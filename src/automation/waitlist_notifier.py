"""
Waitlist notification system for Sports Connect Automation
Sends email notifications to waitlist participants via Gmail (SMTP or OAuth2)
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
                self.gmail_service = GmailOAuth2Service()
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
        
        # Initialize response tracker
        from automation.waitlist_persistence import WaitlistResponseTracker, WaitlistNotificationFilter
        self.tracker = WaitlistResponseTracker()
        
        # Notification filter configuration
        notification_config = config.get('waitlist_notification_config', {}) if config else {}
        filter_config = {
            'days_between_notifications': notification_config.get('days_between_notifications', 7),
            'exclude_confirmed_days': notification_config.get('exclude_confirmed_days', 30)
        }
        self.filter = WaitlistNotificationFilter(self.tracker, filter_config)
    
    def load_waitlist_report(self, file_path: str) -> pd.DataFrame:
        """
        Load waitlist report from Excel file
        
        Args:
            file_path: Path to waitlist report Excel file
            
        Returns:
            DataFrame with waitlist data
        """
        try:
            logger.info(f"Loading waitlist report from: {file_path}")
            df = pd.read_excel(file_path)
            
            # Log columns for debugging
            logger.debug(f"Columns found: {df.columns.tolist()}")
            
            # Standardize column names (handle variations)
            column_mapping = {
                'Player First Name': 'player_first',
                'Player Last Name': 'player_last',
                'Parent First Name': 'parent_first',
                'Parent Last Name': 'parent_last',
                'Parent Email': 'email',
                'User Email': 'email',
                'Division': 'division',
                'Division Name': 'division',
                'Order Date': 'order_date',
                'Order No': 'order_id'
            }
            
            # Rename columns based on mapping
            for old_col, new_col in column_mapping.items():
                if old_col in df.columns:
                    df.rename(columns={old_col: new_col}, inplace=True)
            
            # Ensure required columns exist
            required_columns = ['email', 'division']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                logger.error(f"Missing required columns: {missing_columns}")
                logger.error(f"Available columns: {df.columns.tolist()}")
                raise ValueError(f"Missing required columns: {missing_columns}")
            
            # Filter out rows without email
            df = df[df['email'].notna() & (df['email'] != '')]
            
            logger.info(f"Loaded {len(df)} waitlist entries with valid emails")
            return df
            
        except Exception as e:
            logger.error(f"Error loading waitlist report: {e}")
            raise
    
    def create_email_body(self, row: pd.Series, google_form_url: str) -> str:
        """
        Create email body from template
        
        Args:
            row: DataFrame row with participant data
            google_form_url: URL to Google Form for waitlist response
            
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
                    
                    <p>This email is to inform you that <strong>{player_name}</strong> is currently on the waitlist 
                    for <strong>{division}</strong>.</p>
                    
                    <p>Due to limited space in our programs, we need to know if you would like to remain on the waitlist. 
                    Please click the button below to let us know your decision:</p>
                    
                    <div style="text-align: center;">
                        <a href="{google_form_url}={player_encoded}" class="button">Update Waitlist Status</a>
                    </div>
                    
                    <p><strong>Important:</strong> Please respond within 48 hours. If we do not receive a response, 
                    we may need to remove your child from the waitlist to make room for other participants.</p>
                    
                    <p>If you have any questions, please contact us at {self.reply_to}</p>
                    
                    <p>Thank you for your participation in AYSO!</p>
                    
                    <p>Best regards,<br>
                    AYSO Region 58 Registration Team</p>
                </div>
                
                <div class="footer">
                    <p>Order Reference: {order_id}<br>
                    AYSO Region 58 | Everyone Plays®</p>
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
                # For OAuth2, we use 'me' as sender
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
                # Create message
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
                        # In test mode, send all emails to test address
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
        Send notifications to all waitlist participants
        
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
        df = self.filter.filter_participants(df)
        
        if len(df) == 0:
            logger.info("No participants to notify after applying filters")
            return {
                'total_processed': 0,
                'sent_count': 0,
                'failed_count': 0,
                'sent_emails': [],
                'failed_emails': []
            }
        
        # Apply limit if specified
        if limit:
            df = df.head(limit)
            logger.info(f"Limited to {limit} emails")
        
        # Process each participant
        total = len(df)
        
        for idx, row in df.iterrows():
            try:
                email = row['email']
                division = row['division']
                order_id = str(row.get('order_id', ''))
                player_name = f"{row.get('player_first', '')} {row.get('player_last', '')}".strip()
                
                # Skip if no email
                if not email or pd.isna(email):
                    logger.warning(f"No email for row {idx}")
                    continue
                
                # Create email content
                subject = self.subject_template.format(division=division)
                body = self.create_email_body(row, google_form_url)
                
                # Send email
                if self.send_email(email, subject, body):
                    self.sent_emails.append({
                        'email': email,
                        'division': division,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    # Record in tracker
                    self.tracker.record_notification_sent(
                        order_id, email, player_name, division
                    )
                else:
                    self.failed_emails.append({
                        'email': email,
                        'division': division,
                        'timestamp': datetime.now().isoformat()
                    })
                
                # Progress update
                progress = len(self.sent_emails) + len(self.failed_emails)
                logger.info(f"Progress: {progress}/{total} emails processed")
                
                # Rate limiting
                if idx < len(df) - 1:  # Don't delay after last email
                    time.sleep(self.delay_between_emails)
                    
            except Exception as e:
                logger.error(f"Error processing row {idx}: {e}")
                self.failed_emails.append({
                    'email': row.get('email', 'unknown'),
                    'division': row.get('division', 'unknown'),
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
        
        # Summary
        results = {
            'total_processed': len(df),
            'sent_count': len(self.sent_emails),
            'failed_count': len(self.failed_emails),
            'sent_emails': self.sent_emails,
            'failed_emails': self.failed_emails
        }
        
        logger.info(f"Notification process complete: {results['sent_count']} sent, {results['failed_count']} failed")
        
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
        Save notification results to file
        
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
            f.write(f"Failed: {results['failed_count']}\n\n")
            
            if results['sent_emails']:
                f.write("SENT EMAILS:\n")
                for item in results['sent_emails']:
                    f.write(f"  - {item['email']} ({item['division']})\n")
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
        
        subject = "TEST: " + self.subject_template.format(division='10UB Test Division')
        body = self.create_email_body(test_data, google_form_url)
        
        logger.info(f"Sending test email to: {test_recipient}")
        return self.send_email(test_recipient, subject, body)


class GmailOAuthNotifier(WaitlistNotifier):
    """Alternative implementation using Gmail OAuth instead of SMTP"""
    
    def __init__(self, config=None):
        """Initialize with OAuth credentials"""
        super().__init__(config)
        self.creds = None
        self.service = None
        
    def authenticate(self):
        """Authenticate using Gmail OAuth"""
        # This would use similar logic to google_drive.py
        # but for Gmail API instead
        pass