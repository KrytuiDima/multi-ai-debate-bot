# 🎯 Quick Fix: Multiple Instances on Railway

## Problem
Bot is showing: `Conflict: terminated by other getUpdates request`

This means **2+ bot instances are running at the same time**.

---

## Fix (2 Minutes)

### Step 1: Open Railway Dashboard
https://railway.app/dashboard

### Step 2: Go to Worker Service
Click: Your Project → **Worker** service

### Step 3: Check Deployments
Scroll down to **Deployment** section

**Count how many show "Running":**
- ✅ Good: 1 instance
- ❌ Bad: 2+ instances

### Step 4: Remove Extra Instances
Click the **×** button on extra running deployments

Keep only **1** running instance

### Step 5: Verify
- Wait 30 seconds
- Send `/start` to bot in Telegram
- Check Railway logs for NO "Conflict detected"

---

## What I Fixed

✅ Error handler now **suppresses Conflict errors**
✅ Bot won't crash during restarts
✅ Clear messages show when conflicts happen

---

## If Issue Persists

Check Railway Scale Settings:

1. Worker → **Settings** (gear icon)
2. Find **Scale** section
3. Set **Instances** to: `1`
4. Save
5. Redeploy

---

## Monitor in Railway Logs

Look for:
- ✅ `⚠️  Conflict detected: Another bot instance is running`
- ✅ Single `Instance ID: worker-...` 
- ❌ Multiple "Бот запущено" messages = problem

---

**Next**: Follow the steps above, then test with `/start` in Telegram
