"""
Test script for searching players in Open Orders Line Item spreadsheet
This will help develop the registration cancellation feature
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

class OpenOrdersSearcher:
    """Search and analyze Open Orders Line Item data"""
    
    def __init__(self, download_dir: str = r"C:\Users\sdavis\OneDrive\source\repos\SportsConnectAutomation\data\downloads"):
        self.download_dir = Path(download_dir)
        self.df = None
        self.file_path = None
        
    def find_latest_open_orders_file(self) -> str:
        """Find the most recent Open Orders Line Item file"""
        pattern = self.download_dir / "Open_Orders_Line_Item*.xlsx"
        files = glob.glob(str(pattern))
        
        if not files:
            pattern = self.download_dir / "*Open*Orders*.xlsx"
            files = glob.glob(str(pattern))
        
        if not files:
            raise FileNotFoundError(f"No Open Orders files found in {self.download_dir}")
        
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
        """Load the Open Orders data"""
        self.file_path = self.find_latest_open_orders_file()
        
        logger.info("Loading Excel file...")
        self.df = pd.read_excel(self.file_path)
        
        logger.info(f"Loaded {len(self.df)} rows")
        logger.info(f"Columns: {', '.join(self.df.columns)}")
        
        # Display data types
        logger.info("\nColumn data types:")
        for col in self.df.columns:
            logger.info(f"  {col}: {self.df[col].dtype}")
    
    def search_by_email(self, email: str) -> pd.DataFrame:
        """Search by email address (User Email or Additional Email)"""
        if self.df is None:
            self.load_data()
        
        email_lower = email.lower()
        
        # Search in both email columns
        mask = (
            (self.df['User Email'].str.lower() == email_lower) |
            (self.df['Additional Email'].str.lower() == email_lower)
        )
        
        results = self.df[mask]
        logger.info(f"Found {len(results)} records for email: {email}")
        
        return results
    
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
    
    def search_by_order_number(self, order_no: str) -> pd.DataFrame:
        """Search by order number"""
        if self.df is None:
            self.load_data()
        
        # Convert to string for comparison
        results = self.df[self.df['Order No'].astype(str) == str(order_no)]
        logger.info(f"Found {len(results)} records for order number: {order_no}")
        
        return results
    
    def search_by_program(self, program_name: str) -> pd.DataFrame:
        """Search by program name"""
        if self.df is None:
            self.load_data()
        
        # Case-insensitive partial match
        mask = self.df['Program Name'].str.contains(program_name, case=False, na=False)
        results = self.df[mask]
        logger.info(f"Found {len(results)} records for program: {program_name}")
        
        return results
    
    def advanced_search(self, **kwargs) -> pd.DataFrame:
        """
        Advanced search with multiple criteria
        
        kwargs can include:
        - email, first_name, last_name, order_no, program_name
        - division_name, account_first, account_last
        - min_amount, max_amount (for order amounts)
        - date_from, date_to (for order dates)
        """
        if self.df is None:
            self.load_data()
        
        mask = pd.Series([True] * len(self.df))
        
        # Email search
        if 'email' in kwargs:
            email_lower = kwargs['email'].lower()
            mask &= (
                (self.df['User Email'].str.lower() == email_lower) |
                (self.df['Additional Email'].str.lower() == email_lower)
            )
        
        # Name searches
        if 'first_name' in kwargs:
            mask &= self.df['Player First Name'].str.lower() == kwargs['first_name'].lower()
        
        if 'last_name' in kwargs:
            mask &= self.df['Player Last Name'].str.lower() == kwargs['last_name'].lower()
        
        if 'account_first' in kwargs:
            mask &= self.df['Account First Name'].str.lower() == kwargs['account_first'].lower()
        
        if 'account_last' in kwargs:
            mask &= self.df['Account Last Name'].str.lower() == kwargs['account_last'].lower()
        
        # Order number
        if 'order_no' in kwargs:
            mask &= self.df['Order No'].astype(str) == str(kwargs['order_no'])
        
        # Program and division
        if 'program_name' in kwargs:
            mask &= self.df['Program Name'].str.contains(kwargs['program_name'], case=False, na=False)
        
        if 'division_name' in kwargs:
            mask &= self.df['Division Name'].str.contains(kwargs['division_name'], case=False, na=False)
        
        # Amount filters
        if 'min_amount' in kwargs:
            mask &= self.df['Order Amount'] >= kwargs['min_amount']
        
        if 'max_amount' in kwargs:
            mask &= self.df['Order Amount'] <= kwargs['max_amount']
        
        # Date filters
        if 'date_from' in kwargs or 'date_to' in kwargs:
            # Convert Order Date to datetime if it's not already
            order_dates = pd.to_datetime(self.df['Order Date'])
            
            if 'date_from' in kwargs:
                date_from = pd.to_datetime(kwargs['date_from'])
                mask &= order_dates >= date_from
            
            if 'date_to' in kwargs:
                date_to = pd.to_datetime(kwargs['date_to'])
                mask &= order_dates <= date_to
        
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
                'Order No', 'Order Date', 'Player First Name', 'Player Last Name',
                'Division Name', 'Program Name', 'User Email', 'Order Amount',
                'Order Payment Status'
            ]
        
        # Filter to only existing columns
        display_cols = [col for col in columns if col in results.columns]
        
        logger.info(f"\nDisplaying {len(results)} results:")
        logger.info("-" * 100)
        
        for idx, row in results[display_cols].iterrows():
            logger.info(f"\nRecord {idx + 1}:")
            for col in display_cols:
                value = row[col]
                # Format dates nicely
                if pd.api.types.is_datetime64_any_dtype(type(value)):
                    value = value.strftime('%Y-%m-%d')
                logger.info(f"  {col}: {value}")
    
    def get_summary_stats(self):
        """Get summary statistics about the data"""
        if self.df is None:
            self.load_data()
        
        logger.info("\nData Summary:")
        logger.info(f"Total records: {len(self.df)}")
        logger.info(f"Unique orders: {self.df['Order No'].nunique()}")
        logger.info(f"Unique players: {len(self.df[['Player First Name', 'Player Last Name']].drop_duplicates())}")
        logger.info(f"Unique emails: {self.df['User Email'].nunique()}")
        
        # Program breakdown
        logger.info("\nRecords by Program:")
        program_counts = self.df['Program Name'].value_counts()
        for program, count in program_counts.items():
            logger.info(f"  {program}: {count}")
        
        # Division breakdown
        logger.info("\nRecords by Division:")
        division_counts = self.df['Division Name'].value_counts().head(10)
        for division, count in division_counts.items():
            logger.info(f"  {division}: {count}")
        
        # Payment status breakdown
        logger.info("\nPayment Status:")
        status_counts = self.df['Order Payment Status'].value_counts()
        for status, count in status_counts.items():
            logger.info(f"  {status}: {count}")
        
        # Amount statistics
        logger.info("\nOrder Amount Statistics:")
        logger.info(f"  Total: ${self.df['Order Amount'].sum():,.2f}")
        logger.info(f"  Average: ${self.df['Order Amount'].mean():.2f}")
        logger.info(f"  Median: ${self.df['Order Amount'].median():.2f}")
        logger.info(f"  Min: ${self.df['Order Amount'].min():.2f}")
        logger.info(f"  Max: ${self.df['Order Amount'].max():.2f}")
    
    def find_cancellable_orders(self, program_name: str = None) -> pd.DataFrame:
        """Find orders that might be eligible for cancellation"""
        if self.df is None:
            self.load_data()
        
        # Start with all records
        mask = pd.Series([True] * len(self.df))
        
        # Filter by program if specified
        if program_name:
            mask &= self.df['Program Name'].str.contains(program_name, case=False, na=False)
        
        # Filter by payment status - only show paid/completed orders
        # (assuming we can only cancel orders that have been processed)
        mask &= self.df['Order Payment Status'].isin(['Paid', 'Completed', 'Complete'])
        
        # Filter out any with zero balance (might already be cancelled/refunded)
        mask &= self.df['Order Item Balance'] > 0
        
        results = self.df[mask]
        logger.info(f"Found {len(results)} potentially cancellable orders")
        
        return results


def main():
    """Test the search functionality"""
    searcher = OpenOrdersSearcher()
    
    try:
        # Load the data
        searcher.load_data()
        
        # Show summary statistics
        searcher.get_summary_stats()
        
        # Test searches
        print("\n" + "="*100)
        print("TESTING SEARCH FUNCTIONS")
        print("="*100)
        
        # # Test 1: Search by email
        # test_email = "test@example.com"  # Replace with actual email
        # print(f"\n1. Searching by email: {test_email}")
        # results = searcher.search_by_email(test_email)
        # searcher.display_results(results)
        
        # # Test 2: Search by player name
        # print("\n2. Searching by player name: John Smith")
        # results = searcher.search_by_player_name(first_name="John", last_name="Smith")
        # searcher.display_results(results)
        
        # # Test 3: Search by program
        # print("\n3. Searching by program: 2025 Fall Core")
        # results = searcher.search_by_program("2025 Fall Core")
        # searcher.display_results(results.head(5))  # Show only first 5
        
        # Test 4: Advanced search
        print("\n4. Advanced search: 2025 Fall Core + Division 10UB")
        results = searcher.advanced_search(
            # program_name="2025 Fall Core",
            email="atravelstead@gmail.com",
            first_name = "Grace",
            last_name = "Travelstead"
        )
        searcher.display_results(results.head(5))
        
        # Test 5: Find cancellable orders
        print("\n5. Finding cancellable orders for 2025 Fall Core")
        results = searcher.find_cancellable_orders("2025 Fall Core")
        searcher.display_results(results.head(10))
        
        # Interactive search
        print("\n" + "="*100)
        print("INTERACTIVE SEARCH")
        print("="*100)
        
        while True:
            print("\nSearch Options:")
            print("1. Search by email")
            print("2. Search by player name")
            print("3. Search by order number")
            print("4. Search by program")
            print("5. Advanced search")
            print("6. Show cancellable orders")
            print("0. Exit")
            
            choice = input("\nEnter choice (0-6): ").strip()
            
            if choice == '0':
                break
            elif choice == '1':
                email = input("Enter email address: ").strip()
                results = searcher.search_by_email(email)
                searcher.display_results(results)
            elif choice == '2':
                first = input("Enter first name (or press Enter to skip): ").strip()
                last = input("Enter last name (or press Enter to skip): ").strip()
                results = searcher.search_by_player_name(
                    first_name=first if first else None,
                    last_name=last if last else None
                )
                searcher.display_results(results)
            elif choice == '3':
                order_no = input("Enter order number: ").strip()
                results = searcher.search_by_order_number(order_no)
                searcher.display_results(results)
            elif choice == '4':
                program = input("Enter program name (or part of it): ").strip()
                results = searcher.search_by_program(program)
                searcher.display_results(results.head(20))
            elif choice == '5':
                print("\nAdvanced Search (press Enter to skip any field)")
                params = {}
                
                email = input("Email: ").strip()
                if email:
                    params['email'] = email
                
                first = input("Player first name: ").strip()
                if first:
                    params['first_name'] = first
                
                last = input("Player last name: ").strip()
                if last:
                    params['last_name'] = last
                
                program = input("Program name: ").strip()
                if program:
                    params['program_name'] = program
                
                division = input("Division: ").strip()
                if division:
                    params['division_name'] = division
                
                results = searcher.advanced_search(**params)
                searcher.display_results(results)
            elif choice == '6':
                program = input("Enter program name (or press Enter for all): ").strip()
                results = searcher.find_cancellable_orders(program if program else None)
                searcher.display_results(results.head(20))
            else:
                print("Invalid choice")
                
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
