"""
Waitlist persistence system for tracking participant responses
Maintains a record of who has been notified and their responses
"""
import json
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd

logger = logging.getLogger(__name__)


class WaitlistResponseTracker:
    """Tracks waitlist notification responses and history"""
    
    def __init__(self, data_dir: str = "data/waitlist_tracking"):
        """
        Initialize the response tracker
        
        Args:
            data_dir: Directory to store tracking data
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.responses_file = self.data_dir / "waitlist_responses.json"
        self.notifications_file = self.data_dir / "notification_history.json"
        
        # Load existing data
        self.responses = self._load_responses()
        self.notification_history = self._load_notification_history()
    
    def _load_responses(self) -> Dict[str, Dict]:
        """Load existing response data"""
        if self.responses_file.exists():
            try:
                with open(self.responses_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading responses: {e}")
                return {}
        return {}
    
    def _load_notification_history(self) -> Dict[str, List]:
        """Load notification history"""
        if self.notifications_file.exists():
            try:
                with open(self.notifications_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading notification history: {e}")
                return {}
        return {}
    
    def _save_responses(self):
        """Save responses to file"""
        try:
            with open(self.responses_file, 'w') as f:
                json.dump(self.responses, f, indent=2)
            logger.debug(f"Saved responses to {self.responses_file}")
        except Exception as e:
            logger.error(f"Error saving responses: {e}")
    
    def _save_notification_history(self):
        """Save notification history to file"""
        try:
            with open(self.notifications_file, 'w') as f:
                json.dump(self.notification_history, f, indent=2)
            logger.debug(f"Saved notification history to {self.notifications_file}")
        except Exception as e:
            logger.error(f"Error saving notification history: {e}")
    
    def record_notification_sent(self, order_number: str, email: str, 
                               player_name: str, division: str) -> None:
        """
        Record that a notification was sent
        
        Args:
            order_number: Order number
            email: Email address
            player_name: Player name
            division: Division
        """
        timestamp = datetime.now().isoformat()
        
        # Add to notification history
        if order_number not in self.notification_history:
            self.notification_history[order_number] = []
        
        self.notification_history[order_number].append({
            'timestamp': timestamp,
            'email': email,
            'player_name': player_name,
            'division': division,
            'status': 'sent'
        })
        
        self._save_notification_history()
        logger.info(f"Recorded notification sent for order {order_number}")
    
    def record_response(self, order_number: str, response: str, 
                       response_source: str = 'google_sheet') -> None:
        """
        Record a participant's response
        
        Args:
            order_number: Order number
            response: 'yes' or 'no'
            response_source: Where the response came from
        """
        timestamp = datetime.now().isoformat()
        
        self.responses[order_number] = {
            'response': response.lower(),
            'timestamp': timestamp,
            'source': response_source,
            'last_updated': timestamp
        }
        
        # Also update notification history
        if order_number in self.notification_history:
            self.notification_history[order_number][-1]['response'] = response.lower()
            self.notification_history[order_number][-1]['response_timestamp'] = timestamp
        
        self._save_responses()
        self._save_notification_history()
        logger.info(f"Recorded response '{response}' for order {order_number}")
    
    def should_notify(self, order_number: str, days_between_notifications: int = 7) -> Tuple[bool, str]:
        """
        Check if we should send a notification to this participant
        
        Args:
            order_number: Order number to check
            days_between_notifications: Minimum days between notifications
            
        Returns:
            Tuple of (should_notify: bool, reason: str)
        """
        # Check if they've already responded "yes"
        if order_number in self.responses:
            response_data = self.responses[order_number]
            if response_data['response'] == 'yes':
                last_response_date = datetime.fromisoformat(response_data['timestamp'])
                days_since_response = (datetime.now() - last_response_date).days
                
                if days_since_response < days_between_notifications:
                    return False, f"Already confirmed {days_since_response} days ago"
        
        # Check when last notified
        if order_number in self.notification_history:
            notifications = self.notification_history[order_number]
            if notifications:
                last_notification = notifications[-1]
                last_notified_date = datetime.fromisoformat(last_notification['timestamp'])
                days_since_notification = (datetime.now() - last_notified_date).days
                
                if days_since_notification < days_between_notifications:
                    return False, f"Notified {days_since_notification} days ago"
        
        return True, "OK to notify"
    
    def get_confirmed_participants(self, days_valid: Optional[int] = None) -> List[Dict]:
        """
        Get list of participants who have confirmed they want to stay on waitlist
        
        Args:
            days_valid: Only include confirmations within this many days (None for all)
            
        Returns:
            List of confirmed participants
        """
        confirmed = []
        cutoff_date = None
        
        if days_valid:
            cutoff_date = datetime.now() - timedelta(days=days_valid)
        
        for order_number, response_data in self.responses.items():
            if response_data['response'] == 'yes':
                response_date = datetime.fromisoformat(response_data['timestamp'])
                
                if cutoff_date is None or response_date >= cutoff_date:
                    # Get additional info from notification history
                    participant_info = {
                        'order_number': order_number,
                        'response_date': response_data['timestamp'],
                        'days_ago': (datetime.now() - response_date).days
                    }
                    
                    # Add player info if available
                    if order_number in self.notification_history:
                        last_notification = self.notification_history[order_number][-1]
                        participant_info.update({
                            'player_name': last_notification.get('player_name', 'Unknown'),
                            'division': last_notification.get('division', 'Unknown'),
                            'email': last_notification.get('email', 'Unknown')
                        })
                    
                    confirmed.append(participant_info)
        
        # Sort by response date (most recent first)
        confirmed.sort(key=lambda x: x['response_date'], reverse=True)
        
        return confirmed
    
    def get_pending_responses(self) -> List[Dict]:
        """Get list of participants who haven't responded yet"""
        pending = []
        
        for order_number, notifications in self.notification_history.items():
            if notifications:
                last_notification = notifications[-1]
                
                # Check if they've responded
                has_response = (order_number in self.responses or 
                              'response' in last_notification)
                
                if not has_response:
                    notification_date = datetime.fromisoformat(last_notification['timestamp'])
                    pending.append({
                        'order_number': order_number,
                        'player_name': last_notification.get('player_name', 'Unknown'),
                        'division': last_notification.get('division', 'Unknown'),
                        'email': last_notification.get('email', 'Unknown'),
                        'notified_date': last_notification['timestamp'],
                        'days_waiting': (datetime.now() - notification_date).days
                    })
        
        # Sort by days waiting (longest first)
        pending.sort(key=lambda x: x['days_waiting'], reverse=True)
        
        return pending
    
    def import_google_sheet_responses(self, sheet_responses: Dict[str, List[str]]) -> int:
        """
        Import responses from Google Sheets reader
        
        Args:
            sheet_responses: Dictionary with 'keep' and 'remove' lists
            
        Returns:
            Number of responses imported
        """
        imported = 0
        
        # Record "yes" responses
        for order_number in sheet_responses.get('keep', []):
            self.record_response(order_number, 'yes', 'google_sheet')
            imported += 1
        
        # Record "no" responses
        for order_number in sheet_responses.get('remove', []):
            self.record_response(order_number, 'no', 'google_sheet')
            imported += 1
        
        logger.info(f"Imported {imported} responses from Google Sheet")
        return imported
    
    def generate_summary_report(self) -> str:
        """Generate a summary report of waitlist responses"""
        confirmed = self.get_confirmed_participants()
        pending = self.get_pending_responses()
        
        # Count responses by type
        yes_count = sum(1 for r in self.responses.values() if r['response'] == 'yes')
        no_count = sum(1 for r in self.responses.values() if r['response'] == 'no')
        
        report = []
        report.append("Waitlist Response Summary")
        report.append("=" * 50)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        report.append("Response Statistics:")
        report.append(f"  Total Notifications Sent: {len(self.notification_history)}")
        report.append(f"  Confirmed (Yes): {yes_count}")
        report.append(f"  Declined (No): {no_count}")
        report.append(f"  Pending Response: {len(pending)}\n")
        
        if confirmed:
            report.append("Recent Confirmations:")
            for p in confirmed[:10]:  # Show last 10
                report.append(f"  - {p['player_name']} ({p['division']}) - {p['days_ago']} days ago")
        
        if pending:
            report.append("\nAwaiting Response (>3 days):")
            for p in pending:
                if p['days_waiting'] > 3:
                    report.append(f"  - {p['player_name']} ({p['division']}) - {p['days_waiting']} days")
        
        return "\n".join(report)
    
    def export_to_csv(self, output_path: str = None) -> str:
        """Export tracking data to CSV for analysis"""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.data_dir / f"waitlist_tracking_{timestamp}.csv"
        
        # Combine all data
        rows = []
        
        for order_number, notifications in self.notification_history.items():
            for notification in notifications:
                row = {
                    'order_number': order_number,
                    'player_name': notification.get('player_name', ''),
                    'division': notification.get('division', ''),
                    'email': notification.get('email', ''),
                    'notification_date': notification['timestamp'],
                    'response': '',
                    'response_date': '',
                    'days_to_respond': ''
                }
                
                # Add response data if available
                if order_number in self.responses:
                    response_data = self.responses[order_number]
                    row['response'] = response_data['response']
                    row['response_date'] = response_data['timestamp']
                    
                    # Calculate days to respond
                    notif_date = datetime.fromisoformat(notification['timestamp'])
                    resp_date = datetime.fromisoformat(response_data['timestamp'])
                    row['days_to_respond'] = (resp_date - notif_date).days
                
                rows.append(row)
        
        # Create DataFrame and save
        df = pd.DataFrame(rows)
        df.to_csv(output_path, index=False)
        
        logger.info(f"Exported tracking data to {output_path}")
        return str(output_path)


class WaitlistNotificationFilter:
    """Filter participants based on notification rules"""
    
    def __init__(self, tracker: WaitlistResponseTracker, config: Dict):
        """
        Initialize the filter
        
        Args:
            tracker: Response tracker instance
            config: Notification configuration
        """
        self.tracker = tracker
        self.days_between_notifications = config.get('days_between_notifications', 7)
        self.exclude_confirmed_days = config.get('exclude_confirmed_days', 30)
    
    def filter_participants(self, participants_df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter participants based on notification rules
        
        Args:
            participants_df: DataFrame with waitlist participants
            
        Returns:
            Filtered DataFrame of participants to notify
        """
        # Get list of who to exclude
        exclude_orders = set()
        
        # Get recently confirmed participants
        confirmed = self.tracker.get_confirmed_participants(self.exclude_confirmed_days)
        for participant in confirmed:
            exclude_orders.add(participant['order_number'])
            logger.info(f"Excluding {participant['order_number']} - confirmed {participant['days_ago']} days ago")
        
        # Check notification history for each participant
        filtered_rows = []
        
        for idx, row in participants_df.iterrows():
            order_id = str(row.get('order_id', ''))
            
            if not order_id:
                logger.warning(f"No order ID for row {idx}")
                continue
            
            should_notify, reason = self.tracker.should_notify(
                order_id, 
                self.days_between_notifications
            )
            
            if should_notify and order_id not in exclude_orders:
                filtered_rows.append(row)
                logger.debug(f"Will notify {order_id}: {reason}")
            else:
                logger.debug(f"Skipping {order_id}: {reason}")
        
        # Create filtered DataFrame
        filtered_df = pd.DataFrame(filtered_rows)
        
        logger.info(f"Filtered {len(participants_df)} participants to {len(filtered_df)} to notify")
        
        return filtered_df
