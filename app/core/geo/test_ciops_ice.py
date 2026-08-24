"""Unit tests for CIOPS-East ice WMS helpers (no live GeoMet)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.geo import ciops_ice


def test_expand_time_dimension_pt1h() -> None:
    times = ciops_ice.expand_time_dimension(
        "2026-08-24T06:00:00Z/2026-08-24T08:00:00Z/PT1H"
    )
    assert times == [
        "2026-08-24T06:00:00Z",
        "2026-08-24T07:00:00Z",
        "2026-08-24T08:00:00Z",
    ]


def test_expand_time_dimension_comma_list() -> None:
    times = ciops_ice.expand_time_dimension(
        "2026-08-24T06:00:00Z,2026-08-24T07:00:00Z"
    )
    assert times == ["2026-08-24T06:00:00Z", "2026-08-24T07:00:00Z"]


def test_expand_time_dimension_rejects_unknown_step() -> None:
    with pytest.raises(ValueError, match="unsupported time step"):
        ciops_ice.expand_time_dimension(
            "2026-08-24T06:00:00Z/2026-08-24T08:00:00Z/PT3H"
        )


def test_pick_default_time_last_at_or_before_now() -> None:
    times = [
        "2026-08-24T06:00:00Z",
        "2026-08-24T07:00:00Z",
        "2026-08-24T08:00:00Z",
    ]
    now = datetime(2026, 8, 24, 7, 30, tzinfo=timezone.utc)
    assert ciops_ice.pick_default_time(times, now=now) == "2026-08-24T07:00:00Z"


def test_pick_default_time_before_window_uses_first() -> None:
    times = ["2026-08-24T06:00:00Z", "2026-08-24T07:00:00Z"]
    now = datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc)
    assert ciops_ice.pick_default_time(times, now=now) == "2026-08-24T06:00:00Z"


def test_wms13_bbox_4326_axis_order() -> None:
    # west,south,east,north → south,west,north,east
    assert (
        ciops_ice.wms13_bbox_4326(-70.0, 40.0, -60.0, 50.0)
        == "40.0,-70.0,50.0,-60.0"
    )


def test_build_getmap_url_uses_wms13_axis_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ciops_ice, "get_geomet_url", lambda: "https://geo.weather.gc.ca/geomet")
    monkeypatch.setattr(ciops_ice, "get_layer_name", lambda: "CIOPS-East_2km_SeaIceAreaFraction")
    url = ciops_ice.build_getmap_url(
        west=-70.0,
        south=40.0,
        east=-60.0,
        north=50.0,
        width=256,
        height=256,
        time_iso="2026-08-24T14:00:00Z",
        style="SEA_ICECONC-CIS",
    )
    assert "BBOX=40.0%2C-70.0%2C50.0%2C-60.0" in url or "BBOX=40.0,-70.0,50.0,-60.0" in url
    assert "CRS=EPSG%3A4326" in url or "CRS=EPSG:4326" in url
    assert "TIME=2026-08-24T14%3A00%3A00Z" in url or "TIME=2026-08-24T14:00:00Z" in url
    assert "STYLES=SEA_ICECONC-CIS" in url


def test_assert_allowed_style() -> None:
    assert ciops_ice.assert_allowed_style("SEA_ICECONC-CIS") == "SEA_ICECONC-CIS"
    with pytest.raises(ValueError, match="allowlisted"):
        ciops_ice.assert_allowed_style("NOT_A_STYLE")


def test_parse_capabilities_xml_minimal() -> None:
    xml = """<?xml version="1.0"?>
    <WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0">
      <Capability>
        <Layer>
          <Layer>
            <Name>CIOPS-East_2km_SeaIceAreaFraction</Name>
            <EX_GeographicBoundingBox>
              <westBoundLongitude>-77.015</westBoundLongitude>
              <eastBoundLongitude>-37.025</eastBoundLongitude>
              <southBoundLatitude>34.87</southBoundLatitude>
              <northBoundLatitude>54.47</northBoundLatitude>
            </EX_GeographicBoundingBox>
            <Dimension name="time" units="ISO8601" default="2026-08-24T07:00:00Z">
              2026-08-24T06:00:00Z/2026-08-24T08:00:00Z/PT1H
            </Dimension>
            <Dimension name="reference_time" units="ISO8601" default="2026-08-24T06:00:00Z">
              2026-08-24T06:00:00Z
            </Dimension>
          </Layer>
        </Layer>
      </Capability>
    </WMS_Capabilities>
    """
    parsed = ciops_ice.parse_capabilities_xml(xml)
    assert parsed["times"] == [
        "2026-08-24T06:00:00Z",
        "2026-08-24T07:00:00Z",
        "2026-08-24T08:00:00Z",
    ]
    assert parsed["reference_time"] == "2026-08-24T06:00:00Z"
    assert parsed["domain"]["west"] == pytest.approx(-77.015)
    assert parsed["domain"]["north"] == pytest.approx(54.47)
