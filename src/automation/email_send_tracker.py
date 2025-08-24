"""
Email Send History Tracker for Sports Connect Automation
Tracks all email sends related to medical forms and other communications
"""
import json
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import shutil

logger = logging.getLogger(__name__)


class EmailSendTracker:
    """Tracks email send history with relationship to coach cache"""
    
    def __init__(self, data_dir: str = "data/email_tracking"):
        """
        Initialize Email Send Tracker
        
        Args:
            data_dir: Directory to store tracking files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.send_history_file = self.data_dir / "email_send_history.json"
        self.send_summary_file = self.data_dir / "email_send_summary.json"
        self.backup_dir = self.data_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        
        # Load existing data
        self.send_history = self._load_send_history()
        self.send_summary = self._load_send_summary()
    
    def _load_send_history(self) -> List[Dict]:
        """Load email send history"""
        if self.send_history_file.exists():
            try:
                with open(self.send_history_file, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Loaded email send history with {len(data)} records")
                    return data
            except Exception as e:
                logger.error(f"Error loading send history: {e}")
                return []
        return []
    
    def _load_send_summary(self) -> Dict[str, Dict]:
        """Load email send summary (indexed by coach cache key)"""
        if self.send_summary_file.exists():
            try:
                with open(self.send_summary_file, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Loaded email send summary for {len(data)} coaches")
                    return data
            except Exception as e:
                logger.error(f"Error loading send summary: {e}")
                return {}
        return {}
    
    def _save_data(self) -> bool:
        """Save both history and summary files"""
        try:
            # Create backup before saving
            if self.send_history_file.exists() or self.send_summary_file.exists():
                self._create_backup()
            
            # Save send history
            with open(self.send_history_file, 'w') as f:
                json.dump(self.send_history, f, indent=2)
            
            # Save send summary
            with open(self.send_summary_file, 'w') as f:
                json.dump(self.send_summary, f, indent=2, sort_keys=True)
            
            logger.info(f"Saved email tracking data: {len(self.send_history)} history records, {len(self.send_summary)} coach summaries")
            return True
            
        except Exception as e:
            logger.error(f"Error saving email tracking data: {e}")
            return False
    
    def _create_backup(self):
        """Create backup of current tracking files"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Backup history file
            if self.send_history_file.exists():
                history_backup = self.backup_dir / f"email_send_history_{timestamp}.json"
                shutil.copy2(self.send_history_file, history_backup)
            
            # Backup summary file
            if self.send_summary_file.exists():
                summary_backup = self.backup_dir / f"email_send_summary_{timestamp}.json"
                shutil.copy2(self.send_summary_file, summary_backup)
            
            # Clean old backups (keep last 10)
            self._clean_old_backups()
            
        except Exception as e:
            logger.warning(f"Failed to create backup: {e}")
    
    def _clean_old_backups(self):
        """Keep only the last 10 backups"""
        backup_files = sorted(self.backup_dir.glob("*.json"))
        if len(backup_files) > 20:  # 10 history + 10 summary files
            for old_file in backup_files[:-20]:
                old_file.unlink()
    
    def record_email_sent(self, coach_cache_key: str, coach_info: Dict, 
                         email_type: str,
                         cc_email: str = None,
                         attachment_info: Dict = None,
                         success: bool = True, error_message: str = None) -> Dict:
        """
        Record an email send event
        
        Args:
            coach_cache_key: The cache key from coach cache manager
            coach_info: Coach information (division, team, name, email)
            email_type: Type of email (e.g., 'medical_forms', 'reminder', etc.)
            cc_email: if dc copied the email address used
            attachment_info: Information about attachments (optional)
            success: Whether the email was sent successfully
            error_message: Error message if send failed
            
        Returns:
            The send record created
        """
        # Create send record
        send_record = {
            'send_id': f"{datetime.now().timestamp()}_{coach_cache_key}",
            'timestamp': datetime.now().isoformat(),
            'coach_cache_key': coach_cache_key,
            'division': coach_info.get('division', ''),
            'team': coach_info.get('team', ''),
            'coach_name': coach_info.get('coach_name', ''),
            'coach_email': coach_info.get('coach_email', ''),
            'email_type': email_type,
            'cc_email': cc_email,
            'success': success,
            'error_message': error_message,
            'attachment_info': attachment_info or {}
        }
        
        # Add to history
        self.send_history.append(send_record)
        
        # Update summary
        if coach_cache_key not in self.send_summary:
            self.send_summary[coach_cache_key] = {
                'coach_info': {
                    'division': coach_info.get('division', ''),
                    'team': coach_info.get('team', ''),
                    'coach_name': coach_info.get('coach_name', ''),
                    'coach_email': coach_info.get('coach_email', ''),
                    'cc_email': cc_email
                },
                'first_contact': datetime.now().isoformat(),
                'last_contact': datetime.now().isoformat(),
                'total_emails_sent': 0,
                'successful_sends': 0,
                'failed_sends': 0,
                'email_types': {}
            }
        
        # Update summary statistics
        summary = self.send_summary[coach_cache_key]
        summary['last_contact'] = datetime.now().isoformat()
        summary['total_emails_sent'] += 1
        
        if success:
            summary['successful_sends'] += 1
        else:
            summary['failed_sends'] += 1
        
        # Track by email type
        if email_type not in summary['email_types']:
            summary['email_types'][email_type] = {
                'count': 0,
                'last_sent': None,
                'successful': 0,
                'failed': 0
            }
        
        type_summary = summary['email_types'][email_type]
        type_summary['count'] += 1
        type_summary['last_sent'] = datetime.now().isoformat()
        if success:
            type_summary['successful'] += 1
        else:
            type_summary['failed'] += 1
        
        # Save data
        self._save_data()
        
        return send_record
    
    def get_coach_send_history(self, coach_cache_key: str) -> List[Dict]:
        """Get all email send records for a specific coach"""
        return [
            record for record in self.send_history 
            if record['coach_cache_key'] == coach_cache_key
        ]
    
    def get_coach_summary(self, coach_cache_key: str) -> Optional[Dict]:
        """Get email send summary for a specific coach"""
        return self.send_summary.get(coach_cache_key)
    
    def get_recent_sends(self, days: int = 7, email_type: str = None) -> List[Dict]:
        """Get recent email sends within specified days"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        recent_sends = []
        for record in self.send_history:
            record_date = datetime.fromisoformat(record['timestamp'])
            if record_date >= cutoff_date:
                if email_type is None or record['email_type'] == email_type:
                    recent_sends.append(record)
        
        return sorted(recent_sends, key=lambda x: x['timestamp'], reverse=True)
    
    def should_send_email(self, coach_cache_key: str, email_type: str, 
                         min_days_between: int = 7) -> Tuple[bool, str]:
        """
        Check if we should send an email to this coach
        
        Args:
            coach_cache_key: Coach cache key
            email_type: Type of email to send
            min_days_between: Minimum days between emails of this type
            
        Returns:
            Tuple of (should_send: bool, reason: str)
        """
        summary = self.get_coach_summary(coach_cache_key)
        
        if not summary:
            return True, "No previous emails sent"
        
        type_data = summary.get('email_types', {}).get(email_type)
        if not type_data:
            return True, f"No previous {email_type} emails sent"
        
        # Check last sent date
        last_sent = datetime.fromisoformat(type_data['last_sent'])
        days_since = (datetime.now() - last_sent).days
        
        if days_since < min_days_between:
            return False, f"Last {email_type} sent {days_since} days ago (minimum: {min_days_between})"
        
        return True, f"OK to send - last {email_type} was {days_since} days ago"
    
    def get_failed_sends(self, email_type: str = None) -> List[Dict]:
        """Get all failed email sends"""
        failed = []
        for record in self.send_history:
            if not record['success']:
                if email_type is None or record['email_type'] == email_type:
                    failed.append(record)
        
        return sorted(failed, key=lambda x: x['timestamp'], reverse=True)
    
    def get_statistics(self, email_type: str = None) -> Dict[str, Any]:
        """Get email send statistics"""
        stats = {
            'total_sends': 0,
            'successful_sends': 0,
            'failed_sends': 0,
            'unique_coaches': 0,
            'by_division': {},
            'by_email_type': {},
            'recent_activity': {
                'last_24h': 0,
                'last_7d': 0,
                'last_30d': 0
            }
        }
        
        # Calculate time windows
        now = datetime.now()
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)
        
        # Process history
        for record in self.send_history:
            if email_type and record['email_type'] != email_type:
                continue
            
            stats['total_sends'] += 1
            
            if record['success']:
                stats['successful_sends'] += 1
            else:
                stats['failed_sends'] += 1
            
            # By division
            division = record['division']
            if division not in stats['by_division']:
                stats['by_division'][division] = {'sent': 0, 'success': 0, 'failed': 0}
            stats['by_division'][division]['sent'] += 1
            if record['success']:
                stats['by_division'][division]['success'] += 1
            else:
                stats['by_division'][division]['failed'] += 1
            
            # By email type
            etype = record['email_type']
            if etype not in stats['by_email_type']:
                stats['by_email_type'][etype] = {'sent': 0, 'success': 0, 'failed': 0}
            stats['by_email_type'][etype]['sent'] += 1
            if record['success']:
                stats['by_email_type'][etype]['success'] += 1
            else:
                stats['by_email_type'][etype]['failed'] += 1
            
            # Recent activity
            record_time = datetime.fromisoformat(record['timestamp'])
            if record_time >= last_24h:
                stats['recent_activity']['last_24h'] += 1
            if record_time >= last_7d:
                stats['recent_activity']['last_7d'] += 1
            if record_time >= last_30d:
                stats['recent_activity']['last_30d'] += 1
        
        # Unique coaches
        stats['unique_coaches'] = len(self.send_summary)
        
        # Success rate
        if stats['total_sends'] > 0:
            stats['success_rate'] = round(stats['successful_sends'] / stats['total_sends'] * 100, 1)
        else:
            stats['success_rate'] = 0
        
        return stats
    
    def export_to_csv(self, output_path: str = None, include_history: bool = True) -> str:
        """Export tracking data to CSV"""
        import csv
        
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.data_dir / f"email_tracking_export_{timestamp}.csv"
        
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                if include_history:
                    # Export detailed history
                    fieldnames = [
                        'timestamp', 'coach_cache_key', 'division', 'team', 
                        'coach_name', 'coach_email', 'email_type', 'success', 
                        'error_message', 'attachment_name'
                    ]
                    
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for record in sorted(self.send_history, key=lambda x: x['timestamp']):
                        row = {
                            'timestamp': record['timestamp'],
                            'coach_cache_key': record['coach_cache_key'],
                            'division': record['division'],
                            'team': record['team'],
                            'coach_name': record['coach_name'],
                            'coach_email': record['coach_email'],
                            'email_type': record['email_type'],
                            'success': 'Yes' if record['success'] else 'No',
                            'error_message': record.get('error_message', ''),
                            'attachment_name': record.get('attachment_info', {}).get('filename', '')
                        }
                        writer.writerow(row)
                else:
                    # Export summary only
                    fieldnames = [
                        'coach_cache_key', 'division', 'team', 'coach_name', 
                        'coach_email', 'first_contact', 'last_contact', 
                        'total_sent', 'successful', 'failed'
                    ]
                    
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for cache_key, summary in sorted(self.send_summary.items()):
                        row = {
                            'coach_cache_key': cache_key,
                            'division': summary['coach_info']['division'],
                            'team': summary['coach_info']['team'],
                            'coach_name': summary['coach_info']['coach_name'],
                            'coach_email': summary['coach_info']['coach_email'],
                            'first_contact': summary['first_contact'],
                            'last_contact': summary['last_contact'],
                            'total_sent': summary['total_emails_sent'],
                            'successful': summary['successful_sends'],
                            'failed': summary['failed_sends']
                        }
                        writer.writerow(row)
            
            logger.info(f"Exported email tracking data to: {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")
            return None
    
    def generate_report(self) -> str:
        """Generate a text report of email send activity"""
        stats = self.get_statistics()
        
        report = []
        report.append("Email Send Tracking Report")
        report.append("=" * 50)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        report.append("Overall Statistics:")
        report.append(f"  Total Emails Sent: {stats['total_sends']}")
        report.append(f"  Successful: {stats['successful_sends']}")
        report.append(f"  Failed: {stats['failed_sends']}")
        report.append(f"  Success Rate: {stats['success_rate']}%")
        report.append(f"  Unique Coaches: {stats['unique_coaches']}\n")
        
        report.append("Recent Activity:")
        report.append(f"  Last 24 hours: {stats['recent_activity']['last_24h']}")
        report.append(f"  Last 7 days: {stats['recent_activity']['last_7d']}")
        report.append(f"  Last 30 days: {stats['recent_activity']['last_30d']}\n")
        
        if stats['by_division']:
            report.append("By Division:")
            for div, data in sorted(stats['by_division'].items()):
                report.append(f"  {div}: {data['sent']} sent ({data['success']} successful, {data['failed']} failed)")
            report.append("")
        
        if stats['by_email_type']:
            report.append("By Email Type:")
            for etype, data in sorted(stats['by_email_type'].items()):
                report.append(f"  {etype}: {data['sent']} sent ({data['success']} successful, {data['failed']} failed)")
        
        # Recent failures
        recent_failures = self.get_failed_sends()[:5]
        if recent_failures:
            report.append("\nRecent Failed Sends:")
            for fail in recent_failures:
                report.append(f"  - {fail['timestamp']}: {fail['coach_email']} - {fail.get('error_message', 'Unknown error')}")
        
        return "\n".join(report)