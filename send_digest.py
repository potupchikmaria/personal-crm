#!/usr/bin/env python3
"""Send daily CRM digest to Telegram. Runs Mon-Fri via launchd."""

import sqlite3
import urllib.request
import urllib.parse
import json
import sys
import re
from datetime import date
from pathlib import Path

from config import BOT_TOKEN, CHAT_ID, DB

TOP_N = 7

PRIORITY_SCORE = {"HOT": 400, "Stanford": 200, "Gartner": 150,
                  "Warm": 120, "New": 100, "Investor": 80, "Cold": 50}
STATUS_URGENCY = {
    "damage control": 100, "missed time slot": 90, "awaits response": 80,
    "waiting for your response": 75, "fresh warm": 50, "need re-engagement": 40,
    "asked about raise": 35, "not met yet": 30, "strong relationship": 20,
    "cold but research-ready": 15, "not engaged yet": 10,
}


def score(c):
    s = PRIORITY_SCORE.get(c["priority"], 0)
    for kw, pts in STATUS_URGENCY.items():
        if kw in (c["status"] or "").lower():
            s += pts
            break
    days = c["last_contact_days"]
    if days is not None:
        s += min(days * 3, 300)
    return s


def fmt_days(days):
    if days is None: return "?"
    return "never" if days >= 999 else f"{days}d ago"


def strip_emoji(text):
    return re.sub(r'[^\x00-\x7Fа-яА-ЯёЁ\s\w.,!?:()\-/+@\"\']+', '', text or "").strip()


PRIORITY_EMOJI = {"HOT": "🔥", "Stanford": "🎓", "Gartner": "🏢",
                  "Warm": "🤝", "New": "🆕", "Investor": "💰", "Cold": "❄️"}


def build_message(contacts, today):
    weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][today.weekday()]
    lines = [f"📋 *Reach Out Today — {weekday} {today.strftime('%d %b')}*\n"]
    for i, c in enumerate(contacts, 1):
        emoji = PRIORITY_EMOJI.get(c["priority"], "•")
        status = strip_emoji(c["status"] or "").strip(" —")
        action = (c["outreach_msg"] or c["next_action"] or "")[:160]
        action = re.sub(r'^[✉️📞🔗\s]+', '', action).strip()
        lines.append(
            f"{i}\\. {emoji} *{escape(c['name'])}*\n"
            f"   {escape(c['title'] or '')} · {escape(c['company'] or '')}\n"
            f"   _{escape(status)}_ · {fmt_days(c['last_contact_days'])}\n"
            f"   → {escape(action)}\n"
        )
    return "\n".join(lines)


def escape(text):
    """Escape MarkdownV2 special chars."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.load(resp)
        if not result.get("ok"):
            raise RuntimeError(result)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT *, outreach_msg FROM contacts WHERE skip=0 OR skip IS NULL").fetchall()
    conn.close()

    if not rows:
        print("DB is empty. Run: python3 crm.py import")
        sys.exit(1)

    today = date.today()
    ranked = sorted(rows, key=score, reverse=True)[:TOP_N]
    msg = build_message(ranked, today)
    send_telegram(msg)
    print(f"✓ Sent to Telegram: {ranked[0]['name']}, {ranked[1]['name']} +{TOP_N-2} more")


if __name__ == "__main__":
    main()
