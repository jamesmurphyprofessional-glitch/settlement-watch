from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from settlement_watch.models import ScoredCase
from settlement_watch.scoring import lead_narrative

DISCLAIMER = (
    "SCREENING TOOL ONLY. Rows are public-docket leads for human review. "
    "This file does not determine tax evasion, does not create an IRS case, "
    "and is not a Form 2797, Form 211, BSA SAR, or Special Agent Report. "
    "Many lawful settlements (including IRC §104(a)(2) physical-injury awards) will appear. "
    "False positives are expected. Do not treat a score as proof."
)

FIELD_DICTIONARY = [
    ("lead_id", "Stable id for this row (watch name + docket id).", "Local workpaper key; not a CIMIS number."),
    ("subject_name", "Watchlist name that matched.", "CIMIS/subject name analogue for a lead file."),
    ("subject_type", "person / company / unknown.", "Individual vs entity."),
    ("case_name", "Caption.", "Court identifier."),
    ("court", "Court name.", "Venue."),
    ("court_id", "CourtListener court id.", "Venue code."),
    ("docket_number", "Docket number.", "Court file number."),
    ("pacer_case_id", "PACER case id when present.", "PACER lookup."),
    ("date_filed", "ISO date filed.", "Event date."),
    ("date_terminated", "ISO date terminated, if any.", "Disposition date."),
    ("days_to_resolution", "Terminated minus filed, in days.", "Speed of resolution."),
    ("nature_of_suit", "Nature of suit / cause.", "Issue code analogue."),
    ("parties", "Party names from the public docket.", "Related parties to research."),
    ("amount_parsed_usd", "Dollar amounts parsed from public text.", "Alleged amount; often missing."),
    ("risk_score", "0-100 weighted heuristic.", "Sort key for review — not a fraud probability."),
    ("risk_band", "INFO / LOW / MEDIUM / HIGH.", "Triage band."),
    ("review_priority", "IGNORE / BACKGROUND / REVIEW.", "Whether an examiner should look."),
    ("flag_codes", "Triggered heuristic codes.", "Allegation tags."),
    ("flag_details", "Human-readable reasons.", "Lead narrative facts."),
    ("source_url", "CourtListener URL.", "Information source."),
    ("information_source", "Always public RECAP/CourtListener.", "Source-of-information field."),
    ("run_timestamp_utc", "When this file was generated.", "Workpaper timestamp."),
]


def _iso(value) -> str:
    return value.isoformat() if value else ""


def rows_from_results(results: list[ScoredCase], run_at: datetime) -> list[dict[str, str]]:
    stamp = run_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict[str, str]] = []
    for item in results:
        docket = item.docket
        lead_id = f"{item.watch_name}|{docket.docket_id or docket.docket_number}"
        amounts = "; ".join(str(amount) for amount in item.amounts)
        rows.append(
            {
                "lead_id": lead_id,
                "subject_name": item.watch_name,
                "subject_type": item.entity_type,
                "case_name": docket.case_name,
                "court": docket.court,
                "court_id": docket.court_id,
                "docket_number": docket.docket_number,
                "pacer_case_id": docket.pacer_case_id,
                "date_filed": _iso(docket.date_filed),
                "date_terminated": _iso(docket.date_terminated),
                "days_to_resolution": "" if docket.days_open() is None else str(docket.days_open()),
                "nature_of_suit": docket.suit_nature or docket.cause,
                "parties": "; ".join(docket.parties),
                "amount_parsed_usd": amounts,
                "risk_score": str(item.risk_score),
                "risk_band": item.risk_band,
                "review_priority": item.review_priority,
                "flag_codes": item.flag_codes,
                "flag_details": item.flag_details,
                "source_url": docket.url,
                "information_source": "CourtListener/RECAP public docket",
                "run_timestamp_utc": stamp,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [name for name, _, _ in FIELD_DICTIONARY]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, rows: list[dict[str, str]], run_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool": "Roach Detector",
        "version": "1.0.0",
        "disclaimer": DISCLAIMER,
        "generated_utc": run_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lead_count": len(rows),
        "leads": rows,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_narratives(path: Path, results: list[ScoredCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = [lead_narrative(item) for item in results]
    path.write_text("\n\n" + ("-" * 72) + "\n\n".join(blocks) + "\n", encoding="utf-8")


def write_field_dictionary_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["field_name", "meaning", "analyst_use"])
        for row in FIELD_DICTIONARY:
            writer.writerow(row)


BAND_FILL = {
    "HIGH": PatternFill("solid", fgColor="F4C7C3"),
    "MEDIUM": PatternFill("solid", fgColor="FCE8B2"),
    "LOW": PatternFill("solid", fgColor="D9EAD3"),
    "INFO": PatternFill("solid", fgColor="D0E2F3"),
}


def write_xlsx(
    path: Path,
    all_rows: list[dict[str, str]],
    flagged_rows: list[dict[str, str]],
    results: list[ScoredCase],
    run_at: datetime,
    mode: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    intro = wb.active
    if intro is None:
        intro = wb.create_sheet("Disclaimer", 0)
    intro.title = "Disclaimer"
    intro["A1"] = "Roach Detector — public docket screening workbook"
    intro["A1"].font = Font(bold=True, size=16, color="1F4E79")
    intro["A2"] = DISCLAIMER
    intro["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    intro["A2"].font = Font(size=11, color="9C0006")
    intro.merge_cells("A2:F6")
    intro["A8"] = "Generated (UTC)"
    intro["B8"] = run_at.strftime("%Y-%m-%d %H:%M:%S")
    intro["A9"] = "Run mode"
    intro["B9"] = mode
    intro["A10"] = "Dockets scored"
    intro["B10"] = len(all_rows)
    intro["A11"] = "Flagged for review (MEDIUM/HIGH)"
    intro["B11"] = sum(1 for row in all_rows if row["risk_band"] in {"MEDIUM", "HIGH"})
    intro["A13"] = "How an IRS analyst could use this file"
    intro["A13"].font = Font(bold=True, size=12)
    intro["A14"] = (
        "IRS-CI lead analytics have been described publicly as Excel flat files reviewed by "
        "the Nationally Coordinated Investigations Unit (see IRS PIA for Fraud Detection / "
        "lead files). This workbook is a similar analyst workbook: a disclaimer sheet, a "
        "triage sheet, a full extract, a field dictionary, and paste-ready narratives. "
        "It does not connect to CIMIS, RRP, EFDS, MeF, IDES, or SarGenXpress. Those systems "
        "are internal. Import is copy/paste or CSV load by an authorized user."
    )
    intro["A14"].alignment = Alignment(wrap_text=True, vertical="top")
    intro.merge_cells("A14:F18")
    intro.column_dimensions["A"].width = 28
    intro.column_dimensions["B"].width = 40
    intro.row_dimensions[2].height = 80
    intro.row_dimensions[14].height = 80

    _write_table_sheet(wb, "Flagged_Review", flagged_rows)
    _write_table_sheet(wb, "All_Matches", all_rows)
    _write_dictionary_sheet(wb)
    _write_narrative_sheet(wb, results)

    wb.save(path)


def _write_table_sheet(wb: Workbook, title: str, rows: list[dict[str, str]]) -> None:
    ws = wb.create_sheet(title)
    headers = [name for name, _, _ in FIELD_DICTIONARY]
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E79")
    thin = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(1, col, header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for r_index, row in enumerate(rows, start=2):
        band = row.get("risk_band", "INFO")
        fill = BAND_FILL.get(band)
        for c_index, header in enumerate(headers, start=1):
            value = row.get(header, "")
            if header == "risk_score" and value != "":
                cell_value: int | str = int(value)
            else:
                cell_value = value
            cell = ws.cell(r_index, c_index, cell_value)
            cell.border = thin
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if fill is not None:
                cell.fill = fill
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(len(rows) + 1, 1)}"
    ws.freeze_panes = "A2"
    widths = {
        "lead_id": 28,
        "subject_name": 28,
        "case_name": 42,
        "court": 28,
        "flag_details": 60,
        "source_url": 40,
        "parties": 36,
        "nature_of_suit": 28,
    }
    for col, header in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(col)].width = widths.get(header, 16)
    ws.sheet_properties.tabColor = "1F4E79"
    if rows:
        table = Table(
            displayName=f"{title}Table",
            ref=f"A1:{get_column_letter(len(headers))}{len(rows) + 1}",
        )
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(table)


def _write_dictionary_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet("Field_Dictionary")
    ws.append(["field_name", "meaning", "analyst_use"])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E79")
    for row in FIELD_DICTIONARY:
        ws.append(list(row))
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 55
    ws.column_dimensions["C"].width = 55
    ws.freeze_panes = "A2"


def _write_narrative_sheet(wb: Workbook, results: list[ScoredCase]) -> None:
    ws = wb.create_sheet("Lead_Narratives")
    ws.append(["subject_name", "docket_number", "risk_band", "risk_score", "narrative"])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E79")
    for item in results:
        ws.append(
            [
                item.watch_name,
                item.docket.docket_number,
                item.risk_band,
                item.risk_score,
                lead_narrative(item),
            ]
        )
        ws.cell(ws.max_row, 5).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[ws.max_row].height = 90
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["E"].width = 80
    ws.freeze_panes = "A2"


def export_all(
    out_dir: Path,
    results: list[ScoredCase],
    mode: str,
) -> dict[str, Path]:
    run_at = datetime.now(timezone.utc).replace(microsecond=0)
    all_rows = rows_from_results(results, run_at)
    flagged = [row for row in all_rows if row["risk_band"] in {"MEDIUM", "HIGH"}]
    flagged_results = [item for item in results if item.risk_band in {"MEDIUM", "HIGH"}]
    paths = {
        "xlsx": out_dir / "settlement_watch_leads.xlsx",
        "csv": out_dir / "settlement_watch_leads.csv",
        "flagged_csv": out_dir / "settlement_watch_flagged.csv",
        "json": out_dir / "settlement_watch_leads.json",
        "narratives": out_dir / "lead_narratives.txt",
        "dictionary": out_dir / "field_dictionary.csv",
    }
    write_xlsx(paths["xlsx"], all_rows, flagged, results, run_at, mode)
    write_csv(paths["csv"], all_rows)
    write_csv(paths["flagged_csv"], flagged)
    write_json(paths["json"], all_rows, run_at)
    write_narratives(paths["narratives"], flagged_results or results)
    write_field_dictionary_csv(paths["dictionary"])
    return paths
