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
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
from dotenv import load_dotenv
load_dotenv()
# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_ID", "").split(",")
    if x.strip().isdigit()
}
REPO_OWNER = os.getenv(
    "REPO_OWNER",
    "bdtvyz76b6-blip",
)
REPO_NAME = os.getenv(
    "REPO_NAME",
    "kainkov",
)
REPO_BRANCH = os.getenv(
    "REPO_BRANCH",
    "main",
)
PUBLIC_SUB_TEMPLATE = os.getenv(
    "PUBLIC_SUB_TEMPLATE",
    "https://raw.githubusercontent.com/"
    "bdtvyz76b6-blip/kainkov/main/"
    "users/paid_{user_id}.txt",
)
SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    "@magnitsub",
).strip()
SERVICE_NAME = os.getenv(
    "SERVICE_NAME",
    "MAGNET.NET",
)
TRIAL_DAYS = int(
    os.getenv("TRIAL_DAYS", "2")
)
# Telegram Stars
PRICES = {
    30: 100,
    120: 300,
    240: 650,
}
DURATIONS = {
    100: 30,
    300: 120,
    650: 240,
}
UTC = timezone.utc
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)
# ============================================================
# HAPP CRYPT4
# ============================================================
# RSA-4096 public key used by the legacy Happ crypt4 format.
HAPP_CRYPT4_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAlBetA0wjbaj+h7oJ/d/h
pNrXvAcuhOdFGEFcfCxSWyLzWk4SAQ05gtaEGZyetTax2uqagi9HT6lapUSUe2S8
nMLJf5K+LEs9TYrhhBdx/B0BGahA+lPJa7nUwp7WfUmSF4hir+xka5ApHjzkAQn6
cdG6FKtSPgq1rYRPd1jRf2maEHwiP/e/jqdXLPP0SFBjWTMt/joUDgE7v/IGGB0L
Q7mGPAlgmxUHVqP4bJnZ//5sNLxWMjtYHOYjaV+lixNSfhFM3MdBndjpkmgSfmg
D5uYQYDL29TDk6Eu+xetUEqry8ySPjUbNWdDXCglQWMxDGjaqYXMWgxBA1UKjUBW
wbgr5yKTJ7mTqhlYEC9D5V/LOnKd6pTSvaMxkHXwk8hBWvUNWAxzAf5JZ7EVE3jt
0j682+/hnmL/hymUE44yMG1gCcWvSpB3BTlKoMnl4yrTakmdkbASeFRkN3iMRewa
IenvMhzJh1fq7xwX94otdd5eLB2vRFavrnhOcN2JJAkKTnx9dwQwFpGEkg+8U613
+Tfm/f82l56fFeoFN98dD2mUFLFZoeJ5CG81ZeXrH83niI0joX7rtoAZIPWzqY1
Zb/Zq+kK2hSIhphY172Uvs8X2Qp2ac9UoTPM71tURsA9IvPNvUwSIo/aKlX5KE3I
VE0tje7twWXL5Gb1sfcXRzsCAwEAAQ==
-----END PUBLIC KEY-----"""
# ============================================================
# GITHUB
# ============================================================
GITHUB_API = (
    f"https://api.github.com/repos/"
    f"{REPO_OWNER}/{REPO_NAME}/contents"
)
def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
def github_request(
    method: str,
    path: str,
    **kwargs,
):
    url = f"{GITHUB_API}/{path.lstrip('/')}"
    kwargs.setdefault("headers", github_headers())
    kwargs.setdefault("timeout", 20)
    response = requests.request(
        method,
        url,
        **kwargs,
    )
    return response
def github_get_file(path: str):
    response = github_request(
        "GET",
        path,
        params={"ref": REPO_BRANCH},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    content = data.get("content", "")
    sha = data.get("sha")
    if content:
        content = (
            base64.b64decode(
                content.replace("\n", "")
            )
            .decode("utf-8")
        )
    return {
        "content": content,
        "sha": sha,
    }
def github_put_file(
    path: str,
    content: str,
    message: str,
    sha: Optional[str] = None,
):
    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("utf-8")
    payload = {
        "message": message,
        "content": encoded,
        "branch": REPO_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    response = github_request(
        "PUT",
        path,
        json=payload,
    )
    response.raise_for_status()
    return response.json()
def github_delete_file(
    path: str,
    message: str,
):
    current = github_get_file(path)
    if not current:
        return False
    response = github_request(
        "DELETE",
        path,
        json={
            "message": message,
            "sha": current["sha"],
            "branch": REPO_BRANCH,
        },
    )
    response.raise_for_status()
    return True
# ============================================================
# FILES
# ============================================================
def user_file(
    user_id: int,
    kind: str = "paid",
):
    return f"users/{kind}_{user_id}.txt"
def read_servers():
    active = github_get_file("servers.txt")
    if not active:
        return ""
    return active["content"].strip()
def read_no_servers():
    inactive = github_get_file("no_servers.txt")
    if not inactive:
        return ""
    return inactive["content"].strip()
def generate_subscription_content(
    user_id: int,
    expires: datetime,
    active: bool = True,
):
    if not active:
        servers = read_no_servers()
        if not servers:
            servers = (
                "vless://expired@127.0.0.1:443"
                "?security=none#MAGNET.NET"
            )
        return (
            "# MAGNET.NET\n"
            "# SUBSCRIPTION EXPIRED\n"
            "# SUPPORT: @magnitsub\n"
            f"{servers}\n"
        )
    servers = read_servers()
    if not servers:
        servers = (
            "vless://unavailable@127.0.0.1:443"
            "?security=none#MAGNET.NET"
        )
    return (
        f"# {SERVICE_NAME}\n"
        f"# ID: {user_id}\n"
        f"# EXPIRE: {expires.isoformat()}\n"
        f"# SUPPORT: {SUPPORT_USERNAME}\n"
        f"{servers}\n"
    )
def parse_user_file(content: str):
    if not content:
        return None
    expire = None
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# EXPIRE:"):
            value = line.split(":", 1)[1].strip()
            try:
                expire = datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                )
                if expire.tzinfo is None:
                    expire = expire.replace(
                        tzinfo=UTC
                    )
            except Exception:
                pass
    return {
        "expire": expire,
        "content": content,
    }
# ============================================================
# TIME
# ============================================================
def now_utc():
    return datetime.now(UTC)
def format_date(dt):
    if not dt:
        return "—"
    return dt.astimezone(UTC).strftime(
        "%d.%m.%Y %H:%M"
    )
def days_left(dt):
    if not dt:
        return 0
    seconds = (
        dt - now_utc()
    ).total_seconds()
    if seconds <= 0:
        return 0
    return max(
        1,
        math.ceil(seconds / 86400),
    )
# ============================================================
# SUBSCRIPTIONS
# ============================================================
def get_subscription(
    user_id: int,
    kind: str = "paid",
):
    path = user_file(user_id, kind)
    data = github_get_file(path)
    if not data:
        return None
    parsed = parse_user_file(
        data["content"]
    )
    if not parsed:
        return None
    return {
        "path": path,
        "content": data["content"],
        "sha": data["sha"],
        "expire": parsed["expire"],
    }
def expire_user_if_needed(
    user_id: int,
):
    subscription = get_subscription(
        user_id,
        "paid",
    )
    if not subscription:
        return None
    expire = subscription["expire"]
    if not expire:
        return subscription
    if expire > now_utc():
        return subscription
    content = generate_subscription_content(
        user_id,
        now_utc(),
        active=False,
    )
    github_put_file(
        subscription["path"],
        content,
        f"Expire subscription {user_id}",
        subscription["sha"],
    )
    return {
        "path": subscription["path"],
        "content": content,
        "sha": None,
        "expire": now_utc(),
    }
def has_active_subscription(
    user_id: int,
):
    subscription = expire_user_if_needed(
        user_id
    )
    if not subscription:
        return False
    expire = subscription["expire"]
    return bool(
        expire and expire > now_utc()
    )
def has_trial_used(
    user_id: int,
):
    return github_get_file(
        user_file(user_id, "trial")
    ) is not None
# ============================================================
# SUBSCRIPTION URL
# ============================================================
def get_subscription_url(
    user_id: int,
    kind: str = "paid",
):
    if kind == "trial":
        return (
            "https://raw.githubusercontent.com/"
            f"{REPO_OWNER}/{REPO_NAME}/"
            f"{REPO_BRANCH}/"
            f"users/trial_{user_id}.txt"
        )
    return PUBLIC_SUB_TEMPLATE.format(
        user_id=user_id
    )
# ============================================================
# HAPP CRYPT4
# ============================================================
def generate_happ_crypt4(
    user_id: int,
    kind: str = "paid",
):
    """
    Generates legacy Happ crypt4 directly.
    Result:
        happ://crypt4/<base64>
    It does not call the Happ API and therefore
    cannot accidentally return crypt5.
    """
    subscription_url = get_subscription_url(
        user_id,
        kind,
    )
    try:
        rsa_key = RSA.import_key(
            HAPP_CRYPT4_PUBLIC_KEY
        )
        cipher = PKCS1_v1_5.new(
            rsa_key
        )
        encrypted = cipher.encrypt(
            subscription_url.encode("utf-8")
        )
        encoded = base64.b64encode(
            encrypted
        ).decode("ascii")
        result = (
            "happ://crypt4/"
            + encoded
        )
        logger.info(
            "Generated crypt4 for %s (%s)",
            user_id,
            kind,
        )
        return result
    except Exception as e:
        logger.exception(
            "Crypt4 generation error: %s",
            e,
        )
        return None
# ============================================================
# USER INFO
# ============================================================
USER_INFO_PATH = "users_info.json"
def load_users_info():
    data = github_get_file(
        USER_INFO_PATH
    )
    if not data:
        return {}, None
    try:
        value = json.loads(
            data["content"]
        )
        if not isinstance(value, dict):
            value = {}
        return value, data["sha"]
    except Exception:
        return {}, data["sha"]
def save_users_info(
    users,
    sha=None,
):
    content = json.dumps(
        users,
        ensure_ascii=False,
        indent=2,
    )
    github_put_file(
        USER_INFO_PATH,
        content,
        "Update users info",
        sha,
    )
def save_user_info(
    user_id: int,
    username: str = "",
    first_name: str = "",
):
    users, sha = load_users_info()
    users[str(user_id)] = {
        "id": user_id,
        "username": username or "",
        "first_name": first_name or "",
        "updated_at": now_utc().isoformat(),
    }
    save_users_info(
        users,
        sha,
    )
def get_user_info(
    user_id: int,
):
    users, _ = load_users_info()
    return users.get(
        str(user_id),
        {},
    )
# ============================================================
# USERS
# ============================================================
def get_all_users():
    response = github_request(
        "GET",
        "",
        params={
            "ref": REPO_BRANCH
        },
    )
    # GitHub root doesn't contain all user files,
    # so use Git Trees API.
    url = (
        f"https://api.github.com/repos/"
        f"{REPO_OWNER}/{REPO_NAME}/git/trees/"
        f"{REPO_BRANCH}?recursive=1"
    )
    response = requests.get(
        url,
        headers=github_headers(),
        timeout=20,
    )
    response.raise_for_status()
    tree = response.json().get(
        "tree",
        []
    )
    users = set()
    for item in tree:
        path = item.get("path", "")
        if not path.startswith("users/"):
            continue
        filename = path.split(
            "/",
            1,
        )[1]
        if "_" not in filename:
            continue
        try:
            uid = int(
                filename.split(
                    "_",
                    1,
                )[1].split(
                    ".",
                    1,
                )[0]
            )
            users.add(uid)
        except Exception:
            continue
    return sorted(users)
# ============================================================
# EXTEND / REVOKE
# ============================================================
def extend_subscription(
    user_id: int,
    duration_days: int,
):
    current = get_subscription(
        user_id,
        "paid",
    )
    current_expire = None
    if current:
        current_expire = current["expire"]
    now = now_utc()
    if (
        current_expire
        and current_expire > now
    ):
        start = current_expire
    else:
        start = now
    new_expire = (
        start
        + timedelta(days=duration_days)
    )
    content = generate_subscription_content(
        user_id,
        new_expire,
        active=True,
    )
    path = user_file(
        user_id,
        "paid",
    )
    github_put_file(
        path,
        content,
        f"Extend subscription {user_id}",
        current["sha"]
        if current
        else None,
    )
    return new_expire
def revoke_subscription(
    user_id: int,
):
    current = get_subscription(
        user_id,
        "paid",
    )
    if not current:
        return False
    content = generate_subscription_content(
        user_id,
        now_utc(),
        active=False,
    )
    github_put_file(
        current["path"],
        content,
        f"Revoke subscription {user_id}",
        current["sha"],
    )
    return True
# ============================================================
# BLOCK USERS
# ============================================================
BLOCKS_PATH = "blocked.txt"
def load_blocked():
    data = github_get_file(
        BLOCKS_PATH
    )
    if not data:
        return set(), None
    result = set()
    for line in data["content"].splitlines():
        line = line.strip()
        if line.isdigit():
            result.add(
                int(line)
            )
    return result, data["sha"]
def save_blocked(
    blocked,
    sha=None,
):
    content = "\n".join(
        str(x)
        for x in sorted(blocked)
    )
    github_put_file(
        BLOCKS_PATH,
        content,
        "Update blocked users",
        sha,
    )
def is_blocked(
    user_id: int,
):
    blocked, _ = load_blocked()
    return user_id in blocked
def set_blocked(
    user_id: int,
    value: bool,
):
    blocked, sha = load_blocked()
    if value:
        blocked.add(user_id)
    else:
        blocked.discard(user_id)
    save_blocked(
        blocked,
        sha,
    )
# ============================================================
# PROMOS
# ============================================================
PROMOS_PATH = "promos.txt"
def load_promos():
    data = github_get_file(
        PROMOS_PATH
    )
    if not data:
        return {}, None
    result = {}
    for line in data["content"].splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        code = parts[0].strip().upper()
        try:
            days = int(
                parts[1].strip()
            )
        except Exception:
            continue
        result[code] = days
    return result, data["sha"]
def save_promos(
    promos,
    sha=None,
):
    lines = [
        f"{code}|{days}"
        for code, days
        in sorted(promos.items())
    ]
    github_put_file(
        PROMOS_PATH,
        "\n".join(lines),
        "Update promos",
        sha,
    )
def promo_used_path(
    user_id: int,
    code: str,
):
    return (
        f"promos_used/"
        f"{user_id}_{code}.txt"
    )
def promo_was_used(
    user_id: int,
    code: str,
):
    return (
        github_get_file(
            promo_used_path(
                user_id,
                code,
            )
        )
        is not None
    )
def mark_promo_used(
    user_id: int,
    code: str,
):
    path = promo_used_path(
        user_id,
        code,
    )
    current = github_get_file(
        path
    )
    github_put_file(
        path,
        now_utc().isoformat(),
        f"Use promo {code} by {user_id}",
        current["sha"]
        if current
        else None,
    )
def use_promo(
    user_id: int,
    code: str,
):
    code = code.strip().upper()
    promos, _ = load_promos()
    if code not in promos:
        return (
            False,
            "Промокод не найден."
        )
    if promo_was_used(
        user_id,
        code,
    ):
        return (
            False,
            "Вы уже использовали этот промокод."
        )
    days = promos[code]
    expire = extend_subscription(
        user_id,
        days,
    )
    mark_promo_used(
        user_id,
        code,
    )
    return (
        True,
        f"Промокод активирован!\n"
        f"Добавлено: {days} дн.\n"
        f"До: {format_date(expire)}"
    )
# ============================================================
# REVENUE
# ============================================================
REVENUE_PATH = "revenue.txt"
def add_revenue(
    user_id: int,
    stars: int,
    days: int,
):
    current = github_get_file(
        REVENUE_PATH
    )
    old = (
        current["content"]
        if current
        else ""
    )
    line = (
        f"{now_utc().isoformat()} | "
        f"{user_id} | "
        f"{stars} Stars | "
        f"{days} days"
    )
    content = (
        old.rstrip()
        + "\n"
        + line
    ).strip() + "\n"
    github_put_file(
        REVENUE_PATH,
        content,
        f"Revenue {user_id}",
        current["sha"]
        if current
        else None,
    )
# ============================================================
# KEYBOARDS
# ============================================================
def main_keyboard(
    user_id: int,
):
    rows = [
        [
            InlineKeyboardButton(
                text="🎁 Пробный период",
                callback_data="trial",
            ),
        ],
        [
            InlineKeyboardButton(
                text="💎 Купить подписку",
                callback_data="buy",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📱 Моя подписка",
                callback_data="my_sub",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎟 Промокод",
                callback_data="promo",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🆘 Поддержка",
                url="https://t.me/magnitsub",
            ),
        ],
    ]
    if user_id in ADMIN_IDS:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⚙️ Админ-панель",
                    callback_data="admin",
                )
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )
def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back",
                )
            ]
        ]
    )
def buy_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1 месяц — 100 ⭐",
                    callback_data="buy_30",
                )
            ],
            [
                InlineKeyboardButton(
                    text="4 месяца — 300 ⭐",
                    callback_data="buy_120",
                )
            ],
            [
                InlineKeyboardButton(
                    text="8 месяцев — 650 ⭐",
                    callback_data="buy_240",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back",
                )
            ],
        ]
    )
# ============================================================
# BOT
# ============================================================
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not configured"
    )
bot = Bot(
    token=BOT_TOKEN
)
dp = Dispatcher()
promo_waiting = set()
admin_states = {}
# ============================================================
# START
# ============================================================
@dp.message(Command("start"))
async def cmd_start(
    message: Message,
):
    user = message.from_user
    if not user:
        return
    save_user_info(
        user.id,
        user.username or "",
        user.first_name or "",
    )
    if is_blocked(user.id):
        await message.answer(
            "🚫 Доступ к боту ограничен."
        )
        return
    text = (
        f"🧲 <b>{SERVICE_NAME}</b>\n\n"
        f"Добро пожаловать, "
        f"<b>{user.first_name or 'пользователь'}</b>!\n\n"
        "⚡ Быстрое подключение\n"
        "🔐 Защищённая подписка\n"
        "📱 Поддержка Happ\n\n"
        "Выберите действие:"
    )
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(
            user.id
        ),
    )
# ============================================================
# TRIAL
# ============================================================
@dp.callback_query(
    F.data == "trial"
)
async def callback_trial(
    callback: CallbackQuery,
):
    user_id = callback.from_user.id
    if is_blocked(user_id):
        await callback.answer(
            "Доступ ограничен.",
            show_alert=True,
        )
        return
    if has_trial_used(user_id):
        await callback.message.edit_text(
            "❌ Вы уже использовали "
            "пробный период.",
            reply_markup=back_keyboard(),
        )
        return
    now = now_utc()
    expire = (
        now
        + timedelta(days=TRIAL_DAYS)
    )
    content = generate_subscription_content(
        user_id,
        expire,
        active=True,
    )
    path = user_file(
        user_id,
        "trial",
    )
    github_put_file(
        path,
        content,
        f"Create trial {user_id}",
    )
    crypt4 = generate_happ_crypt4(
        user_id,
        "trial",
    )
    if not crypt4:
        await callback.message.edit_text(
            "❌ Не удалось создать "
            "Happ crypt4.",
            reply_markup=back_keyboard(),
        )
        return
    text = (
        "🎁 <b>Пробный период активирован!</b>\n\n"
        f"⏳ Срок: {TRIAL_DAYS} дн.\n"
        f"📅 До: <b>{format_date(expire)}</b>\n\n"
        "📱 <b>Ссылка для Happ:</b>\n"
        f"<code>{crypt4}</code>\n\n"
        "Нажмите на ссылку и добавьте её в Happ."
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# BUY
# ============================================================
@dp.callback_query(
    F.data == "buy"
)
async def callback_buy(
    callback: CallbackQuery,
):
    await callback.message.edit_text(
        "💎 <b>Выберите тариф</b>\n\n"
        "Оплата производится через "
        "Telegram Stars ⭐",
        parse_mode="HTML",
        reply_markup=buy_keyboard(),
    )
@dp.callback_query(
    F.data.in_({
        "buy_30",
        "buy_120",
        "buy_240",
    })
)
async def callback_buy_tariff(
    callback: CallbackQuery,
):
    user_id = callback.from_user.id
    mapping = {
        "buy_30": (
            30,
            PRICES[30],
        ),
        "buy_120": (
            120,
            PRICES[120],
        ),
        "buy_240": (
            240,
            PRICES[240],
        ),
    }
    days, stars = mapping[
        callback.data
    ]
    title = {
        30: "MAGNET.NET — 1 месяц",
        120: "MAGNET.NET — 4 месяца",
        240: "MAGNET.NET — 8 месяцев",
    }[days]
    await bot.send_invoice(
        chat_id=user_id,
        title=title,
        description=(
            f"VPN-подписка MAGNET.NET "
            f"на {days} дней"
        ),
        payload=f"magnet_{days}_{user_id}",
        currency="XTR",
        prices=[
            LabeledPrice(
                label=title,
                amount=stars,
            )
        ],
        provider_token="",
    )
    await callback.answer()
# ============================================================
# PRE-CHECKOUT
# ============================================================
@dp.pre_checkout_query()
async def process_pre_checkout(
    query: PreCheckoutQuery,
):
    await query.answer(
        ok=True
    )
# ============================================================
# SUCCESSFUL PAYMENT
# ============================================================
@dp.message(
    F.successful_payment
)
async def successful_payment(
    message: Message,
):
    payment = message.successful_payment
    if not payment:
        return
    user_id = message.from_user.id
    try:
        parts = payment.invoice_payload.split("_")
        days = int(parts[1])
    except Exception:
        await message.answer(
            "❌ Ошибка платежа."
        )
        return
    expire = extend_subscription(
        user_id,
        days,
    )
    stars = payment.total_amount
    add_revenue(
        user_id,
        stars,
        days,
    )
    crypt4 = generate_happ_crypt4(
        user_id,
        "paid",
    )
    if not crypt4:
        await message.answer(
            "✅ Оплата прошла.\n\n"
            "Но не удалось создать "
            "ссылку Happ crypt4.\n"
            f"Обратитесь в поддержку: "
            f"{SUPPORT_USERNAME}"
        )
        return
    text = (
        "✅ <b>Оплата успешно получена!</b>\n\n"
        f"🧲 {SERVICE_NAME}\n"
        f"⏳ Добавлено: {days} дн.\n"
        f"📅 Действует до: "
        f"<b>{format_date(expire)}</b>\n\n"
        "📱 <b>Happ crypt4:</b>\n"
        f"<code>{crypt4}</code>\n\n"
        "Нажмите на ссылку, чтобы "
        "добавить подписку в Happ."
    )
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(
            user_id
        ),
    )
# ============================================================
# MY SUBSCRIPTION
# ============================================================
@dp.callback_query(
    F.data == "my_sub"
)
async def callback_my_sub(
    callback: CallbackQuery,
):
    user_id = callback.from_user.id
    subscription = expire_user_if_needed(
        user_id
    )
    if not subscription:
        await callback.message.edit_text(
            "📱 <b>Моя подписка</b>\n\n"
            "У вас пока нет оплаченной подписки.",
            parse_mode="HTML",
            reply_markup=back_keyboard(),
        )
        return
    expire = subscription["expire"]
    if expire and expire > now_utc():
        crypt4 = generate_happ_crypt4(
            user_id,
            "paid",
        )
        text = (
            "📱 <b>Моя подписка</b>\n\n"
            "🟢 Статус: <b>Активна</b>\n"
            f"📅 До: <b>{format_date(expire)}</b>\n"
            f"⏳ Осталось: <b>{days_left(expire)} дн.</b>\n\n"
        )
        if crypt4:
            text += (
                "📋 <b>Happ crypt4:</b>\n"
                f"<code>{crypt4}</code>\n\n"
            )
        text += (
            "🔄 Ссылка генерируется заново "
            "при каждом открытии."
        )
    else:
        text = (
            "📱 <b>Моя подписка</b>\n\n"
            "🔴 Статус: <b>Завершена</b>\n\n"
            f"🆘 Поддержка: "
            f"{SUPPORT_USERNAME}"
        )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# PROMO
# ============================================================
@dp.callback_query(
    F.data == "promo"
)
async def callback_promo(
    callback: CallbackQuery,
):
    promo_waiting.add(
        callback.from_user.id
    )
    await callback.message.edit_text(
        "🎟 <b>Промокод</b>\n\n"
        "Отправьте промокод следующим сообщением.",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# SUPPORT
# ============================================================
@dp.callback_query(
    F.data == "support"
)
async def callback_support(
    callback: CallbackQuery,
):
    await callback.message.edit_text(
        "🆘 <b>Поддержка MAGNET.NET</b>\n\n"
        f"Написать администратору:\n"
        f"👉 <a href=\"https://t.me/magnitsub\">"
        f"@magnitsub</a>",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# BACK
# ============================================================
@dp.callback_query(
    F.data == "back"
)
async def callback_back(
    callback: CallbackQuery,
):
    user_id = callback.from_user.id
    await callback.message.edit_text(
        f"🧲 <b>{SERVICE_NAME}</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=main_keyboard(
            user_id
        ),
    )
# ============================================================
# ADMIN MENU
# ============================================================
def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin_stats",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 Пользователи",
                    callback_data="admin_users",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔎 Найти пользователя",
                    callback_data="admin_find",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➕ Выдать подписку",
                    callback_data="admin_give",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➖ Забрать подписку",
                    callback_data="admin_revoke",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Заблокировать",
                    callback_data="admin_block",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎟 Промокоды",
                    callback_data="admin_promos",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📢 Рассылка",
                    callback_data="admin_broadcast",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Обновить серверы",
                    callback_data="admin_sync",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back",
                ),
            ],
        ]
    )
def is_admin(
    user_id: int,
):
    return user_id in ADMIN_IDS
@dp.callback_query(
    F.data == "admin"
)
async def callback_admin(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "Нет доступа.",
            show_alert=True,
        )
        return
    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )
# ============================================================
# ADMIN STATS
# ============================================================
@dp.callback_query(
    F.data == "admin_stats"
)
async def admin_stats(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    users = get_all_users()
    active = 0
    expired = 0
    for user_id in users:
        if has_active_subscription(
            user_id
        ):
            active += 1
        else:
            expired += 1
    promos, _ = load_promos()
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{len(users)}</b>\n"
        f"🟢 Активных: <b>{active}</b>\n"
        f"🔴 Неактивных: <b>{expired}</b>\n"
        f"🎟 Промокодов: <b>{len(promos)}</b>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# ADMIN USERS
# ============================================================
@dp.callback_query(
    F.data == "admin_users"
)
async def admin_users(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    users = get_all_users()
    if not users:
        text = "👥 Пользователей пока нет."
    else:
        lines = [
            "👥 <b>Пользователи</b>\n"
        ]
        for uid in users[:50]:
            info = get_user_info(uid)
            name = (
                info.get("first_name")
                or info.get("username")
                or "Без имени"
            )
            status = (
                "🟢"
                if has_active_subscription(uid)
                else "🔴"
            )
            lines.append(
                f"{status} <code>{uid}</code> — "
                f"{name}"
            )
        text = "\n".join(lines)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# ADMIN FIND
# ============================================================
@dp.callback_query(
    F.data == "admin_find"
)
async def admin_find(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = "find"
    await callback.message.edit_text(
        "🔎 <b>Поиск пользователя</b>\n\n"
        "Отправьте Telegram ID.",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# ADMIN GIVE
# ============================================================
@dp.callback_query(
    F.data == "admin_give"
)
async def admin_give(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = "give"
    await callback.message.edit_text(
        "➕ <b>Выдать подписку</b>\n\n"
        "Формат:\n"
        "<code>ID ДНИ</code>\n\n"
        "Например:\n"
        "<code>123456789 30</code>",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# ADMIN REVOKE
# ============================================================
@dp.callback_query(
    F.data == "admin_revoke"
)
async def admin_revoke(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = "revoke"
    await callback.message.edit_text(
        "➖ <b>Забрать подписку</b>\n\n"
        "Отправьте Telegram ID.",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# ADMIN BLOCK
# ============================================================
@dp.callback_query(
    F.data == "admin_block"
)
async def admin_block(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = "block"
    await callback.message.edit_text(
        "🚫 <b>Блокировка</b>\n\n"
        "Отправьте Telegram ID.",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# ADMIN PROMOS
# ============================================================
@dp.callback_query(
    F.data == "admin_promos"
)
async def admin_promos(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    promos, _ = load_promos()
    lines = [
        "🎟 <b>Промокоды</b>\n"
    ]
    if not promos:
        lines.append(
            "Промокодов пока нет."
        )
    else:
        for code, days in promos.items():
            lines.append(
                f"<code>{code}</code> — "
                f"{days} дн."
            )
    lines.append(
        "\nЧтобы создать промокод, "
        "отправьте:\n"
        "<code>КОД ДНИ</code>"
    )
    admin_states[
        callback.from_user.id
    ] = "promo_add"
    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# ADMIN BROADCAST
# ============================================================
@dp.callback_query(
    F.data == "admin_broadcast"
)
async def admin_broadcast(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    admin_states[
        callback.from_user.id
    ] = "broadcast"
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Отправьте текст сообщения.",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# ADMIN SYNC
# ============================================================
@dp.callback_query(
    F.data == "admin_sync"
)
async def admin_sync(
    callback: CallbackQuery,
):
    if not is_admin(
        callback.from_user.id
    ):
        return
    users = get_all_users()
    updated = 0
    for uid in users:
        subscription = get_subscription(
            uid,
            "paid",
        )
        if not subscription:
            continue
        expire = subscription[
            "expire"
        ]
        if expire and expire > now_utc():
            content = generate_subscription_content(
                uid,
                expire,
                active=True,
            )
            github_put_file(
                subscription["path"],
                content,
                f"Sync subscription {uid}",
                subscription["sha"],
            )
            updated += 1
    await callback.message.edit_text(
        "🔄 <b>Синхронизация завершена</b>\n\n"
        f"Обновлено подписок: "
        f"<b>{updated}</b>",
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )
# ============================================================
# TEXT HANDLER
# ============================================================
@dp.message(
    F.text
)
async def text_handler(
    message: Message,
):
    user = message.from_user
    if not user:
        return
    user_id = user.id
    text = (
        message.text or ""
    ).strip()
    # --------------------------------------------------------
    # BLOCK
    # --------------------------------------------------------
    if is_blocked(user_id):
        await message.answer(
            "🚫 Доступ к боту ограничен."
        )
        return
    # --------------------------------------------------------
    # PROMO USER
    # --------------------------------------------------------
    if user_id in promo_waiting:
        promo_waiting.discard(
            user_id
        )
        ok, result = use_promo(
            user_id,
            text,
        )
        await message.answer(
            (
                "✅ "
                if ok
                else "❌ "
            )
            + result,
            parse_mode="HTML",
            reply_markup=main_keyboard(
                user_id
            ),
        )
        return
    # --------------------------------------------------------
    # ADMIN STATES
    # --------------------------------------------------------
    if is_admin(user_id):
        state = admin_states.get(
            user_id
        )
        if state == "find":
            if not text.isdigit():
                await message.answer(
                    "❌ ID должен состоять "
                    "только из цифр."
                )
                return
            target_id = int(text)
            info = get_user_info(
                target_id
            )
            subscription = get_subscription(
                target_id,
                "paid",
            )
            if subscription:
                expire = subscription[
                    "expire"
                ]
                status = (
                    "🟢 Активна"
                    if expire
                    and expire > now_utc()
                    else "🔴 Завершена"
                )
                expiry = format_date(
                    expire
                )
            else:
                status = "🔴 Нет подписки"
                expiry = "—"
            name = (
                info.get("first_name")
                or info.get("username")
                or "—"
            )
            await message.answer(
                "🔎 <b>Пользователь</b>\n\n"
                f"👤 {name}\n"
                f"🆔 <code>{target_id}</code>\n"
                f"📱 Статус: {status}\n"
                f"📅 До: {expiry}",
                parse_mode="HTML",
                reply_markup=admin_keyboard(),
            )
            admin_states.pop(
                user_id,
                None,
            )
            return
        if state == "give":
            parts = text.split()
            if len(parts) != 2:
                await message.answer(
                    "❌ Формат:\n"
                    "<code>ID ДНИ</code>",
                    parse_mode="HTML",
                )
                return
            try:
                target_id = int(parts[0])
                days = int(parts[1])
            except ValueError:
                await message.answer(
                    "❌ Неверные данные."
                )
                return
            expire = extend_subscription(
                target_id,
                days,
            )
            admin_states.pop(
                user_id,
                None,
            )
            await message.answer(
                "✅ <b>Подписка выдана</b>\n\n"
                f"🆔 <code>{target_id}</code>\n"
                f"➕ {days} дн.\n"
                f"📅 До: <b>{format_date(expire)}</b>",
                parse_mode="HTML",
                reply_markup=admin_keyboard(),
            )
            try:
                crypt4 = generate_happ_crypt4(
                    target_id,
                    "paid",
                )
                await bot.send_message(
                    target_id,
                    "🎁 <b>Администратор выдал вам подписку!</b>\n\n"
                    f"📅 До: <b>{format_date(expire)}</b>\n\n"
                    f"📱 Happ crypt4:\n"
                    f"<code>{crypt4}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return
        if state == "revoke":
            if not text.isdigit():
                await message.answer(
                    "❌ Отправьте Telegram ID."
                )
                return
            target_id = int(text)
            ok = revoke_subscription(
                target_id
            )
            admin_states.pop(
                user_id,
                None,
            )
            await message.answer(
                (
                    "✅ Подписка забрана."
                    if ok
                    else "❌ Подписка не найдена."
                ),
                reply_markup=admin_keyboard(),
            )
            return
        if state == "block":
            if not text.isdigit():
                await message.answer(
                    "❌ Отправьте Telegram ID."
                )
                return
            target_id = int(text)
            set_blocked(
                target_id,
                True,
            )
            admin_states.pop(
                user_id,
                None,
            )
            await message.answer(
                f"🚫 Пользователь "
                f"<code>{target_id}</code> "
                f"заблокирован.",
                parse_mode="HTML",
                reply_markup=admin_keyboard(),
            )
            return
        if state == "promo_add":
            parts = text.split()
            if len(parts) != 2:
                await message.answer(
                    "❌ Формат:\n"
                    "<code>КОД ДНИ</code>",
                    parse_mode="HTML",
                )
                return
            code = parts[0].upper()
            try:
                days = int(parts[1])
            except ValueError:
                await message.answer(
                    "❌ Количество дней должно "
                    "быть числом."
                )
                return
            promos, sha = load_promos()
            promos[code] = days
            save_promos(
                promos,
                sha,
            )
            admin_states.pop(
                user_id,
                None,
            )
            await message.answer(
                "✅ <b>Промокод создан</b>\n\n"
                f"🎟 <code>{code}</code>\n"
                f"⏳ {days} дн.",
                parse_mode="HTML",
                reply_markup=admin_keyboard(),
            )
            return
        if state == "broadcast":
            admin_states.pop(
                user_id,
                None,
            )
            users = get_all_users()
            sent = 0
            failed = 0
            for target_id in users:
                try:
                    await bot.send_message(
                        target_id,
                        text,
                        parse_mode="HTML",
                    )
                    sent += 1
                    await asyncio.sleep(
                        0.05
                    )
                except Exception:
                    failed += 1
            await message.answer(
                "📢 <b>Рассылка завершена</b>\n\n"
                f"✅ Отправлено: {sent}\n"
                f"❌ Ошибок: {failed}",
                parse_mode="HTML",
                reply_markup=admin_keyboard(),
            )
            return
    # --------------------------------------------------------
    # UNKNOWN TEXT
    # --------------------------------------------------------
    await message.answer(
        f"🧲 <b>{SERVICE_NAME}</b>\n\n"
        "Используйте кнопки меню.",
        parse_mode="HTML",
        reply_markup=main_keyboard(
            user_id
        ),
    )
# ============================================================
# RENDER HEALTH CHECK
# ============================================================
class HealthHandler(
    BaseHTTPRequestHandler
):
    def do_GET(self):
        body = (
            b'{"service":"MAGNET.NET","status":"ok"}'
        )
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/json",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.end_headers()
        self.wfile.write(body)
    def log_message(
        self,
        format,
        *args,
    ):
        return
def run_health_server():
    port = int(
        os.getenv(
            "PORT",
            "10000",
        )
    )
    server = HTTPServer(
        (
            "0.0.0.0",
            port,
        ),
        HealthHandler,
    )
    logger.info(
        "Health server started on port %s",
        port,
    )
    server.serve_forever()
# ============================================================
# MAIN
# ============================================================
async def main():
    logger.info(
        "Starting %s...",
        SERVICE_NAME,
    )
    threading.Thread(
        target=run_health_server,
        daemon=True,
    ).start()
    await dp.start_polling(
        bot
    )
if __name__ == "__main__":
    try:
        asyncio.run(
            main()
        )
    except KeyboardInterrupt:
        pass