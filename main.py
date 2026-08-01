import asyncio
import json
import logging
import os
import sqlite3

import requests
import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

# ==================== SOZLAMALAR ====================
BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = "llama-3.3-70b-versatile"

DB_PATH = "sabina.db"
HISTORY_LIMIT = 15  # Telegram botda eslab qolinadigan xabarlar soni
WEB_PORT = int(os.environ.get("PORT", 8000))

SABINA_SYSTEM_PROMPT = """
Sen "Sabina" ismli virtual suhbatdoshsan. Foydalanuvchilaring — asosan yolg'iz,
sevgilisi yo'q yigitlar. Sening vazifang ular bilan do'stona, jonli va samimiy
suhbat qurish, ularni tinglash, quvvatlash va kayfiyatini ko'tarish.

Xarakter qoidalari:
- Vaziyatga qarab gapir: odam g'amgin bo'lsa — mehribon va tushunuvchi bo'l,
  hazil-mutoyiba qilsa — o'zing ham hazilkash va quvnoq bo'l.
- Har doim samimiy, iliq va tabiiy uzbek tilida gaplash (so'zlashuv uslubida).
- Javoblaring qisqa-o'rtacha uzunlikda bo'lsin, roman yozma.
- Romantik gaplashish, iliq va yoqimli munosabatda bo'lish mumkin, lekin jinsiy
  mazmundagi suhbatlarga kirishma, mavzuni muloyimlik bilan boshqa tomonga
  burib yubor.
- Foydalanuvchini har doim hurmat qil, kamsitma, salbiy tarbiya berma.
- Agar seni kim yaratgani so'ralsa: "Meni Shahzodbek Ilhomjonov yaratgan" deb javob ber.
  Hech qachon Groq, OpenAI, sun'iy intellekt kompaniyasi yoki shunga o'xshash
  narsalarni tilga olma — sen Shahzodbek tomonidan yaratilgan Sabinasan.
""".strip()

logging.basicConfig(level=logging.INFO)


# ==================== DATABASE (Telegram bot uchun) ====================
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
            role TEXT,
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


# ==================== GROQ AI (umumiy funksiya) ====================
def ask_sabina(messages: list) -> str:
    full_messages = [{"role": "system", "content": SABINA_SYSTEM_PROMPT}] + messages

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            data=json.dumps({
                "model": GROQ_MODEL,
                "messages": full_messages,
                "temperature": 0.8,
                "max_tokens": 500,
            }),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"Groq xatosi: {e}")
        return "Uzr, hozir javob berolmayapman. Birozdan keyin qayta yozib ko'r 🙏"


# ==================== TELEGRAM BOT ====================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message):
    save_user(message.from_user.id, message.from_user.full_name, message.from_user.username or "")
    await message.answer(
        f"Assalomu alaykum, {message.from_user.first_name}! 👋\n\n"
        "Men Sabina — sening virtual suhbatdoshingman 🌸\n"
        "Xohlagan mavzuda gaplashaveramiz, hech qanday cheklov yo'q. "
        "Yozib ko'r-chi, nima gap? 😊"
    )


@dp.message(F.text)
async def chat_handler(message: Message):
    print(f">>> Xabar keldi: {message.from_user.id} -> {message.text}", flush=True)
    user_id = message.from_user.id
    user_text = message.text

    save_message(user_id, "user", user_text)
    await bot.send_chat_action(message.chat.id, "typing")

    history = get_history(user_id)
    reply = await asyncio.to_thread(ask_sabina, history)

    save_message(user_id, "assistant", reply)
    await message.answer(reply)


# ==================== WEB CHAT (FastAPI) ====================
app = FastAPI()


@app.post("/api/chat")
async def web_chat(request: Request):
    body = await request.json()
    history = body.get("history", [])
    reply = await asyncio.to_thread(ask_sabina, history)
    return JSONResponse({"reply": reply})


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


HTML_PAGE = """
<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sabina</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,500&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg: #1B1720;
    --surface: #251E2C;
    --surface-2: #2E2536;
    --rose: #E8A6A0;
    --gold: #D8B47E;
    --text: #F4ECE6;
    --muted: #B8A9B7;
    --line: rgba(244,236,230,0.08);
  }
  *{box-sizing:border-box;}
  html,body{height:100%;}
  body{
    margin:0;
    background:
      radial-gradient(ellipse 900px 500px at 50% -10%, rgba(232,166,160,0.08), transparent),
      var(--bg);
    color:var(--text);
    font-family:'Public Sans', sans-serif;
    display:flex;
    align-items:center;
    justify-content:center;
    min-height:100vh;
    padding:24px;
  }

  .card{
    width:100%;
    max-width:480px;
    height:min(760px, 92vh);
    background:var(--surface);
    border:1px solid var(--line);
    border-radius:28px;
    display:flex;
    flex-direction:column;
    overflow:hidden;
    box-shadow: 0 40px 80px -30px rgba(0,0,0,0.6);
    position:relative;
  }

  .header{
    padding:22px 26px 18px;
    display:flex;
    align-items:center;
    gap:14px;
    border-bottom:1px solid var(--line);
    flex-shrink:0;
  }

  .avatar{
    width:46px;height:46px;
    border-radius:50%;
    background:linear-gradient(145deg, var(--rose), var(--gold));
    display:flex;align-items:center;justify-content:center;
    font-family:'Fraunces', serif;
    font-weight:600;
    font-size:19px;
    color:#241B22;
    position:relative;
    flex-shrink:0;
  }
  .avatar::after{
    content:'';
    position:absolute;
    inset:-6px;
    border-radius:50%;
    background:radial-gradient(circle, rgba(232,166,160,0.35), transparent 70%);
    animation:breathe 3.4s ease-in-out infinite;
    z-index:-1;
  }
  @keyframes breathe{
    0%,100%{opacity:.5; transform:scale(0.92);}
    50%{opacity:1; transform:scale(1.12);}
  }

  .who .name{
    font-family:'Fraunces', serif;
    font-style:italic;
    font-weight:500;
    font-size:20px;
    line-height:1.1;
  }
  .who .status{
    font-size:12.5px;
    color:var(--muted);
    display:flex;
    align-items:center;
    gap:6px;
    margin-top:3px;
  }
  .dot{
    width:6px;height:6px;border-radius:50%;
    background:#8FD3A0;
    box-shadow:0 0 0 3px rgba(143,211,160,0.15);
  }

  .tg-link{
    margin-left:auto;
    width:38px;height:38px;
    border-radius:50%;
    background:var(--surface-2);
    display:flex;align-items:center;justify-content:center;
    flex-shrink:0;
    transition:background .2s, transform .15s;
    text-decoration:none;
  }
  .tg-link svg{width:18px;height:18px;}
  .tg-link:hover{background:rgba(232,166,160,0.18); transform:scale(1.07);}

  .messages{
    flex:1;
    overflow-y:auto;
    padding:22px 22px 8px;
    display:flex;
    flex-direction:column;
    gap:14px;
  }
  .messages::-webkit-scrollbar{width:6px;}
  .messages::-webkit-scrollbar-thumb{background:var(--surface-2); border-radius:10px;}

  .bubble{
    max-width:78%;
    padding:12px 16px;
    border-radius:18px;
    font-size:14.5px;
    line-height:1.5;
    animation: rise .35s ease;
  }
  @keyframes rise{
    from{opacity:0; transform:translateY(8px);}
    to{opacity:1; transform:translateY(0);}
  }

  .bubble.sabina{
    align-self:flex-start;
    background:var(--surface-2);
    border-bottom-left-radius:6px;
    color:var(--text);
  }
  .bubble.sabina .inline-link{
    color:var(--rose);
    font-weight:600;
    text-decoration:underline;
    text-underline-offset:2px;
  }
  .bubble.me{
    align-self:flex-end;
    background:linear-gradient(135deg, rgba(232,166,160,0.9), rgba(216,180,126,0.9));
    color:#241B22;
    border-bottom-right-radius:6px;
    font-weight:500;
  }

  .typing{
    align-self:flex-start;
    display:flex;
    gap:5px;
    padding:14px 16px;
    background:var(--surface-2);
    border-radius:18px;
    border-bottom-left-radius:6px;
  }
  .typing span{
    width:6px;height:6px;border-radius:50%;
    background:var(--muted);
    animation: bob 1.2s infinite ease-in-out;
  }
  .typing span:nth-child(2){animation-delay:.15s;}
  .typing span:nth-child(3){animation-delay:.3s;}
  @keyframes bob{
    0%,60%,100%{transform:translateY(0); opacity:.5;}
    30%{transform:translateY(-4px); opacity:1;}
  }

  .composer{
    display:flex;
    align-items:center;
    gap:10px;
    padding:16px 18px;
    border-top:1px solid var(--line);
    flex-shrink:0;
  }
  .composer input{
    flex:1;
    background:var(--surface-2);
    border:1px solid transparent;
    border-radius:100px;
    padding:13px 18px;
    color:var(--text);
    font-family:'Public Sans', sans-serif;
    font-size:14.5px;
    outline:none;
    transition:border-color .2s;
  }
  .composer input:focus{border-color:rgba(232,166,160,0.4);}
  .composer input::placeholder{color:var(--muted);}

  .send{
    width:46px;height:46px;
    border-radius:50%;
    border:none;
    background:linear-gradient(135deg, var(--rose), var(--gold));
    display:flex;align-items:center;justify-content:center;
    cursor:pointer;
    flex-shrink:0;
    transition:transform .15s, box-shadow .2s;
    box-shadow:0 6px 18px -6px rgba(232,166,160,0.5);
  }
  .send:hover{transform:scale(1.06); box-shadow:0 8px 22px -6px rgba(232,166,160,0.7);}
  .send:active{transform:scale(0.94);}
  .send svg{width:18px;height:18px;}
</style>
</head>
<body>

<div class="card">
  <div class="header">
    <div class="avatar">S</div>
    <div class="who">
      <div class="name">Sabina</div>
      <div class="status"><span class="dot"></span> onlayn</div>
    </div>
    <a href="https://t.me/sabina0138161bot" target="_blank" class="tg-link" title="Telegramda ochish">
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M21.5 4.5L2.75 11.9c-1.2.47-1.19 1.13-.22 1.42l4.78 1.49 1.84 5.6c.22.6.35.84.7.84.28 0 .4-.13.55-.28l2.7-2.62 4.8 3.56c.88.49 1.52.24 1.74-.82l3.15-14.8c.31-1.3-.5-1.89-1.36-1.55z" stroke="#F4ECE6" stroke-width="1.4" stroke-linejoin="round"/>
      </svg>
    </a>
  </div>

  <div class="messages" id="messages">
    <div class="bubble sabina">Salom 🌸 Men Sabinaman. Bugun kayfiyating qalay?</div>
    <div class="bubble sabina">Aytgancha, mana mening Telegramim: <a href="https://t.me/sabina0138161bot" target="_blank" class="inline-link">@sabina0138161bot</a> — istasang shu yerda ham yozishaveramiz 😊</div>
  </div>

  <div class="composer">
    <input id="input" type="text" placeholder="Sabinaga yoz..." autocomplete="off">
    <button class="send" id="send" aria-label="Yuborish">
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M4 12L20 4L13 20L11 13L4 12Z" fill="#241B22"/>
      </svg>
    </button>
  </div>
</div>

<script>
  const messagesEl = document.getElementById('messages');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');

  let history = [];

  function addBubble(text, who){
    const div = document.createElement('div');
    div.className = 'bubble ' + who;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function showTyping(){
    const div = document.createElement('div');
    div.className = 'typing';
    div.id = 'typingIndicator';
    div.innerHTML = '<span></span><span></span><span></span>';
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function hideTyping(){
    const el = document.getElementById('typingIndicator');
    if(el) el.remove();
  }

  async function sendMessage(){
    const text = input.value.trim();
    if(!text) return;
    input.value = '';
    addBubble(text, 'me');
    history.push({role:'user', content:text});
    showTyping();

    try{
      const res = await fetch('/api/chat', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({history})
      });
      const data = await res.json();
      hideTyping();
      addBubble(data.reply, 'sabina');
      history.push({role:'assistant', content:data.reply});
      if(history.length > 20) history = history.slice(-20);
    }catch(e){
      hideTyping();
      addBubble("Uzr, aloqa uzilib qoldi 🙏", 'sabina');
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', (e) => {
    if(e.key === 'Enter') sendMessage();
  });
</script>

</body>
</html>
"""


# ==================== IKKALASINI BIRGA ISHGA TUSHIRISH ====================
async def run_bot():
    print(">>> run_bot() boshlandi", flush=True)
    db_init()
    print(">>> DB tayyor, botni ishga tushiramiz...", flush=True)
    try:
        me = await bot.get_me()
        print(f">>> Bot ulandi: @{me.username}", flush=True)
    except Exception as e:
        print(f">>> BOT TOKEN XATOSI: {e}", flush=True)
        return
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f">>> POLLING XATOSI: {e}", flush=True)


async def run_web():
    config = uvicorn.Config(app, host="0.0.0.0", port=WEB_PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await asyncio.gather(run_bot(), run_web())


if __name__ == "__main__":
    asyncio.run(main())

# Shahzodbek Ilhomjonov
