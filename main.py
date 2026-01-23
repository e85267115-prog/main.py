import asyncio
import os
import random
import logging
import asyncpg
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DB_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def format_num(num):
    try:
        num = float(num)
        if num < 1000: return str(int(num))
        if num < 1000000: return f"{num/1000:.2f}к".replace(".00", "")
        if num < 1000000000: return f"{num/1000000:.2f}кк".replace(".00", "")
        return f"{num/1000000000:.2f}ккк".replace(".00", "")
    except: return "0"

def parse_amount(text):
    if not text: return None
    text = text.lower().strip().replace('k', 'к')
    mults = {'кккк': 10**12, 'ккк': 10**9, 'кк': 10**6, 'к': 1000}
    for m, v in mults.items():
        if text.endswith(m):
            try: return int(float(text.replace(m, '')) * v)
            except: return None
    try: return int(float(text))
    except: return None

# --- РАБОТА С БАЗОЙ ДАННЫХ (ФИКС SSL) ---
async def init_db():
    try:
        conn = await asyncpg.connect(DB_URL, ssl='disable')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY, balance BIGINT DEFAULT 50000, btc NUMERIC DEFAULT 0,
                lvl INT DEFAULT 1, xp INT DEFAULT 0, wins INT DEFAULT 0, losses INT DEFAULT 0,
                deposit BIGINT DEFAULT 0, ref_id BIGINT, last_bonus DATE, banned BOOLEAN DEFAULT FALSE
            );
            CREATE TABLE IF NOT EXISTS promos (name TEXT PRIMARY KEY, reward BIGINT, acts INT);
            CREATE TABLE IF NOT EXISTS used_promos (user_id BIGINT, promo_name TEXT);
        ''')
        await conn.close()
        logging.info("✅ База данных подключена!")
    except Exception as e:
        logging.error(f"❌ Ошибка подключения БД: {e}")

async def add_xp(uid, conn, message):
    if random.random() < 0.4:
        u = await conn.fetchrow("SELECT xp, lvl FROM users WHERE id = $1", uid)
        new_xp = u['xp'] + 1
        if new_xp >= (u['lvl'] * 5):
            new_lvl = u['lvl'] + 1
            bonus = 50000 * new_lvl
            await conn.execute("UPDATE users SET lvl = $1, xp = 0, balance = balance + $2 WHERE id = $3", new_lvl, bonus, uid)
            await message.answer(f"🆙 **VIBE UP!**\nВаш уровень теперь: **{new_lvl}** 🎖\nБонус: **{format_num(bonus)} 💰**")
        else:
            await conn.execute("UPDATE users SET xp = $1 WHERE id = $2", new_xp, uid)

# --- ИГРОВЫЕ И ОСНОВНЫЕ КОМАНДЫ ---

@dp.message(Command("help"))
@dp.message(Command("помощь"))
async def cmd_help(message: Message):
    help_text = (
        "📖 **МЕНЮ КОМАНД VIBE BET**\n\n"
        "👤 **АККАУНТ:**\n"
        "• `Я` или `/profile` — Показать свой профиль\n"
        "• `/bonus` — Ежедневный денежный бонус\n"
        "• `/promo [код]` — Активировать промокод\n\n"
        "🎮 **ИГРЫ И ЗАРАБОТОК:**\n"
        "• `/work` — Пойти на работу (Шанс найти BTC!)\n"
        "• `/bj [ставка]` — Игра в Очко (21)\n"
        "• `/casino [ставка] [red/black/номер]` — Рулетка\n\n"
        "🏦 **ЭКОНОМИКА:**\n"
        "• `/bank dep [сумма]` — Положить деньги в банк (+5% в день)\n"
        "• `/bank send [id] [сумма]` — Перевести деньги другому игроку\n"
        "• `/sell_btc [кол-во]` — Продать биткоины по курсу\n\n"
        "🔗 **РЕФЕРАЛЫ:**\n"
        "За каждого приглашенного друга — **50,000 💰**\n"
        f"Ссылка: `t.me/{(await bot.get_me()).username}?start={message.from_user.id}`"
    )
    await message.answer(help_text)

@dp.message(F.text.lower() == "я")
@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    async with dp['db_pool'].acquire() as conn:
        await add_xp(message.from_user.id, conn, message)
        u = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
        if not u: return await message.answer("Напиши /start для регистрации!")
        
        text = (f"👤 **ПРОФИЛЬ | {message.from_user.first_name}**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 **Баланс:** {format_num(u['balance'])}\n"
                f"₿ **Биткоины:** {u['btc']:.5f}\n"
                f"🎖 **Уровень:** {u['lvl']} ({u['xp']}/{u['lvl']*5} XP)\n"
                f"🏦 **В банке:** {format_num(u['deposit'])}\n"
                f"📈 **Побед/Поражений:** {u['wins']}/{u['losses']}")
        await message.answer(text)

@dp.message(Command("work"))
async def cmd_work(message: Message):
    salary = random.randint(15000, 80000)
    btc_find = 0.0005 if random.random() < 0.1 else 0
    async with dp['db_pool'].acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance + $1, btc = btc + $2 WHERE id = $3", salary, btc_find, message.from_user.id)
    res = f"🛠 Ты отлично поработал! +**{format_num(salary)} 💰**"
    if btc_find: res += f"\n🟠 Ого! Ты нашел биткоин: **{btc_find} BTC**"
    await message.answer(res)

@dp.message(Command("casino"))
async def cmd_casino(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    if len(args) < 2: return await message.answer("ℹ️ Пример: `/casino 1000 red` (или black, или число 0-36)")
    
    amt = parse_amount(args[0])
    bet_on = args[1].lower()
    
    async with dp['db_pool'].acquire() as conn:
        user = await conn.fetchrow("SELECT balance FROM users WHERE id = $1", message.from_user.id)
        if not amt or amt > user['balance'] or amt < 100: return await message.answer("❌ Ошибка ставки!")
        
        num = random.randint(0, 36)
        color = "red" if num % 2 != 0 else "black"
        if num == 0: color = "green"
        
        win = False
        mult = 2
        if bet_on == color: win = True
        elif bet_on.isdigit() and int(bet_on) == num:
            win = True
            mult = 36
        
        if win:
            await conn.execute("UPDATE users SET balance = balance + $1, wins = wins + 1 WHERE id = $2", amt * (mult-1), message.from_user.id)
            await message.answer(f"🎰 Выпало: **{num} ({color})**\n✅ Твой выигрыш: **{format_num(amt * mult)} 💰**")
        else:
            await conn.execute("UPDATE users SET balance = balance - $1, losses = losses + 1 WHERE id = $2", amt, message.from_user.id)
            await message.answer(f"🎰 Выпало: **{num} ({color})**\n❌ Ты проиграл **{format_num(amt)} 💰**")

@dp.message(Command("bj"))
async def cmd_bj(message: Message, command: CommandObject):
    amt = parse_amount(command.args)
    async with dp['db_pool'].acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE id = $1", message.from_user.id)
        if not amt or amt > bal or amt < 100: return await message.answer("❌ Ставка от 100!")
        p = [random.randint(2,11), random.randint(2,11)]
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Еще", callback_data=f"bj_h_{amt}_{p[0]}_{p[1]}"),
            InlineKeyboardButton(text="🛑 Стоп", callback_data=f"bj_s_{amt}_{p[0]}_{p[1]}")
        ]])
        await message.answer(f"🃏 Карты: {p} (Сумма: {sum(p)})\nСтавка: {format_num(amt)}", reply_markup=kb)

@dp.callback_query(F.data.startswith("bj_"))
async def bj_callback(call: CallbackQuery):
    data = call.data.split("_")
    act, amt, p = data[1], int(data[2]), [int(x) for x in data[3:]]
    async with dp['db_pool'].acquire() as conn:
        if act == "h":
            p.append(random.randint(2,11))
            if sum(p) > 21:
                await conn.execute("UPDATE users SET balance = balance - $1, losses = losses + 1 WHERE id = $2", amt, call.from_user.id)
                await call.message.edit_text(f"🃏 {p} ({sum(p)})\n💥 **ПЕРЕБОР!** Ты проиграл.")
            else:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="➕ Еще", callback_data=f"bj_h_{amt}_" + "_".join(map(str, p))),
                    InlineKeyboardButton(text="🛑 Стоп", callback_data=f"bj_s_{amt}_" + "_".join(map(str, p)))
                ]])
                await call.message.edit_text(f"🃏 {p} ({sum(p)})\nБерешь еще?", reply_markup=kb)
        else:
            d = [random.randint(2,11), random.randint(2,11)]
            while sum(d) < 17: d.append(random.randint(2,11))
            ps, ds = sum(p), sum(d)
            if ds > 21 or ps > ds:
                await conn.execute("UPDATE users SET balance = balance + $1, wins = wins + 1 WHERE id = $2", amt, call.from_user.id)
                res = f"✅ ПОБЕДА! +{format_num(amt)}"
            elif ps == ds: res = "🤝 НИЧЬЯ!"
            else:
                await conn.execute("UPDATE users SET balance = balance - $1, losses = losses + 1 WHERE id = $2", amt, call.from_user.id)
                res = f"❌ ПРОИГРЫШ! -{format_num(amt)}"
            await call.message.edit_text(f"👤 Вы: {ps} | 🤖 Дилер: {ds}\n\n{res}")

@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    uid = message.from_user.id
    ref_id = int(command.args) if command.args and command.args.isdigit() else None
    async with dp['db_pool'].acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM users WHERE id = $1", uid)
        if not user:
            await conn.execute("INSERT INTO users (id, ref_id) VALUES ($1, $2)", uid, ref_id)
            if ref_id and ref_id != uid:
                await conn.execute("UPDATE users SET balance = balance + 50000 WHERE id = $1", ref_id)
                try: await bot.send_message(ref_id, "🤝 По твоей ссылке зашел друг! Тебе начислено **50,000 💰**")
                except: pass
    await message.answer("🎰 **Vibe Bet** — Твой путь к миллионам!\n\nНапиши **Я**, чтобы открыть профиль или **/help**, чтобы узнать команды.")

# --- АДМИН-КОМАНДЫ ---
@dp.message(Command("setbal"))
async def cmd_setbal(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    args = command.args.split()
    uid, amt = int(args[0]), int(args[1])
    async with dp['db_pool'].acquire() as conn:
        await conn.execute("UPDATE users SET balance = $1 WHERE id = $2", amt, uid)
    await message.answer("✅ Баланс обновлен!")

# --- ЗАПУСК ---
async def handle_ping(request): return web.Response(text="Alive")

async def main():
    await init_db()
    dp['db_pool'] = await asyncpg.create_pool(DB_URL, ssl='disable')
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logging.info("🚀 БОТ ЗАПУЩЕН!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
