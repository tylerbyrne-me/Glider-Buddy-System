"""Wave Glider ORA device library matching."""

from app.platforms.wave_glider.ora_devices import (
    default_device_rows,
    infer_vehicle_model,
    instrument_label,
    merge_tracker_instruments,
)


def test_tracker_names_reuse_library_watts_without_duplicating_the_bus() -> None:
    merged = merge_tracker_instruments(
        default_device_rows(),
        ["Airmar 200WX Weather Station", "RDI Workhorse ADCP", "VM4-009"],
    )
    names = [row["name"] for row in merged]
    assert names.count("Weather Station 200X") == 1
    weather = next(row for row in merged if row["name"] == "Weather Station 200X")
    assert weather["source"] == "tracker"
    assert weather["power_draw"] == "1.8w"
    adcp = next(row for row in merged if row["name"] == "RDI 600 ADCP")
    assert adcp["power_draw"] == "2.5w"
    assert adcp["duty_cycle"] == "5.5%"
    vm4 = next(row for row in merged if row["name"] == "Innovasea VM4")
    assert vm4["power_draw"] == "0.7w"


def test_instrument_label_and_hull_model() -> None:
    assert instrument_label({"instrument": {"identifier": "FLNTU-1"}}) == "FLNTU-1"
    assert infer_vehicle_model("SV3-1071") == "sv3"
    assert infer_vehicle_model("SV2-044") == "sv2"
    assert infer_vehicle_model("peggy") is None
