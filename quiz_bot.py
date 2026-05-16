#!/usr/bin/env python3
"""
🎮 QUIZ BOT - To'liq kod
Ishlatish: pip install aiogram aiohttp aiosqlite
"""

import asyncio
import aiohttp
import aiosqlite
import logging
import random
import string
import datetime
import html
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== CONFIG ====================
BOT_TOKEN = "8982395697:AAFkN_nx0JPQChsQv-5uEgkH2bjsWbJi-Kg"
ADMIN_ID = 7397653738
DB_PATH = "quiz.db"
FREE_DAILY_LIMIT = 10
TRIVIA_API = "https://opentdb.com/api.php"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== STATES ====================
class QuizState(StatesGroup):
    choosing_category = State()
    choosing_difficulty = State()
    answering = State()

class AdminState(StatesGroup):
    broadcasting = State()
    broadcast_target = State()
    adding_channel = State()
    adding_channel_link = State()
    setting_card = State()

class PaymentState(StatesGroup):
    choosing_plan = State()
    uploading_screenshot = State()

class BookState(StatesGroup):
    searching = State()

# ==================== DATABASE ====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                full_name TEXT DEFAULT '',
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT DEFAULT '',
                referral_code TEXT UNIQUE,
                referred_by INTEGER DEFAULT 0,
                referral_count INTEGER DEFAULT 0,
                extra_questions INTEGER DEFAULT 0,
                total_score INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0,
                joined_at TEXT DEFAULT '',
                is_banned INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id INTEGER,
                date TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                plan TEXT,
                status TEXT DEFAULT "pending",
                screenshot_file_id TEXT,
                created_at TEXT,
                confirmed_at TEXT DEFAULT ""
            );
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT,
                channel_name TEXT,
                channel_link TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                category TEXT,
                difficulty TEXT,
                score INTEGER,
                played_at TEXT
            );
            CREATE TABLE IF NOT EXISTS book_favorites (
                user_id INTEGER,
                book_id INTEGER,
                title TEXT,
                PRIMARY KEY (user_id, book_id)
            );
            INSERT OR IGNORE INTO settings VALUES ("payment_card", "9860100126027844");
            INSERT OR IGNORE INTO settings VALUES ("payment_name", "I. Z");
            INSERT OR IGNORE INTO settings VALUES ("price_1m", "10000");
            INSERT OR IGNORE INTO settings VALUES ("price_3m", "25000");
            INSERT OR IGNORE INTO settings VALUES ("price_6m", "40000");
        ''')
        await db.commit()

async def db_get(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cur:
            return await cur.fetchone()

async def db_all(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cur:
            return await cur.fetchall()

async def db_run(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(query, params)
        await db.commit()

async def db_insert(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(query, params)
        await db.commit()
        return cur.lastrowid

async def get_setting(key):
    row = await db_get("SELECT value FROM settings WHERE key=?", (key,))
    return row[0] if row else None

async def get_user(user_id):
    return await db_get("SELECT * FROM users WHERE user_id=?", (user_id,))

async def add_user(user_id, username, full_name, ref_code, referred_by=0):
    now = datetime.datetime.now().isoformat()
    await db_run(
        "INSERT OR IGNORE INTO users (user_id,username,full_name,referral_code,referred_by,joined_at) VALUES (?,?,?,?,?,?)",
        (user_id, username, full_name, ref_code, referred_by, now)
    )
    if referred_by:
        await db_run("UPDATE users SET referral_count=referral_count+1, extra_questions=extra_questions+1 WHERE user_id=?", (referred_by,))

async def check_premium(user_id):
    user = await get_user(user_id)
    if not user or not user[3]:
        return False
    if user[4]:
        try:
            until = datetime.datetime.fromisoformat(user[4])
            if datetime.datetime.now() > until:
                await db_run("UPDATE users SET is_premium=0 WHERE user_id=?", (user_id,))
                return False
        except:
            pass
    return bool(user[3])

async def get_daily_usage(user_id):
    today = datetime.date.today().isoformat()
    row = await db_get("SELECT count FROM daily_usage WHERE user_id=? AND date=?", (user_id, today))
    return row[0] if row else 0

async def inc_daily(user_id):
    today = datetime.date.today().isoformat()
    await db_run(
        "INSERT INTO daily_usage (user_id,date,count) VALUES (?,?,1) ON CONFLICT(user_id,date) DO UPDATE SET count=count+1",
        (user_id, today)
    )

async def get_channels():
    return await db_all("SELECT * FROM channels")

async def check_subscriptions(bot: Bot, user_id: int):
    channels = await get_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch[1], user_id)
            if member.status in ['left', 'banned', 'kicked']:
                return False
        except:
            pass
    return True

def gen_ref_code(user_id):
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f"r{user_id}{suffix}"

# ==================== KEYBOARDS ====================
def main_kb(premium=False):
    rows = [
        [KeyboardButton(text="🎯 O'yin boshlash"), KeyboardButton(text="🏆 Reyting")],
        [KeyboardButton(text="👤 Profilim"), KeyboardButton(text="👥 Referral")],
        [KeyboardButton(text="💎 Premium")]
    ]
    if premium:
        rows.insert(2, [KeyboardButton(text="📚 Kitoblar"), KeyboardButton(text="📊 Statistikam")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="💳 To'lovlar")],
        [KeyboardButton(text="📢 Kanallar"), KeyboardButton(text="📣 Xabar yuborish")],
        [KeyboardButton(text="⚙️ Sozlamalar"), KeyboardButton(text="🔙 Asosiy menyu")]
    ], resize_keyboard=True)

def category_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Geografiya", callback_data="cat:geography"),
         InlineKeyboardButton(text="🔬 Fan", callback_data="cat:science")],
        [InlineKeyboardButton(text="📖 Tarix", callback_data="cat:history"),
         InlineKeyboardButton(text="🏅 Sport", callback_data="cat:sports")],
        [InlineKeyboardButton(text="🎬 Kino", callback_data="cat:entertainment"),
         InlineKeyboardButton(text="💻 Texnologiya", callback_data="cat:computers")],
        [InlineKeyboardButton(text="🧠 Aralash", callback_data="cat:general")]
    ])

def difficulty_kb(cat):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Oson (+10 ball)", callback_data=f"diff:easy:{cat}")],
        [InlineKeyboardButton(text="🟡 O'rta (+20 ball)", callback_data=f"diff:medium:{cat}")],
        [InlineKeyboardButton(text="🔴 Qiyin (+30 ball)", callback_data=f"diff:hard:{cat}")],
    ])

def answer_kb(options, qid):
    labels = ["🅰️", "🅱️", "🆑", "🇩"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{labels[i]} {opt[:35]}", callback_data=f"ans:{qid}:{i}")]
        for i, opt in enumerate(options)
    ])

def sub_kb(channels):
    btns = [[InlineKeyboardButton(text=f"📢 {ch[2]}", url=ch[3])] for ch in channels]
    btns.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="checksub")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def premium_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥉 1 oy — 10,000 so'm", callback_data="buy:1m")],
        [InlineKeyboardButton(text="🥈 3 oy — 25,000 so'm", callback_data="buy:3m")],
        [InlineKeyboardButton(text="🥇 6 oy — 40,000 so'm", callback_data="buy:6m")],
    ])

def payment_admin_kb(pid, uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"payadm:ok:{pid}:{uid}"),
         InlineKeyboardButton(text="❌ Rad etish", callback_data=f"payadm:no:{pid}:{uid}")]
    ])

def broadcast_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Hammaga", callback_data="bcast:all")],
        [InlineKeyboardButton(text="💎 Premium a'zolarga", callback_data="bcast:premium")],
        [InlineKeyboardButton(text="🆓 Oddiy a'zolarga", callback_data="bcast:free")],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="bcast:cancel")]
    ])

def book_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Kitob qidirish", callback_data="book:search")],
        [InlineKeyboardButton(text="📖 Mashhur kitoblar", callback_data="book:popular")],
        [InlineKeyboardButton(text="⭐ Sevimlilarim", callback_data="book:favs")],
    ])

# ==================== TRIVIA API ====================
CATEGORY_IDS = {
    "geography": 22, "science": 17, "history": 23,
    "sports": 21, "entertainment": 11, "computers": 18, "general": 9
}
CATEGORY_NAMES = {
    "geography": "🌍 Geografiya", "science": "🔬 Fan", "history": "📖 Tarix",
    "sports": "🏅 Sport", "entertainment": "🎬 Kino", "computers": "💻 Texnologiya",
    "general": "🧠 Aralash"
}
DIFF_SCORES = {"easy": 10, "medium": 20, "hard": 30}
DIFF_BONUS = {"easy": 5, "medium": 10, "hard": 15}

async def fetch_question(category, difficulty):
    cat_id = CATEGORY_IDS.get(category, 9)
    url = f"{TRIVIA_API}?amount=1&category={cat_id}&difficulty={difficulty}&type=multiple"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                if data.get("response_code") == 0 and data.get("results"):
                    q = data["results"][0]
                    question = html.unescape(q["question"])
                    correct = html.unescape(q["correct_answer"])
                    incorrects = [html.unescape(x) for x in q["incorrect_answers"]]
                    options = incorrects + [correct]
                    random.shuffle(options)
                    correct_idx = options.index(correct)
                    return question, options, correct_idx
    except Exception as e:
        logger.error(f"API xato: {e}")
    return None, None, None

# ==================== ROUTER ====================
router = Router()

# ---------- START ----------
@router.message(CommandStart())
async def cmd_start(msg: Message, bot: Bot, state: FSMContext):
    await state.clear()
    await init_db()
    uid = msg.from_user.id
    uname = msg.from_user.username or ""
    fname = msg.from_user.full_name or "Foydalanuvchi"

    # Referral
    ref_by = 0
    parts = msg.text.split()
    if len(parts) > 1:
        code = parts[1]
        row = await db_get("SELECT user_id FROM users WHERE referral_code=?", (code,))
        if row and row[0] != uid:
            ref_by = row[0]

    user = await get_user(uid)
    if not user:
        code = gen_ref_code(uid)
        await add_user(uid, uname, fname, code, ref_by)
        if ref_by:
            try:
                await bot.send_message(ref_by,
                    "🎉 Referral bonus! Do'stingiz botga qo'shildi.\n+1 qo'shimcha savol huquqi berildi! ✅")
            except:
                pass

    user = await get_user(uid)
    if user and user[12]:
        return await msg.answer("❌ Siz botdan bloklangansiz.")

    # Obuna tekshirish
    if not await check_subscriptions(bot, uid):
        channels = await get_channels()
        return await msg.answer(
            "📢 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
            reply_markup=sub_kb(channels)
        )

    if uid == ADMIN_ID:
        return await msg.answer("👋 Admin paneliga xush kelibsiz!", reply_markup=admin_kb())

    prem = await check_premium(uid)
    badge = "💎 Premium" if prem else "🆓 Bepul"
    await msg.answer(
        f"👋 Salom, {fname}!\n\n🎮 Quiz Botga xush kelibsiz!\n📊 Status: {badge}\n\nQuyidagi menyudan tanlang 👇",
        reply_markup=main_kb(prem)
    )

@router.callback_query(F.data == "checksub")
async def checksub(cb: CallbackQuery, bot: Bot):
    uid = cb.from_user.id
    if await check_subscriptions(bot, uid):
        prem = await check_premium(uid)
        await cb.message.delete()
        await cb.message.answer("✅ Obuna tasdiqlandi! Botga xush kelibsiz! 🎉", reply_markup=main_kb(prem))
    else:
        await cb.answer("❌ Hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)

# ---------- PROFILE ----------
@router.message(F.text == "👤 Profilim")
async def profile(msg: Message):
    uid = msg.from_user.id
    user = await get_user(uid)
    if not user:
        return await msg.answer("Avval /start bosing!")
    prem = await check_premium(uid)
    usage = await get_daily_usage(uid)
    limit = FREE_DAILY_LIMIT if not prem else "♾️ Cheksiz"
    prem_until = ""
    if prem and user[4]:
        try:
            dt = datetime.datetime.fromisoformat(user[4])
            prem_until = f"\n⏳ Premium tugashi: {dt.strftime('%d.%m.%Y')}"
        except:
            pass

    ref_code = user[5] or ""
    bot_username = (await msg.bot.get_me()).username

    await msg.answer(
        f"👤 <b>Profil</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Ism: {user[2]}\n"
        f"📊 Status: {'💎 Premium' if prem else '🆓 Bepul'}{prem_until}\n\n"
        f"🎯 Jami ball: <b>{user[9]}</b>\n"
        f"🎮 O'yinlar soni: <b>{user[10]}</b>\n"
        f"👥 Referrallar: <b>{user[7]}</b>\n"
        f"➕ Bonus savollar: <b>{user[8]}</b>\n\n"
        f"📅 Bugungi: {usage}/{limit}\n\n"
        f"🔗 Referral havola:\n<code>https://t.me/{bot_username}?start={ref_code}</code>",
        parse_mode="HTML"
    )

# ---------- REFERRAL ----------
@router.message(F.text == "👥 Referral")
async def referral(msg: Message):
    uid = msg.from_user.id
    user = await get_user(uid)
    if not user:
        return await msg.answer("Avval /start bosing!")
    bot_username = (await msg.bot.get_me()).username
    ref_code = user[5] or ""
    await msg.answer(
        f"👥 <b>Referral tizimi</b>\n\n"
        f"Do'stingizni taklif qiling va har biri uchun <b>+1 qo'shimcha savol</b> oling!\n\n"
        f"📊 Sizning referrallaringiz: <b>{user[7]}</b>\n"
        f"🎁 Bonus savollar: <b>{user[8]}</b>\n\n"
        f"🔗 Sizning havolangiz:\n<code>https://t.me/{bot_username}?start={ref_code}</code>\n\n"
        f"💡 Havolani do'stlaringizga yuboring!",
        parse_mode="HTML"
    )

# ---------- QUIZ ----------
@router.message(F.text == "🎯 O'yin boshlash")
async def start_quiz(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    user = await get_user(uid)
    if not user:
        return await msg.answer("Avval /start bosing!")

    prem = await check_premium(uid)
    if not prem:
        usage = await get_daily_usage(uid)
        extra = user[8] if user else 0
        total_allowed = FREE_DAILY_LIMIT + extra
        if usage >= total_allowed:
            return await msg.answer(
                f"⛔ Bugunlik {FREE_DAILY_LIMIT} ta bepul savolingiz tugadi!\n\n"
                f"💎 <b>Premium</b> oling va cheksiz o'ynang!\n"
                f"Yoki do'stlarni taklif qiling — har biri uchun +1 savol!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💎 Premium olish", callback_data="show_premium")]
                ]),
                parse_mode="HTML"
            )

    await state.set_state(QuizState.choosing_category)
    await msg.answer("🎯 <b>Mavzuni tanlang:</b>", reply_markup=category_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("cat:"))
async def choose_category(cb: CallbackQuery, state: FSMContext):
    cat = cb.data.split(":")[1]
    await state.update_data(category=cat)
    await state.set_state(QuizState.choosing_difficulty)
    await cb.message.edit_text(
        f"🎯 Mavzu: <b>{CATEGORY_NAMES.get(cat, cat)}</b>\n\n🎚 Qiyinlikni tanlang:",
        reply_markup=difficulty_kb(cat),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("diff:"))
async def choose_difficulty(cb: CallbackQuery, state: FSMContext, bot: Bot):
    parts = cb.data.split(":")
    diff = parts[1]
    cat = parts[2]
    uid = cb.from_user.id

    await cb.message.edit_text("⏳ Savol yuklanmoqda...")

    question, options, correct_idx = await fetch_question(cat, diff)
    if not question:
        return await cb.message.edit_text("❌ Savol olishda xato yuz berdi. Qaytadan urinib ko'ring!")

    qid = random.randint(10000, 99999)
    await state.set_state(QuizState.answering)
    await state.update_data(
        question=question, options=options,
        correct_idx=correct_idx, qid=qid,
        category=cat, difficulty=diff,
        start_time=datetime.datetime.now().isoformat()
    )

    diff_label = {"easy": "🟢 Oson", "medium": "🟡 O'rta", "hard": "🔴 Qiyin"}.get(diff, diff)
    await cb.message.edit_text(
        f"❓ <b>{question}</b>\n\n"
        f"📚 {CATEGORY_NAMES.get(cat, cat)} | {diff_label}\n"
        f"💰 To'g'ri javob: +{DIFF_SCORES[diff]} ball (+{DIFF_BONUS[diff]} tez javob uchun)",
        reply_markup=answer_kb(options, qid),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("ans:"))
async def answer_question(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    qid = int(parts[1])
    chosen = int(parts[2])
    uid = cb.from_user.id

    data = await state.get_data()
    if data.get("qid") != qid:
        return await cb.answer("Bu savol eskirgan!", show_alert=True)

    correct_idx = data["correct_idx"]
    options = data["options"]
    diff = data["difficulty"]
    cat = data["category"]
    start_time = datetime.datetime.fromisoformat(data["start_time"])

    elapsed = (datetime.datetime.now() - start_time).seconds
    base_score = DIFF_SCORES[diff]
    bonus = DIFF_BONUS[diff] if elapsed <= 10 else 0

    prem = await check_premium(uid)
    await inc_daily(uid)

    if chosen == correct_idx:
        total = base_score + bonus
        await db_run("UPDATE users SET total_score=total_score+?, games_played=games_played+1 WHERE user_id=?", (total, uid))
        text = (
            f"✅ <b>To'g'ri javob!</b>\n\n"
            f"Javob: <b>{options[correct_idx]}</b>\n\n"
            f"💰 Ball: +{base_score}"
            + (f" (+{bonus} tez javob bonusi)" if bonus else "") +
            f"\n⏱ Vaqt: {elapsed} soniya"
        )
    else:
        await db_run("UPDATE users SET games_played=games_played+1 WHERE user_id=?", (uid,))
        text = (
            f"❌ <b>Noto'g'ri javob!</b>\n\n"
            f"Siz: <b>{options[chosen]}</b>\n"
            f"To'g'ri: <b>{options[correct_idx]}</b>\n\n"
            f"💡 Keyingi savolda omad!"
        )

    now = datetime.datetime.now().isoformat()
    await db_run("INSERT INTO game_history (user_id,category,difficulty,score,played_at) VALUES (?,?,?,?,?)",
                 (uid, cat, diff, base_score + bonus if chosen == correct_idx else 0, now))

    usage = await get_daily_usage(uid)
    user = await get_user(uid)
    extra = user[8] if user else 0
    total_allowed = FREE_DAILY_LIMIT + extra if not prem else 9999

    next_btn = [[InlineKeyboardButton(text="▶️ Keyingi savol", callback_data=f"next:{cat}:{diff}")]]
    if not prem and usage >= total_allowed:
        text += f"\n\n⚠️ Bugunlik limitingiz tugadi!"
        next_btn = [[InlineKeyboardButton(text="💎 Premium olish", callback_data="show_premium")]]

    await state.set_state(QuizState.choosing_category)
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=next_btn), parse_mode="HTML")

@router.callback_query(F.data.startswith("next:"))
async def next_question(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    cat = parts[1]
    diff = parts[2]
    uid = cb.from_user.id

    prem = await check_premium(uid)
    if not prem:
        usage = await get_daily_usage(uid)
        user = await get_user(uid)
        extra = user[8] if user else 0
        if usage >= FREE_DAILY_LIMIT + extra:
            return await cb.answer("Limit tugadi! Premium oling.", show_alert=True)

    await cb.message.edit_text("⏳ Savol yuklanmoqda...")
    question, options, correct_idx = await fetch_question(cat, diff)
    if not question:
        return await cb.message.edit_text("❌ Savol olishda xato. Qaytadan urinib ko'ring!")

    qid = random.randint(10000, 99999)
    await state.set_state(QuizState.answering)
    await state.update_data(
        question=question, options=options,
        correct_idx=correct_idx, qid=qid,
        category=cat, difficulty=diff,
        start_time=datetime.datetime.now().isoformat()
    )

    diff_label = {"easy": "🟢 Oson", "medium": "🟡 O'rta", "hard": "🔴 Qiyin"}.get(diff, diff)
    await cb.message.edit_text(
        f"❓ <b>{question}</b>\n\n"
        f"📚 {CATEGORY_NAMES.get(cat, cat)} | {diff_label}",
        reply_markup=answer_kb(options, qid),
        parse_mode="HTML"
    )

# ---------- RATING ----------
@router.message(F.text == "🏆 Reyting")
async def show_rating(msg: Message):
    rows = await db_all("SELECT user_id, full_name, total_score, is_premium FROM users ORDER BY total_score DESC LIMIT 10")
    if not rows:
        return await msg.answer("Hali reyting yo'q!")

    text = "🏆 <b>Top 10 O'yinchilar</b>\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["🎖"] * 7
    for i, (uid, name, score, prem) in enumerate(rows):
        badge = "💎" if prem else ""
        text += f"{medals[i]} {name} {badge} — <b>{score} ball</b>\n"

    user_row = await db_get("SELECT total_score FROM users WHERE user_id=?", (msg.from_user.id,))
    if user_row:
        rank_row = await db_get("SELECT COUNT(*)+1 FROM users WHERE total_score > ?", (user_row[0],))
        rank = rank_row[0] if rank_row else "?"
        text += f"\n📊 Sizning o'rningiz: <b>{rank}</b> | Ball: <b>{user_row[0]}</b>"

    await msg.answer(text, parse_mode="HTML")

# ---------- PREMIUM ----------
@router.message(F.text == "💎 Premium")
@router.callback_query(F.data == "show_premium")
async def show_premium(event):
    msg = event if isinstance(event, Message) else event.message
    prem = await check_premium(event.from_user.id)
    if prem:
        user = await get_user(event.from_user.id)
        until = ""
        if user and user[4]:
            try:
                dt = datetime.datetime.fromisoformat(user[4])
                until = dt.strftime('%d.%m.%Y')
            except:
                pass
        text = (
            f"💎 <b>Siz Premium a'zosiz!</b>\n\n"
            f"⏳ Muddati: {until}\n\n"
            f"✅ Cheksiz savollar\n"
            f"✅ VIP reyting\n"
            f"✅ 2x ball bonus\n"
            f"✅ Kitoblar bo'limi\n"
            f"✅ Batafsil statistika\n"
            f"✅ Reklama yo'q"
        )
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(text, parse_mode="HTML")
        else:
            await msg.answer(text, parse_mode="HTML")
    else:
        text = (
            f"💎 <b>Premium imkoniyatlar:</b>\n\n"
            f"✅ Cheksiz kunlik savollar\n"
            f"✅ VIP reyting\n"
            f"✅ 2x ball bonus\n"
            f"✅ 📚 Kitoblar bo'limi\n"
            f"✅ Batafsil statistika\n"
            f"✅ Reklama yo'q\n\n"
            f"💰 <b>Narxlar:</b>"
        )
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(text, reply_markup=premium_kb(), parse_mode="HTML")
        else:
            await msg.answer(text, reply_markup=premium_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("buy:"))
async def buy_premium(cb: CallbackQuery, state: FSMContext):
    plan = cb.data.split(":")[1]
    prices = {"1m": ("10,000", "1_month", 1), "3m": ("25,000", "3_month", 3), "6m": ("40,000", "6_month", 6)}
    price_str, plan_key, months = prices[plan]

    card = await get_setting("payment_card") or "9860100126027844"
    card_name = await get_setting("payment_name") or "I. Z"

    await state.update_data(plan=plan_key, amount=price_str)
    await state.set_state(PaymentState.uploading_screenshot)

    await cb.message.edit_text(
        f"💳 <b>To'lov ma'lumotlari</b>\n\n"
        f"📋 Karta: <code>{card}</code>\n"
        f"👤 Egasi: <b>{card_name}</b>\n"
        f"💰 Summa: <b>{price_str} so'm</b>\n"
        f"📅 Muddat: <b>{months} oy</b>\n\n"
        f"1️⃣ Yuqoridagi kartaga pul o'tkazing\n"
        f"2️⃣ Chek/screenshot oling\n"
        f"3️⃣ Shu yerga yuboring\n\n"
        f"⚡ Admin 24 soat ichida tasdiqlaydi",
        parse_mode="HTML"
    )

@router.message(PaymentState.uploading_screenshot, F.photo)
async def receive_screenshot(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    plan = data.get("plan", "")
    amount = data.get("amount", "")
    uid = msg.from_user.id
    fname = msg.from_user.full_name or ""
    file_id = msg.photo[-1].file_id

    pid = await db_insert(
        "INSERT INTO payments (user_id,amount,plan,screenshot_file_id,created_at) VALUES (?,?,?,?,?)",
        (uid, amount, plan, file_id, datetime.datetime.now().isoformat())
    )

    await state.clear()
    await msg.answer(
        f"✅ <b>Chekingiz qabul qilindi!</b>\n\n"
        f"🆔 To'lov ID: #{pid}\n"
        f"⏳ Admin tez orada tasdiqlaydi.\n\n"
        f"Savollar uchun /start bosing.",
        parse_mode="HTML"
    )

    # Admin ga xabar
    plan_labels = {"1_month": "1 oy", "3_month": "3 oy", "6_month": "6 oy"}
    try:
        await bot.send_photo(
            ADMIN_ID, file_id,
            caption=f"💳 <b>Yangi to'lov #{pid}</b>\n\n"
                    f"👤 {fname} (<code>{uid}</code>)\n"
                    f"💰 {amount} so'm\n"
                    f"📅 {plan_labels.get(plan, plan)}",
            reply_markup=payment_admin_kb(pid, uid),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Admin ga xabar yuborishda xato: {e}")

@router.callback_query(F.data.startswith("payadm:"))
async def payment_admin_action(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != ADMIN_ID:
        return await cb.answer("❌ Ruxsat yo'q!")
    parts = cb.data.split(":")
    action = parts[1]
    pid = int(parts[2])
    uid = int(parts[3])

    if action == "ok":
        row = await db_get("SELECT plan FROM payments WHERE id=?", (pid,))
        if not row:
            return await cb.answer("To'lov topilmadi!")
        plan = row[0]
        months = 1 if plan == "1_month" else (3 if plan == "3_month" else 6)
        until = datetime.datetime.now() + datetime.timedelta(days=30*months)
        await db_run("UPDATE users SET is_premium=1, premium_until=? WHERE user_id=?", (until.isoformat(), uid))
        await db_run("UPDATE payments SET status='confirmed' WHERE id=?", (pid,))
        await cb.message.edit_caption(
            cb.message.caption + f"\n\n✅ <b>TASDIQLANDI</b> — {months} oy",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(uid,
                f"🎉 <b>Premium faollashtirildi!</b>\n\n"
                f"✅ {months} oylik premium sizga berildi!\n"
                f"Muddati: {until.strftime('%d.%m.%Y')}\n\n"
                f"Botdan to'liq foydalaning! 💎",
                parse_mode="HTML"
            )
        except:
            pass
    else:
        await db_run("UPDATE payments SET status='rejected' WHERE id=?", (pid,))
        await cb.message.edit_caption(cb.message.caption + "\n\n❌ <b>RAD ETILDI</b>", parse_mode="HTML")
        try:
            await bot.send_message(uid,
                "❌ Afsuski, to'lovingiz tasdiqlanmadi.\n"
                "Admin bilan bog'laning yoki qayta urinib ko'ring.")
        except:
            pass

# ---------- STATISTICS (PREMIUM) ----------
@router.message(F.text == "📊 Statistikam")
async def my_stats(msg: Message):
    uid = msg.from_user.id
    if not await check_premium(uid):
        return await msg.answer("💎 Bu funksiya faqat Premium a'zolar uchun!")

    user = await get_user(uid)
    history = await db_all(
        "SELECT category, difficulty, score, played_at FROM game_history WHERE user_id=? ORDER BY played_at DESC LIMIT 10",
        (uid,)
    )

    total_games = user[10] if user else 0
    total_score = user[9] if user else 0
    avg_score = total_score // total_games if total_games > 0 else 0

    text = f"📊 <b>Batafsil Statistika</b>\n\n"
    text += f"🎮 Jami o'yin: <b>{total_games}</b>\n"
    text += f"💯 Jami ball: <b>{total_score}</b>\n"
    text += f"📈 O'rtacha ball: <b>{avg_score}</b>\n\n"

    if history:
        text += "🕐 <b>So'nggi o'yinlar:</b>\n"
        for cat, diff, score, played_at in history[:5]:
            cat_name = CATEGORY_NAMES.get(cat, cat)
            diff_label = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(diff, "")
            text += f"{diff_label} {cat_name} — {score} ball\n"

    await msg.answer(text, parse_mode="HTML")

# ---------- BOOKS (PREMIUM) ----------
@router.message(F.text == "📚 Kitoblar")
async def books_menu(msg: Message):
    if not await check_premium(msg.from_user.id):
        return await msg.answer(
            "📚 Kitoblar bo'limi faqat <b>Premium</b> a'zolar uchun!\n\n"
            "💎 Premium oling va minglab kitoblarga kiring.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Premium olish", callback_data="show_premium")]
            ]),
            parse_mode="HTML"
        )
    await msg.answer(
        "📚 <b>Kitoblar bo'limi</b>\n\n"
        "Project Gutenberg va Open Library dan minglab bepul kitoblar!\n\n"
        "Quyidagi tugmalardan birini tanlang:",
        reply_markup=book_kb(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "book:search")
async def book_search_start(cb: CallbackQuery, state: FSMContext):
    if not await check_premium(cb.from_user.id):
        return await cb.answer("Premium kerak!", show_alert=True)
    await state.set_state(BookState.searching)
    await cb.message.edit_text("🔍 Kitob nomini yozing (ingliz yoki o'zbek tilida):")

@router.message(BookState.searching)
async def book_search(msg: Message, state: FSMContext):
    await state.clear()
    query = msg.text.strip()
    await msg.answer("🔍 Qidirilmoqda...")

    try:
        url = f"https://gutendex.com/books/?search={query.replace(' ', '%20')}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                books = data.get("results", [])[:5]

        if not books:
            return await msg.answer(
                f"❌ '{query}' bo'yicha kitob topilmadi.\n\nBoshqa nom bilan qidiring.",
                reply_markup=book_kb()
            )

        text = f"📚 <b>'{query}' bo'yicha natijalar:</b>\n\n"
        btns = []
        for b in books:
            title = b.get("title", "")[:50]
            authors = ", ".join(a["name"] for a in b.get("authors", []))[:40]
            bid = b.get("id")
            langs = ", ".join(b.get("languages", []))
            text += f"📖 <b>{title}</b>\n👤 {authors} | 🌐 {langs}\n\n"
            formats = b.get("formats", {})
            download_url = formats.get("application/epub+zip") or formats.get("text/html") or formats.get("text/plain")
            if download_url:
                btns.append([InlineKeyboardButton(text=f"⬇️ {title[:30]}", url=download_url)])

        btns.append([InlineKeyboardButton(text="🔍 Yana qidirish", callback_data="book:search")])
        await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")

    except Exception as e:
        await msg.answer("❌ Qidiruvda xato yuz berdi. Qaytadan urinib ko'ring.")

@router.callback_query(F.data == "book:popular")
async def book_popular(cb: CallbackQuery):
    if not await check_premium(cb.from_user.id):
        return await cb.answer("Premium kerak!", show_alert=True)

    await cb.message.edit_text("⏳ Mashhur kitoblar yuklanmoqda...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://gutendex.com/books/?sort=popular", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                books = data.get("results", [])[:8]

        text = "📚 <b>Mashhur kitoblar:</b>\n\n"
        btns = []
        for b in books:
            title = b.get("title", "")[:50]
            authors = ", ".join(a["name"] for a in b.get("authors", []))[:35]
            text += f"📖 <b>{title}</b>\n👤 {authors}\n\n"
            formats = b.get("formats", {})
            url = formats.get("application/epub+zip") or formats.get("text/html")
            if url:
                btns.append([InlineKeyboardButton(text=f"⬇️ {title[:30]}", url=url)])

        btns.append([InlineKeyboardButton(text="🔍 Kitob qidirish", callback_data="book:search")])
        await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")

    except:
        await cb.message.edit_text("❌ Xato yuz berdi. Qaytadan urinib ko'ring.")

@router.callback_query(F.data == "book:favs")
async def book_favs(cb: CallbackQuery):
    uid = cb.from_user.id
    rows = await db_all("SELECT book_id, title FROM book_favorites WHERE user_id=?", (uid,))
    if not rows:
        return await cb.message.edit_text(
            "⭐ Sevimlilar bo'sh.\n\nKitob qidiring va sevimlilaringizga qo'shing!",
            reply_markup=book_kb()
        )
    text = "⭐ <b>Sevimli kitoblaringiz:</b>\n\n"
    for bid, title in rows:
        text += f"📖 {title}\n"
    await cb.message.edit_text(text, reply_markup=book_kb(), parse_mode="HTML")

# ---------- ADMIN PANEL ----------
@router.message(F.text == "📊 Statistika")
async def admin_stats(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    total = await db_get("SELECT COUNT(*) FROM users")
    prem = await db_get("SELECT COUNT(*) FROM users WHERE is_premium=1")
    pending = await db_get("SELECT COUNT(*) FROM payments WHERE status='pending'")
    confirmed = await db_get("SELECT COUNT(*) FROM payments WHERE status='confirmed'")
    today = datetime.date.today().isoformat()
    today_users = await db_get("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",))

    await msg.answer(
        f"📊 <b>Bot Statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchi: <b>{total[0]}</b>\n"
        f"💎 Premium a'zolar: <b>{prem[0]}</b>\n"
        f"🆓 Oddiy a'zolar: <b>{total[0] - prem[0]}</b>\n"
        f"📅 Bugun qo'shilgan: <b>{today_users[0]}</b>\n\n"
        f"💳 Kutayotgan to'lovlar: <b>{pending[0]}</b>\n"
        f"✅ Tasdiqlangan to'lovlar: <b>{confirmed[0]}</b>",
        parse_mode="HTML"
    )

@router.message(F.text == "💳 To'lovlar")
async def admin_payments(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    rows = await db_all(
        "SELECT p.id, p.user_id, p.amount, p.plan, p.screenshot_file_id, u.full_name "
        "FROM payments p JOIN users u ON p.user_id=u.user_id WHERE p.status='pending' LIMIT 10"
    )
    if not rows:
        return await msg.answer("✅ Kutayotgan to'lovlar yo'q!")

    await msg.answer(f"💳 Kutayotgan to'lovlar: {len(rows)} ta")
    for pid, uid, amount, plan, file_id, fname in rows:
        plan_labels = {"1_month": "1 oy", "3_month": "3 oy", "6_month": "6 oy"}
        try:
            await msg.bot.send_photo(
                msg.chat.id, file_id,
                caption=f"💳 To'lov #{pid}\n👤 {fname} ({uid})\n💰 {amount} so'm | {plan_labels.get(plan, plan)}",
                reply_markup=payment_admin_kb(pid, uid)
            )
        except:
            await msg.answer(f"To'lov #{pid}: {fname} — {amount} so'm\n(Rasm yuklanmadi)",
                             reply_markup=payment_admin_kb(pid, uid))

@router.message(F.text == "📢 Kanallar")
async def admin_channels(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    channels = await get_channels()
    text = "📢 <b>Majburiy kanallar:</b>\n\n"
    btns = []
    if channels:
        for ch in channels:
            text += f"• {ch[2]} — <code>{ch[1]}</code>\n"
            btns.append([InlineKeyboardButton(text=f"❌ {ch[2]} ni o'chirish", callback_data=f"delchan:{ch[0]}")])
    else:
        text += "Hali kanal qo'shilmagan."
    btns.append([InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="addchan")])
    await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")

@router.callback_query(F.data == "addchan")
async def add_channel_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminState.adding_channel)
    await cb.message.answer(
        "➕ Kanal ID ni yuboring.\n\n"
        "Misol: <code>-1001234567890</code>\n\n"
        "Kanalga botni admin qiling, so'ng ID yuboring.",
        parse_mode="HTML"
    )

@router.message(AdminState.adding_channel)
async def add_channel_id(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        return
    await state.update_data(channel_id=msg.text.strip())
    await state.set_state(AdminState.adding_channel_link)
    await msg.answer("Kanal nomini yuboring (masalan: Mening Kanalim):")

@router.message(AdminState.adding_channel_link)
async def add_channel_link(msg: Message, state: FSMContext, bot: Bot):
    if msg.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    channel_id = data.get("channel_id")
    channel_name = msg.text.strip()

    await state.clear()
    await msg.answer("Kanal linkini yuboring (masalan: https://t.me/mening_kanalim):")

    @router.message(F.from_user.id == ADMIN_ID)
    async def get_link(m: Message):
        link = m.text.strip()
        await db_run("INSERT INTO channels (channel_id, channel_name, channel_link) VALUES (?,?,?)",
                     (channel_id, channel_name, link))
        await m.answer(f"✅ Kanal qo'shildi: {channel_name}")

@router.callback_query(F.data.startswith("delchan:"))
async def delete_channel(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    cid = int(cb.data.split(":")[1])
    await db_run("DELETE FROM channels WHERE id=?", (cid,))
    await cb.answer("✅ Kanal o'chirildi!")
    await cb.message.edit_reply_markup()

@router.message(F.text == "⚙️ Sozlamalar")
async def admin_settings(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    card = await get_setting("payment_card")
    card_name = await get_setting("payment_name")
    p1 = await get_setting("price_1m")
    p3 = await get_setting("price_3m")
    p6 = await get_setting("price_6m")
    await msg.answer(
        f"⚙️ <b>Sozlamalar</b>\n\n"
        f"💳 Karta: <code>{card}</code>\n"
        f"👤 Egasi: {card_name}\n\n"
        f"💰 Narxlar:\n"
        f"• 1 oy: {p1} so'm\n"
        f"• 3 oy: {p3} so'm\n"
        f"• 6 oy: {p6} so'm\n\n"
        f"Kartani o'zgartirish uchun:\n<code>/setcard RAQAM</code>",
        parse_mode="HTML"
    )

@router.message(Command("setcard"))
async def set_card(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split()
    if len(parts) < 2:
        return await msg.answer("Ishlatilishi: /setcard 1234567890123456")
    await db_run("INSERT OR REPLACE INTO settings VALUES ('payment_card', ?)", (parts[1],))
    await msg.answer(f"✅ Karta yangilandi: {parts[1]}")

# ---------- BROADCAST ----------
@router.message(F.text == "📣 Xabar yuborish")
async def broadcast_start(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminState.broadcast_target)
    await msg.answer("📣 Kimga xabar yuborasiz?", reply_markup=broadcast_kb())

@router.callback_query(F.data.startswith("bcast:"))
async def broadcast_target(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID:
        return
    target = cb.data.split(":")[1]
    if target == "cancel":
        await state.clear()
        return await cb.message.edit_text("❌ Bekor qilindi.")
    await state.update_data(target=target)
    await state.set_state(AdminState.broadcasting)
    labels = {"all": "Hammaga", "premium": "Premium a'zolarga", "free": "Oddiy a'zolarga"}
    await cb.message.edit_text(f"📣 {labels[target]} yuborish uchun xabarni yozing (matn, rasm yoki video):")

@router.message(AdminState.broadcasting)
async def do_broadcast(msg: Message, state: FSMContext, bot: Bot):
    if msg.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    target = data.get("target", "all")
    await state.clear()

    if target == "all":
        users = await db_all("SELECT user_id FROM users WHERE is_banned=0")
    elif target == "premium":
        users = await db_all("SELECT user_id FROM users WHERE is_premium=1 AND is_banned=0")
    else:
        users = await db_all("SELECT user_id FROM users WHERE is_premium=0 AND is_banned=0")

    uids = [u[0] for u in users]
    sent, failed = 0, 0

    status_msg = await msg.answer(f"📤 Yuborilmoqda... 0/{len(uids)}")

    for i, uid in enumerate(uids):
        try:
            await msg.copy_to(uid)
            sent += 1
        except:
            failed += 1
        if (i + 1) % 20 == 0:
            try:
                await status_msg.edit_text(f"📤 Yuborilmoqda... {i+1}/{len(uids)}")
            except:
                pass
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ Yuborish yakunlandi!\n\n"
        f"📤 Yuborildi: {sent}\n"
        f"❌ Xato: {failed}\n"
        f"👥 Jami: {len(uids)}"
    )

@router.message(F.text == "🔙 Asosiy menyu")
async def back_to_main(msg: Message):
    uid = msg.from_user.id
    prem = await check_premium(uid)
    await msg.answer("Asosiy menyu:", reply_markup=main_kb(prem))

# ==================== MAIN ====================
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN, parse_mode=None)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    logger.info("🤖 Bot ishga tushdi!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
