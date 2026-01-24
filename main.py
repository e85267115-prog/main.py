import asyncio
import os
import logging
import random
import json
import io
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

# Библиотеки Google
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))

# Твой ID из сообщения
DRIVE_FILE_ID = "1UnFcRsQH59-j2dv_6KSR0lNkSFvERoBfphOtqO2amy0"
CREDENTIALS_FILE = 'credentials.json'

CHANNEL_ID = "@nvibee_bet"
CHAT_ID = "@chatvibee_bet"
CHANNEL_URL = "https://t.me/nvibee_bet"
CHAT_URL = "https://t.me/chatvibee_bet"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

users = {}
bot_username = ""

# --- GOOGLE DRIVE LOGIC ---
def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE):
        logging.error(f"Файл {CREDENTIALS_FILE} не найден! Убедись, что добавил его в Secret Files на Render.")
        return None
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)

def load_data():
    global users
    service = get_drive_service()
    if not service: return
    try:
        request = service.files().get_media(fileId=DRIVE_FILE_ID)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        content = fh.read().decode('utf-8').strip()
        if content:
            users = json.loads(content)
            # Конвертируем ID из строк в числа
            users = {int(k): v for k, v in users.items()}
            logging.info("✅ БД загружена с Google Drive")
        else:
            users = {}
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки с Drive: {e}")
        users = {}

def save_data():
    service = get_drive_service()
    if not service: return
    try:
        with open("temp_db.json", "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=4)
        
        media = MediaFileUpload("temp_db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
        logging.info("☁️ БД сохранена на Google Drive")
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения: {e}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        elif num < 1_000_000: return f"{num/1000:.1f}к".replace(".0", "")
        elif num < 1_000_000_000: return f"{num/1_000_000:.1f}кк".replace(".0", "")
        return f"{num/1_000_000_000:.1f}ккк".replace(".0", "")
    except: return "0"

def get_user(uid, name="Игрок"):
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 50000, "bank": 0, "btc": 0.0, "tools": 5,
            "lvl": 1, "xp": 0, "refs": 0, "reg": datetime.now().strftime("%d.%m.%Y")
        }
        save_data()
    return users[uid]

async def check_subscription(user_id):
    try:
        m1 = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        m2 = await bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
        valid = ['creator', 'administrator', 'member']
        return m1.status in valid and m2.status in valid
    except: return False

def sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Канал", url=CHANNEL_URL), InlineKeyboardButton(text="💬 Чат", url=CHAT_URL)],
        [InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub")]
    ])

# --- ЛОГИКА ПРОФИЛЯ ---
async def show_profile(message_or_call, user_id):
    u = get_user(user_id)
    text = (
        f"👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"⭐ Уровень: <b>{u['lvl']}</b>\n"
        f"✨ XP: <code>{u['xp']}/{u['lvl']*5}</code>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🏦 Банк: <b>{format_num(u.get('bank', 0))} $</b>\n"
        f"🪙 Bitcoin: <b>{u['btc']:.6f} BTC</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👥 Рефералов: <b>{u['refs']}</b>"
    )
    if isinstance(message_or_call, Message):
        await message_or_call.answer(text)
    else:
        await message_or_call.message.answer(text)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    
    # ПРОВЕРКА: Если уже подписан — сразу в профиль
    if await check_subscription(user_id):
        return await show_profile(message, user_id)

    u = get_user(user_id, message.from_user.first_name)
    
    # Реферальная система (только для новых)
    if command.args and user_id not in users:
        try:
            ref_id = int(command.args)
            if ref_id != user_id and ref_id in users:
                users[ref_id]['balance'] += 250000
                users[ref_id]['refs'] += 1
                save_data()
                await bot.send_message(ref_id, "🤝 По вашей ссылке пришел игрок! +250к $")
        except: pass

    caption = f"👋 <b>Привет, {u['name']}!</b>\n🎰 Чтобы начать игру, подпишись на наши ресурсы:"
    await message.answer(caption, reply_markup=sub_keyboard())

@dp.callback_query(F.data == "check_sub")
async def callback_check(call: CallbackQuery):
    user_id = call.from_user.id
    if await check_subscription(user_id):
        await call.message.delete()
        # СРАЗУ ОТКРЫВАЕМ ПРОФИЛЬ
        await show_profile(call, user_id)
    else:
        await call.answer("❌ Подписка не найдена!", show_alert=True)

@dp.message(F.text.lower().in_({"я", "профиль"}))
async def msg_profile(message: Message):
    if not await check_subscription(message.from_user.id):
        return await message.answer("🔒 Подпишись!", reply_markup=sub_keyboard())
    await show_profile(message, message.from_user.id)

@dp.message(Command("help"))
@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    text = (
        "🎮 <b>ПОМОЩЬ:</b>\n\n"
        "💰 <code>/work</code> — Работать\n"
        "🎁 <code>/bonus</code> — Бонус\n"
        "🎰 <code>/casino [сумма]</code> — Казино\n"
        "📈 <code>/crash [сумма]</code> — Краш\n"
        "👤 <b>Профиль</b> — Твои статы"
    )
    await message.answer(text)

# --- SERVER ---
async def handle_ping(request): return web.Response(text="Bot Alive")

async def main():
    global bot_username
    load_data() # Загрузка БД при старте
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
