"""
PlayMetrics Enrollment Summary Report Generator

Reads the scraped packages JSON and PM export CSVs to produce a multi-sheet
Excel report matching the Region 58 Enrollment Summary format.

Data sources:
  - packages_{timestamp}.json (scraped from PM Packages tab via --pm-download packages)
  - registration-responses_{timestamp}.csv (optional, for detailed player data)
  - volunteers_{timestamp}.csv (optional, for volunteer coverage)
  - coaching-requests_{timestamp}.csv (optional, for coaching data)

Usage (standalone):
  python playmetrics_enrollment_report.py

Usage (via main.py):
  python main.py --pm-report
  python main.py --pm-report --pm-report-output data/my_report.xlsx
"""
import os
import re
import json
import math
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# ── Region 58 Division Configuration ────────────────────────────────────
# roster_size and on_field are AYSO rules; max_spots comes from packages JSON.
# Sara requested 07UB roster_size back to 7 (2026-05-24).

DIVISION_CONFIG = {
    "05U Schoolyard Coed": {"roster_size": 12, "roster_min": 10, "on_field": 7,  "refs_required": False, "sort": 1},
    "06UB Boys":           {"roster_size": 10, "roster_min": 8,  "on_field": 6,  "refs_required": False, "sort": 2},
    "06UG Girls":          {"roster_size": 10, "roster_min": 8,  "on_field": 6,  "refs_required": False, "sort": 3},
    "07UB Boys":           {"roster_size": 7,  "roster_min": 7,  "on_field": 7,  "refs_required": False, "sort": 4},
    "07UG Girls":          {"roster_size": 12, "roster_min": 10, "on_field": 7,  "refs_required": False, "sort": 5},
    "08UB Boys":           {"roster_size": 12, "roster_min": 10, "on_field": 7,  "refs_required": False, "sort": 6},
    "08UG Girls":          {"roster_size": 12, "roster_min": 10, "on_field": 7,  "refs_required": False, "sort": 7},
    "10UB Boys":           {"roster_size": 12, "roster_min": 10, "on_field": 9,  "refs_required": True,  "sort": 8},
    "10UG Girls":          {"roster_size": 12, "roster_min": 10, "on_field": 9,  "refs_required": True,  "sort": 9},
    "12UB Boys":           {"roster_size": 12, "roster_min": 10, "on_field": 9,  "refs_required": True,  "sort": 10},
    "12UG Girls":          {"roster_size": 12, "roster_min": 10, "on_field": 9,  "refs_required": True,  "sort": 11},
    "14UB Boys":           {"roster_size": 14, "roster_min": 12, "on_field": 11, "refs_required": True,  "sort": 12},
    "14UG Girls":          {"roster_size": 14, "roster_min": 12, "on_field": 11, "refs_required": True,  "sort": 13},
    "16UB Boys":           {"roster_size": 14, "roster_min": 12, "on_field": 11, "refs_required": True,  "sort": 14},
    "16UG Girls":          {"roster_size": 14, "roster_min": 12, "on_field": 11, "refs_required": True,  "sort": 15},
    "19UB Boys":           {"roster_size": 22, "roster_min": 12, "on_field": 11, "refs_required": True,  "sort": 16},
    "19UG Girls":          {"roster_size": 22, "roster_min": 12, "on_field": 11, "refs_required": True,  "sort": 17},
}

# ── Section colors (alternating backgrounds) ────────────────────────────
COLORS = {
    "enrollment_header":  "1F4E79",   # Dark blue
    "financial_header":   "2E75B6",   # Medium blue
    "team_header":        "375623",   # Dark green
    "volunteer_header":   "7030A0",   # Purple
    "schedule_header":    "C55A11",   # Orange

    "enrollment_bg":      "D6E4F0",   # Light blue
    "financial_bg":       "DAEEF3",   # Light teal
    "team_bg":            "E2EFDA",   # Light green
    "volunteer_bg":       "E8D4F0",   # Light purple
    "schedule_bg":        "FBE5D6",   # Light orange

    "header_font":        "FFFFFF",   # White
    "col_header_bg":      "B4C6E7",   # Medium blue-gray
    "totals_bg":          "FFF2CC",   # Light yellow
}

def _parse_currency(val: str) -> float:
    if not val:
        return 0.0
    return float(re.sub(r'[^\d.\-]', '', val))


def _find_latest_json(data_dir: str, prefix: str = "packages") -> Optional[str]:
    d = Path(data_dir)
    pattern = re.compile(rf'^{prefix}_(\d{{8}}_\d{{6}})\.json$')
    candidates = [f for f in d.iterdir() if f.is_file() and pattern.match(f.name)]
    if not candidates:
        return None
    return str(max(candidates, key=lambda f: f.name))


class PlayMetricsEnrollmentReport:
    """Generates enrollment summary report from PlayMetrics data."""

    # Column layout — defines every column and its section
    # Format: (header_text, section, width, number_format)
    COLUMNS = [
        # A-B: Identity
        ("Program Name",          "identity",   16,  None),
        ("Division Name",         "identity",   30,  None),
        # C-I: Enrollment Summary
        ("Enrollments",           "enrollment", 13,  "#,##0"),
        ("Maximum",               "enrollment", 10,  "#,##0"),
        ("Waitlist",              "enrollment",  9,  "#,##0"),
        ("% Enrolled",            "enrollment", 11,  "0.0%"),
        ("Available",             "enrollment", 10,  "#,##0"),
        ("Unpaid",                "enrollment",  9,  "#,##0"),
        ("% Unpaid",              "enrollment", 10,  "0.0%"),
        # J-M: Financial Summary (NEW)
        ("Total",                 "financial",  13,  "$#,##0.00"),
        ("Paid",                  "financial",  13,  "$#,##0.00"),
        ("Refunded",              "financial",  13,  "$#,##0.00"),
        ("Outstanding",           "financial",  13,  "$#,##0.00"),
        # N-O: Roster config
        ("Roster Size",           "team",       11,  "#,##0"),
        ("On Field",              "team",        9,  "#,##0"),
        # P-S: Team Summary
        ("Target Teams",          "team",       13,  "#,##0"),
        ("Current Teams",         "team",       13,  "#,##0"),
        ("% Teams Formed",        "team",       13,  "0.0%"),
        ("Allocated",             "team",       10,  "#,##0"),
        ("Unallocated",           "team",       12,  "#,##0"),
        # T-X: Volunteer Summary
        ("Head Coach",            "volunteer",  12,  "#,##0"),
        ("% HC Coverage",         "volunteer",  13,  "0.0%"),
        ("Asst Coach",            "volunteer",  11,  "#,##0"),
        ("Referees Needed",       "volunteer",  14,  "#,##0"),
        ("Total Referees",        "volunteer",  13,  "#,##0"),
    ]

    def __init__(self, data_dir: str = "data/playmetrics",
                 output_dir: str = "data/playmetrics"):
        self.data_dir = data_dir
        self.output_dir = output_dir
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    def load_packages(self, json_path: str = None) -> List[Dict]:
        if not json_path:
            json_path = _find_latest_json(self.data_dir, "packages")
        if not json_path:
            raise FileNotFoundError(
                f"No packages JSON found in {self.data_dir}"
            )
        logger.info(f"Loading packages from: {json_path}")
        with open(json_path) as f:
            data = json.load(f)
        return data.get("packages", [])

    def _build_division_rows(self, packages: List[Dict]) -> List[Dict]:
        rows = []
        for pkg in packages:
            name = pkg["name"]
            cfg = DIVISION_CONFIG.get(name, {})
            if not cfg:
                logger.warning(f"Unknown division: {name}, skipping")
                continue

            active = pkg["active_registrations"]
            maximum = pkg["max_spots"]
            waitlist = pkg["waitlist"]
            roster = cfg["roster_size"]
            on_field = cfg["on_field"]
            target_teams = math.ceil(active / roster) if roster > 0 else 0

            rows.append({
                "division": name,
                "enrollments": active,
                "maximum": maximum,
                "waitlist": waitlist,
                "pct_enrolled": active / maximum if maximum > 0 else 0,
                "available": maximum - active,
                "unpaid": 0,  # TODO: from registration-responses CSV
                "pct_unpaid": 0,
                "total": _parse_currency(pkg.get("total", "")),
                "paid": _parse_currency(pkg.get("paid", "")),
                "refunded": _parse_currency(pkg.get("refunded", "")),
                "outstanding": _parse_currency(pkg.get("outstanding", "")),
                "roster_size": roster,
                "on_field": on_field,
                "target_teams": target_teams,
                "current_teams": 0,  # TODO: from team assignments
                "pct_teams": 0,
                "allocated": 0,
                "unallocated": active,
                "head_coach": 0,     # TODO: from volunteers CSV
                "pct_hc": 0,
                "asst_coach": 0,
                "refs_needed": 0,
                "total_refs": 0,
                "sort": cfg.get("sort", 99),
            })

        rows.sort(key=lambda r: r["sort"])
        return rows

    def generate(self, packages_json: str = None,
                 output_path: str = None) -> str:
        packages = self.load_packages(packages_json)
        rows = self._build_division_rows(packages)

        wb = Workbook()
        ws = wb.active
        ws.title = "Enrollment Summary"

        # ── Build section spans ──
        sections = {}
        col = 1
        for _, section, _, _ in self.COLUMNS:
            sections.setdefault(section, {"start": col, "end": col})
            sections[section]["end"] = col
            col += 1

        thin = Side(style='thin', color='D0D0D0')
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        # ── Row 1: Section headers (merged) ──
        section_labels = {
            "identity":   ("Season Details",       COLORS["enrollment_header"]),
            "enrollment": ("Enrollment Summary",   COLORS["enrollment_header"]),
            "financial":  ("Financial Summary",    COLORS["financial_header"]),
            "team":       ("Team Summary",         COLORS["team_header"]),
            "volunteer":  ("Volunteer Summary",    COLORS["volunteer_header"]),
        }

        for section, span in sections.items():
            label, color = section_labels.get(section, ("", None))
            if not label or not color:
                continue
            start_col = span["start"]
            end_col = span["end"]

            cell = ws.cell(row=1, column=start_col, value=label)
            cell.font = Font(bold=True, color=COLORS["header_font"], size=11)
            cell.fill = PatternFill("solid", fgColor=color)
            cell.alignment = Alignment(horizontal="center", vertical="center")

            if end_col > start_col:
                ws.merge_cells(
                    start_row=1, start_column=start_col,
                    end_row=1, end_column=end_col
                )
            # Fill merged range
            for c in range(start_col, end_col + 1):
                ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor=color)
                ws.cell(row=1, column=c).border = border

        # ── Row 2: Column headers ──
        section_bg = {
            "identity":   COLORS["enrollment_bg"],
            "enrollment": COLORS["enrollment_bg"],
            "financial":  COLORS["financial_bg"],
            "team":       COLORS["team_bg"],
            "volunteer":  COLORS["volunteer_bg"],
        }

        for col_idx, (header, section, width, _) in enumerate(self.COLUMNS, 1):
            cell = ws.cell(row=2, column=col_idx, value=header)
            cell.font = Font(bold=True, size=10)
            bg = section_bg.get(section, COLORS["col_header_bg"])
            cell.fill = PatternFill("solid", fgColor=bg)
            cell.alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )
            cell.border = border
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # ── Row 3: Totals row ──
        totals_fill = PatternFill("solid", fgColor=COLORS["totals_bg"])
        ws.cell(row=3, column=1, value="2026 Fall Core").font = Font(bold=True)
        ws.cell(row=3, column=2, value="Totals").font = Font(bold=True)

        data_start = 4
        data_end = data_start + len(rows) - 1

        # Sum formulas for totals row
        sum_cols = {
            3: True, 4: True, 5: True, 7: True, 8: True,  # enrollment
            10: True, 11: True, 12: True, 13: True,        # financial
            16: True, 17: True, 19: True, 20: True,        # team
            21: True, 23: True, 24: True, 25: True,        # volunteer
        }
        pct_cols = {6: (3, 4), 9: (8, 3), 18: (17, 16), 22: (21, 16)}

        for col_idx in range(1, len(self.COLUMNS) + 1):
            cell = ws.cell(row=3, column=col_idx)
            cell.fill = totals_fill
            cell.border = border
            cell.font = Font(bold=True)
            cl = get_column_letter(col_idx)

            if col_idx in sum_cols:
                cell.value = f"=SUM({cl}{data_start}:{cl}{data_end})"
            elif col_idx in pct_cols:
                num_col, den_col = pct_cols[col_idx]
                nc = get_column_letter(num_col)
                dc = get_column_letter(den_col)
                cell.value = f'=IF({dc}3=0,"",{nc}3/{dc}3)'

            # Apply number format
            _, section, _, fmt = self.COLUMNS[col_idx - 1]
            if fmt:
                cell.number_format = fmt

        # ── Data rows ──
        for row_idx, row_data in enumerate(rows, data_start):
            vals = [
                "",                          # A: Program Name (blank for data rows)
                row_data["division"],        # B
                row_data["enrollments"],     # C
                row_data["maximum"],         # D
                row_data["waitlist"],        # E
                row_data["pct_enrolled"],    # F
                row_data["available"],       # G
                row_data["unpaid"],          # H
                row_data["pct_unpaid"],      # I
                row_data["total"],           # J
                row_data["paid"],            # K
                row_data["refunded"],        # L
                row_data["outstanding"],     # M
                row_data["roster_size"],     # N
                row_data["on_field"],        # O
                row_data["target_teams"],    # P
                row_data["current_teams"],   # Q
                row_data["pct_teams"],       # R
                row_data["allocated"],       # S
                row_data["unallocated"],     # T
                row_data["head_coach"],      # U
                row_data["pct_hc"],          # V
                row_data["asst_coach"],      # W
                row_data["refs_needed"],     # X
                row_data["total_refs"],      # Y
            ]

            for col_idx, val in enumerate(vals, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.border = border

                # Apply number format (no alternating backgrounds)
                _, section, _, fmt = self.COLUMNS[col_idx - 1]
                if fmt:
                    cell.number_format = fmt

        # ── Conditional formatting: 3-color scale on percent columns ──
        # Red (0%) → Yellow (50%) → Green (100%)
        from openpyxl.formatting.rule import ColorScaleRule

        pct_column_indices = [6, 9, 18, 22]  # F, I, R, V (% columns)
        for col_idx in pct_column_indices:
            col_letter = get_column_letter(col_idx)
            cell_range = f"{col_letter}{data_start}:{col_letter}{data_end}"
            rule = ColorScaleRule(
                start_type='num', start_value=0,
                start_color='F8696B',      # Red
                mid_type='num', mid_value=0.5,
                mid_color='FFEB84',        # Yellow
                end_type='num', end_value=1,
                end_color='63BE7B',         # Green
            )
            ws.conditional_formatting.add(cell_range, rule)

        # ── Freeze panes ──
        ws.freeze_panes = "C3"

        # ── Sheet 2: Raw packages data ──
        ws2 = wb.create_sheet("Packages Data")
        pkg_headers = ["Division", "Active", "Max Spots", "Waitlist",
                       "Total", "Paid", "Refunded", "Outstanding"]
        for ci, h in enumerate(pkg_headers, 1):
            c = ws2.cell(row=1, column=ci, value=h)
            c.font = Font(bold=True)
        for ri, pkg in enumerate(packages, 2):
            ws2.cell(row=ri, column=1, value=pkg["name"])
            ws2.cell(row=ri, column=2, value=pkg["active_registrations"])
            ws2.cell(row=ri, column=3, value=pkg["max_spots"])
            ws2.cell(row=ri, column=4, value=pkg["waitlist"])
            ws2.cell(row=ri, column=5, value=_parse_currency(pkg.get("total", "")))
            ws2.cell(row=ri, column=6, value=_parse_currency(pkg.get("paid", "")))
            ws2.cell(row=ri, column=7, value=_parse_currency(pkg.get("refunded", "")))
            ws2.cell(row=ri, column=8, value=_parse_currency(pkg.get("outstanding", "")))
            for ci in range(5, 9):
                ws2.cell(row=ri, column=ci).number_format = "$#,##0.00"

        # ── Save ──
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(
                Path(self.output_dir) / f"Enrollment_Summary_Report_{ts}.xlsx"
            )

        wb.save(output_path)
        logger.info(f"Report saved: {output_path}")
        return output_path


def handle_pm_report(config, args) -> int:
    """CLI handler for --pm-report."""
    from utilities.logger import setup_logging
    log = setup_logging(log_level='INFO')

    try:
        data_dir = config.get(
            'playmetrics_config.download_dir', 'data/playmetrics'
        ) if config else 'data/playmetrics'
        output_path = getattr(args, 'pm_report_output', None)

        report = PlayMetricsEnrollmentReport(data_dir=data_dir)
        result = report.generate(output_path=output_path)
        print(f"Report generated: {result}")
        return 0
    except Exception as e:
        log.error(f"Error generating report: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = PlayMetricsEnrollmentReport()
    path = report.generate()
    print(f"Generated: {path}")
