<div align="center">

# 🧠 Personal CRM
### AI-Powered Outreach Assistant for Founders

*Built by a founder, for founders — because relationships are the only pipeline that matters.*

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![SQLite](https://img.shields.io/badge/Storage-SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![Telegram](https://img.shields.io/badge/Notifications-Telegram-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://telegram.org)
[![Zoom](https://img.shields.io/badge/Syncs-Zoom_AI-2D8CFF?style=flat-square&logo=zoom&logoColor=white)](https://zoom.us)
[![LinkedIn](https://img.shields.io/badge/Imports-LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white)](https://linkedin.com)
[![License](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)

**[Why I built this](#the-problem-this-solves) · [What it does](#what-it-does) · [Setup in 15 min](#setup-in-15-minutes) · [CLI reference](#cli)**

</div>

---

Most CRMs are built for sales teams with pipelines and quotas. This one is built for a single person managing 60–100 high-value relationships across investors, enterprise clients, and strategic partners — where every message matters and timing is everything.

---

## The problem this solves

When you're running a company and managing relationships across Zoom calls, LinkedIn messages, and email threads, things fall through the cracks. You forget who you spoke to last week. You lose track of what you promised. You don't know who's going cold.

This system fixes that — automatically.

---

## What it does

Every weekday at 8:00 AM, your phone gets a Telegram message:

```
📋 Reach Out Today — Mon 23 Jun

1. 🔥 Alex Chen
   Chief People Officer · Acme Corp
   Awaits response · 60d ago
   → Hi Alex, just a gentle nudge on my earlier note —
     happy to adjust timing or format, whatever works best.

2. 🎓 Sarah Williams
   VP Transformation · GlobalTech
   Discovery done, ready for proposal · 78d ago
   → Hi Sarah, loved our discovery session — ready to sketch the
     co-design proposal. Can we do 30 min to align on scope?
...
```

Each contact comes with a **ready-to-send message** — not a template, but a context-aware sentence based on where the relationship actually stands.

---

## How the intelligence works

### Contact scoring

Every contact gets a score computed from three signals:

```
score = priority_tier + status_urgency + min(days_since_contact × 3, 300)
```

| Signal | What it captures |
|--------|-----------------|
| **Priority tier** | Strategic importance (HOT=400, Investor=80, Cold=50…) |
| **Status urgency** | Relationship state ("damage control"=100, "awaits response"=80…) |
| **Recency** | Days since last touchpoint — capped at 300 to prevent staleness dominating |

### Data sources synced automatically

| Source | What's pulled |
|--------|--------------|
| **Zoom AI Summaries** | Meeting recap, your action items, their action items |
| **LinkedIn** | Connection history, message threads, last contact date |
| **Gmail** | Thread activity logged back to contacts |

The system reconciles all three sources and always uses the most recent contact date — so if you messaged someone on LinkedIn yesterday but the Excel says 30 days ago, the score reflects reality.

### Outreach message generation

Messages are generated per-contact based on status keywords. No generic "just checking in" — each message is specific to the relationship state:

- **Damage control** → apologetic, action-oriented, offers new slots
- **Missed time slot** → brief, proposes concrete alternatives
- **Strong relationship** → casual, no pitch, genuine catch-up
- **Not met yet (Stanford)** → shared context lead-in, specific ask
- **Post-Zoom** → references the actual call topic as the hook

---

## Architecture

```
crm/
├── config.py            ← credentials (git-ignored)
├── config.example.py    ← setup template
├── crm.py               ← CLI: import / score / log / search / skip
├── morning_sync.py      ← 8:00 AM: sync all sources → send digest
├── zoom_sync.py         ← 7:00 PM: pull Zoom AI Summaries → Telegram
├── send_reminders.py    ← 9:00 AM: overdue action items → Telegram
├── update_crm.py        ← refresh contact data + regenerate outreach messages
└── launchagents/        ← macOS scheduler (launchd plist files)
```

**Fully self-hosted.** Runs on your Mac. No cloud, no subscription, no data leaving your machine except to APIs you already use (Zoom, Telegram, LinkedIn).

**Zero external dependencies** (except `openpyxl` for Excel import). Uses Python stdlib: `sqlite3`, `urllib`, `json`.

---

## Automated schedule

| Time | What runs |
|------|-----------|
| Mon–Fri 8:00 AM | Sync Zoom + LinkedIn → rank contacts → send digest with outreach messages |
| Daily 9:00 AM | Check reminders table → send overdue / due today / due tomorrow |
| Daily 7:00 PM | Pull today's Zoom AI Summaries → extract action items → save as reminders |

---

## CLI

```bash
python3 crm.py today                        # ranked list with scores
python3 crm.py show "Sarah Williams"        # full contact detail
python3 crm.py log "Alex Chen" call_done "Sent follow-up, he's interested"
python3 crm.py history "Alex Chen"          # full activity log
python3 crm.py search "enterprise"          # search across all fields
python3 crm.py skip "acme-vendor"           # hide from digest (vendors, spam)
python3 crm.py skip "acme-vendor" --undo
```

---

## Setup in 15 minutes

### 1. Clone

```bash
git clone https://github.com/YOUR_USERNAME/personal-crm.git
cd personal-crm
cp config.example.py config.py
```

### 2. Install the one dependency

```bash
pip3 install openpyxl
```

### 3. Create a Telegram bot (2 min)

1. Message [@BotFather](https://t.me/BotFather) → `/newbot`
2. Paste the token into `config.py` → `BOT_TOKEN`
3. Send `/start` to your bot, then visit:
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → copy your `chat_id`

### 4. Connect Zoom (5 min)

1. [marketplace.zoom.us](https://marketplace.zoom.us) → Develop → Build App → **Server-to-Server OAuth**
2. Add scopes: `meeting:read:summary`, `meeting:read:meeting`, `meeting:read:list_past_instances` (+ `:admin` variants)
3. Copy Account ID, Client ID, Client Secret into `config.py`

### 5. Import your contacts

```bash
python3 crm.py import            # from Excel
python3 crm.py import-linkedin   # from LinkedIn export CSV
python3 crm.py today             # first run — see who to contact
```

### 6. Schedule (macOS)

```bash
# Edit plist files — replace the home directory path with yours
cp launchagents/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mariia.crm.daily.plist
launchctl load ~/Library/LaunchAgents/com.mariia.crm.zoom.plist
launchctl load ~/Library/LaunchAgents/com.mariia.crm.reminders.plist
```

Done. Tomorrow at 8 AM your digest arrives automatically.

---

## Excel format

The importer reads your existing contact spreadsheet. Expected columns:

| Column | Values |
|--------|--------|
| Name | Full name |
| Title | Job title |
| Company | Company name |
| Priority | `HOT` / `Stanford` / `Gartner` / `Warm` / `New` / `Investor` / `Cold` |
| Status | Free text — keywords drive urgency score |
| Last contact | `14d ago`, `Never`, or numeric days |
| Channel | `linkedin` / `email` / `intro` / `referral` |
| Why ICP | Why this is a target relationship |
| Next action | What to do next |
| Email | Email address |
| LinkedIn | Profile URL |
| Notes | Anything else |

---

## LinkedIn import

Export from [linkedin.com/settings](https://www.linkedin.com/settings/) → Data privacy → Get a copy → select **Connections** and **Messages**. Unzip, point `config.py` to the CSV files, run `python3 crm.py import-linkedin`.

The system matches LinkedIn contacts to your CRM by name and updates `last_contact_days` with the actual message date.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.9+ |
| Storage | SQLite (local, zero config) |
| Notifications | Telegram Bot API (MarkdownV2) |
| Meeting data | Zoom Server-to-Server OAuth + AI Summary API |
| Translation | Google Translate free tier (no key — auto-translates meeting summaries) |
| Scheduling | macOS launchd |
| Dependencies | `openpyxl` only |

---

## Why not just use HubSpot / Salesforce / Clay?

Those tools are great for teams. This is for one person who knows exactly which 70 relationships move the needle — and needs a system that works the way their brain does, not the way a sales funnel does.

---

<div align="center">

Built and used daily by **[Mariia Potupchik](https://www.linkedin.com/in/mariapotupchik/)** — CEO & Co-founder of **[YourSkills](https://yourskills.ai)**

*If this helped you, consider giving it a ⭐ — it helps other founders find it.*

MIT License · Contributions welcome

</div>
