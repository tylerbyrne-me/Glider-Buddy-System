"""ReportLab PDF that mirrors the CCG NAVWARN request form wording and layout.

Kept close to the official .docx for comparison; the filled .docx remains the
primary Coast Guard submission artifact.
"""

from __future__ import annotations

import io
from typing import Optional, Sequence

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.reporting.styling import (
    COLOR_BODY,
    COLOR_MUTED,
    COLOR_PRIMARY,
    COLOR_RULE,
    COLOR_ZEBRA,
    build_paragraph_styles,
)
from app.platforms.wave_glider.navwarn_form import (
    DAYS_OPTIONS,
    FIRM_ESTIMATED_OPTIONS,
    HOURS_OPTIONS,
    MARINE_WORKS_OPTIONS,
    NIS_URL,
    OBSTRUCTION_OPTIONS,
    OFFSHORE_OPTIONS,
    PUBLISH_CONTACT_OPTIONS,
    RECREATIONAL_OPTIONS,
    REGION_LINE,
    TIMEZONE_OPTIONS,
    UPDATE_OR_CANCEL_OPTIONS,
    WASH_BERTH_OPTIONS,
    WAVE_GLIDER_OVERVIEW_URL,
    NavwarnDocumentFields,
    desk_email,
    desk_title_line,
    format_position_parts,
    nature_other_for,
    option_label,
    pdf_or_docx_basename,
)

MARGIN = 0.6 * inch


def pdf_filename(fields: NavwarnDocumentFields) -> str:
    return f"{pdf_or_docx_basename(fields)}.pdf"


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;")


def _mark(is_on: bool, label: str) -> str:
    box = "☒" if is_on else "☐"
    return f"{box} {_escape(label)}"


def _marks(options: Sequence[tuple[str, str]], selected_key: Optional[str]) -> str:
    return "<br/>".join(
        _mark(selected_key == key, label) for key, label in options
    )


def _styles() -> dict[str, ParagraphStyle]:
    base = build_paragraph_styles()
    return {
        "Title": ParagraphStyle(
            "NavwarnTitle",
            parent=base["Heading1"],
            alignment=TA_CENTER,
            fontSize=14,
            leading=18,
            textColor=COLOR_PRIMARY,
            spaceAfter=2,
        ),
        "Subtitle": ParagraphStyle(
            "NavwarnSubtitle",
            parent=base["Body"],
            alignment=TA_CENTER,
            fontSize=11,
            leading=14,
            textColor=COLOR_BODY,
            spaceAfter=2,
        ),
        "Body": ParagraphStyle(
            "NavwarnBody",
            parent=base["Body"],
            alignment=TA_LEFT,
            fontSize=8.5,
            leading=11,
            textColor=COLOR_BODY,
        ),
        "Muted": ParagraphStyle(
            "NavwarnMuted",
            parent=base["Muted"],
            fontSize=8,
            leading=10,
            textColor=COLOR_MUTED,
        ),
        "Section": ParagraphStyle(
            "NavwarnSection",
            parent=base["Heading2"],
            fontSize=9.5,
            leading=12,
            textColor=COLOR_PRIMARY,
            spaceBefore=4,
            spaceAfter=2,
        ),
        "Cell": ParagraphStyle(
            "NavwarnCell",
            parent=base["TableCell"],
            fontSize=8,
            leading=10,
            textColor=COLOR_BODY,
        ),
        "Label": ParagraphStyle(
            "NavwarnLabel",
            parent=base["Caption"],
            fontSize=7.5,
            leading=9.5,
            textColor=COLOR_BODY,
        ),
    }


def _grid_table(rows: list[list], col_widths: list[float]) -> Table:
    table = Table(rows, colWidths=col_widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, COLOR_RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("BACKGROUND", (0, 0), (-1, 0), COLOR_ZEBRA),
            ]
        )
    )
    return table


def _section_banner(text: str, styles: dict, width: float) -> Table:
    row = [[Paragraph(_escape(text), styles["Section"])]]
    table = Table(row, colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_ZEBRA),
                ("BOX", (0, 0), (-1, -1), 0.4, COLOR_RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _value_or_blank(text: str) -> str:
    cleaned = (text or "").strip()
    return _escape(cleaned) if cleaned else "&nbsp;"


def render_navwarn_pdf(fields: NavwarnDocumentFields) -> bytes:
    styles = _styles()
    email = desk_email(fields.desk)
    width = letter[0] - 2 * MARGIN
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title="NAVWARN Request Form",
        author="Glider Buddy System",
    )

    story = [
        Paragraph(_escape(desk_title_line(fields.desk)), styles["Title"]),
        Paragraph(_escape(REGION_LINE), styles["Subtitle"]),
        Paragraph("NAVWARN Request Form", styles["Title"]),
        Spacer(1, 2 * mm),
        Paragraph(
            "Published Navigational Warnings (NAVWARNS) and email subscriptions "
            f"can be accessed at <link href='{NIS_URL}'>{_escape(NIS_URL)}</link>",
            styles["Muted"],
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            "NAVWARNs are messages containing urgent information relevant to safe "
            "navigation that are broadcast to ships. The Canadian Coast Guard issues "
            "and disseminates NAVWARNs to alert mariners of an imminent hazard to "
            "navigation and other urgent information which may impact the safety of "
            "shipping.",
            styles["Body"],
        ),
        Spacer(1, 1 * mm),
        Paragraph(
            "Information published in NAVWARNS must be brief, accurate and concise, "
            "and will be at the discretion of the Officer on Watch in accordance with "
            "Canadian Coast Guard procedures.",
            styles["Body"],
        ),
        Spacer(1, 3 * mm),
        _section_banner(
            f"Return this completed form to the following email address: {email}",
            styles,
            width,
        ),
        Spacer(1, 2 * mm),
        _section_banner("Required Contact Information", styles, width),
        _grid_table(
            [
                [
                    Paragraph(
                        "Name of person, vessel or organization requesting NAVWARN?",
                        styles["Label"],
                    ),
                    Paragraph("Telephone number?", styles["Label"]),
                ],
                [
                    Paragraph(_value_or_blank(fields.requester_name), styles["Cell"]),
                    Paragraph(_value_or_blank(fields.telephone), styles["Cell"]),
                ],
                [
                    Paragraph("Email address?", styles["Label"]),
                    Paragraph("", styles["Label"]),
                ],
                [
                    Paragraph(_value_or_blank(fields.email), styles["Cell"]),
                    Paragraph("", styles["Cell"]),
                ],
            ],
            [width * 0.65, width * 0.35],
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            "Do you wish to have your contact information published in the NAVWARN?",
            styles["Label"],
        ),
        Paragraph(
            _marks(PUBLISH_CONTACT_OPTIONS, fields.publish_contact), styles["Cell"]
        ),
    ]
    if fields.publish_contact == "yes_custom" and fields.publish_contact_custom.strip():
        story.append(
            Paragraph(_escape(fields.publish_contact_custom), styles["Cell"])
        )

    story.extend(
        [
            Spacer(1, 3 * mm),
            _section_banner(
                "Required NAVWARN Information. All below fields must be completed.",
                styles,
                width,
            ),
            _grid_table(
                [
                    [
                        Paragraph(
                            "Is this an update or cancellation to a previously "
                            "requested or published NAVWARN?",
                            styles["Label"],
                        ),
                        Paragraph(
                            "Previously published NAVWARN number (if known)?",
                            styles["Label"],
                        ),
                    ],
                    [
                        Paragraph(
                            _marks(UPDATE_OR_CANCEL_OPTIONS, fields.is_update_or_cancel),
                            styles["Cell"],
                        ),
                        Paragraph(
                            _value_or_blank(
                                fields.previous_navwarn_number
                                if fields.is_update_or_cancel == "yes"
                                else ""
                            ),
                            styles["Cell"],
                        ),
                    ],
                ],
                [width * 0.55, width * 0.45],
            ),
            Spacer(1, 2 * mm),
            Paragraph(
                "Start date and time of NAVWARN event/operation?<br/>"
                "NAVWARNS can be requested in advanced. They will be published "
                "24 hours before the start of the event/operation.",
                styles["Label"],
            ),
            Paragraph(_value_or_blank(fields.start_datetime), styles["Cell"]),
            Spacer(1, 1 * mm),
            Paragraph(
                "Timezone provided in (6.)?<br/>All NAVWARNS will be published in UTC",
                styles["Label"],
            ),
            Paragraph(_marks(TIMEZONE_OPTIONS, fields.timezone), styles["Cell"]),
            Spacer(1, 2 * mm),
            _grid_table(
                [
                    [
                        Paragraph("Days of operation?", styles["Label"]),
                        Paragraph("Hours of operation?", styles["Label"]),
                    ],
                    [
                        Paragraph(
                            _marks(DAYS_OPTIONS, fields.days_of_operation),
                            styles["Cell"],
                        ),
                        Paragraph(
                            _marks(HOURS_OPTIONS, fields.hours_of_operation),
                            styles["Cell"],
                        ),
                    ],
                ],
                [width * 0.5, width * 0.5],
            ),
        ]
    )
    if fields.days_of_operation == "other" and fields.days_other.strip():
        story.append(Paragraph(_escape(f"Days other: {fields.days_other}"), styles["Cell"]))
    if fields.hours_of_operation == "other" and fields.hours_other.strip():
        story.append(
            Paragraph(_escape(f"Hours other: {fields.hours_other}"), styles["Cell"])
        )

    story.extend(
        [
            Spacer(1, 2 * mm),
            _grid_table(
                [
                    [
                        Paragraph(
                            "Completion date &amp; time of NAVWARN event/operation?<br/>"
                            "You are responsible for advising us of changes to the "
                            "completion time.",
                            styles["Label"],
                        ),
                        Paragraph(
                            "Is the completion date &amp; time firm or estimated?<br/>"
                            "We will follow-up if the time is estimated. If the time is "
                            "firm the NAVWARN will be cancelled automatically",
                            styles["Label"],
                        ),
                    ],
                    [
                        Paragraph(
                            _value_or_blank(fields.completion_datetime), styles["Cell"]
                        ),
                        Paragraph(
                            _marks(FIRM_ESTIMATED_OPTIONS, fields.completion_firmness),
                            styles["Cell"],
                        ),
                    ],
                ],
                [width * 0.5, width * 0.5],
            ),
            Spacer(1, 2 * mm),
            Paragraph(
                "Position of NAVWARN event/operation? A latitude and longitude is "
                "required. Positions may be expressed in any of the following formats. "
                "Do not include apostrophes, quotation marks, degree signs or other "
                "symbols.",
                styles["Label"],
            ),
        ]
    )

    parts = format_position_parts(
        fields.latitude, fields.longitude, fields.position_format
    )
    pos_rows = [
        [
            Paragraph("degrees and minutes, or", styles["Label"]),
            Paragraph(
                _value_or_blank(parts["lat_text"] if fields.position_format == "dm" else ""),
                styles["Cell"],
            ),
            Paragraph(
                parts["lat_hemisphere"] if fields.position_format == "dm" else "N",
                styles["Cell"],
            ),
            Paragraph(
                _value_or_blank(parts["lon_text"] if fields.position_format == "dm" else ""),
                styles["Cell"],
            ),
            Paragraph(
                parts["lon_hemisphere"] if fields.position_format == "dm" else "W",
                styles["Cell"],
            ),
        ],
        [
            Paragraph("degrees minutes and seconds, or", styles["Label"]),
            Paragraph(
                _value_or_blank(
                    parts["lat_text"] if fields.position_format == "dms" else ""
                ),
                styles["Cell"],
            ),
            Paragraph(
                parts["lat_hemisphere"] if fields.position_format == "dms" else "N",
                styles["Cell"],
            ),
            Paragraph(
                _value_or_blank(
                    parts["lon_text"] if fields.position_format == "dms" else ""
                ),
                styles["Cell"],
            ),
            Paragraph(
                parts["lon_hemisphere"] if fields.position_format == "dms" else "W",
                styles["Cell"],
            ),
        ],
        [
            Paragraph("degrees minutes and decimal minutes", styles["Label"]),
            Paragraph(
                _value_or_blank(
                    parts["lat_text"] if fields.position_format == "dmm" else ""
                ),
                styles["Cell"],
            ),
            Paragraph(
                parts["lat_hemisphere"] if fields.position_format == "dmm" else "N",
                styles["Cell"],
            ),
            Paragraph(
                _value_or_blank(
                    parts["lon_text"] if fields.position_format == "dmm" else ""
                ),
                styles["Cell"],
            ),
            Paragraph(
                parts["lon_hemisphere"] if fields.position_format == "dmm" else "W",
                styles["Cell"],
            ),
        ],
    ]
    story.append(
        _grid_table(
            pos_rows,
            [width * 0.34, width * 0.22, width * 0.08, width * 0.22, width * 0.14],
        )
    )
    story.extend(
        [
            Spacer(1, 2 * mm),
            Paragraph(
                "If desired, also include a local-area place name that defines where "
                "your event/operation is taking place. For example, the name of a "
                "small town, harbour or region.",
                styles["Label"],
            ),
            Paragraph(_value_or_blank(fields.place_name), styles["Cell"]),
            Spacer(1, 1 * mm),
            Paragraph(
                "If desired, multiple positions can be defined below. The same "
                "position format as in (8.) must be used.",
                styles["Label"],
            ),
            Paragraph(_value_or_blank(fields.extra_positions), styles["Cell"]),
            Spacer(1, 3 * mm),
            Paragraph("Form continues on the next page.", styles["Muted"]),
            Spacer(1, 4 * mm),
            _section_banner(
                "NAVWARN details. Complete all fields pertaining to your event/operation.",
                styles,
                width,
            ),
            Paragraph(
                "Nature of event/operation? Select ONE topic below:",
                styles["Label"],
            ),
            _grid_table(
                [
                    [
                        Paragraph("<b>Marine works:</b>", styles["Label"]),
                        Paragraph("<b>Obstruction:</b>", styles["Label"]),
                        Paragraph("<b>Offshore works:</b>", styles["Label"]),
                    ],
                    [
                        Paragraph(
                            _marks(
                                MARINE_WORKS_OPTIONS,
                                fields.nature_topic
                                if fields.nature_category == "marine_works"
                                else None,
                            ),
                            styles["Cell"],
                        ),
                        Paragraph(
                            _marks(
                                OBSTRUCTION_OPTIONS,
                                fields.nature_topic
                                if fields.nature_category == "obstruction"
                                else None,
                            ),
                            styles["Cell"],
                        ),
                        Paragraph(
                            _marks(
                                OFFSHORE_OPTIONS,
                                fields.nature_topic
                                if fields.nature_category == "offshore"
                                else None,
                            ),
                            styles["Cell"],
                        ),
                    ],
                    [
                        Paragraph("", styles["Cell"]),
                        Paragraph("", styles["Cell"]),
                        Paragraph("<b>Recreational event:</b>", styles["Label"]),
                    ],
                    [
                        Paragraph("", styles["Cell"]),
                        Paragraph("", styles["Cell"]),
                        Paragraph(
                            _marks(
                                RECREATIONAL_OPTIONS,
                                fields.nature_topic
                                if fields.nature_category == "recreational"
                                else None,
                            ),
                            styles["Cell"],
                        ),
                    ],
                ],
                [width / 3, width / 3, width / 3],
            ),
        ]
    )
    other = nature_other_for(fields)
    if other:
        category_labels = (
            ("marine_works", "Marine works"),
            ("obstruction", "Obstruction"),
            ("offshore", "Offshore works"),
            ("recreational", "Recreational event"),
        )
        category_name = option_label(fields.nature_category, category_labels) or "Other"
        story.append(
            Paragraph(
                _escape(f"{category_name} other: {other}"),
                styles["Cell"],
            )
        )

    story.extend(
        [
            Spacer(1, 2 * mm),
            Paragraph(
                "Vessels or other equipment on scene? If available include vessel "
                "name &amp; type, radio frequency monitored or other ways mariners "
                "can make contact.",
                styles["Label"],
            ),
            Paragraph(_value_or_blank(fields.vessels_on_scene), styles["Cell"]),
            Spacer(1, 2 * mm),
            Paragraph(
                "Description of markers, buoys, flags, etc. that will be deployed "
                "on scene? Include type, quantity, colour, etc. Also include light "
                "colour and flash (if any), or \"unlit\" if none.",
                styles["Label"],
            ),
            Paragraph(_value_or_blank(fields.markers_description), styles["Cell"]),
            Spacer(1, 2 * mm),
            Paragraph(
                "Is minimum wash (low wake) and/or a wide berth requested of "
                "passing mariners?",
                styles["Label"],
            ),
            Paragraph(_marks(WASH_BERTH_OPTIONS, fields.wash_berth), styles["Cell"]),
            Spacer(1, 2 * mm),
            Paragraph(
                "Any other details or specific text that mariners must be aware of "
                "for the safety of navigation? (Details must be brief, accurate and "
                "concise. Additional details published will be at the discretion of "
                "the Officer on Watch).",
                styles["Label"],
            ),
            Paragraph(_value_or_blank(fields.other_details), styles["Cell"]),
            Spacer(1, 3 * mm),
            Paragraph(
                "No images, drawings, charts, etc. can be published with NAVWARNS. "
                "However, if you have additional information that is essential to "
                "communicate to the Officer on Watch for clarity of the NAVWARN "
                "request, please attach it via email along with this completed form.",
                styles["Muted"],
            ),
            Spacer(1, 4 * mm),
            Paragraph("Additional information:", styles["Section"]),
            Paragraph(
                f"<link href='{WAVE_GLIDER_OVERVIEW_URL}'>"
                f"{_escape(WAVE_GLIDER_OVERVIEW_URL)}</link>",
                styles["Muted"],
            ),
        ]
    )

    document.build(story)
    return buffer.getvalue()
