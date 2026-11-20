"""Per-log offload mission ID helpers (sheet parser_session_ref attribution)."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.offload_comments import (
    STATION_OFFLOAD_SHEET_MARKER,
    apply_mission_id_to_offload_log,
    enrich_offload_log_read,
    mission_id_from_offload_log,
)


def test_mission_id_from_sheet_ref():
    log = SimpleNamespace(
        parser_session_ref=f"m230-SV3-1070{STATION_OFFLOAD_SHEET_MARKER}HFX273",
        parser_run_id=None,
    )
    assert mission_id_from_offload_log(log) == "m230-SV3-1070"


def test_mission_id_from_parser_run_id_fallback():
    log = SimpleNamespace(
        parser_session_ref=None,
        parser_run_id="m219:vm4:abc",
    )
    assert mission_id_from_offload_log(log) == "m219"


def test_apply_mission_id_sets_independent_sheet_refs():
    older = SimpleNamespace(parser_session_ref=None)
    newer = SimpleNamespace(parser_session_ref=None)
    apply_mission_id_to_offload_log(older, "m230-SV3-1070", station_id="HFX273")
    apply_mission_id_to_offload_log(newer, "m227-SV3-1071", station_id="HFX273")
    assert mission_id_from_offload_log(older) == "m230-SV3-1070"
    assert mission_id_from_offload_log(newer) == "m227-SV3-1071"
    assert older.parser_session_ref != newer.parser_session_ref


def test_apply_mission_id_does_not_clobber_non_sheet_ref():
    log = SimpleNamespace(parser_session_ref="m210:parser_session:xyz")
    apply_mission_id_to_offload_log(log, "m230-SV3-1070", station_id="HFX273")
    assert log.parser_session_ref == "m210:parser_session:xyz"
    assert mission_id_from_offload_log(log) == "m210"


def test_apply_mission_id_clears_sheet_ref_only():
    log = SimpleNamespace(
        parser_session_ref=f"m230-SV3-1070{STATION_OFFLOAD_SHEET_MARKER}HFX273"
    )
    apply_mission_id_to_offload_log(log, "", station_id="HFX273")
    assert log.parser_session_ref is None
    assert mission_id_from_offload_log(log) is None


def test_enrich_includes_mission_id():
    log = SimpleNamespace(
        id=1,
        station_id="HFX273",
        parser_session_ref=f"m227-SV3-1071{STATION_OFFLOAD_SHEET_MARKER}HFX273",
        parser_run_id=None,
        user_notes="ok",
        offload_notes_file_size=None,
        model_dump=lambda: {
            "id": 1,
            "station_id": "HFX273",
            "user_notes": "ok",
            "parser_session_ref": f"m227-SV3-1071{STATION_OFFLOAD_SHEET_MARKER}HFX273",
        },
    )
    payload = enrich_offload_log_read(log)
    assert payload["mission_id"] == "m227-SV3-1071"
    assert payload["offload_comments"] == "ok"
