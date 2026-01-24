import asyncio
import os
import logging
import random
import json
import io
import time
from datetime import datetime
from pytz import timezone

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
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

# Хранилище
users = {}
promos = {}
active_games = {} 

# Цены на инструменты
SHOVEL_PRICE = 50000
DETECTOR_PRICE = 150000

FARM_CONFIG = {
    "rtx3060": {"name": "RTX 3060", "base_price": 150000, "income": 0.00001, "scale": 1.2},
    "rtx4070": {"name": "RTX 4070", "base_price": 220000, "income": 0.00004, "scale": 1.2},
    "rtx4090": {"name": "RTX 4090", "base_price": 350000, "income": 0.00007, "scale": 1.3}
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
    except Exception as e: logging.error(f"Загрузка: {e}")

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        data = {"users": users, "promos": promos}
        with open("db.json", "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e: logging.error(f"Сохранение: {e}")

async def save_data(): await asyncio.to_thread(sync_save)

def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

# --- УТИЛИТЫ ---
def format_num(num):
    num = float(num)
    if num < 1000: return str(int(num))
    suffixes = [(1e12, "кккк"), (1e9, "ккк"), (1e6, "кк"), (1e3, "к")]
    for val, suff in suffixes:
        if num >= val:
            res = num / val
            return f"{int(res) if res == int(res) else round(res, 2)}{suff}"
    return str(int(num))

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all", "вабанк", "max"]: return int(balance)
    multipliers = {"кккк": 1e12, "ккк": 1e9, "кк": 1e6, "к": 1e3}
    for suff, mult in multipliers.items():
        if text.endswith(suff):
            try: return int(float(text[:-len(suff)]) * mult)
            except: pass
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    uid = int(uid)
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 5000, "bank": 0, "btc": 0.0, "lvl": 1, "xp": 0, "banned": False, 
            "shovel": 0, "detector": 0, "last_work": 0, "last_bonus": 0, "used_promos": [],
            "farm": {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
        }
    u = users[uid]
    if "farm" not in u: u["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
    if "shovel" not in u: u["shovel"] = 0
    if "detector" not in u: u["detector"] = 0
    return u

def check_level_up(u):
    req = u['lvl'] * 5
    if u['xp'] >= req:
        u['xp'] -= req
        u['lvl'] += 1
        return True
    return False

# --- MIDDLEWARE ---
@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def ban_check(handler, event, data):
    uid = event.from_user.id
    if get_user(uid, event.from_user.first_name).get('banned'):
        return await event.answer("🚫 Доступ заблокирован!")
    return await handler(event, data)

# --- START & HELP ---
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    if command.args and command.args.startswith("promo_"):
        return await activate_promo(message, command.args.split("_")[1])
    txt = "👋 <b>Vibe Bet!</b>\nИгры, Фермы и Кладоискатель.\n\nПиши <b>Помощь</b> для списка команд."
    await message.answer(txt)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    txt = (
        "🎮 <b>СПИСОК КОМАНД:</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>ИГРЫ:</b>\n"
        "└ <code>Рул [сумма] [ставка]</code> (к, ч, з, 0-36)\n"
        "└ <code>Кости [сумма] [ставка]</code> (Равно, Больше, Меньше)\n"
        "└ <code>Футбол [сумма] [ставка]</code> (Гол, Мимо)\n"
        "└ <code>Алмазы [сумма] [бомбы]</code> (1-2)\n"
        "└ <code>Мины [сумма]</code>\n\n"
        "⛏️ <b>ЗАРАБОТОК:</b>\n"
        "└ <code>Работа</code> — Кладоискатель (нужна лопата)\n"
        "└ <code>Магазин</code> — Купить инструменты\n"
        "└ <code>Ферма</code> — Майнинг BTC\n"
        "└ <code>Бонус</code> — Каждый час\n\n"
        "👤 <b>АККАУНТ:</b>\n"
        "└ <code>Профиль</code>, <code>Топ</code>, <code>Перевести [ID] [Сумма]</code>\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(txt)

# --- ПРОФИЛЬ, ТОП, БОНУС ---
@dp.message(F.text.lower().in_({"профиль", "я", "profile"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    txt = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*5} XP)\n"
        f"🎒 Инструменты: {'🛠 Лопата' if u['shovel'] else '❌'} {'📟 Детектор' if u['detector'] else '❌'}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(txt)

@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    u = get_user(message.from_user.id)
    if time.time() - u['last_bonus'] < 3600:
        rem = int(3600 - (time.time() - u['last_bonus']))
        return await message.answer(f"⏳ Бонус через {rem//60} мин.")
    gain = random.randint(10000, 30000) + (u['lvl'] * 5000)
    u['balance'] += gain
    u['last_bonus'] = time.time()
    await message.answer(f"🎁 Получено: <b>{format_num(gain)} $</b>")
    await save_data()

# --- КЛАДОИСКАТЕЛЬ (РАБОТА) ---
@dp.message(F.text.lower() == "магазин")
async def cmd_shop(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Лопата — {format_num(SHOVEL_PRICE)}$", callback_data="buy_shovel")],
        [InlineKeyboardButton(text=f"Детектор — {format_num(DETECTOR_PRICE)}$", callback_data="buy_detector")]
    ])
    await message.answer("🛒 <b>МАГАЗИН ИНСТРУМЕНТОВ</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_tool(call: CallbackQuery):
    u = get_user(call.from_user.id)
    tool = call.data.split("_")[1]
    price = SHOVEL_PRICE if tool == "shovel" else DETECTOR_PRICE
    if u[tool]: return await call.answer("Уже есть!", show_alert=True)
    if u['balance'] < price: return await call.answer("Недостаточно денег!", show_alert=True)
    u['balance'] -= price
    u[tool] = 1
    await call.message.edit_text(f"✅ Вы купили: {('Лопату' if tool == 'shovel' else 'Детектор')}")
    await save_data()

@dp.message(F.text.lower() == "работа")
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    if not u['shovel']: return await message.answer("❌ Тебе нужна лопата! Купи в магазине.")
    if time.time() - u['last_work'] < 600:
        return await message.answer(f"⏳ Устал, отдохни еще {int(600-(time.time()-u['last_work']))//60} мин.")
    
    gid = f"work_{message.from_user.id}"
    active_games[gid] = {"uid": message.from_user.id}
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Лес 🌲", callback_data=f"dig_{gid}_1"),
        InlineKeyboardButton(text="Пляж 🏖", callback_data=f"dig_{gid}_2"),
        InlineKeyboardButton(text="Поле 🌾", callback_data=f"dig_{gid}_3")
    ]])
    await message.answer("🔍 <b>Где будем копать?</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("dig_"))
async def dig_callback(call: CallbackQuery):
    p = call.data.split("_")
    gid = "_".join(p[1:-1]); u = get_user(call.from_user.id)
    if gid not in active_games: return await call.answer("Уже выкопано!")
    
    u['last_work'] = time.time()
    res = random.random()
    if u['detector']: res += 0.2 # Шанс выше с детектором
    
    if res > 0.4:
        gain = random.randint(30000, 100000) * u['lvl']
        u['balance'] += gain
        txt = f"💎 <b>Нашел клад!</b>\nЗаработок: {format_num(gain)} $"
    else: txt = "🗑 <b>Ничего не нашел...</b> только старые консервные банки."
    
    del active_games[gid]
    u['xp'] += 2; check_level_up(u)
    await call.message.edit_text(txt)
    await save_data()

# --- АЛМАЗЫ (ФИКС КНОПКИ ЗАБРАТЬ) ---
@dp.message(F.text.lower().startswith("алмазы"))
async def game_dia_start(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.split()
    try:
        bet = parse_amount(args[1], u['balance'])
        bombs = int(args[2]) if len(args) > 2 else 1
        if bombs not in [1, 2] or bet < 10 or bet > u['balance']: raise ValueError
        u['balance'] -= bet
        gid = f"dm_{message.from_user.id}_{int(time.time())}"
        active_games[gid] = {"uid": message.from_user.id, "bet": bet, "lvl": 0, "mult": (1.3 if bombs == 1 else 2.3), "bombs": bombs}
        await message.answer(f"💎 <b>АЛМАЗЫ</b> ({bombs} 💣)\nСтавка: {format_num(bet)}$", reply_markup=get_dia_kb(gid))
    except: await message.answer("📝: <code>Алмазы [сумма] [бомбы 1-2]</code>")

def get_dia_kb(gid, finish=None):
    if finish:
        btns = [InlineKeyboardButton(text=("💀" if i in finish['b'] else "💎"), callback_data="ignore") for i in range(3)]
        return InlineKeyboardMarkup(inline_keyboard=[btns])
    btns = [InlineKeyboardButton(text="📦", callback_data=f"dm_g_{gid}_{i}") for i in range(3)]
    # Кнопка забрать появляется только после lvl > 0 (после первого клика)
    kb = [btns]
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("dm_"))
async def dia_act(call: CallbackQuery):
    p = call.data.split("_")
    gid = "_".join(p[2:-1]) if p[1] == 'g' else "_".join(p[2:])
    g = active_games.get(gid)
    if not g: return await call.answer("Игра окончена")

    if p[1] == 'c': # Забрать
        if g['lvl'] == 0: return await call.answer("Нужно открыть хоть один ящик!", show_alert=True)
        win = int(g['bet'] * g['mult'])
        get_user(g['uid'])['balance'] += win
        await call.message.edit_text(f"💰 <b>Забрал: {format_num(win)}$</b>")
        del active_games[gid]; await save_data(); return

    idx = int(p[-1])
    bombs = random.sample([0, 1, 2], g['bombs'])
    if idx in bombs:
        await call.message.edit_text("💥 <b>БОМБА! Проигрыш.</b>", reply_markup=get_dia_kb(gid, {'b': bombs}))
        del active_games[gid]
    else:
        g['lvl'] += 1
        if g['lvl'] > 0: # Добавляем кнопку "Забрать" после успеха
            kb = get_dia_kb(gid).inline_keyboard
            if len(kb) == 1: kb.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ {format_num(int(g['bet']*g['mult']))}$", callback_data=f"dm_c_{gid}")])
        g['mult'] += (0.4 if g['bombs'] == 1 else 0.8)
        await call.message.edit_text(f"💎 <b>Угадал! Множитель: x{g['mult']:.1f}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await save_data()

# --- ФЕРМА (ИСПРАВЛЕН ВИЗУАЛ) ---
@dp.message(F.text.lower() == "ферма")
async def cmd_farm(message: Message):
    u = get_user(message.from_user.id)
    # Считаем доход
    now = time.time()
    hr_btc = sum(u['farm'][k] * FARM_CONFIG[k]['income'] for k in FARM_CONFIG)
    pending = (hr_btc / 3600) * (now - u['farm']['last_collect'])
    
    txt = (
        f"🖥 <b>BTC ФЕРМА</b>\n"
        f"3060: {u['farm']['rtx3060']} | 4070: {u['farm']['rtx4070']} | 4090: {u['farm']['rtx4090']}\n\n"
        f"📉 Доход: {hr_btc:.8f} BTC/ч\n"
        f"💰 Намайнено: <b>{pending:.8f} BTC</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Собрать", callback_data="f_collect")],
        [InlineKeyboardButton(text="🛍 Магазин карт", callback_data="f_shop")]
    ])
    await message.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "f_collect")
async def f_coll(call: CallbackQuery):
    u = get_user(call.from_user.id)
    hr_btc = sum(u['farm'][k] * FARM_CONFIG[k]['income'] for k in FARM_CONFIG)
    pending = (hr_btc / 3600) * (time.time() - u['farm']['last_collect'])
    if pending < 1e-8: return await call.answer("Пусто!", show_alert=True)
    u['btc'] += pending
    u['farm']['last_collect'] = time.time()
    await call.answer(f"Собрано {pending:.8f} BTC")
    # Перерисовываем ту же ферму, чтобы не двоилось
    await call.message.delete()
    await cmd_farm(call.message)

@dp.callback_query(F.data == "f_shop")
async def f_shop(call: CallbackQuery):
    u = get_user(call.from_user.id)
    kb = []
    for k, c in FARM_CONFIG.items():
        price = int(c['base_price'] * (c['scale'] ** u['farm'][k]))
        kb.append([InlineKeyboardButton(text=f"{c['name']} | {format_num(price)}$", callback_data=f"f_buy_{k}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="f_back")])
    await call.message.edit_text("🛒 <b>КУПИТЬ ВИДЕОКАРТЫ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("f_buy_"))
async def f_buy(call: CallbackQuery):
    k = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    price = int(FARM_CONFIG[k]['base_price'] * (FARM_CONFIG[k]['scale'] ** u['farm'][k]))
    if u['balance'] < price: return await call.answer("Мало денег!")
    u['balance'] -= price
    u['farm'][k] += 1
    await call.answer("Куплено!")
    await f_shop(call)

@dp.callback_query(F.data == "f_back")
async def f_back(call: CallbackQuery):
    await call.message.delete()
    await cmd_farm(call.message)

# --- ИГРЫ: КОСТИ (РАВНО) ---
@dp.message(F.text.lower().startswith("кости"))
async def game_dice(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.lower().split()
        bet = parse_amount(args[1], u['balance'])
        choice = args[2]
        if bet < 10 or bet > u['balance']: raise ValueError
        u['balance'] -= bet
        d1 = await message.answer_dice("🎲"); d2 = await message.answer_dice("🎲")
        await asyncio.sleep(3.5); total = d1.dice.value + d2.dice.value
        win = 0
        if choice == "равно" and total == 7: win = bet * 6
        elif choice in [">", "больше"] and total > 7: win = bet * 2.3
        elif choice in ["<", "меньше"] and total < 7: win = bet * 2.3
        
        u['balance'] += int(win)
        res = f"🎲 Сумма: <b>{total}</b>\n" + (f"🎉 Выигрыш: {format_num(win)}$" if win > 0 else "❌ Проигрыш")
        await message.answer(res)
        await save_data()
    except: await message.answer("📝: <code>Кости 1000 [Равно / Больше / Меньше]</code>")

# --- РУЛЕТКА (ФОРМАТ) ---
@dp.message(F.text.lower().startswith("рул"))
async def game_roul(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.lower().split()
        bet = parse_amount(args[1], u['balance'])
        choice = args[2]
        if bet < 10 or bet > u['balance']: raise ValueError
        u['balance'] -= bet
        n = random.randint(0, 36)
        color = "зеленый" if n == 0 else "красный" if n in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный"
        win = 0
        if choice in ["к", "красный"] and color == "красный": win = bet * 2
        elif choice in ["ч", "черный"] and color == "черный": win = bet * 2
        elif choice in ["з", "зеленый"] and color == "зеленый": win = bet * 14
        elif choice.isdigit() and int(choice) == n: win = bet * 36
        u['balance'] += int(win)
        await message.answer(f"🎰 Выпало: <b>{n} ({color})</b>\n" + (f"🎉 +{format_num(win)}$" if win > 0 else "❌ Проигрыш"))
        await save_data()
    except: await message.answer("📝: <code>Рул 1000 к</code> (к, ч, з, 0-36)")

# --- АДМИНКА (ФИКС) ---
@dp.message(Command("give"))
async def admin_give(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        uid, amount = command.args.split()
        u = get_user(int(uid))
        u['balance'] += int(amount)
        await message.answer(f"✅ Выдано {amount}$ игроку {uid}")
        await save_data()
    except: await message.answer("Формат: `/give ID СУММА`")

@dp.message(Command("ban"))
async def admin_ban(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        uid = int(command.args)
        get_user(uid)['banned'] = True
        await message.answer(f"🚫 Игрок {uid} забанен.")
        await save_data()
    except: pass

# --- ЗАПУСК ---
async def main():
    sync_load()
    scheduler.start()
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Running"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
