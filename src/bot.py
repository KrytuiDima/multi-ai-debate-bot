# src/bot.py (Версія з меню та видаленням повідомлень)
import asyncio
import os
try:
    from dotenv import load_dotenv
except Exception:
    # Fallback if python-dotenv is not installed: use a no-op loader and warn.
    def load_dotenv(*args, **kwargs):
        print("warning: python-dotenv not installed; proceeding without loading .env")
from typing import Dict, List, Optional

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

from ai_clients import BaseAI, AI_CLIENTS, AI_CLIENTS_MAP 
from debate_manager import DebateSession, DebateStatus
from database import DB_MANAGER  # Імпортуємо глобальний об'єкт

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- НОВІ ГЛОБАЛЬНІ ЗМІННІ ДЛЯ WEBHOOK ---
APPLICATION = None # Тут буде зберігатися об'єкт Application після ініціалізації
# --- КІНЕЦЬ НОВИХ ЗМІН ---

# --- СТАНИ FSM ---
CHOOSING_ROUNDS = 1
AWAITING_SERVICE = 2
AWAITING_KEY = 3
AWAITING_ALIAS = 4

# Раунди, які пропонуємо
ROUND_OPTIONS = [2, 3, 5, 10]

# Сервіси для додавання ключів
AVAILABLE_SERVICES = {
    'gemini': 'Gemini (Google)',
    'groq': 'Llama3 (Groq)',
    'claude': 'Claude (Anthropic)',
    'deepseek': 'DeepSeek'
}

# --- ФУНКЦІЇ ПЕРЕВІРКИ КЛЮЧІВ ---

def get_key_status() -> dict:
    """Перевіряє наявність ключів API у змінних середовища."""
    status = {
        'groq': bool(os.getenv('GROQ_API_KEY')),
        'gemini': bool(os.getenv('GEMINI_API_KEY')),
        'claude': bool(os.getenv('ANTHROPIC_API_KEY')),
        'deepseek': bool(os.getenv('DEEPSEEK_API_KEY'))
    }
    return status

def get_status_message(status: dict) -> str:
    """Формує повідомлення про статус ключів."""
    total_set = sum(status.values())
    
    messages = ["🔑 <b>Статус Ключів AI</b>:\n"]
    
    key_names = {
        'groq': "Llama3 (Groq)",
        'gemini': "Gemini",
        'claude': "Claude",
        'deepseek': "DeepSeek"
    }

    for key, name in key_names.items():
        icon = '✅' if status[key] else '❌'
        messages.append(f"{icon} {name}")
    
    messages.append(f"\n<b>Всього активовано: {total_set} з 4</b>.")
    
    if total_set < 2:
        messages.append("\n<b>⚠️ Щоб розпочати дебати, потрібно мінімум 2 активні моделі.</b>")
    
    return "\n".join(messages)


# --- ГЛОБАЛЬНЕ ЗБЕРІГАННЯ ДАНИХ (В RAM) ---
user_clients: Dict[int, Dict[str, BaseAI]] = {} 
active_sessions: Dict[int, DebateSession] = {}
# Зберігаємо ID останніх повідомлень для їх видалення/редагування
debate_message_ids: Dict[int, List[int]] = {} 

# СЛОВНИК ДЛЯ ЗБЕРІГАННЯ ЗІБРАНИХ КЛЮЧІВ ДЛЯ НОВОГО КОРИСТУВАЧА ПІСЛЯ ЗАВАНТАЖЕННЯ З БД
cached_user_api_keys: Dict[int, Dict[str, List[str]]] = {}

# --------------------------
# I. Навігація та Головне Меню
# --------------------------

def get_main_menu_markup(user_id: int) -> InlineKeyboardMarkup:
    """Генерує розмітку головного меню."""
    # Кнопка для перегляду профілю
    profile_button = InlineKeyboardButton("👤 Профіль", callback_data='menu_profile')

    # Кнопка для перегляду статусу ключів
    status_button = InlineKeyboardButton("🔑 Статус Ключів", callback_data='menu_status')
    
    # Кнопка для початку дебатів
    start_debate_button = InlineKeyboardButton("⚔️ Почати Дебати", callback_data='menu_ask')

    keyboard = [
        [status_button],
        [profile_button],
        [start_debate_button],
    ]

    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробник команди /start. Відкриває головне меню."""
    user_id = update.effective_user.id
    
    # Використовуємо message.reply_text, оскільки це перша команда
    await update.message.reply_text(
        "👋 <b>Головне меню.</b> Виберіть опцію нижче:",
        reply_markup=get_main_menu_markup(user_id),
        parse_mode="HTML"
    )
    # Повертаємо ConversationHandler.END, оскільки ми не в FSM для навігації
    return ConversationHandler.END


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує статус налаштованих ключів API."""
    status = get_key_status()
    status_msg = get_status_message(status)
    
    await update.message.reply_text(
        f"Привіт! Я бот для AI-дебатів.\n\n{status_msg}",
        parse_mode="HTML"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує довідку про доступні команди."""
    help_text = (
        "<b>📚 Доступні Команди:</b>\n\n"
        "<b>/start</b> - Головне меню\n"
        "<b>/status</b> - Показати статус ключів API\n"
        "<b>/profile</b> - Перегляд профілю\n"
        "<b>/rounds</b> - Вибір кількості раундів дебатів\n"
        "<b>/help</b> - Ця довідка\n"
        "<b>/setup</b> - Інструкції щодо налаштування ключів\n\n"
        "<b>🔑 Як запустити бота:</b>\n"
        "1. Встановіть API ключі у файл <code>.env</code>\n"
        "2. Командуйте /rounds щоб вибрати кількість раундів\n"
        "3. Командуйте /start щоб почати дебати"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


async def setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує інструкції щодо налаштування ключів API."""
    setup_text = (
        "<b>⚙️ Інструкція Налаштування API Ключів</b>\n\n"
        "<b>1️⃣ Groq (Llama3)</b>\n"
        "   • Перейдіть на: https://console.groq.com\n"
        "   • Отримайте ключ\n"
        "   • Додайте до .env: GROQ_API_KEY=your_key\n\n"
        "<b>2️⃣ Gemini (Google)</b>\n"
        "   • Перейдіть на: https://aistudio.google.com\n"
        "   • Отримайте ключ\n"
        "   • Додайте до .env: GEMINI_API_KEY=your_key\n\n"
        "<b>3️⃣ Claude (Anthropic)</b>\n"
        "   • Перейдіть на: https://console.anthropic.com\n"
        "   • Отримайте ключ\n"
        "   • Додайте до .env: ANTHROPIC_API_KEY=your_key\n\n"
        "<b>4️⃣ DeepSeek</b>\n"
        "   • Перейдіть на: https://platform.deepseek.com\n"
        "   • Отримайте ключ\n"
        "   • Додайте до .env: DEEPSEEK_API_KEY=your_key\n\n"
        "<b>📝 Приклад .env файла:</b>\n"
        "<code>TELEGRAM_BOT_TOKEN=your_token\n"
        "GROQ_API_KEY=your_groq_key\n"
        "GEMINI_API_KEY=your_gemini_key\n"
        "ANTHROPIC_API_KEY=your_claude_key\n"
        "DEEPSEEK_API_KEY=your_deepseek_key</code>"
    )
    await update.message.reply_text(setup_text, parse_mode="HTML")


# --- КОМАНДА /addkey ---

async def addkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Початок діалогу для додавання нового API-ключа."""
    keyboard = []
    for service_key, service_name in AVAILABLE_SERVICES.items():
        keyboard.append([InlineKeyboardButton(service_name, callback_data=f"service_{service_key}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "<b>🔑 Оберіть сервіс для додавання ключа:</b>",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    return AWAITING_SERVICE


async def service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір сервісу."""
    query = update.callback_query
    await query.answer()
    
    service_key = query.data.split('_')[1]
    service_name = AVAILABLE_SERVICES.get(service_key)
    
    context.user_data['service_key'] = service_key
    context.user_data['service_name'] = service_name
    
    await query.edit_message_text(
        f"Введіть ваш API-ключ для <b>{service_name}</b>:\n"
        f"(Ключ буде зашифрований і безпечно збережено в базі)",
        parse_mode="HTML"
    )
    
    return AWAITING_KEY


async def receive_api_key_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отримує введений API-ключ."""
    api_key = update.message.text.strip()
    
    if len(api_key) < 10:
        await update.message.reply_text(
            "❌ Ключ занадто короткий. Будь ласка, введіть коректний API-ключ."
        )
        return AWAITING_KEY
    
    context.user_data['api_key'] = api_key
    
    await update.message.reply_text(
        "<b>Як назвати цей ключ?</b>\n"
        "Наприклад: <code>Gemini Personal</code>, <code>Claude Work</code>, тощо",
        parse_mode="HTML"
    )
    
    return AWAITING_ALIAS


async def receive_alias_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отримує введену назву (alias) ключа."""
    alias = update.message.text.strip()
    
    if len(alias) < 3 or len(alias) > 100:
        await update.message.reply_text(
            "❌ Назва має бути від 3 до 100 символів. Спробуйте ще раз.",
            parse_mode="HTML"
        )
        return AWAITING_ALIAS
    
    # Зберігаємо ключ у БД
    user_id = update.effective_user.id
    api_key = context.user_data.get('api_key')
    service_key = context.user_data.get('service_key')
    service_name = context.user_data.get('service_name')
    
    try:
        success = DB_MANAGER.add_api_key(user_id, service_key, api_key, alias)
        
        if success:
            await update.message.reply_text(
                f"✅ <b>Ключ для {service_name} успішно додано!</b>\n\n"
                f"📝 <b>Деталі:</b>\n"
                f"Назва: <code>{alias}</code>\n"
                f"Сервіс: {service_name}\n\n"
                f"Використовуйте /mykeys щоб переглянути та вибрати ключі.",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Ключ з назвою <code>{alias}</code> вже існує.\n"
                f"Будь ласка, використовуйте іншу назву.",
                parse_mode="HTML"
            )
            return AWAITING_ALIAS
    except Exception as e:
        print(f"Помилка при додаванні ключа: {e}")
        await update.message.reply_text(
            "❌ Виникла помилка при додаванні ключа. Спробуйте пізніше."
        )
    
    # Очищуємо користувацькі дані
    context.user_data.pop('service_key', None)
    context.user_data.pop('service_name', None)
    context.user_data.pop('api_key', None)
    
    return ConversationHandler.END


# --- КОМАНДА /mykeys ---

async def mykeys_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відображає список ключів користувача та дозволяє вибрати активний."""
    user_id = update.effective_user.id
    
    try:
        keys = DB_MANAGER.get_user_api_keys(user_id)
        
        if not keys:
            keyboard = [[InlineKeyboardButton("➕ Додати ключ", url=f"https://t.me/{context.bot.username}?start=addkey")]]
            await update.message.reply_text(
                "📭 У вас немає збережених API-ключів.\n\n"
                "Використовуйте /addkey щоб додати новий ключ.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            return
        
        # Формуємо список ключів з кнопками
        text = "Key list:\n\n"
        keyboard = []
        
        active_key_id = DB_MANAGER.get_active_key_id(user_id)
        
        for key_info in keys:
            # key_info is a dict with: id, alias, service, calls_remaining, is_active
            key_id = key_info.get('id')
            alias = key_info.get('alias')
            service = key_info.get('service')
            calls_remaining = key_info.get('calls_remaining')
            
            # Вибираємо емодзі в залежності від сервісу
            service_emoji = {
                'gemini': '(G)',
                'groq': '(Q)',
                'claude': '(C)',
                'deepseek': '(D)'
            }.get(service, '(?)')
            
            status_icon = "[A]" if key_id == active_key_id else "[ ]"
            
            text += f"{status_icon} {service_emoji} {alias}\n"
            text += f"   Calls: {calls_remaining}\n\n"
            
            # Кнопка для вибору ключа
            button_text = f"[A] {alias}" if key_id == active_key_id else f"[ ] {alias}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"select_key_{key_id}")])
        
        # Кнопка для додавання нового ключа
        keyboard.append([InlineKeyboardButton("[+] Add key", callback_data="add_new_key")])
        
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        print(f"Помилка при отриманні списку ключів: {e}")
        await update.message.reply_text(
            "❌ Виникла помилка при завантаженні ключів. Спробуйте пізніше."
        )


def build_ai_clients(user_id: int) -> Optional[Dict[str, BaseAI]]:
    """Повертає словник AI клієнтів, ініціалізованих з ключами з оточення."""
    try:
        clients = {}
        for model_name, client in AI_CLIENTS.items():
            clients[model_name] = client
        return clients
    except Exception as e:
        print(f"Помилка ініціалізації AI клієнтів: {e}")
        return None


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує профіль користувача: баланс, ім'я та дату реєстрації."""
    # Визначаємо user_id та username у випадку команди або callback
    if update.callback_query:
        user = update.callback_query.from_user
    else:
        user = update.effective_user

    user_id = user.id
    username = user.username or "Н/Д"

    balance, join_date = DB_MANAGER.get_user_profile(user_id, username)

    message = (
        "👤 <b>Ваш Профіль</b>\n\n"
        f"ID користувача: <code>{user_id}</code>\n"
        f"Ім'я користувача: @{username}\n"
        f"📅 Дата реєстрації: {join_date}\n\n"
        f"💰 <b>Баланс:</b> {balance:.2f} ₴"
    )

    # Відправляємо приватне повідомлення користувачу
    await context.bot.send_message(user_id, message, parse_mode="HTML")


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробник кнопок головного меню."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == 'menu_status':
        # Показати статус ключів
        status = get_key_status()
        status_msg = get_status_message(status)
        await query.edit_message_text(status_msg, parse_mode="HTML")
        return ConversationHandler.END
    
    elif data == 'menu_profile':
        # Показати профіль користувача
        await show_profile(update, context)
        return ConversationHandler.END
        
    elif data == 'menu_ask':
        # 2. Початок дебатів (Задання запитання)
        await query.edit_message_text("✍️ Надішліть, будь ласка, <b>тему для дебатів</b> (текст запитання).", parse_mode="HTML")
        # Тут не використовуємо FSM, а чекаємо на наступне текстове повідомлення
        return ConversationHandler.END 
        
    return ConversationHandler.END


async def choose_rounds_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропонує вибір кількості раундів для дебатів."""
    keyboard = []
    
    # Створення кнопок для фіксованих значень
    for r in ROUND_OPTIONS:
        keyboard.append(InlineKeyboardButton(str(r), callback_data=f"rounds_{r}"))
    
    # Додавання кнопки для введення власного значення
    keyboard.append(InlineKeyboardButton("Ввести своє число ✍️", callback_data="rounds_custom"))
    
    reply_markup = InlineKeyboardMarkup([keyboard])
    
    await update.message.reply_text(
        "Оберіть кількість раундів для дебатів (мінімум 2):",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    return CHOOSING_ROUNDS


async def rounds_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір кількості раундів кнопкою."""
    query = update.callback_query
    await query.answer()
    
    choice = query.data.split('_')[1]
    
    if choice == 'custom':
        # Перехід до очікування введення користувача
        await query.edit_message_text(
            "Введіть бажану кількість раундів (число, більше 1):",
            parse_mode="HTML"
        )
        return CHOOSING_ROUNDS
    
    try:
        rounds = int(choice)
        context.user_data['rounds'] = rounds
        await query.edit_message_text(
            f"Кількість раундів встановлено: <b>{rounds}</b>.\n"
            f"Тепер оберіть тему дебатів.",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    except ValueError:
        await query.edit_message_text("Помилка вибору. Спробуйте ще раз.")
        return CHOOSING_ROUNDS


async def receive_custom_rounds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє введення користувачем власного числа раундів."""
    text = update.message.text
    
    try:
        rounds = int(text.strip())
        
        if rounds <= 1:
            await update.message.reply_text(
                "Кількість раундів має бути <b>більше 1</b>. Спробуйте ще раз:",
                parse_mode="HTML"
            )
            return CHOOSING_ROUNDS
        
        context.user_data['rounds'] = rounds
        await update.message.reply_text(
            f"Кількість раундів встановлено: <b>{rounds}</b>.\n"
            f"Тепер оберіть тему дебатів.",
            parse_mode="HTML"
        )
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text(
            "Некоректний формат. Будь ласка, введіть числове значення більше 1.",
            parse_mode="HTML"
        )
        return CHOOSING_ROUNDS




# --------------------------
# II. Логіка Дебатів
# --------------------------

async def delete_previous_debate_messages(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Видаляє всі повідомлення останнього раунду."""
    messages_to_delete = debate_message_ids.pop(chat_id, [])
    for msg_id in messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass # Ігноруємо помилки, якщо повідомлення вже видалено

async def run_debate_round(session: DebateSession, chat_id: int, context: ContextTypes.DEFAULT_TYPE, user_id: int = None, client_key_mapping: Dict = None):
    """Виконує один раунд дебатів, оновлюючи UI."""
    
    if user_id is None:
        user_id = context.user_data.get('current_user_id')
    if client_key_mapping is None:
        client_key_mapping = context.user_data.get('client_key_mapping', {})
    
    # Очищуємо попередні повідомлення
    await delete_previous_debate_messages(chat_id, context)
    debate_message_ids[chat_id] = [] # Ініціалізуємо новий список

    # 1. Створюємо статус-повідомлення
    status_msg = await context.bot.send_message(
        chat_id,
        f"🔥 <b>РАУНД {session.round + 1}</b> ({session.round + 1}/{session.MAX_ROUNDS}) 🔥\n\n" + 
        # !!! ВИПРАВЛЕНО: додано .value та змінено на HTML !!!
        f"[{list(session.clients.keys())[0]}]: {DebateStatus.THINKING.value}\n[{list(session.clients.keys())[1]}]: {DebateStatus.THINKING.value}",
        parse_mode="HTML" # Уніфікуємо тут також
    )
    debate_message_ids[chat_id].append(status_msg.message_id)
    
    # 2. Запускаємо раунд асинхронно
    round_results = await session.run_next_round()
    
    # 3. Відстежуємо виконані запити та зменшуємо лімітів
    if user_id and client_key_mapping:
        for client_name in round_results.keys():
            key_id = client_key_mapping.get(client_name)
            if key_id:
                try:
                    DB_MANAGER.decrement_calls(key_id, user_id)
                except Exception as e:
                    print(f"Помилка при зменшенні запитів для {client_name}: {e}")
    
    # 4. Фінальне оновлення статусу
    await status_msg.edit_text(
        f"✅ <b>РАУНД {session.round} ЗАВЕРШЕНО</b> ✅", 
        parse_mode="HTML"
    )

    # 5. Відправка відповідей окремими повідомленнями
    for name, response in round_results.items():
        msg = await context.bot.send_message(
            chat_id, 
            text=f"<b>[{name}]</b>\n{response}", 
            parse_mode="HTML"
        )
        debate_message_ids[chat_id].append(msg.message_id)

    # Додаємо кнопку "Наступний раунд" або "Завершити"
    if session.round < session.MAX_ROUNDS:
        keyboard = [[InlineKeyboardButton("➡️ Наступний раунд", callback_data='debate_next_round')]]
    else:
        keyboard = [[InlineKeyboardButton("🏆 Переглянути фінальний результат", callback_data='debate_final_result')]]
        
    final_prompt_msg = await context.bot.send_message(
        chat_id, 
        "Раунд завершено. Що далі?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    debate_message_ids[chat_id].append(final_prompt_msg.message_id)
    

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробник тексту (питання) для запуску першого раунду."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    topic = update.message.text.strip()
    
    # 1. Захист від команд та порожнього тексту
    if topic.startswith('/') or not topic:
        return

    # 2. Завантажуємо ключі користувача з БД
    try:
        user_keys = DB_MANAGER.get_user_api_keys(user_id)
        
        if not user_keys:
            await update.message.reply_text(
                "🔑 Потрібно додати API-ключі. Використовуйте /addkey щоб додати ключ."
            )
            return
        
        # 3. Ініціалізуємо AI клієнти з активними ключами
        active_key_id = DB_MANAGER.get_active_key_id(user_id)
        
        if not active_key_id:
            await update.message.reply_text(
                "⚠️ Оберіть активний ключ за допомогою /mykeys"
            )
            return
        
        clients = {}
        client_key_mapping = {}  # Mappings: client_name -> key_id
        
        for key_info in user_keys:
            # key_info is a dict with: id, alias, service, calls_remaining, is_active
            key_id = key_info.get('id')
            alias = key_info.get('alias')
            service = key_info.get('service')
            calls_remaining = key_info.get('calls_remaining')
            
            # Пропускаємо ключі без запитів
            if calls_remaining <= 0:
                continue
            
            # Отримуємо розшифрований ключ
            decrypted_key, service_name = DB_MANAGER.get_api_key_decrypted(key_id, user_id)
            
            if decrypted_key and service_name in AI_CLIENTS_MAP:
                try:
                    # Ініціалізуємо клієнт з ключем
                    ClientClass = AI_CLIENTS_MAP[service_name]
                    client = ClientClass(decrypted_key)
                    clients[alias] = client
                    client_key_mapping[alias] = key_id  # Зберігаємо mapping
                except Exception as e:
                    print(f"Помилка при ініціалізації {service_name}: {e}")
        
        if len(clients) < 1:
            await update.message.reply_text(
                "❌ Немає доступних ключів з запитами. Перевірте /mykeys"
            )
            return
        
    except Exception as e:
        print(f"Помилка при завантаженні ключів: {e}")
        await update.message.reply_text(
            "❌ Виникла помилка при завантаженні ключів. Спробуйте пізніше."
        )
        return

    # 4. Ігноруємо, якщо вже йдуть дебати
    if user_id in active_sessions:
        await update.message.reply_text("Будь ласка, дочекайтеся завершення поточних дебатів.")
        return

    # 5. Ініціалізація сесії 
    session = DebateSession(topic=topic, clients_map=clients, max_rounds=3)
    active_sessions[user_id] = session
    
    # Зберігаємо користувача та mapping для відстеження запитів
    context.user_data['current_user_id'] = user_id
    context.user_data['client_key_mapping'] = client_key_mapping
    
    # 6. Одразу запускаємо перший раунд
    await run_debate_round(session, chat_id, context, user_id, client_key_mapping)




async def key_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробник вибору активного ключа з /mykeys."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if query.data == 'add_new_key':
        # Переходимо до /addkey команди
        await query.edit_message_text("Перенаправляємо до додавання нового ключа...")
        await addkey_command(update, context)
        return
    
    if query.data.startswith('select_key_'):
        key_id = int(query.data.split('_')[2])
        
        try:
            # Встановлюємо активний ключ
            success = DB_MANAGER.set_active_key(user_id, key_id)
            
            if success:
                await query.answer("✅ Ключ обраний!", show_alert=False)
                # Оновлюємо список ключів
                await mykeys_command(query, context)
            else:
                await query.answer("❌ Не вдалось обрати ключ!", show_alert=True)
        except Exception as e:
            print(f"Помилка при виборі ключа: {e}")
            await query.answer("❌ Помилка при обранні ключа!", show_alert=True)


async def handle_debate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробник кнопок 'Наступний раунд' та 'Фінальний результат'."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    session = active_sessions.get(user_id)
    
    if not session:
        await query.edit_message_text("Сесія дебатів завершена або не знайдена. Спробуйте /start.")
        return

    if query.data == 'debate_next_round':
        # Якщо сесія ще не завершена, запускаємо наступний раунд
        await query.edit_message_text(f"Запускаємо <b>Раунд {session.round + 1}</b>...", parse_mode="HTML")
        await run_debate_round(session, chat_id, context, user_id)
        
    elif query.data == 'debate_final_result':
        # 1. Очищуємо екран
        await delete_previous_debate_messages(chat_id, context)
        
        # 2. Генеруємо фінальний висновок
        final_prompt = "На основі всіх попередніх аргументів (які містяться в історії), сформулюй єдиний, компромісний висновок з теми."
        
        # Використовуємо перший доступний AI для фінального висновку
        client_name = list(session.clients.keys())[0] 
        client = session.clients[client_name]
        
        final_conclusion = await client.generate_response(
            system_prompt="Ти - незалежний модератор, твоє завдання - узагальнити дебати.",
            debate_history=session.get_full_history(),
            topic=final_prompt
        )
        
        # 3. Надсилаємо фінальне повідомлення
        await context.bot.send_message(
            chat_id, 
            "🏁 **ДЕБАТИ ЗАВЕРШЕНО!** 🏁\n\n"
            "**Фінальна відповідь моделей:**\n"
            f"[Llama3 (Groq)]: {session.history[-2].get('Llama3 (Groq)', 'Н/Д')[:50]}...\n"
            f"[Gemini]: {session.history[-1].get('Gemini', 'Н/Д')[:50]}...\n\n"
            f"**🏆 Об'єднаний висновок (від {client_name}):**\n"
            f"{final_conclusion}",
            parse_mode="HTML"
        )
        
        # 4. Видаляємо сесію та повертаємо головне меню
        del active_sessions[user_id]
        
        await context.bot.send_message(
            chat_id,
            "Виберіть наступну дію:",
            reply_markup=get_main_menu_markup(user_id)
        )


# --------------------------
# III. Запуск
# --------------------------

def main_bot_setup(token: str) -> Application:
    """Налаштовує Telegram Application, але НЕ запускає polling."""
    
    global APPLICATION
    
    if APPLICATION is not None:
        return APPLICATION
    
    # 1. Створюємо таблиці БД при першому запуску
    DB_MANAGER._create_tables()
    
    # Ініціалізуємо Application з переданим токеном
    APPLICATION = Application.builder().token(token).build()
    
    # ConversationHandler для FSM (вибір раундів та додавання ключів)
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("rounds", choose_rounds_command),
            CommandHandler("addkey", addkey_command),
            CallbackQueryHandler(main_menu_callback, pattern='^menu_'),
        ],
        states={
            CHOOSING_ROUNDS: [
                CallbackQueryHandler(rounds_callback_handler, pattern="^rounds_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_rounds),
            ],
            AWAITING_SERVICE: [
                CallbackQueryHandler(service_callback, pattern="^service_"),
            ],
            AWAITING_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_key_input),
            ],
            AWAITING_ALIAS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_alias_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    
    # Реєструємо всі обробники
    APPLICATION.add_handler(CommandHandler("start", start))
    APPLICATION.add_handler(CommandHandler("status", status_command))
    APPLICATION.add_handler(CommandHandler("help", help_command))
    APPLICATION.add_handler(CommandHandler("setup", setup_command))
    APPLICATION.add_handler(CommandHandler("profile", show_profile))
    APPLICATION.add_handler(CommandHandler("mykeys", mykeys_command))
    APPLICATION.add_handler(CommandHandler("addkey", addkey_command))
    APPLICATION.add_handler(conv_handler)
    
    # Хендлер для кнопок головного меню, які не ведуть у FSM
    APPLICATION.add_handler(CallbackQueryHandler(main_menu_callback, pattern='^menu_'))
    
    # Хендлер для вибору ключа з /mykeys
    APPLICATION.add_handler(CallbackQueryHandler(key_selection_callback, pattern='^select_key_|^add_new_key'))
    
    # Хендлер для кнопок управління дебатами
    APPLICATION.add_handler(CallbackQueryHandler(handle_debate_callback, pattern='^debate_'))
    
    # Хендлер для тексту (запитання), коли не активний FSM
    APPLICATION.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_question, 
        block=False
    ))
    
    return APPLICATION


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє помилки без зупинки бота."""
    error = context.error
    error_type = type(error).__name__
    error_msg = str(error)
    
    # Подавляємо Conflict помилки - вони означають, що інша інстанція запущена
    if "Conflict" in error_msg or "terminated by other getUpdates" in error_msg:
        print(f"⚠️  Conflict detected: Another bot instance is running")
        print(f"Деталі: {error_msg}")
        # Не логуємо трасбек для Conflict - це нормальна ситуація при перезапуску
        return
    
    # Логуємо інші помилки
    print(f"Update {update} caused error {error_type}: {error_msg}")
    if hasattr(error, '__traceback__'):
        import traceback
        traceback.print_exception(type(error), error, error.__traceback__)


def main() -> None:
    """Запуск бота у режимі Polling з перевіркою однієї інстанції."""
    import time
    import socket
    
    # Створюємо унікальний ідентифікатор для цієї інстанції
    instance_id = f"{socket.gethostname()}_{os.getpid()}_{int(time.time() * 1000) % 10000}"
    
    application = main_bot_setup(TELEGRAM_BOT_TOKEN)
    
    # Додаємо Error Handler
    application.add_error_handler(error_handler)
    
    print(f"Бот запущено у режимі Polling...")
    print(f"Instance ID: {instance_id}")
    print("Забезпечуємо єдину активну інстанцію...")
    
    try:
        application.run_polling(poll_interval=1.0, timeout=10, allowed_updates=None)
    except Exception as e:
        if "Conflict" in str(e):
            print("\n❌ HELP: Другий бот вже запущений!")
            print("Вирішення: Видаліть webhook через: python reset_webhook.py")
            print("Потім переробляйте на Railway!")
        raise


if __name__ == "__main__":
    main()
