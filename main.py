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

# --- КОНФИГ (Ваши данные) ---
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
active_games = {} # Для хранения состояния игры "Алмазы"

FARM_CONFIG = {
    "rtx3060": {"name": "RTX 3060", "price": 150000, "income": 0.1, "scale": 1.2},
    "rtx4070": {"name": "RTX 4070", "price": 220000, "income": 0.4, "scale": 1.2},
    "rtx4090": {"name": "RTX 4090", "price": 350000, "income": 0.7, "scale": 1.3}
}

# --- СИСТЕМА СОХРАНЕНИЯ (Google Drive) ---
def get_drive_service():
    if not os.path.exists(CREDENTIALS_FILE): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

def sync_load():
    global users, promos
    service = get_drive_service()
    if not service: return
    try:
        request = service.files().get_media(fileId=DRIVE_FILE_ID)
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        data = json.loads(fh.getvalue().decode('utf-8'))
        users = {int(k): v for k, v in data.get("users", {}).items()}
        promos = data.get("promos", {})
    except Exception as e: print(f"Load error: {e}")

def sync_save():
    service = get_drive_service()
    if not service: return
    try:
        data = {"users": users, "promos": promos}
        with open("db.json", "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)
        media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e: print(f"Save error: {e}")

async def save_data(): await asyncio.to_thread(sync_save)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def format_num(num):
    num = float(num)
    if num < 1000: return str(int(num))
    for unit in ['', 'к', 'кк', 'ккк', 'кккк']:
        if abs(num) < 1000.0: return f"{num:3.2f}{unit}".replace(".00", "")
        num /= 1000.0
    return f"{num:.2f}кккк"

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all"]: return int(balance)
    mult = {"к": 1e3, "кк": 1e6, "ккк": 1e9, "кккк": 1e12}
    for s, m in mult.items():
        if text.endswith(s):
            try: return int(float(text[:-len(s)]) * m)
            except: pass
    try: return int(float(text))
    except: return None

def get_user(uid, name="Игрок"):
    uid = int(uid)
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 5000, "bank": 0, "btc": 0.0, "lvl": 1, "xp": 0,
            "banned": False, "last_bonus": 0, "used_promos": [],
            "farm": {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
        }
    if "farm" not in users[uid]: users[uid]["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": time.time()}
    return users[uid]

async def add_xp(uid, amount=1):
    u = users[uid]
    if u['lvl'] >= 100: return
    u['xp'] += amount
    while u['xp'] >= (u['lvl'] * 4):
        u['xp'] -= (u['lvl'] * 4)
        u['lvl'] += 1
        try: await bot.send_message(uid, f"✨ <b>Новый уровень: {u['lvl']}!</b>")
        except: pass

# --- КОМАНДЫ ПРОФИЛЯ И СИСТЕМЫ ---
@dp.message(CommandStart())
async def start(m: Message):
    get_user(m.from_user.id, m.from_user.first_name)
    await m.answer("👋 <b>Vibe Bet приветствует тебя!</b>\nНапиши <code>Помощь</code> для списка команд.")

@dp.message(F.text.lower() == "помощь")
async def help_cmd(m: Message):
    await m.answer(
        "🎮 <b>ИГРЫ:</b>\n"
        "└ <code>Рул [ставка] [цвет/число]</code>\n"
        "└ <code>Кости [ставка] [больше/меньше/7]</code>\n"
        "└ <code>Алмазы [ставка]</code>\n"
        "└ <code>Футбол [ставка] [гол/мимо]</code>\n\n"
        "📈 <b>БИЗНЕС:</b>\n"
        "└ <code>Ферма</code> | <code>Бонус</code>\n\n"
        "👤 <b>АККАУНТ:</b>\n"
        "└ <code>Профиль</code> | <code>Топ</code> | <code>Перевести [ID] [сумма]</code>\n"
        "└ <code>/pr [код]</code>"
    )

@dp.message(F.text.lower().in_(["профиль", "я"]))
async def profile(m: Message):
    u = get_user(m.from_user.id)
    txt = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*4} XP)\n"
        f"🆔 ID: <code>{m.from_user.id}</code>"
    )
    await m.answer(txt)

@dp.message(F.text.lower().startswith("перевести"))
async def transfer(m: Message):
    u = get_user(m.from_user.id)
    args = m.text.split()
    try:
        to_id = int(args[1]); amt = parse_amount(args[2], u['balance'])
        if to_id not in users: return await m.answer("❌ Игрок не найден.")
        if amt <= 0 or u['balance'] < amt: return await m.answer("❌ Ошибка суммы.")
        u['balance'] -= amt; users[to_id]['balance'] += amt
        await save_data()
        await m.answer(f"✅ Переведено <b>{format_num(amt)}$</b>.")
        try: await bot.send_message(to_id, f"💸 Вам пришел перевод <b>{format_num(amt)}$</b> от {u['name']}!")
        except: pass
    except: await m.answer("📝: <code>Перевести [ID] [сумма]</code>")

# --- ИГРЫ (С ФИКСАМИ) ---
@dp.message(F.text.lower().startswith("рул"))
async def game_roulette(m: Message):
    u = get_user(m.from_user.id)
    args = m.text.lower().split()
    if len(args) < 3: return await m.answer("📝: <code>Рул 1к 36</code> или <code>Рул 1к кр</code>")
    
    bet = parse_amount(args[1], u['balance'])
    choice = args[2]
    if not bet or u['balance'] < bet: return await m.answer("❌ Ошибка ставки.")
    
    num = random.randint(0, 36)
    color = "зеро" if num == 0 else ("красный" if num % 2 == 0 else "черный")
    win = 0
    
    if choice in ["кр", "красный"] and color == "красный": win = bet * 2
    elif choice in ["чр", "черный"] and color == "черный": win = bet * 2
    elif choice.isdigit() and int(choice) == num: win = bet * 36
    
    u['balance'] -= bet
    if win > 0: u['balance'] += win; res = f"🎉 <b>ВЫИГРЫШ: {format_num(win)}$</b>"; await add_xp(m.from_user.id, 1)
    else: res = "❌ <b>ПРОИГРЫШ</b>"
    
    await m.answer(f"🎰 Выпало: <b>{num} ({color})</b>\n{res}\n💰 Баланс: {format_num(u['balance'])}$")
    await save_data()

@dp.message(F.text.lower().startswith("кости"))
async def game_dice(m: Message):
    u = get_user(m.from_user.id)
    args = m.text.lower().split()
    if len(args) < 3 or args[2] not in ["больше", "меньше", "7", "б", "м"]:
        return await m.answer("📝: <code>Кости 100 больше/меньше/7</code>")
    
    bet = parse_amount(args[1], u['balance'])
    if not bet or u['balance'] < bet: return await m.answer("❌ Ошибка ставки.")
    
    u['balance'] -= bet
    d1 = await m.answer_dice("🎲"); d2 = await m.answer_dice("🎲")
    await asyncio.sleep(3.5); total = d1.dice.value + d2.dice.value
    
    win = 0
    choice = args[2]
    if choice == "7" and total == 7: win = bet * 5.8
    elif choice in ["больше", "б"] and total > 7: win = bet * 2.3
    elif choice in ["меньше", "м"] and total < 7: win = bet * 2.3
    
    if win > 0: u['balance'] += int(win); res = f"🎉 <b>ПОБЕДА: {format_num(win)}$</b>"; await add_xp(m.from_user.id, 1)
    else: res = "❌ <b>ПРОИГРЫШ</b>"
    await m.answer(f"🎲 Сумма: <b>{total}</b>\n{res}")
    await save_data()

# --- АЛМАЗЫ (ОБНОВЛЕННЫЕ) ---
@dp.message(F.text.lower().startswith("алмазы"))
async def almaz_start(m: Message):
    u = get_user(m.from_user.id)
    try:
        bet = parse_amount(m.text.split()[1], u['balance'])
        if not bet or u['balance'] < bet: return await m.answer("❌ Недостаточно средств.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 Бомба (x1.3)", callback_data=f"al_set_{bet}_1")],
            [InlineKeyboardButton(text="2 Бомбы (x2.3)", callback_data=f"al_set_{bet}_2")]
        ])
        await m.answer("💎 <b>АЛМАЗЫ:</b> Выбери количество бомб на поле (3 ячейки):", reply_markup=kb)
    except: await m.answer("📝: <code>Алмазы 1000</code>")

@dp.callback_query(F.data.startswith("al_set_"))
async def al_init(call: CallbackQuery):
    _, _, bet, count = call.data.split("_"); bet, count = int(bet), int(count)
    u = get_user(call.from_user.id)
    if u['balance'] < bet: return await call.answer("❌ Денег нет")
    
    u['balance'] -= bet
    gid = f"al_{call.from_user.id}_{int(time.time())}"
    grid = [False] * 3
    for i in random.sample(range(3), count): grid[i] = True
    
    active_games[gid] = {
        "uid": call.from_user.id, "bet": bet, "grid": grid, 
        "mult": 2.3 if count == 2 else 1.3, "add": 0.5 if count == 2 else 0.3, "bombs": count
    }
    await call.message.edit_text(f"💎 Игра началась! Множитель: <b>x{active_games[gid]['mult']}</b>", reply_markup=get_al_kb(gid))

def get_al_kb(gid, reveal=False):
    g = active_games[gid]; btns = []
    for i in range(3):
        txt = "📦"
        if reveal: txt = "💣" if g['grid'][i] else "💎"
        btns.append(InlineKeyboardButton(text=txt, callback_data=f"al_cl_{gid}_{i}"))
    kb = [btns]
    if not reveal: kb.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"al_stop_{gid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("al_cl_"))
async def al_cl(call: CallbackQuery):
    gid = call.data.split("_")[2]; idx = int(call.data.split("_")[3]); g = active_games.get(gid)
    if not g or call.from_user.id != g['uid']: return
    
    if g['grid'][idx]:
        await call.message.edit_text("💀 <b>БАБАХ! Проигрыш.</b>", reply_markup=get_al_kb(gid, True))
        del active_games[gid]; await save_data()
    else:
        g['mult'] = round(g['mult'] + g['add'], 1)
        await call.message.edit_text(f"💎 Удача! Множитель: <b>x{g['mult']}</b>", reply_markup=get_al_kb(gid))

@dp.callback_query(F.data.startswith("al_stop_"))
async def al_stop(call: CallbackQuery):
    gid = call.data.split("_")[2]; g = active_games.get(gid)
    if not g: return
    win = int(g['bet'] * g['mult']); get_user(g['uid'])['balance'] += win
    await call.message.edit_text(f"💰 <b>ВЫИГРЫШ: {format_num(win)}$</b>", reply_markup=get_al_kb(gid, True))
    await add_xp(g['uid'], 2); del active_games[gid]; await save_data()

# --- ФЕРМА (ФИКС) ---
@dp.message(F.text.lower() == "ферма")
async def farm_menu(m: Message):
    u = get_user(m.from_user.id); now = time.time()
    hr = sum(u['farm'][k] * FARM_CONFIG[k]['income'] for k in FARM_CONFIG)
    pend = (hr / 3600) * (now - u['farm']['last_collect'])
    
    txt = (
        f"🖥 <b>BTC ФЕРМА</b>\n"
        f"🔹 3060: {u['farm']['rtx3060']} шт | 4070: {u['farm']['rtx4070']} шт\n"
        f"🔹 4090: {u['farm']['rtx4090']} шт\n\n"
        f"📉 Доход: <b>{hr:.2f} BTC/ч</b>\n"
        f"💰 Намайнено: <b>{pend:.6f} BTC</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Собрать", callback_data="f_col")],
        [InlineKeyboardButton(text="🛍 Магазин", callback_data="f_shop")]
    ])
    await m.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "f_shop")
async def f_shop(call: CallbackQuery):
    u = get_user(call.from_user.id); kb = []
    for k, v in FARM_CONFIG.items():
        cnt = u['farm'][k]; price = int(v['price'] * (v['scale'] ** cnt))
        txt = f"{v['name']} - {format_num(price)}$" if cnt < 3 else f"{v['name']} (MAX)"
        kb.append([InlineKeyboardButton(text=txt, callback_data=f"f_buy_{k}" if cnt < 3 else "ignore")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="f_back")])
    await call.message.edit_text("🛍 <b>МАГАЗИН</b> (Лимит 3 шт)", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("f_buy_"))
async def f_buy(call: CallbackQuery):
    k = call.data.split("_")[2]; u = get_user(call.from_user.id)
    price = int(FARM_CONFIG[k]['price'] * (FARM_CONFIG[k]['scale'] ** u['farm'][k]))
    if u['balance'] < price: return await call.answer("❌ Нет денег", show_alert=True)
    u['balance'] -= price; u['farm'][k] += 1; await save_data(); await f_shop(call)

@dp.callback_query(F.data == "f_col")
async def f_col(call: CallbackQuery):
    u = get_user(call.from_user.id); now = time.time()
    hr = sum(u['farm'][k] * FARM_CONFIG[k]['income'] for k in FARM_CONFIG)
    pend = (hr / 3600) * (now - u['farm']['last_collect'])
    if pend < 0.000001: return await call.answer("❌ Мало BTC")
    u['btc'] += pend; u['farm']['last_collect'] = now; await save_data()
    await call.answer(f"✅ Собрано {pend:.6f} BTC"); await farm_menu(call.message)

@dp.callback_query(F.data == "f_back")
async def f_back(call: CallbackQuery): await call.message.delete(); await farm_menu(call.message)

# --- ПРОМО И БОНУС ---
@dp.message(F.text.lower().startswith("создать промо"))
async def create_promo(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    try:
        _, _, code, reward, uses = m.text.split()
        promos[code] = {"reward": parse_amount(reward, 0), "uses": int(uses)}
        await save_data(); await m.answer(f"✅ Промо <code>{code}</code> создан.")
    except: await m.answer("📝: <code>Создать промо [КОД] [СУММА] [КОЛ-ВО]</code>")

@dp.message(Command("pr"))
async def use_promo(m: Message, command: CommandObject):
    u = get_user(m.from_user.id); code = command.args
    if code in promos and code not in u['used_promos']:
        u['balance'] += promos[code]['reward']; u['used_promos'].append(code)
        promos[code]['uses'] -= 1
        if promos[code]['uses'] <= 0: del promos[code]
        await m.answer(f"✅ Активировано! +{format_num(u['balance'])}$"); await save_data()
    else: await m.answer("❌ Ошибка кода.")

@dp.message(F.text.lower() == "бонус")
async def bonus(m: Message):
    u = get_user(m.from_user.id); now = time.time()
    if now - u['last_bonus'] < 3600: return await m.answer("⏳ Бонус раз в час.")
    gain = 5000 * u['lvl']; u['balance'] += gain; u['last_bonus'] = now
    await m.answer(f"🎁 Бонус: <b>{format_num(gain)}$</b>"); await save_data()

# --- ТОП ---
@dp.message(F.text.lower() == "топ")
async def top_majors(m: Message):
    top = sorted(users.items(), key=lambda x: x[1]['balance'], reverse=True)[:10]
    txt = "🏆 <b>ТОП МАЖОРОВ:</b>\n\n"
    for i, (uid, ud) in enumerate(top):
        med = {0:"🥇", 1:"🥈", 2:"🥉"}.get(i, f"{i+1}.")
        txt += f"{med} {ud['name']} — <b>{format_num(ud['balance'])}$</b>\n"
    await m.answer(txt)

# --- АДМИН-КОМАНДЫ ---
@dp.message(F.text.lower().startswith("выдать"))
async def admin_give(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    try:
        args = m.text.split(); uid = int(args[1]); val = parse_amount(args[2], 0)
        get_user(uid)['balance'] += val; await save_data(); await m.answer("✅ Готово")
    except: pass

# --- ЗАПУСК ---
async def main():
    sync_load()
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="Bot Online"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.delete_webhook(drop_pending_updates=True); await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
