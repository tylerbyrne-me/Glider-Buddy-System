# Weekly mission report — style & layout guide

Mission PDFs are built with **ReportLab Platypus** (`app/core/reporting/`): vector text, tables, TOC, and page chrome. **Matplotlib** remains the source of truth for charts; figures are rasterized to PNG and embedded as Platypus `Image` flowables (`charts.py`).

## Layout model

| Piece | Role |
|--------|------|
| `WeeklyReportDocTemplate` (`styling.py`) | `BaseDocTemplate` with **cover**, **portrait**, and **landscape** `PageTemplate`s. Landscape pages **must** set `pagesize=A4_LANDSCAPE` on that template so frame geometry matches the physical page. |
| Frames | Portrait and landscape frames use shared margins (`MARGIN_SIDE`, `MARGIN_TOP`, `MARGIN_BOTTOM`). Inner sizes are exposed as `PORTRAIT_CONTENT_*_PT` and `LANDSCAPE_CONTENT_*_PT`. |
| Headers / footers | `onPage` callbacks draw rule, mission header, report title, page number, and generated timestamp. |
| Outline / bookmarks | `afterFlowable` reacts to `Paragraph` with style `Heading1`: notifies TOC, `bookmarkPage`, `addOutlineEntry`. |

## Design tokens

- **Palette**: `COLOR_PRIMARY`, `COLOR_ACCENT`, `COLOR_BODY`, `COLOR_MUTED`, zebra `COLOR_ZEBRA`, rule `COLOR_RULE`, severity colors (`COLOR_SEV_*`) in `styling.py`.
- **Typography**: body font is resolved from `REPORT_PDF_FONT_STACK` in `app/core/plotting.py` and registered once for ReportLab (`_register_body_font`). Fallback: Helvetica.
- **Reusable flowables**: `SectionHeader`, `DataPeriodBanner`, `NoteCard`, `kpi_row_table`, `styled_data_table`, `severity_pill_cell`, cover helpers in `styling.py`.

## Data tables (wrapping)

ReportLab draws **plain strings** in `Table` cells as **single lines** (no wrap), which causes overlap and margin bleed. `styled_data_table` therefore takes a **`styles`** dict and builds **header `Paragraph`s** plus body cells as **`Paragraph`** or nested **`Flowable`** (e.g. severity pill `Table`). Pass **`colWidths`** that sum to the portrait inner width (`_pw()` in `sections.py`). Optional **`header_style`** (e.g. `InstrumentTableHeader`) shrinks long column titles.

## Table of contents

`TableOfContents` uses **`dotsMinLevel`**: `Heading1` entries are notified at **level 0**, so set **`dotsMinLevel=0`** in `build_toc_flowable` or dot leaders are suppressed (ReportLab default is `1`).

## Charts

1. Plot functions live in `app/core/plotting.py` (`plot_*_for_report`, `plot_telemetry_page_with_notes`, etc.).
2. `reporting/charts.py` opens `report_pdf_rc_context()`, builds the figure, saves to a `BytesIO` PNG, then builds a Platypus `Image` with **width and height** scaled to fit `max_width_pt` and optional `max_height_pt` (so figures never exceed the frame after headings/banners).
3. Section builders pass `LANDSCAPE_CONTENT_WIDTH_PT` and `_landscape_chart_max_height_pt()` (or portrait equivalents for telemetry) so layout stays stable across DPI / `bbox_inches="tight"` variance.

## Vehicle errors

Raw `ErrorMessage` strings are parsed in `app/core/processors.py` via `parse_error_message` → `parsed_severity`, `parsed_source`, `parsed_code`, `parsed_detail` (applied inside `preprocess_error_df`). The errors table uses pill styling for severity (`severity_pill_cell`).

## How to add a new section

1. **Data**: extend `write_weekly_mission_pdf` / `_filter_report_dataframes` in `builder.py` if the section needs a new dataframe or filter window.
2. **Plots**: if matplotlib-based, add `plot_*_for_report` (or reuse) in `plotting.py`, then `chart_*_image` in `charts.py` with explicit max width/height.
3. **Flowables**: add `build_<section>_section(...)` in `sections.py` returning `List[Flowable]`. Use `Heading1` for top-level titles that should appear in the **TOC and PDF outline**. Return `[]` when there is nothing to show so the builder can skip empty pages.
4. **Story order**: append `NextPageTemplate` / `PageBreak` as needed in `builder.py` (landscape block uses `NextPageTemplate("landscape")` before landscape-only chart sections).
5. **Regression**: add or extend `tests/test_weekly_report_pdf.py` (outline strings, page count, non-empty output).

## Public API

Import from `app.core.reporting` (package `app/core/reporting/__init__.py`): `generate_weekly_report`, `generate_weekly_report_pdf_for_mission`, `REPORTS_ROOT`, `LOGO_PATH`, etc. Do not import removed monolith `reporting.py`.
