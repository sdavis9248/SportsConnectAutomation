"""Survey a claude.ai data export: list projects and their chats.

Usage:
  python scripts/claude_export_survey.py                # list projects
  python scripts/claude_export_survey.py <project-uuid-prefix>  # list that project's chats
"""
import json
import sys
from glob import glob
from pathlib import Path

EXPORT_DIR = Path("data/claude_export")


def load_projects():
    projects = []
    for p in sorted(glob(str(EXPORT_DIR / "projects" / "*.json"))):
        with open(p, encoding="utf-8") as f:
            projects.append(json.load(f))
    return projects


def survey_projects():
    for d in load_projects():
        docs = d.get("docs", [])
        doc_kb = sum(len(x.get("content", "")) for x in docs) // 1024
        print(f"{d.get('uuid', '')[:8]}  docs={len(docs):3d} ({doc_kb:5d} KB)  {d.get('name', '')!r}")


def survey_chats(uuid_prefix: str):
    projects = [d for d in load_projects() if d.get("uuid", "").startswith(uuid_prefix)]
    if not projects:
        print(f"No project with uuid starting {uuid_prefix!r}")
        return
    project = projects[0]
    print(f"Project: {project.get('name')!r} ({project.get('uuid')})")
    print(f"Knowledge docs: {len(project.get('docs', []))}")
    for doc in project.get("docs", []):
        print(f"  - {doc.get('filename', '?')} ({len(doc.get('content', ''))//1024} KB)")

    print("\nLoading conversations.json (large file)...")
    with open(EXPORT_DIR / "conversations.json", encoding="utf-8") as f:
        conversations = json.load(f)

    puuid = project.get("uuid")
    chats = [c for c in conversations if (c.get("project") or {}).get("uuid") == puuid]
    print(f"\nChats in project: {len(chats)} (of {len(conversations)} total)")
    for c in sorted(chats, key=lambda c: c.get("created_at", "")):
        msgs = c.get("chat_messages", [])
        n_attach = sum(len(m.get("attachments", [])) + len(m.get("files", [])) for m in msgs)
        chars = sum(len(m.get("text", "")) for m in msgs)
        print(
            f"  {c.get('created_at', '')[:10]}  msgs={len(msgs):3d}  attach={n_attach:2d}  "
            f"{chars//1024:5d} KB  {c.get('name', '')!r}"
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        survey_chats(sys.argv[1])
    else:
        survey_projects()
