# Quick Reference: Encrypted API Key Management System

## Commands for Users

### `/addkey` - Add a new API key
Steps:
1. User triggers `/addkey`
2. Bot shows 4 service options:
   - Gemini (Google)
   - Llama3 (Groq)
   - Claude (Anthropic)
   - DeepSeek
3. User enters their API key
4. User gives the key a name (e.g., "Work Account", "Free Tier")
5. Bot stores it encrypted and ready to use

### `/mykeys` - Manage your keys
View:
- All stored API keys with service type
- How many calls each key has left
- Which key is currently active (marked with [A])

Actions:
- Click a key to make it active
- Click [+] Add key to add another

### `/start` - Begin a debate
- Bot checks that you have keys available
- If no keys: prompts to use `/addkey`
- If keys have 0 calls left: tells you which ones
- Otherwise: starts the debate using your active key

---

## Technical Architecture

### Database Tables

**user_api_keys** - Stores encrypted API keys
```
id          | Auto-increment ID
owner_id    | Which user this key belongs to
api_key     | The key (ENCRYPTED)
service     | Which AI service (gemini, groq, claude, deepseek)
alias       | Human name for this key
calls_left  | How many API calls remain
is_active   | Whether this is the selected key
created_at  | When it was added
```

**user_profiles** - User account info
```
user_id        | Telegram user ID
username       | Telegram username
active_key_id  | Which key is currently selected
```

### Encryption Flow

```
User Input (plaintext API key)
        ↓
encrypt_key() - Uses Fernet cipher
        ↓
Encrypted string stored in DB
        ↓
When debate starts:
decrypt_key() - Reverses encryption
        ↓
Pass decrypted key to AI client
        ↓
After API call:
decrement_calls() - Reduce counter in DB
```

---

## File Changes Summary

### bot.py
- Added: `/addkey` command with 3-step FSM
- Added: `/mykeys` command with key management UI
- Modified: Debate startup to load keys from DB
- Modified: Call tracking after each debate round

### database.py
- Fixed: Fernet key format validation
- Database methods handle encryption/decryption internally

### ai_clients.py
- Modified: All clients accept API key as parameter
- Added: AI_CLIENTS_MAP for dynamic client loading

---

## Environment Setup

Required in `.env` or deployment environment:
```bash
# Master encryption key (can be any string, will be hashed)
ENCRYPTION_KEY=my-secret-key-for-encryption

# PostgreSQL database
DATABASE_URL=postgresql://user:password@hostname:5432/dbname

# Telegram bot token
TELEGRAM_BOT_TOKEN=1234567890:ABCDefGHijKLmnoPQRstUVwxYz
```

---

## Error Messages Users May See

| Message | Meaning | Fix |
|---------|---------|-----|
| "You need to add API keys" | No keys stored yet | Use `/addkey` |
| "Please select an active key" | No key marked as active | Use `/mykeys` and click one |
| "No available keys with calls" | All keys exhausted | Add new key with `/addkey` or wait for quota reset |
| "Key name already exists" | Duplicate alias | Use a different name |
| "Key too short" | Invalid API key format | Make sure you copied the full key |

---

## How Encryption Works (Technical)

1. **Master Key Setup**
   - ENCRYPTION_KEY from environment
   - If > 44 chars: SHA256 hash → Base64 encode (= 44 chars)
   - If < 44 chars: used as-is (must be valid base64)

2. **Encryption Process**
   - Fernet cipher from cryptography library
   - API key string → bytes → encrypted bytes → base64 string
   - Stored in DB as text (encrypted)

3. **Decryption Process**
   - Encrypted string from DB → bytes
   - Fernet decipher → original API key string
   - Passed to AI client constructor
   - Discarded after use (not cached)

4. **Key Isolation**
   - Each user_id owns their own keys
   - Each key tied to one user (owner_id)
   - Aliases must be unique per user (not globally)
   - Can't access other users' keys

---

## Testing

Run: `python test_flow.py`

Tests included:
- ✓ Encryption/decryption roundtrip
- ✓ All 4 AI services available
- ✓ Database methods exist
- ✓ FSM states defined
- ✓ Client initialization works

---

## Deployment Checklist

Before deploying:
- [ ] Set ENCRYPTION_KEY environment variable
- [ ] Set DATABASE_URL to PostgreSQL instance
- [ ] Set TELEGRAM_BOT_TOKEN
- [ ] Run `pip install -r requirements.txt`
- [ ] Run `python test_flow.py` (should pass all tests)
- [ ] Start bot with `python src/bot.py`

---

## Troubleshooting Commands

### Check bot can start
```bash
python -c "from src.bot import main_bot_setup; print('OK')"
```

### Test encryption
```bash
python test_flow.py
```

### Check environment
```bash
echo $ENCRYPTION_KEY
echo $DATABASE_URL
echo $TELEGRAM_BOT_TOKEN
```

---

## Version Info

- **Python**: 3.14+
- **Encryption**: cryptography 41.0.7+
- **Database**: PostgreSQL 12+
- **Telegram**: python-telegram-bot 20.5+

---

**Status**: ✅ Production Ready
**Last Updated**: December 13, 2025
