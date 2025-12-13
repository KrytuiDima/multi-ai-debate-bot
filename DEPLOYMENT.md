# Deployment Guide: Multi-AI Debate Bot with Encrypted Keys

## Pre-Deployment Verification

### 1. System Requirements
```bash
python --version          # Should be 3.10+
pip --version            # Should be 20.0+
psql --version           # PostgreSQL client (optional, for manual DB checks)
```

### 2. Python Dependencies Check
```bash
pip install -r requirements.txt

# Verify key packages
python -c "import cryptography; print('cryptography OK')"
python -c "import psycopg2; print('psycopg2 OK')"
python -c "import telegram; print('telegram OK')"
```

### 3. Run Test Suite
```bash
python test_flow.py

# Should output:
# ======================================================================
# ALL TESTS PASSED!
# ======================================================================
```

## Environment Setup

### Option A: Local Development

Create `.env` file in project root:
```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCDefGHijKLmnoPQRstUVwxYzabcdefghij

# PostgreSQL Database
DATABASE_URL=postgresql://username:password@localhost:5432/debate_db

# Encryption Master Key (any string, will be hashed if > 44 chars)
ENCRYPTION_KEY=your-secure-random-string-here-minimum-32-chars

# Optional: Set mode (polling for local, webhook for Vercel)
BOT_MODE=polling
```

Start bot:
```bash
cd multi_ai_debate
python src/bot.py
```

### Option B: Vercel Deployment

1. **Create Vercel Project**
```bash
# If not already connected
vercel login
vercel link
```

2. **Set Environment Variables in Vercel Dashboard**
   - Go to Project Settings → Environment Variables
   - Add:
     - `TELEGRAM_BOT_TOKEN`: Your bot token
     - `DATABASE_URL`: PostgreSQL URL
     - `ENCRYPTION_KEY`: Random string (min 32 chars)

3. **Deploy**
```bash
git push                    # Triggers auto-deploy
# OR
vercel --prod
```

4. **Configure Telegram Webhook**
   - Get webhook URL from Vercel deployment
   - Run this once:
```python
import requests

TOKEN = "your-token-here"
WEBHOOK_URL = "https://your-vercel-domain.vercel.app/api/webhook"

url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
data = {"url": WEBHOOK_URL}
response = requests.post(url, json=data)
print(response.json())
```

### Option C: Railway.app Deployment

1. **Create Railway Project**
```bash
# Install Railway CLI
npm i -g @railway/cli

# Login and create project
railway login
railway init
```

2. **Add PostgreSQL Plugin**
   - In Railway dashboard, add PostgreSQL service
   - It auto-sets `DATABASE_URL` environment variable

3. **Add Environment Variables**
   - `TELEGRAM_BOT_TOKEN`
   - `ENCRYPTION_KEY`

4. **Deploy**
```bash
railway up
```

5. **Polling Mode** (automatic for Railway)
   - Bot uses polling instead of webhooks
   - No additional configuration needed

## Database Setup

### PostgreSQL Connection

For **Neon** (recommended for Vercel):
1. Create free account at neon.tech
2. Create new database
3. Copy "Connection string"
4. Use as `DATABASE_URL`

For **Local PostgreSQL**:
```bash
# Create database
createdb debate_db

# Connection string
postgresql://postgres:password@localhost:5432/debate_db
```

### Tables Auto-Creation
Tables are created automatically when bot starts:
- `user_profiles` - User accounts
- `user_api_keys` - Encrypted API keys
- `api_keys` - Legacy (kept for compatibility)

## Verification Checklist

### Pre-Launch Tests
```bash
# 1. Test imports
python -c "from src.bot import main_bot_setup; print('Bot OK')"

# 2. Test encryption
python test_flow.py

# 3. Test database connection
python -c "from src.database import DB_MANAGER; print('DB OK')"

# 4. Test AI clients
python -c "from src.ai_clients import AI_CLIENTS_MAP; print(list(AI_CLIENTS_MAP.keys()))"
```

### Manual Testing After Launch

1. **Add User to Bot**
   - Open Telegram
   - Search for bot by username
   - Send `/start`

2. **Test /addkey Flow**
   - Send `/addkey`
   - Select a service
   - Enter test API key
   - Give it a name
   - Verify "Key added successfully" message

3. **Test /mykeys**
   - Send `/mykeys`
   - Should see your key in list
   - Click to select as active

4. **Test Debate**
   - Send: "What is AI?"
   - Bot should start debate using your key
   - Verify both AI models respond

5. **Test Call Tracking**
   - Send another debate question
   - Check `/mykeys` - call count should decrease

## Monitoring & Maintenance

### View Logs

**Local (Polling)**
```bash
tail -f bot.log
```

**Vercel**
```bash
vercel logs
```

**Railway**
```bash
railway logs
```

### Common Log Messages

- `WARNING: DATABASE_URL не знайдено` - Database not connected
- `Таблиці успішно створені` - Database tables created
- `Бот запущено у режимі Polling` - Bot started in polling mode
- `Помилка при додаванні ключа` - Error adding key (check DB)

### Database Maintenance

**Backup Keys**
```bash
# PostgreSQL backup
pg_dump -h hostname -U username debate_db > backup.sql

# Restore
psql -h hostname -U username debate_db < backup.sql
```

**View User Keys** (debugging only)
```sql
SELECT user_id, alias, service, calls_remaining 
FROM user_api_keys 
ORDER BY created_at DESC;
```

**Reset Key Calls** (admin action)
```sql
UPDATE user_api_keys 
SET calls_remaining = 1000 
WHERE user_id = 123456789;
```

## Troubleshooting

### Issue: Bot doesn't respond to commands

**Cause**: Database not connected
```bash
# Check DATABASE_URL is set
echo $DATABASE_URL

# Verify PostgreSQL is running
psql -c "SELECT 1"
```

**Solution**: Verify DATABASE_URL and PostgreSQL server

### Issue: "ENCRYPTION_KEY not found"

**Cause**: Environment variable not set
```bash
# Set for current session
export ENCRYPTION_KEY="your-key-here"

# Or add to .env file
echo "ENCRYPTION_KEY=your-key-here" >> .env
```

### Issue: Keys won't decrypt

**Cause**: ENCRYPTION_KEY changed
- Keys encrypted with old key won't decrypt with new key
- If you must change: migrate keys or recreate them

**Prevention**: Store ENCRYPTION_KEY securely, never change

### Issue: API calls fail mid-debate

**Cause**: API key is invalid or calls exhausted

**Solution**:
- Check key with `/mykeys`
- Add new key with `/addkey`
- Verify API key is correct (test in Groq/Google/Anthropic consoles)

### Issue: PostgreSQL connection timeout

**Cause**: Network/firewall issue
```bash
# Test connection
psql $DATABASE_URL -c "SELECT 1"

# Check if host is reachable
ping neon.tech  # or your DB host
```

## Performance Optimization

### Call Limits
Each key has `calls_remaining` counter:
- Default: 1000 calls
- Decrements by 1 per debate (all models)
- Users can add multiple keys to increase capacity

### Scaling Considerations
- **Users**: System handles unlimited users
- **Keys per user**: No hard limit
- **Database**: PostgreSQL easily handles 10k+ keys
- **Bot performance**: Polling adds 0.5-1s latency

### Optimization Tips
```python
# In database.py, add indexes for faster queries
CREATE INDEX idx_owner_id ON user_api_keys(owner_id);
CREATE INDEX idx_user_id ON user_profiles(user_id);
```

## Security Best Practices

### Never Expose:
- ❌ ENCRYPTION_KEY in code
- ❌ DATABASE_URL in code
- ❌ TELEGRAM_BOT_TOKEN in code
- ❌ Decrypted API keys in logs

### Always:
- ✅ Use `.env` for local development (git-ignored)
- ✅ Use environment variables for production
- ✅ Rotate ENCRYPTION_KEY annually
- ✅ Audit user key access logs
- ✅ Remove inactive users' keys
- ✅ Use SSL/TLS for database connections

## Post-Deployment Checklist

- [ ] All environment variables set
- [ ] Database created and accessible
- [ ] Test suite passes (python test_flow.py)
- [ ] Bot responds to /start
- [ ] /addkey flow works end-to-end
- [ ] /mykeys displays added keys
- [ ] Debate starts and completes
- [ ] Logs show no errors
- [ ] Multiple users can use bot simultaneously
- [ ] Keys persist after bot restart

## Support & Escalation

### Common Issues Table

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Bot doesn't start | Missing TELEGRAM_BOT_TOKEN | Set env var |
| Commands don't work | DATABASE_URL not set | Configure PostgreSQL |
| Encryption fails | ENCRYPTION_KEY too short | Use 32+ char key |
| Slow response | Weak PostgreSQL connection | Check network |
| Keys disappear | DB not persisting | Verify DATABASE_URL |

### Getting Help

1. Check logs first: `python test_flow.py`
2. Verify environment: `echo $ENCRYPTION_KEY`
3. Test database: `psql $DATABASE_URL -c "SELECT 1"`
4. Review QUICK_REFERENCE.md for common issues

---

**Deployment Status**: ✅ Ready for Production
**Last Updated**: December 13, 2025
**Tested On**: Python 3.14.2, PostgreSQL 12+, python-telegram-bot 20.5
