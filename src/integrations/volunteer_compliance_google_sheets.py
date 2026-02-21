"""
Volunteer Compliance Google Sheets Automation
This script automates updating volunteer compliance data in Google Sheets
with better collaboration features and real-time updates.
Save this file as: integrations/volunteer_compliance_google_sheets.py
"""

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime
import logging
from pathlib import Path
from typing import List, Dict, Any

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VolunteerComplianceGoogleSheets:
    def __init__(self, credentials_file: str, spreadsheet_id: str = None):
        """
        Initialize Google Sheets API client
        
        Args:
            credentials_file: Path to Google credentials JSON (service account or OAuth 2.0)
            spreadsheet_id: ID of existing spreadsheet (None to create new)
        """
        import json
        import os
        from pathlib import Path
        
        # Read the credentials file to determine the type
        with open(credentials_file, 'r') as f:
            creds_data = json.load(f)
        
        # Check if it's a service account or OAuth 2.0 credentials
        if 'type' in creds_data and creds_data['type'] == 'service_account':
            # Service account authentication
            from google.oauth2 import service_account
            self.creds = service_account.Credentials.from_service_account_file(
                credentials_file,
                scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
        elif 'web' in creds_data or 'installed' in creds_data:
            # OAuth 2.0 authentication
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            
            SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
            
            creds = None
            token_file = 'token.json'
            
            # Load existing token if available
            if os.path.exists(token_file):
                creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            
            # If there are no (valid) credentials available, let the user log in
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                    creds = flow.run_local_server(port=0)
                # Save the credentials for the next run
                with open(token_file, 'w') as token:
                    token.write(creds.to_json())
            
            self.creds = creds
        else:
            raise ValueError(f"Unsupported credentials format in {credentials_file}")
        
        # Build the service with the appropriate credentials
        from googleapiclient.discovery import build
        self.service = build('sheets', 'v4', credentials=self.creds)
        self.sheets_api = self.service.spreadsheets()
        
        if spreadsheet_id:
            self.spreadsheet_id = spreadsheet_id
        else:
            self.spreadsheet_id = self._create_new_spreadsheet()

    def _calculate_age(self, dob, reference_date=None):
        """Calculate age from DOB"""
        from datetime import date
    
        if reference_date is None:
            reference_date = date.today()
    
        if pd.isna(dob):
            return None
        
        # Handle different date formats
        if isinstance(dob, str):
            try:
                dob = pd.to_datetime(dob).date()
            except:
                return None
        elif isinstance(dob, (pd.Timestamp, datetime)):
            dob = dob.date()
        elif isinstance(dob, (int, float)):
            # Excel serial date
            try:
                dob = pd.to_datetime(dob, unit='D', origin='1899-12-30').date()
            except:
                return None
    
        age = reference_date.year - dob.year
        if reference_date.month < dob.month or (reference_date.month == dob.month and reference_date.day < dob.day):
            age -= 1
    
        return age
            
    def _create_new_spreadsheet(self) -> str:
        """Create a new Google Sheets spreadsheet"""
        spreadsheet = {
            'properties': {
                'title': f'Volunteer Compliance Tracking {datetime.now().year}'
            },
            'sheets': [{
                'properties': {
                    'title': 'Current Status',
                    'gridProperties': {
                        'frozenRowCount': 1
                    }
                }
            }]
        }
        
        result = self.sheets_api.create(body=spreadsheet).execute()
        spreadsheet_id = result.get('spreadsheetId')
        logger.info(f"Created new spreadsheet: {result.get('spreadsheetUrl')}")
        return spreadsheet_id
        
    def update_from_volunteer_report(self, report_path: str):
        """Update Google Sheet from downloaded volunteer report"""
        # Read the volunteer report
        logger.info(f"Reading volunteer report: {report_path}")
        df = pd.read_excel(report_path)
        
        # Prepare data for Google Sheets
        values = [df.columns.tolist()] + df.fillna('').values.tolist()
        
        if 'DOB' in df.columns and 'Volunteer Role' in df.columns:
            logger.info("Checking for minor referees to update to Youth Referee...")
    
            # Count referees before update
            referee_mask = df['Volunteer Role'] == 'Referee'
            total_referees = referee_mask.sum()
    
            # Calculate ages and update minors
            minor_referees_updated = 0
            for idx, row in df[referee_mask].iterrows():
                age = self._calculate_age(row.get('DOB'))
                if age is not None and age < 18:
                    df.at[idx, 'Volunteer Role'] = 'Youth Referee'
                    minor_referees_updated += 1
                    logger.debug(f"Updated {row['Volunteer First Name']} {row['Volunteer Last Name']} (age {age}) to Youth Referee")
    
            logger.info(f"Updated {minor_referees_updated} minor referees out of {total_referees} total referees")

            # IMPORTANT: Remove DOB column before writing to Google Sheets
            logger.info("Removing DOB column from output for privacy, User ID to maintain alignment")
            df = df.drop(columns=['DOB','User Id'])

        # Create new sheet with today's date
        sheet_name = datetime.now().strftime("%m.%d.%y")
        self._create_new_sheet(sheet_name)
        
        # Update the new sheet
        range_name = f"{sheet_name}!A1"
        body = {'values': values}
        
        result = self.sheets_api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        logger.info(f"Updated {result.get('updatedCells')} cells")
        
        # Apply formatting
        self._apply_formatting(sheet_name, len(df.columns), len(df) + 1)
        
        # Update summary sheet
        self._update_summary_sheet(df)
        
    def _create_new_sheet(self, sheet_name: str):
        """Create a new sheet in the spreadsheet"""
        try:
            request = {
                'addSheet': {
                    'properties': {
                        'title': sheet_name,
                        'index': 0,  # Add at the beginning
                        'gridProperties': {
                            'frozenRowCount': 1
                        }
                    }
                }
            }
            
            self.sheets_api.batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={'requests': [request]}
            ).execute()
            
            logger.info(f"Created new sheet: {sheet_name}")
            
        except HttpError as e:
            if 'already exists' in str(e):
                logger.warning(f"Sheet {sheet_name} already exists")
            else:
                raise
                
    def _apply_formatting(self, sheet_name: str, num_cols: int, num_rows: int):
        """Apply formatting to the sheet"""
        # Get sheet ID
        sheet_metadata = self.sheets_api.get(spreadsheetId=self.spreadsheet_id).execute()
        sheet_id = None
        for sheet in sheet_metadata['sheets']:
            if sheet['properties']['title'] == sheet_name:
                sheet_id = sheet['properties']['sheetId']
                break
                
        if not sheet_id:
            logger.error(f"Sheet {sheet_name} not found")
            return
            
        requests = []
        
        # Format header row
        requests.append({
            'repeatCell': {
                'range': {
                    'sheetId': sheet_id,
                    'startRowIndex': 0,
                    'endRowIndex': 1
                },
                'cell': {
                    'userEnteredFormat': {
                        'backgroundColor': {'red': 0.85, 'green': 0.88, 'blue': 0.95},
                        'textFormat': {'bold': True},
                        'horizontalAlignment': 'CENTER'
                    }
                },
                'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
            }
        })
        
        # Auto-resize columns
        requests.append({
            'autoResizeDimensions': {
                'dimensions': {
                    'sheetId': sheet_id,
                    'dimension': 'COLUMNS',
                    'startIndex': 0,
                    'endIndex': num_cols
                }
            }
        })
        
        # Apply conditional formatting for compliance status
        verified_cols = self._find_verified_columns(sheet_name)
        for col_index in verified_cols:
            requests.extend(self._create_conditional_formatting_rules(sheet_id, col_index, num_rows))
            
        # Execute all formatting requests
        if requests:
            self.sheets_api.batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={'requests': requests}
            ).execute()
            
    def _find_verified_columns(self, sheet_name: str) -> List[int]:
        """Find column indices for verified status columns"""
        # Get headers
        result = self.sheets_api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{sheet_name}!1:1"
        ).execute()
        
        headers = result.get('values', [[]])[0]
        verified_cols = []
        
        for i, header in enumerate(headers):
            if 'Verified' in header and 'By' not in header and 'Date' not in header:
                verified_cols.append(i)
                
        return verified_cols
        
    def _create_conditional_formatting_rules(self, sheet_id: int, col_index: int, num_rows: int) -> List[Dict]:
        """Create conditional formatting rules for a column"""
        return [
            {
                'addConditionalFormatRule': {
                    'rule': {
                        'ranges': [{
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': col_index,
                            'endColumnIndex': col_index + 1
                        }],
                        'booleanRule': {
                            'condition': {
                                'type': 'TEXT_EQ',
                                'values': [{'userEnteredValue': 'Y'}]
                            },
                            'format': {
                                'backgroundColor': {'red': 0.78, 'green': 0.94, 'blue': 0.81}
                            }
                        }
                    }
                }
            },
            {
                'addConditionalFormatRule': {
                    'rule': {
                        'ranges': [{
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': col_index,
                            'endColumnIndex': col_index + 1
                        }],
                        'booleanRule': {
                            'condition': {
                                'type': 'TEXT_EQ',
                                'values': [{'userEnteredValue': 'N'}]
                            },
                            'format': {
                                'backgroundColor': {'red': 1.0, 'green': 0.78, 'blue': 0.81}
                            }
                        }
                    }
                }
            }
        ]
        
    def _merge_reports(self, volunteer_df: pd.DataFrame, admin_df: pd.DataFrame) -> pd.DataFrame:
        """
        Merge volunteer and admin credentials reports
        
        Args:
            volunteer_df: DataFrame from Volunteer_Details report
            admin_df: DataFrame from AdminCredentialsStatusDynamic report
            
        Returns:
            Merged DataFrame with all compliance data
        """
        # Ensure join columns are strings for proper joining
        if 'Association Volunteer ID' in volunteer_df.columns:
            volunteer_df['Association Volunteer ID'] = volunteer_df['Association Volunteer ID'].astype(str)
        else:
            logger.error("'Association Volunteer ID' column not found in volunteer report")
            return volunteer_df
            
        if 'Admin ID' in admin_df.columns:
            admin_df['Admin ID'] = admin_df['Admin ID'].astype(str)
        else:
            logger.error("'Admin ID' column not found in admin credentials report")
            return volunteer_df
        
        # Log join statistics before merge
        logger.info(f"Volunteers before merge: {len(volunteer_df)}")
        logger.info(f"Admin records before merge: {len(admin_df)}")
        
        # Select relevant columns from admin credentials report
        admin_columns = ['Admin ID']
        
        # Add credential-specific columns if they exist
        credential_columns = [
            'Admin Alt ID',
            'DOB',
            'Photo Uploaded',
            'Coaching License Level',
            'Coaching License #',
            'Coaching License Obtained',
            'Referee Grade',
            'Referee Grade Obtained',
            'Referee Grade Expire',
            'Credential Printed',
            'ID Verified',
            'ID Verified By',
            'ID Verified Date',
            'Risk Status',
            'Risk Expire Date',
            'AYSOs Safe Haven Uploaded',
            'AYSOs Safe Haven Verified',
            'AYSOs Safe Haven Verified By',
            'AYSOs Safe Haven Verified Date',
            'AYSOs Safe Haven Expire Date',
            'CA Mandated Fingerprinting Uploaded',
            'CA Mandated Fingerprinting Verified',
            'CA Mandated Fingerprinting Verified By',
            'CA Mandated Fingerprinting Verified Date',
            'CA Mandated Fingerprinting Expire Date',
            'Concussion Awareness Uploaded',
            'Concussion Awareness Verified',
            'Concussion Awareness Verified By',
            'Concussion Awareness Verified Date',
            'Concussion Awareness Expire Date',
            'SafeSport Uploaded',
            'SafeSport Verified',
            'SafeSport Verified By',
            'SafeSport Verified Date',
            'SafeSport Expire Date',
            'Sudden Cardiac Arrest Uploaded',
            'Sudden Cardiac Arrest Verified',
            'Sudden Cardiac Arrest Verified By',
            'Sudden Cardiac Arrest Verified Date',
            'Sudden Cardiac Arrest Expire Date'
        ]

        
        for col in credential_columns:
            if col in admin_df.columns:
                admin_columns.append(col)
            else:
                logger.debug(f"Column '{col}' not found in admin report")
        
        # Get subset of admin data
        admin_subset = admin_df[admin_columns].drop_duplicates(subset=['Admin ID'])
        
        # Merge on Association Volunteer ID = Admin ID
        merged_df = volunteer_df.merge(
            admin_subset,
            left_on='Association Volunteer ID',
            right_on='Admin ID',
            how='left',
            suffixes=('', '_admin')
        )
        
        # Log merge results
        volunteers_with_admin = merged_df['Admin ID'].notna().sum()
        volunteers_without_admin = merged_df['Admin ID'].isna().sum()
        logger.info(f"Merge complete: {volunteers_with_admin} volunteers have admin records, {volunteers_without_admin} do not")
        
        # Handle conflicts where columns exist in both reports
        # For Risk Status, prefer admin data if available
        if 'Risk Status_admin' in merged_df.columns and 'Risk Status' in merged_df.columns:
            merged_df['Risk Status'] = merged_df['Risk Status_admin'].fillna(merged_df['Risk Status'])
            merged_df.drop('Risk Status_admin', axis=1, inplace=True)
        
        # Handle other duplicate columns
        for col in ['ID Verified', 'ID Verified By', 'ID Verified Date']:
            if f'{col}_admin' in merged_df.columns:
                # Use admin data where available, fall back to volunteer data
                merged_df[col] = merged_df[f'{col}_admin'].fillna(merged_df[col])
                merged_df.drop(f'{col}_admin', axis=1, inplace=True)
        
        # Drop the duplicate Admin ID column if it exists
        if 'Admin ID' in merged_df.columns and 'Association Volunteer ID' in merged_df.columns:
            merged_df.drop('Admin ID', axis=1, inplace=True)
        
        # Log final column list
        logger.info(f"Final merged DataFrame has {len(merged_df.columns)} columns")
        compliance_cols = [col for col in merged_df.columns if 'Verified' in col or 'Risk' in col]
        logger.info(f"Compliance columns in merged data: {compliance_cols}")
        
        return merged_df
    
    def update_from_volunteer_report(self, volunteer_report_path: str, admin_report_path: str = None):
        """Update Google Sheet from downloaded reports"""
        # Read the volunteer report
        logger.info(f"Reading volunteer report: {volunteer_report_path}")
        volunteer_df = pd.read_excel(volunteer_report_path)
        
        # Read and merge admin report if provided
        if admin_report_path:
            logger.info(f"Reading admin credentials report: {admin_report_path}")
            admin_df = pd.read_excel(admin_report_path)
            
            # Handle Photo Uploaded column in admin_df before merging
            if 'Photo Uploaded' in admin_df.columns:
                # The column might contain Excel serial dates (numbers) or already be datetime
                # Convert numeric values to datetime, leave existing datetime as is
                def convert_photo_date(val):
                    if pd.isna(val) or val == '':
                        return pd.NaT
                    elif isinstance(val, (int, float)):
                        # Excel serial date - convert it
                        try:
                            return pd.to_datetime(val, unit='D', origin='1899-12-30')
                        except:
                            return pd.NaT
                    else:
                        # Already a datetime or string
                        return pd.to_datetime(val, errors='coerce')
                
                admin_df['Photo Uploaded'] = admin_df['Photo Uploaded'].apply(convert_photo_date)
            
            df = self._merge_reports(volunteer_df, admin_df)
        else:
            logger.info("No admin credentials report provided, using volunteer data only")
            df = volunteer_df

        if 'DOB' in df.columns and 'Volunteer Role' in df.columns:
            logger.info("Checking for minor referees to update to Youth Referee...")
    
            # Count referees before update
            referee_mask = df['Volunteer Role'] == 'Referee'
            total_referees = referee_mask.sum()
    
            # Calculate ages and update minors
            minor_referees_updated = 0
            for idx, row in df[referee_mask].iterrows():
                age = self._calculate_age(row.get('DOB'))
                if age is not None and age < 18:
                    df.at[idx, 'Volunteer Role'] = 'Youth Referee'
                    minor_referees_updated += 1
                    logger.debug(f"Updated {row['Volunteer First Name']} {row['Volunteer Last Name']} (age {age}) to Youth Referee")
    
            logger.info(f"Updated {minor_referees_updated} minor referees out of {total_referees} total referees")

            # IMPORTANT: Remove DOB column before writing to Google Sheets
            logger.info("Removing DOB column from output for privacy, User ID to maintain alignment")
            df = df.drop(columns=['DOB','User Id'])
        
        # Convert all date/datetime columns to strings for Google Sheets
        for col in df.columns:
            if df[col].dtype == 'datetime64[ns]' or 'date' in col.lower() or 'expire' in col.lower() or col == 'Photo Uploaded':
                # Convert column to string, handling different data types
                def format_date_value(x):
                    if pd.isna(x):
                        return ''
                    elif isinstance(x, str):
                        # Already a string - return as is or try to parse and reformat
                        if x == '' or x == 'NaT':
                            return ''
                        try:
                            # Try to parse and reformat
                            parsed = pd.to_datetime(x, errors='coerce')
                            return parsed.strftime('%Y-%m-%d') if pd.notna(parsed) else x
                        except:
                            return x
                    elif isinstance(x, (pd.Timestamp, datetime)):
                        # Datetime object - format it
                        return x.strftime('%Y-%m-%d')
                    else:
                        # Other types - convert to string
                        return str(x)
                
                df[col] = df[col].apply(format_date_value)
        
        # Replace any remaining NaN values with empty strings
        df = df.fillna('')
        
        # Convert to list of lists for Google Sheets API
        values = [df.columns.tolist()]
        for _, row in df.iterrows():
            row_values = []
            for val in row.values:
                if pd.isna(val):
                    row_values.append('')
                else:
                    row_values.append(str(val))
            values.append(row_values)

        # Create new sheet with today's date
        sheet_name = datetime.now().strftime("%m.%d.%y")
        self._create_new_sheet(sheet_name)
        
        # Update the new sheet
        range_name = f"{sheet_name}!A1"
        body = {'values': values}
        
        result = self.sheets_api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        logger.info(f"Updated {result.get('updatedCells')} cells")
        
        # Apply formatting
        self._apply_formatting(sheet_name, len(df.columns), len(df) + 1)
        
        # Update summary sheet
        self._update_summary_sheet(df)
        
    def _update_summary_sheet(self, df: pd.DataFrame):
        """Update or create a summary sheet with compliance statistics"""
        sheet_name = 'Compliance Summary'
        
        # Create summary sheet if it doesn't exist
        try:
            self._create_new_sheet(sheet_name)
        except:
            pass  # Sheet might already exist

        youth_referees = len(df[df['Volunteer Role'] == 'Youth Referee'])
        adult_referees = len(df[df['Volunteer Role'] == 'Referee'])

        # Calculate summary statistics
        summary_data = [
            ['Metric', 'Count', 'Percentage'],
            ['Total Volunteers', len(df), '100%'],
            ['Adult Referees', adult_referees, f"{adult_referees / len(df) * 100:.1f}%"],
            ['Youth Referees', youth_referees, f"{youth_referees / len(df) * 100:.1f}%"],
            ['ID Verified', len(df[df['ID Verified'] == 'Y']), f"{len(df[df['ID Verified'] == 'Y']) / len(df) * 100:.1f}%"],
            ['Risk Status Green', len(df[df['Risk Status'] == 'Green']), f"{len(df[df['Risk Status'] == 'Green']) / len(df) * 100:.1f}%"],
            ['Safe Haven Verified', len(df[df['AYSOs Safe Haven Verified'] == 'Y']), f"{len(df[df['AYSOs Safe Haven Verified'] == 'Y']) / len(df) * 100:.1f}%"],
            ['Fingerprinting Verified', len(df[df['CA Mandated Fingerprinting Verified'] == 'Y']), f"{len(df[df['CA Mandated Fingerprinting Verified'] == 'Y']) / len(df) * 100:.1f}%"],
            ['Concussion Training', len(df[df['Concussion Awareness Verified'] == 'Y']), f"{len(df[df['Concussion Awareness Verified'] == 'Y']) / len(df) * 100:.1f}%"],
            ['SafeSport Verified', len(df[df['SafeSport Verified'] == 'Y']), f"{len(df[df['SafeSport Verified'] == 'Y']) / len(df) * 100:.1f}%"],
            ['Cardiac Arrest Training', len(df[df['Sudden Cardiac Arrest Verified'] == 'Y']), f"{len(df[df['Sudden Cardiac Arrest Verified'] == 'Y']) / len(df) * 100:.1f}%"],
            ['', '', ''],
            ['Last Updated', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '']
        ]
        
        # Update summary sheet
        body = {'values': summary_data}
        self.sheets_api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        logger.info("Updated compliance summary")
        
    def get_spreadsheet_url(self) -> str:
        """Get the URL of the spreadsheet"""
        return f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}"


def integrate_with_sports_connect_automation():
    """
    Integration function to be called after SportsConnect downloads reports
    This can be added to the main.py workflow
    """
    import glob
    import os
    
    # Configuration
    credentials_file = "credentials.json"  # Google service account credentials
    spreadsheet_id = "1aIK_g-Q4VGcUkKwfsRzlPnHZP62yTUhdRwYXenHrFFU"  # Your Google Sheet ID
    downloads_dir = r"C:\Users\sdavis\OneDrive\AYSO\data\downloads"
    
    # Find the most recent reports
    volunteer_reports = glob.glob(os.path.join(downloads_dir, "Volunteer_Details*.xlsx"))
    admin_reports = glob.glob(os.path.join(downloads_dir, "AdminCredentialsStatusDynamic*.xlsx"))
    
    if not volunteer_reports:
        logger.error("No volunteer report found in downloads directory")
        return False
        
    # Get the most recent files
    latest_volunteer = max(volunteer_reports, key=os.path.getctime)
    latest_admin = max(admin_reports, key=os.path.getctime) if admin_reports else None
    
    logger.info(f"Using volunteer report: {latest_volunteer}")
    if latest_admin:
        logger.info(f"Using admin credentials report: {latest_admin}")
    
    # Update Google Sheets
    try:
        sheets_updater = VolunteerComplianceGoogleSheets(credentials_file, spreadsheet_id)
        sheets_updater.update_from_volunteer_report(latest_volunteer, latest_admin)
        
        logger.info(f"View updated spreadsheet at: {sheets_updater.get_spreadsheet_url()}")
        return True
        
    except Exception as e:
        logger.error(f"Error updating Google Sheets: {e}")
        return False


if __name__ == "__main__":
    # Example usage
    credentials_file = input("Enter path to Google credentials JSON: ")
    volunteer_report = input("Enter path to downloaded AllVolunteers report: ")
    admin_report = input("Enter path to Admin Credentials report (optional, press Enter to skip): ").strip()
    spreadsheet_id = input("Enter Google Sheets ID (or press Enter for default): ").strip()
    
    if not admin_report:
        admin_report = None
    
    if not spreadsheet_id:
        spreadsheet_id = "1aIK_g-Q4VGcUkKwfsRzlPnHZP62yTUhdRwYXenHrFFU"
        
    updater = VolunteerComplianceGoogleSheets(credentials_file, spreadsheet_id)
    updater.update_from_volunteer_report(volunteer_report, admin_report)
    
    print(f"\nSpreadsheet URL: {updater.get_spreadsheet_url()}")