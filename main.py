import asyncio
import os
import logging
import random
import json
import io
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'
ADMIN_IDS = [1997428703] # ВСТАВЬ СВОЙ ID

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
users = {}

# --- КУРС БИТКОИНА (REAL TIME) ---
async def get_btc_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return data['bitcoin']['usd']
    except:
        return 40000 # Резервная цена, если API недоступно

# --- DB & DRIVE ---
def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

def load_data():
    global users
    service = get_drive_service()
    if not service: return
    try:
        request = service.files().get_media(fileId=DRIVE_FILE_ID)
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8').strip()
        if content:
            users = json.loads(content)
            users = {int(k): v for k, v in users.items()}
    except Exception as e: logging.error(f"DB Load Error: {e}")

def save_data():
    service = get_drive_service()
    if not service: return
    try:
        with open("db.json", "w", encoding="utf-8") as f: json.dump(users, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e: logging.error(f"DB Save Error: {e}")

# --- UTILS ---
def format_num(num):
    num = float(num)
    if num < 1000: return str(int(num))
    if num < 1_000_000: return f"{num/1000:.1f}к"
    if num < 1_000_000_000: return f"{num/1_000_000:.1f}кк"
    return f"{num/1_000_000_000:.1f}ккк"

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё"]: return int(balance)
    m = {"к": 1000, "кк": 1000000, "ккк": 1000000000}
    for k, v in m.items():
        if text.endswith(k):
            try: return int(float(text.replace(k, "")) * v)
            except: return None
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 10000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, 
            "shovel": 0, "detector": 0, "last_work": 0, "last_bonus": 0
        }
        save_data()
    return users[uid]

async def add_xp_logic(message: Message, u, amount):
    u['xp'] += amount
    needed = u['lvl'] * 4
    if u['xp'] >= needed:
        u['lvl'] += 1; u['xp'] = 0
        await message.answer(f"🆙 <b>УРОВЕНЬ ПОВЫШЕН!</b> Теперь у вас {u['lvl']} лвл!")
    save_data()

# --- COMMANDS ---

@dp.message(F.text.lower().in_({"профиль", "стата"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id, message.from_user.first_name)
    needed = u['lvl'] * 4
    text = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"➖➖➖➖➖➖\n"
        f"⭐ Уровень: <b>{u['lvl']}</b>\n"
        f"📈 Опыт: <b>[{u['xp']}/{needed}] XP</b>\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(text)

@dp.message(F.text.lower().startswith("рул"))
async def cmd_roulette(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    try:
        amt = parse_amount(args[1], u['balance'])
        col = args[2].lower()
        if amt is None or amt <= 0 or amt > u['balance']: raise ValueError
    except: return await message.answer("❌ Ставка не верна")

    u['balance'] -= amt
    res_num = random.randint(0, 36)
    win_col = "зеленый" if res_num == 0 else "красный" if res_num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный"
    
    win_amt = 0
    if (col.startswith("чер") and win_col == "черный") or (col.startswith("кра") and win_col == "красный"): win_amt = amt * 2
    elif col.startswith("зел") and win_col == "зеленый": win_amt = amt * 14

    u['balance'] += win_amt
    xp_msg = ""
    if random.random() < 0.50: # 50% Шанс на опыт
        await add_xp_logic(message, u, 1); xp_msg = "\n📈 <b>+1 XP</b>"
    
    status = f"🎉 ВЫИГРЫШ: {format_num(win_amt)} $" if win_amt > 0 else "😔 ПРОИГРЫШ"
    await message.answer(f"🎰 {status}\n📈 Выпало: {res_num} ({win_col})\n💰 Баланс: {format_num(u['balance'])}{xp_msg}")

@dp.message(F.text.lower().startswith("краш"))
async def cmd_crash(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    try:
        amt = parse_amount(args[1], u['balance'])
        mult = float(args[2].replace(",", "."))
        if amt is None or amt <= 0 or amt > u['balance'] or mult < 1.01: raise ValueError
    except: return await message.answer("❌ Ставка не верна")

    u['balance'] -= amt
    crash_point = round(random.uniform(1.0, 4.0), 2)
    xp_msg = ""
    if mult <= crash_point:
        win = int(amt * mult)
        u['balance'] += win
        res = f"🎉 Выигрыш! (x{mult})"
    else:
        win = 0; res = "😔 Крашнулось!"

    if random.random() < 0.50:
        await add_xp_logic(message, u, 1); xp_msg = "\n📈 <b>+1 XP</b>"

    await message.answer(f"🚀 {res}\n📈 Точка: {crash_point}x\n💸 Выигрыш: {format_num(win)} $\n💰 Баланс: {format_num(u['balance'])}{xp_msg}")

@dp.message(F.text.lower() == "работа")
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    now = datetime.now().timestamp()
    if now - u.get('last_work', 0) < 600: return await message.answer("⏳ Отдых еще 10 минут!")
    if u['shovel'] <= 0 or u['detector'] <= 0: return await message.answer("⚒ Нет инструментов! Купи в <b>магазин</b>")

    u['shovel'] -= 1; u['detector'] -= 1; u['last_work'] = now
    
    # 10% ШАНС НА 1 BTC
    btc_find = 0
    if random.random() < 0.10:
        btc_find = 1.0
        u['btc'] += 1.0
    
    money = random.randint(5000, 20000)
    u['balance'] += money
    
    msg = f"⛏ Ты поработал!\n💰 Нашел: <b>{format_num(money)} $</b>"
    if btc_find > 0: msg += f"\n💎 <b>НЕВЕРОЯТНО! Ты выкопал {btc_find} BTC!</b>"
    
    # 30% Шанс на 1-4 EXP
    if random.random() < 0.30:
        xp = random.randint(1, 4)
        await add_xp_logic(message, u, xp)
        msg += f"\n📈 Опыт: <b>+{xp} XP</b>"
    
    save_data()
    await message.answer(msg)

@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    u = get_user(message.from_user.id)
    now = datetime.now().timestamp()
    if now - u.get('last_bonus', 0) < 3600:
        rem = int(3600 - (now - u['last_bonus']))
        return await message.answer(f"⏳ Бонус через {rem // 60} мин.")
    
    reward = 50000 + (u['lvl'] - 1) * 25000
    u['balance'] += reward; u['last_bonus'] = now; save_data()
    await message.answer(f"🎁 Бонус получен: <b>{format_num(reward)} $</b>")

@dp.message(F.text.lower() == "рынок")
async def cmd_market(message: Message):
    price = await get_btc_price()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Продать 0.1 BTC за {format_num(price*0.1)} $", callback_data="sell_0.1")],
        [InlineKeyboardButton(text="Продать ВСЕ Биткоины", callback_data="sell_all")]
    ])
    await message.answer(f"📊 <b>РЫНОК КРИПТОВАЛЮТ</b>\n\nКурс BTC: <b>{format_num(price)} $</b>\nВаши биткоины: <b>{users[message.from_user.id]['btc']:.6f}</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("sell_"))
async def sell_callback(call: CallbackQuery):
    u = get_user(call.from_user.id)
    price = await get_btc_price()
    mode = call.data.split("_")[1]
    
    amt = 0.1 if mode == "0.1" else u['btc']
    if u['btc'] < amt or amt <= 0: return await call.answer("Недостаточно BTC!", show_alert=True)
    
    gain = int(amt * price)
    u['btc'] -= amt; u['balance'] += gain; save_data()
    await call.message.edit_text(f"✅ Продано {amt} BTC за <b>{format_num(gain)} $</b>")

@dp.message(F.text.lower() == "магазин")
async def cmd_shop(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Лопата (50к)", callback_data="buy_shovel")],
        [InlineKeyboardButton(text="Детектор (100к)", callback_data="buy_detector")]
    ])
    await message.answer("🏪 <b>МАГАЗИН ИНСТРУМЕНТОВ</b>\n(Хватает на 5 раз)", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def buy(call: CallbackQuery):
    u = get_user(call.from_user.id); item = call.data.split("_")[1]
    price = 50000 if item == "shovel" else 100000
    if u['balance'] < price: return await call.answer("Мало денег!", show_alert=True)
    u['balance'] -= price; u[item] = 5; save_data()
    await call.message.edit_text("✅ Инструмент готов к работе!")

# --- БАНК (СКРЫТ ИЗ ПРОФИЛЯ) ---
@dp.message(F.text.lower() == "банк")
async def cmd_bank_info(message: Message):
    u = get_user(message.from_user.id)
    await message.answer(f"🏦 <b>ВАШ СЧЕТ:</b>\n\nВ банке: <b>{format_num(u['bank'])} $</b>\n\n<code>деп [сумма]</code>\n<code>снять [сумма]</code>")

@dp.message(F.text.lower().startswith("деп"))
async def cmd_dep(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    try:
        amt = parse_amount(args[1], u['balance'])
        if amt > u['balance']: raise ValueError
        u['balance'] -= amt; u['bank'] += amt; save_data()
        await message.answer(f"✅ Внесено {format_num(amt)} $")
    except: await message.answer("Ошибка")

@dp.message(F.text.lower().startswith("снять"))
async def cmd_withdraw(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    try:
        amt = parse_amount(args[1], u['bank'])
        if amt > u['bank']: raise ValueError
        u['bank'] -= amt; u['balance'] += amt; save_data()
        await message.answer(f"✅ Снято {format_num(amt)} $")
    except: await message.answer("Ошибка")

# --- ADMIN ---
@dp.message(F.text.lower().startswith("выдать"))
async def adm_money(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        tid, val = int(message.text.split()[1]), parse_amount(message.text.split()[2], 0)
        get_user(tid)['balance'] += val; save_data()
        await message.answer("✅ Баланс пополнен")
    except: pass

# --- SERVER ---
async def handle_ping(request): return web.Response(text="Bot Active")

async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    load_data()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
