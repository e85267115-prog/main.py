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
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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
BOT_USERNAME = "VibeBetBot" 

# Каналы для проверки (замените ID если нужно)
REQUIRED_CHANNELS = [
    {"id": -1002488804797, "url": "https://t.me/nvibee_bet", "name": "Канал Vibe"},
    {"id": -1002447915995, "url": "https://t.me/chatvibee_bet", "name": "Чат Vibe"}
]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

users = {}
promos = {}
active_games = {} 

FARM_CONFIG = {
    "rtx3060": {"name": "RTX 3060", "base_price": 150000, "income": 0.00001, "scale": 1.2, "limit": 3},
    "rtx4070": {"name": "RTX 4070", "base_price": 220000, "income": 0.00004, "scale": 1.2, "limit": 3},
    "rtx4090": {"name": "RTX 4090", "base_price": 350000, "income": 0.00007, "scale": 1.3, "limit": 3}
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
    except Exception as e: logging.error(f"Error loading: {e}")

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        data_to_save = {"users": users, "promos": promos}
        with open("db.json", "w", encoding="utf-8") as f: 
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e: logging.error(f"Error saving: {e}")

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

def parse_amount(text, balance=0):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all", "вабанк"]: return int(balance)
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
            "name": name, "balance": 5000, "btc": 0.0, "lvl": 1, "xp": 0,
            "shovel": 0, "last_work": 0, "last_bonus": 0, "used_promos": [],
            "farm": {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
        }
    return users[uid]

async def check_sub(user_id):
    for ch in REQUIRED_CHANNELS:
        try:
            m = await bot.get_chat_member(ch['id'], user_id)
            if m.status in ["left", "kicked"]: return False
        except: return False
    return True

# --- MIDDLEWARE ---
@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def sub_check_mw(handler, event, data):
    uid = event.from_user.id
    if not await check_sub(uid):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=ch['name'], url=ch['url'])] for ch in REQUIRED_CHANNELS])
        msg = "⚠️ <b>Для работы бота необходимо подписаться на канал и чат!</b>"
        if isinstance(event, Message): await event.answer(msg, reply_markup=kb)
        else: await event.answer(msg, show_alert=True)
        return
    return await handler(event, data)

# --- МЕНЮ И СТАРТ ---
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    if command.args and command.args.startswith("promo_"):
        await activate_promo(message, command.args.split("_")[1]); return
    
    txt = (
        "👋 <b>Добро Пожаловать в Vibe Bet!</b>\n"
        "Крути рулетку, рискуй в Краше, а также собирай свою ферму.\n\n"
        "🎲 <b>Игры:</b> 🎲 Кости, ⚽ Футбол, 🎰 Рулетка, 💎 Алмазы, 💣 Мины\n"
        "⛏️ <b>Заработок:</b> 👷 Работа, 🖥 Ферма BTC, 🎁 Бонус\n\n"
        "👇 Жми Помощь для списка команд!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❓ Помощь", callback_data="help")]])
    await message.answer(txt, reply_markup=kb)

@dp.message(F.text.lower() == "помощь")
@dp.callback_query(F.data == "help")
async def cmd_help(event):
    txt = (
        "💎 <b>ЦЕНТР ПОМОЩИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>СТАВКИ:</b>\n"
        "🔹 Рул [сумма] [число/цвет] (кр, чер, зел)\n"
        "🔹 Кости [сумма] [ставка] (равно, больше, меньше)\n"
        "🔹 Футбол [сумма] [ставка] (гол, мимо)\n"
        "🔹 Алмазы [сумма] [бомбы] (1 или 2)\n"
        "🔹 Мины [сумма]\n\n"
        "⛏️ <b>ЗАРАБОТОК:</b>\n"
        "🔹 Работа — Копать клад (нужна лопата)\n"
        "🔹 Ферма — Майнинг биткоина\n"
        "🔹 Бонус — Ежечасная награда\n\n"
        "⚙️ <b>ПРОЧЕЕ:</b>\n"
        "🔹 Профиль, Топ\n"
        "🔹 Перевести [ID] [Сумма]\n"
        "🔹 /pr [код] — Активация промо\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    if isinstance(event, Message): await event.answer(txt)
    else: await event.message.answer(txt); await event.answer()

# --- ПРОФИЛЬ И ТОП ---
@dp.message(F.text.lower().in_({"профиль", "я"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    await message.answer(
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 BTC: <b>{u['btc']:.6f}</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b>\n"
        f"🎒 Лопата: {'✅' if u['shovel'] else '❌'}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )

@dp.message(F.text.lower() == "топ")
async def cmd_top(message: Message):
    top = sorted(users.items(), key=lambda i: i[1]['balance'], reverse=True)[:10]
    res = "🏆 <b>ТОП 10 МАЖОРОВ:</b>\n\n"
    for i, (uid, u) in enumerate(top):
        res += f"{i+1}. <code>{uid}</code> — <b>{format_num(u['balance'])} $</b>\n"
    await message.answer(res)

# --- ИГРЫ (ФУТБОЛ, КОСТИ, РУЛЕТКА) ---
@dp.message(F.text.lower().startswith("футбол"))
async def game_football(message: Message):
    u = get_user(message.from_user.id); args = message.text.lower().split()
    if len(args) < 3: return await message.answer("📝: <code>Футбол [сумма] [гол/мимо]</code>")
    bet = parse_amount(args[1], u['balance'])
    choice = args[2]
    if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ошибка ставки!")
    if choice not in ["гол", "мимо"]: return await message.answer("❌ Выберите: гол или мимо")
    
    u['balance'] -= bet
    msg = await message.answer_dice(emoji="⚽")
    await asyncio.sleep(3.5)
    
    is_goal = msg.dice.value in [3, 4, 5]
    win = 0
    if choice == "гол" and is_goal: win = int(bet * 1.8)
    elif choice == "мимо" and not is_goal: win = int(bet * 2.3)
    
    u['balance'] += win; await save_data()
    txt = f"⚽ <b>{'ГООООЛ!' if is_goal else 'МИМО!'}</b>\n"
    txt += f"{'🎉 Выигрыш: ' + format_num(win) + '$' if win else '❌ Проигрыш'}"
    await message.answer(txt)

@dp.message(F.text.lower().startswith("кости"))
async def game_dice(message: Message):
    u = get_user(message.from_user.id); args = message.text.lower().split()
    if len(args) < 3: return await message.answer("📝: <code>Кости [сумма] [равно/больше/меньше]</code>")
    bet = parse_amount(args[1], u['balance'])
    choice = args[2]
    if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ошибка ставки!")
    if choice not in ["равно", "больше", "меньше"]: return await message.answer("❌ Ставка: равно, больше или меньше")
    
    u['balance'] -= bet
    d1 = await message.answer_dice(emoji="🎲")
    d2 = await message.answer_dice(emoji="🎲")
    await asyncio.sleep(3.5)
    
    total = d1.dice.value + d2.dice.value
    win = 0
    if choice == "равно" and total == 7: win = int(bet * 5.8)
    elif choice == "больше" and total > 7: win = int(bet * 2.3)
    elif choice == "меньше" and total < 7: win = int(bet * 2.3)
    
    u['balance'] += win; await save_data()
    res = f"🎲 Сумма: <b>{total}</b>\n"
    res += f"{'🎉 Выигрыш: ' + format_num(win) + '$' if win else '❌ Проигрыш'}"
    await message.answer(res)

@dp.message(F.text.lower().startswith("рул"))
async def game_roul(message: Message):
    u = get_user(message.from_user.id); args = message.text.lower().split()
    if len(args) < 3: return await message.answer("📝: <code>Рул [сумма] [кр/чер/зел/0-36]</code>")
    bet = parse_amount(args[1], u['balance'])
    choice = args[2]
    if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ошибка ставки!")
    
    u['balance'] -= bet
    n = random.randint(0, 36)
    color = "зеленый" if n==0 else "красный" if n in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный"
    
    win = 0
    if choice in ["кр", "красный"] and color == "красный": win = bet * 2
    elif choice in ["чер", "черный"] and color == "черный": win = bet * 2
    elif choice in ["зел", "зеленый"] and color == "зеленый": win = bet * 14
    elif choice.isdigit() and int(choice) == n: win = bet * 36
    
    u['balance'] += win; await save_data()
    await message.answer(f"🎰 Выпало: <b>{n} ({color})</b>\n{'🎉 +'+format_num(win)+'$' if win else '❌ Проигрыш'}")

# --- АЛМАЗЫ (БАШНЯ) ---
def get_tower_kb(gid, lvl, rows, finished=False):
    kb = []
    for i in range(len(rows)-1, -1, -1):
        r = []
        for j in range(3):
            txt = "⬜️"
            call = "ignore"
            if finished:
                if rows[i]['bomb'] == j: txt = "💣"
                elif rows[i].get('choice') == j: txt = "💎"
            elif i < lvl:
                if rows[i].get('choice') == j: txt = "💎"
            elif i == lvl:
                txt = "📦"; call = f"tw_s_{gid}_{j}"
            r.append(InlineKeyboardButton(text=txt, callback_data=call))
        kb.append(r)
    if not finished: kb.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"tw_c_{gid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(F.text.lower().startswith("алмазы"))
async def game_tower(message: Message):
    u = get_user(message.from_user.id); args = message.text.split()
    if len(args) < 2: return await message.answer("📝: <code>Алмазы [сумма] [бомбы 1-2]</code>")
    bet = parse_amount(args[1], u['balance'])
    bombs = int(args[2]) if len(args) > 2 and args[2] in ["1", "2"] else 1
    if not bet or bet < 10 or bet > u['balance']: return await message.answer("❌ Ставка?")
    
    u['balance'] -= bet
    gid = f"tw_{message.from_user.id}_{int(time.time())}"
    active_games[gid] = {
        "uid": message.from_user.id, "bet": bet, "lvl": 0, "mult": 1.2, 
        "b_count": bombs, "rows": [{"bomb": random.randint(0,2)}]
    }
    await message.answer(f"💎 <b>АЛМАЗЫ</b>\nМножитель: x1.2", reply_markup=get_tower_kb(gid, 0, active_games[gid]['rows']))

@dp.callback_query(F.data.startswith("tw_"))
async def tower_cb(call: CallbackQuery):
    p = call.data.split("_"); gid = "_".join(p[2:-1]) if p[1]=="s" else "_".join(p[2:])
    g = active_games.get(gid)
    if not g or g['uid'] != call.from_user.id: return
    
    if p[1] == "c":
        w = int(g['bet'] * g['mult']); get_user(g['uid'])['balance'] += w
        await call.message.edit_text(f"✅ Вы забрали: <b>{format_num(w)} $</b>", reply_markup=get_tower_kb(gid, g['lvl'], g['rows'], True))
        del active_games[gid]; await save_data(); return
    
    choice = int(p[-1])
    if choice == g['rows'][g['lvl']]['bomb']:
        await call.message.edit_text(f"💥 БАБАХ! Вы проиграли <b>{format_num(g['bet'])} $</b>", reply_markup=get_tower_kb(gid, g['lvl'], g['rows'], True))
        del active_games[gid]; await save_data()
    else:
        g['rows'][g['lvl']]['choice'] = choice; g['lvl'] += 1
        g['mult'] = round(g['mult'] + (0.5 if g['b_count'] == 1 else 1.2), 1)
        g['rows'].append({"bomb": random.randint(0,2)})
        await call.message.edit_text(f"💎 <b>АЛМАЗЫ</b>\nМножитель: x{g['mult']}", reply_markup=get_tower_kb(gid, g['lvl'], g['rows']))

# --- ЗАРАБОТОК (РАБОТА, ФЕРМА, БОНУС) ---
@dp.message(F.text.lower() == "работа")
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    if time.time() - u['last_work'] < 600: return await message.answer("⏳ Работать можно раз в 10 минут!")
    
    gain = random.randint(5000, 15000) * u['lvl']
    res = f"👷 Вы поработали и получили <b>{format_num(gain)}$</b>"
    if u['shovel'] and random.random() < 0.3:
        bonus = gain * 2; gain += bonus
        res += f"\n🎁 Лопата помогла найти клад: <b>+{format_num(bonus)}$</b>"
    
    u['balance'] += gain; u['last_work'] = time.time(); await save_data()
    await message.answer(res)

@dp.message(F.text.lower() == "ферма")
async def cmd_farm(message: Message):
    u = get_user(message.from_user.id)
    inc = sum(u['farm'][k] * FARM_CONFIG[k]['income'] for k in FARM_CONFIG)
    earned = (time.time() - u['farm']['last_collect']) * (inc / 3600)
    
    txt = f"🖥 <b>BTC ФЕРМА</b>\n"
    for k, v in FARM_CONFIG.items(): txt += f"🔹 {v['name']}: {u['farm'][k]}/3\n"
    txt += f"\n💰 Намайнено: <b>{earned:.6f} BTC</b>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Собрать", callback_data="f_collect")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="f_shop")]
    ])
    await message.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "f_collect")
async def f_collect_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    inc = sum(u['farm'][k] * FARM_CONFIG[k]['income'] for k in FARM_CONFIG)
    earned = (time.time() - u['farm']['last_collect']) * (inc / 3600)
    if earned < 0.000001: return await call.answer("❌ Слишком мало!", show_alert=True)
    u['btc'] += earned; u['farm']['last_collect'] = time.time(); await save_data()
    await call.answer(f"✅ Собрано {earned:.6f} BTC"); await cmd_farm(call.message)

@dp.callback_query(F.data == "f_shop")
async def f_shop_cb(call: CallbackQuery):
    u = get_user(call.from_user.id); kb = []
    for k, v in FARM_CONFIG.items():
        price = int(v['base_price'] * (v['scale'] ** u['farm'][k]))
        kb.append([InlineKeyboardButton(text=f"{v['name']} ({format_num(price)}$)", callback_data=f"fbuy_{k}")])
    kb.append([InlineKeyboardButton(text="Лопата (500к)", callback_data="buy_shovel")])
    await call.message.edit_text("🛒 <b>МАГАЗИН</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("fbuy_"))
async def f_buy_cb(call: CallbackQuery):
    u = get_user(call.from_user.id); k = call.data.split("_")[1]
    if u['farm'][k] >= 3: return await call.answer("❌ Лимит 3 карты!")
    price = int(FARM_CONFIG[k]['base_price'] * (FARM_CONFIG[k]['scale'] ** u['farm'][k]))
    if u['balance'] < price: return await call.answer("❌ Нет денег!")
    u['balance'] -= price; u['farm'][k] += 1; await save_data()
    await call.answer("✅ Куплено!"); await f_shop_cb(call)

@dp.callback_query(F.data == "buy_shovel")
async def buy_shovel_cb(call: CallbackQuery):
    u = get_user(call.from_user.id)
    if u['balance'] < 500000: return await call.answer("❌ Нужно 500к!")
    u['balance'] -= 500000; u['shovel'] = 1; await save_data()
    await call.answer("✅ Лопата куплена!"); await call.message.delete()

# --- ПРОМОКОДЫ ---
@dp.message(F.text.lower().startswith("создать промо"))
async def cmd_create_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        args = message.text.split()
        code, reward, uses = args[2], parse_amount(args[3]), int(args[4])
        promos[code] = {"reward": reward, "uses": uses}
        await save_data()
        link = f"t.me/{BOT_USERNAME}?start=promo_{code}"
        await message.answer(
            f"Пpомокод <b>{code}</b> создан! ТЫК ДЛЯ АКТИВАЦИИ\n"
            f"Начисление: {format_num(reward)} монет\n"
            f"Активаций: {uses}\n\n"
            f"Чтобы активировать: <code>/pr {code}</code>\n"
            f"Или ссылка: {link}"
        )
    except: await message.answer("📝 Создать промо [код] [сумма] [кол-во]")

async def activate_promo(message: Message, code: str):
    u = get_user(message.from_user.id)
    if code not in promos or promos[code]['uses'] <= 0: return await message.answer("❌ Промокод не найден")
    if code in u['used_promos']: return await message.answer("❌ Вы уже его использовали")
    u['balance'] += promos[code]['reward']; u['used_promos'].append(code); promos[code]['uses'] -= 1
    await save_data(); await message.answer(f"✅ Активировано! +{format_num(promos[code]['reward'])} $")

@dp.message(Command("pr"))
async def cmd_pr(m: Message, c: CommandObject):
    if c.args: await activate_promo(m, c.args)

# --- АДМИНКА (ВЫДАЧА) ---
@dp.message(F.text.lower().startswith("выдать"))
async def admin_give(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split()
    try:
        if message.reply_to_message:
            uid = message.reply_to_message.from_user.id
            amt = parse_amount(args[1])
        else:
            uid = int(args[1]); amt = parse_amount(args[2])
        get_user(uid)['balance'] += amt; await save_data()
        await message.answer(f"✅ {format_num(amt)}$ выдано <code>{uid}</code>")
    except: await message.answer("📝 Выдать [ID] [сумма] или Реплаем")

# --- ЗАПУСК ---
async def main():
    sync_load()
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="Bot Active"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
