"""NAVWARN .docx template fill."""

from __future__ import annotations

import io

from docx import Document
from docx.oxml.ns import qn

from app.platforms.wave_glider.navwarn_docx import (
    checkbox_label,
    docx_filename,
    list_template_checkbox_labels,
    render_navwarn_docx,
    template_path,
)
from app.platforms.wave_glider.navwarn_form import (
    TEMPLATE_CHECKBOX_LABELS,
    NavwarnDocumentFields,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"


def _fields(**overrides) -> NavwarnDocumentFields:
    base = NavwarnDocumentFields(
        desk="port_aux_basques",
        hull_name="C34167NS",
        requester_name="Tyler Byrne, Dalhousie University, C34167NS",
        telephone="902-719-7078",
        email="tylerbyrne@dal.ca",
        publish_contact="no",
        is_update_or_cancel="yes",
        previous_navwarn_number="NW-N-0623-26",
        start_datetime="15:00 UTC 2026-08-15",
        timezone="utc",
        days_of_operation="daily",
        hours_of_operation="24h",
        completion_datetime="15:00 UTC 2026-08-17",
        completion_firmness="estimated",
        position_format="dmm",
        latitude=44.512,
        longitude=-63.409,
        place_name="Northern Grand Banks",
        extra_positions="5km diameter operation area around the center lat/lon point",
        nature_category="obstruction",
        nature_topic="other",
        nature_other="Acoustic/Oceanographic Survey",
        vessels_on_scene="Wave Glider C34167NS, equipped with a non-transmitting AIS receiver.",
        markers_description="Wave glider C34167NS is copper in colour.",
        wash_berth="none",
        other_details="The Wave Glider is remotely operated.",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _checked_labels(document: Document) -> list[str]:
    labels: list[str] = []
    for sdt in document.element.body.findall(".//{%s}sdt" % W_NS):
        checkbox = sdt.find(".//{%s}checkbox" % W14_NS)
        if checkbox is None:
            continue
        checked_el = checkbox.find("{%s}checked" % W14_NS)
        is_checked = False
        if checked_el is not None:
            value = checked_el.get(qn("w14:val"))
            is_checked = value in (None, "1", "true", "True")
        glyphs = [t.text or "" for t in sdt.findall(".//{%s}t" % W_NS)]
        if "\u2612" in glyphs:
            is_checked = True
        if is_checked:
            labels.append(checkbox_label(sdt))
    return labels


def test_template_checkbox_labels_match_expected() -> None:
    assert list_template_checkbox_labels() == TEMPLATE_CHECKBOX_LABELS
    assert len(TEMPLATE_CHECKBOX_LABELS) == 53


def test_docx_swaps_desk_email_and_fills_values() -> None:
    payload = render_navwarn_docx(_fields())
    document = Document(io.BytesIO(payload))
    assert document.paragraphs[0].text == (
        "Port aux Basques Navigation Warning Issuing Desk"
    )
    assert "Canadian Coast Guard Atlantic Region" in document.paragraphs[1].text
    email_cell = document.tables[0].rows[0].cells[0].text
    assert "navwarn.mctsportauxbasques@innav.gc.ca" in email_cell
    assert "NAVWARN.MCTSSydney@innav.gc.ca" not in email_cell

    assert (
        "Tyler Byrne, Dalhousie University, C34167NS"
        in document.tables[0].rows[3].cells[0].text
    )
    assert "902-719-7078" in document.tables[0].rows[3].cells[2].text
    assert "tylerbyrne@dal.ca" in document.tables[0].rows[5].cells[0].text
    assert "NW-N-0623-26" in document.tables[0].rows[10].cells[1].text
    assert "15:00 UTC 2026-08-15" in document.tables[0].rows[12].cells[0].text
    assert "Northern Grand Banks" in document.tables[1].rows[9].cells[0].text
    assert "44.512" in document.tables[1].rows[7].cells[1].text
    assert "-63.409" in document.tables[1].rows[7].cells[4].text
    assert "Acoustic/Oceanographic Survey" in document.tables[2].rows[3].cells[1].text
    assert "Wave Glider C34167NS" in document.tables[2].rows[7].cells[0].text


def test_docx_checks_expected_boxes() -> None:
    labels = _checked_labels(Document(io.BytesIO(render_navwarn_docx(_fields()))))
    assert labels.count("No") == 1  # publish contact
    assert labels.count("Yes") == 1  # update/cancel
    assert "UTC (Coordinated Universal Time)" in labels
    assert "Daily" in labels
    assert "24 hours" in labels
    assert "Estimated" in labels
    assert "Obstruction (other). Please briefly describe:" in labels
    assert "None" in labels
    assert "Breakwater construction" not in labels
    assert "Local Time" not in labels


def test_docx_filename() -> None:
    from datetime import date

    from app.platforms.wave_glider.navwarn_form import pdf_or_docx_basename

    assert (
        pdf_or_docx_basename(_fields(), created=date(2026, 11, 16))
        == "NAVWARN_Request_C34167NS_2026-11-16"
    )
    name = docx_filename(_fields())
    assert name.startswith("NAVWARN_Request_C34167NS_")
    assert name.endswith(".docx")


def test_template_asset_exists() -> None:
    assert template_path().is_file()
