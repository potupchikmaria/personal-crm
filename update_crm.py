#!/usr/bin/env python3
"""
Update CRM contacts with real data from Zoom/LinkedIn/log,
then generate a short outreach message for each contact.
"""
import sqlite3
import json
import re
from datetime import date
from pathlib import Path
from config import DB

# ─── Short outreach templates by status keyword ───────────────────────────────

def short_message(name, status, company, title, next_action, zoom_summary=None, li_snippet=None):
    """Return a 1-2 sentence outreach message."""
    s = (status or "").lower()
    first = name.split()[0] if name else name
    co = company or ""

    # Use zoom context if recent
    if zoom_summary:
        snip = zoom_summary[:120].split(".")[0]
        return f"Hey {first}, following up on our call — {snip.strip().lower()}. Would love to keep the momentum going."

    if "damage control" in s:
        return f"Hi {first}, so sorry for going quiet — I was sick last week. Still very interested in connecting with {co}. Can we find 20 min this week?"

    if "missed time slot" in s:
        return f"Hi {first}, apologies for the scheduling miss! Still very keen — does Wednesday 11am or Thursday 2pm work for a quick call?"

    if "awaits response" in s or "awaiting" in s:
        return f"Hi {first}, just a gentle nudge on my earlier note — happy to adjust timing or format, whatever works best for you."

    if "waiting for your response" in s:
        return f"Hi {first}, checking back on my last message — let me know if you'd like a quick 15-min intro instead, easier to schedule."

    if "fresh warm" in s or "active warm" in s:
        return f"Hey {first}, loved our last conversation — wanted to share a quick update on YourSkills that's directly relevant to {co}. Got 20 min this week?"

    if "strong relationship" in s or "friend" in s:
        return f"Hey {first}! Quick update from my end — {co} context aside, would love to catch up. Anything new on your side?"

    if "discovery done" in s or "co-design" in s:
        return f"Hi {first}, loved our discovery session — ready to sketch a co-design proposal. Can we do 30 min to align on scope?"

    if "re-engagement" in s or "re-engage" in s:
        return f"Hi {first}, it's been a while — just wanted to share that YourSkills launched Team Dashboard and Hidden Skills Discovery. Might be timely for {co}?"

    if "not met yet" in s or "not engaged" in s:
        return f"Hi {first}, fellow Stanford LEAD alum here — building YourSkills (AI for workforce development). Would love 20 min to hear what {co} is focused on."

    if "cold but research" in s:
        return f"Hi {first}, I've been following {co}'s work in this space — think there's a natural fit with what we're building at YourSkills. Open to a quick intro?"

    if "pause" in s:
        return f"Hi {first}, just a soft check-in — we launched Team Dashboard since we last spoke. Might change the calculus if timing works better now."

    if "asked about raise" in s:
        return f"Hi {first}, circling back — happy to discuss pricing/structure that works for your budget. What would make this a yes?"

    if "self-initiated" in s or "design partner" in s:
        return f"Hi {first}, excited about the fit you mentioned! Our Design Partner program (90 days, co-build) seems perfect — can we lock in a call this week?"

    if "meeting confirmed" in s:
        return f"Looking forward to our call, {first}! I'll send the Zoom link shortly — anything specific you'd like to cover?"

    if "already responded" in s:
        return f"Great connecting, {first}! Next step: I'll set up a 20-min Zoom — does early next week work?"

    # default
    return f"Hi {first}, wanted to reconnect and share what we're building at YourSkills — think there's a real fit with {co}. Open to a quick 20-min call?"


def normalize_name(n):
    return " ".join(n.lower().split())


def match_linkedin(conn, contact_name):
    """Find best LinkedIn match for a CRM contact."""
    words = contact_name.lower().split()
    for word in words:
        if len(word) < 3:
            continue
        row = conn.execute(
            "SELECT * FROM linkedin WHERE lower(name) LIKE ? ORDER BY last_msg_days ASC LIMIT 1",
            (f"%{word}%",)
        ).fetchone()
        if row:
            return row
    return None


def match_zoom(conn, contact_name):
    """Find Zoom meeting where topic contains the contact's first name."""
    first = contact_name.split()[0].lower()
    if len(first) < 3:
        return None
    rows = conn.execute(
        "SELECT * FROM zoom_meetings WHERE lower(topic) LIKE ? ORDER BY date DESC LIMIT 1",
        (f"%{first}%",)
    ).fetchall()
    return rows[0] if rows else None


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Add outreach_msg column if not exists
    cols = [c['name'] for c in conn.execute('PRAGMA table_info(contacts)').fetchall()]
    if 'outreach_msg' not in cols:
        conn.execute('ALTER TABLE contacts ADD COLUMN outreach_msg TEXT')
        conn.commit()

    today = date.today()
    contacts = conn.execute(
        "SELECT * FROM contacts WHERE skip=0 OR skip IS NULL ORDER BY id"
    ).fetchall()

    updated = 0
    for c in contacts:
        cid = c['id']
        name = c['name'] or ""
        days = c['last_contact_days']
        zoom_summary = None

        # 1. Check LinkedIn for more recent contact
        li = match_linkedin(conn, name)
        if li and li['last_msg_days'] is not None:
            li_days = li['last_msg_days']
            if days is None or li_days < days:
                conn.execute(
                    "UPDATE contacts SET last_contact_days=?, last_contact_raw=? WHERE id=?",
                    (li_days, f"{li_days}d ago (LinkedIn)", cid)
                )
                days = li_days

        # 2. Check Zoom meeting match
        zm = match_zoom(conn, name)
        if zm:
            zm_date = zm['date']
            try:
                zm_days = (today - date.fromisoformat(zm_date)).days
            except:
                zm_days = None
            if zm_days is not None and (days is None or zm_days < days):
                conn.execute(
                    "UPDATE contacts SET last_contact_days=?, last_contact_raw=? WHERE id=?",
                    (zm_days, f"{zm_days}d ago (Zoom)", cid)
                )
                days = zm_days
            # Extract summary snippet for message
            raw_summary = zm['summary'] or ""
            # strip headers
            for hdr in ("## Quick recap", "## Краткое резюме", "## Ключевые выводы"):
                raw_summary = raw_summary.replace(hdr, "")
            zoom_summary = raw_summary.strip()[:200] if raw_summary.strip() else None

        # 3. Generate short outreach message
        li_snippet = li['last_msg_snippet'] if li else None
        msg = short_message(
            name=name,
            status=c['status'],
            company=c['company'],
            title=c['title'],
            next_action=c['next_action'],
            zoom_summary=zoom_summary,
            li_snippet=li_snippet,
        )
        conn.execute("UPDATE contacts SET outreach_msg=? WHERE id=?", (msg, cid))
        updated += 1

    conn.commit()

    # Print updated contacts ranked by score
    PRIORITY_SCORE = {"HOT": 400, "Stanford": 200, "Gartner": 150,
                      "Warm": 120, "New": 100, "Investor": 80, "Cold": 50}
    STATUS_URGENCY = {
        "damage control": 100, "missed time slot": 90, "awaits response": 80,
        "waiting for your response": 75, "fresh warm": 50, "active warm": 50,
        "need re-engagement": 40, "re-engagement": 40,
        "asked about raise": 35, "not met yet": 30, "strong relationship": 20,
        "cold but research-ready": 15, "not engaged yet": 10,
    }

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

    rows = conn.execute(
        "SELECT * FROM contacts WHERE skip=0 OR skip IS NULL"
    ).fetchall()
    ranked = sorted(rows, key=score, reverse=True)

    print(f"Updated {updated} contacts. Top contacts to reach out today:\n")
    print(f"{'#':<3} {'Name':<30} {'Co':<25} {'Last':<10} {'Score':<6}  Outreach message")
    print("-" * 130)
    for i, c in enumerate(ranked[:20], 1):
        days_str = "?" if c['last_contact_days'] is None else (
            "never" if c['last_contact_days'] >= 999 else f"{c['last_contact_days']}d"
        )
        sc = score(c)
        msg = (c['outreach_msg'] or "")[:80]
        print(f"{i:<3} {(c['name'] or '')[:29]:<30} {(c['company'] or '')[:24]:<25} {days_str:<10} {sc:<6}  {msg}")

    conn.close()


if __name__ == "__main__":
    main()
