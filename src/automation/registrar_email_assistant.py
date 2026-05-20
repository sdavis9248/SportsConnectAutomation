"""
Registrar Email Assistant for AYSO Region 58
Reads Gmail inbox, analyzes parent requests using Claude AI, and drafts responses.

Integrates with existing SportsConnect data sources:
  - Enrollment_Details (registration status, payment, team placement)
  - Volunteer_Details (volunteer roles, contact info)
  - AdminCredentialsStatusDynamic (compliance/credentials)
  - Waitlist tracking (waitlist position, notification history)
  - Open Orders (payment balances)

Usage:
  python main.py --inbox                     # Process unread inbox emails
  python main.py --inbox --inbox-days 7      # Process emails from last 7 days
  python main.py --inbox --inbox-test        # Analyze but don't mark as processed
  python main.py --inbox-stats               # Show inbox processing statistics
  python main.py --inbox-review              # Review and send/edit drafted responses
  python main.py --inbox-learn               # Learn response style from sent emails (last year)
  python main.py --inbox-learn --inbox-learn-days 180  # Learn from last 6 months
"""

import os
import json
import logging
import base64
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import email
from email import policy

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INTENT_CATEGORIES = [
    "registration_status",
    "registration_help",
    "payment_billing",
    "waitlist_position",
    "team_placement",
    "schedule_info",
    "volunteer_info",
    "general_inquiry",
    "complaint",
    "cancellation_request",
    "transfer_request",
    "unknown",
]

CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1500


# ---------------------------------------------------------------------------
# Data context builder – pulls live data to give Claude relevant context
# ---------------------------------------------------------------------------
class RegistrarDataContext:
    """Loads and queries AYSO data files to provide context for AI responses."""

    def __init__(self, config=None, data_dir: str = "data"):
        self.config = config
        self.data_dir = Path(data_dir)
        self._enrollment_df: Optional[pd.DataFrame] = None
        self._volunteer_df: Optional[pd.DataFrame] = None
        self._credentials_df: Optional[pd.DataFrame] = None
        self._open_orders_df: Optional[pd.DataFrame] = None
        self._waitlist_data: Optional[Dict] = None

    # -- lazy loaders -------------------------------------------------------

    def _find_latest_file(self, pattern: str) -> Optional[Path]:
        """Find the most recent file matching a glob pattern in data_dir and common paths."""
        search_dirs = [self.data_dir, self.data_dir / "downloads", Path(".")]
        if self.config:
            ayso_path = self.config.get("paths", {}).get("ayso_path", "")
            if ayso_path:
                search_dirs.append(Path(os.path.expandvars(ayso_path)))

        candidates: List[Path] = []
        for d in search_dirs:
            if d.exists():
                candidates.extend(d.glob(pattern))
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    @property
    def enrollment_df(self) -> Optional[pd.DataFrame]:
        if self._enrollment_df is None:
            path = self._find_latest_file("Enrollment_Details*.xlsx")
            if path:
                try:
                    self._enrollment_df = pd.read_excel(path)
                    logger.info(f"Loaded enrollment data: {path} ({len(self._enrollment_df)} rows)")
                except Exception as e:
                    logger.warning(f"Failed to load enrollment data: {e}")
        return self._enrollment_df

    @property
    def open_orders_df(self) -> Optional[pd.DataFrame]:
        if self._open_orders_df is None:
            path = self._find_latest_file("Open_Orders_Line_Item*.xlsx")
            if path:
                try:
                    self._open_orders_df = pd.read_excel(path)
                    logger.info(f"Loaded open orders: {path} ({len(self._open_orders_df)} rows)")
                except Exception as e:
                    logger.warning(f"Failed to load open orders: {e}")
        return self._open_orders_df

    @property
    def waitlist_data(self) -> Dict:
        if self._waitlist_data is None:
            tracking_dir = Path("data/waitlist_tracking")
            responses_file = tracking_dir / "waitlist_responses.json"
            if responses_file.exists():
                try:
                    with open(responses_file, "r") as f:
                        self._waitlist_data = json.load(f)
                    logger.info(f"Loaded waitlist tracking data ({len(self._waitlist_data)} entries)")
                except Exception as e:
                    logger.warning(f"Failed to load waitlist data: {e}")
                    self._waitlist_data = {}
            else:
                self._waitlist_data = {}
        return self._waitlist_data

    # -- query methods ------------------------------------------------------

    def lookup_by_email(self, email_address: str) -> Dict[str, Any]:
        """Look up all data associated with an email address."""
        email_lower = email_address.lower().strip()
        result: Dict[str, Any] = {"email": email_lower, "found": False}

        # Enrollment lookup
        if self.enrollment_df is not None:
            email_cols = ["User Email", "Player Email"]
            for col in email_cols:
                if col in self.enrollment_df.columns:
                    matches = self.enrollment_df[
                        self.enrollment_df[col].astype(str).str.lower().str.strip() == email_lower
                    ]
                    if not matches.empty:
                        result["found"] = True
                        players = []
                        for _, row in matches.iterrows():
                            player = {
                                "name": f"{row.get('Player First Name', '')} {row.get('Player Last Name', '')}".strip(),
                                "division": str(row.get("Division Name", "")),
                                "team": str(row.get("Team Name", "")),
                                "program": str(row.get("Program Name", "")),
                                "order_no": str(row.get("Order No", "")),
                                "payment_status": str(row.get("Order Payment Status", "")),
                                "balance": float(row.get("OrderItem Balance", 0) or 0),
                            }
                            players.append(player)
                        result["players"] = players
                        break

        # Open orders lookup
        if self.open_orders_df is not None:
            email_cols_orders = ["User Email", "Email"]
            for col in email_cols_orders:
                if col in self.open_orders_df.columns:
                    matches = self.open_orders_df[
                        self.open_orders_df[col].astype(str).str.lower().str.strip() == email_lower
                    ]
                    if not matches.empty:
                        result["found"] = True
                        orders = []
                        for _, row in matches.iterrows():
                            orders.append({
                                "order_no": str(row.get("Order No", "")),
                                "balance": float(row.get("Balance", 0) or 0),
                                "status": str(row.get("Payment Status", "")),
                            })
                        result["open_orders"] = orders

        # Waitlist lookup
        for key, entry in self.waitlist_data.items():
            entry_email = entry.get("email", "").lower().strip()
            if entry_email == email_lower:
                result["found"] = True
                result["waitlist"] = {
                    "division": entry.get("division", ""),
                    "status": entry.get("status", ""),
                    "notified_date": entry.get("notification_date", ""),
                    "response": entry.get("response", ""),
                }
                break

        return result

    def lookup_by_name(self, first_name: str, last_name: str) -> Dict[str, Any]:
        """Look up by player or parent name."""
        result: Dict[str, Any] = {"name": f"{first_name} {last_name}", "found": False}
        first_lower = first_name.lower().strip()
        last_lower = last_name.lower().strip()

        if self.enrollment_df is not None:
            # Try player name
            matches = self.enrollment_df[
                (self.enrollment_df["Player First Name"].astype(str).str.lower().str.strip() == first_lower)
                & (self.enrollment_df["Player Last Name"].astype(str).str.lower().str.strip() == last_lower)
            ]
            # Try account (parent) name
            if matches.empty:
                matches = self.enrollment_df[
                    (self.enrollment_df["Account First Name"].astype(str).str.lower().str.strip() == first_lower)
                    & (self.enrollment_df["Account Last Name"].astype(str).str.lower().str.strip() == last_lower)
                ]
            if not matches.empty:
                result["found"] = True
                result["records"] = []
                for _, row in matches.iterrows():
                    result["records"].append({
                        "player": f"{row.get('Player First Name', '')} {row.get('Player Last Name', '')}".strip(),
                        "parent": f"{row.get('Account First Name', '')} {row.get('Account Last Name', '')}".strip(),
                        "division": str(row.get("Division Name", "")),
                        "team": str(row.get("Team Name", "")),
                        "payment_status": str(row.get("Order Payment Status", "")),
                        "email": str(row.get("User Email", "")),
                    })
        return result

    def get_registration_status(self) -> Dict[str, Any]:
        """
        Determine current registration status from config and data.

        Returns a dict with:
          - is_open: bool
          - status_message: str (for the system prompt)
        """
        # Check config for explicit registration status
        if self.config:
            reg_config = self.config.get("registration_status", {})
            print(f"DEBUG registration_status config: {reg_config}")
            print(f"DEBUG resolved_config registration_status: {self.config.resolved_config.get('registration_status', 'NOT FOUND')}")
            print(f"DEBUG raw config registration_status: {self.config.config.get('registration_status', 'NOT FOUND')}")            
            if reg_config:
                return {
                    "is_open": reg_config.get("is_open", False),
                    "season": reg_config.get("season", "Fall 2026"),
                    "expected_open_date": reg_config.get("expected_open_date", ""),
                    "message": reg_config.get("message", ""),
                }

        # Default: registration is NOT open (safer default)
        return {
            "is_open": False,
            "season": "Fall 2026",
            "expected_open_date": "",
            "message": "",
        }

    def get_summary_context(self) -> str:
        """Return a short summary of available data for the system prompt."""
        parts = []
        if self.enrollment_df is not None:
            parts.append(f"Enrollment: {len(self.enrollment_df)} players across "
                         f"{self.enrollment_df['Division Name'].nunique()} divisions")
        if self.open_orders_df is not None:
            parts.append(f"Open orders: {len(self.open_orders_df)} outstanding")
        wl_count = len(self.waitlist_data)
        if wl_count:
            parts.append(f"Waitlist: {wl_count} tracked entries")
        return "; ".join(parts) if parts else "No live data loaded."


# ---------------------------------------------------------------------------
# Gmail inbox reader
# ---------------------------------------------------------------------------
class GmailInboxReader:
    """Reads emails from the registrar Gmail inbox using Gmail API (OAuth2)."""

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
    ]

    def __init__(self, config=None):
        self.config = config
        self.service = None

        creds_config = config.get("credentials_config", {}) if config else {}
        self.creds_file = creds_config.get("gmail_creds", "gmail_credentials.json")
        self.token_file = creds_config.get("gmail_token", "gmail_token.pickle")

    def authenticate(self) -> bool:
        """Authenticate with Gmail API using OAuth2."""
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            import pickle

            creds = None

            # Load existing token
            if os.path.exists(self.token_file):
                if self.token_file.endswith(".pickle"):
                    with open(self.token_file, "rb") as f:
                        creds = pickle.load(f)
                else:
                    creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)

            # Refresh or obtain new credentials
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if not os.path.exists(self.creds_file):
                        logger.error(f"Gmail credentials file not found: {self.creds_file}")
                        logger.info("Download OAuth2 credentials from Google Cloud Console")
                        return False
                    flow = InstalledAppFlow.from_client_secrets_file(self.creds_file, self.SCOPES)
                    creds = flow.run_local_server(port=0)

                # Save token
                if self.token_file.endswith(".pickle"):
                    with open(self.token_file, "wb") as f:
                        pickle.dump(creds, f)
                else:
                    with open(self.token_file, "w") as f:
                        f.write(creds.to_json())

            self.service = build("gmail", "v1", credentials=creds)
            logger.info("Gmail API authenticated successfully")
            return True

        except Exception as e:
            logger.error(f"Gmail authentication failed: {e}")
            return False

    def fetch_emails(
        self,
        days: int = 3,
        max_results: int = 50,
        label: str = "INBOX",
        unread_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Fetch emails from the inbox.

        Args:
            days: Look back this many days
            max_results: Maximum emails to return
            label: Gmail label to query
            unread_only: Only fetch unread messages

        Returns:
            List of parsed email dicts
        """
        if not self.service:
            logger.error("Gmail not authenticated")
            return []

        after_date = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
        query_parts = [f"after:{after_date}"]
        if unread_only:
            query_parts.append("is:unread")

        query = " ".join(query_parts)
        logger.info(f"Querying Gmail: {query} (label={label})")

        try:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, labelIds=[label], maxResults=max_results)
                .execute()
            )
            messages = results.get("messages", [])
            logger.info(f"Found {len(messages)} messages")

            emails: List[Dict[str, Any]] = []
            for msg_meta in messages:
                msg = (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=msg_meta["id"], format="full")
                    .execute()
                )
                parsed = self._parse_message(msg)
                if parsed:
                    emails.append(parsed)

            return emails

        except Exception as e:
            logger.error(f"Error fetching emails: {e}")
            return []

    def fetch_sent_emails(self, days: int = 7, max_results: int = 100) -> List[Dict[str, Any]]:
        """Fetch sent emails for thread context."""
        return self.fetch_emails(days=days, max_results=max_results, label="SENT", unread_only=False)

    def _parse_message(self, msg: Dict) -> Optional[Dict[str, Any]]:
        """Parse a Gmail API message into a structured dict."""
        try:
            headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
            body = self._extract_body(msg["payload"])

            # Extract sender email
            from_header = headers.get("from", "")
            sender_email = ""
            sender_name = ""
            email_match = re.search(r"<(.+?)>", from_header)
            if email_match:
                sender_email = email_match.group(1)
                sender_name = from_header.split("<")[0].strip().strip('"')
            else:
                sender_email = from_header
                sender_name = from_header.split("@")[0]

            return {
                "id": msg["id"],
                "thread_id": msg["threadId"],
                "subject": headers.get("subject", "(no subject)"),
                "from_email": sender_email,
                "from_name": sender_name,
                "to": headers.get("to", ""),
                "date": headers.get("date", ""),
                "body": body,
                "snippet": msg.get("snippet", ""),
                "labels": msg.get("labelIds", []),
            }
        except Exception as e:
            logger.warning(f"Failed to parse message: {e}")
            return None

    def _extract_body(self, payload: Dict) -> str:
        """Recursively extract plain-text body from message payload."""
        body = ""

        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        elif payload.get("parts"):
            # Prefer text/plain, fall back to text/html
            plain_parts = [p for p in payload["parts"] if p.get("mimeType") == "text/plain"]
            html_parts = [p for p in payload["parts"] if p.get("mimeType") == "text/html"]

            for part in plain_parts or html_parts:
                part_body = self._extract_body(part)
                if part_body:
                    body += part_body
            # Recurse into multipart/*
            for part in payload["parts"]:
                if part.get("mimeType", "").startswith("multipart/"):
                    body += self._extract_body(part)

        return body.strip()

    def create_draft(
        self, to: str, subject: str, body: str,
        thread_id: str = None, original_email: Dict = None,
    ) -> Optional[str]:
        """
        Create a draft reply in Gmail as HTML so formatting renders.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body text (may contain **bold** markdown)
            thread_id: Gmail thread ID to attach the draft to
            original_email: Original inbound email dict to quote in the reply

        Returns:
            Draft ID if successful, None otherwise
        """
        if not self.service:
            logger.error("Gmail not authenticated")
            return None

        try:
            # Convert markdown-style body to HTML
            html_body = self._body_to_html(body)

            # Add quoted original
            quoted_html = ""
            if original_email:
                orig_date = original_email.get("date", "")
                orig_from = original_email.get("from_name", "")
                orig_email_addr = original_email.get("from_email", "")
                orig_body = original_email.get("body", "")

                # Escape HTML in original body and convert newlines
                import html as html_module
                escaped_orig = html_module.escape(orig_body)
                escaped_orig = escaped_orig.replace("\n", "<br>")

                quoted_html = (
                    f'<br><br><div class="gmail_quote">'
                    f'<div style="margin:0 0 0 .8ex;border-left:1px #ccc solid;padding-left:1ex">'
                    f'On {html_module.escape(orig_date)}, {html_module.escape(orig_from)} '
                    f'&lt;{html_module.escape(orig_email_addr)}&gt; wrote:<br><br>'
                    f'{escaped_orig}'
                    f'</div></div>'
                )

            full_html = f'<div dir="ltr">{html_body}{quoted_html}</div>'

            msg = MIMEMultipart("alternative")
            msg["To"] = to
            msg["Subject"] = subject if subject.startswith("Re:") else f"Re: {subject}"
            msg["From"] = self.config.get("email_config", {}).get("sender_email", "registrar@ayso58.org")
            msg["Reply-To"] = self.config.get("email_config", {}).get("reply_to", "registrar@ayso58.org")
            if original_email and original_email.get("id"):
                msg["In-Reply-To"] = original_email["id"]
                msg["References"] = original_email["id"]

            msg.attach(MIMEText(full_html, "html"))
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

            draft_body: Dict[str, Any] = {"message": {"raw": raw}}
            if thread_id:
                draft_body["message"]["threadId"] = thread_id

            draft = self.service.users().drafts().create(userId="me", body=draft_body).execute()
            logger.info(f"Draft created: {draft['id']} (thread: {thread_id})")
            return draft["id"]

        except Exception as e:
            logger.error(f"Failed to create draft: {e}")
            return None

    @staticmethod
    def _body_to_html(text: str) -> str:
        """
        Convert plain text with markdown-style formatting to HTML.
        Handles **bold**, newlines, and links.
        """
        import html as html_module

        # Escape HTML entities first
        text = html_module.escape(text)

        # Convert **bold** to <b>bold</b>
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)

        # Convert URLs to clickable links
        text = re.sub(
            r'(https?://[^\s<>&]+)',
            r'<a href="\1">\1</a>',
            text,
        )

        # Convert newlines to <br>
        text = text.replace("\n", "<br>\n")

        return text

    def add_label(self, message_id: str, label: str) -> bool:
        """Add a label to a message (for tracking processed emails)."""
        try:
            # Check if label exists, create if not
            labels = self.service.users().labels().list(userId="me").execute().get("labels", [])
            label_id = None
            for lbl in labels:
                if lbl["name"] == label:
                    label_id = lbl["id"]
                    break
            if not label_id:
                created = self.service.users().labels().create(
                    userId="me", body={"name": label, "labelListVisibility": "labelShow",
                                       "messageListVisibility": "show"}
                ).execute()
                label_id = created["id"]

            self.service.users().messages().modify(
                userId="me", id=message_id, body={"addLabelIds": [label_id]}
            ).execute()
            return True
        except Exception as e:
            logger.warning(f"Failed to add label '{label}' to message {message_id}: {e}")
            return False


# ---------------------------------------------------------------------------
# Claude AI analyzer
# ---------------------------------------------------------------------------
class ClaudeEmailAnalyzer:
    """Analyzes inbound emails and generates draft responses using Claude API."""

    def __init__(self, api_key: str, data_context: RegistrarDataContext):
        self.api_key = api_key
        self.data_context = data_context

    def _build_system_prompt(self, sender_context: Dict) -> str:
        """Build a system prompt with data context and learned style."""
        data_summary = self.data_context.get_summary_context()

        sender_section = ""
        if sender_context.get("found"):
            sender_section = f"\n\nSENDER DATA (from our records):\n{json.dumps(sender_context, indent=2, default=str)}"

        # Load style guide if available
        style_section = ""
        style_guide = SentEmailHarvester.load_style_guide()
        if style_guide and not style_guide.get("parse_error"):
            parts = []
            if style_guide.get("registrar_name"):
                parts.append(f"- The registrar's name is {style_guide['registrar_name']}; sign off using their name")
            if style_guide.get("tone_description"):
                parts.append(f"- Tone: {style_guide['tone_description']}")
            if style_guide.get("greeting_patterns"):
                parts.append(f"- Typical greetings: {', '.join(style_guide['greeting_patterns'][:5])}")
            if style_guide.get("signoff_patterns"):
                parts.append(f"- Typical sign-offs: {', '.join(style_guide['signoff_patterns'][:5])}")
            if style_guide.get("common_phrases"):
                parts.append(f"- Common phrases to use: {', '.join(style_guide['common_phrases'][:8])}")
            if style_guide.get("typical_length"):
                parts.append(f"- Typical response length: {style_guide['typical_length']}")
            if style_guide.get("style_rules"):
                for rule in style_guide["style_rules"][:10]:
                    parts.append(f"- {rule}")

            # Add response patterns
            patterns = style_guide.get("response_patterns", {})
            if patterns:
                parts.append("\nRESPONSE PATTERNS BY CATEGORY:")
                for cat, desc in patterns.items():
                    if desc:
                        parts.append(f"- {cat}: {desc}")

            # Add example responses
            examples = style_guide.get("example_responses", [])
            if examples:
                parts.append("\nEXAMPLE RESPONSES (match this style closely):")
                for ex in examples[:6]:
                    parts.append(f"\n[{ex.get('category', 'general')}] Parent asked: {ex.get('inbound_summary', 'N/A')}")
                    parts.append(f"Registrar responded:\n{ex.get('response', '')[:600]}")

            style_section = "\n\nLEARNED REGISTRAR STYLE (from actual sent emails — match this voice):\n" + "\n".join(parts)

        registrar_name_line = "- The registrar's name is not specified; sign off as \"AYSO Region 58 Registrar\""
        if style_guide and style_guide.get("registrar_name"):
            registrar_name_line = f"- The registrar is {style_guide['registrar_name']}"

        # Build registration status section
        reg_status = self.data_context.get_registration_status()
        if reg_status.get("is_open"):
            reg_status_section = f"""
REGISTRATION STATUS: **OPEN**
- The {reg_status.get('season', 'Fall 2026')} season registration is currently OPEN
- Parents can register now at ayso58.org
- If a parent says the website "won't let them register" or they're having trouble, this IS likely a technical issue — help troubleshoot"""
        else:
            expected = reg_status.get("expected_open_date", "")
            expected_line = f"\n- Registration is expected to open: {expected}" if expected else ""
            custom_msg = reg_status.get("message", "")
            custom_line = f"\n- Additional info: {custom_msg}" if custom_msg else ""
            reg_status_section = f"""
⚠️ REGISTRATION STATUS: **NOT OPEN** ⚠️
- The {reg_status.get('season', 'Fall 2026')} season registration is NOT currently open
- There are no programs available to register for right now{expected_line}{custom_line}
- CRITICAL: If a parent says the website "won't let them" register, "won't allow" registration, they "can't register", or asks for help registering — this almost certainly means registration has not opened yet, NOT that there is a technical problem
- Do NOT ask troubleshooting questions about error messages or browser issues
- Instead, explain that registration for the upcoming season has not opened yet, provide the expected opening timeframe if known
- Since the parent was already trying to register on the website, they likely already have an account. Acknowledge this: say something like "Since you were already trying to register on the site, you likely already have an account set up — great! You'll receive an email notification as soon as registration opens." Then add: "If you don't have an account yet, you can create one at ayso58.org so you'll be notified when registration goes live."
- Do NOT assume they need to create an account — lead with the assumption they already have one
- Classify these emails as "registration_help" intent"""

        return f"""You are the AI assistant for the AYSO Region 58 Registrar (registrar@ayso58.org).
Your role is to draft professional, friendly email responses to parents regarding youth soccer registration.

ORGANIZATION CONTEXT:
- AYSO Region 58 (American Youth Soccer Organization)
- Programs: Fall season only (no Spring season) for ages 4-19
- Divisions: 06U through 19U, boys and girls
- Website: ayso58.org
{registrar_name_line}
{reg_status_section}

CURRENT DATA AVAILABLE:
{data_summary}
{sender_section}
{style_section}

RESPONSE GUIDELINES:
1. Be warm, professional, and helpful — these are volunteer-run youth sports parents
2. Use specific data from the sender context when available (player names, divisions, teams, balances)
3. If you don't have the data to answer precisely, acknowledge the question and say the registrar will look into it
4. For payment questions: reference exact balances if available; direct to the SportsConnect portal
5. For waitlist questions: provide position info if available; reassure parents about the process
6. For team placement: ONLY state a player's division if it appears in the sender data lookup. NEVER guess a division based on a child's age — division placement depends on birth date and season-specific age cutoffs, not simply the child's current age. If you don't have division data, just say divisions are determined by birth date and they'll see the correct placement during registration.
7. Never share other families' information
8. Keep responses concise — 2-4 short paragraphs max
9. Match the registrar's actual writing style and voice as closely as possible

OUTPUT FORMAT:
Respond with a JSON object containing:
{{
  "intent": "<one of: {', '.join(INTENT_CATEGORIES)}>",
  "confidence": <float 0-1>,
  "urgency": "<low|medium|high>",
  "summary": "<1-2 sentence summary of the request>",
  "draft_response": "<the full draft email response text>",
  "needs_human_review": <true/false>,
  "review_reason": "<why human review is needed, if applicable>",
  "data_used": ["<list of data sources referenced>"]
}}"""

    def analyze_email(self, email_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Analyze an inbound email and generate a draft response.

        Args:
            email_data: Parsed email dict from GmailInboxReader

        Returns:
            Analysis result dict or None on failure
        """
        import requests

        # Look up sender in our data
        sender_context = self.data_context.lookup_by_email(email_data["from_email"])

        # If email mentions a name we can look up, try that too
        body_text = email_data.get("body", "")
        if not sender_context.get("found"):
            # Try to extract names from sender display name
            parts = email_data.get("from_name", "").split()
            if len(parts) >= 2:
                name_context = self.data_context.lookup_by_name(parts[0], parts[-1])
                if name_context.get("found"):
                    sender_context.update(name_context)
                    sender_context["found"] = True

        system_prompt = self._build_system_prompt(sender_context)
        user_message = self._format_email_for_analysis(email_data)

        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": MAX_TOKENS,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}],
                },
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            # Extract text from response
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]

            # Parse JSON from response
            # Strip markdown fences if present
            text = re.sub(r"```json\s*", "", text)
            text = re.sub(r"```\s*$", "", text)
            text = text.strip()

            result = json.loads(text)
            result["source_email"] = {
                "id": email_data["id"],
                "thread_id": email_data["thread_id"],
                "from": email_data["from_email"],
                "from_name": email_data["from_name"],
                "subject": email_data["subject"],
                "date": email_data["date"],
            }
            result["sender_data"] = sender_context
            result["analyzed_at"] = datetime.now().isoformat()

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.debug(f"Raw response text: {text[:500]}")
            # Return a partial result
            return {
                "intent": "unknown",
                "confidence": 0.0,
                "summary": "Failed to parse AI response",
                "draft_response": text if text else "",
                "needs_human_review": True,
                "review_reason": "AI response was not valid JSON",
                "source_email": {
                    "id": email_data["id"],
                    "thread_id": email_data["thread_id"],
                    "from": email_data["from_email"],
                    "subject": email_data["subject"],
                    "date": email_data["date"],
                },
                "analyzed_at": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return None

    def _format_email_for_analysis(self, email_data: Dict) -> str:
        """Format email data for Claude's analysis."""
        body = email_data.get("body", "")
        # Truncate very long emails
        if len(body) > 3000:
            body = body[:3000] + "\n\n[... email truncated ...]"

        return f"""Analyze the following email received by the AYSO Region 58 registrar and draft a response.

FROM: {email_data.get('from_name', '')} <{email_data.get('from_email', '')}>
DATE: {email_data.get('date', '')}
SUBJECT: {email_data.get('subject', '')}

BODY:
{body}

Please analyze this email and provide your response as the specified JSON object."""


# ---------------------------------------------------------------------------
# Processing log – tracks what's been processed to avoid duplicates
# ---------------------------------------------------------------------------
class InboxProcessingLog:
    """Persists processing history to avoid re-analyzing emails."""

    def __init__(self, log_dir: str = "data/inbox_assistant"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "processing_log.json"
        self.drafts_dir = self.log_dir / "drafts"
        self.drafts_dir.mkdir(exist_ok=True)
        self._log = self._load()

    def _load(self) -> Dict:
        if self.log_file.exists():
            try:
                with open(self.log_file, "r") as f:
                    return json.load(f)
            except Exception:
                return {"processed": {}, "stats": {"total_processed": 0, "total_drafts": 0}}
        return {"processed": {}, "stats": {"total_processed": 0, "total_drafts": 0}}

    def _save(self):
        with open(self.log_file, "w") as f:
            json.dump(self._log, f, indent=2, default=str)

    def is_processed(self, message_id: str) -> bool:
        return message_id in self._log["processed"]

    def mark_processed(self, message_id: str, analysis: Dict):
        self._log["processed"][message_id] = {
            "processed_at": datetime.now().isoformat(),
            "intent": analysis.get("intent", "unknown"),
            "subject": analysis.get("source_email", {}).get("subject", ""),
            "from": analysis.get("source_email", {}).get("from", ""),
            "draft_id": analysis.get("draft_id"),
            "urgency": analysis.get("urgency", "low"),
        }
        self._log["stats"]["total_processed"] += 1
        if analysis.get("draft_id"):
            self._log["stats"]["total_drafts"] += 1
        self._save()

    def save_draft_detail(self, message_id: str, analysis: Dict):
        """Save full analysis to a separate file for review."""
        draft_file = self.drafts_dir / f"{message_id}.json"
        with open(draft_file, "w") as f:
            json.dump(analysis, f, indent=2, default=str)

    def get_pending_drafts(self) -> List[Dict]:
        """Load all draft analyses that haven't been sent yet."""
        drafts = []
        for draft_file in sorted(self.drafts_dir.glob("*.json")):
            try:
                with open(draft_file, "r") as f:
                    data = json.load(f)
                if not data.get("sent"):
                    drafts.append(data)
            except Exception:
                continue
        return drafts

    def mark_sent(self, message_id: str):
        draft_file = self.drafts_dir / f"{message_id}.json"
        if draft_file.exists():
            with open(draft_file, "r") as f:
                data = json.load(f)
            data["sent"] = True
            data["sent_at"] = datetime.now().isoformat()
            with open(draft_file, "w") as f:
                json.dump(data, f, indent=2, default=str)

    def get_stats(self) -> Dict:
        stats = dict(self._log.get("stats", {}))
        # Count by intent
        intent_counts: Dict[str, int] = {}
        urgency_counts: Dict[str, int] = {}
        for entry in self._log.get("processed", {}).values():
            intent = entry.get("intent", "unknown")
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
            urg = entry.get("urgency", "low")
            urgency_counts[urg] = urgency_counts.get(urg, 0) + 1
        stats["by_intent"] = intent_counts
        stats["by_urgency"] = urgency_counts
        stats["pending_drafts"] = len(self.get_pending_drafts())
        return stats


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
class RegistrarEmailAssistant:
    """
    Orchestrates the full inbox-reading, analysis, and draft-creation pipeline.

    Integrates with the existing automation by accepting a config manager and
    optionally reusing an authenticated SportsConnect automation instance.
    """

    def __init__(self, config=None, api_key: str = None):
        """
        Args:
            config: ConfigManager instance (reuse from main.py)
            api_key: Anthropic API key; if None, reads from ANTHROPIC_API_KEY env var
                     or config.inbox_assistant_config.api_key
        """
        self.config = config

        # Resolve API key
        self.api_key = api_key
        if not self.api_key:
            inbox_cfg = config.get("inbox_assistant_config", {}) if config else {}
            self.api_key = inbox_cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Claude API key required. Set ANTHROPIC_API_KEY env var or "
                "add inbox_assistant_config.api_key to config.json"
            )

        # Components
        self.gmail = GmailInboxReader(config)
        self.data_context = RegistrarDataContext(config)
        self.analyzer = ClaudeEmailAnalyzer(self.api_key, self.data_context)
        self.log = InboxProcessingLog()

    def process_inbox(
        self,
        days: int = 3,
        max_emails: int = 20,
        test_mode: bool = False,
        create_drafts: bool = True,
    ) -> Dict[str, Any]:
        """
        Main processing pipeline: read inbox → analyze → draft responses.

        Args:
            days: Look back period
            max_emails: Max emails to process
            test_mode: If True, don't create drafts or mark as processed
            create_drafts: Whether to create Gmail drafts

        Returns:
            Summary dict with results
        """
        logger.info("=" * 60)
        logger.info("Registrar Email Assistant - Processing Inbox")
        logger.info(f"  Days: {days}, Max: {max_emails}, Test: {test_mode}")
        logger.info("=" * 60)

        # Authenticate
        if not self.gmail.authenticate():
            return {"error": "Gmail authentication failed", "processed": 0}

        # Fetch emails
        emails = self.gmail.fetch_emails(days=days, max_results=max_emails)
        if not emails:
            logger.info("No new emails to process")
            return {"processed": 0, "message": "No new emails found"}

        # Filter out already-processed
        new_emails = [e for e in emails if not self.log.is_processed(e["id"])]
        logger.info(f"New emails to process: {len(new_emails)} (skipped {len(emails) - len(new_emails)} already processed)")

        # Filter out automated/noreply and marketing senders
        filtered = []
        skip_patterns = [
            # Automated/system senders
            "noreply@", "no-reply@", "mailer-daemon@", "notifications@",
            "donotreply@", "auto-confirm@", "postmaster@",
            # Marketing/newsletter platforms
            "@mail.beehiiv.com", "@beehiiv.com",
            "@ccsend.com",              # Constant Contact
            "@em.surveymonkey.com", "@surveymonkey.com",
            "@mailchimp.com", "@mail.mailchimp.com",
            "@sendgrid.net",
            "@hubspot.com", "@hubspotmail.com",
            # Specific marketing senders from registrar inbox
            "@go.uclabruins.com",
            "@rmnevents.ccsend.com",
            # Social media / services
            "@facebookmail.com", "@linkedin.com",
            "@accounts.google.com",
        ]
        for em in new_emails:
            sender = em.get("from_email", "").lower()
            if any(p in sender for p in skip_patterns):
                logger.debug(f"Skipping automated/marketing email from: {sender}")
                continue
            filtered.append(em)

        logger.info(f"After filtering automated senders: {len(filtered)} emails")

        results = {
            "processed": 0,
            "drafts_created": 0,
            "errors": 0,
            "high_urgency": 0,
            "needs_review": 0,
            "details": [],
        }

        for i, em in enumerate(filtered, 1):
            logger.info(f"\n[{i}/{len(filtered)}] Analyzing: {em['subject']}")
            logger.info(f"  From: {em['from_name']} <{em['from_email']}>")

            analysis = self.analyzer.analyze_email(em)
            if not analysis:
                logger.error(f"  Analysis failed for message {em['id']}")
                results["errors"] += 1
                continue

            results["processed"] += 1
            logger.info(f"  Intent: {analysis.get('intent')} (confidence: {analysis.get('confidence', 0):.0%})")
            logger.info(f"  Urgency: {analysis.get('urgency')}")
            logger.info(f"  Summary: {analysis.get('summary', '')[:100]}")

            if analysis.get("urgency") == "high":
                results["high_urgency"] += 1
            if analysis.get("needs_human_review"):
                results["needs_review"] += 1

            # Create Gmail draft
            draft_id = None
            if create_drafts and not test_mode:
                draft_response = analysis.get("draft_response", "")
                if draft_response:
                    draft_id = self.gmail.create_draft(
                        to=em["from_email"],
                        subject=em["subject"],
                        body=draft_response,
                        thread_id=em["thread_id"],
                        original_email=em,
                    )
                    if draft_id:
                        results["drafts_created"] += 1
                        analysis["draft_id"] = draft_id
                        logger.info(f"  Draft created: {draft_id}")

            # Log processing
            if not test_mode:
                self.log.mark_processed(em["id"], analysis)
                self.log.save_draft_detail(em["id"], analysis)
                self.gmail.add_label(em["id"], "AI-Processed")

            results["details"].append({
                "subject": em["subject"],
                "from": em["from_email"],
                "intent": analysis.get("intent"),
                "urgency": analysis.get("urgency"),
                "confidence": analysis.get("confidence"),
                "draft_created": draft_id is not None,
                "needs_review": analysis.get("needs_human_review", False),
            })

            # Rate limiting — respect API limits
            if i < len(filtered):
                time.sleep(1)

        # Print summary
        self._print_summary(results)
        return results

    def review_drafts(self) -> List[Dict]:
        """Interactive review of pending drafts."""
        drafts = self.log.get_pending_drafts()
        if not drafts:
            print("\nNo pending drafts to review.")
            return []

        print(f"\n{'='*60}")
        print(f"  Pending Drafts: {len(drafts)}")
        print(f"{'='*60}")

        for i, draft in enumerate(drafts, 1):
            source = draft.get("source_email", {})
            print(f"\n{'─'*60}")
            print(f"  [{i}] {source.get('subject', '(no subject)')}")
            print(f"  From: {source.get('from_name', '')} <{source.get('from', '')}>")
            print(f"  Date: {source.get('date', '')}")
            print(f"  Intent: {draft.get('intent', '?')} | Urgency: {draft.get('urgency', '?')}")
            print(f"  Summary: {draft.get('summary', '')}")
            if draft.get("needs_human_review"):
                print(f"  ⚠ Review needed: {draft.get('review_reason', '')}")
            print(f"\n  --- DRAFT RESPONSE ---")
            print(f"  {draft.get('draft_response', '(no draft)')}")
            print(f"  --- END DRAFT ---")

        return drafts

    def show_stats(self):
        """Display inbox processing statistics."""
        stats = self.log.get_stats()
        print(f"\n{'='*60}")
        print(f"  Registrar Email Assistant Statistics")
        print(f"{'='*60}")
        print(f"  Total processed:  {stats.get('total_processed', 0)}")
        print(f"  Total drafts:     {stats.get('total_drafts', 0)}")
        print(f"  Pending review:   {stats.get('pending_drafts', 0)}")

        if stats.get("by_intent"):
            print(f"\n  By Intent:")
            for intent, count in sorted(stats["by_intent"].items(), key=lambda x: -x[1]):
                print(f"    {intent:<30s} {count}")

        if stats.get("by_urgency"):
            print(f"\n  By Urgency:")
            for urg, count in sorted(stats["by_urgency"].items()):
                print(f"    {urg:<30s} {count}")

    def _print_summary(self, results: Dict):
        """Print a formatted processing summary."""
        print(f"\n{'='*60}")
        print(f"  Inbox Processing Complete")
        print(f"{'='*60}")
        print(f"  Emails processed: {results['processed']}")
        print(f"  Drafts created:   {results['drafts_created']}")
        print(f"  Errors:           {results['errors']}")
        print(f"  High urgency:     {results['high_urgency']}")
        print(f"  Needs review:     {results['needs_review']}")

        if results.get("details"):
            print(f"\n  Details:")
            for d in results["details"]:
                flag = "🔴" if d.get("urgency") == "high" else "🟡" if d.get("urgency") == "medium" else "🟢"
                review = " ⚠ REVIEW" if d.get("needs_review") else ""
                draft = " ✓draft" if d.get("draft_created") else ""
                print(f"    {flag} [{d.get('intent', '?')}] {d.get('subject', '')[:50]}{draft}{review}")


# ---------------------------------------------------------------------------
# Sent email harvester — learns response style from historical sent emails
# ---------------------------------------------------------------------------
class SentEmailHarvester:
    """
    Fetches sent emails from the registrar inbox, pairs them with the inbound
    messages they replied to, and builds a style guide + example bank that
    Claude can use to match the registrar's voice.
    """

    STYLE_GUIDE_FILE = "data/inbox_assistant/response_style_guide.json"

    def __init__(self, gmail: GmailInboxReader, api_key: str):
        self.gmail = gmail
        self.api_key = api_key
        self.style_guide_path = Path(self.STYLE_GUIDE_FILE)
        self.style_guide_path.parent.mkdir(parents=True, exist_ok=True)

    def harvest_sent_emails(self, days: int = 365, max_results: int = 500) -> List[Dict]:
        """
        Fetch sent emails and pair them with the inbound messages they replied to.

        Args:
            days: How far back to look
            max_results: Max sent emails to fetch

        Returns:
            List of exchange dicts with inbound + response pairs
        """
        if not self.gmail.service:
            logger.error("Gmail not authenticated")
            return []

        after_date = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
        query = f"after:{after_date} from:me"

        logger.info(f"Harvesting sent emails: {query} (max {max_results})")

        all_messages = []
        page_token = None

        while len(all_messages) < max_results:
            try:
                fetch_count = min(100, max_results - len(all_messages))
                params = {
                    "userId": "me",
                    "q": query,
                    "maxResults": fetch_count,
                }
                if page_token:
                    params["pageToken"] = page_token

                results = self.gmail.service.users().messages().list(**params).execute()
                messages = results.get("messages", [])
                if not messages:
                    break

                all_messages.extend(messages)
                page_token = results.get("nextPageToken")
                if not page_token:
                    break

                logger.info(f"  Fetched {len(all_messages)} sent message IDs so far...")

            except Exception as e:
                logger.error(f"Error listing sent messages: {e}")
                break

        logger.info(f"Total sent messages found: {len(all_messages)}")

        # Parse each sent message and try to find the inbound it replied to
        exchanges: List[Dict] = []
        for i, msg_meta in enumerate(all_messages):
            if i % 50 == 0 and i > 0:
                logger.info(f"  Parsing message {i}/{len(all_messages)}...")

            try:
                msg = (
                    self.gmail.service.users()
                    .messages()
                    .get(userId="me", id=msg_meta["id"], format="full")
                    .execute()
                )
                parsed = self.gmail._parse_message(msg)
                if not parsed:
                    continue

                # Skip if sent to self or internal-only
                to_addr = parsed.get("to", "").lower()
                if not to_addr or to_addr == parsed.get("from_email", "").lower():
                    continue

                exchange = {
                    "response": {
                        "to": parsed["to"],
                        "subject": parsed["subject"],
                        "body": parsed["body"][:2000],  # Truncate long emails
                        "date": parsed["date"],
                    },
                    "inbound": None,
                }

                # Try to find the inbound message in the same thread
                thread_id = parsed.get("thread_id")
                if thread_id:
                    try:
                        thread = (
                            self.gmail.service.users()
                            .threads()
                            .get(userId="me", id=thread_id, format="full")
                            .execute()
                        )
                        thread_msgs = thread.get("messages", [])
                        # Find the message before the sent one in the thread
                        for t_msg in thread_msgs:
                            if t_msg["id"] == msg_meta["id"]:
                                continue
                            t_parsed = self.gmail._parse_message(t_msg)
                            if t_parsed and t_parsed["from_email"].lower() != parsed["from_email"].lower():
                                exchange["inbound"] = {
                                    "from": t_parsed["from_email"],
                                    "from_name": t_parsed["from_name"],
                                    "subject": t_parsed["subject"],
                                    "body": t_parsed["body"][:2000],
                                    "date": t_parsed["date"],
                                }
                                break
                    except Exception:
                        pass

                exchanges.append(exchange)

            except Exception as e:
                logger.debug(f"Error parsing sent message: {e}")
                continue

        logger.info(f"Harvested {len(exchanges)} sent exchanges ({sum(1 for e in exchanges if e['inbound'])} with inbound context)")
        return exchanges

    def build_style_guide(self, exchanges: List[Dict]) -> Dict:
        """
        Send harvested exchanges to Claude to extract a style guide.

        Returns a structured style guide dict.
        """
        import requests

        # Select the best examples — ones with both inbound and response
        paired = [e for e in exchanges if e.get("inbound")]
        unpaired = [e for e in exchanges if not e.get("inbound")]

        # Sample up to 40 paired + 10 unpaired for analysis
        sample_paired = paired[:40]
        sample_unpaired = unpaired[:10]
        sample = sample_paired + sample_unpaired

        if not sample:
            logger.warning("No sent emails to analyze for style guide")
            return {}

        logger.info(f"Analyzing {len(sample)} email exchanges to build style guide...")

        # Format exchanges for Claude
        exchanges_text = ""
        for i, ex in enumerate(sample, 1):
            exchanges_text += f"\n--- EXCHANGE {i} ---\n"
            if ex.get("inbound"):
                inb = ex["inbound"]
                exchanges_text += f"INBOUND FROM: {inb.get('from_name', '')} <{inb.get('from', '')}>\n"
                exchanges_text += f"SUBJECT: {inb.get('subject', '')}\n"
                exchanges_text += f"BODY:\n{inb.get('body', '')[:800]}\n\n"
            exchanges_text += f"REGISTRAR RESPONSE:\n"
            resp = ex["response"]
            exchanges_text += f"TO: {resp.get('to', '')}\n"
            exchanges_text += f"SUBJECT: {resp.get('subject', '')}\n"
            exchanges_text += f"BODY:\n{resp.get('body', '')[:800]}\n"

        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 4000,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"""Analyze the following sent email exchanges from an AYSO Region 58 Registrar.
Extract the registrar's writing style, tone, common phrases, greeting/sign-off patterns,
and how they handle different types of requests.

{exchanges_text}

Respond with a JSON object containing:
{{
  "registrar_name": "<name if identifiable from sign-offs, or null>",
  "tone_description": "<2-3 sentence description of overall tone and personality>",
  "greeting_patterns": ["<list of common greetings used>"],
  "signoff_patterns": ["<list of common sign-offs used>"],
  "common_phrases": ["<distinctive phrases or expressions frequently used>"],
  "response_patterns": {{
    "registration_inquiry": "<how they typically handle registration questions>",
    "payment_question": "<how they typically handle payment questions>",
    "waitlist_inquiry": "<how they typically handle waitlist questions>",
    "general_question": "<how they typically handle general questions>",
    "complaint": "<how they typically handle complaints>",
    "thank_you": "<how they typically respond to thank-you messages>"
  }},
  "style_rules": [
    "<specific writing style rules observed, e.g. 'Uses exclamation points frequently', 'Refers to organization as AYSO not American Youth Soccer'>"
  ],
  "typical_length": "<short/medium/long — average response length>",
  "example_responses": [
    {{
      "category": "<intent category>",
      "inbound_summary": "<what the parent asked>",
      "response": "<the actual response text (best example for this category)>"
    }}
  ]
}}""",
                        }
                    ],
                },
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]

            text = re.sub(r"```json\s*", "", text)
            text = re.sub(r"```\s*$", "", text)
            text = text.strip()

            style_guide = json.loads(text)
            style_guide["generated_at"] = datetime.now().isoformat()
            style_guide["emails_analyzed"] = len(sample)
            style_guide["total_sent_harvested"] = len(exchanges)

            # Save to file
            with open(self.style_guide_path, "w") as f:
                json.dump(style_guide, f, indent=2, default=str)

            logger.info(f"Style guide saved to: {self.style_guide_path}")
            return style_guide

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse style guide JSON: {e}")
            # Save raw text as fallback
            fallback = {
                "raw_analysis": text[:5000] if text else "",
                "generated_at": datetime.now().isoformat(),
                "parse_error": str(e),
            }
            with open(self.style_guide_path, "w") as f:
                json.dump(fallback, f, indent=2)
            return fallback

        except Exception as e:
            logger.error(f"Failed to build style guide: {e}")
            return {}

    @classmethod
    def load_style_guide(cls) -> Optional[Dict]:
        """Load a previously generated style guide."""
        path = Path(cls.STYLE_GUIDE_FILE)
        if path.exists():
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                return None
        return None


# ---------------------------------------------------------------------------
# CLI handler — called from main.py
# ---------------------------------------------------------------------------
def handle_inbox_assistant(config, args) -> int:
    """
    Entry point called from main.py for --inbox and related commands.

    Args:
        config: ConfigManager instance
        args: Parsed argparse namespace

    Returns:
        Exit code (0 = success)
    """
    try:
        assistant = RegistrarEmailAssistant(config=config)
    except ValueError as e:
        logger.error(str(e))
        print(f"\nError: {e}")
        print("Set ANTHROPIC_API_KEY environment variable or add to config.json:")
        print('  "inbox_assistant_config": { "api_key": "sk-ant-..." }')
        return 1

    if getattr(args, "inbox_stats", False):
        assistant.show_stats()
        return 0

    if getattr(args, "inbox_review", False):
        assistant.review_drafts()
        return 0

    # Handle --inbox-learn: harvest sent emails and build style guide
    if getattr(args, "inbox_learn", False):
        learn_days = getattr(args, "inbox_learn_days", 365)
        learn_max = getattr(args, "inbox_learn_max", 500)
        return _handle_learn(assistant, learn_days, learn_max)

    # Default: process inbox
    days = getattr(args, "inbox_days", 3)
    max_emails = getattr(args, "inbox_max", 20)
    test_mode = getattr(args, "test_mode", False) or getattr(args, "inbox_test", False)

    results = assistant.process_inbox(
        days=days,
        max_emails=max_emails,
        test_mode=test_mode,
    )

    if results.get("error"):
        return 1
    return 0


def _handle_learn(assistant: RegistrarEmailAssistant, days: int, max_emails: int) -> int:
    """Handle the --inbox-learn command."""
    print(f"\n{'='*60}")
    print(f"  Registrar Email Style Learning")
    print(f"  Harvesting sent emails from the last {days} days (max {max_emails})")
    print(f"{'='*60}\n")

    # Authenticate Gmail
    if not assistant.gmail.authenticate():
        print("Error: Gmail authentication failed")
        return 1

    harvester = SentEmailHarvester(assistant.gmail, assistant.api_key)

    # Step 1: Harvest sent emails
    print("Step 1/2: Fetching sent emails...")
    exchanges = harvester.harvest_sent_emails(days=days, max_results=max_emails)
    if not exchanges:
        print("No sent emails found to analyze.")
        return 1

    paired = sum(1 for e in exchanges if e.get("inbound"))
    print(f"  Found {len(exchanges)} sent emails ({paired} with inbound context)")

    # Step 2: Build style guide
    print("\nStep 2/2: Analyzing writing style with Claude...")
    style_guide = harvester.build_style_guide(exchanges)
    if not style_guide:
        print("Error: Failed to build style guide")
        return 1

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Style Guide Generated Successfully")
    print(f"{'='*60}")
    if style_guide.get("registrar_name"):
        print(f"  Registrar: {style_guide['registrar_name']}")
    if style_guide.get("tone_description"):
        print(f"  Tone: {style_guide['tone_description']}")
    if style_guide.get("greeting_patterns"):
        print(f"  Greetings: {', '.join(style_guide['greeting_patterns'][:5])}")
    if style_guide.get("signoff_patterns"):
        print(f"  Sign-offs: {', '.join(style_guide['signoff_patterns'][:5])}")
    if style_guide.get("style_rules"):
        print(f"  Style rules:")
        for rule in style_guide["style_rules"][:8]:
            print(f"    - {rule}")
    if style_guide.get("example_responses"):
        print(f"  Example responses saved: {len(style_guide['example_responses'])}")

    print(f"\n  Saved to: {harvester.style_guide_path}")
    print(f"  This will be automatically used for all future --inbox runs.")
    return 0
