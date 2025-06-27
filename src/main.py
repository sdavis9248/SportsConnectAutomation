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
  python main.py MEDICAL_FORMS             # Download medical forms for all teams
  python main.py WAITLIST_MANAGEMENT       # Run waitlist management
  python main.py --headless                # Run in headless mode
  python main.py --no-upload               # Skip Google Drive upload
  python main.py --no-access               # Skip Access database operations
  python main.py --validate-only           # Only validate existing reports
  python main.py --waitlist-summary        # Get waitlist summary only
  python main.py --access-info             # Show Access database info      """
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
    parser.add_argument('--waitlist-removal', nargs='+', metavar='ORDER_NUM',
                       help='Remove participants by order numbers from waitlists')
    
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
    logger.info("="*60)
    
    # Check credentials
    if not args.validate_only and not args.access_info:
        if not CredentialsManager.check_credentials_exist(config.credentials_file):
            logger.error(f"Credentials file not found: {config.credentials_file}")
            logger.info("Run 'python -m utilities.credentials' to set up credentials")
            return 1
    
    # Handle info-only operations
    if args.access_info:
        return show_access_info(config)
    
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
        if args.waitlist_removal:
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
                        logger.info(f"Success: {report_name}: Valid ({validation['total_rows']} rows)")
                    else:
                        logger.error(f"Error: {report_name}: Invalid - {validation['error']}")
        
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
        if not args.no_upload and config.get('google_drive_folder_id'):
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


def handle_waitlist_removal(automation, order_numbers, config) -> int:
    """Handle waitlist removal from command line"""
    logger = setup_logging(log_level='INFO')
    
    try:
        logger.info(f"Starting waitlist removal for order numbers: {order_numbers}")
        
        program_id = config.get('program_id')
        program_name = config.get('program_name', '2025 Fall Core')
        
        if not program_id:
            logger.error("Program ID not configured")
            return 1
        
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


if __name__ == "__main__":
    sys.exit(main())