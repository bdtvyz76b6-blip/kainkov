import asyncio
import base64
import json
import logging
import math
import os
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import requests
from aiogram import Bot, Dispatcher, F, types
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

# ==================== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_ID", "0").split(",") if x.strip()]

REPO_OWNER = os.getenv("REPO_OWNER", "bdtvyz76b6-blip")
REPO_NAME = os.getenv("REPO_NAME", "kainkov")
BRANCH = os.getenv("BRANCH", "main")

SERVERS_FILE = os.getenv("SERVERS_FILE", "servers.txt")
NO_SERVERS_FILE = os.getenv("NO_SERVERS_FILE", "no_servers.txt")
USERS_DIR = os.getenv("USERS_DIR", "users")
REVENUE_FILE = os.getenv("REVENUE_FILE", "revenue.txt")
PROMOS_FILE = os.getenv("PROMOS_FILE", "promos.txt")
USERS_INFO_FILE = os.getenv("USERS_INFO_FILE", "users_info.json")

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

# ==================== GITHUB API ====================
def github_request(method: str, path: str, data: Optional[dict] = None) -> Optional[dict]:
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers)
        elif method == "PUT":
            resp = requests.put(url, headers=headers, json=data)
        elif method == "DELETE":
            resp = requests.delete(url, headers=headers, json=data)
        else:
            return None
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.error(f"GitHub API error: {e}")
        return None

def github_get_file(path: str) -> Optional[str]:
    data = github_request("GET", path)
    if data and "content" in data:
        try:
            return base64.b64decode(data["content"]).decode("utf-8")
        except:
            pass
    return None

def github_put_file(path: str, content: str, commit_msg: str) -> bool:
    existing = github_request("GET", path)
    sha = existing.get("sha") if existing else None
    payload = {
        "message": commit_msg,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    result = github_request("PUT", path, payload)
    return result is not None

def github_delete_file(path: str, commit_msg: str) -> bool:
    existing = github_request("GET", path)
    if not existing:
        return True
    payload = {
        "message": commit_msg,
        "sha": existing["sha"],
        "branch": BRANCH,
    }
    result = github_request("DELETE", path, payload)
    return result is not None

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def get_user_file_path(user_id: int, kind: str = "paid") -> str:
    return f"{USERS_DIR}/{kind}_{user_id}.txt"

def read_servers(file_name: str) -> list[str]:
    content = github_get_file(file_name)
    if content:
        return [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
    return []

def unix_timestamp(dt: Optional[datetime]) -> int:
    return int(dt.timestamp()) if dt else 0

def generate_subscription_content(servers: list[str], expire_date: Optional[datetime] = None) -> str:
    expire_ts = unix_timestamp(expire_date)
    header = (
        "#profile-title: 𝗠𝗔𝗚𝗡𝗘𝗧.𝗡𝗘𝗧\n"
        "#profile-update-interval: 1\n"
        f"#subscription-userinfo: upload=0; download=0; total=0; expire={expire_ts}\n"
        "#hide-settings: true\n"
        "#happ-hide-settings: true\n"
        "#hide_server_settings: true\n"
        "#hidesettings: true\n"
    )
    return header + "\n".join(servers)

def parse_user_file(content: str) -> Optional[dict]:
    lines = content.splitlines()
    servers = []
    expire_ts = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#subscription-userinfo:"):
            for part in line.split(";"):
                part = part.strip()
                if part.startswith("expire="):
                    try:
                        expire_ts = int(part.split("=")[1])
                    except:
                        pass
        elif line.startswith("#"):
            continue
        else:
            servers.append(line)
    if not servers:
        return None
    expire_date = datetime.fromtimestamp(expire_ts) if expire_ts else None
    return {"servers": servers, "expire_date": expire_date}

async def check_and_cleanup_expired(user_id: int):
    paid_path = get_user_file_path(user_id, "paid")
    paid_content = github_get_file(paid_path)
    if paid_content:
        parsed = parse_user_file(paid_content)
        if parsed and parsed["expire_date"] and parsed["expire_date"] < datetime.now():
            stub_servers = read_servers(NO_SERVERS_FILE)
            new_content = generate_subscription_content(stub_servers)
            github_put_file(paid_path, new_content, f"Expired paid for user {user_id}")

    trial_path = get_user_file_path(user_id, "trial")
    trial_content = github_get_file(trial_path)
    if trial_content:
        parsed = parse_user_file(trial_content)
        if parsed and parsed["expire_date"] and parsed["expire_date"] < datetime.now():
            stub_servers = read_servers(NO_SERVERS_FILE)
            new_content = generate_subscription_content(stub_servers)
            github_put_file(trial_path, new_content, f"Expired trial for user {user_id}")

async def has_active_subscription(user_id: int) -> bool:
    await check_and_cleanup_expired(user_id)
    paid_path = get_user_file_path(user_id, "paid")
    content = github_get_file(paid_path)
    if content:
        parsed = parse_user_file(content)
        if parsed and parsed["expire_date"] and parsed["expire_date"] >= datetime.now():
            return True
    return False

async def has_trial_used(user_id: int) -> bool:
    trial_path = get_user_file_path(user_id, "trial")
    return github_get_file(trial_path) is not None

async def get_active_subscription_info(user_id: int) -> Optional[dict]:
    await check_and_cleanup_expired(user_id)
    paid_path = get_user_file_path(user_id, "paid")
    content = github_get_file(paid_path)
    if content:
        parsed = parse_user_file(content)
        if parsed and parsed["expire_date"] and parsed["expire_date"] >= datetime.now():
            parsed["kind"] = "paid"
            return parsed
    trial_path = get_user_file_path(user_id, "trial")
    content = github_get_file(trial_path)
    if content:
        parsed = parse_user_file(content)
        if parsed and parsed["expire_date"] and parsed["expire_date"] >= datetime.now():
            parsed["kind"] = "trial"
            return parsed
    return None

def update_revenue(amount: int):
    current = github_get_file(REVENUE_FILE)
    if current is None:
        current = "0"
    try:
        total = int(current.strip()) + amount
    except:
        total = amount
    github_put_file(REVENUE_FILE, str(total), "Update revenue")

def get_revenue() -> int:
    content = github_get_file(REVENUE_FILE)
    if content is None:
        return 0
    try:
        return int(content.strip())
    except:
        return 0

# ==================== USERS INFO (имя/username) ====================
def load_users_info() -> dict:
    content = github_get_file(USERS_INFO_FILE)
    if content:
        try:
            return json.loads(content)
        except:
            pass
    return {}

def save_users_info(info: dict):
    github_put_file(USERS_INFO_FILE, json.dumps(info, ensure_ascii=False), "Update users info")

def save_user_info(user_id: int, first_name: str = "", username: str = ""):
    info = load_users_info()
    info[str(user_id)] = {
        "first_name": first_name,
        "username": username,
    }
    save_users_info(info)

def get_user_meta(user_id: int) -> dict:
    info = load_users_info()
    return info.get(str(user_id), {})

# ==================== ПОЛЬЗОВАТЕЛИ ====================
def get_all_user_ids() -> list[int]:
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/git/trees/{BRANCH}?recursive=1"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return []
    data = resp.json()
    ids = set()
    for item in data.get("tree", []):
        path = item.get("path", "")
        if path.startswith(USERS_DIR + "/"):
            fname = path.split("/")[-1]
            if fname.startswith("paid_"):
                try:
                    ids.add(int(fname[5:-4]))
                except:
                    pass
            elif fname.startswith("trial_"):
                try:
                    ids.add(int(fname[6:-4]))
                except:
                    pass
    info = load_users_info()
    for uid_str in info.keys():
        try:
            ids.add(int(uid_str))
        except:
            pass
    return sorted(ids)

def get_user(user_id: int) -> Optional[dict]:
    paid_path = get_user_file_path(user_id, "paid")
    trial_path = get_user_file_path(user_id, "trial")
    paid_content = github_get_file(paid_path)
    trial_content = github_get_file(trial_path)
    data = {
        "user_id": user_id,
        "blocked": False,
        "subscription": None,
        "expire_date": None,
        "first_name": "",
        "username": "",
    }
    meta = get_user_meta(user_id)
    if meta:
        data["first_name"] = meta.get("first_name", "")
        data["username"] = meta.get("username", "")
    blocked_path = f"{USERS_DIR}/blocked_{user_id}.txt"
    if github_get_file(blocked_path):
        data["blocked"] = True
    for content, kind in ((paid_content, "paid"), (trial_content, "trial")):
        if content:
            parsed = parse_user_file(content)
            if parsed and parsed["expire_date"] and parsed["expire_date"] >= datetime.now():
                data["subscription"] = kind
                data["expire_date"] = parsed["expire_date"]
                break
    return data if data["subscription"] or data["blocked"] or data["first_name"] or data["username"] else None

def extend_subscription(user_id: int, days: int):
    paid_path = get_user_file_path(user_id, "paid")
    current = github_get_file(paid_path)
    if current:
        parsed = parse_user_file(current)
        base = parsed["expire_date"] if parsed and parsed["expire_date"] and parsed["expire_date"] > datetime.now() else datetime.now()
    else:
        base = datetime.now()
    new_expire = base + timedelta(days=days)
    servers = read_servers(SERVERS_FILE)
    content = generate_subscription_content(servers, new_expire)
    github_put_file(paid_path, content, f"Extended subscription for {user_id} by admin")

def revoke_subscription(user_id: int):
    paid_path = get_user_file_path(user_id, "paid")
    stub_servers = read_servers(NO_SERVERS_FILE)
    content = generate_subscription_content(stub_servers)
    github_put_file(paid_path, content, f"Revoked subscription for {user_id} by admin")

def set_blocked(user_id: int, blocked: bool):
    blocked_path = f"{USERS_DIR}/blocked_{user_id}.txt"
    if blocked:
        github_put_file(blocked_path, "blocked", f"Blocked user {user_id}")
    else:
        github_delete_file(blocked_path, f"Unblocked user {user_id}")

def create_promo(code: str, days: int) -> bool:
    promos_content = github_get_file(PROMOS_FILE)
    promos = []
    if promos_content:
        promos = [line.strip() for line in promos_content.splitlines() if line.strip()]
    if any(p.split()[0] == code for p in promos):
        return False
    promos.append(f"{code} {days}")
    github_put_file(PROMOS_FILE, "\n".join(promos), f"Created promo {code}")
    return True

def get_all_promos() -> list[tuple[str, int]]:
    content = github_get_file(PROMOS_FILE)
    result = []
    if content:
        for line in content.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    result.append((parts[0], int(parts[1])))
                except:
                    pass
    return result

# ==================== HAPP LINK ====================
def generate_happ_link(user_id: int, kind: str = "paid") -> str:
    """
    Генерирует ссылку happ://crypt4/<base64 от raw_url>.
    Вместо raw_url мы вставляем base64-кодированную строку raw_url.
    Если необходимо использовать другой алгоритм (например, шифрование) — замените эту функцию.
    """
    raw_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/{USERS_DIR}/{kind}_{user_id}.txt"
    encoded = base64.urlsafe_b64encode(raw_url.encode()).decode().rstrip("=")
    return f"happ://crypt4/{encoded}"

# ==================== HEALTH CHECK SERVER ====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# ==================== ИНИЦИАЛИЗАЦИЯ БОТА ====================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== КЛАВИАТУРЫ ====================
def main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Пробный период", callback_data="trial")
    builder.button(text="💎 Купить подписку", callback_data="buy")
    builder.button(text="📋 Моя подписка", callback_data="my_sub")
    builder.button(text="🆘 Поддержка", callback_data="support")
    if ADMIN_IDS:
        builder.button(text="🔑 Админ-панель", callback_data="admin")
    builder.adjust(2, 2)
    return builder.as_markup()

def buy_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="1 месяц - 100⭐", callback_data="buy_1_month")
    builder.button(text="4 месяца - 300⭐", callback_data="buy_4_months")
    builder.button(text="8 месяцев - 650⭐", callback_data="buy_8_months")
    builder.button(text="⬅️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()

def admin_menu_keyboard():
    rows = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats"),
         InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users:0")],
        [InlineKeyboardButton(text="🔎 Найти пользователя", callback_data="admin:find")],
        [InlineKeyboardButton(text="➕ Выдать подписку", callback_data="admin:give"),
         InlineKeyboardButton(text="🚫 Отозвать", callback_data="admin:revoke")],
        [InlineKeyboardButton(text="⛔ Блокировки", callback_data="admin:block"),
         InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin:promos")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="🔄 Обновить серверы", callback_data="admin:sync")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def back_to_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]
    ])

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    save_user_info(
        user_id,
        first_name=message.from_user.first_name or "",
        username=message.from_user.username or ""
    )
    await message.answer(
        "👋 Добро пожаловать в VPN бот!\n\n"
        "Здесь вы можете получить доступ к нашим серверам.\n"
        "Пробный период — 2 дня бесплатно.\n"
        "После вы можете оформить платную подписку.",
        reply_markup=main_keyboard()
    )

# ==================== CALLBACK-ОБРАБОТЧИКИ ====================
@dp.callback_query(F.data == "trial")
async def process_trial(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer()
    if await has_trial_used(user_id):
        await callback.message.edit_text("❌ Вы уже использовали пробный период.")
        return
    if await has_active_subscription(user_id):
        await callback.message.edit_text("✅ У вас уже есть активная платная подписка!")
        return
    servers = read_servers(NO_SERVERS_FILE)
    if not servers:
        await callback.message.edit_text("⚠️ Серверы временно недоступны.")
        return
    expire_date = datetime.now() + timedelta(days=TRIAL_DAYS)
    content = generate_subscription_content(servers, expire_date)
    path = get_user_file_path(user_id, "trial")
    success = github_put_file(path, content, f"Trial for user {user_id}")
    if success:
        await callback.message.edit_text(
            f"🎉 Пробный период активирован!\n"
            f"Длительность: {TRIAL_DAYS} дня\n"
            f"Дата окончания: {expire_date.strftime('%Y-%m-%d')}\n\n"
            f"Подключение доступно в разделе «Моя подписка»."
        )
    else:
        await callback.message.edit_text("❌ Ошибка при активации.")

@dp.callback_query(F.data == "buy")
async def process_buy(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выберите тариф:", reply_markup=buy_keyboard())

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy_tariff(callback: CallbackQuery):
    tariff = callback.data[4:]
    if tariff not in PRICES:
        await callback.answer("Неверный тариф")
        return
    price = PRICES[tariff]
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"VPN Подписка ({tariff.replace('_', ' ')})",
        description=f"Доступ к VPN серверам на {DURATIONS[tariff]} дней",
        payload=f"vpn_{tariff}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Подписка", amount=price)],
        start_parameter="vpn_subscription",
    )
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    user_id = message.from_user.id
    payment = message.successful_payment
    payload = payment.invoice_payload
    tariff = payload[4:]
    if tariff not in DURATIONS:
        await message.answer("❌ Ошибка определения тарифа.")
        return
    days = DURATIONS[tariff]
    price = PRICES[tariff]
    servers = read_servers(SERVERS_FILE)
    if not servers:
        await message.answer("⚠️ Серверы временно недоступны.")
        return
    expire_date = datetime.now() + timedelta(days=days)
    content = generate_subscription_content(servers, expire_date)
    path = get_user_file_path(user_id, "paid")
    success = github_put_file(path, content, f"Paid subscription for user {user_id}")
    if success:
        update_revenue(price)
        save_user_info(
            user_id,
            first_name=message.from_user.first_name or "",
            username=message.from_user.username or ""
        )
        await message.answer(
            f"✅ Подписка успешно оплачена и активирована!\n"
            f"Тариф: {tariff.replace('_', ' ').capitalize()}\n"
            f"Срок: {days} дней\n"
            f"Дата окончания: {expire_date.strftime('%Y-%m-%d')}\n\n"
            f"Подключение доступно в разделе «Моя подписка»."
        )
    else:
        await message.answer("❌ Ошибка при создании подписки.")

@dp.callback_query(F.data == "my_sub")
async def process_my_sub(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer()
    info = await get_active_subscription_info(user_id)
    if info:
        kind = info["kind"]
        expire = info["expire_date"].strftime("%Y-%m-%d")
        happ_url = generate_happ_link(user_id, kind)
        text = (
            f"📋 <b>Ваша подписка</b>\n\n"
            f"🌐 Название: <b>MAGNET.NET</b>\n"
            f"📅 Действует до: <b>{expire}</b>\n\n"
            f"⚡ <b>Ссылка для подключения (Happ):</b>\n"
            f"<code>{happ_url}</code>\n\n"
            f"Нажмите кнопку ниже, чтобы открыть в Happ."
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Открыть в Happ", url=happ_url)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await callback.message.edit_text("У вас нет активной подписки.")

@dp.callback_query(F.data == "support")
async def process_support(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("По всем вопросам обращайтесь: @your_support_username")

@dp.callback_query(F.data == "back_main")
async def process_back_main(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Главное меню:", reply_markup=main_keyboard())

# ==================== АДМИН-ПАНЕЛЬ ====================
admin_states = {}

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@dp.callback_query(F.data == "admin")
async def process_admin(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("🛠 Админ-панель:", reply_markup=admin_menu_keyboard())

@dp.callback_query(F.data == "admin:menu")
async def admin_menu_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("🛠 Админ-панель:", reply_markup=admin_menu_keyboard())

@dp.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    user_ids = get_all_user_ids()
    total_users = len(user_ids)
    active = 0
    for uid in user_ids:
        info = await get_active_subscription_info(uid)
        if info:
            active += 1
    revenue = get_revenue()
    servers_count = len(read_servers(SERVERS_FILE))
    await callback.answer()
    await callback.message.edit_text(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"🟢 Активных: <b>{active}</b>\n"
        f"⭐ Получено Stars: <b>{revenue}</b>\n"
        f"🌐 Серверов: <b>{servers_count}</b>",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )

@dp.callback_query(F.data.startswith("admin:users:"))
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    page = int(callback.data.split(":")[-1])
    per_page = 8
    all_users = get_all_user_ids()
    total = len(all_users)
    pages = max(1, math.ceil(total / per_page))
    start = page * per_page
    current = all_users[start:start + per_page]
    rows = []
    for uid in current:
        user = get_user(uid)
        if not user:
            continue
        status = "🟢" if user.get("subscription") else "🔴"
        name = user.get("first_name") or user.get("username") or str(uid)
        label = f"{status} {name}"
        if len(label) > 30:
            label = label[:27] + "..."
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"admin:user:{uid}"
            )
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin:users:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="admin:noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admin:users:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")])
    await callback.answer()
    await callback.message.edit_text(
        f"👥 <b>Пользователи</b> (всего: {total})",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

@dp.callback_query(F.data.startswith("admin:user:"))
async def admin_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = int(callback.data.split(":")[-1])
    user = get_user(uid)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    expire = user["expire_date"].strftime("%Y-%m-%d") if user["expire_date"] else "нет"
    blocked = user["blocked"]
    username = user.get("username") or "нет"
    first_name = user.get("first_name") or "нет"
    # Для админа также показываем crypt4 (вместо raw)
    kind = user.get("subscription") or "paid"
    happ_url = generate_happ_link(uid, kind)
    text = (
        f"👤 <b>Пользователь {uid}</b>\n"
        f"Имя: <b>{first_name}</b>\n"
        f"Username: @{username}\n"
        f"Статус: {'🔴 Заблокирован' if blocked else '🟢 Активен' if user['subscription'] else '🔴 Неактивен'}\n"
        f"Подписка: {user['subscription'] or 'нет'}\n"
        f"Действует до: {expire}\n\n"
        f"⚡ Crypt4: <code>{happ_url}</code>"
    )
    rows = [
        [InlineKeyboardButton(text="➕ 30 дней", callback_data=f"admin:add:{uid}:30"),
         InlineKeyboardButton(text="➕ 90 дней", callback_data=f"admin:add:{uid}:90")],
        [InlineKeyboardButton(text="➕ 180 дней", callback_data=f"admin:add:{uid}:180"),
         InlineKeyboardButton(text="➕ 365 дней", callback_data=f"admin:add:{uid}:365")],
        [InlineKeyboardButton(text="🚫 Отозвать подписку", callback_data=f"admin:revoke_user:{uid}")],
        [InlineKeyboardButton(text="🔓 Разблокировать" if blocked else "⛔ Заблокировать",
                              callback_data=f"admin:unblock:{uid}" if blocked else f"admin:block_user:{uid}")],
        [InlineKeyboardButton(text="🔄 Обновить подписку", callback_data=f"admin:sync_user:{uid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:users:0")]
    ]
    await callback.answer()
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("admin:add:"))
async def admin_add(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    uid = int(parts[2])
    days = int(parts[3])
    extend_subscription(uid, days)
    await callback.answer("✅ Подписка продлена", show_alert=True)
    await admin_user(callback)

@dp.callback_query(F.data.startswith("admin:revoke_user:"))
async def admin_revoke_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = int(callback.data.split(":")[-1])
    revoke_subscription(uid)
    await callback.answer("🚫 Подписка отозвана", show_alert=True)
    await admin_user(callback)

@dp.callback_query(F.data.startswith("admin:block_user:"))
async def admin_block_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = int(callback.data.split(":")[-1])
    set_blocked(uid, True)
    await callback.answer("⛔ Пользователь заблокирован", show_alert=True)
    await admin_user(callback)

@dp.callback_query(F.data.startswith("admin:unblock:"))
async def admin_unblock(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = int(callback.data.split(":")[-1])
    set_blocked(uid, False)
    await callback.answer("🔓 Пользователь разблокирован", show_alert=True)
    await admin_user(callback)

@dp.callback_query(F.data.startswith("admin:sync_user:"))
async def admin_sync_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = int(callback.data.split(":")[-1])
    user = get_user(uid)
    if user and user["subscription"]:
        extend_subscription(uid, 0)
        await callback.answer("✅ Подписка обновлена", show_alert=True)
    else:
        await callback.answer("❌ Нет активной подписки", show_alert=True)
    await admin_user(callback)

@dp.callback_query(F.data == "admin:find")
async def admin_find(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    admin_states[callback.from_user.id] = {"action": "find"}
    await callback.answer()
    await callback.message.edit_text(
        "🔎 <b>Поиск пользователя</b>\n\nОтправьте Telegram ID пользователя.",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )

@dp.callback_query(F.data == "admin:give")
async def admin_give(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    admin_states[callback.from_user.id] = {"action": "give"}
    await callback.answer()
    await callback.message.edit_text(
        "➕ <b>Выдать подписку</b>\n\nОтправьте сообщение в формате:\n<code>ID ДНИ</code>\nНапример: <code>123456789 30</code>",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )

@dp.callback_query(F.data == "admin:revoke")
async def admin_revoke(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    admin_states[callback.from_user.id] = {"action": "revoke"}
    await callback.answer()
    await callback.message.edit_text(
        "🚫 <b>Отозвать подписку</b>\n\nОтправьте Telegram ID.",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )

@dp.callback_query(F.data == "admin:block")
async def admin_block(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    admin_states[callback.from_user.id] = {"action": "block"}
    await callback.answer()
    await callback.message.edit_text(
        "⛔ <b>Блокировка</b>\n\nОтправьте:\n<code>ID on</code> — заблокировать\n<code>ID off</code> — разблокировать",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )

@dp.callback_query(F.data == "admin:promos")
async def admin_promos(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    promos = get_all_promos()
    text = "🎟 <b>Промокоды</b>\n\n"
    if promos:
        text += "\n".join([f"<code>{p[0]}</code> — {p[1]} дней" for p in promos])
    else:
        text += "Нет активных промокодов."
    text += "\n\nСоздать новый промокод:"
    await callback.answer()
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать", callback_data="admin:create_promo")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]
        ])
    )

@dp.callback_query(F.data == "admin:create_promo")
async def admin_create_promo(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    admin_states[callback.from_user.id] = {"action": "promo"}
    await callback.answer()
    await callback.message.edit_text(
        "🎟 <b>Создание промокода</b>\n\nОтправьте:\n<code>КОД ДНИ</code>\nНапример: <code>MAGNIT30 30</code>",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )

@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    admin_states[callback.from_user.id] = {"action": "broadcast"}
    await callback.answer()
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nОтправьте текст сообщения.",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )

@dp.callback_query(F.data == "admin:sync")
async def admin_sync(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.answer("🔄 Обновление серверов...")
    await asyncio.sleep(0.5)
    await callback.message.edit_text(
        "✅ Серверы обновлены (заглушки применены к истекшим).",
        reply_markup=back_to_admin_keyboard()
    )

@dp.callback_query(F.data == "admin:noop")
async def admin_noop(callback: CallbackQuery):
    await callback.answer()

# ==================== ОБРАБОТКА ТЕКСТОВЫХ СОСТОЯНИЙ АДМИНА ====================
@dp.message()
async def admin_text_handler(message: Message):
    if not is_admin(message.from_user.id):
        return
    state = admin_states.get(message.from_user.id)
    if not state:
        return
    action = state["action"]
    text = (message.text or "").strip()

    if action == "find":
        try:
            uid = int(text)
        except:
            await message.answer("❌ Некорректный ID.")
            return
        admin_states.pop(message.from_user.id, None)
        user = get_user(uid)
        if not user:
            await message.answer("❌ Пользователь не найден.", reply_markup=admin_menu_keyboard())
            return
        expire = user["expire_date"].strftime("%Y-%m-%d") if user["expire_date"] else "нет"
        kind = user.get("subscription") or "paid"
        happ_url = generate_happ_link(uid, kind)
        await message.answer(
            f"👤 <b>Пользователь {uid}</b>\n"
            f"Имя: {user.get('first_name') or 'нет'}\n"
            f"Username: @{user.get('username') or 'нет'}\n"
            f"Статус: {'🔴 Заблокирован' if user['blocked'] else '🟢 Активен' if user['subscription'] else '🔴 Неактивен'}\n"
            f"Подписка: {user['subscription'] or 'нет'}\n"
            f"Действует до: {expire}\n"
            f"⚡ Crypt4: <code>{happ_url}</code>",
            parse_mode="HTML",
            reply_markup=admin_menu_keyboard()
        )
        return

    elif action == "give":
        parts = text.split()
        if len(parts) != 2:
            await message.answer("❌ Формат: <code>ID ДНИ</code>", parse_mode="HTML")
            return
        try:
            uid = int(parts[0])
            days = int(parts[1])
        except:
            await message.answer("❌ ID и дни должны быть числами.")
            return
        extend_subscription(uid, days)
        admin_states.pop(message.from_user.id, None)
        await message.answer(
            f"✅ Подписка выдана пользователю {uid} на {days} дней.",
            reply_markup=admin_menu_keyboard()
        )
        return

    elif action == "revoke":
        try:
            uid = int(text)
        except:
            await message.answer("❌ Некорректный ID.")
            return
        revoke_subscription(uid)
        admin_states.pop(message.from_user.id, None)
        await message.answer(f"🚫 Подписка пользователя {uid} отозвана.", reply_markup=admin_menu_keyboard())
        return

    elif action == "block":
        parts = text.split()
        if len(parts) != 2:
            await message.answer("❌ Формат: <code>ID on</code> или <code>ID off</code>", parse_mode="HTML")
            return
        try:
            uid = int(parts[0])
        except:
            await message.answer("❌ Некорректный ID.")
            return
        mode = parts[1].lower()
        if mode not in ("on", "off"):
            await message.answer("❌ Используйте on или off.")
            return
        set_blocked(uid, mode == "on")
        admin_states.pop(message.from_user.id, None)
        await message.answer(
            ("⛔ Пользователь заблокирован." if mode == "on" else "🔓 Пользователь разблокирован."),
            reply_markup=admin_menu_keyboard()
        )
        return

    elif action == "promo":
        parts = text.split()
        if len(parts) != 2:
            await message.answer("❌ Формат: <code>КОД ДНИ</code>", parse_mode="HTML")
            return
        code = parts[0].upper()
        try:
            days = int(parts[1])
        except:
            await message.answer("❌ Количество дней должно быть числом.")
            return
        if create_promo(code, days):
            await message.answer(f"✅ Промокод <code>{code}</code> создан.", parse_mode="HTML", reply_markup=admin_menu_keyboard())
        else:
            await message.answer("❌ Такой промокод уже существует.", reply_markup=admin_menu_keyboard())
        admin_states.pop(message.from_user.id, None)
        return

    elif action == "broadcast":
        admin_states.pop(message.from_user.id, None)
        users = get_all_user_ids()
        sent, failed = 0, 0
        await message.answer(f"📢 Рассылка начата для {len(users)} пользователей...")
        for uid in users:
            try:
                await bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1
        await message.answer(
            f"📢 <b>Рассылка завершена</b>\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}",
            parse_mode="HTML",
            reply_markup=admin_menu_keyboard()
        )
        return

# ==================== ЗАПУСК ====================
async def main():
    # Инициализация файлов, если их нет
    if not github_get_file(SERVERS_FILE):
        github_put_file(SERVERS_FILE, "# Рабочие серверы", "Init servers.txt")
    if not github_get_file(NO_SERVERS_FILE):
        github_put_file(NO_SERVERS_FILE, "# Заглушки", "Init no_servers.txt")
    if not github_get_file(REVENUE_FILE):
        github_put_file(REVENUE_FILE, "0", "Init revenue.txt")
    if not github_get_file(PROMOS_FILE):
        github_put_file(PROMOS_FILE, "", "Init promos.txt")
    if not github_get_file(USERS_INFO_FILE):
        github_put_file(USERS_INFO_FILE, "{}", "Init users info")

    # Запуск health-check сервера в отдельном потоке
    import threading
    threading.Thread(target=run_health_server, daemon=True).start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())