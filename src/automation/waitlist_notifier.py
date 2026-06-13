"""
Waitlist notification / curation for AYSO Region 58.

Sends "still interested?" check-in emails to waitlist participants and tracks
responses (via the Google Form/Sheet) and non-responders. Reads the PlayMetrics
waitlist export (waitlist_*.csv), keyed on PlayMetrics player_id; a legacy
Sports Connect WAITLIST Excel export is still accepted by the loader.

Modification History:
  2026-06-13  Read PlayMetrics waitlist CSV (player_id key); add SC/PM loader
              split and discover_latest_pm_waitlist(). Refresh stale header.
  (earlier)   Sports Connect waitlist Excel source; enhanced persistence
              tracking for non-responders. See git history.
"""
import os
import logging
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import pandas as pd
from pathlib import Path
import urllib.parse

logger = logging.getLogger(__name__)


class WaitlistNotifier:
    """Handles sending email notifications to waitlist participants"""
    
    def __init__(self, config=None):
        """
        Initialize Waitlist Notifier
        
        Args:
            config: Configuration manager instance
        """
        self.config = config
        
        # Email configuration
        email_config = config.get('email_config', {}) if config else {}
        self.email_method = email_config.get('method', 'oauth2')  # 'oauth2' or 'smtp'
        
        # Common settings
        self.sender_email = email_config.get('sender_email', '')
        self.sender_name = email_config.get('sender_name', 'AYSO Region 58')
        self.reply_to = email_config.get('reply_to', 'registrar@ayso58.org')
        
        # SMTP settings (if using SMTP)
        self.smtp_server = email_config.get('smtp_server', 'smtp.gmail.com')
        self.smtp_port = email_config.get('smtp_port', 587)
        self.sender_password = email_config.get('sender_password', '')
        
        # OAuth2 settings (if using OAuth2)
        self.gmail_service = None
        if self.email_method == 'oauth2':
            try:
                from integrations.gmail_oauth import GmailOAuth2Service
                creds_config = config.get("credentials_config", {})
                self.gmail_service = GmailOAuth2Service(
                    credentials_file=creds_config.get("gmail_creds", "src/gmail_credentials.json"),
                    token_file=creds_config.get("gmail_token", "src/gmail_token.pickle")
                )
            except Exception as e:
                logger.warning(f"Failed to initialize Gmail OAuth2: {e}")
                logger.info("Falling back to SMTP method")
                self.email_method = 'smtp'
        
        # Email templates
        self.subject_template = email_config.get('subject_template', 
            'AYSO Waitlist Notification - {division}')
        
        # Rate limiting
        self.delay_between_emails = email_config.get('delay_between_emails', 2)
        self.test_mode = email_config.get('test_mode', False)
        self.test_email = email_config.get('test_email', '')
        
        # Tracking
        self.sent_emails = []
        self.failed_emails = []
        
        # Initialize response tracker with enhanced persistence
        from automation.waitlist_persistence import WaitlistResponseTracker, WaitlistNotificationFilter
        self.tracker = WaitlistResponseTracker()
        
        # Notification filter configuration
        notification_config = config.get('waitlist_notification_config', {}) if config else {}
        filter_config = {
            'days_between_notifications': notification_config.get('days_between_notifications', 7),
            'exclude_confirmed_days': notification_config.get('exclude_confirmed_days', 30)
        }
        self.filter = WaitlistNotificationFilter(self.tracker, filter_config)
        
        # Log configuration
        logger.info(f"Waitlist Notifier initialized with:")
        logger.info(f"  - Days between notifications: {filter_config['days_between_notifications']}")
        logger.info(f"  - Exclude confirmed for days: {filter_config['exclude_confirmed_days']}")
    
    @staticmethod
    def discover_latest_pm_waitlist(data_dir: str = "data/playmetrics") -> Optional[str]:
        """Return the newest PlayMetrics waitlist CSV (waitlist_*.csv), or None."""
        d = Path(data_dir)
        if not d.exists():
            return None
        candidates = list(d.glob("waitlist_*.csv"))
        if not candidates:
            return None
        return str(max(candidates, key=lambda p: p.stat().st_mtime))

    @staticmethod
    def _normalize_pm_waitlist(df: pd.DataFrame) -> pd.DataFrame:
        """Map a PlayMetrics waitlist CSV to the notifier's normalized schema.

        The stable per-player key (player_id) is carried in `order_id` so the
        response tracker, notification filter, and Google Form prefill all work
        unchanged (they treat it as an opaque string key).
        """
        # Only players actually still on the waitlist (skip Invited/Registered).
        if 'status' in df.columns:
            df = df[df['status'].astype(str).str.strip().str.lower() == 'waitlist'].copy()
        mapping = {
            'player_first_name': 'player_first',
            'player_last_name': 'player_last',
            'account_first_name': 'parent_first',
            'account_last_name': 'parent_last',
            'account_email': 'email',
            'package_name': 'division',
            'registered_on': 'order_date',
            'parent2_email': 'secondary_email',
        }
        for old, new in mapping.items():
            if old in df.columns:
                df.rename(columns={old: new}, inplace=True)
        if 'division' not in df.columns and 'Division' in df.columns:
            df.rename(columns={'Division': 'division'}, inplace=True)
        if 'player_id' in df.columns:
            df['order_id'] = df['player_id'].apply(
                lambda v: str(int(v)) if pd.notna(v) else '')
        return df

    @staticmethod
    def _normalize_sc_waitlist(df: pd.DataFrame) -> pd.DataFrame:
        """Map a legacy Sports Connect WAITLIST Excel export to the schema."""
        mapping = {
            'Player First Name': 'player_first',
            'Player Last Name': 'player_last',
            'Account First Name': 'parent_first',
            'Account Last Name': 'parent_last',
            'Secondary Email': 'secondary_email',
            'User Email': 'email',
            'Division Name': 'division',
            'Order Date': 'order_date',
            'Order No': 'order_id',
        }
        for old, new in mapping.items():
            if old in df.columns:
                df.rename(columns={old: new}, inplace=True)
        return df

    def load_waitlist_report(self, file_path: str) -> pd.DataFrame:
        """Load a waitlist export into a normalized DataFrame.

        Supports the PlayMetrics waitlist CSV (current) and, for back-compat,
        the legacy Sports Connect WAITLIST Excel export. Both normalize to:
        email, division, player_first/last, parent_first/last (optional), and
        order_id (the stable per-player key — player_id on PM, Order No on SC).
        """
        try:
            logger.info(f"Loading waitlist report from: {file_path}")
            is_csv = str(file_path).lower().endswith(".csv")
            df = pd.read_csv(file_path) if is_csv else pd.read_excel(file_path)
            logger.debug(f"Columns found: {df.columns.tolist()}")

            # PlayMetrics CSVs carry player_id / account_email; SC exports don't.
            if 'player_id' in df.columns or 'account_email' in df.columns:
                df = self._normalize_pm_waitlist(df)
            else:
                df = self._normalize_sc_waitlist(df)

            required_columns = ['email', 'division', 'player_first', 'player_last']
            missing_columns = [c for c in required_columns if c not in df.columns]
            if missing_columns:
                logger.error(f"Missing required columns: {missing_columns}")
                logger.error(f"Available columns: {df.columns.tolist()}")
                raise ValueError(f"Missing required columns: {missing_columns}")

            # Drop rows without an email
            df = df[df['email'].notna() & (df['email'].astype(str).str.strip() != '')]
            logger.info(f"Loaded {len(df)} waitlist entries with valid emails")
            return df

        except Exception as e:
            logger.error(f"Error loading waitlist report: {e}")
            raise
    
    def create_email_body(self, row: pd.Series, google_form_url: str, 
                         notification_number: int = 1) -> str:
        """
        Create email body from template with notification number awareness
        
        Args:
            row: DataFrame row with participant data
            google_form_url: URL to Google Form for waitlist response
            notification_number: Which notification attempt this is
            
        Returns:
            HTML email body
        """
        # Extract data with defaults
        player_name = f"{row.get('player_first', '')} {row.get('player_last', '')}".strip()
        parent_name = f"{row.get('parent_first', '')} {row.get('parent_last', '')}".strip()
        division = row.get('division', 'Unknown Division')
        order_id = row.get('order_id', '')
        player_encoded = urllib.parse.quote_plus(f"{player_name} {division} (Order {order_id})")
        
        # Use player name if no specific parent name
        if not parent_name or parent_name == " ":
            parent_name = "Parent/Guardian"
        
        # Adjust messaging based on notification number
        if notification_number > 1:
            reminder_text = f"""
                <p style="color: #cc0000; font-weight: bold;">
                    This is reminder #{notification_number}. We have not received a response to our previous notification(s).
                </p>
            """
            urgency_text = """
                <p><strong style="color: #cc0000;">URGENT:</strong> This may be your final opportunity to remain on the waitlist. 
                Please respond within 24 hours or your spot may be released to other participants.</p>
            """
        else:
            reminder_text = ""
            urgency_text = """
                <p><strong>Important:</strong> Please respond within 48 hours. If we do not receive a response, 
                we may need to remove your child from the waitlist to make room for other participants.</p>
            """
        
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #0066cc; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background-color: #f9f9f9; }}
                .button {{ 
                    display: inline-block; 
                    padding: 12px 30px; 
                    background-color: #0066cc; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 5px; 
                    margin: 20px 0;
                }}
                .reminder {{ 
                    background-color: #fff3cd; 
                    border: 1px solid #ffecc0; 
                    padding: 15px; 
                    margin: 15px 0; 
                    border-radius: 5px; 
                }}
                .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>AYSO Region 58 - Waitlist Notification</h1>
                </div>
                
                <div class="content">
                    <p>Dear {parent_name},</p>
                    
                    {reminder_text}
                    
                    <p>This email is to inform you that <strong>{player_name}</strong> is currently on the waitlist 
                    for <strong>{division}</strong>.</p>
                    
                    <p>We will occasionally ask for you verify your continued interest
                    so in the event a spot opens we can fill it quickly. 
                    Please click the button below to let us know your decision:</p>
                    
                    <div style="text-align: center;">
                        <a href="{google_form_url}={player_encoded}" class="button">Click Here to Update Waitlist Status</a>
                    </div>
                    
                    {urgency_text}
                    
                    <p>If you have any questions, please contact us at {self.reply_to}</p>
                    
                    <p>Thank you for your participation in AYSO!</p>
                    
                    <p>Best regards,<br>
                    AYSO Region 58 Registration Team</p>
                </div>
                
                <div class="footer">
                    <p>Order Reference: {order_id}<br>
                    AYSO Region 58 | Everyone Plays®</p>
                    <p style="font-size: 10px; color: #999;">
                        Notification #{notification_number} sent on {datetime.now().strftime('%B %d, %Y')}
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_body
    
    def send_email(self, to_email: str, subject: str, body: str) -> bool:
        """
        Send an email via Gmail (SMTP or OAuth2)
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body: HTML email body
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Clean up email address
            to_email = to_email.strip()
            
            if self.email_method == 'oauth2' and self.gmail_service:
                # Use OAuth2 method
                sender = 'me'
                
                if self.test_mode and self.test_email:
                    logger.info(f"TEST MODE: Would send to {to_email}, actually sending to {self.test_email}")
                    actual_recipient = self.test_email.strip()
                else:
                    actual_recipient = to_email
                
                return self.gmail_service.send_email(
                    sender=sender,
                    to=actual_recipient,
                    subject=subject,
                    body_html=body,
                    reply_to=self.reply_to
                )
            else:
                # Use SMTP method
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = f"{self.sender_name} <{self.sender_email}>"
                msg['To'] = to_email
                msg['Reply-To'] = self.reply_to
                
                # Add HTML body
                html_part = MIMEText(body, 'html')
                msg.attach(html_part)
                
                # Connect to Gmail
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.sender_email, self.sender_password)
                    
                    # Send email
                    if self.test_mode and self.test_email:
                        logger.info(f"TEST MODE: Would send to {to_email}, actually sending to {self.test_email}")
                        server.send_message(msg, to_addrs=[self.test_email])
                    else:
                        server.send_message(msg)
                    
                    logger.info(f"Email sent successfully to: {to_email}")
                    return True
                
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
    
    def send_waitlist_notifications(self, 
                                  waitlist_file: str,
                                  google_form_url: str,
                                  division_filter: List[str] = None,
                                  limit: int = None) -> Dict[str, any]:
        """
        Send notifications to all waitlist participants with enhanced tracking
        
        Args:
            waitlist_file: Path to waitlist Excel file
            google_form_url: URL to Google Form for responses
            division_filter: List of divisions to include (None for all)
            limit: Maximum number of emails to send (None for all)
            
        Returns:
            Dictionary with results
        """
        logger.info("Starting waitlist notification process")
        
        # First, sync responses from Google Sheet if configured
        if self.config:
            self._sync_google_sheet_responses()
        
        # Load waitlist data
        df = self.load_waitlist_report(waitlist_file)
        
        # Apply division filter if specified
        if division_filter:
            df = df[df['division'].isin(division_filter)]
            logger.info(f"Filtered to {len(df)} entries for divisions: {division_filter}")
        
        # Apply notification rules to filter participants
        logger.info("Applying notification rules...")
        df_to_notify = self.filter.filter_participants(df)
        
        # Log filtering results
        logger.info(f"Notification filtering results:")
        logger.info(f"  - Total participants: {len(df)}")
        logger.info(f"  - Eligible for notification: {len(df_to_notify)}")
        logger.info(f"  - Filtered out: {len(df) - len(df_to_notify)}")
        
        # Get non-responder statistics
        non_responders = self.tracker.get_non_responders_report()
        if non_responders:
            multi_attempt = [nr for nr in non_responders if nr['notification_count'] >= 2]
            if multi_attempt:
                logger.info(f"  - Non-responders (2+ attempts): {len(multi_attempt)}")
        
        if len(df_to_notify) == 0:
            logger.info("No participants to notify after applying filters")
            return {
                'total_processed': 0,
                'sent_count': 0,
                'failed_count': 0,
                'sent_emails': [],
                'failed_emails': [],
                'non_responder_count': len(non_responders) if non_responders else 0
            }
        
        # Apply limit if specified
        if limit:
            df_to_notify = df_to_notify.head(limit)
            logger.info(f"Limited to {limit} emails")
        
        # Process each participant
        total = len(df_to_notify)
        
        for idx, row in df_to_notify.iterrows():
            try:
                email = row['email']
                division = row['division']
                order_id = str(row.get('order_id', ''))
                player_name = f"{row.get('player_first', '')} {row.get('player_last', '')}".strip()
                
                # Skip if no email
                if not email or pd.isna(email):
                    logger.warning(f"No email for row {idx}")
                    continue
                
                # Get notification attempt number
                notification_number = self.tracker.get_non_response_count(order_id) + 1
                
                # Create email content with notification number
                subject = self.subject_template.format(division=division)
                if notification_number > 1:
                    subject = f"REMINDER #{notification_number}: " + subject
                
                body = self.create_email_body(row, google_form_url, notification_number)
                
                # Send email
                if self.send_email(email, subject, body):
                    self.sent_emails.append({
                        'email': email,
                        'division': division,
                        'order_id': order_id,
                        'player_name': player_name,
                        'notification_number': notification_number,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    # Record in tracker
                    self.tracker.record_notification_sent(
                        order_id, email, player_name, division
                    )
                    
                    logger.info(f"Sent notification #{notification_number} to {email} for {player_name}")
                else:
                    self.failed_emails.append({
                        'email': email,
                        'division': division,
                        'order_id': order_id,
                        'timestamp': datetime.now().isoformat()
                    })
                
                # Progress update
                progress = len(self.sent_emails) + len(self.failed_emails)
                logger.info(f"Progress: {progress}/{total} emails processed")
                
                # Rate limiting
                if idx < len(df_to_notify) - 1:  # Don't delay after last email
                    time.sleep(self.delay_between_emails)
                    
            except Exception as e:
                logger.error(f"Error processing row {idx}: {e}")
                self.failed_emails.append({
                    'email': row.get('email', 'unknown'),
                    'division': row.get('division', 'unknown'),
                    'order_id': str(row.get('order_id', '')),
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
        
        # Get updated non-responder statistics
        updated_non_responders = self.tracker.get_non_responders_report()
        
        # Summary
        results = {
            'total_processed': len(df_to_notify),
            'sent_count': len(self.sent_emails),
            'failed_count': len(self.failed_emails),
            'sent_emails': self.sent_emails,
            'failed_emails': self.failed_emails,
            'non_responder_count': len(updated_non_responders) if updated_non_responders else 0,
            'multi_attempt_count': len([nr for nr in updated_non_responders if nr['notification_count'] >= 2]) if updated_non_responders else 0
        }
        
        logger.info(f"Notification process complete: {results['sent_count']} sent, {results['failed_count']} failed")
        logger.info(f"Non-responders: {results['non_responder_count']} total, {results['multi_attempt_count']} with 2+ attempts")
        
        # Save results
        self.save_results(results)
        
        # Generate tracking report
        tracking_report = self.tracker.generate_summary_report()
        logger.info("\n" + tracking_report)
        
        return results
    
    def _sync_google_sheet_responses(self):
        """Sync responses from Google Sheet"""
        try:
            waitlist_config = self.config.get('waitlist_config', {})
            if waitlist_config.get('use_google_sheet', False):
                from integrations.google_sheets_waitlist import GoogleSheetsWaitlistReader
                
                sheet_id = waitlist_config.get('google_sheet_id')
                if sheet_id:
                    logger.info("Syncing responses from Google Sheet...")
                    reader = GoogleSheetsWaitlistReader(sheet_id)
                    responses = reader.read_waitlist_decisions()
                    
                    imported = self.tracker.import_google_sheet_responses(responses)
                    logger.info(f"Synced {imported} responses from Google Sheet")
        except Exception as e:
            logger.error(f"Error syncing Google Sheet responses: {e}")
    
    def save_results(self, results: Dict) -> str:
        """
        Save notification results to file with enhanced tracking info
        
        Args:
            results: Results dictionary
            
        Returns:
            Path to results file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_dir = Path("data/downloads/notifications")
        results_dir.mkdir(parents=True, exist_ok=True)
        
        results_file = results_dir / f"waitlist_notifications_{timestamp}.txt"
        
        with open(results_file, 'w') as f:
            f.write("Waitlist Notification Results\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Processed: {results['total_processed']}\n")
            f.write(f"Emails Sent: {results['sent_count']}\n")
            f.write(f"Failed: {results['failed_count']}\n")
            f.write(f"Non-Responders: {results['non_responder_count']} total\n")
            f.write(f"Multi-Attempt Non-Responders: {results['multi_attempt_count']}\n\n")
            
            if results['sent_emails']:
                f.write("SENT EMAILS:\n")
                # Group by notification number
                by_attempt = {}
                for item in results['sent_emails']:
                    attempt_num = item.get('notification_number', 1)
                    if attempt_num not in by_attempt:
                        by_attempt[attempt_num] = []
                    by_attempt[attempt_num].append(item)
                
                for attempt_num in sorted(by_attempt.keys()):
                    f.write(f"\n  Notification Attempt #{attempt_num}:\n")
                    for item in by_attempt[attempt_num]:
                        f.write(f"    - {item['email']} - {item['player_name']} ({item['division']})\n")
                f.write("\n")
            
            if results['failed_emails']:
                f.write("FAILED EMAILS:\n")
                for item in results['failed_emails']:
                    error = item.get('error', 'Unknown error')
                    f.write(f"  - {item['email']} ({item['division']}) - {error}\n")
        
        logger.info(f"Results saved to: {results_file}")
        return str(results_file)
    
    def send_test_email(self, google_form_url: str) -> bool:
        """
        Send a test email to verify configuration
        
        Args:
            google_form_url: URL to Google Form
            
        Returns:
            True if successful
        """
        # Determine test recipient
        test_recipient = self.test_email if self.test_email else self.sender_email
        if not test_recipient:
            logger.error("No test email address configured")
            return False
            
        test_data = pd.Series({
            'player_first': 'Test',
            'player_last': 'Player',
            'parent_first': 'Test',
            'parent_last': 'Parent',
            'division': '10UB Test Division',
            'email': test_recipient,
            'order_id': '123456789'
        })
        
        # Test both first notification and reminder formats
        logger.info("Sending test emails...")
        
        # First notification
        subject1 = "TEST: " + self.subject_template.format(division='10UB Test Division')
        body1 = self.create_email_body(test_data, google_form_url, notification_number=1)
        
        if not self.send_email(test_recipient, subject1, body1):
            return False
        
        # Wait a moment
        time.sleep(2)
        
        # Reminder notification
        subject2 = "TEST REMINDER #2: " + self.subject_template.format(division='10UB Test Division')
        body2 = self.create_email_body(test_data, google_form_url, notification_number=2)
        
        logger.info(f"Sending test reminder email to: {test_recipient}")
        return self.send_email(test_recipient, subject2, body2)