"""
Google Sheets integration for waitlist management
Reads waitlist decisions from a Google Sheet survey to determine which participants to remove
"""
import os
import re
import logging
import requests
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class GoogleSheetsWaitlistReader:
    """Reads waitlist decisions from Google Sheets"""
    
    def __init__(self, sheet_id: str = "1wraHRkpi2HkhKClP5KMQmAflntsC-V3PQVW5S7QGav8"):
        """
        Initialize Google Sheets reader
        
        Args:
            sheet_id: Google Sheets ID (from the URL)
        """
        self.sheet_id = sheet_id
        self.export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
        logger.info(f"Initialized Google Sheets reader for sheet: {sheet_id}")
    
    def download_sheet(self, download_path: str = None) -> Optional[str]:
        """
        Download the Google Sheet as Excel file
        
        Args:
            download_path: Path to save the file (optional)
            
        Returns:
            Path to downloaded file if successful, None otherwise
        """
        try:
            if download_path is None:
                # Create temporary download path
                download_dir = Path("data/downloads/waitlist_sheets")
                download_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                download_path = download_dir / f"waitlist_decisions_{timestamp}.xlsx"
            
            logger.info(f"Downloading Google Sheet to: {download_path}")
            
            # Download the sheet
            response = requests.get(self.export_url, timeout=30)
            response.raise_for_status()
            
            # Save to file
            with open(download_path, 'wb') as f:
                f.write(response.content)
            
            logger.info(f"Successfully downloaded Google Sheet ({len(response.content)} bytes)")
            return str(download_path)
            
        except requests.RequestException as e:
            logger.error(f"Failed to download Google Sheet: {e}")
            return None
        except Exception as e:
            logger.error(f"Error downloading Google Sheet: {e}")
            return None
    
    def extract_order_number(self, player_info: str) -> Optional[str]:
        """
        Extract order number from player information string
        
        Args:
            player_info: String containing player info and order number
            
        Returns:
            Order number if found, None otherwise
        """
        if not player_info or pd.isna(player_info):
            return None
        
        # Pattern to match (Order XXXXXXXXX) at the end of the string
        pattern = r'\(Order\s+(\d+)\)$'
        match = re.search(pattern, str(player_info).strip())
        
        if match:
            order_number = match.group(1)
            logger.debug(f"Extracted order number: {order_number}")
            return order_number
        else:
            logger.warning(f"No order number found in: {player_info}")
            return None
    
    def read_waitlist_decisions(self, file_path: str = None) -> Dict[str, List[str]]:
        """
        Read waitlist decisions from the Excel file
        
        Args:
            file_path: Path to Excel file (will download if not provided)
            
        Returns:
            Dictionary with 'remove' and 'keep' lists of order numbers
        """
        results = {
            'remove': [],      # Order numbers to remove (answered "No")
            'keep': [],        # Order numbers to keep (answered "Yes")
            'no_response': []  # Order numbers with no response
        }
        
        try:
            # Download sheet if no file path provided
            if file_path is None:
                file_path = self.download_sheet()
                if file_path is None:
                    logger.error("Failed to download Google Sheet")
                    return results
            
            # Read Excel file
            logger.info(f"Reading waitlist decisions from: {file_path}")
            df = pd.read_excel(file_path)
            
            # Log column names for debugging
            logger.debug(f"Columns found: {df.columns.tolist()}")
            
            # Find the relevant columns (handle potential variations)
            timestamp_col = None
            response_col = None
            player_col = None
            
            for col in df.columns:
                col_lower = str(col).lower()
                if 'timestamp' in col_lower:
                    timestamp_col = col
                elif 'want to stay' in col_lower or 'waitlist' in col_lower:
                    response_col = col
                elif 'player' in col_lower or 'information' in col_lower:
                    player_col = col
            
            if not all([timestamp_col, response_col, player_col]):
                logger.error(f"Required columns not found. Found: {df.columns.tolist()}")
                return results
            
            logger.info(f"Processing {len(df)} rows from Google Sheet")
            
            # Process each row
            for idx, row in df.iterrows():
                try:
                    response = str(row[response_col]).strip().lower() if pd.notna(row[response_col]) else ""
                    player_info = row[player_col]
                    
                    # Extract order number
                    order_number = self.extract_order_number(player_info)
                    
                    if order_number:
                        if response == 'yes':
                            results['keep'].append(order_number)
                            logger.debug(f"Keep on waitlist: {order_number}")
                        elif response == 'no':
                            results['remove'].append(order_number)
                            logger.debug(f"Remove from waitlist: {order_number}")
                        else:
                            results['no_response'].append(order_number)
                            logger.debug(f"No response for: {order_number}")
                    
                except Exception as e:
                    logger.error(f"Error processing row {idx}: {e}")
                    continue
            
            # Summary
            logger.info(f"Waitlist decision summary:")
            logger.info(f"  - Remove from waitlist: {len(results['remove'])} participants")
            logger.info(f"  - Keep on waitlist: {len(results['keep'])} participants")
            logger.info(f"  - No response: {len(results['no_response'])} participants")
            
            # Log order numbers to remove
            if results['remove']:
                logger.info(f"Order numbers to remove: {', '.join(results['remove'])}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error reading waitlist decisions: {e}")
            return results
    
    def get_removal_list(self) -> List[str]:
        """
        Get list of order numbers to remove from waitlist
        
        Returns:
            List of order numbers for participants who want to be removed
        """
        decisions = self.read_waitlist_decisions()
        return decisions['remove']
    
    def save_decisions_summary(self, decisions: Dict[str, List[str]], 
                             output_path: str = None) -> str:
        """
        Save a summary of waitlist decisions
        
        Args:
            decisions: Dictionary of decisions
            output_path: Path to save summary (optional)
            
        Returns:
            Path to saved file
        """
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"data/downloads/waitlist_decisions_summary_{timestamp}.txt"
        
        try:
            with open(output_path, 'w') as f:
                f.write("Waitlist Decisions Summary\n")
                f.write("=" * 50 + "\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Google Sheet ID: {self.sheet_id}\n\n")
                
                f.write(f"REMOVE FROM WAITLIST ({len(decisions['remove'])} participants):\n")
                for order in decisions['remove']:
                    f.write(f"  - {order}\n")
                f.write("\n")
                
                f.write(f"KEEP ON WAITLIST ({len(decisions['keep'])} participants):\n")
                for order in decisions['keep']:
                    f.write(f"  - {order}\n")
                f.write("\n")
                
                f.write(f"NO RESPONSE ({len(decisions['no_response'])} participants):\n")
                for order in decisions['no_response']:
                    f.write(f"  - {order}\n")
            
            logger.info(f"Saved decisions summary to: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error saving decisions summary: {e}")
            return None


# Convenience function
def get_waitlist_removal_orders(sheet_id: str = None) -> List[str]:
    """
    Get order numbers to remove from waitlist from Google Sheet
    
    Args:
        sheet_id: Google Sheet ID (uses default if not provided)
        
    Returns:
        List of order numbers to remove
    """
    reader = GoogleSheetsWaitlistReader(sheet_id) if sheet_id else GoogleSheetsWaitlistReader()
    return reader.get_removal_list()


if __name__ == "__main__":
    # Test the reader
    reader = GoogleSheetsWaitlistReader()
    decisions = reader.read_waitlist_decisions()
    
    print(f"\nWaitlist Decisions:")
    print(f"Remove: {decisions['remove']}")
    print(f"Keep: {decisions['keep']}")
    print(f"No Response: {decisions['no_response']}")
    
    # Save summary
    reader.save_decisions_summary(decisions)
