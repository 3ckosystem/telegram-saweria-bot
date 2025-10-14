# --- app/bot.py (drop-in replacement) ---

from dotenv import load_dotenv
load_dotenv()  # baca .env saat jalan lokal

import os, json, time
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# Baca env aman (tidak meledak kalau kosong)
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN belum di-set. Isi di .env (lokal) atau Railway Variables (production)."
    )

BASE_URL = os.getenv("BASE_URL") or "http://127.0.0.1:8000"  # aman untuk lokal
GROUPS = json.loads(os.getenv("GROUP_IDS_JSON") or "[]")

def build_app() -> Application:
    return Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Tombol untuk membuka Mini App (katalog)
    webapp_url = f"{BASE_URL}/webapp/index.html"
    kb = [[KeyboardButton(text="🛍️ Buka Katalog", web_app=WebAppInfo(url=webapp_url))]]
    await update.message.reply_text(
        "Pilih grup yang ingin kamu join, lanjutkan pembayaran QRIS, lalu bot akan kirimkan link undangannya.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

# Penting: gunakan Application (app) agar bisa dipanggil dari FastAPI webhook tanpa Context
async def send_invite_link(app: Application, chat_id: int, target_group_id: str):
    # Buat link sekali pakai (1 member, expired cepat)
    expire = int(time.time()) + 15*60
    link = await app.bot.create_chat_invite_link(
        chat_id=target_group_id,
        member_limit=1,
        expire_date=expire,
        creates_join_request=False,
        name="Paid join"
    )
    await app.bot.send_message(chat_id, f"✅ Pembayaran diterima.\nBerikut link undangan kamu:\n{link.invite_link}")

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
