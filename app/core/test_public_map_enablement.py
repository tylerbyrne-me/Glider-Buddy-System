"""Unit tests for public login map catalog enablement."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from app.core import public_map_service as pms


class _FakeSession:
    def __init__(
        self,
        *,
        overviews: Optional[dict[str, Any]] = None,
        deployments: Optional[list[Any]] = None,
    ) -> None:
        self._overviews = overviews or {}
        self._deployments = deployments or []

    def get(self, _model: Any, key: str) -> Any:
        return self._overviews.get(key)

    def exec(self, _statement: Any) -> Any:
        result = MagicMock()
        result.first.return_value = self._deployments[0] if self._deployments else None
        return result


def test_active_keys_flag_off_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pms.settings, "mission_catalog_public_map_from_catalog", False)
    monkeypatch.setattr(pms.settings, "active_realtime_missions", ["m229-SV3-1071"])
    monkeypatch.setattr(pms.settings, "active_slocum_datasets", ["fundy"])
    monkeypatch.setattr(
        pms,
        "configured_slocum_dataset_keys",
        lambda _keys: ["fundy"],
    )
    session = _FakeSession()
    assert pms.active_keys_for_public_map("wave_glider", session) == ["m229-SV3-1071"]
    assert pms.active_keys_for_public_map("slocum", session) == ["fundy"]


def test_active_keys_flag_on_uses_catalog_enablement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pms.settings, "mission_catalog_public_map_from_catalog", True)
    monkeypatch.setattr(pms.settings, "active_realtime_missions", ["m229-SV3-1071"])

    calls: list[str] = []

    def fake_targets(platform: str, _session: Any) -> list[str]:
        calls.append(platform)
        return ["m229-SV3-1071"]

    monkeypatch.setattr(
        "app.core.mission_catalog.enablement.list_catalog_sync_targets",
        fake_targets,
    )
    monkeypatch.setattr(
        "app.core.mission_catalog.enablement.log_enablement_parity",
        lambda _session: None,
    )
    assert pms.active_keys_for_public_map("wave_glider", _FakeSession()) == [
        "m229-SV3-1071"
    ]
    assert calls == ["wave_glider"]


def test_active_keys_falls_back_to_env_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pms.settings, "mission_catalog_public_map_from_catalog", True)
    monkeypatch.setattr(pms.settings, "active_realtime_missions", ["m229-SV3-1071"])

    def boom(_platform: str, _session: Any) -> list[str]:
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(
        "app.core.mission_catalog.enablement.list_catalog_sync_targets",
        boom,
    )
    monkeypatch.setattr(
        "app.core.mission_catalog.enablement.log_enablement_parity",
        lambda _session: None,
    )
    assert pms.active_keys_for_public_map("wave_glider", _FakeSession()) == [
        "m229-SV3-1071"
    ]


def test_allowlist_requires_public_map_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pms.settings, "mission_catalog_public_map_from_catalog", False)
    monkeypatch.setattr(pms.settings, "active_realtime_missions", ["m229-SV3-1071"])
    monkeypatch.setattr(pms, "is_feature_enabled", lambda _name: False)
    monkeypatch.setattr(
        pms,
        "resolve_public_mission_labels",
        lambda *_args, **_kwargs: ("SV3-1071", "Fundy"),
    )

    disabled = SimpleNamespace(
        mission_id="m229-SV3-1071",
        public_map_enabled=False,
        public_weekly_report_enabled=False,
    )
    enabled = SimpleNamespace(
        mission_id="m229-SV3-1071",
        public_map_enabled=True,
        public_weekly_report_enabled=False,
    )

    assert pms.get_public_mission_allowlist(_FakeSession(overviews={"m229-SV3-1071": disabled})) == []
    refs = pms.get_public_mission_allowlist(
        _FakeSession(overviews={"m229-SV3-1071": enabled})
    )
    assert len(refs) == 1
    assert refs[0].mission_id == "m229-SV3-1071"
    assert refs[0].platform == "wave_glider"
