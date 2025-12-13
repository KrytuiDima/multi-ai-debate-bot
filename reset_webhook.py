#!/usr/bin/env python3
"""
Script to reset Telegram webhook and prepare bot for fresh start
"""
import sys
import os
import json
from urllib.request import urlopen
from urllib.error import URLError
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
    sys.exit(1)

print("Resetting Telegram Webhook...")
print(f"Bot Token: {TOKEN[:20]}...")

# Delete any existing webhook
url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true"

try:
    response = urlopen(url, timeout=10)
    data = json.loads(response.read().decode())
    
    if data.get("ok"):
        print("✅ Webhook deleted successfully!")
        print(f"Result: {data.get('result')}")
        print(f"Description: {data.get('description', 'N/A')}")
        print("\nNow your bot will use Polling mode exclusively.")
        print("\nNext steps on Railway:")
        print("1. Go to your Railway dashboard")
        print("2. Click 'Redeploy' on your Worker service")
        print("3. Wait for the new instance to start")
        print("4. Bot should now work without conflicts!")
    else:
        print(f"❌ Error: {data.get('description')}")
        sys.exit(1)
        
except URLError as e:
    print(f"❌ Network Error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
