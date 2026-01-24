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

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

users = {}
promos = {}

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
    val = num / 1_000_000_000
    return f"{int(val) if val == int(val) else round(val, 2)}ккк"

def parse_amount(text, balance):
    text = str(text).lower().replace(",", ".")
    if text in ["все", "всё", "all"]: return int(balance)
    m = {"к": 1000, "кк": 1000000, "ккк": 1000000000}
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
            "name": name, "balance": 5000, "bank": 0, "btc": 0.0, 
            "lvl": 1, "xp": 0, "banned": False, 
            "shovel": 0, "detector": 0, "last_work": 0, "last_bonus": 0, "used_promos": []
        }
        asyncio.create_task(save_data())
    return users[uid]

async def get_btc_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return data['bitcoin']['usd']
    except: return 98500

# --- МИДЛВАРЬ (БАН) ---
@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def ban_check(handler, event, data):
    user_id = event.from_user.id
    u = get_user(user_id, event.from_user.first_name)
    if u.get('banned'):
        if isinstance(event, Message):
            await event.answer("🚫 <b>Доступ заблокирован!</b>")
        else:
            await event.answer("🚫 Доступ заблокирован!", show_alert=True)
        return
    return await handler(event, data)

# --- КОМАНДЫ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    txt = "Добро Пожаловать в Vibe Bet. Играй и Веселись, все это ТУТ!"
    try: await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt)
    except: await message.answer(txt)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message(Message)):
    txt = (
        "💎 <b>МЕНЮ VIBE BET</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👤 <b>ПРОФИЛЬ:</b> <code>Профиль</code>, <code>Топ</code>\n"
        "🎰 <b>ИГРЫ:</b> <code>Рул [сумма] [цвет]</code>, <code>Краш [сумма] [кэф]</code>\n"
        "⛏️ <b>РАБОТА:</b> <code>Работа</code>, <code>Магазин</code>, <code>Бонус</code>\n"
        "🏦 <b>ФИНАНСЫ:</b> <code>Банк</code>, <code>Деп [сумма]</code>, <code>Снять [сумма]</code>\n"
        "🪙 <b>БИТКОИН:</b> <code>Рынок</code>, <code>Продать биткоин [кол-во]</code>\n"
        "🎁 <b>БОНУСЫ:</b> <code>Промо [код]</code>, <code>Создать промо ...</code>\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(txt)

@dp.message(F.text.lower().in_({"профиль", "я"}))
async def cmd_profile(message: Message):
    u = get_user(message.from_user.id)
    txt = (
        f"👤 <b>АККАУНТ: {message.from_user.first_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Биткоины: <b>{u['btc']:.6f} BTC</b>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*10} XP)\n"
        f"🎒 Инструменты: {'⛏️' if u['shovel'] else '❌'} {'📡' if u['detector'] else '❌'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(txt)

# --- РАБОТА (3 ЭТАПА) ---
@dp.message(F.text.lower() == "работа")
async def work_stage1(message: Message):
    u = get_user(message.from_user.id)
    if not u['shovel'] or not u['detector']:
        return await message.answer("❌ <b>Ошибка!</b>\nКупите лопату и детектор в магазине.")
    now = datetime.now().timestamp()
    if now - u['last_work'] < 600:
        return await message.answer(f"⏳ Отдохните еще {int((600-(now-u['last_work']))//60)} мин.")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Начать поиск 🗺️", callback_data="w_scan")]])
    await message.answer("⛏️ <b>КЛАДОИСКАТЕЛЬ</b>\n━━━━━━━━━━━━\nГотовы найти сокровища?", reply_markup=kb)

@dp.callback_query(F.data == "w_scan")
async def work_stage2(call: CallbackQuery):
    await call.message.edit_text("📡 <b>СКАНИРОВАНИЕ...</b>\n━━━━━━━━━━━━\n<i>Ищем сигналы под землей...</i>")
    await asyncio.sleep(2)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⛏️ КОПАТЬ ТУТ", callback_data="w_fin")]])
    await call.message.edit_text("📍 <b>СИГНАЛ НАЙДЕН!</b>\n━━━━━━━━━━━━\nНачинаем раскопки?", reply_markup=kb)

@dp.callback_query(F.data == "w_fin")
async def work_stage3(call: CallbackQuery):
    u = get_user(call.from_user.id)
    u['last_work'] = datetime.now().timestamp()
    win = random.randint(15000, 150000)
    u['balance'] += win; u['xp'] += 3
    if u['xp'] >= u['lvl']*10: u['lvl'] += 1; u['xp'] = 0
    await save_data()
    await call.message.edit_text(f"💎 <b>УСПЕХ!</b>\n━━━━━━━━━━━━\n💰 Найдено: <b>{format_num(win)} $</b>\n📊 Опыт: <b>+3 XP</b>\n💰 Баланс: <b>{format_num(u['balance'])} $</b>")

# --- ГЕМБЛИНГ ---
@dp.message(F.text.lower().startswith("рул"))
async def cmd_roul(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split(); amt = parse_amount(args[1], u['balance']); col = args[2].lower()
        if amt < 10 or amt > u['balance']: return await message.answer("❌ Нет денег!")
        u['balance'] -= amt
        res = random.randint(0, 36)
        win_c = "зеленый" if res == 0 else "красный" if res in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный"
        mul = 14 if col[:3] == "зел" and win_c == "зеленый" else 2 if col[:3] == win_c[:3] else 0
        u['balance'] += (amt * mul)
        status = f"✅ Выиграл: <b>+{format_num(amt*mul)}$</b>" if mul else f"❌ Слил: <b>-{format_num(amt)}$</b>"
        await message.answer(f"🎡 <b>РУЛЕТКА</b>\n━━━━━━━━━━━━\n🎰 Выпало: <b>{res} ({win_c})</b>\n📥 Ставка: {format_num(amt)}$ на {col}\n━━━━━━━━━━━━\n{status}\n💰 Баланс: <b>{format_num(u['balance'])} $</b>")
        await save_data()
    except: await message.answer("📝 Рул [сумма] [цвет]")

@dp.message(F.text.lower().startswith("краш"))
async def cmd_crash(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split(); amt = parse_amount(args[1], u['balance']); target = float(args[2].replace(",", "."))
        if amt < 10 or amt > u['balance']: return await message.answer("❌ Ошибка!")
        u['balance'] -= amt; crash = round(random.uniform(1.0, 3.5), 2)
        if target <= crash:
            win = int(amt * target); u['balance'] += win
            res = f"✅ Выигрыш: <b>+{format_num(win)}$</b>"
        else: res = f"❌ Проигрыш: <b>-{format_num(amt)}$</b>"
        await message.answer(f"🚀 <b>КРАШ</b>\n━━━━━━━━━━━━\n📈 Кэф: <b>x{crash}</b> | Цель: <b>x{target}</b>\n━━━━━━━━━━━━\n{res}\n💰 Баланс: <b>{format_num(u['balance'])} $</b>")
        await save_data()
    except: await message.answer("📝 Краш [сумма] [кэф]")

# --- БАНК ---
@dp.message(F.text.lower() == "банк")
async def cmd_bank(message: Message):
    u = get_user(message.from_user.id)
    await message.answer(f"🏦 <b>VIBE BANK</b>\n━━━━━━━━━━━━\n💰 В банке: <b>{format_num(u['bank'])} $</b>\n📈 Процент: <b>10% в 00:00 МСК</b>\n━━━━━━━━━━━━\n<i>'Деп [сумма]' | 'Снять [сумма]'</i>")

@dp.message(F.text.lower().startswith("деп"))
async def cmd_dep(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = parse_amount(message.text.split()[1], u['balance'])
        if amt > 0 and u['balance'] >= amt:
            u['balance'] -= amt; u['bank'] += amt; await save_data()
            await message.answer(f"✅ Внесено: <b>{format_num(amt)}$</b>")
    except: pass

@dp.message(F.text.lower().startswith("снять"))
async def cmd_withdraw(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = parse_amount(message.text.split()[1], u['bank'])
        if amt > 0 and u['bank'] >= amt:
            u['bank'] -= amt; u['balance'] += amt; await save_data()
            await message.answer(f"✅ Снято: <b>{format_num(amt)}$</b>")
    except: pass

# --- ПРОМОКОДЫ ---
@dp.message(F.text.lower().startswith("создать промо"))
async def cmd_create_promo(message: Message):
    u = get_user(message.from_user.id)
    try:
        args = message.text.split(); code = args[2].upper(); reward = parse_amount(args[3], u['balance']); uses = int(args[4])
        if u['balance'] < (reward * uses): return await message.answer("❌ Не хватает баланса!")
        u['balance'] -= (reward * uses)
        promos[code] = {"reward": reward, "uses": uses}
        await save_data()
        await message.answer(f"✨ <b>ПРОМОКОД СОЗДАН</b>\n━━━━━━━━━━━━━━━━━━\n🎫 Код: <code>{code}</code>\n💰 Награда: <b>{format_num(reward)} $</b>\n👥 Активаций: <b>{uses}</b>\n━━━━━━━━━━━━━━━━━━")
    except: await message.answer("📝 Создать промо [КОД] [СУММА] [КОЛ-ВО]")

@dp.message(F.text.lower().startswith("промо"))
async def cmd_use_promo(message: Message):
    if "создать" in message.text.lower(): return
    u = get_user(message.from_user.id)
    try:
        code = message.text.split()[1].upper()
        if code not in promos or code in u['used_promos']: return await message.answer("❌ Ошибка активации!")
        u['balance'] += promos[code]['reward']; u['used_promos'].append(code); promos[code]['uses'] -= 1
        reward = promos[code]['reward']
        if promos[code]['uses'] <= 0: del promos[code]
        await message.answer(f"✅ Получено <b>{format_num(reward)} $</b>!"); await save_data()
    except: pass

# --- РЫНОК ---
@dp.message(F.text.lower() == "рынок")
async def cmd_market(message: Message):
    p = await get_btc_price(); u = get_user(message.from_user.id)
    await message.answer(f"📊 <b>КРИПТО-РЫНОК</b>\n━━━━━━━━━━━━\n🪙 Курс BTC: <b>{format_num(p)}$</b>\n💰 У вас: <b>{u['btc']:.6f} BTC</b>")

@dp.message(F.text.lower().startswith("продать биткоин"))
async def cmd_sell_btc(message: Message):
    u = get_user(message.from_user.id)
    try:
        amt = float(message.text.split()[2].replace(",", ".")); p = await get_btc_price()
        if u['btc'] >= amt:
            gain = int(amt * p); u['btc'] -= amt; u['balance'] += gain
            await message.answer(f"✅ Продано за <b>{format_num(gain)}$</b>"); await save_data()
    except: pass

# --- БОНУС ---
@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    u = get_user(message.from_user.id); now = datetime.now().timestamp()
    if now - u.get('last_bonus', 0) < 3600:
        return await message.answer(f"⏳ Бонус через {int((3600-(now-u['last_bonus']))//60)} мин.")
    gain = 50000 + (u['lvl'] - 1) * 25000
    u['balance'] += gain; u['last_bonus'] = now; await save_data()
    await message.answer(f"🎁 <b>БОНУС</b>\nПолучено: <b>{format_num(gain)} $</b> (Ур. {u['lvl']})")

# --- МАГАЗИН ---
@dp.message(F.text.lower() == "магазин")
async def cmd_shop(message: Message):
    u = get_user(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Лопата (50к)", callback_data="buy_sh"), InlineKeyboardButton(text="Детектор (100к)", callback_data="buy_dt")]
    ])
    await message.answer(f"🏪 <b>МАГАЗИН</b>\nЛопата: {'✅' if u['shovel'] else '❌'}\nДетектор: {'✅' if u['detector'] else '❌'}", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_"))
async def shop_buy(call: CallbackQuery):
    u = get_user(call.from_user.id); item = "shovel" if "sh" in call.data else "detector"
    price = 50000 if item == "shovel" else 100000
    if u[item] or u['balance'] < price: return await call.answer("Недоступно", show_alert=True)
    u['balance'] -= price; u[item] = 1; await save_data(); await call.message.delete(); await cmd_shop(call.message)

# --- АДМИН ПАНЕЛЬ ---
@dp.message()
async def admin_cmds(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    t = message.text.lower(); args = message.text.split()
    try:
        uid = int(args[1])
        if t.startswith("выдатьбтк"):
            val = float(args[2]); get_user(uid)['btc'] += val
            await bot.send_message(uid, f"🎁 Админ выдал вам <b>{val} BTC</b>!")
        elif t.startswith("выдатьлвл"):
            val = int(args[2]); get_user(uid)['lvl'] = val
            await bot.send_message(uid, f"⭐ Ваш уровень теперь: <b>{val}</b>")
        elif t.startswith("выдатьхп"):
            val = int(args[2]); get_user(uid)['xp'] = val
        elif t.startswith("выдать"):
            val = parse_amount(args[2], 0); get_user(uid)['balance'] += val
            await bot.send_message(uid, f"💰 Вам выдано <b>{format_num(val)}$</b>!")
        elif t.startswith("бан"):
            get_user(uid)['banned'] = True
            await bot.send_message(uid, "🚫 Вы забанены!")
        elif t.startswith("разбан"):
            get_user(uid)['banned'] = False
            await bot.send_message(uid, "✅ Вы разблокированы!")
        await message.answer("✅ Готово"); await save_data()
    except: pass

async def bank_interest():
    for u in users.values():
        if u['bank'] > 0: u['bank'] += int(u['bank'] * 0.10)
    await save_data()

async def main():
    sync_load()
    scheduler.add_job(bank_interest, 'cron', hour=0, minute=0, timezone=timezone('Europe/Moscow'))
    scheduler.start()
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app); await runner.setup(); await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.delete_webhook(drop_pending_updates=True); await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
