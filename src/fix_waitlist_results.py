"""
One-off script to fix Player Information column in waitlist verification results
by matching with notification_history.json
"""
import pandas as pd
import json
import logging
from pathlib import Path
from datetime import datetime
import re

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_player_name_from_info(player_info):
    """
    Extract player name from the existing Player Information field
    Handles various formats that might be in the column
    """
    if pd.isna(player_info) or not player_info:
        return None
    
    # Convert to string
    player_info = str(player_info).strip()
    
    # If it already has the full format, extract just the name
    if ' (Order ' in player_info:
        # Format: "Name Division (Order XXX)"
        name_part = player_info.split(' (Order ')[0]
        # Now need to separate name from division
        # Assume division starts with a number followed by U
        parts = name_part.split()
        name_parts = []
        for i, part in enumerate(parts):
            if re.match(r'^\d+U[BG]', part):
                # Found division, everything before is name
                break
            name_parts.append(part)
        return ' '.join(name_parts).strip()
    
    # If it's just a name or name with some other format
    # Try to identify where the name ends (before any division codes)
    parts = player_info.split()
    name_parts = []
    for part in parts:
        # Stop if we hit a division code (like 10UB, 12UG, etc.)
        if re.match(r'^\d+U[BG]', part):
            break
        # Stop if we hit common division descriptors
        if part.lower() in ['boys', 'girls', 'and', 'yr', 'old', 'born']:
            break
        name_parts.append(part)
    
    name = ' '.join(name_parts).strip()
    return name if name else player_info


def load_notification_history(file_path):
    """Load the notification history JSON file"""
    logger.info(f"Loading notification history from: {file_path}")
    
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    # Create a lookup dictionary by player name
    lookup = {}
    
    # The structure has order IDs as keys, with lists of notification records
    notification_count = 0
    
    for order_id, notification_list in data.items():
        # Each order_id has a list of notifications
        for notification in notification_list:
            player_name = notification.get('player_name', '').strip()
            if player_name:
                # Add the order_id to the notification data
                notification_data = notification.copy()
                notification_data['order_id'] = order_id
                
                # Store the notification data
                lookup[player_name.lower()] = notification_data
                
                # Also try variations of the name (first last, last first)
                name_parts = player_name.split()
                if len(name_parts) == 2:
                    # Try reversed name
                    reversed_name = f"{name_parts[1]} {name_parts[0]}"
                    lookup[reversed_name.lower()] = notification_data
                
                notification_count += 1
    
    logger.info(f"Loaded {notification_count} notifications from {len(data)} orders, created {len(lookup)} lookup entries")
    return lookup


def format_player_information(notification_data):
    """
    Format the player information string based on notification data
    Format: "Name Division (Order XXX)"
    """
    player_name = notification_data.get('player_name', '')
    division = notification_data.get('division', '')
    order_id = notification_data.get('order_id', '')
    
    # Create the formatted string
    return f"{player_name} {division} (Order {order_id})"


def fix_waitlist_verification(excel_file, notification_history_file, output_file=None):
    """
    Main function to fix the Player Information column
    """
    logger.info("Starting waitlist verification fix process")
    
    # Load the notification history
    notification_lookup = load_notification_history(notification_history_file)
    
    # Load the Excel file
    logger.info(f"Loading Excel file: {excel_file}")
    df = pd.read_excel(excel_file)
    
    # Log the columns found
    logger.info(f"Columns in Excel file: {df.columns.tolist()}")
    
    # Find the Player Information column (handle variations)
    player_info_col = None
    for col in df.columns:
        if 'player' in col.lower() and 'information' in col.lower():
            player_info_col = col
            break
    
    if not player_info_col:
        logger.error("Could not find 'Player Information' column")
        logger.info(f"Available columns: {df.columns.tolist()}")
        return False
    
    logger.info(f"Found Player Information column: '{player_info_col}'")
    
    # Track statistics
    matched = 0
    unmatched = 0
    already_formatted = 0
    
    # Process each row
    for idx, row in df.iterrows():
        current_info = row[player_info_col]
        
        # Check if already properly formatted
        if pd.notna(current_info) and ' (Order ' in str(current_info):
            already_formatted += 1
            logger.debug(f"Row {idx}: Already formatted - {current_info}")
            continue
        
        # Extract player name from current info
        player_name = extract_player_name_from_info(current_info)
        
        if not player_name:
            logger.warning(f"Row {idx}: Could not extract player name from '{current_info}'")
            unmatched += 1
            continue
        
        # Look up in notification history
        lookup_key = player_name.lower()
        
        if lookup_key in notification_lookup:
            # Found a match
            notification_data = notification_lookup[lookup_key]
            new_info = format_player_information(notification_data)
            df.at[idx, player_info_col] = new_info
            matched += 1
            logger.info(f"Row {idx}: Matched '{player_name}' -> '{new_info}'")
        else:
            # Try partial matching
            found = False
            for key, notification_data in notification_lookup.items():
                if lookup_key in key or key in lookup_key:
                    # Partial match found
                    new_info = format_player_information(notification_data)
                    df.at[idx, player_info_col] = new_info
                    matched += 1
                    found = True
                    logger.info(f"Row {idx}: Partial match '{player_name}' -> '{new_info}'")
                    break
            
            if not found:
                unmatched += 1
                logger.warning(f"Row {idx}: No match found for '{player_name}'")
    
    # Save the updated file
    if output_file is None:
        # Create output filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"waitlist_verification_fixed_{timestamp}.xlsx"
    
    logger.info(f"Saving updated file to: {output_file}")
    df.to_excel(output_file, index=False)
    
    # Print summary
    logger.info("\n" + "="*50)
    logger.info("FIX SUMMARY")
    logger.info("="*50)
    logger.info(f"Total rows processed: {len(df)}")
    logger.info(f"Already formatted: {already_formatted}")
    logger.info(f"Successfully matched: {matched}")
    logger.info(f"Unmatched: {unmatched}")
    logger.info(f"Output saved to: {output_file}")
    
    return True


def main():
    """Main entry point for the script"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Fix Player Information column in waitlist verification results'
    )
    parser.add_argument(
        'excel_file',
        help='Path to the waitlist verification Excel file'
    )
    parser.add_argument(
        'notification_history',
        help='Path to the notification_history.json file'
    )
    parser.add_argument(
        '--output',
        '-o',
        help='Output file path (optional, will auto-generate if not provided)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    args = parser.parse_args()
    
    # Set debug logging if requested
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate input files exist
    if not Path(args.excel_file).exists():
        logger.error(f"Excel file not found: {args.excel_file}")
        return 1
    
    if not Path(args.notification_history).exists():
        logger.error(f"Notification history file not found: {args.notification_history}")
        return 1
    
    # Run the fix
    success = fix_waitlist_verification(
        args.excel_file,
        args.notification_history,
        args.output
    )
    
    return 0 if success else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())