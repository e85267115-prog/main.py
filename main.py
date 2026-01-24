import asyncio
import os
import logging
import random
import json
import io
import aiohttp
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

REQUIRED_CHANNELS = [
    {"username": "@nvibee_bet", "url": "https://t.me/nvibee_bet", "name": "Канал Vibe Bet"},
    {"username": "@chatvibee_bet", "url": "https://t.me/chatvibee_bet", "name": "Чат Vibe Bet"}
]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()
users = {}

# --- GOOGLE DRIVE & DB ---
def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

def sync_load():
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
            data = json.loads(content)
            users = {int(k): v for k, v in data.items()}
            logging.info("✅ БД Загружена")
    except Exception as e: logging.error(f"DB Error: {e}")

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        with open("db.json", "w", encoding="utf-8") as f: 
            json.dump(users, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e: logging.error(f"Save Error: {e}")

async def save_data():
    await asyncio.to_thread(sync_save)

# --- UTILS ---
def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        if num < 1_000_000: return f"{num/1000:.2f}к"
        if num < 1_000_000_000: return f"{num/1_000_000:.2f}кк"
        if num < 1_000_000_000_000: return f"{num/1_000_000_000:.2f}ккк"
        return f"{num/1_000_000_000_000:.2f}кккк"
    except: return "0"

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all"]: return int(balance)
    m = {"к": 1000, "кк": 1000000, "ккк": 1000000000, "кккк": 1000000000000}
    for k, v in m.items():
        if text.endswith(k):
            try: return int(float(text.replace(k, "")) * v)
            except: return None
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    uid = int(uid)
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 10000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, 
            "shovel": 0, "detector": 0, "last_work": 0
        }
        asyncio.create_task(save_data())
    return users[uid]

async def get_btc_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return data['bitcoin']['usd']
    except: return 95000

# --- БАНК (00:00 MSK) ---
async def bank_interest_job():
    for uid, u in users.items():
        if u.get('bank', 0) > 0:
            u['bank'] += int(u['bank'] * 0.10)
    await save_data()

# --- MIDDLEWARE (БАН И ПОДПИСКА) ---
@dp.message.outer_middleware()
async def check_access(handler, event: Message, data):
    if not event.text: return await handler(event, data)
    uid = event.from_user.id
    u = get_user(uid, event.from_user.first_name)
    
    # ПРОВЕРКА БАНА
    if u.get('banned'):
        await event.answer("🚫 <b>Доступ заблокирован!</b>\nВы были забанены администрацией и больше не можете использовать бота.")
        return 

    # ПРОВЕРКА ПОДПИСКИ (кроме админа и старта)
    if uid not in ADMIN_IDS and not event.text.startswith("/start"):
        for ch in REQUIRED_CHANNELS:
            try:
                m = await bot.get_chat_member(chat_id=ch["username"], user_id=uid)
                if m.status in ["left", "kicked"]:
                    kb = [[InlineKeyboardButton(text=f"👉 {c['name']}", url=c['url'])] for c in REQUIRED_CHANNELS]
                    kb.append([InlineKeyboardButton(text="✅ ПРОВЕРИТЬ", callback_data="check_sub")])
                    return await event.answer("🔒 <b>Для продолжения подпишитесь:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            except: pass
    return await handler(event, data)

# --- ОСНОВНЫЕ КОМАНДЫ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    photo = FSInputFile("start_img.jpg")
    txt = "Добро Пожаловать в Vibe Bet, игровой телеграм бот. Играй, веселись, все это ТУТ!"
    try: await message.answer_photo(photo, caption=txt)
    except: await message.answer(txt)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    await message.answer(
        "📚 <b>СПИСОК КОМАНД:</b>\n\n"
        "👤 <b>Аккаунт:</b>\n"
        "• <code>Профиль</code> (или Я)\n"
        "• <code>Перевести [ID] [сумма]</code>\n\n"
        "⛏️ <b>Заработок:</b>\n"
        "• <code>Работа</code> — Квест кладоискателя\n"
        "• <code>Магазин</code> — Инструменты\n\n"
        "🏦 <b>Финансы:</b>\n"
        "• <code>Банк</code> | <code>Деп</code> | <code>Снять</code>\n"
        "• <code>Рынок</code> | <code>Продать биткоин [кол-во]</code>\n\n"
        "🎰 <b>Игры:</b>\n"
        "• <code>Рул [сумма] [цвет]</code>\n"
        "• <code>Краш [сумма] [кэф]</code>"
    )

@dp.message(F.text.lower().in_({"профиль", "я"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    c = (1 if u['shovel'] > 0 else 0) + (1 if u['detector'] > 0 else 0)
    await message.answer(
        f"👤 <b>ВАШ ПРОФИЛЬ</b>\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*10} XP)\n"
        f"🎒 Инструменты: <b>{c}/2</b>\n"
        f"🆔 Ваш ID: <code>{message.from_user.id}</code>"
    )

# --- РЫНОК ---
@dp.message(F.text.lower() == "рынок")
async def cmd_market(message: Message):
    price = await get_btc_price()
    u = get_user(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💰 Продать BTC", callback_data="sell_btc_info")]])
    await message.answer(
        f"📊 <b>CRYPTO MARKET</b>\nКурс: <b>{format_num(price)} $</b>\n"
        f"Ваш баланс: <b>{u['btc']:.6f} BTC</b>", reply_markup=kb
    )

@dp.callback_query(F.data == "sell_btc_info")
async def btc_info(call: CallbackQuery):
    u = get_user(call.from_user.id)
    await call.message.answer(
        f"💸 <b>ОБМЕННИК</b>\nУ вас есть: <code>{u['btc']:.6f}</code> BTC\n\n"
        f"Чтобы продать, напишите:\n<code>Продать биткоин [кол-во]</code>"
    )
    await call.answer()

@dp.message(F.text.lower().startswith("продать биткоин"))
async def btc_sell_act(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = float(message.text.split()[2].replace(",", "."))
        if amt <= 0 or u['btc'] < amt: raise ValueError
        price = await get_btc_price()
        gain = int(amt * price)
        u['btc'] -= amt
        u['balance'] += gain
        await save_data()
        await message.answer(f"✅ Успешно продано <b>{amt} BTC</b>\n💰 Получено: <b>{format_num(gain)} $</b>")
    except: await message.answer("❌ Ошибка! Неверное количество или недостаточно BTC.")

# --- КВЕСТ КЛАДОИСКАТЕЛЬ ---
@dp.message(F.text.lower() == "работа")
async def work_stage1(message: Message):
    u = get_user(message.from_user.id)
    if u['shovel'] < 1 or u['detector'] < 1:
        return await message.answer("❌ Вам нужны <b>Лопата</b> и <b>Детектор</b>!\nКупите их в магазине.")
    
    now = datetime.now().timestamp()
    if now - u['last_work'] < 600:
        return await message.answer(f"⏳ Вы устали. Отдых еще {int(600-(now-u['last_work']))} сек.")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Заброшенный завод 🏭", callback_data="w_2"),
        InlineKeyboardButton(text="Старый пляж 🏖️", callback_data="w_2")
    ], [InlineKeyboardButton(text="Густой лес 🌲", callback_data="w_2")]])
    await message.answer("🗺️ <b>ЭТАП 1: Поиск места</b>\nГде сегодня будем искать клад?", reply_markup=kb)

@dp.callback_query(F.data == "w_2")
async def work_stage2(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📡 Запустить сканер", callback_data="w_3")]])
    await call.message.edit_text("🔍 <b>ЭТАП 2: Сканирование</b>\nМесто выбрано. Включаем металлоискатель...", reply_markup=kb)

@dp.callback_query(F.data == "w_3")
async def work_stage3(call: CallbackQuery):
    await call.message.edit_text("⏳ <i>Идет поиск сигнала... Пожалуйста, подождите.</i>")
    await asyncio.sleep(3)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⛏️ НАЧАТЬ КОПАТЬ", callback_data="w_fin")]])
    await call.message.edit_text("📍 <b>ЭТАП 3: Раскопки</b>\nЕсть мощный сигнал! Пора пустить лопату в дело.", reply_markup=kb)

@dp.callback_query(F.data == "w_fin")
async def work_fin(call: CallbackQuery):
    u = get_user(call.from_user.id)
    u['last_work'] = datetime.now().timestamp()
    
    chance = min(0.05 + (u['lvl'] * 0.015), 0.35)
    if random.random() < chance:
        win = random.randint(500000, 3000000)
        txt = "💎 <b>НЕВЕРОЯТНО!</b> Вы откопали старинный клад!"
    else:
        win = random.randint(10000, 150000)
        txt = "💰 <b>Успешно.</b> Вы нашли горсть ценных монет."

    u['balance'] += win
    u['xp'] += 3
    if u['xp'] >= u['lvl']*10:
        u['lvl'] += 1; u['xp'] = 0
        txt += f"\n🆙 <b>LEVEL UP! Ваш новый уровень: {u['lvl']}</b>"
    
    await save_data()
    await call.message.edit_text(f"{txt}\n\n💵 Выручка: <b>{format_num(win)} $</b>\n📊 Получено: 3 XP")

# --- МАГАЗИН ---
@dp.message(F.text.lower() == "магазин")
async def cmd_shop(message: Message):
    u = get_user(message.from_user.id)
    c = (1 if u['shovel'] > 0 else 0) + (1 if u['detector'] > 0 else 0)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Лопата (50к)", callback_data="b_sh"), 
         InlineKeyboardButton(text="Детектор (100к)", callback_data="b_dt")]
    ])
    await message.answer(f"🏪 <b>VIBE SHOP</b>\nПредметов: {c}/2\n\nЛопата: {'✅' if u['shovel'] else '❌'}\nДетектор: {'✅' if u['detector'] else '❌'}", reply_markup=kb)

@dp.callback_query(F.data.startswith("b_"))
async def buy(call: CallbackQuery):
    u = get_user(call.from_user.id)
    item = "shovel" if call.data == "b_sh" else "detector"
    price = 50000 if item == "shovel" else 100000
    if u[item] > 0: return await call.answer("У вас уже есть этот предмет!", show_alert=True)
    if u['balance'] < price: return await call.answer("Недостаточно средств!", show_alert=True)
    u['balance'] -= price; u[item] = 1
    await save_data(); await call.answer("Куплено!"); await cmd_shop(call.message)

# --- АДМИН ПАНЕЛЬ ---
@dp.message(F.text.lower().startswith("выдатьбтк"))
async def adm_btc(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        _, tid, amt = message.text.split()
        target = get_user(tid)
        target['btc'] += float(amt.replace(",", "."))
        await save_data(); await message.answer(f"✅ Игроку {tid} выдано {amt} BTC")
    except: await message.answer("⚠️ Ошибка. Пример: <code>выдатьбтк ID 1</code>")

@dp.message(F.text.lower().startswith("выдать"))
async def adm_mon(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        _, tid, amt = message.text.split()
        target = get_user(tid)
        target['balance'] += parse_amount(amt, 0)
        await save_data(); await message.answer(f"✅ Игроку {tid} выдано {amt} $")
    except: await message.answer("⚠️ Ошибка. Пример: <code>выдать ID 100к</code>")

@dp.message(F.text.lower().startswith("бан"))
async def adm_ban(message: Message):
    if message.from_user.id in ADMIN_IDS:
        target_id = message.text.split()[1]
        get_user(target_id)['banned'] = True
        await save_data(); await message.answer(f"🚫 Игрок {target_id} забанен.")

@dp.message(F.text.lower().startswith("разбан"))
async def adm_un(message: Message):
    if message.from_user.id in ADMIN_IDS:
        target_id = message.text.split()[1]
        get_user(target_id)['banned'] = False
        await save_data(); await message.answer(f"✅ Игрок {target_id} разбанен.")

# --- БАНК И ПЕРЕВОДЫ ---
@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split()
        tid, amt = int(args[1]), parse_amount(args[2], u['balance'])
        if tid not in users or amt <= 0 or u['balance'] < amt: raise ValueError
        u['balance'] -= amt; users[tid]['balance'] += amt
        await save_data(); await message.answer(f"✅ Перевод <b>{format_num(amt)}$</b> игроку {tid} выполнен!")
    except: await message.answer("⚠️ Ошибка. Пример: <code>Перевести ID 50к</code>")

@dp.message(F.text.lower().startswith("деп"))
async def cmd_dep(message: Message):
    u = get_user(message.from_user.id)
    amt = parse_amount(message.text.split()[1], u['balance'])
    if amt and 0 < amt <= u['balance']:
        u['balance'] -= amt; u['bank'] += amt
        await message.answer(f"🏦 Депозит: {format_num(amt)}$ принят."); await save_data()

@dp.message(F.text.lower().startswith("снять"))
async def cmd_with(message: Message):
    u = get_user(message.from_user.id)
    amt = parse_amount(message.text.split()[1], u['bank'])
    if amt and 0 < amt <= u['bank']:
        u['bank'] -= amt; u['balance'] += amt
        await message.answer(f"💳 Снято: {format_num(amt)}$"); await save_data()

@dp.message(F.text.lower() == "банк")
async def cmd_bank_view(message: Message):
    u = get_user(message.from_user.id)
    await message.answer(f"🏦 <b>VIBE BANK</b>\nНа счету: <b>{format_num(u['bank'])}$</b>\nПроцент: 10% ежедневно в 00:00")

# --- ГЕМБЛИНГ ---
@dp.message(F.text.lower().startswith("рул"))
async def cmd_roul(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    try:
        amt = parse_amount(args[1], u['balance'])
        col = args[2].lower()
        if amt <= 0 or u['balance'] < amt: raise ValueError
        u['balance'] -= amt
        res = random.randint(0,36)
        win_c = "зеленый" if res==0 else "красный" if res in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный"
        mul = 14 if col=="зеленый" and win_c=="зеленый" else 2 if col[:3]==win_c[:3] else 0
        u['balance'] += amt*mul; await save_data()
        await message.answer(f"🎲 Выпало: {res} ({win_c})\n{'✅ Победа!' if mul else '❌ Проигрыш'}\nБаланс: {format_num(u['balance'])}")
    except: await message.answer("Пример: <code>рул 10к крас</code>")

@dp.message(F.text.lower().startswith("краш"))
async def cmd_crash(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    try:
        amt, target = parse_amount(args[1], u['balance']), float(args[2].replace(",","."))
        u['balance'] -= amt
        cp = round(random.uniform(1.0, 3.5), 2)
        if target <= cp:
            u['balance'] += int(amt*target); res = f"🚀 Вылет на {cp}x. Вы забрали!"
        else: res = f"💥 КРАШ на {cp}x!"
        await save_data(); await message.answer(f"{res}\nБаланс: {format_num(u['balance'])}")
    except: await message.answer("Пример: <code>краш 10к 1.5</code>")

# --- ЗАПУСК ---
async def main():
    await asyncio.to_thread(sync_load)
    scheduler.add_job(bank_interest_job, 'cron', hour=0, minute=0, timezone=timezone('Europe/Moscow'))
    scheduler.start()
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
