"""
Sports Connect Automation - Main Entry Point
Built for Visual Studio 2022
Updated with Sports Affinity and Waitlist Management integration
"""
import sys
import os
import argparse
import glob
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import ConfigManager
from automation.sports_connect import SportsConnectAutomation
from automation.report_handlers import ReportType
from automation.waitlist_manager import WaitlistManager
from integrations.google_drive import GoogleDriveUploader
from integrations.access_db import AccessDatabaseManager
from utilities.logger import setup_logging, LogContext
from utilities.archiver import ReportArchiver
from utilities.validator import ReportValidator
from utilities.credentials import CredentialsManager


def main():
    """Main entry point for the automation"""
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description='Sports Connect Report Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                           # Run all enabled reports
  python main.py TEAM_DETAIL               # Run specific Sports Connect report
  python main.py ADMIN_DETAILS             # Run specific Sports Affinity report
  python main.py WAITLIST_MANAGEMENT       # Run waitlist management (reads from Google Sheet if enabled)
  python main.py WAITLIST_REPORT           # Download waitlist report for notifications
  python main.py --headless                # Run in headless mode
  python main.py --no-upload               # Skip Google Drive upload
  python main.py --no-access               # Skip Access database operations
  python main.py --validate-only           # Only validate existing reports
  python main.py --waitlist-summary        # Get waitlist summary only
  python main.py --waitlist-sheet          # Show waitlist decisions from Google Sheet
  python main.py --waitlist-notify         # Send email notifications to waitlist participants
  python main.py --waitlist-removal        # Remove participants using Google Sheet data
  python main.py --waitlist-removal 12345  # Remove specific order number
  python main.py --access-info             # Show Access database info
  python main.py --access-macro UpdateAdminDetail    # Execute specific Access macro
  python main.py --access-macro UpdateEnrollmentSummary  # Execute enrollment macro
        """
    )
    
    parser.add_argument('report', nargs='?', help='Specific report to run')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--config', default='config/config.json', help='Config file path')
    parser.add_argument('--no-upload', action='store_true', help='Skip Google Drive upload')
    parser.add_argument('--no-access', action='store_true', help='Skip Access database operations')
    parser.add_argument('--validate-only', action='store_true', help='Only validate existing reports')
    parser.add_argument('--archive', action='store_true', help='Archive downloaded reports')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    parser.add_argument('--waitlist-summary', action='store_true', help='Get waitlist summary only')
    parser.add_argument('--access-info', action='store_true', help='Show Access database info')
    parser.add_argument('--access-macro', metavar='MACRO_NAME', help='Execute a specific Access macro')
    parser.add_argument('--no-enrollment-macro', action='store_true', 
                   help='Skip running UpdateEnrollmentSummary macro after reports')
    parser.add_argument('--waitlist-sheet', action='store_true', help='Show waitlist decisions from Google Sheet')
    parser.add_argument('--waitlist-notify', action='store_true', help='Send email notifications to waitlist participants')
    parser.add_argument('--waitlist-tracking', action='store_true', help='Show waitlist notification tracking status')
    parser.add_argument('--waitlist-removal', nargs='*', metavar='ORDER_NUM',
                       help='Remove participants by order numbers from waitlists (or from Google Sheet if no numbers provided)',
                       default=None)

    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = ConfigManager(args.config)
        config.load_config()
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return 1
    
    # Override config with command line arguments
    if args.headless:
        config.set('headless_mode', True)
    
    # Set up logging
    logger = setup_logging(
        log_level=args.log_level,
        log_dir=config.get('log_dir', 'logs')
    )
    
    logger.info("="*60)
    logger.info("Sports Connect Automation Started")
    logger.info(f"Configuration: {args.config}")
    logger.info(f"Mode: {'Headless' if config.headless_mode else 'Normal'}")
    logger.info(f"CLI Arguments: {' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'None'}")
    logger.info(f"Parsed Args: {vars(args)}")
    logger.info("="*60)
    
    # Check credentials
    if not args.validate_only and not args.access_info and not args.waitlist_sheet:
        if not CredentialsManager.check_credentials_exist(config.credentials_file):
            logger.error(f"Credentials file not found: {config.credentials_file}")
            logger.info("Run 'python -m utilities.credentials' to set up credentials")
            return 1
    
    # Handle info-only operations
    if args.access_info:
        return show_access_info(config)
    
    # Handle Access macro execution
    if args.access_macro:
        return execute_access_macro(args.access_macro, config)
    
    # Handle waitlist sheet display
    if args.waitlist_sheet:
        return show_waitlist_sheet_decisions(config)
    
    # Handle waitlist notifications
    if args.waitlist_notify:
        return handle_waitlist_notifications(config)
    
    # Handle waitlist tracking status
    if args.waitlist_tracking:
        return show_waitlist_tracking_status(config)
    
    # Validate only mode
    if args.validate_only:
        return validate_existing_reports(config)
    
    # Initialize components
    automation = None
    drive_uploader = None
    access_manager = None
    archiver = ReportArchiver(config.get('archive_dir', 'data/archives'))
    
    try:
        # Initialize automation
        with LogContext("Initialization", logger):
            automation = SportsConnectAutomation(config)
            automation.initialize()
        
        # Login (shared for both Sports Connect and Sports Affinity)
        with LogContext("Login", logger):
            if not automation.login():
                logger.error("Login failed")
                return 1
        
        # Handle waitlist summary only
        if args.waitlist_summary:
            return handle_waitlist_summary(automation, config)
        
        # Handle waitlist removal from command line
        if args.waitlist_removal is not None:
            return handle_waitlist_removal(automation, args.waitlist_removal, config)
        
        # Run reports
        if args.report:
            # Run specific report
            with LogContext(f"Export {args.report}", logger):
                result = automation.run_single_report(args.report)
                if not result:
                    logger.error(f"Failed to export {args.report}")
                    return 1
                downloaded_files = {args.report: result}
        else:
            # Run all reports
            with LogContext("Export All Reports", logger):
                results = automation.export_all_reports()
                downloaded_files = {
                    report_type.name: path 
                    for report_type, path in results.items() 
                    if path
                }
        
        # Validate reports
        with LogContext("Validation", logger):
            validator = ReportValidator()
            validations = {}
            
            for report_name, file_path in downloaded_files.items():
                if file_path and os.path.exists(file_path):
                    validation = validator.validate_excel_file(file_path)
                    validations[report_name] = validation
                    
                    if validation['valid']:
                        logger.info(f"✓ {report_name}: Valid ({validation['total_rows']} rows)")
                    else:
                        logger.error(f"✗ {report_name}: Invalid - {validation['error']}")
        
        # Run UpdateEnrollmentSummary macro after all Sports Connect reports are downloaded
        if (not args.no_access and 
            not args.no_enrollment_macro and 
            config.get('access_config', {}).get('enabled', True) and
            config.get('access_config', {}).get('auto_run_macros', True)):
            
            # Check if we downloaded any Sports Connect reports
            sports_connect_reports = [
                'TEAM_DETAIL', 'VOLUNTEER_DETAIL', 'PLAYER_DETAIL', 
                'ENROLLMENT_SUMMARY', 'DIVISION_DETAILS', 'OPEN_ORDERS'
            ]
            
            has_sports_connect_reports = any(
                report_name in downloaded_files 
                for report_name in sports_connect_reports
            )
            
            if has_sports_connect_reports:
                with LogContext("Update Enrollment Summary Macro", logger):
                    try:
                        logger.info("Running UpdateEnrollmentSummary macro to process all Sports Connect reports...")
                        
                        if not access_manager:
                            access_manager = AccessDatabaseManager(config)
                        
                        # Create backup if configured
                        if config.get('access_config', {}).get('backup_before_macro', False):
                            backup_file = access_manager.backup_database()
                            if backup_file:
                                logger.info(f"Database backup created: {backup_file}")
                        
                        # Run the macro
                        macro_name = config.get('access_config', {}).get('macros', {}).get('enrollment_summary', 'UpdateEnrollmentSummary')
                        success = access_manager.run_macro(macro_name)
                        
                        if success:
                            logger.info(f"✓ Access macro '{macro_name}' completed successfully")
                            logger.info("All Sports Connect reports have been imported into Access database")
                        else:
                            logger.error(f"✗ Access macro '{macro_name}' failed")
                            
                    except Exception as e:
                        logger.error(f"Error running UpdateEnrollmentSummary macro: {e}")
            else:
                logger.info("No Sports Connect reports downloaded, skipping UpdateEnrollmentSummary macro")
        
        # Archive reports if requested
        if args.archive:
            with LogContext("Archive Reports", logger):
                for report_name, file_path in downloaded_files.items():
                    if file_path and os.path.exists(file_path):
                        archived = archiver.archive_report(file_path, report_name)
                        if archived:
                            logger.info(f"Archived {report_name} to {archived}")
        
        # Access database operations (handled automatically in report processing)
        if not args.no_access and config.get('access_config', {}).get('enabled', True):
            with LogContext("Access Database Summary", logger):
                try:
                    access_manager = AccessDatabaseManager(config)
                    db_info = access_manager.get_database_info()
                    
                    if db_info['database_exists'] and db_info['access_exe_exists']:
                        logger.info("Access database integration available")
                        logger.info(f"Database: {db_info['database_path']}")
                        logger.info(f"Size: {db_info['database_size']} bytes")
                        if db_info['last_modified']:
                            logger.info(f"Last modified: {db_info['last_modified']}")
                    else:
                        logger.warning("Access database or executable not found")
                        
                except Exception as e:
                    logger.error(f"Access database error: {e}")
        
        # Google Drive upload
        if not args.no_upload and config.get('google_drive_config', {}).get('folder_id'):
            with LogContext("Google Drive Upload", logger):
                try:
                    if os.path.exists('credentials.json'):
                        drive_uploader = GoogleDriveUploader()
                        results = drive_uploader.upload_reports(
                            downloaded_files,
                            config.get('google_drive_folder_id')
                        )
                        
                        for report_name, file_id in results.items():
                            if file_id:
                                logger.info(f"Success: Uploaded {report_name}: {file_id}")
                            else:
                                logger.warning(f"Error: Failed to upload {report_name}")
                    else:
                        logger.warning("Google Drive credentials not found, skipping upload")
                        
                except Exception as e:
                    logger.error(f"Google Drive upload error: {e}")
        
        # Summary
        logger.info("\n" + "="*60)
        logger.info("Automation Summary")
        logger.info("="*60)
        logger.info(f"Reports Downloaded: {len(downloaded_files)}")
        logger.info(f"Reports Validated: {sum(1 for v in validations.values() if v.get('valid'))}")
        
        if not args.no_upload and drive_uploader:
            logger.info(f"Reports Uploaded: {sum(1 for r in results.values() if r)}")
        
        logger.info("Success: Automation completed successfully!")
        
        return 0
        
    except Exception as e:
        logger.error(f"Automation failed: {e}", exc_info=True)
        return 1
        
    finally:
        if automation:
            automation.cleanup()


def validate_existing_reports(config: ConfigManager) -> int:
    """Validate existing report files"""
    logger = setup_logging(log_level=config.log_level)
    logger.info("Running validation only mode")
    
    validator = ReportValidator()
    download_dir = Path(config.download_dir)
    
    if not download_dir.exists():
        logger.error(f"Download directory not found: {download_dir}")
        return 1
    
    # Find Excel files
    excel_files = list(download_dir.glob("*.xlsx")) + list(download_dir.glob("*.xls"))
    json_files = list(download_dir.glob("*waitlist*.json")) + list(download_dir.glob("*removal*.json"))
    
    all_files = excel_files + json_files
    
    if not all_files:
        logger.warning("No files found to validate")
        return 0
    
    logger.info(f"Found {len(all_files)} files to validate")
    
    validations = {}
    for file_path in all_files:
        if file_path.suffix.lower() in ['.xlsx', '.xls']:
            validation = validator.validate_excel_file(str(file_path))
        else:
            validation = validator.validate_json_file(str(file_path))
        
        validations[file_path.name] = validation
        
        if validation['valid']:
            logger.info(f"Success: {file_path.name}: Valid ({validation.get('total_rows', 'N/A')} rows)")
        else:
            logger.error(f"Error: {file_path.name}: Invalid - {validation['error']}")
    
    # Generate report
    report = validator.generate_validation_report(validations)
    logger.info("\n" + report)
    
    # Save report
    report_path = download_dir / f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_path, 'w') as f:
        f.write(report)
    
    logger.info(f"Validation report saved to: {report_path}")
    
    return 0


def show_access_info(config: ConfigManager) -> int:
    """Show Access database information"""
    logger = setup_logging(log_level='INFO')
    logger.info("Access Database Information")
    logger.info("="*40)
    
    try:
        access_manager = AccessDatabaseManager(config)
        db_info = access_manager.get_database_info()
        
        logger.info(f"Database Path: {db_info['database_path']}")
        logger.info(f"Access Executable: {db_info['access_exe_path']}")
        logger.info(f"Database Exists: {db_info['database_exists']}")
        logger.info(f"Access Executable Exists: {db_info['access_exe_exists']}")
        
        if db_info['database_exists']:
            logger.info(f"Database Size: {db_info['database_size']:,} bytes")
            if db_info['last_modified']:
                logger.info(f"Last Modified: {db_info['last_modified']}")
        
        logger.info("\nAvailable Macros:")
        macros = access_manager.list_available_macros()
        for macro in macros:
            logger.info(f"  - {macro}")
        
        # Test connection
        if access_manager.check_database_connection():
            logger.info("\nDatabase connection: Success")
        else:
            logger.error("\nDatabase connection: Failed")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error getting Access info: {e}")
        return 1


def execute_access_macro(macro_name: str, config: ConfigManager) -> int:
    """Execute a specific Access macro"""
    logger = setup_logging(log_level='INFO')
    logger.info(f"Executing Access Macro: {macro_name}")
    logger.info("="*40)
    
    try:
        access_manager = AccessDatabaseManager(config)
        
        # Check if database and Access executable exist
        db_info = access_manager.get_database_info()
        
        if not db_info['database_exists']:
            logger.error(f"Database not found at: {db_info['database_path']}")
            return 1
            
        if not db_info['access_exe_exists']:
            logger.error(f"Microsoft Access not found at: {db_info['access_exe_path']}")
            return 1
        
        # Check if backup is configured
        if config.get('access_config.backup_before_macro', False):
            logger.info("Creating database backup...")
            backup_path = access_manager.backup_database()
            if backup_path:
                logger.info(f"Backup created: {backup_path}")
            else:
                logger.warning("Failed to create backup, continuing anyway...")
        
        # Execute the macro
        logger.info(f"Executing macro '{macro_name}'...")
        success = access_manager.run_macro(macro_name)
        
        if success:
            logger.info(f"[SUCCESS] Macro '{macro_name}' executed successfully")
            return 0
        else:
            logger.error(f"[FAILED] Macro '{macro_name}' execution failed")
            return 1
            
    except Exception as e:
        logger.error(f"Error executing Access macro: {e}")
        return 1


def handle_waitlist_summary(automation, config) -> int:
    """Handle waitlist summary request"""
    logger = setup_logging(log_level='INFO')
    
    try:
        summary = automation.get_waitlist_summary()
        if summary:
            logger.info("\nWaitlist Summary")
            logger.info("="*40)
            logger.info(f"Program: {summary['program_name']}")
            logger.info(f"Total Divisions: {summary['total_divisions']}")
            logger.info(f"Divisions with Waitlists: {summary['divisions_with_waitlists']}")
            logger.info(f"Total Waitlist Participants: {summary['total_waitlist_participants']}")
            
            if summary['divisions']:
                logger.info("\nDivisions with Waitlists:")
                for division in summary['divisions']:
                    logger.info(f"  - {division['divisionName']}: {division['waitlist']} participants")
            
            return 0
        else:
            logger.error("Failed to get waitlist summary")
            return 1
            
    except Exception as e:
        logger.error(f"Error getting waitlist summary: {e}")
        return 1


def show_waitlist_sheet_decisions(config: ConfigManager) -> int:
    """Show waitlist decisions from Google Sheet"""
    logger = setup_logging(log_level='INFO')
    
    try:
        from integrations.google_sheets_waitlist import GoogleSheetsWaitlistReader
        
        logger.info("Reading Waitlist Decisions from Google Sheet")
        logger.info("="*50)
        
        waitlist_config = config.get('waitlist_config', {})
        google_sheet_id = waitlist_config.get('google_sheet_id', '1wraHRkpi2HkhKClP5KMQmAflntsC-V3PQVW5S7QGav8')
        
        # Create reader and get decisions
        reader = GoogleSheetsWaitlistReader(google_sheet_id)
        decisions = reader.read_waitlist_decisions()
        
        # Display results
        logger.info(f"\nGoogle Sheet ID: {google_sheet_id}")
        logger.info(f"\nDecisions Summary:")
        logger.info(f"  - Remove from waitlist: {len(decisions['remove'])} participants")
        logger.info(f"  - Keep on waitlist: {len(decisions['keep'])} participants")
        logger.info(f"  - No response: {len(decisions['no_response'])} participants")
        
        if decisions['remove']:
            logger.info(f"\nOrder Numbers to Remove:")
            for order in decisions['remove']:
                logger.info(f"  - {order}")
        
        if decisions['keep']:
            logger.info(f"\nOrder Numbers to Keep:")
            for order in decisions['keep']:
                logger.info(f"  - {order}")
                
        if decisions['no_response']:
            logger.info(f"\nNo Response:")
            for order in decisions['no_response']:
                logger.info(f"  - {order}")
        
        # Save summary
        summary_path = reader.save_decisions_summary(decisions)
        if summary_path:
            logger.info(f"\nSummary saved to: {summary_path}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error reading waitlist sheet: {e}")
        return 1


def show_waitlist_tracking_status(config: ConfigManager) -> int:
    """Show waitlist notification tracking status"""
    logger = setup_logging(log_level='INFO')
    
    try:
        from automation.waitlist_persistence import WaitlistResponseTracker
        
        logger.info("Waitlist Notification Tracking Status")
        logger.info("="*50)
        
        # Create tracker
        tracker = WaitlistResponseTracker()
        
        # Generate and display summary report
        report = tracker.generate_summary_report()
        logger.info("\n" + report)
        
        # Show recent confirmations
        confirmed = tracker.get_confirmed_participants(days_valid=7)
        if confirmed:
            logger.info(f"\nRecent Confirmations (last 7 days): {len(confirmed)}")
            for p in confirmed[:5]:
                logger.info(f"  - {p['player_name']} ({p['division']}) - Order: {p['order_number']}")
        
        # Show pending responses
        pending = tracker.get_pending_responses()
        if pending:
            logger.info(f"\nPending Responses: {len(pending)}")
            for p in pending[:5]:
                if p['days_waiting'] > 3:
                    logger.warning(f"  - {p['player_name']} ({p['division']}) - {p['days_waiting']} days waiting")
        
        # Export option
        if input("\nExport tracking data to CSV? (y/n): ").lower() == 'y':
            csv_path = tracker.export_to_csv()
            logger.info(f"Exported to: {csv_path}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error showing tracking status: {e}")
        return 1


def handle_waitlist_removal(automation, order_numbers, config) -> int:
    """Handle waitlist removal from command line"""
    logger = setup_logging(log_level='INFO')
    
    try:
        logger.info(f"Starting waitlist removal...")
        
        program_id = config.get('program_id')
        program_name = config.get('program_name', '2025 Fall Core')
        
        if not program_id:
            logger.error("Program ID not configured")
            return 1
        
        # Check if we should use Google Sheets
        waitlist_config = config.get('waitlist_config', {})
        use_google_sheet = waitlist_config.get('use_google_sheet', False)
        
        # If no order numbers provided via command line and Google Sheets is enabled
        if not order_numbers and use_google_sheet:
            logger.info("No order numbers provided, reading from Google Sheet...")
            try:
                from integrations.google_sheets_waitlist import GoogleSheetsWaitlistReader
                google_sheet_id = waitlist_config.get('google_sheet_id', '1wraHRkpi2HkhKClP5KMQmAflntsC-V3PQVW5S7QGav8')
                sheets_reader = GoogleSheetsWaitlistReader(google_sheet_id)
                order_numbers = sheets_reader.get_removal_list()
                
                if not order_numbers:
                    logger.error("No removal orders found in Google Sheet")
                    return 1
                    
                logger.info(f"Found {len(order_numbers)} order numbers to remove from Google Sheet")
            except Exception as e:
                logger.error(f"Failed to read from Google Sheet: {e}")
                return 1
        
        if not order_numbers:
            logger.error("No order numbers to process")
            return 1
            
        logger.info(f"Processing removal for order numbers: {order_numbers}")
        
        waitlist_manager = WaitlistManager(automation.driver, automation.config.base_url, 
                                         automation.config.organization_id, automation.config)
        
        results = waitlist_manager.process_all_divisions(program_id, order_numbers, program_name)
        
        # Save results
        results_file = waitlist_manager.save_results(results, order_numbers, config.download_dir)
        
        # Log summary
        total_removed = sum(r['removed'] for r in results)
        successful_divisions = len([r for r in results if r['status'] == 'success'])
        
        logger.info("\nWaitlist Removal Summary")
        logger.info("="*40)
        logger.info(f"Order Numbers Processed: {', '.join(order_numbers)}")
        logger.info(f"Total Participants Removed: {total_removed}")
        logger.info(f"Successful Divisions: {successful_divisions}/{len(results)}")
        logger.info(f"Results saved to: {results_file}")
        
        # Show detailed results
        for result in results:
            status_symbol = "Success" if result['status'] == 'success' else "Error" if result['status'] == 'error' else "Warning"
            logger.info(f"{status_symbol}: {result['division']}: {result['removed']} removed")
            
            if result.get('participants'):
                for participant in result['participants']:
                    logger.info(f"  - {participant['name']} (Order: {participant['order']})")
        
        return 0 if total_removed > 0 else 1
        
    except Exception as e:
        logger.error(f"Error in waitlist removal: {e}")
        return 1


def handle_waitlist_notifications(config: ConfigManager) -> int:
    """Handle sending waitlist notifications"""
    logger = setup_logging(log_level='INFO')
    
    try:
        from automation.waitlist_notifier import WaitlistNotifier
        from automation.sports_connect import SportsConnectAutomation
        from automation.report_handlers import ReportType
        
        logger.info("Starting Waitlist Notification Process")
        logger.info("="*50)
        
        # Check email configuration
        email_config = config.get('email_config', {})
        if not email_config.get('enabled', False):
            logger.error("Email notifications are not enabled in configuration")
            return 1
        
        email_method = email_config.get('method', 'oauth2')
        
        if email_method == 'smtp':
            # Check SMTP credentials
            if not email_config.get('sender_email') or not email_config.get('sender_password'):
                logger.error("Email credentials not configured for SMTP method")
                logger.info("Please configure 'sender_email' and 'sender_password' in email_config")
                logger.info("To use App Passwords, you need 2-Step Verification enabled on your Google account")
                return 1
        else:
            # Check OAuth2 setup
            if not os.path.exists('gmail_credentials.json'):
                logger.error("Gmail OAuth2 credentials not found")
                logger.info("Please run: python -m integrations.gmail_oauth")
                logger.info("This will guide you through setting up Gmail API access")
                return 1
        
        google_form_url = email_config.get('google_form_url', '')
        if not google_form_url:
            logger.error("Google Form URL not configured")
            logger.info("Please configure 'google_form_url' in email_config")
            return 1
        
        # First, download the waitlist report
        logger.info("Downloading waitlist report...")
        
        automation = None
        try:
            # Initialize automation
            automation = SportsConnectAutomation(config)
            automation.initialize()
            
            # Login
            if not automation.login():
                logger.error("Login failed")
                return 1
            
            # Export waitlist report
            waitlist_file = automation.export_report(ReportType.WAITLIST_REPORT)
            
            if not waitlist_file:
                logger.error("Failed to download waitlist report")
                return 1
                
            logger.info(f"Waitlist report downloaded: {waitlist_file}")
            
        finally:
            if automation:
                automation.cleanup()
        
        # Create notifier
        notifier = WaitlistNotifier(config)
        
        # Test mode check
        if email_config.get('test_mode', False):
            logger.warning("TEST MODE ENABLED - Emails will be sent to test address only")
            logger.info(f"Test email: {email_config.get('test_email', 'Not configured')}")
            
            # Send test email
            if input("Send test email? (y/n): ").lower() == 'y':
                if notifier.send_test_email(google_form_url):
                    logger.info("Test email sent successfully")
                else:
                    logger.error("Test email failed")
                    return 1
        
        # Get notification parameters
        notification_config = config.get('waitlist_notification_config', {})
        division_filter = notification_config.get('divisions_to_notify')
        if division_filter and division_filter != 'all':
            division_filter = division_filter if isinstance(division_filter, list) else [division_filter]
        else:
            division_filter = None
        
        max_emails = notification_config.get('max_emails_per_run')
        
        # Confirm before sending
        if not email_config.get('test_mode', False):
            logger.warning("PRODUCTION MODE - Emails will be sent to actual recipients")
            if input("Continue with sending notifications? (y/n): ").lower() != 'y':
                logger.info("Notification process cancelled")
                return 0
        
        # Send notifications
        results = notifier.send_waitlist_notifications(
            waitlist_file,
            google_form_url,
            division_filter,
            max_emails
        )
        
        # Display results
        logger.info("\nNotification Results")
        logger.info("="*40)
        logger.info(f"Total Processed: {results['total_processed']}")
        logger.info(f"Emails Sent: {results['sent_count']}")
        logger.info(f"Failed: {results['failed_count']}")
        
        return 0 if results['sent_count'] > 0 else 1
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure waitlist_notifier.py is in src/automation/")
        return 1
    except Exception as e:
        logger.error(f"Error in waitlist notifications: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())