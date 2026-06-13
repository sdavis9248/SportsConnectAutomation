"""Distill the claude.ai export (Playmetrics project docs + relevant chats)
into the email assistant's knowledge base.

Stages:
  python scripts/claude_export_distill.py docs    # project docs -> knowledge_distill/docs/
  python scripts/claude_export_distill.py chats [N]  # distill chats (optionally first N)
  python scripts/claude_export_distill.py merge   # merge everything -> data/knowledge/*.md

Intermediate output goes to data/knowledge_distill/ (NOT data/knowledge/) so the
email assistant never loads undistilled material.
"""
import json
import re
import sys
from pathlib import Path

import anthropic
from bs4 import BeautifulSoup

EXPORT_DIR = Path("data/claude_export")
PROJECT_FILE = EXPORT_DIR / "projects" / "019be6db-9fbd-76ba-8266-3558344c076b.json"
DISTILL_DIR = Path("data/knowledge_distill")
KNOWLEDGE_DIR = Path("data/knowledge")

MODEL = "claude-opus-4-8"

# Registrar/policy-relevant chats chosen from claude_export_rank.py output.
# uuid prefix -> short slug
SELECTED_CHATS = {
    "acb2526b": "fall-season-setup",
    "d9d0359f": "fall-season-launch-planning",
    "9b66d948": "division-coordinator-reports",
    "cf3160eb": "etrainu-portal-volunteer-integration",
    "e6d3ff82": "unregistered-players-mailchimp",
    "28acf123": "pm-export-download-model",
    "942993d5": "waitlist-notification-processing",
    "e353bae4": "strict-bc-mode-import-guide",
    "84a6bd24": "registrar-email-assistant-design",
    "bddbd583": "pm-exports-vs-suite",
    "e7d9fb84": "u12-allstar-eligibility",
    "5d061524": "volunteer-license-requirements",
    "efa3c7c4": "pm-website-updates-fall-2026",
    "677229e0": "pm-architecture-affinity-integration",
    "482a2283": "registration-responses-insights",
    "00e40631": "csv-export-player-import",
    "6e5d14cc": "financial-aid-vetting",
    "d4cc1b75": "import-guide-updates",
    "e272200e": "import-inactive-participants",
    "68695688": "strict-bc-mode-2",
    "bd213512": "strict-bc-mode-3",
    "81187e6b": "sc-to-pm-data-migration",
    "481ccfe0": "migration-pipeline-release",
    "b4b20be7": "pm-scheduling-capability",
}

ATTACHMENT_CAP = 15_000  # chars per attachment included in a chat transcript
CHAT_CAP = 600_000       # chars per chat transcript sent for distillation

CHAT_EXTRACTION_PROMPT = """You are distilling a working chat between an AYSO Region 58 registrar \
and an AI assistant into durable reference knowledge. The knowledge will be used by an email \
assistant that drafts replies to soccer parents about registration on PlayMetrics.

Extract ONLY durable, reusable knowledge:
- Facts about how PlayMetrics works (invitations, accounts, birth certificate verification, \
imports, payments, programs, scheduling, volunteer signup)
- Region 58 policies, fees, deadlines, procedures, and decisions that were made
- How specific parent-facing situations should be handled (Q -> correct answer patterns)
- Known issues/gotchas and their resolutions

Rules:
- SKIP code, debugging, file paths, CLI flags, and implementation details of automation scripts.
- SKIP dead ends, brainstorming that wasn't adopted, and anything purely conversational.
- NEVER include personal data about specific families, players, parents, or volunteers \
(no names, emails, phone numbers, order numbers). Generalize examples.
- If a fact was clearly superseded later in the chat, keep only the final version.
- If a fact may be time-sensitive or you are unsure it is still current, append " [VERIFY]".
- Write concise markdown bullet points grouped under ## topic headings.
- If the chat contains NO durable registrar-relevant knowledge, respond with exactly: NO_KNOWLEDGE

Chat transcript follows:

"""

MERGE_PROMPT = """You are building the knowledge base for an AI email assistant that answers \
parents' emails for the AYSO Region 58 registrar (registrar@ayso58.org). The region migrated \
from SportsConnect to PlayMetrics for Fall 2026.

Below are (a) distilled notes from the registrar's working chats and (b) reference documents. \
Merge everything into a clean, deduplicated, topically organized knowledge base.

Requirements:
- Organize into separate markdown files by topic. Emit each file as:
  === FILE: <kebab-case-name>.md ===
  <content>
- Suggested topics (adjust as the material dictates): registration-process, invitation-links, \
birth-certificate-verification, accounts-and-login, fees-payments-refunds, financial-aid, \
divisions-and-programs, waitlist, volunteers-and-coaching, schedules-and-season, \
migration-from-sportsconnect, common-questions.
- Resolve conflicts in favor of the most recent/most authoritative statement; keep any \
" [VERIFY]" flags on claims that need human confirmation.
- NO personal data about specific families/players/volunteers.
- Write for an AI reader: dense, factual, unambiguous. No filler.
- Total size target: roughly 30-60 KB across all files. Prioritize parent-facing knowledge.

MATERIAL:

"""


def client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def call_claude(prompt: str, max_tokens: int, label: str) -> str:
    with client().messages.stream(
        model=MODEL, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    text = "".join(b.text for b in msg.content if b.type == "text")
    u = msg.usage
    print(f"  [{label}] in={u.input_tokens} out={u.output_tokens} stop={msg.stop_reason}")
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"{label}: request refused")
    return text


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def stage_docs():
    """Project knowledge docs -> knowledge_distill/docs/ (HTML converted; huge docs condensed)."""
    out_dir = DISTILL_DIR / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(PROJECT_FILE, encoding="utf-8") as f:
        project = json.load(f)
    for doc in project.get("docs", []):
        name = doc.get("filename", "unnamed")
        content = doc.get("content", "")
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(name).stem).strip("-").lower()
        if name.lower().endswith((".html", ".htm")):
            content = html_to_text(content)
        if name.endswith(".py"):
            print(f"skip (code): {name}")
            continue
        if len(content) > 120_000:
            print(f"condensing large doc: {name} ({len(content)//1024} KB)")
            content = call_claude(
                "Condense this PlayMetrics reference document into dense markdown notes "
                "covering every fact, procedure, and setting a soccer-club registrar would "
                "need. Skip boilerplate and navigation text. Keep all concrete values "
                "(fees, dates, field names, rules).\n\nDOCUMENT:\n\n" + content,
                max_tokens=30_000, label=stem,
            )
        (out_dir / f"{stem}.md").write_text(content, encoding="utf-8")
        print(f"wrote docs/{stem}.md ({len(content)//1024} KB)")


def format_chat(chat) -> str:
    lines = [f"CHAT TITLE: {chat.get('name', '')}", f"CREATED: {chat.get('created_at', '')[:10]}"]
    for m in chat.get("chat_messages", []):
        sender = "REGISTRAR" if m.get("sender") == "human" else "ASSISTANT"
        text = (m.get("text") or "").strip()
        if text:
            lines.append(f"\n[{sender}]\n{text}")
        for a in m.get("attachments", []):
            extracted = (a.get("extracted_content") or "").strip()
            if extracted:
                if len(extracted) > ATTACHMENT_CAP:
                    extracted = extracted[:ATTACHMENT_CAP] + "\n[... attachment truncated ...]"
                lines.append(f"\n[ATTACHMENT: {a.get('file_name', '?')}]\n{extracted}")
    transcript = "\n".join(lines)
    if len(transcript) > CHAT_CAP:
        transcript = transcript[:CHAT_CAP] + "\n[... chat truncated ...]"
        print(f"  note: transcript truncated to {CHAT_CAP} chars")
    return transcript


def stage_chats(limit: int = None):
    out_dir = DISTILL_DIR / "chats"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(EXPORT_DIR / "conversations.json", encoding="utf-8") as f:
        conversations = json.load(f)
    by_prefix = {c.get("uuid", "")[:8]: c for c in conversations}

    items = list(SELECTED_CHATS.items())[:limit] if limit else list(SELECTED_CHATS.items())
    for prefix, slug in items:
        out_file = out_dir / f"{prefix}_{slug}.md"
        if out_file.exists():
            print(f"skip (done): {slug}")
            continue
        chat = by_prefix.get(prefix)
        if not chat:
            print(f"MISSING chat {prefix} ({slug})")
            continue
        transcript = format_chat(chat)
        print(f"distilling {slug} ({len(transcript)//1024} KB)...")
        notes = call_claude(CHAT_EXTRACTION_PROMPT + transcript, max_tokens=16_000, label=slug)
        if notes.strip() == "NO_KNOWLEDGE":
            out_file.write_text("(no durable knowledge)\n", encoding="utf-8")
            print(f"  -> no durable knowledge")
        else:
            header = f"<!-- distilled from chat {prefix} {chat.get('name', '')!r} -->\n\n"
            out_file.write_text(header + notes, encoding="utf-8")
            print(f"  -> wrote chats/{out_file.name} ({len(notes)//1024} KB)")


def stage_merge():
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    material = []
    for f in sorted((DISTILL_DIR / "chats").glob("*.md")):
        body = f.read_text(encoding="utf-8")
        if "(no durable knowledge)" in body:
            continue
        material.append(f"----- CHAT NOTES: {f.name} -----\n{body}")
    for f in sorted((DISTILL_DIR / "docs").glob("*.md")):
        material.append(f"----- DOCUMENT: {f.name} -----\n{f.read_text(encoding='utf-8')}")
    blob = "\n\n".join(material)
    print(f"merging {len(material)} sources ({len(blob)//1024} KB)...")
    result = call_claude(MERGE_PROMPT + blob, max_tokens=64_000, label="merge")

    files = re.split(r"=== FILE: (.+?\.md) ===", result)
    # re.split yields [preamble, name1, content1, name2, content2, ...]
    count = 0
    for i in range(1, len(files) - 1, 2):
        name = files[i].strip()
        content = files[i + 1].strip() + "\n"
        if not re.fullmatch(r"[a-z0-9-]+\.md", name):
            print(f"skipping odd filename: {name!r}")
            continue
        (KNOWLEDGE_DIR / name).write_text(content, encoding="utf-8")
        print(f"wrote data/knowledge/{name} ({len(content)//1024} KB)")
        count += 1
    if count == 0:
        (DISTILL_DIR / "merge_raw.md").write_text(result, encoding="utf-8")
        print("no files parsed — raw output saved to knowledge_distill/merge_raw.md")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage == "docs":
        stage_docs()
    elif stage == "chats":
        stage_chats(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif stage == "merge":
        stage_merge()
    else:
        print(__doc__)
