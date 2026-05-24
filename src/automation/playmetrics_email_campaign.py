
"""
PlayMetrics Email Campaign Manager for AYSO Region 58
Sends heads-up emails to imported families and tracks registration conversion.

Data sources:
  - PM All Players export (all-players.csv) → recipient list
  - PM Export Responses (Player_registration_questions_export.csv) → registered players
  - PM Player Contacts export (all-player-contacts.csv) → contact_id cross-reference

Usage (via main.py):
  python main.py --pm-campaign                    # Interactive campaign send
  python main.py --pm-campaign --pm-test          # Test mode (no emails sent)
  python main.py --pm-campaign-status             # Show campaign + registration status
  python main.py --pm-campaign-status --pm-export # Export registration tracking to CSV
"""

import os
import csv
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime, date

import pandas as pd

from automation.waitlist_notifier import WaitlistNotifier
from core.config import ConfigManager

logger = logging.getLogger(__name__)

# Gmail daily send limit for Google Workspace
GMAIL_DAILY_LIMIT = 2000

# Default campaign template
DEFAULT_HEADSUP_TEMPLATE = """Dear AYSO Region 58 Families,

Thank you for your patience as we finalized the details of our new registration system. Please read the information below to learn about the transition.

Registration: We are moving to PlayMetrics for our Fall 2026 season and will no longer be using SportsConnect. To make the transition as easy as possible, we have already imported your information into PlayMetrics. There is no need to create a new account. Instead, you will receive an invitation email from noreply@reg.playmetrics.com within the next 48 hours. The subject line will be "Sign Up for Player Access to AYSO Region 58." This is not a spam email. That email will contain a unique link that will connect you to your PlayMetrics account. You just need to create a password and complete your player's registration for fall 2026.

You must register using this unique link directly from PlayMetrics. If you do not use the link and instead create a new account, you will need to upload your player's birth certificate again.

If you have questions, please email our Registrar, Steve Davis, at registrar@ayso58.org."""


class PlayMetricsCampaign:
    """Manages the PlayMetrics migration email campaign with registration tracking."""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.notifier = WaitlistNotifier(config)

        # Campaign tracking directory (separate from SC batch tracking)
        self.tracking_dir = Path(
            config.get("email_batch_config", {}).get("tracking_dir", "data/email_batch_tracking")
        ).parent / "pm_campaign_tracking"
        self.tracking_dir.mkdir(parents=True, exist_ok=True)

        # Campaign state file — single file for the whole campaign
        self.campaign_file = self.tracking_dir / "campaign_state.json"
        self.campaign_state = self._load_campaign_state()

        # Rate limit config
        batch_cfg = config.get("email_batch_config", {})
        rate_cfg = batch_cfg.get("rate_limit", {})
        self.delay_between_emails = rate_cfg.get("delay_between_emails", 2)
        self.max_per_day = min(rate_cfg.get("max_per_day", 2000), GMAIL_DAILY_LIMIT)

        # Sender config
        sender_cfg = batch_cfg.get("sender_info", {})
        email_cfg = config.get("email_config", {})
        self.sender_name = sender_cfg.get("name", email_cfg.get("sender_name", "AYSO Region 58 Registrar"))
        self.sender_email = email_cfg.get("sender_email", "registrar@ayso58.org")
        self.reply_to = sender_cfg.get("reply_to", email_cfg.get("reply_to", "registrar@ayso58.org"))

    # ── Campaign state ──────────────────────────────────────────────────

    def _load_campaign_state(self) -> Dict:
        """Load or initialize campaign state."""
        if self.campaign_file.exists():
            try:
                with open(self.campaign_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load campaign state: {e}")

        return {
            "campaign_name": "PlayMetrics Migration - Fall 2026",
            "created": datetime.now().isoformat(),
            "sent_emails": {},  # email → {sent_at, player_names, status}
            "failed_emails": {},  # email → {failed_at, error}
            "send_sessions": [],  # [{date, count, session_id}]
            "total_recipients": 0,
            "template_subject": "",
            "template_hash": "",
        }

    def _save_campaign_state(self):
        """Persist campaign state."""
        try:
            with open(self.campaign_file, "w", encoding="utf-8") as f:
                json.dump(self.campaign_state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save campaign state: {e}")

    @property
    def sent_emails(self) -> Set[str]:
        return set(self.campaign_state.get("sent_emails", {}).keys())

    # ── Data loading ────────────────────────────────────────────────────

    def load_recipients(self, csv_path: str) -> pd.DataFrame:
        """
        Load recipient list from PM All Players export.

        Deduplicates by parent1_email — one email per family.

        Returns DataFrame with columns:
            parent1_email, parent1_first_name, parent1_last_name,
            player_names (comma-separated), player_count
        """
        logger.info(f"Loading recipients from: {csv_path}")
        df = pd.read_csv(csv_path)

        # Clean emails
        df["parent1_email"] = df["parent1_email"].astype(str).str.strip().str.lower()
        df = df[df["parent1_email"].notna() & (df["parent1_email"] != "") & (df["parent1_email"] != "nan")]

        # Aggregate players per parent email
        grouped = (
            df.groupby("parent1_email")
            .agg(
                parent1_first_name=("parent1_first_name", "first"),
                parent1_last_name=("parent1_last_name", "first"),
                player_names=("player_first_name", lambda x: ", ".join(x.dropna().unique())),
                player_count=("player_first_name", "nunique"),
            )
            .reset_index()
        )

        logger.info(f"Loaded {len(grouped)} unique family email addresses from {len(df)} player records")
        self.campaign_state["total_recipients"] = len(grouped)
        self._save_campaign_state()
        return grouped

    def load_registered(self, csv_path: str) -> Set[str]:
        """
        Load registered emails from PM Export Responses CSV.

        Returns set of lowercase emails that have completed registration.
        """
        logger.info(f"Loading registered players from: {csv_path}")
        df = pd.read_csv(csv_path)

        email_col = "account_email" if "account_email" in df.columns else "User Email"
        if email_col not in df.columns:
            logger.warning(f"Could not find email column in {csv_path}. Columns: {list(df.columns)}")
            return set()

        registered = set(df[email_col].astype(str).str.strip().str.lower().unique())
        registered.discard("")
        registered.discard("nan")
        logger.info(f"Found {len(registered)} registered email addresses")
        return registered

    # ── Email preparation ───────────────────────────────────────────────

    def _load_opt_outs(self) -> Set[str]:
        """Load opt-out emails from file."""
        opt_out_file = self.tracking_dir / "opt_out.txt"
        if opt_out_file.exists():
            with open(opt_out_file, "r", encoding="utf-8") as f:
                return set(
                    line.strip().lower() for line in f 
                    if line.strip() and not line.startswith("#")
                )
        return set()
    
    def prepare_send_list(
        self, recipients_df: pd.DataFrame, exclude_sent: bool = True
    ) -> List[Dict]:
        """
        Prepare the send list, excluding already-sent emails.

        Returns list of dicts ready for sending.
        """
        records = []
        opt_outs = self._load_opt_outs()

        for _, row in recipients_df.iterrows():
            email = row["parent1_email"]

            if exclude_sent and email in self.sent_emails:
                continue
            if email in opt_outs:
                continue
            
            records.append(
                {
                    "email": email,
                    "parent_first_name": str(row.get("parent1_first_name", "")).strip(),
                    "parent_last_name": str(row.get("parent1_last_name", "")).strip(),
                    "player_names": str(row.get("player_names", "")).strip(),
                    "player_count": int(row.get("player_count", 1)),
                }
            )

        logger.info(
            f"Send list: {len(records)} remaining "
            f"({len(self.sent_emails)} already sent, "
            f"{len(recipients_df) - len(records) - len(self.sent_emails)} excluded)"
        )
        return records

    def format_email(self, record: Dict, template: str, subject: str) -> Tuple[str, str]:
        """
        Format the email with recipient-specific variables.

        Supported placeholders:
            {parentFirstName}, {parentLastName}, {playerNames}, {playerCount}
        """

        # Fallback for missing/bad names
        parent_name = record["parent_first_name"]
        if not parent_name or len(parent_name) < 2:
            parent_name = "AYSO Region 58 Family"

        replacements = {
            "{parentFirstName}": parent_name,
            "{parentLastName}": record["parent_last_name"],
            "{playerNames}": record["player_names"],
            "{playerCount}": str(record["player_count"]),
        }

        body = template
        formatted_subject = subject
        for key, value in replacements.items():
            body = body.replace(key, value)
            formatted_subject = formatted_subject.replace(key, value)

        return formatted_subject, body

    # ── Sending ─────────────────────────────────────────────────────────

    def send_campaign(
        self,
        send_list: List[Dict],
        template: str,
        subject: str,
        test_mode: bool = False,
        daily_limit: int = None,
        batch_confirm: bool = True,
    ) -> Dict:
        """
        Send campaign emails with rate limiting and daily cap.

        Args:
            send_list: Prepared recipient list
            template: Email body template
            subject: Email subject line
            test_mode: If True, log but don't send
            daily_limit: Override daily send limit
            batch_confirm: If True, pause every 50 emails for confirmation

        Returns:
            Stats dict with sent/failed/remaining counts
        """
        limit = daily_limit or self.max_per_day
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        sent_count = 0
        failed_count = 0
        skipped_count = 0

        self.campaign_state["template_subject"] = subject

        # Respect daily limit
        today_sends = sum(
            1
            for info in self.campaign_state.get("sent_emails", {}).values()
            if info.get("sent_at", "").startswith(date.today().isoformat())
        )
        remaining_today = limit - today_sends

        if remaining_today <= 0:
            logger.warning(f"Daily limit reached ({limit}). Already sent {today_sends} today.")
            return {"sent": 0, "failed": 0, "remaining": len(send_list), "daily_limit_hit": True}

        to_send = send_list[:remaining_today]
        logger.info(
            f"Sending {len(to_send)} of {len(send_list)} "
            f"(daily limit: {limit}, already sent today: {today_sends})"
        )

        for i, record in enumerate(to_send):
            try:
                formatted_subject, body = self.format_email(record, template, subject)

                if test_mode:
                    logger.info(f"[TEST {i+1}/{len(to_send)}] Would send to {record['email']}")
                    logger.debug(f"  Subject: {formatted_subject}")
                    logger.debug(f"  Body preview: {body[:120]}...")
                    sent_count += 1
                    # Track even in test mode for dry-run visibility
                    continue

                # Send via Gmail OAuth2
                success = self.notifier.send_email(
                    record["email"],
                    formatted_subject,
                    body
                )

                if success:
                    self.campaign_state["sent_emails"][record["email"]] = {
                        "sent_at": datetime.now().isoformat(),
                        "player_names": record["player_names"],
                        "parent_name": f"{record['parent_first_name']} {record['parent_last_name']}",
                        "session_id": session_id,
                    }
                    sent_count += 1
                    logger.info(f"✓ [{i+1}/{len(to_send)}] {record['email']}")
                else:
                    self.campaign_state["failed_emails"][record["email"]] = {
                        "failed_at": datetime.now().isoformat(),
                        "error": "send_message returned False",
                    }
                    failed_count += 1
                    logger.error(f"✗ [{i+1}/{len(to_send)}] {record['email']}")

                # Rate limiting
                if i < len(to_send) - 1:
                    time.sleep(self.delay_between_emails)

                # Periodic save
                if (i + 1) % 25 == 0:
                    self._save_campaign_state()
                    logger.info(f"  Progress: {sent_count} sent, {failed_count} failed")

                # Batch confirmation pause
                if batch_confirm and (i + 1) % 500 == 0 and i < len(to_send) - 1:
                    self._save_campaign_state()
                    remaining = len(to_send) - (i + 1)
                    cont = input(f"\n  {sent_count} sent so far. Continue with {remaining} remaining? (y/n): ")
                    if cont.lower() != "y":
                        logger.info("Send paused by user")
                        break

            except Exception as e:
                self.campaign_state["failed_emails"][record["email"]] = {
                    "failed_at": datetime.now().isoformat(),
                    "error": str(e),
                }
                failed_count += 1
                logger.error(f"✗ [{i+1}/{len(to_send)}] {record['email']}: {e}")

        # Record session
        self.campaign_state["send_sessions"].append(
            {
                "session_id": session_id,
                "date": datetime.now().isoformat(),
                "sent": sent_count,
                "failed": failed_count,
                "test_mode": test_mode,
            }
        )
        self._save_campaign_state()

        remaining = len(send_list) - sent_count
        stats = {
            "sent": sent_count,
            "failed": failed_count,
            "remaining": remaining,
            "daily_limit_hit": sent_count >= remaining_today,
            "session_id": session_id,
        }

        logger.info(f"Session complete: {sent_count} sent, {failed_count} failed, {remaining} remaining")
        if stats["daily_limit_hit"]:
            logger.info(f"Daily limit reached. Run again tomorrow to send the remaining {remaining}.")

        return stats

    # ── Registration tracking ───────────────────────────────────────────

    def get_registration_status(self, registered_emails: Set[str]) -> Dict:
        """
        Cross-reference sent emails against registered emails.

        Returns:
            Dict with conversion stats and lists of registered/unregistered families
        """
        sent = self.campaign_state.get("sent_emails", {})
        if not sent:
            return {"error": "No emails have been sent yet."}

        sent_set = set(sent.keys())
        registered_from_campaign = sent_set & registered_emails
        not_yet_registered = sent_set - registered_emails

        # Build detailed lists
        registered_list = []
        for email in sorted(registered_from_campaign):
            info = sent.get(email, {})
            registered_list.append(
                {
                    "email": email,
                    "parent_name": info.get("parent_name", ""),
                    "player_names": info.get("player_names", ""),
                    "sent_at": info.get("sent_at", ""),
                }
            )

        not_registered_list = []
        for email in sorted(not_yet_registered):
            info = sent.get(email, {})
            not_registered_list.append(
                {
                    "email": email,
                    "parent_name": info.get("parent_name", ""),
                    "player_names": info.get("player_names", ""),
                    "sent_at": info.get("sent_at", ""),
                }
            )

        total_sent = len(sent_set)
        total_registered = len(registered_from_campaign)
        conversion_rate = (total_registered / total_sent * 100) if total_sent else 0

        return {
            "total_sent": total_sent,
            "total_registered": total_registered,
            "total_not_registered": len(not_yet_registered),
            "total_failed": len(self.campaign_state.get("failed_emails", {})),
            "conversion_rate": round(conversion_rate, 1),
            "registered": registered_list,
            "not_registered": not_registered_list,
            "sessions": self.campaign_state.get("send_sessions", []),
        }

    def export_tracking(self, registered_emails: Set[str], output_path: str = None) -> str:
        """Export registration tracking to CSV."""
        if not output_path:
            output_path = str(
                self.tracking_dir / f"registration_tracking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )

        sent = self.campaign_state.get("sent_emails", {})
        rows = []
        for email, info in sorted(sent.items()):
            rows.append(
                {
                    "email": email,
                    "parent_name": info.get("parent_name", ""),
                    "player_names": info.get("player_names", ""),
                    "sent_at": info.get("sent_at", ""),
                    "registered": "Yes" if email in registered_emails else "No",
                }
            )

        df = pd.DataFrame(rows)
        df.to_csv(output_path, index=False)
        logger.info(f"Exported tracking data to {output_path}")
        return output_path


# ── CLI ─────────────────────────────────────────────────────────────────

class PlayMetricsCampaignCLI:
    """Command-line interface for the PM email campaign."""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.campaign = PlayMetricsCampaign(config)

    def run_send(self, test_mode: bool = False):
        """Interactive campaign send flow."""
        print("\n" + "=" * 60)
        print("PlayMetrics Migration Email Campaign")
        print("=" * 60)

        # Show existing campaign state
        sent_count = len(self.campaign.sent_emails)
        if sent_count:
            print(f"\nExisting campaign: {sent_count} emails already sent")

        # Load recipients
        default_path = "data/all-players.csv"
        csv_path = input(f"\nPath to PM All Players CSV [{default_path}]: ").strip() or default_path

        if not os.path.exists(csv_path):
            print(f"Error: File not found: {csv_path}")
            return

        recipients_df = self.campaign.load_recipients(csv_path)
        send_list = self.campaign.prepare_send_list(recipients_df)

        print(f"\nTotal families: {len(recipients_df)}")
        print(f"Already sent: {sent_count}")
        print(f"To send: {len(send_list)}")
        print(f"Daily limit: {self.campaign.max_per_day}")

        if not send_list:
            print("\nAll emails have been sent!")
            return

        # Template
        print("\n" + "-" * 40)
        print("Email Template")
        print("-" * 40)

        template_path = self.campaign.tracking_dir / "campaign_template.html"

        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
            print(f"Loaded saved template from {template_path}")
            print(f"Preview:\n{template[:200]}...")
            use_saved = input("\nUse this template? (y/n): ").lower() == "y"
            if not use_saved:
                template = None
        else:
            template = None

        if template is None:
            print("\nOptions:")
            print("  1. Use default heads-up template")
            print("  2. Load from file")
            print("  3. Enter custom text")

            choice = input("\nChoice [1]: ").strip() or "1"

            if choice == "1":
                template = DEFAULT_HEADSUP_TEMPLATE
            elif choice == "2":
                path = input("Template file path: ").strip()
                with open(path, "r", encoding="utf-8") as f:
                    template = f.read()
            else:
                print("Enter template (end with blank line):")
                lines = []
                while True:
                    line = input()
                    if not line:
                        break
                    lines.append(line)
                template = "\n".join(lines)

            # Save template for future runs
            with open(template_path, "w", encoding="utf-8") as f:
                f.write(template)

        # Subject
        default_subject = "AYSO Region 58 — Important Registration Update for Fall 2026"
        subject = input(f"\nSubject [{default_subject}]: ").strip() or default_subject

        # Sender info
        print(f"\nSending from: {self.campaign.sender_name} <{self.campaign.sender_email}>")
        print(f"Reply-to: {self.campaign.reply_to}")

        # Test mode
        if test_mode:
            print("\n*** TEST MODE — no emails will be sent ***")

        # Preview
        print("\n" + "-" * 40)
        print("Preview (first recipient):")
        print("-" * 40)
        preview_subj, preview_body = self.campaign.format_email(send_list[0], template, subject)
        print(f"To: {send_list[0]['email']}")
        print(f"Subject: {preview_subj}")
        print(f"\n{preview_body[:300]}...")

        # Send test copy to admin
        if test_mode:
            test_email = self.config.get("email_batch_config", {}).get(
                "test_recipients", ["sdavis@davisportal.com"]
            )[0]
            send_proof = input(f"\nSend proof copy to {test_email}? (y/n): ").lower()
            if send_proof == "y":
                success = self.campaign.notifier.send_email(
                    test_email,
                    preview_subj,
                    preview_body
                )
                if success:
                    print(f"✓ Proof sent to {test_email}")
                else:
                    print(f"✗ Failed to send proof to {test_email}")
                    
        # Confirm
        print(f"\n{'TEST ' if test_mode else ''}Ready to send {min(len(send_list), self.campaign.max_per_day)} emails")
        confirm = input("Proceed? (y/n): ").lower()
        if confirm != "y":
            print("Cancelled.")
            return

        # Send
        stats = self.campaign.send_campaign(
            send_list, template, subject, test_mode=test_mode
        )

        # Summary
        print("\n" + "=" * 60)
        print("SESSION SUMMARY")
        print("=" * 60)
        print(f"Sent: {stats['sent']}")
        print(f"Failed: {stats['failed']}")
        print(f"Remaining: {stats['remaining']}")
        if stats.get("daily_limit_hit"):
            print(f"\nDaily limit reached. Run again tomorrow for the remaining {stats['remaining']}.")

    def run_status(self, export: bool = False):
        """Show campaign status and registration conversion."""
        print("\n" + "=" * 60)
        print("PlayMetrics Campaign Status")
        print("=" * 60)

        sent_count = len(self.campaign.sent_emails)
        failed_count = len(self.campaign.campaign_state.get("failed_emails", {}))
        total = self.campaign.campaign_state.get("total_recipients", 0)

        print(f"\nCampaign: {self.campaign.campaign_state.get('campaign_name', 'Unknown')}")
        print(f"Total recipients: {total}")
        print(f"Sent: {sent_count}")
        print(f"Failed: {failed_count}")
        print(f"Remaining: {max(0, total - sent_count)}")

        # Sessions
        sessions = self.campaign.campaign_state.get("send_sessions", [])
        if sessions:
            print(f"\nSend sessions: {len(sessions)}")
            for s in sessions[-5:]:
                mode = " (TEST)" if s.get("test_mode") else ""
                print(f"  {s['date'][:16]} — {s['sent']} sent, {s['failed']} failed{mode}")

        # Registration tracking
        responses_path = input(
            "\nPath to PM Export Responses CSV (Enter to skip): "
        ).strip()

        if responses_path and os.path.exists(responses_path):
            registered = self.campaign.load_registered(responses_path)
            status = self.campaign.get_registration_status(registered)

            print(f"\n{'─' * 40}")
            print("REGISTRATION CONVERSION")
            print(f"{'─' * 40}")
            print(f"Emails sent: {status['total_sent']}")
            print(f"Registered: {status['total_registered']}")
            print(f"Not yet registered: {status['total_not_registered']}")
            print(f"Conversion rate: {status['conversion_rate']}%")

            if status["not_registered"]:
                print(f"\nTop unregistered families:")
                for r in status["not_registered"][:10]:
                    print(f"  {r['email']} — {r['parent_name']} ({r['player_names']})")
                if len(status["not_registered"]) > 10:
                    print(f"  ... and {len(status['not_registered']) - 10} more")

            if export:
                export_path = self.campaign.export_tracking(registered)
                print(f"\nExported to: {export_path}")
        else:
            if responses_path:
                print(f"File not found: {responses_path}")
            print("Skipping registration tracking.")


# ── Entry point for main.py ─────────────────────────────────────────────

def handle_pm_campaign(config: ConfigManager, args) -> int:
    """Handle PM campaign operations from command line."""
    logger.info("Starting PlayMetrics Campaign Manager")
    try:
        cli = PlayMetricsCampaignCLI(config)

        if getattr(args, "pm_campaign_status", False):
            export = getattr(args, "pm_export", False)
            cli.run_status(export=export)
        else:
            test_mode = getattr(args, "pm_test", False)
            cli.run_send(test_mode=test_mode)

        return 0
    except Exception as e:
        logger.error(f"Error in PM campaign manager: {e}")
        import traceback
        traceback.print_exc()
        return 1