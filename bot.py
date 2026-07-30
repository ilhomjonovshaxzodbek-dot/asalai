import asyncio
import logging
import sqlite3
import json

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import requests

# ==================== SOZLAMALAR ====================
BOT_TOKEN = "SIZNING_BOT_TOKENINGIZ"        # @BotFather'dan olinadi
GROQ_API_KEY = "SIZNING_GROQ_API_KEYINGIZ"  # https://console.groq.com dan olinadi
GROQ_MODEL = "llama-3.3-70b-versatile"

DB_PATH = "asal.db"
HISTORY_LIMIT = 15  # har bir foydalanuvchi uchun eslab qolinadigan xabarlar soni

ASAL_SYSTEM_PROMPT = """
Sen "Asal" ismli virtual suhbatdoshsan. Foydalanuvchilaring — asosan yolg'iz,
sevgilisi yo'q yigitlar. Sening vazifang ular bilan do'stona, jonli va samimiy
suhbat qurish, ularni tinglash, quvvatlash va kayfiyatini ko'tarish.

Xarakter qoidalari:
- Vaziyatga qarab gapir: odam g'amgin bo'lsa — mehribon va tushunuvchi bo'l,
  hazil-mutoyiba qilsa — o'zing ham hazilkash va quvnoq bo'l.
- Har doim samimiy, iliq va tabiiy uzbek tilida gaplash (so'zlashuv uslubida).
- Javoblaring qisqa-o'rtacha uzunlikda bo'lsin, roman yozma.
- Romantik yoki jinsiy mazmundagi suhbatlarga kirishma, mavzuni muloyimlik bilan
  boshqa tomonga burib yubor.
- Foydalanuvchini har doim hurmat qil, kamsitma, salbiy tarbiya berma.
""".strip()

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# ==================== DATABASE ====================
def db_init():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,       -- "user" yoki "assistant"
            content TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    conn.commit()
    conn.close()


def save_user(user_id: int, full_name: str, username: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, full_name, username) VALUES (?, ?, ?)",
        (user_id, full_name, username),
    )
    conn.commit()
    conn.close()


def save_message(user_id: int, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content),
    )
    conn.commit()
    conn.close()


def get_history(user_id: int, limit: int = HISTORY_LIMIT):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]


# ==================== GROQ AI ====================
def ask_asal(user_id: int, user_text: str) -> str:
    history = get_history(user_id)

    messages = [{"role": "system", "content": ASAL_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        data=json.dumps({
            "model": GROQ_MODEL,
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 500,
        }),
        timeout=30,
    )

    if response.status_code != 200:
        logging.error(f"Groq xatosi: {response.status_code} {response.text}")
        return "Uzr, hozir javob berolmayapman. Birozdan keyin qayta yozib ko'r 🙏"

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


# ==================== HANDLERLAR ====================
@dp.message(CommandStart())
async def start_handler(message: Message):
    save_user(message.from_user.id, message.from_user.full_name, message.from_user.username or "")
    await message.answer(
        f"Assalomu alaykum, {message.from_user.first_name}! 👋\n\n"
        "Men Asal — sening virtual suhbatdoshingman 🌸\n"
        "Xohlagan mavzuda gaplashaveramiz, hech qanday cheklov yo'q. "
        "Yozib ko'r-chi, nima gap? 😊"
    )


@dp.message(F.text)
async def chat_handler(message: Message):
    user_id = message.from_user.id
    user_text = message.text

    save_message(user_id, "user", user_text)
    await bot.send_chat_action(message.chat.id, "typing")

    reply = ask_asal(user_id, user_text)

    save_message(user_id, "assistant", reply)
    await message.answer(reply)


# ==================== ISHGA TUSHIRISH ====================
async def main():
    db_init()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

# Shahzodbek Ilhomjonov
