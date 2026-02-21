"""
ETrainU Event Scraper and Volunteer Course Matcher
Part of the SportsConnectAutomation project - automation/ module
Handles parsing training events and matching volunteers to courses
"""
import json
import re
import pandas as pd
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Import from existing automation modules
from core.element_interactor import ElementInteractor

logger = logging.getLogger(__name__)

class ETrainUEventScraper:
    """Scrapes events from ETrainU website and matches volunteers to courses"""
    
    def __init__(self, data_dir: str = "data"):
        """Initialize the scraper with data directory"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        # Storage for scraped data
        self.events = []
        self.volunteer_data = None
        self.compliance_data = None
        self.enrollment_data = None
        
        # Course matching rules based on AYSO requirements
        self.course_prerequisites = self._initialize_course_requirements()
    
    def _initialize_course_requirements(self) -> Dict[str, Dict[str, Any]]:
        """Initialize course requirements based on AYSO training structure"""
        return {
            "6U/8U Coach": {
                "min_age": 18,
                "required_certs": ["AYSOs Safe Haven Verified", "Concussion Awareness Verified", "SafeSport Verified"],
                "target_roles": ["Head Coach", "Assistant Coach"],
                "target_divisions": ["06U", "07U", "08U", "6U", "7U", "8U"],
                "coaching_level_required": None,
                "description": "Entry-level coaching for youngest players"
            },
            "10U Coach": {
                "min_age": 18,
                "required_certs": ["AYSOs Safe Haven Verified", "Concussion Awareness Verified", 
                                 "SafeSport Verified", "Sudden Cardiac Arrest Verified"],
                "target_roles": ["Head Coach", "Assistant Coach"],
                "target_divisions": ["10U"],
                "coaching_level_required": None,
                "description": "Intermediate coaching certification"
            },
            "12U Coach": {
                "min_age": 18,
                "required_certs": ["AYSOs Safe Haven Verified", "Concussion Awareness Verified", 
                                 "SafeSport Verified", "Sudden Cardiac Arrest Verified"],
                "target_roles": ["Head Coach", "Assistant Coach"],
                "target_divisions": ["12U"],
                "coaching_level_required": "10U",
                "prerequisites": ["10U Coach Certification"],
                "description": "Advanced coaching building on 10U certification"
            },
            "14U/Intermediate Coach": {
                "min_age": 18,
                "required_certs": ["AYSOs Safe Haven Verified", "Concussion Awareness Verified", 
                                 "SafeSport Verified", "Sudden Cardiac Arrest Verified"],
                "target_roles": ["Head Coach", "Assistant Coach"],
                "target_divisions": ["14U"],
                "coaching_level_required": "12U",
                "prerequisites": ["12U Coach Certification", "Summary of Laws of Game"],
                "description": "Advanced coaching for older players"
            },
            "Regional Referee": {
                "min_age": 12,
                "required_certs": ["AYSOs Safe Haven Verified", "Concussion Awareness Verified", 
                                 "SafeSport Verified", "Sudden Cardiac Arrest Verified"],
                "target_roles": ["Referee", "Assistant Referee", "Head Coach", "Assistant Coach"],
                "target_divisions": ["all"],
                "prerequisites": ["Regional Referee Online Course"],
                "description": "Entry-level referee certification"
            },
            "Intermediate Referee": {
                "min_age": 14,
                "required_certs": ["AYSOs Safe Haven Verified", "Concussion Awareness Verified", 
                                 "SafeSport Verified", "Sudden Cardiac Arrest Verified"],
                "target_roles": ["Referee", "Assistant Referee"],
                "target_divisions": ["all"],
                "referee_level_required": "Regional",
                "prerequisites": ["Regional Referee Certification"],
                "description": "Advanced referee certification"
            }
        }
    
    def parse_html_file(self, html_file_path: str) -> List[Dict[str, Any]]:
        """Parse the etrainu.html file and extract event information"""
        logger.info(f"Parsing ETrainU HTML file: {html_file_path}")
        
        try:
            with open(html_file_path, 'r', encoding='utf-8') as file:
                html_content = file.read()
            
            soup = BeautifulSoup(html_content, 'html.parser')
            events = []
            
            # Find all event containers
            event_containers = soup.find_all('div', class_='event')
            logger.info(f"Found {len(event_containers)} event containers")
            
            for event_container in event_containers:
                event_data = self._extract_event_data(event_container)
                if event_data:
                    events.append(event_data)
            
            self.events = events
            logger.info(f"Successfully extracted {len(events)} events from HTML")
            return events
            
        except Exception as e:
            logger.error(f"Error parsing HTML file: {e}")
            return []
    
    def _extract_event_data(self, event_container) -> Optional[Dict[str, Any]]:
        """Extract data from a single event container"""
        try:
            # Basic event identifiers
            event_id = event_container.get('id', '')
            data_event_id = event_container.get('data-event-id', '')
            
            # Event title
            title_element = event_container.find('h3', class_='title')
            title = title_element.text.strip() if title_element else 'Unknown Event'
            
            # Event description
            description = self._extract_description(event_container)
            
            # Session information
            sessions = self._extract_sessions(event_container)
            
            # Contact information
            contact = self._extract_contact_info(event_container)
            
            # Enrollment button data
            enroll_info = self._extract_enroll_info(event_container)
            
            # Region information
            region = self._extract_region(event_container)
            
            # Course information
            courses = self._extract_courses(event_container)
            
            # Determine course type and prerequisites
            course_type = self._determine_course_type(title, description)
            prerequisites = self._extract_prerequisites_from_description(description, course_type)
            
            return {
                'event_id': event_id,
                'data_event_id': data_event_id,
                'title': title,
                'description': description,
                'course_type': course_type,
                'sessions': sessions,
                'contact': contact,
                'enroll_info': enroll_info,
                'region': region,
                'courses': courses,
                'prerequisites': prerequisites,
                'scraped_at': datetime.now().isoformat(),
                'raw_html': str(event_container)  # Keep for debugging
            }
            
        except Exception as e:
            logger.error(f"Error extracting event data: {e}")
            return None
    
    def _extract_description(self, event_container) -> str:
        """Extract event description"""
        description_element = event_container.find('div', class_='detail-content-inner')
        if description_element:
            return description_element.get_text(separator=' ', strip=True)
        return ''
    
    def _extract_sessions(self, event_container) -> List[Dict[str, Any]]:
        """Extract session information from event"""
        sessions = []
        
        # Look for session containers
        session_containers = event_container.find_all('div', class_='session')
        
        for session in session_containers:
            session_data = {}
            
            # Extract date, time, location from various possible structures
            date_elem = session.find('div', class_='session-date')
            time_elem = session.find('div', class_='session-time') 
            location_elem = session.find('div', class_='session-location')
            
            # Alternative patterns for session info
            if not date_elem:
                # Look for date in text content
                session_text = session.get_text()
                date_match = re.search(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', session_text)
                if date_match:
                    session_data['date'] = date_match.group()
            
            if date_elem:
                session_data['date'] = date_elem.text.strip()
            if time_elem:
                session_data['time'] = time_elem.text.strip()
            if location_elem:
                session_data['location'] = location_elem.text.strip()
            
            # Extract from session text if structured elements not found
            if not session_data and session:
                session_text = session.get_text(strip=True)
                if session_text:
                    session_data['info'] = session_text
            
            if session_data:
                sessions.append(session_data)
        
        return sessions
    
    def _extract_contact_info(self, event_container) -> Dict[str, str]:
        """Extract contact information"""
        contact = {}
        
        # Look for contact section
        contact_section = event_container.find('div', class_='contact-details')
        
        if contact_section:
            # Extract name
            contact_span = contact_section.find('span')
            if contact_span:
                # Get text content, excluding icon links
                name_text = contact_span.get_text(strip=True)
                # Remove phone and email icons/text
                name_text = re.sub(r'\s*(phone|email)\s*', '', name_text, flags=re.IGNORECASE)
                contact['name'] = name_text.strip()
            
            # Extract phone number
            phone_link = contact_section.find('a', href=re.compile(r'^tel:'))
            if phone_link:
                contact['phone'] = phone_link.get('href').replace('tel:', '')
            
            # Extract email
            email_link = contact_section.find('a', href=re.compile(r'^mailto:'))
            if email_link:
                contact['email'] = email_link.get('href').replace('mailto:', '')
        
        return contact
    
    def _extract_enroll_info(self, event_container) -> Dict[str, str]:
        """Extract enrollment button information"""
        enroll_info = {}
        enroll_button = event_container.find('button', class_='enrol-button')
        
        if enroll_button:
            enroll_info['data_event'] = enroll_button.get('data-event', '')
            enroll_info['data_session'] = enroll_button.get('data-session', '')
            enroll_info['button_text'] = enroll_button.text.strip()
        
        return enroll_info
    
    def _extract_region(self, event_container) -> str:
        """Extract region information"""
        region_element = event_container.find('div', class_='detail-content')
        if region_element and 'region' in region_element.text.lower():
            return region_element.text.strip()
        return ''
    
    def _extract_courses(self, event_container) -> List[str]:
        """Extract course list"""
        courses = []
        course_list = event_container.find('div', class_='course-list')
        
        if course_list:
            course_divs = course_list.find_all('div')
            for course_div in course_divs:
                course_text = course_div.text.strip()
                if course_text:
                    courses.append(course_text)
        
        return courses
    
    def _determine_course_type(self, title: str, description: str) -> str:
        """Determine the course type from title and description"""
        title_lower = title.lower()
        description_lower = description.lower()
        
        # Coach certifications
        if ('6u' in title_lower or '8u' in title_lower) and 'coach' in title_lower:
            return '6U/8U Coach'
        elif '10u' in title_lower and 'coach' in title_lower:
            return '10U Coach'
        elif '12u' in title_lower and 'coach' in title_lower:
            return '12U Coach'
        elif ('14u' in title_lower or 'intermediate' in title_lower) and 'coach' in title_lower:
            return '14U/Intermediate Coach'
        
        # Referee certifications
        elif 'regional referee' in title_lower:
            return 'Regional Referee'
        elif 'intermediate referee' in title_lower:
            return 'Intermediate Referee'
        elif 'referee' in title_lower and 'companion' in title_lower:
            return 'Regional Referee'
        
        # Other certifications
        elif 'safe haven' in title_lower:
            return 'Safe Haven'
        elif 'concussion' in title_lower:
            return 'Concussion Awareness'
        elif 'safesport' in title_lower:
            return 'SafeSport'
        
        return 'Other'
    
    def _extract_prerequisites_from_description(self, description: str, course_type: str) -> List[str]:
        """Extract prerequisites from event description"""
        prerequisites = []
        description_lower = description.lower()
        
        # Look for explicit prerequisite mentions
        prereq_patterns = [
            (r'10u certification.*pre.?requisite', '10U Coach Certification'),
            (r'12u certification.*pre.?requisite', '12U Coach Certification'),
            (r'regional referee.*online.*course', 'Regional Referee Online Course'),
            (r'safe haven', 'Safe Haven'),
            (r'cdc concussion', 'CDC Concussion Awareness'),
            (r'concussion awareness', 'Concussion Awareness'),
            (r'safesport', 'SafeSport'),
            (r'sudden cardiac arrest', 'Sudden Cardiac Arrest'),
            (r'summary.*laws.*game', 'Summary of Laws of Game'),
            (r'livescan', 'Background Check (LiveScan)')
        ]
        
        for pattern, prereq_name in prereq_patterns:
            if re.search(pattern, description_lower):
                prerequisites.append(prereq_name)
        
        # Add default prerequisites based on course type
        if course_type in self.course_prerequisites:
            default_prereqs = self.course_prerequisites[course_type].get('required_certs', [])
            for cert in default_prereqs:
                cert_name = cert.replace(' Verified', '').replace('AYSOs ', '')
                if cert_name not in prerequisites:
                    prerequisites.append(cert_name)
        
        return prerequisites
    
    def load_volunteer_data(self, volunteer_files: Dict[str, str]):
        """Load volunteer data from Excel files"""
        logger.info("Loading volunteer data from Excel files...")
        
        try:
            # Load compliance data (main source for certifications)
            if 'compliance' in volunteer_files and Path(volunteer_files['compliance']).exists():
                self.compliance_data = pd.read_excel(volunteer_files['compliance'])
                logger.info(f"Loaded {len(self.compliance_data)} compliance records")
            
            # Load volunteer details (contact info, addresses)
            if 'volunteer_details' in volunteer_files and Path(volunteer_files['volunteer_details']).exists():
                self.volunteer_data = pd.read_excel(volunteer_files['volunteer_details'])
                logger.info(f"Loaded {len(self.volunteer_data)} volunteer detail records")
            
            # Load enrollment data (current registrations)
            if 'enrollment' in volunteer_files and Path(volunteer_files['enrollment']).exists():
                self.enrollment_data = pd.read_excel(volunteer_files['enrollment'])
                logger.info(f"Loaded {len(self.enrollment_data)} enrollment records")
                
        except Exception as e:
            logger.error(f"Error loading volunteer data: {e}")
            raise
 
    def _extract_age_group(self, division_name: str) -> str:
        """Extract age group from division name - simplified version"""
        if not division_name:
            return ""
    
        import re
        division_upper = str(division_name).upper()
    
        # Look for age patterns
        match = re.search(r'(\d{1,2}U|U\d{1,2})', division_upper)
        if match:
            age_group = match.group(1)
            # Convert U14 format to 14U format
            if age_group.startswith('U'):
                return f"{age_group[1:]}U"
            return age_group
    
        return ""        

    def determine_volunteer_requirements(self, volunteer: pd.Series) -> Dict[str, Any]:
        """
        Determine what certifications/training a volunteer needs based on their current role/division
        Instead of course requirements, this is volunteer-specific requirements
        """
        volunteer_role = str(volunteer.get('Volunteer Role', '')).lower()
        volunteer_division = str(volunteer.get('Division Name', ''))
        current_coaching_level = str(volunteer.get('Coaching License Level', ''))
    
        # Extract age group from division (06U, 10U, 12U, etc.)
        division_age = self._extract_age_group(volunteer_division)
    
        requirements = {
            'needed_certs': [],
            'needed_coaching_level': None,
            'needed_referee_level': None,
            'target_courses': [],
            'priority_level': 'low'
        }
    
        # Determine what coaching level they need based on their division
        needed_level = 'undefined'
        if 'coach' in volunteer_role:
            if division_age in ['06U', '07U', '08U', '6U', '7U', '8U']:
                needed_level = '6U/8U Coach'
            elif division_age == '10U':
                needed_level = '10U Coach'
            elif division_age == '12U':
                needed_level = '12U Coach'
            elif division_age in ['14U', '16U', '19U']:
                needed_level = '14U/Intermediate Coach'
        
            # Check if they already have required level
            if needed_level not in current_coaching_level:
                requirements['needed_coaching_level'] = needed_level
                requirements['target_courses'].append(needed_level)
                requirements['priority_level'] = 'high'  # Missing required level
    
        # Add referee training if they're also a referee
        if 'referee' in volunteer_role:
            if 'Regional' not in str(volunteer.get('Referee License Level', '')):
                requirements['needed_referee_level'] = 'Regional Referee'
                requirements['target_courses'].append('Regional Referee')
    
        return requirements

    def match_volunteers_to_courses(self) -> Dict[str, List[Dict[str, Any]]]:
        """Match volunteers to courses they actually need"""
    
        matches = {}
    
        for _, volunteer in self.compliance_data.iterrows():
        
            # get volunteer_name
            volunteer_name = f"{volunteer.get('Volunteer First Name', '')} {volunteer.get('Volunteer Last Name', '')}".strip()

            # NEW: Determine what THIS volunteer needs
            volunteer_requirements = self.determine_volunteer_requirements(volunteer)
        
            volunteer_matches = []
        
            # Check each available event
            for event in self.events:
                course_type = event['course_type']
            
                # NEW: Only consider events that provide what this volunteer needs
                if course_type in volunteer_requirements['target_courses']:
                
                    # Use existing evaluation but with volunteer-specific requirements
                    course_requirements = self.course_prerequisites[course_type]
                    match_result = self._evaluate_volunteer_match(
                        volunteer, 
                        course_requirements, 
                        event
                    )

                    # match_result = self._evaluate_volunteer_match(
                    #     volunteer, 
                    #     course_requirements, 
                    #     event,
                    #     volunteer_requirements  # NEW: Pass volunteer needs
                    # )
                
                    if match_result['qualifies']:
                        volunteer_matches.append({
                            'event': event,
                            'course_type': course_type,
                            'volunteer_needs': volunteer_requirements,  # NEW: What they need
                            'match_score': match_result['score'],
                            'why_needed': self._explain_why_needed(volunteer, course_type)  # NEW
                        })
        
            if volunteer_matches:
                matches[volunteer_name] = volunteer_matches
    
        return matches

    def _explain_why_needed(self, volunteer: pd.Series, course_type: str) -> str:
        """Explain why this volunteer needs this specific course"""
    
        volunteer_role = volunteer.get('Volunteer Role', '')
        volunteer_division = volunteer.get('Division Name', '')
        current_level = volunteer.get('Coaching License Level', '')
    
        if course_type == '06U Coach' and '06U' in volunteer_division:
            return f"Required certification for {volunteer_role} in {volunteer_division}"
        elif course_type == '10U Coach' and not current_level:
            return f"Missing required coaching certification for {volunteer_role}"
        elif 'Referee' in course_type and 'referee' in volunteer_role.lower():
            return f"Required referee certification for {volunteer_role}"
    
        return f"Recommended training for {volunteer_role}"
    
    def _evaluate_volunteer_match(self, volunteer: pd.Series, requirements: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate how well a volunteer matches a course"""
        score = 0.0
        reasons = []
        missing = []
        
        # Check role compatibility (35 points)
        volunteer_role = str(volunteer.get('Volunteer Role', '')).lower()
        target_roles = [role.lower() for role in requirements.get('target_roles', [])]
        
        if any(role.replace(' ', '') in volunteer_role.replace(' ', '') for role in target_roles):
            score += 35
            reasons.append(f"Role match: {volunteer.get('Volunteer Role', '')}")
        else:
            missing.append(f"Role mismatch (need: {', '.join(requirements.get('target_roles', []))})")
        
        # Check division compatibility (25 points)
        volunteer_division = str(volunteer.get('Division Name', ''))
        target_divisions = requirements.get('target_divisions', [])
        
        if 'all' in target_divisions or any(div in volunteer_division for div in target_divisions):
            score += 25
            reasons.append(f"Division match: {volunteer_division}")
        else:
            if target_divisions and 'all' not in target_divisions:
                missing.append(f"Division mismatch (need: {', '.join(target_divisions)})")
        
        # Check required certifications (30 points)
        required_certs = requirements.get('required_certs', [])
        cert_score = 0
        cert_details = []
        
        for cert in required_certs:
            cert_status = volunteer.get(cert, 'N')
            if cert_status == 'Y':
                cert_score += 1
                cert_name = cert.replace(' Verified', '').replace('AYSOs ', '')
                cert_details.append(cert_name)
            else:
                cert_name = cert.replace(' Verified', '').replace('AYSOs ', '')
                missing.append(f"Missing: {cert_name}")
        
        if required_certs:
            cert_percentage = cert_score / len(required_certs)
            score += cert_percentage * 30
            if cert_details:
                reasons.append(f"Certifications: {', '.join(cert_details)} ({cert_score}/{len(required_certs)})")
        
        # Check coaching level prerequisites (if applicable)
        required_coaching_level = requirements.get('coaching_level_required')
        if required_coaching_level:
            current_level = str(volunteer.get('Coaching License Level', ''))
            if required_coaching_level in current_level:
                score += 10
                reasons.append(f"Has required coaching level: {current_level}")
            else:
                missing.append(f"Missing coaching level: {required_coaching_level}")
        
        # Bonus factors
        if volunteer.get('Risk Status') == 'Green':
            score += 8
            reasons.append("Green risk status")
        
        if volunteer.get('Is Rostered to Team') == 'Y':
            score += 2
            reasons.append("Currently rostered")
        
        # Determine if volunteer qualifies (threshold: 60 points)
        qualifies = score >= 60 and len(missing) <= 2
        
        return {
            'qualifies': qualifies,
            'score': round(score, 1),
            'reasons': reasons,
            'missing': missing
        }
    
    def _get_priority_level(self, score: float) -> str:
        """Get priority level based on match score"""
        if score >= 90:
            return 'High'
        elif score >= 75:
            return 'Medium'
        elif score >= 60:
            return 'Low'
        else:
            return 'Not Recommended'
    
    def generate_enrollment_report(self, matches: Dict[str, List[Dict[str, Any]]]) -> pd.DataFrame:
        """Generate comprehensive enrollment report"""
        logger.info("Generating enrollment report...")
        
        report_data = []
        
        for volunteer_name, volunteer_matches in matches.items():
            # Get volunteer details from compliance data
            volunteer_row = self.compliance_data[
                (self.compliance_data['Volunteer First Name'] + ' ' + 
                 self.compliance_data['Volunteer Last Name']) == volunteer_name
            ]
            
            if not volunteer_row.empty:
                volunteer_info = volunteer_row.iloc[0]
                
                for match in volunteer_matches:
                    event = match['event']
                    
                    # Extract session information for display
                    session_info = "TBD"
                    if event['sessions']:
                        session_data = event['sessions'][0]
                        session_parts = []
                        if 'date' in session_data:
                            session_parts.append(session_data['date'])
                        if 'time' in session_data:
                            session_parts.append(session_data['time'])
                        if 'location' in session_data:
                            session_parts.append(session_data['location'])
                        session_info = ' | '.join(session_parts) if session_parts else session_info
                    
                    report_data.append({
                        'Volunteer Name': volunteer_name,
                        'Email': volunteer_info.get('Volunteer Email Address', ''),
                        'Phone': volunteer_info.get('Volunteer Cellphone', volunteer_info.get('Volunteer Telephone', '')),
                        'Current Role': volunteer_info.get('Volunteer Role', ''),
                        'Current Division': volunteer_info.get('Division Name', ''),
                        'Risk Status': volunteer_info.get('Risk Status', ''),
                        'Recommended Course': match['course_type'],
                        'Event Title': event['title'],
                        'Session Info': session_info,
                        'Match Score': match['match_score'],
                        'Priority': match.get('volunteer_needs', {}).get('priority_level'),
                        'Qualification Reasons': '; '.join(match['why_needed']),
                        'Missing Requirements': '; '.join(match.get('volunteer_needs', {}).get('needed_certs')) if match.get('volunteer_needs', {}).get('needed_certs') else 'None',
                        'Contact Name': event.get('contact', {}).get('name', ''),
                        'Contact Email': event.get('contact', {}).get('email', ''),
                        'Contact Phone': event.get('contact', {}).get('phone', ''),
                        'Event ID': event['event_id'],
                        'Data Event ID': event.get('enroll_info', {}).get('data_event', ''),
                        'Data Session ID': event.get('enroll_info', {}).get('data_session', '')
                    })
        
        return pd.DataFrame(report_data)
    
    def save_events_to_json(self, filename: str = None) -> str:
        """Save scraped events to JSON file"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"etrainu_events_{timestamp}.json"
        
        filepath = self.data_dir / filename
        
        # Prepare events for JSON serialization
        json_events = []
        for event in self.events:
            # Create a copy without the raw HTML
            event_copy = event.copy()
            event_copy.pop('raw_html', None)  # Remove raw HTML for cleaner JSON
            json_events.append(event_copy)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(json_events, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"Saved {len(json_events)} events to {filepath}")
        return str(filepath)
    
    def save_matches_to_json(self, matches: Dict[str, List[Dict[str, Any]]], filename: str = None) -> str:
        """Save volunteer-course matches to JSON file"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"volunteer_course_matches_{timestamp}.json"
        
        filepath = self.data_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(matches, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"Saved matches for {len(matches)} volunteers to {filepath}")
        return str(filepath)


class ETrainUAutomationModule:
    """Integration module for ETrainU with SportsConnectAutomation"""
    
    def __init__(self, sports_connect_automation, config=None):
        """Initialize with SportsConnectAutomation instance"""
        self.automation = sports_connect_automation
        self.config = config
        self.scraper = ETrainUEventScraper(config.get('download_dir', 'data') if config else 'data')
        self.driver = sports_connect_automation.driver if sports_connect_automation else None
        self.interactor = ElementInteractor(self.driver) if self.driver else None
        
        # Initialize ETrainU manager for live site interaction
        self.etrainu_manager = None
        if self.driver and sports_connect_automation:
            try:
                from automation.etrainu_manager import ETrainUManager
                self.etrainu_manager = ETrainUManager(
                    driver=self.driver,
                    config=config,
                    already_logged_in=True
                )
            except ImportError:
                logger.warning("ETrainU manager not available - live scraping disabled")
    
    def initialize_from_files(self, html_file: str, volunteer_files: Dict[str, str], use_live_scraping: bool = None):
        """
        Initialize scraper with HTML file and volunteer data
        
        Args:
            html_file: Path to static HTML file
            volunteer_files: Dictionary of volunteer data file paths
            use_live_scraping: Whether to scrape live events from ETrainU site
                              If None, will check config for preference
        """
        logger.info("Initializing ETrainU automation module...")
        
        # Determine if we should use live scraping
        if use_live_scraping is None:
            # Check configuration for preference
            etrainu_config = self.config.get('etrainu_config', {}) if self.config else {}
            use_live_scraping = etrainu_config.get('prefer_live_scraping', False)
            
            # Also check if live scraping is explicitly enabled
            if not use_live_scraping:
                use_live_scraping = etrainu_config.get('scraping', {}).get('prefer_live_scraping', False)
        
        # Only attempt live scraping if we have the manager
        if use_live_scraping and not self.etrainu_manager:
            logger.warning("Live scraping requested but ETrainU manager not available - using static HTML")
            use_live_scraping = False
        
        if use_live_scraping and self.etrainu_manager:
            # Use live scraping instead of static HTML
            logger.info("Using live ETrainU site scraping...")
            
            if self.etrainu_manager.navigate_to_etrainu():
                events = self.etrainu_manager.scrape_live_events()
                self.scraper.events = events
                logger.info(f"Scraped {len(events)} live events from ETrainU")
                
                # Optionally save the live events for backup
                if self.config and self.config.get('etrainu_config', {}).get('scraping', {}).get('save_scraped_events', True):
                    events_file = self.etrainu_manager.save_events_to_json()
                    logger.info(f"Saved live events to: {events_file}")
            else:
                logger.error("Failed to access ETrainU site - falling back to HTML file")
                use_live_scraping = False
        
        if not use_live_scraping:
            # Use static HTML file
            html_path = Path(html_file)
            if not html_path.exists():
                if self.config and self.config.get('etrainu_config', {}).get('scraping', {}).get('fallback_to_html', True):
                    logger.error(f"HTML file not found: {html_file}")
                raise FileNotFoundError(f"HTML file not found: {html_file}")
            
            events_count = len(self.scraper.parse_html_file(str(html_path)))
            logger.info(f"Parsed {events_count} events from static HTML file: {html_file}")
        
        # Load volunteer data using enhanced method (supports Google Sheets)
        logger.info("Loading volunteer data...")
        try:
            from automation.google_sheets_helper import load_volunteer_data_enhanced
            load_volunteer_data_enhanced(self.scraper, volunteer_files, self.config)
        except ImportError:
            logger.warning("Google Sheets helper not available, using standard file loading")
            # Validate volunteer files exist if using local files
            missing_files = []
            for key, filepath in volunteer_files.items():
                if not Path(filepath).exists():
                    missing_files.append(f"{key}: {filepath}")
            
            if missing_files:
                logger.warning(f"Missing volunteer files: {', '.join(missing_files)}")
            
            # Use standard loading
            self.scraper.load_volunteer_data(volunteer_files)
        
        final_event_count = len(self.scraper.events)
        data_source = "live ETrainU site" if use_live_scraping and final_event_count > 0 else "static HTML file"
        logger.info(f"ETrainU module initialized successfully with {final_event_count} events from {data_source}")
        
        # Log volunteer data summary
        if hasattr(self.scraper, 'compliance_data') and self.scraper.compliance_data is not None:
            logger.info(f"Loaded {len(self.scraper.compliance_data)} volunteer compliance records")
        if hasattr(self.scraper, 'volunteer_data') and self.scraper.volunteer_data is not None:
            logger.info(f"Loaded {len(self.scraper.volunteer_data)} volunteer detail records")
        if hasattr(self.scraper, 'enrollment_data') and self.scraper.enrollment_data is not None:
            logger.info(f"Loaded {len(self.scraper.enrollment_data)} enrollment records")

    
    def get_enrollment_recommendations(self) -> Dict[str, Any]:
        """Get comprehensive enrollment recommendations"""
        logger.info("Generating enrollment recommendations...")
        
        # Generate volunteer-course matches
        matches = self.scraper.match_volunteers_to_courses()
        
        # Create detailed report
        report_df = self.scraper.generate_enrollment_report(matches)
        
        # Save data files
        events_file = self.scraper.save_events_to_json()
        matches_file = self.scraper.save_matches_to_json(matches)
        
        # Calculate summary statistics
        summary_stats = self._calculate_summary_statistics(matches, report_df)
        
        return {
            'matches': matches,
            'report_dataframe': report_df,
            'events_file': events_file,
            'matches_file': matches_file,
            'summary_statistics': summary_stats,
            'total_volunteers_matched': len(matches),
            'total_events': len(self.scraper.events),
            'total_recommendations': len(report_df)
        }
    
    def _calculate_summary_statistics(self, matches: Dict[str, List], report_df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate summary statistics for reporting"""
        stats = {}
        
        # Course demand
        if not report_df.empty:
            course_demand = report_df['Recommended Course'].value_counts().to_dict()
            stats['course_demand'] = course_demand
            
            # Priority distribution
            priority_dist = report_df['Priority'].value_counts().to_dict()
            stats['priority_distribution'] = priority_dist
            
            # Average match score
            stats['average_match_score'] = round(report_df['Match Score'].mean(), 2)
            
            # Certification gaps
            missing_certs = []
            for _, row in report_df.iterrows():
                if row['Missing Requirements'] and row['Missing Requirements'] != 'None':
                    missing_certs.extend([req.strip() for req in row['Missing Requirements'].split(';')])
            
            cert_gaps = pd.Series(missing_certs).value_counts().head(5).to_dict()
            stats['top_certification_gaps'] = cert_gaps
        
        return stats
    
    def auto_enroll_volunteers(self, recommendations: Dict[str, Any], 
                             max_enrollments: int = 10,
                             priority_filter: str = 'High',
                             use_live_enrollment: bool = False) -> List[Dict[str, Any]]:
        """
        Automatically enroll volunteers in recommended courses
        
        Args:
            recommendations: Enrollment recommendations from get_enrollment_recommendations()
            max_enrollments: Maximum number of enrollments to perform
            priority_filter: Priority level to filter by ('High', 'Medium', 'Low', 'All')
            use_live_enrollment: Whether to perform actual enrollments on live site
        """
        if not self.driver:
            logger.error("No WebDriver available for auto-enrollment")
            return []
        
        if use_live_enrollment and not self.etrainu_manager:
            logger.error("Live enrollment requested but ETrainU manager not available")
            return []
        
        logger.info(f"Starting auto-enrollment (max: {max_enrollments}, priority: {priority_filter}, live: {use_live_enrollment})...")
        
        report_df = recommendations['report_dataframe']
        
        # Filter by priority and sort by match score
        if priority_filter != 'All':
            filtered_df = report_df[report_df['Priority'] == priority_filter]
        else:
            filtered_df = report_df
        
        sorted_recommendations = filtered_df.sort_values('Match Score', ascending=False)
        
        enrollment_results = []
        enrolled_count = 0
        
        for _, recommendation in sorted_recommendations.iterrows():
            if enrolled_count >= max_enrollments:
                break
            
            try:
                if use_live_enrollment:
                    # Perform actual enrollment on live site
                    result = self._perform_live_enrollment(recommendation)
                else:
                    # Simulate enrollment (placeholder)
                    result = self._perform_enrollment(recommendation)
                
                enrollment_results.append(result)
                
                if result['success']:
                    enrolled_count += 1
                    logger.info(f"Enrolled {recommendation['Volunteer Name']} in {recommendation['Recommended Course']}")
                else:
                    logger.warning(f"Failed to enroll {recommendation['Volunteer Name']}: {result.get('error', 'Unknown error')}")
                
                # Add delay between enrollments
                time.sleep(3)
                
            except Exception as e:
                logger.error(f"Error enrolling {recommendation['Volunteer Name']}: {e}")
                enrollment_results.append({
                    'volunteer_name': recommendation['Volunteer Name'],
                    'course': recommendation['Recommended Course'],
                    'success': False,
                    'error': str(e)
                })
        
        logger.info(f"Auto-enrollment complete: {enrolled_count}/{len(enrollment_results)} successful")
        return enrollment_results
    
    def _perform_live_enrollment(self, recommendation: pd.Series) -> Dict[str, Any]:
        """Perform actual enrollment using ETrainU manager"""
        try:
            # Prepare volunteer info
            volunteer_info = {
                'name': recommendation['Volunteer Name'],
                'email': recommendation['Email'],
                'phone': recommendation['Phone']
            }
            
            # Find matching event in scraped events
            event_title = recommendation['Event Title']
            matching_event = None
            
            for event in self.scraper.events:
                if event['title'] == event_title:
                    matching_event = event
                    break
            
            if not matching_event:
                return {
                    'volunteer_name': recommendation['Volunteer Name'],
                    'course': recommendation['Recommended Course'],
                    'success': False,
                    'error': 'Matching event not found'
                }
            
            # Perform enrollment using ETrainU manager
            result = self.etrainu_manager.auto_enroll_volunteer(volunteer_info, matching_event)
            
            # Add recommendation context to result
            result['recommendation_score'] = recommendation['Match Score']
            result['recommendation_priority'] = recommendation['Priority']
            
            return result
            
        except Exception as e:
            return {
                'volunteer_name': recommendation['Volunteer Name'],
                'course': recommendation['Recommended Course'],
                'success': False,
                'error': f'Live enrollment error: {str(e)}'
            }
    
    def _perform_enrollment(self, recommendation: pd.Series) -> Dict[str, Any]:
        """Perform actual enrollment for a volunteer"""
        # This is a placeholder for the actual enrollment logic
        # You would implement the Selenium automation to:
        # 1. Navigate to the enrollment page
        # 2. Fill in volunteer information
        # 3. Select the course/event
        # 4. Submit the enrollment
        
        return {
            'volunteer_name': recommendation['Volunteer Name'],
            'course': recommendation['Recommended Course'],
            'event_title': recommendation['Event Title'],
            'success': False,  # Set to True when implemented
            'message': 'Auto-enrollment functionality pending implementation',
            'enrollment_url': 'https://etrainu.com/enrollment',  # Would be actual URL
            'data_event_id': recommendation.get('Data Event ID', ''),
            'data_session_id': recommendation.get('Data Session ID', '')
        }
    
    @classmethod
    def create_from_automation(cls, automation_instance, config=None):
        """Factory method to create ETrainUAutomationModule from existing SportsConnectAutomation"""
        return cls(automation_instance, config)


# Integration helper functions
def quick_run_etrainu_analysis(html_file: str, data_dir: str = "data", config=None) -> Dict[str, Any]:
    """Quick function to run ETrainU analysis without full automation setup"""
    
    # Initialize scraper
    scraper = ETrainUEventScraper(data_dir)
    
    # Parse HTML
    events = scraper.parse_html_file(html_file)
    
    # Load volunteer data
    volunteer_files = {
        'compliance': f"{data_dir}/2025 Volunteer Compliance.xlsx",
        'volunteer_details': f"{data_dir}/Volunteer_Details 63.xlsx", 
        'enrollment': f"{data_dir}/Enrollment_Details.xlsx"
    }
    
    # Use enhanced loading if config provided
    if config:
        try:
            from automation.google_sheets_helper import load_volunteer_data_enhanced
            load_volunteer_data_enhanced(scraper, volunteer_files, config)
        except ImportError:
            scraper.load_volunteer_data(volunteer_files)
    else:
        scraper.load_volunteer_data(volunteer_files)
    
    # Generate matches
    matches = scraper.match_volunteers_to_courses()
    
    # Create report
    report_df = scraper.generate_enrollment_report(matches)
    
    # Save files
    events_file = scraper.save_events_to_json()
    matches_file = scraper.save_matches_to_json(matches)
    
    return {
        'events': events,
        'matches': matches,
        'report': report_df,
        'files': {
            'events': events_file,
            'matches': matches_file
        },
        'summary': {
            'total_events': len(events),
            'total_volunteers': len(matches),
            'total_recommendations': len(report_df)
        }
    }