"""
Payment Reminder Manager for Sports Connect Automation
Handles sending payment reminders for outstanding orders
"""
import os
import json
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

logger = logging.getLogger(__name__)


class PaymentReminderManager:
    """Manages payment reminders for outstanding orders"""
    
    def __init__(self, config=None, open_orders_file: str = None):
        """
        Initialize Payment Reminder Manager
        
        Args:
            config: Configuration manager instance
            open_orders_file: Path to Open Orders Line Item file
        """
        self.config = config
        self.open_orders_file = open_orders_file
        self.open_orders_df = None
        
        # Email configuration
        email_config = config.get('email_config', {}) if config else {}
        self.smtp_server = email_config.get('smtp_server', 'smtp.gmail.com')
        self.smtp_port = email_config.get('smtp_port', 587)
        self.sender_email = email_config.get('sender_email', 'registrar@ayso58.org')
        self.sender_password = email_config.get('sender_password', '')
        self.sender_name = email_config.get('sender_name', 'AYSO Region 58 Registrar')
        
        # Email log tracking
        self.email_log_file = self._get_email_log_path()
        self.email_log = self._load_email_log()
        
        # Payment holds/exceptions tracking
        self.holds_file = self._get_holds_file_path()
        self.payment_holds = self._load_payment_holds()
        
        # Gmail OAuth support (optional)
        self.gmail_service = None
        self.email_method = email_config.get('method', 'smtp')
        if self.email_method == 'oauth2':
            try:
                from integrations.gmail_oauth import GmailOAuth2Service
                self.gmail_service = GmailOAuth2Service()
            except Exception as e:
                logger.warning(f"Gmail OAuth not available, falling back to SMTP: {e}")
                self.email_method = 'smtp'
    
    def _get_email_log_path(self) -> str:
        """Get path for email log file"""
        data_dir = self.config.get('paths.data_dir', 'data') if self.config else 'data'
        log_dir = Path(data_dir) / 'payment_reminders'
        log_dir.mkdir(parents=True, exist_ok=True)
        return str(log_dir / 'payment_reminder_log.json')
    
    def _load_email_log(self) -> List[Dict]:
        """Load email log from file"""
        if os.path.exists(self.email_log_file):
            try:
                with open(self.email_log_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading email log: {e}")
                return []
        return []
    
    def _save_email_log(self):
        """Save email log to file"""
        try:
            with open(self.email_log_file, 'w') as f:
                json.dump(self.email_log, f, indent=2, default=str)
            logger.debug(f"Email log saved to {self.email_log_file}")
        except Exception as e:
            logger.error(f"Error saving email log: {e}")
    
    def _get_holds_file_path(self) -> str:
        """Get path for payment holds file"""
        data_dir = self.config.get('paths.data_dir', 'data') if self.config else 'data'
        log_dir = Path(data_dir) / 'payment_reminders'
        log_dir.mkdir(parents=True, exist_ok=True)
        return str(log_dir / 'payment_holds.json')
    
    def _load_payment_holds(self) -> Dict[str, Dict]:
        """Load payment holds from file"""
        if os.path.exists(self.holds_file):
            try:
                with open(self.holds_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading payment holds: {e}")
                return {}
        return {}
    
    def _save_payment_holds(self):
        """Save payment holds to file"""
        try:
            with open(self.holds_file, 'w') as f:
                json.dump(self.payment_holds, f, indent=2, default=str)
            logger.debug(f"Payment holds saved to {self.holds_file}")
        except Exception as e:
            logger.error(f"Error saving payment holds: {e}")
    
    def add_payment_hold(self, order_no: str, reason: str, hold_until_date: Optional[str] = None,
                        player_info: Optional[Dict] = None) -> bool:
        """
        Add a payment hold for an order
        
        Args:
            order_no: Order number to hold
            reason: Reason for the hold
            hold_until_date: Optional date to automatically remove hold (ISO format)
            player_info: Optional player information
            
        Returns:
            True if successful
        """
        try:
            hold_entry = {
                'order_no': str(order_no),
                'reason': reason,
                'hold_date': datetime.now().isoformat(),
                'hold_until_date': hold_until_date,
                'added_by': 'system',
                'active': True
            }
            
            # Add player info if available
            if player_info:
                hold_entry.update({
                    'player_first_name': player_info.get('Player First Name', ''),
                    'player_last_name': player_info.get('Player Last Name', ''),
                    'division_name': player_info.get('Division Name', ''),
                    'user_email': player_info.get('User Email', '')
                })
            
            self.payment_holds[str(order_no)] = hold_entry
            self._save_payment_holds()
            
            logger.info(f"Added payment hold for order {order_no}: {reason}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding payment hold: {e}")
            return False
    
    def remove_payment_hold(self, order_no: str, removal_reason: str = None) -> bool:
        """
        Remove a payment hold
        
        Args:
            order_no: Order number to remove hold from
            removal_reason: Optional reason for removal
            
        Returns:
            True if successful
        """
        try:
            order_no = str(order_no)
            if order_no in self.payment_holds:
                self.payment_holds[order_no]['active'] = False
                self.payment_holds[order_no]['removed_date'] = datetime.now().isoformat()
                if removal_reason:
                    self.payment_holds[order_no]['removal_reason'] = removal_reason
                
                self._save_payment_holds()
                logger.info(f"Removed payment hold for order {order_no}")
                return True
            else:
                logger.warning(f"No payment hold found for order {order_no}")
                return False
                
        except Exception as e:
            logger.error(f"Error removing payment hold: {e}")
            return False
    
    def is_order_on_hold(self, order_no: str) -> Tuple[bool, Optional[str]]:
        """
        Check if an order has an active payment hold
        
        Args:
            order_no: Order number to check
            
        Returns:
            Tuple of (is_on_hold, reason)
        """
        order_no = str(order_no)
        if order_no in self.payment_holds:
            hold = self.payment_holds[order_no]
            
            # Check if hold is active
            if not hold.get('active', True):
                return False, None
            
            # Check if hold has expired
            if hold.get('hold_until_date'):
                try:
                    hold_until = datetime.fromisoformat(hold['hold_until_date'])
                    if datetime.now() > hold_until:
                        # Auto-expire the hold
                        self.remove_payment_hold(order_no, "Hold automatically expired")
                        return False, None
                except:
                    pass
            
            return True, hold.get('reason', 'No reason specified')
        
        return False, None
    
    def get_all_active_holds(self) -> List[Dict]:
        """Get all active payment holds"""
        active_holds = []
        
        for order_no, hold in self.payment_holds.items():
            if hold.get('active', True):
                # Check expiration
                is_on_hold, _ = self.is_order_on_hold(order_no)
                if is_on_hold:
                    active_holds.append(hold)
        
        return active_holds
    
    def load_open_orders(self, file_path: str = None) -> bool:
        """
        Load Open Orders Line Item data
        
        Args:
            file_path: Path to Open Orders file (uses latest if not provided)
            
        Returns:
            True if successful
        """
        try:
            if file_path:
                self.open_orders_file = file_path
            elif not self.open_orders_file:
                # Find latest Open Orders file
                download_dir = self.config.get('paths.download_dir', 'data/downloads') if self.config else 'data/downloads'
                self.open_orders_file = self._find_latest_open_orders_file(download_dir)
            
            logger.info(f"Loading Open Orders data from: {self.open_orders_file}")
            self.open_orders_df = pd.read_excel(self.open_orders_file)
            
            # Filter for pending orders with balance due
            self.open_orders_df = self.open_orders_df[
                (self.open_orders_df['Order Payment Status'] == 'Pending') &
                (self.open_orders_df['Order Item Balance'] > 0)
            ]
            
            logger.info(f"Loaded {len(self.open_orders_df)} pending orders with balance due")
            return True
            
        except Exception as e:
            logger.error(f"Error loading Open Orders data: {e}")
            return False
    
    def _find_latest_open_orders_file(self, download_dir: str) -> str:
        """Find the most recent Open Orders Line Item file"""
        import glob
        
        patterns = [
            "Open_Orders_Line_Item*.xlsx",
            "*Open*Orders*.xlsx",
            "OpenOrders*.xlsx"
        ]
        
        files = []
        for pattern in patterns:
            files.extend(glob.glob(os.path.join(download_dir, pattern)))
        
        if not files:
            raise FileNotFoundError(f"No Open Orders files found in {download_dir}")
        
        # Get the most recent file
        return max(files, key=os.path.getmtime)
    
    def get_pending_orders_for_notification(self, is_final_notice: bool = False) -> pd.DataFrame:
        """
        Get pending orders that need notification with reminder count
    
        Args:
            is_final_notice: Whether this is for final notices
        
        Returns:
            DataFrame with orders to notify, including reminder_count column
        """
        if self.open_orders_df is None:
            return pd.DataFrame()
    
        # Apply base filtering criteria (from SQL query)
        # 1. Program Name contains '2025'
        program_filter = self.open_orders_df['Program Name'].str.contains('2025', case=False, na=False)
    
        # 2. Order Item Balance > 99
        balance_filter = self.open_orders_df['Order Item Balance'] > 99
    
        # 3. Order Payment Status = 'Pending'
        status_filter = self.open_orders_df['Order Payment Status'] == 'Pending'
    
        # Start with orders that meet base criteria
        eligible_orders = self.open_orders_df[program_filter & balance_filter & status_filter].copy()
    
        if eligible_orders.empty:
            logger.info("No orders meet base criteria for payment reminders")
            return pd.DataFrame()
    
        # Ensure Order No is string type for consistent comparison
        eligible_orders['Order No'] = eligible_orders['Order No'].astype(str)
    
        # Generate Payment URL if not already present
        if 'PaymentURL' not in eligible_orders.columns:
            url_prefix = "https://www.ayso58.org/Default.aspx?tabid=813703&"
            eligible_orders['PaymentURL'] = url_prefix + eligible_orders['Order No']
    
        # Calculate reminder counts for each order
        reminder_counts = {}
        regular_reminder_counts = {}
        final_notice_counts = {}
        last_reminder_dates = {}
    
        for log in self.email_log:
            order_no = str(log.get('order_no', ''))
            if not order_no:
                continue
            
            # Count total reminders
            if order_no not in reminder_counts:
                reminder_counts[order_no] = 0
            reminder_counts[order_no] += 1
        
            # Count by type
            if log.get('final_notice', False):
                if order_no not in final_notice_counts:
                    final_notice_counts[order_no] = 0
                final_notice_counts[order_no] += 1
            else:
                if order_no not in regular_reminder_counts:
                    regular_reminder_counts[order_no] = 0
                regular_reminder_counts[order_no] += 1
        
            # Track last reminder date
            if order_no not in last_reminder_dates or log.get('email_sent_on', '') > last_reminder_dates[order_no]:
                last_reminder_dates[order_no] = log.get('email_sent_on', '')
    
        # Get order numbers that have received reminders
        sent_orders = set(reminder_counts.keys())
        orders_with_final_notice = set(final_notice_counts.keys())
    
        # Get orders currently on hold
        active_holds = self.get_all_active_holds()
        orders_on_hold = {str(hold['order_no']) for hold in active_holds}
    
        # Add reminder count to eligible_orders first for filtering
        eligible_orders['total_reminders'] = eligible_orders['Order No'].map(reminder_counts).fillna(0).astype(int)
        eligible_orders['regular_reminders'] = eligible_orders['Order No'].map(regular_reminder_counts).fillna(0).astype(int)
        eligible_orders['final_notices'] = eligible_orders['Order No'].map(final_notice_counts).fillna(0).astype(int)
    
        if is_final_notice:
            # For final notices: orders that have 3 or more total reminders,
            # haven't had a final notice yet, and are not on hold
            mask = (
                (eligible_orders['total_reminders'] > 2) & 
                ~eligible_orders['Order No'].isin(orders_with_final_notice) &
                ~eligible_orders['Order No'].isin(orders_on_hold)
            )
            result = eligible_orders[mask].copy()
            logger.info(f"Found {len(result)} orders eligible for final notices (>2 reminders sent)")
        else:
            # For regular reminders: orders that have less than 3 total reminders
            # and are not on hold
            mask = (
                (eligible_orders['total_reminders'] < 3) &
                ~eligible_orders['Order No'].isin(orders_on_hold)
            )
            result = eligible_orders[mask].copy()
            logger.info(f"Found {len(result)} orders eligible for regular reminders (<3 reminders sent)")
    
        # Add reminder count information to the result
        if not result.empty:
            # Add total reminder count
            result['reminder_count'] = result['Order No'].map(reminder_counts).fillna(0).astype(int)
        
            # Add regular and final notice counts
            result['regular_reminder_count'] = result['Order No'].map(regular_reminder_counts).fillna(0).astype(int)
            result['final_notice_count'] = result['Order No'].map(final_notice_counts).fillna(0).astype(int)
        
            # Add last reminder date
            result['last_reminder_date'] = result['Order No'].map(last_reminder_dates).fillna('')
        
            # Calculate days since last reminder
            def calculate_days_since_reminder(date_str):
                if not date_str:
                    return None
                try:
                    last_date = datetime.fromisoformat(date_str.replace(' ', 'T'))
                    days_diff = (datetime.now() - last_date).days
                    return days_diff
                except:
                    return None
        
            result['days_since_last_reminder'] = result['last_reminder_date'].apply(calculate_days_since_reminder)
    
        # Log filtering statistics
        if len(result) > 0:
            logger.info(f"Pending orders breakdown:")
            logger.info(f"  - Meet base criteria: {len(eligible_orders)}")
            logger.info(f"  - Orders with 0 reminders: {len(eligible_orders[eligible_orders['total_reminders'] == 0])}")
            logger.info(f"  - Orders with 1-2 reminders: {len(eligible_orders[(eligible_orders['total_reminders'] > 0) & (eligible_orders['total_reminders'] < 3)])}")
            logger.info(f"  - Orders with 3+ reminders: {len(eligible_orders[eligible_orders['total_reminders'] >= 3])}")
            logger.info(f"  - Already sent final notices: {len(orders_with_final_notice)}")
            logger.info(f"  - Currently on hold: {len(orders_on_hold)}")
            logger.info(f"  - Eligible for {'final' if is_final_notice else 'regular'} notices: {len(result)}")
        
            # Show division breakdown
            division_counts = result['Division Name'].value_counts()
            logger.debug(f"By division: {dict(division_counts.head())}")
        
            # Show reminder statistics
            if 'reminder_count' in result.columns and result['reminder_count'].sum() > 0:
                logger.debug(f"Reminder statistics for eligible orders:")
                logger.debug(f"  - Average reminders sent: {result['reminder_count'].mean():.1f}")
                logger.debug(f"  - Max reminders sent: {result['reminder_count'].max()}")
            
                if 'days_since_last_reminder' in result.columns:
                    avg_days = result['days_since_last_reminder'].dropna().mean()
                    if not pd.isna(avg_days):
                        logger.debug(f"  - Average days since last reminder: {avg_days:.1f}")
    
        return result
    
    def generate_reminder_email(self, order_row: pd.Series, is_final_notice: bool = False) -> Tuple[str, str]:
        """
        Generate email subject and body for a payment reminder
        
        Args:
            order_row: Row from Open Orders DataFrame
            is_final_notice: Whether this is a final notice
            
        Returns:
            Tuple of (subject, body)
        """
        player_name = f"{order_row['Player First Name']} {order_row['Player Last Name']}"
        division = order_row['Division Name']
        amount = order_row['Order Item Balance']
        order_number = order_row['Order No']
        
        # Subject
        subject = f"{'FINAL NOTICE: ' if is_final_notice else ''}" \
                 f"AYSO Region 58: Outstanding Payment Reminder for {player_name})"
        
        # Body
        notice_text = ""
        if is_final_notice:
            notice_text = f"""This is a <b>FINAL NOTICE</b>. If payment is not received within <b>24 hours</b>, 
            your registration for {player_name} in the {division} division is subject to cancellation.
            <div><br></div>"""
        else:
            notice_text = f"""This is a reminder that your registration for {player_name} 
            in the {division} division has a balance due.
            <div><br></div>"""
        
        body = f"""
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
                    <h1>AYSO Region 58 - Payment Reminder</h1>
                </div>
        
                <div class="content">
                    <p>Dear {order_row.get('Account First Name', 'Parent/Guardian')},</p>

                    <p>{notice_text}</p>

                    <div class="important">
                        <strong>Amount Due:</strong> ${amount:.2f}
                        <strong>Order Number:</strong> {order_number}
                    </div>

                    <p>Please visit the AYSO Region 58 website to complete your payment:</p>
                    <p><a href='http://ayso58.org'>http://ayso58.org</a></p>

                    <p>If you are no longer interested in participating, you may simply reply to this email with the word <strong>Cancel</strong> and we will remove your registration.</p>

                    <p>Thank you for your prompt attention.</p>

                    <p>Best regards,<br>
                    {self.sender_name}</p>
                </div>

                <div class="footer">
                    <p>AYSO Region 58 | Everyone Plays®</p>
                </div>
            </div>
        </body>
        </html>
        """

        
        return subject, body
    
    def send_email(self, to_email: str, subject: str, body: str) -> bool:
        """
        Send an email
        
        Args:
            to_email: Recipient email
            subject: Email subject
            body: HTML email body
            
        Returns:
            True if successful
        """
        try:
            if self.email_method == 'oauth2' and self.gmail_service:
                # Use OAuth2 method
                return self.gmail_service.send_email(
                    sender='me',
                    to=to_email,
                    subject=subject,
                    body_html=body
                )
            else:
                # Use SMTP method
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = f"{self.sender_name} <{self.sender_email}>"
                msg['To'] = to_email
                
                html_part = MIMEText(body, 'html')
                msg.attach(html_part)
                
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.sender_email, self.sender_password)
                    server.send_message(msg)
                
                logger.info(f"Email sent to: {to_email}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
    
    def log_email_sent(self, order_row: pd.Series, is_final_notice: bool = False):
        """Log that an email was sent"""
        log_entry = {
            'id': len(self.email_log) + 1,
            'program_name': order_row.get('Program Name', ''),
            'account_first_name': order_row.get('Account First Name', ''),
            'account_last_name': order_row.get('Account Last Name', ''),
            'division_name': order_row.get('Division Name', ''),
            'player_first_name': order_row.get('Player First Name', ''),
            'player_last_name': order_row.get('Player Last Name', ''),
            'user_email': order_row.get('User Email', ''),
            'order_no': str(order_row.get('Order No', '')),
            'order_item_balance': float(order_row.get('Order Item Balance', 0)),
            'order_payment_status': order_row.get('Order Payment Status', ''),
            'payment_url': f"https://www.ayso58.org/Default.aspx?tabid=813703&{order_row.get('Order No', '')}",
            'email_sent_on': datetime.now().isoformat(),
            'final_notice': is_final_notice
        }
        
        self.email_log.append(log_entry)
        self._save_email_log()
    
    def send_payment_reminders(self, is_final_notice: bool = False, 
                             test_mode: bool = False,
                             limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Send payment reminders for all pending orders
        
        Args:
            is_final_notice: Whether to send final notices
            test_mode: If True, only log what would be sent
            limit: Maximum number of emails to send
            
        Returns:
            Summary of results
        """
        # Confirm before proceeding
        if not test_mode:
            notice_type = "FINAL NOTICE" if is_final_notice else "regular reminder"
            confirm = input(f"Ready to send {notice_type} emails. Continue? (y/n): ")
            if confirm.lower() != 'y':
                logger.info("Payment reminder sending cancelled")
                return {'cancelled': True}
        
        # Get orders to notify
        orders_to_notify = self.get_pending_orders_for_notification(is_final_notice)
        
        if limit:
            orders_to_notify = orders_to_notify.head(limit)
        
        logger.info(f"Found {len(orders_to_notify)} orders to notify")
        
        results = {
            'total': len(orders_to_notify),
            'sent': 0,
            'failed': 0,
            'errors': [],
            'skipped_holds': 0
        }
        
        # Process each order
        for idx, (_, order_row) in enumerate(orders_to_notify.iterrows()):
            try:
                order_no = str(order_row['Order No'])
                
                # Double-check hold status (in case it changed)
                is_on_hold, hold_reason = self.is_order_on_hold(order_no)
                if is_on_hold:
                    logger.info(f"Skipping order {order_no} - Payment hold: {hold_reason}")
                    results['skipped_holds'] += 1
                    continue
                
                email = order_row['User Email']
                subject, body = self.generate_reminder_email(order_row, is_final_notice)
                
                if test_mode:
                    logger.info(f"TEST MODE - Would send to: {email}")
                    logger.debug(f"Subject: {subject}")
                else:
                    # email = 'sdavis@davisportal.com'
                    if self.send_email(email, subject, body):
                        self.log_email_sent(order_row, is_final_notice)
                        results['sent'] += 1
                    else:
                        results['failed'] += 1
                        results['errors'].append(f"Failed to send to {email}")
                
                # Progress update
                if (idx + 1) % 10 == 0:
                    logger.info(f"Progress: {idx + 1}/{len(orders_to_notify)}")
                    
            except Exception as e:
                logger.error(f"Error processing order {order_row.get('Order No', 'Unknown')}: {e}")
                results['failed'] += 1
                results['errors'].append(str(e))
        
        # Summary
        logger.info(f"Payment reminders complete: {results['sent']} sent, {results['failed']} failed, {results['skipped_holds']} on hold")
        
        return results
    
    def get_reminder_statistics(self) -> Dict[str, Any]:
        """Get statistics about payment reminders sent"""
        stats = {
            'total_reminders_sent': len(self.email_log),
            'regular_reminders': sum(1 for log in self.email_log if not log.get('final_notice', False)),
            'final_notices': sum(1 for log in self.email_log if log.get('final_notice', False)),
            'unique_orders': len(set(log.get('order_no', '') for log in self.email_log)),
            'reminders_by_division': {},
            'recent_reminders': [],
            'active_holds': len(self.get_all_active_holds()),
            'total_holds': len(self.payment_holds)
        }
        
        # Count by division
        for log in self.email_log:
            division = log.get('division_name', 'Unknown')
            stats['reminders_by_division'][division] = stats['reminders_by_division'].get(division, 0) + 1
        
        # Get recent reminders (last 7 days)
        cutoff_date = datetime.now() - timedelta(days=7)
        for log in self.email_log:
            try:
                sent_date = datetime.fromisoformat(log['email_sent_on'])
                if sent_date > cutoff_date:
                    stats['recent_reminders'].append({
                        'date': sent_date.strftime('%Y-%m-%d %H:%M'),
                        'player': f"{log.get('player_first_name', '')} {log.get('player_last_name', '')}",
                        'division': log.get('division_name', ''),
                        'final_notice': log.get('final_notice', False)
                    })
            except:
                continue
        
        return stats
    
    def export_reminder_report(self, output_path: str = None) -> str:
        """
        Export payment reminder report
        
        Args:
            output_path: Path for output file
            
        Returns:
            Path to exported file
        """
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"payment_reminder_report_{timestamp}.xlsx"
        
        # Convert log to DataFrame
        df = pd.DataFrame(self.email_log)
        
        # Add derived columns
        if not df.empty:
            df['email_sent_date'] = pd.to_datetime(df['email_sent_on']).dt.date
            df['days_since_sent'] = (datetime.now() - pd.to_datetime(df['email_sent_on'])).dt.days
        
        # Create Excel writer
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Full log
            df.to_excel(writer, sheet_name='Email Log', index=False)
            
            # Summary by order
            if not df.empty:
                order_summary = df.groupby('order_no').agg({
                    'id': 'count',
                    'player_first_name': 'first',
                    'player_last_name': 'first',
                    'division_name': 'first',
                    'order_item_balance': 'first',
                    'final_notice': 'any'
                }).rename(columns={'id': 'reminder_count'})
                
                order_summary.to_excel(writer, sheet_name='Order Summary')
            
            # Statistics
            stats_df = pd.DataFrame([self.get_reminder_statistics()])
            stats_df.to_excel(writer, sheet_name='Statistics', index=False)
        
        logger.info(f"Payment reminder report exported to: {output_path}")
        return output_path
    
    def check_order_payment_status(self, order_no: str) -> Optional[str]:
        """
        Check if an order has been paid
        
        Args:
            order_no: Order number to check
            
        Returns:
            Payment status or None if not found
        """
        if self.open_orders_df is None:
            return None
        
        order_mask = self.open_orders_df['Order No'].astype(str) == str(order_no)
        if order_mask.any():
            return self.open_orders_df[order_mask].iloc[0]['Order Payment Status']
        
        return None
    
    def get_orders_ready_for_cancellation(self, days_after_final_notice: int = 2) -> pd.DataFrame:
        """
        Get orders that are ready for cancellation after final notice period
        
        Args:
            days_after_final_notice: Days to wait after final notice
            
        Returns:
            DataFrame with orders ready for cancellation
        """
        cancellation_ready = []
        cutoff_date = datetime.now() - timedelta(days=days_after_final_notice)
        
        # Find orders with final notices sent before cutoff
        for log in self.email_log:
            if log.get('final_notice', False):
                try:
                    sent_date = datetime.fromisoformat(log['email_sent_on'])
                    if sent_date < cutoff_date:
                        order_no = log.get('order_no')
                        if order_no:
                            # Check if order is on hold
                            is_on_hold, _ = self.is_order_on_hold(order_no)
                            if not is_on_hold and self.check_order_payment_status(order_no) == 'Pending':
                                cancellation_ready.append(log)
                except:
                    continue
        
        if cancellation_ready:
            return pd.DataFrame(cancellation_ready)
        return pd.DataFrame()
    
    def interactive_reminder_session(self):
        """Interactive session for sending payment reminders"""
        print("\nPayment Reminder Manager")
        print("=" * 50)
        
        # Load latest data
        if not self.load_open_orders():
            print("Error: Could not load Open Orders data")
            return
        
        # Show statistics
        stats = self.get_reminder_statistics()
        print(f"\nReminder Statistics:")
        print(f"  Total reminders sent: {stats['total_reminders_sent']}")
        print(f"  Regular reminders: {stats['regular_reminders']}")
        print(f"  Final notices: {stats['final_notices']}")
        print(f"  Unique orders: {stats['unique_orders']}")
        print(f"  Active payment holds: {stats['active_holds']}")
        
        # Get pending counts
        regular_pending = len(self.get_pending_orders_for_notification(False))
        final_pending = len(self.get_pending_orders_for_notification(True))
        
        print(f"\nPending Notifications:")
        print(f"  Regular reminders available: {regular_pending}")
        print(f"  Final notices available: {final_pending}")
        
        # Menu
        while True:
            print("\nOptions:")
            print("1. Send regular reminders")
            print("2. Send final notices")
            print("3. View orders ready for cancellation")
            print("4. Export reminder report")
            print("5. Test mode (preview emails)")
            print("6. Manage payment holds")
            print("7. View active holds")
            print("0. Exit")
            
            choice = input("\nEnter choice (0-7): ").strip()
            
            if choice == '0':
                break
            elif choice == '1':
                results = self.send_payment_reminders(is_final_notice=False)
                print(f"\nSent {results.get('sent', 0)} regular reminders")
                if results.get('skipped_holds', 0) > 0:
                    print(f"Skipped {results['skipped_holds']} orders on hold")
            elif choice == '2':
                results = self.send_payment_reminders(is_final_notice=True)
                print(f"\nSent {results.get('sent', 0)} final notices")
                if results.get('skipped_holds', 0) > 0:
                    print(f"Skipped {results['skipped_holds']} orders on hold")
            elif choice == '3':
                ready_for_cancel = self.get_orders_ready_for_cancellation()
                if not ready_for_cancel.empty:
                    print(f"\n{len(ready_for_cancel)} orders ready for cancellation:")
                    for _, order in ready_for_cancel.iterrows():
                        print(f"  - {order['player_first_name']} {order['player_last_name']} " \
                              f"({order['division_name']}) - Order: {order['order_no']}")
                else:
                    print("\nNo orders ready for cancellation")
            elif choice == '4':
                report_path = self.export_reminder_report()
                print(f"\nReport exported to: {report_path}")
            elif choice == '5':
                print("\nTest mode - no emails will be sent")
                limit = input("Number of orders to preview (Enter for all): ").strip()
                limit = int(limit) if limit else None
                results = self.send_payment_reminders(test_mode=True, limit=limit)
            elif choice == '6':
                self._interactive_manage_holds()
            elif choice == '7':
                self._display_active_holds()
    
    def _interactive_manage_holds(self):
        """Interactive session for managing payment holds"""
        print("\nManage Payment Holds")
        print("-" * 40)
        
        while True:
            print("\nHold Management Options:")
            print("1. Add new hold")
            print("2. Remove existing hold")
            print("3. Search for order")
            print("4. View all holds")
            print("0. Back to main menu")
            
            choice = input("\nEnter choice (0-4): ").strip()
            
            if choice == '0':
                break
            elif choice == '1':
                self._add_hold_interactive()
            elif choice == '2':
                self._remove_hold_interactive()
            elif choice == '3':
                self._search_order_interactive()
            elif choice == '4':
                self._display_active_holds()
    
    def _add_hold_interactive(self):
        """Interactive add payment hold"""
        order_no = input("\nEnter order number: ").strip()
        if not order_no:
            return
        
        # Check if order exists in open orders
        if self.open_orders_df is not None:
            order_mask = self.open_orders_df['Order No'].astype(str) == order_no
            if order_mask.any():
                order_info = self.open_orders_df[order_mask].iloc[0]
                print(f"\nFound order:")
                print(f"  Player: {order_info['Player First Name']} {order_info['Player Last Name']}")
                print(f"  Division: {order_info['Division Name']}")
                print(f"  Balance: ${order_info['Order Item Balance']:.2f}")
                
                # Common hold reasons
                print("\nCommon hold reasons:")
                print("1. Waiting for sibling registration")
                print("2. Waiting for waitlist activation")
                print("3. Financial hardship - payment plan")
                print("4. Registration issue being resolved")
                print("5. Other (custom reason)")
                
                reason_choice = input("\nSelect reason (1-5): ").strip()
                
                reasons = {
                    '1': "Waiting for sibling registration to be confirmed",
                    '2': "Waiting for another player to be activated from waitlist",
                    '3': "Financial hardship - payment plan arranged",
                    '4': "Registration issue being resolved with registrar"
                }
                
                if reason_choice in reasons:
                    reason = reasons[reason_choice]
                else:
                    reason = input("Enter custom reason: ").strip()
                
                if not reason:
                    print("Hold reason is required")
                    return
                
                # Ask for hold duration
                duration = input("\nHold duration in days (Enter for indefinite): ").strip()
                hold_until_date = None
                if duration and duration.isdigit():
                    hold_until_date = (datetime.now() + timedelta(days=int(duration))).isoformat()
                
                # Add the hold
                if self.add_payment_hold(order_no, reason, hold_until_date, order_info.to_dict()):
                    print(f"\n✓ Payment hold added for order {order_no}")
                else:
                    print(f"\n✗ Failed to add payment hold")
            else:
                print(f"\nOrder {order_no} not found in open orders")
                confirm = input("Add hold anyway? (y/n): ").strip()
                if confirm.lower() == 'y':
                    reason = input("Enter hold reason: ").strip()
                    if reason and self.add_payment_hold(order_no, reason):
                        print(f"\n✓ Payment hold added for order {order_no}")
    
    def _remove_hold_interactive(self):
        """Interactive remove payment hold"""
        # Show active holds
        active_holds = self.get_all_active_holds()
        if not active_holds:
            print("\nNo active payment holds")
            return
        
        print("\nActive Payment Holds:")
        for i, hold in enumerate(active_holds, 1):
            print(f"\n{i}. Order: {hold['order_no']}")
            if 'player_first_name' in hold:
                print(f"   Player: {hold.get('player_first_name', '')} {hold.get('player_last_name', '')}")
            print(f"   Reason: {hold['reason']}")
            print(f"   Added: {hold['hold_date'][:10]}")
        
        choice = input("\nEnter number to remove (0 to cancel): ").strip()
        if choice.isdigit() and 0 < int(choice) <= len(active_holds):
            hold = active_holds[int(choice) - 1]
            reason = input("Reason for removing hold: ").strip()
            
            if self.remove_payment_hold(hold['order_no'], reason):
                print(f"\n✓ Payment hold removed for order {hold['order_no']}")
            else:
                print(f"\n✗ Failed to remove payment hold")
    
    def _search_order_interactive(self):
        """Search for a specific order"""
        order_no = input("\nEnter order number to search: ").strip()
        if not order_no:
            return
        
        # Check hold status
        is_on_hold, hold_reason = self.is_order_on_hold(order_no)
        
        print(f"\nOrder {order_no}:")
        if is_on_hold:
            print(f"  Status: ON HOLD")
            print(f"  Reason: {hold_reason}")
            
            # Show hold details
            hold = self.payment_holds.get(order_no)
            if hold:
                print(f"  Added: {hold['hold_date'][:10]}")
                if hold.get('hold_until_date'):
                    print(f"  Expires: {hold['hold_until_date'][:10]}")
        else:
            print(f"  Status: NOT ON HOLD")
        
        # Check order details
        if self.open_orders_df is not None:
            order_mask = self.open_orders_df['Order No'].astype(str) == order_no
            if order_mask.any():
                order_info = self.open_orders_df[order_mask].iloc[0]
                print(f"\n  Player: {order_info['Player First Name']} {order_info['Player Last Name']}")
                print(f"  Division: {order_info['Division Name']}")
                print(f"  Balance: ${order_info['Order Item Balance']:.2f}")
                
                # Check reminder history
                reminders_sent = sum(1 for log in self.email_log if log.get('order_no') == order_no)
                final_notice_sent = any(log.get('final_notice') for log in self.email_log if log.get('order_no') == order_no)
                
                print(f"\n  Reminders sent: {reminders_sent}")
                print(f"  Final notice sent: {'Yes' if final_notice_sent else 'No'}")
    
    def _display_active_holds(self):
        """Display all active payment holds"""
        active_holds = self.get_all_active_holds()
        
        if not active_holds:
            print("\nNo active payment holds")
            return
        
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
