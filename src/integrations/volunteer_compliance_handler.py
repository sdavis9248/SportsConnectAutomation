"""
Integration module for SportsConnectAutomation to handle Volunteer Compliance updates
This is a simplified handler that uses the separate Google Sheets implementation
Save this file as: integrations/volunteer_compliance_handler.py
"""

import logging
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime
import json
import pandas as pd

logger = logging.getLogger(__name__)

class VolunteerComplianceHandler:
    """Handler for automating volunteer compliance tracking"""
    
    def __init__(self, config):
        """
        Initialize the handler with configuration
        
        Args:
            config: ConfigManager instance
        """
        self.config = config
        self.compliance_config = config.get('volunteer_compliance', {})
        
        # Configuration settings
        self.use_xlwings = self.compliance_config.get('use_xlwings', False)
        self.use_google_sheets = self.compliance_config.get('use_google_sheets', True)
        self.google_sheet_id = self.compliance_config.get('google_sheet_id', None)
        self.merge_admin_credentials = self.compliance_config.get('merge_admin_credentials', True)
        
    def process_volunteer_report(self, volunteer_report_path: str, admin_credentials_path: str = None) -> bool:
        """
        Process the downloaded volunteer report and update compliance tracking
        
        Args:
            volunteer_report_path: Path to the downloaded AllVolunteers report
            admin_credentials_path: Path to the Admin Credentials report (optional)
            
        Returns:
            True if successful
        """
        try:
            if not Path(volunteer_report_path).exists():
                logger.error(f"Volunteer report not found: {volunteer_report_path}")
                return False
            
            # Check if admin credentials report exists
            if admin_credentials_path and not Path(admin_credentials_path).exists():
                logger.warning(f"Admin credentials report not found: {admin_credentials_path}")
                admin_credentials_path = None
                
            logger.info("Processing volunteer compliance update...")
            logger.info(f"Volunteer report: {volunteer_report_path}")
            if admin_credentials_path:
                logger.info(f"Admin credentials report: {admin_credentials_path}")
                    
            # Update Google Sheets if configured
            if self.use_google_sheets and self.google_sheet_id:
                success = self._update_google_sheets(volunteer_report_path, admin_credentials_path)
                if not success:
                    logger.error("Failed to update Google Sheets")
                    return False
                    
            # Generate compliance report
            self._generate_compliance_report(volunteer_report_path, admin_credentials_path)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing volunteer compliance: {e}")
            return False
            
    def _update_google_sheets(self, volunteer_report_path: str, admin_credentials_path: str = None) -> bool:
        """Update Google Sheets with compliance data"""
        try:
            # Import the Google Sheets implementation
            from integrations.volunteer_compliance_google_sheets import VolunteerComplianceGoogleSheets
            
            # First try to get sheets-specific credentials, then fall back to general Google credentials
            credentials_file = self.compliance_config.get('google_sheets_credentials_file')
            if not credentials_file:
                # Fall back to general Google Drive credentials
                credentials_file = self.config.get('google_drive_config.credentials_file', 'credentials.json')
                logger.info(f"Using general Google credentials: {credentials_file}")
            else:
                logger.info(f"Using Google Sheets service account: {credentials_file}")
                
            if not Path(credentials_file).exists():
                logger.error(f"Google credentials file not found: {credentials_file}")
                logger.info("Please create a service account and save the JSON key file")
                return False
                
            # Initialize Google Sheets updater
            sheets_updater = VolunteerComplianceGoogleSheets(
                credentials_file,
                self.google_sheet_id
            )
            
            # Update the spreadsheet
            sheets_updater.update_from_volunteer_report(
                volunteer_report_path,
                admin_credentials_path
            )
            
            logger.info(f"Successfully updated Google Sheets")
            logger.info(f"View at: {sheets_updater.get_spreadsheet_url()}")
            
            return True
            
        except ImportError as e:
            logger.error(f"Failed to import Google Sheets implementation: {e}")
            logger.info("Make sure volunteer_compliance_google_sheets.py is in the integrations folder")
            return False
        except Exception as e:
            logger.error(f"Error updating Google Sheets: {e}")
            return False
            
    def _generate_compliance_report(self, volunteer_report_path: str, admin_credentials_path: str = None) -> Dict[str, Any]:
        """Generate a compliance summary report"""
        try:
            # Read data
            df = pd.read_excel(volunteer_report_path)
            
            if admin_credentials_path and self.merge_admin_credentials:
                admin_df = pd.read_excel(admin_credentials_path)
                df = self._merge_reports(df, admin_df)
            
            # Calculate metrics
            total_volunteers = len(df)
            
            metrics = {
                'total_volunteers': total_volunteers,
                'timestamp': datetime.now().isoformat(),
                'compliance_summary': {},
                'reports_used': {
                    'volunteer_report': str(volunteer_report_path),
                    'admin_report': str(admin_credentials_path) if admin_credentials_path else None
                }
            }
            
            # Check each certification type
            certifications = [
                ('ID Verified', 'ID Verification'),
                ('AYSOs Safe Haven Verified', 'Safe Haven Training'),
                ('CA Mandated Fingerprinting Verified', 'Fingerprinting'),
                ('Concussion Awareness Verified', 'Concussion Training'),
                ('SafeSport Verified', 'SafeSport'),
                ('Sudden Cardiac Arrest Verified', 'Cardiac Arrest Training'),
                ('Risk Status', 'Risk Status Green')
            ]
            
            for col, name in certifications:
                if col in df.columns:
                    if col == 'Risk Status':
                        verified = len(df[df[col] == 'Green'])
                    else:
                        verified = len(df[df[col] == 'Y'])
                    
                    metrics['compliance_summary'][name] = {
                        'count': verified,
                        'percentage': (verified / total_volunteers * 100) if total_volunteers > 0 else 0
                    }
            
            # Save summary report
            summary_path = Path(volunteer_report_path).parent / f"compliance_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(summary_path, 'w') as f:
                json.dump(metrics, f, indent=2, default=str)
                
            logger.info(f"Compliance summary saved to: {summary_path}")
            
            # Log summary
            logger.info("\n=== Volunteer Compliance Summary ===")
            for cert, data in metrics['compliance_summary'].items():
                logger.info(f"{cert}: {data['count']}/{total_volunteers} ({data['percentage']:.1f}%)")
                
            return metrics
            
        except Exception as e:
            logger.error(f"Error generating compliance report: {e}")
            return {}
            
    def _merge_reports(self, volunteer_df: pd.DataFrame, admin_df: pd.DataFrame) -> pd.DataFrame:
        """Merge volunteer and admin credentials reports"""
        # Ensure join columns are strings
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
        
        # Select relevant columns from admin report
        admin_columns = ['Admin ID']
        credential_columns = [
            'Admin Alt ID', 'Photo Uploaded', 'Credential Printed',
            'ID Verified', 'ID Verified By', 'ID Verified Date'
        ]
        
        for col in credential_columns:
            if col in admin_df.columns:
                admin_columns.append(col)
        
        admin_subset = admin_df[admin_columns].drop_duplicates(subset=['Admin ID'])
        
        # Merge on Association Volunteer ID = Admin ID
        merged_df = volunteer_df.merge(
            admin_subset,
            left_on='Association Volunteer ID',
            right_on='Admin ID',
            how='left',
            suffixes=('', '_admin')
        )
        
        # Handle duplicate columns
        for col in ['ID Verified', 'ID Verified By', 'ID Verified Date']:
            if f'{col}_admin' in merged_df.columns:
                merged_df[col] = merged_df[f'{col}_admin'].fillna(merged_df[col])
                merged_df.drop(f'{col}_admin', axis=1, inplace=True)
        
        # Drop the duplicate Admin ID column if it exists
        if 'Admin ID' in merged_df.columns and 'Association Volunteer ID' in merged_df.columns:
            merged_df.drop('Admin ID', axis=1, inplace=True)
        
        logger.info(f"Merged {len(volunteer_df)} volunteer records with {len(admin_subset)} admin records")
        return merged_df