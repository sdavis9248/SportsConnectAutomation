"""
Medical Forms Email Sender for Sports Connect Automation
Sends medical forms to coaches based on cached coach information
"""
import os
import re
import logging
import smtplib
import time
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import List, Dict, Optional, Tuple, Any
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
        self.sender_email = email_config.get('sender_email', 'registrar@ayso58.org')
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
        self.coach_cache_manager = CoachCacheManager(config=self.config)
        
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

    # Confirm the medical forms file exists
    def _check_medical_forms_exist(self, division: str, team: str) -> bool:
        """
        Check if medical forms PDF exists for a team
    
        Args:
            division: Division code (e.g., '07UB')
            team: Team name
    
        Returns:
            True if medical forms PDF exists, False otherwise
        """
        try:
            # Use the existing _find_medical_form method
            form_path = self._find_medical_form(division, team)
            exists = form_path is not None
        
            if not exists:
                logger.debug(f"Medical forms not found for {team} in division {division}")
            else:
                logger.debug(f"Medical forms found at: {form_path}")
            
            return exists
        
        except Exception as e:
            logger.error(f"Error checking medical forms existence: {e}")
            return False

    def _get_division_coordinator_email(self, division: str) -> str:
        """
        Get the division coordinator email address
        
        Args:
            division: Division code (e.g., '10UB')
            
        Returns:
            Email address for division coordinator
        """
        # Format: divisionDivMgr@ayso58.org
        return f"{division}DivMgr@ayso58.org"

    def _send_coach_email(self, coach_name: str, coach_email: str, team: str, 
                         division: str, reason: str = None) -> bool:
        """
        Send medical forms email to a coach
    
        Args:
            coach_name: Coach's name
            coach_email: Coach's email address
            team: Team name
            division: Division code
            reason: Optional reason for sending (e.g., "NEW PLAYER")
    
        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            # Get email configuration
            email_config = self.config.get('email_config', {})
        
            # Check if in test mode
            if self.test_mode:
                recipient_email = self.test_email if self.test_email else coach_email
                logger.info(f"TEST MODE: Redirecting email to {recipient_email}")
            else:
                recipient_email = coach_email
        
            # MODIFIED: Prepare email subject with reason
            if reason:
                subject = f"AYSO Region 58 - {team} Medical Forms - {reason}"
            else:
                subject = f"AYSO Region 58 - {team} Medical Forms"
        
            # MODIFIED: Pass reason to email body creation
            body_html = self._create_email_body(coach_name, team, division, reason=reason)


    def _send_via_oauth2(self, to_email: str, subject: str, body: str, attachment_path: Path) -> bool:
        """Send email via OAuth2 using Gmail API"""
        try:
            # Create message with attachment
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
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
                logger.error("Cannot access Gmail service object")
                return False
            
        except Exception as e:
            logger.error(f"OAuth2 send failed: {e}")
            return False


    def _send_via_smtp(self, to_email: str, subject: str, body: str, attachment_path: Path) -> bool:
        """Send email via SMTP"""
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.base import MIMEBase
            from email import encoders
        
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = to_email
            msg['Subject'] = subject
            msg['Reply-To'] = self.reply_to
        
            # Add HTML body
            msg.attach(MIMEText(body, 'html'))
        
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
        
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
        
            logger.info(f"Email sent successfully via SMTP to: {to_email}")
            return True
        
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return False
   
    def verify_coaches_for_season(self, season: str, division_filter: List[str] = None) -> Dict[str, Any]:
        """
        Verify coach information for a specific season
    
        Args:
            season: Season to verify
            division_filter: Optional list of divisions to check
        
        Returns:
            Verification results
        """
        coaches = self.coach_cache_manager.get_coaches_by_season(season)
    
        if division_filter:
            coaches = {k: v for k, v in coaches.items() if v.get('division') in division_filter}
    
        verification = {
            'season': season,
            'total_coaches': len(coaches),
            'divisions': {},
            'coaches_without_email': [],
            'duplicate_emails': {}
        }
    
        email_to_coaches = {}
    
        for cache_key, coach in coaches.items():
            division = coach.get('division')
            email = coach.get('coach_email', '').lower()
        
            # Track by division
            if division not in verification['divisions']:
                verification['divisions'][division] = {
                    'total': 0,
                    'with_email': 0,
                    'without_email': 0
                }
        
            verification['divisions'][division]['total'] += 1
        
            # Check for email
            if email:
                verification['divisions'][division]['with_email'] += 1
            
                # Track duplicates
                if email in email_to_coaches:
                    if email not in verification['duplicate_emails']:
                        verification['duplicate_emails'][email] = []
                    verification['duplicate_emails'][email].append({
                        'division': division,
                        'team': coach.get('team'),
                        'name': coach.get('coach_name')
                    })
                else:
                    email_to_coaches[email] = cache_key
            else:
                verification['divisions'][division]['without_email'] += 1
                verification['coaches_without_email'].append({
                    'division': division,
                    'team': coach.get('team'),
                    'name': coach.get('coach_name')
                })
    
        return verification
    
    def send_medical_forms_to_all_coaches(self, division_filter: List[str] = None, 
                                         dry_run: bool = False, 
                                         send_to_dc: bool = False) -> Dict[str, Any]:
        """
        Send medical forms emails to coaches
    
        Args:
            division_filter: List of divisions to process (None for all)
            dry_run: If True, don't actually send emails
            send_to_dc: If True, CC the division coordinator
        
        Returns:
            Dictionary with results
        """
        results = {
            'total_processed': 0,
            'sent_count': 0,
            'failed_count': 0,
            'dry_run': dry_run,
            'divisions_processed': {},
            'failed_emails': [],
            'timestamp': datetime.now().isoformat()
        }
    
        # Get the current season from configuration
        current_season = self.config.get('season', None)
        medical_season = self.config.get('medical_forms_config', {}).get('medical_forms_season', current_season)
    
        if not medical_season:
            logger.error("No season specified in configuration")
            results['failed_emails'].append({
                'email': 'N/A',
                'team': 'N/A',
                'error': 'No season configured - unable to match coaches'
            })
            return results
    
        logger.info(f"Sending medical forms for season: {medical_season}")
    
        # Get all coaches from cache for the current season
        all_coaches = self.coach_cache_manager.get_coaches_by_season(medical_season)
    
        if not all_coaches:
            logger.warning(f"No coaches found for season: {medical_season}")
            results['failed_emails'].append({
                'email': 'N/A',
                'team': 'N/A',
                'error': f'No coaches found for season {medical_season}'
            })
            return results
    
        # Filter by divisions if specified
        if division_filter:
            filtered_coaches = {}
            for key, coach in all_coaches.items():
                if coach.get('division') in division_filter:
                    filtered_coaches[key] = coach
            coaches_to_process = filtered_coaches
            logger.info(f"Filtered to {len(coaches_to_process)} coaches in divisions: {division_filter}")
        else:
            coaches_to_process = all_coaches
    
        results['total_processed'] = len(coaches_to_process)
    
        # Process each coach
        for cache_key, coach in coaches_to_process.items():
            division = coach.get('division')
            team = coach.get('team')
            coach_name = coach.get('coach_name')
            coach_email = coach.get('coach_email')
            season = coach.get('season')
        
            # Track division statistics
            if division not in results['divisions_processed']:
                results['divisions_processed'][division] = {
                    'total': 0,
                    'sent': 0,
                    'failed': 0,
                    'season': season
                }
        
            results['divisions_processed'][division]['total'] += 1
        
            if not coach_email:
                logger.warning(f"No email for coach of {team} in {division}")
                results['failed_count'] += 1
                results['divisions_processed'][division]['failed'] += 1
                results['failed_emails'].append({
                    'email': 'N/A',
                    'team': f"{team} ({division})",
                    'error': 'No email address'
                })
                continue
        
            try:
                if dry_run:
                    logger.info(f"[DRY RUN] Would send email to {coach_name} ({coach_email}) for {team} in {division} - {season}")
                    if send_to_dc:
                        dc_email = self._get_division_coordinator_email(division)
                        logger.info(f"[DRY RUN] Would CC division coordinator: {dc_email}")
                    results['sent_count'] += 1
                    results['divisions_processed'][division]['sent'] += 1
                else:
                    # Find the medical form PDF
                    pdf_path = self._find_medical_form(division, team)
                    if not pdf_path:
                        logger.error(f"Medical form PDF not found for {team} in {division}")
                        results['failed_count'] += 1
                        results['divisions_processed'][division]['failed'] += 1
                        results['failed_emails'].append({
                            'email': coach_email,
                            'team': f"{team} ({division})",
                            'error': 'PDF file not found'
                        })
                        continue
                
                    # Send the email with CC option
                    success = self._send_coach_email(coach_name, coach_email, team, division, cc_division_coordinator=send_to_dc)

                    # success = self._send_medical_forms_email(
                    #     coach_email, coach_name, team, division, pdf_path, 
                    #     cc_division_coordinator=send_to_dc
                    # )
                
                    if success:
                        logger.info(f"Email sent to {coach_name} ({coach_email}) for {team} in {division}")
                        results['sent_count'] += 1
                        results['divisions_processed'][division]['sent'] += 1
                    
                        # Track the email
                        self.email_tracker.record_email_sent(
                            coach_cache_key=cache_key,
                            coach_info={
                                'division': division,
                                'team': team,
                                'coach_name': coach_name,
                                'coach_email': coach_email,
                                'season': current_season,
                            },
                            email_type='medical_forms',
                            cc_email=self._get_division_coordinator_email(division) if send_to_dc else None,                            
                            attachment_info={
                                'filename': f"{team} Medical Forms.pdf",
                                'type': 'pdf'
                            },
                            success=True
                        )
 
                        # Delay between emails to avoid rate limits
                        time.sleep(self.delay_between_emails)
                    else:
                        results['failed_count'] += 1
                        results['divisions_processed'][division]['failed'] += 1
                        results['failed_emails'].append({
                            'email': coach_email,
                            'team': f"{team} ({division})",
                            'error': 'Email send failed'
                        })
                 
                    # Rate limiting
                    time.sleep(2)  # Wait between emails to avoid rate limits
                
            except Exception as e:
                logger.error(f"Error processing coach {coach_name}: {e}")
                results['failed_count'] += 1
                results['divisions_processed'][division]['failed'] += 1
                results['failed_emails'].append({
                    'email': coach_email,
                    'team': f"{team} ({division})",
                    'error': str(e)
                })
    
        # Log summary by division
        logger.info(f"\nEmail distribution summary for season {medical_season}:")
        for division, stats in results['divisions_processed'].items():
            logger.info(f"  {division}: {stats['sent']}/{stats['total']} sent ({stats['failed']} failed)")
    
        return results

    def send_medical_forms_to_team(self, team_prefix: str, dry_run: bool = False, reason: str = None) -> Dict[str, Any]:
        """
        Send medical forms email to a specific team using its prefix
    
        Args:
            team_prefix: Team identifier like '16UB-01 Hart' or just '16UB Hart'
            dry_run: If True, don't actually send emails
            reason: Optional reason for sending (e.g., "NEW PLAYER")
    
        Returns:
            Dictionary with results
        """
        results = {
            'team_prefix': team_prefix,
            'sent_count': 0,
            'failed_count': 0,
            'dry_run': dry_run,
            'timestamp': datetime.now().isoformat(),
            'sent_emails': [],
            'failed_emails': []
        }
    
        # ... existing code to find the team ...
    
        # In the section where the email is sent:
        if dry_run:
            logger.info(f"DRY RUN: Would send email to {coach_email} for {team}")
            if reason:
                logger.info(f"  Subject would include: {reason}")
            results['sent_emails'].append({
                'email': coach_email,
                'team': team,
                'division': division,
                'coach': coach_name,
                'attachment': str(form_path),
                'dry_run': True,
                'reason': reason  # ADDED
            })
            results['sent_count'] = 1
        else:
            # MODIFIED: Pass reason to _send_coach_email
            success = self._send_coach_email(coach_name, coach_email, team, division, reason=reason)
        
            if success:
                results['sent_count'] = 1
                # Track in email send history with correct method name
                self.email_tracker.record_email_sent(
                    coach_cache_key=cache_key,
                    coach_info={
                        'division': division,
                        'team': team,
                        'coach_name': coach_name,
                        'coach_email': coach_email,
                        'season': current_season
                    },
                    email_type='medical_forms',
                    attachment_info={
                        'filename': f"{team} Medical Forms.pdf",
                        'type': 'pdf'
                    },
                    additional_info={'reason': reason} if reason else None,  # ADDED
                    success=True
                )
            
                # ADDED: Include reason in results
                results['sent_emails'].append({
                    'email': coach_email,
                    'team': team,
                    'division': division,
                    'coach': coach_name,
                    'reason': reason
                })

    
    def verify_coaches_before_sending(self, division_filter: List[str] = None) -> Dict[str, Any]:
        """
        Verify coach information before sending emails
    
        Args:
            division_filter: Optional list of divisions to check
        
        Returns:
            Verification results
        """
        # Get the current season
        current_season = self.config.get('season', None)
        medical_season = self.config.get('medical_forms_config', {}).get('medical_forms_season', current_season)
    
        if not medical_season:
            return {
                'error': 'No season configured',
                'season': None,
                'total_coaches': 0
            }
    
        # Get coaches for the season
        coaches = self.coach_cache_manager.get_coaches_by_season(medical_season)
    
        if division_filter:
            coaches = {k: v for k, v in coaches.items() if v.get('division') in division_filter}
    
        verification = {
            'season': medical_season,
            'total_coaches': len(coaches),
            'divisions': {},
            'coaches_without_email': [],
            'coaches_without_forms': [],
            'ready_to_send': []
        }
    
        # Check each coach
        for cache_key, coach in coaches.items():
            division = coach.get('division')
            team = coach.get('team')
            email = coach.get('coach_email', '')
        
            # Initialize division stats
            if division not in verification['divisions']:
                verification['divisions'][division] = {
                    'total': 0,
                    'with_email': 0,
                    'with_forms': 0,
                    'ready': 0
                }
        
            verification['divisions'][division]['total'] += 1
        
            # Check email
            has_email = bool(email)
            if has_email:
                verification['divisions'][division]['with_email'] += 1
            else:
                verification['coaches_without_email'].append({
                    'division': division,
                    'team': team,
                    'coach': coach.get('coach_name', 'Unknown')
                })
        
            # Check forms
            has_forms = self._check_medical_forms_exist(division, team)
            if has_forms:
                verification['divisions'][division]['with_forms'] += 1
            else:
                verification['coaches_without_forms'].append({
                    'division': division,
                    'team': team,
                    'coach': coach.get('coach_name', 'Unknown')
                })
        
            # Check if ready to send
            if has_email and has_forms:
                verification['divisions'][division]['ready'] += 1
                verification['ready_to_send'].append({
                    'division': division,
                    'team': team,
                    'coach': coach.get('coach_name'),
                    'email': email
                })
    
        return verification

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
    
    ## Redundant
    # def _send_medical_forms_email(self, to_email: str, coach_name: str, 
    #                             team_name: str, division: str, 
    #                             attachment_path: Path) -> bool:
    #     """Send email with medical forms attachment"""
    #     try:
    #         # Create email content
    #         subject = self.subject_template.format(team_name=team_name, division=division)
    #         body = self._create_email_body(coach_name, team_name, division)
            
    #         if self.test_mode and self.test_email:
    #             logger.info(f"TEST MODE: Would send to {to_email}, actually sending to {self.test_email}")
    #             actual_recipient = self.test_email.strip()
    #         else:
    #             actual_recipient = to_email.strip()
    #             actual_recipient = "sdavis@davisportal.com"
            
    #         if self.email_method == 'oauth2' and self.gmail_service:
    #             # Use OAuth2 method
    #             return self._send_via_oauth2(
    #                 actual_recipient, subject, body, attachment_path
    #             )
    #         else:
    #             # Use SMTP method
    #             return self._send_via_smtp(
    #                 actual_recipient, subject, body, attachment_path
    #             )
                
    #     except Exception as e:
    #         logger.error(f"Failed to send email to {to_email}: {e}")
    #         return False
    
    def _create_email_body(self, coach_name: str, team_name: str, division: str, reason: str = None) -> str:
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
                .reason {{ background-color: #e3f2fd; border: 1px solid #90caf9; padding: 15px; margin: 15px 0; border-radius: 5px; }}
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
        """
    
        # ADDED: Include reason section if provided
        if reason:
            html_body += f"""
                    <div class="reason">
                        <strong>Reason for new forms:</strong> {reason}
                    </div>
            """
    
        html_body += f"""
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
                      attachment_path: Path, cc_email: str = None) -> bool:
        """Send email via SMTP with attachment"""
        try:
            # Create message
            msg = MIMEMultipart()
            msg['Subject'] = subject
            msg['From'] = f"{self.sender_name} <{self.sender_email}>"
            msg['To'] = to_email
            msg['Reply-To'] = self.reply_to
            
            # Add CC if provided
            if cc_email:
                msg['Cc'] = cc_email
                logger.info(f"CC'ing division coordinator: {cc_email}")
            
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
                
                # Create recipient list including CC
                recipients = [to_email]
                if cc_email:
                    recipients.append(cc_email)
                
                server.send_message(msg, from_addr=self.sender_email, to_addrs=recipients)
                
            logger.info(f"Email sent successfully to: {to_email}" + 
                       (f" (CC: {cc_email})" if cc_email else ""))
            return True
            
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return False
    
    def _send_via_oauth2(self, to_email: str, subject: str, body: str, 
                        attachment_path: Path, cc_email: str = None) -> bool:
        """Send email via Gmail OAuth2 with attachment"""
        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.base import MIMEBase
            from email import encoders
            import base64
        
            # Create message container
            msg = MIMEMultipart()
            msg['Subject'] = subject
            msg['From'] = self.sender_email
            msg['To'] = to_email
            msg['Reply-To'] = self.reply_to
            
            # Add CC if provided
            if cc_email:
                msg['Cc'] = cc_email
                logger.info(f"CC'ing division coordinator: {cc_email}")
        
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
                    logger.info(f"Email sent successfully via OAuth2 to: {to_email}" + 
                               (f" (CC: {cc_email})" if cc_email else ""))
                    return True
                except Exception as e:
                    logger.error(f"Gmail API error: {e}")
                    return False
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
            
            # Deprecated details, text file no longer has these keys
            # if results['sent_emails']:
            #     f.write("SENT EMAILS:\n")
            #     for item in results['sent_emails']:
            #         f.write(f"  - {item['email']} - {item['team']} ({item['division']})\n")
            #         f.write(f"    Attachment: {item['attachment']}\n")
            #     f.write("\n")
            
            # if results['failed_emails']:
            #     f.write("FAILED EMAILS:\n")
            #     for item in results['failed_emails']:
            #         error = item.get('error', 'Unknown error')
            #         f.write(f"  - {item['email']} - {item['team']} ({item['division']}) - {error}\n")
        
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