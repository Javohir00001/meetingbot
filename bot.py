import os
import json
import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes,
    filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  ⚙️  НАСТРОЙКИ — ЗАПОЛНИ ЭТО ПЕРЕД ЗАПУСКОМ
# ─────────────────────────────────────────────
BOT_TOKEN = "8685100980:AAE4N7JmQQ8vdNPl6_Xqo8e1XQkU82zfWi4"          # токен от @BotFather
SUPER_ADMIN_ID = 677456564              # твой Telegram user_id (число)
TIMEZONE = "Asia/Tashkent"             # часовой пояс
# ─────────────────────────────────────────────

DATA_FILE = "data.json"

# Состояния диалога
(
    MAIN_MENU,
    ASK_TIME, ASK_TYPE, ASK_WHO, ASK_USERNAMES,
    ASK_LINK, ASK_TITLE, CONFIRM,
    ADMIN_MENU, ADD_ADMIN, REMOVE_ADMIN,
) = range(11)


# ══════════════════════════════════════════════
#  ХРАНИЛИЩЕ (простой JSON файл)
# ══════════════════════════════════════════════

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"admins": [], "meetings": [], "group_chat_id": None}

def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_admin(user_id: int) -> bool:
    data = load_data()
    return user_id == SUPER_ADMIN_ID or user_id in data["admins"]


# ══════════════════════════════════════════════
#  КОМАНДА /start
# ══════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(
            "👋 Привет! Я бот для напоминания о встречах.\n"
            "У тебя нет прав для настройки. Обратись к администратору."
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("➕ Добавить встречу", callback_data="add_meeting")],
        [InlineKeyboardButton("📋 Список встреч", callback_data="list_meetings")],
        [InlineKeyboardButton("🗑 Удалить встречу", callback_data="delete_meeting")],
        [InlineKeyboardButton("👥 Управление админами", callback_data="manage_admins")],
        [InlineKeyboardButton("🔗 Привязать группу", callback_data="set_group")],
    ]
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я помогу настроить напоминания о встречах для твоей группы.\n"
        "Что хочешь сделать?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MAIN_MENU


# ══════════════════════════════════════════════
#  ГЛАВНОЕ МЕНЮ — обработка кнопок
# ══════════════════════════════════════════════

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "add_meeting":
        await query.edit_message_text("⏰ Во сколько будет встреча?\nНапиши время в формате ЧЧ:ММ (например: 10:30)")
        return ASK_TIME

    elif data == "list_meetings":
        return await show_meetings(update, context)

    elif data == "delete_meeting":
        return await show_delete_menu(update, context)

    elif data == "manage_admins":
        if update.effective_user.id != SUPER_ADMIN_ID:
            await query.edit_message_text("❌ Только супер-админ может управлять администраторами.")
            return ConversationHandler.END
        return await admin_menu(update, context)

    elif data == "set_group":
        data_store = load_data()
        group = data_store.get("group_chat_id")
        text = (
            f"✅ Сейчас привязана группа: `{group}`\n\n" if group else
            "ℹ️ Группа ещё не привязана.\n\n"
        )
        await query.edit_message_text(
            text +
            "Чтобы привязать группу:\n"
            "1. Добавь меня в нужную группу\n"
            "2. Напиши в той группе команду /register\n"
            "Я запомню её как основную группу для напоминаний.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    elif data == "back_main":
        return await back_to_main(update, context)


async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ Добавить встречу", callback_data="add_meeting")],
        [InlineKeyboardButton("📋 Список встреч", callback_data="list_meetings")],
        [InlineKeyboardButton("🗑 Удалить встречу", callback_data="delete_meeting")],
        [InlineKeyboardButton("👥 Управление админами", callback_data="manage_admins")],
        [InlineKeyboardButton("🔗 Привязать группу", callback_data="set_group")],
    ]
    msg = "Главное меню — что хочешь сделать?"
    if query:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    return MAIN_MENU


# ══════════════════════════════════════════════
#  ДОБАВЛЕНИЕ ВСТРЕЧИ — шаг 1: время
# ══════════════════════════════════════════════

async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        t = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text("❌ Неправильный формат. Напиши время как ЧЧ:ММ, например 10:30")
        return ASK_TIME

    context.user_data["meeting_time"] = text
    keyboard = [
        [InlineKeyboardButton("🔁 Ежедневный (дейли)", callback_data="type_daily")],
        [InlineKeyboardButton("1️⃣ Одноразовая встреча", callback_data="type_once")],
    ]
    await update.message.reply_text(
        f"✅ Время: {text}\n\nЭто ежедневный дейли или одноразовая встреча?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_TYPE


# ══════════════════════════════════════════════
#  Шаг 2: тип встречи
# ══════════════════════════════════════════════

async def ask_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["meeting_type"] = query.data  # "type_daily" или "type_once"

    keyboard = [
        [InlineKeyboardButton("📢 Тегнуть всех (@all)", callback_data="who_all")],
        [InlineKeyboardButton("📝 Указать список username", callback_data="who_list")],
    ]
    await query.edit_message_text(
        "Кого тегнуть при напоминании?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_WHO


# ══════════════════════════════════════════════
#  Шаг 3: кого тегать
# ══════════════════════════════════════════════

async def ask_who(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "who_all":
        context.user_data["mention_all"] = True
        await query.edit_message_text(
            "✏️ Напиши username всех участников через запятую или пробел.\n"
            "Пример: @ivan, @maria, @alex\n\n"
            "Бот тегнёт всех этих людей при каждом напоминании."
        )
        return ASK_USERNAMES
    else:
        context.user_data["mention_all"] = False
        await query.edit_message_text(
            "✏️ Напиши список username через запятую или пробел.\n"
            "Пример: @ivan, @maria, @alex"
        )
        return ASK_USERNAMES


async def ask_usernames(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # парсим юзернеймы
    parts = text.replace(",", " ").split()
    usernames = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not p.startswith("@"):
            p = "@" + p
        usernames.append(p)

    if not usernames:
        await update.message.reply_text("❌ Не нашёл ни одного username. Попробуй ещё раз:")
        return ASK_USERNAMES

    context.user_data["usernames"] = usernames
    await update.message.reply_text(
        f"✅ Буду тегать: {' '.join(usernames)}\n\n"
        "🔗 Введи ссылку на встречу (например https://meet.google.com/xxx)\n"
        "Или напиши «нет» если ссылки нет:"
    )
    return ASK_LINK


# ══════════════════════════════════════════════
#  Шаг 4: ссылка
# ══════════════════════════════════════════════

async def ask_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["link"] = "" if text.lower() in ("нет", "no", "-") else text
    await update.message.reply_text("📌 Как называется встреча? (например: Дейли, Планёрка, Sprint Review)")
    return ASK_TITLE


# ══════════════════════════════════════════════
#  Шаг 5: название → подтверждение
# ══════════════════════════════════════════════

async def ask_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["title"] = update.message.text.strip()
    ud = context.user_data

    meet_type = "🔁 Ежедневно" if ud["meeting_type"] == "type_daily" else "1️⃣ Одноразово"
    who = "все участники группы" if ud["mention_all"] else " ".join(ud["usernames"])
    link_line = f"\n🔗 Ссылка: {ud['link']}" if ud.get("link") else ""

    text = (
        f"Проверь настройки встречи:\n\n"
        f"📌 Название: {ud['title']}\n"
        f"⏰ Время: {ud['meeting_time']}\n"
        f"📅 Тип: {meet_type}\n"
        f"👥 Тегать: {who}"
        f"{link_line}\n\n"
        f"Всё верно?"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Сохранить", callback_data="confirm_save")],
        [InlineKeyboardButton("❌ Отмена", callback_data="back_main")],
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM


async def confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data != "confirm_save":
        return await back_to_main(update, context)

    ud = context.user_data
    data = load_data()

    meeting = {
        "id": int(datetime.now().timestamp()),
        "title": ud["title"],
        "time": ud["meeting_time"],
        "type": ud["meeting_type"],      # type_daily / type_once
        "mention_all": ud["mention_all"],
        "usernames": ud.get("usernames", []),
        "link": ud.get("link", ""),
        "active": True,
    }
    data["meetings"].append(meeting)
    save_data(data)

    # Перезапускаем планировщик чтобы подхватить новую встречу
    await schedule_all_meetings(context.application)

    meet_type = "🔁 Ежедневно" if meeting["type"] == "type_daily" else "1️⃣ Одноразово"
    await query.edit_message_text(
        f"✅ Встреча сохранена!\n\n"
        f"📌 {meeting['title']} в {meeting['time']} ({meet_type})\n\n"
        f"Бот будет отправлять напоминание за 10 минут до начала и в момент начала."
    )
    context.user_data.clear()
    return ConversationHandler.END


# ══════════════════════════════════════════════
#  СПИСОК ВСТРЕЧ
# ══════════════════════════════════════════════

async def show_meetings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_data()
    meetings = data.get("meetings", [])

    if not meetings:
        await query.edit_message_text(
            "📋 Встреч пока нет.\n",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_main")]])
        )
        return MAIN_MENU

    lines = []
    for m in meetings:
        meet_type = "🔁" if m["type"] == "type_daily" else "1️⃣"
        status = "✅" if m["active"] else "⏸"
        lines.append(f"{status} {meet_type} {m['title']} — {m['time']}")

    text = "📋 Список встреч:\n\n" + "\n".join(lines)
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_main")]])
    )
    return MAIN_MENU


# ══════════════════════════════════════════════
#  УДАЛЕНИЕ ВСТРЕЧИ
# ══════════════════════════════════════════════

async def show_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_data()
    meetings = data.get("meetings", [])

    if not meetings:
        await query.edit_message_text(
            "🗑 Нечего удалять — встреч нет.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_main")]])
        )
        return MAIN_MENU

    keyboard = []
    for m in meetings:
        meet_type = "🔁" if m["type"] == "type_daily" else "1️⃣"
        keyboard.append([InlineKeyboardButton(
            f"🗑 {meet_type} {m['title']} {m['time']}",
            callback_data=f"del_{m['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])

    await query.edit_message_text(
        "Выбери встречу для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MAIN_MENU


async def delete_meeting_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    meeting_id = int(query.data.replace("del_", ""))

    data = load_data()
    before = len(data["meetings"])
    data["meetings"] = [m for m in data["meetings"] if m["id"] != meeting_id]
    save_data(data)

    if len(data["meetings"]) < before:
        await schedule_all_meetings(context.application)
        await query.edit_message_text(
            "✅ Встреча удалена.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_main")]])
        )
    else:
        await query.edit_message_text("❌ Не нашёл такую встречу.")
    return MAIN_MENU


# ══════════════════════════════════════════════
#  УПРАВЛЕНИЕ АДМИНАМИ
# ══════════════════════════════════════════════

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_data()
    admins = data.get("admins", [])

    admin_list = "\n".join([f"• {a}" for a in admins]) if admins else "пока никого"
    keyboard = [
        [InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin")],
        [InlineKeyboardButton("➖ Удалить админа", callback_data="remove_admin")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        f"👥 Управление администраторами\n\n"
        f"Текущие админы (ID):\n{admin_list}\n\n"
        f"Супер-админ: {SUPER_ADMIN_ID}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_MENU


async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "add_admin":
        await query.edit_message_text("Напиши Telegram ID пользователя которого хочешь добавить в админы:")
        return ADD_ADMIN
    elif query.data == "remove_admin":
        await query.edit_message_text("Напиши Telegram ID пользователя которого хочешь убрать из админов:")
        return REMOVE_ADMIN
    elif query.data == "back_main":
        return await back_to_main(update, context)


async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом. Попробуй ещё раз:")
        return ADD_ADMIN

    data = load_data()
    if new_id == SUPER_ADMIN_ID:
        await update.message.reply_text("Это супер-админ, он уже имеет все права.")
        return ConversationHandler.END
    if new_id in data["admins"]:
        await update.message.reply_text(f"ℹ️ ID {new_id} уже в списке админов.")
        return ConversationHandler.END

    data["admins"].append(new_id)
    save_data(data)
    await update.message.reply_text(f"✅ ID {new_id} добавлен в список администраторов.")
    return ConversationHandler.END


async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rem_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом. Попробуй ещё раз:")
        return REMOVE_ADMIN

    data = load_data()
    if rem_id not in data["admins"]:
        await update.message.reply_text(f"ℹ️ ID {rem_id} не найден в списке.")
        return ConversationHandler.END

    data["admins"].remove(rem_id)
    save_data(data)
    await update.message.reply_text(f"✅ ID {rem_id} убран из администраторов.")
    return ConversationHandler.END


# ══════════════════════════════════════════════
#  РЕГИСТРАЦИЯ ГРУППЫ
# ══════════════════════════════════════════════

async def register_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Эту команду нужно написать в группе.")
        return

    if not is_admin(user.id):
        await update.message.reply_text("❌ Только администраторы могут привязать группу.")
        return

    data = load_data()
    data["group_chat_id"] = chat.id
    save_data(data)
    await update.message.reply_text(
        f"✅ Группа «{chat.title}» привязана!\n"
        f"ID группы: `{chat.id}`\n\n"
        f"Теперь я буду присылать напоминания сюда.",
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════════
#  ПЛАНИРОВЩИК НАПОМИНАНИЙ
# ══════════════════════════════════════════════

def build_reminder_message(meeting: dict, is_start: bool) -> str:
    """Строим текст напоминания"""
    if meeting["mention_all"]:
        mention = "🔔 Всем!"
    else:
        mention = " ".join(meeting["usernames"])

    title = meeting["title"]
    link_line = f"\n🔗 {meeting['link']}" if meeting.get("link") else ""

    if is_start:
        return (
            f"{mention}\n\n"
            f"🚀 Начинается {title}!\n"
            f"Заходите прямо сейчас! ⬇️"
            f"{link_line}"
        )
    else:
        return (
            f"{mention}\n\n"
            f"⏰ Через 10 минут — {title}!\n"
            f"Готовьтесь и заходите вовремя."
            f"{link_line}"
        )


async def send_reminder(app, meeting: dict, is_start: bool):
    # Для ежедневных встреч — только пн-пт, пропускаем сб-вс
    if meeting["type"] == "type_daily":
        tz = ZoneInfo(TIMEZONE)
        today = datetime.now(tz).weekday()  # 0=пн, 5=сб, 6=вс
        if today >= 5:
            logger.info(f"Выходной день, пропускаем: {meeting['title']}")
            return

    data = load_data()
    group_id = data.get("group_chat_id")
    if not group_id:
        logger.warning("Группа не привязана, напоминание не отправлено")
        return

    text = build_reminder_message(meeting, is_start)
    try:
        await app.bot.send_message(chat_id=group_id, text=text)
        logger.info(f"Напоминание отправлено: {meeting['title']} is_start={is_start}")

        # Если встреча одноразовая и это уже финальное напоминание — деактивируем
        if is_start and meeting["type"] == "type_once":
            data = load_data()
            for m in data["meetings"]:
                if m["id"] == meeting["id"]:
                    m["active"] = False
            save_data(data)
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")


def seconds_until(target_time: time, tz: ZoneInfo) -> float:
    """Сколько секунд до следующего момента времени"""
    now = datetime.now(tz)
    target_dt = now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
    if target_dt <= now:
        # уже прошло сегодня — переносим на завтра
        from datetime import timedelta
        target_dt += timedelta(days=1)
    return (target_dt - now).total_seconds()


async def schedule_all_meetings(app):
    """Перезапускает все задачи планировщика"""
    tz = ZoneInfo(TIMEZONE)

    # Отменяем старые задачи
    jobs = app.job_queue.jobs()
    for job in jobs:
        if job.name.startswith("meeting_"):
            job.schedule_removal()

    data = load_data()
    for meeting in data.get("meetings", []):
        if not meeting.get("active", True):
            continue

        try:
            meet_time = datetime.strptime(meeting["time"], "%H:%M").time()
        except ValueError:
            continue

        # Время напоминания = за 10 минут
        from datetime import timedelta
        reminder_dt = datetime.now(tz).replace(
            hour=meet_time.hour, minute=meet_time.minute, second=0, microsecond=0
        ) - timedelta(minutes=10)
        reminder_time = reminder_dt.time()

        # Задача "за 10 минут"
        delay_remind = seconds_until(reminder_time, tz)
        interval = 86400 if meeting["type"] == "type_daily" else None  # раз в сутки или один раз

        mid = meeting["id"]

        if interval:
            app.job_queue.run_repeating(
                lambda ctx, m=meeting: asyncio.create_task(send_reminder(ctx.application, m, False)),
                interval=interval,
                first=delay_remind,
                name=f"meeting_{mid}_remind"
            )
            app.job_queue.run_repeating(
                lambda ctx, m=meeting: asyncio.create_task(send_reminder(ctx.application, m, True)),
                interval=interval,
                first=seconds_until(meet_time, tz),
                name=f"meeting_{mid}_start"
            )
        else:
            app.job_queue.run_once(
                lambda ctx, m=meeting: asyncio.create_task(send_reminder(ctx.application, m, False)),
                when=delay_remind,
                name=f"meeting_{mid}_remind"
            )
            app.job_queue.run_once(
                lambda ctx, m=meeting: asyncio.create_task(send_reminder(ctx.application, m, True)),
                when=seconds_until(meet_time, tz),
                name=f"meeting_{mid}_start"
            )

        logger.info(f"Запланировано: {meeting['title']} в {meeting['time']}, тип={meeting['type']}")


async def on_startup(app):
    await schedule_all_meetings(app)
    logger.info("Бот запущен, все встречи запланированы")


# ══════════════════════════════════════════════
#  НЕИЗВЕСТНЫЕ СООБЩЕНИЯ
# ══════════════════════════════════════════════

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("Напиши /start чтобы открыть меню.")


# ══════════════════════════════════════════════
#  СБОРКА И ЗАПУСК
# ══════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(delete_meeting_handler, pattern=r"^del_\d+$"),
                CallbackQueryHandler(main_menu_handler),
            ],
            ASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
            ASK_TYPE: [CallbackQueryHandler(ask_type, pattern=r"^type_")],
            ASK_WHO: [CallbackQueryHandler(ask_who, pattern=r"^who_")],
            ASK_USERNAMES: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_usernames)],
            ASK_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_link)],
            ASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_title)],
            CONFIRM: [CallbackQueryHandler(confirm_save)],
            ADMIN_MENU: [CallbackQueryHandler(admin_menu_handler)],
            ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin)],
            REMOVE_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_admin)],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("register", register_group))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    logger.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
