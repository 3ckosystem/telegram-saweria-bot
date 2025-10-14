import os, json, asyncio, time
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROUPS = json.loads(os.environ.get("GROUP_IDS_JSON","[]"))

def build_app() -> Application:
    return Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Tombol untuk membuka Mini App (katalog)
    webapp_url = f'{os.environ["BASE_URL"]}/webapp/index.html'
    kb = [[KeyboardButton(text="🛍️ Buka Katalog", web_app=WebAppInfo(url=webapp_url))]]
    await update.message.reply_text(
        "Pilih grup yang ingin kamu join, lanjutkan pembayaran QRIS, lalu bot akan kirimkan link undangannya.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def send_invite_link(context: ContextTypes.DEFAULT_TYPE, chat_id: int, target_group_id: str):
    # Buat link sekali pakai (1 member, expired cepat)
    expire = int(time.time()) + 15*60
    link = await context.bot.create_chat_invite_link(
        chat_id=target_group_id,
        member_limit=1,
        expire_date=expire,
        creates_join_request=False,
        name="Paid join"
    )
    await context.bot.send_message(chat_id, f"✅ Pembayaran diterima.\nBerikut link undangan kamu:\n{link.invite_link}")

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
