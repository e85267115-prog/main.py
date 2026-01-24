import asyncio
import os
import logging
import random
import json
import io
import aiohttp
from datetime import datetime, timedelta
import pytz

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Библиотеки Google
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))
# ТВОЙ ID ФАЙЛА (оставляем тот же)
DRIVE_FILE_ID = "1UnFcRsQH59-j2dv_6KSR0lNkSFvERoBfphOtqO2amy0" 
CREDENTIALS_FILE = 'credentials.json'

CHANNEL_ID = "@nvibee_bet"
CHAT_ID = "@chatvibee_bet"
CHANNEL_URL = "https://t.me/nvibee_bet"
CHAT_URL = "https://t.me/chatvibee_bet"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

users = {}

# --- GOOGLE DRIVE & DB ---
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
            logging.info("✅ БД загружена")
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки БД: {e}")
        users = {}

def save_data():
    service = get_drive_service()
    if not service: return
    try:
        with open("temp_db.json", "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("temp_db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения: {e}")

# --- UTIL FUNCTIONS ---
async def get_btc_price_usd():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                return float(data['price'])
        except:
            return 95000.0

def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        elif num < 1_000_000:
            val = num / 1000
            return f"{val:.1f}к".replace(".0", "")
        elif num < 1_000_000_000:
            val = num / 1_000_000
            return f"{val:.1f}кк".replace(".0", "")
        return f"{val/1_000_000_000:.1f}ккк".replace(".0", "")
    except: return "0"

def parse_amount(text, balance):
    if not text: return None
    text = str(text).lower().strip().replace(",", ".")
    if text in ["все", "всё", "all", "ва-банк"]: return int(balance)
    mults = {"кк": 10**6, "к": 1000, "m": 10**6, "k": 1000}
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
            "lvl": 1, "xp": 0, "refs": 0,
            "reg": datetime.now().strftime("%d.%m.%Y"),
            "shovel": 0, "detector": 0, "last_work_time": 0
        }
        save_data()
    # Проверка целостности полей
    required = ["shovel", "detector", "last_work_time", "bank", "btc", "xp", "lvl"]
    for field in required:
        if field not in users[uid]: users[uid][field] = 0
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

# --- БАНК ТАЙМЕР ---
async def bank_interest_task():
    logging.info("🕒 Выплата процентов...")
    for uid in users:
        if users[uid].get('bank', 0) > 0:
            users[uid]['bank'] += int(users[uid]['bank'] * 0.10)
    save_data()

# --- HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    if await check_subscription(user_id):
        return await cmd_profile(message)

    u = get_user(user_id, message.from_user.first_name)
    if command.args and user_id not in users:
        try:
            ref_id = int(command.args)
            if ref_id != user_id and ref_id in users:
                users[ref_id]['balance'] += 250000
                users[ref_id]['refs'] += 1
                save_data()
                await bot.send_message(ref_id, "👤 Новый реферал! +250к $")
        except: pass

    cap = f"👋 <b>Привет, {u['name']}!</b>\n👇 Подпишись, чтобы начать:"
    try: await message.answer_photo(FSInputFile("start_img.jpg"), caption=cap, reply_markup=sub_keyboard())
    except: await message.answer(cap, reply_markup=sub_keyboard())

@dp.callback_query(F.data == "check_sub")
async def callback_check_sub(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await cmd_profile(call.message)
    else:
        await call.answer("❌ Подпишись на каналы!", show_alert=True)

# --- ПРОФИЛЬ (БЕЗ ИНСТРУМЕНТОВ) ---
@dp.message(F.text.lower().in_({"я", "профиль"}))
async def cmd_profile(message: Message):
    if not await check_subscription(message.from_user.id):
        return await message.answer("🔒 Подпишись!", reply_markup=sub_keyboard())
    
    u = get_user(message.from_user.id)
    text = (
        f"👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*5} XP)\n"
        f"💰 На руках: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Bitcoin: <b>{u['btc']:.6f} BTC</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👥 Рефералов: <b>{u['refs']}</b>\n"
        f"🔗 Ссылка: <code>/ref</code>"
    )
    await message.answer(text)

# --- БАНК ---
@dp.message(Command("bank"))
async def cmd_bank_menu(message: Message):
    u = get_user(message.from_user.id)
    text = (
        f"🏦 <b>VIBE BANK</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"💵 Счет: <b>{format_num(u['bank'])} $</b>\n"
        f"📈 Ставка: <b>10%</b> (в 00:00 МСК)\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📥 Пополнить: <code>/dep [сумма]</code>\n"
        f"📤 Снять: <code>/with [сумма]</code>\n"
        f"💸 Перевод: <code>/pay [id] [сумма]</code>"
    )
    await message.answer(text)

@dp.message(Command("dep"))
async def cmd_deposit(message: Message, command: CommandObject):
    u = get_user(message.from_user.id)
    amount = parse_amount(command.args, u['balance'])
    if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
    if amount > u['balance']: return await message.answer("❌ Недостаточно средств!")
    u['balance'] -= amount
    u['bank'] += amount
    save_data()
    await message.answer(f"🏦 Депозит: <b>+{format_num(amount)} $</b>")

@dp.message(Command("with"))
async def cmd_withdraw(message: Message, command: CommandObject):
    u = get_user(message.from_user.id)
    amount = parse_amount(command.args, u['bank'])
    if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
    if amount > u['bank']: return await message.answer("❌ Недостаточно в банке!")
    u['bank'] -= amount
    u['balance'] += amount
    save_data()
    await message.answer(f"🏦 Снято: <b>{format_num(amount)} $</b>")

@dp.message(Command("pay"))
async def cmd_pay(message: Message, command: CommandObject):
    u_sender = get_user(message.from_user.id)
    try:
        args = command.args.split()
        target_id = int(args[0])
        amount = parse_amount(args[1], u_sender['balance'])
    except: return await message.answer("❌ Формат: <code>/pay [ID] [сумма]</code>")
    
    if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
    if amount > u_sender['balance']: return await message.answer("❌ Мало денег!")
    if target_id not in users: return await message.answer("❌ Игрок не найден!")
    
    users[target_id]['balance'] += amount
    u_sender['balance'] -= amount
    save_data()
    await message.answer(f"💸 Перевод <b>{format_num(amount)} $</b> игроку {users[target_id]['name']}!")
    try: await bot.send_message(target_id, f"💸 Перевод: <b>+{format_num(amount)} $</b> от {u_sender['name']}")
    except: pass

# --- МАГАЗИН (ВСЯ ИНФА ОБ ИНСТРУМЕНТАХ ТУТ) ---
@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    u = get_user(message.from_user.id)
    
    # Считаем количество инструментов (0/2, 1/2, 2/2)
    count = 0
    if u['shovel'] > 0: count += 1
    if u['detector'] > 0: count += 1
    
    inv_text = f"У вас: Нету инструментов 0/2" if count == 0 else f"У вас есть инструменты {count}/2"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏ Лопата (100к)", callback_data="buy_shovel")],
        [InlineKeyboardButton(text="📟 Металлоискатель (150к)", callback_data="buy_detector")]
    ])
    
    text = (
        f"🏪 <b>МАГАЗИН ИНСТРУМЕНТОВ</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🎒 <b>{inv_text}</b>\n"
        f"⛏ Лопата: {u['shovel']}/5 ходок\n"
        f"📟 Детектор: {u['detector']}/5 ходок\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👇 Покупайте, чтобы работать!"
    )
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_tool_callback(call: CallbackQuery):
    u = get_user(call.from_user.id)
    item = call.data.split("_")[1]
    price = 100000 if item == "shovel" else 150000
    name = "Лопата" if item == "shovel" else "Металлоискатель"
    
    if u['balance'] < price:
        return await call.answer("❌ Недостаточно денег!", show_alert=True)
    if u[item] > 0:
        return await call.answer(f"❌ {name} уже куплена! (Прочность: {u[item]}/5)", show_alert=True)
    
    u['balance'] -= price
    u[item] = 5
    save_data()
    await cmd_shop(call.message) # Обновляем сообщение магазина
    await call.answer("✅ Куплено!")

# --- РАБОТА (С ОПИСАНИЕМ) ---
@dp.message(Command("work"))
async def cmd_work(message: Message):
    if not await check_subscription(message.from_user.id): return
    u = get_user(message.from_user.id)
    
    # Кулдаун
    now_ts = datetime.now().timestamp()
    if now_ts - u['last_work_time'] < 7200: 
        rem = int(7200 - (now_ts - u['last_work_time']))
        h, m = divmod(divmod(rem, 60)[0], 60)
        return await message.answer(f"⏳ Перерыв! Отдых еще: <b>{h}ч {m}м</b>")

    if u['shovel'] <= 0 or u['detector'] <= 0:
        return await message.answer("🛠 <b>Инструментов нет или они сломаны!</b>\nЗайдите в /shop")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌲 Сектор 1", callback_data="dig_1"),
         InlineKeyboardButton(text="🌲 Сектор 2", callback_data="dig_2"),
         InlineKeyboardButton(text="🌲 Сектор 3", callback_data="dig_3")]
    ])
    
    text = (
        "🗺 <b>КЛАДОИСКАТЕЛЬ</b>\n"
        "Вы отправляетесь на поиски сокровищ!\n\n"
        "📚 <b>Правила:</b>\n"
        "🔸 Шанс найти Bitcoin: <b>10%</b>\n"
        "🔸 Шанс найти Деньги: <b>60%</b>\n"
        "🔸 Шанс неудачи: <b>30%</b>\n"
        "⚠️ <i>Каждая ходка отнимает 1 ед. прочности у инструментов.</i>\n\n"
        "👇 <b>Выберите сектор для раскопок:</b>"
    )
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("dig_"))
async def work_callback(call: CallbackQuery):
    u = get_user(call.from_user.id)
    if u['shovel'] <= 0 or u['detector'] <= 0:
        await call.message.delete()
        return await call.answer("🛠 Инструменты сломались!", show_alert=True)

    u['shovel'] -= 1
    u['detector'] -= 1
    
    # Если сломались
    if u['shovel'] == 0 or u['detector'] == 0:
        u['last_work_time'] = datetime.now().timestamp()
        broken_msg = "\n🧨 <b>Инструменты сломались!</b>\nКупите новые в /shop (кд 2 часа)."
    else:
        broken_msg = f"\n🔧 Остаток прочности: {u['shovel']}/5"

    rand = random.randint(1, 100)
    if rand <= 10: 
        btc_price = await get_btc_price_usd()
        found_btc = random.uniform(0.0001, 0.0005) 
        val_usd = int(found_btc * btc_price)
        u['balance'] += val_usd
        u['btc'] += found_btc
        res = f"💎 <b>ДЖЕКПОТ!</b> Найден BTC: <b>{found_btc:.6f}</b>\n💵 Продано на бирже за: <b>{format_num(val_usd)} $</b>"
    elif rand <= 70:
        money = random.randint(20000, 80000)
        u['balance'] += money
        res = f"⛏ Успех! Выкопано: <b>{format_num(money)} $</b>"
    else:
        res = "🗑 Вы нашли только старый ботинок... Пусто."

    save_data()
    await call.message.edit_text(res + broken_msg)

# --- РУЛЕТКА ---
@dp.message(Command("рулетка", "рул", "roulette"))
async def cmd_roulette(message: Message, command: CommandObject):
    u = get_user(message.from_user.id)
    try:
        args = command.args.split()
        amount = parse_amount(args[0], u['balance'])
        bet_color = args[1].lower()
    except: return await message.answer("🎰 Формат: <code>/рул [сумма] [кра/чер/зел]</code>")
    
    if 'кра' in bet_color: target = 'red'
    elif 'чер' in bet_color: target = 'black'
    elif 'зел' in bet_color: target = 'green'
    else: return await message.answer("❌ Цвета: кра, чер, зел")
    
    if not amount or amount <= 0: return await message.answer("❌ Неверная сумма!")
    if amount > u['balance']: return await message.answer("❌ Недостаточно средств!")
    
    u['balance'] -= amount
    num = random.randint(0, 36)
    color = 'green' if num == 0 else ('black' if num % 2 == 0 else 'red')
    
    emojis = {'red': '🔴', 'black': '⚫', 'green': '🟢'}
    if target == color:
        win = amount * (14 if target == 'green' else 2)
        u['balance'] += win
        msg = f"✅ <b>ПОБЕДА!</b> Выпало: {num} {emojis[color]}\nВыигрыш: <b>{format_num(win)} $</b>"
    else:
        msg = f"❌ <b>Проиграл.</b> Выпало: {num} {emojis[color]}"
    
    save_data()
    await message.answer(msg)

@dp.message(Command("help"))
@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    text = (
        "🎮 <b>СПИСОК КОМАНД:</b>\n\n"
        "💼 <b>РАБОТА:</b>\n"
        "• <code>/work</code> — Искать клад (нужны инструменты)\n"
        "• <code>/shop</code> — Магазин и Инвентарь\n\n"
        "🏦 <b>ФИНАНСЫ:</b>\n"
        "• <code>/bank</code> — Меню банка\n"
        "• <code>/pay [id] [сумма]</code> — Перевод\n\n"
        "🎰 <b>ИГРЫ:</b>\n"
        "• <code>/рул [сумма] [цвет]</code> — Рулетка\n\n"
        "👤 <b>Профиль</b> — Твоя стата"
    )
    await message.answer(text)

# --- SERVER ---
async def handle_ping(request): return web.Response(text="Bot Alive")

async def main():
    load_data()
    msk_tz = pytz.timezone('Europe/Moscow')
    scheduler.add_job(bank_interest_task, 'cron', hour=0, minute=0, timezone=msk_tz)
    scheduler.start()
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
