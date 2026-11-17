"""Render a Wave Glider ORA request as a ReportLab PDF.

Uses the shared report palette, paragraph styles, and data tables from
``app.core.reporting.styling``. The file is what gets emailed to Liquid Robotics.
An optional operations-area map PNG (``ora_map``) sits just before the coordinates table.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from PIL import Image as PILImage
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.reporting.styling import (
    A4_PORTRAIT,
    COLOR_ACCENT,
    COLOR_BODY,
    COLOR_MUTED,
    COLOR_PRIMARY,
    COLOR_RULE,
    COLOR_ZEBRA,
    HEADER_RULE_FROM_PAGE_TOP,
    HEADER_TEXT_FROM_PAGE_TOP,
    MARGIN_BOTTOM,
    MARGIN_SIDE,
    MARGIN_TOP,
    PORTRAIT_CONTENT_WIDTH_PT,
    build_paragraph_styles,
    styled_data_table,
)

OPS_CENTER_EMAIL = "opscenter@liquid-robotics.com"

PURPOSE_OPTIONS = (
    ("mission", "Mission"),
    ("demo", "Demo"),
    ("training", "Training"),
    ("regional_analysis", "Regional Analysis"),
)
VEHICLE_OPTIONS = (("sv2", "SV2"), ("sv3", "SV3"))
UMBILICAL_OPTIONS = (("4", "4m"), ("8", "8m"), ("20", "20m"))
YES_NO_OPTIONS = (("yes", "Yes"), ("no", "No"))
PRIORITY_LABELS = {
    1: "1 — Company critical",
    2: "2 — High importance",
    3: "3 — Standard mission",
}


@dataclass
class OraCoordinate:
    label: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    comment: str = ""


@dataclass
class OraDeviceLine:
    name: str = ""
    power_draw: str = ""
    duty_cycle: str = ""
    included: bool = True


@dataclass
class OraDocumentFields:
    requester: str = ""
    project_code: str = ""
    project_code_other: str = ""
    client: str = ""
    dates_of_operation: str = ""
    purposes: list[str] = field(default_factory=list)
    priority: Optional[int] = None
    coordinates: list[OraCoordinate] = field(default_factory=list)
    vehicle_model: Optional[str] = None
    umbilical_m: Optional[str] = None
    towing: Optional[str] = None
    towed_device: str = ""
    ecos_up_to_date: Optional[str] = None
    sv3_software_version: str = ""
    apu_count: str = ""
    smc_version: str = ""
    devices: list[OraDeviceLine] = field(default_factory=list)
    notes: str = ""
    title: str = ""
    hull_name: str = ""


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;")


def _marks(selected: Iterable[str], options: tuple[tuple[str, str], ...]) -> str:
    chosen = {str(item).strip().lower() for item in selected if str(item).strip()}
    parts = []
    for key, label in options:
        mark = "[x]" if key in chosen else "[ ]"
        parts.append(f"{mark} {label}")
    return "    ".join(parts)


def _project_code_text(fields: OraDocumentFields) -> str:
    code = (fields.project_code or "").strip()
    other = (fields.project_code_other or "").strip()
    if code and other:
        return f"{code}    Other: {other}"
    if code:
        return code
    if other:
        return f"Other: {other}"
    return "—"


def _choice_label(value: Optional[str], options: Sequence[tuple[str, str]]) -> str:
    if not value:
        return "—"
    for key, label in options:
        if key == value:
            return label
    return value


def _format_coord(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def table_coordinates(fields: OraDocumentFields) -> list[OraCoordinate]:
    """Coordinate rows printed in the PDF; the map numbers points in this order."""
    return [
        point
        for point in fields.coordinates
        if point.lat is not None or point.lon is not None or (point.comment or "").strip()
    ]


# Leaves room for the request header so the map stays on page 1.
AREA_MAP_MAX_HEIGHT_PT = 150 * mm


def _area_map_flowables(png: bytes, styles: dict) -> list:
    heading = Paragraph("Operations area map", styles["Heading2"])
    caption = Paragraph(
        "Numbers match the # column of the Coordinates table below. "
        "Stars are hold stations; shaded areas are boxes.",
        styles["Caption"],
    )
    with PILImage.open(io.BytesIO(png)) as pil:
        px_w, px_h = pil.size
    aspect = px_h / max(px_w, 1)
    width = min(PORTRAIT_CONTENT_WIDTH_PT, AREA_MAP_MAX_HEIGHT_PT / aspect)
    image = Image(io.BytesIO(png), width=width, height=width * aspect)
    return [KeepTogether([heading, caption, Spacer(1, 2 * mm), image])]


def pdf_filename(title: Optional[str], hull_name: Optional[str]) -> str:
    raw = (title or hull_name or "ORA request").strip()
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "", raw).strip()[:80] or "ORA request"
    return f"ORA Request - {safe}.pdf"


def _label_value_table(rows: list[list[str]], styles: dict) -> Table:
    """Two label/value pairs per row. Empty cells are left blank."""
    cell = styles["TableCell"]
    label_style = styles["Caption"]
    built = []
    for row in rows:
        padded = (list(row) + ["", "", "", ""])[:4]
        built.append(
            [
                Paragraph(_escape(padded[0]), label_style),
                Paragraph(_escape(padded[1] or "—") if padded[0] else "", cell),
                Paragraph(_escape(padded[2]), label_style),
                Paragraph(_escape(padded[3] or "—") if padded[2] else "", cell),
            ]
        )
    width = PORTRAIT_CONTENT_WIDTH_PT
    table = Table(
        built,
        colWidths=[width * 0.20, width * 0.30, width * 0.20, width * 0.30],
    )
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), COLOR_ZEBRA),
        ("BACKGROUND", (2, 0), (2, -1), COLOR_ZEBRA),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    table.setStyle(TableStyle(commands))
    return table


def _draw_page(canvas, doc) -> None:
    canvas.saveState()
    page_w, page_h = A4_PORTRAIT
    y_text = page_h - HEADER_TEXT_FROM_PAGE_TOP
    y_rule = page_h - HEADER_RULE_FROM_PAGE_TOP
    font = doc.ora_font
    canvas.setFont(font, 8.5)
    canvas.setFillColor(COLOR_BODY)
    canvas.drawString(MARGIN_SIDE, y_text, "Glider Buddy System")
    canvas.setFillColor(COLOR_PRIMARY)
    canvas.drawRightString(page_w - MARGIN_SIDE, y_text, "Operational Risk Assessment")
    canvas.setStrokeColor(COLOR_ACCENT)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN_SIDE, y_rule, page_w - MARGIN_SIDE, y_rule)
    canvas.setFont(font, 8)
    canvas.setFillColor(COLOR_MUTED)
    canvas.drawString(MARGIN_SIDE, 6 * mm, f"Page {canvas.getPageNumber()}")
    canvas.drawRightString(
        page_w - MARGIN_SIDE,
        6 * mm,
        OPS_CENTER_EMAIL,
    )
    canvas.restoreState()


def render_ora_pdf(
    fields: OraDocumentFields, *, area_map_png: Optional[bytes] = None
) -> bytes:
    styles = build_paragraph_styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4_PORTRAIT,
        leftMargin=MARGIN_SIDE,
        rightMargin=MARGIN_SIDE,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM + 4 * mm,
        title="Operational Risk Assessment",
        author="Glider Buddy System",
    )
    document.ora_font = styles["Body"].fontName

    story = [
        Paragraph("Operational Risk Assessment", styles["Heading1"]),
        Paragraph(
            _escape(
                f"Wave Glider request. Email this PDF to {OPS_CENTER_EMAIL}."
            ),
            styles["Muted"],
        ),
    ]
    heading = " · ".join(
        part for part in ((fields.title or "").strip(), (fields.hull_name or "").strip()) if part
    )
    if heading:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(_escape(heading), styles["Heading2"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Request", styles["Heading2"]))
    priority = PRIORITY_LABELS.get(fields.priority or 0, "—")
    story.append(
        _label_value_table(
            [
                ["Requester", fields.requester, "Project code", _project_code_text(fields)],
                ["Client", fields.client, "Dates of operation", fields.dates_of_operation],
                ["Hull", fields.hull_name, "Priority", priority],
            ],
            styles,
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            "Purpose: " + _escape(_marks(fields.purposes, PURPOSE_OPTIONS)),
            styles["Body"],
        )
    )

    if area_map_png:
        story.append(Spacer(1, 4 * mm))
        story.extend(_area_map_flowables(area_map_png, styles))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Coordinates", styles["Heading2"]))
    story.append(
        Paragraph(
            "Single point for hold-station, bounding box, or multiple points for a course.",
            styles["Caption"],
        )
    )
    coord_rows = [
        [
            str(number),
            (point.label or "").strip() or f"Coordinate {number}",
            _format_coord(point.lat),
            _format_coord(point.lon),
            point.comment or "",
        ]
        for number, point in enumerate(table_coordinates(fields), start=1)
    ]
    if coord_rows:
        story.append(
            styled_data_table(
                ["#", "Location", "Latitude", "Longitude", "Comments"],
                coord_rows,
                styles=styles,
                col_widths=[
                    PORTRAIT_CONTENT_WIDTH_PT * 0.06,
                    PORTRAIT_CONTENT_WIDTH_PT * 0.22,
                    PORTRAIT_CONTENT_WIDTH_PT * 0.16,
                    PORTRAIT_CONTENT_WIDTH_PT * 0.16,
                    PORTRAIT_CONTENT_WIDTH_PT * 0.40,
                ],
            )
        )
    else:
        story.append(Paragraph("No coordinates.", styles["Muted"]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Wave Glider configuration", styles["Heading2"]))
    story.append(
        _label_value_table(
            [
                [
                    "Model",
                    _choice_label(fields.vehicle_model, VEHICLE_OPTIONS),
                    "Umbilical",
                    _choice_label(fields.umbilical_m, UMBILICAL_OPTIONS),
                ],
                [
                    "Towing",
                    _choice_label(fields.towing, YES_NO_OPTIONS),
                    "Towed device",
                    fields.towed_device,
                ],
                [
                    "ECO's up to date",
                    _choice_label(fields.ecos_up_to_date, YES_NO_OPTIONS),
                    "SV3 software",
                    fields.sv3_software_version,
                ],
                ["# of APUs", fields.apu_count, "SMC version", fields.smc_version],
            ],
            styles,
        )
    )

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Devices and power", styles["Heading2"]))
    device_rows = [
        [device.name, device.power_draw or "", device.duty_cycle or ""]
        for device in fields.devices
        if device.included and (device.name or "").strip()
    ]
    if device_rows:
        story.append(
            styled_data_table(
                ["Device", "Power draw", "Duty cycle"],
                device_rows,
                styles=styles,
                col_widths=[
                    PORTRAIT_CONTENT_WIDTH_PT * 0.50,
                    PORTRAIT_CONTENT_WIDTH_PT * 0.22,
                    PORTRAIT_CONTENT_WIDTH_PT * 0.28,
                ],
            )
        )
    else:
        story.append(Paragraph("No devices listed.", styles["Muted"]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Additional notes", styles["Heading2"]))
    notes = (fields.notes or "").strip()
    if notes:
        for block in notes.splitlines():
            story.append(Paragraph(_escape(block) or "&nbsp;", styles["Body"]))
            story.append(Spacer(1, 1 * mm))
    else:
        story.append(Paragraph("None.", styles["Muted"]))

    document.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    return buffer.getvalue()
