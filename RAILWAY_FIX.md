# 🚂 Railway Deployment: Fix Multiple Instances

## Problem
```
telegram.error.Conflict: Conflict: terminated by other getUpdates request
```

Your bot is running on Railway with **multiple active instances** polling Telegram simultaneously.

---

## Root Cause
Railway has spawned multiple **worker processes** or **dynos**, all trying to poll the same Telegram bot token.

Only **ONE** polling instance allowed per token!

---

## Solution

### ✅ What I Fixed
1. Error handler now **suppresses Conflict errors** gracefully
2. Bot won't crash when another instance starts
3. Clear logging shows when conflicts occur

### 🚀 What You Need to Do

#### **Option 1: Stop Extra Instances (Recommended)**

In Railway Dashboard:

1. Go to Your Project
2. Click **Worker** service
3. Scroll down to **Deployment**
4. Look for multiple running instances
5. Click the **×** on all but ONE instance to remove them

**Expected**: Only 1 "Running" instance remains

#### **Option 2: Use Scale Settings**

In Railway Dashboard:

1. Go to **Worker** service
2. Click **Settings** (gear icon)
3. Find **Scale** section
4. Set:
   - **Instances**: `1` (only one!)
   - **Memory**: Keep default
5. Save

#### **Option 3: Complete Railway Reset**

If above doesn't work:

1. **In Railway Dashboard**:
   - Worker → Settings → **Remove Environment**
   - Click **Redeploy**
   - Wait for green ✅

2. **Verify webhook deleted**:
   ```bash
   curl "https://api.telegram.org/bot{YOUR_TOKEN}/getWebhookInfo"
   ```
   
   Should show:
   ```json
   {"ok":true,"result":{"url":"","has_custom_certificate":false,"pending_update_count":0}}
   ```

---

## How to Monitor

### Check Railway Logs (Real-time)
1. Railway Dashboard → Worker → **Logs**
2. Look for:
   - ✅ `Бот запущено у режимі Polling...` (one instance)
   - ✅ `Instance ID: worker-abc123_12345_67890` (single ID)
   - ❌ Multiple "Бот запущено" messages = multiple instances

### Check Active Instances
1. Railway Dashboard → Worker → **Deployments**
2. Count how many show "Running" status
3. Should be: **1 only**

### Monitor for Conflicts
1. In Railway logs, search for: `Conflict detected`
2. If you see it: Another instance is active
3. Follow "Stop Extra Instances" above

---

## What Changed in Bot Code

### Error Handler
```python
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    error_msg = str(error)
    
    # Suppresses Conflict errors gracefully (normal during restarts)
    if "Conflict" in error_msg or "terminated by other getUpdates" in error_msg:
        print(f"⚠️  Conflict detected: Another bot instance is running")
        print(f"Деталі: {error_msg}")
        return  # Don't crash, just log and continue
    
    # Log other errors normally
    print(f"Update caused error {type(error).__name__}: {error_msg}")
```

**Result**: Bot handles conflicts gracefully without crashing ✅

---

## Step-by-Step Fix

1. **Open Railway Dashboard**
   - https://railway.app/dashboard

2. **Select Your Project**
   - Click project name

3. **Find Worker Service**
   - Click "Worker" in the services list

4. **Check Deployment Count**
   - Scroll to "Deployment" section
   - Count running instances
   - **Should be: 1 only**

5. **Stop Extra Instances**
   - Click **×** on extra running instances
   - Confirm deletion

6. **Verify in Telegram**
   - Send `/start` to bot
   - Should respond normally
   - No "Conflict" errors in Railway logs

7. **Monitor Next Hour**
   - Watch Railway logs for conflicts
   - If conflicts appear = still multiple instances
   - Repeat Step 5

---

## Testing the Fix

### Local Test (Optional)
```bash
# Run bot locally (don't keep it running!)
python -m src.bot
```

Should show:
```
Бот запущено у режимі Polling...
Instance ID: your_machine_abc123_12345_67890
Забезпечуємо єдину активну інстанцію...
```

Stop with **Ctrl+C**

### Production Test
1. Redeploy on Railway (if you made scale changes)
2. Wait 30 seconds for new instance to start
3. Send `/start` in Telegram
4. Check Railway logs for NO "Conflict" errors

---

## Common Issues

### Still Getting Conflict Error?

**Check**:
- How many instances showing "Running" in Railway?
- Are you seeing multiple "Бот запущено" in logs?

**Fix**:
1. Stop all extra instances (leave 1)
2. Wait 60 seconds
3. Try `/start` again

### Logs Show Multiple Instance IDs?

Different IDs = multiple instances running!

**Fix**:
- Go to Railway Dashboard
- Worker → Deployments
- Remove all but ONE running instance

### Webhook Still Set?

Run:
```bash
python reset_webhook.py
```

Should return: `"url":""`

---

## Railway Scale Configuration

**Location**: Worker Service → Settings → Scale

**Correct Settings**:
- **Instances**: `1`
- **Memory**: `512MB` or `1GB`
- **CPU**: default

**Wrong Settings** (will cause multiple instances):
- Instances: `2` or higher
- Multiple dynos active

---

## Prevention

To prevent this in future:

1. **Set Scale to 1** in Railway (do this now!)
2. **Delete webhook** before deploying (do `python reset_webhook.py`)
3. **Monitor deployments** - watch for multiple instances
4. **Check logs regularly** - look for Conflict errors

---

## Success Criteria

✅ Bot is ready when:
- [ ] Only 1 instance running in Railway
- [ ] `/start` command works in Telegram
- [ ] Railway logs show NO "Conflict detected"
- [ ] Error handler catches other errors gracefully
- [ ] `Instance ID: ...` appears once per restart

---

## Support

If still failing:

1. Share Railway logs showing the Conflict
2. Tell me how many instances show "Running"
3. Confirm you deleted webhook with `python reset_webhook.py`

---

**Updated**: 2025-12-13
**Status**: 🔧 In Progress - Monitor and Follow Steps Above
