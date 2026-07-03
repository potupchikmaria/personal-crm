#!/usr/bin/env python3
"""Check pending reminders and send due ones to Telegram."""

import sqlite3
import urllib.request
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from config import BOT_TOKEN, CHAT_ID, DB


def escape_md(text):
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
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Find unsent reminders due today or overdue
    rows = conn.execute("""
        SELECT r.*, c.name as contact_name
        FROM reminders r
        LEFT JOIN contacts c ON r.contact_id = c.id
        WHERE r.done=0 AND r.sent=0
        ORDER BY r.due_date
    """).fetchall()

    if not rows:
        print("No pending reminders.")
        conn.close()
        return

    overdue, due_today, due_tomorrow = [], [], []
    for r in rows:
        try:
            d = datetime.strptime(r["due_date"], "%Y-%m-%d").date()
        except:
            d = today
        if d < today:
            overdue.append((r, d))
        elif d == today:
            due_today.append((r, d))
        elif d == tomorrow:
            due_tomorrow.append((r, d))

    if not (overdue or due_today or due_tomorrow):
        print("No reminders due soon.")
        conn.close()
        return

    lines = ["⏰ *Reminders*\n"]

    if overdue:
        lines.append("🔴 *Overdue:*")
        for r, d in overdue:
            name = r["contact_name"] or "—"
            lines.append(f"• {escape_md(name)}: {escape_md(r['action'][:100])}")
            lines.append(f"  _was due {escape_md(str(d))}_")
        lines.append("")

    if due_today:
        lines.append("🟡 *Due today:*")
        for r, d in due_today:
            name = r["contact_name"] or "—"
            lines.append(f"• {escape_md(name)}: {escape_md(r['action'][:100])}")
        lines.append("")

    if due_tomorrow:
        lines.append("🔵 *Due tomorrow:*")
        for r, d in due_tomorrow:
            name = r["contact_name"] or "—"
            lines.append(f"• {escape_md(name)}: {escape_md(r['action'][:100])}")

    send_telegram("\n".join(lines))

    # Mark as sent
    ids = [r["id"] for r, _ in overdue + due_today + due_tomorrow]
    conn.execute(f"UPDATE reminders SET sent=1 WHERE id IN ({','.join('?'*len(ids))})", ids)
    conn.commit()
    conn.close()
    print(f"✓ Sent {len(ids)} reminders")


if __name__ == "__main__":
    main()
