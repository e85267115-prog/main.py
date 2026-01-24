import asyncio
import os
import logging
import random
import json
import io
import aiohttp
from datetime import datetime
from pytz import timezone

# Библиотеки Telegram
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiohttp import web

# Библиотеки Google
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Планировщик для Банка (00:00 МСК)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN") 
ADMIN_IDS = [1997428703] # Твой ID
PORT = int(os.getenv("PORT", 8080))

# Google Drive
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'

# Каналы для подписки
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

# --- UTILS (ФОРМАТИРОВАНИЕ) ---
def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        if num < 1_000_000: return f"{num/1000:.2f}к" # 1.05к
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
    except: return 95000 # Если API упал

# --- БАНКОВСКАЯ ЗАДАЧА (00:00 MSK) ---
async def bank_interest_job():
    logging.info("⏳ Начисление процентов в банке...")
    count = 0
    for uid, u in users.items():
        if u.get('bank', 0) > 0:
            interest = int(u['bank'] * 0.10) # 10%
            u['bank'] += interest
            count += 1
    if count > 0:
        await save_data()
        logging.info(f"✅ Проценты начислены {count} пользователям.")

# --- MIDDLEWARE (ПОДПИСКА + БАН) ---
@dp.message.outer_middleware()
async def check_access(handler, event: Message, data):
    if not isinstance(event, Message): return await handler(event, data) # Пропуск для колбэков, если нужно
    
    uid = event.from_user.id
    u = get_user(uid, event.from_user.first_name)
    
    # 1. Проверка Бана
    if u.get('banned'):
        return # Игнор

    # 2. Проверка Подписки (кроме админа и старта)
    if uid not in ADMIN_IDS and not event.text.startswith("/start"):
        not_subbed = []
        for ch in REQUIRED_CHANNELS:
            try:
                m = await bot.get_chat_member(chat_id=ch["username"], user_id=uid)
                if m.status in ["left", "kicked"]: not_subbed.append(ch)
            except: pass # Бот не админ
            
        if not_subbed:
            kb = [[InlineKeyboardButton(text=f"👉 {ch['name']}", url=ch['url'])] for ch in not_subbed]
            kb.append([InlineKeyboardButton(text="✅ Я ПОДПИСАЛСЯ", callback_data="check_sub")])
            return await event.answer("🔒 <b>Подпишись для игры:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            
    return await handler(event, data)

@dp.callback_query(F.data == "check_sub")
async def sub_check_call(call: CallbackQuery):
    await call.message.delete()
    await call.message.answer("🔄 Проверьте снова командой /start")

# --- КОМАНДЫ ПОЛЬЗОВАТЕЛЯ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    u = get_user(message.from_user.id, message.from_user.first_name)
    photo = FSInputFile("start_img.jpg")
    txt = (
        "👋 <b>Добро Пожаловать в Vibe Bet!</b>\n\n"
        "Игровой телеграм бот. Играй, веселись, все это ТУТ!\n\n"
        "⚙️ Используй кнопки меню или напиши <b>Помощь</b>"
    )
    try: await message.answer_photo(photo, caption=txt)
    except: await message.answer(txt)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    txt = (
        "📚 <b>СПИСОК КОМАНД:</b>\n\n"
        "👤 <b>Основное:</b>\n"
        "• <code>Профиль</code> (или 'Я') — Статистика\n"
        "• <code>Магазин</code> — Инструменты\n"
        "• <code>Работа</code> — Мини-игра (Клад)\n"
        "• <code>Рынок</code> — Курс Биткоина\n\n"
        "💸 <b>Финансы:</b>\n"
        "• <code>Банк</code> — Твой счет\n"
        "• <code>Деп [сумма]</code> — Положить в банк\n"
        "• <code>Снять [сумма]</code> — Снять из банка\n"
        "• <code>Перевести [ID] [сумма]</code> — Другу\n\n"
        "🎰 <b>Игры:</b>\n"
        "• <code>Рул [сумма] [цвет]</code>\n"
        "• <code>Краш [сумма] [кэф]</code>"
    )
    await message.answer(txt)

@dp.message(F.text.lower().in_({"профиль", "я", "стата"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    needed = u['lvl'] * 10
    
    # Считаем инструменты для отображения "Инструментов 2/2"
    tools_count = 0
    if u['shovel'] > 0: tools_count += 1
    if u['detector'] > 0: tools_count += 1
    
    txt = (
        f"👤 <b>ТВОЙ ПРОФИЛЬ</b>\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"💰 На руках: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b>\n"
        f"📊 Опыт: <b>{u['xp']} / {needed} XP</b>\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"🎒 Инструментов: <b>{tools_count}/2</b>"
    )
    await message.answer(txt)

# --- БАНК И ПЕРЕВОДЫ ---
@dp.message(F.text.lower() == "банк")
async def cmd_bank(message: Message):
    u = get_user(message.from_user.id)
    await message.answer(
        f"🏦 <b>VIBE BANK</b>\n\n"
        f"💳 На счете: <b>{format_num(u['bank'])} $</b>\n"
        f"📈 Ставка: <b>10% в день</b> (в 00:00 МСК)\n\n"
        f"↘️ <code>Деп [сумма]</code>\n"
        f"↙️ <code>Снять [сумма]</code>"
    )

@dp.message(F.text.lower().startswith("деп"))
async def cmd_deposit(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = parse_amount(message.text.split()[1], u['balance'])
        if amt <= 0 or amt > u['balance']: raise ValueError
        u['balance'] -= amt; u['bank'] += amt
        await save_data()
        await message.answer(f"✅ В банк положено: <b>{format_num(amt)} $</b>")
    except: await message.answer("❌ Ошибка суммы.")

@dp.message(F.text.lower().startswith("снять"))
async def cmd_withdraw(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = parse_amount(message.text.split()[1], u['bank'])
        if amt <= 0 or amt > u['bank']: raise ValueError
        u['bank'] -= amt; u['balance'] += amt
        await save_data()
        await message.answer(f"✅ Из банка снято: <b>{format_num(amt)} $</b>")
    except: await message.answer("❌ Ошибка суммы.")

@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    # перевести ID СУММА
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        target_id = int(args[1])
        amt = parse_amount(args[2], u['balance'])
        
        if target_id not in users: return await message.answer("❌ Игрок не найден.")
        if target_id == message.from_user.id: return await message.answer("❌ Себе нельзя.")
        if amt <= 0 or amt > u['balance']: return await message.answer("❌ Не хватает денег.")
        
        u['balance'] -= amt
        users[target_id]['balance'] += amt
        await save_data()
        
        await message.answer(f"💸 Перевод <b>{format_num(amt)} $</b> игроку {target_id} успешен.")
        try: await bot.send_message(target_id, f"📩 Вам перевели <b>{format_num(amt)} $</b>")
        except: pass
    except: await message.answer("⚠️ Пиши: <code>Перевести ID Сумма</code>")

# --- РЫНОК ---
@dp.message(F.text.lower() == "рынок")
async def cmd_market(message: Message):
    price = await get_btc_price()
    u = get_user(message.from_user.id)
    val_usd = u['btc'] * price
    
    await message.answer(
        f"📊 <b>CRYPTO MARKET</b>\n\n"
        f"🔸 BTC Price: <b>{format_num(price)} $</b>\n"
        f"💼 Твой портфель: <b>{u['btc']:.6f} BTC</b>\n"
        f"💵 Оценка: <b>~{format_num(val_usd)} $</b>"
    )

# --- РАБОТА (КЛАДОИСКАТЕЛЬ) ---
@dp.message(F.text.lower().in_({"работа", "work"}))
async def cmd_work_start(message: Message):
    u = get_user(message.from_user.id)
    
    # Проверка инструментов (нужны оба, максимум по 1)
    if u['shovel'] < 1 or u['detector'] < 1:
        return await message.answer("❌ Нужна <b>Лопата</b> и <b>Детектор</b>!\nКупи в магазине.")

    # Проверка КД (10 минут)
    now = datetime.now().timestamp()
    if now - u['last_work'] < 600:
        rem = int(600 - (now - u['last_work']))
        return await message.answer(f"⏳ Отдыхай еще {rem // 60} мин {rem % 60} сек")

    # Старт мини-игры
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏜️", callback_data="dig_1"),
            InlineKeyboardButton(text="🏚️", callback_data="dig_2"),
            InlineKeyboardButton(text="🏝️", callback_data="dig_3")
        ]
    ])
    await message.answer("🗺️ <b>Где будем копать?</b>\nВыбери место, где спрятан клад:", reply_markup=kb)

@dp.callback_query(F.data.startswith("dig_"))
async def work_process(call: CallbackQuery):
    u = get_user(call.from_user.id)
    # Повторная проверка КД (чтобы не кликали)
    now = datetime.now().timestamp()
    if now - u['last_work'] < 600: 
        return await call.answer("⏳ Рано!", show_alert=True)
    
    u['last_work'] = now
    
    # Логика награды (10к - 3кк)
    # Шанс на крупный выигрыш растет с уровнем
    chance_big = 0.05 + (u['lvl'] * 0.01) # 5% + 1% за уровень
    if chance_big > 0.30: chance_big = 0.30 # Кап 30%
    
    if random.random() < chance_big:
        # КРУПНЫЙ КУШ
        win = random.randint(500_000, 3_000_000)
        emoji = "💎"
        msg = "<b>ЛЕГЕНДАРНЫЙ КЛАД!</b>"
    else:
        # ОБЫЧНЫЙ
        win = random.randint(10_000, 100_000)
        emoji = "💰"
        msg = "Неплохой улов!"
    
    # Иногда инструмент ломается (10% шанс) - хотя пользователь просил по 1 шт
    # Раз просили ограничение 1/1, сделаем инструменты вечными или пусть ломаются? 
    # Сделаем вечными, раз покупка лимитирована 1 шт. Или пусть покупает заново.
    # Давайте пусть ломаются редко (5%)
    broken = ""
    if random.random() < 0.05:
        if random.random() < 0.5:
            u['shovel'] = 0; broken = "\n💥 <b>Лопата сломалась!</b>"
        else:
            u['detector'] = 0; broken = "\n💥 <b>Детектор сломался!</b>"

    u['balance'] += win
    
    # Опыт
    xp = random.randint(2, 5)
    u['xp'] += xp
    xp_msg = f"+{xp} XP"
    
    # Проверка уровня
    if u['xp'] >= u['lvl'] * 10:
        u['lvl'] += 1; u['xp'] = 0
        xp_msg += f" | 🆙 <b>LVL {u['lvl']}</b>"

    await save_data()
    await call.message.edit_text(
        f"{emoji} {msg}\n"
        f"💵 Выкопано: <b>{format_num(win)} $</b>\n"
        f"📊 Опыт: {xp_msg}"
        f"{broken}"
    )

# --- МАГАЗИН ---
@dp.message(F.text.lower() == "магазин")
async def cmd_shop(message: Message):
    u = get_user(message.from_user.id)
    
    # Считаем
    has_shovel = "✅" if u['shovel'] > 0 else "❌"
    has_detect = "✅" if u['detector'] > 0 else "❌"
    count = (1 if u['shovel'] > 0 else 0) + (1 if u['detector'] > 0 else 0)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Лопата (50к)", callback_data="buy_shovel")],
        [InlineKeyboardButton(text="Детектор (100к)", callback_data="buy_detector")]
    ])
    
    await message.answer(
        f"🏪 <b>VIBE SHOP</b>\n\n"
        f"1. Лопата: {has_shovel}\n"
        f"2. Детектор: {has_detect}\n\n"
        f"🎒 Инструментов: <b>{count}/2</b>\n"
        f"<i>(Можно иметь только по 1 шт)</i>",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("buy_"))
async def shop_buy(call: CallbackQuery):
    u = get_user(call.from_user.id)
    item = call.data.split("_")[1]
    
    # Проверка наличия
    if u.get(item, 0) >= 1:
        return await call.answer("⚠️ У вас уже есть этот предмет!", show_alert=True)
        
    price = 50000 if item == "shovel" else 100000
    if u['balance'] < price:
        return await call.answer("❌ Не хватает денег!", show_alert=True)
        
    u['balance'] -= price
    u[item] = 1 # Ставим 1, так как ограничение
    await save_data()
    await call.answer("✅ Куплено!")
    await call.message.delete()
    await cmd_shop(call.message) # Обновляем меню

# --- АДМИН КОМАНДЫ ---
@dp.message(F.text.lower().startswith("выдатьбтк"))
async def adm_give_btc(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        _, uid, amt = message.text.split()
        uid = int(uid); amt = float(amt.replace(",", "."))
        get_user(uid)['btc'] += amt
        await save_data()
        await message.answer(f"✅ Выдано {amt} BTC игроку {uid}")
    except: await message.answer("Ошибка")

@dp.message(F.text.lower().startswith("выдать"))
async def adm_give_money(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        parts = message.text.split()
        uid = int(parts[1])
        amt = parse_amount(parts[2], 0)
        get_user(uid)['balance'] += amt
        await save_data()
        await message.answer(f"✅ Выдано {format_num(amt)}$ игроку {uid}")
    except: await message.answer("Ошибка")

@dp.message(F.text.lower().startswith("бан"))
async def adm_ban(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        uid = int(message.text.split()[1])
        get_user(uid)['banned'] = True
        await save_data()
        await message.answer(f"🚫 Игрок {uid} забанен")
    except: pass

@dp.message(F.text.lower().startswith("разбан"))
async def adm_unban(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        uid = int(message.text.split()[1])
        get_user(uid)['banned'] = False
        await save_data()
        await message.answer(f"✅ Игрок {uid} разбанен")
    except: pass

# --- СТАРЫЕ ИГРЫ (КРАШ И РУЛЕТКА) ---
@dp.message(F.text.lower().startswith("рул"))
async def cmd_roulette(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        amt = parse_amount(args[1], u['balance'])
        col = args[2].lower()
        if amt <= 0 or amt > u['balance']: raise ValueError
    except: return await message.answer("❌ Ставка не верна")

    u['balance'] -= amt
    res_num = random.randint(0, 36)
    win_col = "зеленый" if res_num == 0 else "красный" if res_num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный"
    
    win_amt = 0
    if (col.startswith("чер") and win_col == "черный") or (col.startswith("кра") and win_col == "красный"): win_amt = amt * 2
    elif col.startswith("зел") and win_col == "зеленый": win_amt = amt * 14

    u['balance'] += win_amt
    await save_data()
    status = f"🎉 ВЫИГРЫШ: {format_num(win_amt)} $" if win_amt > 0 else "😔 ПРОИГРЫШ"
    await message.answer(f"🎰 {status}\n📈 Выпало: {res_num} ({win_col})\n💰 Баланс: {format_num(u['balance'])}")

@dp.message(F.text.lower().startswith("краш"))
async def cmd_crash(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    try:
        amt = parse_amount(args[1], u['balance'])
        mult = float(args[2].replace(",", "."))
        if amt <= 0 or amt > u['balance'] or mult < 1.01: raise ValueError
    except: return await message.answer("❌ Ставка не верна")

    u['balance'] -= amt
    crash_point = round(random.uniform(1.0, 4.0), 2)
    win = 0
    if mult <= crash_point:
        win = int(amt * mult)
        u['balance'] += win
        res = f"🎉 Выигрыш! (x{mult})"
    else: res = "😔 Крашнулось!"
    
    await save_data()
    await message.answer(f"🚀 {res}\n📈 Точка: {crash_point}x\n💸 Приз: {format_num(win)} $\n💰 Баланс: {format_num(u['balance'])}")

# --- ЗАПУСК ---
async def handle_ping(request): return web.Response(text="OK")

async def main():
    await asyncio.to_thread(sync_load)
    
    # Настройка планировщика (Банк)
    scheduler.add_job(bank_interest_job, 'cron', hour=0, minute=0, timezone=timezone('Europe/Moscow'))
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
