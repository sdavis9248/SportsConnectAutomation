"""
Report archiving utilities for Sports Connect Automation
"""
import os
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)


class ReportArchiver:
    """Archives and manages exported reports"""
    
    def __init__(self, archive_dir: str = None):
        """
        Initialize Report Archiver
        
        Args:
            archive_dir: Base directory for archives
        """
        if archive_dir is None:
            archive_dir = "data/archives"
        
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
    
    def archive_report(self, file_path: str, report_type: str,
                      preserve_original: bool = True) -> Optional[str]:
        """
        Archive a report file with proper organization
        
        Args:
            file_path: Path to file to archive
            report_type: Type of report for organization
            preserve_original: Keep original file
            
        Returns:
            Path to archived file
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return None
        
        # Create year/month subdirectory
        now = datetime.now()
        archive_subdir = self.archive_dir / str(now.year) / f"{now.month:02d}"
        archive_subdir.mkdir(parents=True, exist_ok=True)
        
        # Create new filename with timestamp
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        new_filename = f"{report_type}_{timestamp}{file_path.suffix}"
        archive_path = archive_subdir / new_filename
        
        try:
            if preserve_original:
                shutil.copy2(file_path, archive_path)
                logger.info(f"Archived (copied): {file_path} -> {archive_path}")
            else:
                shutil.move(str(file_path), str(archive_path))
                logger.info(f"Archived (moved): {file_path} -> {archive_path}")
            
            return str(archive_path)
            
        except Exception as e:
            logger.error(f"Failed to archive file: {e}")
            return None
    
    def cleanup_old_archives(self, days_to_keep: int = 90) -> int:
        """
        Remove archives older than specified days
        
        Args:
            days_to_keep: Number of days to keep archives
            
        Returns:
            Number of files deleted
        """
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        deleted_count = 0
        
        logger.info(f"Cleaning up archives older than {days_to_keep} days...")
        
        for year_dir in self.archive_dir.iterdir():
            if year_dir.is_dir():
                for month_dir in year_dir.iterdir():
                    if month_dir.is_dir():
                        for file in month_dir.iterdir():
                            if file.is_file():
                                file_time = datetime.fromtimestamp(file.stat().st_mtime)
                                if file_time < cutoff_date:
                                    try:
                                        file.unlink()
                                        deleted_count += 1
                                        logger.debug(f"Deleted old archive: {file}")
                                    except Exception as e:
                                        logger.error(f"Failed to delete {file}: {e}")
                        
                        # Remove empty directories
                        if not any(month_dir.iterdir()):
                            month_dir.rmdir()
                
                # Remove empty year directories
                if not any(year_dir.iterdir()):
                    year_dir.rmdir()
        
        logger.info(f"Deleted {deleted_count} old archive files")
        return deleted_count
    
    def get_archive_size(self) -> int:
        """
        Get total size of archives in bytes
        
        Returns:
            Total size in bytes
        """
        total_size = 0
        
        for file in self.archive_dir.rglob("*"):
            if file.is_file():
                total_size += file.stat().st_size
        
        return total_size
    
    def get_archive_stats(self) -> dict:
        """
        Get statistics about archived files
        
        Returns:
            Dictionary with archive statistics
        """
        stats = {
            "total_files": 0,
            "total_size": 0,
            "by_year": {},
            "by_type": {},
            "oldest_file": None,
            "newest_file": None
        }
        
        oldest_time = None
        newest_time = None
        
        for file in self.archive_dir.rglob("*"):
            if file.is_file():
                stats["total_files"] += 1
                file_size = file.stat().st_size
                stats["total_size"] += file_size
                
                # Year statistics
                year = file.parent.parent.name
                if year not in stats["by_year"]:
                    stats["by_year"][year] = {"count": 0, "size": 0}
                stats["by_year"][year]["count"] += 1
                stats["by_year"][year]["size"] += file_size
                
                # Type statistics (based on filename prefix)
                report_type = file.stem.split("_")[0]
                if report_type not in stats["by_type"]:
                    stats["by_type"][report_type] = {"count": 0, "size": 0}
                stats["by_type"][report_type]["count"] += 1
                stats["by_type"][report_type]["size"] += file_size
                
                # Track oldest/newest
                file_time = datetime.fromtimestamp(file.stat().st_mtime)
                if oldest_time is None or file_time < oldest_time:
                    oldest_time = file_time
                    stats["oldest_file"] = str(file)
                if newest_time is None or file_time > newest_time:
                    newest_time = file_time
                    stats["newest_file"] = str(file)
        
        # Convert size to human readable
        stats["total_size_mb"] = round(stats["total_size"] / (1024 * 1024), 2)
        
        return stats
    
    def list_archives(self, report_type: str = None,
                     start_date: datetime = None,
                     end_date: datetime = None) -> List[Path]:
        """
        List archived files with optional filters
        
        Args:
            report_type: Filter by report type
            start_date: Filter by start date
            end_date: Filter by end date
            
        Returns:
            List of archive file paths
        """
        archives = []
        
        for file in self.archive_dir.rglob("*"):
            if file.is_file():
                # Filter by report type
                if report_type and not file.stem.startswith(report_type):
                    continue
                
                # Filter by date
                if start_date or end_date:
                    file_time = datetime.fromtimestamp(file.stat().st_mtime)
                    if start_date and file_time < start_date:
                        continue
                    if end_date and file_time > end_date:
                        continue
                
                archives.append(file)
        
        # Sort by modification time
        archives.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        return archives
    
    def create_archive_report(self) -> str:
        """
        Create a summary report of archives
        
        Returns:
            Report content as string
        """
        stats = self.get_archive_stats()
        
        report = ["Archive Summary Report", "=" * 50, ""]
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Archive Directory: {self.archive_dir.absolute()}")
        report.append("")
        
        report.append("Overall Statistics:")
        report.append(f"  Total Files: {stats['total_files']}")
        report.append(f"  Total Size: {stats['total_size_mb']} MB")
        if stats['oldest_file']:
            report.append(f"  Oldest File: {Path(stats['oldest_file']).name}")
        if stats['newest_file']:
            report.append(f"  Newest File: {Path(stats['newest_file']).name}")
        report.append("")
        
        if stats['by_year']:
            report.append("Archives by Year:")
            for year, data in sorted(stats['by_year'].items()):
                size_mb = round(data['size'] / (1024 * 1024), 2)
                report.append(f"  {year}: {data['count']} files, {size_mb} MB")
            report.append("")
        
        if stats['by_type']:
            report.append("Archives by Type:")
            for rtype, data in sorted(stats['by_type'].items()):
                size_mb = round(data['size'] / (1024 * 1024), 2)
                report.append(f"  {rtype}: {data['count']} files, {size_mb} MB")
        
        return "\n".join(report)
