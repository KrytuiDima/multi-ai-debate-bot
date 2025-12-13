# src/bot.py
import asyncio
import os
import logging
from typing import Dict, List, Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    filters, 
    ContextTypes, 
    ConversationHandler
)

# Імпортуємо тільки те, що дійсно використовується, щоб уникнути помилок імпорту
from ai_clients import BaseAI, AI_CLIENTS_MAP 
from debate_manager import DebateSession, DebateStatus
from database import DB_MANAGER, decrypt_key 
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- НАЛАШТУВАННЯ ЛОГУВАННЯ ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- СТАНИ FSM ---
CHOOSING_ROUNDS = 1
AWAITING_SERVICE = 2
AWAITING_KEY = 3
AWAITING_ALIAS = 4
AWAITING_LIMIT = 5 
AWAITING_DEBATE_TOPIC = 10
AWAITING_DEBATE_ROUNDS = 11
AWAITING_DEBATE_AI1 = 12
AWAITING_DEBATE_AI2 = 13


# --- ГЛОБАЛЬНІ КОНСТАНТИ ---
AVAILABLE_SERVICES: Dict[str, str] = {
    'groq': 'Groq (Llama 3)',
    'gemini': 'Gemini (Flash)',
    'claude': 'Claude (Haiku)',
    'deepseek': 'DeepSeek',
}

# --- ДОПОМІЖНІ ФУНКЦІЇ ---

def get_main_menu(user_id: int) -> InlineKeyboardMarkup:
    """Генерує головне меню залежно від наявності ключів."""
    user_keys = DB_MANAGER.get_user_keys_with_alias(user_id)
    
    if user_keys:
        buttons = [
            [InlineKeyboardButton("⚔️ Розпочати Дебати", callback_data='cmd_debate')],
            [InlineKeyboardButton("➕ Додати API ключ", callback_data='cmd_addkey')],
            [InlineKeyboardButton("🔑 Мої Ключі", callback_data='cmd_mykeys')],
            [InlineKeyboardButton("❓ Допомога", callback_data='cmd_help')],
        ]
    else:
        buttons = [
            [InlineKeyboardButton("➕ Додати API ключ", callback_data='cmd_addkey')],
            [InlineKeyboardButton("❓ Допомога", callback_data='cmd_help')],
        ]
        
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє команду /start."""
    user = update.effective_user
    DB_MANAGER.register_user(user.id, user.username or '', user.first_name or '')
    
    welcome_message = (
        f"👋 Вітаємо, **{user.first_name}**!\n\n"
        "Я - **AI Debate Bot**. Я влаштовую дебати між двома різними AI-моделями на будь-яку тему.\n\n"
        "Для початку роботи, вам потрібно додати свої API ключі (BYOK - Bring Your Own Key) від Groq, Gemini, Claude або DeepSeek.\n\n"
        "Оберіть дію нижче:"
    )
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=get_main_menu(user.id),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє команду /cancel і завершує розмову."""
    user_id = update.effective_user.id
    await update.message.reply_text(
        'Скасовано. Повертаємось до головного меню.',
        reply_markup=get_main_menu(user_id)
    )
    # Очищуємо тимчасові дані
    context.user_data.pop('new_key_service', None)
    context.user_data.pop('new_key_value', None)
    context.user_data.pop('new_key_limit', None)
    context.user_data.pop('current_debate_session', None)
    return ConversationHandler.END


# --- 1. ЛОГІКА ДОДАВАННЯ КЛЮЧІВ (BYOK) ---

async def addkey_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Початок розмови для додавання ключа."""
    
    keyboard = []
    for code, name in AVAILABLE_SERVICES.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f'srv_{code}')])
    
    # Визначаємо, звідки прийшов запит (команда чи callback)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Оберіть AI сервіс, ключ якого ви хочете додати:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "Оберіть AI сервіс, ключ якого ви хочете додати:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return AWAITING_SERVICE

async def addkey_service_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка вибору сервісу."""
    query = update.callback_query
    await query.answer()
    srv_code = query.data.split('_')[1]
    context.user_data['new_key_service'] = srv_code
    
    # Визначаємо, як має виглядати ключ для підказки користувачеві
    key_prefix = ""
    if srv_code == 'groq':
        key_prefix = "gsk_..."
    elif srv_code == 'claude':
        key_prefix = "sk-ant-api03-..."
    elif srv_code == 'gemini':
        key_prefix = "AIzaSy..."
    elif srv_code == 'deepseek':
        key_prefix = "sk-..."

    await query.edit_message_text(
        f"Введіть API ключ для **{AVAILABLE_SERVICES[srv_code]}**.\n"
        f"Він має починатися з `{key_prefix}`",
        parse_mode='Markdown'
    )
    return AWAITING_KEY

async def addkey_receive_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка введеного ключа та синтаксична валідація."""
    key = update.message.text.strip()
    service = context.user_data.get('new_key_service')
    
    # 1. Валідація синтаксису ключа
    is_valid_syntax = False
    if service == 'groq' and key.startswith('gsk_'):
        is_valid_syntax = True
    elif service == 'claude' and key.startswith('sk-ant-api03-'):
        is_valid_syntax = True
    elif service == 'gemini' and key.startswith('AIzaSy'):
        is_valid_syntax = True
    elif service == 'deepseek' and key.startswith('sk-'):
        is_valid_syntax = True
    
    if not is_valid_syntax:
        await update.message.reply_text(
            f"❌ Це не схоже на ключ для **{AVAILABLE_SERVICES.get(service)}**.\n"
            f"Перевірте, чи ви обрали правильний сервіс або чи правильно скопіювали ключ.",
            parse_mode='Markdown'
        )
        return AWAITING_KEY

    context.user_data['new_key_value'] = key
    
    # ПЕРЕХІД ДО ВВЕДЕННЯ ЛІМІТУ
    return await addkey_receive_limit(update, context, is_initial=True) 

async def addkey_receive_limit(update: Update, context: ContextTypes.DEFAULT_TYPE, is_initial: bool = False) -> int:
    """Обробка ліміту запитів."""
    service = context.user_data.get('new_key_service')
    
    # Інформація про безкоштовні ліміти (для підказки)
    limit_info = {
        'groq': "Groq: Ліміт залежить від токенів (близько 131k/день). Рекомендований стартовий ліміт: **2000**.",
        'gemini': "Gemini: Free Tier API - до **1000** запитів на день (залежить від моделі).",
        'claude': "Claude: Free Tier API ліміти гнучкі та часто змінюються. Рекомендований стартовий ліміт: **100**.",
        'deepseek': "DeepSeek: API формально без ліміту, але для Free Tier Web - 10 запитів/день. Рекомендований стартовий ліміт: **10**.",
    }
    
    info = limit_info.get(service, "Точний безкоштовний ліміт невідомий. Рекомендовано 1000.")
    
    if not is_initial:
        # Обробка введеного користувачем ліміту
        try:
            limit = int(update.message.text.strip())
            if limit < 0: raise ValueError
        except ValueError:
            await update.message.reply_text("Будь ласка, введіть коректне число (більше або дорівнює 0) для ліміту.")
            return AWAITING_LIMIT
        
        context.user_data['new_key_limit'] = limit
        await update.message.reply_text("Введіть назву (alias) для цього ключа (напр. 'Мій Groq'):")
        return AWAITING_ALIAS
    else:
        # Перший вхід у стан: просимо ліміт
        await update.message.reply_text(
            f"**Введіть місячний ліміт запитів** для ключа **{AVAILABLE_SERVICES[service]}**.\n"
            f"*{info}*\n\n"
            f"Наприклад, 1000 (або 0, якщо ліміту немає/невідомо)."
            f"\n\n**(Пам'ятайте, один раунд дебатів = 2 запити)**",
            parse_mode='Markdown'
        )
        return AWAITING_LIMIT

async def addkey_receive_alias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка псевдоніма ключа та збереження в БД."""
    alias = update.message.text.strip()
    user_id = update.effective_user.id
    
    key = context.user_data['new_key_value']
    service = context.user_data['new_key_service']
    limit = context.user_data.get('new_key_limit', 0) 

    # Перевірка на унікальність псевдоніма
    if DB_MANAGER.get_key_details_by_alias(user_id, alias):
        await update.message.reply_text("❌ Ключ з такою назвою (alias) вже існує. Спробуйте іншу назву.")
        return AWAITING_ALIAS

    success = DB_MANAGER.add_api_key(
        owner_id=user_id, 
        service=service, 
        api_key=key, 
        alias=alias,
        calls_remaining=limit
    )
    
    if success:
        await update.message.reply_text(f"✅ Ключ **'{alias}'** ({AVAILABLE_SERVICES[service]}) додано з лімітом **{limit}** запитів!", parse_mode='Markdown', reply_markup=get_main_menu(user_id))
    else:
        await update.message.reply_text("❌ Помилка. Не вдалося додати ключ. Можливо, назва ключа вже існує. Спробуйте іншу назву.", reply_markup=get_main_menu(user_id))
    
    context.user_data.clear()
    return ConversationHandler.END

# --- 2. ЛОГІКА ДЕБАТІВ ---

def get_key_keyboard(user_id: int, prefix: str) -> InlineKeyboardMarkup:
    """Генерує клавіатуру з ключами користувача, включаючи залишок запитів."""
    keys = DB_MANAGER.get_user_keys_with_alias(user_id)
    keyboard = []
    
    for alias, service, remaining, key_id in keys:
        display_name = f"{alias} ({AVAILABLE_SERVICES[service]}) [ {remaining} ]"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f'{prefix}_{alias}')])
        
    return InlineKeyboardMarkup(keyboard)

async def debate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Початок розмови для дебатів."""
    user_id = update.effective_user.id
    keys = DB_MANAGER.get_user_keys_with_alias(user_id)
    
    if len(keys) < 2:
        # Визначаємо, звідки прийшов запит для коректної відповіді
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                "❌ У вас має бути додано мінімум два API ключі для проведення дебатів. Будь ласка, додайте ще ключі.",
                reply_markup=get_main_menu(user_id)
            )
        else:
            await update.message.reply_text(
                "❌ У вас має бути додано мінімум два API ключі для проведення дебатів. Будь ласка, додайте ще ключі.",
                reply_markup=get_main_menu(user_id)
            )
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Введіть тему, на яку будуть дебатувати AI (напр. 'Чи повинна влада регулювати ШІ?'):"
        )
    else:
        await update.message.reply_text(
            "Введіть тему, на яку будуть дебатувати AI (напр. 'Чи повинна влада регулювати ШІ?'):"
        )
    
    return AWAITING_DEBATE_TOPIC

async def debate_topic_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка отриманої теми та запит на кількість раундів."""
    context.user_data['debate_topic'] = update.message.text.strip()
    
    keyboard = [[InlineKeyboardButton(str(r), callback_data=f'rounds_{r}')] for r in [3, 5, 7]]
    
    await update.message.reply_text(
        "Оберіть кількість раундів для дебатів (кожен раунд = 2 запити до API):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AWAITING_DEBATE_ROUNDS

async def debate_rounds_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка вибору раундів та запит на першого AI."""
    query = update.callback_query
    await query.answer()
    
    rounds = int(query.data.split('_')[1])
    context.user_data['debate_rounds'] = rounds
    
    await query.edit_message_text(
        "Оберіть **AI 1** (перший учасник):",
        reply_markup=get_key_keyboard(update.effective_user.id, 'ai1'),
        parse_mode='Markdown'
    )
    return AWAITING_DEBATE_AI1

async def debate_ai1_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка вибору AI 1 та запит на другого AI."""
    query = update.callback_query
    await query.answer()
    
    alias1 = query.data.split('_')[1]
    context.user_data['debate_ai1_alias'] = alias1
    
    # Фільтруємо клавіатуру, щоб не пропонувати той самий AI
    keys = DB_MANAGER.get_user_keys_with_alias(update.effective_user.id)
    keyboard = []
    for alias, service, remaining, key_id in keys:
        if alias != alias1:
            display_name = f"{alias} ({AVAILABLE_SERVICES[service]}) [ {remaining} ]"
            keyboard.append([InlineKeyboardButton(display_name, callback_data=f'ai2_{alias}')])

    await query.edit_message_text(
        f"✅ Ви обрали **{alias1}** як AI 1.\n\n"
        f"Оберіть **AI 2** (другий учасник):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return AWAITING_DEBATE_AI2

async def debate_ai2_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка вибору AI 2 та старт дебатів."""
    query = update.callback_query
    await query.answer()
    
    context.user_data['debate_ai2_alias'] = query.data.split('_')[1]

    await query.edit_message_text("⏳ Ініціалізація дебатів...")
    
    # Викликаємо функцію, яка почне дебати
    return await start_debate_with_clients(query, context)


async def start_debate_with_clients(update_or_query: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Остаточна підготовка, перевірка лімітів та запуск сесії."""
    # Отримуємо об'єкт повідомлення для відповіді, незалежно від того, чи це Update чи CallbackQuery
    message = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query
    
    user_id = message.chat.id
    topic = context.user_data['debate_topic']
    
    alias1 = context.user_data['debate_ai1_alias']
    alias2 = context.user_data['debate_ai2_alias']
    
    try:
        # 1. Отримання деталей ключів (id, service, encrypted_key)
        key1_details = DB_MANAGER.get_key_details_by_alias(user_id, alias1)
        key2_details = DB_MANAGER.get_key_details_by_alias(user_id, alias2)

        if not key1_details or not key2_details:
             await message.reply_text("❌ Помилка: Не вдалося знайти один із вибраних ключів у базі даних.", reply_markup=get_main_menu(user_id))
             return ConversationHandler.END

        key1_id, service1, encrypted_key1 = key1_details
        key2_id, service2, encrypted_key2 = key2_details
        
        # 2. Перевірка лімітів ПЕРЕД запуском
        remaining1 = DB_MANAGER.get_remaining_calls(key1_id)
        remaining2 = DB_MANAGER.get_remaining_calls(key2_id)
        
        # Перевірка: чи вистачить запитів хоча б на 1 раунд (мінімум 1 запит на кожного)
        if (remaining1 is None or remaining1 < 1) or (remaining2 is None or remaining2 < 1):
            msg = "❌ **Дебати не можуть розпочатися:** У одного з вибраних AI закінчилися запити. "
            if remaining1 is not None and remaining1 < 1: msg += f"'{alias1}' = {remaining1} "
            if remaining2 is not None and remaining2 < 1: msg += f"'{alias2}' = {remaining2}"
            msg += ". Будь ласка, додайте новий ключ або збільште ліміт."
            
            await message.reply_text(msg, parse_mode='Markdown', reply_markup=get_main_menu(user_id))
            return ConversationHandler.END

        # 3. Дешифрування та ініціалізація клієнтів
        api_key1 = decrypt_key(encrypted_key1)
        api_key2 = decrypt_key(encrypted_key2)

        # Використовуємо AI_CLIENTS_MAP для створення екземплярів
        client1 = AI_CLIENTS_MAP[service1](api_key=api_key1) 
        client2 = AI_CLIENTS_MAP[service2](api_key=api_key2) 
        
        # Зберігаємо імена для відображення
        ai1_name = f"*{alias1}* ({AVAILABLE_SERVICES[service1]})"
        ai2_name = f"*{alias2}* ({AVAILABLE_SERVICES[service2]})"
        
        clients_map = {ai1_name: client1, ai2_name: client2}
        key_ids_map = {ai1_name: key1_id, ai2_name: key2_id}

        # 4. Створення сесії (передача key_ids_map)
        session = DebateSession(
            topic=topic, 
            clients_map=clients_map, 
            key_ids_map=key_ids_map, 
            max_rounds=context.user_data.get('debate_rounds', 3)
        )
        
        context.user_data['current_debate_session'] = session
        
        initial_message = (
            f"**⚔️ Дебати розпочато!**\n\n"
            f"**Тема:** {topic}\n"
            f"**Учасники:** {ai1_name} vs {ai2_name}\n"
            f"**Раундів:** {session.MAX_ROUNDS}\n"
            f"**Початкові ліміти:** {alias1}: {remaining1}, {alias2}: {remaining2}\n"
            f"Натисніть *'Наступний Раунд'* для продовження."
        )
        
        await message.reply_text(
            initial_message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Наступний Раунд", callback_data='run_round')]]),
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Помилка при запуску дебатів: {e}")
        await message.reply_text(f"❌ Критична помилка при запуску: {e}", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END


async def run_debate_round(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Виконує один раунд дебатів, декрементує ліміти та відображає результат."""
    query = update.callback_query
    await query.answer(text="Генерую відповіді...")
    
    session: DebateSession = context.user_data.get('current_debate_session')
    if not session:
        await query.edit_message_text("❌ Сесія дебатів не знайдена. Почніть нові дебати: /debate", reply_markup=get_main_menu(update.effective_user.id))
        return ConversationHandler.END
        
    # Ключі клієнтів вже з alias та service, тому вони унікальні
    ai1_name, ai2_name = list(session.clients.keys())

    try:
        await query.edit_message_text(f"⏳ Раунд {session.round + 1} з {session.MAX_ROUNDS}: {ai1_name} та {ai2_name} думають...", parse_mode='Markdown')
        
        # run_next_round: асинхронно отримує відповіді та виконує DB_MANAGER.decrement_calls
        response1, response2 = await session.run_next_round() 
        
        # 1. Форматування відповіді
        round_text = (
            f"**--- РАУНД {session.round}/{session.MAX_ROUNDS} ---**\n\n"
            f"**{ai1_name}:**\n{response1}\n\n"
            f"**{ai2_name}:**\n{response2}\n"
        )
        
        await query.edit_message_text(round_text, parse_mode='Markdown')

        # 2. Оновлення інформації про ліміти у відповіді
        remaining1 = DB_MANAGER.get_remaining_calls(session.key_ids[ai1_name])
        remaining2 = DB_MANAGER.get_remaining_calls(session.key_ids[ai2_name])
        
        status_message = (
            f"**Ліміти після раунду {session.round}:**\n"
            f"{ai1_name}: {remaining1} запитів\n"
            f"{ai2_name}: {remaining2} запитів"
        )
        
        await query.message.reply_text(status_message, parse_mode='Markdown')
        
        # 3. Перевірка завершення
        if session.round >= session.MAX_ROUNDS:
             final_message = f"✅ **Дебати ЗАВЕРШЕНО!**\n\nТема: {session.topic}\nКількість раундів: {session.MAX_ROUNDS}\n"
             final_message += "Натисніть /history для перегляду всіх раундів."
             await query.message.reply_text(final_message, reply_markup=get_main_menu(update.effective_user.id))
             context.user_data.pop('current_debate_session', None)
             return ConversationHandler.END
        
        # 4. Наступний раунд
        await query.message.reply_text(
            f"Дебати тривають. Наступний раунд {session.round + 1} з {session.MAX_ROUNDS}.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Наступний Раунд", callback_data='run_round')]])
        )
        
    except Exception as e:
        # Обробка помилки вичерпання ліміту
        if "Ліміт запитів" in str(e):
             await query.message.reply_text(f"❌ **Дебати зупинено:** {e}", reply_markup=get_main_menu(update.effective_user.id), parse_mode='Markdown')
        else:
            logger.error(f"Помилка в раунді дебатів: {e}")
            await query.message.reply_text(f"❌ Сталася помилка в раунді: {e}", reply_markup=get_main_menu(update.effective_user.id))
        
        # Очистка сесії
        context.user_data.pop('current_debate_session', None)
        return ConversationHandler.END

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує історію поточної сесії."""
    session: DebateSession = context.user_data.get('current_debate_session')
    
    if not session:
        await update.message.reply_text("❌ Немає активної або щойно завершеної сесії дебатів.")
        return

    history = session.get_full_history()
    
    response = (
        f"**📜 Історія Дебатів**\n"
        f"**Тема:** {session.topic}\n"
        f"**Завершено раундів:** {session.round}\n\n"
        f"```\n{history}\n```"
    )
    
    await update.message.reply_text(response, parse_mode='Markdown')


# --- 3. ІНШІ КОМАНДИ ---

async def mykeys_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відображає ключі користувача."""
    user_id = update.effective_user.id
    keys = DB_MANAGER.get_user_keys_with_alias(user_id)
    
    if not keys:
        message = "🔑 У вас немає доданих API ключів.\n\nНатисніть /addkey, щоб додати перший ключ."
    else:
        message = "🔑 **Ваші API ключі та ліміти:**\n\n"
        for alias, service, remaining, key_id in keys:
            service_name = AVAILABLE_SERVICES.get(service, service.upper())
            
            message += f"**• {alias}**\n"
            message += f"  > Сервіс: `{service_name}`\n"
            message += f"  > Залишок запитів: **{remaining}**\n\n"
            
    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=get_main_menu(user_id))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відображає довідку."""
    help_text = (
        "🤖 **Довідка по AI Debate Bot:**\n\n"
        "1. **/addkey** або кнопка `➕ Додати API ключ`:\n"
        "   - Додайте свій ключ для використання AI-моделей. Це BYOK (Bring Your Own Key).\n"
        "   - Ви самі встановлюєте **місячний ліміт запитів** для цього ключа.\n"
        "   - **1 раунд дебатів = 2 запити** (один на AI 1, один на AI 2).\n\n"
        "2. **/debate** або кнопка `⚔️ Розпочати Дебати`:\n"
        "   - Оберіть тему, кількість раундів та два AI для участі.\n"
        "   - Після кожного раунду бот показує **залишок запитів** для кожного ключа.\n\n"
        "3. **/mykeys** або кнопка `🔑 Мої Ключі`:\n"
        "   - Перегляньте список своїх ключів, їхній сервіс та поточний залишок запитів.\n\n"
        "4. **/history**:\n"
        "   - Показує повну історію останньої активної або завершеної сесії дебатів.\n\n"
        "5. **/cancel**:\n"
        "   - Скасовує поточну розмову (наприклад, додавання ключа) і повертає до головного меню."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=get_main_menu(update.effective_user.id))

# --- ERROR HANDLER ---

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message."""
    logger.error("Помилка обробки оновлення:", exc_info=context.error)
    
    # Try to send a message to the user
    if update and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Виникла внутрішня помилка. Будь ласка, спробуйте ще раз або використайте /cancel.",
            )
        except Exception as e:
            logger.error(f"Не вдалося відправити повідомлення про помилку користувачу: {e}")

# --- SETUP ---

def main_bot_setup(token: str) -> Application:
    """Налаштування Application та додавання хендлерів."""
    
    application = Application.builder().token(token).build()
    
    # Conversation: Add Key
    conv_addkey = ConversationHandler(
        entry_points=[CommandHandler('addkey', addkey_start), CallbackQueryHandler(addkey_start, pattern='^cmd_addkey')],
        states={
            AWAITING_SERVICE: [CallbackQueryHandler(addkey_service_chosen, pattern='^srv_')],
            AWAITING_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, addkey_receive_key)],
            AWAITING_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, addkey_receive_limit)], 
            AWAITING_ALIAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, addkey_receive_alias)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Conversation: Debate
    conv_debate = ConversationHandler(
        entry_points=[CommandHandler('debate', debate_start), CallbackQueryHandler(debate_start, pattern='^cmd_debate')],
        states={
            AWAITING_DEBATE_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, debate_topic_received)],
            AWAITING_DEBATE_ROUNDS: [CallbackQueryHandler(debate_rounds_chosen, pattern='^rounds_')],
            AWAITING_DEBATE_AI1: [CallbackQueryHandler(debate_ai1_chosen, pattern='^ai1_')],
            AWAITING_DEBATE_AI2: [CallbackQueryHandler(debate_ai2_chosen, pattern='^ai2_')]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Головні команди та меню
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("mykeys", mykeys_command))
    application.add_handler(CommandHandler("history", history_command))
    
    # Хендлери для розмов
    application.add_handler(conv_addkey)
    application.add_handler(conv_debate)
    
    # Хендлер для продовження дебатів (поза FSM, оскільки це ітераційний процес)
    application.add_handler(CallbackQueryHandler(run_debate_round, pattern='^run_round$'))

    return application

def main() -> None:
    """Запуск бота у режимі Polling."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не знайдено.")
        return

    application = main_bot_setup(TELEGRAM_BOT_TOKEN)
    application.add_error_handler(error_handler)
    
    logger.info("Бот запущено у режимі Polling...")
    application.run_polling(poll_interval=1.0)

if __name__ == '__main__':
    main()