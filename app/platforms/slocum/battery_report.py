"""Battery endurance helpers for Slocum weekly PDF reports.

Pure transforms on dashboard coulomb / voltage frames and checklist pack refs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

import pandas as pd

from app.platforms.slocum.checklist_autofill import (
    BATTERY_PACK_PRESETS,
    compute_amphr_usage_rate,
    parse_checklist_reference_values,
)

USAGE_THRESHOLD_FRACTIONS: tuple[float, ...] = (0.5, 0.75, 0.9, 1.0)
# Day-to-day spans shorter than this are treated as incomplete (normalize to Ah/day).
COMPLETE_DAY_MIN_HOURS = 18.0


def resolve_endurance_amphr(
    checklist_reference_values: Optional[str] = None,
    *,
    refs: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    """Return pack / manual endurance Ah after preset expansion."""
    resolved = refs if refs is not None else parse_checklist_reference_values(checklist_reference_values)
    raw = resolved.get("endurance_amphr_total")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def resolve_battery_pack_meta(
    checklist_reference_values: Optional[str] = None,
    *,
    refs: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Pack label + endurance Ah for report banners."""
    resolved = refs if refs is not None else parse_checklist_reference_values(checklist_reference_values)
    pack_id = str(resolved.get("battery_pack") or "").strip()
    label: Optional[str] = None
    if pack_id in BATTERY_PACK_PRESETS:
        label = str(BATTERY_PACK_PRESETS[pack_id].get("label") or pack_id)
    elif pack_id:
        label = pack_id
    return {
        "pack_id": pack_id or None,
        "pack_label": label,
        "endurance_amphr_total": resolve_endurance_amphr(refs=resolved),
    }


def _coulomb_day_end_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Last valid coulomb sample per UTC calendar day.

    Columns: ``date``, ``cumulative_ah``, ``end_ts``.
    """
    empty = pd.DataFrame(columns=["date", "cumulative_ah", "end_ts"])
    if df is None or df.empty:
        return empty
    if "Timestamp" not in df.columns or "MCoulombAmphrTotal" not in df.columns:
        return empty
    work = df[["Timestamp", "MCoulombAmphrTotal"]].copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], utc=True, errors="coerce")
    work["MCoulombAmphrTotal"] = pd.to_numeric(work["MCoulombAmphrTotal"], errors="coerce")
    work = work.dropna(subset=["Timestamp", "MCoulombAmphrTotal"]).sort_values("Timestamp")
    if work.empty:
        return empty
    work["utc_date"] = work["Timestamp"].dt.floor("D").dt.date
    # Keep the last sample of each day (timestamp + Ah together).
    last_idx = work.groupby("utc_date", sort=True)["Timestamp"].idxmax()
    ends = work.loc[last_idx].sort_values("Timestamp")
    return pd.DataFrame(
        {
            "date": ends["utc_date"].to_numpy(),
            "cumulative_ah": ends["MCoulombAmphrTotal"].to_numpy(dtype=float),
            "end_ts": ends["Timestamp"].to_numpy(),
        }
    ).reset_index(drop=True)


def daily_coulomb_consumption(df: pd.DataFrame) -> pd.DataFrame:
    """Calendar-day Ah consumption from cumulative coulomb totals.

    Returns columns:
    - ``date``, ``cumulative_ah``, ``end_ts``
    - ``ah_observed`` — raw positive day-to-day ΔAh (NaN on reset / first row)
    - ``hours_elapsed`` — hours between consecutive day-end samples
    - ``is_complete`` — True when ``hours_elapsed >= COMPLETE_DAY_MIN_HOURS``
    - ``ah_day`` — chart value: observed for complete days; rate-normalized
      ``observed * 24 / hours`` for incomplete days
    """
    ends = _coulomb_day_end_frame(df)
    if ends.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "ah_day",
                "ah_observed",
                "hours_elapsed",
                "is_complete",
                "cumulative_ah",
                "end_ts",
            ]
        )

    ah = ends["cumulative_ah"].astype(float)
    ts = pd.to_datetime(ends["end_ts"], utc=True)
    delta = ah.diff()
    hours = (ts - ts.shift(1)).dt.total_seconds() / 3600.0
    ah_observed = delta.where(delta >= 0.0)
    is_complete = hours.notna() & (hours >= COMPLETE_DAY_MIN_HOURS) & ah_observed.notna()

    ah_day = ah_observed.copy()
    incomplete = ah_observed.notna() & hours.notna() & (hours > 0) & ~is_complete
    ah_day.loc[incomplete] = ah_observed.loc[incomplete] * (24.0 / hours.loc[incomplete])

    return pd.DataFrame(
        {
            "date": ends["date"],
            "ah_day": ah_day.to_numpy(dtype=float),
            "ah_observed": ah_observed.to_numpy(dtype=float),
            "hours_elapsed": hours.to_numpy(dtype=float),
            "is_complete": is_complete.to_numpy(dtype=bool),
            "cumulative_ah": ends["cumulative_ah"].to_numpy(dtype=float),
            "end_ts": ends["end_ts"],
        }
    )


def mean_daily_ah_rate(daily_df: pd.DataFrame) -> Optional[float]:
    """Mean Ah/day for projections: complete days only, else normalized incomplete."""
    if daily_df is None or daily_df.empty or "ah_day" not in daily_df.columns:
        return None
    work = daily_df.copy()
    work["ah_day"] = pd.to_numeric(work["ah_day"], errors="coerce")
    if "is_complete" in work.columns:
        complete = work["is_complete"].fillna(False).astype(bool)
        complete_vals = work.loc[complete, "ah_day"].dropna()
        complete_vals = complete_vals[complete_vals >= 0]
        if not complete_vals.empty:
            return float(complete_vals.mean())
        # No full days — use rate-normalized incomplete bars.
        incomplete_vals = work.loc[~complete, "ah_day"].dropna()
        incomplete_vals = incomplete_vals[incomplete_vals >= 0]
        if not incomplete_vals.empty:
            return float(incomplete_vals.mean())
        return None
    values = work["ah_day"].dropna()
    values = values[values >= 0]
    if values.empty:
        return None
    return float(values.mean())


def fallback_24h_ah_rate(df: pd.DataFrame) -> Optional[float]:
    """Checklist-style ~24h coulomb rate from a dashboard frame."""
    if df is None or df.empty:
        return None
    if "Timestamp" not in df.columns or "MCoulombAmphrTotal" not in df.columns:
        return None
    work = df[["Timestamp", "MCoulombAmphrTotal"]].copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], utc=True, errors="coerce")
    work["MCoulombAmphrTotal"] = pd.to_numeric(work["MCoulombAmphrTotal"], errors="coerce")
    work = work.dropna(subset=["Timestamp", "MCoulombAmphrTotal"]).sort_values("Timestamp")
    if work.empty:
        return None
    latest_ts = work["Timestamp"].iloc[-1]
    latest_ah = float(work["MCoulombAmphrTotal"].iloc[-1])
    target = latest_ts - timedelta(hours=24)
    prior = work[work["Timestamp"] <= target]
    if prior.empty:
        # Allow nearest within 12–36h window (same spirit as dashboard derive).
        lag_h = (latest_ts - work["Timestamp"]).dt.total_seconds() / 3600.0
        window = work[(lag_h >= 12.0) & (lag_h <= 36.0)]
        if window.empty:
            return None
        prior_row = window.iloc[-1]
    else:
        prior_row = prior.iloc[-1]
    hours = (latest_ts - prior_row["Timestamp"]).total_seconds() / 3600.0
    return compute_amphr_usage_rate(latest_ah, float(prior_row["MCoulombAmphrTotal"]), hours)


def latest_coulomb_ah(df: pd.DataFrame) -> Optional[float]:
    if df is None or df.empty or "MCoulombAmphrTotal" not in df.columns:
        return None
    series = pd.to_numeric(df["MCoulombAmphrTotal"], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.iloc[-1])


def latest_battery_voltage(df: pd.DataFrame) -> Optional[float]:
    if df is None or df.empty or "MBattery" not in df.columns:
        return None
    series = pd.to_numeric(df["MBattery"], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.iloc[-1])


def project_usage_thresholds(
    latest_ah: Optional[float],
    endurance_ah: Optional[float],
    ah_per_day: Optional[float],
    *,
    as_of: Optional[datetime] = None,
    fractions: Sequence[float] = USAGE_THRESHOLD_FRACTIONS,
) -> list[dict[str, Any]]:
    """Project or mark calendar dates for pack-usage thresholds.

    Each row: ``fraction``, ``label``, ``target_ah``, ``status``
    (``reached`` | ``projected`` | ``unavailable``), ``date`` (ISO date or None),
    ``detail`` (human string).
    """
    base = as_of or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)

    rows: list[dict[str, Any]] = []
    for frac in fractions:
        pct = int(round(float(frac) * 100))
        label = f"{pct}% used"
        if endurance_ah is None or endurance_ah <= 0:
            rows.append(
                {
                    "fraction": float(frac),
                    "label": label,
                    "target_ah": None,
                    "status": "unavailable",
                    "date": None,
                    "detail": "Set battery pack on deployment",
                }
            )
            continue
        target_ah = float(endurance_ah) * float(frac)
        if latest_ah is not None and latest_ah >= target_ah:
            rows.append(
                {
                    "fraction": float(frac),
                    "label": label,
                    "target_ah": target_ah,
                    "status": "reached",
                    "date": base.date().isoformat(),
                    "detail": f"reached (≤ {base.date().isoformat()})",
                }
            )
            continue
        if latest_ah is None or ah_per_day is None or ah_per_day <= 0:
            rows.append(
                {
                    "fraction": float(frac),
                    "label": label,
                    "target_ah": target_ah,
                    "status": "unavailable",
                    "date": None,
                    "detail": "N/A",
                }
            )
            continue
        days = (target_ah - float(latest_ah)) / float(ah_per_day)
        projected = (base + timedelta(days=float(days))).date()
        rows.append(
            {
                "fraction": float(frac),
                "label": label,
                "target_ah": target_ah,
                "status": "projected",
                "date": projected.isoformat(),
                "detail": f"projected {projected.isoformat()}",
            }
        )
    return rows


def build_battery_report_context(
    *,
    period_dashboard: pd.DataFrame,
    mission_dashboard: pd.DataFrame,
    checklist_reference_values: Optional[str],
    as_of: Optional[datetime] = None,
) -> dict[str, Any]:
    """Assemble daily series, rate, KPIs, and threshold projections for the PDF page."""
    pack = resolve_battery_pack_meta(checklist_reference_values)
    daily = daily_coulomb_consumption(period_dashboard)
    rate = mean_daily_ah_rate(daily)
    rate_source = "complete-day daily mean"
    if rate is None:
        rate = fallback_24h_ah_rate(period_dashboard)
        if rate is None:
            rate = fallback_24h_ah_rate(mission_dashboard)
        rate_source = "~24h coulomb delta" if rate is not None else "unavailable"
    elif "is_complete" in daily.columns and not daily["is_complete"].fillna(False).any():
        rate_source = "partial-day rate-normalized mean"

    mission = mission_dashboard if mission_dashboard is not None and not mission_dashboard.empty else period_dashboard
    latest_ah = latest_coulomb_ah(mission)
    latest_v = latest_battery_voltage(mission)
    endurance = pack.get("endurance_amphr_total")
    pct_used = None
    if latest_ah is not None and endurance is not None and endurance > 0:
        pct_used = 100.0 * float(latest_ah) / float(endurance)

    as_of_dt = as_of
    if as_of_dt is None and mission is not None and not mission.empty and "Timestamp" in mission.columns:
        ts = pd.to_datetime(mission["Timestamp"], utc=True, errors="coerce").dropna()
        if not ts.empty:
            as_of_dt = ts.iloc[-1].to_pydatetime()
            if as_of_dt.tzinfo is None:
                as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)

    projections = project_usage_thresholds(
        latest_ah,
        endurance,
        rate,
        as_of=as_of_dt,
    )
    return {
        "pack_label": pack.get("pack_label"),
        "endurance_amphr_total": endurance,
        "latest_voltage": latest_v,
        "latest_ah": latest_ah,
        "pct_used": pct_used,
        "ah_per_day": rate,
        "ah_per_day_source": rate_source,
        "daily": daily,
        "projections": projections,
        "as_of": as_of_dt,
    }
