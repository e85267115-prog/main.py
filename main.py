import asyncio
import os
import logging
import random
import json
import io
import aiohttp
from datetime import datetime
import pytz

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Библиотеки Google
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW"
CREDENTIALS_FILE = 'credentials.json'

CHANNEL_ID = "@nvibee_bet"
CHAT_ID = "@chatvibee_bet"
CHANNEL_URL = "https://t.me/nvibee_bet"
CHAT_URL = "https://t.me/chatvibee_bet"

# ⚠️ ВПИШИ СВОЙ ID СЮДА
ADMIN_IDS = [1997428703] 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

users = {}

# --- РАБОТА С БАЗОЙ ДАННЫХ (GOOGLE DRIVE) ---
def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE):
        logging.error("❌ Файл credentials.json не найден!")
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
            users = {int(k): v for k, v in users.items()}
            logging.info("✅ БД успешно загружена")
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки БД: {e}")

def save_data():
    service = get_drive_service()
    if not service: return
    try:
        with open("temp_db.json", "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("temp_db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения БД: {e}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        elif num < 1_000_000: return f"{num/1000:.2f}к".replace(".00", "")
        elif num < 1_000_000_000: return f"{num/1_000_000:.2f}кк".replace(".00", "")
        elif num < 1_000_000_000_000: return f"{num/1_000_000_000:.2f}ккк".replace(".00", "")
        else: return f"{num/1_000_000_000_000:.2f}кккк".replace(".00", "")
    except: return "0"

def parse_amount(text, balance):
    text = str(text).lower().strip().replace(",", ".")
    if text in ["все", "всё", "all"]: return int(balance)
    mults = {"кккк": 10**12, "ккк": 10**9, "кк": 10**6, "к": 1000}
    for m, v in mults.items():
        if text.endswith(m):
            try: return int(float(text.replace(m, "")) * v)
            except: pass
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 50000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "refs": 0, "banned": False,
            "shovel": 0, "detector": 0, "last_work_time": 0
        }
        save_data()
    return users[uid]

async def check_access(message: Message):
    u = get_user(message.from_user.id, message.from_user.first_name)
    if u.get('banned'):
        await message.answer("🚫 <b>Доступ заблокирован администрацией.</b>")
        return False
    # Тут можно добавить проверку подписки, если нужно
    return True

# --- ОСНОВНЫЕ КОМАНДЫ (БЕЗ СЛЕШЕЙ) ---

@dp.message(F.text.lower().in_({"профиль", "стата", "я"}))
async def cmd_profile(message: Message):
    if not await check_access(message): return
    u = get_user(message.from_user.id)
    text = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🏦 В банке: <b>{format_num(u['bank'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b>\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(text)

@dp.message(F.text.lower() == "банк")
async def cmd_bank_info(message: Message):
    if not await check_access(message): return
    u = get_user(message.from_user.id)
    await message.answer(f"🏦 <b>Ваш счет:</b> {format_num(u['bank'])} $\n\nДля пополнения: <code>деп [сумма]</code>\nДля снятия: <code>снять [сумма]</code>")

@dp.message(F.text.lower().startswith("деп"))
async def cmd_dep(message: Message):
    if not await check_access(message): return
    u = get_user(message.from_user.id)
    try:
        amount = parse_amount(message.text.split()[1], u['balance'])
        if amount > u['balance'] or amount <= 0: raise ValueError
        u['balance'] -= amount
        u['bank'] += amount
        save_data()
        await message.answer(f"✅ Вы положили в банк <b>{format_num(amount)} $</b>")
    except: await message.answer("❌ Ошибка. Пример: <code>деп 100к</code>")

@dp.message(F.text.lower().startswith("снять"))
async def cmd_withdraw(message: Message):
    if not await check_access(message): return
    u = get_user(message.from_user.id)
    try:
        amount = parse_amount(message.text.split()[1], u['bank'])
        if amount > u['bank'] or amount <= 0: raise ValueError
        u['bank'] -= amount
        u['balance'] += amount
        save_data()
        await message.answer(f"✅ Вы сняли из банка <b>{format_num(amount)} $</b>")
    except: await message.answer("❌ Ошибка. Пример: <code>снять 100к</code>")

@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    if not await check_access(message): return
    u = get_user(message.from_user.id)
    try:
        args = message.text.split()
        target_id = int(args[1])
        amount = parse_amount(args[2], u['balance'])
        if amount > u['balance'] or amount <= 0 or target_id not in users: raise ValueError
        u['balance'] -= amount
        users[target_id]['balance'] += amount
        save_data()
        await message.answer(f"✅ Перевод {format_num(amount)} $ игроку {target_id} выполнен!")
    except: await message.answer("❌ Ошибка. Пример: <code>перевести [ID] [сумма]</code>")

# --- ИГРЫ ---

@dp.message(F.text.lower().startswith("рул"))
async def cmd_roulette(message: Message):
    if not await check_access(message): return
    u = get_user(message.from_user.id)
    try:
        args = message.text.split()
        amount = parse_amount(args[1], u['balance'])
        bet_type = args[2].lower()
        if amount > u['balance'] or amount <= 0: raise ValueError
    except: return await message.answer("🎰 <code>рул [сумма] [чер/кра/зел]</code>")

    u['balance'] -= amount
    num = random.randint(0, 36)
    
    if num == 0: color = "зеленый"; res = "green"
    elif num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]: color = "красный"; res = "red"
    else: color = "черный"; res = "black"
    
    parity = "четное" if num % 2 == 0 and num != 0 else "нечетное"
    if num == 0: parity = "зеро"

    win = False
    if bet_type.startswith("чер") and res == "black": win = True
    elif bet_type.startswith("кра") and res == "red": win = True
    elif bet_type.startswith("зел") and res == "green": win = True

    win_sum = 0
    if win:
        mult = 14 if res == "green" else 2
        win_sum = amount * mult
        u['balance'] += win_sum

    save_data()
    
    result_text = (
        f"💸 Ставка: {format_num(amount)}\n"
        f"{'🎉 Выигрыш' if win else '😔 Проигрыш'}: {format_num(win_sum)}\n"
        f"📈 Выпало: {num} ({color}, {parity})\n"
        f"💰 Баланс: {format_num(u['balance'])}"
    )
    await message.answer(result_text)

@dp.message(F.text.lower().startswith("краш"))
async def cmd_crash(message: Message):
    if not await check_access(message): return
    u = get_user(message.from_user.id)
    try:
        args = message.text.split()
        amount = parse_amount(args[1], u['balance'])
        target_m = float(args[2].replace(",", "."))
        if amount > u['balance'] or amount <= 0 or target_m < 1.01: raise ValueError
    except: return await message.answer("🚀 <code>краш [сумма] [множитель]</code>")

    u['balance'] -= amount
    crash_point = round(random.uniform(1.0, 5.0), 2) # Упрощенный шанс
    
    win = target_m <= crash_point
    if win:
        win_sum = int(amount * target_m)
        u['balance'] += win_sum
        header = "🎉 Вы выиграли!"
    else:
        header = "😔 Вы проиграли!"

    save_data()
    
    text = (
        f"{header}\n"
        f"📈 Точка краша: {crash_point}\n"
        f"🎯 Множитель: {target_m:.2f}\n"
        f"💸 Ставка: {format_num(amount)}\n"
        f"💰 Баланс: {format_num(u['balance'])}"
    )
    await message.answer(text)

# --- МАГАЗИН И РАБОТА ---

@dp.message(F.text.lower() == "магазин")
async def cmd_shop(message: Message):
    if not await check_access(message): return
    await message.answer("🏪 <b>МАГАЗИН:</b>\n\n1. Лопата — 50к\n2. Детектор — 150к\n\nЧтобы купить, используйте кнопки (добавь логику кнопок по желанию).")

@dp.message(F.text.lower() == "работа")
async def cmd_work(message: Message):
    if not await check_access(message): return
    u = get_user(message.from_user.id)
    # Упрощенная логика работы
    reward = random.randint(5000, 15000)
    u['balance'] += reward
    save_data()
    await message.answer(f"🛠 Вы поработали и получили <b>{format_num(reward)} $</b>")

# --- АДМИН КОМАНДЫ ---

@dp.message(F.text.lower().startswith("бан"))
async def admin_ban(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        tid = int(message.text.split()[1])
        users[tid]['banned'] = True
        save_data()
        logging.info(f"ЛОГ: Админ {message.from_user.id} забанил {tid}")
        await message.answer(f"🚫 Пользователь {tid} забанен.")
    except: await message.answer("бан [ID]")

@dp.message(F.text.lower().startswith("разбан"))
async def admin_unban(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        tid = int(message.text.split()[1])
        users[tid]['banned'] = False
        save_data()
        await message.answer(f"✅ Пользователь {tid} разбанен.")
    except: pass

@dp.message(F.text.lower().startswith("выдатьбит"))
async def admin_give_btc(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        tid, val = int(args[1]), float(args[2])
        users[tid]['btc'] += val
        save_data()
        logging.info(f"ЛОГ: Админ выдал {val} BTC игроку {tid}")
        await message.answer(f"🪙 Выдано {val} BTC игроку {tid}")
    except: await message.answer("выдатьбит [ID] [количество]")

@dp.message(F.text.lower().startswith("выдать"))
async def admin_give_money(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        tid = int(args[1])
        val = parse_amount(args[2], 0)
        users[tid]['balance'] += val
        save_data()
        logging.info(f"ЛОГ: Админ выдал {val} $ игроку {tid}")
        await message.answer(f"💰 Выдано {format_num(val)} $ игроку {tid}")
    except: await message.answer("выдать [ID] [сумма]")

@dp.message(F.text.lower().startswith("забрать"))
async def admin_take_money(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        tid = int(args[1])
        val = parse_amount(args[2], users[tid]['balance'])
        users[tid]['balance'] -= val
        save_data()
        await message.answer(f"💸 Забрано {format_num(val)} $ у игрока {tid}")
    except: pass

# --- ЗАПУСК СЕРВЕРА ---

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def main():
    # Запуск веб-сервера для Render сразу
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    load_data()
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())