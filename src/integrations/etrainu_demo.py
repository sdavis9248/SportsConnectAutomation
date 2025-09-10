#!/usr/bin/env python3
"""
Demo script to test ETrainU functionality with your uploaded data
This script processes the actual files you uploaded to demonstrate the functionality
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ETrainUDemo:
    """Demo class to test ETrainU functionality with actual data"""
    
    def __init__(self):
        self.volunteer_data = None
        self.compliance_data = None
        self.enrollment_data = None
        self.parsed_events = []
        
    def load_actual_data(self, file_paths: dict):
        """Load the actual Excel files you uploaded"""
        logger.info("Loading actual volunteer data...")
        
        try:
            # Load compliance data
            if 'compliance' in file_paths:
                self.compliance_data = pd.read_excel(file_paths['compliance'])
                logger.info(f"✓ Loaded {len(self.compliance_data)} compliance records")
                logger.info(f"Columns: {list(self.compliance_data.columns[:5])}...")  # Show first 5 columns
            
            # Load volunteer details
            if 'volunteer_details' in file_paths:
                self.volunteer_data = pd.read_excel(file_paths['volunteer_details'])
                logger.info(f"✓ Loaded {len(self.volunteer_data)} volunteer detail records")
            
            # Load enrollment data
            if 'enrollment' in file_paths:
                self.enrollment_data = pd.read_excel(file_paths['enrollment'])
                logger.info(f"✓ Loaded {len(self.enrollment_data)} enrollment records")
                
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            raise
    
    def parse_sample_events(self):
        """Parse sample events from the HTML structure we saw"""
        logger.info("Creating sample events from HTML structure...")
        
        # Based on the HTML content we saw, create sample events
        sample_events = [
            {
                'event_id': '6838d0f7df5518001a602dae_6838d0f7df5518001a602daf',
                'data_event_id': '6838d0f7df5518001a602dae',
                'title': 'Regional Referee Companion Course',
                'description': 'This is the in-person companion course intended to be taken by entry-level referee volunteers after they completed the Regional Referee online course.',
                'course_type': 'Regional Referee',
                'prerequisites': ['Regional Referee Online Course', 'Safe Haven', 'CDC Concussion', 'SafeSport'],
                'contact': {'name': 'Fred Weihmiller', 'email': 'r100Referee@aysohawaii.org'},
                'sessions': [{'date': '2025-08-15', 'time': '9:00 AM', 'location': 'TBD'}],
                'scraped_at': datetime.now().isoformat()
            },
            {
                'event_id': '68a22687c9b1cc001ae18d66_68a22687c9b1cc001ae18d67',
                'data_event_id': '68a22687c9b1cc001ae18d66',
                'title': '10U Coach Training Online + In-Person Classroom and Field Session',
                'description': 'This is a 10U Coach Training course which has online pre-requisite, classroom session, and field session.',
                'course_type': '10U Coach',
                'prerequisites': ['Safe Haven', 'CDC Concussion', 'SafeSport', 'Sudden Cardiac Arrest'],
                'contact': {'name': 'Coach Administrator', 'email': 'coach@ayso.org'},
                'sessions': [{'date': '2025-08-16', 'time': '10:00 AM', 'location': 'Local Field'}],
                'scraped_at': datetime.now().isoformat()
            },
            {
                'event_id': '68a22721c9b1cc001ae18d6f_68a22721c9b1cc001ae18d70',
                'data_event_id': '68a22721c9b1cc001ae18d6f',
                'title': '12U Coach Training Online + In-Person Classroom and Field Session',
                'description': 'This is a 10U/12U Coach Training course with online pre-requisite, Friday Zoom classroom, and Saturday field session.',
                'course_type': '12U Coach',
                'prerequisites': ['10U Coach Certification', 'Safe Haven', 'CDC Concussion', 'SafeSport'],
                'contact': {'name': 'Training Coordinator', 'email': 'training@ayso.org'},
                'sessions': [
                    {'date': '2025-08-22', 'time': '7:00 PM', 'location': 'Zoom'},
                    {'date': '2025-08-23', 'time': '9:00 AM', 'location': 'Field Session'}
                ],
                'scraped_at': datetime.now().isoformat()
            },
            {
                'event_id': '6894d19ff38344001a391f6b_6894d19ff38344001a391f6c',
                'data_event_id': '6894d19ff38344001a391f6b',
                'title': '6U/8U In-Person Coach Course',
                'description': 'Entry level coaching course for 6U and 8U divisions.',
                'course_type': '6U/8U Coach',
                'prerequisites': ['Safe Haven', 'CDC Concussion', 'SafeSport'],
                'contact': {'name': 'Youth Coach Coordinator', 'email': 'youth@ayso.org'},
                'sessions': [{'date': '2025-08-17', 'time': '11:00 AM', 'location': 'Training Center'}],
                'scraped_at': datetime.now().isoformat()
            },
            {
                'event_id': '68ae3a57df5518001a607a5f_68ae3a57df5518001a607a60',
                'data_event_id': '68ae3a57df5518001a607a5f',
                'title': 'Intermediate Coach Certification (14U)',
                'description': 'Advanced coaching course for 14U division requiring 12U certification as prerequisite.',
                'course_type': '14U/Intermediate Coach',
                'prerequisites': ['12U Coach Certification', 'Safe Haven', 'CDC Concussion', 'SafeSport', 'Summary of Laws'],
                'contact': {'name': 'Derek Bartolome', 'email': 'aca@ayso11o.org'},
                'sessions': [{'date': '2025-08-24', 'time': '1:00 PM', 'location': 'Advanced Training Field'}],
                'scraped_at': datetime.now().isoformat()
            }
        ]
        
        self.parsed_events = sample_events
        logger.info(f"✓ Created {len(sample_events)} sample events")
        return sample_events
    
    def analyze_volunteer_certifications(self):
        """Analyze current volunteer certification status"""
        if self.compliance_data is None:
            logger.warning("No compliance data available for analysis")
            return {}
        
        logger.info("Analyzing volunteer certifications...")
        
        analysis = {
            'total_volunteers': len(self.compliance_data),
            'certification_status': {},
            'role_distribution': {},
            'division_distribution': {},
            'risk_status': {}
        }
        
        # Certification status analysis
        cert_columns = [
            'AYSOs Safe Haven Verified',
            'Concussion Awareness Verified',
            'SafeSport Verified',
            'Sudden Cardiac Arrest Verified'
        ]
        
        for cert in cert_columns:
            if cert in self.compliance_data.columns:
                verified_count = (self.compliance_data[cert] == 'Y').sum()
                analysis['certification_status'][cert] = {
                    'verified': verified_count,
                    'percentage': f"{(verified_count/len(self.compliance_data)*100):.1f}%"
                }
        
        # Role distribution
        if 'Volunteer Role' in self.compliance_data.columns:
            role_counts = self.compliance_data['Volunteer Role'].value_counts()
            analysis['role_distribution'] = role_counts.to_dict()
        
        # Division distribution
        if 'Division Name' in self.compliance_data.columns:
            div_counts = self.compliance_data['Division Name'].value_counts()
            analysis['division_distribution'] = dict(div_counts.head(10))  # Top 10 divisions
        
        # Risk status
        if 'Risk Status' in self.compliance_data.columns:
            risk_counts = self.compliance_data['Risk Status'].value_counts()
            analysis['risk_status'] = risk_counts.to_dict()
        
        return analysis
    
    def match_volunteers_to_courses(self):
        """Match volunteers to available courses based on their qualifications"""
        if self.compliance_data is None or not self.parsed_events:
            logger.warning("Missing data for volunteer matching")
            return {}
        
        logger.info("Matching volunteers to courses...")
        
        matches = {}
        total_matches = 0
        
        # Define course requirements
        course_requirements = {
            '6U/8U Coach': {
                'target_divisions': ['06U', '08U'],
                'target_roles': ['Head Coach', 'Assistant Coach'],
                'required_certs': ['AYSOs Safe Haven Verified', 'Concussion Awareness Verified', 'SafeSport Verified']
            },
            '10U Coach': {
                'target_divisions': ['10U'],
                'target_roles': ['Head Coach', 'Assistant Coach'],
                'required_certs': ['AYSOs Safe Haven Verified', 'Concussion Awareness Verified', 'SafeSport Verified']
            },
            '12U Coach': {
                'target_divisions': ['12U'],
                'target_roles': ['Head Coach', 'Assistant Coach'],
                'required_certs': ['AYSOs Safe Haven Verified', 'Concussion Awareness Verified', 'SafeSport Verified'],
                'prerequisite_level': '10U'
            },
            'Regional Referee': {
                'target_roles': ['Referee', 'Assistant Referee', 'Head Coach', 'Assistant Coach'],
                'required_certs': ['AYSOs Safe Haven Verified', 'Concussion Awareness Verified', 'SafeSport Verified']
            }
        }
        
        for _, volunteer in self.compliance_data.iterrows():
            volunteer_name = f"{volunteer.get('Volunteer First Name', '')} {volunteer.get('Volunteer Last Name', '')}"
            volunteer_matches = []
            
            # Check each course
            for event in self.parsed_events:
                course_type = event['course_type']
                if course_type in course_requirements:
                    requirements = course_requirements[course_type]
                    
                    match_score = self._calculate_volunteer_match(volunteer, requirements)
                    if match_score > 60:  # Threshold for recommendation
                        volunteer_matches.append({
                            'event': event,
                            'course_type': course_type,
                            'match_score': match_score,
                            'reasons': self._get_match_reasons(volunteer, requirements)
                        })
                        total_matches += 1
            
            if volunteer_matches:
                matches[volunteer_name] = volunteer_matches
        
        logger.info(f"✓ Generated {total_matches} total matches for {len(matches)} volunteers")
        return matches
    
    def _calculate_volunteer_match(self, volunteer: pd.Series, requirements: dict) -> float:
        """Calculate match score for volunteer-course pairing"""
        score = 0.0
        
        # Check role match
        volunteer_role = str(volunteer.get('Volunteer Role', '')).lower()
        target_roles = [role.lower() for role in requirements.get('target_roles', [])]
        
        if any(role in volunteer_role for role in target_roles):
            score += 30.0
        
        # Check division match
        volunteer_division = str(volunteer.get('Division Name', ''))
        target_divisions = requirements.get('target_divisions', [])
        
        if not target_divisions or any(div in volunteer_division for div in target_divisions):
            score += 25.0
        
        # Check certifications
        required_certs = requirements.get('required_certs', [])
        cert_score = 0
        for cert in required_certs:
            if volunteer.get(cert) == 'Y':
                cert_score += 1
        
        if required_certs:
            score += (cert_score / len(required_certs)) * 30.0
        
        # Bonus for green risk status
        if volunteer.get('Risk Status') == 'Green':
            score += 10.0
        
        # Bonus for existing coaching level
        if pd.notna(volunteer.get('Coaching License Level')):
            score += 5.0
        
        return min(score, 100.0)
    
    def _get_match_reasons(self, volunteer: pd.Series, requirements: dict) -> str:
        """Get human-readable reasons for the match"""
        reasons = []
        
        # Role match
        volunteer_role = volunteer.get('Volunteer Role', '')
        if volunteer_role:
            reasons.append(f"Role: {volunteer_role}")
        
        # Division match
        division = volunteer.get('Division Name', '')
        if division:
            reasons.append(f"Division: {division}")
        
        # Risk status
        risk_status = volunteer.get('Risk Status', '')
        if risk_status == 'Green':
            reasons.append("Green risk status")
        
        # Existing certifications
        cert_count = 0
        required_certs = requirements.get('required_certs', [])
        for cert in required_certs:
            if volunteer.get(cert) == 'Y':
                cert_count += 1
        
        if cert_count > 0:
            reasons.append(f"{cert_count}/{len(required_certs)} required certifications")
        
        return "; ".join(reasons)
    
    def generate_demo_report(self, analysis: dict, matches: dict):
        """Generate a comprehensive demo report"""
        logger.info("Generating demo report...")
        
        # Create recommendations dataframe
        report_data = []
        
        for volunteer_name, volunteer_matches in matches.items():
            for match in volunteer_matches:
                event = match['event']
                report_data.append({
                    'Volunteer Name': volunteer_name,
                    'Recommended Course': match['course_type'],
                    'Event Title': event['title'],
                    'Match Score': match['match_score'],
                    'Event Date': event['sessions'][0].get('date', 'TBD') if event['sessions'] else 'TBD',
                    'Event Time': event['sessions'][0].get('time', 'TBD') if event['sessions'] else 'TBD',
                    'Location': event['sessions'][0].get('location', 'TBD') if event['sessions'] else 'TBD',
                    'Contact': event['contact'].get('name', 'TBD'),
                    'Contact Email': event['contact'].get('email', 'TBD'),
                    'Reasons': match['reasons'],
                    'Prerequisites': ', '.join(event.get('prerequisites', []))
                })
        
        report_df = pd.DataFrame(report_data)
        
        # Save to Excel
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create output directory
        output_dir = Path("demo_output")
        output_dir.mkdir(exist_ok=True)
        
        # Save comprehensive report
        report_file = output_dir / f"etrainu_demo_report_{timestamp}.xlsx"
        
        with pd.ExcelWriter(report_file) as writer:
            # Main recommendations
            report_df.to_excel(writer, sheet_name='Recommendations', index=False)
            
            # Volunteer analysis summary
            analysis_data = []
            
            # Certification status
            for cert, data in analysis['certification_status'].items():
                analysis_data.append({
                    'Category': 'Certification Status',
                    'Item': cert.replace(' Verified', ''),
                    'Count': data['verified'],
                    'Total': analysis['total_volunteers'],
                    'Percentage': data['percentage']
                })
            
            # Role distribution
            for role, count in analysis['role_distribution'].items():
                analysis_data.append({
                    'Category': 'Role Distribution',
                    'Item': role,
                    'Count': count,
                    'Total': analysis['total_volunteers'],
                    'Percentage': f"{(count/analysis['total_volunteers']*100):.1f}%"
                })
            
            analysis_df = pd.DataFrame(analysis_data)
            analysis_df.to_excel(writer, sheet_name='Volunteer Analysis', index=False)
            
            # Course summary
            course_summary = report_df['Recommended Course'].value_counts().reset_index()
            course_summary.columns = ['Course Type', 'Number of Matches']
            course_summary.to_excel(writer, sheet_name='Course Summary', index=False)
        
        # Save JSON data
        json_file = output_dir / f"etrainu_demo_data_{timestamp}.json"
        demo_data = {
            'events': self.parsed_events,
            'matches': matches,
            'analysis': analysis,
            'timestamp': timestamp
        }
        
        with open(json_file, 'w') as f:
            json.dump(demo_data, f, indent=2, default=str)
        
        logger.info(f"✓ Demo report saved to: {report_file}")
        logger.info(f"✓ Demo data saved to: {json_file}")
        
        return {
            'report_file': str(report_file),
            'json_file': str(json_file),
            'report_dataframe': report_df,
            'total_recommendations': len(report_df)
        }
    
    def run_complete_demo(self, file_paths: dict):
        """Run the complete demonstration"""
        logger.info("Starting complete ETrainU demo...")
        
        try:
            # Load data
            self.load_actual_data(file_paths)
            
            # Parse events
            events = self.parse_sample_events()
            
            # Analyze volunteers
            analysis = self.analyze_volunteer_certifications()
            
            # Match volunteers to courses
            matches = self.match_volunteers_to_courses()
            
            # Generate report
            report_info = self.generate_demo_report(analysis, matches)
            
            # Print summary
            self.print_demo_summary(analysis, matches, report_info)
            
            return {
                'success': True,
                'events': events,
                'analysis': analysis,
                'matches': matches,
                'report': report_info
            }
            
        except Exception as e:
            logger.error(f"Demo failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def print_demo_summary(self, analysis: dict, matches: dict, report_info: dict):
        """Print a nice summary of the demo results"""
        print("\n" + "="*70)
        print("ETRAINU DEMO RESULTS SUMMARY")
        print("="*70)
        
        print(f"\n📊 VOLUNTEER ANALYSIS:")
        print(f"  Total Volunteers: {analysis['total_volunteers']}")
        
        print(f"\n📋 CERTIFICATION STATUS:")
        for cert, data in analysis['certification_status'].items():
            cert_name = cert.replace(' Verified', '').replace('AYSOs ', '')
            print(f"  {cert_name}: {data['verified']} verified ({data['percentage']})")
        
        print(f"\n👥 TOP VOLUNTEER ROLES:")
        for role, count in list(analysis['role_distribution'].items())[:5]:
            percentage = (count/analysis['total_volunteers']*100)
            print(f"  {role}: {count} ({percentage:.1f}%)")
        
        print(f"\n🎯 COURSE MATCHING RESULTS:")
        print(f"  Volunteers with Matches: {len(matches)}")
        print(f"  Total Recommendations: {report_info['total_recommendations']}")
        print(f"  Average Matches per Volunteer: {report_info['total_recommendations']/len(matches):.1f}")
        
        # Course breakdown
        course_counts = {}
        for volunteer_matches in matches.values():
            for match in volunteer_matches:
                course_type = match['course_type']
                course_counts[course_type] = course_counts.get(course_type, 0) + 1
        
        print(f"\n📚 COURSE DEMAND:")
        for course, count in sorted(course_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {course}: {count} matches")
        
        print(f"\n📁 OUTPUT FILES:")
        print(f"  Excel Report: {report_info['report_file']}")
        print(f"  JSON Data: {report_info['json_file']}")
        
        print("\n" + "="*70)
        print("Demo completed successfully! Check the output files for detailed results.")
        print("="*70 + "\n")


# Main execution
if __name__ == "__main__":
    # File paths for the uploaded data
    file_paths = {
        'compliance': 'data/compliance/2025 Volunteer Compliance.xlsx',
        'volunteer_details': 'data/downloads/Volunteer_Details (67).xlsx',
        'enrollment': 'data/downloads/Enrollment_Details (72).xlsx'
    }
    
    # Run demo
    demo = ETrainUDemo()
    results = demo.run_complete_demo(file_paths)
    
    if results['success']:
        print("✅ ETrainU demo completed successfully!")
        print(f"Check the 'demo_output' directory for generated reports.")
    else:
        print(f"❌ Demo failed: {results['error']}")
