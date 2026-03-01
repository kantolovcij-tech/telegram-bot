import asyncio
import logging
import sqlite3
import uuid
import threading
import time
import requests
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8512473902:AAEjXmCgzsZ6ikZG0js2lwh_NRnDJwUuSMM"
ADMIN_IDS = [7654091786, 8259572484]  # Два админа
RENDER_URL = "https://telegram-bot-phe1.onrender.com"  # URL бота
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

# ==================== ВЕБ-СЕРВЕР ДЛЯ RENDER ====================
from http.server import HTTPServer, BaseHTTPRequestHandler

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"Bot is alive! Server time: {datetime.now()}".encode())
        
def run_web_server():
    """Запускает веб-сервер на порту 10000 для пингов от Render"""
    try:
        server = HTTPServer(('0.0.0.0', 10000), PingHandler)
        print(f"✅ Веб-сервер запущен на порту 10000 в {datetime.now().strftime('%H:%M:%S')}")
        server.serve_forever()
    except Exception as e:
        print(f"❌ Ошибка веб-сервера: {e}")

# Запускаем веб-сервер в отдельном потоке
threading.Thread(target=run_web_server, daemon=True).start()

# Функция для пинга самого себя (каждые 5 минут)
def self_ping():
    """Каждые 5 минут пингует свой URL, чтобы Render не усыпил бота"""
    time.sleep(30)  # Даем время серверу запуститься
    while True:
        try:
            response = requests.get(RENDER_URL, timeout=30)
            now = datetime.now().strftime('%H:%M:%S')
            print(f"✅ Само-пинг в {now} | Статус: {response.status_code}")
        except Exception as e:
            now = datetime.now().strftime('%H:%M:%S')
            print(f"❌ Ошибка само-пинга в {now}: {e}")
        time.sleep(300)  # 5 минут

threading.Thread(target=self_ping, daemon=True).start()
# ===============================================================

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    with sqlite3.connect('data.db') as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, 
                balance_usd REAL DEFAULT 0,
                balance_rub REAL DEFAULT 0,
                balance_ton REAL DEFAULT 0,
                balance_stars REAL DEFAULT 0,
                card TEXT, wallet TEXT, verified INTEGER DEFAULT 0, deals INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS deals (
                deal_id TEXT PRIMARY KEY, seller_id INTEGER, seller_name TEXT,
                buyer TEXT, item TEXT, amount REAL, currency TEXT, status TEXT, created TEXT
            );
            CREATE TABLE IF NOT EXISTS withdraws (
                req_id TEXT PRIMARY KEY, user_id INTEGER, amount REAL, currency TEXT,
                method TEXT, details TEXT, status TEXT, date TEXT
            );
        ''')
init_db()

# ==================== ФУНКЦИИ ====================
def db_exec(query, params=()):
    with sqlite3.connect('data.db') as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        return cur.fetchall()

def get_user(user_id):
    r = db_exec("SELECT * FROM users WHERE user_id=?", (user_id,))
    return r[0] if r else None

def create_user(user_id, username):
    db_exec("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))

def update_balance(user_id, currency, amount):
    """Обновление баланса в указанной валюте"""
    col_map = {
        "USD": "balance_usd",
        "RUB": "balance_rub", 
        "TON": "balance_ton",
        "STARS": "balance_stars"
    }
    col = col_map.get(currency)
    if col:
        db_exec(f"UPDATE users SET {col} = {col} + ? WHERE user_id=?", (amount, user_id))

def get_balance_text(user):
    """Возвращает текст со всеми балансами"""
    return (f"💰 <b>ВАШ БАЛАНС</b>\n━━━━━━━━━━━━━━━━\n"
            f"🇺🇸 USD: <b>${user[2]:.2f}</b>\n"
            f"🇷🇺 RUB: <b>₽{user[3]:.2f}</b>\n"
            f"💎 TON: <b>{user[4]:.2f} TON</b>\n"
            f"⭐ STARS: <b>{user[5]:.0f} ⭐</b>")

def create_deal(seller_id, seller_name, buyer, item, amount, currency):
    deal_id = str(uuid.uuid4())[:8].upper()
    db_exec("INSERT INTO deals VALUES (?,?,?,?,?,?,?,?,?)", 
            (deal_id, seller_id, seller_name, buyer, item, amount, currency, "waiting", datetime.now().strftime("%d.%m %H:%M")))
    return deal_id

def get_deal(deal_id):
    r = db_exec("SELECT * FROM deals WHERE deal_id=?", (deal_id,))
    return r[0] if r else None

def update_deal(deal_id, status):
    db_exec("UPDATE deals SET status=? WHERE deal_id=?", (status, deal_id))

def get_deals(status=None):
    if status:
        return db_exec("SELECT * FROM deals WHERE status=? ORDER BY created DESC", (status,))
    return db_exec("SELECT * FROM deals ORDER BY created DESC")

def save_card(uid, card, holder):
    db_exec("UPDATE users SET card=?, holder=?, verified=1 WHERE user_id=?", (card, holder, uid))

def save_wallet(uid, wallet):
    db_exec("UPDATE users SET wallet=?, verified=1 WHERE user_id=?", (wallet, uid))

def create_withdraw(uid, amount, currency, method, details):
    req_id = str(uuid.uuid4())[:8].upper()
    db_exec("INSERT INTO withdraws VALUES (?,?,?,?,?,?,?,?)",
            (req_id, uid, amount, currency, method, details, "pending", datetime.now().strftime("%d.%m %H:%M")))
    return req_id

def get_withdraws(status="pending"):
    return db_exec("SELECT * FROM withdraws WHERE status=? ORDER BY date", (status,))

def update_withdraw(req_id, status):
    db_exec("UPDATE withdraws SET status=? WHERE req_id=?", (status, req_id))

# ==================== СОСТОЯНИЯ ====================
class States:
    class Seller(StatesGroup):
        buyer = State()
        item = State()
        amount = State()
        currency = State()
    class Withdraw(StatesGroup):
        amount = State()
        currency = State()
        card = State()
        holder = State()
        wallet = State()
    class Admin(StatesGroup):
        user_id = State()
        amount = State()
        currency = State()

# ==================== КЛАВИАТУРЫ ====================
def kb_main(uid):
    user = get_user(uid)
    if user:
        bal_text = f"💰 {user[2]:.1f}$ | {user[3]:.0f}₽ | {user[4]:.1f}TON | {user[5]:.0f}⭐"
    else:
        bal_text = "💰 Баланс"
    
    if uid in ADMIN_IDS:
        buttons = [
            [InlineKeyboardButton(text="📋 СДЕЛКИ", callback_data="deals")],
            [InlineKeyboardButton(text=bal_text, callback_data="balance")],
            [InlineKeyboardButton(text="⚙️ АДМИН", callback_data="admin")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton(text="📝 ПРОДАТЬ", callback_data="sell")],
            [InlineKeyboardButton(text=bal_text, callback_data="balance")],
            [InlineKeyboardButton(text="💳 КОШЕЛЕК", callback_data="wallet")],
            [InlineKeyboardButton(text="💸 ВЫВОД", callback_data="withdraw")]
        ]
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_currency():
    """Клавиатура выбора валюты"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇸 ДОЛЛАР (USD)", callback_data="cur_usd")],
        [InlineKeyboardButton(text="🇷🇺 РУБЛЬ (RUB)", callback_data="cur_rub")],
        [InlineKeyboardButton(text="💎 TON", callback_data="cur_ton")],
        [InlineKeyboardButton(text="⭐ ЗВЕЗДЫ (STARS)", callback_data="cur_stars")],
        [InlineKeyboardButton(text="◀️ НАЗАД", callback_data="back")]
    ])

def kb_withdraw_currency(balances):
    """Клавиатура выбора валюты для вывода (только с положительным балансом)"""
    buttons = []
    if balances[2] > 0:
        buttons.append([InlineKeyboardButton(text=f"🇺🇸 ДОЛЛАР (${balances[2]:.2f})", callback_data="wcur_usd")])
    if balances[3] > 0:
        buttons.append([InlineKeyboardButton(text=f"🇷🇺 РУБЛЬ (₽{balances[3]:.2f})", callback_data="wcur_rub")])
    if balances[4] > 0:
        buttons.append([InlineKeyboardButton(text=f"💎 TON ({balances[4]:.2f})", callback_data="wcur_ton")])
    if balances[5] > 0:
        buttons.append([InlineKeyboardButton(text=f"⭐ ЗВЕЗДЫ ({balances[5]:.0f})", callback_data="wcur_stars")])
    
    buttons.append([InlineKeyboardButton(text="◀️ НАЗАД", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_deal(deal_id, status, role):
    buttons = []
    
    if role == "buyer":
        if status == "waiting":
            buttons.append([InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ ОПЛАТУ", callback_data=f"pay_{deal_id}")])
        elif status == "sent":
            buttons.append([InlineKeyboardButton(text="📦 ПОЛУЧИЛ ТОВАР", callback_data=f"done_{deal_id}")])
    else:
        if status == "paid":
            buttons.append([InlineKeyboardButton(text="📦 ОТПРАВИЛ ТОВАР", callback_data=f"send_{deal_id}")])
    
    if status not in ["done"]:
        buttons.append([InlineKeyboardButton(text="❌ ОТМЕНИТЬ СДЕЛКУ", callback_data=f"cancel_{deal_id}")])
    
    buttons.append([InlineKeyboardButton(text="◀️ НАЗАД", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ НАЗАД", callback_data="back")]
    ])

def kb_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 ПОЛЬЗОВАТЕЛИ", callback_data="a_users")],
        [InlineKeyboardButton(text="💰 НАКРУТКА", callback_data="a_balance")],
        [InlineKeyboardButton(text="📋 ЗАЯВКИ", callback_data="a_withdraws")],
        [InlineKeyboardButton(text="📊 СТАТИСТИКА", callback_data="a_stats")],
        [InlineKeyboardButton(text="◀️ ГЛАВНОЕ", callback_data="back")]
    ])

def kb_payment_methods():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 КАРТА", callback_data="add_card")],
        [InlineKeyboardButton(text="₿ КОШЕЛЕК", callback_data="add_wallet")],
        [InlineKeyboardButton(text="◀️ НАЗАД", callback_data="back")]
    ])

def kb_admin_withdraw():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ ВСЕ", callback_data="a_approve_all")],
        [InlineKeyboardButton(text="◀️ НАЗАД", callback_data="admin")]
    ])

# ==================== КОМАНДА /ADMIN ====================
@dp.message(Command('admin'))
async def admin_command(msg: Message):
    if msg.from_user.id in ADMIN_IDS:
        await msg.answer(
            "⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n"
            "━━━━━━━━━━━━━━━━\n"
            "Выберите действие:",
            parse_mode="HTML",
            reply_markup=kb_admin_panel()
        )
    else:
        await msg.answer("❌ У вас нет доступа")

# ==================== СТАРТ ====================
@dp.message(CommandStart())
async def start(msg: Message):
    create_user(msg.from_user.id, msg.from_user.username or "no_name")
    is_admin = " АДМИН" if msg.from_user.id in ADMIN_IDS else ""
    await msg.answer(f"👋 ДОБРО ПОЖАЛОВАТЬ{is_admin}!", reply_markup=kb_main(msg.from_user.id))

@dp.callback_query(F.data == "back")
async def back(call: CallbackQuery):
    await call.message.edit_text("ГЛАВНОЕ МЕНЮ:", reply_markup=kb_main(call.from_user.id))
    await call.answer()

# ==================== БАЛАНС ====================
@dp.callback_query(F.data == "balance")
async def balance(call: CallbackQuery):
    u = get_user(call.from_user.id)
    txt = get_balance_text(u)
    if u[6]: txt += f"\n💳 Карта: {u[6][:4]}****{u[6][-4:]}"
    if u[7]: txt += f"\n₿ Кошелек: {u[7][:6]}...{u[7][-4:]}"
    await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb_back())

# ==================== ПРОДАВЕЦ ====================
@dp.callback_query(F.data == "sell")
async def sell_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("👤 Введите @username покупателя:")
    await state.set_state(States.Seller.buyer)
    await call.answer()

@dp.message(States.Seller.buyer)
async def sell_buyer(msg: Message, state: FSMContext):
    if not msg.text.startswith('@'): 
        await msg.answer("❌ Должно начинаться с @")
        return
    await state.update_data(buyer=msg.text)
    await msg.answer("📦 Введите название товара:")
    await state.set_state(States.Seller.item)

@dp.message(States.Seller.item)
async def sell_item(msg: Message, state: FSMContext):
    await state.update_data(item=msg.text)
    await msg.answer("💰 Выберите валюту:", reply_markup=kb_currency())
    await state.set_state(States.Seller.currency)

@dp.callback_query(F.data.startswith("cur_"))
async def sell_currency(call: CallbackQuery, state: FSMContext):
    currency_map = {
        "cur_usd": "USD",
        "cur_rub": "RUB", 
        "cur_ton": "TON",
        "cur_stars": "STARS"
    }
    currency = currency_map.get(call.data)
    if not currency:
        return
    
    await state.update_data(currency=currency)
    
    currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
    symbol = currency_symbols.get(currency, "")
    
    await call.message.edit_text(f"💰 Введите сумму в {currency} {symbol}:")
    await state.set_state(States.Seller.amount)
    await call.answer()

@dp.message(States.Seller.amount)
async def sell_amount(msg: Message, state: FSMContext):
    try:
        amount = float(msg.text)
        data = await state.get_data()
        
        deal_id = create_deal(
            msg.from_user.id, 
            msg.from_user.username, 
            data['buyer'], 
            data['item'], 
            amount, 
            data['currency']
        )
        
        currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
        symbol = currency_symbols.get(data['currency'], "")
        
        await msg.answer(
            f"✅ <b>СДЕЛКА СОЗДАНА!</b>\n━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: <code>{deal_id}</code>\n"
            f"📦 Товар: {data['item']}\n"
            f"💰 Сумма: {symbol}{amount:.2f} {data['currency']}\n"
            f"👤 Покупатель: {data['buyer']}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏳ Ожидайте подтверждения",
            parse_mode="HTML",
            reply_markup=kb_main(msg.from_user.id)
        )
        
        # Уведомление админам
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🆕 <b>НОВАЯ СДЕЛКА!</b>\n━━━━━━━━━━━━━━━━\n"
                    f"🆔 ID: <code>{deal_id}</code>\n"
                    f"📦 Товар: {data['item']}\n"
                    f"💰 Сумма: {symbol}{amount:.2f} {data['currency']}\n"
                    f"👤 Продавец: @{msg.from_user.username}\n"
                    f"👤 Покупатель: {data['buyer']}",
                    parse_mode="HTML",
                    reply_markup=kb_deal(deal_id, "waiting", "buyer")
                )
            except:
                pass
        await state.clear()
    except ValueError:
        await msg.answer("❌ Введите число")
    except Exception as e:
        await msg.answer(f"❌ Ошибка: {e}")

# ==================== ПОКУПАТЕЛЬ (АДМИНЫ) ====================
@dp.callback_query(F.data.startswith("pay_"))
async def pay_deal(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа!", show_alert=True)
    
    deal_id = call.data[4:]
    deal = get_deal(deal_id)
    if not deal:
        return await call.answer("❌ Сделка не найдена!", show_alert=True)
    
    update_deal(deal_id, "paid")
    
    currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
    symbol = currency_symbols.get(deal[6], "")
    
    await call.message.edit_text(
        f"✅ <b>ОПЛАТА ПОДТВЕРЖДЕНА!</b>\n━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{deal_id}</code>",
        parse_mode="HTML",
        reply_markup=kb_main(call.from_user.id)
    )
    
    await bot.send_message(
        deal[1],
        f"💰 <b>ОПЛАТА ПОЛУЧЕНА!</b>\n━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{deal_id}</code>\n"
        f"💰 Сумма: {symbol}{deal[5]:.2f} {deal[6]}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 Отправьте товар и нажмите кнопку:",
        parse_mode="HTML",
        reply_markup=kb_deal(deal_id, "paid", "seller")
    )
    await call.answer("✅ Оплата подтверждена!")

@dp.callback_query(F.data.startswith("send_"))
async def send_deal(call: CallbackQuery):
    deal_id = call.data[5:]
    deal = get_deal(deal_id)
    
    if not deal or call.from_user.id != deal[1]:
        return await call.answer("❌ Ошибка доступа!", show_alert=True)
    
    update_deal(deal_id, "sent")
    await call.message.edit_text(
        f"📦 <b>ТОВАР ОТПРАВЛЕН!</b>\n━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{deal_id}</code>",
        parse_mode="HTML",
        reply_markup=kb_main(deal[1])
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📦 <b>ТОВАР ОТПРАВЛЕН!</b>\n━━━━━━━━━━━━━━━━\n"
                f"🆔 ID: <code>{deal_id}</code>\n"
                f"✅ Подтвердите получение:",
                parse_mode="HTML",
                reply_markup=kb_deal(deal_id, "sent", "buyer")
            )
        except:
            pass
    await call.answer("✅ Статус обновлен!")

@dp.callback_query(F.data.startswith("done_"))
async def done_deal(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа!", show_alert=True)
    
    deal_id = call.data[5:]
    deal = get_deal(deal_id)
    if not deal:
        return await call.answer("❌ Сделка не найдена!", show_alert=True)
    
    update_deal(deal_id, "done")
    update_balance(deal[1], deal[6], deal[5])
    
    currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
    symbol = currency_symbols.get(deal[6], "")
    
    await call.message.edit_text(
        f"🎉 <b>СДЕЛКА ЗАВЕРШЕНА!</b>\n━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{deal_id}</code>",
        parse_mode="HTML",
        reply_markup=kb_main(call.from_user.id)
    )
    
    await bot.send_message(
        deal[1],
        f"✅ <b>ДЕНЬГИ ЗАЧИСЛЕНЫ!</b>\n━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{deal_id}</code>\n"
        f"💰 Сумма: {symbol}{deal[5]:.2f} {deal[6]}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💸 Средства доступны для вывода.",
        parse_mode="HTML",
        reply_markup=kb_main(deal[1])
    )
    await call.answer("🎉 Сделка завершена!")

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_deal(call: CallbackQuery):
    deal_id = call.data[7:]
    deal = get_deal(deal_id)
    
    if not deal:
        return await call.answer("❌ Сделка не найдена!", show_alert=True)
    
    if call.from_user.id != deal[1] and call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа!", show_alert=True)
    
    update_deal(deal_id, "cancelled")
    await call.message.edit_text(
        f"❌ <b>СДЕЛКА ОТМЕНЕНА</b>\n━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{deal_id}</code>",
        parse_mode="HTML",
        reply_markup=kb_main(call.from_user.id)
    )
    
    if call.from_user.id in ADMIN_IDS:
        await bot.send_message(deal[1], f"❌ Сделка {deal_id} отменена гарантом.")
    else:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, f"❌ Сделка {deal_id} отменена продавцом.")
            except:
                pass
    await call.answer("❌ Сделка отменена!")

@dp.callback_query(F.data == "deals")
async def show_deals(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа!", show_alert=True)
    
    deals = get_deals()
    if not deals:
        await call.message.edit_text("📋 <b>СПИСОК СДЕЛОК</b>\n━━━━━━━━━━━━━━━━\n❌ Сделок пока нет.", parse_mode="HTML", reply_markup=kb_back())
        return
    
    currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
    
    txt = "📋 <b>СПИСОК СДЕЛОК</b>\n━━━━━━━━━━━━━━━━\n"
    for d in deals[:10]:
        status_emoji = {"waiting":"🆕","paid":"💰","sent":"📦","done":"✅","cancelled":"❌"}.get(d[7], "⏳")
        symbol = currency_symbols.get(d[6], "")
        txt += f"{status_emoji} <code>{d[0]}</code> | {d[4]} | {symbol}{d[5]:.2f} {d[6]} | @{d[2]}\n"
    
    await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb_back())

# ==================== КОШЕЛЕК ====================
@dp.callback_query(F.data == "wallet")
async def wallet_menu(call: CallbackQuery):
    await call.message.edit_text(
        "💳 <b>ПРИВЯЗКА РЕКВИЗИТОВ</b>\n━━━━━━━━━━━━━━━━\nВыберите способ:",
        parse_mode="HTML",
        reply_markup=kb_payment_methods()
    )

@dp.callback_query(F.data == "add_card")
async def add_card(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("💳 Введите номер карты (16 цифр):")
    await state.set_state(States.Withdraw.card)
    await call.answer()

@dp.message(States.Withdraw.card)
async def proc_card(msg: Message, state: FSMContext):
    card = msg.text.replace(" ", "")
    if not card.isdigit() or len(card) != 16:
        await msg.answer("❌ Неверный формат")
        return
    
    await state.update_data(card=card)
    await msg.answer("Введите имя владельца:")
    await state.set_state(States.Withdraw.holder)

@dp.message(States.Withdraw.holder)
async def proc_holder(msg: Message, state: FSMContext):
    data = await state.get_data()
    save_card(msg.from_user.id, data['card'], msg.text.upper())
    await msg.answer(
        "✅ <b>КАРТА ПРИВЯЗАНА!</b>",
        parse_mode="HTML",
        reply_markup=kb_main(msg.from_user.id)
    )
    await state.clear()

@dp.callback_query(F.data == "add_wallet")
async def add_wallet(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("₿ Введите адрес кошелька (USDT TRC20):")
    await state.set_state(States.Withdraw.wallet)
    await call.answer()

@dp.message(States.Withdraw.wallet)
async def proc_wallet(msg: Message, state: FSMContext):
    save_wallet(msg.from_user.id, msg.text.strip())
    await msg.answer(
        "✅ <b>КОШЕЛЕК ПРИВЯЗАН!</b>",
        parse_mode="HTML",
        reply_markup=kb_main(msg.from_user.id)
    )
    await state.clear()

# ==================== ВЫВОД ====================
@dp.callback_query(F.data == "withdraw")
async def withdraw_start(call: CallbackQuery, state: FSMContext):
    u = get_user(call.from_user.id)
    
    if not u[6] and not u[7]:
        await call.message.edit_text(
            "❌ <b>РЕКВИЗИТЫ НЕ НАЙДЕНЫ</b>\n━━━━━━━━━━━━━━━━\nСначала привяжите карту или кошелек",
            parse_mode="HTML",
            reply_markup=kb_back()
        )
        return
    
    await call.message.edit_text(
        get_balance_text(u) + "\n━━━━━━━━━━━━━━━━\nВыберите валюту для вывода:",
        parse_mode="HTML",
        reply_markup=kb_withdraw_currency(u)
    )
    await state.set_state(States.Withdraw.currency)

@dp.callback_query(F.data.startswith("wcur_"))
async def withdraw_currency(call: CallbackQuery, state: FSMContext):
    currency_map = {
        "wcur_usd": "USD",
        "wcur_rub": "RUB",
        "wcur_ton": "TON",
        "wcur_stars": "STARS"
    }
    currency = currency_map.get(call.data)
    if not currency:
        return
    
    await state.update_data(currency=currency)
    
    u = get_user(call.from_user.id)
    balance_map = {"USD":2, "RUB":3, "TON":4, "STARS":5}
    available = u[balance_map[currency]]
    
    currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
    symbol = currency_symbols.get(currency, "")
    
    await call.message.edit_text(
        f"💰 <b>ВЫВОД {currency}</b>\n━━━━━━━━━━━━━━━━\n"
        f"Доступно: {symbol}{available:.2f}\n"
        f"Введите сумму:",
        parse_mode="HTML"
    )
    await state.set_state(States.Withdraw.amount)
    await call.answer()

@dp.message(States.Withdraw.amount)
async def withdraw_amount(msg: Message, state: FSMContext):
    try:
        amount = float(msg.text)
        data = await state.get_data()
        u = get_user(msg.from_user.id)
        
        balance_map = {"USD":2, "RUB":3, "TON":4, "STARS":5}
        balance_idx = balance_map[data['currency']]
        
        if amount <= 0:
            await msg.answer("❌ Сумма должна быть больше 0")
            return
        
        if amount > u[balance_idx]:
            await msg.answer("❌ Недостаточно средств")
            return
        
        await state.update_data(amount=amount)
        
        # Списываем баланс
        update_balance(msg.from_user.id, data['currency'], -amount)
        
        # Создаем заявку
        if u[6]:  # карта
            req_id = create_withdraw(
                msg.from_user.id, 
                amount, 
                data['currency'],
                "card", 
                f"{u[6][:4]}****{u[6][-4:]}"
            )
            method_text = f"💳 Карта: {u[6][:4]}****{u[6][-4:]}"
        else:  # кошелек
            req_id = create_withdraw(
                msg.from_user.id, 
                amount, 
                data['currency'],
                "crypto", 
                f"{u[7][:6]}...{u[7][-4:]}"
            )
            method_text = f"₿ Кошелек: {u[7][:6]}...{u[7][-4:]}"
        
        currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
        symbol = currency_symbols.get(data['currency'], "")
        
        await msg.answer(
            f"✅ <b>ЗАЯВКА СОЗДАНА!</b>\n━━━━━━━━━━━━━━━━\n"
            f"🆔 Заявка: <code>{req_id}</code>\n"
            f"💰 Сумма: {symbol}{amount:.2f} {data['currency']}\n"
            f"{method_text}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏳ Ожидайте обработки",
            parse_mode="HTML",
            reply_markup=kb_main(msg.from_user.id)
        )
        await state.clear()
        
    except ValueError:
        await msg.answer("❌ Введите число")

# ==================== АДМИН ====================
@dp.callback_query(F.data == "admin")
async def admin_menu(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа!", show_alert=True)
    
    await call.message.edit_text(
        "⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n━━━━━━━━━━━━━━━━\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=kb_admin_panel()
    )

@dp.callback_query(F.data == "a_users")
async def a_users(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    
    users = db_exec("SELECT user_id, username, balance_usd, balance_rub, balance_ton, balance_stars, verified FROM users ORDER BY balance_usd DESC LIMIT 20")
    
    txt = "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n━━━━━━━━━━━━━━━━\n"
    for u in users:
        verified = "✅" if u[6] else "❌"
        txt += f"<code>{u[0]}</code> @{u[1]}\n"
        txt += f"  💰 ${u[2]:.1f} | ₽{u[3]:.0f} | {u[4]:.1f}TON | {u[5]:.0f}⭐ | {verified}\n"
    
    await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb_back())

@dp.callback_query(F.data == "a_balance")
async def a_balance_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    
    await call.message.edit_text(
        "💰 <b>НАКРУТКА БАЛАНСА</b>\n━━━━━━━━━━━━━━━━\n"
        "Введите ID пользователя:",
        parse_mode="HTML"
    )
    await state.set_state(States.Admin.user_id)
    await call.answer()

@dp.message(States.Admin.user_id)
async def a_balance_user(msg: Message, state: FSMContext):
    try:
        uid = int(msg.text)
        user = get_user(uid)
        
        if not user:
            await msg.answer("❌ Пользователь не найден")
            await state.clear()
            return
        
        await state.update_data(uid=uid)
        await msg.answer(
            "Выберите валюту:",
            reply_markup=kb_currency()
        )
        await state.set_state(States.Admin.currency)
    except ValueError:
        await msg.answer("❌ Введите ID")

@dp.callback_query(States.Admin.currency, F.data.startswith("cur_"))
async def a_balance_currency(call: CallbackQuery, state: FSMContext):
    currency_map = {
        "cur_usd": "USD",
        "cur_rub": "RUB",
        "cur_ton": "TON",
        "cur_stars": "STARS"
    }
    currency = currency_map.get(call.data)
    if not currency:
        return
    
    await state.update_data(currency=currency)
    
    currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
    symbol = currency_symbols.get(currency, "")
    
    await call.message.edit_text(f"Введите сумму в {currency} {symbol}:")
    await state.set_state(States.Admin.amount)
    await call.answer()

@dp.message(States.Admin.amount)
async def a_balance_amount(msg: Message, state: FSMContext):
    try:
        amount = float(msg.text)
        data = await state.get_data()
        
        update_balance(data['uid'], data['currency'], amount)
        
        currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
        symbol = currency_symbols.get(data['currency'], "")
        
        try:
            await bot.send_message(
                data['uid'],
                f"🎉 <b>ВАМ НАЧИСЛЕНО!</b>\n━━━━━━━━━━━━━━━━\n"
                f"💰 {symbol}{amount:.2f} {data['currency']}",
                parse_mode="HTML"
            )
        except:
            pass
        
        await msg.answer(
            f"✅ <b>ГОТОВО!</b>\n━━━━━━━━━━━━━━━━\n"
            f"👤 Пользователь: {data['uid']}\n"
            f"💰 Сумма: {symbol}{amount:.2f} {data['currency']}",
            parse_mode="HTML",
            reply_markup=kb_main(msg.from_user.id)
        )
        await state.clear()
        
    except ValueError:
        await msg.answer("❌ Введите число")

@dp.callback_query(F.data == "a_withdraws")
async def a_withdraws(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    
    withdraws = get_withdraws("pending")
    
    if not withdraws:
        await call.message.edit_text(
            "📋 <b>ЗАЯВКИ НА ВЫВОД</b>\n━━━━━━━━━━━━━━━━\n❌ Нет активных заявок",
            parse_mode="HTML",
            reply_markup=kb_back()
        )
        return
    
    currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
    
    txt = "📋 <b>ЗАЯВКИ НА ВЫВОД</b>\n━━━━━━━━━━━━━━━━\n"
    for w in withdraws:
        symbol = currency_symbols.get(w[3], "")
        txt += f"🆔 <code>{w[0]}</code>\n"
        txt += f"👤 ID: {w[1]}\n"
        txt += f"💰 {symbol}{w[2]:.2f} {w[3]}\n"
        txt += f"📱 {w[4]}: {w[5]}\n"
        txt += f"⏰ {w[7]}\n"
        txt += "────────────────\n"
    
    await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb_admin_withdraw())

@dp.callback_query(F.data == "a_approve_all")
async def a_approve_all(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    
    withdraws = get_withdraws("pending")
    count = 0
    
    currency_symbols = {"USD":"$", "RUB":"₽", "TON":"💎", "STARS":"⭐"}
    
    for w in withdraws:
        update_withdraw(w[0], "completed")
        symbol = currency_symbols.get(w[3], "")
        try:
            await bot.send_message(
                w[1],
                f"✅ <b>ВЫВОД ВЫПОЛНЕН!</b>\n━━━━━━━━━━━━━━━━\n"
                f"🆔 Заявка: <code>{w[0]}</code>\n"
                f"💰 {symbol}{w[2]:.2f} {w[3]}\n"
                f"💸 Средства отправлены",
                parse_mode="HTML"
            )
            count += 1
        except:
            pass
    
    await call.message.edit_text(
        f"✅ <b>ГОТОВО!</b>\n━━━━━━━━━━━━━━━━\n"
        f"📋 Обработано заявок: {count}",
        parse_mode="HTML",
        reply_markup=kb_main(call.from_user.id)
    )
    await call.answer()

@dp.callback_query(F.data == "a_stats")
async def a_stats(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    
    users_count = db_exec("SELECT COUNT(*) FROM users")[0][0]
    total_usd = db_exec("SELECT SUM(balance_usd) FROM users")[0][0] or 0
    total_rub = db_exec("SELECT SUM(balance_rub) FROM users")[0][0] or 0
    total_ton = db_exec("SELECT SUM(balance_ton) FROM users")[0][0] or 0
    total_stars = db_exec("SELECT SUM(balance_stars) FROM users")[0][0] or 0
    deals_count = db_exec("SELECT COUNT(*) FROM deals")[0][0]
    done_deals = db_exec("SELECT COUNT(*) FROM deals WHERE status='done'")[0][0]
    pending_withdraws = db_exec("SELECT COUNT(*) FROM withdraws WHERE status='pending'")[0][0]
    completed_withdraws = db_exec("SELECT COUNT(*) FROM withdraws WHERE status='completed'")[0][0]
    
    txt = f"📊 <b>СТАТИСТИКА</b>\n━━━━━━━━━━━━━━━━\n"
    txt += f"👥 Пользователей: {users_count}\n\n"
    txt += f"💰 <b>ОБЩИЙ БАЛАНС:</b>\n"
    txt += f"🇺🇸 USD: ${total_usd:.2f}\n"
    txt += f"🇷🇺 RUB: ₽{total_rub:.2f}\n"
    txt += f"💎 TON: {total_ton:.2f}\n"
    txt += f"⭐ STARS: {total_stars:.0f}\n\n"
    txt += f"📊 Всего сделок: {deals_count}\n"
    txt += f"✅ Завершено: {done_deals}\n"
    txt += f"⏳ Ожидает вывода: {pending_withdraws}\n"
    txt += f"💸 Выплачено: {completed_withdraws}"
    
    await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb_back())

# ==================== ЗАПУСК ====================
async def main():
    print("✅ Бот запущен с поддержкой 4 валют")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
