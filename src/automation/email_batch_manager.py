"""
Email Batch Manager for Sports Connect Automation
Handles sending targeted emails in controlled batches with tracking
"""
import os
import logging
import pandas as pd
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from automation.waitlist_notifier import WaitlistNotifier
from core.config import ConfigManager

logger = logging.getLogger(__name__)


class EmailBatchManager:
    """Manages batch email sending with division filtering and tracking"""
    
    def __init__(self, config: ConfigManager):
        """
        Initialize Email Batch Manager
        
        Args:
            config: Configuration manager instance
        """
        self.config = config
        self.notifier = WaitlistNotifier(config)
        
        # Tracking directory
        self.tracking_dir = Path(config.get('email_batch_tracking_dir', 'data/email_batch_tracking'))
        self.tracking_dir.mkdir(parents=True, exist_ok=True)
        
        # Current session tracking
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = self.tracking_dir / f"session_{self.session_id}.json"
        
        # Email templates directory
        self.templates_dir = Path('config/email_templates')
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        # Batch configuration
        self.batch_size = 10
        self.current_batch = []
        self.sent_emails = set()
        self.failed_emails = set()
        
        # Load historical tracking
        self.load_sent_history()
    
    def load_sent_history(self) -> Set[str]:
        """Load previously sent emails from all sessions"""
        self.sent_emails = set()
        
        try:
            # Load all session files
            session_files = list(self.tracking_dir.glob("session_*.json"))
            
            for session_file in session_files:
                try:
                    with open(session_file, 'r') as f:
                        session_data = json.load(f)
                        # Add emails from sent_emails list
                        for email in session_data.get('sent_emails', []):
                            self.sent_emails.add(email.lower())
                except Exception as e:
                    logger.warning(f"Error loading session file {session_file}: {e}")
            
            logger.info(f"Loaded {len(self.sent_emails)} previously sent emails from history")
            
        except Exception as e:
            logger.error(f"Error loading sent history: {e}")
        
        return self.sent_emails
    
    def save_session(self):
        """Save current session data"""
        session_data = {
            'session_id': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'sent_emails': list(self.sent_emails),
            'failed_emails': list(self.failed_emails),
            'total_sent': len(self.sent_emails),
            'total_failed': len(self.failed_emails)
        }
        
        try:
            with open(self.session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            logger.debug(f"Session data saved to {self.session_file}")
        except Exception as e:
            logger.error(f"Error saving session data: {e}")
    
    def load_enrollment_data(self, file_path: str) -> pd.DataFrame:
        """
        Load enrollment data from Excel file
        
        Args:
            file_path: Path to Enrollment_Details.xlsx
            
        Returns:
            DataFrame with enrollment data
        """
        try:
            logger.info(f"Loading enrollment data from: {file_path}")
            df = pd.read_excel(file_path)
            
            # Log info about the data
            logger.info(f"Loaded {len(df)} total enrollment records")
            
            # Get unique divisions
            divisions = df['Division Name'].unique()
            logger.info(f"Found {len(divisions)} unique divisions")
            
            return df
            
        except Exception as e:
            logger.error(f"Error loading enrollment data: {e}")
            raise
    
    def filter_by_division(self, df: pd.DataFrame, division: str) -> pd.DataFrame:
        """
        Filter enrollment data by division
        
        Args:
            df: Enrollment DataFrame
            division: Division to filter (e.g., "10UB")
            
        Returns:
            Filtered DataFrame
        """
        # Filter by division name containing the division code
        filtered = df[df['Division Name'].str.contains(division, na=False)]
        logger.info(f"Filtered to {len(filtered)} records for division {division}")
        return filtered
    
    def prepare_email_batch(self, df: pd.DataFrame, exclude_sent: bool = True) -> List[Dict]:
        """
        Prepare a batch of emails from enrollment data
        
        Args:
            df: Filtered enrollment DataFrame
            exclude_sent: Whether to exclude previously sent emails
            
        Returns:
            List of email records ready to send
        """
        email_records = []
        
        for _, row in df.iterrows():
            # Get email and parent info
            email = str(row.get('User Email', '')).strip().lower()
            parent_first = str(row.get('Account First Name', '')).strip()
            parent_last = str(row.get('Account Last Name', '')).strip()
            player_first = str(row.get('Player First Name', '')).strip()
            player_last = str(row.get('Player Last Name', '')).strip()
            division = str(row.get('Division Name', '')).strip()
            
            # Skip if no email
            if not email or email == 'nan':
                continue
            
            # Skip if already sent (if requested)
            if exclude_sent and email in self.sent_emails:
                logger.debug(f"Skipping {email} - already sent")
                continue
            
            # Create email record
            record = {
                'email': email,
                'parent_first_name': parent_first,
                'parent_last_name': parent_last,
                'player_first_name': player_first,
                'player_last_name': player_last,
                'division': division,
                'order_no': row.get('Order No', ''),
                'order_date': row.get('Order Date', ''),
                'order_amount': row.get('Order Amount', 0)
            }
            
            email_records.append(record)
        
        logger.info(f"Prepared {len(email_records)} email records")
        return email_records
    
    def get_next_batch(self, email_records: List[Dict], batch_size: int = None) -> List[Dict]:
        """
        Get the next batch of emails to send
        
        Args:
            email_records: List of all email records
            batch_size: Size of batch (default: self.batch_size)
            
        Returns:
            List of email records for the next batch
        """
        if batch_size is None:
            batch_size = self.batch_size
        
        # Get records that haven't been sent
        unsent_records = [r for r in email_records if r['email'] not in self.sent_emails]
        
        # Return the next batch
        next_batch = unsent_records[:batch_size]
        logger.info(f"Next batch contains {len(next_batch)} emails")
        
        return next_batch
    
    def format_email_content(self, record: Dict, template: str, reply_date: str) -> Tuple[str, str]:
        """
        Format email content with template variables
        
        Args:
            record: Email record with recipient info
            template: Email template with placeholders
            reply_date: Reply by date
            
        Returns:
            Tuple of (subject, body)
        """
        # Extract division code (e.g., "10UB" from "10UB - Boys 8 and 9 yr old, born 2016 or 2017")
        division_code = record['division'].split(' - ')[0] if ' - ' in record['division'] else record['division']
        
        # Replace template variables
        replacements = {
            '{parentFirstName}': record['parent_first_name'],
            '{parentLastName}': record['parent_last_name'],
            '{playerFirstName}': record['player_first_name'],
            '{playerLastName}': record['player_last_name'],
            '{division}': division_code,
            '{fullDivision}': record['division'],
            '{replyDate}': reply_date,
            '{orderNo}': str(record['order_no']),
            '{orderAmount}': f"${record['order_amount']:.2f}" if record['order_amount'] else "$0.00"
        }
        
        formatted_template = template
        for key, value in replacements.items():
            formatted_template = formatted_template.replace(key, value)
        
        # Split subject and body
        lines = formatted_template.strip().split('\n')
        subject_line = ""
        body_lines = []
        
        for i, line in enumerate(lines):
            if line.startswith('Subject:'):
                subject_line = line.replace('Subject:', '').strip()
                body_lines = lines[i+1:]
                break
        
        body = '\n'.join(body_lines).strip()
        
        return subject_line, body
    
    def send_batch(self, batch: List[Dict], template: str, reply_date: str, 
                   test_mode: bool = False) -> Dict[str, int]:
        """
        Send a batch of emails
        
        Args:
            batch: List of email records to send
            template: Email template
            reply_date: Reply by date
            test_mode: Whether to run in test mode
            
        Returns:
            Dictionary with send statistics
        """
        logger.info(f"Sending batch of {len(batch)} emails...")
        
        sent_count = 0
        failed_count = 0
        
        for i, record in enumerate(batch):
            try:
                # Format email content
                subject, body = self.format_email_content(record, template, reply_date)
                
                # Log what we're sending
                logger.info(f"[{i+1}/{len(batch)}] Sending to {record['email']}")
                logger.debug(f"Subject: {subject}")
                
                if test_mode:
                    # In test mode, just log
                    logger.info(f"TEST MODE: Would send to {record['email']}")
                    logger.info(f"Body preview: {body[:200]}...")
                    sent_count += 1
                else:
                    # Send the email
                    success = self._send_single_email(
                        record['email'],
                        subject,
                        body,
                        record['parent_first_name']
                    )
                    
                    if success:
                        self.sent_emails.add(record['email'])
                        sent_count += 1
                        logger.info(f"✓ Successfully sent to {record['email']}")
                    else:
                        self.failed_emails.add(record['email'])
                        failed_count += 1
                        logger.error(f"✗ Failed to send to {record['email']}")
                
                # Rate limiting
                if i < len(batch) - 1:  # Don't delay after last email
                    delay = self.notifier.delay_between_emails
                    logger.debug(f"Waiting {delay} seconds before next email...")
                    time.sleep(delay)
                
            except Exception as e:
                logger.error(f"Error processing email for {record['email']}: {e}")
                self.failed_emails.add(record['email'])
                failed_count += 1
        
        # Save session after each batch
        self.save_session()
        
        stats = {
            'sent': sent_count,
            'failed': failed_count,
            'total': len(batch)
        }
        
        logger.info(f"Batch complete: {sent_count} sent, {failed_count} failed")
        return stats
    
    def _send_single_email(self, recipient: str, subject: str, body: str, 
                          recipient_name: str = None) -> bool:
        """
        Send a single email using the configured method
        
        Args:
            recipient: Email address
            subject: Email subject
            body: Email body
            recipient_name: Recipient's name
            
        Returns:
            True if successful
        """
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = f"{self.notifier.sender_name} <{self.notifier.sender_email}>"
            msg['To'] = recipient
            msg['Subject'] = subject
            msg['Reply-To'] = self.notifier.reply_to
            
            # Add body
            msg.attach(MIMEText(body, 'plain'))
            
            # Send using configured method
            if self.notifier.email_method == 'oauth2' and self.notifier.gmail_service:
                return self.notifier.gmail_service.send_message(
                    recipient,
                    subject,
                    body,
                    sender_name=self.notifier.sender_name
                )
            else:
                # Use SMTP
                return self.notifier._send_smtp_email(msg)
                
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False
    
    def get_summary_report(self) -> Dict:
        """Get a summary report of email sending activity"""
        
        # Load all sessions for complete history
        all_sessions = []
        session_files = sorted(self.tracking_dir.glob("session_*.json"))
        
        for session_file in session_files:
            try:
                with open(session_file, 'r') as f:
                    all_sessions.append(json.load(f))
            except:
                continue
        
        # Calculate totals
        total_sent = len(self.sent_emails)
        total_failed = len(self.failed_emails)
        
        report = {
            'current_session': {
                'id': self.session_id,
                'sent': len([e for e in self.sent_emails if e not in self.load_sent_history()]),
                'failed': len(self.failed_emails),
                'timestamp': datetime.now().isoformat()
            },
            'all_time': {
                'total_sent': total_sent,
                'total_failed': total_failed,
                'unique_recipients': total_sent,
                'sessions': len(all_sessions)
            },
            'recent_sessions': all_sessions[-5:]  # Last 5 sessions
        }
        
        return report
    
    def export_sent_list(self, output_file: str = None) -> str:
        """
        Export list of sent emails to CSV
        
        Args:
            output_file: Output file path (optional)
            
        Returns:
            Path to exported file
        """
        if not output_file:
            output_file = self.tracking_dir / f"sent_emails_{self.session_id}.csv"
        
        # Create DataFrame
        sent_data = []
        for email in sorted(self.sent_emails):
            sent_data.append({
                'email': email,
                'sent': 'Yes',
                'timestamp': datetime.now().isoformat()
            })
        
        df = pd.DataFrame(sent_data)
        df.to_csv(output_file, index=False)
        
        logger.info(f"Exported {len(sent_data)} sent emails to {output_file}")
        return str(output_file)


class EmailBatchCLI:
    """Command-line interface for email batch sending"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.manager = EmailBatchManager(config)
        
    def run_interactive(self):
        """Run interactive email batch sending session"""
        print("\n" + "="*60)
        print("AYSO Email Batch Manager")
        print("="*60)
        
        # Load enrollment data
        enrollment_file = input("\nEnter path to Enrollment_Details.xlsx: ").strip()
        if not os.path.exists(enrollment_file):
            print(f"Error: File not found: {enrollment_file}")
            return
        
        try:
            df = self.manager.load_enrollment_data(enrollment_file)
        except Exception as e:
            print(f"Error loading file: {e}")
            return
        
        # Show available divisions
        divisions = sorted(df['Division Name'].unique())
        print(f"\nFound {len(divisions)} divisions:")
        for i, div in enumerate(divisions, 1):
            print(f"  {i}. {div}")
        
        # Select division
        div_input = input("\nEnter division number or division code (e.g., 10UB): ").strip()
        
        if div_input.isdigit():
            div_idx = int(div_input) - 1
            if 0 <= div_idx < len(divisions):
                selected_division = divisions[div_idx]
            else:
                print("Invalid division number")
                return
        else:
            # Search for division containing the code
            matching = [d for d in divisions if div_input.upper() in d.upper()]
            if matching:
                selected_division = matching[0]
            else:
                print(f"No division found matching '{div_input}'")
                return
        
        print(f"\nSelected division: {selected_division}")
        
        # Filter data
        filtered_df = self.manager.filter_by_division(df, selected_division.split(' - ')[0])
        
        # Prepare email records
        email_records = self.manager.prepare_email_batch(filtered_df)
        
        print(f"\nPrepared {len(email_records)} unique email recipients")
        print(f"(Excluded {len(filtered_df) - len(email_records)} duplicate or previously sent)")
        
        if not email_records:
            print("\nNo emails to send!")
            return
        
        # Get email template
        print("\nEmail Template:")
        print("-" * 40)
        default_template = """Subject: Quick Check – {division} Fall Core

Hi {parentFirstName},

The coach draft for the upcoming {division} season is coming up soon, and we're confirming final rosters. **This is not meant to encourage anyone to drop**, but if your player will not be participating, please let us know before the draft so we can open the spot to a waitlisted player.

Even though we're past the refund deadline, we can offer a full refund of your program fee (minus the $25 AYSO National Membership Fee) if you withdraw **before the coach draft**. This offer is only available through **{replyDate}**.

If your child is playing, no action is needed. If you do wish to drop, reply to this email by **{replyDate}**.

Thanks,
Steve Davis
Registrar – AYSO Region 58"""
        
        use_default = input("\nUse default template? (y/n): ").lower() == 'y'
        
        if use_default:
            template = default_template
        else:
            print("\nEnter custom template (use {variables} for placeholders)")
            print("Available variables: {parentFirstName}, {division}, {replyDate}")
            print("End with a blank line:")
            
            lines = []
            while True:
                line = input()
                if not line:
                    break
                lines.append(line)
            template = '\n'.join(lines)
        
        # Get reply date
        reply_date = input("\nEnter reply by date (e.g., Friday, August 30): ").strip()
        
        # Test mode?
        test_mode = input("\nRun in TEST MODE? (y/n): ").lower() == 'y'
        
        if test_mode:
            print("\n*** TEST MODE ENABLED - No emails will actually be sent ***")
        
        # Batch size
        batch_size_input = input(f"\nBatch size (default {self.manager.batch_size}): ").strip()
        if batch_size_input.isdigit():
            self.manager.batch_size = int(batch_size_input)
        
        # Start sending batches
        total_sent = 0
        batch_num = 0
        
        while True:
            # Get next batch
            next_batch = self.manager.get_next_batch(email_records)
            
            if not next_batch:
                print("\nNo more emails to send!")
                break
            
            batch_num += 1
            print(f"\n" + "="*60)
            print(f"Batch #{batch_num} - {len(next_batch)} emails")
            print("="*60)
            
            # Show preview
            print("\nRecipients in this batch:")
            for i, record in enumerate(next_batch[:5], 1):
                print(f"  {i}. {record['email']} ({record['parent_first_name']} {record['parent_last_name']})")
            if len(next_batch) > 5:
                print(f"  ... and {len(next_batch) - 5} more")
            
            # Confirm send
            if test_mode:
                confirm = input("\nSend TEST batch? (y/n): ").lower()
            else:
                confirm = input("\n*** SEND THIS BATCH? *** (y/n): ").lower()
            
            if confirm != 'y':
                print("Batch skipped")
                continue
            
            # Send batch
            stats = self.manager.send_batch(next_batch, template, reply_date, test_mode)
            total_sent += stats['sent']
            
            print(f"\nBatch complete: {stats['sent']} sent, {stats['failed']} failed")
            print(f"Total sent so far: {total_sent}")
            
            # Continue?
            if len(email_records) > total_sent:
                remaining = len(email_records) - total_sent
                cont = input(f"\nSend next batch? ({remaining} remaining) (y/n): ").lower()
                if cont != 'y':
                    break
            else:
                print("\nAll emails have been sent!")
                break
        
        # Summary
        print("\n" + "="*60)
        print("SESSION SUMMARY")
        print("="*60)
        
        summary = self.manager.get_summary_report()
        print(f"Session ID: {summary['current_session']['id']}")
        print(f"Emails sent: {summary['current_session']['sent']}")
        print(f"Emails failed: {summary['current_session']['failed']}")
        print(f"Total unique recipients: {summary['all_time']['total_sent']}")
        
        # Export option
        export = input("\nExport sent list to CSV? (y/n): ").lower()
        if export == 'y':
            export_file = self.manager.export_sent_list()
            print(f"Exported to: {export_file}")
        
        print("\nSession complete!")


# Integration point for main.py
def handle_email_batch(config: ConfigManager, args) -> int:
    """
    Handle email batch operations from command line
    
    Args:
        config: Configuration manager
        args: Command line arguments
        
    Returns:
        Exit code
    """
    logger.info("Starting Email Batch Manager")
    
    try:
        cli = EmailBatchCLI(config)
        cli.run_interactive()
        return 0
    except Exception as e:
        logger.error(f"Error in email batch manager: {e}")
        return 1
