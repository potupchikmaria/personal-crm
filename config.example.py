# Personal CRM — config template
# Copy this file to config.py and fill in your values.

from pathlib import Path

# ── Telegram ──────────────────────────────────────────────────────────────────
# Create a bot via @BotFather, then send /start to your bot and grab the chat_id
# from https://api.telegram.org/bot<TOKEN>/getUpdates
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID   = "YOUR_TELEGRAM_CHAT_ID"

# ── Zoom Server-to-Server OAuth ───────────────────────────────────────────────
# Create an app at marketplace.zoom.us → Develop → Build App → Server-to-Server OAuth
# Required scopes: meeting:read:list_past_instances, meeting:read:meeting,
#                  meeting:read:summary, meeting:read:list_past_instances:admin,
#                  meeting:read:meeting:admin, meeting:read:summary:admin
ZOOM_ACCOUNT_ID    = "YOUR_ZOOM_ACCOUNT_ID"
ZOOM_CLIENT_ID     = "YOUR_ZOOM_CLIENT_ID"
ZOOM_CLIENT_SECRET = "YOUR_ZOOM_CLIENT_SECRET"
ZOOM_USER_ID       = "YOUR_ZOOM_USER_ID"   # from /users/me endpoint or Zoom profile

# ── Data files ────────────────────────────────────────────────────────────────
# Path to your CRM Excel file (see README for expected columns)
CRM_XLSX             = Path("/path/to/your_crm.xlsx")
# Path to your meetings Excel file
MEETINGS_XLSX        = Path("/path/to/meetings.xlsx")
# Unzip your LinkedIn data export and point here
LINKEDIN_CONNECTIONS = Path("/path/to/linkedin_export/Connections.csv")
LINKEDIN_MESSAGES    = Path("/path/to/linkedin_export/messages.csv")

# ── Database ──────────────────────────────────────────────────────────────────
DB = Path(__file__).parent / "crm.db"
