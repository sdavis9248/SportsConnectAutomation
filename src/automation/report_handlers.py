"""
Report-specific handlers for Sports Connect Automation
Updated to include Sports Affinity reports and optimized configuration
"""
import logging
from enum import Enum
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

class ReportType(Enum):
    """Enum for different report types"""
    # Sports Connect Reports
    TEAM_DETAIL = "Team Detail"
    VOLUNTEER_DETAIL = "Volunteer Detail" 
    PLAYER_DETAIL = "Player Detail"
    ENROLLMENT_SUMMARY = "Enrollment Summary"
    DIVISION_DETAILS = "Division Details"
    OPEN_ORDERS = "Open Orders Line Item"
    WAITLIST_MANAGEMENT = "Waitlist Management"
    WAITLIST_REPORT = "Waitlist Report"
    SCHEDULE_MATCH = "Schedule Match Report"
    
    # Sports Affinity Reports
    ADMIN_CREDENTIALS = "Admin Credentials"
    ADMIN_DETAILS = "Admin Details"
    MEDICAL_FORMS = "Medical Forms"

    # PlayMetrics Reports
    PM_REGISTRATION_RESPONSES = "PM Registration Responses"
    PM_VOLUNTEERS = "PM Volunteers"
    PM_COACHING_REQUESTS = "PM Coaching Requests"

class SiteType(Enum):
    """Enum for different site types"""
    SPORTS_CONNECT = "sports_connect"
    SPORTS_AFFINITY = "sports_affinity"
    PLAYMETRICS = "playmetrics"

@dataclass
class ReportConfig:
    """Configuration for a specific report"""
    name: str
    url: str
    export_filename_prefix: str
    wait_time: int = 10
    is_saved_report: bool = False
    report_id: Optional[str] = None
    site_type: str = "sports_connect"  # "sports_connect" or "sports_affinity"
    description: Optional[str] = None
    requires_season: bool = True
    post_process_macro: Optional[str] = None

class ReportHandlers:
    """Handles report-specific logic and configurations"""
    
    @staticmethod
    def get_report_configs(base_url: str, org_id: str) -> Dict[ReportType, ReportConfig]:
        """Get configurations for all reports"""
        return {
            # Sports Connect Reports
            ReportType.TEAM_DETAIL: ReportConfig(
                name="Team Detail Report",
                url=f"{base_url}/{org_id}/admin/static/TeamDetailReportsNewRegistration",
                export_filename_prefix="Team_Detail",
                wait_time=20,
                site_type=SiteType.SPORTS_CONNECT.value,
                description="Detailed team information including players and coaches",
                requires_season=True
            ),
            ReportType.VOLUNTEER_DETAIL: ReportConfig(
                name="Volunteer Detail Report",
                url=f"{base_url}/{org_id}/admin/saved/173209",
                export_filename_prefix="Volunteer_Details",
                is_saved_report=True,
                report_id="173209",
                wait_time=90,
                site_type=SiteType.SPORTS_CONNECT.value,
                description="Complete volunteer information and certifications",
                requires_season=False
            ),
            ReportType.PLAYER_DETAIL: ReportConfig(
                name="Player Detail Report",
                url=f"{base_url}/{org_id}/admin/saved/65583",
                export_filename_prefix="Enrollment_Details",
                is_saved_report=True,
                report_id="65583",
                wait_time=12,
                site_type=SiteType.SPORTS_CONNECT.value,
                description="Detailed player registration and status information",
                requires_season=True
            ),
            ReportType.ENROLLMENT_SUMMARY: ReportConfig(
                name="Enrollment Summary Report",
                url=f"{base_url}/{org_id}/admin/program-enrollment-summary",
                export_filename_prefix="Enrollment_Summary_Report",
                wait_time=10,
                site_type=SiteType.SPORTS_CONNECT.value,
                description="Program enrollment statistics and division summaries",
                requires_season=True,
                # post_process_macro="enrollment_summary"
            ),
            ReportType.DIVISION_DETAILS: ReportConfig(
                name="Division Details Report",
                url=f"{base_url}/{org_id}/admin/saved/173208",
                export_filename_prefix="Division_Details",
                is_saved_report=True,
                report_id="173208",
                wait_time=5,
                site_type=SiteType.SPORTS_CONNECT.value,
                description="Division-specific enrollment and team information",
                requires_season=True
            ),
            ReportType.OPEN_ORDERS: ReportConfig(
                name="Open Orders Line Item Report",
                url=f"{base_url}/{org_id}/admin/saved/110470",
                export_filename_prefix="Open_Orders_Line_Item",
                is_saved_report=True,
                report_id="110470",
                wait_time=20,
                site_type=SiteType.SPORTS_CONNECT.value,
                description="Outstanding payment orders and transaction details",
                requires_season=False
            ),
            ReportType.WAITLIST_MANAGEMENT: ReportConfig(
                name="Waitlist Management",
                url=f"{base_url}/{org_id}/admin/program-enrollment-summary",
                export_filename_prefix="WaitlistResults",
                wait_time=15,
                site_type=SiteType.SPORTS_CONNECT.value,
                description="Manage waitlist participants across all divisions",
                requires_season=True
            ),
            ReportType.WAITLIST_REPORT: ReportConfig(
                name="Waitlist Report",
                url=f"{base_url}/{org_id}/admin/saved/111258",
                export_filename_prefix="Waitlist",
                is_saved_report=True,
                report_id="111258",
                wait_time=10,
                site_type=SiteType.SPORTS_CONNECT.value,
                description="Complete waitlist participant information for notifications",
                requires_season=False
            ),
            ReportType.SCHEDULE_MATCH: ReportConfig(
                name="Schedule Match",
                url=f"{base_url}/{org_id}/admin/static/ScheduleMatchNewRegistration",
                export_filename_prefix="ScheduleMatch",
                is_saved_report=True,
                wait_time=10,
                site_type=SiteType.SPORTS_CONNECT.value,
                description="Schedule match for generating game cards",
                requires_season=False
            ),
            # Sports Affinity Reports
            ReportType.ADMIN_CREDENTIALS: ReportConfig(
                name="Admin Credentials Report",
                url="https://ayso.sportsaffinity.com/foundation/login.aspx",
                export_filename_prefix="AdminCredentialsStatusDynamic",
                wait_time=15,
                site_type=SiteType.SPORTS_AFFINITY.value,
                description="Administrator certification and credential status",
                requires_season=False
            ),
            ReportType.ADMIN_DETAILS: ReportConfig(
                name="Admin Details Report",
                url="https://ayso.sportsaffinity.com/foundation/login.aspx",
                export_filename_prefix="teamAdminDetail",
                wait_time=15,
                site_type=SiteType.SPORTS_AFFINITY.value,
                description="Complete administrator contact and role information",
                requires_season=False,
                post_process_macro="admin_detail"
            ),
            
            ReportType.MEDICAL_FORMS: ReportConfig(
                name="Medical Forms Download",
                url="https://ayso.sportsaffinity.com/foundation/login.aspx",
                export_filename_prefix="MedicalForms",
                wait_time=20,
                site_type=SiteType.SPORTS_AFFINITY.value,
                description="Download player medical forms for all teams in specified divisions",
                requires_season=True
            ),
            
            # PlayMetrics Reports
            ReportType.PM_REGISTRATION_RESPONSES: ReportConfig(
                name="PM Registration Responses",
                url="",  # Navigated via UI, not direct URL
                export_filename_prefix="registration-responses",
                wait_time=15,
                site_type=SiteType.PLAYMETRICS.value,
                description="Player registration data, parent info, volunteer interest, question answers",
                requires_season=False
            ),
            ReportType.PM_VOLUNTEERS: ReportConfig(
                name="PM Volunteers",
                url="",
                export_filename_prefix="volunteers",
                wait_time=10,
                site_type=SiteType.PLAYMETRICS.value,
                description="Volunteer signup data from PlayMetrics programs",
                requires_season=False
            ),
            ReportType.PM_COACHING_REQUESTS: ReportConfig(
                name="PM Coaching Requests",
                url="",
                export_filename_prefix="coaching-requests",
                wait_time=10,
                site_type=SiteType.PLAYMETRICS.value,
                description="Coaching request responses from PlayMetrics leagues",
                requires_season=False
            )
        }
    
    @staticmethod
    def get_report_by_name(report_name: str) -> Optional[ReportType]:
        """Get ReportType by name (case insensitive)"""
        name_lower = report_name.lower().replace('_', ' ')
        for report_type in ReportType:
            if report_type.value.lower() == name_lower:
                return report_type
            if report_type.name.lower() == name_lower:
                return report_type
        return None
    
    @staticmethod
    def get_export_filename_pattern(report_type: ReportType) -> str:
        """Get the expected filename pattern for a report"""
        patterns = {
            # Sports Connect patterns
            ReportType.TEAM_DETAIL: "TeamDetail*.xlsx",
            ReportType.VOLUNTEER_DETAIL: "*Volunteer*.xlsx",
            ReportType.PLAYER_DETAIL: "*ReportWizard*.xlsx",
            ReportType.ENROLLMENT_SUMMARY: "*Enrollment*.xlsx",
            ReportType.DIVISION_DETAILS: "*Division*.xlsx",
            ReportType.OPEN_ORDERS: "*Order*.xlsx",
            ReportType.WAITLIST_MANAGEMENT: "*Waitlist*.json",
            ReportType.WAITLIST_REPORT: "Waitlist*.xlsx",
            ReportType.SCHEDULE_MATCH: "Schedule_Match*.xlsx",
            
            # Sports Affinity patterns
            ReportType.ADMIN_CREDENTIALS: "*Admin*Credential*.xlsx",
            ReportType.ADMIN_DETAILS: "*Admin*Detail*.xlsx",
            ReportType.MEDICAL_FORMS: "*Medical*Forms*.pdf",
            
            # PlayMetrics patterns
            ReportType.PM_REGISTRATION_RESPONSES: "registration-responses*.csv",
            ReportType.PM_VOLUNTEERS: "volunteers*.csv",
            ReportType.PM_COACHING_REQUESTS: "*coaching-requests*.csv"
        }
        return patterns.get(report_type, "*.xlsx")
    
    @staticmethod
    def get_sports_connect_reports() -> list:
        """Get list of Sports Connect reports"""
        configs = ReportHandlers.get_report_configs("", "")
        return [report for report in ReportType 
                if configs[report].site_type == SiteType.SPORTS_CONNECT.value]
    
    @staticmethod
    def get_sports_affinity_reports() -> list:
        """Get list of Sports Affinity reports"""
        configs = ReportHandlers.get_report_configs("", "")
        return [report for report in ReportType 
                if configs[report].site_type == SiteType.SPORTS_AFFINITY.value]
    
    @staticmethod
    def get_playmetrics_reports() -> list:
        """Get list of PlayMetrics reports"""
        configs = ReportHandlers.get_report_configs("", "")
        return [report for report in ReportType 
                if configs[report].site_type == SiteType.PLAYMETRICS.value]
    
    @staticmethod
    def get_reports_requiring_season() -> list:
        """Get list of reports that require season selection"""
        configs = ReportHandlers.get_report_configs("", "")
        return [report for report in ReportType 
                if configs[report].requires_season]
    
    @staticmethod
    def get_reports_with_macros() -> Dict[ReportType, str]:
        """Get mapping of reports to their post-processing macros"""
        configs = ReportHandlers.get_report_configs("", "")
        return {report: config.post_process_macro 
                for report, config in configs.items() 
                if config.post_process_macro}
    
    @staticmethod
    def get_report_description(report_type: ReportType) -> str:
        """Get description for a report type"""
        configs = ReportHandlers.get_report_configs("", "")
        return configs.get(report_type, ReportConfig("", "", "")).description or "No description available"
    
    @staticmethod
    def list_all_reports() -> Dict[str, Dict]:
        """Get a comprehensive list of all reports with their details"""
        configs = ReportHandlers.get_report_configs("", "")
        
        report_list = {}
        for report_type, config in configs.items():
            report_list[report_type.name] = {
                "display_name": config.name,
                "site_type": config.site_type,
                "description": config.description,
                "requires_season": config.requires_season,
                "is_saved_report": config.is_saved_report,
                "wait_time": config.wait_time,
                "has_macro": config.post_process_macro is not None,
                "macro_name": config.post_process_macro
            }
        
        return report_list
    
    @staticmethod
    def validate_report_name(report_name: str) -> tuple:
        """
        Validate a report name and return status
        
        Returns:
            (is_valid: bool, report_type: ReportType or None, message: str)
        """
        report_type = ReportHandlers.get_report_by_name(report_name)
        
        if report_type is None:
            available_reports = [rt.name for rt in ReportType]
            message = f"Invalid report name '{report_name}'. Available reports: {', '.join(available_reports)}"
            return False, None, message
        
        return True, report_type, f"Valid report: {report_type.value}"
    
    @staticmethod
    def get_default_enabled_reports() -> Dict[str, bool]:
        """Get default enabled status for all reports"""
        return {
            # Sports Connect reports - enabled by default
            "team_detail": True,
            "volunteer_detail": True,
            "player_detail": True,
            "enrollment_summary": True,
            "division_details": True,
            "open_orders": True,
            "waitlist_management": False,  # Disabled by default (operational)
            "waitlist_report": False,  # Disabled by default (used for notifications)
            "schedule_match": True,
            
            # Sports Affinity reports - enabled by default
            "admin_credentials": True,
            "admin_details": True,
            "medical_forms": False,  # Disabled by default (bulk operation)
            
            # PlayMetrics reports - disabled by default (separate login)
            "pm_registration_responses": False,
            "pm_volunteers": False,
            "pm_coaching_requests": False
        }