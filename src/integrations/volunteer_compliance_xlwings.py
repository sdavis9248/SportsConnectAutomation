"""
Volunteer Compliance Excel Automation using XlWings
This script automates updating the 2025 Volunteer Compliance.xlsx file
while preserving all formatting, colors, and structure.
"""

import xlwings as xw
import pandas as pd
from datetime import datetime
import os
import shutil
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VolunteerComplianceUpdater:
    def __init__(self, compliance_file_path, volunteer_report_path, admin_credentials_path=None):
        """
        Initialize the updater with file paths
        
        Args:
            compliance_file_path: Path to the 2025 Volunteer Compliance.xlsx file
            volunteer_report_path: Path to the downloaded AllVolunteers report
            admin_credentials_path: Path to the Admin Credentials report (optional)
        """
        self.compliance_file = Path(compliance_file_path)
        self.volunteer_report = Path(volunteer_report_path)
        self.admin_credentials_report = Path(admin_credentials_path) if admin_credentials_path else None
        
        # Backup the original file
        self._create_backup()
        
    def _create_backup(self):
        """Create a backup of the compliance file"""
        backup_path = self.compliance_file.with_suffix(
            f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )
        shutil.copy2(self.compliance_file, backup_path)
        logger.info(f"Created backup: {backup_path}")
        
    def update_compliance_file(self):
        """Update the compliance file with new data"""
        try:
            # Read the volunteer data from Sports Connect
            logger.info(f"Reading volunteer report: {self.volunteer_report}")
            volunteer_df = pd.read_excel(self.volunteer_report)
            
            # Read admin credentials data from Sports Affinity if available
            admin_df = None
            if self.admin_credentials_report and self.admin_credentials_report.exists():
                logger.info(f"Reading admin credentials report: {self.admin_credentials_report}")
                admin_df = pd.read_excel(self.admin_credentials_report)
            
            # Merge the data if we have both reports
            if admin_df is not None:
                logger.info("Merging volunteer and admin credentials data...")
                # Join on Admin ID field
                merged_df = self._merge_reports(volunteer_df, admin_df)
            else:
                logger.warning("No admin credentials report provided, using volunteer data only")
                merged_df = volunteer_df
            
            # Open the compliance file with xlwings
            logger.info("Opening compliance file with xlwings...")
            app = xw.App(visible=False)
            wb = app.books.open(str(self.compliance_file))
            
            # Create new sheet with today's date
            sheet_name = datetime.now().strftime("%m.%d.%y")
            
            # Check if sheet already exists
            existing_sheets = [sheet.name for sheet in wb.sheets]
            if sheet_name in existing_sheets:
                logger.warning(f"Sheet {sheet_name} already exists. Renaming...")
                sheet_name = f"{sheet_name}_v2"
            
            # Add new sheet at the beginning
            new_sheet = wb.sheets.add(sheet_name, before=wb.sheets[0])
            logger.info(f"Created new sheet: {sheet_name}")
            
            # Write headers (preserving formatting from first sheet)
            if len(wb.sheets) > 1:
                # Copy formatting from the previous sheet
                source_sheet = wb.sheets[1]
                
                # Copy column widths
                for col in range(1, len(merged_df.columns) + 1):
                    new_sheet.range((1, col)).column_width = source_sheet.range((1, col)).column_width
                
                # Copy header formatting
                header_range = source_sheet.range('A1').expand('right')
                header_format = {
                    'font_name': header_range.font.name,
                    'font_size': header_range.font.size,
                    'bold': header_range.font.bold,
                    'color': header_range.font.color,
                    'fill_color': header_range.color
                }
            
            # Write data to new sheet
            new_sheet.range('A1').value = merged_df.columns.tolist()
            new_sheet.range('A2').value = merged_df.values.tolist()
            
            # Apply formatting
            header_range = new_sheet.range('A1').expand('right')
            header_range.font.bold = True
            header_range.color = (217, 225, 242)  # Light blue background
            
            # Format date columns
            date_columns = [col for col in merged_df.columns if 'Date' in col or 'Expire' in col]
            for col in date_columns:
                col_index = merged_df.columns.get_loc(col) + 1
                date_range = new_sheet.range((2, col_index)).expand('down')
                date_range.number_format = 'mm/dd/yyyy'
            
            # Apply conditional formatting for compliance status
            self._apply_conditional_formatting(new_sheet, merged_df)
            
            # Auto-fit columns
            new_sheet.autofit(axis='columns')
            
            # Delete old sheets if more than 12 exist (keep ~3 months of history)
            if len(wb.sheets) > 12:
                oldest_sheet = wb.sheets[-1]
                logger.info(f"Deleting old sheet: {oldest_sheet.name}")
                oldest_sheet.delete()
            
            # Save and close
            wb.save()
            wb.close()
            app.quit()
            
            logger.info(f"Successfully updated compliance file with {len(merged_df)} records")
            
            # Generate summary report
            self._generate_summary_report(merged_df)
            
        except Exception as e:
            logger.error(f"Error updating compliance file: {e}")
            raise
            
    def _merge_reports(self, volunteer_df, admin_df):
        """
        Merge volunteer and admin credentials reports
        
        Args:
            volunteer_df: DataFrame from AllVolunteers report
            admin_df: DataFrame from Admin Credentials report
            
        Returns:
            Merged DataFrame with all compliance data
        """
        # Ensure Admin ID columns are strings for proper joining
        if 'Admin ID' in volunteer_df.columns:
            volunteer_df['Admin ID'] = volunteer_df['Admin ID'].astype(str)
        if 'Admin ID' in admin_df.columns:
            admin_df['Admin ID'] = admin_df['Admin ID'].astype(str)
        
        # Select relevant columns from admin credentials report
        admin_columns = ['Admin ID']
        
        # Add credential-specific columns if they exist
        credential_columns = [
            'Admin Alt ID', 
            'Photo Uploaded', 
            'Credential Printed',
            'ID Verified',
            'ID Verified By',
            'ID Verified Date'
        ]
        
        for col in credential_columns:
            if col in admin_df.columns:
                admin_columns.append(col)
        
        # Get subset of admin data
        admin_subset = admin_df[admin_columns].drop_duplicates(subset=['Admin ID'])
        
        # Merge on Admin ID
        merged_df = volunteer_df.merge(
            admin_subset,
            on='Admin ID',
            how='left',
            suffixes=('', '_admin')
        )
        
        # Handle conflicts where columns exist in both reports
        # Prefer admin credentials data for these fields
        for col in ['ID Verified', 'ID Verified By', 'ID Verified Date']:
            if f'{col}_admin' in merged_df.columns:
                # Use admin data where available, fall back to volunteer data
                merged_df[col] = merged_df[f'{col}_admin'].fillna(merged_df[col])
                merged_df.drop(f'{col}_admin', axis=1, inplace=True)
        
        logger.info(f"Merged {len(volunteer_df)} volunteer records with {len(admin_subset)} admin records")
        
        return merged_df
    
    def _apply_conditional_formatting(self, sheet, data):
        """Apply conditional formatting to highlight compliance issues"""
        # Find columns for verified status
        verified_columns = [col for col in data.columns if 'Verified' in col and 'By' not in col and 'Date' not in col]
        
        for col in verified_columns:
            col_index = data.columns.get_loc(col) + 1
            # Apply red fill for 'N' values, green for 'Y'
            for row in range(2, len(data) + 2):
                cell = sheet.range((row, col_index))
                if cell.value == 'N':
                    cell.color = (255, 199, 206)  # Light red
                elif cell.value == 'Y':
                    cell.color = (198, 239, 206)  # Light green
                    
    def _generate_summary_report(self, data):
        """Generate a summary report of compliance status"""
        summary = {
            'Total Volunteers': len(data),
            'ID Verified': len(data[data['ID Verified'] == 'Y']),
            'Risk Status Green': len(data[data['Risk Status'] == 'Green']),
            'Safe Haven Verified': len(data[data['AYSOs Safe Haven Verified'] == 'Y']),
            'Fingerprinting Verified': len(data[data['CA Mandated Fingerprinting Verified'] == 'Y']),
            'Concussion Training': len(data[data['Concussion Awareness Verified'] == 'Y']),
            'SafeSport Verified': len(data[data['SafeSport Verified'] == 'Y']),
            'Cardiac Arrest Training': len(data[data['Sudden Cardiac Arrest Verified'] == 'Y'])
        }
        
        logger.info("\n=== Compliance Summary ===")
        for key, value in summary.items():
            percentage = (value / summary['Total Volunteers'] * 100) if summary['Total Volunteers'] > 0 else 0
            logger.info(f"{key}: {value} ({percentage:.1f}%)")
            
        return summary


def integrate_with_sports_connect_automation():
    """
    Integration function to be called after SportsConnect downloads reports
    """
    # Configuration
    compliance_file = r"C:\Users\sdavis\OneDrive\AYSO\2025 Volunteer Compliance.xlsx"
    downloads_dir = r"C:\Users\sdavis\OneDrive\AYSO\data\downloads"
    
    # Find the most recent reports
    import glob
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
    
    # Update the compliance file
    updater = VolunteerComplianceUpdater(compliance_file, latest_volunteer, latest_admin)
    updater.update_compliance_file()
    
    return True


if __name__ == "__main__":
    # Example usage
    compliance_file = input("Enter path to 2025 Volunteer Compliance.xlsx: ")
    volunteer_report = input("Enter path to downloaded AllVolunteers report: ")
    admin_report = input("Enter path to Admin Credentials report (optional, press Enter to skip): ").strip()
    
    if not admin_report:
        admin_report = None
    
    updater = VolunteerComplianceUpdater(compliance_file, volunteer_report, admin_report)
    updater.update_compliance_file()
