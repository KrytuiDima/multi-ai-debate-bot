# Telegram Conflict Fix Guide

## Problem
```
telegram.error.Conflict: Conflict: terminated by other getUpdates request
```

This means TWO bot instances are running simultaneously and competing for the same Telegram connection.

## Root Cause
- Old Railway deployment is still polling
- New Railway deployment started polling
- Both trying to use the same bot token on Polling mode

## Solution (Step by Step)

### Step 1: Reset Telegram Webhook (Important!)

Run this command to delete any lingering webhook configuration:

```bash
python reset_webhook.py
```

You should see:
```
✅ Webhook deleted successfully!
Result: True
Description: Webhook was deleted
```

**Why**: Even though we use Polling mode, old webhook configurations can interfere.

### Step 2: Stop Old Instances

In your local terminal (if running locally):
```bash
# Press Ctrl+C to stop
```

### Step 3: Redeploy on Railway

1. Go to [Railway Dashboard](https://railway.app)
2. Click on your **Project Name**
3. Click on the **Worker** service
4. In the top-right, click **Redeploy**
5. Choose "Deploy latest commit"
6. Wait for the deployment to complete (green checkmark appears)

### Step 4: Verify Single Instance

Check Railway logs - you should see:
```
Бот запущено у режимі Polling...
Instance ID: worker-xyz_12345_67890
Забезпечуємо єдину активну інстанцію...
```

**No "Conflict" errors** = Success! ✅

### Step 5: Test the Bot

In Telegram, type `/start` and verify it responds.

## Advanced: Force Stop Railway

If the issue persists:

1. **In Railway Dashboard**:
   - Click the Worker service
   - Click "Settings" (gear icon)
   - Click "Remove Environment"
   - Redeploy

2. **Or via Webhook Reset (Nuclear Option)**:

```bash
curl "https://api.telegram.org/botYOUR_TOKEN_HERE/deleteWebhook?drop_pending_updates=true"
```

Response should be:
```json
{"ok":true,"result":true,"description":"Webhook was deleted"}
```

## Troubleshooting Checklist

- [ ] Ran `python reset_webhook.py` successfully
- [ ] Redeployed on Railway (new green checkmark visible)
- [ ] Railway logs show NO "Conflict" error
- [ ] Single instance ID shown in logs
- [ ] Bot responds to `/start` in Telegram
- [ ] No multiple "Бот запущено" messages in logs

## If Still Failing

The error handler is now in place - it will:
1. Catch the Conflict error
2. Print a helpful message
3. Tell you exactly what to do

Check the error message in Railway logs - it will guide you.

## Key Files

- `reset_webhook.py` - Deletes webhook, unlocks bot
- `src/bot.py` - Updated with Conflict detection
- `requirements.txt` - All dependencies included

## Polling Mode Details

Our bot uses **Polling** (not Webhooks):
- Bot constantly asks: "Do you have updates for me?"
- Only ONE polling instance allowed per token
- Multiple instances = Conflict error

This is perfect for development, Railway free tier, and reliability.
