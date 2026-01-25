import asyncio
import os
import logging
import random
import json
import io
import time
from datetime import datetime
from typing import Dict, List, Optional, Union

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

# ==========================================
# КОНФИГУРАЦИЯ И НАСТРОЙКИ
# ==========================================

# Основные токены и ID
TOKEN = os.getenv("BOT_TOKEN") 
ADMIN_IDS = [1997428703] # Твой ID
PORT = int(os.getenv("PORT", 8080))
BOT_USERNAME = "VibeBetBot"

# Google Drive
DRIVE_FILE_ID = "1_PdomDLZAisdVlkCwkQn02x75uoqtMWW" 
CREDENTIALS_FILE = 'credentials.json'

# Каналы (Обязательная подписка)
REQUIRED_CHANNELS = [
    {"username": "@chatvibee_bet", "link": "https://t.me/chatvibee_bet"},
    {"username": "@nvibee_bet", "link": "https://t.me/nvibee_bet"}
]

# Настройки Фермы (Майнинг)
FARM_CONFIG = {
    "rtx3060": {"name": "NVIDIA RTX 3060", "price": 150000, "income": 0.00001, "scale": 1.2, "limit": 3},
    "rtx4070": {"name": "NVIDIA RTX 4070", "price": 220000, "income": 0.00004, "scale": 1.2, "limit": 3},
    "rtx4090": {"name": "NVIDIA RTX 4090", "price": 350000, "income": 0.00007, "scale": 1.3, "limit": 3}
}

# Настройки Работы
WORK_CONFIG = {
    "tools": {
        "shovel": {"name": "Лопата", "price": 50000},
        "detector": {"name": "Металлоискатель", "price": 100000}
    },
    "cooldown": 600, # 10 минут
    "rewards": {"min": 30000, "max": 150000},
    "btc_chance": 0.10, # 10%
    "xp_gain": {"min": 1, "max": 5}
}

# Экономика уровней
LEVEL_CONFIG = {
    "xp_base": 4, # С 1 на 2 уровень нужно 4 xp
    "xp_step": 4, # +4 xp за каждый следующий уровень
    "bonus_base": 50000,
    "bonus_step": 25000
}

# Логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# ==========================================
# МЕНЕДЖЕР ДАННЫХ (DATABASE MANAGER)
# ==========================================

class DataManager:
    """Класс для управления данными пользователей и сохранения в Google Drive"""
    def __init__(self):
        self.users: Dict[int, dict] = {}
        self.promos: Dict[str, dict] = {}
        self.market_btc: int = 50000
        self.active_games: Dict[str, dict] = {}

    def get_service(self):
        if not os.path.exists(CREDENTIALS_FILE):
            logger.error("Файл credentials.json не найден!")
            return None
        try:
            creds = service_account.Credentials.from_service_account_file(
                CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive']
            )
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            logger.error(f"Ошибка авторизации Google: {e}")
            return None

    def load(self):
        service = self.get_service()
        if not service: return
        try:
            logger.info("Загрузка БД из Google Drive...")
            request = service.files().get_media(fileId=DRIVE_FILE_ID)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            
            content = fh.getvalue().decode('utf-8').strip()
            if content:
                data = json.loads(content)
                self.users = {int(k): v for k, v in data.get("users", {}).items()}
                self.promos = data.get("promos", {})
                self.market_btc = data.get("market_btc", 50000)
                logger.info(f"БД загружена. Пользователей: {len(self.users)}")
        except Exception as e:
            logger.error(f"КРИТИЧЕСКАЯ ОШИБКА ЗАГРУЗКИ: {e}")

    def save(self):
        service = self.get_service()
        if not service: return
        try:
            data = {
                "users": self.users,
                "promos": self.promos,
                "market_btc": self.market_btc
            }
            with open("db.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            
            media = MediaFileUpload("db.json", mimetype='application/json', resumable=True)
            service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
            logger.info("БД успешно сохранена в облако.")
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")

    async def async_save(self):
        await asyncio.to_thread(self.save)

    def get_user(self, uid: int, name: str = "Игрок") -> dict:
        uid = int(uid)
        now = time.time()
        
        # Шаблон нового пользователя
        if uid not in self.users:
            self.users[uid] = {
                "name": name,
                "balance": 5000,
                "btc": 0.0,
                "lvl": 1,
                "xp": 0,
                "banned": False,
                "registered": False,
                "reg_date": now,
                "inventory": {"shovel": False, "detector": False},
                "stats": {"games_played": 0, "won": 0},
                "last_work": 0,
                "last_bonus": 0,
                "used_promos": [],
                "farm": {
                    "rtx3060": 0, "rtx4070": 0, "rtx4090": 0,
                    "last_collect": now
                }
            }
            asyncio.create_task(self.async_save())
        
        # МИГРАЦИЯ (Проверка целостности данных старых юзеров)
        u = self.users[uid]
        if "inventory" not in u:
            # Конвертация старого формата (shovel=1) в новый (inventory dict)
            sh = u.get("shovel", 0)
            det = u.get("detector", 0)
            u["inventory"] = {"shovel": bool(sh), "detector": bool(det)}
        
        if "farm" not in u:
            u["farm"] = {"rtx3060": 0, "rtx4070": 0, "rtx4090": 0, "last_collect": now}
            
        u["name"] = name # Обновляем имя если сменил
        return u

# Глобальный экземпляр БД
db = DataManager()

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (UTILS)
# ==========================================

def format_num(num: Union[int, float]) -> str:
    """Красивое форматирование чисел (1к, 1кк, 1ккк)"""
    num = float(num)
    if num < 1000: return str(int(num))
    
    suffixes = [
        (1e12, "кккк"), 
        (1e9, "ккк"), 
        (1e6, "кк"), 
        (1e3, "к")
    ]
    for val, suff in suffixes:
        if num >= val:
            res = num / val
            # Если дробная часть 0, не показываем её
            return f"{int(res)}{suff}" if res.is_integer() else f"{res:.2f}{suff}"
    return str(int(num))

def parse_money(text: str, user_balance: int) -> Optional[int]:
    """Парсинг суммы из текста (включая 'вабанк', '10к', '5кк')"""
    text = str(text).lower().replace(",", ".").strip()
    if text in ["все", "всё", "all", "вабанк", "max"]: 
        return int(user_balance)
    
    multipliers = {"кккк": 1e12, "ккк": 1e9, "кк": 1e6, "к": 1e3}
    for suff, mult in multipliers.items():
        if text.endswith(suff):
            try:
                base = float(text[:-len(suff)])
                return int(base * mult)
            except ValueError:
                return None
    
    try:
        val = int(float(text))
        return val if val > 0 else None
    except ValueError:
        return None

async def check_subs(user_id: int) -> bool:
    """Проверка подписки на каналы"""
    for ch in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=ch["username"], user_id=user_id)
            if member.status in ['left', 'kicked', 'restricted']:
                return False
        except Exception as e:
            logger.warning(f"Ошибка проверки подписки {user_id} на {ch['username']}: {e}")
            # Если бот не админ, возвращаем True, чтобы не блокировать функционал
            return True
    return True

async def update_btc_course():
    """Фоновая задача: Обновление курса BTC"""
    old_rate = db.market_btc
    db.market_btc = random.randint(10000, 150000)
    await db.async_save()
    logger.info(f"MARKET: BTC price updated {old_rate} -> {db.market_btc}")

def get_level_req(lvl):
    """Считает XP для следующего уровня. 1->2 (4xp), 2->3 (8xp), 3->4 (12xp)"""
    return lvl * LEVEL_CONFIG["xp_step"]

def add_exp(u, amount):
    """Безопасное добавление опыта и повышение уровня"""
    u['xp'] += amount
    leveled_up = False
    
    while True:
        req = get_level_req(u['lvl'])
        if u['xp'] >= req:
            u['xp'] -= req
            u['lvl'] += 1
            leveled_up = True
        else:
            break
    return leveled_up

# ==========================================
# MIDDLEWARE (ПРОВЕРКИ)
# ==========================================

@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def main_middleware(handler, event, data):
    # Определение user_id и имени
    if isinstance(event, Message):
        uid = event.from_user.id
        name = event.from_user.first_name
        text = event.text or ""
    elif isinstance(event, CallbackQuery):
        uid = event.from_user.id
        name = event.from_user.first_name
        text = ""
    else:
        return await handler(event, data)

    # Получаем профиль
    u = db.get_user(uid, name)

    # 1. Проверка бана
    if u.get('banned'):
        return # Полный игнор

    # 2. Проверка регистрации
    is_auth_command = text.startswith("/start") or text.startswith("/reg")
    if not u['registered'] and not is_auth_command:
        if isinstance(event, Message):
            await event.answer("⛔ <b>Доступ запрещен!</b>\nСначала зарегистрируйтесь: /reg")
        return

    return await handler(event, data)

# ==========================================
# КЛАВИАТУРЫ (UI)
# ==========================================

def kb_main_menu():
    return None # Используем текстовое меню или картинку

def kb_sub_check():
    kb = []
    for ch in REQUIRED_CHANNELS:
        kb.append([InlineKeyboardButton(text=f"👉 Подписаться на {ch['username']}", url=ch['link'])])
    kb.append([InlineKeyboardButton(text="✅ Я ПОДПИСАЛСЯ", callback_data="reg_check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def kb_shop(u):
    kb = []
    inv = u['inventory']
    
    # Лопата
    if not inv['shovel']:
        p = WORK_CONFIG['tools']['shovel']['price']
        kb.append([InlineKeyboardButton(text=f"🛠 Лопата — {format_num(p)}$", callback_data="buy_tool_shovel")])
    else:
        kb.append([InlineKeyboardButton(text="✅ Лопата (Куплено)", callback_data="ignore")])
        
    # Детектор
    if not inv['detector']:
        p = WORK_CONFIG['tools']['detector']['price']
        kb.append([InlineKeyboardButton(text=f"📡 Металлоискатель — {format_num(p)}$", callback_data="buy_tool_detector")])
    else:
        kb.append([InlineKeyboardButton(text="✅ Металлоискатель (Куплено)", callback_data="ignore")])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)

def kb_farm_main():
    kb = [
        [InlineKeyboardButton(text="💰 Собрать прибыль", callback_data="farm_collect")],
        [InlineKeyboardButton(text="🛒 Магазин видеокарт", callback_data="farm_shop_menu")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="farm_refresh")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def kb_farm_shop(u):
    kb = []
    for key, cfg in FARM_CONFIG.items():
        count = u['farm'].get(key, 0)
        # Динамическая цена: Base * (Scale ^ Count)
        price = int(cfg['price'] * (cfg['scale'] ** count))
        
        if count >= cfg['limit']:
            btn_txt = f"🚫 {cfg['name']} (МАКС)"
            cb = "ignore"
        else:
            btn_txt = f"🛍 {cfg['name']} — {format_num(price)}$"
            cb = f"farm_buy_{key}"
            
        kb.append([InlineKeyboardButton(text=btn_txt, callback_data=cb)])
    
    kb.append([InlineKeyboardButton(text="🔙 Назад в Ферму", callback_data="farm_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==========================================
# ОБРАБОТЧИКИ: СИСТЕМНЫЕ
# ==========================================

@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    u = db.get_user(message.from_user.id)
    
    # Обработка рефералов
    if command.args and command.args.startswith("promo_"):
        code = command.args.split("_")[1]
        await activate_promo_logic(message, code)
        return

    if not u['registered']:
        return await message.answer("👋 <b>Добро пожаловать в Vibe Bet!</b>\n\nДля начала игры необходимо пройти регистрацию.\nВведите команду: /reg")
    
    await send_main_interface(message)

async def send_main_interface(message: Message):
    txt = (
        f"🖥 <b>ГЛАВНОЕ МЕНЮ VIBE BET</b>\n"
        f"💸 Курс BTC: <b>{format_num(db.market_btc)} $</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 <b>Игры:</b> Рул, Кости, Футбол, Алмазы, Мины\n"
        f"⛏️ <b>Работа:</b> /work (Копать клад)\n"
        f"🏪 <b>Магазин:</b> /shop (Инструменты)\n"
        f"🔋 <b>Ферма:</b> Майнинг Биткоина\n"
        f"🎁 <b>Бонус:</b> Ежечасная халява\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 Профиль | 🆘 Помощь | 🎒 Инв"
    )
    # Попытка отправить картинку
    try:
        await message.answer_photo(FSInputFile("start_img.jpg"), caption=txt)
    except:
        await message.answer(txt)

@dp.message(Command("reg"))
async def cmd_reg(message: Message):
    u = db.get_user(message.from_user.id)
    if u['registered']:
        return await message.answer("✅ <b>Вы уже зарегистрированы!</b>")

    await message.answer("📝 <b>Создаем аккаунт...</b>")
    await asyncio.sleep(1.0)
    
    if not await check_subs(message.from_user.id):
        return await message.answer(
            "🔒 <b>Обязательная проверка!</b>\nПодпишитесь на каналы спонсоров:",
            reply_markup=kb_sub_check()
        )
    
    u['registered'] = True
    await db.async_save()
    await message.answer("✅ <b>Регистрация завершена!</b> Приятной игры!", reply_markup=None)
    await send_main_interface(message)

@dp.callback_query(F.data == "reg_check_sub")
async def cb_reg_check(call: CallbackQuery):
    if await check_subs(call.from_user.id):
        u = db.get_user(call.from_user.id)
        u['registered'] = True
        await db.async_save()
        await call.message.delete()
        await call.message.answer("✅ <b>Успешно!</b> Жмите /start")
    else:
        await call.answer("❌ Вы не подписаны!", show_alert=True)

@dp.message(F.text.lower() == "помощь")
async def cmd_help(message: Message):
    txt = (
        "📚 <b>СПРАВОЧНИК КОМАНД</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎰 <b>АЗАРТНЫЕ ИГРЫ:</b>\n"
        "• <code>Рул [сумма] [к/ч/з/число]</code> - Рулетка\n"
        "• <code>Кости [сумма] [больше/меньше/равно]</code>\n"
        "• <code>Футбол [сумма] [гол/мимо]</code>\n"
        "• <code>Алмазы [сумма] [1/2]</code> - Сапер с бомбами\n"
        "• <code>Мины [сумма]</code> - Классические мины\n\n"
        "💰 <b>ЗАРАБОТОК:</b>\n"
        "• <code>/work</code> или <code>Работа</code> - Искать клад\n"
        "• <code>Ферма</code> - Управление видеокартами\n"
        "• <code>Бонус</code> - Получить деньги (раз в час)\n\n"
        "⚙️ <b>ПРОФИЛЬ:</b>\n"
        "• <code>Профиль</code> - Статистика\n"
        "• <code>Инв</code> - Инвентарь\n"
        "• <code>/shop</code> - Покупка инструментов\n"
        "• <code>Перевести [ID] [Сумма]</code> - Перевод игроку\n"
        "• <code>Создать промо [код] [сумма] [кол-во]</code>\n"
        "• <code>/pr [код]</code> - Ввод промокода"
    )
    await message.answer(txt)

# ==========================================
# ОБРАБОТЧИКИ: ЭКОНОМИКА И ПРОФИЛЬ
# ==========================================

@dp.message(F.text.lower().in_({"профиль", "я", "profile", "stats"}))
async def cmd_profile(message: Message):
    u = db.get_user(message.from_user.id)
    req_xp = get_level_req(u['lvl'])
    
    # Считаем стоимость фермы
    farm_value = 0
    for k, v in u['farm'].items():
        if k in FARM_CONFIG:
            farm_value += v * FARM_CONFIG[k]['price']
            
    txt = (
        f"👤 <b>ЛИЧНОЕ ДЕЛО: {u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"💰 Баланс: <b>{format_num(u['balance'])} $</b>\n"
        f"🪙 Криптокошелек: <b>{u['btc']:.6f} BTC</b> (~{format_num(u['btc'] * db.market_btc)}$)\n"
        f"⭐ Уровень: <b>{u['lvl']}</b> [{u['xp']}/{req_xp} XP]\n"
        f"🏭 Стоимость фермы: <b>{format_num(farm_value)} $</b>\n"
        f"📅 В игре с: {datetime.fromtimestamp(u['reg_date']).strftime('%d.%m.%Y')}"
    )
    await message.answer(txt)

@dp.message(F.text.lower().in_({"инв", "инвентарь", "inv"}))
async def cmd_inventory(message: Message):
    u = db.get_user(message.from_user.id)
    inv = u['inventory']
    txt = (
        f"🎒 <b>ВАШ ИНВЕНТАРЬ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🛠 Лопата: {'✅ Есть' if inv['shovel'] else '❌ Нет'}\n"
        f"📡 Металлоискатель: {'✅ Есть' if inv['detector'] else '❌ Нет'}\n\n"
        f"<i>Для работы используйте команду /work</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏪 Перейти в магазин", callback_data="open_shop")]])
    await message.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "open_shop")
async def open_shop_cb(call: CallbackQuery):
    await call.message.delete()
    await cmd_shop(call.message)

@dp.message(F.text.lower().in_({"shop", "магазин", "/shop"}))
async def cmd_shop(message: Message):
    u = db.get_user(message.from_user.id)
    await message.answer("🏪 <b>МАГАЗИН ОБОРУДОВАНИЯ</b>\nЗдесь можно купить предметы для работы.", reply_markup=kb_shop(u))

@dp.callback_query(F.data.startswith("buy_tool_"))
async def cb_buy_tool(call: CallbackQuery):
    tool = call.data.split("_")[2]
    u = db.get_user(call.from_user.id)
    cfg = WORK_CONFIG['tools'][tool]
    
    if u['balance'] < cfg['price']:
        return await call.answer("❌ Недостаточно средств!", show_alert=True)
    
    u['balance'] -= cfg['price']
    u['inventory'][tool] = True
    await db.async_save()
    
    await call.message.edit_text(f"✅ <b>Успешно куплено: {cfg['name']}!</b>", reply_markup=None)
    await call.message.answer("Теперь можно работать: /work")

@dp.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    u = db.get_user(message.from_user.id)
    now = time.time()
    if now - u['last_bonus'] < 3600:
        rem = int(3600 - (now - u['last_bonus']))
        m, s = divmod(rem, 60)
        return await message.answer(f"⏳ <b>Подождите:</b> {m} мин. {s} сек.")
    
    # Расчет бонуса от уровня
    # Формула: База + (Лвл-1)*Шаг
    reward = LEVEL_CONFIG['bonus_base'] + ((u['lvl'] - 1) * LEVEL_CONFIG['bonus_step'])
    
    u['balance'] += reward
    u['last_bonus'] = now
    await db.async_save()
    
    await message.answer(f"🎁 <b>Ежечасный бонус получен!</b>\n➕ {format_num(reward)} $\n<i>(Чем выше уровень, тем больше бонус!)</i>")

@dp.message(F.text.lower().startswith("перевести"))
async def cmd_transfer(message: Message):
    try:
        args = message.text.split()
        if len(args) < 3: raise ValueError
        
        target_id = int(args[1])
        amount = parse_
        def parse_money(text: str, user_balance: int) -> Optional[int]:
    """
    Профессиональный парсер денежных сумм.
    Поддерживает сокращения: к, кк, ккк, вабанк.
    """
    try:
        text = str(text).lower().strip().replace(",", ".")
        if text in ["все", "всё", "all", "вабанк", "max", "баланс"]:
            return int(user_balance)
        
        # Обработка буквенных множителей
        multipliers = {
            "кккк": 1_000_000_000_000,
            "ккк": 1_000_000_000,
            "кк": 1_000_000,
            "к": 1_000
        }
        
        for suffix, factor in multipliers.items():
            if text.endswith(suffix):
                num_part = text[:-len(suffix)]
                return int(float(num_part) * factor)
        
        # Обычное число
        val = int(float(text))
        return val if val > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None

# ==========================================
# СИСТЕМА ПОДПИСОК И ПРОВЕРОК
# ==========================================

async def check_subs(user_id: int) -> bool:
    """Проверка подписки пользователя на обязательные каналы спонсоров"""
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["username"], user_id=user_id)
            if member.status in ['left', 'kicked', 'restricted']:
                logger.info(f"User {user_id} NOT subscribed to {channel['username']}")
                return False
        except Exception as e:
            logger.error(f"Error checking sub for {user_id} on {channel['username']}: {e}")
            # Если бот не имеет прав в канале, считаем что подписка есть, чтобы не ломать игру
            continue 
    return True

# ==========================================
# ЛОГИКА УРОВНЕЙ И ОПЫТА
# ==========================================

def get_level_req(lvl: int) -> int:
    """Расчет необходимого опыта для следующего уровня (прогрессивная шкала)"""
    return lvl * LEVEL_CONFIG["xp_step"]

def add_exp(u: dict, amount: int) -> bool:
    """Добавление опыта и проверка повышения уровня"""
    u['xp'] += amount
    leveled_up = False
    
    # Цикл на случай, если опыта пришло сразу на несколько уровней
    while u['xp'] >= get_level_req(u['lvl']):
        u['xp'] -= get_level_req(u['lvl'])
        u['lvl'] += 1
        leveled_up = True
        logger.info(f"User {u.get('name')} reached level {u['lvl']}")
    
    return leveled_up

# ==========================================
# ИНТЕРФЕЙСЫ И КЛАВИАТУРЫ (UI/UX)
# ==========================================

def get_shop_kb(u: dict) -> InlineKeyboardMarkup:
    """Динамическая клавиатура магазина на основе инвентаря"""
    builder = []
    inv = u.get('inventory', {})
    
    # Инструменты для работы
    for item_id, item_data in WORK_CONFIG['tools'].items():
        status = "✅ Куплено" if inv.get(item_id) else f"🛒 Купить за {format_num(item_data['price'])}$"
        callback = "ignore" if inv.get(item_id) else f"buy_tool_{item_id}"
        builder.append([InlineKeyboardButton(text=f"{item_data['name']} | {status}", callback_data=callback)])
    
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_farm_kb(u: dict) -> InlineKeyboardMarkup:
    """Клавиатура управления фермой"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Собрать прибыль", callback_data="farm_collect")],
        [InlineKeyboardButton(text="🛒 Магазин видеокарт", callback_data="farm_shop_open")],
        [InlineKeyboardButton(text="🔄 Обновить данные", callback_data="farm_refresh")]
    ])

# ==========================================
# ОБРАБОТЧИКИ КОМАНД (HANDLERS)
# ==========================================

@dp.message(Command("reg"))
async def cmd_registration(message: Message):
    """Процесс регистрации нового пользователя"""
    u = db.get_user(message.from_user.id, message.from_user.first_name)
    
    if u['registered']:
        return await message.answer("✅ Вы уже являетесь участником системы!")

    if not await check_subs(message.from_user.id):
        kb = []
        for ch in REQUIRED_CHANNELS:
            kb.append([InlineKeyboardButton(text=f"Подписаться на {ch['username']}", url=ch['link'])])
        kb.append([InlineKeyboardButton(text="💎 Я ПОДПИСАЛСЯ", callback_data="check_reg_sub")])
        
        return await message.answer(
            "⚠️ <b>Доступ ограничен!</b>\n\nДля регистрации подпишитесь на наши каналы:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
    
    u['registered'] = True
    await db.async_save()
    await message.answer(f"🎉 <b>Поздравляем, {u['name']}!</b>\nВаш аккаунт успешно создан. Вам начислено 5,000$ стартового капитала.\n\nИспользуйте /start для входа в меню.")

@dp.message(F.text.lower().in_({"профиль", "статистика", "stats"}))
async def show_profile(message: Message):
    """Вывод детальной статистики игрока"""
    u = db.get_user(message.from_user.id)
    
    # Расчет прогресса уровня
    req = get_level_req(u['lvl'])
    progress_bar = "🟢" * int((u['xp']/req)*10) + "⚪" * (10 - int((u['xp']/req)*10))
    
    text = (
        f"👤 <b>ПРОФИЛЬ: {u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <code>{format_num(u['balance'])} $</code>\n"
        f"🪙 Биткоины: <code>{u['btc']:.6f} BTC</code>\n"
        f"⭐ Уровень: <b>{u['lvl']}</b>\n"
        f"📊 Опыт: [{progress_bar}] {u['xp']}/{req}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 Регистрация: {datetime.fromtimestamp(u['reg_date']).strftime('%d.%m.%Y')}\n"
        f"🕹 Игр сыграно: {u['stats'].get('games_played', 0)}\n"
        f"🏆 Побед: {u['stats'].get('won', 0)}"
    )
    await message.answer(text)

@dp.message(F.text.lower().startswith("перевести"))
async def transfer_money(message: Message):
    """Безопасный перевод денег между игроками"""
    u = db.get_user(message.from_user.id)
    args = message.text.split()
    
    if len(args) < 3:
        return await message.answer("📝 Формат: <code>Перевести [ID] [Сумма]</code>\nID можно узнать в профиле игрока.")
    
    try:
        target_id = int(args[1])
        amount = parse_money(args[2], u['balance'])
        
        if not amount or amount <= 0:
            return await message.answer("❌ Укажите корректную сумму для перевода.")
            
        if amount > u['balance']:
            return await message.answer(f"❌ Недостаточно средств! Ваш баланс: {format_num(u['balance'])}$")
            
        if target_id == message.from_user.id:
            return await message.answer("🤔 Зачем переводить деньги самому себе?")
            
        if target_id not in db.users:
            return await message.answer("❌ Пользователь с таким ID не найден в нашей базе данных.")
            
        target_user = db.get_user(target_id)
        
        # Выполнение транзакции
        u['balance'] -= amount
        target_user['balance'] += amount
        
        await db.async_save()
        
        await message.answer(f"✅ <b>Перевод выполнен!</b>\nОтправлено: {format_num(amount)}$\nПолучатель: {target_user['name']}")
        
        try:
            await bot.send_message(target_id, f"💰 Вам поступил перевод: <b>{format_num(amount)}$</b>\nОтправитель: {u['name']} (ID: {message.from_user.id})")
        except:
            pass # Пользователь мог заблокировать бота
            
    except ValueError:
        await message.answer("❌ ID должен быть числом.")

# ==========================================
# ИГРОВЫЕ МОДУЛИ (GAMES)
# ==========================================

@dp.message(F.text.lower().startswith("рул"))
async def game_roulette(message: Message):
    """Классическая рулетка"""
    u = db.get_user(message.from_user.id)
    args = message.text.lower().split()
    
    if len(args) < 3:
        return await message.answer("🎰 <b>РУЛЕТКА</b>\nИспользование: <code>Рул [сумма] [цвет/число]</code>\nЦвета: к, ч, з\nЧисла: 0-36")
        
    bet = parse_money(args[1], u['balance'])
    if not bet or bet < 10: return await message.answer("❌ Минимальная ставка — 10$.")
    if bet > u['balance']: return await message.answer("❌ Недостаточно средств.")
    
    target = args[2]
    u['balance'] -= bet
    u['stats']['games_played'] = u['stats'].get('games_played', 0) + 1
    
    res_n = random.randint(0, 36)
    res_color = "зеленый" if res_n == 0 else "красный" if res_n in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "черный"
    
    win = 0
    # Логика проверки
    if target in ['к', 'красный', 'red'] and res_color == "красный": win = bet * 2
    elif target in ['ч', 'черный', 'black'] and res_color == "черный": win = bet * 2
    elif target in ['з', 'зеленый', 'green'] and res_color == "зеленый": win = bet * 14
    elif target.isdigit() and int(target) == res_n: win = bet * 36
    
    u['balance'] += win
    if win > 0: u['stats']['won'] = u['stats'].get('won', 0) + 1
    
    color_emoji = "🔴" if res_color == "красный" else "⚫" if res_color == "черный" else "🟢"
    result_text = f"🎉 ВЫИГРЫШ: <b>{format_num(win)}$</b>" if win > 0 else "💀 ПРОИГРЫШ"
    
    await message.reply(
        f"🎰 Крутим колесо...\n"
        f"📈 Выпало: {color_emoji} <b>{res_n} ({res_color})</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n"
        f"💰 Баланс: {format_num(u['balance'])}$"
    )
    await db.async_save()

# ==========================================
# СИСТЕМА ПРОМОКОДОВ
# ==========================================

@dp.message(F.text.lower().startswith("создать промо"))
async def admin_create_promo(message: Message):
    """Создание промокода (доступно всем по вашему запросу)"""
    try:
        parts = message.text.split()
        name = parts[2].upper()
        reward = parse_money(parts[3], 0)
        uses = int(parts[4])
        
        if name in db.promos:
            return await message.answer("❌ Такой промокод уже существует.")
            
        db.promos[name] = {
            "reward": reward,
            "uses": uses,
            "creator": message.from_user.id
        }
        await db.async_save()
        await message.answer(f"🎁 Промокод <code>{name}</code> успешно создан!\nНаграда: {format_num(reward)}$\nКол-во активаций: {uses}")
    except:
        await message.answer("📝 Формат: <code>Создать промо [КОД] [СУММА] [КОЛ-ВО]</code>")

@dp.message(Command("pr"))
async def use_promo(message: Message, command: CommandObject):
    """Активация промокода"""
    if not command.args:
        return await message.answer("📝 Введите код: <code>/pr КОД</code>")
        
    code = command.args.upper()
    u = db.get_user(message.from_user.id)
    
    if code not in db.promos:
        return await message.answer("❌ Такого промокода не существует.")
        
    promo = db.promos[code]
    if promo['uses'] <= 0:
        return await message.answer("❌ Активации данного промокода закончились.")
        
    if code in u.get('used_promos', []):
        return await message.answer("❌ Вы уже активировали этот промокод!")
        
    u['balance'] += promo['reward']
    promo['uses'] -= 1
    if 'used_promos' not in u: u['used_promos'] = []
    u['used_promos'].append(code)
    
    await db.async_save()
    await message.answer(f"✅ <b>Успех!</b>\nВы получили <b>{format_num(promo['reward'])}$</b>")

# ==========================================
# АДМИН-ПАНЕЛЬ (SECRET)
# ==========================================

@dp.message(Command("hhh"))
async def admin_give_bal(message: Message, command: CommandObject):
    """Выдача баланса админом (ID 1997428703)"""
    if message.from_user.id not in ADMIN_IDS: return
    
    try:
        # Если команда дана ответом на сообщение
        if message.reply_to_message:
            target_id = message.reply_to_message.from_user.id
            amount = parse_money(command.args, 0)
        else:
            args = command.args.split()
            target_id = int(args[0])
            amount = parse_money(args[1], 0)
            
        t_user = db.get_user(target_id)
        t_user['balance'] += amount
        await db.async_save()
        await message.answer(f"💎 Администратор выдал {format_num(amount)}$ игроку {t_user['name']}")
    except:
        await message.answer("📝 <code>/hhh [ID] [СУММА]</code> или ответом на сообщение.")

# ==========================================
# ЗАПУСК БОТА (STARTUP)
# ==========================================

async def background_tasks():
    """Задачи, выполняемые в фоновом режиме"""
    while True:
        try:
            # Обновление курса биткоина раз в час
            db.market_btc = random.randint(15000, 180000)
            # Авто-сохранение данных
            await db.async_save()
            logger.info("Background tasks executed: BTC price updated & DB saved.")
        except Exception as e:
            logger.error(f"Error in background task: {e}")
        await asyncio.sleep(3600)

async def main():
    """Главная функция инициализации"""
    print("--- STARTING VIBE BET SYSTEM ---")
    
    # 1. Загрузка базы данных
    db.load()
    
    # 2. Запуск фоновых задач
    asyncio.create_task(background_tasks())
    
    # 3. Настройка Web-сервера для предотвращения сна (Render)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    # 4. Удаление старых обновлений и запуск Polling
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot turned off manually")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
