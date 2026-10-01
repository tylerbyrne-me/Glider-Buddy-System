"""ORA PDF content."""

import io

import PyPDF2

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


def test_pdf_filename() -> None:
    assert pdf_filename("Spring Bloom 2026", "SV3-1071") == "ORA Request - Spring Bloom 2026.pdf"
    assert "/" not in pdf_filename("a/b", None)
