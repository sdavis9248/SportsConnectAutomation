"""
Sports Connect Automation - Main Entry Point
Built for Visual Studio 2022
Updated with Sports Affinity, Waitlist Management, Medical Forms, and Payment Reminders integration
"""
import sys
import os
import argparse
import glob
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import ConfigManager
from automation.sports_connect import SportsConnectAutomation
from automation.report_handlers import ReportType
from automation.waitlist_manager import WaitlistManager
from automation.email_batch_manager import handle_email_batch
from automation.playmetrics_email_campaign import handle_pm_campaign
from automation.playmetrics_enrollment_report import handle_pm_report
from automation.playmetrics_download_manager import PlayMetricsDownloadManager, PlayMetricsExportType
from automation.payment_reminder_manager import PaymentReminderManager
from automation.game_card_processor import GameCardProcessor
from integrations.google_drive import GoogleDriveUploader
from integrations.volunteer_compliance_handler import VolunteerComplianceHandler
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
  python main.py MEDICAL_FORMS             # Download medical forms for all configured divisions
  python main.py WAITLIST_MANAGEMENT       # Run waitlist management (reads from Google Sheet if enabled)
  python main.py WAITLIST_REPORT           # Download waitlist report for notifications
  python main.py --headless                # Run in headless mode
  python main.py --upload                  # Enable Google Drive upload for downloaded reports
  python main.py --no-access               # Skip Access database operations
  python main.py --validate-only           # Only validate existing reports
  python main.py --waitlist-summary        # Get waitlist summary only
  python main.py --waitlist-sheet          # Show waitlist decisions from Google Sheet
  python main.py --waitlist-notify         # Send email notifications to waitlist participants
  python main.py --waitlist-removal        # Remove participants using Google Sheet data
  python main.py --waitlist-removal 12345  # Remove specific order number
  
  python main.py --medical-forms           # Download medical forms for all divisions
  python main.py --medical-forms 07UB      # Download medical forms for specific division
  python main.py --access-info             # Show Access database info
  python main.py --access-macro UpdateAdminDetail    # Execute specific Access macro
  python main.py --access-macro UpdateEnrollmentSummary  # Execute enrollment macro
  python main.py --coach-cache list                        # List all cached coach info
  python main.py --email-tracking stats                    # Show email statistics
  python main.py --coach-email-history email@example.com   # View coach email history
  python main.py --payment-reminders                       # Show payment reminder summary
  python main.py --send-payment-reminders                  # Send regular payment reminders
  python main.py --send-payment-reminders --final-notice   # Send final payment notices
  python main.py --payment-interactive                     # Interactive payment reminder mode
  python main.py --payment-stats                           # Show payment reminder statistics
  python main.py --payment-holds                           # Interactive payment holds management
  python main.py --list-holds                              # List all active payment holds
  python main.py --add-hold 124166154 --hold-reason "Waiting for sibling registration" --hold-days 7
  python main.py --remove-hold 124166154 --hold-reason "Payment received"
  
  python main.py --playmetrics-preview                         # Preview player export counts by division
  python main.py --playmetrics-players                         # Export all players to PlayMetrics CSV
  python main.py --playmetrics-players --exclude-unallocated   # Export only team-assigned players
  python main.py --playmetrics-coaches --team-info-file downloads/Volunteer_Details*.xlsx  # Export coaches
  python main.py TEAM_INFO                                     # Download team info report (saved/65588)
  
  python main.py --pm-download                                 # Download all PM exports for enrollment summary
  python main.py --pm-download responses                       # Download registration responses only
  python main.py --pm-download volunteers                      # Download volunteer info only
  python main.py --pm-download coaching                        # Download coaching requests only
  python main.py --pm-status                                   # Show PM export file status
  
        """
    )
    
    parser.add_argument('report', nargs='?', help='Specific report to run')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--config', default='config/config.json', help='Config file path')
    parser.add_argument('--upload', action='store_true', help='Enable Google Drive upload')
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
    parser.add_argument('--waitlist-non-responders', 
                       choices=['summary', 'report', 'remove'],
                       help='Manage waitlist participants who have not responded')
    parser.add_argument('--non-response-days', 
                       type=int, 
                       default=3,
                       help='Days to wait before considering as non-responder (default: 3)')
    parser.add_argument('--auto-remove-non-responders', 
                       action='store_true',
                       help='Auto-confirm removal of non-responders')
    parser.add_argument('--medical-forms', nargs='*', metavar='DIVISION',
                       help='Download medical forms for specified divisions (all if none specified)',
                       default=None)
    parser.add_argument('--email-medical-forms', nargs='*', metavar='DIVISION',
                   help='Email medical forms to coaches (specify divisions or leave empty for all)',
                   default=None)
    parser.add_argument('--email-team-medical-forms', metavar='TEAM_PREFIX',
                   help='Email medical forms to a specific team (e.g., "16UB-01 Hart")')
    parser.add_argument('--send-to-dc', action='store_true',
                   help='CC the division coordinator on medical forms emails')
    parser.add_argument('--dry-run', action='store_true',
                   help='Perform dry run without sending emails')
    parser.add_argument('--coach-cache', choices=['list', 'export', 'stats'],
                   help='Manage coach cache (list all, export to CSV, show statistics)')
    parser.add_argument('--email-tracking', choices=['stats', 'recent', 'failed', 'export', 'report'],
                       help='View email tracking information')
    parser.add_argument('--coach-email-history', metavar='EMAIL',
                       help='View email history for a specific coach email')
    # batch emailer for divisions
    parser.add_argument(
        '--email-batch',
        action='store_true',
        help='Run interactive email batch sender for division-specific emails'
    )
    parser.add_argument(
        '--email-batch-test',
        action='store_true',
        help='Run email batch sender in test mode (no emails sent)'
    )
    parser.add_argument('--pm-campaign', action='store_true',
                       help='Run PlayMetrics migration email campaign')
   
    parser.add_argument('--pm-test', action='store_true',
                       help='Run PM campaign in test mode (no emails sent)')
    parser.add_argument('--pm-campaign-status', action='store_true',
                       help='Show PM campaign status and registration conversion')
    parser.add_argument('--pm-export', action='store_true',
                       help='Export PM campaign registration tracking to CSV')
    
    parser.add_argument('--pm-report', action='store_true',
                       help='Generate PlayMetrics enrollment summary report')
    parser.add_argument('--pm-report-output', type=str, default=None,
                       help='Output path for PM enrollment report (default: data/)')
    
    # Payment reminder arguments
    parser.add_argument('--payment-reminders', action='store_true',
                       help='Show payment reminder summary')
    parser.add_argument('--send-payment-reminders', action='store_true',
                       help='Send payment reminders')
    parser.add_argument('--payment-interactive', action='store_true',
                       help='Run payment reminders in interactive mode')
    parser.add_argument('--payment-stats', action='store_true',
                       help='Show payment reminder statistics')
    parser.add_argument('--payment-cancellation-ready', action='store_true',
                       help='Show orders ready for cancellation')
    parser.add_argument('--payment-export', metavar='FILE',
                       help='Export payment reminder report to file')
    parser.add_argument('--final-notice', action='store_true',
                       help='Send final notices instead of regular reminders (use with --send-payment-reminders)')
    parser.add_argument('--payment-test-mode', action='store_true',
                       help='Test mode for payment reminders - no emails actually sent')
    parser.add_argument('--payment-limit', type=int, metavar='N',
                       help='Limit number of payment reminder emails to send')
    parser.add_argument('--days-after-final', type=int, default=2,
                       help='Days after final notice before cancellation (default: 2)')
    parser.add_argument('--open-orders-file', metavar='FILE',
                       help='Path to Open Orders Line Item file for payment reminders')
    # Payment holds arguments
    parser.add_argument('--payment-holds', action='store_true',
                       help='Manage payment holds')
    parser.add_argument('--add-hold', metavar='ORDER_NO',
                       help='Add payment hold for specific order')
    parser.add_argument('--remove-hold', metavar='ORDER_NO',
                       help='Remove payment hold for specific order')
    parser.add_argument('--list-holds', action='store_true',
                       help='List all active payment holds')
    parser.add_argument('--hold-reason', metavar='REASON',
                       help='Reason for adding payment hold (use with --add-hold)')
    parser.add_argument('--hold-days', type=int, metavar='DAYS',
                       help='Number of days to hold (use with --add-hold)')
    # Game card processor
    parser.add_argument('--process-game-card', 
                       help='Process league game card with upper division details',
                       nargs='?', const='auto', metavar='GAME_CARD_PATH')

    parser.add_argument('--process-game-card-division',
                       help='Process a single division on game card (e.g., 16UG)',
                       metavar='DIVISION')

    parser.add_argument('--game-card-summary',
                       help='Generate summary report for upper divisions',
                       action='store_true')
    parser.add_argument('--prepare-game-card',
                       help='Show instructions for preparing game card sheets',
                       action='store_true')
    # PlayMetrics export arguments
    parser.add_argument('--playmetrics-players', action='store_true',
                       help='Export players to PlayMetrics CSV format')
    parser.add_argument('--playmetrics-coaches', action='store_true',
                       help='Export coaches to PlayMetrics CSV format')
    parser.add_argument('--playmetrics-preview', action='store_true',
                       help='Preview PlayMetrics player export without writing file')
    parser.add_argument('--playmetrics-file', metavar='FILE',
                       help='Enrollment_Details file to use for PlayMetrics export')
    parser.add_argument('--team-info-file', metavar='FILE',
                       help='Team info file for PlayMetrics coach export (saved report 65588)')
    parser.add_argument('--exclude-unallocated', action='store_true',
                       help='Exclude unallocated players from PlayMetrics export')
    parser.add_argument('--playmetrics-output', metavar='FILE',
                       help='Output file path for PlayMetrics export')
    # PlayMetrics download arguments (from PlayMetrics admin site)
    parser.add_argument('--pm-download', nargs='?', const='all',
                       choices=['all', 'responses', 'volunteers', 'coaching', 'packages'],
                       help='Download PlayMetrics CSV exports (default: all)')
    parser.add_argument('--pm-status', action='store_true',
                       help='Show PlayMetrics export file status')
    parser.add_argument('--pm-setup', action='store_true',
                       help='First-run setup: login with SMS code to establish device trust')
    # Volunteers
    parser.add_argument('--update-volunteer-compliance', 
                        action='store_true',
                        help='Update volunteer compliance tracking after downloading reports')
    parser.add_argument('--compliance-only',
                        action='store_true', 
                        help='Only update volunteer compliance without downloading new reports')
    parser.add_argument('--no-compliance',
                    action='store_true',
                    help='Skip volunteer compliance tracking update')
    # eTrainu event scraper
    parser.add_argument('ETRAINU', nargs='?', help='Run ETrainU volunteer-course matching')
    parser.add_argument('--etrainu', action='store_true', 
                       help='Run ETrainU volunteer-course matching analysis')
    parser.add_argument('--etrainu-live', action='store_true',
                   help='Use live ETrainU site scraping instead of HTML file')
    parser.add_argument('--etrainu-html', default='data/etrainu.html',
                       help='Path to etrainu.html file')
    parser.add_argument('--etrainu-data', default='data',
                       help='Directory containing volunteer Excel files')
    # Registrar inbox assistant
    parser.add_argument('--inbox', action='store_true',
                        help='Process registrar inbox with AI assistant')
    parser.add_argument('--inbox-days', type=int, default=3,
                        help='Days to look back for emails (default: 3)')
    parser.add_argument('--inbox-max', type=int, default=20,
                        help='Max emails to process per run (default: 20)')
    parser.add_argument('--inbox-test', action='store_true',
                        help='Test mode - analyze without creating drafts')
    parser.add_argument('--inbox-stats', action='store_true',
                        help='Show inbox processing statistics')
    parser.add_argument('--inbox-review', action='store_true',
                        help='Review pending draft responses')
    parser.add_argument('--inbox-learn', action='store_true',
                        help='Learn response style from sent emails')
    parser.add_argument('--inbox-learn-days', type=int, default=365,
                        help='Days of sent email history to analyze (default: 365)')
    parser.add_argument('--inbox-learn-max', type=int, default=500,
                        help='Max sent emails to harvest (default: 500)')
    
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
    if not args.validate_only and not args.access_info and not args.waitlist_sheet \
            and not args.playmetrics_players and not args.playmetrics_coaches \
            and not args.playmetrics_preview \
            and not args.pm_download and not args.pm_status and not args.pm_setup \
            and not args.inbox and not args.inbox_stats and not args.inbox_review and not args.inbox_learn:
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

    # Maintain coach cache
    if args.coach_cache:
        return handle_coach_cache(args.coach_cache, config)

    # Handle email batch operations
    if args.email_batch or args.email_batch_test:
        if args.email_batch_test:
            # Set test mode in args
            args.test_mode = True
        return handle_email_batch(config, args)
    
    # Handle PlayMetrics campaign operations
    if args.pm_campaign or args.pm_campaign_status:
        return handle_pm_campaign(config, args)
    
    if args.pm_report:
        return handle_pm_report(config, args)

    # Handle PlayMetrics admin downloads
    if args.pm_download is not None or args.pm_status or args.pm_setup:
        return handle_pm_downloads(config, args)

<<<<<<< HEAD
    if args.pm_push_sheets:
        from automation.playmetrics_sheets_publisher import PlayMetricsSheetsPublisher
 
        publisher = PlayMetricsSheetsPublisher(config=config)
        success = publisher.push_to_google_sheets(
            packages_file=args.packages_file,
            spreadsheet_id=args.sheet_id,
            include_history=not args.no_history,
        )
        if success:
            print("✅ Dashboard data pushed to Google Sheets")
        else:
            print("❌ Failed to push dashboard data")
            sys.exit(1)
        return

=======
>>>>>>> origin/master
    # Coach email tracking
    if args.email_tracking:
        return handle_email_tracking(args.email_tracking)

    # Handle coach email history
    if args.coach_email_history:
        return handle_coach_email_history(args.coach_email_history, config)

    # Handle inbox assistant
    if args.inbox or args.inbox_stats or args.inbox_review or args.inbox_learn:
        from automation.registrar_email_assistant import handle_inbox_assistant
        return handle_inbox_assistant(config, args)
    
    # Handle PlayMetrics exports
    if any([args.playmetrics_players, args.playmetrics_coaches, args.playmetrics_preview]):
        return handle_playmetrics_export(config, args)

    # Handle payment holds operations
    if any([args.payment_holds, args.add_hold, args.remove_hold, args.list_holds]):
        return handle_payment_holds(config, args)   

     # Handle payment reminder operations
    if any([args.payment_reminders, args.send_payment_reminders, args.payment_interactive,
            args.payment_stats, args.payment_cancellation_ready, args.payment_export]):
        return handle_payment_reminders(config, args)
 
    if args.prepare_game_card:
        processor = GameCardProcessor(config)
        print(processor.create_game_card_instructions())
        return 0

    # Handle single division processing
    if args.process_game_card_division:
        return handle_game_card_processing(
            config, 
            single_division=args.process_game_card_division
        )
    
    # Handle game card processing
    if args.process_game_card:
        return handle_game_card_processing(config, args.process_game_card)
    
    # Handle game card summary only
    if args.game_card_summary:
        try:
            processor = GameCardProcessor(config)
            summary = processor.generate_summary_report()
            
            logger.info("Upper Divisions Summary:")
            logger.info(f"Total players in upper divisions: {summary['total_players']}")
            
            for division, stats in summary['divisions'].items():
                logger.info(f"\n{division}:")
                logger.info(f"  Total players: {stats['total_players']}")
                logger.info(f"  Teams: {stats['teams']}")
                logger.info(f"  Players with jerseys: {stats['players_with_jerseys']}")
                logger.info(f"  Team breakdown:")
                for team, count in stats['teams_list'].items():
                    logger.info(f"    {team}: {count} players")
                    
            return 0
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return 1

    # Handle medical forms download from command line
    if args.medical_forms is not None:
        return handle_medical_forms_download(args.medical_forms, config)
    
    # Handle emailing medical forms to coaches
    if args.email_medical_forms is not None:
        divisions = args.email_medical_forms if args.email_medical_forms else None
        return handle_medical_forms_email(divisions, args.dry_run, args.send_to_dc, config)

    # Handle emailing medical forms to a specific team
    if args.email_team_medical_forms:
        return handle_team_medical_forms_email(args.email_team_medical_forms, args.dry_run, config)

    if args.compliance_only:
        return handle_volunteer_compliance_update(config)

    if args.etrainu:
        return handle_etrainu_standalone(config, args)

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

        if args.waitlist_non_responders:
            # Check if automation already exists in the current context
            existing_automation = locals().get('automation', None)
    
            return handle_waitlist_non_responders(
                config, 
                action=args.waitlist_non_responders,
                days=args.non_response_days,
                auto_remove=args.auto_remove_non_responders,
                existing_automation=existing_automation
            )
        
        # Run reports
        if args.report:
            # Run specific report
            # OPTION 2: Add ETrainU check here (AFTER automation is initialized)
            if args.report == 'ETRAINU':
                return handle_etrainu_with_automation(automation, config, args)

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
                    # Skip validation for medical forms (PDF/JSON files)
                    if report_name == 'MEDICAL_FORMS':
                        logger.info(f"✓ {report_name}: Completed (see results file)")
                        continue
                        
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
                'TEAM_DETAIL', 'VOLUNTEER_DETAIL', 'WAITLIST_REPORT', 'PLAYER_DETAIL', 
                'ENROLLMENT_SUMMARY', 'DIVISION_DETAILS', 'OPEN_ORDERS', 'SCHEDULE_MATCH'
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
                            
                            # Upload the enrollment summary file to Google Drive
                            if config.get('google_drive_config', {}).get('folder_id'):
                                logger.info("Uploading enrollment summary to Google Drive...")
                                upload_success = upload_enrollment_summary_to_drive(config, drive_uploader)
                                if not upload_success:
                                    logger.warning("Failed to upload enrollment summary to Google Drive")

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
        if args.upload and config.get('google_drive_config', {}).get('folder_id'):
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
        
        if args.upload and drive_uploader:
            logger.info(f"Reports Uploaded: {sum(1 for r in results.values() if r)}")
        
        logger.info("Success: Automation completed successfully!")
        
        return 0
        
    except Exception as e:
        logger.error(f"Automation failed: {e}", exc_info=True)
        return 1
        
    finally:
        if automation:
            automation.cleanup()

# Update volunteer compliance if enabled and reports were downloaded
    if (config.get('volunteer_compliance.enabled', False) and 
        not args.no_compliance and
        'downloaded_files' in locals()):
    
        with LogContext("Volunteer Compliance Update", logger):
            try:
                compliance_handler = VolunteerComplianceHandler(config)
            
                # Get paths to both reports if they were downloaded
                volunteer_report_path = downloaded_files.get('VOLUNTEER_DETAIL')
                admin_credentials_path = downloaded_files.get('ADMIN_CREDENTIALS')
            
                if volunteer_report_path:
                    logger.info("Updating volunteer compliance tracking...")
                
                    if compliance_handler.process_volunteer_report(volunteer_report_path, admin_credentials_path):
                        logger.info("✓ Volunteer compliance tracking updated successfully")
                    
                        # Show Google Sheets URL if using Google Sheets
                        if config.get('volunteer_compliance.use_google_sheets'):
                            sheet_id = config.get('volunteer_compliance.google_sheet_id')
                            if sheet_id:
                                logger.info(f"View at: https://docs.google.com/spreadsheets/d/{sheet_id}")
                    else:
                        logger.error("✗ Failed to update volunteer compliance tracking")
                else:
                    logger.warning("Volunteer Detail report not found, skipping compliance update")
                
            except Exception as e:
                logger.error(f"Error in volunteer compliance update: {e}")


def handle_coach_cache(action: str, config=None) -> int:
    """Handle coach cache management commands
    
    Args:
        action: Cache action to perform ('list', 'export', 'stats')
        config: Configuration manager instance
    """
    from automation.coach_cache_manager import CoachCacheManager
    
    manager = CoachCacheManager(config=config)
    
    if action == 'list':
        coaches = manager.get_all_coaches()
        print(f"\nCoach Cache ({len(coaches)} entries)")
        print("="*60)
        
        for key, coach in sorted(coaches.items()):
            print(f"{coach['division']:5} | {coach['team']:30} | {coach['coach_name']:25} | {coach['coach_email']}")
    
    elif action == 'export':
        csv_path = manager.export_to_csv()
        print(f"Exported to: {csv_path}")
    
    elif action == 'stats':
        stats = manager.get_statistics()
        print("\nCoach Cache Statistics")
        print("="*40)
        print(f"Total Coaches: {stats['total_coaches']}")
        print(f"Total Updates: {stats['total_updates']}")
        print(f"Coaches with History: {stats['coaches_with_history']}")
        print(f"Last Update: {stats['last_update']}")
        print("\nBy Division:")
        for div, count in sorted(stats['divisions'].items()):
            print(f"  {div}: {count}")
    
    return 0

def handle_email_tracking(action: str) -> int:
    """Handle email tracking commands
    
    Args:
        action: Tracking action to perform ('stats', 'recent', 'failed', 'export', 'report')
        
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    from automation.email_send_tracker import EmailSendTracker
    from datetime import datetime
    from automation.coach_cache_manager import CoachCacheManager
    from core.config import ConfigManager
    
    try:
        tracker = EmailSendTracker()
    except Exception as e:
        print(f"Error initializing EmailSendTracker: {e}")
        return 1
    
    # Initialize config for CoachCacheManager
    try:
        config = ConfigManager()
        config.load_config()
    except:
        config = None
    
    if action == 'stats':
        # Show email statistics - safely handle missing methods/data
        print("\nEmail Tracking Statistics")
        print("="*50)
        
        try:
            # Get statistics from the tracker
            if hasattr(tracker, 'get_statistics'):
                stats = tracker.get_statistics()
                
                # Display the basic statistics
                print(f"Total Emails Sent: {stats.get('total_sends', 0)}")
                print(f"Successful: {stats.get('successful_sends', 0)}")
                print(f"Failed: {stats.get('failed_sends', 0)}")
                print(f"Success Rate: {stats.get('success_rate', 0):.1f}%")
                print(f"Unique Coaches Emailed: {stats.get('unique_coaches', 0)}")
                
                # Display by email type
                by_type = stats.get('by_email_type', {})
                if by_type:
                    print("\nBy Email Type:")
                    for email_type, type_stats in by_type.items():
                        print(f"  {email_type}: {type_stats.get('sent', 0)} sent ({type_stats.get('success', 0)} successful)")
                
                # Get division data and coach cache data
                by_division = stats.get('by_division', {})
                
                # Try to get all divisions from coach cache
                all_divisions = set()
                divisions_coach_count = {}
                
                try:
                    coach_manager = CoachCacheManager(config=config)
                    all_coaches = coach_manager.get_all_coaches()
                    
                    for coach in all_coaches.values():
                        division = coach.get('division')
                        if division:
                            all_divisions.add(division)
                            divisions_coach_count[division] = divisions_coach_count.get(division, 0) + 1
                except Exception as e:
                    print(f"\nNote: Could not load full coach cache: {e}")
                    all_coaches = {}
                
                # Show medical forms specific stats if we have medical forms emails
                if 'medical_forms' in by_type:
                    print("\nMedical Forms Distribution:")
                    
                    # Get divisions that have received medical forms
                    divisions_with_medical = set(by_division.keys())
                    
                    if all_divisions:
                        divisions_without_medical = all_divisions - divisions_with_medical
                        print(f"  Divisions with forms sent: {len(divisions_with_medical)}")
                        print(f"  Divisions without forms: {len(divisions_without_medical)}")
                    else:
                        print(f"  Divisions with forms sent: {len(divisions_with_medical)}")
                    
                    # List divisions with medical forms sent
                    if by_division:
                        print("\n  Sent:")
                        for division in sorted(by_division.keys()):
                            div_stats = by_division[division]
                            sent = div_stats.get('sent', 0)
                            success = div_stats.get('success', 0)
                            failed = div_stats.get('failed', 0)
                            coach_count = divisions_coach_count.get(division, '?')
                            print(f"    {division}: {success} successful, {failed} failed (of {coach_count} coaches)")
                    
                    # List divisions WITHOUT medical forms
                    if all_divisions:
                        divisions_without_medical = all_divisions - divisions_with_medical
                        if divisions_without_medical:
                            print("\n  NOT Sent:")
                            for division in sorted(divisions_without_medical):
                                coach_count = divisions_coach_count.get(division, '?')
                                print(f"    {division}: 0 sent ({coach_count} coaches)")
                    
                    # Summary
                    if all_divisions:
                        print(f"\n  Summary:")
                        print(f"    Total divisions in system: {len(all_divisions)}")
                        print(f"    Divisions completed: {len(divisions_with_medical)} ({len(divisions_with_medical)/len(all_divisions)*100:.1f}%)")
                        print(f"    Divisions remaining: {len(divisions_without_medical)}")
                
                # Show recent activity if available
                recent = stats.get('recent_activity', {})
                if recent:
                    print("\nRecent Activity:")
                    print(f"  Last 24 hours: {recent.get('last_24h', 0)}")
                    print(f"  Last 7 days: {recent.get('last_7d', 0)}")
                    print(f"  Last 30 days: {recent.get('last_30d', 0)}")
                    
            else:
                print("Email tracking statistics not available.")
                
        except Exception as e:
            print(f"Error retrieving statistics: {e}")
            import traceback
            traceback.print_exc()
    
    elif action == 'recent':
        # Show recent emails
        print("\nRecent Email Sends")
        print("="*70)
        
        try:
            if hasattr(tracker, 'get_recent_sends'):
                recent = tracker.get_recent_sends(limit=20)
            elif hasattr(tracker, 'send_history'):
                # Get recent from raw data
                send_history = tracker.send_history if hasattr(tracker, 'send_history') else tracker.data.get('send_history', {})
                recent_items = sorted(send_history.items(), 
                                    key=lambda x: x[1].get('timestamp', ''), 
                                    reverse=True)[:20]
                recent = [item[1] for item in recent_items]
            else:
                recent = []
            
            if not recent:
                print("No recent email sends found.")
                return 0
            
            print(f"Showing last {len(recent)} emails:")
            for send in recent:
                status = "✓" if send.get('success', False) else "✗"
                timestamp = send.get('timestamp', 'Unknown time')[:19]  # Trim microseconds
                email_type = send.get('email_type', 'unknown')
                coach_info = send.get('coach_info', {})
                division = coach_info.get('division', 'N/A')
                team = coach_info.get('team', 'N/A')
                
                print(f"{status} {timestamp} | {email_type:15} | {division:5} | {team}")
                
                if not send.get('success', False):
                    error = send.get('error_message', 'Unknown error')
                    print(f"   Error: {error}")
                    
        except Exception as e:
            print(f"Error retrieving recent sends: {e}")
    
    elif action == 'failed':
        # Show failed emails
        print("\nFailed Email Sends")
        print("="*70)
        
        try:
            failed = []
            if hasattr(tracker, 'get_failed_sends'):
                failed = tracker.get_failed_sends()
            elif hasattr(tracker, 'send_history'):
                # Get failed from raw data
                send_history = tracker.send_history if hasattr(tracker, 'send_history') else tracker.data.get('send_history', {})
                failed = [record for record in send_history.values() if not record.get('success', False)]
            
            if not failed:
                print("No failed email sends found.")
                return 0
            
            print(f"Total failed: {len(failed)}")
            for send in failed:
                timestamp = send.get('timestamp', 'Unknown time')[:19]
                email_type = send.get('email_type', 'unknown')
                coach_info = send.get('coach_info', {})
                division = coach_info.get('division', 'N/A')
                team = coach_info.get('team', 'N/A')
                email = coach_info.get('coach_email', 'N/A')
                error = send.get('error_message', 'Unknown error')
                
                print(f"\n{timestamp} | {email_type}")
                print(f"  Division: {division} | Team: {team}")
                print(f"  Email: {email}")
                print(f"  Error: {error}")
                
        except Exception as e:
            print(f"Error retrieving failed sends: {e}")
    
    elif action == 'export':
        # Export tracking data to CSV
        try:
            if hasattr(tracker, 'export_to_csv'):
                export_path = tracker.export_to_csv()
                print(f"\nEmail tracking data exported to: {export_path}")
            else:
                print("Export functionality not available.")
                return 1
        except Exception as e:
            print(f"Error exporting data: {e}")
            return 1
    
    elif action == 'report':
        # Generate comprehensive report - focusing on medical forms
        print("\nEmail Tracking Report")
        print("="*70)
        print(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # Get all divisions from coach cache to compare
            all_divisions = set()
            try:
                coach_manager = CoachCacheManager(config=config)
                all_coaches = coach_manager.get_all_coaches()
                for coach in all_coaches.values():
                    division = coach.get('division')
                    if division:
                        all_divisions.add(division)
            except:
                all_coaches = {}
                print("Note: Could not load coach cache for complete division list")
            
            # Get email tracking data
            if hasattr(tracker, 'send_history'):
                send_history = tracker.send_history if hasattr(tracker, 'send_history') else tracker.data.get('send_history', {})
            else:
                send_history = {}
            
            # Calculate statistics
            medical_forms_by_division = {}
            total_medical_forms = 0
            successful_medical_forms = 0
            
            for record in send_history.values():
                if record.get('email_type') == 'medical_forms':
                    total_medical_forms += 1
                    if record.get('success', False):
                        successful_medical_forms += 1
                    
                    coach_info = record.get('coach_info', {})
                    division = coach_info.get('division', 'Unknown')
                    if division:
                        if division not in medical_forms_by_division:
                            medical_forms_by_division[division] = {'sent': 0, 'failed': 0, 'teams': set()}
                        
                        if record.get('success', False):
                            medical_forms_by_division[division]['sent'] += 1
                        else:
                            medical_forms_by_division[division]['failed'] += 1
                        
                        team = coach_info.get('team')
                        if team:
                            medical_forms_by_division[division]['teams'].add(team)
            
            # Display medical forms summary
            print("\nMedical Forms Email Summary:")
            print(f"  Total Attempts: {total_medical_forms}")
            print(f"  Successful: {successful_medical_forms}")
            print(f"  Failed: {total_medical_forms - successful_medical_forms}")
            
            if medical_forms_by_division:
                print("\n  Divisions with Emails Sent:")
                for division in sorted(medical_forms_by_division.keys()):
                    stats = medical_forms_by_division[division]
                    total = stats['sent'] + stats['failed']
                    teams_count = len(stats['teams'])
                    print(f"    {division}: {stats['sent']} sent, {stats['failed']} failed ({teams_count} teams)")
            
            # Show divisions without any emails (only if we have coach data)
            if all_divisions:
                divisions_without_emails = all_divisions - set(medical_forms_by_division.keys())
                if divisions_without_emails:
                    print("\n  Divisions WITHOUT Medical Forms Emails:")
                    for division in sorted(divisions_without_emails):
                        # Count coaches in this division
                        coach_count = sum(1 for coach in all_coaches.values() 
                                        if coach.get('division') == division)
                        print(f"    {division}: 0 sent ({coach_count} coaches in cache)")
                
                # Overall summary
                print(f"\n  Total Divisions: {len(all_divisions)}")
                print(f"  Divisions with Emails: {len(medical_forms_by_division)}")
                print(f"  Divisions without Emails: {len(divisions_without_emails)}")
            
        except Exception as e:
            print(f"Error generating report: {e}")
            import traceback
            traceback.print_exc()
    
    else:
        print(f"Unknown email tracking action: {action}")
        return 1
    
    return 0

def handle_coach_email_history(email: str, config=None) -> int:
    """View email history for a specific coach
    
    Args:
        email: Coach email address to search for
        config: Configuration manager instance
    """
    from automation.coach_cache_manager import CoachCacheManager
    from automation.email_send_tracker import EmailSendTracker
    
    coach_manager = CoachCacheManager(config=config)
    email_tracker = EmailSendTracker()
    
    # Find coach in cache
    coaches = coach_manager.search_coaches(email)
    
    if not coaches:
        print(f"No coach found with email: {email}")
        return 1
    
    # Show coach info and email history
    for cache_key, coach in coaches.items():
        print(f"\nCoach: {coach['coach_name']}")
        print(f"Team: {coach['team']} ({coach['division']})")
        print(f"Email: {coach['coach_email']}")
        print(f"Cache Key: {cache_key}")
        
        # Get email summary
        summary = email_tracker.get_coach_summary(cache_key)
        if summary:
            print(f"\nEmail Summary:")
            print(f"  First Contact: {summary['first_contact'][:19]}")
            print(f"  Last Contact: {summary['last_contact'][:19]}")
            print(f"  Total Emails: {summary['total_emails_sent']}")
            print(f"  Successful: {summary['successful_sends']}")
            print(f"  Failed: {summary['failed_sends']}")
            
            if summary['email_types']:
                print("\n  By Type:")
                for etype, data in summary['email_types'].items():
                    print(f"    {etype}: {data['count']} sent (last: {data['last_sent'][:19]})")
        
        # Get detailed history
        history = email_tracker.get_coach_send_history(cache_key)
        if history:
            print(f"\nEmail History ({len(history)} records):")
            for record in sorted(history, key=lambda x: x['timestamp'], reverse=True)[:10]:
                status = "✓" if record['success'] else "✗"
                print(f"  {status} {record['timestamp'][:19]} - {record['email_type']}")
                if not record['success']:
                    print(f"    Error: {record.get('error_message', 'Unknown')}")
    
    return 0


def handle_coach_email_history(email: str) -> int:
    """View email history for a specific coach"""
    from automation.coach_cache_manager import CoachCacheManager
    from automation.email_send_tracker import EmailSendTracker
    
    coach_manager = CoachCacheManager(config=config)
    email_tracker = EmailSendTracker()
    
    # Find coach in cache
    coaches = coach_manager.search_coaches(email)
    
    if not coaches:
        print(f"No coach found with email: {email}")
        return 1
    
    # Show coach info and email history
    for cache_key, coach in coaches.items():
        print(f"\nCoach: {coach['coach_name']}")
        print(f"Team: {coach['team']} ({coach['division']})")
        print(f"Email: {coach['coach_email']}")
        print(f"Cache Key: {cache_key}")
        
        # Get email summary
        summary = email_tracker.get_coach_summary(cache_key)
        if summary:
            print(f"\nEmail Summary:")
            print(f"  First Contact: {summary['first_contact'][:19]}")
            print(f"  Last Contact: {summary['last_contact'][:19]}")
            print(f"  Total Emails: {summary['total_emails_sent']}")
            print(f"  Successful: {summary['successful_sends']}")
            print(f"  Failed: {summary['failed_sends']}")
            
            if summary['email_types']:
                print("\n  By Type:")
                for etype, data in summary['email_types'].items():
                    print(f"    {etype}: {data['count']} sent (last: {data['last_sent'][:19]})")
        
        # Get detailed history
        history = email_tracker.get_coach_send_history(cache_key)
        if history:
            print(f"\nEmail History ({len(history)} records):")
            for record in sorted(history, key=lambda x: x['timestamp'], reverse=True)[:10]:
                status = "✓" if record['success'] else "✗"
                print(f"  {status} {record['timestamp'][:19]} - {record['email_type']}")
                if not record['success']:
                    print(f"    Error: {record.get('error_message', 'Unknown')}")
    
    return 0


def handle_payment_reminders(config: ConfigManager, args) -> int:
    """Handle payment reminder operations"""
    logger = setup_logging(log_level=args.log_level)
    
    try:
        from automation.payment_reminder_manager import PaymentReminderManager
        from automation.report_handlers import ReportType
        
        logger.info("Payment Reminder Manager")
        logger.info("="*50)
        
        # Create payment reminder manager
        reminder_manager = PaymentReminderManager(config)
        
        # Load open orders data
        if args.open_orders_file:
            success = reminder_manager.load_open_orders(args.open_orders_file)
        else:
            # Download fresh Open Orders report if requested or if sending reminders
            if args.send_payment_reminders and not args.payment_test_mode:
                logger.info("Downloading fresh Open Orders report...")
                automation = SportsConnectAutomation(config)
                try:
                    automation.initialize()
                    if not automation.login():
                        logger.error("Login failed")
                        return 1
                    
                    # Export Open Orders report
                    open_orders_file = automation.export_report(ReportType.OPEN_ORDERS)
                    
                    if open_orders_file:
                        logger.info(f"Downloaded Open Orders report: {open_orders_file}")
                        success = reminder_manager.load_open_orders(open_orders_file)
                    else:
                        logger.error("Failed to download Open Orders report")
                        return 1
                finally:
                    automation.cleanup()
            else:
                # Use latest existing file
                success = reminder_manager.load_open_orders()
        
        if not success:
            logger.error("Failed to load Open Orders data")
            return 1
        
        # Handle different operations
        if args.payment_interactive:
            # Interactive mode
            reminder_manager.interactive_reminder_session()
            
        elif args.send_payment_reminders:
            # Send reminders
            is_final = args.final_notice
            results = reminder_manager.send_payment_reminders(
                is_final_notice=is_final,
                test_mode=args.payment_test_mode,
                limit=args.payment_limit
            )
            
            if not results.get('cancelled', False):
                logger.info(f"Sent {results['sent']} reminders, {results['failed']} failed")
                
        elif args.payment_stats:
            # Show statistics
            stats = reminder_manager.get_reminder_statistics()
            print("\nPayment Reminder Statistics")
            print("=" * 40)
            print(f"Total reminders sent: {stats['total_reminders_sent']}")
            print(f"Regular reminders: {stats['regular_reminders']}")
            print(f"Final notices: {stats['final_notices']}")
            print(f"Unique orders: {stats['unique_orders']}")
            
            print("\nReminders by Division:")
            for division, count in sorted(stats['reminders_by_division'].items()):
                print(f"  {division}: {count}")
                
        elif args.payment_cancellation_ready:
            # Show orders ready for cancellation
            ready = reminder_manager.get_orders_ready_for_cancellation(args.days_after_final)
            if not ready.empty:
                print(f"\n{len(ready)} orders ready for cancellation:")
                for _, order in ready.iterrows():
                    print(f"Order {order['order_no']}: {order['player_first_name']} {order['player_last_name']} " \
                          f"({order['division_name']}) - ${order['order_item_balance']:.2f}")
            else:
                print("No orders ready for cancellation")
                
        elif args.payment_export:
            # Export report
            report_path = reminder_manager.export_reminder_report(args.payment_export)
            logger.info(f"Report exported to: {report_path}")
            
        else:
            # Default: show pending counts
            regular_pending = len(reminder_manager.get_pending_orders_for_notification(False))
            final_pending = len(reminder_manager.get_pending_orders_for_notification(True))
            
            print("\nPayment Reminder Summary")
            print("=" * 40)
            print(f"Open orders with balance due: {len(reminder_manager.open_orders_df)}")
            print(f"Regular reminders available: {regular_pending}")
            print(f"Final notices available: {final_pending}")
            print("\nUse --send-payment-reminders to send reminders")
            print("Use --payment-interactive for interactive mode")
        
        return 0
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure payment_reminder_manager.py is in src/automation/")
        return 1
    except Exception as e:
        logger.error(f"Error in payment reminder handling: {e}")
        import traceback
        traceback.print_exc()
        return 1

def handle_payment_holds(config: ConfigManager, args) -> int:
    """Handle payment holds operations"""
    logger = setup_logging(log_level=args.log_level)
    
    try:
        from automation.payment_reminder_manager import PaymentReminderManager
        
        logger.info("Payment Holds Management")
        logger.info("="*50)
        
        # Create payment reminder manager
        reminder_manager = PaymentReminderManager(config)
        
        # Load open orders to get player information
        if not reminder_manager.load_open_orders():
            logger.warning("Could not load Open Orders data - hold management will have limited info")
        
        # Handle specific operations
        if args.add_hold:
            # Add payment hold
            order_no = args.add_hold
            reason = args.hold_reason or "Hold added via CLI"
            
            # Calculate hold until date if days specified
            hold_until_date = None
            if args.hold_days:
                from datetime import datetime, timedelta
                hold_until_date = (datetime.now() + timedelta(days=args.hold_days)).isoformat()
            
            # Get player info if available
            player_info = None
            if reminder_manager.open_orders_df is not None:
                order_mask = reminder_manager.open_orders_df['Order No'].astype(str) == str(order_no)
                if order_mask.any():
                    player_info = reminder_manager.open_orders_df[order_mask].iloc[0].to_dict()
                    logger.info(f"Found order: {player_info['Player First Name']} {player_info['Player Last Name']} ({player_info['Division Name']})")
            
            # Add the hold
            if reminder_manager.add_payment_hold(order_no, reason, hold_until_date, player_info):
                logger.info(f"✓ Payment hold added for order {order_no}")
                if hold_until_date:
                    logger.info(f"  Hold expires: {hold_until_date[:10]}")
                return 0
            else:
                logger.error(f"Failed to add payment hold for order {order_no}")
                return 1
                
        elif args.remove_hold:
            # Remove payment hold
            order_no = args.remove_hold
            reason = args.hold_reason or "Hold removed via CLI"
            
            if reminder_manager.remove_payment_hold(order_no, reason):
                logger.info(f"✓ Payment hold removed for order {order_no}")
                return 0
            else:
                logger.error(f"Failed to remove payment hold for order {order_no}")
                return 1
                
        elif args.list_holds:
            # List all active holds
            active_holds = reminder_manager.get_all_active_holds()
            
            if not active_holds:
                logger.info("No active payment holds")
                return 0
            
            print(f"\nActive Payment Holds ({len(active_holds)} total)")
            print("=" * 80)
            
            for hold in active_holds:
                print(f"\nOrder: {hold['order_no']}")
                
                if 'player_first_name' in hold:
                    print(f"Player: {hold.get('player_first_name', '')} {hold.get('player_last_name', '')}")
                    print(f"Division: {hold.get('division_name', 'Unknown')}")
                    print(f"Email: {hold.get('user_email', 'Unknown')}")
                
                print(f"Reason: {hold['reason']}")
                print(f"Added: {hold['hold_date'][:19]}")
                
                if hold.get('hold_until_date'):
                    print(f"Expires: {hold['hold_until_date'][:19]}")
                else:
                    print(f"Expires: No expiration (indefinite)")
                
                print("-" * 40)
            
            return 0
            
        else:
            # Interactive mode
            reminder_manager.interactive_reminder_session()
            return 0
            
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Error in payment holds handling: {e}")
        import traceback
        traceback.print_exc()
        return 1
   
def handle_medical_forms_download(divisions, config) -> int:
    """Handle medical forms download from command line"""
    logger = setup_logging(log_level='INFO')
    
    try:
        from automation.medical_forms_manager import MedicalFormsManager
        from automation.sports_connect import SportsConnectAutomation
        
        logger.info("Starting Medical Forms Download")
        logger.info("="*50)
        
        # Check if medical forms are enabled
        medical_config = config.get('medical_forms_config', {})
        if not medical_config.get('enabled', False):
            logger.error("Medical forms download is not enabled in configuration")
            logger.info("Set 'medical_forms_config.enabled' to true in config.json")
            return 1
        
        # Get divisions to process
        if divisions:
            # Specific divisions provided
            divisions_to_process = divisions
            logger.info(f"Processing specified divisions: {', '.join(divisions)}")
        else:
            # Use configured divisions
            divisions_to_process = medical_config.get('divisions', ['07UB'])
            logger.info(f"Processing configured divisions: {', '.join(divisions_to_process)}")
        
        if not divisions_to_process:
            logger.error("No divisions specified for medical forms download")
            return 1
        
        # Initialize automation and login
        automation = None
        try:
            automation = SportsConnectAutomation(config)
            automation.initialize()
            
            if not automation.login():
                logger.error("Login failed")
                return 1
            
            # Create medical forms manager
            medical_manager = MedicalFormsManager(automation.driver, config, already_logged_in=True)
            
            # Navigate to Sports Affinity
            if not medical_manager.navigate_to_sports_affinity():
                logger.error("Failed to navigate to Sports Affinity")
                return 1
            
            # Process all divisions
            results = medical_manager.process_all_divisions(divisions_to_process)
            
            # Save results summary
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = os.path.join(config.download_dir, f"medical_forms_results_{timestamp}.json")
            
            import json
            with open(results_file, "w") as f:
                json.dump(results, f, indent=2)
            
            # Display summary
            logger.info("\nMedical Forms Download Summary")
            logger.info("="*50)
            logger.info(f"Total divisions processed: {results['successful_divisions']}/{results['total_divisions']}")
            logger.info(f"Total teams processed: {results['total_teams_processed']}")
            logger.info(f"Results saved to: {results_file}")
            
            # Show detailed results with ASCII-safe characters
            logger.info("\nDetailed Results:")
            for division_result in results['division_results']:
                # Use ASCII-safe status indicators
                if division_result['status'] == 'success':
                    status_icon = "[OK]"
                elif division_result['status'] == 'no_teams':
                    status_icon = "[--]"
                else:
                    status_icon = "[XX]"
                    
                logger.info(f"{status_icon} {division_result['division']}: {division_result['teams_processed']} teams")
                if division_result.get('error'):
                    logger.error(f"  Error: {division_result['error']}")
            
            # Clean up
            medical_manager.cleanup()
            
            return 0 if results['successful_divisions'] > 0 else 1
            
        finally:
            if automation:
                automation.cleanup()
                
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure medical_forms_manager.py is in src/automation/")
        return 1
    except Exception as e:
        logger.error(f"Error in medical forms download: {e}")
        import traceback
        traceback.print_exc()
        return 1

# email medical forms to coaches
def handle_medical_forms_email(divisions, dry_run, send_to_dc, config) -> int:
    """Handle sending medical forms to coaches via email
    
    Args:
        divisions: List of divisions to process (None for all)
        dry_run: If True, don't actually send emails
        send_to_dc: If True, CC the division coordinator
        config: Configuration object
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    logger = setup_logging(log_level='INFO')
    
    try:
        from automation.medical_forms_emailer import MedicalFormsEmailer
        from automation.coach_cache_manager import CoachCacheManager
        
        logger.info("Starting Medical Forms Email Distribution")
        logger.info("="*50)
        
        # Check email configuration
        email_config = config.get('email_config', {})
        if not email_config.get('enabled', False):
            logger.error("Email notifications are not enabled in configuration")
            logger.info("Set 'email_config.enabled' to true in config.json")
            return 1
        
        # Check coach cache using the cache manager
        coach_cache_manager = CoachCacheManager(config=config)
        all_coaches = coach_cache_manager.get_all_coaches()
        
        if not all_coaches:
            logger.error("No coach information cached")
            logger.info("Run --medical-forms first to download forms and cache coach information")
            return 1
        
        # Show cache statistics
        stats = coach_cache_manager.get_statistics()
        logger.info(f"Coach cache contains {stats['total_coaches']} coaches across {len(stats['divisions'])} divisions")
        
        # Log if CC'ing division coordinators
        if send_to_dc:
            logger.info("Division coordinators will be CC'd on all emails")
        
        # Create emailer
        emailer = MedicalFormsEmailer(config)
        
        # Verify before sending
        division_filter = divisions if divisions else None
        verification = emailer.verify_coaches_before_sending(division_filter)
        
        logger.info(f"\nVerification Results for {verification['season']}:")
        logger.info(f"Total coaches to email: {len(verification['ready_to_send'])}")
        
        # Show division breakdown
        for division, stats in verification['divisions'].items():
            logger.info(f"  {division}: {stats['ready']}/{stats['total']} ready " +
                       f"({stats['with_email']} have email, {stats['with_forms']} have forms)")
            if send_to_dc:
                dc_email = f"{division}DivMgr@ayso58.org"
                logger.info(f"    Division Coordinator CC: {dc_email}")
        
        # Show coaches without email
        if verification['coaches_without_email']:
            logger.warning(f"\nCoaches without email ({len(verification['coaches_without_email'])}):")
            for coach in verification['coaches_without_email'][:5]:  # Show first 5
                logger.warning(f"  - {coach['team']} ({coach['division']}): {coach['coach']}")
            if len(verification['coaches_without_email']) > 5:
                logger.warning(f"  ... and {len(verification['coaches_without_email']) - 5} more")
        
        # Show coaches without forms
        if verification['coaches_without_forms']:
            logger.warning(f"\nCoaches without medical forms ({len(verification['coaches_without_forms'])}):")
            for coach in verification['coaches_without_forms'][:5]:  # Show first 5
                logger.warning(f"  - {coach['team']} ({coach['division']}): {coach['coach']}")
            if len(verification['coaches_without_forms']) > 5:
                logger.warning(f"  ... and {len(verification['coaches_without_forms']) - 5} more")
        
        # Confirm before sending
        if not dry_run and len(verification['ready_to_send']) > 0:
            logger.info(f"\nReady to send {len(verification['ready_to_send'])} emails")
            if send_to_dc:
                logger.info("Each email will be CC'd to the respective division coordinator")
            if input("Continue? (y/n): ").lower() != 'y':
                logger.info("Email process cancelled")
                return 0
        
        # Send test email if requested
        if email_config.get('test_mode', False):
            logger.warning("TEST MODE ENABLED - Emails will be sent to test address only")
            logger.info(f"Test email: {email_config.get('test_email', 'Not configured')}")
            
            if input("Send test email? (y/n): ").lower() == 'y':
                if emailer.send_test_email():
                    logger.info("Test email sent successfully!")
                else:
                    logger.error("Test email failed!")
                    return 1
                
                if input("Continue with full send? (y/n): ").lower() != 'y':
                    logger.info("Email process cancelled")
                    return 0
        
        # Send emails with the CC flag
        results = emailer.send_medical_forms_to_all_coaches(
            division_filter=division_filter,
            dry_run=dry_run,
            send_to_dc=send_to_dc  # Pass the new parameter
        )
        
        # Display results
        logger.info("\nEmail Distribution Results")
        logger.info("="*40)
        logger.info(f"Total Coaches: {results['total_processed']}")
        logger.info(f"Emails Sent: {results['sent_count']}")
        logger.info(f"Failed: {results['failed_count']}")
        if send_to_dc:
            logger.info(f"CC'd Division Coordinators: Yes")
        
        if dry_run:
            logger.info("\n*** DRY RUN - No emails were actually sent ***")
        
        # Show division summary
        logger.info("\nBy Division:")
        for division, stats in results['divisions_processed'].items():
            logger.info(f"  {division}: {stats['sent']}/{stats['total']} sent, {stats['failed']} failed")
            if send_to_dc:
                logger.info(f"    CC: {division}DivMgr@ayso58.org")
        
        # Show failed emails if any
        if results['failed_count'] > 0:
            logger.warning("\nFailed emails:")
            for failed in results['failed_emails']:
                logger.warning(f"  - {failed['email']} ({failed['team']}): {failed['error']}")
        
        # Save results
        if not dry_run and results['sent_count'] > 0:
            results_file = emailer.save_results(results)
            logger.info(f"\nResults saved to: {results_file}")
        
        return 0 if results['sent_count'] > 0 or dry_run else 1
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure medical_forms_emailer.py is in src/automation/")
        return 1
    except Exception as e:
        logger.error(f"Error in medical forms email: {e}")
        import traceback
        traceback.print_exc()
        return 1

# handler to send a single team to a coach (used for updates to roster specific to team)
def handle_team_medical_forms_email(team_prefix, dry_run, config) -> int:
    """Handle sending medical forms to a specific team via email"""
    logger = setup_logging(log_level='INFO')
    
    try:
        from automation.medical_forms_emailer import MedicalFormsEmailer
        from automation.coach_cache_manager import CoachCacheManager
        
        logger.info("Starting Team-Specific Medical Forms Email")
        logger.info("="*50)
        logger.info(f"Team: {team_prefix}")
        
        # Check email configuration
        email_config = config.get('email_config', {})
        if not email_config.get('enabled', False):
            logger.error("Email notifications are not enabled in configuration")
            logger.info("Set 'email_config.enabled' to true in config.json")
            return 1
        
        # Check coach cache
        coach_cache_manager = CoachCacheManager(config=config)
        all_coaches = coach_cache_manager.get_all_coaches()
        
        if not all_coaches:
            logger.error("No coach information cached")
            logger.info("Run --medical-forms first to download forms and cache coach information")
            return 1
        
        # Create emailer
        emailer = MedicalFormsEmailer(config)
        
        # Add the send_medical_forms_to_team method to the emailer if not already present
        if not hasattr(emailer, 'send_medical_forms_to_team'):
            logger.error("MedicalFormsEmailer does not have send_medical_forms_to_team method")
            logger.info("Please update MedicalFormsEmailer with the new method")
            return 1
        
        # ADDED: Prompt for reason
        logger.info("\nThis team is receiving medical forms outside the normal distribution.")
        reason = input("Please enter the reason (e.g., 'NEW PLAYER', 'UPDATED FORMS', 'REPLACEMENT'): ").strip()
        
        if not reason:
            logger.warning("No reason provided. Using default.")
            reason = "UPDATED FORMS"
        
        logger.info(f"Reason: {reason}")
        
        # Show what we're doing
        if dry_run:
            logger.info("DRY RUN MODE - No emails will be sent")
        else:
            # ADDED: Confirm before sending
            logger.info(f"\nReady to send medical forms to team: {team_prefix}")
            logger.info(f"Reason will be included in subject and email body: {reason}")
            if input("Continue? (y/n): ").lower() != 'y':
                logger.info("Email cancelled")
                return 0
        
        # Send to the specific team
        logger.info(f"Searching for team matching: {team_prefix}")
        
        # MODIFIED: Pass reason to the method
        results = emailer.send_medical_forms_to_team(team_prefix, dry_run=dry_run, reason=reason)
        
        # Display results
        logger.info("="*50)
        logger.info("Specific Medical Forms Email Send Results")
        logger.info("="*50)
        
        if results['sent_count'] > 0:
            logger.info(f"✓ Successfully sent: {results['sent_count']}")
            for item in results['sent_emails']:
                logger.info(f"  - {item['team']} ({item['division']}) -> {item['email']}")
                if dry_run:
                    logger.info("    (DRY RUN - not actually sent)")
                if reason:
                    logger.info(f"    Reason: {reason}")
        
        if results['failed_count'] > 0:
            logger.error(f"✗ Failed: {results['failed_count']}")
            for item in results['failed_emails']:
                logger.error(f"  - {item['team']} ({item.get('division', 'N/A')}) - {item.get('error', 'Unknown error')}")
        
        if results['sent_count'] == 0 and results['failed_count'] == 0:
            logger.warning("No teams found matching the specified prefix")
        
        return 0 if results['sent_count'] > 0 else 1
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure medical_forms_emailer.py is in src/automation/")
        return 1
    except Exception as e:
        logger.error(f"Error sending team medical forms: {e}")
        import traceback
        traceback.print_exc()
        return 1


def handle_game_card_processing(config, game_card_path=None, single_division=None):
    """
    Handle game card processing
    
    Args:
        config: Configuration manager
        game_card_path: Path to game card file or 'auto' to find it
        single_division: Process only this division (for sheets with graphics)
        
    Returns:
        0 for success, 1 for failure
    """
    try:
        logger = setup_logging(log_level='INFO')
        
        processor = GameCardProcessor(config)
        
        # If 'auto' or no path specified, try to find the game card
        if game_card_path == 'auto' or not game_card_path:
            # Look for game card files in download directory
            import glob
            import os
            
            download_dir = config.get('download_dir', 'data/downloads')
            pattern = os.path.join(download_dir, "*league*game*card.xlsx")
            files = glob.glob(pattern, recursive=False)
            
            if not files:
                logger.error("No game card file found. Please specify the path.")
                return 1
                
            # Use the most recent file
            game_card_path = max(files, key=os.path.getmtime)
            logger.info(f"Found game card: {game_card_path}")
        
        # Process single division if specified
        if single_division:
            result = processor.process_game_card_single_sheet(
                game_card_path, 
                single_division
            )
            if result:
                logger.info(f"Successfully processed {single_division}: {result}")
                return 0
            else:
                logger.error(f"Failed to process {single_division}")
                return 1
        
        # Process all divisions
        result = processor.process_game_card(game_card_path)
        
        if result:
            logger.info(f"Successfully processed game card: {result}")
            
            # Generate summary
            summary = processor.generate_summary_report()
            logger.info(f"Upper divisions summary:")
            logger.info(f"  Total players: {summary['total_players']}")
            for division, stats in summary['divisions'].items():
                logger.info(f"  {division}: {stats['total_players']} players across {stats['teams']} teams")
            
            return 0
        else:
            logger.error("Failed to process game card")
            return 1
            
    except Exception as e:
        logger.error(f"Error in game card processing: {e}")
        return 1

# Add this to the main() function (after the payment reminder handling section)
    # Show game card preparation instructions
    if args.prepare_game_card:
        processor = GameCardProcessor(config)
        print(processor.create_game_card_instructions())
        return 0

    # Handle single division processing
    if args.process_game_card_division:
        return handle_game_card_processing(
            config, 
            single_division=args.process_game_card_division
        )
    
    # Handle game card processing
    if args.process_game_card:
        return handle_game_card_processing(config, args.process_game_card)
    
    # Handle game card summary only
    if args.game_card_summary:
        try:
            processor = GameCardProcessor(config)
            summary = processor.generate_summary_report()
            
            logger.info("Upper Divisions Summary:")
            logger.info(f"Total players in upper divisions: {summary['total_players']}")
            
            for division, stats in summary['divisions'].items():
                logger.info(f"\n{division}:")
                logger.info(f"  Total players: {stats['total_players']}")
                logger.info(f"  Teams: {stats['teams']}")
                logger.info(f"  Players with jerseys: {stats['players_with_jerseys']}")
                logger.info(f"  Team breakdown:")
                for team, count in stats['teams_list'].items():
                    logger.info(f"    {team}: {count} players")
                    
            return 0
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return 1

def handle_etrainu_standalone(config, args):
    """Handle ETrainU analysis without automation (standalone mode)"""
    import pandas as pd
    from datetime import datetime
    from pathlib import Path
    
    logger = setup_logging(log_level='INFO')
    
    try:
        from automation.etrainu_scraper import quick_run_etrainu_analysis
        
        logger.info("Running ETrainU analysis in standalone mode...")
        
        # Use default file paths
        html_file = getattr(args, 'etrainu_html', 'data/etrainu.html')
        data_dir = getattr(args, 'etrainu_data', 'data')
        
        # Run analysis
        results = quick_run_etrainu_analysis(html_file, data_dir)
        
        # Generate Excel report
        report_df = results['report']
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Determine output directory
        output_dir = Path(config.get('download_dir', 'reports')) if config else Path('reports')
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f"etrainu_standalone_{timestamp}.xlsx"
        
        # Save report
        if not report_df.empty:
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                report_df.to_excel(writer, sheet_name='Recommendations', index=False)
                
                # Add course demand summary
                course_demand = report_df['Recommended Course'].value_counts().reset_index()
                course_demand.columns = ['Course Type', 'Matches']
                course_demand.to_excel(writer, sheet_name='Course Demand', index=False)
        
        # Print results
        print(f"\nETrainU Standalone Analysis Results:")
        print(f"  Events Processed: {results['summary']['total_events']}")
        print(f"  Volunteers Matched: {results['summary']['total_volunteers']}")
        print(f"  Total Recommendations: {results['summary']['total_recommendations']}")
        if not report_df.empty:
            print(f"  Report saved: {output_file}")
            print(f"  Top course demand: {report_df['Recommended Course'].value_counts().head(3).to_dict()}")
        
        return 0
        
    except ImportError as e:
        logger.error(f"ETrainU module import failed: {e}")
        logger.error("Make sure etrainu_scraper.py is in the automation/ directory")
        return 1
    except Exception as e:
        logger.error(f"ETrainU standalone analysis failed: {e}")
        return 1

def handle_etrainu_with_automation(automation, config, args):
    """Handle ETrainU analysis with full automation integration"""
    import pandas as pd
    from datetime import datetime
    from pathlib import Path
    
    logger = setup_logging(log_level='INFO')
    
    try:
        from automation.etrainu_scraper import ETrainUAutomationModule
        
        logger.info("Starting ETrainU analysis with automation integration...")
        
        # Create ETrainU module using the logged-in automation instance
        etrainu_module = ETrainUAutomationModule(automation, config)
        
        # Define volunteer data files (these will be ignored if Google Sheets is enabled)
        volunteer_files = {
            'compliance': 'data/2025 Volunteer Compliance.xlsx',
            'volunteer_details': 'data/Volunteer_Details 63.xlsx',
            'enrollment': 'data/Enrollment_Details.xlsx'
        }
        
        # Note: If config has use_google_sheets: true, these local files will be ignored
        # and data will be loaded from Google Sheets URLs in the config instead

        # Initialize with HTML file and volunteer data
        etrainu_module.initialize_from_files('data/compliance/etrainu.html', volunteer_files)
        
        # Get enrollment recommendations
        recommendations = etrainu_module.get_enrollment_recommendations()
        
        # Generate Excel report
        report_df = recommendations['report_dataframe']
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = Path(config.get('download_dir', 'data/downloads')) / f"etrainu_automation_{timestamp}.xlsx"
        
        if not report_df.empty:
            # Create comprehensive Excel report
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                report_df.to_excel(writer, sheet_name='Recommendations', index=False)
                
                # Add summary sheets if available
                if 'summary_statistics' in recommendations:
                    stats = recommendations['summary_statistics']
                    
                    if 'course_demand' in stats:
                        course_demand_df = pd.DataFrame(
                            list(stats['course_demand'].items()), 
                            columns=['Course Type', 'Matches']
                        )
                        course_demand_df.to_excel(writer, sheet_name='Course Demand', index=False)
                    
                    if 'priority_distribution' in stats:
                        priority_df = pd.DataFrame(
                            list(stats['priority_distribution'].items()),
                            columns=['Priority', 'Count']
                        )
                        priority_df.to_excel(writer, sheet_name='Priority Breakdown', index=False)
            
            logger.info(f"ETrainU automation report saved: {output_file}")
        
        # Print results
        print(f"\nETrainU Automation Analysis Complete:")
        print(f"  Events: {recommendations['total_events']}")
        print(f"  Volunteers Matched: {recommendations['total_volunteers_matched']}")
        print(f"  Total Recommendations: {recommendations['total_recommendations']}")
        if not report_df.empty:
            print(f"  Report saved: {output_file}")
            if 'summary_statistics' in recommendations and 'average_match_score' in recommendations['summary_statistics']:
                print(f"  Average Match Score: {recommendations['summary_statistics']['average_match_score']}")
        
        # Return the result for further processing (uploads, etc.)
        return str(output_file) if not report_df.empty else None
        
    except ImportError as e:
        logger.error(f"ETrainU module import failed: {e}")
        logger.error("Make sure etrainu_scraper.py is in the automation/ directory")
        return 1
    except Exception as e:
        logger.error(f"ETrainU automation analysis failed: {e}")
        return 1
   
def validate_existing_reports(config: ConfigManager) -> int:
    """Validate existing report files"""
    logger = setup_logging(log_level='INFO')
    logger.info("Running validation only mode")
    
    validator = ReportValidator()
    download_dir = Path(config.download_dir)
    
    if not download_dir.exists():
        logger.error(f"Download directory not found: {download_dir}")
        return 1
    
    # Find Excel files
    excel_files = list(download_dir.glob("*.xlsx")) + list(download_dir.glob("*.xls"))
    json_files = list(download_dir.glob("*waitlist*.json")) + list(download_dir.glob("*removal*.json"))
    pdf_files = list(download_dir.glob("*medical*.pdf"))
    
    all_files = excel_files + json_files + pdf_files
    
    if not all_files:
        logger.warning("No files found to validate")
        return 0
    
    logger.info(f"Found {len(all_files)} files to validate")
    
    validations = {}
    for file_path in all_files:
        if file_path.suffix.lower() in ['.xlsx', '.xls']:
            validation = validator.validate_excel_file(str(file_path))
        elif file_path.suffix.lower() == '.pdf':
            # Basic PDF validation
            validation = {
                'valid': os.path.getsize(file_path) > 1000,  # At least 1KB
                'file_size': os.path.getsize(file_path),
                'error': None if os.path.getsize(file_path) > 1000 else "PDF file too small"
            }
        else:
            # JSON validation
            try:
                with open(file_path, 'r') as f:
                    import json
                    json.load(f)
                validation = {'valid': True, 'error': None}
            except Exception as e:
                validation = {'valid': False, 'error': str(e)}
        
        validations[file_path.name] = validation
        
        if validation['valid']:
            logger.info(f"Success: {file_path.name}: Valid")
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


def upload_enrollment_summary_to_drive(config: ConfigManager, drive_uploader=None) -> bool:
    """
    Find and upload the most recent enrollment summary file created by Access macro
    Always replaces the same file in Google Drive to maintain sharing permissions
    
    Args:
        config: Configuration manager
        drive_uploader: Existing GoogleDriveUploader instance (optional)
        
    Returns:
        True if successful
    """
    logger = setup_logging(log_level='INFO')
    
    try:
        # Get the directory path from config or use default
        ayso_path = config.get('paths.ayso_path', 
                              f"{os.environ.get('USERPROFILE', '')}\\OneDrive\\AYSO")
        
        # Pattern for enrollment summary files
        pattern = os.path.join(ayso_path, "enrollment_summary_*.xls*")  # Matches both .xls and .xlsx
        files = glob.glob(pattern)
        
        if not files:
            logger.warning(f"No enrollment summary files found in {ayso_path}")
            return False
        
        # Get the most recent file
        latest_file = max(files, key=os.path.getmtime)
        logger.info(f"Found enrollment summary file: {latest_file}")
        
        # Create uploader if not provided
        if drive_uploader is None:
            if not os.path.exists('credentials.json'):
                logger.warning("Google Drive credentials not found")
                return False
            drive_uploader = GoogleDriveUploader()
        
        # Get folder ID from config
        folder_id = config.get('google_drive_config.folder_id')
        if not folder_id:
            logger.warning("No Google Drive folder ID configured")
            return False
        
        # Fixed filename for Google Drive
        fixed_filename = "Enrollment_Summary_Report.xlsx"
        
        # Check if file already exists in Google Drive
        existing_files = drive_uploader.list_files(folder_id, fixed_filename)
        
        # Filter for exact name match
        file_id = next(
            (f["id"] for f in existing_files if f["name"] == fixed_filename),
            None
        )

        if file_id:
            # File exists - update it to preserve sharing permissions
            file_id = existing_files[0]['id']
            logger.info(f"Updating existing file: {fixed_filename} (ID: {file_id})")
            
            # Update the existing file
            success = update_drive_file(drive_uploader, file_id, latest_file)
            
            if success:
                logger.info(f"✓ Successfully updated {fixed_filename} in Google Drive")
                logger.info("  Sharing permissions have been preserved")
                return True
            else:
                logger.error("Failed to update enrollment summary in Google Drive")
                return False
        else:
            # File doesn't exist - create new
            logger.info(f"Creating new file: {fixed_filename}")
            file_id = drive_uploader.upload_file(latest_file, folder_id, fixed_filename)
            
            if file_id:
                logger.info(f"✓ Successfully uploaded {fixed_filename} to Google Drive (ID: {file_id})")
                logger.info("  Note: You'll need to set sharing permissions for this new file")
                return True
            else:
                logger.error("Failed to upload enrollment summary to Google Drive")
                return False
            
    except Exception as e:
        logger.error(f"Error uploading enrollment summary: {e}")
        return False

def handle_volunteer_compliance_update(config, volunteer_report=None, admin_report=None):
    """
    Handle volunteer compliance update
    
    Args:
        config: Configuration manager
        volunteer_report: Path to volunteer report (optional)
        admin_report: Path to admin credentials report (optional)
    
    Returns:
        0 if successful, 1 if failed
    """
    logger = setup_logging(log_level='INFO')
    
    try:
        # Initialize compliance handler
        compliance_handler = VolunteerComplianceHandler(config)
        
        # If no reports provided, find the most recent ones
        if not volunteer_report:
            download_dir = Path(config.get('paths.download_dir', 'data/downloads'))
            
            # Find most recent volunteer report
            volunteer_files = list(download_dir.glob('Volunteer_Details*.xlsx'))
            if volunteer_files:
                volunteer_report = str(max(volunteer_files, key=lambda p: p.stat().st_mtime))
                logger.info(f"Using volunteer report: {volunteer_report}")
            else:
                logger.error("No volunteer report found in downloads directory")
                return 1
        
        if not admin_report:
            download_dir = Path(config.get('paths.download_dir', 'data/downloads'))
            
            # Find most recent admin credentials report
            admin_files = list(download_dir.glob('AdminCredentialsStatusDynamic*.xlsx'))
            if admin_files:
                admin_report = str(max(admin_files, key=lambda p: p.stat().st_mtime))
                logger.info(f"Using admin credentials report: {admin_report}")
            else:
                logger.warning("No admin credentials report found, proceeding without it")
        
        # Process the reports
        if compliance_handler.process_volunteer_report(volunteer_report, admin_report):
            logger.info("✓ Volunteer compliance tracking updated successfully")
            
            # Show Google Sheets URL if using Google Sheets
            if config.get('volunteer_compliance.use_google_sheets'):
                sheet_id = config.get('volunteer_compliance.google_sheet_id')
                if sheet_id:
                    logger.info(f"View updated compliance tracking at: https://docs.google.com/spreadsheets/d/{sheet_id}")
            
            return 0
        else:
            logger.error("✗ Failed to update volunteer compliance tracking")
            return 1
            
    except Exception as e:
        logger.error(f"Error updating volunteer compliance: {e}")
        return 1


def update_drive_file(drive_uploader, file_id: str, local_file_path: str) -> bool:
    """
    Update an existing Google Drive file with new content
    
    Args:
        drive_uploader: GoogleDriveUploader instance
        file_id: Google Drive file ID to update
        local_file_path: Path to local file with new content
        
    Returns:
        True if successful
    """
    logger = setup_logging(log_level='INFO')
    
    try:
        from googleapiclient.http import MediaFileUpload
        
        # Determine MIME type
        mime_type = drive_uploader._get_mime_type(local_file_path)
        
        # Create media upload
        media = MediaFileUpload(local_file_path, mimetype=mime_type, resumable=True)
        
        # Update the file (keeps the same ID and permissions)
        updated_file = drive_uploader.service.files().update(
            fileId=file_id,
            media_body=media
        ).execute()
        
        return True
        
    except Exception as e:
        logger.error(f"Error updating Drive file: {e}")
        return False
    

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


def filter_by_current_waitlist(removal_orders: List[str], waitlist_file: str, logger) -> List[str]:
    """
    Filter removal orders to only include those currently on waitlist
    
    Args:
        removal_orders: List of order numbers marked for removal
        waitlist_file: Path to current waitlist Excel file
        logger: Logger instance
        
    Returns:
        Filtered list of order numbers that are actually on the waitlist
    """
    try:
        import pandas as pd
        
        # Read the waitlist report
        df = pd.read_excel(waitlist_file)
        
        # Find the order number column (might be named differently)
        order_col = None
        for col in df.columns:
            if 'order' in col.lower() and ('no' in col.lower() or 'number' in col.lower()):
                order_col = col
                break
        
        if not order_col:
            logger.error("Could not find order number column in waitlist report")
            logger.debug(f"Available columns: {df.columns.tolist()}")
            return removal_orders  # Return original list if we can't verify
        
        # Get all order numbers currently on waitlist
        current_waitlist_orders = df[order_col].astype(str).tolist()
        
        # Filter removal orders
        filtered_orders = []
        removed_already = []
        
        for order in removal_orders:
            if str(order) in current_waitlist_orders:
                filtered_orders.append(order)
            else:
                removed_already.append(order)
        
        # Log the results
        if removed_already:
            logger.info(f"Skipping {len(removed_already)} orders not found on current waitlist:")
            for order in removed_already[:10]:  # Show first 10
                logger.info(f"  - {order}")
            if len(removed_already) > 10:
                logger.info(f"  ... and {len(removed_already) - 10} more")
        
        return filtered_orders
        
    except Exception as e:
        logger.error(f"Error filtering by current waitlist: {e}")
        # Return original list if filtering fails
        return removal_orders


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
                from automation.report_handlers import ReportType
                
                google_sheet_id = waitlist_config.get('google_sheet_id', '1wraHRkpi2HkhKClP5KMQmAflntsC-V3PQVW5S7QGav8')
                sheets_reader = GoogleSheetsWaitlistReader(google_sheet_id)
                order_numbers = sheets_reader.get_removal_list()
                
                if not order_numbers:
                    logger.error("No removal orders found in Google Sheet")
                    return 1
                    
                logger.info(f"Found {len(order_numbers)} order numbers marked for removal from Google Sheet")
                
                # NEW: Download fresh waitlist report to verify who's still on waitlist
                logger.info("Downloading current waitlist report to verify participants...")
                waitlist_file = automation.export_report(ReportType.WAITLIST_REPORT)
                
                if not waitlist_file:
                    logger.error("Failed to download waitlist report")
                    return 1
                
                # Filter order numbers to only include those still on waitlist
                order_numbers = filter_by_current_waitlist(order_numbers, waitlist_file, logger)
                
                if not order_numbers:
                    logger.info("No participants from the removal list are currently on the waitlist")
                    return 0
                    
                logger.info(f"Filtered to {len(order_numbers)} participants who are still on waitlist")
                
            except Exception as e:
                logger.error(f"Failed to read from Google Sheet: {e}")
                return 1
        
        if not order_numbers:
            logger.error("No order numbers to process")
            return 1
            
        logger.info(f"Processing removal for order numbers: {order_numbers}")
        
        # Create waitlist manager with automation instance
        waitlist_manager = WaitlistManager(
            automation.driver, 
            automation.config.base_url, 
            automation.config.organization_id,
            automation.config,
            automation=automation  # Pass the automation instance
        )
        
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


def handle_waitlist_non_responders(config: ConfigManager, action: str = 'report', 
                                  days: int = 3, auto_remove: bool = False,
                                  existing_automation=None) -> int:
    """
    Handle non-responder management from command line
    
    Args:
        config: Configuration manager
        action: 'report', 'summary', or 'remove'
        days: Days to consider as non-response
        auto_remove: Auto-confirm removal
        existing_automation: Existing SportsConnectAutomation instance (optional)
        
    Returns:
        Exit code
    """
    logger = setup_logging(log_level='INFO')
    
    try:
        from automation.sports_connect import SportsConnectAutomation
        from automation.waitlist_manager import WaitlistManager
        
        logger.info("Processing Waitlist Non-Responders")
        logger.info("=" * 50)
        
        # Check if we have an existing automation instance or need to create one
        automation = existing_automation
        cleanup_needed = False
        
        if not automation:
            # Need to create new automation instance
            logger.info("Creating new automation instance...")
            try:
                automation = SportsConnectAutomation(config)
                automation.initialize()
                cleanup_needed = True  # We created it, so we should clean it up
                
                if not automation.login():
                    logger.error("Login failed")
                    return 1
            except Exception as e:
                logger.error(f"Failed to initialize automation: {e}")
                return 1
        else:
            logger.info("Using existing automation instance")
            # Check if we're logged in
            try:
                # Simple check - try to get current URL
                current_url = automation.driver.current_url
                if "login" in current_url.lower():
                    logger.info("Not logged in, attempting login...")
                    if not automation.login():
                        logger.error("Login failed")
                        return 1
            except:
                logger.warning("Could not verify login status")
        
        try:

            # Create waitlist manager with automation instance
            waitlist_manager = WaitlistManager(
                automation.driver, 
                automation.config.base_url, 
                automation.config.organization_id,
                automation.config,
                automation=automation  # Pass the automation instance
            )
            
            # # Create waitlist manager
            # waitlist_manager = WaitlistManager(
            #     automation.driver, 
            #     automation.config.base_url, 
            #     automation.config.organization_id,
            #     automation.config
            # )
            
            program_id = config.get('program_id')
            program_name = config.get('program_name', '2025 Fall Core')
            
            if not program_id:
                logger.error("Program ID not configured")
                return 1
            
            if action == 'summary':
                # Just show summary
                summary = waitlist_manager.get_non_responder_summary(days)
                
                logger.info(f"\nNon-Responder Summary (>{days} days):")
                logger.info(f"Total pending responses: {summary['total_pending']}")
                logger.info(f"Non-responders: {summary['non_responders']}")
                
                if summary.get('non_responders_by_division'):
                    logger.info("\nBy Division:")
                    for div, count in summary['non_responders_by_division'].items():
                        logger.info(f"  {div}: {count}")
                
                if summary.get('oldest_pending'):
                    oldest = summary['oldest_pending']
                    logger.info(f"\nOldest pending: {oldest['player_name']} - {oldest['days_waiting']} days")
                
            elif action == 'report':
                # Generate detailed report
                report = waitlist_manager.create_non_responder_report(days, save_to_file=True)
                print("\n" + report)
                
            elif action == 'remove':
                # Actually remove non-responders
                if not auto_remove:
                    # Show summary first
                    summary = waitlist_manager.get_non_responder_summary(days)
                    logger.info(f"\nAbout to remove {summary['non_responders']} participants")
                    
                    if summary['non_responders'] > 0:
                        confirm = input(f"\nRemove {summary['non_responders']} non-responders? (y/n): ")
                        if confirm.lower() != 'y':
                            logger.info("Removal cancelled")
                            return 0
                
                # Process removal
                results = waitlist_manager.process_non_responders(program_id, days, program_name)
                
                logger.info("\nRemoval Results:")
                logger.info(f"Total non-responders: {results.get('total_non_responders', 0)}")
                logger.info(f"Successfully removed: {results.get('total_removed', 0)}")
                
                if results.get('results'):
                    for div_result in results['results']:
                        status = "✓" if div_result['status'] == 'success' else "✗"
                        logger.info(f"{status} {div_result['division']}: {div_result['removed']} removed")
            
            return 0
            
        finally:
            # Only clean up if we created the automation instance
            if cleanup_needed and automation:
                logger.info("Cleaning up automation instance...")
                automation.cleanup()
                
    except Exception as e:
        logger.error(f"Error handling non-responders: {e}")
        import traceback
        traceback.print_exc()
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

# Playmetrics handler
def handle_playmetrics_export(config, args) -> int:
    """Handle PlayMetrics export operations"""
    from utilities.logger import setup_logging
    logger = setup_logging(log_level='INFO')
 
    try:
        from automation.playmetrics_export_manager import PlayMetricsExportManager
 
        mgr = PlayMetricsExportManager(config)
        enrollment_file = getattr(args, 'playmetrics_file', None)
        output_file = getattr(args, 'playmetrics_output', None)
 
        # Preview mode
        if args.playmetrics_preview:
            summary = mgr.preview_export(enrollment_file=enrollment_file)
            print(mgr.format_preview_report(summary))
            return 0
 
        # Player export
        if args.playmetrics_players:
            result = mgr.export_players(
                enrollment_file=enrollment_file,
                output_file=output_file,
                exclude_unallocated=getattr(args, 'exclude_unallocated', False),
                exclude_jamboree=True
            )
            if result:
                logger.info(f"PlayMetrics player CSV exported: {result}")
                return 0
            else:
                logger.error("PlayMetrics player export failed")
                return 1
 
        # Coach export
        if args.playmetrics_coaches:
            team_info_file = getattr(args, 'team_info_file', None)
 
            # If no team info file provided and we need to download it,
            # spin up an automation instance
            automation = None
            if not team_info_file:
                # Check if a file exists locally first
                found = False
                for pattern in mgr.TEAM_INFO_FILE_PATTERNS:
                    if mgr._find_file(pattern):
                        found = True
                        break
                
                if not found:
                    try:
                        from automation.sports_connect import SportsConnectAutomation
                        logger.info("Team info not found locally. Downloading saved report 65588...")
                        automation = SportsConnectAutomation(config)
                        automation.initialize()
                        if not automation.login():
                            logger.error("Login failed - cannot download team info report")
                            logger.info("Provide the file manually: --team-info-file path/to/file.xlsx")
                            return 1
                    except Exception as e:
                        logger.warning(f"Could not start automation for download: {e}")
                        logger.info("Provide the file manually: --team-info-file path/to/file.xlsx")
 
            try:
                result = mgr.export_coaches(
                    team_info_file=team_info_file,
                    output_file=output_file,
                    automation=automation
                )
            finally:
                if automation:
                    automation.cleanup()
 
            if result:
                logger.info(f"PlayMetrics coach CSV exported: {result}")
                return 0
            else:
                logger.error("PlayMetrics coach export failed")
                return 1
 
        return 0
 
    except Exception as e:
        logger.error(f"Error in PlayMetrics export: {e}")
        import traceback
        traceback.print_exc()
        return 1
<<<<<<< HEAD

=======
 
def handle_pm_downloads(config, args) -> int:
    """Handle PlayMetrics admin site CSV export downloads.
    
    Downloads the CSV exports needed for the Enrollment Summary Report
    directly from the PlayMetrics admin portal via Selenium.
    """
    from utilities.logger import setup_logging
    logger = setup_logging(log_level='INFO')

    try:
        # Status-only mode — no browser needed
        if args.pm_status:
            manager = PlayMetricsDownloadManager(config=config)
            print(manager.get_download_summary())
            return 0

        # Setup mode — first-run MFA device trust
        if args.pm_setup:
            manager = PlayMetricsDownloadManager(config=config)
            try:
                success = manager.setup_first_run()
                return 0 if success else 1
            finally:
                manager.cleanup()

        # Download mode
        manager = PlayMetricsDownloadManager(config=config)
        manager.initialize()

        try:
            if not manager.login():
                logger.error("PlayMetrics login failed")
                return 1

            if args.pm_download == 'all':
                results = manager.download_all_enrollment_exports()
                failed = sum(1 for v in results.values() if v is None)
                return 1 if failed == len(results) else 0

            elif args.pm_download == 'responses':
                result = manager.download_registration_responses()

            elif args.pm_download == 'volunteers':
                result = manager.download_volunteers()

            elif args.pm_download == 'coaching':
                result = manager.download_coaching_requests()

            elif args.pm_download == 'packages':
                result = manager.scrape_packages()

            else:
                # Default to all
                results = manager.download_all_enrollment_exports()
                failed = sum(1 for v in results.values() if v is None)
                return 1 if failed == len(results) else 0

            return 0 if result else 1

        finally:
            manager.cleanup()

    except Exception as e:
        logger.error(f"Error in PlayMetrics download: {e}")
        import traceback
        traceback.print_exc()
        return 1
>>>>>>> origin/master

if __name__ == "__main__":
    sys.exit(main())