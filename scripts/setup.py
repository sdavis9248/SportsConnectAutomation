"""
Setup script for Sports Connect Automation
"""
import os
import sys
import json
import getpass
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from utilities.credentials import CredentialsManager


def main():
    """Run setup wizard"""
    print("Sports Connect Automation Setup")
    print("=" * 50)
    
    # Check if config exists
    config_path = "config/config.json"
    if not os.path.exists(config_path):
        print("Configuration file not found. Creating from template...")
        # Copy from example
        example_path = "config/config.example.json"
        if os.path.exists(example_path):
            import shutil
            shutil.copy(example_path, config_path)
            print(f"Created {config_path}")
    
    # Set up credentials
    print("\nCredentials Setup")
    print("-" * 30)
    setup_creds = input("Do you want to set up Sports Connect credentials? (y/n): ")
    
    if setup_creds.lower() == 'y':
        username = input("Enter Sports Connect username: ")
        password = getpass.getpass("Enter Sports Connect password: ")
        
        creds_manager = CredentialsManager()
        creds_path = "config/credentials.csv"
        creds_manager.save_credentials(username, password, creds_path)
        print(f"Credentials saved to {creds_path}")
    
    # Create necessary directories
    dirs_to_create = [
        "logs",
        "data/downloads",
        "data/archives"
    ]
    
    print("\nCreating directories...")
    for dir_path in dirs_to_create:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        print(f"Created: {dir_path}")
    
    print("\nSetup complete!")
    print("Run 'python src/main.py' to start the automation.")


if __name__ == "__main__":
    main()
