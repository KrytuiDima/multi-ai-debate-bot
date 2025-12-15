# src/bot.py
import asyncio
import os
import logging
from typing import Dict, List, Optional, Tuple, Type
import sys
import time
import socket

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, error
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    filters, 
    ContextTypes, 
    ConversationHandler
)

# Виправляємо імпорти: додано AVAILABLE_MODELS
from ai_clients import BaseAI, AI_CLIENTS_MAP, MODEL_NAME_TO_ID, AVAILABLE_SERVICES, AVAILABLE_MODELS
from debate_manager import DebateSession, DebateStatus
from database import DB_MANAGER, decrypt_key 
from dotenv import load_dotenv

# Завантаження змінних середовища
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- НАЛАШТУВАННЯ ЛОГУВАННЯ ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- СТАНИ FSM ---
# Для /addkey
AWAITING_SERVICE = 1
AWAITING_KEY = 2
AWAITING_ALIAS = 3
AWAITING_LIMIT = 4 

# Для /debate
AWAITING_DEBATE_TOPIC = 10
AWAITING_DEBATE_ROUNDS = 11
AWAITING_DEBATE_AI1 = 12
AWAITING_DEBATE_AI2 = 13

# Максимальна кількість раундів для вибору
DEBATE_ROUNDS = [3, 5, 7]

# --- КОРИСНІ ФУНКЦІЇ ---

async def delete_previous_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Видаляє повідомлення, яке викликало колбек, якщо це можливо."""
    try:
        if update.callback_query and update.effective_message:
            await update.effective_message.delete()
    except Exception as e:
        logger.warning(f"Не вдалося видалити повідомлення: {e}")

# --- КОМАНДИ МЕНЮ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє команду /start."""
    user = update.effective_user
    text = (
        f"👋 Вітаю, {user.full_name}!\n\n"
        "Я — ваш персональний AI-дебатер. Я можу організувати дебати між двома різними AI-моделями на будь-яку тему.\n\n"
        "Для використання потрібно додати свої API-ключі. Використовуйте:\n"
        "🔹 /addkey - для додавання нового API-ключа.\n"
        "🔹 /mykeys - для перегляду та видалення ваших ключів.\n"
        "🔹 /debate - для початку нових дебатів."
    )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє команду /help."""
    text = (
        "**🤖 Команди AI-дебатера:**\n"
        "🔹 /start - Почати роботу та отримати вітання.\n"
        "🔹 /help - Показати цю довідку.\n"
        "🔹 /addkey - Додати новий API-ключ для Groq, Gemini, DeepSeek або Claude.\n"
        "🔹 /mykeys - Переглянути ваші збережені ключі та їхні ліміти. Можна видалити ключ.\n"
        "🔹 /debate - Розпочати нові дебати між двома обраними AI-моделями (за вашими ключами).\n"
        "\n_Важливо: Ваші ключі зберігаються у зашифрованому вигляді._"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє команду /history (замість неї покажемо поточний статус дебатів)."""
    # Перевіряємо, чи є активна сесія дебатів
    session: Optional[DebateSession] = context.chat_data.get('debate_session')
    
    if not session:
        await update.message.reply_text("Наразі немає активних дебатів. Спробуйте /debate.")
        return

    # Показуємо останній раунд та загальний статус
    text = (
        f"**📊 Активні дебати:**\n"
        f"Тема: _{session.topic}_\n"
        f"Раунд: **{session.round}/{session.MAX_ROUNDS}**\n"
        f"AI 1: `{list(session.clients.keys())[0]}` vs AI 2: `{list(session.clients.keys())[1]}`\n\n"
    )
    
    keyboard = []
    if session.is_running:
        text += f"Поточний статус: {DebateStatus.THINKING.value}\n"
        # Не додаємо кнопку, бо бот працює
    elif session.round > 0 and session.round < session.MAX_ROUNDS:
        text += f"Поточний статус: Очікування наступного раунду.\n"
        keyboard.append([InlineKeyboardButton("Продовжити раунд", callback_data='run_round')])
    elif session.round == session.MAX_ROUNDS:
        text += f"Поточний статус: {DebateStatus.FINISHED.value}\n"
    else:
        text += f"Поточний статус: Очікування початку (Раунд 1).\n"
        keyboard.append([InlineKeyboardButton("Розпочати раунд 1", callback_data='run_round')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)


# --- FSM: ДОДАВАННЯ КЛЮЧА /ADDKEY ---

async def addkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Починає розмову для додавання ключа."""
    keyboard = []
    for service in AVAILABLE_SERVICES:
        keyboard.append([InlineKeyboardButton(service, callback_data=f'service_{service}')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "**🔑 Який сервіс ви хочете додати?**", 
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return AWAITING_SERVICE

async def receive_service_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приймає вибір сервісу."""
    query = update.callback_query
    await query.answer()
    
    service_name = query.data.split('_')[1]
    context.user_data['temp_service'] = service_name
    await delete_previous_message(update, context)

    await query.edit_message_text(
        f"**🔗 Ви обрали: {service_name}.**\n"
        f"Тепер, будь ласка, **надішліть ваш API-ключ** для {service_name}."
        f"\n\n_Ви можете скасувати, надіславши команду /cancel_"
    , parse_mode='Markdown')
    return AWAITING_KEY

async def receive_api_key_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приймає API-ключ та починає його валідацію."""
    api_key = update.message.text.strip()
    service_name = context.user_data['temp_service']
    
    await update.message.reply_text(f"⏳ Перевіряю ключ для {service_name}...")
    
    # 1. Спроба створити клієнта
    try:
        # Для валідації беремо першу доступну модель для цього сервісу
        # AVAILABLE_MODELS тепер імпортовано
        model_name_key = AVAILABLE_MODELS.get(service_name, [None])[0]
        model_name = MODEL_NAME_TO_ID.get(model_name_key)
        
        if not model_name:
            await update.message.reply_text("Помилка: Не знайдено моделі для цього сервісу.")
            return ConversationHandler.END

        AIClientClass: Type[BaseAI] = AI_CLIENTS_MAP[service_name]
        client = AIClientClass(model_name=model_name, api_key=api_key)
    except Exception as e:
        await update.message.reply_text(f"Помилка ініціалізації клієнта: {e}")
        return AWAITING_KEY # Повторити спробу

    # 2. Асинхронна валідація ключа
    try:
        is_valid = await client.validate_key()
    except Exception as e:
        logger.error(f"Помилка під час валідації ключа {service_name}: {e}")
        is_valid = False

    if is_valid:
        context.user_data['temp_api_key'] = api_key
        context.user_data['temp_model_name'] = model_name_key
        await update.message.reply_text(
            f"✅ **Ключ для {service_name} успішно перевірено!**\n"
            f"Обрана модель: _{model_name_key} ({model_name})_\n\n"
            "Тепер, будь ласка, **надішліть унікальний аліас** (наприклад, `MyGroqKey` або `FastClaude`)."
        , parse_mode='Markdown')
        return AWAITING_ALIAS
    else:
        await update.message.reply_text(
            f"❌ **Помилка валідації ключа для {service_name}.**\n"
            "Перевірте ключ і спробуйте ще раз. Можливо, він недійсний або вичерпано ліміт."
        )
        return AWAITING_KEY

async def receive_alias_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приймає аліас."""
    alias = update.message.text.strip()
    context.user_data['temp_alias'] = alias

    await update.message.reply_text(
        f"**🤖 Аліас '{alias}' встановлено.**\n\n"
        "І останнє: **встановіть ліміт викликів** (наприклад, 100). Це захист від випадкового вичерпання лімітів."
        "\n_Введіть ціле число (0 для безліміту)._"
    , parse_mode='Markdown')
    return AWAITING_LIMIT


async def receive_limit_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приймає ліміт та зберігає ключ у БД."""
    try:
        calls_limit = int(update.message.text.strip())
        if calls_limit < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Будь ласка, введіть коректне ціле число (0 або більше).")
        return AWAITING_LIMIT

    user_id = update.effective_user.id
    service_name = context.user_data['temp_service']
    api_key = context.user_data['temp_api_key']
    alias = context.user_data['temp_alias']

    # Зберігаємо у БД
    success = DB_MANAGER.add_new_key(
        user_id=user_id,
        ai_service=service_name,
        api_key=api_key,
        alias=alias,
        calls_limit=calls_limit
    )

    if success:
        limit_text = "Безлімітно" if calls_limit == 0 else f"{calls_limit} запитів"
        await update.message.reply_text(
            f"**🎉 Ключ '{alias}' ({service_name}) успішно додано!**\n"
            f"Ліміт: {limit_text}. Поточних: {calls_limit}."
        , parse_mode='Markdown')
    else:
        await update.message.reply_text(
            f"❌ **Помилка збереження ключа.**\n"
            "Можливо, ви вже маєте ключ з таким аліасом для цього сервісу. Спробуйте інший аліас або /mykeys."
        )

    # Очищуємо дані сесії
    context.user_data.pop('temp_service', None)
    context.user_data.pop('temp_api_key', None)
    context.user_data.pop('temp_alias', None)
    context.user_data.pop('temp_model_name', None)
    
    return ConversationHandler.END

# --- КОМАНДА ПЕРЕГЛЯДУ КЛЮЧІВ /MYKEYS ---

async def mykeys_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує всі збережені ключі користувача."""
    user_id = update.effective_user.id
    keys = DB_MANAGER.get_keys_by_user(user_id) # (key_id, service, key, alias, limit, remaining)

    if not keys:
        await update.message.reply_text(
            "У вас поки немає доданих API-ключів. Використовуйте /addkey, щоб додати перший."
        )
        return

    text = "**🔑 Ваші збережені API-ключі:**\n\n"
    keyboard = []
    
    for key_id, service, _, alias, calls_limit, calls_remaining in keys:
        limit_display = "Безліміт" if calls_limit == 0 else str(calls_limit)
        
        # Перевірка статусу ліміту
        status = ""
        if calls_limit > 0 and calls_remaining <= 0:
            status = " (❌ ВИЧЕРПАНО)"
        elif calls_limit > 0 and calls_remaining < calls_limit * 0.1:
            status = " (⚠️ НИЗЬКИЙ ЛІМІТ)"
            
        text += (
            f"**{alias}** ({service})\n"
            f"   - Ліміт: {limit_display}\n"
            f"   - Залишок: **{calls_remaining}**{status}\n"
            f"   - ID: `{key_id}`\n---\n"
        )
        
        keyboard.append([
            InlineKeyboardButton(f"Видалити {alias} (ID: {key_id})", callback_data=f'deletekey_{key_id}')
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def delete_key_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє видалення ключа."""
    query = update.callback_query
    await query.answer()
    
    key_id = int(query.data.split('_')[1])
    user_id = update.effective_user.id

    success = DB_MANAGER.delete_key(user_id, key_id)

    if success:
        # Видаляємо старе повідомлення або редагуємо, щоб уникнути помилки "Message is not modified"
        try:
             await query.edit_message_text(f"✅ Ключ ID `{key_id}` успішно видалено.", parse_mode='Markdown')
        except error.BadRequest:
             # Якщо повідомлення вже змінено, просто ігноруємо
             pass
        # Оновлюємо список
        await mykeys_command(update, context) 
    else:
        await query.edit_message_text(f"❌ Помилка видалення ключа ID `{key_id}`. Можливо, він вже був видалений.")


# --- FSM: ДЕБАТИ /DEBATE ---

async def debate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Починає процес налаштування дебатів - введення теми."""
    
    # Скидаємо будь-яку стару сесію
    if context.chat_data.get('debate_session'):
        context.chat_data.pop('debate_session')

    await update.message.reply_text(
        "**💬 Починаємо налаштування дебатів!**\n\n"
        "**1. Введіть тему дебатів** (наприклад, _'Чи потрібен безумовний базовий дохід?'_)."
        "\n\n_Ви можете скасувати, надіславши команду /cancel_"
    , parse_mode='Markdown')
    return AWAITING_DEBATE_TOPIC

async def debate_topic_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приймає тему та просить обрати кількість раундів."""
    context.chat_data['debate_topic'] = update.message.text.strip()
    
    keyboard = []
    for rounds in DEBATE_ROUNDS:
        keyboard.append([InlineKeyboardButton(f"{rounds} раундів", callback_data=f'rounds_{rounds}')])
        
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"**Тема:** _{context.chat_data['debate_topic']}_\n\n"
        "**2. Скільки раундів** триватимуть дебати?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return AWAITING_DEBATE_ROUNDS

async def debate_rounds_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приймає кількість раундів та просить обрати AI 1."""
    query = update.callback_query
    await query.answer()
    
    context.chat_data['debate_rounds'] = int(query.data.split('_')[1])
    await delete_previous_message(update, context)

    user_id = update.effective_user.id
    keys = DB_MANAGER.get_keys_by_user(user_id) # (key_id, service, key, alias, limit, remaining)

    if len(keys) < 2:
        await query.edit_message_text(
            "❌ **У вас недостатньо ключів.** Для дебатів потрібно **мінімум два** активних ключі.\n"
            f"Зараз у вас: {len(keys)}. Використовуйте /addkey, щоб додати більше."
        , parse_mode='Markdown')
        return ConversationHandler.END

    context.chat_data['available_keys'] = keys
    
    keyboard = []
    for key_id, service, _, alias, calls_limit, calls_remaining in keys:
        limit_needed = context.chat_data['debate_rounds']
        status = f"({calls_remaining}/{calls_limit or '∞'})"
        if calls_limit > 0 and calls_remaining < limit_needed:
            status = f"⚠️ ЛІМІТ НИЗЬКИЙ ({calls_remaining}/{limit_needed})"
        
        keyboard.append([
            InlineKeyboardButton(f"{alias} ({service}) {status}", callback_data=f'ai1_{key_id}')
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"**Тема:** _{context.chat_data['debate_topic']}_\n"
        f"**Раундів:** {context.chat_data['debate_rounds']}\n\n"
        "**3. Оберіть AI 1** (Захисник).",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return AWAITING_DEBATE_AI1

async def debate_ai1_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приймає вибір AI 1 та просить обрати AI 2."""
    query = update.callback_query
    await query.answer()
    
    ai1_key_id = int(query.data.split('_')[1])
    context.chat_data['ai1_key_id'] = ai1_key_id
    
    # Видаляємо вже обраний ключ зі списку доступних для AI 2
    keys = context.chat_data['available_keys']
    ai2_choices = [key for key in keys if key[0] != ai1_key_id]
    
    ai1_data = next(key for key in keys if key[0] == ai1_key_id)
    ai1_alias = ai1_data[3]

    keyboard = []
    for key_id, service, _, alias, calls_limit, calls_remaining in ai2_choices:
        limit_needed = context.chat_data['debate_rounds']
        status = f"({calls_remaining}/{calls_limit or '∞'})"
        if calls_limit > 0 and calls_remaining < limit_needed:
            status = f"⚠️ ЛІМІТ НИЗЬКИЙ ({calls_remaining}/{limit_needed})"
        
        keyboard.append([
            InlineKeyboardButton(f"{alias} ({service}) {status}", callback_data=f'ai2_{key_id}')
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"**AI 1 (Захисник):** _{ai1_alias}_\n"
        "**4. Оберіть AI 2** (Опонент).",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return AWAITING_DEBATE_AI2

async def debate_ai2_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приймає вибір AI 2, створює сесію дебатів та запускає перший раунд."""
    query = update.callback_query
    await query.answer()

    ai2_key_id = int(query.data.split('_')[1])
    context.chat_data['ai2_key_id'] = ai2_key_id
    
    await delete_previous_message(update, context)

    # 1. Збір та перевірка даних
    topic = context.chat_data['debate_topic']
    max_rounds = context.chat_data['debate_rounds']
    keys = context.chat_data['available_keys'] # (key_id, service, key, alias, limit, remaining)
    
    ai1_data = next(key for key in keys if key[0] == context.chat_data['ai1_key_id'])
    ai2_data = next(key for key in keys if key[0] == context.chat_data['ai2_key_id'])
    
    limit_needed = max_rounds

    # Перевірка лімітів 
    if ai1_data[5] < limit_needed and ai1_data[4] > 0:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ **Ліміт вичерпано.** AI 1 ({ai1_data[3]}) має лише {ai1_data[5]} запитів, але потрібно {limit_needed}."
        )
        return ConversationHandler.END
    if ai2_data[5] < limit_needed and ai2_data[4] > 0:
         await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ **Ліміт вичерпано.** AI 2 ({ai2_data[3]}) має лише {ai2_data[5]} запитів, але потрібно {limit_needed}."
        )
         return ConversationHandler.END


    # 2. Створення клієнтів
    try:
        clients_map: Dict[str, BaseAI] = {}
        key_ids_map: Dict[str, int] = {}
        
        # AI 1
        service1, key1, alias1 = ai1_data[1], ai1_data[2], ai1_data[3]
        model_name1_key = AVAILABLE_MODELS.get(service1, [None])[0]
        model_name1 = MODEL_NAME_TO_ID.get(model_name1_key)
        
        AIClientClass1: Type[BaseAI] = AI_CLIENTS_MAP[service1]
        clients_map[alias1] = AIClientClass1(model_name=model_name1, api_key=key1)
        key_ids_map[alias1] = ai1_data[0]
        
        # AI 2
        service2, key2, alias2 = ai2_data[1], ai2_data[2], ai2_data[3]
        model_name2_key = AVAILABLE_MODELS.get(service2, [None])[0]
        model_name2 = MODEL_NAME_TO_ID.get(model_name2_key)
        
        AIClientClass2: Type[BaseAI] = AI_CLIENTS_MAP[service2]
        clients_map[alias2] = AIClientClass2(model_name=model_name2, api_key=key2)
        key_ids_map[alias2] = ai2_data[0]

    except Exception as e:
        logger.error(f"Помилка ініціалізації клієнтів дебатів: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ **Критична помилка ініціалізації AI-клієнтів.** Перевірте, чи встановлені всі необхідні бібліотеки (groq, google-genai, anthropic, httpx)."
        )
        return ConversationHandler.END

    # 3. Створення сесії дебатів
    session = DebateSession(
        topic=topic,
        clients_map=clients_map,
        key_ids_map=key_ids_map,
        max_rounds=max_rounds
    )
    context.chat_data['debate_session'] = session
    
    # 4. Повідомлення про початок
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"**⚔️ Дебати розпочато!**\n\n"
            f"**Тема:** _{topic}_\n"
            f"**Учасники:** {alias1} ({model_name1_key}) проти {alias2} ({model_name2_key})\n"
            f"**Раундів:** {max_rounds}\n\n"
            "Натисніть кнопку, щоб почати перший раунд..."
        ),
        parse_mode='Markdown'
    )
    
    # Запускаємо перший раунд (відразу після створення)
    await run_debate_round(update, context)

    # Виходимо з ConversationHandler
    return ConversationHandler.END


# --- ЛОГІКА ДЕБАТІВ ---

async def run_debate_round(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє наступний раунд дебатів."""
    query = update.callback_query
    
    session: Optional[DebateSession] = context.chat_data.get('debate_session')
    if not session:
        if query:
            await query.answer("Помилка: Не знайдено активної сесії дебатів. Спробуйте /debate.")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Помилка: Не знайдено активної сесії дебатів. Спробуйте /debate.")
        return

    if session.is_running:
        if query:
            await query.answer("Зачекайте, AI вже думають над своїми ходами...")
        return
        
    # Якщо це колбек, видаляємо кнопку, щоб уникнути подвійного натискання
    if query:
        await query.answer(f"Запускаю раунд {session.round + 1}...")
        try:
            # Змінюємо повідомлення на "Думає..."
            await query.edit_message_text(
                f"**Тема:** _{session.topic}_\n"
                f"**РАУНД {session.round + 1}/{session.MAX_ROUNDS}**\n\n"
                f"{DebateStatus.THINKING.value}"
            , parse_mode='Markdown')
        except error.BadRequest as e:
            # Якщо повідомлення занадто старе або вже змінено
            logger.warning(f"Failed to edit message to 'THINKING': {e}")
            pass

    # Основна логіка раунду
    try:
        is_finished, result_text = await session.next_round()
    except Exception as e:
        logger.error(f"Критична помилка виконання раунду: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ **Критична помилка під час виконання раунду:**\n`{e}`\nДебати зупинено. Спробуйте /debate знову."
        , parse_mode='Markdown')
        context.chat_data.pop('debate_session', None)
        return

    # 4. Відправка результатів
    
    # Кнопка для наступного раунду
    keyboard = []
    if not is_finished:
        keyboard.append([InlineKeyboardButton("➡️ Наступний раунд", callback_data='run_round')])
        final_text = result_text + "\n\n**Натисніть 'Наступний раунд'** для продовження."
    else:
        final_text = result_text + "\n\n**🛑 ДЕБАТИ ЗАВЕРШЕНО!**\n\nВикористовуйте /debate для нових дебатів."
        context.chat_data.pop('debate_session', None)
        
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Використовуємо `send_message` для коректного відображення довгих відповідей
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=final_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# --- СКИНУТИ РОЗМОВУ ---

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє команду /cancel та завершує будь-яку розмову."""
    if update.message:
        try:
            await update.message.reply_text(
                '✅ Скасовано. Ви можете почати нову операцію.', 
                reply_markup=InlineKeyboardMarkup([])
            )
        except Exception:
             pass # Не критично
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text('✅ Скасовано.')
        except Exception:
            pass # Не критично
        
    # Скидаємо всі тимчасові дані
    context.user_data.pop('temp_service', None)
    context.user_data.pop('temp_api_key', None)
    context.user_data.pop('temp_alias', None)
    context.chat_data.pop('debate_session', None)
    context.chat_data.pop('debate_topic', None)
    
    return ConversationHandler.END


# --- ЗАГАЛЬНІ НАЛАШТУВАННЯ ---

def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Логує помилки та обробляє типові ситуації."""
    try:
        error = context.error
        error_msg = str(error)
        error_type = type(error).__name__

        if isinstance(error, error.Conflict) or 'Conflict' in error_type:
             logger.info("Conflict detected, likely another instance is running.")
             return
        
        logger.error(f"Update {update} caused error {error_type}: {error_msg}")
        
        # Відправка повідомлення користувачу про критичну помилку
        if update and update.effective_chat:
            if 'Message is not modified' in error_msg or 'Message to edit not found' in error_msg:
                 # Ігноруємо цю помилку, вона часта при редагуванні
                 return

            if 'telegram.error' in error_type:
                 # Типова помилка, яку можна ігнорувати або логувати
                 logger.info(f"Telegram API error: {error_msg}")
                 return

            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ **Виникла непередбачувана помилка!**\nСпробуйте команду ще раз або зверніться до розробника. Деталі: `{error_type}`"
            , parse_mode='Markdown')

    except Exception as e:
        logger.critical(f"Помилка в обробнику помилок: {e}")


def main_bot_setup(token: str) -> Application:
    """Створює та налаштовує об'єкт Application."""
    if not token:
        raise ValueError("Token is not set.")
        
    application = Application.builder().token(token).build()

    # --- Хендлери для /addkey (FSM) ---
    conv_addkey = ConversationHandler(
        entry_points=[CommandHandler('addkey', addkey_command)],
        states={
            AWAITING_SERVICE: [CallbackQueryHandler(receive_service_choice, pattern='^service_')],
            AWAITING_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_key_input)],
            AWAITING_ALIAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_alias_input)],
            AWAITING_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_limit_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # --- Хендлери для /debate (FSM) ---
    conv_debate = ConversationHandler(
        entry_points=[CommandHandler('debate', debate_command)],
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
    
    # Хендлери для видалення ключа
    application.add_handler(CallbackQueryHandler(delete_key_handler, pattern='^deletekey_'))
    
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
    
    # Виводимо інформацію про інстанцію
    instance_id = f"{socket.gethostname()}_{os.getpid()}_{int(time.time() * 1000) % 10000}"
    print(f"Бот запущено у режимі Polling...")
    print(f"Instance ID: {instance_id}")

    try:
        application.run_polling(poll_interval=1.0, timeout=10.0, close_loop=False)
    except error.Conflict as e:
        logger.error(f"Критична помилка: Конфлікт інстанцій. Переконайтеся, що не запущено Webhook та лише один процес Polling: {e}")
    except Exception as e:
        logger.critical(f"Критична помилка запуску бота: {e}")
        # Логуємо трасбек для критичних помилок
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    # Оскільки тут використовується sys, socket та інші системні речі, 
    # це має бути запущено з кореневої директорії проекту, де є src/
    
    # Додамо перевірку для локального запуску
    if not os.path.exists('./src') and not os.path.exists('./src/bot.py'):
        print("Попередження: Схоже, ви запускаєте файл не з кореневої папки проекту, переконайтеся, що модулі імпортуються коректно.")
    
    # Встановлюємо шлях, щоб уникнути помилок імпорту
    if os.path.isdir('./src') and './src' not in sys.path:
        sys.path.insert(0, './src')
        
    main()