"""
Test script for searching players in Enrollment Details spreadsheet
This will help develop player lookup and management features
"""
import pandas as pd
import glob
import os
from pathlib import Path
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class EnrollmentDetailsSearcher:
    """Search and analyze Enrollment Details data"""
    
    def __init__(self, download_dir: str = r"C:\Users\sdavis\OneDrive\source\repos\SportsConnectAutomation\data\downloads"):
        self.download_dir = Path(download_dir)
        self.df = None
        self.file_path = None
        
        # Define expected columns for reference
        self.expected_columns = [
            'Program Name', 'Division Name', 'Player First Name', 'Player Last Name',
            'Player Evaluation Rating', 'Player Evaluation Comment', 'Team Name',
            'Player Jersey Number', 'Player Email', 'Birth Certificate',
            'Account First Name', 'Account Last Name', 'Order No', 'Order Payment Status',
            'Order Amount', 'Order Payment Amount', 'OrderItem Amount',
            'OrderItem Amount Paid', 'OrderItem Balance', 'Birth Certificate Note',
            'Birth Date', 'Time Stamp', 'Birth Certificate User Id', 'User Email',
            'Association Player ID', 'Would you like information on volunteering as a head coach?'
        ]
    
    def find_latest_enrollment_file(self) -> str:
        """Find the most recent Enrollment Details file"""
        pattern = self.download_dir / "Enrollment_Details*.xlsx"
        files = glob.glob(str(pattern))
        
        if not files:
            # Try alternative patterns
            patterns = [
                "*Enrollment*Details*.xlsx",
                "*enrollment*details*.xlsx",
                "DivisionDetails*.xlsx"
            ]
            for alt_pattern in patterns:
                files = glob.glob(str(self.download_dir / alt_pattern))
                if files:
                    break
        
        if not files:
            raise FileNotFoundError(f"No Enrollment Details files found in {self.download_dir}")
        
        # Get the most recent file
        latest_file = max(files, key=os.path.getmtime)
        logger.info(f"Found latest file: {latest_file}")
        
        # Get file info
        file_stat = os.stat(latest_file)
        mod_time = datetime.fromtimestamp(file_stat.st_mtime)
        logger.info(f"Last modified: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"File size: {file_stat.st_size:,} bytes")
        
        return latest_file
    
    def load_data(self):
        """Load the Enrollment Details data"""
        self.file_path = self.find_latest_enrollment_file()
        
        logger.info("Loading Excel file...")
        self.df = pd.read_excel(self.file_path)
        
        logger.info(f"Loaded {len(self.df)} rows")
        logger.info(f"Columns found: {', '.join(self.df.columns)}")
        
        # Check for missing expected columns
        missing_cols = [col for col in self.expected_columns if col not in self.df.columns]
        if missing_cols:
            logger.warning(f"Missing expected columns: {', '.join(missing_cols)}")
        
        # Display data types
        logger.info("\nColumn data types:")
        for col in self.df.columns:
            logger.info(f"  {col}: {self.df[col].dtype}")
    
    def search_by_player_name(self, first_name: str = None, last_name: str = None) -> pd.DataFrame:
        """Search by player name (first and/or last)"""
        if self.df is None:
            self.load_data()
        
        mask = pd.Series([True] * len(self.df))
        
        if first_name:
            mask &= self.df['Player First Name'].str.lower() == first_name.lower()
        
        if last_name:
            mask &= self.df['Player Last Name'].str.lower() == last_name.lower()
        
        results = self.df[mask]
        logger.info(f"Found {len(results)} records for player: {first_name or ''} {last_name or ''}")
        
        return results
    
    def search_by_email(self, email: str) -> pd.DataFrame:
        """Search by email address (User Email or Player Email)"""
        if self.df is None:
            self.load_data()
        
        email_lower = email.lower()
        
        # Search in both email columns
        mask = pd.Series([False] * len(self.df))
        
        if 'User Email' in self.df.columns:
            mask |= self.df['User Email'].str.lower() == email_lower
        
        if 'Player Email' in self.df.columns:
            mask |= self.df['Player Email'].str.lower() == email_lower
        
        results = self.df[mask]
        logger.info(f"Found {len(results)} records for email: {email}")
        
        return results
    
    def search_by_order_number(self, order_no: str) -> pd.DataFrame:
        """Search by order number"""
        if self.df is None:
            self.load_data()
        
        # Convert to string for comparison
        results = self.df[self.df['Order No'].astype(str) == str(order_no)]
        logger.info(f"Found {len(results)} records for order number: {order_no}")
        
        return results
    
    def search_by_division(self, division: str) -> pd.DataFrame:
        """Search by division name"""
        if self.df is None:
            self.load_data()
        
        # Case-insensitive match
        mask = self.df['Division Name'].str.upper() == division.upper()
        results = self.df[mask]
        logger.info(f"Found {len(results)} records for division: {division}")
        
        return results
    
    def search_by_team(self, team_name: str) -> pd.DataFrame:
        """Search by team name"""
        if self.df is None:
            self.load_data()
        
        # Handle NaN values and do case-insensitive partial match
        mask = self.df['Team Name'].fillna('').str.contains(team_name, case=False, na=False)
        results = self.df[mask]
        logger.info(f"Found {len(results)} records for team: {team_name}")
        
        return results
    
    def search_by_account(self, first_name: str = None, last_name: str = None) -> pd.DataFrame:
        """Search by account holder name (parent/guardian)"""
        if self.df is None:
            self.load_data()
        
        mask = pd.Series([True] * len(self.df))
        
        if first_name:
            mask &= self.df['Account First Name'].str.lower() == first_name.lower()
        
        if last_name:
            mask &= self.df['Account Last Name'].str.lower() == last_name.lower()
        
        results = self.df[mask]
        logger.info(f"Found {len(results)} records for account: {first_name or ''} {last_name or ''}")
        
        return results
    
    def advanced_search(self, **kwargs) -> pd.DataFrame:
        """
        Advanced search with multiple criteria
        
        kwargs can include:
        - player_first, player_last, email, order_no
        - division, team, program
        - account_first, account_last
        - has_birth_cert (True/False)
        - payment_status
        - wants_coach_info (True/False)
        """
        if self.df is None:
            self.load_data()
        
        mask = pd.Series([True] * len(self.df))
        
        # Player name
        if 'player_first' in kwargs:
            mask &= self.df['Player First Name'].str.lower() == kwargs['player_first'].lower()
        
        if 'player_last' in kwargs:
            mask &= self.df['Player Last Name'].str.lower() == kwargs['player_last'].lower()
        
        # Email search
        if 'email' in kwargs:
            email_lower = kwargs['email'].lower()
            email_mask = pd.Series([False] * len(self.df))
            if 'User Email' in self.df.columns:
                email_mask |= self.df['User Email'].str.lower() == email_lower
            if 'Player Email' in self.df.columns:
                email_mask |= self.df['Player Email'].str.lower() == email_lower
            mask &= email_mask
        
        # Order number
        if 'order_no' in kwargs:
            mask &= self.df['Order No'].astype(str) == str(kwargs['order_no'])
        
        # Division and team
        if 'division' in kwargs:
            mask &= self.df['Division Name'].str.upper() == kwargs['division'].upper()
        
        if 'team' in kwargs:
            mask &= self.df['Team Name'].fillna('').str.contains(kwargs['team'], case=False, na=False)
        
        if 'program' in kwargs:
            mask &= self.df['Program Name'].str.contains(kwargs['program'], case=False, na=False)
        
        # Account holder
        if 'account_first' in kwargs:
            mask &= self.df['Account First Name'].str.lower() == kwargs['account_first'].lower()
        
        if 'account_last' in kwargs:
            mask &= self.df['Account Last Name'].str.lower() == kwargs['account_last'].lower()
        
        # Birth certificate status
        if 'has_birth_cert' in kwargs:
            if kwargs['has_birth_cert']:
                mask &= self.df['Birth Certificate'].notna()
            else:
                mask &= self.df['Birth Certificate'].isna()
        
        # Payment status
        if 'payment_status' in kwargs:
            mask &= self.df['Order Payment Status'] == kwargs['payment_status']
        
        # Coach volunteer interest
        if 'wants_coach_info' in kwargs:
            coach_col = 'Would you like information on volunteering as a head coach?'
            if coach_col in self.df.columns:
                if kwargs['wants_coach_info']:
                    mask &= self.df[coach_col].str.lower() == 'yes'
                else:
                    mask &= self.df[coach_col].str.lower() != 'yes'
        
        results = self.df[mask]
        logger.info(f"Advanced search found {len(results)} records")
        
        return results
    
    def display_results(self, results: pd.DataFrame, columns: list = None):
        """Display search results in a formatted way"""
        if len(results) == 0:
            logger.info("No results to display")
            return
        
        if columns is None:
            # Default columns to display
            columns = [
                'Player First Name', 'Player Last Name', 'Division Name', 
                'Team Name', 'Player Jersey Number', 'User Email', 
                'Order No', 'Order Payment Status'
            ]
        
        # Filter to only existing columns
        display_cols = [col for col in columns if col in results.columns]
        
        logger.info(f"\nDisplaying {len(results)} results:")
        logger.info("-" * 100)
        
        for idx, row in results[display_cols].iterrows():
            logger.info(f"\nRecord {idx + 1}:")
            for col in display_cols:
                value = row[col]
                if pd.isna(value):
                    value = "N/A"
                logger.info(f"  {col}: {value}")
    
    def get_summary_stats(self):
        """Get summary statistics about the data"""
        if self.df is None:
            self.load_data()
        
        logger.info("\nData Summary:")
        logger.info(f"Total records: {len(self.df)}")
        logger.info(f"Unique players: {len(self.df[['Player First Name', 'Player Last Name']].drop_duplicates())}")
        logger.info(f"Unique orders: {self.df['Order No'].nunique()}")
        
        # Division breakdown
        logger.info("\nRecords by Division:")
        division_counts = self.df['Division Name'].value_counts()
        for division, count in division_counts.items():
            logger.info(f"  {division}: {count}")
        
        # Team assignments
        if 'Team Name' in self.df.columns:
            assigned_to_teams = self.df['Team Name'].notna().sum()
            logger.info(f"\nTeam Assignments:")
            logger.info(f"  Assigned to teams: {assigned_to_teams}")
            logger.info(f"  Not assigned: {len(self.df) - assigned_to_teams}")
            
            # Teams breakdown
            team_counts = self.df['Team Name'].value_counts().head(10)
            if not team_counts.empty:
                logger.info("\nTop 10 Teams by Player Count:")
                for team, count in team_counts.items():
                    logger.info(f"  {team}: {count}")
        
        # Payment status
        logger.info("\nPayment Status:")
        payment_counts = self.df['Order Payment Status'].value_counts()
        for status, count in payment_counts.items():
            logger.info(f"  {status}: {count}")
        
        # Birth certificate status
        if 'Birth Certificate' in self.df.columns:
            has_cert = self.df['Birth Certificate'].notna().sum()
            logger.info(f"\nBirth Certificate Status:")
            logger.info(f"  Has certificate: {has_cert}")
            logger.info(f"  Missing certificate: {len(self.df) - has_cert}")
        
        # Coach interest
        coach_col = 'Would you like information on volunteering as a head coach?'
        if coach_col in self.df.columns:
            coach_interest = self.df[coach_col].value_counts()
            logger.info("\nCoach Volunteer Interest:")
            for response, count in coach_interest.items():
                logger.info(f"  {response}: {count}")
        
        # Jersey numbers
        if 'Player Jersey Number' in self.df.columns:
            has_jersey = self.df['Player Jersey Number'].notna().sum()
            logger.info(f"\nJersey Numbers:")
            logger.info(f"  Assigned: {has_jersey}")
            logger.info(f"  Not assigned: {len(self.df) - has_jersey}")
    
    def find_players_without_teams(self) -> pd.DataFrame:
        """Find players not assigned to teams"""
        if self.df is None:
            self.load_data()
        
        if 'Team Name' not in self.df.columns:
            logger.warning("Team Name column not found")
            return pd.DataFrame()
        
        mask = self.df['Team Name'].isna()
        results = self.df[mask]
        logger.info(f"Found {len(results)} players without team assignments")
        
        return results
    
    def find_missing_birth_certificates(self) -> pd.DataFrame:
        """Find players missing birth certificates"""
        if self.df is None:
            self.load_data()
        
        if 'Birth Certificate' not in self.df.columns:
            logger.warning("Birth Certificate column not found")
            return pd.DataFrame()
        
        mask = self.df['Birth Certificate'].isna()
        results = self.df[mask]
        logger.info(f"Found {len(results)} players without birth certificates")
        
        return results
    
    def find_potential_coaches(self) -> pd.DataFrame:
        """Find parents interested in coaching"""
        if self.df is None:
            self.load_data()
        
        coach_col = 'Would you like information on volunteering as a head coach?'
        if coach_col not in self.df.columns:
            logger.warning("Coach interest column not found")
            return pd.DataFrame()
        
        mask = self.df[coach_col].str.lower() == 'yes'
        results = self.df[mask]
        logger.info(f"Found {len(results)} parents interested in coaching")
        
        return results


def main():
    """Test the search functionality"""
    searcher = EnrollmentDetailsSearcher()
    
    try:
        # Load the data
        searcher.load_data()
        
        # Show summary statistics
        searcher.get_summary_stats()
        
        # Test searches
        print("\n" + "="*100)
        print("TESTING SEARCH FUNCTIONS")
        print("="*100)
        
        # Test 1: Search by player name
        print("\n1. Searching by player name: Grace Travelstead")
        results = searcher.search_by_player_name(first_name="Grace", last_name="Travelstead")
        searcher.display_results(results)
        
        # Test 2: Search by email
        test_email = "atravelstead@gmail.com"  # Replace with actual email
        print(f"\n2. Searching by email: {test_email}")
        results = searcher.search_by_email(test_email)
        searcher.display_results(results)
        
        # Test 3: Search by division
        print("\n3. Searching by division: 10UB")
        results = searcher.search_by_division("10UB")
        searcher.display_results(results.head(5))  # Show only first 5
        
        # Test 4: Find players without teams
        print("\n4. Finding players without team assignments")
        results = searcher.find_players_without_teams()
        searcher.display_results(results.head(10))
        
        # Test 5: Find missing birth certificates
        print("\n5. Finding players without birth certificates")
        results = searcher.find_missing_birth_certificates()
        searcher.display_results(results.head(10))
        
        # Test 6: Find potential coaches
        print("\n6. Finding parents interested in coaching")
        results = searcher.find_potential_coaches()
        searcher.display_results(results.head(10), 
                                 columns=['Account First Name', 'Account Last Name', 
                                         'User Email', 'Division Name', 
                                         'Player First Name', 'Player Last Name'])

        # Test 7: Advanced search
        print("\n4. Advanced search: program + email + first_name + last_name")
        results = searcher.advanced_search(
            program="2025 Fall Core",
            email="atravelstead@gmail.com",
            player_first = "Grace",
            player_last = "Travelstead"
        )
        searcher.display_results(results.head(5))
        
        # Interactive search
        print("\n" + "="*100)
        print("INTERACTIVE SEARCH")
        print("="*100)
        
        while True:
            print("\nSearch Options:")
            print("1. Search by player name")
            print("2. Search by email")
            print("3. Search by order number")
            print("4. Search by division")
            print("5. Search by team")
            print("6. Search by account holder")
            print("7. Advanced search")
            print("8. Show players without teams")
            print("9. Show missing birth certificates")
            print("10. Show potential coaches")
            print("0. Exit")
            
            choice = input("\nEnter choice (0-10): ").strip()
            
            if choice == '0':
                break
            elif choice == '1':
                first = input("Enter player first name (or press Enter to skip): ").strip()
                last = input("Enter player last name (or press Enter to skip): ").strip()
                results = searcher.search_by_player_name(
                    first_name=first if first else None,
                    last_name=last if last else None
                )
                searcher.display_results(results)
            elif choice == '2':
                email = input("Enter email address: ").strip()
                results = searcher.search_by_email(email)
                searcher.display_results(results)
            elif choice == '3':
                order_no = input("Enter order number: ").strip()
                results = searcher.search_by_order_number(order_no)
                searcher.display_results(results)
            elif choice == '4':
                division = input("Enter division (e.g., 10UB): ").strip()
                results = searcher.search_by_division(division)
                searcher.display_results(results.head(20))
            elif choice == '5':
                team = input("Enter team name (or part of it): ").strip()
                results = searcher.search_by_team(team)
                searcher.display_results(results)
            elif choice == '6':
                first = input("Enter account holder first name (or press Enter to skip): ").strip()
                last = input("Enter account holder last name (or press Enter to skip): ").strip()
                results = searcher.search_by_account(
                    first_name=first if first else None,
                    last_name=last if last else None
                )
                searcher.display_results(results)
            elif choice == '7':
                print("\nAdvanced Search (press Enter to skip any field)")
                params = {}
                
                player_first = input("Player first name: ").strip()
                if player_first:
                    params['player_first'] = player_first
                
                player_last = input("Player last name: ").strip()
                if player_last:
                    params['player_last'] = player_last
                
                email = input("Email: ").strip()
                if email:
                    params['email'] = email
                
                division = input("Division: ").strip()
                if division:
                    params['division'] = division
                
                team = input("Team: ").strip()
                if team:
                    params['team'] = team
                
                results = searcher.advanced_search(**params)
                searcher.display_results(results)
            elif choice == '8':
                results = searcher.find_players_without_teams()
                searcher.display_results(results.head(20))
            elif choice == '9':
                results = searcher.find_missing_birth_certificates()
                searcher.display_results(results.head(20))
            elif choice == '10':
                results = searcher.find_potential_coaches()
                searcher.display_results(results.head(20), 
                                       columns=['Account First Name', 'Account Last Name', 
                                               'User Email', 'Division Name', 
                                               'Player First Name', 'Player Last Name'])
            else:
                print("Invalid choice")
                
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
