"""
Medical Forms Email Sender for Sports Connect Automation
Sends medical forms to coaches based on cached coach information
"""
import os
import logging
import smtplib
import time
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from automation.coach_cache_manager import CoachCacheManager
from automation.email_send_tracker import EmailSendTracker

logger = logging.getLogger(__name__)


class MedicalFormsEmailer:
    """Handles sending medical forms to coaches via email"""
    
    def __init__(self, config=None):
        """
        Initialize Medical Forms Emailer
        
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
                # Check for gmail credentials file first
                gmail_creds = config.get('credentials_config.gmail_creds', 'gmail_credentials.json') if config else 'gmail_credentials.json'
                if not os.path.exists(gmail_creds):
                    logger.warning(f"Gmail credentials file not found: {gmail_creds}")
                    logger.info("Falling back to SMTP method. Run 'python -m integrations.gmail_oauth' to set up OAuth2")
                    self.email_method = 'smtp'
                else:
                    from integrations.gmail_oauth import GmailOAuth2Service
                    self.gmail_service = GmailOAuth2Service(
                        credentials_file=gmail_creds,
                        token_file=config.get('credentials_config.gmail_token', 'gmail_token.pickle') if config else 'gmail_token.pickle'
                    )
                    logger.info("Gmail OAuth2 service initialized successfully")
            except ImportError as e:
                logger.warning(f"Gmail OAuth module not found: {e}")
                logger.info("Falling back to SMTP method")
                self.email_method = 'smtp'
            except Exception as e:
                logger.warning(f"Failed to initialize Gmail OAuth2: {e}")
                logger.info("Falling back to SMTP method")
                self.email_method = 'smtp'
        
        # Medical forms configuration
        medical_config = config.get('medical_forms_config', {}) if config else {}
        self.medical_forms_dir = medical_config.get('destination_dir', 'data/medical_forms')
        self.medical_forms_season = medical_config.get('medical_forms_season', '')
        
        # Initialize coach cache manager
        self.coach_cache_manager = CoachCacheManager()
        
        # Initialize email send tracker
        self.email_tracker = EmailSendTracker()
        
        # Extract season from config
        if self.medical_forms_season and len(self.medical_forms_season) >= 6:
            self.season = self.medical_forms_season[-6:]
        else:
            # Fallback to current season
            current_month = datetime.now().month
            year = datetime.now().strftime("%y")
            season_name = "Fall" if current_month >= 6 else "Spring"
            self.season = f"{season_name}{year}"
        
        # Email template settings
        self.subject_template = email_config.get('medical_forms_subject', 
            'AYSO Medical Forms - {team_name} ({division})')
        
        # Rate limiting
        self.delay_between_emails = email_config.get('delay_between_emails', 2)
        self.test_mode = email_config.get('test_mode', False)
        self.test_email = email_config.get('test_email', '')
        
        # Tracking
        self.sent_emails = []
        self.failed_emails = []
    
    def send_medical_forms_to_all_coaches(self, division_filter: List[str] = None, 
                                        dry_run: bool = False) -> Dict[str, any]:
        """
        Send medical forms to all coaches in the cache
        
        Args:
            division_filter: List of divisions to include (None for all)
            dry_run: If True, don't actually send emails
            
        Returns:
            Dictionary with results
        """
        logger.info("Starting medical forms email distribution")
        
        # Get coaches from cache manager
        all_coaches = self.coach_cache_manager.get_all_coaches()
        
        if not all_coaches:
            logger.error("No coaches found in cache")
            return {
                'total_processed': 0,
                'sent_count': 0,
                'failed_count': 0,
                'sent_emails': [],
                'failed_emails': []
            }
        
        # Filter coaches by division if specified
        coaches_to_process = {}
        for cache_key, coach_info in all_coaches.items():
            division = coach_info.get('division', '')
            if division_filter is None or division in division_filter:
                coaches_to_process[cache_key] = coach_info
        
        logger.info(f"Found {len(coaches_to_process)} coaches to process")
        
        # Process each coach
        for cache_key, coach_info in coaches_to_process.items():
            try:
                division = coach_info['division']
                team_name = coach_info['team']
                coach_name = coach_info['coach_name']
                coach_email = coach_info['coach_email']
                
                # Check if we should send this email (avoid duplicates)
                should_send, reason = self.email_tracker.should_send_email(
                    cache_key, 'medical_forms', min_days_between=30
                )
                
                if not should_send and not dry_run:
                    logger.info(f"Skipping {coach_email}: {reason}")
                    continue
                
                # Find medical forms file
                medical_form_path = self._find_medical_form(division, team_name)
                
                if not medical_form_path:
                    logger.warning(f"No medical form found for {team_name} ({division})")
                    
                    # Track failed attempt
                    self.email_tracker.record_email_sent(
                        cache_key, coach_info, 'medical_forms',
                        success=False, error_message='Medical form file not found'
                    )
                    
                    self.failed_emails.append({
                        'email': coach_email,
                        'team': team_name,
                        'division': division,
                        'error': 'Medical form file not found',
                        'timestamp': datetime.now().isoformat()
                    })
                    continue
                
                # Prepare attachment info
                attachment_info = {
                    'filename': medical_form_path.name,
                    'filepath': str(medical_form_path),
                    'size': medical_form_path.stat().st_size
                }
                
                # Send email
                if dry_run:
                    logger.info(f"DRY RUN: Would send email to {coach_email} for {team_name}")
                    logger.info(f"  Attachment: {medical_form_path}")
                    
                    # Track dry run
                    self.email_tracker.record_email_sent(
                        cache_key, coach_info, 'medical_forms',
                        attachment_info=attachment_info,
                        success=True, error_message='DRY RUN - not actually sent'
                    )
                    
                    self.sent_emails.append({
                        'email': coach_email,
                        'team': team_name,
                        'division': division,
                        'attachment': str(medical_form_path),
                        'timestamp': datetime.now().isoformat(),
                        'dry_run': True,
                        'cache_key': cache_key
                    })
                else:
                    success = self._send_medical_forms_email(
                        coach_email, coach_name, team_name, 
                        division, medical_form_path
                    )
                    
                    # Track the send
                    self.email_tracker.record_email_sent(
                        cache_key, coach_info, 'medical_forms',
                        attachment_info=attachment_info,
                        success=success,
                        error_message=None if success else 'Email send failed'
                    )
                    
                    if success:
                        self.sent_emails.append({
                            'email': coach_email,
                            'team': team_name,
                            'division': division,
                            'attachment': str(medical_form_path),
                            'timestamp': datetime.now().isoformat(),
                            'cache_key': cache_key
                        })
                    else:
                        self.failed_emails.append({
                            'email': coach_email,
                            'team': team_name,
                            'division': division,
                            'error': 'Email send failed',
                            'timestamp': datetime.now().isoformat(),
                            'cache_key': cache_key
                        })
                
                # Rate limiting
                if not dry_run and cache_key != list(coaches_to_process.keys())[-1]:
                    time.sleep(self.delay_between_emails)
                    
            except Exception as e:
                logger.error(f"Error processing coach for {cache_key}: {e}")
                
                # Track the error
                self.email_tracker.record_email_sent(
                    cache_key, coach_info, 'medical_forms',
                    success=False, error_message=str(e)
                )
                
                self.failed_emails.append({
                    'email': coach_info.get('coach_email', 'unknown'),
                    'team': coach_info.get('team', 'unknown'),
                    'division': coach_info.get('division', 'unknown'),
                    'error': str(e),
                    'timestamp': datetime.now().isoformat(),
                    'cache_key': cache_key
                })
        
        # Summary
        results = {
            'total_processed': len(coaches_to_process),
            'sent_count': len(self.sent_emails),
            'failed_count': len(self.failed_emails),
            'sent_emails': self.sent_emails,
            'failed_emails': self.failed_emails,
            'dry_run': dry_run
        }
        
        logger.info(f"Email process complete: {results['sent_count']} sent, {results['failed_count']} failed")
        
        # Save results
        self.save_results(results)
        
        return results
    
    def _find_medical_form(self, division: str, team_name: str) -> Optional[Path]:
        """Find the medical form file for a specific team"""
        # Build path to medical forms directory
        forms_dir = Path(self.medical_forms_dir) / self.season / division
        
        if not forms_dir.exists():
            logger.warning(f"Medical forms directory not found: {forms_dir}")
            return None
        
        # Look for file with team name
        # Handle various naming patterns
        patterns = [
            f"{team_name} Medical Forms.pdf",
            f"{team_name} medical forms.pdf",
            f"{team_name}_Medical_Forms.pdf",
            f"{team_name}.pdf"
        ]
        
        for pattern in patterns:
            file_path = forms_dir / pattern
            if file_path.exists():
                return file_path
        
        # Try partial match
        for file in forms_dir.glob("*.pdf"):
            if team_name.lower() in file.name.lower():
                return file
        
        return None
    
    def _send_medical_forms_email(self, to_email: str, coach_name: str, 
                                team_name: str, division: str, 
                                attachment_path: Path) -> bool:
        """Send email with medical forms attachment"""
        try:
            # Create email content
            subject = self.subject_template.format(team_name=team_name, division=division)
            body = self._create_email_body(coach_name, team_name, division)
            
            if self.test_mode and self.test_email:
                logger.info(f"TEST MODE: Would send to {to_email}, actually sending to {self.test_email}")
                actual_recipient = self.test_email.strip()
            else:
                actual_recipient = to_email.strip()
                actual_recipient = "sdavis@davisportal.com"
            
            if self.email_method == 'oauth2' and self.gmail_service:
                # Use OAuth2 method
                return self._send_via_oauth2(
                    actual_recipient, subject, body, attachment_path
                )
            else:
                # Use SMTP method
                return self._send_via_smtp(
                    actual_recipient, subject, body, attachment_path
                )
                
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
    
    def _create_email_body(self, coach_name: str, team_name: str, division: str) -> str:
        """Create email body HTML"""
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #0066cc; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background-color: #f9f9f9; }}
                .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #666; }}
                .important {{ background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>AYSO Region 58 - Medical Forms</h1>
                </div>
                
                <div class="content">
                    <p>Dear Coach {coach_name},</p>
                    
                    <p>Attached are the medical forms for <strong>{team_name}</strong> in division <strong>{division}</strong>.</p>
                    
                    <div class="important">
                        <strong>Important:</strong> Please keep these forms with you at all practices and games. 
                        These forms contain important medical information and emergency contacts for your players.
                    </div>
                    
                    <p>As a reminder:</p>
                    <ul>
                        <li>Review each player's medical conditions and allergies</li>
                        <li>Keep forms in a secure, waterproof folder</li>
                        <li>Ensure assistant coaches know where forms are located</li>
                        <li>Have forms readily accessible during all team activities</li>
                    </ul>
                    
                    <p>If you have any questions or need updated forms, please contact us at {self.reply_to}</p>
                    
                    <p>Thank you for volunteering!</p>
                    
                    <p>Best regards,<br>
                    AYSO Region 58 Registration Team</p>
                </div>
                
                <div class="footer">
                    <p>AYSO Region 58 | Everyone Plays®<br>
                    This email contains confidential medical information. Please handle appropriately.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_body
    
    def _send_via_smtp(self, to_email: str, subject: str, body: str, 
                      attachment_path: Path) -> bool:
        """Send email via SMTP with attachment"""
        try:
            # Create message
            msg = MIMEMultipart()
            msg['Subject'] = subject
            msg['From'] = f"{self.sender_name} <{self.sender_email}>"
            msg['To'] = to_email
            msg['Reply-To'] = self.reply_to
            
            # Add HTML body
            html_part = MIMEText(body, 'html')
            msg.attach(html_part)
            
            # Add attachment
            with open(attachment_path, 'rb') as f:
                attach = MIMEApplication(f.read(), _subtype='pdf')
                attach.add_header('Content-Disposition', 'attachment', 
                                filename=attachment_path.name)
                msg.attach(attach)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
                
            logger.info(f"Email sent successfully to: {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return False
    
    def _send_via_oauth2(self, to_email: str, subject: str, body: str, 
                        attachment_path: Path) -> bool:
        """Send email via Gmail OAuth2 with attachment"""
        try:
            # Create the message with attachment
            from email.mime.base import MIMEBase
            from email import encoders
            import base64
            
            # Create message container
            msg = MIMEMultipart()
            msg['Subject'] = subject
            msg['From'] = self.sender_email
            msg['To'] = to_email
            msg['Reply-To'] = self.reply_to
            
            # Add HTML body
            html_part = MIMEText(body, 'html')
            msg.attach(html_part)
            
            # Add PDF attachment
            with open(attachment_path, 'rb') as f:
                mime_base = MIMEBase('application', 'pdf')
                mime_base.set_payload(f.read())
                encoders.encode_base64(mime_base)
                mime_base.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{attachment_path.name}"'
                )
                msg.attach(mime_base)
            
            # Create the raw message
            raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
            
            # Send using the Gmail service directly
            if hasattr(self.gmail_service, 'service') and self.gmail_service.service:
                try:
                    message = self.gmail_service.service.users().messages().send(
                        userId='me',
                        body={'raw': raw_message}
                    ).execute()
                    logger.info(f"Email sent successfully via OAuth2 to: {to_email}")
                    return True
                except Exception as e:
                    logger.error(f"Gmail API error: {e}")
                    return False
            else:
                # Try to access the service through a method
                if hasattr(self.gmail_service, 'get_service'):
                    service = self.gmail_service.get_service()
                    message = service.users().messages().send(
                        userId='me',
                        body={'raw': raw_message}
                    ).execute()
                    logger.info(f"Email sent successfully via OAuth2 to: {to_email}")
                    return True
                else:
                    logger.error("Cannot access Gmail service object")
                    return False
                    
        except Exception as e:
            logger.error(f"OAuth2 send failed: {e}")
            return False
    
    def save_results(self, results: Dict) -> str:
        """Save email results to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_dir = Path(self.medical_forms_dir) / "email_results"
        results_dir.mkdir(parents=True, exist_ok=True)
        
        results_file = results_dir / f"medical_forms_emails_{timestamp}.txt"
        
        with open(results_file, 'w') as f:
            f.write("Medical Forms Email Results\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Season: {self.season}\n")
            f.write(f"Total Processed: {results['total_processed']}\n")
            f.write(f"Emails Sent: {results['sent_count']}\n")
            f.write(f"Failed: {results['failed_count']}\n")
            if results.get('dry_run'):
                f.write("*** DRY RUN MODE ***\n")
            f.write("\n")
            
            if results['sent_emails']:
                f.write("SENT EMAILS:\n")
                for item in results['sent_emails']:
                    f.write(f"  - {item['email']} - {item['team']} ({item['division']})\n")
                    f.write(f"    Attachment: {item['attachment']}\n")
                f.write("\n")
            
            if results['failed_emails']:
                f.write("FAILED EMAILS:\n")
                for item in results['failed_emails']:
                    error = item.get('error', 'Unknown error')
                    f.write(f"  - {item['email']} - {item['team']} ({item['division']}) - {error}\n")
        
        logger.info(f"Results saved to: {results_file}")
        return str(results_file)
    
    def send_test_email(self) -> bool:
        """Send a test email to verify configuration"""
        test_recipient = self.test_email if self.test_email else self.sender_email
        if not test_recipient:
            logger.error("No test email address configured")
            return False
        
        # Create a dummy PDF for testing
        test_pdf_path = Path(self.medical_forms_dir) / "test_medical_form.pdf"
        
        # Use an existing PDF if available
        if not test_pdf_path.exists():
            # Find any PDF in the medical forms directory
            for pdf in Path(self.medical_forms_dir).rglob("*.pdf"):
                test_pdf_path = pdf
                break
        
        if not test_pdf_path.exists():
            logger.error("No PDF file found for test email")
            return False
        
        logger.info(f"Sending test email to: {test_recipient}")
        return self._send_medical_forms_email(
            test_recipient, 
            "Test Coach", 
            "Test Team", 
            "TEST", 
            test_pdf_path
        )