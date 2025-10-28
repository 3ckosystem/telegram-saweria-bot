# --- app/bot.py (drop-in replacement with membership gate) ---

from dotenv import load_dotenv
load_dotenv()  # baca .env saat jalan lokal

import os, json, time, asyncio
from datetime import datetime, timedelta
from typing import Any, Optional, List, Tuple

from telegram import (
    Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler
)
from telegram.error import Forbidden, BadRequest, RetryAfter, TimedOut, NetworkError
from telegram.ext import MessageHandler, filters



# ===================== ENV & CONFIG =====================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN belum di-set. Isi di .env (lokal) atau Railway Variables (production).")

BASE_URL = os.getenv("BASE_URL") or "http://127.0.0.1:8000"
WEBAPP_URL = (os.getenv("WEBAPP_URL") or "").strip()  # jika kosong, fallback pakai BASE_URL

def _split_env(name: str) -> List[str]:
    val = os.getenv(name, "") or ""
    return [x.strip() for x in val.split(",") if x.strip()]

# Gate multi grup/channel
REQ_GROUP_IDS: List[str] = _split_env("REQUIRED_GROUP_IDS")
REQ_CHANNEL_IDS: List[str] = _split_env("REQUIRED_CHANNEL_IDS")
REQ_GROUP_INVITES: List[str] = _split_env("REQUIRED_GROUP_INVITES")
REQ_CHANNEL_INVITES: List[str] = _split_env("REQUIRED_CHANNEL_INVITES")
REQ_GROUP_USERNAMES: List[str] = _split_env("REQUIRED_GROUP_USERNAMES")
REQ_CHANNEL_USERNAMES: List[str] = _split_env("REQUIRED_CHANNEL_USERNAMES")

def _raw_env(name: str) -> str:
    v = os.getenv(name, "")
    # potong biar aman ditampilkan
    return (v[:300] + "...") if len(v) > 300 else v

async def gate_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    def join(lst): return ", ".join(lst) if lst else "(empty)"
    msg = (
        "🔎 Gate Debug\n"
        f"- REQUIRED_MODE = {REQ_MODE}\n"
        f"- REQUIRED_MIN_COUNT = {REQ_MIN_COUNT}\n"
        f"- RAW REQUIRED_GROUP_IDS = { _raw_env('REQUIRED_GROUP_IDS') }\n"
        f"- RAW REQUIRED_CHANNEL_IDS = { _raw_env('REQUIRED_CHANNEL_IDS') }\n"
        f"- Parsed GROUP_IDS = [{join(REQ_GROUP_IDS)}]\n"
        f"- Parsed CHANNEL_IDS = [{join(REQ_CHANNEL_IDS)}]\n"
        f"- GROUP_INVITES = [{join(REQ_GROUP_INVITES)}]\n"
        f"- CHANNEL_INVITES = [{join(REQ_CHANNEL_INVITES)}]\n"
        f"- GROUP_USERNAMES = [{join(REQ_GROUP_USERNAMES)}]\n"
        f"- CHANNEL_USERNAMES = [{join(REQ_CHANNEL_USERNAMES)}]\n"
    )
    await update.message.reply_text(msg)

# --- di register_handlers(app) tambahkan baris ini:
def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gate_debug", gate_debug))  # <— debug
    app.add_handler(CallbackQueryHandler(on_recheck, pattern="^recheck_membership$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))

REQ_MODE = (os.getenv("REQUIRED_MODE", "ALL") or "ALL").upper()  # ALL | ANY
try:
    REQ_MIN_COUNT = int(os.getenv("REQUIRED_MIN_COUNT", "1"))
except ValueError:
    REQ_MIN_COUNT = 1

# GROUPS lama (untuk mapping nama saat kirim undangan)
GROUPS = json.loads(os.getenv("GROUP_IDS_JSON") or "[]")
GROUP_NAME_BY_ID = {}
try:
    for g in GROUPS:
        gid = str(g.get("id") or "").strip()
        nm  = str(g.get("name") or gid).strip()
        if gid:
            GROUP_NAME_BY_ID[gid] = nm
except Exception:
    pass

ALLOWED_STATUSES = {"member", "administrator", "creator"}  # dianggap lolos

# ===================== APP FACTORY =====================

def build_app() -> Application:
    return Application.builder().token(BOT_TOKEN).build()

# ===================== WEBAPP LAUNCH =====================

def _webapp_url_for(uid: int) -> str:
    # Prioritas WEBAPP_URL; fallback ke BASE_URL + query yang lama
    if WEBAPP_URL:
        # tambahkan uid & cache-buster sederhana
        sep = "&" if ("?" in WEBAPP_URL) else "?"
        return f"{WEBAPP_URL}{sep}uid={uid}&t={int(time.time())}"
    return f"{BASE_URL}/webapp/index.html?v=neon4&uid={uid}"

async def _send_webapp_button(chat_id: int, uid: int, context: ContextTypes.DEFAULT_TYPE):
    webapp_url = _webapp_url_for(uid)
    kb = [[KeyboardButton(text="🛍️ Buka Katalog", web_app=WebAppInfo(url=webapp_url))]]
    await context.bot.send_message(
        chat_id=chat_id,
        text="Pilih grup yang ingin kamu join, lanjutkan pembayaran QRIS, lalu bot akan kirimkan link undangannya.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

# ===================== MEMBERSHIP GATE =====================

async def _is_member(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: str) -> Optional[bool]:
    """
    True  -> user adalah member
    False -> user bukan member
    None  -> tidak bisa memeriksa (bot tak punya akses / chat invalid)
    """
    if not chat_id:
        return True
    try:
        cm = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return getattr(cm, "status", "") in ALLOWED_STATUSES
    except Forbidden:
        return None
    except BadRequest:
        return None
    except Exception:
        return None

def _join_button(label: str, invite: Optional[str], username: Optional[str]) -> InlineKeyboardButton:
    if invite:
        return InlineKeyboardButton(label, url=invite)
    if username:
        return InlineKeyboardButton(label, url=f"https://t.me/{username}")
    return InlineKeyboardButton(f"{label} (minta admin set link)", callback_data="noop")

def _gate_keyboard() -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    # tombol untuk semua grup
    for i, _ in enumerate(REQ_GROUP_IDS):
        inv = REQ_GROUP_INVITES[i] if i < len(REQ_GROUP_INVITES) else ""
        usr = REQ_GROUP_USERNAMES[i] if i < len(REQ_GROUP_USERNAMES) else ""
        rows.append([_join_button("Join Group", inv, usr)])
    # tombol untuk semua channel
    for i, _ in enumerate(REQ_CHANNEL_IDS):
        inv = REQ_CHANNEL_INVITES[i] if i < len(REQ_CHANNEL_INVITES) else ""
        usr = REQ_CHANNEL_USERNAMES[i] if i < len(REQ_CHANNEL_USERNAMES) else ""
        rows.append([_join_button("Subscribe Channel", inv, usr)])
    rows.append([InlineKeyboardButton("✅ Saya sudah join (Re-check)", callback_data="recheck_membership")])
    return InlineKeyboardMarkup(rows)

async def _count_memberships(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> Tuple[int, int, int, bool]:
    """
    Return (ok_count, total_checkable, total_required, any_cannot_check)
    """
    total_required = len(REQ_GROUP_IDS) + len(REQ_CHANNEL_IDS)
    ok_count = 0
    total_checkable = 0
    any_cannot_check = False

    for chat_id in REQ_GROUP_IDS:
        res = await _is_member(context, user_id, chat_id)
        if res is None:
            any_cannot_check = True
        else:
            total_checkable += 1
            if res: ok_count += 1

    for chat_id in REQ_CHANNEL_IDS:
        res = await _is_member(context, user_id, chat_id)
        if res is None:
            any_cannot_check = True
        else:
            total_checkable += 1
            if res: ok_count += 1

    return ok_count, total_checkable, total_required, any_cannot_check

def _is_pass(ok_count: int, total_required: int) -> bool:
    if total_required == 0:
        return True
    if REQ_MODE == "ALL":
        return ok_count >= total_required
    # ANY
    min_need = max(1, REQ_MIN_COUNT)
    if min_need > total_required:
        min_need = total_required
    return ok_count >= min_need

def _need_access_tips(any_cannot_check: bool) -> str:
    if not any_cannot_check:
        return ""
    tips = []
    if REQ_GROUP_IDS:
        tips.append("• Tambahkan bot ke semua GRUP wajib (minimal member).")
    if REQ_CHANNEL_IDS:
        tips.append("• Jadikan bot ADMIN di semua CHANNEL wajib.")
    return "\n\nBot belum bisa memeriksa salah satu/lebih chat:\n" + "\n".join(tips)

# ========== HANDLERS: /start + Re-check ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id

    # Jika tidak ada syarat gate sama sekali -> langsung buka Mini App
    if not REQ_GROUP_IDS and not REQ_CHANNEL_IDS:
        await _send_webapp_button(chat_id, uid, context)
        return

    ok_count, _, total_required, any_cannot_check = await _count_memberships(context, uid)
    passed = _is_pass(ok_count, total_required)

    if passed and not any_cannot_check:
        await _send_webapp_button(chat_id, uid, context)
        return

    # Belum lolos gate → kirim instruksi & tombol Join + Re-check
    lines = []
    if REQ_MODE == "ALL":
        lines.append(f"Kamu perlu join **semua** ({total_required}) grup/channel yang diwajibkan.")
    else:
        min_need = max(1, REQ_MIN_COUNT)
        if total_required and min_need > total_required: min_need = total_required
        lines.append(f"Kamu perlu join **minimal {min_need}** dari {total_required} grup/channel yang diwajibkan.")
    lines.append(f"Status terdeteksi: {ok_count}/{total_required} sudah join.")

    tips = _need_access_tips(any_cannot_check)
    text = "\n".join(lines) + (tips or "") + "\n\nSetelah join, klik Re-check di bawah."
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=_gate_keyboard())

async def on_recheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    chat_id = query.message.chat_id

    ok_count, _, total_required, any_cannot_check = await _count_memberships(context, uid)
    passed = _is_pass(ok_count, total_required)

    if passed and not any_cannot_check:
        await query.edit_message_text("✅ Terima kasih! Kamu sudah lolos verifikasi.")
        await _send_webapp_button(chat_id, uid, context)
    else:
        min_need_info = ""
        if REQ_MODE == "ANY":
            min_need_info = f"(minimal {max(1, min(REQ_MIN_COUNT, total_required))}) "
        tips = _need_access_tips(any_cannot_check)
        await query.edit_message_text(
            f"Belum memenuhi syarat {min_need_info}: {ok_count}/{total_required} terdeteksi join.{tips}\n\nSilakan lengkapi lalu Re-check lagi.",
            reply_markup=_gate_keyboard()
        )

# ===================== INVITE LINK (tetap kompatibel versi stabil) =====================

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

    # buat link sekali pakai (member_limit=1) + kedaluwarsa cepat (15 menit)
    expire_ts = int(time.time()) + 15 * 60

    link_obj = await _create_link_with_retry(
        app.bot,
        chat_id=group_id_norm,
        member_limit=1,
        expire_date=expire_ts,
        creates_join_request=False,
        name="Paid join",
    )

    invite_link_url: Optional[str] = None
    if link_obj and getattr(link_obj, "invite_link", None):
        invite_link_url = link_obj.invite_link
    else:
        # fallback: export (permanent) jika create gagal
        try:
            invite_link_url = await app.bot.export_chat_invite_link(chat_id=group_id_norm)
        except Exception as e:
            print(f"[invite] export_chat_invite_link failed for {group_id_str}:", e)

    if not invite_link_url:
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ Gagal membuat undangan untuk grup: {group_name}\n"
                     f"Pastikan bot adalah admin/diizinkan membuat link di grup tsb."
            )
        except Exception as e:
            print("[invite] notify user failed:", e)
        return

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

# ===================== REGISTER HANDLERS =====================

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_recheck, pattern="^recheck_membership$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
