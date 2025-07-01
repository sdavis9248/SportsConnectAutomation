"""
Enhanced migration script for waitlist persistence data
Imports existing responses from Excel file and sets up proper tracking
"""
import json
import os
import logging
from datetime import datetime
from pathlib import Path
import shutil
from typing import Dict, List, Optional, Tuple
import pandas as pd
import re

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class WaitlistDataMigration:
    """Handles one-time migration of waitlist persistence data with Excel import"""
    
    def __init__(self, data_dir: str = "data/waitlist_tracking"):
        """
        Initialize migration handler
        
        Args:
            data_dir: Directory containing waitlist tracking data
        """
        self.data_dir = Path(data_dir)
        self.backup_dir = self.data_dir / "backup_before_migration"
        
        # File paths
        self.responses_file = self.data_dir / "waitlist_responses.json"
        self.notifications_file = self.data_dir / "notification_history.json"
        self.non_responders_file = self.data_dir / "non_responders.json"
        
        # Migration status file
        self.migration_status_file = self.data_dir / ".migration_v2_completed"
        
        # Excel file path
        self.excel_file = None
    
    def import_excel_responses(self, excel_path: str) -> Tuple[Dict, List[str], List[str]]:
        """
        Import responses from the Excel file
        
        Args:
            excel_path: Path to Excel file with responses
            
        Returns:
            Tuple of (responses_dict, keep_list, remove_list)
        """
        logger.info(f"Importing responses from: {excel_path}")
        
        try:
            # Read Excel file
            df = pd.read_excel(excel_path)
            logger.info(f"Read {len(df)} rows from Excel file")
            
            # Initialize collections
            responses = {}
            keep_list = []
            remove_list = []
            
            # Process each row
            for idx, row in df.iterrows():
                try:
                    # Get data from row
                    timestamp = row.get('Timestamp', pd.NaT)
                    response = row.get('Do you want to stay on the waitlist?', '')
                    player_info = row.get('Player Information', '')
                    
                    if not player_info or pd.isna(player_info):
                        continue
                    
                    # Extract order number
                    order_match = re.search(r'\(Order\s+(\d+)\)', str(player_info))
                    if not order_match:
                        logger.warning(f"No order number found in: {player_info}")
                        continue
                    
                    order_number = order_match.group(1)
                    
                    # Extract player name and division
                    # Format: "Player Name DIVISION - Description (Order 123)"
                    info_parts = str(player_info).split('(Order')[0].strip()
                    
                    # Try to extract division (e.g., 12UB, 10UG)
                    division_match = re.search(r'(\d{2}U[BG])', info_parts)
                    division = division_match.group(1) if division_match else 'Unknown'
                    
                    # Extract player name (everything before the division)
                    if division_match:
                        player_name = info_parts[:division_match.start()].strip()
                    else:
                        # Fallback: take everything before the first hyphen
                        player_name = info_parts.split('-')[0].strip()
                    
                    # Determine response
                    response_lower = str(response).lower().strip()
                    
                    # Create response record
                    response_record = {
                        'response': 'yes' if response_lower == 'yes' else 'no',
                        'timestamp': pd.to_datetime(timestamp).isoformat() if pd.notna(timestamp) else datetime.now().isoformat(),
                        'source': 'excel_import',
                        'last_updated': datetime.now().isoformat(),
                        'player_name': player_name,
                        'division': division,
                        'original_response': response
                    }
                    
                    responses[order_number] = response_record
                    
                    # Add to appropriate list
                    if response_lower == 'yes':
                        keep_list.append(order_number)
                    else:
                        remove_list.append(order_number)
                    
                    logger.debug(f"Processed: {order_number} - {player_name} ({division}) - {response}")
                    
                except Exception as e:
                    logger.error(f"Error processing row {idx}: {e}")
                    continue
            
            logger.info(f"Import complete: {len(responses)} responses ({len(keep_list)} yes, {len(remove_list)} no)")
            
            return responses, keep_list, remove_list
            
        except Exception as e:
            logger.error(f"Error importing Excel file: {e}")
            raise
    
    def migrate_with_excel_data(self, excel_path: str):
        """
        Perform migration including Excel data import
        
        Args:
            excel_path: Path to Excel file with responses
        """
        logger.info("Starting enhanced migration with Excel import...")
        
        # Import Excel responses first
        excel_responses, keep_list, remove_list = self.import_excel_responses(excel_path)
        
        # Load existing data
        existing_responses = self._load_json_file(self.responses_file)
        notification_history = self._load_json_file(self.notifications_file)
        
        # Merge responses (Excel takes precedence)
        merged_responses = existing_responses.copy()
        merged_responses.update(excel_responses)
        
        # Create notification history for imported responses
        for order_number, response_data in excel_responses.items():
            if order_number not in notification_history:
                notification_history[order_number] = []
            
            # Add a synthetic notification entry
            notification_history[order_number].append({
                'timestamp': response_data['timestamp'],
                'email': 'imported@excel.com',  # Placeholder since we don't have emails
                'player_name': response_data['player_name'],
                'division': response_data['division'],
                'status': 'sent',
                'response': response_data['response'],
                'response_timestamp': response_data['timestamp'],
                'note': 'Imported from Excel file'
            })
        
        # Create non_responders data
        non_responders = {}
        
        # Check all participants in the waitlist
        all_participants = set()
        
        # Get all order numbers from notification history
        for order_number in notification_history.keys():
            all_participants.add(order_number)
        
        # Identify non-responders (those not in Excel responses)
        for order_number in all_participants:
            if order_number not in excel_responses:
                # This person was notified but didn't respond via the form
                notifications = notification_history.get(order_number, [])
                if notifications:
                    first_notification = notifications[0]
                    last_notification = notifications[-1]
                    
                    non_responders[order_number] = {
                        'notification_count': len(notifications),
                        'first_notification': first_notification['timestamp'],
                        'last_notification': last_notification['timestamp'],
                        'player_name': last_notification.get('player_name', 'Unknown'),
                        'division': last_notification.get('division', 'Unknown'),
                        'email': last_notification.get('email', 'Unknown'),
                        'imported_as_non_responder': True
                    }
        
        # Save all data
        self._save_json_file(self.responses_file, merged_responses)
        self._save_json_file(self.notifications_file, notification_history)
        self._save_json_file(self.non_responders_file, non_responders)
        
        # Create summary report
        logger.info("\n" + "="*60)
        logger.info("MIGRATION SUMMARY")
        logger.info("="*60)
        logger.info(f"Excel Import Results:")
        logger.info(f"  - Total responses imported: {len(excel_responses)}")
        logger.info(f"  - Keep on waitlist: {len(keep_list)}")
        logger.info(f"  - Remove from waitlist: {len(remove_list)}")
        logger.info(f"\nOverall Results:")
        logger.info(f"  - Total responses in system: {len(merged_responses)}")
        logger.info(f"  - Non-responders identified: {len(non_responders)}")
        
        # Save lists for easy reference
        summary_file = self.data_dir / "migration_summary.json"
        summary_data = {
            'migration_date': datetime.now().isoformat(),
            'excel_file': excel_path,
            'import_stats': {
                'total_imported': len(excel_responses),
                'yes_responses': len(keep_list),
                'no_responses': len(remove_list)
            },
            'remove_list': remove_list,
            'keep_list': keep_list,
            'non_responders': list(non_responders.keys())
        }
        
        self._save_json_file(summary_file, summary_data)
        logger.info(f"\nMigration summary saved to: {summary_file}")
        
        # Mark migration as complete
        self._mark_migration_complete()
    
    def _load_json_file(self, file_path: Path) -> Dict:
        """Load JSON file safely"""
        if not file_path.exists():
            return {}
        
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return {}
    
    def _save_json_file(self, file_path: Path, data: Dict):
        """Save JSON file safely"""
        try:
            # Ensure directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {file_path}")
        except Exception as e:
            logger.error(f"Error saving {file_path}: {e}")
            raise
    
    def _mark_migration_complete(self):
        """Mark migration as completed"""
        with open(self.migration_status_file, 'w') as f:
            f.write(json.dumps({
                'migration_version': 'v2_excel_import',
                'completed_at': datetime.now().isoformat(),
                'success': True
            }, indent=2))
        logger.info("Migration marked as complete")
    
    def backup_existing_data(self):
        """Create backup of existing data before migration"""
        logger.info("Creating backup of existing data...")
        
        # Create backup directory
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Backup existing files
        files_to_backup = [
            self.responses_file,
            self.notifications_file,
            self.non_responders_file
        ]
        
        for file_path in files_to_backup:
            if file_path.exists():
                backup_path = self.backup_dir / file_path.name
                shutil.copy2(file_path, backup_path)
                logger.info(f"Backed up {file_path.name} to {backup_path}")
    
    def run_migration(self, excel_path: str = None):
        """
        Run the complete migration process
        
        Args:
            excel_path: Path to Excel file with responses
        """
        logger.info("="*60)
        logger.info("Waitlist Data Migration with Excel Import")
        logger.info("="*60)
        
        try:
            # Look for Excel file if not provided
            if not excel_path:
                possible_paths = [
                    "AYSO Region 58  Waitlist Confirmation Responses.xlsx",
                    "data/AYSO Region 58  Waitlist Confirmation Responses.xlsx",
                    "data/downloads/AYSO Region 58  Waitlist Confirmation Responses.xlsx"
                ]
                
                for path in possible_paths:
                    if os.path.exists(path):
                        excel_path = path
                        logger.info(f"Found Excel file at: {path}")
                        break
                
                if not excel_path:
                    logger.error("Excel file not found. Please provide path to 'AYSO Region 58  Waitlist Confirmation Responses.xlsx'")
                    return
            
            # Backup existing data
            self.backup_existing_data()
            
            # Perform migration with Excel import
            self.migrate_with_excel_data(excel_path)
            
            logger.info("\nMigration completed successfully!")
            logger.info(f"Backup saved to: {self.backup_dir}")
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            logger.error("Original data has been preserved. Please check the error and try again.")
            raise


def main():
    """Run the migration with Excel import"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate waitlist data with Excel import')
    parser.add_argument('--data-dir', default='data/waitlist_tracking',
                       help='Directory containing waitlist data')
    parser.add_argument('--excel-file', 
                       default='AYSO Region 58  Waitlist Confirmation Responses.xlsx',
                       help='Path to Excel file with responses')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be imported without making changes')
    
    args = parser.parse_args()
    
    migration = WaitlistDataMigration(args.data_dir)
    
    if args.dry_run:
        # Just show what would be imported
        try:
            responses, keep_list, remove_list = migration.import_excel_responses(args.excel_file)
            print(f"\nDry run results:")
            print(f"Would import {len(responses)} responses")
            print(f"Keep on waitlist: {len(keep_list)}")
            print(f"Remove from waitlist: {len(remove_list)}")
            print(f"\nSample entries to remove:")
            for order in remove_list[:5]:
                r = responses[order]
                print(f"  {order}: {r['player_name']} ({r['division']})")
        except Exception as e:
            print(f"Error: {e}")
            return 1
    else:
        try:
            migration.run_migration(args.excel_file)
            return 0
        except Exception:
            return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())