"""
Coach Cache Manager for Sports Connect Automation
Manages persistent storage of coach information separate from configuration
"""
import json
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import shutil

logger = logging.getLogger(__name__)


class CoachCacheManager:
    """Manages coach information cache in a separate file"""
    
    def __init__(self, cache_dir: str = "data/coach_cache"):
        """
        Initialize Coach Cache Manager
        
        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.cache_file = self.cache_dir / "coach_cache.json"
        self.backup_dir = self.cache_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        
        # Load existing cache
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict[str, Dict]:
        """Load existing coach cache from file"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Loaded coach cache with {len(data)} entries")
                    return data
            except Exception as e:
                logger.error(f"Error loading coach cache: {e}")
                # Create backup of corrupted file
                backup_path = self.backup_dir / f"coach_cache_corrupted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                shutil.copy2(self.cache_file, backup_path)
                logger.info(f"Backed up corrupted cache to: {backup_path}")
                return {}
        return {}
    
    def _save_cache(self) -> bool:
        """Save coach cache to file"""
        try:
            # Create backup before saving
            if self.cache_file.exists():
                self._create_backup()
            
            # Save cache with pretty formatting
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2, sort_keys=True)
            
            logger.info(f"Saved coach cache with {len(self.cache)} entries")
            return True
            
        except Exception as e:
            logger.error(f"Error saving coach cache: {e}")
            return False
    
    def _create_backup(self):
        """Create a backup of the current cache file"""
        try:
            # Only keep last 10 backups
            existing_backups = sorted(self.backup_dir.glob("coach_cache_*.json"))
            if len(existing_backups) >= 10:
                # Remove oldest backups
                for old_backup in existing_backups[:-9]:
                    old_backup.unlink()
                    logger.debug(f"Removed old backup: {old_backup}")
            
            # Create new backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"coach_cache_{timestamp}.json"
            shutil.copy2(self.cache_file, backup_path)
            logger.debug(f"Created backup: {backup_path}")
            
        except Exception as e:
            logger.warning(f"Failed to create backup: {e}")
    
    def add_coach(self, division: str, team_name: str, coach_name: str, 
                  coach_email: str, additional_info: Dict = None) -> str:
        """
        Add or update coach information
        
        Args:
            division: Division code (e.g., '07UB')
            team_name: Team name
            coach_name: Coach's full name
            coach_email: Coach's email address
            additional_info: Optional additional information
            
        Returns:
            Cache key for the entry
        """
        # Create consistent key
        cache_key = self._generate_cache_key(division, team_name)
        
        # Create coach entry
        coach_entry = {
            'division': division,
            'team': team_name,
            'coach_name': coach_name,
            'coach_email': coach_email,
            'last_updated': datetime.now().isoformat(),
            'update_count': self.cache.get(cache_key, {}).get('update_count', 0) + 1
        }
        
        # Add additional info if provided
        if additional_info:
            coach_entry.update(additional_info)
        
        # Preserve history if entry exists
        if cache_key in self.cache:
            if 'history' not in coach_entry:
                coach_entry['history'] = []
            
            # Add previous version to history
            old_entry = self.cache[cache_key].copy()
            old_entry.pop('history', None)  # Don't nest history
            coach_entry['history'] = self.cache[cache_key].get('history', [])
            coach_entry['history'].append({
                'archived_at': datetime.now().isoformat(),
                'data': old_entry
            })
            
            # Keep only last 5 history entries
            coach_entry['history'] = coach_entry['history'][-5:]
        
        # Update cache
        self.cache[cache_key] = coach_entry
        
        # Save to file
        if self._save_cache():
            logger.info(f"Added/updated coach: {coach_name} <{coach_email}> for {team_name} ({division})")
        
        return cache_key
    
    def get_coach(self, division: str, team_name: str) -> Optional[Dict]:
        """Get coach information for a specific team"""
        cache_key = self._generate_cache_key(division, team_name)
        return self.cache.get(cache_key)
    
    def get_coaches_by_division(self, division: str) -> Dict[str, Dict]:
        """Get all coaches for a specific division"""
        result = {}
        for key, coach in self.cache.items():
            if coach.get('division') == division:
                result[key] = coach
        return result
    
    def get_all_coaches(self) -> Dict[str, Dict]:
        """Get all cached coaches"""
        return self.cache.copy()
    
    def search_coaches(self, search_term: str) -> Dict[str, Dict]:
        """Search for coaches by name, email, or team"""
        search_term = search_term.lower()
        result = {}
        
        for key, coach in self.cache.items():
            if (search_term in coach.get('coach_name', '').lower() or
                search_term in coach.get('coach_email', '').lower() or
                search_term in coach.get('team', '').lower()):
                result[key] = coach
        
        return result
    
    def remove_coach(self, division: str, team_name: str) -> bool:
        """Remove a coach from the cache"""
        cache_key = self._generate_cache_key(division, team_name)
        
        if cache_key in self.cache:
            removed_coach = self.cache.pop(cache_key)
            if self._save_cache():
                logger.info(f"Removed coach: {removed_coach['coach_name']} for {team_name} ({division})")
                return True
        
        return False
    
    def export_to_csv(self, output_path: str = None) -> str:
        """Export coach cache to CSV file"""
        import csv
        
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.cache_dir / f"coach_export_{timestamp}.csv"
        
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                # Define CSV columns
                fieldnames = ['division', 'team', 'coach_name', 'coach_email', 
                             'last_updated', 'update_count', 'cache_key']
                
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                # Write coach data
                for cache_key, coach in sorted(self.cache.items()):
                    row = {
                        'division': coach.get('division', ''),
                        'team': coach.get('team', ''),
                        'coach_name': coach.get('coach_name', ''),
                        'coach_email': coach.get('coach_email', ''),
                        'last_updated': coach.get('last_updated', ''),
                        'update_count': coach.get('update_count', 0),
                        'cache_key': cache_key
                    }
                    writer.writerow(row)
            
            logger.info(f"Exported {len(self.cache)} coaches to: {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")
            return None
    
    def import_from_csv(self, csv_path: str, update_existing: bool = True) -> int:
        """Import coaches from CSV file"""
        import csv
        imported_count = 0
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    if row.get('division') and row.get('team') and row.get('coach_email'):
                        cache_key = self._generate_cache_key(row['division'], row['team'])
                        
                        # Skip if exists and not updating
                        if cache_key in self.cache and not update_existing:
                            continue
                        
                        # Add coach
                        self.add_coach(
                            division=row['division'],
                            team_name=row['team'],
                            coach_name=row.get('coach_name', ''),
                            coach_email=row['coach_email']
                        )
                        imported_count += 1
            
            logger.info(f"Imported {imported_count} coaches from CSV")
            return imported_count
            
        except Exception as e:
            logger.error(f"Error importing from CSV: {e}")
            return 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the coach cache"""
        stats = {
            'total_coaches': len(self.cache),
            'divisions': {},
            'last_update': None,
            'coaches_with_history': 0,
            'total_updates': 0
        }
        
        # Analyze cache
        for coach in self.cache.values():
            # Division counts
            division = coach.get('division', 'Unknown')
            stats['divisions'][division] = stats['divisions'].get(division, 0) + 1
            
            # History tracking
            if coach.get('history'):
                stats['coaches_with_history'] += 1
            
            # Update counts
            stats['total_updates'] += coach.get('update_count', 1)
            
            # Track most recent update
            last_updated = coach.get('last_updated')
            if last_updated:
                if stats['last_update'] is None or last_updated > stats['last_update']:
                    stats['last_update'] = last_updated
        
        return stats
    
    def _generate_cache_key(self, division: str, team_name: str) -> str:
        """Generate consistent cache key"""
        # Normalize the key to handle variations in team names
        normalized_team = team_name.strip().replace(' ', '_').replace('-', '_').lower()
        normalized_division = division.strip().upper()
        return f"{normalized_division}_{normalized_team}"
    
    def migrate_from_config(self, config) -> int:
        """
        Migrate coach cache from config.json to separate file
        
        Args:
            config: ConfigManager instance
            
        Returns:
            Number of coaches migrated
        """
        try:
            # Get coach cache from config
            old_cache = config.get('medical_forms_config.coach_cache', {})
            
            if not old_cache:
                logger.info("No coach cache found in config to migrate")
                return 0
            
            migrated_count = 0
            
            # Migrate each coach entry
            for key, coach_data in old_cache.items():
                if isinstance(coach_data, dict):
                    self.add_coach(
                        division=coach_data.get('division', ''),
                        team_name=coach_data.get('team', ''),
                        coach_name=coach_data.get('coach_name', ''),
                        coach_email=coach_data.get('coach_email', ''),
                        additional_info={
                            'migrated_from_config': True,
                            'original_key': key,
                            'migration_date': datetime.now().isoformat()
                        }
                    )
                    migrated_count += 1
            
            if migrated_count > 0:
                # Remove from config after successful migration
                config.set('medical_forms_config.coach_cache', {})
                config.set('medical_forms_config.coach_cache_migrated', True)
                config.set('medical_forms_config.coach_cache_location', str(self.cache_file))
                config.save_config()
                
                logger.info(f"Successfully migrated {migrated_count} coaches from config")
            
            return migrated_count
            
        except Exception as e:
            logger.error(f"Error migrating coach cache: {e}")
            return 0