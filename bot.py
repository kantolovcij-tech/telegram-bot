import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ================== НАСТРОЙКИ ==================
# ВАШИ ДАННЫЕ (уже вставлены)
BOT_TOKEN = "8623415156:AAEknOvnE8KtumXn1brqc8hWqa5xfaPBkyI"  # Ваш токен
GROUP_ID = -1003856989196  # ID вашей группы
ADMIN_ID = 5979001063  # Ваш личный ID
# ================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальный словарь для временных данных
temp_data = {}

def init_db():
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    
    # Таблица кодов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS codes (
            code TEXT PRIMARY KEY,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица пользователей (без code_used)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            anon_id INTEGER UNIQUE,
            nickname TEXT,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_online TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица для связи пользователей и кодов (новая таблица)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_codes (
            user_id INTEGER,
            code TEXT,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (code) REFERENCES codes(code)
        )
    ''')
    
    # Таблица сообщений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_message_id INTEGER UNIQUE,
            user_id INTEGER,
            message_text TEXT,
            message_type TEXT,
            file_id TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_deleted INTEGER DEFAULT 0,
            edited_at TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ База данных создана")

def add_code(code):
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO codes (code) VALUES (?)", (code,))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False
    except Exception as e:
        print(f"Ошибка добавления кода: {e}")
        conn.close()
        return False

def get_all_codes():
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    cursor.execute("SELECT code, used FROM codes ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def check_code(code):
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    cursor.execute("SELECT used FROM codes WHERE code = ?", (code,))
    row = cursor.fetchone()
    conn.close()
    return row

def use_code(code):
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE codes SET used = 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()

def save_user_code(user_id, code):
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO user_codes (user_id, code) VALUES (?, ?)", (user_id, code))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка сохранения кода пользователя: {e}")
        conn.close()
        return False

def register_user(user_id, code):
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    
    try:
        # Проверяем код
        cursor.execute("SELECT used FROM codes WHERE code = ?", (code,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "❌ Код не найден"
        if row[0] == 1:
            conn.close()
            return False, "❌ Код уже использован"
        
        # Получаем следующий ID
        cursor.execute("SELECT MAX(anon_id) FROM users")
        row = cursor.fetchone()
        next_id = (row[0] or 0) + 1
        
        # Регистрируем пользователя
        cursor.execute('''
            INSERT INTO users (user_id, anon_id, nickname) 
            VALUES (?, ?, ?)
        ''', (user_id, next_id, f"User_{next_id}"))
        
        # Помечаем код как использованный
        cursor.execute("UPDATE codes SET used = 1 WHERE code = ?", (code,))
        
        # Сохраняем связь пользователя с кодом
        cursor.execute("INSERT INTO user_codes (user_id, code) VALUES (?, ?)", (user_id, code))
        
        conn.commit()
        conn.close()
        return True, f"✅ Регистрация успешна! Ваш ID: #{next_id}"
    except Exception as e:
        conn.close()
        return False, f"❌ Ошибка: {e}"

def get_user(user_id):
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    cursor.execute('SELECT anon_id, nickname, last_online FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_user_by_anon_id(anon_id):
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, nickname FROM users WHERE anon_id = ?', (anon_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def update_last_online(user_id):
    try:
        conn = sqlite3.connect('anon_chat.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET last_online = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка обновления времени: {e}")

def get_all_users():
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    cursor.execute('SELECT anon_id, nickname, last_online FROM users')
    rows = cursor.fetchall()
    conn.close()
    
    users = []
    now = datetime.now()
    
    for row in rows:
        try:
            last_online = datetime.strptime(row[2], '%Y-%m-%d %H:%M:%S')
        except:
            last_online = now
        is_online = (now - last_online) < timedelta(minutes=5)
        users.append({
            'anon_id': row[0],
            'nickname': row[1],
            'is_online': is_online
        })
    return users

def change_nickname(user_id, new_nick):
    try:
        conn = sqlite3.connect('anon_chat.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET nickname = ? WHERE user_id = ?', (new_nick, user_id))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def save_message(group_message_id, user_id, message_text, message_type='text', file_id=None):
    try:
        conn = sqlite3.connect('anon_chat.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO messages (group_message_id, user_id, message_text, message_type, file_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (group_message_id, user_id, message_text, message_type, file_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка сохранения сообщения: {e}")
        return False

def get_message_by_group_id(group_message_id):
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_id, message_text, message_type, file_id, sent_at, is_deleted 
        FROM messages WHERE group_message_id = ?
    ''', (group_message_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def delete_message(group_message_id):
    try:
        conn = sqlite3.connect('anon_chat.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE messages SET is_deleted = 1 WHERE group_message_id = ?
        ''', (group_message_id,))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def edit_message_text(group_message_id, new_text):
    try:
        conn = sqlite3.connect('anon_chat.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE messages SET message_text = ?, edited_at = CURRENT_TIMESTAMP 
            WHERE group_message_id = ?
        ''', (new_text, group_message_id))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_user_messages_last_day(user_id):
    conn = sqlite3.connect('anon_chat.db')
    cursor = conn.cursor()
    one_day_ago = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        SELECT group_message_id, message_text, sent_at, is_deleted 
        FROM messages 
        WHERE user_id = ? AND sent_at > ? AND is_deleted = 0
        ORDER BY sent_at DESC
    ''', (user_id, one_day_ago))
    rows = cursor.fetchall()
    conn.close()
    return rows

# =============== КЛАВИАТУРЫ ===============

def get_main_reply_keyboard():
    """Основная клавиатура с кнопками (всегда видна)"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="👤 Профиль")
    builder.button(text="👥 Онлайн")
    builder.button(text="✏️ Сменить ник")
    builder.button(text="📨 Мои сообщения")
    builder.button(text="📝 Отправить SMS")
    builder.button(text="💬 Личное сообщение")
    builder.button(text="❓ Помощь")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True, input_field_placeholder="Выберите действие...")

def get_cancel_reply_keyboard():
    """Клавиатура с кнопкой отмены"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True)

def get_back_reply_keyboard():
    """Клавиатура с кнопкой назад"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="◀️ Назад в меню")
    return builder.as_markup(resize_keyboard=True)

# =============== ОБРАБОТЧИКИ КОМАНД ===============

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if user:
        update_last_online(user_id)
        await message.answer(
            f"👋 С возвращением, {user[1]}!\n"
            f"🆔 Ваш ID: #{user[0]}\n\n"
            f"Выберите действие на клавиатуре ниже:",
            reply_markup=get_main_reply_keyboard()
        )
    else:
        await message.answer(
            "👋 Добро пожаловать в анонимный чат!\n"
            "📝 Для регистрации введите код, полученный у администратора.",
            reply_markup=ReplyKeyboardRemove()
        )

@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    """Показать главное меню"""
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if not user:
        await message.answer("❌ Сначала зарегистрируйтесь")
        return
    
    update_last_online(user_id)
    await message.answer(
        "📋 Главное меню\n\nВыберите действие на клавиатуре:",
        reply_markup=get_main_reply_keyboard()
    )

@dp.message(Command("sms"))
async def cmd_sms(message: Message):
    """Отправить SMS в общий чат"""
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if not user:
        await message.answer("❌ Сначала зарегистрируйтесь")
        return
    
    # Получаем текст сообщения
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ Используйте: /sms Текст сообщения\n"
            "Пример: /sms Всем привет!"
        )
        return
    
    sms_text = parts[1]
    
    # Отправляем в группу
    try:
        sent_msg = await bot.send_message(
            GROUP_ID,
            f"📱 {user[1]} [#{user[0]}]: {sms_text}"
        )
        save_message(sent_msg.message_id, user[0], sms_text, 'text')
        await message.reply("✅ SMS отправлена в общий чат!", reply_markup=get_main_reply_keyboard())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("addcode"))
async def cmd_addcode(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет прав")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        # Показываем список кодов
        codes = get_all_codes()
        if codes:
            text = "📋 Существующие коды:\n\n"
            for code, used in codes:
                status = "✅ Использован" if used else "🟢 Доступен"
                text += f"• {code} - {status}\n"
        else:
            text = "📭 Нет добавленных кодов"
        
        await message.answer(text + "\n\nЧтобы добавить код: /addcode КОД")
        return
    
    code = parts[1]
    if add_code(code):
        await message.answer(f"✅ Код {code} добавлен!")
    else:
        await message.answer("❌ Код уже существует")

# =============== ОБРАБОТЧИК ТЕКСТОВЫХ КНОПОК ===============

@dp.message()
async def handle_reply_buttons(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    # Если пользователь не зарегистрирован
    if not user:
        if message.text and not message.text.startswith('/'):
            success, msg = register_user(user_id, message.text.strip())
            await message.answer(msg)
            if success:
                # Показываем меню после регистрации
                await message.answer(
                    "📋 Главное меню\n\nВыберите действие на клавиатуре:",
                    reply_markup=get_main_reply_keyboard()
                )
        return
    
    # Обновляем время онлайн
    update_last_online(user_id)
    
    # Проверяем, не ждем ли мы ник
    if user_id in temp_data:
        if temp_data[user_id] == "waiting_for_nick":
            if message.text and message.text != "❌ Отмена" and len(message.text) <= 20:
                new_nick = message.text.strip()
                if change_nickname(user_id, new_nick):
                    del temp_data[user_id]
                    await message.answer(
                        f"✅ Ник изменён на {new_nick}!",
                        reply_markup=get_main_reply_keyboard()
                    )
                else:
                    await message.answer(
                        "❌ Ошибка при смене ника",
                        reply_markup=get_main_reply_keyboard()
                    )
            else:
                del temp_data[user_id]
                await message.answer(
                    "❌ Действие отменено",
                    reply_markup=get_main_reply_keyboard()
                )
            return
        
        elif temp_data[user_id].startswith("editing_"):
            if message.text and message.text != "❌ Отмена":
                group_msg_id = int(temp_data[user_id].split("_")[1])
                
                # Обновляем текст в БД
                edit_message_text(group_msg_id, message.text)
                
                # Отправляем уведомление об edit
                await bot.send_message(
                    GROUP_ID,
                    f"✏️ [{user[1]} #{user[0]}] отредактировал(а) сообщение"
                )
                
                del temp_data[user_id]
                await message.answer(
                    "✅ Сообщение отредактировано",
                    reply_markup=get_main_reply_keyboard()
                )
            else:
                del temp_data[user_id]
                await message.answer(
                    "❌ Редактирование отменено",
                    reply_markup=get_main_reply_keyboard()
                )
            return
        
        elif temp_data[user_id] == "waiting_for_private":
            if message.text and message.text != "❌ Отмена":
                # Ожидаем ввод в формате #ID текст
                if message.text.startswith('#'):
                    await handle_private_message(message, user)
                else:
                    await message.answer(
                        "❌ Неправильный формат. Используйте: #ID текст\nПример: #5 Привет",
                        reply_markup=get_cancel_reply_keyboard()
                    )
            else:
                del temp_data[user_id]
                await message.answer(
                    "❌ Действие отменено",
                    reply_markup=get_main_reply_keyboard()
                )
            return
        
        elif temp_data[user_id] == "waiting_for_sms":
            if message.text and message.text != "❌ Отмена":
                # Отправляем SMS
                try:
                    sent_msg = await bot.send_message(
                        GROUP_ID,
                        f"📱 {user[1]} [#{user[0]}]: {message.text}"
                    )
                    save_message(sent_msg.message_id, user[0], message.text, 'text')
                    await message.answer("✅ SMS отправлена в общий чат!", reply_markup=get_main_reply_keyboard())
                except Exception as e:
                    await message.answer(f"❌ Ошибка: {e}")
                
                del temp_data[user_id]
            else:
                del temp_data[user_id]
                await message.answer(
                    "❌ Отправка отменена",
                    reply_markup=get_main_reply_keyboard()
                )
            return
    
    # Обработка текстовых кнопок
    if message.text == "👤 Профиль":
        profile_text = (
            f"👤 Ваш профиль\n\n"
            f"🆔 Анонимный ID: #{user[0]}\n"
            f"📝 Ваш ник: {user[1]}\n"
            f"🟢 Статус: онлайн"
        )
        await message.answer(profile_text, reply_markup=get_main_reply_keyboard())
    
    elif message.text == "👥 Онлайн":
        users = get_all_users()
        online = [u for u in users if u['is_online']]
        offline = [u for u in users if not u['is_online']]
        
        text = "👥 Пользователи онлайн:\n\n"
        if online:
            for u in online:
                text += f"🟢 {u['nickname']} [#{u['anon_id']}]\n"
        else:
            text += "🟡 Нет пользователей онлайн\n"
        
        if offline:
            text += "\n⚪ Не в сети:\n"
            for u in offline[:5]:
                text += f"⚪ {u['nickname']} [#{u['anon_id']}]\n"
        
        await message.answer(text, reply_markup=get_main_reply_keyboard())
    
    elif message.text == "✏️ Сменить ник":
        temp_data[user_id] = "waiting_for_nick"
        await message.answer(
            "✏️ Введите новый ник (до 20 символов):\n"
            "Или нажмите '❌ Отмена'",
            reply_markup=get_cancel_reply_keyboard()
        )
    
    elif message.text == "📨 Мои сообщения":
        messages = get_user_messages_last_day(user_id)
        
        if not messages:
            await message.answer(
                "📭 У вас нет сообщений за последние 24 часа",
                reply_markup=get_main_reply_keyboard()
            )
            return
        
        text = "📨 Ваши сообщения за 24 часа:\n\n"
        for i, (group_msg_id, msg_text, sent_at, _) in enumerate(messages[:5], 1):
            time_str = datetime.strptime(sent_at, '%Y-%m-%d %H:%M:%S').strftime('%H:%M')
            short_text = msg_text[:20] + "..." if len(msg_text) > 20 else msg_text
            text += f"{i}. [{time_str}] {short_text}\n"
        
        text += "\nВведите номер сообщения для управления:"
        
        # Сохраняем список сообщений во временные данные
        temp_data[user_id] = {"action": "selecting_message", "messages": messages[:5]}
        await message.answer(text, reply_markup=get_cancel_reply_keyboard())
    
    elif message.text == "📝 Отправить SMS":
        temp_data[user_id] = "waiting_for_sms"
        await message.answer(
            "📝 Введите текст SMS для отправки в общий чат:\n"
            "Или нажмите '❌ Отмена'",
            reply_markup=get_cancel_reply_keyboard()
        )
    
    elif message.text == "💬 Личное сообщение":
        temp_data[user_id] = "waiting_for_private"
        await message.answer(
            "💬 Введите личное сообщение в формате:\n"
            "#ID текст\n\n"
            "Пример: #5 Привет, как дела?\n\n"
            "Или нажмите '❌ Отмена'",
            reply_markup=get_cancel_reply_keyboard()
        )
    
    elif message.text == "❓ Помощь":
        help_text = (
            "❓ Помощь\n\n"
            "📝 **Как общаться:**\n"
            "• Нажмите '📝 Отправить SMS' для отправки в общий чат\n"
            "• Или используйте команду: /sms текст\n\n"
            "💬 **Личные сообщения:**\n"
            "• Нажмите '💬 Личное сообщение'\n"
            "• Затем введите: #ID текст\n"
            "• Пример: #5 Привет\n\n"
            "✏️ **Управление сообщениями:**\n"
            "• Можно редактировать/удалять сообщения за 24ч\n"
            "• Нажмите '📨 Мои сообщения'\n\n"
            f"👤 **Ваш профиль:**\n"
            f"• Имя: {user[1]}\n"
            f"• ID: #{user[0]}\n\n"
            "📋 **Команды:**\n"
            "/menu - Открыть меню\n"
            "/sms текст - Отправить SMS\n"
            "/addcode КОД - Добавить код (только админ)"
        )
        await message.answer(help_text, reply_markup=get_main_reply_keyboard())
    
    elif message.text == "◀️ Назад в меню" or message.text == "❌ Отмена":
        if user_id in temp_data:
            del temp_data[user_id]
        await message.answer(
            "📋 Главное меню",
            reply_markup=get_main_reply_keyboard()
        )
    
    # Обработка выбора номера сообщения
    elif user_id in temp_data and isinstance(temp_data[user_id], dict) and temp_data[user_id].get("action") == "selecting_message":
        if message.text.isdigit():
            idx = int(message.text) - 1
            messages = temp_data[user_id].get("messages", [])
            
            if 0 <= idx < len(messages):
                group_msg_id = messages[idx][0]
                message_data = get_message_by_group_id(group_msg_id)
                
                if message_data:
                    text = f"📄 Сообщение:\n\n{message_data[2]}\n\nВыберите действие:"
                    
                    # Создаем инлайн клавиатуру для действий
                    builder = InlineKeyboardBuilder()
                    builder.button(text="✏️ Редактировать", callback_data=f"edit_{group_msg_id}")
                    builder.button(text="🗑️ Удалить", callback_data=f"delete_{group_msg_id}")
                    builder.button(text="◀️ Назад", callback_data="back_to_messages")
                    builder.adjust(2)
                    
                    await message.answer(text, reply_markup=builder.as_markup())
                    return
        
        # Если неправильный ввод
        await message.answer("❌ Неправильный номер. Попробуйте снова:", reply_markup=get_cancel_reply_keyboard())
    
    # Обработка обычных сообщений (не кнопки)
    elif message.text and not message.text.startswith('/'):
        # Проверяем, не личное ли это сообщение (начинается с #)
        if message.text.startswith('#'):
            await handle_private_message(message, user)
        else:
            # Показываем подсказку
            await message.answer(
                "📝 Используйте кнопки на клавиатуре для действий\n"
                "или команду /sms для отправки сообщения",
                reply_markup=get_main_reply_keyboard()
            )

# Функция для обработки личных сообщений
async def handle_private_message(message: Message, user):
    try:
        # Парсим сообщение вида "#123 Привет"
        parts = message.text.split(' ', 1)
        target = parts[0][1:]  # убираем #
        if len(parts) > 1 and target.isdigit():
            target_anon_id = int(target)
            private_text = parts[1]
            
            # Ищем получателя
            target_user = get_user_by_anon_id(target_anon_id)
            if target_user:
                target_user_id, target_nick = target_user
                
                # Отправляем личное сообщение
                await bot.send_message(
                    target_user_id,
                    f"💌 [Личное] от {user[1]} [#{user[0]}]:\n\n{private_text}"
                )
                await message.reply(f"✅ Сообщение отправлено #{target_anon_id}", reply_markup=get_main_reply_keyboard())
                
                # Очищаем состояние если было
                if message.from_user.id in temp_data and temp_data[message.from_user.id] == "waiting_for_private":
                    del temp_data[message.from_user.id]
            else:
                await message.reply(f"❌ Пользователь #{target_anon_id} не найден", reply_markup=get_main_reply_keyboard())
        else:
            await message.reply("❌ Неправильный формат. Используйте: #ID текст", reply_markup=get_main_reply_keyboard())
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}", reply_markup=get_main_reply_keyboard())

# =============== ОБРАБОТЧИКИ ИНЛАЙН КНОПОК ===============

@dp.callback_query()
async def handle_callbacks(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if not user:
        await callback.answer("❌ Сначала зарегистрируйтесь", show_alert=True)
        return
    
    await callback.answer()
    
    if callback.data.startswith("delete_"):
        group_msg_id = int(callback.data.split("_")[1])
        
        # Проверяем, что сообщение принадлежит пользователю
        message_data = get_message_by_group_id(group_msg_id)
        if not message_data or message_data[1] != user_id:
            await callback.message.edit_text("❌ Нельзя удалить это сообщение")
            return
        
        # Удаляем сообщение
        delete_message(group_msg_id)
        
        # Отправляем уведомление об удалении в группу
        await bot.send_message(
            GROUP_ID,
            f"🗑️ [{user[1]} #{user[0]}] удалил(а) сообщение"
        )
        
        await callback.message.edit_text("✅ Сообщение удалено")
        await callback.message.answer("📋 Главное меню", reply_markup=get_main_reply_keyboard())
    
    elif callback.data.startswith("edit_"):
        group_msg_id = int(callback.data.split("_")[1])
        
        # Проверяем, что сообщение принадлежит пользователю
        message_data = get_message_by_group_id(group_msg_id)
        if not message_data or message_data[1] != user_id:
            await callback.message.edit_text("❌ Нельзя редактировать это сообщение")
            return
        
        temp_data[user_id] = f"editing_{group_msg_id}"
        await callback.message.edit_text("✏️ Введите новый текст сообщения:")
        await callback.message.answer("Или нажмите '❌ Отмена'", reply_markup=get_cancel_reply_keyboard())
    
    elif callback.data == "back_to_messages":
        if user_id in temp_data:
            del temp_data[user_id]
        await callback.message.edit_text("📋 Возврат в меню")
        await callback.message.answer("📋 Главное меню", reply_markup=get_main_reply_keyboard())

# =============== ЗАПУСК БОТА ===============

async def main():
    print("=" * 40)
    print("🚀 ЗАПУСК АНОНИМНОГО ЧАТ-БОТА")
    print("=" * 40)
    
    if BOT_TOKEN == "8623415156:AAEknOvnE8KtumXn1brqc8hWqa5xfaPBkyI":
        print("✅ Токен загружен")
    else:
        print("❌ Проблема с токеном")
        return
    
    if GROUP_ID == -1003856989196:
        print(f"✅ ID группы: {GROUP_ID}")
    else:
        print("❌ Проблема с ID группы")
        return
    
    if ADMIN_ID == 5979001063:
        print(f"✅ ID администратора: {ADMIN_ID}")
    else:
        print("❌ Проблема с ID администратора")
        return
    
    # Удаляем старую базу данных если есть проблемы
    import os
    if os.path.exists('anon_chat.db'):
        print("🔄 Обновление структуры базы данных...")
        os.remove('anon_chat.db')
        print("✅ Старая база данных удалена")
    
    init_db()
    print("=" * 40)
    print("✅ Бот успешно запущен!")
    print("📋 Функции:")
    print("  • 👤 Профиль и онлайн")
    print("  • ✏️ Смена ника")
    print("  • 💬 Личные сообщения (#ID)")
    print("  • 📱 Отправка SMS (/sms или кнопка)")
    print("  • 📨 Редактирование/удаление (24ч)")
    print("  • 🔑 Коды для приглашенных")
    print("  • ⌨️ Удобная клавиатура с кнопками")
    print("=" * 40)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())