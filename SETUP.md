# Quick Start Guide - Local Development

## Setup (5 minutes)

### 1. Get Telegram Bot Token
- Open Telegram, search for `@BotFather`
- Send `/newbot` command
- Follow the instructions
- Copy the token you get

### 2. Setup Environment
```bash
# Edit .env file
# On Windows
notepad .env

# Add your bot token:
TELEGRAM_BOT_TOKEN=123456789:ABCDefGHijKLmnoPQRstUVwxYz...
ENCRYPTION_KEY=my-secret-encryption-key-here
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Bot
```bash
python src/bot.py
```

You should see:
```
Using SQLite (debate_bot.db) for local development
Бот запущено у режимі Polling...
```

---

## Using the Bot

### In Telegram:

1. **Start Bot**
   ```
   /start
   ```

2. **Add API Keys**
   ```
   /addkey
   ```
   - Select service (Gemini, Groq, Claude, DeepSeek)
   - Enter your API key
   - Give it a name (e.g., "My Groq Key")

3. **View Keys**
   ```
   /mykeys
   ```
   - Click a key to select it as active

4. **Start Debate**
   Just send any question:
   ```
   What is the best programming language?
   ```

---

## Troubleshooting

### Issue: "No module named 'cryptography'"
```bash
pip install cryptography
```

### Issue: "TELEGRAM_BOT_TOKEN invalid"
- Check `.env` file has correct token
- Make sure you copied the full token from BotFather

### Issue: "ENCRYPTION_KEY not set"
- Check `.env` file has ENCRYPTION_KEY line
- Make sure it's at least 20 characters long

### Issue: Database locked
- Delete `debate_bot.db` file and restart
```bash
rm debate_bot.db
python src/bot.py
```

---

## Files Created/Used

- `.env` - Your configuration (NEVER commit this)
- `debate_bot.db` - SQLite database (created automatically)
- `src/bot.py` - Main bot code
- `src/database.py` - Database manager
- `src/ai_clients.py` - AI service clients

---

## For Production (Railway/Vercel)

Set environment variables:
- `TELEGRAM_BOT_TOKEN`
- `ENCRYPTION_KEY`
- `DATABASE_URL` (PostgreSQL URL)

Then the bot will automatically use PostgreSQL instead of SQLite.

---

**Status**: Ready to use! 🚀
