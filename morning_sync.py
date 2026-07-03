#!/usr/bin/env python3
"""
Morning CRM sync — runs every weekday at 8:00.
Order: 1) Zoom sync  2) LinkedIn + data refresh  3) Gmail check  4) Send digest
"""

import sqlite3
import urllib.request
import urllib.parse
import json
import base64
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from config import (BOT_TOKEN, CHAT_ID, DB,
                    ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID,
                    ZOOM_CLIENT_SECRET, ZOOM_USER_ID)

ZOOM_DAYS_BACK = 2   # check last 2 days each morning (yesterday + today)

TOP_N = 7

PRIORITY_SCORE = {"HOT": 400, "Stanford": 200, "Gartner": 150,
                  "Warm": 120, "New": 100, "Investor": 80, "Cold": 50}
STATUS_URGENCY = {
    "damage control": 100, "missed time slot": 90, "awaits response": 80,
    "waiting for your response": 75, "fresh warm": 50, "active warm": 50,
    "need re-engagement": 40, "re-engagement": 40,
    "asked about raise": 35, "not met yet": 30, "strong relationship": 20,
    "cold but research-ready": 15, "not engaged yet": 10,
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def translate_to_en(text):
    if not text:
        return text
    cyrillic = sum(1 for c in text if 'Ѐ' <= c <= 'ӿ')
    if cyrillic < len(text) * 0.15:
        return text
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
        return text


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


# ─── Step 1: Zoom sync ────────────────────────────────────────────────────────

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
        raise RuntimeError(f"Zoom {path}: {body[:200]}")


def extract_names_from_topic(topic):
    topic = topic.replace("Mariia Potupchik", "").replace("Mariia", "").replace("'s", "")
    parts = re.split(r"[&,]|Zoom Meeting|Meeting|Sync|Call|Weekly|sync", topic)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 2]


def find_crm_contact(conn, name_hint):
    for word in name_hint.lower().split():
        if len(word) < 3:
            continue
        row = conn.execute(
            "SELECT * FROM contacts WHERE lower(name) LIKE ? LIMIT 1",
            (f"%{word}%",)
        ).fetchone()
        if row:
            return row
    return None


def sync_zoom(conn):
    log("Zoom: fetching recent meetings...")
    try:
        token = get_zoom_token()
    except Exception as e:
        log(f"Zoom auth failed: {e}")
        return []

    today = date.today()
    try:
        meetings_data = zoom_get(token, f"/users/{ZOOM_USER_ID}/meetings?type=previous_meetings&page_size=30")
    except Exception as e:
        log(f"Zoom meetings list failed: {e}")
        return []

    meetings = meetings_data.get("meetings", [])
    new_summaries = []

    for m in meetings:
        mid = str(m["id"])
        topic = m.get("topic", "")
        start = m.get("start_time", "")[:10]

        try:
            meeting_date = datetime.strptime(start, "%Y-%m-%d").date()
            if (today - meeting_date).days > ZOOM_DAYS_BACK:
                continue
        except:
            continue

        existing = conn.execute(
            "SELECT id FROM zoom_meetings WHERE meeting_id=?", (mid,)
        ).fetchone()
        if existing:
            continue

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

            conn.execute(
                """INSERT OR IGNORE INTO zoom_meetings
                   (meeting_id, uuid, topic, date, summary, next_steps, participants)
                   VALUES (?,?,?,?,?,?,?)""",
                (mid, uuid, topic, start, summary,
                 json.dumps(next_steps), json.dumps(participants))
            )

            name_hints = extract_names_from_topic(topic)
            matched = []
            for hint in name_hints:
                contact = find_crm_contact(conn, hint)
                if contact:
                    days = (today - meeting_date).days
                    conn.execute(
                        """UPDATE contacts SET last_contact_days=?, last_contact_raw=?
                           WHERE id=? AND (last_contact_days IS NULL OR last_contact_days > ?)""",
                        (days, f"{days}d ago (Zoom)", contact["id"], days)
                    )
                    matched.append(contact["name"])
                    conn.execute(
                        "INSERT INTO log (contact_id, action, note) VALUES (?,?,?)",
                        (contact["id"], "call_done", f"Zoom: {topic} ({start})")
                    )

            # Save reminders
            for step in next_steps:
                if "mariia" in step.lower() or "мария" in step.lower():
                    for cname in matched:
                        c = conn.execute(
                            "SELECT id FROM contacts WHERE name=? LIMIT 1", (cname,)
                        ).fetchone()
                        if c:
                            conn.execute(
                                "INSERT INTO reminders (contact_id, meeting_id, due_date, action) VALUES (?,?,?,?)",
                                (c["id"], mid, start, step[:300])
                            )

            new_summaries.append({
                "topic": topic, "date": start,
                "matched": matched, "summary": summary,
                "next_steps": next_steps,
            })

    conn.commit()
    log(f"Zoom: {len(new_summaries)} new meetings synced")
    return new_summaries


# ─── Step 2: Update last_contact from LinkedIn + regenerate outreach_msg ──────

def short_message(name, status, company, zoom_summary=None):
    s = (status or "").lower()
    first = name.split()[0] if name else name
    co = company or ""

    if zoom_summary:
        snip = zoom_summary[:100].split(".")[0]
        return f"Hey {first}, following up on our call — {snip.strip().lower()}. Would love to keep the momentum going."
    if "damage control" in s:
        return f"Hi {first}, so sorry for going quiet — still very interested. Can we find 20 min this week?"
    if "missed time slot" in s:
        return f"Hi {first}, apologies for the scheduling miss! Does Wednesday 11am or Thursday 2pm work?"
    if "awaits response" in s or "awaiting" in s:
        return f"Hi {first}, just a gentle nudge on my earlier note — happy to adjust timing or format."
    if "waiting for your response" in s:
        return f"Hi {first}, checking back — a quick 15-min intro might be easier if that suits better."
    if "fresh warm" in s or "active warm" in s:
        return f"Hey {first}, loved our last chat — quick update on YourSkills that's relevant to {co}. Got 20 min?"
    if "strong relationship" in s or "friend" in s:
        return f"Hey {first}! Quick update — anything new on your side? Would love to catch up."
    if "discovery done" in s or "co-design" in s:
        return f"Hi {first}, ready to sketch the co-design proposal — can we do 30 min to align on scope?"
    if "re-engagement" in s or "re-engage" in s:
        return f"Hi {first}, it's been a while — YourSkills just launched Team Dashboard. Might be timely for {co}?"
    if "not met yet" in s or "not engaged" in s:
        return f"Hi {first}, fellow Stanford LEAD alum — building YourSkills (AI for workforce). 20 min to hear about {co}?"
    if "cold but research" in s:
        return f"Hi {first}, following {co}'s work closely — think there's a fit with YourSkills. Open to a quick intro?"
    if "pause" in s:
        return f"Hi {first}, soft check-in — we launched Team Dashboard, might change the calculus if timing works now?"
    if "asked about raise" in s:
        return f"Hi {first}, happy to discuss pricing that works for your budget — what would make this a yes?"
    if "self-initiated" in s or "design partner" in s:
        return f"Hi {first}, our Design Partner program (90 days, co-build) seems like a great fit — this week?"
    if "meeting confirmed" in s:
        return f"Looking forward to our call, {first}! Sending Zoom link — anything specific to cover?"
    if "already responded" in s:
        return f"Great connecting, {first}! Next: 20-min Zoom — does early next week work?"
    return f"Hi {first}, wanted to reconnect and share a quick update on YourSkills — think there's a fit with {co}. 20 min?"


def update_contacts(conn):
    log("Updating contacts from LinkedIn + Zoom...")
    today = date.today()

    # Ensure outreach_msg column exists
    cols = [c['name'] for c in conn.execute('PRAGMA table_info(contacts)').fetchall()]
    if 'outreach_msg' not in cols:
        conn.execute('ALTER TABLE contacts ADD COLUMN outreach_msg TEXT')

    contacts = conn.execute("SELECT * FROM contacts WHERE skip=0 OR skip IS NULL").fetchall()

    for c in contacts:
        cid = c['id']
        name = c['name'] or ""
        days = c['last_contact_days']
        zoom_summary = None

        # LinkedIn
        for word in name.lower().split():
            if len(word) < 3:
                continue
            li = conn.execute(
                "SELECT * FROM linkedin WHERE lower(name) LIKE ? AND last_msg_days IS NOT NULL ORDER BY last_msg_days ASC LIMIT 1",
                (f"%{word}%",)
            ).fetchone()
            if li:
                li_days = li['last_msg_days']
                if days is None or li_days < days:
                    conn.execute(
                        "UPDATE contacts SET last_contact_days=?, last_contact_raw=? WHERE id=?",
                        (li_days, f"{li_days}d ago (LinkedIn)", cid)
                    )
                    days = li_days
                break

        # Zoom
        first = name.split()[0].lower()
        if len(first) >= 3:
            zm = conn.execute(
                "SELECT * FROM zoom_meetings WHERE lower(topic) LIKE ? ORDER BY date DESC LIMIT 1",
                (f"%{first}%",)
            ).fetchone()
            if zm:
                try:
                    zm_days = (today - date.fromisoformat(zm['date'])).days
                    if days is None or zm_days < days:
                        conn.execute(
                            "UPDATE contacts SET last_contact_days=?, last_contact_raw=? WHERE id=?",
                            (zm_days, f"{zm_days}d ago (Zoom)", cid)
                        )
                        days = zm_days
                    raw = (zm['summary'] or "")
                    for hdr in ("## Quick recap", "## Краткое резюме", "## Ключевые выводы"):
                        raw = raw.replace(hdr, "")
                    zoom_summary = raw.strip()[:200] or None
                except:
                    pass

        msg = short_message(name, c['status'], c['company'], zoom_summary)
        conn.execute("UPDATE contacts SET outreach_msg=? WHERE id=?", (msg, cid))

    conn.commit()
    log("Contacts updated")


# ─── Step 3: Gmail — check recent threads ────────────────────────────────────
# Gmail MCP is only available interactively; here we check if any contact
# email appears in the log from a recent gmail sync and update last_contact_days.

def update_from_gmail_log(conn):
    """
    If gmail sync was run recently (via CRM log), pick up those updates.
    The actual Gmail fetch happens via MCP in Claude sessions; this just
    processes anything already written to the log table.
    """
    today = date.today()
    rows = conn.execute(
        """SELECT l.contact_id, l.created_at FROM log l
           WHERE l.action='gmail_thread'
           ORDER BY l.id DESC"""
    ).fetchall()
    updated = 0
    for r in rows:
        try:
            log_date = datetime.fromisoformat(r['created_at']).date()
            days = (today - log_date).days
        except:
            continue
        c = conn.execute("SELECT last_contact_days FROM contacts WHERE id=?", (r['contact_id'],)).fetchone()
        if c and (c['last_contact_days'] is None or days < c['last_contact_days']):
            conn.execute(
                "UPDATE contacts SET last_contact_days=?, last_contact_raw=? WHERE id=?",
                (days, f"{days}d ago (Gmail)", r['contact_id'])
            )
            updated += 1
    if updated:
        conn.commit()
        log(f"Gmail log: updated {updated} contacts")


# ─── Step 4: Build and send digest ────────────────────────────────────────────

PRIORITY_EMOJI = {"HOT": "🔥", "Stanford": "🎓", "Gartner": "🏢",
                  "Warm": "🤝", "New": "🆕", "Investor": "💰", "Cold": "❄️"}


def score(c):
    s = PRIORITY_SCORE.get(c['priority'], 0)
    for kw, pts in STATUS_URGENCY.items():
        if kw in (c['status'] or '').lower():
            s += pts
            break
    d = c['last_contact_days']
    if d is not None:
        s += min(d * 3, 300)
    return s


def fmt_days(days):
    if days is None: return "?"
    return "never" if days >= 999 else f"{days}d ago"


def strip_emoji(text):
    return re.sub(r'[^\x00-\x7Fа-яА-ЯёЁ\s\w.,!?:()\-/+@\"\']+', '', text or "").strip()


def send_digest(conn, zoom_new):
    log("Building digest...")
    today = date.today()
    rows = conn.execute("SELECT * FROM contacts WHERE skip=0 OR skip IS NULL").fetchall()
    ranked = sorted(rows, key=score, reverse=True)[:TOP_N]

    weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][today.weekday()]
    lines = [f"📋 *Reach Out Today — {weekday} {escape_md(today.strftime('%d %b'))}*\n"]

    for i, c in enumerate(ranked, 1):
        emoji = PRIORITY_EMOJI.get(c['priority'], "•")
        status = strip_emoji(c['status'] or "").strip(" —")
        action = (c['outreach_msg'] or c['next_action'] or "")[:160]
        action = re.sub(r'^[✉️📞🔗\s]+', '', action).strip()
        days_str = fmt_days(c['last_contact_days'])
        lines.append(
            f"{i}\\. {emoji} *{escape_md(c['name'] or '')}*\n"
            f"   {escape_md(c['title'] or '')} · {escape_md(c['company'] or '')}\n"
            f"   _{escape_md(status)}_ · {days_str}\n"
            f"   → {escape_md(action)}\n"
        )

    # Append Zoom summary note if new meetings found
    if zoom_new:
        lines.append(f"📹 _{escape_md(str(len(zoom_new)))} new Zoom meeting(s) synced — check summaries above_")

    send_telegram("\n".join(lines))
    log(f"Digest sent: {ranked[0]['name']}, {ranked[1]['name']} +{TOP_N-2} more")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log("=== Morning CRM sync started ===")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 1. Zoom
    zoom_new = sync_zoom(conn)

    # 2. Zoom summaries to Telegram (if any new)
    if zoom_new:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "zoom_sync", Path(__file__).parent / "zoom_sync.py")
        zm_mod = importlib.util.module_from_spec(spec)
        # Just send the summaries inline instead of re-importing
        for s in zoom_new:
            my_steps = [ns for ns in s["next_steps"]
                        if "mariia" in ns.lower() or "мария" in ns.lower()]
            their_steps = [ns for ns in s["next_steps"] if ns not in my_steps]
            tl = [f"📹 *Zoom Summary — {escape_md(s['date'])}*"]
            tl.append(f"_{escape_md(s['topic'])}_")
            if s["matched"]:
                tl.append(f"👤 CRM: {escape_md(', '.join(s['matched']))}")
            tl.append("")
            summary_short = s["summary"].split("\n\n")[0]
            for hdr in ("## Quick recap", "## Краткое резюме", "## Ключевые выводы", "## Краткие выводы"):
                summary_short = summary_short.replace(hdr, "")
            summary_short = translate_to_en(summary_short.strip())
            if summary_short:
                tl.append(escape_md(summary_short[:250]))
                tl.append("")
            if my_steps:
                tl.append("*✅ Your action items:*")
                for step in my_steps[:4]:
                    clean = re.sub(r"^Mariia[:\s]+|^Мария[:\s]+", "", step, flags=re.IGNORECASE).strip()
                    tl.append(f"• {escape_md(translate_to_en(clean)[:120])}")
            if their_steps:
                tl.append("\n*🔄 Their action items:*")
                for step in their_steps[:3]:
                    tl.append(f"• {escape_md(translate_to_en(step)[:120])}")
            try:
                send_telegram("\n".join(tl))
            except Exception as e:
                log(f"Zoom summary send error: {e}")

    # 3. Refresh contact data from LinkedIn + Zoom
    update_contacts(conn)

    # 4. Pick up any Gmail updates from log
    update_from_gmail_log(conn)

    # 5. Send digest
    send_digest(conn, zoom_new)

    conn.close()
    log("=== Done ===")


if __name__ == "__main__":
    main()
