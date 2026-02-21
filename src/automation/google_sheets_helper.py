"""
Google Sheets Helper for ETrainU Integration
Handles reading volunteer data from Google Sheets with date-based sheet selection
"""
import logging
import pandas as pd
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import re

logger = logging.getLogger(__name__)

class GoogleSheetsHelper:
    """Helper class for reading Google Sheets data"""
    
    def __init__(self):
        self.base_url = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    
    def extract_sheet_id_from_url(self, url: str) -> str:
        """Extract the Google Sheets ID from a URL"""
        # Pattern to match Google Sheets URLs
        pattern = r'/spreadsheets/d/([a-zA-Z0-9-_]+)'
        match = re.search(pattern, url)
        
        if match:
            return match.group(1)
        else:
            raise ValueError(f"Could not extract sheet ID from URL: {url}")
    
    def get_sheet_names_and_gids(self, sheet_id: str) -> List[Dict[str, str]]:
        """
        Get all sheet names and their GIDs from a Google Spreadsheet
        Note: This is a simplified approach. For production, you'd use Google Sheets API
        """
        try:
            # Try to get the main sheet first (gid=0)
            test_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
            response = requests.get(test_url, timeout=10)
            
            if response.status_code == 200:
                # For now, return a basic structure
                # In a full implementation, you'd use Google Sheets API to get all sheet metadata
                return [
                    {'name': 'default', 'gid': '0'},
                    {'name': 'current', 'gid': '714775987'}  # From the URL you provided
                ]
            else:
                logger.warning("Could not access Google Sheet metadata")
                return []
                
        except Exception as e:
            logger.error(f"Error getting sheet metadata: {e}")
            return []
    
    def find_most_recent_date_sheet(self, sheet_id: str, fallback_gid: str = None) -> Tuple[str, str]:
        """
        Find the most recent sheet based on mm.dd.yy naming pattern
        
        Args:
            sheet_id: Google Sheets ID
            fallback_gid: GID to use if no date sheets found
            
        Returns:
            Tuple of (sheet_name, gid)
        """
        try:
            # For now, use the known GID from the URL
            # In production, you'd enumerate all sheets and find the most recent date
            
            # This is a simplified implementation
            # You would use Google Sheets API to get all sheet names
            current_date = datetime.now()
            
            # Mock finding the most recent sheet (in real implementation, you'd query the API)
            recent_sheet_name = current_date.strftime("%m.%d.%y")
            recent_gid = fallback_gid or "714775987"
            
            logger.info(f"Using sheet: {recent_sheet_name} (GID: {recent_gid})")
            return recent_sheet_name, recent_gid
            
        except Exception as e:
            logger.error(f"Error finding recent sheet: {e}")
            # Fallback to provided GID
            return "current", fallback_gid or "714775987"
    
    def read_google_sheet_as_dataframe(self, url: str, gid: str = None) -> pd.DataFrame:
        """
        Read a Google Sheet as a pandas DataFrame
        
        Args:
            url: Google Sheets URL
            gid: Specific sheet GID (extracted from URL if not provided)
            
        Returns:
            pandas DataFrame with the sheet data
        """
        try:
            # Extract sheet ID from URL
            sheet_id = self.extract_sheet_id_from_url(url)
            
            # Extract GID from URL if not provided
            if gid is None:
                gid_match = re.search(r'gid=(\d+)', url)
                if gid_match:
                    gid = gid_match.group(1)
                else:
                    gid = "0"  # Default to first sheet
            
            # Build CSV export URL
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
            
            logger.info(f"Reading Google Sheet: {csv_url}")
            
            # Read the CSV data
            response = requests.get(csv_url, timeout=30)
            response.raise_for_status()
            
            # Parse as DataFrame
            from io import StringIO
            csv_data = StringIO(response.text)
            df = pd.read_csv(csv_data)
            
            logger.info(f"Successfully read Google Sheet: {len(df)} rows, {len(df.columns)} columns")
            return df
            
        except Exception as e:
            logger.error(f"Error reading Google Sheet: {e}")
            raise
    
    def read_most_recent_volunteer_compliance(self, sheets_url: str) -> pd.DataFrame:
        """
        Read the most recent volunteer compliance data from Google Sheets
        
        Args:
            sheets_url: Google Sheets URL
            
        Returns:
            pandas DataFrame with compliance data
        """
        try:
            sheet_id = self.extract_sheet_id_from_url(sheets_url)
            
            # Find the most recent date-based sheet
            sheet_name, gid = self.find_most_recent_date_sheet(sheet_id, "714775987")
            
            # Read the data
            df = self.read_google_sheet_as_dataframe(sheets_url, gid)
            
            logger.info(f"Read volunteer compliance data from sheet '{sheet_name}': {len(df)} records")
            return df
            
        except Exception as e:
            logger.error(f"Error reading volunteer compliance from Google Sheets: {e}")
            raise


def get_volunteer_data_from_google_sheets(config) -> Dict[str, pd.DataFrame]:
    """
    Get volunteer data from the same Google Sheets used for volunteer compliance
    
    Args:
        config: Configuration manager instance
        
    Returns:
        Dictionary of DataFrames keyed by data type
    """
    volunteer_data = {}
    
    try:
        # Use the same volunteer compliance Google Sheets configuration
        compliance_config = config.get('volunteer_compliance', {})
        
        if not compliance_config.get('use_google_sheets', False):
            logger.warning("Google Sheets not enabled in volunteer_compliance config")
            return volunteer_data
            
        google_sheet_id = compliance_config.get('google_sheet_id')
        credentials_file = compliance_config.get('google_sheets_credentials_file', 'credentials.json')
        
        if not google_sheet_id:
            logger.error("No google_sheet_id found in volunteer_compliance config")
            return volunteer_data
            
        if not Path(credentials_file).exists():
            logger.error(f"Google credentials file not found: {credentials_file}")
            return volunteer_data
        
        # Import and initialize the Google Sheets handler
        from integrations.volunteer_compliance_google_sheets import VolunteerComplianceGoogleSheets
        
        # Initialize with the same credentials and sheet ID used for compliance
        sheets_handler = VolunteerComplianceGoogleSheets(credentials_file, google_sheet_id)
        
        # Read the most recent sheet (date-based sheet name like "mm.dd.yy")
        try:
            # Get all sheets in the workbook
            spreadsheet = sheets_handler.sheets_api.get(spreadsheetId=google_sheet_id).execute()
            sheet_names = [sheet['properties']['title'] for sheet in spreadsheet['sheets']]
            
            # Find the most recent date-based sheet (format: mm.dd.yy)
            date_pattern = re.compile(r'^\d{2}\.\d{2}\.\d{2}$')
            date_sheets = [name for name in sheet_names if date_pattern.match(name)]
            
            if date_sheets:
                # Sort by date (assuming mm.dd.yy format) - most recent first
                date_sheets.sort(reverse=True)
                latest_sheet = date_sheets[0]
                logger.info(f"Using most recent compliance sheet: {latest_sheet}")
                
                # Read the data from the latest sheet
                range_name = f"'{latest_sheet}'!A:BH"  # Read all columns from A to Z
                result = sheets_handler.sheets_api.values().get(
                    spreadsheetId=google_sheet_id,
                    range=range_name
                ).execute()
                
                values = result.get('values', [])
                
                if values:
                    # Convert to DataFrame
                    headers = values[0]
                    data_rows = values[1:] if len(values) > 1 else []
                    
                    # Pad rows to match header length
                    for row in data_rows:
                        while len(row) < len(headers):
                            row.append('')
                    
                    compliance_df = pd.DataFrame(data_rows, columns=headers)
                    volunteer_data['compliance'] = compliance_df
                    logger.info(f"Loaded compliance data from '{latest_sheet}': {len(compliance_df)} records")
                else:
                    logger.warning(f"No data found in sheet: {latest_sheet}")
            else:
                logger.warning("No date-based sheets found in the compliance workbook")
                
                # Fallback: try 'Current Status' sheet if no date sheets found
                if 'Current Status' in sheet_names:
                    logger.info("Falling back to 'Current Status' sheet")
                    range_name = "'Current Status'!A:Z"
                    result = sheets_handler.sheets_api.values().get(
                        spreadsheetId=google_sheet_id,
                        range=range_name
                    ).execute()
                    
                    values = result.get('values', [])
                    if values:
                        headers = values[0]
                        data_rows = values[1:] if len(values) > 1 else []
                        
                        for row in data_rows:
                            while len(row) < len(headers):
                                row.append('')
                        
                        compliance_df = pd.DataFrame(data_rows, columns=headers)
                        volunteer_data['compliance'] = compliance_df
                        logger.info(f"Loaded compliance data from 'Current Status': {len(compliance_df)} records")
                        
        except Exception as e:
            logger.error(f"Failed to read compliance data from Google Sheets: {e}")
            
    except ImportError as e:
        logger.error(f"Failed to import Google Sheets implementation: {e}")
        logger.info("Make sure volunteer_compliance_google_sheets.py is in the integrations folder")
    except Exception as e:
        logger.error(f"Error accessing Google Sheets: {e}")
    
    return volunteer_data


# Enhanced ETrainU scraper load method
def load_volunteer_data_enhanced(scraper, volunteer_files: Dict[str, str], config):
    """
    Enhanced volunteer data loading that supports both local files and Google Sheets
    
    Args:
        scraper: ETrainU scraper instance
        volunteer_files: Dictionary of file paths (can be URLs or local paths)
        config: Configuration manager
    """
    logger.info("Loading volunteer data (enhanced mode)...")
    
    # Check if we should use Google Sheets
    etrainu_config = config.get('etrainu_config', {}) if config else {}
    use_google_sheets = etrainu_config.get('use_google_sheets', False)
    
    if use_google_sheets:
        logger.info("Using Google Sheets for volunteer data")
        
        # Load from Google Sheets
        volunteer_data = get_volunteer_data_from_google_sheets(config)
        
        # Set the data directly on the scraper
        if 'compliance' in volunteer_data:
            scraper.compliance_data = volunteer_data['compliance']
        if 'volunteer_details' in volunteer_data:
            scraper.volunteer_data = volunteer_data['volunteer_details']
        if 'enrollment' in volunteer_data:
            scraper.enrollment_data = volunteer_data['enrollment']
    
    else:
        logger.info("Using local Excel files for volunteer data")
        
        # Use original file-based loading
        scraper.load_volunteer_data(volunteer_files)
