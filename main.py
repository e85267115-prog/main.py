import asyncio
import os
import logging
import random
import json
import io
import time
import aiohttp
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
# Укажи тут юзернейм своего бота (без @), чтобы работали ссылки на промо
BOT_USERNAME = "VibeBetBot" 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Хранилище в памяти
users = {}
promos = {}
active_games = {} 

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
    except Exception as e:
        logging.error(f"Ошибка загрузки БД: {e}")

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        data_to_save = {"users": users, "promos": promos}
        with open("db.json", "w", encoding="utf-8") as f: 
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e:
        logging.error(f"Ошибка сохранения БД: {e}")

async def save_data(): 
    await asyncio.to_thread(sync_save)

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
            "name": name, "balance": 5000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, 
            "shovel": 0, "detector": 0, 
            "last_work": 0, "last_bonus": 0, "used_promos": [],
            "farm": {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
        }
        asyncio.create_task(save_data())
    
    # Миграция
    if "farm" not in users[uid]:
        users[uid]["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
    if "shovel" not in users[uid]: users[uid]["shovel"] = 0
    if "detector" not in users[uid]: users[uid]["detector"] = 0
    
    return users[uid]

async def get_btc_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return float(data['bitcoin']['usd'])
    except: return 98500.0

# --- БАН CHECK ---
@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def ban_check(handler, event, data):
    uid = event.from_user.id
    if get_user(uid, event.from_user.first_name).get('banned'):
        return await event.answer("🚫 <b>Доступ заблокирован!</b>")
    return await handler(event, data)

# --- START & HELP & PROMO LINK ---
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    args = command.args
    # Обработка Deep Link промокода
    if args and args.startswith("promo_"):
        code = args.split("_")[1]
        await activate_promo(message, code)
        return

    txt = (
        "👋 <b>Добро Пожаловать в Vibe Bet!</b>\n"
        "Лучший бот для развлечений и заработка.\n\n"
        "🎲 <b>Игры:</b> Кости, Футбол, Рулетка, Краш, Мины\n"
        "⛏️ <b>Заработок:</b> Работа кладоискателя, Ферма BTC\n\n"
        "Жми <i>Помощь</i> или введи команду!"
    )
    try: await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt)
    except: await message.answer(txt)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    txt = (
        "💎 <b>ЦЕНТР ПОМОЩИ VIBE BET</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>ИГРЫ:</b>\n"
        "└ <code>Рул [сумма] [цвет/число]</code>\n"
        "└ <code>Краш [сумма] [кэф]</code>\n"
        "└ <code>Кости [сумма] [ставка]</code> (7, больше, меньше)\n"
        "└ <code>Футбол [сумма] [ставка]</code> (гол, мимо)\n"
        "└ <code>Мины [сумма]</code> | <code>Алмазы [сумма]</code>\n\n"
        "⛏️ <b>АКТИВНОСТЬ:</b>\n"
        "└ <code>Работа</code> | <code>Ферма</code> | <code>Бонус</code>\n\n"
        "🎁 <b>ПРОМО:</b>\n"
        "└ <code>/pr [код]</code> - активировать\n"
        "└ <code>Профиль</code> | <code>Топ</code>\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(txt)

# --- ПРОФИЛЬ ---
@dp.message(F.text.lower().in_({"профиль", "я", "profile"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    txt = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🏦 В банке: <b>{format_num(u['bank'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*100} XP)\n"
        f"🎒 Инструменты: {'✅' if u['shovel'] else '❌'} {'✅' if u['detector'] else '❌'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(txt)

# --- ТОП (БЕЗ ЛИШНИХ ЭМОДЗИ) ---
@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    sorted_users = sorted(users.items(), key=lambda i: i[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>Топ 10 игроков по балансу:</b>\n\n"
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    
    for i, (uid, u) in enumerate(sorted_users):
        icon = medals.get(i, "")
        name = u['name'].replace("<", "&lt;")
        txt += f"{i+1}) {name} {icon} — {format_num(u['balance'])}\n"
    await message.answer(txt)

# --- ПРОМОКОДЫ ---
@dp.message(F.text.lower().startswith("создать промо"))
async def cmd_create_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split(); code = args[2]; reward = parse_amount(args[3], 0); uses = int(args[4])
        promos[code] = {"reward": reward, "uses": uses}
        await save_data()
        
        bot_user = await bot.get_me()
        bot_link = f"https://t.me/{bot_user.username}?start=promo_{code}"
        
        txt = (
            f"✅ <b>Промокод {code} создан!</b>\n"
            f"👇 <b>ТЫК ДЛЯ АКТИВАЦИИ</b>\n"
            f"💰 Начисление: <b>{format_num(reward)} $</b>\n"
            f"👥 Активаций: <b>{uses}</b>\n\n"
            f"Чтобы активировать: <code>/pr {code}</code>\n"
            f"🔗 Ссылка: <a href='{bot_link}'>Нажми сюда</a>"
        )
        await message.answer(txt)
    except: await message.answer("📝: <code>Создать промо [КОД] [СУММА] [КОЛ-ВО]</code>")

async def activate_promo(message: Message, code: str):
    u = get_user(message.from_user.id)
    if code not in promos: return await message.answer("❌ Промокод не найден!")
    if code in u['used_promos']: return await message.answer("❌ Вы уже активировали этот код!")
    
    promos[code]['uses'] -= 1
    reward = promos[code]['reward']
    u['balance'] += reward
    u['used_promos'].append(code)
    
    if promos[code]['uses'] <= 0: del promos[code]
    await save_data()
    await message.answer(f"✅ <b>Успешно!</b>\nВам начислено: <b>{format_num(reward)} $</b>")

@dp.message(Command("pr"))
async def cmd_pr(message: Message, command: CommandObject):
    if not command.args: return await message.answer("📝 Введите код: `/pr CODE`")
    await activate_promo(message, command.args)

# --- РАБОТА (КЛАДОИСКАТЕЛЬ) ---
@dp.message(F.text.lower() == "работа")
async def work_start(message: Message):
    u = get_user(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏪 Магазин инструментов", callback_data="work_shop")]])
    
    if not u['shovel'] or not u['detector']:
        return await message.answer("❌ <b>Нет инструментов!</b>\nКупите лопату и детектор.", reply_markup=kb)
        
    now = time.time()
    if now - u['last_work'] < 600:
        rem = int(600 - (now - u['last_work']))
        return await message.answer(f"⏳ <b>Усталость!</b> Отдохните еще {rem // 60} мин.")

    kb_work = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗺️ Начать поиск", callback_data="w_scan")]])
    await message.answer("⛏️ <b>КЛАДОИСКАТЕЛЬ</b>\nГотовы искать сокровища?", reply_markup=kb_work)

@dp.callback_query(F.data == "work_shop")
async def work_shop_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    kb = [
        [InlineKeyboardButton(text=f"🔦 Детектор (50к) {'✅' if u['detector'] else ''}", callback_data="buy_tool_det")],
        [InlineKeyboardButton(text=f"⛏️ Лопата (20к) {'✅' if u['shovel'] else ''}", callback_data="buy_tool_sho")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="farm_back")] # Используем общий close/back
    ]
    await call.message.edit_text("🏪 <b>МАГАЗИН ИНСТРУМЕНТОВ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_tool_"))
async def buy_tool_cb(call: CallbackQuery):
    tool = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    price = 50000 if tool == "det" else 20000
    key = "detector" if tool == "det" else "shovel"
    
    if u[key]: return await call.answer("Уже куплено!", show_alert=True)
    if u['balance'] < price: return await call.answer("Не хватает денег!", show_alert=True)
    
    u['balance'] -= price
    u[key] = 1
    await save_data()
    await call.answer("Успешно куплено!")
    await work_shop_cb(call)

@dp.callback_query(F.data == "w_scan")
async def work_scan(call: CallbackQuery):
    await call.message.edit_text("📡 <b>СКАНИРОВАНИЕ...</b>\n<i>Ищем сигналы...</i>")
    await asyncio.sleep(2)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⛏️ КОПАТЬ ТУТ", callback_data="w_dig")]])
    await call.message.edit_text("📍 <b>СИГНАЛ НАЙДЕН!</b>\nДетектор пищит!", reply_markup=kb)

@dp.callback_query(F.data == "w_dig")
async def work_dig(call: CallbackQuery):
    u = get_user(call.from_user.id)
    u['last_work'] = time.time()
    
    win = random.randint(15000, 150000)
    found_btc = 0
    if random.random() < 0.05: # 5% шанс найти BTC
        found_btc = random.uniform(0.0001, 0.001)
        u['btc'] += found_btc
    
    u['balance'] += win
    u['xp'] += 5
    if u['xp'] >= u['lvl']*100: u['lvl'] += 1; u['xp'] = 0
    await save_data()
    
    txt = (
        f"💎 <b>УСПЕШНЫЕ РАСКОПКИ!</b>\n"
        f"💰 Найдено: <b>{format_num(win)} $</b>\n"
    )
    if found_btc > 0: txt += f"🪙 <b>RARE!</b> Найден биток: <b>{found_btc:.6f} BTC</b>\n"
    txt += f"📊 Опыт: +5 XP"
    
    await call.message.edit_text(txt)

# ================= ИГРЫ =================

# --- КОСТИ (РЕАЛЬНЫЕ КУБИКИ) ---
@dp.message(F.text.lower().startswith("кости"))
async def game_dice(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split() # Используем lower split
    try:
        # кости 10к больше
        bet = parse_amount(args[1], u['balance'])
        outcome = args[2]
        
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        u['balance'] -= bet
        
        # Кидаем 2 кубика
        msg1 = await message.answer_dice(emoji="🎲")
        msg2 = await message.answer_dice(emoji="🎲")
        
        # Ждем анимацию
        await asyncio.sleep(3.5)
        
        d1 = msg1.dice.value
        d2 = msg2.dice.value
        total = d1 + d2
        
        win_mult = 0
        if outcome in ["7", "семь"] and total == 7: win_mult = 5.8
        elif outcome in ["больше", "б", ">"] and total > 7: win_mult = 2.33
        elif outcome in ["меньше", "м", "<"] and total < 7: win_mult = 2.33
        
        win_val = int(bet * win_mult)
        res_txt = (
            f"🎲 <b>КОСТИ:</b> {d1} + {d2} = <b>{total}</b>\n"
            f"Ваш выбор: <b>{outcome}</b> | Ставка: {format_num(bet)}\n"
        )
        if win_val > 0:
            u['balance'] += win_val
            res_txt += f"🎉 <b>ПОБЕДА: +{format_num(win_val)} $</b>"
        else:
            res_txt += "❌ <b>ПРОИГРЫШ</b>"
        res_txt += f"\n💰 Баланс: {format_num(u['balance'])}"
        
        await message.answer(res_txt)
        await save_data()
    except: await message.answer("📝 Пример: <code>Кости 10к больше</code> (или меньше, 7)")

# --- ФУТБОЛ (РЕАЛЬНЫЙ) ---
@dp.message(F.text.lower().startswith("футбол"))
async def game_soccer(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    try:
        bet = parse_amount(args[1], u['balance'])
        outcome = args[2] # гол, мимо
        
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        u['balance'] -= bet
        
        msg = await message.answer_dice(emoji="⚽")
        await asyncio.sleep(3.5)
        val = msg.dice.value 
        # 1,2 = Мимо. 3,4,5 = Гол.
        
        win_mult = 0
        is_goal = val in [3, 4, 5]
        
        if outcome in ["гол", "goal"] and is_goal: win_mult = 1.8
        elif outcome in ["мимо", "miss"] and not is_goal: win_mult = 2.3
        
        win_val = int(bet * win_mult)
        res = "ГОЛ! 🥅" if is_goal else "МИМО! 💨"
        
        txt = f"⚽ <b>ФУТБОЛ: {res}</b>\n"
        if win_val > 0:
            u['balance'] += win_val
            txt += f"🎉 <b>+{format_num(win_val)} $</b>"
        else: txt += "❌ <b>Проигрыш</b>"
        txt += f"\n💰 Баланс: {format_num(u['balance'])}"
        
        await message.answer(txt)
        await save_data()
    except: await message.answer("📝 Пример: <code>Футбол 10к гол</code> (или мимо)")

# --- РУЛЕТКА ---
@dp.message(F.text.lower().startswith("рул"))
async def game_roul(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        choice = args[2]
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ставка?")
        u['balance'] -= bet
        
        n = random.randint(0, 36)
        color = "зеленый" if n==0 else "черный" if n in [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35] else "красный"
        parity = "четное" if n!=0 and n%2==0 else "нечетное" if n!=0 else ""
        
        win = 0
        if choice in ["к", "крас", "красный"] and color == "красный": win = bet*2
        elif choice in ["ч", "черн", "черный"] and color == "черный": win = bet*2
        elif choice in ["з", "зел", "зеленый"] and color == "зеленый": win = bet*14
        elif choice.isdigit() and int(choice) == n: win = bet*36
        elif choice in ["чет"] and parity == "четное": win = bet*2
        elif choice in ["нечет"] and parity == "нечетное": win = bet*2
        
        u['balance'] += win
        await message.answer(
            f"💸 Ставка: {format_num(bet)} $\n"
            f"🎉 Выигрыш: {format_num(win)} $\n"
            f"📈 Выпало: {n} ({color}, {parity})\n"
            f"💰 Баланс: {format_num(u['balance'])} $"
        )
        await save_data()
    except: await message.answer("📝 Пример: <code>Рул 1к к</code> (к, ч, з, 1-36)")

# --- АЛМАЗЫ (КРАСИВЫЕ) ---
@dp.message(F.text.lower().startswith("алмазы"))
async def game_dia_start(message: Message):
    u = get_user(message.from_user.id)
    try:
        bet = parse_amount(message.text.split()[1], u['balance'])
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ставка?")
        u['balance'] -= bet
        gid = f"dm_{message.from_user.id}_{int(time.time())}"
        active_games[gid] = {"type": "dm", "uid": message.from_user.id, "bet": bet, "lvl": 0, "mult": 1.0}
        await message.answer(f"💎 <b>АЛМАЗЫ: Уровень 1</b>\n💰 Ставка: {format_num(bet)}", reply_markup=get_dia_kb(gid))
        await save_data()
    except: pass

def get_dia_kb(gid, win=False):
    # 3 кнопки. Если win=True, показываем результат
    row = [InlineKeyboardButton(text="📦", callback_data=f"dm_g_{gid}_{i}") for i in range(3)]
    cashout = [InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"dm_c_{gid}")]
    return InlineKeyboardMarkup(inline_keyboard=[row, cashout])

@dp.callback_query(F.data.startswith("dm_"))
async def dia_act(call: CallbackQuery):
    p = call.data.split("_"); act = p[1]; gid = "_".join(p[2:] if act=='c' else p[2:-1])
    g = active_games.get(gid)
    if not g: return await call.answer("Игра окончена", show_alert=True)
    
    if act == "c":
        w = int(g['bet'] * g['mult'])
        get_user(g['uid'])['balance'] += w
        del active_games[gid]
        await save_data()
        await call.message.edit_text(f"💰 <b>Вы забрали: {format_num(w)} $</b>")
        return

    ch = int(p[-1]); cor = random.randint(0, 2)
    if ch == cor:
        g['lvl'] += 1; g['mult'] *= 2
        await call.message.edit_text(f"💎 <b>УГАДАЛ! Уровень {g['lvl']+1}</b>\nМножитель: x{g['mult']:.1f}", reply_markup=get_dia_kb(gid))
    else:
        del active_games[gid]
        await call.message.edit_text(f"💀 <b>ПУСТО! Алмаз был в {cor+1}-й ячейке.</b>")

# --- ФЕРМА BTC (ИСПРАВЛЕНА) ---
FARM_CFG = {
    "rtx3060": {"n": "RTX 3060", "p": 150000, "inc": 0.1, "sc": 1.2},
    "rtx4070": {"n": "RTX 4070", "p": 220000, "inc": 0.4, "sc": 1.2},
    "rtx4090": {"n": "RTX 4090", "p": 350000, "inc": 0.7, "sc": 1.3}
}

def calc_farm(u):
    now = time.time(); last = u['farm']['last_collect']
    sec = now - last
    hr_inc = sum(u['farm'][k] * v['inc'] for k,v in FARM_CFG.items())
    return (hr_inc / 3600) * sec, hr_inc

@dp.message(F.text.lower() == "ферма")
async def cmd_farm(message: Message):
    u = get_user(message.from_user.id)
    pend, hr = calc_farm(u)
    txt = (
        f"🖥 <b>BTC ФЕРМА</b>\n━━━━━━━━━━━━━━━━━━\n"
          f"⚡ <b>Ваши видеокарты:</b>\n"
        f"🔹 RTX 3060: <b>{u['farm']['rtx3060']} шт.</b>\n"
        f"🔹 RTX 4070: <b>{u['farm']['rtx4070']} шт.</b>\n"
        f"🔹 RTX 4090: <b>{u['farm']['rtx4090']} шт.</b>\n\n"
        f"📉 Доход в час: <b>{hourly:.2f} BTC</b>\n"
        f"💰 Намайнено: <b>{pending_btc:.6f} BTC</b>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Собрать доход", callback_data="farm_collect")],
        [InlineKeyboardButton(text="🛍 Купить видеокарты", callback_data="farm_shop")]
    ])
    await message.answer(txt, reply_markup=kb)

# --- ОБРАБОТКА ФЕРМЫ ---
@dp.callback_query(F.data == "farm_collect")
async def farm_collect_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    pending_btc, _ = calculate_farm_income(u)
    
    if pending_btc <= 0:
        return await call.answer("⚠️ Нечего собирать!", show_alert=True)
    
    u['btc'] += pending_btc
    u['farm']['last_collect'] = datetime.now().timestamp()
    await save_data()
    
    await call.answer(f"✅ Собрано {pending_btc:.6f} BTC", show_alert=True)
    # Обновляем сообщение фермы
    await cmd_farm(call.message)

@dp.callback_query(F.data == "farm_shop")
async def farm_shop_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    kb_list = []
    
    for key, cfg in FARM_CONFIG.items():
        count = u['farm'][key]
        if count >= 3:
            btn_text = f"{cfg['name']} (МАКС)"
            cb = "ignore"
        else:
            price = int(cfg['base_price'] * (cfg['scale'] ** count))
            btn_text = f"{cfg['name']} - {format_num(price)}$ (+{cfg['income']} BTC/ч)"
            cb = f"farm_buy_{key}"
        
        kb_list.append([InlineKeyboardButton(text=btn_text, callback_data=cb)])
        
    kb_list.append([InlineKeyboardButton(text="🔙 Назад", callback_data="farm_back")])
    await call.message.edit_text("🛍 <b>МАГАЗИН ВИДЕОКАРТ</b>\nЛимит: 3 шт. каждой модели.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("farm_buy_"))
async def farm_buy_cb(call: CallbackQuery):
    key = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    cfg = FARM_CONFIG[key]
    
    count = u['farm'][key]
    price = int(cfg['base_price'] * (cfg['scale'] ** count))
    
    if u['balance'] < price:
        return await call.answer("❌ Недостаточно денег!", show_alert=True)
    
    # Сначала собираем текущий доход
    pending, _ = calculate_farm_income(u)
    u['btc'] += pending
    u['farm']['last_collect'] = datetime.now().timestamp()
    
    u['balance'] -= price
    u['farm'][key] += 1
    
    await save_data()
    await call.answer(f"✅ Куплено: {cfg['name']}", show_alert=True)
    await farm_shop_cb(call)

@dp.callback_query(F.data == "farm_back")
async def farm_back_cb(call: CallbackQuery):
    await call.message.delete()
    await cmd_farm(call.message)

# --- НОВЫЕ ИГРЫ: КОСТИ (РЕАЛЬНЫЕ) И ФУТБОЛ ---

@dp.message(F.text.lower().startswith("кости"))
async def game_dice_real(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    try:
        bet = parse_amount(args[1], u['balance'])
        outcome = args[2]
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ставка?")
        
        u['balance'] -= bet
        # Кидаем 2 реальных кубика Телеграма
        msg1 = await message.answer_dice(emoji="🎲")
        msg2 = await message.answer_dice(emoji="🎲")
        
        await asyncio.sleep(3.5) # Ждем анимацию
        total = msg1.dice.value + msg2.dice.value
        
        win_mult = 0
        if outcome in ["7", "семь"] and total == 7: win_mult = 5.8
        elif outcome in ["больше", "б", ">"] and total > 7: win_mult = 2.3
        elif outcome in ["меньше", "м", "<"] and total < 7: win_mult = 2.3
        
        win_val = int(bet * win_mult)
        res_txt = f"🎲 <b>КОСТИ: {msg1.dice.value} + {msg2.dice.value} = {total}</b>\n"
        
        if win_val > 0:
            u['balance'] += win_val
            res_txt += f"🎉 <b>Вы выиграли: {format_num(win_val)} $</b>"
        else:
            res_txt += f"❌ <b>Вы проиграли</b>"
        
        await message.answer(res_txt + f"\n💰 Баланс: {format_num(u['balance'])} $")
        await save_data()
    except: await message.answer("📝: <code>Кости 10к больше/меньше/7</code>")

@dp.message(F.text.lower().startswith("футбол"))
async def game_football_real(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    try:
        bet = parse_amount(args[1], u['balance'])
        outcome = args[2] # гол / мимо
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ставка?")
        
        u['balance'] -= bet
        msg = await message.answer_dice(emoji="⚽")
        await asyncio.sleep(3.5)
        
        is_goal = msg.dice.value in [3, 4, 5] # В Телеграм-мяче это гол
        win = 0
        if outcome == "гол" and is_goal: win = int(bet * 1.8)
        elif outcome == "мимо" and not is_goal: win = int(bet * 2.3)
        
        if win > 0:
            u['balance'] += win
            txt = f"⚽ <b>ГООООЛ!</b>\n🎉 Выигрыш: {format_num(win)} $"
        else:
            txt = f"⚽ {'МИМО!' if not is_goal else 'ВРАТАРЬ СЕЙВ!'} \n❌ Проигрыш"
            
        await message.answer(txt + f"\n💰 Баланс: {format_num(u['balance'])} $")
        await save_data()
    except: await message.answer("📝: <code>Футбол 10к гол/мимо</code>")

# --- ИГРА МИНЫ (ИНЛАЙН) ---
@dp.message(F.text.lower().startswith("мины"))
async def game_mines_start(message: Message):
    u = get_user(message.from_user.id)
    try:
        bet = parse_amount(message.text.split()[1], u['balance'])
        if bet < 10 or bet > u['balance']: return await message.answer("❌ Ставка?")
        
        u['balance'] -= bet
        grid = [False]*25; mines = random.sample(range(25), 3)
        for m in mines: grid[m] = True
        
        gid = f"mn_{message.from_user.id}_{int(time.time())}"
        active_games[gid] = {"type":"mines", "uid":message.from_user.id, "bet":bet, "grid":grid, "opened":[False]*25, "mult":1.0, "step":0}
        
        await message.answer(f"💣 <b>МИНЫ</b>\nСтавка: {format_num(bet)}$\nМин: 3. Открывай ячейки!", reply_markup=get_mines_kb(gid, [False]*25))
    except: await message.answer("📝: <code>Мины 1000</code>")

def get_mines_kb(gid, opened, finish=False, grid=None):
    kb = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r*5+c
            txt = "⬜️"
            if finish:
                if grid[idx]: txt = "💣"
                elif opened[idx]: txt = "💎"
                else: txt = "🔹"
            elif opened[idx]: txt = "💎"
            
            row.append(InlineKeyboardButton(text=txt, callback_data="ignore" if opened[idx] or finish else f"mn_click_{gid}_{idx}"))
        kb.append(row)
    if not finish: kb.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"mn_stop_{gid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("mn_"))
async def mines_callback(call: CallbackQuery):
    data = call.data.split("_")
    gid = "_".join(data[2:-1]) if data[1] == "click" else "_".join(data[2:])
    game = active_games.get(gid)
    if not game or game['uid'] != call.from_user.id: return await call.answer("Игра не найдена")

    if data[1] == "stop":
        win = int(game['bet'] * game['mult'])
        get_user(game['uid'])['balance'] += win
        await call.message.edit_text(f"💰 <b>ВЫИГРЫШ: {format_num(win)} $</b>", reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
        del active_games[gid]; await save_data(); return

    idx = int(data[-1])
    if game['grid'][idx]:
        await call.message.edit_text(f"💥 <b>БАБАХ! Проигрыш {format_num(game['bet'])} $</b>", reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
        del active_games[gid]
    else:
        game['opened'][idx] = True; game['step'] += 1
        game['mult'] *= 1.2 # Множитель за шаг
        await call.message.edit_text(f"💎 <b>МИНЫ</b> | x{game['mult']:.2f}\nВыигрыш: {format_num(int(game['bet']*game['mult']))}$", reply_markup=get_mines_kb(gid, game['opened']))

# --- ТОП (БЕЗ ЭМОДЗИ, КРОМЕ 1-3) ---
@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    sorted_users = sorted(users.items(), key=lambda i: i[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>ТОП 10 МАЖОРОВ:</b>\n\n"
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (uid, u) in enumerate(sorted_users):
        medal = medals.get(i, f"{i+1}.")
        txt += f"{medal} {u['name']} — <b>{format_num(u['balance'])} $</b>\n"
    await message.answer(txt)

# --- АДМИН ПАНЕЛЬ (ИСПРАВЛЕННАЯ) ---
@dp.message()
async def admin_cmds_final(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split(); cmd = args[0].lower()
    try:
        uid = int(args[1])
        if cmd == "выдать":
            val = parse_amount(args[2], 0); get_user(uid)['balance'] += val
            await message.answer(f"✅ Выдано <b>{format_num(val)}$</b> игроку <code>{uid}</code>")
        elif cmd == "выдатьбтк":
            val = float(args[2]); get_user(uid)['btc'] += val
            await message.answer(f"✅ Выдано <b>{val} BTC</b>")
        await save_data()
    except: pass

# --- ЗАПУСК ---
async def bank_interest():
    for u in users.values():
        if u.get('bank', 0) > 0: u['bank'] += int(u['bank'] * 0.10)
    await save_data()

async def main():
    sync_load()
    # Проценты в банке в полночь по МСК
    scheduler.add_job(bank_interest, 'cron', hour=0, minute=0, timezone=timezone('Europe/Moscow'))
    scheduler.start()
    
    # Web server для Render/Railway
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import time # На всякий случай для меток времени
    asyncio.run(main())
