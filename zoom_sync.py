#!/usr/bin/env python3
"""
Zoom AI Summary → CRM sync.
Fetches recent meetings, matches participants to CRM contacts,
updates last_contact_days, saves summaries, sends Telegram digest.
"""

import sqlite3
import urllib.request
import urllib.parse
import json
import base64
import re
import sys
from datetime import date, datetime
from pathlib import Path


def translate_to_en(text: str) -> str:
    """Translate text to English via Google Translate (free tier, no key needed)."""
    if not text:
        return text
    # Detect if mostly Cyrillic
    cyrillic = sum(1 for c in text if 'Ѐ' <= c <= 'ӿ')
    if cyrillic < len(text) * 0.15:
        return text  # already mostly English
    try:
        params = urllib.parse.urlencode({
            "client": "gtx", "sl": "auto", "tl": "en",
            "dt": "t", "q": text[:4000]
        })
        req = urllib.request.Request(
            f"https://translate.googleapis.com/translate_a/single?{params}",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        return "".join(seg[0] for seg in data[0] if seg[0])
    except Exception:
        return text  # fallback: return original

# ─── Config ──────────────────────────────────────────────────────────────────

from config import (BOT_TOKEN, CHAT_ID, DB,
                    ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID,
                    ZOOM_CLIENT_SECRET, ZOOM_USER_ID)

DAYS_BACK = 7   # how many days of meetings to sync


# ─── Zoom auth ────────────────────────────────────────────────────────────────

def get_zoom_token():
    creds = base64.b64encode(f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}".encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type": "account_credentials",
        "account_id": ZOOM_ACCOUNT_ID
    }).encode()
    req = urllib.request.Request(
        "https://zoom.us/oauth/token", data=data,
        headers={"Authorization": f"Basic {creds}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["access_token"]


def zoom_get(token, path):
    req = urllib.request.Request(
        f"https://api.zoom.us/v2{path}",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Zoom API {path}: {body[:200]}")


# ─── DB helpers ───────────────────────────────────────────────────────────────

def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS zoom_meetings (
        id           INTEGER PRIMARY KEY,
        meeting_id   TEXT UNIQUE,
        uuid         TEXT,
        topic        TEXT,
        date         TEXT,
        duration_min INTEGER,
        summary      TEXT,
        next_steps   TEXT,   -- JSON list
        participants TEXT,   -- JSON list of names
        synced_at    TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS reminders (
        id          INTEGER PRIMARY KEY,
        contact_id  INTEGER,
        meeting_id  TEXT,
        due_date    TEXT,
        action      TEXT,
        done        INTEGER DEFAULT 0,
        sent        INTEGER DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()


# ─── Name matching ────────────────────────────────────────────────────────────

def extract_names_from_topic(topic):
    """'Dirk & Mariia's Zoom Meeting' → ['Dirk']"""
    topic = topic.replace("Mariia Potupchik", "").replace("Mariia", "").replace("'s", "")
    parts = re.split(r"[&,]|Zoom Meeting|Meeting|Sync|Call|Weekly|sync", topic)
    names = [p.strip() for p in parts if p.strip() and len(p.strip()) > 2]
    return names


def find_crm_contact(conn, name_hint):
    """Fuzzy match name hint to CRM contact."""
    words = name_hint.lower().split()
    for word in words:
        if len(word) < 3:
            continue
        row = conn.execute(
            "SELECT * FROM contacts WHERE lower(name) LIKE ? LIMIT 1",
            (f"%{word}%",)
        ).fetchone()
        if row:
            return row
    return None


# ─── Telegram ─────────────────────────────────────────────────────────────────

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
        result = json.load(r)
    if not result.get("ok"):
        raise RuntimeError(result)


# ─── Main sync ────────────────────────────────────────────────────────────────

def sync():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    token = get_zoom_token()
    today = date.today()

    # Fetch recent past meetings
    meetings_data = zoom_get(token, f"/users/{ZOOM_USER_ID}/meetings?type=previous_meetings&page_size=30")
    meetings = meetings_data.get("meetings", [])

    new_summaries = []

    for m in meetings:
        mid = str(m["id"])
        topic = m.get("topic", "")
        start = m.get("start_time", "")[:10]

        # Skip if too old
        try:
            meeting_date = datetime.strptime(start, "%Y-%m-%d").date()
            if (today - meeting_date).days > DAYS_BACK:
                continue
        except:
            continue

        # Skip if already synced
        existing = conn.execute(
            "SELECT id FROM zoom_meetings WHERE meeting_id=?", (mid,)
        ).fetchone()
        if existing:
            continue

        # Get past instances → UUID
        try:
            inst_data = zoom_get(token, f"/past_meetings/{mid}/instances")
            instances = inst_data.get("meetings", [])
        except:
            continue

        for inst in instances[:1]:
            uuid = inst.get("uuid", "")
            if uuid.startswith("/") or "//" in uuid:
                enc = urllib.parse.quote(urllib.parse.quote(uuid, safe=""), safe="")
            else:
                enc = urllib.parse.quote(uuid, safe="")

            try:
                s = zoom_get(token, f"/meetings/{enc}/meeting_summary")
            except:
                continue

            summary = s.get("summary_content", "") or ""
            next_steps = s.get("next_steps", [])
            participants = [p.get("display_name", "") for p in s.get("participants", [])]

            if not summary and not next_steps:
                continue

            # Save to DB
            conn.execute(
                """INSERT OR IGNORE INTO zoom_meetings
                   (meeting_id, uuid, topic, date, summary, next_steps, participants)
                   VALUES (?,?,?,?,?,?,?)""",
                (mid, uuid, topic, start, summary,
                 json.dumps(next_steps), json.dumps(participants))
            )

            # Match to CRM contacts and update last_contact_days
            name_hints = extract_names_from_topic(topic)
            matched_contacts = []
            for hint in name_hints:
                contact = find_crm_contact(conn, hint)
                if contact:
                    days = (today - meeting_date).days
                    conn.execute(
                        """UPDATE contacts SET last_contact_days=?, last_contact_raw=?
                           WHERE id=? AND (last_contact_days IS NULL OR last_contact_days > ?)""",
                        (days, f"{days}d ago (Zoom)", contact["id"], days)
                    )
                    matched_contacts.append(contact["name"])

                    # Log meeting
                    conn.execute(
                        """INSERT INTO log (contact_id, action, note) VALUES (?,?,?)""",
                        (contact["id"], "call_done",
                         f"Zoom: {topic} ({start})")
                    )

            # Save Mariia's next steps as reminders
            for step in next_steps:
                if "mariia" in step.lower() or "мария" in step.lower() or "мар" in step.lower():
                    for contact_name in matched_contacts:
                        c = conn.execute(
                            "SELECT id FROM contacts WHERE name=? LIMIT 1", (contact_name,)
                        ).fetchone()
                        if c:
                            conn.execute(
                                """INSERT INTO reminders (contact_id, meeting_id, due_date, action)
                                   VALUES (?,?,?,?)""",
                                (c["id"], mid, start, step[:300])
                            )

            new_summaries.append({
                "topic": topic,
                "date": start,
                "matched": matched_contacts,
                "summary": summary[:300],
                "next_steps": next_steps,
            })

    conn.commit()
    conn.close()

    # Send Telegram notifications
    if not new_summaries:
        print("No new summaries found.")
        return

    for s in new_summaries:
        my_steps = [ns for ns in s["next_steps"]
                    if "mariia" in ns.lower() or "мария" in ns.lower() or "мар" in ns.lower()]
        their_steps = [ns for ns in s["next_steps"]
                       if ns not in my_steps]

        lines = [f"📹 *Zoom Summary — {escape_md(s['date'])}*"]
        lines.append(f"_{escape_md(s['topic'])}_")
        if s["matched"]:
            lines.append(f"👤 CRM: {escape_md(', '.join(s['matched']))}")
        lines.append("")

        # Summary snippet — translate if Russian
        summary_short = s["summary"].split("\n\n")[0]
        for hdr in ("## Quick recap", "## Краткое резюме", "## Ключевые выводы", "## Краткие выводы"):
            summary_short = summary_short.replace(hdr, "")
        summary_short = translate_to_en(summary_short.strip())
        if summary_short:
            lines.append(escape_md(summary_short[:250]))
            lines.append("")

        if my_steps:
            lines.append("*✅ Your action items:*")
            for step in my_steps[:4]:
                clean = re.sub(r"^Mariia[:\s]+|^Мария[:\s]+|^Мар[:\s]+", "", step, flags=re.IGNORECASE).strip()
                clean = translate_to_en(clean)
                lines.append(f"• {escape_md(clean[:120])}")
            lines.append("")

        if their_steps:
            lines.append("*🔄 Their action items:*")
            for step in their_steps[:3]:
                step = translate_to_en(step)
                lines.append(f"• {escape_md(step[:120])}")

        try:
            send_telegram("\n".join(lines))
            print(f"✓ Sent: {s['topic']} ({s['date']})")
        except Exception as e:
            print(f"Telegram error: {e}")

    print(f"\nDone: {len(new_summaries)} new meetings synced.")


if __name__ == "__main__":
    sync()
