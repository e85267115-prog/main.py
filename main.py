import asyncio
import os
import logging
import random
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))

CHANNEL_ID = "@nvibee_bet"
CHAT_ID = "@chatvibee_bet"
CHANNEL_URL = "https://t.me/nvibee_bet"
CHAT_URL = "https://t.me/chatvibee_bet"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

users = {}
bj_games = {}
bot_username = ""

# --- УМНОЕ ФОРМАТИРОВАНИЕ ЧИСЕЛ ---
def format_num(num):
    num = float(num)
    if num < 1000:
        return str(int(num))
    elif num < 1_000_000:
        val = num / 1000
        return f"{val:.2f}к".replace(".00", "") if val % 1 != 0 else f"{int(val)}к"
    elif num < 1_000_000_000:
        val = num / 1_000_000
        return f"{val:.2f}кк".replace(".00", "") if val % 1 != 0 else f"{int(val)}кк"
    else:
        val = num / 1_000_000_000
        return f"{val:.2f}ккк".replace(".00", "") if val % 1 != 0 else f"{int(val)}ккк"

def parse_amount(text, balance=0):
    if not text: return None
    text = str(text).lower().strip().replace(",", ".")
    if text in ["все", "всё", "all"]: return int(balance)
    
    mults = {"кккк": 10**12, "ккк": 10**9, "кк": 10**6, "к": 1000}
    for m, v in mults.items():
        if text.endswith(m):
            try: return int(float(text.replace(m, "")) * v)
            except: return None
    try: return int(float(text))
    except: return None

# --- БАЗОВЫЕ ФУНКЦИИ ---
def get_user(uid, name="Игрок"):
    if uid not in users:
        users[uid] = {
            "name": name, "balance": 50000, "btc": 0.0, "tools": 0,
            "lvl": 1, "xp": 0, "refs": 0, "last_bonus": None, "reg": datetime.now().strftime("%d.%m.%Y")
        }
    return users[uid]

async def is_sub(uid):
    try:
        m1 = await bot.get_chat_member(CHANNEL_ID, uid)
        m2 = await bot.get_chat_member(CHAT_ID, uid)
        return m1.status in ['member', 'administrator', 'creator'] and m2.status in ['member', 'administrator', 'creator']
    except: return False

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    u = get_user(message.from_user.id, message.from_user.first_name)
    if command.args and command.args.isdigit():
        ref_id = int(command.args)
        if ref_id != message.from_user.id and ref_id in users and message.from_user.id not in users:
            users[ref_id]['balance'] += 150000
            users[ref_id]['refs'] += 1
            try: await bot.send_message(ref_id, f"🤝 <b>Новый реферал!</b> Вам начислено <b>150к</b>")
            except: pass

    cap = f"🚀 <b>Vibe Bet 4.0</b>\n\nПринимаем ставки: <b>1к, 1.5к, 10кк</b>\nРефералка: <b>150к</b>\nБонус: <b>/bonus</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Канал", url=CHANNEL_URL), InlineKeyboardButton(text="💬 Чат", url=CHAT_URL)], [InlineKeyboardButton(text="✅ Проверить", callback_data="check")]])
    try: await message.answer_photo(photo=FSInputFile("start_img.jpg"), caption=cap, reply_markup=kb)
    except: await message.answer(cap, reply_markup=kb)

@dp.message(F.text.lower().in_({"я", "профиль"}))
async def cmd_profile(message: Message):
    if not await is_sub(message.from_user.id): return
    u = get_user(message.from_user.id)
    text = (f"👤 <b>{u['name']}</b>\n"
            f"⭐ Уровень: <b>{u['lvl']}</b> ({u['xp']}/{u['lvl']*4} XP)\n"
            f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
            f"🪙 BTC: <b>{u['btc']:.6f}</b>\n"
            f"👥 Рефов: <b>{u['refs']}</b>\n\n"
            f"🔗 Ссылка: <code>/ref</code>")
    await message.answer(text)

# --- ИГРЫ ---

@dp.message(Command("р", "рулетка", "casino"))
async def cmd_roulette(message: Message, command: CommandObject):
    u = get_user(message.from_user.id)
    args = command.args.split() if command.args else []
    if len(args) < 2: return await message.answer("🎰 <b>Формат:</b> <code>/р [сумма] [куда]</code>\nКуда: red, black, green")
    
    amt = parse_amount(args[0], u['balance'])
    goal = args[1].lower()
    
    if not amt or amt > u['balance'] or amt <= 0: return await message.answer("❌ Ошибка суммы!")
    if goal not in ['red', 'black', 'green', 'красное', 'черное', 'зеленое']: return await message.answer("❌ Куда ставим?")
    
    u['balance'] -= amt
    roll = random.randint(0, 36)
    color = "green" if roll == 0 else ("red" if roll % 2 == 0 else "black")
    
    win = 0
    if (goal in ['red', 'красное'] and color == 'red') or (goal in ['black', 'черное'] and color == 'black'):
        win = amt * 2
    elif (goal in ['green', 'зеленое'] and color == 'green'):
        win = amt * 14
        
    if win > 0:
        u['balance'] += win
        u['xp'] += 1
        res = f"✅ <b>ВЫИГРЫШ!</b>\nМножитель: <b>x{win/amt}</b>\nПлюс: <b>+{format_num(win)} $</b>"
    else:
        res = f"❌ <b>ПРОИГРЫШ</b>\nВыпало: <b>{color} ({roll})</b>"
    
    await message.answer(f"🎰 <b>РУЛЕТКА</b>\n{res}\n💰 Баланс: {format_num(u['balance'])} $")

@dp.message(Command("21", "bj", "очко"))
async def cmd_bj(message: Message, command: CommandObject):
    u = get_user(message.from_user.id)
    amt = parse_amount(command.args, u['balance'])
    if not amt or amt > u['balance'] or amt <= 0: return await message.answer("🃏 <b>Формат:</b> <code>/21 [сумма]</code>")
    
    u['balance'] -= amt
    deck = [2,3,4,5,6,7,8,9,10,10,10,10,11] * 4
    random.shuffle(deck)
    p, d = [deck.pop(), deck.pop()], [deck.pop(), deck.pop()]
    bj_games[message.from_user.id] = {'bet': amt, 'p': p, 'd': d, 'deck': deck}
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👊 Еще", callback_data="bj_h"), InlineKeyboardButton(text="✋ Стоп", callback_data="bj_s")]])
    await message.answer(f"🃏 <b>ОЧКО</b>\n\nВы: <b>{sum(p)}</b>\nДилер: <b>{d[0]}</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("bj_"))
async def bj_callback(call: CallbackQuery):
    uid = call.from_user.id
    if uid not in bj_games: return await call.answer("Игра не найдена!")
    g = bj_games[uid]
    
    if call.data == "bj_h":
        g['p'].append(g['deck'].pop())
        if sum(g['p']) > 21:
            await call.message.edit_text(f"💀 <b>ПЕРЕБОР!</b> ({sum(g['p'])})\nМинус: <b>{format_num(g['bet'])} $</b>")
            del bj_games[uid]
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👊 Еще", callback_data="bj_h"), InlineKeyboardButton(text="✋ Стоп", callback_data="bj_s")]])
            await call.message.edit_text(f"🃏 <b>ОЧКО</b>\n\nВы: <b>{sum(g['p'])}</b>\nДилер: <b>{g['d'][0]}</b>", reply_markup=kb)
    elif call.data == "bj_s":
        while sum(g['d']) < 17: g['d'].append(g['deck'].pop())
        ps, ds, u = sum(g['p']), sum(g['d']), get_user(uid)
        if ds > 21 or ps > ds:
            win = g['bet'] * 2
            u['balance'] += win
            res = f"✅ <b>ВЫИГРЫШ!</b>\nПлюс: <b>+{format_num(win)} $</b>"
        elif ps == ds:
            u['balance'] += g['bet']
            res = "🤝 <b>НИЧЬЯ!</b>"
        else:
            res = f"❌ <b>ПРОИГРЫШ!</b>\nУ дилера: {ds}"
        await call.message.edit_text(f"🃏 <b>ИТОГ</b>\nВы: {ps} | Дилер: {ds}\n\n{res}")
        del bj_games[uid]

# --- РАБОТА И БОНУС ---

@dp.message(Command("work", "копать", "клад"))
async def cmd_work(message: Message):
    u = get_user(message.from_user.id)
    if u['tools'] <= 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛒 Купить за 250к", callback_data="buy")]])
        return await message.answer("🛠 <b>Инструменты сломаны!</b>", reply_markup=kb)
    
    cash = random.randint(20000, 60000)
    u['balance'] += cash
    u['tools'] -= 1
    u['xp'] += 1
    await message.answer(f"⛏ <b>Вы нашли клад!</b>\nНаходка: <b>{format_num(cash)} $</b>\nПрочность: {u['tools']}/5")

@dp.callback_query(F.data == "buy")
async def buy_tools(call: CallbackQuery):
    u = get_user(call.from_user.id)
    if u['balance'] >= 250000:
        u['balance'] -= 250000
        u['tools'] = 5
        await call.message.edit_text("✅ <b>Инструменты куплены!</b>")
    else: await call.answer("❌ Недостаточно средств!")

@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):
    u = get_user(message.from_user.id)
    now = datetime.now()
    if u['last_bonus'] and now < u['last_bonus'] + timedelta(hours=1):
        diff = (u['last_bonus'] + timedelta(hours=1)) - now
        return await message.answer(f"⏳ Жди {int(diff.total_seconds()//60)} мин.")
    
    reward = 50000 + (u['lvl'] - 1) * 25000
    u['balance'] += reward
    u['last_bonus'] = now
    await message.answer(f"🎁 Бонус: <b>{format_num(reward)} $</b>")

# --- СИСТЕМНОЕ ---
async def main():
    global bot_username
    me = await bot.get_me()
    bot_username = me.username
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Vibe Bet Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())async def check_subscription(user_id):
    try:
        m1 = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        m2 = await bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
        valid = ['creator', 'administrator', 'member']
        return m1.status in valid and m2.status in valid
    except: return False

def sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Канал", url=CHANNEL_URL), InlineKeyboardButton(text="💬 Чат", url=CHAT_URL)],
        [InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub")]
    ])

# --- START И РЕФЕРАЛКА ---
@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    is_new = user_id not in users
    u = get_user(user_id, message.from_user.first_name)
    
    # Обработка реферала
    if is_new and command.args:
        try:
            referrer_id = int(command.args)
            if referrer_id != user_id and referrer_id in users:
                users[referrer_id]['balance'] += 250000
                users[referrer_id]['refs'] += 1
                try:
                    await bot.send_message(referrer_id, f"👤 <b>Новый реферал!</b>\nВам начислено: <b>250 000 $</b>")
                except: pass
        except: pass

    caption = (
        f"👋 <b>Привет, {u['name']}!</b>\n"
        f"🎰 Vibe Bet 3.0 — Казино, Работа и Бонусы!\n\n"
        f"⚠️ <b>Подпишись, чтобы играть:</b>"
    )
    try:
        await message.answer_photo(photo=FSInputFile("start_img.jpg"), caption=caption, reply_markup=sub_keyboard())
    except:
        await message.answer(caption, reply_markup=sub_keyboard())

@dp.callback_query(F.data == "check_sub")
async def callback_check(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await call.message.answer("🎉 <b>Ты в игре!</b>\nЖми /help или пиши <b>Я</b>")
    else:
        await call.answer("❌ Подпишись на всё!", show_alert=True)

# --- ПРОФИЛЬ ---
@dp.message(F.text.lower().in_({"я", "профиль"}))
async def cmd_profile(message: Message):
    if not await check_subscription(message.from_user.id): return await message.answer("🔒 Подпишись!", reply_markup=sub_keyboard())
    u = get_user(message.from_user.id)
    
    req_xp = get_xp_needed(u['lvl'])
    
    text = (
        f"👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"⭐ Уровень: <b>{u['lvl']}</b>\n"
        f"✨ XP: <code>{u['xp']}/{req_xp}</code>\n"
        f"👥 Рефералов: <b>{u['refs']}</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"💰 Баланс: <b>{format_money(u['balance'])} $</b>\n"
        f"🪙 Bitcoin: <b>{u['btc']:.6f} BTC</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🔗 Твоя ссылка: <code>/ref</code>"
    )
    await message.answer(text)

# --- РЕФЕРАЛКА ---
@dp.message(Command("ref"))
async def cmd_ref(message: Message):
    link = f"https://t.me/{bot_username}?start={message.from_user.id}"
    await message.answer(
        f"🤝 <b>ПАРТНЕРСКАЯ ПРОГРАММА</b>\n\n"
        f"Приглашай друзей и получай <b>250 000 $</b> за каждого!\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n<code>{link}</code>"
    )

# --- ЕЖЕЧАСНЫЙ БОНУС ---
@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):
    if not await check_subscription(message.from_user.id): return
    u = get_user(message.from_user.id)
    
    now = datetime.now()
    if u['last_bonus'] and now < u['last_bonus'] + timedelta(hours=1):
        left = (u['last_bonus'] + timedelta(hours=1)) - now
        return await message.answer(f"⏳ <b>Подожди еще:</b> {int(left.total_seconds()//60)} мин.")
    
    # Расчет бонуса: 50к + (Lvl-1)*25к
    amount = 50000 + (u['lvl'] - 1) * 25000
    u['balance'] += amount
    u['last_bonus'] = now
    
    await message.answer(f"🎁 <b>Ежечасный бонус!</b>\nНачислено: <b>{format_money(amount)} $</b>")

# --- РАБОТА (С инструментами) ---
@dp.message(Command("work"))
@dp.message(F.text.lower().contains("работ"))
async def cmd_work(message: Message):
    if not await check_subscription(message.from_user.id): return
    u = get_user(message.from_user.id)
    
    # Показываем инструменты ТОЛЬКО ТУТ
    if u['tools'] <= 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛒 Купить за 250к", callback_data="buy_tools")]])
        return await message.answer(f"🛠 <b>Работа встала!</b>\nВаши инструменты сломаны (0/5).", reply_markup=kb)
    
    money = random.randint(20000, 70000)
    # Шанс на BTC и XP
    btc_drop = random.uniform(0.0001, 0.001) if random.random() < 0.1 else 0
    xp_drop = 1
    
    u['balance'] += money
    u['btc'] += btc_drop
    u['tools'] -= 1
    lvl_up = add_xp(message.from_user.id, xp_drop)
    
    res = (f"⛏ <b>Смена окончена!</b>\n"
           f"💵 Зарплата: <b>{format_money(money)} $</b>\n"
           f"🔧 Инструменты: {u['tools']}/5")
    
    if btc_drop: res += f"\n🪙 Найдено: <b>{btc_drop:.5f} BTC</b>"
    if lvl_up: res += f"\n🆙 <b>НОВЫЙ УРОВЕНЬ: {u['lvl']}!</b>"
    
    await message.answer(res)

@dp.callback_query(F.data == "buy_tools")
async def buy_tools(call: CallbackQuery):
    u = get_user(call.from_user.id)
    if u['balance'] >= 250000:
        u['balance'] -= 250000
        u['tools'] = 5
        await call.message.edit_text("✅ <b>Инструменты куплены!</b> (5 использований)")
    else: await call.answer("❌ Мало денег!", show_alert=True)

# --- ИГРЫ: РУЛЕТКА ---
@dp.message(Command("casino"))
async def cmd_roulette(message: Message, command: CommandObject):
    u = get_user(message.from_user.id)
    args = command.args.split() if command.args else []
    if len(args) < 2: return await message.answer("ℹ️ <b>Пример:</b> `/casino 5000 red`\nЦвета: red, black, green")
    
    try:
        bet = int(args[0])
        choice = args[1].lower()
    except: return
    
    if bet > u['balance'] or bet <= 0: return await message.answer("❌ Неверная ставка")
    if choice not in ['red', 'black', 'green', 'красное', 'черное', 'зеленое']: return await message.answer("❌ Выбери цвет!")
    
    u['balance'] -= bet
    
    # Логика: 0-Green, 1-18 Red, 19-36 Black
    roll = random.randint(0, 36)
    color = "green" if roll == 0 else ("red" if 1 <= roll <= 18 else "black")
    
    win = 0
    if choice in [color, 'красное' if color=='red' else 'x', 'черное' if color=='black' else 'x', 'зеленое' if color=='green' else 'x']:
        mult = 14 if color == "green" else 2
        win = bet * mult
        u['balance'] += win
        res_text = f"✅ <b>ПОБЕДА!</b> Выпало {color.upper()}"
        add_xp(message.from_user.id, 1) # +1 XP за игру
    else:
        res_text = f"❌ <b>Поражение.</b> Выпало {color.upper()}"
    
    await message.answer(f"🎰 <b>РУЛЕТКА</b>\nВыпало число: <b>{roll}</b> ({color})\n{res_text}\n💰 Баланс: {format_money(u['balance'])}")

# --- ИГРЫ: CRASH ---
@dp.message(Command("crash"))
async def cmd_crash(message: Message, command: CommandObject):
    # Формат: /crash сумма кэф
    u = get_user(message.from_user.id)
    args = command.args.split() if command.args else []
    if len(args) < 2: return await message.answer("🚀 <b>Пример:</b> `/crash 1000 1.5`\n(Ставка 1000, автовывод на 1.5x)")
    
    try:
        bet = int(args[0])
        auto_cashout = float(args[1].replace(',', '.'))
    except: return
    
    if bet > u['balance'] or bet <= 0: return await message.answer("❌ Неверная ставка")
    if auto_cashout <= 1: return await message.answer("❌ Кэф должен быть > 1")
    
    u['balance'] -= bet
    
    # Алгоритм краша (простой)
    # Шанс упасть сразу = 10%. Иначе рандом до 100х
    crash_point = 1.0
    if random.random() > 0.1:
        crash_point = random.uniform(1.1, 5.0) # Чаще всего до 5х
        if random.random() < 0.05: crash_point = random.uniform(5.0, 50.0) # Редко большие иксы
    
    crash_point = round(crash_point, 2)
    
    if crash_point >= auto_cashout:
        win = int(bet * auto_cashout)
        u['balance'] += win
        add_xp(message.from_user.id, 1)
        await message.answer(f"🚀 <b>КРАШ УЛЕТЕЛ!</b>\nКрашнулся на: <b>{crash_point}x</b>\n✅ Вы забрали на: <b>{auto_cashout}x</b>\n➕ Выигрыш: <b>{format_money(win)} $</b>")
    else:
        await message.answer(f"💥 <b>БАБАХ!</b>\nРакета взорвалась на: <b>{crash_point}x</b>\n❌ Вы не успели забрать.")

# --- ИГРЫ: BLACKJACK (Очко) ---
@dp.message(Command("bj"))
@dp.message(Command("21"))
async def cmd_bj(message: Message, command: CommandObject):
    user_id = message.from_user.id
    if user_id in bj_games: return await message.answer("⚠️ Закончи прошлую игру!")
    
    u = get_user(user_id)
    try: bet = int(command.args)
    except: return await message.answer("🃏 <b>Пример:</b> `/bj 1000`")
    
    if bet > u['balance'] or bet <= 0: return await message.answer("❌ Неверная ставка")
    
    u['balance'] -= bet
    
    # Колода и раздача
    deck = [2,3,4,5,6,7,8,9,10,10,10,10,11] * 4
    random.shuffle(deck)
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]
    
    bj_games[user_id] = {'bet': bet, 'deck': deck, 'p': player_hand, 'd': dealer_hand}
    
    await send_bj_table(message, user_id)

async def send_bj_table(message, user_id):
    game = bj_games[user_id]
    p_score = sum(game['p'])
    d_score = game['d'][0] # Показываем только 1 карту дилера
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👊 Взять ({p_score})", callback_data="bj_hit"),
         InlineKeyboardButton(text="✋ Хватит", callback_data="bj_stand")]
    ])
    
    await message.answer(
        f"🃏 <b>BLACKJACK</b> | Ставка: {game['bet']}\n\n"
        f"👨‍💼 <b>Дилер:</b> {d_score} + [?]\n"
        f"🃏 Карты: <code>{game['d'][0]}</code> <code>?</code>\n\n"
        f"👤 <b>Вы:</b> {p_score}\n"
        f"🃏 Карты: <code>{' '.join(map(str, game['p']))}</code>",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("bj_"))
async def bj_action(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in bj_games: return await call.answer("Игра не найдена", show_alert=True)
    
    game = bj_games[user_id]
    action = call.data.split("_")[1]
    
    if action == "hit":
        game['p'].append(game['deck'].pop())
        score = sum(game['p'])
        if score > 21:
            await call.message.edit_text(f"💀 <b>ПЕРЕБОР!</b> ({score})\nВы проиграли <b>{game['bet']} $</b>")
            del bj_games[user_id]
        else:
            await call.message.delete()
            await send_bj_table(call.message, user_id)
            
    elif action == "stand":
        # Ход дилера
        while sum(game['d']) < 17: game['d'].append(game['deck'].pop())
        
        p_score = sum(game['p'])
        d_score = sum(game['d'])
        u = get_user(user_id)
        
        res = ""
        win = 0
        if d_score > 21 or p_score > d_score:
            win = game['bet'] * 2
            res = "✅ <b>ПОБЕДА!</b>"
            add_xp(user_id, 2)
        elif p_score == d_score:
            win = game['bet']
            res = "🤝 <b>НИЧЬЯ!</b>"
        else:
            res = "❌ <b>ДИЛЕР ВЫИГРАЛ.</b>"
            
        u['balance'] += win
        
        await call.message.edit_text(
            f"🃏 <b>ИГРА ОКОНЧЕНА</b>\n\n"
            f"👨‍💼 Дилер: <b>{d_score}</b> [{', '.join(map(str, game['d']))}]\n"
            f"👤 Вы: <b>{p_score}</b> [{', '.join(map(str, game['p']))}]\n\n"
            f"{res} (+{format_money(win)})"
        )
        del bj_games[user_id]

# --- ОСТАЛЬНОЕ ---
@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "🎮 <b>КОМАНДЫ VIBE BET:</b>\n\n"
        "🃏 <b>ИГРЫ:</b>\n"
        "• <code>/casino [сумма] [цвет]</code> — Рулетка\n"
        "• <code>/crash [сумма] [кэф]</code> — Краш\n"
        "• <code>/bj [сумма]</code> — Очко (21)\n\n"
        "💼 <b>ЗАРАБОТОК:</b>\n"
        "• <code>/work</code> — Кладоискатель\n"
        "• <code>/bonus</code> — Ежечасный бонус\n"
        "• <code>/ref</code> — Пригласить друга (+250к)\n"
        "• <code>/bank</code> — Банк\n\n"
        "👤 <b>ПРОФИЛЬ:</b>\n"
        "• <code>Я</code> — Статистика и уровень"
    )
    await message.answer(text)

# Банк и Переводы оставил без изменений в логике, так как они нужны
@dp.message(Command("bank"))
async def cmd_bank_legacy(message: Message):
    await message.answer("🏦 <b>Банк работает!</b> Используй <code>/bank dep [сумма]</code> или кнопки.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Внести всё", callback_data="bank_all_in")]]))
    
# СЕРВЕР
async def handle_ping(request): return web.Response(text="Bot Alive")

async def main():
    global bot_username
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logging.info("🚀 VIBE BET 3.0 ЗАПУЩЕН!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
