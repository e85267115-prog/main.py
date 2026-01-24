import asyncio
import os
import logging
import random
import json
import io
import aiohttp
import time
from datetime import datetime
from pytz import timezone

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiohttp import web
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN") 
ADMIN_IDS = [1997428703]
PORT = int(os.getenv("PORT", 8080))
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

users = {}
promos = {}

FARM_CONFIG = {
    "low": {"name": "NVIDIA RTX 4060", "price": 150000, "inc": 1.2, "sec_income": 0.1 / 3600},
    "mid": {"name": "NVIDIA RTX 4080", "price": 220000, "inc": 1.2, "sec_income": 0.4 / 3600},
    "high": {"name": "NVIDIA RTX 4090", "price": 350000, "inc": 1.3, "sec_income": 0.7 / 3600}
}

# --- DB & SYNC ---
def sync_load():
    global users, promos
    service = get_drive_service()
    if not service: return
    try:
        request = service.files().get_media(fileId=DRIVE_FILE_ID)
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8').strip()
        if content:
            data = json.loads(content)
            users = {int(k): v for k, v in data.get("users", {}).items()}
            promos = data.get("promos", {})
    except Exception: pass

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        data_to_save = {"users": users, "promos": promos}
        with open("db.json", "w", encoding="utf-8") as f: 
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception: pass

async def save_data(): await asyncio.to_thread(sync_save)

def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

# --- УТИЛИТЫ ---
def format_num(num):
    num = float(num)
    if num < 1000: return str(int(num))
    if num < 1_000_000:
        val = num / 1000
        return f"{int(val) if val == int(val) else round(val, 2)}к"
    if num < 1_000_000_000:
        val = num / 1_000_000
        return f"{int(val) if val == int(val) else round(val, 2)}кк"
    if num < 1_000_000_000_000:
        val = num / 1_000_000_000
        return f"{int(val) if val == int(val) else round(val, 2)}ккк"
    val = num / 1_000_000_000_000
    return f"{int(val) if val == int(val) else round(val, 2)}кккк"

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all"]: return int(balance)
    m = {"к": 1000, "кк": 1000000, "ккк": 1000000000, "кккк": 1000000000000}
    for k, v in sorted(m.items(), key=lambda x: len(x[0]), reverse=True):
        if text.endswith(k):
            try: return int(float(text.replace(k, "")) * v)
            except: return None
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    uid = int(uid)
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 5000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, "used_promos": [],
            "farm_low": 0, "farm_mid": 0, "farm_high": 0, "last_collect": time.time()
        }
        asyncio.create_task(save_data())
    return users[uid]

async def get_btc_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=5) as resp:
                data = await resp.json()
                return data['bitcoin']['usd']
    except: return 98500

# --- ФЕРМА (ИНЛАЙН И СЕКУНДНЫЙ ДОХОД) ---
def calc_income(u):
    now = time.time()
    passed = now - u.get('last_collect', now)
    income = (
        u.get('farm_low', 0) * FARM_CONFIG['low']['sec_income'] +
        u.get('farm_mid', 0) * FARM_CONFIG['mid']['sec_income'] +
        u.get('farm_high', 0) * FARM_CONFIG['high']['sec_income']
    ) * passed
    return round(income, 8)

@dp.message(F.text.lower().in_({"ферма", "фермы"}))
async def cmd_farm_menu(message: Message):
    u = get_user(message.from_user.id)
    pending = calc_income(u)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 Собрать ({pending:.6f} BTC)", callback_data="farm_collect")],
        [InlineKeyboardButton(text="🛒 Купить видеокарты", callback_data="farm_shop")]
    ])
    await message.answer(f"⛏ <b>МАЙНИНГ NVIDIA</b>\n━━━━━━━━━━━━\nВаш текущий доход начисляется каждую секунду!\nНамайнено: <b>{pending:.8f} BTC</b>", reply_markup=kb)

@dp.callback_query(F.data == "farm_collect")
async def farm_collect_callback(call: CallbackQuery):
    u = get_user(call.from_user.id)
    income = calc_income(u)
    if income <= 0: return await call.answer("❌ Дохода пока нет!", show_alert=True)
    u['btc'] += income
    u['last_collect'] = time.time()
    await call.message.edit_text(f"✅ Вы собрали <b>{income:.8f} BTC</b>!\n💰 Ваш баланс BTC: <b>{u['btc']:.8f}</b>")
    await save_data()

@dp.callback_query(F.data == "farm_shop")
async def farm_shop_callback(call: CallbackQuery):
    u = get_user(call.from_user.id)
    
    def get_p(t): return int(FARM_CONFIG[t]['price'] * (FARM_CONFIG[t]['inc'] ** u.get(f'farm_{t}', 0)))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"RTX 4060 ({format_num(get_p('low'))}$)", callback_data="buy_low")],
        [InlineKeyboardButton(text=f"RTX 4080 ({format_num(get_p('mid'))}$)", callback_data="buy_mid")],
        [InlineKeyboardButton(text=f"RTX 4090 ({format_num(get_p('high'))}$)", callback_data="buy_high")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="farm_back")]
    ])
    await call.message.edit_text("🛒 <b>МАГАЗИН ВИДЕОКАРТ</b>\nЛимит: 3 шт. каждой модели.\nВыберите карту для покупки:", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_process(call: CallbackQuery):
    u = get_user(call.from_user.id)
    ftype = call.data.split("_")[1]
    key = f"farm_{ftype}"
    
    if u.get(key, 0) >= 3: return await call.answer("❌ Лимит (3 шт) достигнут!", show_alert=True)
    
    price = int(FARM_CONFIG[ftype]['price'] * (FARM_CONFIG[ftype]['inc'] ** u.get(key, 0)))
    if u['balance'] < price: return await call.answer(f"❌ Нужно {format_num(price)}$", show_alert=True)
    
    # Собираем доход перед покупкой, чтобы сбросить таймер корректно
    u['btc'] += calc_income(u)
    u['balance'] -= price
    u[key] = u.get(key, 0) + 1
    u['last_collect'] = time.time()
    
    await call.answer(f"✅ Куплено: {FARM_CONFIG[ftype]['name']}!")
    await farm_shop_callback(call)
    await save_data()

@dp.callback_query(F.data == "farm_back")
async def farm_back(call: CallbackQuery):
    await cmd_farm_menu(call.message)

# --- ГЕМБЛИНГ (РУЛЕТКА И КРАШ ПО ТВОЕМУ ШАБЛОНУ) ---
@dp.message(F.text.lower().startswith("рул"))
async def cmd_roul(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split(); amt = parse_amount(args[1], u['balance']); col = args[2].lower()
        if amt < 10 or amt > u['balance']: return await message.answer("❌ Ошибка ставки!")
        u['balance'] -= amt; res = random.randint(0, 36)
        color = "зеленый" if res == 0 else "красный" if res in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный"
        parity = "четное" if res % 2 == 0 and res != 0 else "нечетное"
        mul = 14 if col[:3] == "зел" and color == "зеленый" else 2 if col[:3] == color[:3] else 0
        u['balance'] += (amt * mul)
        
        status = f"🎉 Выигрыш: {format_num(amt*mul)}" if mul else "😔 Вы проиграли!"
        await message.answer(f"💸 Ставка: <b>{format_num(amt)}</b>\n{status}\n📈 Выпало: <b>{res} ({color}, {parity})</b>\n💰 Баланс: <b>{format_num(u['balance'])}</b>")
        await save_data()
    except: await message.answer("📝 Рул [сумма] [цвет]")

@dp.message(F.text.lower().startswith("краш"))
async def cmd_crash(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split(); amt = parse_amount(args[1], u['balance']); target = float(args[2].replace(",", "."))
        u['balance'] -= amt; crash = round(random.uniform(1.0, 4.0), 2)
        if target <= crash:
            win = int(amt * target); u['balance'] += win
            txt = f"🎉 Вы выиграли!"
        else: txt = f"😔 Вы проиграли!"
        await message.answer(f"{txt}\n📈 Точка краша: <b>{crash}</b>\n🎯 Множитель: <b>{target}</b>\n💸 Ставка: <b>{format_num(amt)}</b>\n💰 Баланс: <b>{format_num(u['balance'])}</b>")
        await save_data()
    except: pass

# --- ИГРЫ (КОСТИ, МИНЫ, АЛМАЗЫ) ---
@dp.message(F.text.lower().startswith("кости"))
async def cmd_dice(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split(); amt = parse_amount(args[1], u['balance']); choice = args[2].lower()
        u['balance'] -= amt; d1, d2 = random.randint(1,6), random.randint(1,6); total = d1 + d2
        win = int(amt * 2.33) if (choice == "больше" and total > 7) or (choice == "меньше" and total < 7) else int(amt * 5.8) if (choice == "7" and total == 7) else 0
        u['balance'] += win
        await message.answer(f"🎲 Кости: {d1} + {d2} = <b>{total}</b>\n{'✅ Win: ' + format_num(win) if win else '❌ Loss'}\n💰 Баланс: {format_num(u['balance'])}")
    except: pass

@dp.message(F.text.lower().startswith("мины"))
async def cmd_mines(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = parse_amount(message.text.split()[1], u['balance'])
        u['balance'] -= amt
        if random.random() > 0.4:
            win = int(amt * 2); u['balance'] += win
            await message.answer(f"💣 Чисто! Выигрыш: <b>{format_num(win)}</b>")
        else: await message.answer(f"💥 БАБАХ! Ставка {format_num(amt)} сгорела.")
    except: pass

@dp.message(F.text.lower().startswith("алмазы"))
async def cmd_diamonds(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = parse_amount(message.text.split()[1], u['balance'])
        u['balance'] -= amt
        if random.randint(1, 4) == 1:
            win = amt * 4; u['balance'] += win
            await message.answer(f"💎 Нашел! +<b>{format_num(win)}</b>")
        else: await message.answer("🗑 Пусто...")
    except: pass

# --- ТОП ---
@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    sorted_users = sorted(users.items(), key=lambda x: x[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>Топ 10 игроков по балансу:</b>\n\n"
    for i, (uid, data) in enumerate(sorted_users, 1):
        txt += f"{i}) {data.get('name', 'Игрок')} — <b>{format_num(data['balance'])}</b>\n"
    await message.answer(txt)

# --- РЫНОК ---
@dp.message(F.text.lower() == "рынок")
async def cmd_market(message: Message):
    price = await get_btc_price()
    await message.answer(f"📊 <b>КРИПТО-РЫНОК</b>\nBTC: <b>{format_num(price)}$</b>\n\n📝 <code>Продать биткоин [кол-во]</code>")

@dp.message(F.text.lower().startswith("продать биткоин"))
async def cmd_sell_btc(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = float(message.text.split()[2]); price = await get_btc_price()
        if u['btc'] >= amt:
            gain = int(amt * price); u['btc'] -= amt; u['balance'] += gain
            await message.answer(f"✅ Продано! +<b>{format_num(gain)}$</b>")
        else: await message.answer("❌ Мало BTC")
    except: pass

# --- ПРОФИЛЬ ---
@dp.message(F.text.lower().in_({"профиль", "я"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id, message.from_user.first_name)
    await message.answer(f"👤 <b>{u['name']}</b>\n💰 Баланс: {format_num(u['balance'])}\n🪙 BTC: {u['btc']:.6f}\n🆔 <code>{message.from_user.id}</code>")

# --- АДМИН ПАНЕЛЬ ---
@dp.message()
async def admin_handler(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    try:
        if "выдать" in args[0]:
            uid = int(args[1]); val = parse_amount(args[2], 0)
            get_user(uid)['balance'] += val; await message.answer("✅")
        await save_data()
    except: pass

async def main():
    sync_load()
    scheduler.add_job(lambda: asyncio.create_task(save_data()), 'interval', minutes=5)
    scheduler.start()
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app); await runner.setup(); await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.delete_webhook(drop_pending_updates=True); await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
