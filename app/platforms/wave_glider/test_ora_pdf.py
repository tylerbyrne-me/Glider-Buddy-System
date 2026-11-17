"""ORA PDF content."""

import io

import PyPDF2
from PIL import Image

from app.platforms.wave_glider import ora_map
from app.platforms.wave_glider.ora_pdf import (
    OraCoordinate,
    OraDeviceLine,
    OraDocumentFields,
    pdf_filename,
    render_ora_pdf,
)


def _fields() -> OraDocumentFields:
    return OraDocumentFields(
        title="Spring Bloom",
        hull_name="SV3-1071",
        requester="Ada Lovelace",
        project_code="800000",
        project_code_other="Bloom",
        client="Dalhousie",
        dates_of_operation="7 Apr 2026 – 6 May 2026",
        purposes=["mission"],
        priority=2,
        coordinates=[
            OraCoordinate("Coordinate 1", 44.571698, -63.470147, "Deployment location"),
        ],
        vehicle_model="sv3",
        umbilical_m="8",
        towing="no",
        sv3_software_version="3.2.2",
        apu_count="2",
        devices=[
            OraDeviceLine("Innovasea VM4", "0.7w", "100%", True),
            OraDeviceLine("Spare", "1w", "10%", False),
        ],
        notes="Hold south of Halifax.",
    )


def _text(payload: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_includes_request_fields_and_skips_unchecked_devices() -> None:
    payload = render_ora_pdf(_fields())
    assert payload.startswith(b"%PDF")
    text = _text(payload)
    assert "Ada Lovelace" in text
    assert "Dalhousie" in text
    assert "800000" in text
    assert "Bloom" in text
    assert "[x] Mission" in text
    assert "High importance" in text
    assert "44.571698" in text
    assert "Deployment location" in text
    assert "SV3" in text
    assert "Innovasea VM4" in text
    assert "Spare" not in text
    assert "Hold south of Halifax." in text
    assert "opscenter@liquid-robotics.com" in text


def _mixed_coordinates() -> list[OraCoordinate]:
    return [
        OraCoordinate("Coordinate 1", 44.40, -63.50, "Deployment location"),
        OraCoordinate("Coordinate 2", 44.30, -63.30, ""),
        OraCoordinate("Coordinate 3", 44.20, -63.20, "Hold station"),
        OraCoordinate("Coordinate 4", 44.10, -63.40, "Box NW"),
        OraCoordinate("Coordinate 5", 44.10, -63.10, "Box NE"),
        OraCoordinate("Coordinate 6", 43.90, -63.10, "Box SE"),
        OraCoordinate("Coordinate 7", 43.90, -63.40, "Box SW"),
    ]


def test_box_groups_find_box_runs_inside_a_mixed_list() -> None:
    groups = ora_map._box_groups(_mixed_coordinates())
    assert groups == [[(44.10, -63.40), (44.10, -63.10), (43.90, -63.10), (43.90, -63.40)]]


def test_area_map_png_renders_mixed_points(monkeypatch) -> None:
    monkeypatch.setattr(ora_map, "_add_report_bathymetry_contours", lambda ax, extent: None)
    png = ora_map.render_ora_area_map_png(_mixed_coordinates())
    assert png and png.startswith(b"\x89PNG")


def test_area_map_png_is_none_without_positions() -> None:
    assert ora_map.render_ora_area_map_png([OraCoordinate("Coordinate 1", None, None, "TBD")]) is None


def test_pdf_places_map_before_coordinates_when_png_given() -> None:
    fields = _fields()
    text = _text(render_ora_pdf(fields, area_map_png=_tiny_png()))
    assert "Purpose" in text
    assert text.index("Purpose") < text.index("Operations area map") < text.index("Coordinates\n")
    assert "Operations area map" not in _text(render_ora_pdf(fields))


def _tiny_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_pdf_filename() -> None:
    assert pdf_filename("Spring Bloom 2026", "SV3-1071") == "ORA Request - Spring Bloom 2026.pdf"
    assert "/" not in pdf_filename("a/b", None)
