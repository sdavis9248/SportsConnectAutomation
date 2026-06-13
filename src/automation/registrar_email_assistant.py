"""
Registrar Email Assistant for AYSO Region 58
Reads Gmail inbox, analyzes parent requests using Claude AI (anthropic SDK,
claude-opus-4-8), and drafts responses.

Data sources (PlayMetrics is the registration platform as of Fall 2026):
  - registration-responses CSV (registration status, division/team placement)
  - all-players / player-contacts CSVs (full roster + parent contact info)
  - PlayMetrics waitlist export (per-player waitlist status by division)
  - PM payments export, if present (payment balances)
  - Sports Affinity AdminCredentials* (volunteer compliance/credentials — the
    governing system; still Affinity-sourced, not PlayMetrics)
  - data/knowledge/*.md (curated, cached policy/FAQ knowledge base)
  - campaign tracking + season details
All PlayMetrics exports are refreshed with `python main.py --pm-download`.

Usage:
  python main.py --inbox                     # Process unread inbox emails
  python main.py --inbox --inbox-days 7      # Process emails from last 7 days
  python main.py --inbox --inbox-test        # Analyze but don't mark as processed
  python main.py --inbox-stats               # Show inbox processing statistics
  python main.py --inbox-review              # Review and send/edit drafted responses
  python main.py --inbox-learn               # Learn response style from sent emails (last year)
  python main.py --inbox-learn --inbox-learn-days 180  # Learn from last 6 months
  python main.py --inbox-reset               # Clear processed-email tracking (re-analyze)

Modification History:
  2026-06-13  Header refreshed to PlayMetrics data sources.
  2026-06-12  Migrate to anthropic SDK + claude-opus-4-8; cache the system prompt
              and load data/knowledge/*.md; PlayMetrics waitlist/all-players/
              player-contacts sources (drop SC open-orders); add --inbox-reset;
              robust _extract_body (html-only + attachment bodies). Restored
              after a rebase had corrupted the module.
  (earlier)   Original SportsConnect-sourced implementation. See git history.
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
    "invitation_link_issue",
    "duplicate_account",
    "playmetrics_help",
    "bc_verification",
    "unknown",
]

CLAUDE_MODEL = "claude-opus-4-8"
MAX_TOKENS = 1500
# Curated PlayMetrics/AYSO knowledge base (topical .md files) loaded into the
# cached system prompt. Populated from the claude.ai project export distillation.
KNOWLEDGE_DIR = "data/knowledge"


# ---------------------------------------------------------------------------
# Data context builder – pulls live data to give Claude relevant context
# ---------------------------------------------------------------------------
class RegistrarDataContext:
    """Loads and queries AYSO data files to provide context for AI responses.
    
    Supports both PlayMetrics (PM) and SportsConnect (SC) data sources.
    PM sources are preferred; SC is used as fallback during transition.
    """

    # Column mappings: PM CSV column → normalized key
    PM_ENROLLMENT_COLS = {
        "account_email": "User Email",
        "account_first_name": "Account First Name",
        "account_last_name": "Account Last Name",
        "player_first_name": "Player First Name",
        "player_last_name": "Player Last Name",
        "package_name": "Division Name",
        "status": "Order Payment Status",
        "player_id": "player_id",
        "registered_on": "registered_on",
        "age_group": "age_group",
    }

    def __init__(self, config=None, data_dir: str = "data"):
        self.config = config
        self.data_dir = Path(data_dir)
        self._enrollment_df: Optional[pd.DataFrame] = None
        self._volunteer_df: Optional[pd.DataFrame] = None
        self._credentials_df: Optional[pd.DataFrame] = None
        self._open_orders_df: Optional[pd.DataFrame] = None
        self._waitlist_df: Optional[pd.DataFrame] = None
        self._all_players_df: Optional[pd.DataFrame] = None
        self._player_contacts_df: Optional[pd.DataFrame] = None
        self._campaign_data: Optional[Dict] = None
        self._data_source: str = "none"  # "playmetrics" or "sportsconnect"

    # -- lazy loaders -------------------------------------------------------

    def _find_latest_file(self, pattern: str) -> Optional[Path]:
        """Find the most recent file matching a glob pattern in data_dir and common paths."""
        search_dirs = [
            self.data_dir,
            self.data_dir / "downloads",
            self.data_dir / "playmetrics",
            Path("."),
        ]
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

    def _find_latest_any(self, patterns: List[str]) -> Optional[Path]:
        """Newest file (by mtime) matching ANY of the glob patterns."""
        candidates = [p for pat in patterns for p in [self._find_latest_file(pat)] if p]
        return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

    @property
    def all_players_df(self) -> Optional[pd.DataFrame]:
        """Load PM All Players export — full player roster with parent contacts.

        Matches both manual browser downloads (all-players.csv) and
        --pm-download's canonical naming (player-players_{timestamp}.csv).
        """
        if self._all_players_df is None:
            path = self._find_latest_any(
                ["all-players*.csv", "all_players*.csv", "player-players_*.csv"]
            )
            if path:
                try:
                    self._all_players_df = pd.read_csv(path, encoding="utf-8")
                    logger.info(f"Loaded PM all-players: {path} ({len(self._all_players_df)} rows)")
                except Exception as e:
                    logger.warning(f"Failed to load all-players: {e}")
        return self._all_players_df

    @property
    def player_contacts_df(self) -> Optional[pd.DataFrame]:
        """Load PM Player Contacts export — contact_id, email, phone, linked players.

        Matches both manual browser downloads (all-player-contacts.csv) and
        --pm-download's canonical naming (player-contacts_{timestamp}.csv).
        """
        if self._player_contacts_df is None:
            path = self._find_latest_any(
                ["all-player-contacts*.csv", "all_player_contacts*.csv", "player-contacts_*.csv"]
            )
            if path:
                try:
                    self._player_contacts_df = pd.read_csv(path, encoding="utf-8")
                    logger.info(f"Loaded PM player contacts: {path} ({len(self._player_contacts_df)} rows)")
                except Exception as e:
                    logger.warning(f"Failed to load player contacts: {e}")
        return self._player_contacts_df

    @property
    def campaign_data(self) -> Dict:
        """Load PM email campaign tracking state."""
        if self._campaign_data is None:
            campaign_dir = self.data_dir / "pm_campaign_tracking"
            state_file = campaign_dir / "campaign_state.json"
            if not state_file.exists():
                # Also check parent dir
                state_file = Path("data/pm_campaign_tracking/campaign_state.json")
            if state_file.exists():
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        self._campaign_data = json.load(f)
                    sent_count = len(self._campaign_data.get("sent_emails", {}))
                    logger.info(f"Loaded campaign tracking: {sent_count} emails sent")
                except Exception as e:
                    logger.warning(f"Failed to load campaign tracking: {e}")
                    self._campaign_data = {}
            else:
                self._campaign_data = {}
        return self._campaign_data

    @property
    def season_details(self) -> str:
        """Load season details text file for schedule/location questions."""
        if not hasattr(self, "_season_details"):
            self._season_details = ""
        if not self._season_details:
            path = self._find_latest_file("season-details*.txt")
            if not path:
                path = self._find_latest_file("season_details*.txt")
            if path:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self._season_details = f.read().strip()
                    logger.info(f"Loaded season details: {path}")
                except Exception as e:
                    logger.warning(f"Failed to load season details: {e}")
        return self._season_details

    def _load_pm_enrollment(self) -> Optional[pd.DataFrame]:
        """Try to load PlayMetrics Export Responses CSV.
        
        Searches for registration-responses*.csv in data directories.
        Export via Programs → 2026 Fall Core → More Actions → Export Responses.
        """
        patterns = [
            "registration-responses*.csv",
            "registration_responses*.csv",
        ]
        path = None
        for pattern in patterns:
            path = self._find_latest_file(pattern)
            if path:
                break
        if path:
            try:
                df = pd.read_csv(path, encoding="utf-8")
                # Rename PM columns to normalized names for compatibility
                rename_map = {pm: norm for pm, norm in self.PM_ENROLLMENT_COLS.items() if pm in df.columns}
                df = df.rename(columns=rename_map)
                logger.info(f"Loaded PM enrollment data: {path} ({len(df)} rows)")
                self._data_source = "playmetrics"
                return df
            except Exception as e:
                logger.warning(f"Failed to load PM enrollment data: {e}")
        return None

    @property
    def enrollment_df(self) -> Optional[pd.DataFrame]:
        if self._enrollment_df is None:
            # Try PlayMetrics first, fall back to SportsConnect
            self._enrollment_df = self._load_pm_enrollment()
            if self._enrollment_df is None:
                path = self._find_latest_file("Enrollment_Details*.xlsx")
                if path:
                    try:
                        self._enrollment_df = pd.read_excel(path)
                        self._data_source = "sportsconnect"
                        logger.info(f"Loaded SC enrollment data: {path} ({len(self._enrollment_df)} rows)")
                    except Exception as e:
                        logger.warning(f"Failed to load enrollment data: {e}")
        return self._enrollment_df

    @property
    def open_orders_df(self) -> Optional[pd.DataFrame]:
        """PM payments export. (SC Open_Orders_Line_Item fallback removed — fully migrated.)"""
        if self._open_orders_df is None:
            path = self._find_latest_file("*payments*export*.csv")
            if path:
                try:
                    self._open_orders_df = pd.read_csv(path)
                    logger.info(f"Loaded PM payments: {path} ({len(self._open_orders_df)} rows)")
                except Exception as e:
                    logger.warning(f"Failed to load PM payments: {e}")
        return self._open_orders_df

    @property
    def waitlist_df(self) -> Optional[pd.DataFrame]:
        """Latest PlayMetrics waitlist export (data/playmetrics/waitlist_YYYYMMDD_HHMMSS.csv)."""
        if self._waitlist_df is None:
            path = self._find_latest_file("waitlist_*.csv")
            if path:
                try:
                    self._waitlist_df = pd.read_csv(path)
                    logger.info(f"Loaded PM waitlist: {path} ({len(self._waitlist_df)} rows)")
                except Exception as e:
                    logger.warning(f"Failed to load PM waitlist: {e}")
        return self._waitlist_df

    # -- query methods ------------------------------------------------------

    def lookup_by_email(self, email_address: str) -> Dict[str, Any]:
        """Look up all data associated with an email address."""
        email_lower = email_address.lower().strip()
        result: Dict[str, Any] = {"email": email_lower, "found": False, "data_source": self._data_source}

        # Enrollment lookup — works with both PM and SC column names
        if self.enrollment_df is not None:
            email_cols = ["User Email", "account_email", "Player Email"]
            for col in email_cols:
                if col in self.enrollment_df.columns:
                    matches = self.enrollment_df[
                        self.enrollment_df[col].astype(str).str.lower().str.strip() == email_lower
                    ]
                    if not matches.empty:
                        result["found"] = True
                        players = []
                        for _, row in matches.iterrows():
                            player_first = row.get("Player First Name", row.get("player_first_name", ""))
                            player_last = row.get("Player Last Name", row.get("player_last_name", ""))
                            division = row.get("Division Name", row.get("package_name", ""))
                            team = row.get("Team Name", row.get("team", ""))
                            player = {
                                "name": f"{player_first} {player_last}".strip(),
                                "division": str(division),
                                "team": str(team),
                                "program": str(row.get("Program Name", row.get("program_name", "2026 Fall Core"))),
                                "status": str(row.get("status", row.get("Order Payment Status", ""))),
                            }
                            # PM-specific fields
                            if self._data_source == "playmetrics":
                                player["registered_on"] = str(row.get("registered_on", ""))
                                player["age_group"] = str(row.get("age_group", ""))
                                player["player_id"] = str(row.get("player_id", ""))
                            else:
                                player["order_no"] = str(row.get("Order No", ""))
                                player["payment_status"] = str(row.get("Order Payment Status", ""))
                                player["balance"] = float(row.get("OrderItem Balance", 0) or 0)
                            players.append(player)
                        result["players"] = players
                        break

        # Open orders lookup (SC format)
        if self.open_orders_df is not None:
            email_cols_orders = ["User Email", "Email", "account_email"]
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
                                "order_no": str(row.get("Order No", row.get("receipt", ""))),
                                "balance": float(row.get("Balance", row.get("outstanding", 0)) or 0),
                                "status": str(row.get("Payment Status", row.get("payment_status", ""))),
                            })
                        result["open_orders"] = orders

        # Waitlist lookup (PlayMetrics waitlist export)
        if self.waitlist_df is not None and "account_email" in self.waitlist_df.columns:
            matches = self.waitlist_df[
                self.waitlist_df["account_email"].astype(str).str.lower().str.strip() == email_lower
            ]
            if not matches.empty:
                result["found"] = True
                entries = []
                for _, row in matches.iterrows():
                    entries.append({
                        "player": f"{row.get('player_first_name', '')} {row.get('player_last_name', '')}".strip(),
                        "division": str(row.get("package_name", row.get("Division", ""))),
                        "age_group": str(row.get("age_group", "")),
                        "status": str(row.get("status", "")),
                        "joined_waitlist": str(row.get("registered_on", "")),
                    })
                result["waitlist"] = entries

        # All-players lookup (broader contact info — address, parent2, phone)
        if self.all_players_df is not None and "players" not in result:
            email_cols_ap = ["parent1_email", "parent2_email"]
            for col in email_cols_ap:
                if col in self.all_players_df.columns:
                    matches = self.all_players_df[
                        self.all_players_df[col].astype(str).str.lower().str.strip() == email_lower
                    ]
                    if not matches.empty:
                        result["found"] = True
                        if "players" not in result:
                            players = []
                            for _, row in matches.iterrows():
                                players.append({
                                    "name": f"{row.get('player_first_name', '')} {row.get('player_last_name', '')}".strip(),
                                    "division": str(row.get("age_group", "")),
                                    "parent": f"{row.get('parent1_first_name', '')} {row.get('parent1_last_name', '')}".strip(),
                                    "phone": str(row.get("parent1_mobile_number", "")),
                                    "address": f"{row.get('street', '')}, {row.get('city', '')}, {row.get('state', '')} {row.get('zip', '')}".strip(", "),
                                })
                            result["all_players"] = players
                        break

        # Player contacts lookup (contact_id, additional contacts, phone)
        if self.player_contacts_df is not None:
            email_col_pc = "contact_email" if "contact_email" in self.player_contacts_df.columns else None
            if email_col_pc:
                matches = self.player_contacts_df[
                    self.player_contacts_df[email_col_pc].astype(str).str.lower().str.strip() == email_lower
                ]
                if not matches.empty:
                    result["found"] = True
                    contacts = []
                    for _, row in matches.iterrows():
                        contacts.append({
                            "contact_id": str(row.get("contact_id", "")),
                            "contact_name": f"{row.get('contact_first_name', '')} {row.get('contact_last_name', '')}".strip(),
                            "contact_phone": str(row.get("contact_phone", "")),
                            "player_name": f"{row.get('player_first_name', '')} {row.get('player_last_name', '')}".strip(),
                            "player_id": str(row.get("player_id", "")),
                            "relationship": str(row.get("relationship", "")),
                        })
                    result["player_contacts"] = contacts

        # Campaign tracking lookup
        campaign_sent = self.campaign_data.get("sent_emails", {})
        if email_lower in campaign_sent:
            result["found"] = True
            sent_info = campaign_sent[email_lower]
            result["campaign"] = {
                "heads_up_sent": True,
                "sent_at": sent_info.get("sent_at", ""),
                "player_names": sent_info.get("player_names", ""),
            }
        elif campaign_sent:
            result["campaign"] = {"heads_up_sent": False}

        # Check if registered (in enrollment/responses data) vs just imported (in all-players only)
        if "players" in result:
            result["registration_status"] = "registered"
        elif "all_players" in result:
            result["registration_status"] = "imported_not_registered"
        else:
            result["registration_status"] = "unknown"

        return result

    def lookup_by_name(self, first_name: str, last_name: str) -> Dict[str, Any]:
        """Look up by player or parent name."""
        result: Dict[str, Any] = {"name": f"{first_name} {last_name}", "found": False}
        first_lower = first_name.lower().strip()
        last_lower = last_name.lower().strip()

        if self.enrollment_df is not None:
            # Column names vary by source — try both
            player_first_cols = ["Player First Name", "player_first_name"]
            player_last_cols = ["Player Last Name", "player_last_name"]
            acct_first_cols = ["Account First Name", "account_first_name"]
            acct_last_cols = ["Account Last Name", "account_last_name"]

            def _try_match(first_cols, last_cols):
                for fc in first_cols:
                    for lc in last_cols:
                        if fc in self.enrollment_df.columns and lc in self.enrollment_df.columns:
                            m = self.enrollment_df[
                                (self.enrollment_df[fc].astype(str).str.lower().str.strip() == first_lower)
                                & (self.enrollment_df[lc].astype(str).str.lower().str.strip() == last_lower)
                            ]
                            if not m.empty:
                                return m
                return pd.DataFrame()

            matches = _try_match(player_first_cols, player_last_cols)
            if matches.empty:
                matches = _try_match(acct_first_cols, acct_last_cols)

            if not matches.empty:
                result["found"] = True
                result["records"] = []
                for _, row in matches.iterrows():
                    player_first = row.get("Player First Name", row.get("player_first_name", ""))
                    player_last = row.get("Player Last Name", row.get("player_last_name", ""))
                    acct_first = row.get("Account First Name", row.get("account_first_name", ""))
                    acct_last = row.get("Account Last Name", row.get("account_last_name", ""))
                    result["records"].append({
                        "player": f"{player_first} {player_last}".strip(),
                        "parent": f"{acct_first} {acct_last}".strip(),
                        "division": str(row.get("Division Name", row.get("package_name", ""))),
                        "team": str(row.get("Team Name", row.get("team", ""))),
                        "payment_status": str(row.get("Order Payment Status", row.get("status", ""))),
                        "email": str(row.get("User Email", row.get("account_email", ""))),
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
            if reg_config:
                return {
                    "is_open": reg_config.get("is_open", False),
                    "season": reg_config.get("season", "Fall 2026"),
                    "platform": reg_config.get("platform", "PlayMetrics"),
                    "registration_url": reg_config.get("registration_url", ""),
                    "invitation_sender": reg_config.get("invitation_sender", "noreply@playmetrics.com"),
                    "invitation_subject": reg_config.get("invitation_subject", ""),
                    "confirmation_sender": reg_config.get("confirmation_sender", ""),
                    "fee": reg_config.get("fee", ""),
                    "early_bird_discount": reg_config.get("early_bird_discount", ""),
                    "refund_deadline": reg_config.get("refund_deadline", ""),
                    "expected_open_date": reg_config.get("expected_open_date", ""),
                    "message": reg_config.get("message", ""),
                }

        # Default: registration is NOT open (safer default)
        return {
            "is_open": False,
            "season": "Fall 2026",
            "platform": "PlayMetrics",
            "expected_open_date": "",
            "message": "",
        }

    def get_summary_context(self) -> str:
        """Return a short summary of available data for the system prompt."""
        parts = [f"Data source: {self._data_source}"]
        if self.enrollment_df is not None:
            div_col = "Division Name" if "Division Name" in self.enrollment_df.columns else "package_name"
            if div_col in self.enrollment_df.columns:
                parts.append(f"Registered players: {len(self.enrollment_df)} across "
                             f"{self.enrollment_df[div_col].nunique()} divisions")
            else:
                parts.append(f"Registered players: {len(self.enrollment_df)}")
        if self.all_players_df is not None:
            parts.append(f"All imported players: {len(self.all_players_df)}")
            unique_emails = self.all_players_df["parent1_email"].dropna().nunique() if "parent1_email" in self.all_players_df.columns else 0
            parts.append(f"Unique families: {unique_emails}")
        if self.player_contacts_df is not None:
            parts.append(f"Player contacts: {len(self.player_contacts_df)}")
        if self.open_orders_df is not None:
            parts.append(f"Payment records: {len(self.open_orders_df)}")
        campaign_sent = self.campaign_data.get("sent_emails", {})
        if campaign_sent:
            parts.append(f"Campaign emails sent: {len(campaign_sent)}")
        if self.waitlist_df is not None and len(self.waitlist_df):
            wl = f"Waitlist (PlayMetrics): {len(self.waitlist_df)} players"
            if "package_name" in self.waitlist_df.columns:
                by_div = self.waitlist_df["package_name"].value_counts().to_dict()
                wl += " (" + ", ".join(f"{d}: {n}" for d, n in by_div.items()) + ")"
            parts.append(wl)
        if self.season_details:
            parts.append("Season details: loaded")
        return "; ".join(parts) if parts else "No live data loaded."

    def get_campaign_summary(self) -> str:
        """Return campaign summary for the system prompt."""
        campaign = self.campaign_data
        if not campaign or not campaign.get("sent_emails"):
            return ""

        sent = campaign.get("sent_emails", {})
        failed = campaign.get("failed_emails", {})
        total = campaign.get("total_recipients", 0)
        sessions = campaign.get("send_sessions", [])

        # Count registered vs not (requires enrollment data)
        registered_count = 0
        if self.enrollment_df is not None:
            email_col = "User Email" if "User Email" in self.enrollment_df.columns else "account_email"
            if email_col in self.enrollment_df.columns:
                registered_emails = set(self.enrollment_df[email_col].astype(str).str.lower().str.strip())
                registered_count = len(set(sent.keys()) & registered_emails)

        return f"""
EMAIL CAMPAIGN STATUS:
- Campaign: {campaign.get('campaign_name', 'PlayMetrics Migration')}
- Total heads-up emails sent: {len(sent)}
- Delivery failures: {len(failed)}
- Families who have since registered: {registered_count}
- Families who have NOT yet registered: {len(sent) - registered_count}
- If a parent says they didn't get our email, check if their email is in our sent list. If it is, the email was delivered — check spam. If it's not, they may not have been in our import."""

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
            body = self._extract_body(msg["payload"], msg.get("id"))

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

    def _extract_body(self, payload: Dict, message_id: str = None) -> str:
        """Extract the best text body from a Gmail message payload.

        Walks the entire MIME tree. Prefers text/plain; falls back to
        text/html (converted to text) when no plain part exists. Handles
        single-part messages (html-only is common on iPhone), nested
        multipart trees, and parts whose content is stored as a separate
        attachment (body.attachmentId) rather than inline (body.data) —
        which Gmail does for longer bodies and which the old code dropped.
        """
        plain_chunks: List[str] = []
        html_chunks: List[str] = []

        def decode(part: Dict) -> str:
            body = part.get("body", {}) or {}
            data = body.get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            attach_id = body.get("attachmentId")
            if attach_id and message_id:
                return self._fetch_attachment_text(message_id, attach_id)
            return ""

        def walk(part: Dict):
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                text = decode(part)
                if text:
                    plain_chunks.append(text)
            elif mime == "text/html":
                text = decode(part)
                if text:
                    html_chunks.append(text)
            for child in part.get("parts", []) or []:
                walk(child)

        walk(payload)

        if plain_chunks:
            return "\n".join(plain_chunks).strip()
        if html_chunks:
            return self._html_to_text("\n".join(html_chunks)).strip()
        return ""

    def _fetch_attachment_text(self, message_id: str, attachment_id: str) -> str:
        """Fetch a body part stored as an attachment (large bodies use this)."""
        try:
            att = (
                self.service.users().messages().attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            data = att.get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Failed to fetch body attachment {attachment_id}: {e}")
        return ""

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Lightweight HTML→text for email bodies that have no plain-text part."""
        import html as html_module
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html_module.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
        return text.strip()

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

    def remove_label(self, message_id: str, label: str) -> bool:
        """Remove a label from a message. No-op (success) if the label doesn't exist."""
        try:
            labels = self.service.users().labels().list(userId="me").execute().get("labels", [])
            label_id = next((lbl["id"] for lbl in labels if lbl["name"] == label), None)
            if not label_id:
                return True  # label doesn't exist — nothing to remove
            self.service.users().messages().modify(
                userId="me", id=message_id, body={"removeLabelIds": [label_id]}
            ).execute()
            return True
        except Exception as e:
            logger.warning(f"Failed to remove label '{label}' from message {message_id}: {e}")
            return False


# ---------------------------------------------------------------------------
# Claude AI analyzer
# ---------------------------------------------------------------------------
class ClaudeEmailAnalyzer:
    """Analyzes inbound emails and generates draft responses using Claude API."""

    def __init__(self, api_key: str, data_context: RegistrarDataContext):
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "The 'anthropic' package is required for the inbox assistant. "
                "Install it with: pip install anthropic"
            ) from e
        self.api_key = api_key
        self.data_context = data_context
        self.client = anthropic.Anthropic(api_key=api_key)
        # The system prompt is stable for the lifetime of this analyzer (one
        # inbox run). It must stay byte-identical across emails so the API's
        # prompt cache gets hits — per-email data goes in the user message.
        self._system_prompt: Optional[str] = None

    @staticmethod
    def _load_knowledge_base() -> str:
        """Load curated knowledge files (data/knowledge/**/*.md) for the prompt."""
        kb_dir = Path(KNOWLEDGE_DIR)
        if not kb_dir.exists():
            return ""
        sections = []
        for path in sorted(kb_dir.rglob("*.md")):
            try:
                text = path.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning(f"Could not read knowledge file {path}: {e}")
                continue
            if text:
                sections.append(f"--- {path.relative_to(kb_dir)} ---\n{text}")
        if not sections:
            return ""
        return (
            "\n\nKNOWLEDGE BASE (curated PlayMetrics/AYSO reference — treat as authoritative):\n"
            + "\n\n".join(sections)
        )

    def get_system_prompt(self) -> str:
        """Stable system prompt, built once per run and reused for every email."""
        if self._system_prompt is None:
            self._system_prompt = self._build_system_prompt()
        return self._system_prompt

    def _build_system_prompt(self) -> str:
        """Build the stable system prompt: data context, knowledge base, learned style."""
        data_summary = self.data_context.get_summary_context()

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
        platform = reg_status.get("platform", "PlayMetrics")

        if reg_status.get("is_open") and platform == "PlayMetrics":
            fee = reg_status.get("fee", "$205 + $25 NPF")
            early_bird = reg_status.get("early_bird_discount", "")
            refund = reg_status.get("refund_deadline", "")
            inv_sender = reg_status.get("invitation_sender", "noreply@playmetrics.com")
            inv_subject = reg_status.get("invitation_subject", "Sign Up For Player Access to AYSO Region 58")
            conf_sender = reg_status.get("confirmation_sender", "noreply@ayso58.playmetrics.com")
            early_bird_line = f"\n- Early bird discount: {early_bird}" if early_bird else ""
            refund_line = f"\n- Refund policy: {refund}" if refund else ""

            reg_status_section = f"""
REGISTRATION STATUS: **OPEN ON PLAYMETRICS** (new platform for Fall 2026)
- We have migrated from SportsConnect to PlayMetrics for registration
- Fee: {fee}{early_bird_line}{refund_line}
- Everyone who registers plays — there are no tryouts
- The PlayMetrics app is available on iOS and Android and works great for registration

INVITATION LINK FLOW (for returning families):
- Returning families from 2023-2025 received an invitation email from {inv_sender}
- Subject line: "{inv_subject}"
- The email contains a unique Sign Up button that connects them to their pre-loaded account
- They click the link, create a password, and their player info + birth certificate status is already there
- They must use THIS link — if they create a new account instead, they lose their BC-verified status and have to re-upload
- Confirmation emails come from {conf_sender}

COMMON PLAYMETRICS ISSUES:
- "I can't find the invitation email" → Check spam/junk folder for emails from {inv_sender}. We can resend the invitation — just ask.
- "I created a new account instead of using the link" → Their birth certificate status won't carry over. They'll need to re-upload their BC. Direct them to registrar@ayso58.org for help.
- "The link doesn't work / expired" → We can resend a fresh invitation. Ask them to reply and we'll trigger a new one.
- "I don't see any programs" → They may have created a new account instead of using their invitation link. Ask if they used the link from the email.
- "How do I register a second child?" → During registration, after the first player, there's an option to add another player before checkout.
- "Can I sign up as a volunteer/coach?" → Volunteer positions (Head Coach, Assistant Coach, Referee, Board Member) are offered during registration. Coaches can also sign up after registration via the Coach Request Link. Route follow-up questions by role: coaches → coachadmin@ayso58.org, referees → refadmin@ayso58.org, all other volunteer roles (team manager, field setup, board, etc.) → volcoordinator@ayso58.org.
- "How do I see my registration details?" → They received a confirmation email with all their answers. They can also log in to PlayMetrics to view their account.

NEW FAMILIES (no invitation):
- New families who were not in our previous system can register directly at the public registration link
- They create a new account, add their player(s), and complete registration
- They will need to upload a birth certificate for age verification
- Direct them to the registration link or tell them to look for announcements on our social media and website"""

        elif reg_status.get("is_open"):
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
{self.data_context.get_campaign_summary()}

SEASON & SCHEDULE DETAILS:
{self.data_context.season_details if self.data_context.season_details else "No season details loaded."}
{self._load_knowledge_base()}
{style_section}

RESPONSE GUIDELINES:
1. Be warm, professional, and helpful — these are volunteer-run youth sports parents
2. Use specific data from the sender context when available (player names, divisions, registration status)
3. If you don't have the data to answer precisely, acknowledge the question and say the registrar will look into it
4. For payment questions: reference exact amounts if available; the fee is $205 + $25 NPF. Registration and payment are handled through PlayMetrics.
5. For invitation link issues: always offer to resend, tell them to check spam for noreply@playmetrics.com, and emphasize NOT to create a new account
6. For team placement: ONLY state a player's division if it appears in the sender data lookup. NEVER guess a division based on a child's age — division placement depends on birth date and season-specific age cutoffs, not simply the child's current age. If you don't have division data, just say divisions are determined by birth date and they'll see the correct placement during registration.
7. Never share other families' information
8. Keep responses concise — 2-4 short paragraphs max
9. Match the registrar's actual writing style and voice as closely as possible
10. For duplicate account issues: be empathetic, explain the BC re-upload requirement, and offer to help
11. NEVER reference SportsConnect for registration — we have fully migrated to PlayMetrics. Only mention SC if a parent asks about historical data.

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

        system_prompt = self.get_system_prompt()
        user_message = self._format_email_for_analysis(email_data, sender_context)

        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            )
            logger.debug(
                "Claude usage: input=%s, cache_write=%s, cache_read=%s",
                response.usage.input_tokens,
                response.usage.cache_creation_input_tokens,
                response.usage.cache_read_input_tokens,
            )

            # Extract text from response
            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text

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

    def _format_email_for_analysis(self, email_data: Dict, sender_context: Dict = None) -> str:
        """Format email data (plus per-sender lookup data) for Claude's analysis.

        Sender data lives here rather than in the system prompt so the system
        prompt stays byte-identical across emails and the prompt cache hits.
        """
        body = email_data.get("body", "")
        # Truncate very long emails
        if len(body) > 3000:
            body = body[:3000] + "\n\n[... email truncated ...]"

        sender_section = ""
        if sender_context and sender_context.get("found"):
            sender_section = (
                f"\nSENDER DATA (from our records):\n"
                f"{json.dumps(sender_context, indent=2, default=str)}\n"
            )

        return f"""Analyze the following email received by the AYSO Region 58 registrar and draft a response.
{sender_section}
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

    def _matching_ids(self, days: Optional[int]) -> List[str]:
        """Message IDs in the processed log, optionally limited to the last N days."""
        processed = self._log.get("processed", {})
        if days is None:
            return list(processed.keys())
        cutoff = datetime.now() - timedelta(days=days)
        ids = []
        for mid, entry in processed.items():
            try:
                when = datetime.fromisoformat(entry.get("processed_at", ""))
            except (ValueError, TypeError):
                when = None
            if when is None or when >= cutoff:  # keep undated entries to be safe
                ids.append(mid)
        return ids

    def count_processed(self, days: Optional[int] = None) -> int:
        return len(self._matching_ids(days))

    def reset(self, days: Optional[int] = None) -> List[str]:
        """Remove processed entries (and their saved draft analyses).

        Args:
            days: Only reset entries processed within the last N days; None = all.

        Returns:
            The message IDs that were reset (so Gmail labels can be cleaned up).
        """
        reset_ids = self._matching_ids(days)
        processed = self._log.get("processed", {})
        for mid in reset_ids:
            processed.pop(mid, None)
            draft_file = self.drafts_dir / f"{mid}.json"
            if draft_file.exists():
                try:
                    draft_file.unlink()
                except Exception as e:
                    logger.warning(f"Could not delete draft file {draft_file}: {e}")
        self._log["processed"] = processed
        stats = self._log.setdefault("stats", {})
        stats["total_processed"] = len(processed)
        stats["total_drafts"] = sum(1 for e in processed.values() if e.get("draft_id"))
        self._save()
        return reset_ids

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

    def reset_processed(self, days: Optional[int] = None, untag: bool = True) -> Dict[str, Any]:
        """Clear local processed state so emails are re-analyzed on the next run.

        Args:
            days: Only reset entries processed within the last N days; None = all.
            untag: Also remove the 'AI-Processed' Gmail label from the reset messages.

        Returns:
            {"reset": n, "untagged": n, "untag_failed": n}
        """
        reset_ids = self.log.reset(days=days)
        result = {"reset": len(reset_ids), "untagged": 0, "untag_failed": 0}
        if not reset_ids:
            return result
        logger.info(f"Reset {len(reset_ids)} processed entries (and their draft analyses).")
        if untag:
            if self.gmail.authenticate():
                for mid in reset_ids:
                    if self.gmail.remove_label(mid, "AI-Processed"):
                        result["untagged"] += 1
                    else:
                        result["untag_failed"] += 1
                logger.info(f"Removed 'AI-Processed' from {result['untagged']} messages.")
            else:
                logger.warning("Gmail auth failed — skipped untagging; local state still reset.")
        return result

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
        import anthropic

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
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4000,
                messages=[
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
            )

            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text

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

    # Handle --inbox-reset: clear processed state so emails get re-analyzed
    reset_val = getattr(args, "inbox_reset", None)
    if reset_val is not None:
        if reset_val == "all":
            days = None
        else:
            try:
                days = int(reset_val)
            except (ValueError, TypeError):
                print(f"Invalid --inbox-reset value: {reset_val!r}. Use a number of days, or omit for all.")
                return 1
        n = assistant.log.count_processed(days=days)
        scope = "ALL processed emails" if days is None else f"emails processed in the last {days} day(s)"
        if n == 0:
            print(f"Nothing to reset ({scope}).")
            return 0
        untag = not getattr(args, "inbox_reset_keep_label", False)
        print(f"This will reset {n} {scope}:")
        print("  - remove them from the local processing log")
        print("  - delete their saved draft analyses (data/inbox_assistant/drafts/)")
        if untag:
            print("  - remove the 'AI-Processed' Gmail label from those messages")
        print("NOTE: existing Gmail drafts are NOT deleted — remove wrong ones manually.")
        resp = input("Proceed? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.")
            return 0
        result = assistant.reset_processed(days=days, untag=untag)
        msg = f"\nReset {result['reset']} entries."
        if untag:
            msg += f" Untagged {result['untagged']} messages."
            if result["untag_failed"]:
                msg += f" ({result['untag_failed']} untag failures — see log.)"
        print(msg)
        print("Re-run `python src\\main.py --inbox` to regenerate drafts.")
        return 0

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