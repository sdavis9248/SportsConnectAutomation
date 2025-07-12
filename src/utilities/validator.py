"""
Report validation utilities for Sports Connect Automation
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import pandas as pd

logger = logging.getLogger(__name__)


class ReportValidator:
    """Validates exported reports for data quality"""
    
    @staticmethod
    def validate_excel_file(file_path: str) -> Dict[str, Any]:
        """
        Validate an Excel file and return statistics
    
        Args:
            file_path: Path to Excel file
        
        Returns:
            Dictionary with validation results
        """
        result = {
            "valid": False,
            "error": None,
            "file_size": 0,
            "sheets": [],
            "total_rows": 0,
            "total_columns": 0,
            "warnings": []
        }
    
        if not os.path.exists(file_path):
            result["error"] = "File not found"
            return result
    
        excel_file = None
        try:
            # Get file size
            result["file_size"] = os.path.getsize(file_path)
        
            # Check minimum file size (empty Excel is ~7KB)
            if result["file_size"] < 5000:
                result["warnings"].append("File size is suspiciously small")
        
            # Read Excel file using context manager
            with pd.ExcelFile(file_path) as excel_file:
                result["sheets"] = excel_file.sheet_names
            
                # Validate each sheet
                for sheet_name in excel_file.sheet_names:
                    # Read sheet using the already open ExcelFile object
                    df = pd.read_excel(excel_file, sheet_name=sheet_name)
                    rows, cols = df.shape
                
                    result["total_rows"] += rows
                    result["total_columns"] = max(result["total_columns"], cols)
                
                    # Check for empty sheets
                    if rows == 0:
                        result["warnings"].append(f"Sheet '{sheet_name}' is empty")
                
                    # Check for missing headers
                    if cols > 0 and df.columns.tolist()[0] == 0:
                        result["warnings"].append(f"Sheet '{sheet_name}' may be missing headers")
        
            # Overall validation
            if result["total_rows"] == 0:
                result["error"] = "No data found in file"
            else:
                result["valid"] = True
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Failed to validate {file_path}: {e}")
    
        return result    

    @staticmethod
    def validate_pdf_file(file_path: str) -> Dict[str, Any]:
        """
        Validate a PDF file
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Dictionary with validation results
        """
        result = {
            "valid": False,
            "error": None,
            "file_size": 0,
            "warnings": []
        }
        
        if not os.path.exists(file_path):
            result["error"] = "File not found"
            return result
        
        try:
            # Get file size
            result["file_size"] = os.path.getsize(file_path)
            
            # Check minimum file size (empty PDF is ~1KB)
            if result["file_size"] < 1000:
                result["warnings"].append("File size is suspiciously small")
            
            # Basic PDF validation - check header
            with open(file_path, 'rb') as f:
                header = f.read(5)
                if header != b'%PDF-':
                    result["error"] = "Not a valid PDF file"
                    return result
            
            result["valid"] = True
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Failed to validate PDF {file_path}: {e}")
        
        return result
    
    @staticmethod
    def validate_json_file(file_path: str) -> Dict[str, Any]:
        """
        Validate a JSON file
        
        Args:
            file_path: Path to JSON file
            
        Returns:
            Dictionary with validation results
        """
        result = {
            "valid": False,
            "error": None,
            "file_size": 0,
            "total_rows": 0,
            "warnings": []
        }
        
        if not os.path.exists(file_path):
            result["error"] = "File not found"
            return result
        
        try:
            # Get file size
            result["file_size"] = os.path.getsize(file_path)
            
            # Try to parse JSON
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Check if it's a waitlist results file
            if isinstance(data, dict) and 'results' in data:
                result["total_rows"] = len(data.get('results', []))
            
            result["valid"] = True
            
        except json.JSONDecodeError as e:
            result["error"] = f"Invalid JSON: {e}"
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Failed to validate JSON {file_path}: {e}")
        
        return result
    
    @staticmethod
    def compare_reports(current_file: str, previous_file: str) -> Dict[str, Any]:
        """
        Compare two report files for changes
        
        Args:
            current_file: Path to current report
            previous_file: Path to previous report
            
        Returns:
            Dictionary with comparison results
        """
        comparison = {
            "files_match": False,
            "row_difference": 0,
            "column_difference": 0,
            "current_rows": 0,
            "previous_rows": 0,
            "changes": []
        }
        
        try:
            # Read both files
            current_df = pd.read_excel(current_file)
            previous_df = pd.read_excel(previous_file)
            
            comparison["current_rows"] = len(current_df)
            comparison["previous_rows"] = len(previous_df)
            comparison["row_difference"] = len(current_df) - len(previous_df)
            
            # Check columns
            current_cols = set(current_df.columns)
            previous_cols = set(previous_df.columns)
            
            if current_cols != previous_cols:
                added_cols = current_cols - previous_cols
                removed_cols = previous_cols - current_cols
                
                if added_cols:
                    comparison["changes"].append(f"Added columns: {added_cols}")
                if removed_cols:
                    comparison["changes"].append(f"Removed columns: {removed_cols}")
            
            comparison["column_difference"] = len(current_cols) - len(previous_cols)
            
            # Check if files are identical
            if comparison["row_difference"] == 0 and comparison["column_difference"] == 0:
                comparison["files_match"] = current_df.equals(previous_df)
            
        except Exception as e:
            comparison["error"] = str(e)
            logger.error(f"Failed to compare reports: {e}")
        
        return comparison
    
    @staticmethod
    def validate_report_by_type(file_path: str, report_type: str) -> Dict[str, Any]:
        """
        Validate report based on expected structure for report type
        
        Args:
            file_path: Path to report file
            report_type: Type of report
            
        Returns:
            Validation results
        """
        # Define expected columns for each report type
        expected_columns = {
            "team_detail": ["Team", "Division", "Coach", "Players"],
            "volunteer_detail": ["Name", "Email", "Phone", "Role"],
            "player_detail": ["Name", "DOB", "Division", "Team"],
            "enrollment_summary": ["Division", "Enrolled", "Capacity"],
            "division_details": ["Division", "Age Group", "Teams"],
            "open_orders": ["Order", "Date", "Amount", "Status"],
            "admin_credentials": ["Name", "ID", "Certifications"],
            "admin_details": ["Name", "Email", "Phone", "Address"]
        }
        
        result = ReportValidator.validate_excel_file(file_path)
        
        if result["valid"] and report_type in expected_columns:
            try:
                df = pd.read_excel(file_path)
                actual_columns = df.columns.tolist()
                expected = expected_columns[report_type]
                
                # Check for required columns
                missing_columns = []
                for col in expected:
                    if not any(col.lower() in str(actual_col).lower() 
                             for actual_col in actual_columns):
                        missing_columns.append(col)
                
                if missing_columns:
                    result["warnings"].append(
                        f"Missing expected columns: {missing_columns}"
                    )
                
            except Exception as e:
                logger.error(f"Failed to validate report structure: {e}")
        
        return result
    
    @staticmethod
    def check_data_quality(file_path: str) -> Dict[str, Any]:
        """
        Check data quality issues in report
        
        Args:
            file_path: Path to report file
            
        Returns:
            Data quality results
        """
        quality = {
            "null_counts": {},
            "duplicate_rows": 0,
            "issues": []
        }
        
        try:
            df = pd.read_excel(file_path)
            
            # Check for null values
            null_counts = df.isnull().sum()
            quality["null_counts"] = null_counts[null_counts > 0].to_dict()
            
            # Check for duplicate rows
            quality["duplicate_rows"] = df.duplicated().sum()
            
            # Check for common data quality issues
            if len(df) > 0:
                # Check for empty strings
                for col in df.columns:
                    if df[col].dtype == 'object':
                        empty_count = (df[col] == '').sum()
                        if empty_count > 0:
                            quality["issues"].append(
                                f"Column '{col}' has {empty_count} empty strings"
                            )
                
                # Check for suspicious patterns
                if quality["duplicate_rows"] > len(df) * 0.1:
                    quality["issues"].append(
                        "More than 10% duplicate rows detected"
                    )
                
        except Exception as e:
            quality["error"] = str(e)
            logger.error(f"Failed to check data quality: {e}")
        
        return quality
    
    @staticmethod
    def generate_validation_report(validations: Dict[str, Dict]) -> str:
        """
        Generate a validation report for multiple files
        
        Args:
            validations: Dictionary of filename: validation_results
            
        Returns:
            Report as string
        """
        report = ["Report Validation Summary", "=" * 50, ""]
        
        for filename, validation in validations.items():
            report.append(f"File: {filename}")
            report.append("-" * len(f"File: {filename}"))
            
            if validation.get("valid"):
                report.append("✓ Valid file")
                
                # Show appropriate stats based on file type
                if "total_rows" in validation:
                    report.append(f"  Rows: {validation.get('total_rows', 0)}")
                if "total_columns" in validation:
                    report.append(f"  Columns: {validation.get('total_columns', 0)}")
                if "sheets" in validation and validation["sheets"]:
                    report.append(f"  Sheets: {', '.join(validation['sheets'])}")
                
                report.append(f"  Size: {validation.get('file_size', 0):,} bytes")
            else:
                report.append("✗ Invalid file")
                report.append(f"  Error: {validation.get('error', 'Unknown')}")
            
            warnings = validation.get("warnings", [])
            if warnings:
                report.append("  Warnings:")
                for warning in warnings:
                    report.append(f"    - {warning}")
            
            report.append("")
        
        return "\n".join(report)
    
    @staticmethod
    def validate_all_reports(download_dir: str) -> Dict[str, Dict]:
        """
        Validate all reports in download directory
        
        Args:
            download_dir: Directory containing downloaded reports
            
        Returns:
            Dictionary of validation results
        """
        validations = {}
        download_path = Path(download_dir)
        
        if not download_path.exists():
            logger.error(f"Download directory not found: {download_dir}")
            return validations
        
        # Find all report files
        excel_files = list(download_path.glob("*.xlsx")) + list(download_path.glob("*.xls"))
        pdf_files = list(download_path.glob("*.pdf"))
        json_files = list(download_path.glob("*.json"))
        
        # Validate Excel files
        for file_path in excel_files:
            validation = ReportValidator.validate_excel_file(str(file_path))
            validations[file_path.name] = validation
        
        # Validate PDF files
        for file_path in pdf_files:
            validation = ReportValidator.validate_pdf_file(str(file_path))
            validations[file_path.name] = validation
        
        # Validate JSON files
        for file_path in json_files:
            validation = ReportValidator.validate_json_file(str(file_path))
            validations[file_path.name] = validation
        
        return validations