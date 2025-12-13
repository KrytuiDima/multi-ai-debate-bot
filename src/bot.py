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

from ai_clients import BaseAI, AI_CLIENTS 
from debate_manager import DebateSession, DebateStatus
from database import DB_MANAGER  # Імпортуємо глобальний об'єкт

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- НОВІ ГЛОБАЛЬНІ ЗМІННІ ДЛЯ WEBHOOK ---
APPLICATION = None # Тут буде зберігатися об'єкт Application після ініціалізації
# --- КІНЕЦЬ НОВИХ ЗМІН ---

# --- СТАНИ FSM ---
# FSM використовується для ОДНОГО завдання: отримання API ключа
WAITING_API_KEY = 1
CHOOSING_ROUNDS = 2

# Раунди, які пропонуємо
ROUND_OPTIONS = [2, 3, 5, 10]

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
    """Генерує розмітку головного меню в залежності від статусу ключів."""
    # Викликаємо build_ai_clients, щоб завантажити ключі з БД (якщо їх немає в кеші)
    clients = build_ai_clients(user_id)

    count_gemini = len(clients.get('Gemini').api_keys) if clients and 'Gemini' in clients else 0
    count_groq = len(clients.get('Llama3 (Groq)').api_keys) if clients and 'Llama3 (Groq)' in clients else 0
    count_claude = len(clients.get('Claude').api_keys) if clients and 'Claude' in clients else 0
    count_deepseek = len(clients.get('DeepSeek').api_keys) if clients and 'DeepSeek' in clients else 0

    status_gemini = "✅" if count_gemini > 0 else "❌"
    status_groq = "✅" if count_groq > 0 else "❌"
    status_claude = "✅" if count_claude > 0 else "❌"
    status_deepseek = "✅" if count_deepseek > 0 else "❌"

    # Кнопки для додавання/статусу ключів
    key_buttons = [
        InlineKeyboardButton(f"Додати API Groq {status_groq} ({count_groq})", callback_data='menu_key_Llama3 (Groq)'),
        InlineKeyboardButton(f"Додати API Gemini {status_gemini} ({count_gemini})", callback_data='menu_key_Gemini'),
        InlineKeyboardButton(f"Додати API Claude {status_claude} ({count_claude})", callback_data='menu_key_Claude'),
        InlineKeyboardButton(f"Додати API DeepSeek {status_deepseek} ({count_deepseek})", callback_data='menu_key_DeepSeek'),
    ]
    # Кнопка для перегляду профілю
    profile_button = InlineKeyboardButton("👤 Профіль", callback_data='menu_profile')

    # Кнопка для початку дебатів (активна, якщо є ключі для обох моделей)
    is_ready = (count_gemini > 0 and count_groq > 0)

    debate_button_text = "⚔️ Почати дебати / Задати запитання" if is_ready else "🛑 Потрібні ключі для обох моделей"
    debate_button_data = "menu_ask" if is_ready else "menu_status"

    keyboard = [
        key_buttons,
        [profile_button],
        [InlineKeyboardButton(debate_button_text, callback_data=debate_button_data)],
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


def build_ai_clients(user_id: int) -> Optional[Dict[str, BaseAI]]:
    """Ініціалізує об'єкти клієнтів на основі списку збережених ключів (з БД)."""

    # 1. Спробувати отримати ключи з кешу
    keys_map = cached_user_api_keys.get(user_id)

    # 2. Якщо ключів немає в кеші, завантажити їх з бази даних
    if not keys_map:
        keys_map = DB_MANAGER.get_keys_by_user(user_id)
        if keys_map:
            cached_user_api_keys[user_id] = keys_map

    if not keys_map or len(keys_map) < 2:
        return None

    # 3. Ініціалізація клієнтів
    clients = {}
    for model_name, api_keys in keys_map.items():
        if api_keys:
            ClientCreator = AI_CLIENTS.get(model_name)
            if ClientCreator:
                # Використовуємо перший ключ для ініціалізації клієнта,
                # але зберігаємо весь список у атрибуті .api_keys
                client = ClientCreator(api_keys[0])
                setattr(client, 'api_keys', api_keys)
                clients[model_name] = client

    # 4. Кешування та повернення
    user_clients[user_id] = clients # Зберігаємо ініціалізовані об'єкти
    return clients


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
    
    if data.startswith('menu_key_'):
        # 1. Початок FSM для додавання ключа
        model_name = data.split('_')[2].replace('%20', ' ')
        context.user_data['temp_model_name'] = model_name
        
        await query.edit_message_text(
            f"Надішліть, будь ласка, Ваш API-ключ для <b>{model_name}</b>.",
            parse_mode="HTML"
        )
        return WAITING_API_KEY # Переходимо до FSM
    
    elif data == 'menu_profile':
        # Показати профіль користувача
        await show_profile(update, context)
        return ConversationHandler.END
        
    elif data == 'menu_ask':
        # 2. Початок дебатів (Задання запитання)
        await query.edit_message_text("✍️ Надішліть, будь ласка, <b>тему для дебатів</b> (текст запитання).", parse_mode="HTML")
        # Тут не використовуємо FSM, а чекаємо на наступне текстове повідомлення
        return ConversationHandler.END 
        
    elif data == 'menu_status':
        # 3. Якщо кнопа неактивна, просто показуємо статус
        await query.answer("Потрібно додати два API-ключі!")
        await query.edit_message_text(
            "🛑 Потрібно додати два API-ключі!\nВиберіть модель, щоб продовжити:",
            reply_markup=get_main_menu_markup(user_id),
            parse_mode="HTML"
        )
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


async def receive_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробник отримання API-ключа (FSM state)."""
    user_id = update.effective_user.id
    api_key = update.message.text.strip()
    model_name = context.user_data.get('temp_model_name')

    # Відповідь буде відправлена як нове повідомлення (не можна редагувати попереднє)
    status_msg = await update.message.reply_text("Перевіряю ключ...")

    try:
        ClientCreator = AI_CLIENTS.get(model_name)
        # Створюємо тимчасовий клієнт для валідації нового ключа
        temp_client = ClientCreator(api_key)
        is_valid = await temp_client.validate_key()

        if is_valid:
            # --- 1. ЗБЕРІГАННЯ В БД ---
            is_new = DB_MANAGER.add_key(user_id, model_name, api_key)

            if not is_new:
                # Ключ вже існує, просто оновлюємо кеш
                message_text = f"🔑 Ключ для <b>{model_name}</b> вже був доданий."
            else:
                message_text = f"✅ Ключ для <b>{model_name}</b> додано."

            # --- 2. ОНОВЛЕННЯ КЛІЄНТІВ ---
            # Видаляємо старий кеш, щоб build_ai_clients знову завантажив усі ключі з БД
            cached_user_api_keys.pop(user_id, None)
            clients_map = build_ai_clients(user_id)

            # Порахувати кількість ключів для моделі
            model_count = 0
            if clients_map and model_name in clients_map and getattr(clients_map.get(model_name), 'api_keys', None):
                model_count = len(clients_map.get(model_name).api_keys)

            await status_msg.edit_text(
                f"{message_text} (Всього: {model_count} ключів). Виберіть наступну дію:",
                reply_markup=get_main_menu_markup(user_id), 
                parse_mode="HTML"
            )

        else:
            await status_msg.edit_text(
                f"❌ Це не ключ для <b>{model_name}</b>. Спробуйте ще раз.",
                parse_mode="HTML"
            )
            return WAITING_API_KEY

    except Exception as e:
        print(f"Критична помилка при перевірці ключа: {e}")
        await status_msg.edit_text("Виникла непередбачена помилка. Спробуйте /start.")

    context.user_data.pop('temp_model_name', None)
    return ConversationHandler.END # Успішний вихід, якщо ключ валідний


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

async def run_debate_round(session: DebateSession, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Виконує один раунд дебатів, оновлюючи UI."""
    
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
    
    # 3. Фінальне оновлення статусу
    await status_msg.edit_text(
        f"✅ <b>РАУНД {session.round} ЗАВЕРШЕНО</b> ✅", 
        parse_mode="HTML"
    )

    # 4. Відправка відповідей окремими повідомленнями
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

    # 2. Перевірка наявності клієнтів (мінімум 2)
    clients = user_clients.get(user_id, {})
    if len(clients) < 2:
        await update.message.reply_text(
            "🛑 Потрібно додати принаймні два робочих API-ключі. Використовуйте /start."
        )
        return

    # 3. Ігноруємо, якщо вже йдуть дебати
    if user_id in active_sessions:
        await update.message.reply_text("Будь ласка, дочекайтеся завершення поточних дебатів.")
        return

    # 4. Ініціалізація сесії (фіксуємо 3 раунди, як просили)
    session = DebateSession(topic=topic, clients_map=clients, max_rounds=3)
    active_sessions[user_id] = session
    
    # 5. Одразу запускаємо перший раунд
    await run_debate_round(session, chat_id, context)


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
        await run_debate_round(session, chat_id, context)
        
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
    
    # ConversationHandler для FSM (введення API ключа та вибір раундів)
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("rounds", choose_rounds_command),
            CallbackQueryHandler(main_menu_callback, pattern='^menu_key_'),
        ],
        states={
            WAITING_API_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_key),
            ],
            CHOOSING_ROUNDS: [
                CallbackQueryHandler(rounds_callback_handler, pattern="^rounds_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_rounds),
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    
    # Реєструємо всі обробники
    APPLICATION.add_handler(CommandHandler("start", start))
    APPLICATION.add_handler(CommandHandler("status", status_command))
    APPLICATION.add_handler(CommandHandler("profile", show_profile))
    APPLICATION.add_handler(conv_handler)
    
    # Хендлер для кнопок головного меню, які не ведуть у FSM
    APPLICATION.add_handler(CallbackQueryHandler(main_menu_callback, pattern='^menu_'))
    
    # Хендлер для кнопок управління дебатами
    APPLICATION.add_handler(CallbackQueryHandler(handle_debate_callback, pattern='^debate_'))
    
    # Хендлер для тексту (запитання), коли не активний FSM
    APPLICATION.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_question, 
        block=False
    ))
    
    return APPLICATION


def main() -> None:
    """Запуск бота у режимі Polling."""
    application = main_bot_setup(TELEGRAM_BOT_TOKEN)
    
    print("Бот запущено у режимі Polling...")
    application.run_polling(poll_interval=1.0, timeout=10)


if __name__ == "__main__":
    main()
