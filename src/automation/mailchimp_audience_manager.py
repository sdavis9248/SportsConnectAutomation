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

Data sources (self-contained; no Gmail/PlayMetricsCampaign dependency):
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
import json
import glob
import zipfile
import tempfile
import logging
from datetime import datetime
from typing import Set, Tuple, Optional, Dict, List

import pandas as pd

from core.config import ConfigManager

logger = logging.getLogger(__name__)


def _resolve_contacts_file(explicit: Optional[str] = None) -> Optional[str]:
    """
    Resolve the PlayMetrics Player Contacts CSV.

    If an explicit path is given and exists, use it. Otherwise auto-discover the
    newest timestamped export the downloader produces in data/playmetrics
    (player-contacts_<timestamp>.csv), with fallbacks for older/manual names.
    """
    if explicit and os.path.exists(explicit):
        return explicit
    pattern_groups = [
        "data/playmetrics/player-contacts_*.csv",
        "data/playmetrics/*player-contacts*.csv",
        "data/playmetrics/all-player-contacts*.csv",
        "data/all-player-contacts*.csv",
    ]
    for pat in pattern_groups:
        matches = glob.glob(pat)
        if matches:
            # Filenames carry a sortable _YYYYMMDD_HHMMSS stamp, so the lexically
            # greatest basename is the newest; mtime breaks ties for unstamped names.
            return max(matches, key=lambda p: (os.path.basename(p), os.path.getmtime(p)))
    return explicit  # nothing found; let the caller report the missing path

# Candidate email column names across PM and MailChimp export formats.
_REGISTERED_EMAIL_COLS = ["account_email", "User Email", "Email Address", "email", "Email"]


class MailChimpAudienceManager:
    """Builds the not-yet-registered MailChimp audience from PlayMetrics exports."""

    def __init__(self, config: ConfigManager):
        self.config = config

    @staticmethod
    def _load_all_players(csv_path: str) -> pd.DataFrame:
        """Universe loader for an All Players export, deduped by parent1_email.
        Returns columns: parent1_email, parent1_first_name, parent1_last_name,
        player_names, player_count. Self-contained (no Gmail/campaign dependency)."""
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        df["parent1_email"] = df["parent1_email"].astype(str).str.strip().str.lower()
        df = df[(df["parent1_email"] != "") & (df["parent1_email"] != "nan")].copy()

        def _join_unique(x):
            return ", ".join(pd.Series(x).dropna().astype(str).unique())

        recipients = (
            df.groupby("parent1_email")
            .agg(
                parent1_first_name=("parent1_first_name", "first"),
                parent1_last_name=("parent1_last_name", "first"),
                player_names=("player_first_name", _join_unique),
            )
            .reset_index()
        )
        recipients["player_count"] = recipients["player_names"].apply(
            lambda s: len([p for p in s.split(", ") if p])
        )
        return recipients

    # ── Registered set (PM responses OR MailChimp export) ────────────────

    @staticmethod
    def _emails_from_frame(df: pd.DataFrame) -> Set[str]:
        col = next((c for c in _REGISTERED_EMAIL_COLS if c in df.columns), None)
        if not col:
            return set()
        s = set(df[col].astype(str).str.strip().str.lower().unique())
        s.discard("")
        s.discard("nan")
        return s

    def load_registered(self, path: str) -> Set[str]:
        """
        Load the set of already-registered (activated) lowercase emails.

        Accepts:
          - a MailChimp member CSV ("Email Address"), or PM responses CSV
            (account_email / User Email) — column auto-detected;
          - a MailChimp "Export Audience" .zip — every member CSV inside is unioned
            (subscribed + unsubscribed + nonsubscribed + cleaned), since presence in
            the synced audience means the account was activated regardless of opt-in.
        """
        # MailChimp export zip → union all member CSVs.
        if path.lower().endswith(".zip"):
            registered: Set[str] = set()
            members: List[str] = []
            with tempfile.TemporaryDirectory() as tmp:
                with zipfile.ZipFile(path) as zf:
                    zf.extractall(tmp)
                for csv_file in glob.glob(os.path.join(tmp, "**", "*.csv"), recursive=True):
                    try:
                        emails = self._emails_from_frame(pd.read_csv(csv_file))
                    except Exception as e:
                        logger.warning(f"Skipping {os.path.basename(csv_file)}: {e}")
                        continue
                    if emails:
                        members.append(f"{os.path.basename(csv_file)} ({len(emails)})")
                        registered |= emails
            logger.info(f"Loaded {len(registered)} registered emails from zip members: {members}")
            return registered

        # Plain CSV — column auto-detection covers both MailChimp and PM formats.
        registered = self._emails_from_frame(pd.read_csv(path))
        if not registered:
            logger.warning(f"No recognizable email column in {path}.")
        logger.info(f"Found {len(registered)} registered email addresses")
        return registered

    # ── Build ────────────────────────────────────────────────────────────

    # Columns that mark a Player Contacts export (enables player-level logic).
    _CONTACT_COLS = {"contact_email", "player_id"}

    def _resolve_output(self, output_path: Optional[str]) -> str:
        if output_path:
            return output_path
        out_dir = self.config.get("output_dir", "data")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(out_dir, f"mailchimp_not_registered_{ts}.csv")

    def build(
        self,
        recipients_csv: str,
        registered_csv: str,
        output_path: Optional[str] = None,
        all_guardians: bool = True,
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Build the not-yet-registered audience.

        Auto-detects the universe file:
          - Player Contacts export (contact_email + player_id) -> player-level logic
            (a player is registered if ANY linked guardian activated; the audience is
            the guardians of players with no activated account).
          - otherwise -> All Players export, deduped by parent1_email.

        Returns (audience_df, stats) with MailChimp import columns.
        """
        header = pd.read_csv(recipients_csv, nrows=0)
        if self._CONTACT_COLS.issubset(set(header.columns)):
            return self.build_from_contacts(
                recipients_csv, registered_csv, output_path, all_guardians=all_guardians
            )

        recipients = self._load_all_players(recipients_csv)  # deduped by parent1_email
        registered = self.load_registered(registered_csv)

        not_reg = recipients[~recipients["parent1_email"].isin(registered)].copy()
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
            "mode": "all_players",
            "total_families": total,
            "registered": registered_count,
            "not_registered": len(audience),
            "conversion_rate": round(registered_count / total * 100, 1) if total else 0.0,
        }

        output_path = self._resolve_output(output_path)
        audience.to_csv(output_path, index=False)
        stats["output_path"] = output_path
        logger.info(f"Wrote {len(audience)} not-registered contacts to {output_path}")
        return audience, stats

    def compute_from_contacts(
        self,
        contacts_csv: str,
        registered: Set[str],
        all_guardians: bool = True,
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Core player-level computation (no file output). Shared by the CSV builder
        and the API sync.

        A player is "registered" if ANY of its linked guardian emails is in the
        `registered` set. The audience is the guardians of players with NO activated
        account. If all_guardians is False, only one guardian per player is kept.
        """
        df = pd.read_csv(contacts_csv)
        missing = {"contact_email", "player_id"} - set(df.columns)
        if missing:
            raise ValueError(
                f"{contacts_csv} is missing column(s) {sorted(missing)} — this does not look "
                f"like a PlayMetrics Player Contacts export. Columns found: {list(df.columns)}"
            )
        df["contact_email"] = df["contact_email"].astype(str).str.strip().str.lower()
        df = df[(df["contact_email"] != "") & (df["contact_email"] != "nan")].copy()
        registered = {str(e).strip().lower() for e in registered}

        # Per-player: registered if any of its contacts is in the registered set.
        df["_is_reg_contact"] = df["contact_email"].isin(registered)
        player_registered = df.groupby("player_id")["_is_reg_contact"].any()
        unregistered_player_ids = set(player_registered[~player_registered].index)

        target = df[df["player_id"].isin(unregistered_player_ids)].copy()
        if not all_guardians:
            target = target.drop_duplicates(subset="player_id", keep="first")

        # Collapse to one row per guardian email; list only the unregistered players.
        grouped = (
            target.groupby("contact_email")
            .agg(
                first=("contact_first_name", "first"),
                last=("contact_last_name", "first"),
                players=("player_first_name", lambda x: ", ".join(pd.Series(x).dropna().astype(str).unique())),
                player_count=("player_id", "nunique"),
            )
            .reset_index()
        )

        audience = pd.DataFrame(
            {
                "Email Address": grouped["contact_email"],
                "First Name": grouped["first"],
                "Last Name": grouped["last"],
                "Players": grouped["players"],
                "Player Count": grouped["player_count"],
            }
        )

        total_players = df["player_id"].nunique()
        registered_players = total_players - len(unregistered_player_ids)
        # Sanity: how many registered emails actually appear among contacts.
        matched = len(registered & set(df["contact_email"].unique()))
        stats = {
            "mode": "player_contacts",
            "total_players": total_players,
            "registered_players": registered_players,
            "unregistered_players": len(unregistered_player_ids),
            "registered_emails_total": len(registered),
            "registered_emails_matched_in_contacts": matched,
            "audience_contacts": len(audience),
            "player_conversion_rate": round(registered_players / total_players * 100, 1) if total_players else 0.0,
        }
        return audience, stats

    def build_from_contacts(
        self,
        contacts_csv: str,
        registered_csv: str,
        output_path: Optional[str] = None,
        all_guardians: bool = True,
    ) -> Tuple[pd.DataFrame, Dict]:
        """CSV builder: load registered from a file, compute, and write the add list."""
        registered = self.load_registered(registered_csv)
        audience, stats = self.compute_from_contacts(contacts_csv, registered, all_guardians)
        output_path = self._resolve_output(output_path)
        audience.to_csv(output_path, index=False)
        stats["output_path"] = output_path
        logger.info(
            f"[player_contacts] {len(audience)} guardian contacts across "
            f"{stats['unregistered_players']} unregistered players -> {output_path}"
        )
        return audience, stats

    # ── Reconcile (repeatable: add list + archive list + state) ───────────

    def _state_path(self, state_path: Optional[str]) -> str:
        if state_path:
            return state_path
        out_dir = self.config.get("output_dir", "data")
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, "pm_mailchimp_audience_state.json")

    @staticmethod
    def _load_state(state_path: str) -> Dict:
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"not_registered_emails": [], "history": []}

    def reconcile(
        self,
        recipients_csv: str,
        registered_csv: str,
        output_dir: Optional[str] = None,
        all_guardians: bool = True,
        state_path: Optional[str] = None,
    ) -> Dict:
        """
        Repeatable build that also manages departures.

        Each run writes:
          - add_file: the current not-registered audience (import to add/update).
          - archive_file: emails that were on the list last run but have since
            registered (import these to archive/remove them from the audience).

        State is persisted in pm_mailchimp_audience_state.json so the archive list
        is computed as (previous list - current list).
        """
        out_dir = output_dir or self.config.get("output_dir", "data")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        add_path = os.path.join(out_dir, f"mailchimp_not_registered_{ts}.csv")

        audience, build_stats = self.build(
            recipients_csv, registered_csv, output_path=add_path, all_guardians=all_guardians
        )
        current = {e for e in audience["Email Address"].astype(str).str.strip().str.lower()
                   if e and e != "nan"}

        state_path = self._state_path(state_path)
        state = self._load_state(state_path)
        previous = {str(e).strip().lower() for e in state.get("not_registered_emails", [])}

        to_archive = sorted(previous - current)   # were not-registered, now registered/gone
        new_adds = sorted(current - previous)

        archive_path = None
        if to_archive:
            names = {}
            try:
                cdf = pd.read_csv(recipients_csv)
                if "contact_email" in cdf.columns:
                    cdf["contact_email"] = cdf["contact_email"].astype(str).str.strip().str.lower()
                    m = cdf.drop_duplicates("contact_email").set_index("contact_email")
                    for e in to_archive:
                        if e in m.index:
                            names[e] = (m.at[e, "contact_first_name"], m.at[e, "contact_last_name"])
            except Exception:
                pass
            archive_path = os.path.join(out_dir, f"mailchimp_archive_registered_{ts}.csv")
            pd.DataFrame(
                [{"Email Address": e,
                  "First Name": names.get(e, ("", ""))[0],
                  "Last Name": names.get(e, ("", ""))[1]} for e in to_archive],
                columns=["Email Address", "First Name", "Last Name"],
            ).to_csv(archive_path, index=False)

        state["not_registered_emails"] = sorted(current)
        state["last_run"] = ts
        state.setdefault("history", []).append(
            {"run": ts, "added": len(new_adds), "archived": len(to_archive),
             "total_on_list": len(current)}
        )
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        return {
            "first_run": len(previous) == 0,
            "add_file": add_path,
            "archive_file": archive_path,
            "added": len(new_adds),
            "archived": len(to_archive),
            "total_on_list": len(current),
            "build_stats": build_stats,
            "state_path": state_path,
        }

    # ── API sync (reads both audiences from MailChimp; reconciles directly) ──

    def _mc_config(self) -> Dict:
        mc = self.config.get("mailchimp", {}) or {}
        cfg = {
            "api_key": mc.get("api_key") or os.environ.get("MAILCHIMP_API_KEY"),
            "server_prefix": mc.get("server_prefix") or os.environ.get("MAILCHIMP_SERVER_PREFIX"),
            "registered_list_id": mc.get("registered_list_id"),
            "not_registered_list_id": mc.get("not_registered_list_id"),
            "tag": mc.get("not_registered_tag", "fall2026-not-registered"),
            "merge_fields": mc.get("merge_fields", {
                "first": "FNAME", "last": "LNAME",
                "players": "PLAYERS", "player_count": "PLAYERCNT",
            }),
            "on_convert": mc.get("on_convert", "archive"),  # "archive" or "tag"
            "converted_tag": mc.get("converted_tag", "registered-now"),
        }
        return cfg

    def list_audiences(self):
        """Discovery helper: print audiences + their merge-field tags to fill config."""
        from automation.mailchimp_api_client import MailChimpAPIClient
        cfg = self._mc_config()
        client = MailChimpAPIClient(cfg["api_key"], cfg["server_prefix"])
        print("\nAudiences (use the id values in config.mailchimp):")
        for lst in client.get_lists():
            mc = lst.get("stats", {}).get("member_count", "?")
            print(f"  {lst['id']}  {lst['name']}  ({mc} members)")
            for mf in client.get_merge_fields(lst["id"]):
                print(f"       merge tag: {mf['tag']:<12} ({mf['name']})")

    def sync_via_api(self, contacts_csv: str, all_guardians: bool = True,
                     dry_run: bool = True) -> Dict:
        """
        Full hands-off reconcile against MailChimp:
          1. Pull the registered (PM-synced) audience members via API.
          2. Compute the current not-registered audience from the contacts export.
          3. Pull the current not-registered audience members via API.
          4. Add new not-registered contacts (+ tag); archive (or tag) the converts.

        dry_run=True (default) reports the planned changes without writing.
        """
        from automation.mailchimp_api_client import MailChimpAPIClient

        cfg = self._mc_config()
        for required in ("api_key", "registered_list_id", "not_registered_list_id"):
            if not cfg[required]:
                raise ValueError(
                    f"Missing MailChimp config '{required}'. Set it under config.mailchimp "
                    f"(run with --mc-list-audiences to find list ids)."
                )

        client = MailChimpAPIClient(cfg["api_key"], cfg["server_prefix"])

        # 1. registered set straight from the synced audience
        registered = client.get_member_emails(cfg["registered_list_id"])
        logger.info(f"Registered audience members: {len(registered)}")

        # 2. desired not-registered audience from the contacts export
        audience, stats = self.compute_from_contacts(contacts_csv, registered, all_guardians)
        desired = {r["Email Address"].strip().lower(): r for _, r in audience.iterrows()}

        # 3. who is currently in the not-registered audience
        existing = client.get_member_emails(cfg["not_registered_list_id"])

        to_add = [e for e in desired if e not in existing]
        to_convert = sorted(existing - set(desired))  # were on list, now registered/gone

        mf = cfg["merge_fields"]
        plan = {
            "dry_run": dry_run,
            "registered_members": len(registered),
            "desired_not_registered": len(desired),
            "already_on_list": len(existing),
            "to_add": len(to_add),
            "to_convert": len(to_convert),
            "on_convert": cfg["on_convert"],
            "build_stats": stats,
        }

        if dry_run:
            logger.info(f"[DRY RUN] would add {len(to_add)}, "
                        f"{cfg['on_convert']} {len(to_convert)} converts")
            return plan

        nrid = cfg["not_registered_list_id"]
        added = 0
        for email in to_add:
            row = desired[email]
            merge = {mf["first"]: str(row["First Name"]), mf["last"]: str(row["Last Name"])}
            if mf.get("players"):
                merge[mf["players"]] = str(row["Players"])
            if mf.get("player_count"):
                merge[mf["player_count"]] = str(row["Player Count"])
            client.upsert_member(nrid, email, merge_fields=merge)
            client.add_tag(nrid, email, cfg["tag"])
            added += 1

        converted = 0
        for email in to_convert:
            if cfg["on_convert"] == "tag":
                client.add_tag(nrid, email, cfg["converted_tag"])
            else:
                client.archive_member(nrid, email)
            converted += 1

        plan.update({"added_applied": added, "converted_applied": converted})
        logger.info(f"Applied: added {added}, {cfg['on_convert']} {converted}")
        return plan


# ── CLI ──────────────────────────────────────────────────────────────────

class MailChimpAudienceCLI:
    """Command-line interface for building the MailChimp not-registered audience."""

    DEFAULT_RECIPIENTS = "data/playmetrics/all-player-contacts.csv"

    def __init__(self, config: ConfigManager):
        self.config = config
        self.manager = MailChimpAudienceManager(config)

    def run_build(self, recipients_csv: str = None, registered_csv: str = None,
                  output_dir: str = None, all_guardians: bool = True):
        print("\n" + "=" * 60)
        print("MailChimp Audience — Not Yet Registered (repeatable)")
        print("=" * 60)

        recipients_csv = recipients_csv or input(
            f"\nPath to PM Player Contacts (or All Players) CSV [{self.DEFAULT_RECIPIENTS}]: "
        ).strip() or self.DEFAULT_RECIPIENTS
        if not os.path.exists(recipients_csv):
            print(f"Error: recipients file not found: {recipients_csv}")
            return

        if not registered_csv:
            registered_csv = input(
                "Path to MailChimp synced export (.zip or .csv) or PM responses CSV: "
            ).strip()
        if not registered_csv or not os.path.exists(registered_csv):
            print(f"Error: registered file not found: {registered_csv}")
            return

        result = self.manager.reconcile(
            recipients_csv, registered_csv,
            output_dir=output_dir, all_guardians=all_guardians,
        )
        bs = result["build_stats"]

        print("\n" + "-" * 40)
        if bs.get("mode") == "player_contacts":
            print(f"Players total:         {bs['total_players']}")
            print(f"Registered players:    {bs['registered_players']} ({bs['player_conversion_rate']}%)")
            print(f"Unregistered players:  {bs['unregistered_players']}")
        print(f"On not-registered list: {result['total_on_list']}")
        print(f"  New this run (add):    {result['added']}")
        print(f"  Registered since last "
              f"(archive):  {result['archived']}")
        print(f"\nADD/KEEP file:  {result['add_file']}")
        if result["archive_file"]:
            print(f"ARCHIVE file:   {result['archive_file']}")

        print("\nMailChimp steps:")
        print("  1. Import the ADD/KEEP file into your separate 'Not Yet Registered'")
        print("     audience (status Subscribed; tag 'fall2026-not-registered').")
        if result["archive_file"]:
            print("  2. Import the ARCHIVE file into the SAME audience, tag it")
            print("     'registered-archive', then filter by that tag and Archive —")
            print("     this removes everyone who has since registered.")
        else:
            print("  2. No archive list this run.")
        if result["first_run"]:
            print("\n(First run: no prior state, so nothing to archive yet. Future runs")
            print(" will compute the archive list automatically.)")


def handle_pm_mailchimp_audience(config: ConfigManager, args) -> int:
    """Handle MailChimp audience build/reconcile from command line."""
    logger.info("Starting MailChimp Audience Manager")
    try:
        cli = MailChimpAudienceCLI(config)
        cli.run_build(
            recipients_csv=getattr(args, "recipients_csv", None),
            registered_csv=getattr(args, "registered_csv", None),
            output_dir=getattr(args, "audience_output_dir", None),
            all_guardians=not getattr(args, "audience_one_per_player", False),
        )
        return 0
    except Exception as e:
        logger.error(f"Error in MailChimp audience manager: {e}")
        import traceback
        traceback.print_exc()
        return 1


def handle_pm_mailchimp_sync(config: ConfigManager, args) -> int:
    """Handle MailChimp API sync (reads both audiences, reconciles directly)."""
    logger.info("Starting MailChimp API sync")
    try:
        manager = MailChimpAudienceManager(config)

        if getattr(args, "mc_list_audiences", False):
            manager.list_audiences()
            return 0

        contacts = _resolve_contacts_file(getattr(args, "recipients_csv", None))
        if not contacts or not os.path.exists(contacts):
            print("Error: no Player Contacts CSV found. Looked for "
                  "data/playmetrics/player-contacts_*.csv — pass --recipients-csv "
                  "or run the contacts download first.")
            return 1
        print(f"Using contacts file: {contacts}")

        dry_run = not getattr(args, "apply", False)
        plan = manager.sync_via_api(
            contacts,
            all_guardians=not getattr(args, "audience_one_per_player", False),
            dry_run=dry_run,
        )

        print("\n" + "=" * 56)
        print("MailChimp API Sync " + ("(DRY RUN — no changes made)" if dry_run else "(APPLIED)"))
        print("=" * 56)
        bs = plan["build_stats"]
        print(f"Players total / registered / unregistered:  "
              f"{bs['total_players']} / {bs['registered_players']} / {bs['unregistered_players']}")
        print(f"Registered audience members (MailChimp):     {plan['registered_members']}")
        print(f"Desired not-registered audience:             {plan['desired_not_registered']}")
        print(f"Already on the not-registered audience:      {plan['already_on_list']}")
        print(f"  To ADD:                                    {plan['to_add']}")
        print(f"  To {plan['on_convert'].upper()} (converted since last sync):   {plan['to_convert']}")
        if dry_run:
            print("\nThis was a preview. Re-run with --apply to make these changes.")
        else:
            print(f"\nApplied: added {plan.get('added_applied', 0)}, "
                  f"{plan['on_convert']} {plan.get('converted_applied', 0)}.")
        return 0
    except Exception as e:
        logger.error(f"Error in MailChimp API sync: {e}")
        import traceback
        traceback.print_exc()
        return 1