"""Rank exported claude.ai chats by PlayMetrics/registrar relevance.

Usage: python scripts/claude_export_rank.py [min_score]
"""
import json
import re
import sys
from pathlib import Path

EXPORT_DIR = Path("data/claude_export")

# keyword -> weight
KEYWORDS = {
    "playmetrics": 5,
    "invitation link": 4,
    "birth certificate": 3,
    "bc verification": 4,
    "registrar": 3,
    "registration": 1,
    "waitlist": 2,
    "ayso": 1,
    "blue sombrero": 2,
    "sports connect": 2,
    "sportsconnect": 2,
    "volunteer": 1,
    "division": 1,
    "etrainu": 2,
    "safesport": 2,
}


def score_chat(chat) -> int:
    text = (chat.get("name") or "") + " "
    for m in chat.get("chat_messages", []):
        text += (m.get("text") or "") + " "
        for a in m.get("attachments", []):
            text += (a.get("extracted_content") or "")[:20000] + " "
    text = text.lower()
    score = 0
    for kw, weight in KEYWORDS.items():
        score += weight * len(re.findall(re.escape(kw), text))
    return score


def main():
    min_score = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    with open(EXPORT_DIR / "conversations.json", encoding="utf-8") as f:
        conversations = json.load(f)

    ranked = []
    for c in conversations:
        s = score_chat(c)
        if s >= min_score:
            ranked.append((s, c))
    ranked.sort(key=lambda x: -x[0])

    print(f"{len(ranked)} of {len(conversations)} chats score >= {min_score}\n")
    for s, c in ranked:
        msgs = c.get("chat_messages", [])
        chars = sum(len(m.get("text", "")) for m in msgs)
        print(
            f"score={s:5d}  {c.get('created_at', '')[:10]}  msgs={len(msgs):3d}  "
            f"{chars//1024:5d} KB  {c.get('uuid', '')[:8]}  {c.get('name', '')!r}"
        )


if __name__ == "__main__":
    main()
