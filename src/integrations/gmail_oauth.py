"""
Gmail OAuth2 integration for sending emails
Alternative to SMTP with App Passwords
"""
import os
import pickle
import base64
import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


class GmailOAuth2Service:
    """Gmail service using OAuth2 authentication"""
    
    # If modifying these scopes, delete the token file
    SCOPES = ['https://www.googleapis.com/auth/gmail.send']
    
    def __init__(self, credentials_file: str = 'gmail_credentials.json',
                 token_file: str = 'gmail_token.pickle'):
        """
        Initialize Gmail OAuth2 service
        
        Args:
            credentials_file: Path to Gmail OAuth2 credentials JSON
            token_file: Path to store authentication token
        """
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self.creds = None
        
        if not os.path.exists(credentials_file):
            logger.warning(f"Gmail credentials file not found: {credentials_file}")
            logger.info("Please set up Gmail API credentials first")
        else:
            self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Gmail API using OAuth2"""
        try:
            # Load existing token
            if os.path.exists(self.token_file):
                with open(self.token_file, 'rb') as token:
                    self.creds = pickle.load(token)
            
            # If no valid credentials, get new ones
            if not self.creds or not self.creds.valid:
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    logger.info("Refreshing Gmail token...")
                    self.creds.refresh(Request())
                else:
                    logger.info("Getting new Gmail credentials...")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, self.SCOPES)
                    self.creds = flow.run_local_server(port=0)
                
                # Save the credentials for next run
                with open(self.token_file, 'wb') as token:
                    pickle.dump(self.creds, token)
            
            # Build the service
            self.service = build('gmail', 'v1', credentials=self.creds)
            logger.info("Gmail OAuth2 authentication successful")
            
        except Exception as e:
            logger.error(f"Gmail authentication failed: {e}")
            raise
    
    def create_message(self, sender: str, to: str, subject: str, 
                      body_html: str, reply_to: str = None) -> Dict:
        """
        Create an email message
        
        Args:
            sender: Sender email address
            to: Recipient email address
            subject: Email subject
            body_html: HTML email body
            reply_to: Reply-to address (optional)
            
        Returns:
            Message dict ready to send
        """
        message = MIMEMultipart('alternative')
        message['to'] = to
        message['subject'] = subject
        
        # Handle sender format
        if sender == 'me':
            message['from'] = sender
        else:
            message['from'] = sender
        
        if reply_to:
            message['reply-to'] = reply_to
        
        # Create the HTML part
        html_part = MIMEText(body_html, 'html')
        message.attach(html_part)
        
        # Encode the message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        return {'raw': raw_message}
    
    def send_email(self, sender: str, to: str, subject: str, 
                   body_html: str, reply_to: str = None) -> bool:
        """
        Send an email using Gmail API
        
        Args:
            sender: Sender email address
            to: Recipient email address
            subject: Email subject
            body_html: HTML email body
            reply_to: Reply-to address (optional)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.service:
                logger.error("Gmail service not initialized")
                return False
            
            # Create message
            message = self.create_message(sender, to, subject, body_html, reply_to)
            
            # Send message
            result = self.service.users().messages().send(
                userId='me',
                body=message
            ).execute()
            
            logger.info(f"Email sent successfully to {to} (Message ID: {result['id']})")
            return True
            
        except HttpError as error:
            logger.error(f'An error occurred: {error}')
            return False
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False
    
    def send_bulk_emails(self, emails: List[Dict], delay_seconds: int = 2) -> Dict:
        """
        Send multiple emails with rate limiting
        
        Args:
            emails: List of email dictionaries with keys: to, subject, body_html
            delay_seconds: Delay between emails
            
        Returns:
            Results dictionary
        """
        sent = []
        failed = []
        
        for i, email_data in enumerate(emails):
            try:
                success = self.send_email(
                    sender=email_data.get('sender', 'me'),
                    to=email_data['to'],
                    subject=email_data['subject'],
                    body_html=email_data['body_html'],
                    reply_to=email_data.get('reply_to')
                )
                
                if success:
                    sent.append(email_data['to'])
                else:
                    failed.append(email_data['to'])
                
                # Rate limiting
                if i < len(emails) - 1:
                    import time
                    time.sleep(delay_seconds)
                    
            except Exception as e:
                logger.error(f"Error processing email to {email_data.get('to', 'unknown')}: {e}")
                failed.append(email_data.get('to', 'unknown'))
        
        return {
            'sent_count': len(sent),
            'failed_count': len(failed),
            'sent': sent,
            'failed': failed
        }


def setup_gmail_oauth():
    """Interactive setup for Gmail OAuth2 credentials"""
    print("\nGmail OAuth2 Setup")
    print("==================")
    print("This setup will help you configure Gmail API access.\n")
    
    print("Step 1: Enable Gmail API")
    print("1. Go to: https://console.cloud.google.com/")
    print("2. Create a new project or select an existing one")
    print("3. Go to 'APIs & Services' > 'Library'")
    print("4. Search for 'Gmail API' and enable it\n")
    
    print("Step 2: Create OAuth2 Credentials")
    print("1. Go to 'APIs & Services' > 'Credentials'")
    print("2. Click 'Create Credentials' > 'OAuth client ID'")
    print("3. Choose 'Desktop app' as application type")
    print("4. Name it 'AYSO Waitlist Notifier'")
    print("5. Download the credentials JSON file")
    print("6. Save it as 'gmail_credentials.json' in your project directory\n")
    
    creds_path = input("Enter path to credentials file (or press Enter for 'gmail_credentials.json'): ").strip()
    if not creds_path:
        creds_path = 'gmail_credentials.json'
    
    if os.path.exists(creds_path):
        print(f"✓ Found credentials file: {creds_path}")
        
        # Test authentication
        try:
            service = GmailOAuth2Service(creds_path)
            print("✓ Gmail OAuth2 authentication successful!")
            
            # Offer to send test email
            if input("\nSend a test email? (y/n): ").lower() == 'y':
                test_email = input("Enter test email address: ").strip()
                if test_email:
                    success = service.send_email(
                        sender='me',
                        to=test_email,
                        subject='AYSO Waitlist Notifier - Test Email',
                        body_html='<p>This is a test email from the AYSO Waitlist Notifier.</p>'
                    )
                    if success:
                        print("✓ Test email sent successfully!")
                    else:
                        print("✗ Test email failed")
            
            return True
            
        except Exception as e:
            print(f"✗ Authentication failed: {e}")
            return False
    else:
        print(f"✗ Credentials file not found: {creds_path}")
        return False


if __name__ == "__main__":
    # Run setup when executed directly
    setup_gmail_oauth()