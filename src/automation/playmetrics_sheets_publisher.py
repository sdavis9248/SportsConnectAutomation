"""
PlayMetrics Google Sheets Publisher for Looker Studio Dashboard
Reads packages_{timestamp}.json and pushes a flat dashboard-ready table
to a designated Google Sheet. Supports historical tracking for trend analysis.

Data flow:
  --pm-download packages → packages_*.json → --pm-push-sheets → Google Sheet → Looker Studio

Two sheets are maintained:
  1. "Current" — overwritten each run (one row per division, no timestamp)
     → Looker Studio scorecards, bar charts, detail table
  2. "History" — appended each run (one row per division per timestamp)
     → Looker Studio time-series charts for enrollment trends

Requires:
  - google_sheets_helper.py (already in src/automation/)
  - Service account key: kinetic-cosmos-469504-f4-f9182e88bc72.json
  - Google Sheet shared with the service account email
  - pip install gspread google-auth

Usage:
  python main.py --pm-push-sheets
  python main.py --pm-push-sheets --packages-file data/playmetrics/packages_20260524.json
  python main.py --pm-push-sheets --sheet-id 1ABC...xyz
"""

import os
import json
import math
import glob
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Division config — roster sizes and on-field counts
# Mirrors DIVISION_CONFIG from playmetrics_enrollment_report.py
# ─────────────────────────────────────────────────────────────
DIVISION_CONFIG = {
    # Co-ed divisions
    '04UC Co-ed':  {'roster_size': 6,  'on_field': 4,  'sort': 1},
    '05UC Co-ed':  {'roster_size': 6,  'on_field': 4,  'sort': 2},
    '06UB Boys':   {'roster_size': 8,  'on_field': 5,  'sort': 3},
    '06UG Girls':  {'roster_size': 8,  'on_field': 5,  'sort': 4},
    # 7U/8U — Sara's fix: 7UB roster_size = 7
    '07UB Boys':   {'roster_size': 7,  'on_field': 7,  'sort': 5},
    '07UG Girls':  {'roster_size': 12, 'on_field': 7,  'sort': 6},
    '08UB Boys':   {'roster_size': 12, 'on_field': 7,  'sort': 7},
    '08UG Girls':  {'roster_size': 12, 'on_field': 7,  'sort': 8},
    # Older divisions
    '10UB Boys':   {'roster_size': 12, 'on_field': 8,  'sort': 9},
    '10UG Girls':  {'roster_size': 12, 'on_field': 8,  'sort': 10},
    '12UB Boys':   {'roster_size': 14, 'on_field': 11, 'sort': 11},
    '12UG Girls':  {'roster_size': 14, 'on_field': 11, 'sort': 12},
    '14UB Boys':   {'roster_size': 18, 'on_field': 11, 'sort': 13},
    '14UG Girls':  {'roster_size': 18, 'on_field': 11, 'sort': 14},
    '16UB Boys':   {'roster_size': 18, 'on_field': 11, 'sort': 15},
    '16UG Girls':  {'roster_size': 18, 'on_field': 11, 'sort': 16},
    '19UC Co-ed':  {'roster_size': 18, 'on_field': 11, 'sort': 17},
}


class PlayMetricsSheetsPublisher:
    """Publishes PlayMetrics enrollment data from packages JSON to Google Sheets."""

    # Column headers for the "Current" sheet
    CURRENT_COLUMNS = [
        'Division', 'Age Group', 'Gender', 'Enrolled', 'Capacity',
        'Waitlist', '% Full', 'Available', 'Roster Size', 'Target Teams',
        'Total Revenue', 'Paid', 'Refunded', 'Outstanding', '% Collected',
        'On Field', 'Sort Order',
    ]

    # Column headers for the "History" sheet (adds Timestamp)
    HISTORY_COLUMNS = ['Timestamp'] + CURRENT_COLUMNS

    def __init__(self, config=None):
        """
        Args:
            config: ConfigManager instance (optional).
                    Uses paths.data_dir for file discovery,
                    google_sheets.spreadsheet_id for the target sheet,
                    google_sheets.service_account_file for auth.
        """
        self.config = config

        # Paths
        if config:
            data_dir = config.get('paths.data_dir', 'data')
            self.service_account_file = config.get(
                'google_sheets.service_account_file',
                'kinetic-cosmos-469504-f4-f9182e88bc72.json'
            )
            self.spreadsheet_id = config.get(
                'google_sheets.spreadsheet_id', None
            )
        else:
            data_dir = 'data'
            self.service_account_file = 'kinetic-cosmos-469504-f4-f9182e88bc72.json'
            self.spreadsheet_id = None

        self.packages_dir = Path(data_dir) / 'playmetrics'

    # ─────────────────────────────────────────────────────────
    #  PUBLIC: push_to_google_sheets
    # ─────────────────────────────────────────────────────────

    def push_to_google_sheets(
        self,
        packages_file: str = None,
        spreadsheet_id: str = None,
        include_history: bool = True,
    ) -> bool:
        """
        Read packages JSON → build flat table → push to Google Sheets.

        Args:
            packages_file: Path to packages_*.json (auto-detects latest if None)
            spreadsheet_id: Google Sheet ID (falls back to config or env var)
            include_history: If True, also append timestamped rows to "History" sheet

        Returns:
            True on success, False on failure
        """
        try:
            # 1. Resolve packages file
            packages_file = packages_file or self._find_latest_packages()
            if not packages_file:
                logger.error("No packages JSON found in %s", self.packages_dir)
                return False

            logger.info("Reading packages from: %s", packages_file)
            with open(packages_file, 'r', encoding='utf-8') as f:
                packages_data = json.load(f)

            # 2. Build flat rows
            rows = self._build_flat_rows(packages_data)
            if not rows:
                logger.error("No rows generated from packages data")
                return False

            logger.info("Built %d division rows", len(rows))

            # 3. Connect to Google Sheets
            sheet_id = spreadsheet_id or self.spreadsheet_id or os.environ.get(
                'PM_DASHBOARD_SHEET_ID'
            )
            if not sheet_id:
                logger.error(
                    "No spreadsheet ID provided. Set via --sheet-id, config, "
                    "or PM_DASHBOARD_SHEET_ID env var."
                )
                return False

            gc = self._get_gspread_client()
            spreadsheet = gc.open_by_key(sheet_id)

            # 4. Write "Current" sheet (overwrite)
            self._write_current_sheet(spreadsheet, rows)

            # 5. Append to "History" sheet
            if include_history:
                timestamp = packages_data.get(
                    'scraped_at',
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
                self._append_history_sheet(spreadsheet, rows, timestamp)

            logger.info("Successfully pushed to Google Sheet: %s", sheet_id)
            return True

        except Exception as e:
            logger.error("Failed to push to Google Sheets: %s", e)
            import traceback
            traceback.print_exc()
            return False

    # ─────────────────────────────────────────────────────────
    #  DATA TRANSFORMATION
    # ─────────────────────────────────────────────────────────

    def _build_flat_rows(self, packages_data: Dict) -> List[List[Any]]:
        """
        Transform packages JSON into flat rows for Google Sheets.

        Each row = one division with all computed fields.
        """
        packages = packages_data.get('packages', [])
        rows = []

        for pkg in packages:
            name = pkg.get('name', '')
            if not name:
                continue

            # Enrollment metrics
            enrolled = pkg.get('active_registrations', 0) or 0
            capacity = pkg.get('max_spots', 0) or 0
            waitlist = pkg.get('waitlist_count', 0) or 0
            pct_full = round((enrolled / capacity * 100), 1) if capacity > 0 else 0
            available = max(capacity - enrolled, 0)

            # Financial metrics
            fin = pkg.get('financials', {})
            total_rev = fin.get('total', 0) or 0
            paid = fin.get('paid', 0) or 0
            refunded = fin.get('refunded', 0) or 0
            outstanding = fin.get('outstanding', 0) or 0
            pct_collected = round((paid / total_rev * 100), 1) if total_rev > 0 else 0

            # Division config lookup
            div_config = DIVISION_CONFIG.get(name, {})
            roster_size = div_config.get('roster_size', 12)
            on_field = div_config.get('on_field', 0)
            sort_order = div_config.get('sort', 99)
            target_teams = math.ceil(enrolled / roster_size) if roster_size > 0 else 0

            # Derived fields
            age_group = self._extract_age_group(name)
            gender = self._extract_gender(name)

            rows.append([
                name,           # Division
                age_group,      # Age Group
                gender,         # Gender
                enrolled,       # Enrolled
                capacity,       # Capacity
                waitlist,       # Waitlist
                pct_full,       # % Full
                available,      # Available
                roster_size,    # Roster Size
                target_teams,   # Target Teams
                total_rev,      # Total Revenue
                paid,           # Paid
                refunded,       # Refunded
                outstanding,    # Outstanding
                pct_collected,  # % Collected
                on_field,       # On Field
                sort_order,     # Sort Order
            ])

        # Sort by division sort order
        rows.sort(key=lambda r: r[-1])  # sort_order is last column
        return rows

    @staticmethod
    def _extract_age_group(division_name: str) -> str:
        """'06UB Boys' → 'U6', '10UG Girls' → 'U10', '04UC Co-ed' → 'U4'"""
        if len(division_name) < 3:
            return ''
        num_part = division_name[:2]
        if num_part.isdigit():
            return f"U{int(num_part)}"
        return ''

    @staticmethod
    def _extract_gender(division_name: str) -> str:
        """'06UB Boys' → 'Boys', '10UG Girls' → 'Girls', '04UC Co-ed' → 'Co-ed'"""
        if len(division_name) < 4:
            return ''
        code = division_name[3].upper()
        if code == 'B':
            return 'Boys'
        elif code == 'G':
            return 'Girls'
        elif code == 'C':
            return 'Co-ed'
        return ''

    # ─────────────────────────────────────────────────────────
    #  GOOGLE SHEETS I/O
    # ─────────────────────────────────────────────────────────

    def _get_gspread_client(self):
        """Authenticate with Google Sheets via service account."""
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
        ]

        # Look for service account key in several locations
        key_paths = [
            self.service_account_file,
            Path('config') / self.service_account_file,
            Path.home() / '.config' / self.service_account_file,
        ]

        key_path = None
        for p in key_paths:
            if Path(p).exists():
                key_path = str(p)
                break

        if not key_path:
            raise FileNotFoundError(
                f"Service account key not found. Searched: {key_paths}"
            )

        logger.info("Using service account: %s", key_path)
        creds = Credentials.from_service_account_file(key_path, scopes=scopes)
        return gspread.authorize(creds)

    def _write_current_sheet(self, spreadsheet, rows: List[List[Any]]):
        """Overwrite the 'Current' sheet with latest data + totals row."""
        try:
            ws = spreadsheet.worksheet('Current')
        except Exception:
            ws = spreadsheet.add_worksheet(
                title='Current', rows=len(rows) + 5, cols=len(self.CURRENT_COLUMNS)
            )

        # Clear existing data
        ws.clear()

        # Build data: header + rows + totals
        all_data = [self.CURRENT_COLUMNS]
        all_data.extend(rows)

        # Totals row
        totals = self._compute_totals(rows)
        all_data.append(totals)

        # Batch update (single API call)
        ws.update(
            range_name='A1',
            values=all_data,
            value_input_option='USER_ENTERED',
        )

        # Format header row
        ws.format('A1:Q1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.15, 'green': 0.25, 'blue': 0.45},
            'horizontalAlignment': 'CENTER',
            'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
        })

        # Format totals row
        totals_row = len(rows) + 2  # +1 for header, +1 for 1-indexed
        ws.format(f'A{totals_row}:Q{totals_row}', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9},
        })

        # Freeze header
        ws.freeze(rows=1, cols=1)

        logger.info("Updated 'Current' sheet: %d divisions + totals", len(rows))

    def _append_history_sheet(
        self, spreadsheet, rows: List[List[Any]], timestamp: str
    ):
        """Append timestamped rows to the 'History' sheet."""
        try:
            ws = spreadsheet.worksheet('History')
        except Exception:
            ws = spreadsheet.add_worksheet(
                title='History', rows=1000, cols=len(self.HISTORY_COLUMNS)
            )
            # Write header on first creation
            ws.update(
                range_name='A1',
                values=[self.HISTORY_COLUMNS],
                value_input_option='USER_ENTERED',
            )
            ws.format('A1:R1', {
                'textFormat': {'bold': True},
                'backgroundColor': {'red': 0.15, 'green': 0.25, 'blue': 0.45},
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            })
            ws.freeze(rows=1, cols=2)

        # Prepend timestamp to each row
        history_rows = [[timestamp] + row for row in rows]

        # Append (doesn't overwrite existing data)
        ws.append_rows(
            history_rows,
            value_input_option='USER_ENTERED',
            insert_data_option='INSERT_ROWS',
        )

        logger.info(
            "Appended %d rows to 'History' sheet (timestamp: %s)",
            len(history_rows), timestamp
        )

    @staticmethod
    def _compute_totals(rows: List[List[Any]]) -> List[Any]:
        """Compute totals row for numeric columns."""
        if not rows:
            return []

        # Column indices: 3=Enrolled, 4=Capacity, 5=Waitlist, 7=Available,
        # 9=Target Teams, 10=Total Rev, 11=Paid, 12=Refunded, 13=Outstanding
        numeric_sum_cols = [3, 4, 5, 7, 9, 10, 11, 12, 13]

        totals = ['TOTAL', '', '', ]  # Division, Age Group, Gender
        for col_idx in range(3, len(rows[0])):
            if col_idx in numeric_sum_cols:
                totals.append(sum(r[col_idx] for r in rows))
            elif col_idx == 6:  # % Full — recompute from totals
                total_enrolled = sum(r[3] for r in rows)
                total_capacity = sum(r[4] for r in rows)
                totals.append(
                    round(total_enrolled / total_capacity * 100, 1)
                    if total_capacity > 0 else 0
                )
            elif col_idx == 14:  # % Collected — recompute from totals
                total_rev = sum(r[10] for r in rows)
                total_paid = sum(r[11] for r in rows)
                totals.append(
                    round(total_paid / total_rev * 100, 1)
                    if total_rev > 0 else 0
                )
            else:
                totals.append('')  # non-summable columns

        return totals

    # ─────────────────────────────────────────────────────────
    #  FILE HELPERS
    # ─────────────────────────────────────────────────────────

    def _find_latest_packages(self) -> Optional[str]:
        """Find the most recent packages_*.json in the data directory."""
        pattern = str(self.packages_dir / 'packages_*.json')
        matches = glob.glob(pattern)
        if not matches:
            # Also check data/ root
            alt_pattern = str(Path(self.packages_dir).parent / 'packages_*.json')
            matches = glob.glob(alt_pattern)
        if matches:
            return max(matches, key=os.path.getmtime)
        return None


# ─────────────────────────────────────────────────────────────
#  STANDALONE USAGE
# ─────────────────────────────────────────────────────────────

def main():
    """CLI entry point for standalone testing."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
    )

    parser = argparse.ArgumentParser(
        description='Push PlayMetrics enrollment data to Google Sheets'
    )
    parser.add_argument(
        '--packages-file',
        help='Path to packages_*.json (auto-detects latest)',
    )
    parser.add_argument(
        '--sheet-id',
        help='Google Sheet spreadsheet ID',
    )
    parser.add_argument(
        '--no-history',
        action='store_true',
        help='Skip appending to History sheet',
    )
    parser.add_argument(
        '--service-account',
        default='kinetic-cosmos-469504-f4-f9182e88bc72.json',
        help='Path to service account key JSON',
    )

    args = parser.parse_args()

    publisher = PlayMetricsSheetsPublisher()
    publisher.service_account_file = args.service_account

    success = publisher.push_to_google_sheets(
        packages_file=args.packages_file,
        spreadsheet_id=args.sheet_id,
        include_history=not args.no_history,
    )

    if success:
        print("✅ Dashboard data pushed to Google Sheets")
    else:
        print("❌ Failed to push data. Check logs above.")
        exit(1)


if __name__ == '__main__':
    main()
