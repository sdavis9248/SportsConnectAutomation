"""
PlayMetrics Export Manager for Sports Connect Automation
Transforms SportsConnect Enrollment_Details data into PlayMetrics import CSV format.

Supports player, coach, and game exports matching PlayMetrics bulk import templates.
Ported from Access VBA module (Playmetrics.bas) to Python.
"""
import os
import re
import csv
import glob
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class PlayMetricsExportManager:
    """Manages export of SportsConnect data to PlayMetrics CSV import format"""

    # PlayMetrics player CSV column order (must match their import template)
    PLAYER_CSV_COLUMNS = [
        'team', 'season_id', 'season', 'player_first_name', 'player_last_name',
        'gender', 'birth_date', 'age_group', 'position', 'number', 'Foot',
        'parent1_email', 'parent1_first_name', 'parent1_last_name', 'parent1_mobile_number',
        'parent2_email', 'parent2_first_name', 'parent2_last_name', 'parent2_mobile_number',
        'street', 'city', 'state', 'zip'
    ]

    # PlayMetrics coach CSV column order
    COACH_CSV_COLUMNS = [
        'season', 'name', 'acct_code', 'gender', 'level', 'birth_year',
        'age_group', 'coach_first_name', 'coach_last_name', 'coach_email',
        'coach_mobile', 'num_players', 'num_starting_players'
    ]

    # PlayMetrics game CSV column order
    GAME_CSV_COLUMNS = [
        'Date', 'Start Time', 'Game Duration (in minutes)', 'Field Name',
        'Division Name', 'Home Team Name', 'Home Team Score',
        'Away Team Name', 'Away Team Score', 'External Game ID'
    ]

    def __init__(self, config=None):
        """
        Initialize PlayMetrics Export Manager

        Args:
            config: ConfigManager instance (uses season/program_name, paths)
        """
        self.config = config
        self.season_name = config.get('season', '2025 Fall Core') if config else '2025 Fall Core'
        self.program_name = config.get('program_name', '2025 Fall Core') if config else '2025 Fall Core'

        # Output directory
        if config:
            data_dir = config.get('paths.data_dir', 'data')
        else:
            data_dir = 'data'
        self.output_dir = Path(data_dir) / 'playmetrics'
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================
    #  PLAYER EXPORT
    # =========================================================

    def export_players(self,
                       enrollment_file: str = None,
                       output_file: str = None,
                       program_filter: str = None,
                       exclude_unallocated: bool = False,
                       exclude_jamboree: bool = True) -> Optional[str]:
        """
        Export players from Enrollment_Details to PlayMetrics CSV format.

        Args:
            enrollment_file: Path to Enrollment_Details Excel file (auto-detected if None)
            output_file: Output CSV path (auto-generated if None)
            program_filter: Program name to filter on (defaults to config season)
            exclude_unallocated: If True, skip players with 'Unallocated' team
            exclude_jamboree: If True, skip Jamboree division players

        Returns:
            Path to generated CSV file, or None on failure
        """
        try:
            # Find enrollment file
            enrollment_file = enrollment_file or self._find_enrollment_file()
            if not enrollment_file:
                logger.error("No Enrollment_Details file found")
                return None

            logger.info(f"Reading enrollment data from: {enrollment_file}")
            df = pd.read_excel(enrollment_file)
            logger.info(f"Loaded {len(df)} enrollment records")

            # Filter by program
            program = program_filter or self.program_name
            if program and 'Program Name' in df.columns:
                df = df[df['Program Name'] == program]
                logger.info(f"Filtered to program '{program}': {len(df)} records")

            if df.empty:
                logger.warning("No records after filtering")
                return None

            # Exclude Jamboree division
            if exclude_jamboree and 'Division Name' in df.columns:
                pre_count = len(df)
                df = df[~df['Division Name'].str.contains('Jamboree', case=False, na=False)]
                excluded = pre_count - len(df)
                if excluded > 0:
                    logger.info(f"Excluded {excluded} Jamboree players")

            # Exclude Unallocated teams if requested
            if exclude_unallocated and 'Team Name' in df.columns:
                pre_count = len(df)
                df = df[df['Team Name'].str.upper() != 'UNALLOCATED']
                excluded = pre_count - len(df)
                if excluded > 0:
                    logger.info(f"Excluded {excluded} Unallocated players")

            # De-duplicate (same logic as Access VBA DISTINCT)
            dedup_cols = ['Player First Name', 'Player Last Name', 'Birth Date Time Stamp', 'Team Name']
            available_dedup = [c for c in dedup_cols if c in df.columns]
            if available_dedup:
                pre_count = len(df)
                df = df.drop_duplicates(subset=available_dedup)
                dupes = pre_count - len(df)
                if dupes > 0:
                    logger.info(f"Removed {dupes} duplicate records")

            # Build PlayMetrics rows
            rows = []
            for _, record in df.iterrows():
                row = self._build_player_row(record)
                rows.append(row)

            # Sort by last name, first name
            rows.sort(key=lambda r: (r['player_last_name'].lower(), r['player_first_name'].lower()))

            # Write CSV
            output_file = output_file or self._generate_output_path('playmetrics_players')
            self._write_csv(output_file, self.PLAYER_CSV_COLUMNS, rows)

            logger.info(f"Player export complete: {len(rows)} records -> {output_file}")
            return output_file

        except Exception as e:
            logger.error(f"Error exporting players: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _build_player_row(self, record: pd.Series) -> Dict[str, str]:
        """Build a single PlayMetrics player CSV row from an enrollment record"""
        team_name = self._normalize_team_name(str(record.get('Team Name', '') or ''))
        division_name = str(record.get('Division Name', '') or '')
        gender = self._derive_gender_from_division(division_name)
        birth_date = self._format_birth_date(record.get('Birth Date Time Stamp'))

        # Parent phone: prefer Cellphone, fall back to Telephone
        cellphone = str(record.get('Cellphone', '') or '')
        telephone = str(record.get('Telephone', '') or '')
        parent_phone = self._format_phone(cellphone if cellphone.strip() else telephone)

        return {
            'team': team_name,
            'season_id': '',
            'season': self.season_name,
            'player_first_name': str(record.get('Player First Name', '') or '').strip(),
            'player_last_name': str(record.get('Player Last Name', '') or '').strip(),
            'gender': gender,
            'birth_date': birth_date,
            'age_group': '',
            'position': '',
            'number': '',
            'Foot': '',
            'parent1_email': str(record.get('User Email', '') or '').strip(),
            'parent1_first_name': str(record.get('Account First Name', '') or '').strip(),
            'parent1_last_name': str(record.get('Account Last Name', '') or '').strip(),
            'parent1_mobile_number': parent_phone,
            'parent2_email': '',
            'parent2_first_name': '',
            'parent2_last_name': '',
            'parent2_mobile_number': '',
            'street': '',
            'city': '',
            'state': '',
            'zip': ''
        }

    # =========================================================
    #  COACH EXPORT
    # =========================================================

    # Team Info source: SportsConnect saved report 65588
    # URL: https://reporting.bluesombrero.com/{org_id}/admin/saved/65588
    # Can be downloaded via: python main.py TEAM_INFO
    # IMPORTANT: The browser saves this as "Volunteer_Details - <timestamp>.xlsx"
    # which is the SAME prefix as the Volunteer_Details report (saved/173209).
    # To avoid ambiguity, always use --team-info-file to specify the exact path.
    # Auto-detection will pick the most recent Volunteer_Details file, which
    # may be wrong if both reports have been downloaded.
    TEAM_INFO_REPORT_ID = "65588"
    TEAM_INFO_FILE_PATTERNS = [
        'TeamInfo*.xlsx',           # manually renamed
        'tbl_TeamInfo*.xlsx',       # Access export legacy name
        'Volunteer_Details*.xlsx',  # browser download name (ambiguous!)
    ]

    def export_coaches(self,
                       team_info_file: str = None,
                       volunteer_details_file: str = None,
                       output_file: str = None,
                       program_filter: str = None,
                       automation=None) -> Optional[str]:
        """
        Export coaches to PlayMetrics CSV format.

        Requires team info (saved report 65588) and volunteer contact details.
        Can optionally accept an authenticated automation instance to download
        the team info report automatically.

        Args:
            team_info_file: Path to team info Excel file (auto-detected if None)
            volunteer_details_file: Path to Volunteer_Details Excel file (auto-detected if None)
            output_file: Output CSV path (auto-generated if None)
            program_filter: Program name filter (defaults to config season)
            automation: Optional SportsConnectAutomation instance for downloading
                        team info report if not already on disk

        Returns:
            Path to generated CSV file, or None on failure
        """
        try:
            # Find volunteer details
            volunteer_details_file = volunteer_details_file or self._find_file('Volunteer_Details*.xlsx')
            if not volunteer_details_file:
                logger.error("No Volunteer_Details file found")
                logger.info("  Download first: python main.py VOLUNTEER_DETAIL")
                return None

            # Find team info file - try multiple patterns
            if not team_info_file:
                for pattern in self.TEAM_INFO_FILE_PATTERNS:
                    team_info_file = self._find_file(pattern)
                    if team_info_file:
                        break

            # If still not found, try downloading via automation
            if not team_info_file and automation:
                team_info_file = self._download_team_info_report(automation)

            if not team_info_file:
                logger.error("No team info file found.")
                logger.info(f"  Download saved report 65588 from SportsConnect:")
                logger.info(f"  python main.py TEAM_INFO")
                logger.info(f"  Or provide the file: --playmetrics-coaches --team-info-file path/to/file.xlsx")
                return None

            logger.info(f"Reading team info from: {team_info_file}")
            teams_df = pd.read_excel(team_info_file)
            logger.info(f"Loaded {len(teams_df)} team info records, columns: {list(teams_df.columns)}")

            logger.info(f"Reading volunteer details from: {volunteer_details_file}")
            volunteers_df = pd.read_excel(volunteer_details_file)

            # Filter to program and Head Coach role
            program = program_filter or self.program_name
            if 'Program Name' in teams_df.columns:
                teams_df = teams_df[teams_df['Program Name'] == program]
                logger.info(f"Filtered to program '{program}': {len(teams_df)} records")
            if 'Volunteer Role' in teams_df.columns:
                teams_df = teams_df[teams_df['Volunteer Role'] == 'Head Coach']
                logger.info(f"Filtered to Head Coach: {len(teams_df)} records")
            if 'Team Name' in teams_df.columns:
                teams_df = teams_df[~teams_df['Team Name'].str.upper().isin(['UNALLOCATED', ''])]

            if teams_df.empty:
                logger.warning("No head coach records found after filtering")
                return None

            # Join volunteer contact info (email, phone)
            # Team info has 'Volunteer ID', Volunteer_Details has 'Volunteer Id'
            vol_id_col_teams = self._find_column(teams_df, ['Volunteer ID', 'Volunteer Id', 'VolunteerID'])
            vol_id_col_vols = self._find_column(volunteers_df, ['Volunteer Id', 'Volunteer ID', 'VolunteerID'])

            if vol_id_col_teams and vol_id_col_vols:
                # Select relevant volunteer columns
                vol_cols = [vol_id_col_vols]
                for col in ['Volunteer Email Address', 'Volunteer Cellphone', 'Volunteer Phone']:
                    if col in volunteers_df.columns:
                        vol_cols.append(col)

                merged = teams_df.merge(
                    volunteers_df[vol_cols].drop_duplicates(subset=[vol_id_col_vols]),
                    left_on=vol_id_col_teams, right_on=vol_id_col_vols, how='left'
                )
                logger.info(f"Joined volunteer contact info: {len(merged)} records")
            else:
                logger.warning(f"Cannot join team/volunteer data - volunteer ID column not found")
                logger.info(f"  Team info columns: {list(teams_df.columns)}")
                logger.info(f"  Volunteer columns: {list(volunteers_df.columns)}")
                merged = teams_df

            rows = []
            for _, rec in merged.iterrows():
                division = str(rec.get('Division Name', '') or '')
                team_name = self._normalize_team_name(str(rec.get('Team Name', '') or ''))
                if not team_name:
                    continue

                # Find email - try multiple possible column names
                coach_email = ''
                for col in ['Volunteer Email Address', 'Volunteer Email', 'Email']:
                    val = rec.get(col)
                    if val and not pd.isna(val):
                        coach_email = str(val).strip()
                        break

                # Find phone
                coach_phone = ''
                for col in ['Volunteer Cellphone', 'Volunteer Phone', 'Cellphone']:
                    val = rec.get(col)
                    if val and not pd.isna(val):
                        coach_phone = self._format_phone(str(val))
                        break

                rows.append({
                    'season': self.season_name,
                    'name': team_name,
                    'acct_code': '',
                    'gender': self._derive_gender_from_division(division),
                    'level': 'Classic',
                    'birth_year': '',
                    'age_group': self._division_to_age_group(division),
                    'coach_first_name': str(rec.get('Volunteer First Name', '') or '').strip(),
                    'coach_last_name': str(rec.get('Volunteer Last Name', '') or '').strip(),
                    'coach_email': coach_email,
                    'coach_mobile': coach_phone,
                    'num_players': '',
                    'num_starting_players': ''
                })

            rows.sort(key=lambda r: (r['age_group'], r['name'], r['coach_last_name']))

            output_file = output_file or self._generate_output_path('playmetrics_coaches')
            self._write_csv(output_file, self.COACH_CSV_COLUMNS, rows)

            logger.info(f"Coach export complete: {len(rows)} records -> {output_file}")
            return output_file

        except Exception as e:
            logger.error(f"Error exporting coaches: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _download_team_info_report(self, automation) -> Optional[str]:
        """
        Download team info saved report (65588) using an authenticated automation instance.

        Args:
            automation: Authenticated SportsConnectAutomation instance

        Returns:
            Path to downloaded file, or None
        """
        try:
            from automation.report_handlers import ReportType
            logger.info("Downloading Team Info report (saved/65588)...")
            # Use the TEAM_INFO report type if registered, otherwise
            # navigate directly to the saved report URL
            if hasattr(ReportType, 'TEAM_INFO'):
                return automation.export_report(ReportType.TEAM_INFO)
            else:
                # Direct download using existing saved report mechanism
                base_url = self.config.get('base_url', 'https://reporting.bluesombrero.com')
                org_id = self.config.get('organization_id', '14780')
                url = f"{base_url}/{org_id}/admin/saved/{self.TEAM_INFO_REPORT_ID}"
                logger.info(f"Navigating to saved report: {url}")
                automation.driver.get(url)
                import time
                time.sleep(5)
                # Trigger export using the automation's existing methods
                automation._click_export_button(None)
                automation._select_excel_format()
                time.sleep(automation.config.get('download_delay', 10))
                return automation._find_latest_download('Volunteer_Details')
        except Exception as e:
            logger.error(f"Failed to download team info report: {e}")
            return None

    # =========================================================
    #  SUMMARY / PREVIEW
    # =========================================================

    def preview_export(self, enrollment_file: str = None, program_filter: str = None) -> Dict[str, Any]:
        """
        Preview what would be exported without writing a file.

        Returns:
            Summary dict with counts by division, team allocation stats, etc.
        """
        try:
            enrollment_file = enrollment_file or self._find_enrollment_file()
            if not enrollment_file:
                return {'error': 'No Enrollment_Details file found'}

            df = pd.read_excel(enrollment_file)

            program = program_filter or self.program_name
            if program and 'Program Name' in df.columns:
                df = df[df['Program Name'] == program]

            summary = {
                'file': enrollment_file,
                'program': program,
                'total_records': len(df),
                'divisions': {},
                'unallocated_count': 0,
                'jamboree_count': 0,
                'allocated_count': 0
            }

            if 'Division Name' in df.columns:
                for div, group in df.groupby('Division Name'):
                    div_str = str(div)
                    team_counts = {}
                    unalloc = 0
                    if 'Team Name' in group.columns:
                        for team, tgroup in group.groupby('Team Name'):
                            team_str = str(team)
                            if team_str.upper() == 'UNALLOCATED':
                                unalloc = len(tgroup)
                            else:
                                team_counts[team_str] = len(tgroup)

                    is_jamboree = 'jamboree' in div_str.lower()
                    summary['divisions'][div_str] = {
                        'total': len(group),
                        'allocated': len(group) - unalloc,
                        'unallocated': unalloc,
                        'teams': team_counts,
                        'is_jamboree': is_jamboree
                    }
                    summary['unallocated_count'] += unalloc
                    if is_jamboree:
                        summary['jamboree_count'] += len(group)

            summary['allocated_count'] = summary['total_records'] - summary['unallocated_count']

            return summary

        except Exception as e:
            logger.error(f"Error generating preview: {e}")
            return {'error': str(e)}

    # =========================================================
    #  DATA TRANSFORMATION HELPERS
    # =========================================================

    @staticmethod
    def _normalize_team_name(team_name: str) -> str:
        """Normalize team name: blank out Unallocated and Jamboree teams"""
        team_name = team_name.strip()
        if not team_name:
            return ''
        if team_name.upper() == 'UNALLOCATED':
            return ''
        if 'jamboree' in team_name.lower():
            return ''
        return team_name

    @staticmethod
    def _derive_gender_from_division(division_name: str) -> str:
        """
        Derive gender from AYSO division name format.
        E.g., '10UB - Boys...' -> 'M', '10UG - Girls...' -> 'F'
        The 4th character (index 3) is B=Boys or G=Girls.
        """
        if len(division_name) < 4:
            return ''
        code = division_name[3].upper()
        if code == 'B':
            return 'M'
        elif code == 'G':
            return 'F'
        return ''

    @staticmethod
    def _division_to_age_group(division_name: str) -> str:
        """
        Extract age group from division name.
        E.g., '06UB - Boys...' -> 'U6', '10UG - Girls...' -> 'U10'
        """
        if len(division_name) < 3:
            return ''
        num_part = division_name[:2]
        if num_part.isdigit():
            return f"U{int(num_part)}"
        return ''

    @staticmethod
    def _format_birth_date(value) -> str:
        """Format birth date to MM/DD/YYYY for PlayMetrics import"""
        if pd.isna(value) or value is None:
            return ''
        try:
            if isinstance(value, datetime):
                return value.strftime('%m/%d/%Y')
            if isinstance(value, str):
                # Try common formats
                for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y'):
                    try:
                        dt = datetime.strptime(value.strip(), fmt)
                        return dt.strftime('%m/%d/%Y')
                    except ValueError:
                        continue
            # pandas Timestamp
            ts = pd.Timestamp(value)
            if not pd.isna(ts):
                return ts.strftime('%m/%d/%Y')
        except Exception:
            pass
        return ''

    @staticmethod
    def _format_phone(phone: str) -> str:
        """
        Normalize phone to 10-digit format.
        Strips all non-digit chars, removes leading '1' country code.
        """
        if not phone or pd.isna(phone):
            return ''
        phone = str(phone).strip()
        # Extract digits only
        digits = re.sub(r'\D', '', phone)
        # Remove leading country code
        if len(digits) == 11 and digits.startswith('1'):
            digits = digits[1:]
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        # Return original if not standard 10-digit
        return phone if phone else ''

    # =========================================================
    #  FILE I/O HELPERS
    # =========================================================

    def _find_enrollment_file(self) -> Optional[str]:
        """Auto-detect latest Enrollment_Details file in data directory"""
        return self._find_file('Enrollment_Details*.xlsx')

    @staticmethod
    def _find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        """Find the first matching column name from a list of candidates"""
        for col in candidates:
            if col in df.columns:
                return col
        return None

    def _find_file(self, pattern: str) -> Optional[str]:
        """Find the most recent file matching a glob pattern"""
        search_dirs = []
        if self.config:
            data_dir = self.config.get('paths.data_dir', 'data')
            download_dir = self.config.get('paths.download_dir', 'data/downloads')
            search_dirs.append(download_dir)
            search_dirs.append(data_dir)
        else:
            search_dirs.extend(['data/downloads', 'data'])
        # Current directory as last resort
        search_dirs.append('.')

        for search_dir in search_dirs:
            matches = glob.glob(os.path.join(search_dir, pattern))
            if matches:
                # Return most recently modified
                return max(matches, key=os.path.getmtime)
        return None

    def _generate_output_path(self, base_name: str) -> str:
        """Generate timestamped output file path"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{base_name}_{timestamp}.csv"
        return str(self.output_dir / filename)

    @staticmethod
    def _write_csv(filepath: str, columns: List[str], rows: List[Dict[str, str]]):
        """Write rows to CSV with proper quoting"""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)

    # =========================================================
    #  DISPLAY HELPERS
    # =========================================================

    @staticmethod
    def format_preview_report(summary: Dict[str, Any]) -> str:
        """Format preview summary for console display"""
        if 'error' in summary:
            return f"Error: {summary['error']}"

        lines = [
            "PlayMetrics Player Export Preview",
            "=" * 50,
            f"Source file: {summary['file']}",
            f"Program: {summary['program']}",
            f"Total records: {summary['total_records']}",
            f"Allocated to teams: {summary['allocated_count']}",
            f"Unallocated: {summary['unallocated_count']}",
            f"Jamboree: {summary['jamboree_count']}",
            "",
            "Division Breakdown:",
            "-" * 50
        ]

        for div_name, div_info in sorted(summary.get('divisions', {}).items()):
            marker = " [Jamboree]" if div_info.get('is_jamboree') else ""
            lines.append(f"  {div_name}{marker}")
            lines.append(f"    Total: {div_info['total']}  "
                         f"(Allocated: {div_info['allocated']}, "
                         f"Unallocated: {div_info['unallocated']})")
            if div_info.get('teams'):
                for team, count in sorted(div_info['teams'].items()):
                    lines.append(f"      {team}: {count}")

        return '\n'.join(lines)