import asyncio
import os
import logging
import random
import json
import io
import time
import aiohttp
from datetime import datetime, timedelta
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

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN") 
# Add your Admin ID here
ADMIN_IDS = [1997428703] 
PORT = int(os.getenv("PORT", 8080))
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'
BOT_USERNAME = "VibeBetBot" 

# Channels for subscription
REQUIRED_CHANNELS = [
    {"username": "@chatvibee_bet", "link": "https://t.me/chatvibee_bet"},
    {"username": "@nvibee_bet", "link": "https://t.me/nvibee_bet"}
]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# In-memory storage
users = {}
promos = {}
active_games = {} 

# Global Market State
btc_rate = 50000  # Default starting price

# --- FARM CONFIG ---
# Max 3 cards of each type per person
FARM_CONFIG = {
    "rtx3060": {"name": "RTX 3060", "base_price": 150000, "income": 0.00001, "scale": 1.2, "limit": 3},
    "rtx4070": {"name": "RTX 4070", "base_price": 220000, "income": 0.00004, "scale": 1.2, "limit": 3},
    "rtx4090": {"name": "RTX 4090", "base_price": 350000, "income": 0.00007, "scale": 1.3, "limit": 3}
}

# --- WORK CONFIG ---
WORK_CONFIG = {
    "shovel_price": 50000,
    "detector_price": 100000,
    "cooldown": 600, # 10 minutes
    "reward_min": 30000,
    "reward_max": 150000,
    "btc_chance": 0.10, # 10%
    "btc_drop_range": [1.0, 2.0] # Drops 1-2 BTC
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
    except Exception as e:
        logging.error(f"DB Load Error: {e}")

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
        logging.error(f"DB Save Error: {e}")

async def save_data(): 
    await asyncio.to_thread(sync_save)

def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

# --- UTILS ---
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
            "name": name, "balance": 5000, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, 
            "registered": False, "reg_date": time.time(),
            "shovel": 0, "detector": 0, 
            "last_work": 0, "last_bonus": 0, "used_promos": [],
            "farm": {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
        }
        asyncio.create_task(save_data())
    
    # Migrations
    if "farm" not in users[uid]:
        users[uid]["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
    if "registered" not in users[uid]: users[uid]["registered"] = False
    
    return users[uid]

def check_level_up(u):
    # XP Required: Level * 4 (e.g., Lvl 1->2 needs 4, Lvl 2->3 needs 8)
    req = u['lvl'] * 4 
    if u['xp'] >= req:
        u['xp'] -= req
        u['lvl'] += 1
        return True
    return False

async def update_btc_market():
    global btc_rate
    # Random price between 10k and 150k
    btc_rate = random.randint(10000, 150000)
    await save_data()

# --- SUBSCRIPTION CHECK ---
async def check_subscription(user_id):
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["username"], user_id=user_id)
            if member.status in ['left', 'kicked', 'restricted']:
                return False
        except Exception:
            # If bot isn't admin, assume true to not block users, or return False if strict
            return True 
    return True

# --- MIDDLEWARE & REGISTRATION CHECK ---
@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def global_check(handler, event, data):
    uid = event.from_user.id
    u = get_user(uid, event.from_user.first_name)
    
    if u.get('banned'):
        return 
        
    # Helper to detect if command is /start or /reg
    msg_text = event.text if isinstance(event, Message) and event.text else ""
    is_auth_cmd = msg_text.startswith("/start") or msg_text.startswith("/reg")
    
    # If not registered and not using auth commands, block
    if not u['registered'] and not is_auth_cmd:
        if isinstance(event, Message):
            await event.answer("⛔ <b>Вы не зарегистрированы!</b>\nВведите /reg для создания аккаунта.")
        return

    return await handler(event, data)

# --- COMMANDS ---

@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    u = get_user(message.from_user.id)
    
    if not u['registered']:
        await message.answer("👋 <b>Привет!</b> Чтобы начать играть, нужно зарегистрироваться.\n\nВведите команду: /reg")
        return

    # Referral/Promo processing
    args = command.args
    if args and args.startswith("promo_"):
        code = args.split("_")[1]
        await activate_promo(message, code)
        return

    await send_main_menu(message)

async def send_main_menu(message: Message):
    txt = (
        f"🖥 <b>VIBE BET MENU</b> | BTC: {format_num(btc_rate)}$\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎲 <b>Игры:</b> Рул, Кости, Футбол, Алмазы, Мины\n"
        "⛏️ <b>Работа:</b> /work (Нужна лопата и детектор)\n"
        "🏪 <b>Магазин:</b> /shop (Инструменты)\n"
        "🖥 <b>Ферма:</b> Майнинг (Лимит 3 карты)\n"
        "🎁 <b>Бонус:</b> Ежечасная халява\n"
        "📈 <b>Курс BTC:</b> Меняется каждый час\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👤 Профиль | 🆘 Помощь"
    )
    try: 
        await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt)
    except: 
        await message.answer(txt)

@dp.message(Command("reg"))
async def cmd_reg(message: Message):
    u = get_user(message.from_user.id)
    if u['registered']:
        return await message.answer("✅ <b>Вы уже зарегистрированы!</b> Можете играть.")

    await message.answer("⏳ <b>Ваш аккаунт создается...</b>")
    await asyncio.sleep(1.5)
    
    # Check Subs
    is_sub = await check_subscription(message.from_user.id)
    if not is_sub:
        kb = []
        for ch in REQUIRED_CHANNELS:
            kb.append([InlineKeyboardButton(text=f"Подписаться на {ch['username']}", url=ch['link'])])
        kb.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub_reg")])
        
        return await message.answer("🔒 <b>Для завершения регистрации подпишитесь на каналы:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    
    u['registered'] = True
    await save_data()
    await message.answer("✅ <b>Регистрация успешно завершена!</b>\nПриятной игры! Жмите /start")

@dp.callback_query(F.data == "check_sub_reg")
async def check_sub_reg_cb(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        u = get_user(call.from_user.id)
        u['registered'] = True
        await save_data()
        await call.message.delete()
        await call.message.answer("✅ <b>Регистрация завершена!</b> Жмите /start")
    else:
        await call.answer("❌ Вы не подписались на все каналы!", show_alert=True)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    txt = (
        "💎 <b>ЦЕНТР ПОМОЩИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>СТАВКИ:</b>\n"
        "🔹 <code>Рул [сумма] [ставка]</code> (к, ч, з)\n"
        "🔹 <code>Кости [сумма] [ставка]</code> (больше, меньше, равно)\n"
        "🔹 <code>Футбол [сумма] [ставка]</code> (гол, мимо)\n"
        "🔹 <code>Алмазы [сумма]</code>\n"
        "🔹 <code>Мины [сумма]</code>\n\n"
        "⚒️ <b>ЭКОНОМИКА:</b>\n"
        "🔹 <code>/work</code> — Копать (30к-150к, шанс BTC)\n"
        "🔹 <code>/shop</code> — Купить лопату и детектор\n"
        "🔹 <code>Ферма</code> — Майнинг BTC\n"
        "🔹 <code>Бонус</code> — Ежечасная награда\n\n"
        "⚙️ <b>ПРОЧЕЕ:</b>\n"
        "🔹 <code>Профиль</code>, <code>Топ</code>\n"
        "🔹 <code>Перевести [ID] [Сумма]</code>\n"
        "🔹 <code>/pr [код]</code> — Промокод\n"
    )
    await message.answer(txt)

# --- SHOP COMMAND ---
@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    u = get_user(message.from_user.id)
    kb = []
    
    if not u['shovel']:
        kb.append([InlineKeyboardButton(text=f"🛒 Купить Лопату ({format_num(WORK_CONFIG['shovel_price'])}$)", callback_data="buy_tool_shovel")])
    else:
        kb.append([InlineKeyboardButton(text="✅ Лопата куплена", callback_data="ignore")])
        
    if not u['detector']:
        kb.append([InlineKeyboardButton(text=f"📡 Купить Детектор ({format_num(WORK_CONFIG['detector_price'])}$)", callback_data="buy_tool_detector")])
    else:
        kb.append([InlineKeyboardButton(text="✅ Детектор куплен", callback_data="ignore")])
        
    await message.answer("🏪 <b>МАГАЗИН ИНСТРУМЕНТОВ</b>\nЛопата и Детектор нужны для работы (/work).", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_tool_"))
async def buy_tool_cb(call: CallbackQuery):
    tool = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    price = WORK_CONFIG[f"{tool}_price"]
    
    if u['balance'] < price:
        return await call.answer("❌ Недостаточно денег!", show_alert=True)
    
    u['balance'] -= price
    u[tool] = 1
    await save_data()
    await call.answer(f"✅ {tool.capitalize()} куплен!", show_alert=True)
    await call.message.delete()
    await cmd_shop(call.message)

# --- WORK (TREASURE HUNTER) ---
@dp.message(F.text.lower().in_({"/work", "работа"}))
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    
    # Check tools
    if not u['shovel'] or not u['detector']:
        return await message.answer("❌ <b>Ошибка работы!</b>\nДля работы нужны <b>Лопата</b> И <b>Металлоискатель</b>.\nКупите их в /shop")

    # Cooldown
    now = time.time()
    if now - u['last_work'] < WORK_CONFIG['cooldown']:
        rem = int(WORK_CONFIG['cooldown'] - (now - u['last_work']))
        m, s = divmod(rem, 60)
        return await message.answer(f"⏳ <b>Отдых!</b> Работать можно через: {m} мин {s} сек")
    
    u['last_work'] = now
    
    # Reward Logic
    cash_reward = random.randint(WORK_CONFIG['reward_min'], WORK_CONFIG['reward_max'])
    u['balance'] += cash_reward
    
    # XP Logic
    xp_gain = 4 * u['lvl'] # Custom logic if needed, user said "from 1-2 need 4 exp, from 2-3 8". This means gain is fixed or requirement is fixed?
    # User said: "for each trip get 1-5 exp. from 1-2 need 4 exp, from 2-3 8, raise by 4 exp each lvl"
    
    gained_xp = random.randint(1, 5)
    u['xp'] += gained_xp
    
    lvl_up = check_level_up(u)
    
    # BTC Drop
    btc_found = 0
    if random.random() < WORK_CONFIG['btc_chance']:
        btc_found = random.uniform(WORK_CONFIG['btc_drop_range'][0], WORK_CONFIG['btc_drop_range'][1])
        u['btc'] += btc_found
    
    await save_data()
    
    txt = (
        f"⚒️ <b>СМЕНА ОКОНЧЕНА</b>\n"
        f"💵 Заработано: <b>{format_num(cash_reward)} $</b>\n"
        f"⭐ Опыт: <b>+{gained_xp} XP</b>\n"
    )
    if btc_found > 0:
        txt += f"🎁 <b>ДЖЕКПОТ!</b> Вы нашли <b>{btc_found:.4f} BTC!</b>\n"
    if lvl_up:
        txt += f"🆙 <b>НОВЫЙ УРОВЕНЬ!</b> Теперь вы {u['lvl']} lvl!\n"
        
    await message.answer(txt)

# --- ADMIN COMMANDS (REPLY SUPPORT) ---
def get_target_id(message: Message, command: CommandObject):
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    if command.args:
        try:
            return int(command.args.split()[0])
        except: return None
    return None

@dp.message(Command("hhh"))
async def admin_give_coins(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    target_id = get_target_id(message, command)
    if not target_id: return await message.answer("⚠️ Reply or ID required")
    
    try:
        amount = int(command.args.split()[-1]) # Last arg is amount
        u = get_user(target_id)
        u['balance'] += amount
        await save_data()
        await message.answer(f"✅ Выдано <b>{format_num(amount)} $</b> игроку {target_id}")
        await bot.send_message(target_id, f"💳 Администратор выдал вам <b>{format_num(amount)} $</b>")
    except: await message.answer("📝 `/hhh [ID] SUM` or Reply `/hhh SUM`")

@dp.message(Command("hhhh"))
async def admin_give_btc(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    target_id = get_target_id(message, command)
    if not target_id: return
    try:
        amount = float(command.args.split()[-1])
        u = get_user(target_id)
        u['btc'] += amount
        await save_data()
        await message.answer(f"✅ Выдано <b>{amount} BTC</b>")
    except: pass

@dp.message(Command("ban"))
async def admin_ban(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    target_id = get_target_id(message, command)
    if target_id:
        get_user(target_id)['banned'] = True
        await save_data()
        await message.answer(f"⛔ Игрок {target_id} забанен.")

@dp.message(Command("unban"))
async def admin_unban(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    target_id = get_target_id(message, command)
    if target_id:
        get_user(target_id)['banned'] = False
        await save_data()
        await message.answer(f"✅ Игрок {target_id} разбанен.")

# --- PROFILE & BONUS ---
@dp.message(F.text.lower().in_({"профиль", "я", "profile"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    req_xp = u['lvl'] * 4
    txt = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.8f} BTC</b> (~{format_num(u['btc']*btc_rate)}$)\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{req_xp} XP)\n"
        f"🎒 Инструменты: {'✅' if u['shovel'] else '❌'} {'✅' if u['detector'] else '❌'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(txt)

@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    u = get_user(message.from_user.id)
    now = time.time()
    if now - u['last_bonus'] < 3600:
        return await message.answer(f"⏳ Бонус раз в час!")
    
    base = random.randint(10000, 50000)
    extra = u['lvl'] * 1000
    total = base + extra
    
    u['balance'] += total
    u['last_bonus'] = now
    
    await save_data()
    await message.answer(f"🎁 <b>Бонус: {format_num(total)} $</b>")

@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    try:
        args = message.text.split()
        target_id = int(args[1])
        amount = parse_amount(args[2], get_user(message.from_user.id)['balance'])
        
        sender = get_user(message.from_user.id)
        if not amount or amount <= 0 or amount > sender['balance']: return await message.answer("❌ Ошибка суммы")
        
        receiver = get_user(target_id)
        sender['balance'] -= amount
        receiver['balance'] += amount
        await save_data()
        await message.answer("✅ Перевод успешен!")
        await bot.send_message(target_id, f"💸 Вам пришло {format_num(amount)} $")
    except: pass

@dp.message(Command("pr"))
async def cmd_pr(message: Message, command: CommandObject):
    if not command.args: return
    await activate_promo(message, command.args)

async def activate_promo(message: Message, code: str):
    u = get_user(message.from_user.id)
    if code in promos and code not in u['used_promos'] and promos[code]['uses'] > 0:
        promos[code]['uses'] -= 1
        r = promos[code]['reward']
        u['balance'] += r
        u['used_promos'].append(code)
        await save_data()
        await message.answer(f"✅ Промокод на {format_num(r)} $ активирован!")
    else:
        await message.answer("❌ Неверный или использованный код.")

@dp.message(F.text.lower().startswith("создать промо"))
async def cmd_create_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        code, reward, uses = args[2], int(args[3]), int(args[4])
        promos[code] = {"reward": reward, "uses": uses}
        await save_data()
        await message.answer(f"✅ Промокод `{code}` создан.")
    except: pass

# ================= GAMES =================

# --- ROULETTE ---
@dp.message(F.text.lower().startswith("рул"))
async def game_roul(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    try:
        if len(args) < 3: raise ValueError
        bet = parse_amount(args[1], u['balance'])
        c = args[2] # choice
        
        # Normalize input
        if c in ["кр", "к", "red", "красный", "крас"]: choice = "red"
        elif c in ["ч", "чер", "black", "черный", "черн"]: choice = "black"
        elif c in ["з", "зел", "green", "зеленый"]: choice = "green"
        elif c in ["чет", "even"]: choice = "even"
        elif c in ["нечет", "odd"]: choice = "odd"
        elif c.isdigit() and 0 <= int(c) <= 36: choice = int(c)
        else: return await message.answer("❌ Ставка: кр, чер, зел, чет, нечет, 0-36")

        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Неверная ставка!")
        
        u['balance'] -= bet
        n = random.randint(0, 36)
        
        # Determine result properties
        if n == 0: color = "green"
        elif n in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]: color = "red"
        else: color = "black"
        parity = "even" if n != 0 and n % 2 == 0 else "odd" if n != 0 else ""
        
        win = 0
        if choice == "red" and color == "red": win = bet * 2
        elif choice == "black" and color == "black": win = bet * 2
        elif choice == "green" and color == "green": win = bet * 14
        elif choice == "even" and parity == "even": win = bet * 2
        elif choice == "odd" and parity == "odd": win = bet * 2
        elif isinstance(choice, int) and choice == n: win = bet * 36
        
        u['balance'] += win
        
        col_disp = "🔴" if color == "red" else "⚫" if color == "black" else "🟢"
        res_text = f"🎉 <b>Выигрыш: {format_num(win)} $</b>" if win > 0 else "❌ <b>Проигрыш</b>"
        
        await message.reply(
            f"🎰 <b>Рулетка</b>\n"
            f"Выпало: {col_disp} <b>{n}</b>\n"
            f"{res_text}\n"
            f"💰 Баланс: {format_num(u['balance'])} $"
        )
        await save_data()
    except Exception: 
        await message.answer("❌ Ошибка! Используйте: <code>рул 10к кр</code>")

# --- КОСТИ ---
@dp.message(F.text.lower().startswith("кости"))
async def game_dice_real(message: Message):
    u = get_user(message.from_user.id)
    args = message.text.lower().split()
    try:
        bet = parse_amount(args[1], u['balance'])
        outcome = args[2]
        
        if outcome in ["равно", "=", "7"]: type_ = "eq"
        elif outcome in ["больше", "б", ">"]: type_ = "over"
        elif outcome in ["меньше", "м", "<"]: type_ = "under"
        else: return await message.answer("❌ Ставки: больше, меньше, равно")
        
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Недостаточно средств!")
        
        u['balance'] -= bet
        m1 = await message.answer_dice("🎲")
        m2 = await message.answer_dice("🎲")
        await asyncio.sleep(3.5)
        
        val = m1.dice.value + m2.dice.value
        win_mult = 0
        if type_ == "eq" and val == 7: win_mult = 5.0
        elif type_ == "over" and val > 7: win_mult = 2.0
        elif type_ == "under" and val < 7: win_mult = 2.0
        
        win = int(bet * win_mult)
        u['balance'] += win
        res = "🎉 Победа" if win > 0 else "❌ Проигрыш"
        
        await message.reply(f"🎲 Сумма: <b>{val}</b>\n{res}: {format_num(win)}$\n💰 Баланс: {format_num(u['balance'])}$")
        await save_data()
    except: await message.answer("📝 Пример: <code>Кости 1000 больше</code>")

# --- АЛМАЗЫ (FIXED) ---
@dp.message(F.text.lower().startswith("алмазы"))
async def game_dia_start(message: Message):
    u = get_user(message.from_user.id)
    try:
        bet = parse_amount(message.text.split()[1], u['balance'])
        if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Недостаточно средств!")
        
        u['balance'] -= bet
        gid = f"dm_{message.from_user.id}_{int(time.time())}"
        
        # Начальный множитель на 2-й ход будет 1.21
        active_games[gid] = {
            "type": "dm", "uid": message.from_user.id, "bet": bet, 
            "round": 0, "mult": 1.21, "history": []
        }
        
        await message.answer(
            f"💎 <b>АЛМАЗЫ</b>\n💰 Ставка: {format_num(bet)} $\n👇 Выберите ячейку (раунд 1):", 
            reply_markup=get_dia_kb(gid, 0)
        )
        await save_data()
    except: await message.answer("📝 Пример: <code>Алмазы 1000</code>")

def get_dia_kb(gid, round_num, finished=False, dead_idx=None):
    btns = []
    row = []
    for i in range(3):
        txt = "📦"
        cb = f"dm_go_{gid}_{i}"
        if finished:
            txt = "💀" if i == dead_idx else "💎"
            cb = "ignore"
        row.append(InlineKeyboardButton(text=txt, callback_data=cb))
    btns.append(row)
    
    if not finished:
        if round_num == 0:
            btns.append([InlineKeyboardButton(text="🔙 ОТМЕНИТЬ ИГРУ", callback_data=f"dm_cancel_{gid}")])
        else:
            btns.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ ВЫИГРЫШ", callback_data=f"dm_take_{gid}")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

@dp.callback_query(F.data.startswith("dm_"))
async def dia_handler(call: CallbackQuery):
    parts = call.data.split("_")
    action = parts[1]
    gid = "_".join(parts[2:-1]) if action == "go" else "_".join(parts[2:])
    game = active_games.get(gid)
    if not game: return await call.answer("Игра не найдена")
    
    if action == "cancel":
        get_user(game['uid'])['balance'] += game['bet']
        del active_games[gid]
        await call.message.edit_text("✅ Игра отменена, ставка возвращена.")
        return

    if action == "take":
        current_win = int(game['bet'] * (game['mult'] - 0.35))
        get_user(game['uid'])['balance'] += current_win
        await call.message.edit_text(f"💰 <b>Вы забрали: {format_num(current_win)} $</b>")
        del active_games[gid]
        await save_data()
        return

    if action == "go":
        dead = random.randint(0, 2)
        idx = int(parts[-1])
        
        if idx == dead:
            await call.message.edit_text(f"💀 <b>Бомба!</b> Вы проиграли {format_num(game['bet'])} $", 
                                         reply_markup=get_dia_kb(gid, 0, True, dead))
            del active_games[gid]
        else:
            m = game['mult']
            game['mult'] += 0.35
            game['round'] += 1
            await call.message.edit_text(
                f"💎 <b>Успех! Раунд {game['round']}</b>\nМножитель: <b>x{m:.2f}</b>\nТекущий выигрыш: <b>{format_num(int(game['bet']*m))} $</b>",
                reply_markup=get_dia_kb(gid, game['round'])
            )
        await save_data()

# --- МИНЫ (FIXED) ---
@dp.message(F.text.lower().startswith("мины"))
async def game_mines_start(message: Message):
    u = get_user(message.from_user.id)
    try:
        bet = parse_amount(message.text.split()[1], u['balance'])
        if bet < 10 or bet > u['balance']: return await message.answer("❌ Недостаточно средств!")
        
        u['balance'] -= bet
        grid = [False]*25
        mines = random.sample(range(25), 3)
        for m in mines: grid[m] = True
        
        gid = f"mn_{message.from_user.id}_{int(time.time())}"
        active_games[gid] = {"type":"mines", "uid":message.from_user.id, "bet":bet, "grid":grid, "opened":[False]*25, "mult":1.0}
        
        await message.answer(f"💣 <b>МИНЫ</b>\nСтавка: {format_num(bet)}$", 
                             reply_markup=get_mines_kb(gid, [False]*25))
        await save_data()
    except: await message.answer("📝 Пример: <code>Мины 1000</code>")

def get_mines_kb(gid, opened, finish=False, grid=None):
    kb = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r*5+c
            txt = "⬜️"
            cbd = f"mn_click_{gid}_{idx}"
            if opened[idx]: txt = "💎"; cbd = "ignore"
            if finish:
                cbd = "ignore"
                if grid[idx]: txt = "💣"
                elif opened[idx]: txt = "💎"
                else: txt = "🔹"
            row.append(InlineKeyboardButton(text=txt, callback_data=cbd))
        kb.append(row)
    if not finish: kb.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"mn_stop_{gid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("mn_"))
async def mines_callback(call: CallbackQuery):
    data = call.data.split("_")
    action = data[1]
    gid = "_".join(data[2:-1]) if action == "click" else "_".join(data[2:])
    game = active_games.get(gid)
    if not game: return
    
    if action == "stop":
        win = int(game['bet'] * game['mult'])
        get_user(game['uid'])['balance'] += win
        await call.message.edit_text(f"💰 <b>Выигрыш: {format_num(win)} $</b>", 
                                     reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
        del active_games[gid]
        await save_data()
        return

    idx = int(data[-1])
    if game['grid'][idx]:
        await call.message.edit_text(f"💥 <b>БА-БАХ!</b> Вы проиграли ставку.", 
                                     reply_markup=get_mines_kb(gid, game['opened'], True, game['grid']))
        del active_games[gid]
    else:
        game['opened'][idx] = True
        game['mult'] += 0.35
        await call.message.edit_text(f"💎 <b>МИНЫ</b> | x{game['mult']:.2f}", reply_markup=get_mines_kb(gid, game['opened']))
    await save_data()

# --- ФЕРМА (FIXED) ---
def get_farm_stats(u):
    now = time.time()
    last = u['farm'].get('last_collect', now)
    btc_hour = 0
    for k, v in FARM_CONFIG.items():
        btc_hour += u['farm'].get(k, 0) * v['income']
    pending = (btc_hour / 3600) * (now - last)
    return pending, btc_hour

@dp.message(F.text.lower() == "ферма")
async def cmd_farm(message: Message):
    u = get_user(message.from_user.id)
    pending, hourly = get_farm_stats(u)
    txt = (
        f"🖥 <b>ВАША ФЕРМА</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 RTX 3060: {u['farm'].get('rtx3060', 0)}/3\n"
        f"💳 RTX 4070: {u['farm'].get('rtx4070', 0)}/3\n"
        f"💳 RTX 4090: {u['farm'].get('rtx4090', 0)}/3\n\n"
        f"⛏️ Майнинг: <b>{hourly:.6f} BTC/ч</b>\n"
        f"💰 Доход: <b>{pending:.8f} BTC</b>"
    )
    kb = [
        [InlineKeyboardButton(text="💰 Собрать доход", callback_data="farm_menu_collect")],
        [InlineKeyboardButton(text="🛒 Магазин карт", callback_data="farm_menu_shop")]
    ]
    await message.answer(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "farm_menu_collect")
async def farm_coll_menu(call: CallbackQuery):
    pending, _ = get_farm_stats(get_user(call.from_user.id))
    kb = [[InlineKeyboardButton(text="✅ Подтвердить", callback_data="farm_do_collect")],
          [InlineKeyboardButton(text="🔙 Назад", callback_data="farm_back")]]
    await call.message.edit_text(f"💰 Доступно: {pending:.8f} BTC\nЖелаете собрать?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "farm_do_collect")
async def farm_do_coll(call: CallbackQuery):
    u = get_user(call.from_user.id)
    pending, _ = get_farm_stats(u)
    if pending < 0.00000001: return await call.answer("⚠️ Пусто!")
    u['btc'] += pending
    u['farm']['last_collect'] = time.time()
    await save_data()
    await call.answer("✅ Доход собран!")
    await farm_back(call)

@dp.callback_query(F.data == "farm_menu_shop")
async def farm_shop(call: CallbackQuery):
    u = get_user(call.from_user.id)
    kb = []
    for k, v in FARM_CONFIG.items():
        count = u['farm'].get(k, 0)
        price = int(v['base_price'] * (1.2 ** count))
        btn_text = f"{v['name']} ({count}/3) - {format_num(price)}$"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"farm_buy_{k}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="farm_back")])
    await call.message.edit_text("🛍 <b>МАГАЗИН ВИДЕОКАРТ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("farm_buy_"))
async def farm_buy_act(call: CallbackQuery):
    item = call.data.split("_")[2]
    u = get_user(call.from_user.id)
    count = u['farm'].get(item, 0)
    if count >= 3: return await call.answer("❌ Лимит 3 карты!", show_alert=True)
    
    price = int(FARM_CONFIG[item]['base_price'] * (1.2 ** count))
    if u['balance'] < price: return await call.answer("❌ Нет денег!", show_alert=True)
    
    u['balance'] -= price
    u['farm'][item] = count + 1
    await save_data()
    await call.answer("✅ Куплено!")
    await farm_shop(call)

@dp.callback_query(F.data == "farm_back")
async def farm_back(call: CallbackQuery):
    await call.message.delete()
    await cmd_farm(call.message)

# --- ТОП ---
@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    sorted_users = sorted(users.items(), key=lambda i: i[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>ТОП 10 МАЖОРОВ:</b>\n\n"
    for i, (uid, u) in enumerate(sorted_users):
        txt += f"{i+1}. {u['name']} — <b>{format_num(u['balance'])} $</b>\n"
    await message.answer(txt)

# --- АДМИН-КОМАНДЫ (С REPLAY) ---
def get_admin_target(message, command):
    if message.reply_to_message: return message.reply_to_message.from_user.id
    if command.args:
        try: return int(command.args.split()[0])
        except: return None
    return None

@dp.message(Command("hhh"))
async def adm_give_money(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    tid = get_admin_target(message, command)
    if not tid: return
    try:
        val = int(command.args.split()[-1])
        get_user(tid)['balance'] += val
        await save_data()
        await message.answer(f"✅ Выдано {format_num(val)}$")
    except: pass

@dp.message(Command("hhhh"))
async def adm_give_btc(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    tid = get_admin_target(message, command)
    if not tid: return
    try:
        val = float(command.args.split()[-1])
        get_user(tid)['btc'] += val
        await save_data()
        await message.answer(f"✅ Выдано {val} BTC")
    except: pass

@dp.message(Command("ban"))
async def adm_ban(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS: return
    tid = get_admin_target(message, command)
    if tid:
        get_user(tid)['banned'] = True
        await save_data()
        await message.answer("⛔ Пользователь забанен.")

# --- ЗАПУСК ---
async def main():
    sync_load()
    # Обновление рынка BTC каждый час
    scheduler.add_job(update_btc_market, 'interval', hours=1)
    scheduler.start()
    
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Running"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
