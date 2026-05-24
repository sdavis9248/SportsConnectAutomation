"""
PlayMetrics Enrollment Summary Report Generator

Reads the scraped packages JSON and PM export CSVs to produce a
formatted Excel report matching the Region 58 Enrollment Summary format.

Data sources:
  - packages_{timestamp}.json (scraped via --pm-download packages)
  - registration-responses_{timestamp}.csv (optional, for detailed player data)
  - volunteers_{timestamp}.csv (optional, for volunteer coverage)
  - coaching-requests_{timestamp}.csv (optional, for coaching data)

Usage:
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
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# ── Region 58 Division Configuration ────────────────────────────────────
# roster_size/on_field are AYSO rules; max_spots comes from packages JSON.
# Sara: 07UB roster_size back to 7 (2026-05-24).

DIVISION_CONFIG = {
    "05U Schoolyard Coed": {"roster_size":  0, "roster_min":  0, "on_field":  0,  "refs_required": False, "sort": 1},
    "06UB Boys":           {"roster_size":  6, "roster_min":  5, "on_field":  4,  "refs_required": False, "sort": 2},
    "06UG Girls":          {"roster_size":  6, "roster_min":  5, "on_field":  4,  "refs_required": False, "sort": 3},
    "07UB Boys":           {"roster_size":  7, "roster_min":  6, "on_field":  4,  "refs_required": False, "sort": 4},
    "07UG Girls":          {"roster_size":  7, "roster_min":  6, "on_field":  4,  "refs_required": False, "sort": 5},
    "08UB Boys":           {"roster_size":  7, "roster_min":  6, "on_field":  5,  "refs_required": False, "sort": 6},
    "08UG Girls":          {"roster_size":  7, "roster_min":  6, "on_field":  5,  "refs_required": False, "sort": 7},
    "10UB Boys":           {"roster_size":  9, "roster_min":  8, "on_field":  7,  "refs_required": True,  "sort": 8},
    "10UG Girls":          {"roster_size":  9, "roster_min":  8, "on_field":  7,  "refs_required": True,  "sort": 9},
    "12UB Boys":           {"roster_size": 12, "roster_min": 10, "on_field":  9,  "refs_required": True,  "sort": 10},
    "12UG Girls":          {"roster_size": 12, "roster_min": 10, "on_field":  9,  "refs_required": True,  "sort": 11},
    "14UB Boys":           {"roster_size": 14, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 12},
    "14UG Girls":          {"roster_size": 14, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 13},
    "16UB Boys":           {"roster_size": 14, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 14},
    "16UG Girls":          {"roster_size": 14, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 15},
    "19UB Boys":           {"roster_size": 22, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 16},
    "19UG Girls":          {"roster_size": 22, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 17},
}

# Section colors
COLORS = {
    "enrollment_header":  "1F4E79",
    "financial_header":   "2E75B6",
    "team_header":        "375623",
    "volunteer_header":   "7030A0",
    "enrollment_bg":      "D6E4F0",
    "financial_bg":       "DAEEF3",
    "team_bg":            "E2EFDA",
    "volunteer_bg":       "E8D4F0",
    "header_font":        "FFFFFF",
    "totals_bg":          "FFF2CC",
}

def _parse_currency(val):
    if not val:
        return 0.0
    return float(re.sub(r'[^\d.\-]', '', str(val)))

def _find_latest_json(data_dir, prefix="packages"):
    d = Path(data_dir)
    pattern = re.compile(rf'^{prefix}_(\d{{8}}_\d{{6}})\.json$')
    candidates = [f for f in d.iterdir() if f.is_file() and pattern.match(f.name)]
    return str(max(candidates, key=lambda f: f.name)) if candidates else None


class PlayMetricsEnrollmentReport:

    COLUMNS = [
        ("Program Name",    "identity",   16,  None),
        ("Division Name",   "identity",   30,  None),
        ("Enrollments",     "enrollment", 13,  "#,##0"),
        ("Maximum",         "enrollment", 10,  "#,##0"),
        ("Waitlist",        "enrollment",  9,  "#,##0"),
        ("% Enrolled",      "enrollment", 11,  "0.0%"),
        ("Available",       "enrollment", 10,  "#,##0"),
        ("Unpaid",          "enrollment",  9,  "#,##0"),
        ("% Unpaid",        "enrollment", 10,  "0.0%"),
        ("Total",           "financial",  13,  "$#,##0.00"),
        ("Paid",            "financial",  13,  "$#,##0.00"),
        ("Refunded",        "financial",  13,  "$#,##0.00"),
        ("Outstanding",     "financial",  13,  "$#,##0.00"),
        ("Roster Size",     "team",       11,  "#,##0"),
        ("On Field",        "team",        9,  "#,##0"),
        ("Target Teams",    "team",       13,  "#,##0"),
        ("Current Teams",   "team",       13,  "#,##0"),
        ("% Teams Formed",  "team",       13,  "0.0%"),
        ("Allocated",       "team",       10,  "#,##0"),
        ("Unallocated",     "team",       12,  "#,##0"),
        ("Head Coach",      "volunteer",  12,  "#,##0"),
        ("% HC Coverage",   "volunteer",  13,  "0.0%"),
        ("Asst Coach",      "volunteer",  11,  "#,##0"),
        ("Referees Needed", "volunteer",  14,  "#,##0"),
        ("Total Referees",  "volunteer",  13,  "#,##0"),
    ]

    def __init__(self, data_dir="data/playmetrics", output_dir="data/playmetrics"):
        self.data_dir = data_dir
        self.output_dir = output_dir
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    def load_packages(self, json_path=None):
        if not json_path:
            json_path = _find_latest_json(self.data_dir, "packages")
        if not json_path:
            raise FileNotFoundError(f"No packages JSON found in {self.data_dir}")
        logger.info(f"Loading packages from: {json_path}")
        with open(json_path) as f:
            return json.load(f).get("packages", [])

    def _build_division_rows(self, packages):
        rows = []
        for pkg in packages:
            name = pkg["name"]
            cfg = DIVISION_CONFIG.get(name)
            if not cfg:
                continue
            active = pkg["active_registrations"]
            maximum = pkg["max_spots"]
            roster = cfg["roster_size"]
            roster_min = cfg["roster_min"]
            waitlist = pkg["waitlist"]

            # Target teams = Int(maximum / roster_size) — from Access SQL
            target_teams = int(maximum / roster) if roster > 0 else 0

            # Current teams — Access SQL logic:
            # effective = enrollments if enrollments >= roster_size
            #           else roster_size if enrollments >= roster_min
            #           else enrollments
            # if (effective + waitlist) > maximum: use maximum
            # current_teams = Int(result / roster_size)
            if roster > 0:
                if active < roster:
                    effective = roster if active >= roster_min else active
                else:
                    effective = active
                capped = maximum if (effective + waitlist) > maximum else effective
                current_teams = int(capped / roster)
            else:
                current_teams = 0

            rows.append({
                "division": name,
                "enrollments": active, "maximum": maximum,
                "waitlist": waitlist,
                "pct_enrolled": min(active / maximum, 1) if maximum else 0,
                "available": maximum - active,
                "unpaid": 0, "pct_unpaid": 0,
                "total": _parse_currency(pkg.get("total", "")),
                "paid": _parse_currency(pkg.get("paid", "")),
                "refunded": _parse_currency(pkg.get("refunded", "")),
                "outstanding": _parse_currency(pkg.get("outstanding", "")),
                "roster_size": roster, "on_field": cfg["on_field"],
                "target_teams": target_teams,
                "current_teams": current_teams,
                "pct_teams": min(current_teams / target_teams, 1) if target_teams else 0,
                "allocated": 0, "unallocated": active,
                "head_coach": 0, "pct_hc": 0, "asst_coach": 0,
                "refs_needed": 0, "total_refs": 0,
                "sort": cfg.get("sort", 99),
            })
        rows.sort(key=lambda r: r["sort"])
        return rows

    def generate(self, packages_json=None, output_path=None):
        packages = self.load_packages(packages_json)
        rows = self._build_division_rows(packages)

        wb = Workbook()
        ws = wb.active
        ws.title = "Enrollment Summary"

        total_cols = len(self.COLUMNS)
        data_start = 4
        data_end = data_start + len(rows) - 1

        # Section spans
        sections = {}
        col = 1
        for _, section, _, _ in self.COLUMNS:
            sections.setdefault(section, {"start": col, "end": col})
            sections[section]["end"] = col
            col += 1

        # ── Borders ──
        thin = Side(style='thin', color='B0B0B0')
        medium = Side(style='medium', color='404040')
        section_right_cols = {2, 9, 13, 20}   # B, I, M, T
        section_left_cols = {3, 10, 14, 21}   # C, J, N, U

        def _border(row, ci):
            l, r, t, b = thin, thin, thin, thin
            if ci in section_right_cols: r = medium
            if ci in section_left_cols:  l = medium
            if ci == 1:          l = medium
            if ci == total_cols: r = medium
            if row == 1:         t = medium
            if row == data_end:  b = medium
            if row == 2:         b = medium
            if row == 3:         t = medium; b = medium
            if row == data_start: t = medium
            return Border(left=l, right=r, top=t, bottom=b)

        # ── Zero-as-blank number formats ──
        zb = {"#,##0": '#,##0;;""', "0.0%": '0.0%;;""', "$#,##0.00": '$#,##0.00;;""'}

        # ── Section header/bg mappings ──
        section_labels = {
            "identity":   ("Season Details",     COLORS["enrollment_header"]),
            "enrollment": ("Enrollment Summary", COLORS["enrollment_header"]),
            "financial":  ("Financial Summary",  COLORS["financial_header"]),
            "team":       ("Team Summary",       COLORS["team_header"]),
            "volunteer":  ("Volunteer Summary",  COLORS["volunteer_header"]),
        }
        section_bg = {
            "identity":   COLORS["enrollment_bg"],
            "enrollment": COLORS["enrollment_bg"],
            "financial":  COLORS["financial_bg"],
            "team":       COLORS["team_bg"],
            "volunteer":  COLORS["volunteer_bg"],
        }

        # ── Row 1: Section headers ──
        for section, span in sections.items():
            label, color = section_labels.get(section, ("", None))
            if not label or not color:
                continue
            sc, ec = span["start"], span["end"]
            cell = ws.cell(row=1, column=sc, value=label)
            cell.font = Font(name='Calibri', bold=True, color=COLORS["header_font"], size=11)
            cell.fill = PatternFill("solid", fgColor=color)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            if ec > sc:
                ws.merge_cells(start_row=1, start_column=sc, end_row=1, end_column=ec)
            for c in range(sc, ec + 1):
                ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor=color)
                ws.cell(row=1, column=c).border = _border(1, c)

        # ── Row 2: Column headers ──
        for ci, (header, section, width, _) in enumerate(self.COLUMNS, 1):
            cell = ws.cell(row=2, column=ci, value=header)
            cell.font = Font(name='Calibri', bold=True, size=10)
            cell.fill = PatternFill("solid", fgColor=section_bg.get(section, 'D6E4F0'))
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = _border(2, ci)
            ws.column_dimensions[get_column_letter(ci)].width = width

        # ── Row 3: Totals ──
        totals_fill = PatternFill("solid", fgColor=COLORS["totals_bg"])
        ws.cell(row=3, column=1, value="2026 Fall Core").font = Font(name='Calibri', bold=True)
        ws.cell(row=3, column=1).alignment = Alignment(horizontal="center")
        ws.cell(row=3, column=2, value="Totals").font = Font(name='Calibri', bold=True)
        ws.cell(row=3, column=2).alignment = Alignment(horizontal="right")

        sum_cols = {3, 4, 5, 7, 8, 10, 11, 12, 13, 16, 17, 19, 20, 21, 23, 24, 25}
        pct_cols = {6: (3, 4), 9: (8, 3), 18: (17, 16), 22: (21, 16)}

        for ci in range(1, total_cols + 1):
            cell = ws.cell(row=3, column=ci)
            cell.fill = totals_fill
            cell.border = _border(3, ci)
            cell.font = Font(name='Calibri', bold=True)
            cl = get_column_letter(ci)
            if ci in sum_cols:
                cell.value = f"=SUM({cl}{data_start}:{cl}{data_end})"
            elif ci in pct_cols:
                nc = get_column_letter(pct_cols[ci][0])
                dc = get_column_letter(pct_cols[ci][1])
                cell.value = f'=IF({dc}3=0,"",{nc}3/{dc}3)'
            _, _, _, fmt = self.COLUMNS[ci - 1]
            if fmt:
                cell.number_format = zb.get(fmt, fmt)

        # ── Data rows ──
        now = datetime.now()
        val_keys = [
            None, "division", "enrollments", "maximum", "waitlist",
            "pct_enrolled", "available", "unpaid", "pct_unpaid",
            "total", "paid", "refunded", "outstanding",
            "roster_size", "on_field", "target_teams", "current_teams",
            "pct_teams", "allocated", "unallocated",
            "head_coach", "pct_hc", "asst_coach", "refs_needed", "total_refs",
        ]

        for row_idx, row_data in enumerate(rows, data_start):
            for ci in range(1, total_cols + 1):
                key = val_keys[ci - 1] if ci - 1 < len(val_keys) else None
                val = row_data.get(key, "") if key else ""
                cell = ws.cell(row=row_idx, column=ci, value=val)
                cell.font = Font(name='Calibri', size=10)
                cell.border = _border(row_idx, ci)
                _, section, _, fmt = self.COLUMNS[ci - 1]
                bg = section_bg.get(section)
                if bg:
                    cell.fill = PatternFill("solid", fgColor=bg)
                if fmt:
                    cell.number_format = zb.get(fmt, fmt)

        # Date/time in A4, A5 (centered)
        c = ws.cell(row=data_start, column=1, value=now.date())
        c.number_format = 'MM/DD/YYYY'
        c.alignment = Alignment(horizontal="center")
        c = ws.cell(row=data_start + 1, column=1, value=now.time())
        c.number_format = 'HH:MM:SS AM/PM'
        c.alignment = Alignment(horizontal="center")

        # ── Conditional formatting ──
        from openpyxl.formatting.rule import ColorScaleRule

        # % Enrolled, % Teams, % HC: Red→Yellow→Green  (0→50→100%)
        for ci in [6, 18, 22]:
            cl = get_column_letter(ci)
            ws.conditional_formatting.add(
                f"{cl}{data_start}:{cl}{data_end}",
                ColorScaleRule(
                    start_type='num', start_value=0,   start_color='F8696B',
                    mid_type='num',   mid_value=0.5,   mid_color='FFEB84',
                    end_type='num',   end_value=1,     end_color='63BE7B',
                ))

        # % Unpaid: enrollment_bg→Yellow→Red  (0→1%→10%)
        # Start at section bg color so 0% blank cells keep the tint
        cl = get_column_letter(9)
        ws.conditional_formatting.add(
            f"{cl}{data_start}:{cl}{data_end}",
            ColorScaleRule(
                start_type='num', start_value=0,    start_color=COLORS["enrollment_bg"],
                mid_type='num',   mid_value=0.01,   mid_color='FFEB84',
                end_type='num',   end_value=0.10,   end_color='F8696B',
            ))

        # ── Freeze A:I ──
        ws.freeze_panes = "J3"

        # ── Save ──
        if not output_path:
            ts = now.strftime("%Y%m%d_%H%M%S")
            output_path = str(Path(self.output_dir) / f"Enrollment_Summary_Report_{ts}.xlsx")
        wb.save(output_path)
        logger.info(f"Report saved: {output_path}")
        return output_path


def handle_pm_report(config, args) -> int:
    from utilities.logger import setup_logging
    log = setup_logging(log_level='INFO')
    try:
        data_dir = config.get('playmetrics_config.download_dir', 'data/playmetrics') if config else 'data/playmetrics'
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
    print(f"Generated: {report.generate()}")
