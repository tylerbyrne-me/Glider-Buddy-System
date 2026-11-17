"""Fill the official CCG NAVWARN request .docx template.

Only the desk title, return email, value cells, and checkbox states change.
All other Coast Guard wording stays as in the template asset.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable, Optional

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from app.platforms.wave_glider.navwarn_form import (
    TEMPLATE_CHECKBOX_LABELS,
    NavwarnDocumentFields,
    desk_email,
    desk_title_line,
    format_position_parts,
    nature_other_for,
    pdf_or_docx_basename,
    selected_checkbox_indices,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"

TEMPLATE_PATH = (
    Path(__file__).resolve().parent / "templates" / "navwarn_request_form.docx"
)

CHECKED_GLYPH = "\u2612"
UNCHECKED_GLYPH = "\u2610"


class NavwarnDocxError(Exception):
    """Raised when the template cannot be filled safely."""


def template_path() -> Path:
    return TEMPLATE_PATH


def docx_filename(fields: NavwarnDocumentFields) -> str:
    return f"{pdf_or_docx_basename(fields)}.docx"


def _checkbox_sdts(document: Document) -> list:
    body = document.element.body
    return [
        sdt
        for sdt in body.findall(f".//{{{W_NS}}}sdt")
        if sdt.find(f".//{{{W14_NS}}}checkbox") is not None
    ]


def checkbox_label(sdt) -> str:
    parent = sdt.getparent()
    after = False
    parts: list[str] = []
    for child in list(parent):
        if child is sdt:
            after = True
            continue
        if not after:
            continue
        if (
            child.tag == qn("w:sdt")
            and child.find(f".//{{{W14_NS}}}checkbox") is not None
        ):
            break
        parts.extend(t.text or "" for t in child.findall(f".//{{{W_NS}}}t"))
    return "".join(parts).strip()


def list_template_checkbox_labels(
    path: Optional[Path] = None,
) -> tuple[str, ...]:
    document = Document(str(path or TEMPLATE_PATH))
    return tuple(checkbox_label(sdt) for sdt in _checkbox_sdts(document))


def set_checkbox(sdt, checked: bool) -> None:
    checkbox = sdt.find(f".//{{{W14_NS}}}checkbox")
    if checkbox is None:
        return
    checked_el = checkbox.find(f"{{{W14_NS}}}checked")
    if checked:
        if checked_el is None:
            checked_el = etree.SubElement(checkbox, f"{{{W14_NS}}}checked")
        checked_el.set(qn("w14:val"), "1")
    elif checked_el is not None:
        checkbox.remove(checked_el)
    glyph = CHECKED_GLYPH if checked else UNCHECKED_GLYPH
    for text_el in sdt.findall(f".//{{{W_NS}}}t"):
        text_el.text = glyph


def _clear_paragraph_runs(paragraph) -> None:
    for run in paragraph.runs:
        run.text = ""


def set_cell_text(cell, text: str) -> None:
    paragraphs = cell.paragraphs
    if not paragraphs:
        cell.add_paragraph(text)
        return
    first = paragraphs[0]
    if first.runs:
        first.runs[0].text = text
        for run in first.runs[1:]:
            run.text = ""
    else:
        first.add_run(text)
    for paragraph in paragraphs[1:]:
        _clear_paragraph_runs(paragraph)


def _unique_cell(table, row_idx: int, col_idx: int):
    return table.rows[row_idx].cells[col_idx]


def _replace_desk_title(document: Document, desk: str) -> None:
    target = desk_title_line(desk)
    paragraph = document.paragraphs[0]
    if not paragraph.runs:
        paragraph.add_run(target)
        return
    # Keep run formatting from the first run; collapse the rest.
    paragraph.runs[0].text = target
    for run in paragraph.runs[1:]:
        run.text = ""


def _replace_return_email(document: Document, desk: str) -> None:
    email = desk_email(desk)
    cell = _unique_cell(document.tables[0], 0, 0)
    set_cell_text(
        cell,
        f"Return this completed form to the following email address:\n{email}",
    )


def _append_text_after_label(cell, label: str, text: str) -> None:
    """Write free-text into the first empty paragraph after a checkbox label."""
    cleaned = (text or "").strip()
    found_label = False
    for paragraph in cell.paragraphs:
        if label in paragraph.text:
            found_label = True
            continue
        if not found_label:
            continue
        if paragraph._p.findall(f".//{{{W14_NS}}}checkbox"):
            continue
        # Prefer an empty-ish paragraph after the label.
        if paragraph.text.strip() and cleaned not in paragraph.text:
            continue
        if paragraph.runs:
            paragraph.runs[0].text = cleaned
            for run in paragraph.runs[1:]:
                run.text = ""
        else:
            paragraph.add_run(cleaned)
        return
    if found_label and cleaned:
        cell.add_paragraph(cleaned)


def _apply_checkboxes(document: Document, fields: NavwarnDocumentFields) -> None:
    sdts = _checkbox_sdts(document)
    labels = tuple(checkbox_label(sdt) for sdt in sdts)
    if labels != TEMPLATE_CHECKBOX_LABELS:
        raise NavwarnDocxError(
            "NAVWARN template checkbox labels do not match the expected list. "
            "Replace templates/navwarn_request_form.docx with a matching CCG form."
        )
    selected = selected_checkbox_indices(fields)
    for index, sdt in enumerate(sdts):
        set_checkbox(sdt, index in selected)


def _apply_position(document: Document, fields: NavwarnDocumentFields) -> None:
    parts = format_position_parts(
        fields.latitude, fields.longitude, fields.position_format
    )
    table = document.tables[1]
    # Clear all three format rows first.
    for row_idx in (5, 6, 7):
        for col in (1, 2, 4):
            set_cell_text(_unique_cell(table, row_idx, col), "")
        set_cell_text(_unique_cell(table, row_idx, 3), "N")
        set_cell_text(_unique_cell(table, row_idx, 5), "W")

    row_by_format = {"dm": 5, "dms": 6, "dmm": 7}
    row_idx = row_by_format.get(fields.position_format, 7)
    lat = parts["lat_text"]
    lon = parts["lon_text"]
    # Sample form duplicated lat into two merged-looking cells; write both.
    set_cell_text(_unique_cell(table, row_idx, 1), lat)
    set_cell_text(_unique_cell(table, row_idx, 2), lat)
    set_cell_text(_unique_cell(table, row_idx, 3), parts["lat_hemisphere"])
    set_cell_text(_unique_cell(table, row_idx, 4), lon)
    set_cell_text(_unique_cell(table, row_idx, 5), parts["lon_hemisphere"])


def _apply_values(document: Document, fields: NavwarnDocumentFields) -> None:
    t0, t1, t2 = document.tables

    set_cell_text(_unique_cell(t0, 3, 0), fields.requester_name)
    set_cell_text(_unique_cell(t0, 3, 2), fields.telephone)
    set_cell_text(_unique_cell(t0, 5, 0), fields.email)

    if fields.publish_contact == "yes_custom":
        _append_text_after_label(
            _unique_cell(t0, 7, 0),
            "Yes, the following contact information:",
            fields.publish_contact_custom,
        )

    set_cell_text(
        _unique_cell(t0, 10, 1),
        fields.previous_navwarn_number if fields.is_update_or_cancel == "yes" else "",
    )
    set_cell_text(_unique_cell(t0, 12, 0), fields.start_datetime)

    if fields.days_of_operation == "other":
        _append_text_after_label(
            _unique_cell(t1, 1, 0),
            "Other (please specify)",
            fields.days_other,
        )
    if fields.hours_of_operation == "other":
        _append_text_after_label(
            _unique_cell(t1, 1, 2),
            "Other (please specify)",
            fields.hours_other,
        )

    set_cell_text(_unique_cell(t1, 3, 0), fields.completion_datetime)
    _apply_position(document, fields)
    set_cell_text(_unique_cell(t1, 9, 0), fields.place_name)
    set_cell_text(_unique_cell(t1, 11, 0), fields.extra_positions)

    other_text = nature_other_for(fields)
    if other_text:
        category = fields.nature_category
        if category == "marine_works":
            _append_text_after_label(
                _unique_cell(t2, 3, 0),
                "Marine works (other). Please briefly describe:",
                other_text,
            )
        elif category == "obstruction":
            _append_text_after_label(
                _unique_cell(t2, 3, 1),
                "Obstruction (other). Please briefly describe:",
                other_text,
            )
        elif category == "offshore":
            _append_text_after_label(
                _unique_cell(t2, 3, 2),
                "Offshore works (other). Please briefly describe:",
                other_text,
            )
        elif category == "recreational":
            _append_text_after_label(
                _unique_cell(t2, 5, 2),
                "Recreational event (other). Please briefly describe:",
                other_text,
            )

    set_cell_text(_unique_cell(t2, 7, 0), fields.vessels_on_scene)
    set_cell_text(_unique_cell(t2, 9, 0), fields.markers_description)
    set_cell_text(_unique_cell(t2, 13, 0), fields.other_details)


def render_navwarn_docx(fields: NavwarnDocumentFields) -> bytes:
    if not TEMPLATE_PATH.is_file():
        raise NavwarnDocxError(f"Missing NAVWARN template at {TEMPLATE_PATH}")
    document = Document(str(TEMPLATE_PATH))
    if fields.desk not in ("sydney", "port_aux_basques"):
        raise NavwarnDocxError(f"Unsupported NAVWARN desk {fields.desk!r}.")
    _replace_desk_title(document, fields.desk)
    _replace_return_email(document, fields.desk)
    _apply_checkboxes(document, fields)
    _apply_values(document, fields)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def iter_static_paragraph_texts(document: Document) -> Iterable[str]:
    for paragraph in document.paragraphs:
        yield paragraph.text
