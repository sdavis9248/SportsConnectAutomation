"""
Minimal MailChimp Marketing API client (requests-based).

Auth: HTTP Basic with any username + the API key as password. The data-center
suffix is the part of the API key after the dash (e.g. "...-us21" -> us21).

Credentials are read by the caller from config/env and passed in here — never
hardcode them and never commit them (config.json is gitignored).

Docs: https://mailchimp.com/developer/marketing/api/
"""

import time
import hashlib
import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class MailChimpAPIError(Exception):
    pass


class MailChimpAPIClient:
    def __init__(self, api_key: str, server_prefix: Optional[str] = None, timeout: int = 30):
        if not api_key:
            raise MailChimpAPIError("Missing MailChimp API key")
        self.api_key = api_key
        dc = server_prefix or (api_key.split("-")[-1] if "-" in api_key else None)
        if not dc:
            raise MailChimpAPIError(
                "Could not determine MailChimp data center; set server_prefix (e.g. 'us21')"
            )
        self.base = f"https://{dc}.api.mailchimp.com/3.0"
        self.timeout = timeout
        self._auth = ("anystring", api_key)

    # ── low-level ─────────────────────────────────────────────────────────

    @staticmethod
    def subscriber_hash(email: str) -> str:
        return hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()

    def _request(self, method: str, path: str, max_retries: int = 4, **kwargs) -> requests.Response:
        url = f"{self.base}{path}"
        for attempt in range(max_retries):
            resp = requests.request(method, url, auth=self._auth, timeout=self.timeout, **kwargs)
            if resp.status_code == 429:  # rate limited
                wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                logger.warning(f"Rate limited; sleeping {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                # 405 on DELETE of an already-archived member, etc. — surface detail
                detail = ""
                try:
                    detail = resp.json().get("detail", "")
                except Exception:
                    detail = resp.text[:200]
                raise MailChimpAPIError(f"{method} {path} -> {resp.status_code}: {detail}")
            return resp
        raise MailChimpAPIError(f"{method} {path} failed after {max_retries} retries (rate limit)")

    # ── audiences ─────────────────────────────────────────────────────────

    def get_lists(self) -> List[Dict]:
        resp = self._request("GET", "/lists", params={"count": 200, "fields": "lists.id,lists.name,lists.stats.member_count"})
        return resp.json().get("lists", [])

    def get_merge_fields(self, list_id: str) -> List[Dict]:
        resp = self._request("GET", f"/lists/{list_id}/merge-fields",
                             params={"count": 200, "fields": "merge_fields.tag,merge_fields.name,merge_fields.type"})
        return resp.json().get("merge_fields", [])

    def get_member_emails(self, list_id: str, statuses: Optional[List[str]] = None) -> set:
        """Return the set of lowercased member emails (optionally filtered by status)."""
        emails, offset, count = set(), 0, 1000
        while True:
            params = {"count": count, "offset": offset,
                      "fields": "members.email_address,members.status,total_items"}
            data = self._request("GET", f"/lists/{list_id}/members", params=params).json()
            members = data.get("members", [])
            for m in members:
                if statuses and m.get("status") not in statuses:
                    continue
                emails.add(m["email_address"].strip().lower())
            offset += count
            if offset >= data.get("total_items", 0) or not members:
                break
        return emails

    # ── member writes ─────────────────────────────────────────────────────

    def upsert_member(self, list_id: str, email: str, merge_fields: Optional[Dict] = None,
                      status_if_new: str = "subscribed") -> None:
        body = {"email_address": email, "status_if_new": status_if_new}
        if merge_fields:
            body["merge_fields"] = merge_fields
        self._request("PUT", f"/lists/{list_id}/members/{self.subscriber_hash(email)}", json=body)

    def add_tag(self, list_id: str, email: str, tag: str) -> None:
        self._request("POST", f"/lists/{list_id}/members/{self.subscriber_hash(email)}/tags",
                      json={"tags": [{"name": tag, "status": "active"}]})

    def archive_member(self, list_id: str, email: str) -> None:
        """Archive (reversible). DELETE on the member resource archives, not hard-deletes."""
        try:
            self._request("DELETE", f"/lists/{list_id}/members/{self.subscriber_hash(email)}")
        except MailChimpAPIError as e:
            # Already archived / not present is fine for reconciliation purposes.
            logger.info(f"archive skipped for {email}: {e}")
