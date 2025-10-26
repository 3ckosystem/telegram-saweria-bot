# --- app/bot.py (drop-in replacement) ---

from dotenv import load_dotenv
load_dotenv()  # baca .env saat jalan lokal

import os, json, time, asyncio
from typing import Any, Optional
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import Forbidden, BadRequest, RetryAfter, TimedOut, NetworkError

# ENV aman
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN belum di-set. Isi di .env (lokal) atau Railway Variables (production).")

BASE_URL = os.getenv("BASE_URL") or "http://127.0.0.1:8000"  # aman untuk lokal
GROUPS = json.loads(os.getenv("GROUP_IDS_JSON") or "[]")

# peta id -> name (untuk pesan yang lebih informatif)
GROUP_NAME_BY_ID = {}
try:
    for g in GROUPS:
        gid = str(g.get("id") or "").strip()
        nm  = str(g.get("name") or gid).strip()
        if gid:
            GROUP_NAME_BY_ID[gid] = nm
except Exception:
    pass


def build_app() -> Application:
    return Application.builder().token(BOT_TOKEN).build()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    webapp_url = f"{BASE_URL}/webapp/index.html?v=netflix1&uid={uid}"



    kb = [[KeyboardButton(
        text="🛍️ Buka Katalog",
        web_app=WebAppInfo(url=webapp_url)
    )]]
    await update.message.reply_text(
        "Pilih grup yang ingin kamu join, lanjutkan pembayaran QRIS, lalu bot akan kirimkan link undangannya.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )


async def _to_int_or_str(v: Any):
    """Normalisasi chat_id: utamakan int jika bisa, jika tidak biarkan string."""
    try:
        return int(str(v))
    except Exception:
        return str(v)


async def _create_link_with_retry(bot, chat_id, **kwargs):
    """
    Coba create_chat_invite_link dengan retry & backoff ringan.
    Return: objek InviteLink atau None jika gagal permanen.
    """
    delays = [0, 0.7, 1.2]  # 3 percobaan
    last_err: Optional[Exception] = None
    for d in delays:
        if d:
            await asyncio.sleep(d)
        try:
            return await bot.create_chat_invite_link(chat_id=chat_id, **kwargs)
        except RetryAfter as e:
            await asyncio.sleep(getattr(e, "retry_after", 1.5))
            last_err = e
        except (TimedOut, NetworkError) as e:
            last_err = e
        except (Forbidden, BadRequest) as e:
            # biasanya: bot bukan admin, tidak punya izin
            last_err = e
            break
        except Exception as e:
            last_err = e
    if last_err:
        print("[invite] create_chat_invite_link failed:", last_err)
    return None


# Penting: gunakan Application (app) agar bisa dipanggil dari FastAPI webhook tanpa Context
async def send_invite_link(app: Application, user_id: int, target_group_id):
    """
    Kirim SATU link undangan untuk satu grup (dipanggil berulang oleh main.py untuk multi-grup).
    - Normalisasi group_id → int bila memungkinkan.
    - Coba create_chat_invite_link; jika gagal, fallback export_chat_invite_link.
    - Kirim DM berbeda untuk setiap grup.
    """
    group_id_norm = await _to_int_or_str(target_group_id)
    group_id_str  = str(target_group_id)
    group_name    = GROUP_NAME_BY_ID.get(group_id_str, group_id_str)

    # buat link sekali pakai (member_limit=1) + kedaluwarsa cepat
    expire = int(time.time()) + 15 * 60

    link_obj = await _create_link_with_retry(
        app.bot,
        chat_id=group_id_norm,
        member_limit=1,
        expire_date=expire,
        creates_join_request=False,
        name="Paid join",
    )

    invite_link_url: Optional[str] = None
    if link_obj and getattr(link_obj, "invite_link", None):
        invite_link_url = link_obj.invite_link
    else:
        # fallback: export (permanent) jika create gagal (mis. bot bukan admin penuh)
        try:
            invite_link_url = await app.bot.export_chat_invite_link(chat_id=group_id_norm)
        except Exception as e:
            print(f"[invite] export_chat_invite_link failed for {group_id_str}:", e)

    if not invite_link_url:
        # beritahu user gagal untuk grup ini, namun jangan hentikan alur grup lain
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ Gagal membuat undangan untuk grup: {group_name}\n"
                     f"Pastikan bot adalah admin di grup tersebut."
            )
        except Exception as e:
            print("[invite] notify user failed:", e)
        return

    # kirim DM satu pesan per grup
    try:
        await app.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ Pembayaran diterima.\n"
                f"Undangan untuk {group_name}:\n{invite_link_url}"
            )
        )
    except Exception as e:
        print("[invite] send DM failed:", e)


def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
