"""
Google Drive integration for Sports Connect Automation
"""
import os
import pickle
import logging
from pathlib import Path
from typing import Optional, List, Dict
from mimetypes import MimeTypes
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from core.exceptions import GoogleDriveError

logger = logging.getLogger(__name__)


class GoogleDriveUploader:
    """Handles Google Drive uploads"""
    
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
 
    def __init__(self, credentials_file: str = 'credentials.json',
                 token_file: str = 'token.pickle'):
        """
        Initialize Google Drive uploader
        
        Args:
            credentials_file: Path to Google API credentials JSON
            token_file: Path to store authentication token
        """
        if credentials_file is None:
            credentials_file = config.get('credentials_config.google_drive_creds', 'credentials.json')
        if token_file is None:
            token_file = config.get('credentials_config.google_drive_token', 'token.pickle')
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self.creds = None
        
        if not os.path.exists(credentials_file):
            logger.warning(f"Google Drive credentials file not found: {credentials_file}")
        else:
            self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google Drive API"""
        try:
            # Load existing token
            if os.path.exists(self.token_file):
                with open(self.token_file, 'rb') as token:
                    self.creds = pickle.load(token)
            
            # If no valid credentials, get new ones
            if not self.creds or not self.creds.valid:
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    logger.info("Refreshing Google Drive token...")
                    self.creds.refresh(Request())
                else:
                    logger.info("Getting new Google Drive credentials...")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, self.SCOPES)
                    self.creds = flow.run_local_server(port=0)
                
                # Save the credentials for the next run
                with open(self.token_file, 'wb') as token:
                    pickle.dump(self.creds, token)
            
            # Build the service
            self.service = build('drive', 'v3', credentials=self.creds)
            logger.info("Google Drive authentication successful")
            
        except Exception as e:
            logger.error(f"Google Drive authentication failed: {e}")
            raise GoogleDriveError(f"Authentication failed: {e}")
    
    def upload_file(self, file_path: str, folder_id: Optional[str] = None,
                   filename: Optional[str] = None) -> Optional[str]:
        """
        Upload a file to Google Drive
        
        Args:
            file_path: Path to file to upload
            folder_id: Google Drive folder ID (optional)
            filename: Custom filename (optional, uses original if not provided)
            
        Returns:
            File ID if successful, None otherwise
        """
        if not self.service:
            logger.error("Google Drive service not initialized")
            return None
        
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None
        
        try:
            # Determine filename
            if not filename:
                filename = Path(file_path).name
            
            # Determine MIME type
            mime_type = self._get_mime_type(file_path)
            
            # Set up file metadata
            file_metadata = {
                'name': filename
            }
            
            # Add parent folder if specified
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            # Create media upload
            media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
            
            # Upload file
            logger.info(f"Uploading {filename} to Google Drive...")
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            file_id = file.get('id')
            logger.info(f"Successfully uploaded {filename} (ID: {file_id})")
            return file_id
            
        except HttpError as e:
            logger.error(f"HTTP error uploading {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error uploading {file_path}: {e}")
            return None
    
    def upload_reports(self, report_files: Dict[str, str], 
                      folder_id: Optional[str] = None) -> Dict[str, Optional[str]]:
        """
        Upload multiple report files
        
        Args:
            report_files: Dictionary mapping report names to file paths
            folder_id: Google Drive folder ID (optional)
            
        Returns:
            Dictionary mapping report names to file IDs
        """
        results = {}
        
        for report_name, file_path in report_files.items():
            if file_path and os.path.exists(file_path):
                # Generate filename with timestamp
                timestamp = Path(file_path).stem.split('_')[-1] if '_' in Path(file_path).stem else ''
                if timestamp:
                    filename = f"{report_name}_{timestamp}.xlsx"
                else:
                    filename = f"{report_name}.xlsx"
                
                file_id = self.upload_file(file_path, folder_id, filename)
                results[report_name] = file_id
            else:
                logger.warning(f"File not found for {report_name}: {file_path}")
                results[report_name] = None
        
        return results
    
    def create_folder(self, folder_name: str, parent_folder_id: Optional[str] = None) -> Optional[str]:
        """
        Create a folder in Google Drive
        
        Args:
            folder_name: Name of folder to create
            parent_folder_id: Parent folder ID (optional)
            
        Returns:
            Folder ID if successful, None otherwise
        """
        if not self.service:
            logger.error("Google Drive service not initialized")
            return None
        
        try:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            
            if parent_folder_id:
                file_metadata['parents'] = [parent_folder_id]
            
            folder = self.service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()
            
            folder_id = folder.get('id')
            logger.info(f"Created folder '{folder_name}' (ID: {folder_id})")
            return folder_id
            
        except HttpError as e:
            logger.error(f"HTTP error creating folder: {e}")
            return None
        except Exception as e:
            logger.error(f"Error creating folder: {e}")
            return None
    
    def list_files(self, folder_id: Optional[str] = None, 
                   name_contains: Optional[str] = None) -> List[Dict]:
        """
        List files in Google Drive
        
        Args:
            folder_id: Folder ID to search in (optional)
            name_contains: Filter by filename containing text (optional)
            
        Returns:
            List of file information dictionaries
        """
        if not self.service:
            logger.error("Google Drive service not initialized")
            return []
        
        try:
            # Build query
            query_parts = []
            
            if folder_id:
                query_parts.append(f"'{folder_id}' in parents")
            
            if name_contains:
                query_parts.append(f"name contains '{name_contains}'")
            
            query = " and ".join(query_parts) if query_parts else None
            
            # Execute query
            results = self.service.files().list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)"
            ).execute()
            
            files = results.get('files', [])
            logger.info(f"Found {len(files)} files")
            return files
            
        except HttpError as e:
            logger.error(f"HTTP error listing files: {e}")
            return []
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []
    
    def delete_file(self, file_id: str) -> bool:
        """
        Delete a file from Google Drive
        
        Args:
            file_id: ID of file to delete
            
        Returns:
            True if successful, False otherwise
        """
        if not self.service:
            logger.error("Google Drive service not initialized")
            return False
        
        try:
            self.service.files().delete(fileId=file_id).execute()
            logger.info(f"Deleted file ID: {file_id}")
            return True
            
        except HttpError as e:
            logger.error(f"HTTP error deleting file: {e}")
            return False
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False
    
    def share_file(self, file_id: str, email: str, role: str = 'reader') -> bool:
        """
        Share a file with another user
        
        Args:
            file_id: ID of file to share
            email: Email address to share with
            role: Permission role (reader, writer, commenter)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.service:
            logger.error("Google Drive service not initialized")
            return False
        
        try:
            permission = {
                'type': 'user',
                'role': role,
                'emailAddress': email
            }
            
            self.service.permissions().create(
                fileId=file_id,
                body=permission,
                sendNotificationEmail=True
            ).execute()
            
            logger.info(f"Shared file {file_id} with {email} as {role}")
            return True
            
        except HttpError as e:
            logger.error(f"HTTP error sharing file: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sharing file: {e}")
            return False
    
    def get_file_link(self, file_id: str) -> Optional[str]:
        """
        Get shareable link for a file
        
        Args:
            file_id: ID of file
            
        Returns:
            Shareable link if successful, None otherwise
        """
        if not self.service:
            logger.error("Google Drive service not initialized")
            return None
        
        try:
            file = self.service.files().get(
                fileId=file_id,
                fields='webViewLink'
            ).execute()
            
            link = file.get('webViewLink')
            logger.info(f"Got link for file {file_id}: {link}")
            return link
            
        except HttpError as e:
            logger.error(f"HTTP error getting file link: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting file link: {e}")
            return None
    
    def download_file(self, file_id: str, download_path: str) -> bool:
        """
        Download a file from Google Drive
        
        Args:
            file_id: ID of file to download
            download_path: Local path to save file
            
        Returns:
            True if successful, False otherwise
        """
        if not self.service:
            logger.error("Google Drive service not initialized")
            return False
        
        try:
            # Get file metadata
            file_metadata = self.service.files().get(fileId=file_id).execute()
            
            # Request file content
            request = self.service.files().get_media(fileId=file_id)
            
            # Download file
            with open(download_path, 'wb') as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                    logger.info(f"Download progress: {int(status.progress() * 100)}%")
            
            logger.info(f"Downloaded {file_metadata['name']} to {download_path}")
            return True
            
        except HttpError as e:
            logger.error(f"HTTP error downloading file: {e}")
            return False
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return False
    
    def _get_mime_type(self, file_path: str) -> str:
        """
        Get MIME type for a file
        
        Args:
            file_path: Path to file
            
        Returns:
            MIME type string
        """
        mime = MimeTypes()
        mime_type, _ = mime.guess_type(file_path)
        
        if mime_type is None:
            # Default MIME types for common file extensions
            ext = Path(file_path).suffix.lower()
            mime_types = {
                '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                '.xls': 'application/vnd.ms-excel',
                '.pdf': 'application/pdf',
                '.txt': 'text/plain',
                '.csv': 'text/csv'
            }
            mime_type = mime_types.get(ext, 'application/octet-stream')
        
        return mime_type
    
    def cleanup_old_files(self, folder_id: str, days_old: int = 30) -> int:
        """
        Clean up files older than specified days
        
        Args:
            folder_id: Folder ID to clean up
            days_old: Delete files older than this many days
            
        Returns:
            Number of files deleted
        """
        if not self.service:
            logger.error("Google Drive service not initialized")
            return 0
        
        try:
            from datetime import datetime, timedelta
            
            cutoff_date = datetime.now() - timedelta(days=days_old)
            cutoff_str = cutoff_date.isoformat() + 'Z'
            
            # Find old files
            query = f"'{folder_id}' in parents and modifiedTime < '{cutoff_str}'"
            
            results = self.service.files().list(
                q=query,
                fields="files(id, name, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            deleted_count = 0
            
            for file in files:
                if self.delete_file(file['id']):
                    deleted_count += 1
                    logger.info(f"Deleted old file: {file['name']}")
            
            logger.info(f"Cleaned up {deleted_count} old files")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up old files: {e}")
            return 0


class GoogleDriveBatchUploader(GoogleDriveUploader):
    """Extended uploader with batch operations"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.batch_queue = []
    
    def add_to_batch(self, file_path: str, folder_id: Optional[str] = None,
                    filename: Optional[str] = None):
        """Add file to batch upload queue"""
        self.batch_queue.append({
            'file_path': file_path,
            'folder_id': folder_id,
            'filename': filename
        })
    
    def execute_batch(self) -> List[Optional[str]]:
        """Execute all files in batch queue"""
        results = []
        
        for item in self.batch_queue:
            file_id = self.upload_file(
                item['file_path'],
                item['folder_id'],
                item['filename']
            )
            results.append(file_id)
        
        # Clear queue after execution
        self.batch_queue.clear()
        
        return results
    
    def clear_batch(self):
        """Clear the batch queue without executing"""
        self.batch_queue.clear()
        logger.info("Batch queue cleared")


# Utility functions
def setup_google_drive_credentials():
    """Interactive setup for Google Drive credentials"""
    print("Google Drive Setup")
    print("==================")
    print("1. Go to the Google Cloud Console: https://console.cloud.google.com/")
    print("2. Create a new project or select existing one")
    print("3. Enable the Google Drive API")
    print("4. Create credentials (OAuth 2.0 Client ID)")
    print("5. Download the credentials JSON file")
    print("6. Save it as 'credentials.json' in your project directory")
    print()
    
    creds_path = input("Enter path to credentials file (or press Enter for 'credentials.json'): ").strip()
    if not creds_path:
        creds_path = 'credentials.json'
    
    if os.path.exists(creds_path):
        print(f"✓ Found credentials file: {creds_path}")
        
        # Test authentication
        try:
            uploader = GoogleDriveUploader(creds_path)
            print("✓ Google Drive authentication successful!")
            return True
        except Exception as e:
            print(f"✗ Authentication failed: {e}")
            return False
    else:
        print(f"✗ Credentials file not found: {creds_path}")
        return False


if __name__ == "__main__":
    # Interactive setup when run directly
    setup_google_drive_credentials()