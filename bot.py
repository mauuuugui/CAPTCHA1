#!/usr/bin/env python3
# bot.py
import os
import sqlite3
import random
import string
import io
import time
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
import telebot

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None

if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN missing. Put it into a .env file or environment variable.")

DB_PATH = "bot.db"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ---------- Database helpers ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        wallet INTEGER DEFAULT 0,
        withdrawable INTEGER DEFAULT 0,
        pending_captcha TEXT,
        captcha_ts INTEGER
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        status TEXT,
        created_at INTEGER,
        details TEXT
    )
    """)
    conn.commit()
    conn.close()

def ensure_user(user_id, username=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    if not r:
        # starting demo wallet (change if you want)
        cur.execute("INSERT INTO users (user_id, username, wallet, withdrawable) VALUES (?,?,?,?)",
                    (user_id, username or "", 100, 0))
        conn.commit()
    else:
        if username and r["username"] != username:
            cur.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
            conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    conn.close()
    return r

def update_balances(user_id, delta_wallet=0, delta_withdrawable=0):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet + ?, withdrawable = withdrawable + ? WHERE user_id = ?",
                (delta_wallet, delta_withdrawable, user_id))
    conn.commit()
    conn.close()

def set_pending_captcha(user_id, text):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET pending_captcha = ?, captcha_ts = ? WHERE user_id = ?",
                (text, int(time.time()), user_id))
    conn.commit()
    conn.close()

def clear_pending_captcha(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET pending_captcha = NULL, captcha_ts = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def create_withdraw_request(user_id, amount, details=""):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO withdrawals (user_id, amount, status, created_at, details) VALUES (?,?,?,?,?)",
                (user_id, amount, "pending", int(time.time()), details))
    conn.commit()
    conn.close()

def list_pending_withdrawals():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT w.id, w.user_id, w.amount, w.status, w.created_at, u.username FROM withdrawals w LEFT JOIN users u ON u.user_id = w.user_id WHERE w.status = 'pending' ORDER BY w.created_at ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

# ---------- Captcha image generator ----------
def gen_captcha_text(n=5):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

def gen_captcha_image(text):
    W, H = 260, 90
    image = Image.new('RGB', (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    # font: fallback to default font
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
    except Exception:
        font = ImageFont.load_default()

    # draw noisy background
    for _ in range(40):
        x1 = random.randint(0, W)
        y1 = random.randint(0, H)
        x2 = x1 + random.randint(1, 10)
        y2 = y1 + random.randint(1, 10)
        draw.line(((x1, y1), (x2, y2)), fill=(random.randint(100,200), random.randint(100,200), random.randint(100,200)))

    # draw text in slightly varying positions and rotations
    spacing = W // len(text)
    for i, ch in enumerate(text):
        x = 10 + i * spacing + random.randint(-6, 6)
        y = 15 + random.randint(-8, 8)
        draw.text((x, y), ch, font=font, fill=(0, 0, 0))

    # more noise dots
    for _ in range(200):
        x = random.randint(0, W-1)
        y = random.randint(0, H-1)
        draw.point((x, y), fill=(random.randint(0,150), random.randint(0,150), random.randint(0,150)))

    bio = io.BytesIO()
    image.save(bio, format='PNG')
    bio.seek(0)
    return bio

# ---------- Command handlers ----------
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    user_id = msg.from_user.id
    username = msg.from_user.username or f"{msg.from_user.first_name} {msg.from_user.last_name or ''}".strip()
    ensure_user(user_id, username)
    b = get_user(user_id)
    text = (
        f"👋 Hello {msg.from_user.first_name}!\n\n"
        "This bot runs games to earn virtual pesos.\n\n"
        "Available commands:\n"
        "/balance - Show your wallet & withdrawable balance\n"
        "/withdraw <amount> - Request withdrawal (min ₱888)\n"
        "/captcha2earn - Solve a visual captcha to earn ₱1–₱10\n"
        "/dice <odd|even> <amount> - 2x payout on win\n"
        "/scatter <amount> - Slot-like spin (30% win chance, 2x on win)\n\n"
        "Type a command to begin. Good luck! 🍀"
    )
    bot.reply_to(msg, text)

@bot.message_handler(commands=['help'])
def cmd_help(msg):
    cmd_start(msg)

@bot.message_handler(commands=['balance'])
def cmd_balance(msg):
    user_id = msg.from_user.id
    ensure_user(user_id, msg.from_user.username)
    u = get_user(user_id)
    text = (
        f"💼 <b>Wallet</b>: ₱{u['wallet']}\n"
        f"💳 <b>Withdrawable</b>: ₱{u['withdrawable']}\n\n"
        "Wallet = funds you can bet with.\n"
        "Withdrawable = funds eligible for withdrawal (must be ≥ ₱888 to request)."
    )
    bot.reply_to(msg, text)

@bot.message_handler(commands=['captcha2earn'])
def cmd_captcha(msg):
    user_id = msg.from_user.id
    ensure_user(user_id, msg.from_user.username)
    code = gen_captcha_text(5)
    bio = gen_captcha_image(code)
    set_pending_captcha(user_id, code)
    caption = "✅ Solve the captcha: send the text exactly (case-insensitive) as a message to this chat.\nYou will earn a random ₱1–₱10 if correct."
    bot.send_photo(msg.chat.id, bio, caption=caption)

# fallback: check if user is answering a pending captcha
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(msg):
    user_id = msg.from_user.id
    ensure_user(user_id, msg.from_user.username)
    u = get_user(user_id)
    text = msg.text.strip()
    # check captcha first
    if u and u['pending_captcha']:
        expected = u['pending_captcha']
        # allow case-insensitive match
        if text.upper() == expected.upper():
            reward = random.randint(1, 10)
            # reward both wallet and withdrawable (makes them withdrawable)
            update_balances(user_id, delta_wallet=reward, delta_withdrawable=reward)
            clear_pending_captcha(user_id)
            bot.reply_to(msg, f"✅ Correct! You earned ₱{reward}. Your withdrawable and wallet increased by ₱{reward}.\nUse /balance to see totals.")
            return
        else:
            bot.reply_to(msg, "❌ That's not correct. Try /captcha2earn to get a new captcha.")
            return
    # otherwise, no special fallback
    bot.reply_to(msg, "I didn't recognize that. Use /help to see available commands.")

# ---- Dice game ----
@bot.message_handler(commands=['dice'])
def cmd_dice(msg):
    user_id = msg.from_user.id
    ensure_user(user_id, msg.from_user.username)
    parts = msg.text.split()
    if len(parts) < 3:
        bot.reply_to(msg, "Usage: /dice <odd|even> <amount>\nExample: /dice odd 50")
        return
    choice = parts[1].lower()
    if choice not in ('odd','even'):
        bot.reply_to(msg, "Choice must be 'odd' or 'even'.")
        return
    try:
        amt = int(parts[2])
    except:
        bot.reply_to(msg, "Amount must be a whole number (pesos).")
        return
    u = get_user(user_id)
    if amt <= 0:
        bot.reply_to(msg, "Bet must be positive.")
        return
    if amt > u['wallet']:
        bot.reply_to(msg, f"Insufficient wallet funds. Your wallet: ₱{u['wallet']}")
        return
    # deduct stake
    update_balances(user_id, delta_wallet=-amt, delta_withdrawable=0)
    roll = random.randint(1,6)
    is_odd = roll % 2 == 1
    win = (is_odd and choice == 'odd') or (not is_odd and choice == 'even')
    if win:
        payout = amt * 2  # returns stake + profit
        # credit payout; add profit to withdrawable (profit equals amt)
        update_balances(user_id, delta_wallet=payout, delta_withdrawable=amt)
        bot.reply_to(msg, f"🎲 Roll: {roll} — <b>YOU WIN</b>!\nYou bet ₱{amt} on {choice}. Payout: ₱{payout} (2x).\nProfit ₱{amt} added to withdrawable.\nUse /balance to view totals.")
    else:
        bot.reply_to(msg, f"🎲 Roll: {roll} — <b>YOU LOSE</b>.\nYou lost ₱{amt}. Better luck next time! Use /balance to view totals.")

# ---- Scatter (slot-like) game ----
EMOJIS = ["🍒","7️⃣","🔔","🍋","⭐","🍀","🍉","🍇"]

@bot.message_handler(commands=['scatter'])
def cmd_scatter(msg):
    user_id = msg.from_user.id
    ensure_user(user_id, msg.from_user.username)
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, "Usage: /scatter <amount>\nExample: /scatter 50")
        return
    try:
        amt = int(parts[1])
    except:
        bot.reply_to(msg, "Amount must be a whole number (pesos).")
        return
    u = get_user(user_id)
    if amt <= 0:
        bot.reply_to(msg, "Bet must be positive.")
        return
    if amt > u['wallet']:
        bot.reply_to(msg, f"Insufficient wallet funds. Your wallet: ₱{u['wallet']}")
        return

    # deduct stake
    update_balances(user_id, delta_wallet=-amt, delta_withdrawable=0)

    # send "spinning" message and animate
    spinning = bot.send_message(msg.chat.id, "🎰 Spinning...")
    spin_steps = 7
    final = []
    for i in range(spin_steps):
        sample = random.choices(EMOJIS, k=3)
        bot.edit_message_text(chat_id=spinning.chat.id, message_id=spinning.message_id, text=" ".join(sample))
        time.sleep(0.5)

    # determine win with 30% probability
    win = random.random() < 0.30
    final_symbols = random.choices(EMOJIS, k=3)
    if win:
        # make final symbols look like a "winning" combo (prefer 7's or three same)
        choice = random.choice(EMOJIS)
        final_symbols = [choice, choice, choice]
        payout = amt * 2
        update_balances(user_id, delta_wallet=payout, delta_withdrawable=amt)
        bot.edit_message_text(chat_id=spinning.chat.id, message_id=spinning.message_id,
                              text=f"{' '.join(final_symbols)}\n\n🎉 <b>YOU WIN!</b>\nYou bet ₱{amt} — payout ₱{payout} (2x). Profit ₱{amt} added to withdrawable.\nUse /balance to see totals.")
    else:
        bot.edit_message_text(chat_id=spinning.chat.id, message_id=spinning.message_id,
                              text=f"{' '.join(final_symbols)}\n\n💨 <b>House wins</b> — You lost ₱{amt}. Better luck next time!\nUse /balance to see totals.")

# ---- Withdraw ----
@bot.message_handler(commands=['withdraw'])
def cmd_withdraw(msg):
    user_id = msg.from_user.id
    ensure_user(user_id, msg.from_user.username)
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, "Usage: /withdraw <amount>\nMinimum withdrawal: ₱888")
        return
    try:
        amt = int(parts[1])
    except:
        bot.reply_to(msg, "Amount must be a whole number.")
        return
    if amt < 888:
        bot.reply_to(msg, "Minimum withdrawal amount is ₱888.")
        return
    u = get_user(user_id)
    if amt > u['withdrawable']:
        bot.reply_to(msg, f"You don't have enough withdrawable funds. Withdrawable: ₱{u['withdrawable']}")
        return
    # create request and deduct immediately from withdrawable & wallet
    create_withdraw_request(user_id, amt, details="")
    update_balances(user_id, delta_wallet=-amt, delta_withdrawable=-amt)
    bot.reply_to(msg, f"✅ Withdrawal request created for ₱{amt}. An admin will review it.\nIf you want to provide payout details, reply here with your payout method (e.g. GCash number).")

# ---- Admin: list pending withdrawals ----
@bot.message_handler(commands=['pending_withdrawals'])
def cmd_pending(msg):
    if ADMIN_ID is None or msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "Unauthorized.")
        return
    rows = list_pending_withdrawals()
    if not rows:
        bot.reply_to(msg, "No pending withdrawals.")
        return
    lines = []
    for r in rows:
        ts = datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"ID:{r['id']} user:{r['username'] or r['user_id']} amount:₱{r['amount']} time:{ts}")
    bot.reply_to(msg, "\n".join(lines))

# ---------- start ----------
if __name__ == "__main__":
    init_db()
    print("Bot starting...")
    bot.infinity_polling()

