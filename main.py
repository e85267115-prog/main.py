import asyncio
import os
import random
import logging
import asyncpg
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DB_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def format_num(num):
    num = float(num)
    if num < 1000: return str(int(num))
    elif num < 1000000: return f"{num/1000:.2f}к".replace(".00", "")
    elif num < 1000000000: return f"{num/1000000:.2f}кк".replace(".00", "")
    elif num < 1000000000000: return f"{num/1000000000:.2f}ккк".replace(".00", "")
    return f"{num/1000000000000:.2f}кккк".replace(".00", "")

def parse_amount(text):
    if not text: return None
    text = text.lower().strip().replace('k', 'к')
    mults = {'ккккк': 10**15, 'кккк': 10**12, 'ккк': 10**9, 'кк': 10**6, 'к': 1000}
    for m, v in mults.items():
        if text.endswith(m):
            try: return int(float(text.replace(m, '')) * v)
            except: return None
    try: return int(float(text))
    except: return None

async def get_btc_price():
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as r:
                data = await r.json()
                return data['bitcoin']['usd']
        except: return 65000

# --- ИНИЦИАЛИЗАЦИЯ БД ---
async def init_db():
    conn = await asyncpg.connect(DB_URL)
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

# --- СИСТЕМА УРОВНЕЙ ---
async def add_xp(uid, conn, message):
    if random.random() < 0.5:
        u = await conn.fetchrow("SELECT xp, lvl FROM users WHERE id = $1", uid)
        new_xp = u['xp'] + 1
        needed = u['lvl'] * 4
        if new_xp >= needed:
            new_lvl = u['lvl'] + 1
            bonus = 50000 + (new_lvl - 1) * 25000
            await conn.execute("UPDATE users SET lvl = $1, xp = 0, balance = balance + $2 WHERE id = $3", new_lvl, bonus, uid)
            await message.answer(f"🆙 **Уровень повышен!**\nТеперь ваш уровень: **{new_lvl}** 🎖\nБонус: **{format_num(bonus)} 💰**")
        else:
            await conn.execute("UPDATE users SET xp = $1 WHERE id = $2", new_xp, uid)

# --- КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ ---

@dp.message(Command("start", "старт"))
async def cmd_start(message: Message, command: CommandObject):
    pool = dp['db_pool']
    uid, ref_id = message.from_user.id, None
    if command.args and command.args.isdigit():
        ref_id = int(command.args)
    
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT id FROM users WHERE id = $1", uid)
        if not exists:
            if ref_id and ref_id != uid:
                await conn.execute("UPDATE users SET balance = balance + 50000 WHERE id = $1", ref_id)
                try: await bot.send_message(ref_id, "🔔 У вас новый реферал! +50,000 💰")
                except: pass
            await conn.execute("INSERT INTO users (id, ref_id) VALUES ($1, $2)", uid, ref_id)
    await message.answer("🎰 **Добро пожаловать в GameBot!**\n\nТут есть казино, работа и банк. Напиши **/profile**, чтобы начать!")

@dp.message(Command("profile", "профиль", "stats"))
async def cmd_profile(message: Message):
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        await add_xp(message.from_user.id, conn, message)
        u = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
        if u['banned']: return await message.answer("🚫 Вы забанены.")
        
        text = (f"👤 **Профиль игрока:** `{u['id']}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 **Баланс:** {format_num(u['balance'])}\n"
                f"₿ **BTC:** {u['btc']:.5f}\n"
                f"🎖 **Уровень:** {u['lvl']} ({u['xp']}/{u['lvl']*4} XP)\n"
                f"📈 **Побед:** {u['wins']} | 📉 **Проигрышей:** {u['losses']}")
        await message.answer(text)

@dp.message(Command("work", "работа"))
async def cmd_work(message: Message):
    jobs = ["Хакер 💻", "Кладоискатель 🗺", "Трейдер 📈", "Доставщик 🍕", "Шахтер ⛏"]
    job = random.choice(jobs)
    salary = random.randint(10000, 1000000)
    btc_find = 0.0005 if random.random() < 0.09 else 0
    
    async with dp['db_pool'].acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance + $1, btc = btc + $2 WHERE id = $3", salary, btc_find, message.from_user.id)
    
    msg = f"🛠 Вы поработали: **{job}**\n💵 Зарплата: **{format_num(salary)} 💰**"
    if btc_find: msg += f"\n🟠 Ого! Вы нашли **{btc_find} BTC**!"
    await message.answer(msg)

@dp.message(Command("bonus", "бонус"))
async def cmd_bonus(message: Message):
    async with dp['db_pool'].acquire() as conn:
        u = await conn.fetchrow("SELECT last_bonus, lvl FROM users WHERE id = $1", message.from_user.id)
        today = datetime.utcnow().date()
        if u['last_bonus'] == today:
            return await message.answer("📅 Бонус можно брать раз в день!")
        
        reward = 50000 + (u['lvl'] - 1) * 25000
        await conn.execute("UPDATE users SET balance = balance + $1, last_bonus = $2 WHERE id = $3", reward, today, message.from_user.id)
        await message.answer(f"🎁 Ежедневный бонус: **{format_num(reward)} 💰**")

# --- КАЗИНО (РУЛЕТКА, ОЧКО, КРАШ) ---

@dp.message(Command("casino", "казино", "roulette"))
async def cmd_casino(message: Message, command: CommandObject):
    if not command.args or len(command.args.split()) < 2:
        return await message.answer("🎰 `/casino [сумма] [ставка]`\nСтавки: red, black, 1-12, 13-24, 25-36, 0-36")
    
    args = command.args.split()
    amt, bet = parse_amount(args[0]), args[1].lower()
    
    async with dp['db_pool'].acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE id = $1", message.from_user.id)
        if not amt or amt > bal or amt <= 0: return await message.answer("❌ Недостаточно средств!")
        
        res = random.randint(0, 36)
        win = False
        mul = 2
        
        if bet in ['red', 'кра'] and res % 2 != 0: win = True
        elif bet in ['black', 'чер'] and res % 2 == 0 and res != 0: win = True
        elif bet == '1-12' and 1 <= res <= 12: win, mul = True, 3
        elif bet == '13-24' and 13 <= res <= 24: win, mul = True, 3
        elif bet == '25-36' and 25 <= res <= 36: win, mul = True, 3
        elif bet.isdigit() and int(bet) == res: win, mul = True, 36

        if win:
            await conn.execute("UPDATE users SET balance = balance + $1, wins = wins + 1 WHERE id = $2", amt*(mul-1), message.from_user.id)
            await message.answer(f"🎰 Выпало: **{res}**\n✅ Победа! +{format_num(amt*mul)} 💰")
        else:
            await conn.execute("UPDATE users SET balance = balance - $1, losses = losses + 1 WHERE id = $2", amt, message.from_user.id)
            await message.answer(f"🎰 Выпало: **{res}**\n❌ Проигрыш: -{format_num(amt)} 💰")

@dp.message(Command("bj", "очко", "21"))
async def cmd_bj(message: Message, command: CommandObject):
    amt = parse_amount(command.args)
    async with dp['db_pool'].acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE id = $1", message.from_user.id)
        if not amt or amt > bal or amt < 100: return await message.answer("❌ Ставка от 100 💰")
        
        cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11]
        p = [random.choice(cards), random.choice(cards)]
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Еще", callback_data=f"bj_h_{amt}_{p[0]}_{p[1]}"),
            InlineKeyboardButton(text="🛑 Стоп", callback_data=f"bj_s_{amt}_{p[0]}_{p[1]}")
        ]])
        await message.answer(f"🃏 **Очко**\nКарты: {p} (Сумма: {sum(p)})\nСтавка: {format_num(amt)}", reply_markup=kb)

@dp.callback_query(F.data.startswith("bj_"))
async def bj_call(call: CallbackQuery):
    _, act, amt, *p = call.data.split("_")
    amt, p = int(amt), [int(x) for x in p]
    cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11]
    
    async with dp['db_pool'].acquire() as conn:
        if act == "h":
            p.append(random.choice(cards))
            s = sum(p)
            if s > 21:
                await conn.execute("UPDATE users SET balance = balance - $1, losses = losses + 1 WHERE id = $2", amt, call.from_user.id)
                return await call.message.edit_text(f"🃏 Карты: {p} ({s})\n💥 **Перебор!** -{format_num(amt)}")
            
            new_data = f"bj_h_{amt}_" + "_".join(map(str, p))
            stop_data = f"bj_s_{amt}_" + "_".join(map(str, p))
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="➕ Еще", callback_data=new_data),
                InlineKeyboardButton(text="🛑 Стоп", callback_data=stop_data)
            ]])
            await call.message.edit_text(f"🃏 Карты: {p} ({s})\nСтавка: {format_num(amt)}", reply_markup=kb)
        else:
            d = [random.choice(cards), random.choice(cards)]
            while sum(d) < 17: d.append(random.choice(cards))
            ps, ds = sum(p), sum(d)
            if ds > 21 or ps > ds:
                await conn.execute("UPDATE users SET balance = balance + $1, wins = wins + 1 WHERE id = $2", amt, call.from_user.id)
                res = f"✅ Победа! +{format_num(amt*2)}"
            elif ps == ds: res = "🤝 Ничья!"
            else:
                await conn.execute("UPDATE users SET balance = balance - $1, losses = losses + 1 WHERE id = $2", amt, call.from_user.id)
                res = f"❌ Проигрыш! -{format_num(amt)}"
            await call.message.edit_text(f"👤 Вы: {ps} {p}\n🤖 Дилер: {ds} {d}\n\n{res}")

@dp.message(Command("crash", "краш"))
async def cmd_crash(message: Message, command: CommandObject):
    amt = parse_amount(command.args)
    async with dp['db_pool'].acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE id = $1", message.from_user.id)
        if not amt or amt > bal or amt <= 0: return await message.answer("❌ Ошибка ставки.")
        
        crash_point = random.uniform(1.0, 4.0)
        user_exit = random.uniform(1.1, 3.5) # В реальном боте тут нужны кнопки, но для краткости сделаем авто-стоп
        
        if user_exit < crash_point:
            win = int(amt * user_exit)
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE id = $2", win - amt, message.from_user.id)
            await message.answer(f"🚀 График взлетел до {crash_point:.2f}x!\n✅ Вы вышли на **{user_exit:.2f}x** и забрали **{format_num(win)} 💰**")
        else:
            await conn.execute("UPDATE users SET balance = balance - $1 WHERE id = $2", amt, message.from_user.id)
            await message.answer(f"🚀 График упал на {crash_point:.2f}x!\n❌ Вы не успели выйти. Проигрыш: -{format_num(amt)} 💰")

# --- БАНК И МАРКЕТ ---

@dp.message(Command("bank"))
async def cmd_bank(message: Message, command: CommandObject):
    if not command.args: return await message.answer("🏦 `/bank dep [сумма]` или `/bank send [id] [сумма]`")
    args = command.args.split()
    async with dp['db_pool'].acquire() as conn:
        if args[0] == "dep":
            val = parse_amount(args[1])
            bal = await conn.fetchval("SELECT balance FROM users WHERE id = $1", message.from_user.id)
            if val and val <= bal:
                await conn.execute("UPDATE users SET balance = balance - $1, deposit = deposit + $1 WHERE id = $2", val, message.from_user.id)
                await message.answer("💳 Депозит пополнен! +5% каждую полночь.")
        elif args[0] == "send":
            to_id, val = int(args[1]), parse_amount(args[2])
            bal = await conn.fetchval("SELECT balance FROM users WHERE id = $1", message.from_user.id)
            if val and val <= bal:
                await conn.execute("UPDATE users SET balance = balance - $1 WHERE id = $2", val, message.from_user.id)
                await conn.execute("UPDATE users SET balance = balance + $1 WHERE id = $2", val, to_id)
                await message.answer("💸 Деньги отправлены!")
                try: await bot.send_message(to_id, f"📥 Вам пришел перевод: {format_num(val)} 💰 от ID {message.from_user.id}")
                except: pass

@dp.message(Command("sell_btc"))
async def cmd_sell_btc(message: Message, command: CommandObject):
    qty = float(command.args) if command.args else 0
    price = await get_btc_price()
    async with dp['db_pool'].acquire() as conn:
        u_btc = await conn.fetchval("SELECT btc FROM users WHERE id = $1", message.from_user.id)
        if qty <= 0 or qty > u_btc: return await message.answer("❌ Недостаточно BTC.")
        total = int(qty * price)
        await conn.execute("UPDATE users SET btc = btc - $1, balance = balance + $2 WHERE id = $3", qty, total, message.from_user.id)
        await message.answer(f"✅ Продано {qty} BTC за **{format_num(total)} 💰** (Курс: ${price})")

# --- АДМИН ПАНЕЛЬ ---

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("👑 **Админ-меню**\n/give [id] [сумма]\n/take [id] [сумма]\n/ban [id]\n/create_promo [код] [кол-во] [сумма]")

@dp.message(Command("give"))
async def cmd_give(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    args = command.args.split()
    uid, amt = int(args[0]), parse_amount(args[1])
    async with dp['db_pool'].acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE id = $2", amt, uid)
    await message.answer("✅ Выдано.")

@dp.message(Command("create_promo"))
async def cmd_cr_promo(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    args = command.args.split()
    name, acts, rew = args[0], int(args[1]), parse_amount(args[2])
    async with dp['db_pool'].acquire() as conn:
        await conn.execute("INSERT INTO promos VALUES ($1, $2, $3)", name, rew, acts)
    await message.answer(f"🎟 Промокод `{name}` создан.")

@dp.message(Command("promo"))
async def cmd_promo(message: Message, command: CommandObject):
    if not command.args: return
    async with dp['db_pool'].acquire() as conn:
        p = await conn.fetchrow("SELECT * FROM promos WHERE name = $1", command.args)
        used = await conn.fetchval("SELECT user_id FROM used_promos WHERE user_id = $1 AND promo_name = $2", message.from_user.id, command.args)
        if p and p['acts'] > 0 and not used:
            await conn.execute("UPDATE promos SET acts = acts - 1 WHERE name = $1", command.args)
            await conn.execute("INSERT INTO used_promos VALUES ($1, $2)", message.from_user.id, command.args)
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE id = $2", p['reward'], message.from_user.id)
            await message.answer(f"✅ Активировано! +{format_num(p['reward'])} 💰")
        else: await message.answer("❌ Промокод недействителен.")

# --- WEB SERVER & CRON ---
async def handle_ping(request): return aiohttp.web.Response(text="Alive")

async def run_server():
    app = aiohttp.web.Application()
    app.router.add_get("/", handle_ping)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    await aiohttp.web.TCPSite(runner, "0.0.0.0", PORT).start()

async def bank_cron():
    while True:
        now = datetime.utcnow()
        if now.hour == 21 and now.minute == 0: # 00:00 МСК
            async with dp['db_pool'].acquire() as conn:
                await conn.execute("UPDATE users SET deposit = CAST(deposit * 1.05 AS BIGINT) WHERE deposit > 0")
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def main():
    await init_db()
    dp['db_pool'] = await asyncpg.create_pool(DB_URL)
    asyncio.create_task(run_server())
    asyncio.create_task(bank_cron())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())