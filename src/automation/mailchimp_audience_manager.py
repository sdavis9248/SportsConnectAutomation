"""
MailChimp Audience Manager for AYSO Region 58

Builds a MailChimp-import-ready audience of families who were imported into
PlayMetrics but have NOT yet registered / activated their account.

The PlayMetrics -> MailChimp native sync only pushes ACTIVATED accounts, so the
synced audience already covers registered families. This utility produces the
complement -- the not-yet-registered families -- as a CSV you upload to a
separate, manually-managed MailChimp audience (kept separate so the PM sync does
not reconcile manual contacts out of it).

    not_registered = (imported families) - (registered families)

Data sources (reuses PlayMetricsCampaign loaders, no logic duplication):
  - Universe   : PM All Players export (data/all-players.csv) -> deduped by parent1_email
  - Registered : either of
        * PM Export Responses (Player_registration_questions_export.csv), OR
        * a MailChimp export of the PM-synced audience (any "Email Address" column)
    The registered loader auto-detects the email column for both formats.

Output (MailChimp default field headers + merge fields):
    Email Address, First Name, Last Name, Players, Player Count

Usage (via main.py):
  python main.py --pm-mailchimp-audience
  python main.py --pm-mailchimp-audience --registered-csv data/all-players-contacts.csv
  python main.py --pm-mailchimp-audience \
      --recipients-csv data/all-players.csv \
      --registered-csv data/mailchimp_synced_export.csv \
      --audience-output data/mailchimp_not_registered.csv
"""

import os
import logging
from datetime import datetime
from typing import Set, Tuple, Optional, Dict

import pandas as pd

from core.config import ConfigManager
from automation.playmetrics_email_campaign import PlayMetricsCampaign

logger = logging.getLogger(__name__)

# Candidate email column names across PM and MailChimp export formats.
_REGISTERED_EMAIL_COLS = ["account_email", "User Email", "Email Address", "email", "Email"]


class MailChimpAudienceManager:
    """Builds the not-yet-registered MailChimp audience from PlayMetrics exports."""

    def __init__(self, config: ConfigManager):
        self.config = config
        # Reuse the canonical loaders so the universe/registered contracts stay in sync.
        self.campaign = PlayMetricsCampaign(config)

    # ── Registered set (PM responses OR MailChimp export) ────────────────

    def load_registered(self, csv_path: str) -> Set[str]:
        """
        Load the set of already-registered (activated) lowercase emails.

        Tries the PlayMetricsCampaign loader first (PM responses format). If that
        finds nothing -- e.g. the file is a MailChimp export whose column is
        "Email Address" -- falls back to direct column detection.
        """
        registered = self.campaign.load_registered(csv_path)
        if registered:
            return registered

        logger.info("PM-format load found no emails; trying MailChimp export format.")
        df = pd.read_csv(csv_path)
        col = next((c for c in _REGISTERED_EMAIL_COLS if c in df.columns), None)
        if not col:
            logger.warning(
                f"No recognizable email column in {csv_path}. Columns: {list(df.columns)}"
            )
            return set()
        registered = set(df[col].astype(str).str.strip().str.lower().unique())
        registered.discard("")
        registered.discard("nan")
        logger.info(f"Found {len(registered)} registered email addresses (MailChimp format)")
        return registered

    # ── Build ────────────────────────────────────────────────────────────

    def build(
        self,
        recipients_csv: str,
        registered_csv: str,
        output_path: Optional[str] = None,
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Build the not-yet-registered audience.

        Returns:
            (audience_df, stats) where audience_df has MailChimp import columns.
        """
        recipients = self.campaign.load_recipients(recipients_csv)  # deduped by parent1_email
        registered = self.load_registered(registered_csv)

        mask_not_registered = ~recipients["parent1_email"].isin(registered)
        not_reg = recipients[mask_not_registered].copy()

        audience = pd.DataFrame(
            {
                "Email Address": not_reg["parent1_email"],
                "First Name": not_reg["parent1_first_name"],
                "Last Name": not_reg["parent1_last_name"],
                "Players": not_reg["player_names"],
                "Player Count": not_reg["player_count"],
            }
        )
        audience = audience[audience["Email Address"].astype(str).str.strip() != ""]

        total = len(recipients)
        registered_count = total - len(not_reg)
        stats = {
            "total_families": total,
            "registered": registered_count,
            "not_registered": len(audience),
            "conversion_rate": round(registered_count / total * 100, 1) if total else 0.0,
        }

        if output_path is None:
            out_dir = self.config.get("output_dir", "data")
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(out_dir, f"mailchimp_not_registered_{ts}.csv")

        audience.to_csv(output_path, index=False)
        stats["output_path"] = output_path
        logger.info(
            f"Wrote {len(audience)} not-registered contacts to {output_path} "
            f"({stats['conversion_rate']}% already registered)"
        )
        return audience, stats


# ── CLI ──────────────────────────────────────────────────────────────────

class MailChimpAudienceCLI:
    """Command-line interface for building the MailChimp not-registered audience."""

    DEFAULT_RECIPIENTS = "data/all-players.csv"

    def __init__(self, config: ConfigManager):
        self.config = config
        self.manager = MailChimpAudienceManager(config)

    def run_build(self, recipients_csv: str = None, registered_csv: str = None,
                  output_path: str = None):
        print("\n" + "=" * 60)
        print("MailChimp Audience Builder — Not Yet Registered")
        print("=" * 60)

        recipients_csv = recipients_csv or input(
            f"\nPath to PM All Players CSV [{self.DEFAULT_RECIPIENTS}]: "
        ).strip() or self.DEFAULT_RECIPIENTS
        if not os.path.exists(recipients_csv):
            print(f"Error: recipients file not found: {recipients_csv}")
            return

        if not registered_csv:
            registered_csv = input(
                "Path to registered export (PM responses OR MailChimp synced export): "
            ).strip()
        if not registered_csv or not os.path.exists(registered_csv):
            print(f"Error: registered file not found: {registered_csv}")
            return

        audience, stats = self.manager.build(recipients_csv, registered_csv, output_path)

        print("\n" + "-" * 40)
        print(f"Total imported families:   {stats['total_families']}")
        print(f"Already registered:        {stats['registered']}")
        print(f"NOT yet registered:        {stats['not_registered']}")
        print(f"Conversion rate:           {stats['conversion_rate']}%")
        print(f"\nWrote: {stats['output_path']}")
        print(
            "\nNext: import this CSV into a SEPARATE MailChimp audience (not the PM-synced one).\n"
            "Map Email Address / First Name / Last Name to standard fields; Players /\n"
            "Player Count to custom fields. Re-run periodically — the list shrinks as\n"
            "families register."
        )


def handle_pm_mailchimp_audience(config: ConfigManager, args) -> int:
    """Handle MailChimp audience build operations from command line."""
    logger.info("Starting MailChimp Audience Manager")
    try:
        cli = MailChimpAudienceCLI(config)
        cli.run_build(
            recipients_csv=getattr(args, "recipients_csv", None),
            registered_csv=getattr(args, "registered_csv", None),
            output_path=getattr(args, "audience_output", None),
        )
        return 0
    except Exception as e:
        logger.error(f"Error in MailChimp audience manager: {e}")
        import traceback
        traceback.print_exc()
        return 1
