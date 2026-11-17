"""NAVWARN ReportLab PDF content."""

from __future__ import annotations

import io

import PyPDF2

from app.platforms.wave_glider.navwarn_form import NavwarnDocumentFields
from app.platforms.wave_glider.navwarn_pdf import pdf_filename, render_navwarn_pdf


def _fields() -> NavwarnDocumentFields:
    return NavwarnDocumentFields(
        desk="sydney",
        hull_name="C34166NS",
        requester_name="Tyler Byrne, Dalhousie University, C34166NS",
        telephone="902-719-7078",
        email="tylerbyrne@dal.ca",
        publish_contact="no",
        is_update_or_cancel="no",
        start_datetime="15:00 UTC 2026-04-21",
        timezone="utc",
        days_of_operation="daily",
        hours_of_operation="24h",
        completion_datetime="15:00 UTC 2026-04-23",
        completion_firmness="estimated",
        position_format="dmm",
        latitude=44.512,
        longitude=-63.409,
        place_name="Halifax Approaches",
        nature_category="obstruction",
        nature_topic="other",
        nature_other="Acoustic/Oceanographic Survey",
        vessels_on_scene="Wave Glider C34166NS, equipped with a non-transmitting AIS receiver.",
        markers_description="Wave glider C34166NS is copper in colour.",
        wash_berth="none",
        other_details="The Wave Glider is remotely operated.",
    )


def _text(payload: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_includes_form_wording_and_values() -> None:
    payload = render_navwarn_pdf(_fields())
    assert payload.startswith(b"%PDF")
    text = _text(payload)
    assert "Sydney Navigation Warning Issuing Desk" in text
    assert "Canadian Coast Guard Atlantic Region" in text
    assert "NAVWARN Request Form" in text
    assert "NAVWARN.MCTSSydney@innav.gc.ca" in text
    assert "Tyler Byrne, Dalhousie University, C34166NS" in text
    assert "Halifax Approaches" in text
    assert "44.512" in text
    assert "Acoustic/Oceanographic Survey" in text
    assert "Wave Glider C34166NS" in text
    assert "Form continues on the next page." in text
    assert "liquid-robotics.com/wave-glider/overview" in text


def test_pdf_filename() -> None:
    from datetime import date

    from app.platforms.wave_glider.navwarn_form import pdf_or_docx_basename

    assert (
        pdf_or_docx_basename(_fields(), created=date(2026, 11, 16))
        == "NAVWARN_Request_C34166NS_2026-11-16"
    )
    name = pdf_filename(_fields())
    assert name.startswith("NAVWARN_Request_C34166NS_")
    assert name.endswith(".pdf")
