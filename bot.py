import asyncio
import base64
import json
import logging
import math
import os
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
import requests
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_ID", "").split(",")
    if x.strip().isdigit()
]
REPO_OWNER = os.getenv("REPO_OWNER", "bdtvyz76b6-blip")
REPO_NAME = os.getenv("REPO_NAME", "kainkov")
BRANCH = os.getenv("BRANCH", "main")
SERVERS_FILE = os.getenv("SERVERS_FILE", "servers.txt")
NO_SERVERS_FILE = os.getenv("NO_SERVERS_FILE", "no_servers.txt")
USERS_DIR = os.getenv("USERS_DIR", "users")
REVENUE_FILE = os.getenv("REVENUE_FILE", "revenue.txt")
PROMOS_FILE = os.getenv("PROMOS_FILE", "promos.txt")
USERS_INFO_FILE = os.getenv("USERS_INFO_FILE", "users_info.json")
# ------------------------------------------------------------
# ВАЖНО:
# Это URL ПОДПИСКИ пользователя.
#
# Если у тебя для каждого пользователя отдельный GitHub-файл,
# оставь PUBLIC_SUB_TEMPLATE.
#
# Пример:
# https://raw.githubusercontent.com/bdtvyz76b6-blip/kainkov/main/users/paid_{user_id}.txt
# ------------------------------------------------------------
PUBLIC_SUB_TEMPLATE = os.getenv(
    "PUBLIC_SUB_TEMPLATE",
    "https://raw.githubusercontent.com/"
    "bdtvyz76b6-blip/kainkov/main/users/paid_{user_id}.txt"
)
SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    "your_support_username"
)
SERVICE_NAME = os.getenv(
    "SERVICE_NAME",
    "MAGNET.NET"
)
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "2"))
PRICES = {
    "1_month": 100,
    "4_months": 300,
    "8_months": 650,
}
DURATIONS = {
    "1_month": 30,
    "4_months": 120,
    "8_months": 240,
}
HAPP_CRYPTO_API = "https://crypto.happ.su/api-v2.php"
UTC = timezone.utc
# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)
# ============================================================
# TIME
# ============================================================
def now_utc() -> datetime:
    return datetime.now(UTC)
def unix_timestamp(dt: Optional[datetime]) -> int:
    if not dt:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())
def format_date(dt: Optional[datetime]) -> str:
    if not dt:
        return "нет"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.strftime("%d.%m.%Y")
# ============================================================
# GITHUB API
# ============================================================
def github_request(
    method: str,
    path: str,
    data: Optional[dict] = None
) -> Optional[dict]:
    url = (
        f"https://api.github.com/repos/"
        f"{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    )
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    try:
        if method == "GET":
            response = requests.get(
                url,
                headers=headers,
                timeout=20
            )
        elif method == "PUT":
            response = requests.put(
                url,
                headers=headers,
                json=data,
                timeout=20
            )
        elif method == "DELETE":
            response = requests.delete(
                url,
                headers=headers,
                json=data,
                timeout=20
            )
        else:
            return None
        if response.status_code == 404:
            return None
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()
    except Exception as e:
        logger.error("GitHub API error: %s", e)
        return None
def github_get_file(path: str) -> Optional[str]:
    data = github_request("GET", path)
    if not data:
        return None
    content = data.get("content")
    if not content:
        return None
    try:
        return base64.b64decode(
            content.replace("\n", "")
        ).decode("utf-8")
    except Exception as e:
        logger.error("GitHub decode error: %s", e)
        return None
def github_put_file(
    path: str,
    content: str,
    commit_msg: str
) -> bool:
    existing = github_request("GET", path)
    sha = None
    if existing:
        sha = existing.get("sha")
    payload = {
        "message": commit_msg,
        "content": base64.b64encode(
            content.encode("utf-8")
        ).decode("utf-8"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    result = github_request(
        "PUT",
        path,
        payload
    )
    return result is not None
def github_delete_file(
    path: str,
    commit_msg: str
) -> bool:
    existing = github_request("GET", path)
    if not existing:
        return True
    payload = {
        "message": commit_msg,
        "sha": existing["sha"],
        "branch": BRANCH,
    }
    result = github_request(
        "DELETE",
        path,
        payload
    )
    return result is not None
# ============================================================
# FILES
# ============================================================
def user_file(
    user_id: int,
    kind: str
) -> str:
    return f"{USERS_DIR}/{kind}_{user_id}.txt"
def read_servers(
    file_name: str
) -> list[str]:
    content = github_get_file(file_name)
    if not content:
        return []
    result = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        result.append(line)
    return result
# ============================================================
# SUBSCRIPTION
# ============================================================
def generate_subscription_content(
    servers: list[str],
    expire_date: Optional[datetime] = None
) -> str:
    expire_ts = unix_timestamp(expire_date)
    header = (
        f"#profile-title: {SERVICE_NAME}\n"
        "#profile-update-interval: 1\n"
        f"#subscription-userinfo: "
        f"upload=0; download=0; total=0; expire={expire_ts}\n"
        "#hide-settings: true\n"
        "#happ-hide-settings: true\n"
        "#hide_server_settings: true\n"
        "#hidesettings: true\n"
    )
    body = "\n".join(servers)
    if body:
        return header + "\n" + body
    return header
def parse_user_file(
    content: str
) -> Optional[dict]:
    if not content:
        return None
    servers = []
    expire_ts = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#subscription-userinfo:"):
            parts = line.split(";")
            for part in parts:
                part = part.strip()
                if part.startswith("expire="):
                    try:
                        expire_ts = int(
                            part.split("=", 1)[1]
                        )
                    except Exception:
                        pass
            continue
        if line.startswith("#"):
            continue
        servers.append(line)
    if expire_ts is None:
        return None
    expire_date = datetime.fromtimestamp(
        expire_ts,
        UTC
    )
    return {
        "servers": servers,
        "expire_date": expire_date
    }
# ============================================================
# SUBSCRIPTION CHECK
# ============================================================
async def expire_user_if_needed(
    user_id: int
):
    paid_path = user_file(user_id, "paid")
    content = github_get_file(paid_path)
    if not content:
        return
    parsed = parse_user_file(content)
    if not parsed:
        return
    expire = parsed["expire_date"]
    if expire <= now_utc():
        stub = read_servers(NO_SERVERS_FILE)
        new_content = generate_subscription_content(
            stub
        )
        github_put_file(
            paid_path,
            new_content,
            f"Expire subscription {user_id}"
        )
async def has_active_subscription(
    user_id: int
) -> bool:
    await expire_user_if_needed(user_id)
    content = github_get_file(
        user_file(user_id, "paid")
    )
    if not content:
        return False
    parsed = parse_user_file(content)
    if not parsed:
        return False
    return parsed["expire_date"] > now_utc()
def has_trial_used(
    user_id: int
) -> bool:
    return github_get_file(
        user_file(user_id, "trial")
    ) is not None
async def get_subscription(
    user_id: int
) -> Optional[dict]:
    await expire_user_if_needed(user_id)
    paid_content = github_get_file(
        user_file(user_id, "paid")
    )
    if paid_content:
        paid = parse_user_file(paid_content)
        if paid and paid["expire_date"] > now_utc():
            paid["kind"] = "paid"
            return paid
    trial_content = github_get_file(
        user_file(user_id, "trial")
    )
    if trial_content:
        trial = parse_user_file(trial_content)
        if trial and trial["expire_date"] > now_utc():
            trial["kind"] = "trial"
            return trial
    return None
# ============================================================
# HAPP CRYPT4
# ============================================================
def get_subscription_url(
    user_id: int,
    kind: str = "paid"
) -> str:
    if kind == "trial":
        return (
            f"https://raw.githubusercontent.com/"
            f"{REPO_OWNER}/{REPO_NAME}/{BRANCH}/"
            f"{USERS_DIR}/trial_{user_id}.txt"
        )
    return PUBLIC_SUB_TEMPLATE.format(
        user_id=user_id
    )
def generate_happ_crypt4(
    user_id: int,
    kind: str = "paid"
) -> Optional[str]:
    """
    REAL Happ crypt4.
    Мы НЕ кодируем содержимое файла в Base64.
    Happ crypt4 принимает зашифрованный URL подписки.
    Официальный API Happ:
    https://crypto.happ.su/api-v2.php
    """
    url = get_subscription_url(
        user_id,
        kind
    )
    try:
        response = requests.post(
            HAPP_CRYPTO_API,
            json={"url": url},
            headers={
                "Content-Type": "application/json"
            },
            timeout=20
        )
        response.raise_for_status()
        # API может вернуть JSON или обычный текст.
        try:
            data = response.json()
        except Exception:
            data = None
        if isinstance(data, dict):
            for key in (
                "url",
                "link",
                "result",
                "encrypted",
                "data",
                "encryptedContent"
            ):
                value = data.get(key)
                if isinstance(value, str):
                    if value.startswith("happ://"):
                        return value
                    return "happ://crypt4/" + value
        text = response.text.strip()
        if text:
            if text.startswith("happ://"):
                return text
            # Иногда API возвращает JSON-строку.
            if text.startswith('"'):
                try:
                    text = json.loads(text)
                except Exception:
                    pass
            if isinstance(text, str) and text:
                return "happ://crypt4/" + text
        logger.error(
            "Happ API returned unknown response: %s",
            response.text[:500]
        )
    except Exception as e:
        logger.error(
            "Happ crypt4 error: %s",
            e
        )
    return None
# ============================================================
# USERS INFO
# ============================================================
def load_users_info() -> dict:
    content = github_get_file(
        USERS_INFO_FILE
    )
    if not content:
        return {}
    try:
        return json.loads(content)
    except Exception:
        return {}
def save_users_info(
    info: dict
):
    github_put_file(
        USERS_INFO_FILE,
        json.dumps(
            info,
            ensure_ascii=False,
            indent=2
        ),
        "Update users info"
    )
def save_user_info(
    user_id: int,
    first_name: str = "",
    username: str = ""
):
    info = load_users_info()
    info[str(user_id)] = {
        "first_name": first_name,
        "username": username
    }
    save_users_info(info)
def get_user_meta(
    user_id: int
) -> dict:
    return load_users_info().get(
        str(user_id),
        {}
    )
# ============================================================
# USERS
# ============================================================
def get_all_user_ids() -> list[int]:
    url = (
        f"https://api.github.com/repos/"
        f"{REPO_OWNER}/{REPO_NAME}/git/trees/"
        f"{BRANCH}?recursive=1"
    )
    try:
        response = requests.get(
            url,
            headers={
                "Authorization":
                    f"Bearer {GITHUB_TOKEN}"
            },
            timeout=20
        )
        if response.status_code != 200:
            return []
        data = response.json()
    except Exception:
        return []
    ids = set()
    for item in data.get("tree", []):
        path = item.get("path", "")
        if not path.startswith(
            USERS_DIR + "/"
        ):
            continue
        filename = path.split("/")[-1]
        if filename.startswith("paid_"):
            try:
                ids.add(
                    int(filename[5:-4])
                )
            except Exception:
                pass
        elif filename.startswith("trial_"):
            try:
                ids.add(
                    int(filename[6:-4])
                )
            except Exception:
                pass
    info = load_users_info()
    for uid in info:
        try:
            ids.add(int(uid))
        except Exception:
            pass
    return sorted(ids)
def get_user(
    user_id: int
) -> Optional[dict]:
    meta = get_user_meta(user_id)
    blocked = bool(
        github_get_file(
            f"{USERS_DIR}/blocked_{user_id}.txt"
        )
    )
    paid = github_get_file(
        user_file(user_id, "paid")
    )
    trial = github_get_file(
        user_file(user_id, "trial")
    )
    subscription = None
    expire_date = None
    for content, kind in (
        (paid, "paid"),
        (trial, "trial")
    ):
        if not content:
            continue
        parsed = parse_user_file(content)
        if not parsed:
            continue
        if parsed["expire_date"] > now_utc():
            subscription = kind
            expire_date = parsed["expire_date"]
            break
    data = {
        "user_id": user_id,
        "blocked": blocked,
        "subscription": subscription,
        "expire_date": expire_date,
        "first_name": meta.get(
            "first_name",
            ""
        ),
        "username": meta.get(
            "username",
            ""
        )
    }
    if (
        subscription
        or blocked
        or data["first_name"]
        or data["username"]
    ):
        return data
    return None
# ============================================================
# ADMIN SUBSCRIPTION
# ============================================================
def extend_subscription(
    user_id: int,
    days: int
):
    paid_path = user_file(
        user_id,
        "paid"
    )
    current = github_get_file(
        paid_path
    )
    base = now_utc()
    if current:
        parsed = parse_user_file(
            current
        )
        if parsed:
            if parsed["expire_date"] > base:
                base = parsed["expire_date"]
    expire = base + timedelta(
        days=days
    )
    servers = read_servers(
        SERVERS_FILE
    )
    content = generate_subscription_content(
        servers,
        expire
    )
    github_put_file(
        paid_path,
        content,
        f"Extend subscription {user_id} +{days}"
    )
def revoke_subscription(
    user_id: int
):
    stub = read_servers(
        NO_SERVERS_FILE
    )
    content = generate_subscription_content(
        stub
    )
    github_put_file(
        user_file(user_id, "paid"),
        content,
        f"Revoke subscription {user_id}"
    )
def set_blocked(
    user_id: int,
    blocked: bool
):
    path = (
        f"{USERS_DIR}/blocked_{user_id}.txt"
    )
    if blocked:
        github_put_file(
            path,
            "blocked",
            f"Block user {user_id}"
        )
    else:
        github_delete_file(
            path,
            f"Unblock user {user_id}"
        )
# ============================================================
# PROMOS
# ============================================================
def get_all_promos() -> list[tuple[str, int]]:
    content = github_get_file(
        PROMOS_FILE
    )
    result = []
    if not content:
        return result
    for line in content.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            result.append(
                (
                    parts[0].upper(),
                    int(parts[1])
                )
            )
        except Exception:
            pass
    return result
def create_promo(
    code: str,
    days: int
) -> bool:
    code = code.upper()
    promos = get_all_promos()
    if any(
        existing == code
        for existing, _ in promos
    ):
        return False
    promos.append(
        (code, days)
    )
    content = "\n".join(
        f"{c} {d}"
        for c, d in promos
    )
    github_put_file(
        PROMOS_FILE,
        content,
        f"Create promo {code}"
    )
    return True
def get_promo(
    code: str
) -> Optional[int]:
    code = code.upper()
    for promo, days in get_all_promos():
        if promo == code:
            return days
    return None
def promo_used(
    user_id: int,
    code: str
) -> bool:
    path = (
        f"{USERS_DIR}/promo_"
        f"{user_id}_{code.upper()}.txt"
    )
    return github_get_file(path) is not None
def use_promo(
    user_id: int,
    code: str
) -> Optional[int]:
    code = code.upper()
    days = get_promo(code)
    if days is None:
        return None
    if promo_used(user_id, code):
        return 0
    github_put_file(
        f"{USERS_DIR}/promo_{user_id}_{code}.txt",
        "used",
        f"Promo {code} used by {user_id}"
    )
    return days
# ============================================================
# REVENUE
# ============================================================
def get_revenue() -> int:
    content = github_get_file(
        REVENUE_FILE
    )
    if not content:
        return 0
    try:
        return int(content.strip())
    except Exception:
        return 0
def update_revenue(
    amount: int
):
    total = get_revenue()
    total += amount
    github_put_file(
        REVENUE_FILE,
        str(total),
        "Update revenue"
    )
# ============================================================
# BOT
# ============================================================
bot = Bot(
    token=BOT_TOKEN
)
dp = Dispatcher()
admin_states = {}
def is_admin(
    user_id: int
) -> bool:
    return user_id in ADMIN_IDS
def is_blocked(
    user_id: int
) -> bool:
    return bool(
        github_get_file(
            f"{USERS_DIR}/blocked_{user_id}.txt"
        )
    )
# ============================================================
# KEYBOARDS
# ============================================================
def main_keyboard(
    user_id: int
):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🚀 Пробный период",
        callback_data="trial"
    )
    builder.button(
        text="💎 Купить подписку",
        callback_data="buy"
    )
    builder.button(
        text="📋 Моя подписка",
        callback_data="my_sub"
    )
    builder.button(
        text="🎟 Промокод",
        callback_data="promo"
    )
    builder.button(
        text="🆘 Поддержка",
        callback_data="support"
    )
    if is_admin(user_id):
        builder.button(
            text="🔐 Админ-панель",
            callback_data="admin"
        )
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()
def buy_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💎 1 месяц • 100⭐",
                    callback_data="buy_1_month"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 4 месяца • 300⭐",
                    callback_data="buy_4_months"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 8 месяцев • 650⭐",
                    callback_data="buy_8_months"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main"
                )
            ]
        ]
    )
def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main"
                )
            ]
        ]
    )
def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin:stats"
                ),
                InlineKeyboardButton(
                    text="👥 Пользователи",
                    callback_data="admin:users:0"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔎 Найти",
                    callback_data="admin:find"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Выдать",
                    callback_data="admin:give"
                ),
                InlineKeyboardButton(
                    text="🚫 Отозвать",
                    callback_data="admin:revoke"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⛔ Блокировки",
                    callback_data="admin:block"
                ),
                InlineKeyboardButton(
                    text="🎟 Промокоды",
                    callback_data="admin:promos"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Рассылка",
                    callback_data="admin:broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Обновить серверы",
                    callback_data="admin:sync"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main"
                )
            ]
        ]
    )
def admin_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Админ-панель",
                    callback_data="admin:menu"
                )
            ]
        ]
    )
# ============================================================
# START
# ============================================================
@dp.message(Command("start"))
async def start(
    message: Message
):
    user_id = message.from_user.id
    save_user_info(
        user_id,
        message.from_user.first_name or "",
        message.from_user.username or ""
    )
    if is_blocked(user_id):
        await message.answer(
            "⛔ <b>Доступ заблокирован.</b>\n\n"
            "Обратитесь в поддержку.",
            parse_mode="HTML"
        )
        return
    text = (
        f"☂️ <b>{SERVICE_NAME}</b>\n\n"
        "Добро пожаловать!\n\n"
        "🚀 Пробный период — "
        f"<b>{TRIAL_DAYS} дня</b>\n"
        "💎 Быстрые тарифы\n"
        "🔐 Защищённая ссылка Happ\n\n"
        "Выберите действие ниже:"
    )
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(user_id)
    )
# ============================================================
# TRIAL
# ============================================================
@dp.callback_query(F.data == "trial")
async def trial(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    await callback.answer()
    if is_blocked(user_id):
        await callback.message.edit_text(
            "⛔ Доступ заблокирован.",
            reply_markup=back_keyboard()
        )
        return
    if has_trial_used(user_id):
        await callback.message.edit_text(
            "❌ <b>Пробный период уже использован.</b>",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )
        return
    if await has_active_subscription(user_id):
        await callback.message.edit_text(
            "✅ У вас уже есть активная подписка.",
            reply_markup=back_keyboard()
        )
        return
    servers = read_servers(
        SERVERS_FILE
    )
    if not servers:
        await callback.message.edit_text(
            "⚠️ Серверы временно недоступны.",
            reply_markup=back_keyboard()
        )
        return
    expire = now_utc() + timedelta(
        days=TRIAL_DAYS
    )
    content = generate_subscription_content(
        servers,
        expire
    )
    success = github_put_file(
        user_file(user_id, "trial"),
        content,
        f"Trial for {user_id}"
    )
    if not success:
        await callback.message.edit_text(
            "❌ Не удалось создать подписку.",
            reply_markup=back_keyboard()
        )
        return
    happ = generate_happ_crypt4(
        user_id,
        "trial"
    )
    if happ:
        text = (
            "🎉 <b>Пробный период активирован!</b>\n\n"
            f"⏳ Срок: <b>{TRIAL_DAYS} дня</b>\n"
            f"📅 До: <b>{format_date(expire)}</b>\n\n"
            "🔐 <b>Happ crypt4:</b>\n"
            f"<code>{happ}</code>\n\n"
            "Нажмите ссылку и добавьте её в Happ."
        )
    else:
        text = (
            "🎉 <b>Пробный период активирован!</b>\n\n"
            f"📅 До: <b>{format_date(expire)}</b>\n\n"
            "⚠️ Crypt4 временно не удалось создать.\n"
            "Откройте «Моя подписка» позже."
        )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )
# ============================================================
# BUY
# ============================================================
@dp.callback_query(F.data == "buy")
async def buy(
    callback: CallbackQuery
):
    await callback.answer()
    await callback.message.edit_text(
        "💎 <b>Выберите тариф</b>\n\n"
        "Все тарифы оплачиваются Telegram Stars ⭐",
        parse_mode="HTML",
        reply_markup=buy_keyboard()
    )
@dp.callback_query(F.data.startswith("buy_"))
async def buy_tariff(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    if is_blocked(user_id):
        await callback.answer(
            "⛔ Доступ заблокирован.",
            show_alert=True
        )
        return
    tariff = callback.data[4:]
    if tariff not in PRICES:
        await callback.answer(
            "Неверный тариф.",
            show_alert=True
        )
        return
    await bot.send_invoice(
        chat_id=user_id,
        title=f"{SERVICE_NAME} • подписка",
        description=(
            f"Доступ на "
            f"{DURATIONS[tariff]} дней"
        ),
        payload=f"vpn_{tariff}",
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Подписка",
                amount=PRICES[tariff]
            )
        ],
        start_parameter="vpn_subscription"
    )
    await callback.answer()
# ============================================================
# PAYMENT
# ============================================================
@dp.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery
):
    await bot.answer_pre_checkout_query(
        query.id,
        ok=True
    )
@dp.message(F.successful_payment)
async def payment(
    message: Message
):
    user_id = message.from_user.id
    payment = message.successful_payment
    payload = payment.invoice_payload
    tariff = payload[4:]
    if tariff not in DURATIONS:
        await message.answer(
            "❌ Ошибка определения тарифа."
        )
        return
    days = DURATIONS[tariff]
    servers = read_servers(
        SERVERS_FILE
    )
    if not servers:
        await message.answer(
            "⚠️ Серверы временно недоступны."
        )
        return
    # --------------------------------------------------------
    # ВАЖНО:
    # если подписка уже есть, добавляем дни к ней.
    # --------------------------------------------------------
    current = github_get_file(
        user_file(user_id, "paid")
    )
    base = now_utc()
    if current:
        parsed = parse_user_file(
            current
        )
        if parsed and parsed["expire_date"] > base:
            base = parsed["expire_date"]
    expire = base + timedelta(
        days=days
    )
    content = generate_subscription_content(
        servers,
        expire
    )
    success = github_put_file(
        user_file(user_id, "paid"),
        content,
        f"Payment {user_id} {tariff}"
    )
    if not success:
        await message.answer(
            "❌ Не удалось создать подписку."
        )
        return
    update_revenue(
        PRICES[tariff]
    )
    save_user_info(
        user_id,
        message.from_user.first_name or "",
        message.from_user.username or ""
    )
    happ = generate_happ_crypt4(
        user_id,
        "paid"
    )
    text = (
        "✅ <b>Оплата прошла успешно!</b>\n\n"
        f"💎 Тариф: <b>{tariff.replace('_', ' ')}</b>\n"
        f"⏳ Добавлено: <b>{days} дней</b>\n"
        f"📅 Действует до: <b>{format_date(expire)}</b>\n\n"
    )
    if happ:
        text += (
            "🔐 <b>Happ crypt4:</b>\n"
            f"<code>{happ}</code>\n\n"
            "Скопируйте ссылку и добавьте её в Happ."
        )
    else:
        text += (
            "⚠️ Crypt4 сейчас не удалось создать.\n"
            "Зайдите в «Моя подписка» позже."
        )
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(user_id)
    )
# ============================================================
# MY SUB
# ============================================================
@dp.callback_query(F.data == "my_sub")
async def my_subscription(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    await callback.answer()
    if is_blocked(user_id):
        await callback.message.edit_text(
            "⛔ Доступ заблокирован.",
            reply_markup=back_keyboard()
        )
        return
    info = await get_subscription(
        user_id
    )
    if not info:
        await callback.message.edit_text(
            "📋 <b>Моя подписка</b>\n\n"
            "❌ Активной подписки нет.\n\n"
            "Выберите «Купить подписку» "
            "или получите пробный период.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💎 Купить",
                            callback_data="buy"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🚀 Пробный период",
                            callback_data="trial"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data="back_main"
                        )
                    ]
                ]
            )
        )
        return
    kind = info["kind"]
    expire = info["expire_date"]
    happ = generate_happ_crypt4(
        user_id,
        kind
    )
    if happ:
        crypt_text = (
            f"<code>{happ}</code>"
        )
    else:
        crypt_text = (
            "⚠️ Не удалось получить crypt4.\n"
            "Нажмите «Обновить ссылку»."
        )
    text = (
        "📋 <b>Моя подписка</b>\n\n"
        f"☂️ Сервис: <b>{SERVICE_NAME}</b>\n"
        f"📦 Тип: <b>{'Платная' if kind == 'paid' else 'Пробная'}</b>\n"
        f"📅 Действует до: <b>{format_date(expire)}</b>\n\n"
        "🔐 <b>Happ crypt4:</b>\n"
        f"{crypt_text}\n\n"
        "Ссылка скрывает адрес подписки "
        "от пользователя внутри Happ."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить crypt4",
                    callback_data="refresh_crypt4"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Продлить",
                    callback_data="buy"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main"
                )
            ]
        ]
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )
@dp.callback_query(F.data == "refresh_crypt4")
async def refresh_crypt4(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    await callback.answer(
        "🔄 Создаю новую ссылку..."
    )
    info = await get_subscription(
        user_id
    )
    if not info:
        await callback.message.edit_text(
            "❌ Активной подписки нет.",
            reply_markup=back_keyboard()
        )
        return
    happ = generate_happ_crypt4(
        user_id,
        info["kind"]
    )
    if not happ:
        await callback.message.edit_text(
            "❌ Happ crypt4 временно недоступен.",
            reply_markup=back_keyboard()
        )
        return
    await callback.message.edit_text(
        "🔐 <b>Новая Happ crypt4 ссылка</b>\n\n"
        f"<code>{happ}</code>\n\n"
        "Добавьте её в Happ.",
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )
# ============================================================
# PROMO USER
# ============================================================
@dp.callback_query(F.data == "promo")
async def promo_start(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    await callback.answer()
    admin_states[user_id] = {
        "action": "user_promo"
    }
    await callback.message.edit_text(
        "🎟 <b>Промокод</b>\n\n"
        "Отправьте промокод сообщением.",
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )
# ============================================================
# SUPPORT
# ============================================================
@dp.callback_query(F.data == "support")
async def support(
    callback: CallbackQuery
):
    await callback.answer()
    await callback.message.edit_text(
        "🆘 <b>Поддержка</b>\n\n"
        f"По всем вопросам: @{SUPPORT_USERNAME}",
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )
# ============================================================
# BACK
# ============================================================
@dp.callback_query(F.data == "back_main")
async def back_main(
    callback: CallbackQuery
):
    await callback.answer()
    await callback.message.edit_text(
        f"☂️ <b>{SERVICE_NAME}</b>\n\n"
        "Главное меню:",
        parse_mode="HTML",
        reply_markup=main_keyboard(
            callback.from_user.id
        )
    )
# ============================================================
# ADMIN
# ============================================================
@dp.callback_query(F.data == "admin")
async def admin(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )
        return
    await callback.answer()
    await callback.message.edit_text(
        "🔐 <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )
@dp.callback_query(F.data == "admin:menu")
async def admin_menu(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    await callback.answer()
    await callback.message.edit_text(
        "🔐 <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )
# ============================================================
# ADMIN STATS
# ============================================================
@dp.callback_query(F.data == "admin:stats")
async def admin_stats(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    users = get_all_user_ids()
    active = 0
    for uid in users:
        if await get_subscription(uid):
            active += 1
    revenue = get_revenue()
    servers = len(
        read_servers(SERVERS_FILE)
    )
    await callback.answer()
    await callback.message.edit_text(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{len(users)}</b>\n"
        f"🟢 Активных: <b>{active}</b>\n"
        f"⭐ Stars: <b>{revenue}</b>\n"
        f"🌐 Серверов: <b>{servers}</b>",
        parse_mode="HTML",
        reply_markup=admin_back_keyboard()
    )
# ============================================================
# ADMIN USERS
# ============================================================
@dp.callback_query(F.data.startswith("admin:users:"))
async def admin_users(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    page = int(
        callback.data.split(":")[-1]
    )
    users = get_all_user_ids()
    per_page = 8
    pages = max(
        1,
        math.ceil(
            len(users) / per_page
        )
    )
    page = min(
        page,
        pages - 1
    )
    current = users[
        page * per_page:
        (page + 1) * per_page
    ]
    rows = []
    for uid in current:
        user = get_user(uid)
        if not user:
            continue
        status = (
            "🟢"
            if user["subscription"]
            else "🔴"
        )
        name = (
            user["first_name"]
            or user["username"]
            or str(uid)
        )
        if len(name) > 25:
            name = name[:22] + "..."
        rows.append([
            InlineKeyboardButton(
                text=f"{status} {name}",
                callback_data=f"admin:user:{uid}"
            )
        ])
    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"admin:users:{page-1}"
            )
        )
    navigation.append(
        InlineKeyboardButton(
            text=f"{page+1}/{pages}",
            callback_data="admin:noop"
        )
    )
    if page < pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"admin:users:{page+1}"
            )
        )
    rows.append(navigation)
    rows.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="admin:menu"
        )
    ])
    await callback.answer()
    await callback.message.edit_text(
        f"👥 <b>Пользователи</b>\n\n"
        f"Всего: <b>{len(users)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        )
    )
# ============================================================
# ADMIN USER
# ============================================================
@dp.callback_query(F.data.startswith("admin:user:"))
async def admin_user(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    uid = int(
        callback.data.split(":")[-1]
    )
    user = get_user(uid)
    if not user:
        await callback.answer(
            "Пользователь не найден.",
            show_alert=True
        )
        return
    name = user["first_name"] or "нет"
    username = user["username"]
    username_text = (
        f"@{username}"
        if username
        else "нет"
    )
    status = (
        "⛔ Заблокирован"
        if user["blocked"]
        else (
            "🟢 Активен"
            if user["subscription"]
            else "🔴 Неактивен"
        )
    )
    text = (
        f"👤 <b>Пользователь</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Имя: <b>{name}</b>\n"
        f"🔗 Username: {username_text}\n"
        f"📊 Статус: <b>{status}</b>\n"
        f"📦 Подписка: "
        f"<b>{user['subscription'] or 'нет'}</b>\n"
        f"📅 До: "
        f"<b>{format_date(user['expire_date'])}</b>"
    )
    block_button = (
        "🔓 Разблокировать"
        if user["blocked"]
        else "⛔ Заблокировать"
    )
    block_callback = (
        f"admin:unblock:{uid}"
        if user["blocked"]
        else f"admin:block_user:{uid}"
    )
    rows = [
        [
            InlineKeyboardButton(
                text="➕ 30 дней",
                callback_data=f"admin:add:{uid}:30"
            ),
            InlineKeyboardButton(
                text="➕ 90 дней",
                callback_data=f"admin:add:{uid}:90"
            )
        ],
        [
            InlineKeyboardButton(
                text="➕ 180 дней",
                callback_data=f"admin:add:{uid}:180"
            ),
            InlineKeyboardButton(
                text="➕ 365 дней",
                callback_data=f"admin:add:{uid}:365"
            )
        ],
        [
            InlineKeyboardButton(
                text="🚫 Отозвать",
                callback_data=f"admin:revoke_user:{uid}"
            )
        ],
        [
            InlineKeyboardButton(
                text=block_button,
                callback_data=block_callback
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Пользователи",
                callback_data="admin:users:0"
            )
        ]
    ]
    await callback.answer()
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        )
    )
# ============================================================
# ADMIN ACTIONS
# ============================================================
@dp.callback_query(F.data.startswith("admin:add:"))
async def admin_add(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    parts = callback.data.split(":")
    uid = int(parts[2])
    days = int(parts[3])
    extend_subscription(
        uid,
        days
    )
    await callback.answer(
        f"✅ +{days} дней",
        show_alert=True
    )
    # Открываем карточку пользователя
    callback.data = f"admin:user:{uid}"
    await admin_user(callback)
@dp.callback_query(F.data.startswith("admin:revoke_user:"))
async def admin_revoke_user(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    uid = int(
        callback.data.split(":")[-1]
    )
    revoke_subscription(uid)
    await callback.answer(
        "🚫 Подписка отозвана.",
        show_alert=True
    )
    callback.data = f"admin:user:{uid}"
    await admin_user(callback)
@dp.callback_query(F.data.startswith("admin:block_user:"))
async def admin_block_user(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    uid = int(
        callback.data.split(":")[-1]
    )
    set_blocked(
        uid,
        True
    )
    await callback.answer(
        "⛔ Пользователь заблокирован.",
        show_alert=True
    )
    callback.data = f"admin:user:{uid}"
    await admin_user(callback)
@dp.callback_query(F.data.startswith("admin:unblock:"))
async def admin_unblock(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    uid = int(
        callback.data.split(":")[-1]
    )
    set_blocked(
        uid,
        False
    )
    await callback.answer(
        "🔓 Пользователь разблокирован.",
        show_alert=True
    )
    callback.data = f"admin:user:{uid}"
    await admin_user(callback)
# ============================================================
# ADMIN FIND
# ============================================================
@dp.callback_query(F.data == "admin:find")
async def admin_find(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = {
        "action": "find"
    }
    await callback.answer()
    await callback.message.edit_text(
        "🔎 <b>Поиск пользователя</b>\n\n"
        "Отправьте Telegram ID.",
        parse_mode="HTML",
        reply_markup=admin_back_keyboard()
    )
# ============================================================
# ADMIN GIVE
# ============================================================
@dp.callback_query(F.data == "admin:give")
async def admin_give(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = {
        "action": "give"
    }
    await callback.answer()
    await callback.message.edit_text(
        "➕ <b>Выдать подписку</b>\n\n"
        "Формат:\n"
        "<code>ID ДНИ</code>\n\n"
        "Пример:\n"
        "<code>123456789 30</code>",
        parse_mode="HTML",
        reply_markup=admin_back_keyboard()
    )
# ============================================================
# ADMIN REVOKE
# ============================================================
@dp.callback_query(F.data == "admin:revoke")
async def admin_revoke(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = {
        "action": "revoke"
    }
    await callback.answer()
    await callback.message.edit_text(
        "🚫 <b>Отозвать подписку</b>\n\n"
        "Отправьте Telegram ID.",
        parse_mode="HTML",
        reply_markup=admin_back_keyboard()
    )
# ============================================================
# ADMIN BLOCK
# ============================================================
@dp.callback_query(F.data == "admin:block")
async def admin_block(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = {
        "action": "block"
    }
    await callback.answer()
    await callback.message.edit_text(
        "⛔ <b>Блокировка</b>\n\n"
        "Формат:\n"
        "<code>ID on</code>\n"
        "<code>ID off</code>",
        parse_mode="HTML",
        reply_markup=admin_back_keyboard()
    )
# ============================================================
# ADMIN PROMOS
# ============================================================
@dp.callback_query(F.data == "admin:promos")
async def admin_promos(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    promos = get_all_promos()
    if promos:
        lines = [
            f"🎟 <code>{code}</code> — {days} дней"
            for code, days in promos
        ]
        text = (
            "🎟 <b>Промокоды</b>\n\n"
            + "\n".join(lines)
        )
    else:
        text = (
            "🎟 <b>Промокоды</b>\n\n"
            "Промокодов пока нет."
        )
    await callback.answer()
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="➕ Создать",
                        callback_data="admin:create_promo"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="admin:menu"
                    )
                ]
            ]
        )
    )
@dp.callback_query(F.data == "admin:create_promo")
async def admin_create_promo(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = {
        "action": "promo"
    }
    await callback.answer()
    await callback.message.edit_text(
        "🎟 <b>Создание промокода</b>\n\n"
        "Формат:\n"
        "<code>MAGNIT30 30</code>",
        parse_mode="HTML",
        reply_markup=admin_back_keyboard()
    )
# ============================================================
# ADMIN BROADCAST
# ============================================================
@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = {
        "action": "broadcast"
    }
    await callback.answer()
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Отправьте текст сообщения.",
        parse_mode="HTML",
        reply_markup=admin_back_keyboard()
    )
# ============================================================
# ADMIN SYNC
# ============================================================
@dp.callback_query(F.data == "admin:sync")
async def admin_sync(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    await callback.answer(
        "🔄 Синхронизация..."
    )
    users = get_all_user_ids()
    expired = 0
    for uid in users:
        before = github_get_file(
            user_file(uid, "paid")
        )
        if before:
            parsed = parse_user_file(
                before
            )
            if (
                parsed
                and parsed["expire_date"] <= now_utc()
            ):
                await expire_user_if_needed(uid)
                expired += 1
    await callback.message.edit_text(
        "🔄 <b>Синхронизация завершена</b>\n\n"
        f"👥 Проверено: <b>{len(users)}</b>\n"
        f"🔴 Истёкших обработано: <b>{expired}</b>",
        parse_mode="HTML",
        reply_markup=admin_back_keyboard()
    )
@dp.callback_query(F.data == "admin:noop")
async def admin_noop(
    callback: CallbackQuery
):
    await callback.answer()
# ============================================================
# TEXT STATES
# ============================================================
@dp.message()
async def text_handler(
    message: Message
):
    user_id = message.from_user.id
    state = admin_states.get(
        user_id
    )
    if not state:
        return
    text = (
        message.text or ""
    ).strip()
    action = state["action"]
    # --------------------------------------------------------
    # USER PROMO
    # --------------------------------------------------------
    if action == "user_promo":
        admin_states.pop(
            user_id,
            None
        )
        code = text.upper()
        days = use_promo(
            user_id,
            code
        )
        if days is None:
            await message.answer(
                "❌ Промокод не найден.",
                reply_markup=main_keyboard(user_id)
            )
            return
        if days == 0:
            await message.answer(
                "❌ Вы уже использовали этот промокод.",
                reply_markup=main_keyboard(user_id)
            )
            return
        extend_subscription(
            user_id,
            days
        )
        await message.answer(
            "🎉 <b>Промокод активирован!</b>\n\n"
            f"➕ Добавлено: <b>{days} дней</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard(user_id)
        )
        return
    # --------------------------------------------------------
    # ADMIN ONLY
    # --------------------------------------------------------
    if not is_admin(user_id):
        return
    # --------------------------------------------------------
    # FIND
    # --------------------------------------------------------
    if action == "find":
        admin_states.pop(
            user_id,
            None
        )
        try:
            uid = int(text)
        except Exception:
            await message.answer(
                "❌ Некорректный ID.",
                reply_markup=admin_keyboard()
            )
            return
        user = get_user(uid)
        if not user:
            await message.answer(
                "❌ Пользователь не найден.",
                reply_markup=admin_keyboard()
            )
            return
        name = (
            user["first_name"]
            or "нет"
        )
        username = (
            "@" + user["username"]
            if user["username"]
            else "нет"
        )
        await message.answer(
            "👤 <b>Пользователь</b>\n\n"
            f"🆔 <code>{uid}</code>\n"
            f"👤 {name}\n"
            f"🔗 {username}\n"
            f"📦 {user['subscription'] or 'нет'}\n"
            f"📅 {format_date(user['expire_date'])}\n"
            f"📊 {'⛔ Заблокирован' if user['blocked'] else '🟢 Активен'}",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
        return
    # --------------------------------------------------------
    # GIVE
    # --------------------------------------------------------
    if action == "give":
        parts = text.split()
        if len(parts) != 2:
            await message.answer(
                "❌ Формат: ID ДНИ"
            )
            return
        try:
            uid = int(parts[0])
            days = int(parts[1])
        except Exception:
            await message.answer(
                "❌ ID и дни должны быть числами."
            )
            return
        extend_subscription(
            uid,
            days
        )
        admin_states.pop(
            user_id,
            None
        )
        await message.answer(
            f"✅ Пользователю "
            f"<code>{uid}</code> выдано "
            f"<b>{days} дней</b>.",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
        return
    # --------------------------------------------------------
    # REVOKE
    # --------------------------------------------------------
    if action == "revoke":
        try:
            uid = int(text)
        except Exception:
            await message.answer(
                "❌ Некорректный ID."
            )
            return
        revoke_subscription(uid)
        admin_states.pop(
            user_id,
            None
        )
        await message.answer(
            f"🚫 Подписка "
            f"<code>{uid}</code> отозвана.",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
        return
    # --------------------------------------------------------
    # BLOCK
    # --------------------------------------------------------
    if action == "block":
        parts = text.split()
        if len(parts) != 2:
            await message.answer(
                "❌ Формат: ID on/off"
            )
            return
        try:
            uid = int(parts[0])
        except Exception:
            await message.answer(
                "❌ Некорректный ID."
            )
            return
        mode = parts[1].lower()
        if mode not in (
            "on",
            "off"
        ):
            await message.answer(
                "❌ Используйте on или off."
            )
            return
        set_blocked(
            uid,
            mode == "on"
        )
        admin_states.pop(
            user_id,
            None
        )
        await message.answer(
            "⛔ Заблокирован."
            if mode == "on"
            else "🔓 Разблокирован.",
            reply_markup=admin_keyboard()
        )
        return
    # --------------------------------------------------------
    # PROMO
    # --------------------------------------------------------
    if action == "promo":
        parts = text.split()
        if len(parts) != 2:
            await message.answer(
                "❌ Формат: КОД ДНИ"
            )
            return
        code = parts[0].upper()
        try:
            days = int(parts[1])
        except Exception:
            await message.answer(
                "❌ Дни должны быть числом."
            )
            return
        if days <= 0:
            await message.answer(
                "❌ Дни должны быть больше 0."
            )
            return
        if create_promo(
            code,
            days
        ):
            answer = (
                "✅ Промокод "
                f"<code>{code}</code> создан.\n"
                f"Дней: <b>{days}</b>"
            )
        else:
            answer = (
                "❌ Такой промокод уже существует."
            )
        admin_states.pop(
            user_id,
            None
        )
        await message.answer(
            answer,
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
        return
    # --------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------
    if action == "broadcast":
        admin_states.pop(
            user_id,
            None
        )
        users = get_all_user_ids()
        await message.answer(
            f"📢 Рассылка для "
            f"<b>{len(users)}</b> пользователей...",
            parse_mode="HTML"
        )
        sent = 0
        failed = 0
        for uid in users:
            try:
                if is_blocked(uid):
                    continue
                await bot.send_message(
                    uid,
                    text
                )
                sent += 1
                await asyncio.sleep(
                    0.05
                )
            except Exception:
                failed += 1
        await message.answer(
            "📢 <b>Рассылка завершена</b>\n\n"
            f"✅ Отправлено: <b>{sent}</b>\n"
            f"❌ Ошибок: <b>{failed}</b>",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )
# ============================================================
# HEALTH SERVER
# ============================================================
class HealthHandler(
    BaseHTTPRequestHandler
):
    def do_GET(self):
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )
        self.end_headers()
        self.wfile.write(
            b"OK"
        )
    def log_message(
        self,
        format,
        *args
    ):
        return
def run_health_server():
    port = int(
        os.getenv(
            "PORT",
            "8080"
        )
    )
    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )
    logger.info(
        "Health server started on port %s",
        port
    )
    server.serve_forever()
# ============================================================
# INIT
# ============================================================
def init_github_files():
    defaults = {
        SERVERS_FILE:
            "# Рабочие серверы",
        NO_SERVERS_FILE:
            "# Подписка истекла",
        REVENUE_FILE:
            "0",
        PROMOS_FILE:
            "",
        USERS_INFO_FILE:
            "{}"
    }
    for path, content in defaults.items():
        if github_get_file(path) is None:
            github_put_file(
                path,
                content,
                f"Initialize {path}"
            )
# ============================================================
# MAIN
# ============================================================
async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не задан."
        )
    if not GITHUB_TOKEN:
        raise RuntimeError(
            "GITHUB_TOKEN не задан."
        )
    init_github_files()
    threading.Thread(
        target=run_health_server,
        daemon=True
    ).start()
    await bot.delete_webhook(
        drop_pending_updates=True
    )
    logger.info(
        "Bot started"
    )
    await dp.start_polling(
        bot
    )
if __name__ == "__main__":
    asyncio.run(
        main()
    )