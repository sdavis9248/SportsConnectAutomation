#!/usr/bin/env python3
"""
Integration script for ETrainU with SportsConnectAutomation
Run this script to parse events and match volunteers with courses
"""

import sys
import os
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime

# Add the automation directory to the path (adjust as needed for your project structure)
current_dir = Path(__file__).parent
src_dir = current_dir.parent / 'src'
if src_dir.exists():
    sys.path.insert(0, str(src_dir))

# Import your existing automation classes
try:
    from core.config import ConfigManager
    from automation.sports_connect import SportsConnectAutomation
    from automation.etrainu_scraper import ETrainUEventScraper, ETrainUAutomationModule
except ImportError as e:
    print(f"Import error: {e}")
    print("Please ensure the ETrainU scraper module is in the automation directory")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('etrainu_integration.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ETrainUIntegrator:
    """Integrates ETrainU functionality with existing SportsConnect automation"""
    
    def __init__(self, config_path: str = 'config/config.json'):
        """Initialize the integrator"""
        self.config = ConfigManager(config_path)
        self.config.load_config()
        self.automation = None
        self.etrainu_module = None
        
    def setup_automation(self, login_required: bool = False):
        """Set up the automation components"""
        logger.info("Setting up automation components...")
        
        # Initialize SportsConnect automation if needed
        if login_required:
            self.automation = SportsConnectAutomation(self.config)
            self.automation.initialize()
            if not self.automation.login():
                logger.error("Failed to login to SportsConnect")
                return False
        
        # Initialize ETrainU module
        self.etrainu_module = ETrainUAutomationModule(self.automation, self.config)
        
        logger.info("✓ Automation setup complete")
        return True
    
    def process_etrainu_data(self, html_file: str, data_directory: str = "data") -> dict:
        """Process ETrainU HTML and volunteer data"""
        logger.info("Processing ETrainU data...")
        
        # Define file paths
        data_path = Path(data_directory)
        volunteer_files = {
            'compliance': data_path / '2025 Volunteer Compliance.xlsx',
            'volunteer_details': data_path / 'Volunteer_Details 63.xlsx',
            'enrollment': data_path / 'Enrollment_Details.xlsx'
        }
        
        # Check if files exist
        missing_files = []
        for key, filepath in volunteer_files.items():
            if not filepath.exists():
                missing_files.append(str(filepath))
        
        if missing_files:
            logger.warning(f"Missing files: {', '.join(missing_files)}")
            # Use only available files
            volunteer_files = {k: v for k, v in volunteer_files.items() if v.exists()}
        
        # Convert to strings for the module
        volunteer_files_str = {k: str(v) for k, v in volunteer_files.items()}
        
        # Initialize the module with data
        self.etrainu_module.initialize_from_files(html_file, volunteer_files_str)
        
        # Get recommendations
        recommendations = self.etrainu_module.get_enrollment_recommendations()
        
        logger.info(f"✓ Processing complete:")
        logger.info(f"  - {recommendations['total_events']} events parsed")
        logger.info(f"  - {recommendations['total_volunteers']} volunteers with matches")
        logger.info(f"  - {recommendations['total_recommendations']} total recommendations")
        
        return recommendations
    
    def generate_reports(self, recommendations: dict, output_dir: str = "reports") -> dict:
        """Generate various reports from the recommendations"""
        logger.info("Generating reports...")
        
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        report_df = recommendations['report_dataframe']
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Main enrollment report
        enrollment_report_file = output_path / f"enrollment_recommendations_{timestamp}.xlsx"
        report_df.to_excel(enrollment_report_file, index=False)
        
        # Summary report
        summary_data = []
        
        # Course popularity
        course_counts = report_df['Recommended Course'].value_counts()
        for course, count in course_counts.items():
            summary_data.append({
                'Metric': 'Course Demand',
                'Category': course,
                'Count': count,
                'Percentage': f"{(count/len(report_df)*100):.1f}%"
            })
        
        # Top volunteers by match score
        top_volunteers = report_df.nlargest(10, 'Match Score')[['Volunteer Name', 'Match Score']]
        for _, vol in top_volunteers.iterrows():
            summary_data.append({
                'Metric': 'Top Match Score',
                'Category': vol['Volunteer Name'],
                'Count': vol['Match Score'],
                'Percentage': ''
            })
        
        summary_df = pd.DataFrame(summary_data)
        summary_file = output_path / f"enrollment_summary_{timestamp}.xlsx"
        
        # Create multi-sheet Excel file
        with pd.ExcelWriter(summary_file) as writer:
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            report_df.to_excel(writer, sheet_name='Full Report', index=False)
            
            # Course breakdown sheet
            course_breakdown = report_df.groupby(['Recommended Course']).agg({
                'Match Score': ['mean', 'count', 'max'],
                'Volunteer Name': 'nunique'
            }).round(2)
            course_breakdown.to_excel(writer, sheet_name='Course Breakdown')
        
        logger.info(f"✓ Reports generated:")
        logger.info(f"  - Main report: {enrollment_report_file}")
        logger.info(f"  - Summary report: {summary_file}")
        
        return {
            'enrollment_report': str(enrollment_report_file),
            'summary_report': str(summary_file),
            'report_dataframe': report_df
        }
    
    def run_full_integration(self, html_file: str, data_dir: str = "data", 
                           output_dir: str = "reports", login: bool = False) -> dict:
        """Run the complete integration process"""
        logger.info("Starting full ETrainU integration...")
        
        try:
            # Setup
            if not self.setup_automation(login_required=login):
                return {'success': False, 'error': 'Failed to setup automation'}
            
            # Process data
            recommendations = self.process_etrainu_data(html_file, data_dir)
            
            # Generate reports
            reports = self.generate_reports(recommendations, output_dir)
            
            # Combine results
            results = {
                'success': True,
                'recommendations': recommendations,
                'reports': reports,
                'summary': {
                    'total_events': recommendations['total_events'],
                    'total_volunteers': recommendations['total_volunteers'],
                    'total_recommendations': recommendations['total_recommendations'],
                    'events_file': recommendations['events_file'],
                    'matches_file': recommendations['matches_file']
                }
            }
            
            logger.info("✓ Full integration completed successfully!")
            return results
            
        except Exception as e:
            logger.error(f"Integration failed: {e}")
            return {'success': False, 'error': str(e)}


def main():
    """Main function to run the integration"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ETrainU Integration with SportsConnect')
    parser.add_argument('--html', required=True, help='Path to etrainu.html file')
    parser.add_argument('--data-dir', default='data', help='Directory containing volunteer Excel files')
    parser.add_argument('--output-dir', default='reports', help='Output directory for reports')
    parser.add_argument('--login', action='store_true', help='Login to SportsConnect (optional)')
    parser.add_argument('--config', default='config/config.json', help='Path to config file')
    
    args = parser.parse_args()
    
    # Check if HTML file exists
    if not Path(args.html).exists():
        logger.error(f"HTML file not found: {args.html}")
        return 1
    
    # Run integration
    integrator = ETrainUIntegrator(args.config)
    results = integrator.run_full_integration(
        html_file=args.html,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        login=args.login
    )
    
    if results['success']:
        print("\n" + "="*60)
        print("ETRAINU INTEGRATION COMPLETED SUCCESSFULLY!")
        print("="*60)
        print(f"Events processed: {results['summary']['total_events']}")
        print(f"Volunteers matched: {results['summary']['total_volunteers']}")
        print(f"Recommendations: {results['summary']['total_recommendations']}")
        print("\nFiles generated:")
        print(f"  - Events: {results['summary']['events_file']}")
        print(f"  - Matches: {results['summary']['matches_file']}")
        print(f"  - Enrollment Report: {results['reports']['enrollment_report']}")
        print(f"  - Summary Report: {results['reports']['summary_report']}")
        print("="*60)
        return 0
    else:
        print(f"\nIntegration failed: {results['error']}")
        return 1


if __name__ == "__main__":
    exit(main())
