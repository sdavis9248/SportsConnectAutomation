"""
Enhanced Waitlist persistence system for tracking participant responses
Maintains a record of who has been notified, their responses, and non-response counts
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
        self.non_responders_file = self.data_dir / "non_responders.json"
        
        # Load existing data
        self.responses = self._load_responses()
        self.notification_history = self._load_notification_history()
        self.non_responders = self._load_non_responders()
    
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
    
    def _load_non_responders(self) -> Dict[str, Dict]:
        """Load non-responder tracking data"""
        if self.non_responders_file.exists():
            try:
                with open(self.non_responders_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading non-responders: {e}")
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
    
    def _save_non_responders(self):
        """Save non-responder data to file"""
        try:
            with open(self.non_responders_file, 'w') as f:
                json.dump(self.non_responders, f, indent=2)
            logger.debug(f"Saved non-responders to {self.non_responders_file}")
        except Exception as e:
            logger.error(f"Error saving non-responders: {e}")
    
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
        
        notification_entry = {
            'timestamp': timestamp,
            'email': email,
            'player_name': player_name,
            'division': division,
            'status': 'sent'
        }
        
        self.notification_history[order_number].append(notification_entry)
        
        # Track as potential non-responder
        if order_number not in self.non_responders:
            self.non_responders[order_number] = {
                'notification_count': 0,
                'last_notification': timestamp,
                'first_notification': timestamp,
                'player_name': player_name,
                'division': division,
                'email': email
            }
        
        self.non_responders[order_number]['notification_count'] += 1
        self.non_responders[order_number]['last_notification'] = timestamp
        
        self._save_notification_history()
        self._save_non_responders()
        logger.info(f"Recorded notification sent for order {order_number} (notification #{self.non_responders[order_number]['notification_count']})")
    
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
        
        # Update notification history
        if order_number in self.notification_history:
            self.notification_history[order_number][-1]['response'] = response.lower()
            self.notification_history[order_number][-1]['response_timestamp'] = timestamp
        
        # Remove from non-responders since they responded
        if order_number in self.non_responders:
            del self.non_responders[order_number]
            logger.info(f"Removed order {order_number} from non-responders list")
        
        self._save_responses()
        self._save_notification_history()
        self._save_non_responders()
        logger.info(f"Recorded response '{response}' for order {order_number}")
    
    def should_notify(self, order_number: str, days_between_notifications: int = 7,
                     exclude_confirmed_days: int = 30) -> Tuple[bool, str]:
        """
        Check if we should send a notification to this participant
        
        Args:
            order_number: Order number to check
            days_between_notifications: Minimum days between notifications
            exclude_confirmed_days: Days to exclude confirmed participants
            
        Returns:
            Tuple of (should_notify: bool, reason: str)
        """
        # Check if they've already responded "yes" within exclusion period
        if order_number in self.responses:
            response_data = self.responses[order_number]
            if response_data['response'] == 'yes':
                last_response_date = datetime.fromisoformat(response_data['timestamp'])
                days_since_response = (datetime.now() - last_response_date).days
                
                if days_since_response < exclude_confirmed_days:
                    return False, f"Confirmed {days_since_response} days ago (excluded for {exclude_confirmed_days} days)"
                else:
                    # They confirmed but it's been long enough to check again
                    logger.info(f"Order {order_number} confirmed {days_since_response} days ago, eligible for re-notification")
        
        # Check if they responded "no" - don't notify them again
        if order_number in self.responses:
            response_data = self.responses[order_number]
            if response_data['response'] == 'no':
                return False, "Declined to stay on waitlist"
        
        # For non-responders, always check notification frequency
        if order_number in self.notification_history:
            notifications = self.notification_history[order_number]
            if notifications:
                last_notification = notifications[-1]
                last_notified_date = datetime.fromisoformat(last_notification['timestamp'])
                days_since_notification = (datetime.now() - last_notified_date).days
                
                # Check if they haven't responded to the last notification
                has_responded = 'response' in last_notification
                
                if not has_responded:
                    # Non-responder - check if enough time has passed
                    if days_since_notification < days_between_notifications:
                        non_response_count = self.get_non_response_count(order_number)
                        return False, f"Non-responder notified {days_since_notification} days ago (attempt #{non_response_count})"
                    else:
                        non_response_count = self.get_non_response_count(order_number)
                        return True, f"Non-responder ready for notification #{non_response_count + 1}"
                else:
                    # They responded previously but may need re-notification
                    if days_since_notification < days_between_notifications:
                        return False, f"Notified {days_since_notification} days ago"
        
        return True, "OK to notify - first notification"
    
    def get_non_response_count(self, order_number: str) -> int:
        """
        Get the number of notifications sent without response
        
        Args:
            order_number: Order number to check
            
        Returns:
            Number of notifications without response
        """
        if order_number in self.non_responders:
            return self.non_responders[order_number]['notification_count']
        return 0
    
    def get_non_responders_report(self, min_notifications: int = 2) -> List[Dict]:
        """
        Get report of persistent non-responders
        
        Args:
            min_notifications: Minimum notifications to be considered persistent
            
        Returns:
            List of non-responder information
        """
        persistent_non_responders = []
        
        for order_number, data in self.non_responders.items():
            if data['notification_count'] >= min_notifications:
                last_notified = datetime.fromisoformat(data['last_notification'])
                first_notified = datetime.fromisoformat(data['first_notification'])
                
                persistent_non_responders.append({
                    'order_number': order_number,
                    'player_name': data['player_name'],
                    'division': data['division'],
                    'email': data['email'],
                    'notification_count': data['notification_count'],
                    'days_since_first': (datetime.now() - first_notified).days,
                    'days_since_last': (datetime.now() - last_notified).days,
                    'first_notification': data['first_notification'],
                    'last_notification': data['last_notification']
                })
        
        # Sort by notification count (highest first)
        persistent_non_responders.sort(key=lambda x: x['notification_count'], reverse=True)
        
        return persistent_non_responders
    
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
                    notification_count = self.get_non_response_count(order_number)
                    
                    pending.append({
                        'order_number': order_number,
                        'player_name': last_notification.get('player_name', 'Unknown'),
                        'division': last_notification.get('division', 'Unknown'),
                        'email': last_notification.get('email', 'Unknown'),
                        'notified_date': last_notification['timestamp'],
                        'days_waiting': (datetime.now() - notification_date).days,
                        'notification_count': notification_count
                    })
        
        # Sort by days waiting (longest first)
        pending.sort(key=lambda x: x['days_waiting'], reverse=True)
        
        return pending
    
    def mark_notification_check(self, order_number: str, email: str, 
                               player_name: str, division: str) -> None:
        """
        Mark that we checked if we should notify this participant
        Used to track non-responders even when we don't send a new notification
        
        Args:
            order_number: Order number
            email: Email address
            player_name: Player name
            division: Division
        """
        timestamp = datetime.now().isoformat()
        
        # Update non-responder tracking
        if order_number in self.non_responders:
            self.non_responders[order_number]['last_check'] = timestamp
            self._save_non_responders()
    
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
        non_responders = self.get_non_responders_report()
        
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
        report.append(f"  Pending Response: {len(pending)}")
        report.append(f"  Non-Responders (2+ attempts): {len([nr for nr in non_responders if nr['notification_count'] >= 2])}\n")
        
        if confirmed:
            report.append("Recent Confirmations:")
            for p in confirmed[:10]:  # Show last 10
                report.append(f"  - {p['player_name']} ({p['division']}) - {p['days_ago']} days ago")
        
        if non_responders:
            report.append("\nPersistent Non-Responders (2+ notifications):")
            for nr in non_responders[:10]:  # Show top 10
                report.append(f"  - {nr['player_name']} ({nr['division']}) - "
                            f"{nr['notification_count']} attempts, last {nr['days_since_last']} days ago")
        
        if pending:
            report.append("\nAwaiting Response (>3 days):")
            for p in pending:
                if p['days_waiting'] > 3:
                    report.append(f"  - {p['player_name']} ({p['division']}) - "
                                f"{p['days_waiting']} days, attempt #{p['notification_count']}")
        
        return "\n".join(report)
    
    def export_to_csv(self, output_path: str = None) -> str:
        """Export tracking data to CSV for analysis"""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.data_dir / f"waitlist_tracking_{timestamp}.csv"
        
        # Combine all data
        rows = []
        
        for order_number, notifications in self.notification_history.items():
            for i, notification in enumerate(notifications):
                row = {
                    'order_number': order_number,
                    'player_name': notification.get('player_name', ''),
                    'division': notification.get('division', ''),
                    'email': notification.get('email', ''),
                    'notification_date': notification['timestamp'],
                    'notification_attempt': i + 1,
                    'response': '',
                    'response_date': '',
                    'days_to_respond': '',
                    'is_non_responder': 'No',
                    'total_notifications': len(notifications)
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
                
                # Mark non-responders
                if order_number in self.non_responders:
                    row['is_non_responder'] = 'Yes'
                
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
        filtered_rows = []
        
        for idx, row in participants_df.iterrows():
            order_id = str(row.get('order_id', ''))
            
            if not order_id:
                logger.warning(f"No order ID for row {idx}")
                continue
            
            should_notify, reason = self.tracker.should_notify(
                order_id, 
                self.days_between_notifications,
                self.exclude_confirmed_days
            )
            
            # Always mark that we checked this participant
            self.tracker.mark_notification_check(
                order_id,
                row.get('email', ''),
                f"{row.get('player_first', '')} {row.get('player_last', '')}".strip(),
                row.get('division', '')
            )
            
            if should_notify:
                filtered_rows.append(row)
                logger.info(f"Will notify {order_id}: {reason}")
            else:
                logger.debug(f"Skipping {order_id}: {reason}")
        
        # Create filtered DataFrame
        filtered_df = pd.DataFrame(filtered_rows)
        
        logger.info(f"Filtered {len(participants_df)} participants to {len(filtered_df)} to notify")
        
        # Log non-responder summary
        non_responders = self.tracker.get_non_responders_report()
        if non_responders:
            logger.info(f"Current non-responders with 2+ attempts: {len([nr for nr in non_responders if nr['notification_count'] >= 2])}")
        
        return filtered_df