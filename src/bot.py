# src/bot.py
import asyncio
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    filters, ContextTypes, ConversationHandler
)
from database import DB_MANAGER
from ai_clients import AI_CLIENT_CLASSES
from debate_manager import DebateSession

# Логування
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# СТАНИ FSM
CHOOSING_ROUNDS = 1
AWAITING_SERVICE = 2
AWAITING_KEY = 3
AWAITING_ALIAS = 4

AVAILABLE_SERVICES = {
    'gemini': 'Gemini (Google)',
    'groq': 'Llama3 (Groq)',
    'claude': 'Claude (Anthropic)',
    'deepseek': 'DeepSeek'
}

# --- ЗБЕРІГАННЯ СТАНУ В RAM ---
active_sessions = {} # user_id -> DebateSession

# --- ДОПОМІЖНІ ФУНКЦІЇ ---

def get_main_menu(user_id):
    kb = [
        [InlineKeyboardButton("🔑 Мої Ключі", callback_data='cmd_mykeys')],
        [InlineKeyboardButton("➕ Додати Ключ", callback_data='cmd_addkey')],
        [InlineKeyboardButton("⚔️ Почати Дебати", callback_data='cmd_start_debate')],
        [InlineKeyboardButton("⚙️ Налаштування Раундів", callback_data='cmd_rounds')]
    ]
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Ініціалізація профілю в БД
    DB_MANAGER.get_user_profile(user.id, user.username)
    await update.message.reply_text(
        f"Привіт, {user.first_name}! Я AI Debate Bot.\n"
        "Я використовую ТВОЇ ключі для дебатів.\n"
        "Додай ключі і поїхали!",
        reply_markup=get_main_menu(user.id)
    )

# --- 1. ЛОГІКА ДОДАВАННЯ КЛЮЧІВ (BYOK) ---

async def addkey_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(name, callback_data=f"srv_{code}")] for code, name in AVAILABLE_SERVICES.items()]
    text = "Оберіть сервіс:"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return AWAITING_SERVICE

async def addkey_service_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    srv_code = query.data.split('_')[1]
    context.user_data['new_key_service'] = srv_code
    await query.edit_message_text(f"Введіть API ключ для {AVAILABLE_SERVICES[srv_code]}:")
    return AWAITING_KEY

async def addkey_receive_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    if len(key) < 5:
        await update.message.reply_text("Ключ занадто короткий. Спробуйте ще раз.")
        return AWAITING_KEY
    context.user_data['new_key_value'] = key
    await update.message.reply_text("Введіть назву (alias) для цього ключа (напр. 'Мій Gemini'):")
    return AWAITING_ALIAS

async def addkey_receive_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    alias = update.message.text.strip()
    user_id = update.effective_user.id
    
    success = DB_MANAGER.add_api_key(
        user_id, 
        context.user_data['new_key_service'], 
        context.user_data['new_key_value'], 
        alias
    )
    
    if success:
        await update.message.reply_text(f"✅ Ключ '{alias}' додано!", reply_markup=get_main_menu(user_id))
    else:
        await update.message.reply_text("❌ Помилка. Можливо, назва вже існує.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Скасовано.", reply_markup=get_main_menu(update.effective_user.id))
    return ConversationHandler.END

# --- 2. ЛОГІКА ПЕРЕГЛЯДУ КЛЮЧІВ ---

async def mykeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keys = DB_MANAGER.get_user_api_keys(user_id)
    if not keys:
        text = "У вас немає ключів."
    else:
        text = "<b>Ваші ключі:</b>\n"
        for k in keys:
            text += f"🔹 <b>{k['alias']}</b> ({k['service']}) - {k['calls_remaining']} calls\n"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=get_main_menu(user_id))
    else:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=get_main_menu(user_id))

# --- 3. ЛОГІКА РАУНДІВ ---

async def rounds_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("2", callback_data="rnd_2"), InlineKeyboardButton("3", callback_data="rnd_3")],
        [InlineKeyboardButton("5", callback_data="rnd_5"), InlineKeyboardButton("10", callback_data="rnd_10")],
        [InlineKeyboardButton("Ввести вручну", callback_data="rnd_custom")]
    ]
    text = "Скільки раундів?"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSING_ROUNDS

async def rounds_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')[1]
    if data == 'custom':
        await query.edit_message_text("Введіть число (>1):")
        return CHOOSING_ROUNDS
    
    rounds = int(data)
    context.user_data['rounds'] = rounds
    await query.edit_message_text(f"Встановлено раундів: {rounds}", reply_markup=get_main_menu(query.from_user.id))
    return ConversationHandler.END

async def rounds_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        if val < 2: raise ValueError
        context.user_data['rounds'] = val
        await update.message.reply_text(f"Встановлено раундів: {val}", reply_markup=get_main_menu(update.effective_user.id))
        return ConversationHandler.END
    except:
        await update.message.reply_text("Введіть число більше 1.")
        return CHOOSING_ROUNDS

# --- 4. ЛОГІКА ДЕБАТІВ ---

async def ask_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Напишіть тему для дебатів:")
    else:
        await update.message.reply_text("Напишіть тему для дебатів:")

async def handle_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    topic = update.message.text
    
    # 1. Отримуємо ключі користувача
    keys = DB_MANAGER.get_user_api_keys(user_id)
    valid_keys = [k for k in keys if k['calls_remaining'] > 0]
    
    if len(valid_keys) < 1: # Потрібен хоча б 1 ключ (можна симулювати опонента або якщо є 2 ключі - супер)
        await update.message.reply_text("❌ Потрібен хоча б 1 активний ключ з лімітом > 0. Додайте через /addkey.")
        return

    # 2. Ініціалізуємо клієнтів
    clients_map = {}
    
    # Логіка вибору: беремо перші 2 доступні ключі. 
    # Якщо ключ 1 -> Клон. Якщо ключів >= 2 -> Різні моделі.
    
    # Ключ 1
    k1 = valid_keys[0]
    decrypted1, srv1 = DB_MANAGER.get_api_key_decrypted(k1['id'], user_id)
    clients_map[f"{k1['alias']} ({srv1})"] = AI_CLIENT_CLASSES[srv1](decrypted1)
    DB_MANAGER.decrement_calls(k1['id'], user_id) # Знімаємо ліміт за старт
    
    # Ключ 2 (або той самий, якщо один)
    if len(valid_keys) >= 2:
        k2 = valid_keys[1]
        decrypted2, srv2 = DB_MANAGER.get_api_key_decrypted(k2['id'], user_id)
        clients_map[f"{k2['alias']} ({srv2})"] = AI_CLIENT_CLASSES[srv2](decrypted2)
        DB_MANAGER.decrement_calls(k2['id'], user_id)
    else:
        # Клон першого
        clients_map[f"{k1['alias']} (Opponent)"] = AI_CLIENT_CLASSES[srv1](decrypted1)
    
    # 3. Старт сесії
    rounds = context.user_data.get('rounds', 3)
    session = DebateSession(topic, clients_map, rounds)
    active_sessions[user_id] = session
    
    await update.message.reply_text(f"⚔️ Дебати розпочато! Раундів: {rounds}\nУчасники: {list(clients_map.keys())}")
    await run_round(update, context, session)

async def run_round(update, context, session):
    res = await session.run_next_round()
    if not res:
        await context.bot.send_message(update.effective_chat.id, "🏁 Дебати завершено!", reply_markup=get_main_menu(update.effective_user.id))
        return

    text = f"🔥 **Round {session.round}**\n\n"
    for name, response in res.items():
        text += f"🗣 **{name}**:\n{response}\n\n"
    
    kb = [[InlineKeyboardButton("➡️ Наступний Раунд", callback_data="next_round")]]
    await context.bot.send_message(update.effective_chat.id, text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def next_round_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id in active_sessions:
        await query.edit_message_reply_markup(reply_markup=None) # Прибираємо кнопку
        await run_round(update, context, active_sessions[user_id])
    else:
        await query.edit_message_text("Сесія не знайдена.")

# --- MAIN SETUP ---

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERROR: Token not found")
        return

    # Ініціалізація БД
    DB_MANAGER._create_tables()

    application = Application.builder().token(token).build()

    # Conversation: Add Key
    conv_addkey = ConversationHandler(
        entry_points=[CommandHandler('addkey', addkey_start), CallbackQueryHandler(addkey_start, pattern='^cmd_addkey')],
        states={
            AWAITING_SERVICE: [CallbackQueryHandler(addkey_service_chosen, pattern='^srv_')],
            AWAITING_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, addkey_receive_key)],
            AWAITING_ALIAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, addkey_receive_alias)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Conversation: Rounds
    conv_rounds = ConversationHandler(
        entry_points=[CommandHandler('rounds', rounds_start), CallbackQueryHandler(rounds_start, pattern='^cmd_rounds')],
        states={
            CHOOSING_ROUNDS: [
                CallbackQueryHandler(rounds_chosen, pattern='^rnd_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, rounds_custom)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_addkey)
    application.add_handler(conv_rounds)
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('mykeys', mykeys))
    application.add_handler(CallbackQueryHandler(mykeys, pattern='^cmd_mykeys'))
    application.add_handler(CallbackQueryHandler(ask_topic, pattern='^cmd_start_debate'))
    application.add_handler(CallbackQueryHandler(next_round_cb, pattern='^next_round'))
    
    # Обробка тексту як теми дебатів (якщо не в FSM)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_topic))

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()