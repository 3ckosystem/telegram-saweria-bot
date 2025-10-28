# app/bot.py
from __future__ import annotations
import os
from typing import List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.error import Forbidden, BadRequest

WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()

def _split_env(name: str) -> List[str]:
    val = os.getenv(name, "") or ""
    items = [x.strip() for x in val.split(",") if x.strip()]
    return items

# Ambil list ID (string, termasuk tanda -100...)
REQ_GROUP_IDS: List[str] = _split_env("REQUIRED_GROUP_IDS")
REQ_CHANNEL_IDS: List[str] = _split_env("REQUIRED_CHANNEL_IDS")

# Link/username untuk tombol (opsional) — harus sejajar urutannya
REQ_GROUP_INVITES: List[str] = _split_env("REQUIRED_GROUP_INVITES")
REQ_CHANNEL_INVITES: List[str] = _split_env("REQUIRED_CHANNEL_INVITES")
REQ_GROUP_USERNAMES: List[str] = _split_env("REQUIRED_GROUP_USERNAMES")
REQ_CHANNEL_USERNAMES: List[str] = _split_env("REQUIRED_CHANNEL_USERNAMES")

REQ_MODE = (os.getenv("REQUIRED_MODE", "ALL") or "ALL").upper()  # ALL | ANY
try:
    REQ_MIN_COUNT = int(os.getenv("REQUIRED_MIN_COUNT", "1"))
except ValueError:
    REQ_MIN_COUNT = 1

ALLOWED_STATUSES = {"member", "administrator", "creator"}

async def _is_member(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: str) -> Optional[bool]:
    """
    True  -> user adalah member
    False -> user bukan member
    None  -> tidak bisa memeriksa (bot tak punya akses / chat tidak valid)
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

    # Buat tombol untuk semua grup
    for i, _ in enumerate(REQ_GROUP_IDS):
        invite = REQ_GROUP_INVITES[i] if i < len(REQ_GROUP_INVITES) else ""
        uname  = REQ_GROUP_USERNAMES[i] if i < len(REQ_GROUP_USERNAMES) else ""
        rows.append([_join_button("Join Group", invite, uname)])

    # Buat tombol untuk semua channel
    for i, _ in enumerate(REQ_CHANNEL_IDS):
        invite = REQ_CHANNEL_INVITES[i] if i < len(REQ_CHANNEL_INVITES) else ""
        uname  = REQ_CHANNEL_USERNAMES[i] if i < len(REQ_CHANNEL_USERNAMES) else ""
        rows.append([_join_button("Subscribe Channel", invite, uname)])

    rows.append([InlineKeyboardButton("✅ Saya sudah join (Re-check)", callback_data="recheck_membership")])
    return InlineKeyboardMarkup(rows)

async def _count_memberships(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> tuple[int, int, int, bool]:
    """
    Return (ok_count, total_checkable, total_required, any_cannot_check)
    - ok_count: berapa chat yang user memang terdeteksi join
    - total_checkable: berapa chat yang berhasil dicek (tidak None)
    - total_required: total item (grup+channel) yang dicantumkan
    - any_cannot_check: True jika ada yang None (bot tak bisa cek)
    """
    total_required = len(REQ_GROUP_IDS) + len(REQ_CHANNEL_IDS)
    ok_count = 0
    total_checkable = 0
    any_cannot_check = False

    # Cek semua grup
    for chat_id in REQ_GROUP_IDS:
        res = await _is_member(context, user_id, chat_id)
        if res is None:
            any_cannot_check = True
        else:
            total_checkable += 1
            if res: ok_count += 1

    # Cek semua channel
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
        return True  # tidak ada syarat
    if REQ_MODE == "ALL":
        return ok_count >= total_required
    # ANY mode
    min_need = max(1, REQ_MIN_COUNT)
    # Boleh juga: min_need tidak boleh > total_required
    if min_need > total_required:
        min_need = total_required
    return ok_count >= min_need

async def _open_webapp(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    if WEBAPP_URL:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Buka Mini App untuk memilih grup & checkout:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🛍️ Buka Mini App", web_app=WebAppInfo(url=WEBAPP_URL))]]
            ),
        )
    else:
        await context.bot.send_message(chat_id=chat_id, text="WEBAPP_URL belum diset di .env")

def _need_access_tips(any_cannot_check: bool) -> str:
    if not any_cannot_check:
        return ""
    tips = []
    if REQ_GROUP_IDS:
        tips.append("• Tambahkan bot ke semua GRUP yang diwajibkan (minimal sebagai member).")
    if REQ_CHANNEL_IDS:
        tips.append("• Jadikan bot ADMIN di semua CHANNEL yang diwajibkan.")
    return "\n\nBot belum bisa memeriksa salah satu/lebih chat:\n" + "\n".join(tips)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    ok_count, total_checkable, total_required, any_cannot_check = await _count_memberships(context, user.id)
    passed = _is_pass(ok_count, total_required)

    if passed and not any_cannot_check:
        await _open_webapp(chat_id, context)
        return

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
    user = query.from_user
    chat_id = query.message.chat_id

    ok_count, _, total_required, any_cannot_check = await _count_memberships(context, user.id)
    passed = _is_pass(ok_count, total_required)

    if passed and not any_cannot_check:
        await query.edit_message_text("✅ Terima kasih! Kamu sudah lolos verifikasi.")
        await _open_webapp(chat_id, context)
    else:
        min_need_info = ""
        if REQ_MODE == "ANY":
            min_need_info = f"(minimal {max(1, min(REQ_MIN_COUNT, total_required))}) "
        tips = _need_access_tips(any_cannot_check)
        await query.edit_message_text(
            f"Belum memenuhi syarat {min_need_info}: {ok_count}/{total_required} terdeteksi join.{tips}\n\nSilakan lengkapi lalu Re-check lagi.",
            reply_markup=_gate_keyboard()
        )

def register_gate_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_recheck, pattern="^recheck_membership$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
