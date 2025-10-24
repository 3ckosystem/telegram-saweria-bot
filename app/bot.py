# =============================
# app/bot.py
# =============================
from typing import Optional
from telegram.ext import Application, ApplicationBuilder

async def build_app(token: str) -> Application:
    app = ApplicationBuilder().token(token).build()
    return app

async def send_invite_link(app: Application, chat_id: int, target_group_id: str):
    """
    Buat invite link 1x pakai (expire 2 jam) lalu kirim ke DM user.
    Pastikan target_group_id adalah -100xxxxxxxxxx (supergroup).
    """
    import time
    expire = int(time.time()) + 2 * 60 * 60  # 2 jam

    chat_id_int = int(target_group_id)  # pastikan -100... terbaca sebagai int

    link = await app.bot.create_chat_invite_link(
        chat_id=chat_id_int,
        member_limit=1,
        expire_date=expire,
        creates_join_request=False,
        name="Paid join"
    )

    await app.bot.send_message(
        chat_id,
        f"✅ Pembayaran diterima.\nLink undangan kamu (1x pakai, 2 jam):\n{link.invite_link}"
    )
