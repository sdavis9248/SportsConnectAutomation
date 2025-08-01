"""
Enhanced Coach Cache Manager with Season Support
This module manages caching of coach information including season association
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import csv

logger = logging.getLogger(__name__)


class CoachCacheManager:
    """Manages caching of coach information with season support"""
    
    def __init__(self, cache_file: str = None, config=None):
        """
        Initialize coach cache manager
    
        Args:
            cache_file: Path to the cache file (overrides config)
            config: Configuration manager instance
        """
        # Determine cache file location

        if cache_file:
            self.cache_file = cache_file
        elif config:
            # Check in medical_forms_config first (where it actually is)
            medical_config = config.get('medical_forms_config', {})
            if medical_config.get('coach_cache_location'):
                self.cache_file = medical_config.get('coach_cache_location')
            else:
                self.cache_file = "data/coach_coach/coach_cache.json"
        
        self.coach_data = {}
        self._ensure_cache_dir()
        self._load_cache()
    
    def _ensure_cache_dir(self):
        """Ensure cache directory exists"""
        cache_dir = Path(self.cache_file).parent
        cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_cache(self):
        """Load cache from file"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    # Handle legacy format (without version)
                    if 'version' not in data:
                        logger.info("Migrating coach cache to new format with season support")
                        self._migrate_legacy_cache(data)
                    else:
                        self.coach_data = data
                        
                logger.info(f"Loaded {len(self.get_all_coaches())} coaches from cache")
            else:
                # Initialize with new format
                self.coach_data = {
                    'version': '2.0',
                    'coaches': {},
                    'metadata': {
                        'created': datetime.now().isoformat(),
                        'last_updated': datetime.now().isoformat()
                    }
                }
                self._save_cache()
        except Exception as e:
            logger.error(f"Error loading coach cache: {e}")
            self.coach_data = {
                'version': '2.0',
                'coaches': {},
                'metadata': {
                    'created': datetime.now().isoformat(),
                    'last_updated': datetime.now().isoformat()
                }
            }
    
    def _migrate_legacy_cache(self, legacy_data: Dict):
        """Migrate legacy cache format to new format with season support"""
        self.coach_data = {
            'version': '2.0',
            'coaches': {},
            'metadata': {
                'created': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'migrated_from_legacy': True
            }
        }
        
        # Migrate each coach entry
        for old_key, coach_info in legacy_data.items():
            if isinstance(coach_info, dict) and 'division' in coach_info and 'team' in coach_info:
                # Generate new key with placeholder season
                season = coach_info.get('season', 'Unknown Season')
                new_key = self.generate_cache_key(
                    division=coach_info['division'],
                    team=coach_info['team'],
                    season=season
                )
                
                # Add season to coach info if not present
                coach_info['season'] = season
                
                # Store with new key
                self.coach_data['coaches'][new_key] = coach_info
        
        self._save_cache()
        logger.info(f"Migrated {len(self.coach_data['coaches'])} coaches to new format")
    
    def _save_cache(self):
        """Save cache to file"""
        try:
            self.coach_data['metadata']['last_updated'] = datetime.now().isoformat()
            with open(self.cache_file, 'w') as f:
                json.dump(self.coach_data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving coach cache: {e}")
    
    def generate_cache_key(self, division: str, team: str, season: str) -> str:
        """
        Generate unique cache key for a coach
        
        Args:
            division: Division code (e.g., '07UB')
            team: Team name
            season: Season identifier (e.g., '2025 Fall Core')
            
        Returns:
            Unique cache key
        """
        # Normalize inputs
        division = division.upper().strip()
        team = team.strip()
        season = season.strip()
        
        # Create composite key
        return f"{season}|{division}|{team}"
    
    def update_coach(self, division: str, team: str, season: str, 
                    coach_name: str, coach_email: str, **kwargs) -> str:
        """
        Update or add coach information
        
        Args:
            division: Division code
            team: Team name
            season: Season identifier
            coach_name: Coach's name
            coach_email: Coach's email
            **kwargs: Additional coach information
            
        Returns:
            Cache key for the coach
        """
        cache_key = self.generate_cache_key(division, team, season)
        
        # Get existing data or create new
        if cache_key in self.coach_data.get('coaches', {}):
            coach_info = self.coach_data['coaches'][cache_key]
            coach_info['update_history'] = coach_info.get('update_history', [])
            coach_info['update_history'].append({
                'timestamp': datetime.now().isoformat(),
                'previous_name': coach_info.get('coach_name'),
                'previous_email': coach_info.get('coach_email')
            })
        else:
            coach_info = {
                'created': datetime.now().isoformat(),
                'update_history': []
            }
        
        # Update coach information
        coach_info.update({
            'division': division,
            'team': team,
            'season': season,
            'coach_name': coach_name,
            'coach_email': coach_email,
            'last_updated': datetime.now().isoformat(),
            **kwargs
        })
        
        # Ensure coaches dict exists
        if 'coaches' not in self.coach_data:
            self.coach_data['coaches'] = {}
            
        self.coach_data['coaches'][cache_key] = coach_info
        self._save_cache()
        
        logger.debug(f"Updated coach: {cache_key}")
        return cache_key
    
    def get_coach(self, cache_key: str) -> Optional[Dict]:
        """Get coach information by cache key"""
        return self.coach_data.get('coaches', {}).get(cache_key)
    
    def get_coach_by_components(self, division: str, team: str, season: str) -> Optional[Dict]:
        """Get coach information by division, team, and season"""
        cache_key = self.generate_cache_key(division, team, season)
        return self.get_coach(cache_key)
    
    def get_all_coaches(self) -> Dict[str, Dict]:
        """Get all cached coaches"""
        return self.coach_data.get('coaches', {})
    
    def get_coaches_by_division(self, division: str, season: Optional[str] = None) -> Dict[str, Dict]:
        """
        Get all coaches for a specific division and optionally season
        
        Args:
            division: Division code
            season: Optional season filter
            
        Returns:
            Dictionary of coaches
        """
        coaches = {}
        for key, coach in self.coach_data.get('coaches', {}).items():
            if coach.get('division') == division:
                if season is None or coach.get('season') == season:
                    coaches[key] = coach
        return coaches
    
    def get_coaches_by_season(self, season: str) -> Dict[str, Dict]:
        """Get all coaches for a specific season"""
        coaches = {}
        for key, coach in self.coach_data.get('coaches', {}).items():
            if coach.get('season') == season:
                coaches[key] = coach
        return coaches
    
    def search_coaches(self, email: str) -> Dict[str, Dict]:
        """Search for coaches by email"""
        coaches = {}
        for key, coach in self.coach_data.get('coaches', {}).items():
            if coach.get('coach_email', '').lower() == email.lower():
                coaches[key] = coach
        return coaches
    
    def get_statistics(self) -> Dict:
        """Get cache statistics"""
        all_coaches = self.get_all_coaches()
        
        # Count by division and season
        divisions = {}
        seasons = {}
        division_season_matrix = {}
        
        for coach in all_coaches.values():
            division = coach.get('division', 'Unknown')
            season = coach.get('season', 'Unknown')
            
            divisions[division] = divisions.get(division, 0) + 1
            seasons[season] = seasons.get(season, 0) + 1
            
            # Build matrix
            if division not in division_season_matrix:
                division_season_matrix[division] = {}
            division_season_matrix[division][season] = division_season_matrix[division].get(season, 0) + 1
        
        # Count coaches with update history
        coaches_with_history = sum(1 for coach in all_coaches.values() 
                                 if coach.get('update_history'))
        
        # Count total updates
        total_updates = sum(len(coach.get('update_history', [])) 
                          for coach in all_coaches.values())
        
        return {
            'total_coaches': len(all_coaches),
            'divisions': divisions,
            'seasons': seasons,
            'division_season_matrix': division_season_matrix,
            'coaches_with_history': coaches_with_history,
            'total_updates': total_updates,
            'last_update': self.coach_data.get('metadata', {}).get('last_updated', 'Unknown'),
            'cache_version': self.coach_data.get('version', 'Unknown')
        }
    
    def export_to_csv(self, filename: Optional[str] = None) -> str:
        """
        Export coach cache to CSV
        
        Args:
            filename: Optional output filename
            
        Returns:
            Path to exported file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/exports/coach_cache_{timestamp}.csv"
        
        # Ensure export directory exists
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        
        # Write CSV
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['cache_key', 'season', 'division', 'team', 'coach_name', 
                         'coach_email', 'created', 'last_updated', 'update_count']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            writer.writeheader()
            
            for key, coach in sorted(self.get_all_coaches().items()):
                writer.writerow({
                    'cache_key': key,
                    'season': coach.get('season', ''),
                    'division': coach.get('division', ''),
                    'team': coach.get('team', ''),
                    'coach_name': coach.get('coach_name', ''),
                    'coach_email': coach.get('coach_email', ''),
                    'created': coach.get('created', ''),
                    'last_updated': coach.get('last_updated', ''),
                    'update_count': len(coach.get('update_history', []))
                })
        
        logger.info(f"Exported coach cache to: {filename}")
        return filename
    
    def cleanup_old_seasons(self, seasons_to_keep: List[str]) -> int:
        """
        Remove coaches from seasons not in the keep list
        
        Args:
            seasons_to_keep: List of season identifiers to keep
            
        Returns:
            Number of coaches removed
        """
        removed_count = 0
        coaches_to_remove = []
        
        for key, coach in self.coach_data.get('coaches', {}).items():
            if coach.get('season') not in seasons_to_keep:
                coaches_to_remove.append(key)
        
        for key in coaches_to_remove:
            del self.coach_data['coaches'][key]
            removed_count += 1
        
        if removed_count > 0:
            self._save_cache()
            logger.info(f"Removed {removed_count} coaches from old seasons")
        
        return removed_count
    
    def merge_cache(self, other_cache_file: str) -> int:
        """
        Merge another cache file into this one
        
        Args:
            other_cache_file: Path to cache file to merge
            
        Returns:
            Number of coaches merged
        """
        try:
            with open(other_cache_file, 'r') as f:
                other_data = json.load(f)
            
            merged_count = 0
            other_coaches = other_data.get('coaches', other_data)  # Handle both formats
            
            for key, coach in other_coaches.items():
                if key not in self.coach_data.get('coaches', {}):
                    self.coach_data['coaches'][key] = coach
                    merged_count += 1
            
            if merged_count > 0:
                self._save_cache()
                logger.info(f"Merged {merged_count} coaches from {other_cache_file}")
            
            return merged_count
            
        except Exception as e:
            logger.error(f"Error merging cache file {other_cache_file}: {e}")
            return 0