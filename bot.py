import asyncio
import base64
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import requests
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ==================== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
REPO_OWNER = os.getenv("REPO_OWNER", "bdtvyz76b6-blip")
REPO_NAME = os.getenv("REPO_NAME", "kainkov")
BRANCH = os.getenv("BRANCH", "main")

SERVERS_FILE = os.getenv("SERVERS_FILE", "servers.txt")
NO_SERVERS_FILE = os.getenv("NO_SERVERS_FILE", "no_servers.txt")
USERS_DIR = os.getenv("USERS_DIR", "users")
REVENUE_FILE = os.getenv("REVENUE_FILE", "revenue.txt")

TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "2"))

# Тарифы (цены в Telegram Stars)
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
        return [line.strip() for line in content.splitlines() if line.strip()]
    return []

def create_user_file(user_id: int, kind: str, servers: list[str], subscription_name: str, expire_date: datetime, traffic: str = "Unlimited") -> bool:
    path = get_user_file_path(user_id, kind)
    content_lines = servers + [
        "",
        f"Subscription: {subscription_name}",
        f"Expires: {expire_date.strftime('%Y-%m-%d')}",
        f"Traffic: {traffic}",
    ]
    content = "\n".join(content_lines)
    return github_put_file(path, content, f"User {user_id} {kind} subscription")

def parse_user_file(content: str) -> Optional[dict]:
    lines = content.splitlines()
    servers = []
    subscription_name = None
    expire_date = None
    traffic = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("Subscription:"):
            subscription_name = line.split(":", 1)[1].strip()
        elif line.startswith("Expires:"):
            date_str = line.split(":", 1)[1].strip()
            try:
                expire_date = datetime.strptime(date_str, "%Y-%m-%d")
            except:
                pass
        elif line.startswith("Traffic:"):
            traffic = line.split(":", 1)[1].strip()
        else:
            servers.append(line)
    if not servers or not subscription_name or not expire_date:
        return None
    return {
        "servers": servers,
        "subscription_name": subscription_name,
        "expire_date": expire_date,
        "traffic": traffic,
    }

async def check_and_cleanup_expired(user_id: int):
    paid_path = get_user_file_path(user_id, "paid")
    paid_content = github_get_file(paid_path)
    if paid_content:
        parsed = parse_user_file(paid_content)
        if parsed and parsed["expire_date"] < datetime.now():
            github_delete_file(paid_path, f"Expired paid subscription for user {user_id}")
            logging.info(f"Deleted expired paid subscription for user {user_id}")

    trial_path = get_user_file_path(user_id, "trial")
    trial_content = github_get_file(trial_path)
    if trial_content:
        parsed = parse_user_file(trial_content)
        if parsed and parsed["expire_date"] < datetime.now():
            github_put_file(trial_path, "expired", f"Trial expired for user {user_id}")
            logging.info(f"Marked trial as expired for user {user_id}")

async def has_active_subscription(user_id: int) -> bool:
    await check_and_cleanup_expired(user_id)
    paid_path = get_user_file_path(user_id, "paid")
    content = github_get_file(paid_path)
    if content:
        parsed = parse_user_file(content)
        if parsed and parsed["expire_date"] >= datetime.now():
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
        if parsed and parsed["expire_date"] >= datetime.now():
            return parsed
    trial_path = get_user_file_path(user_id, "trial")
    content = github_get_file(trial_path)
    if content and content != "expired":
        parsed = parse_user_file(content)
        if parsed and parsed["expire_date"] >= datetime.now():
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

async def get_user_stats() -> dict:
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/git/trees/{BRANCH}?recursive=1"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return {"error": "Не удалось получить список файлов"}
    data = resp.json()
    users_files = []
    for item in data.get("tree", []):
        path = item.get("path", "")
        if path.startswith(USERS_DIR + "/"):
            users_files.append(path)

    total_users = 0
    active_paid = 0
    active_trial = 0
    for fpath in users_files:
        fname = fpath.split("/")[-1]
        if fname.startswith("trial_"):
            total_users += 1
            content = github_get_file(fpath)
            if content and content != "expired":
                parsed = parse_user_file(content)
                if parsed and parsed["expire_date"] >= datetime.now():
                    active_trial += 1
        elif fname.startswith("paid_"):
            total_users += 1
            content = github_get_file(fpath)
            if content:
                parsed = parse_user_file(content)
                if parsed and parsed["expire_date"] >= datetime.now():
                    active_paid += 1

    revenue = get_revenue()
    return {
        "total_users": total_users,
        "active_paid": active_paid,
        "active_trial": active_trial,
        "revenue": revenue,
        "files_count": len(users_files),
    }

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
    if ADMIN_ID:
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

def admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="➕ Выдать подписку", callback_data="admin_give")
    builder.button(text="➖ Забрать подписку", callback_data="admin_revoke")
    builder.button(text="⬅️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Добро пожаловать в VPN бот!\n\n"
        "Здесь вы можете получить доступ к нашим серверам.\n"
        "Пробный период — 2 дня бесплатно.\n"
        "После вы можете оформить платную подписку.",
        reply_markup=main_keyboard()
    )

# ==================== CALLBACK-ОБРАБОТЧИКИ ====================
@dp.callback_query(F.data == "trial")
async def process_trial(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer()

    if await has_trial_used(user_id):
        await callback.message.answer("❌ Вы уже использовали пробный период.")
        return

    if await has_active_subscription(user_id):
        await callback.message.answer("✅ У вас уже есть активная платная подписка!")
        return

    servers = read_servers(NO_SERVERS_FILE)
    if not servers:
        await callback.message.answer("⚠️ Серверы временно недоступны, попробуйте позже.")
        return

    expire_date = datetime.now() + timedelta(days=TRIAL_DAYS)
    success = create_user_file(
        user_id=user_id,
        kind="trial",
        servers=servers,
        subscription_name="Trial",
        expire_date=expire_date,
    )
    if success:
        await callback.message.answer(
            f"🎉 Пробный период активирован!\n"
            f"Длительность: {TRIAL_DAYS} дня\n"
            f"Дата окончания: {expire_date.strftime('%Y-%m-%d')}\n\n"
            f"Серверы:\n" + "\n".join(servers)
        )
    else:
        await callback.message.answer("❌ Ошибка при активации пробного периода.")

@dp.callback_query(F.data == "buy")
async def process_buy(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Выберите тариф:",
        reply_markup=buy_keyboard()
    )

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy_tariff(callback: types.CallbackQuery):
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
        await message.answer("⚠️ Серверы временно недоступны, обратитесь в поддержку.")
        return

    expire_date = datetime.now() + timedelta(days=days)
    subscription_name = tariff.replace("_", " ").capitalize()
    success = create_user_file(
        user_id=user_id,
        kind="paid",
        servers=servers,
        subscription_name=subscription_name,
        expire_date=expire_date,
    )
    if success:
        update_revenue(price)
        await message.answer(
            f"✅ Подписка успешно оплачена и активирована!\n"
            f"Тариф: {subscription_name}\n"
            f"Срок: {days} дней\n"
            f"Дата окончания: {expire_date.strftime('%Y-%m-%d')}\n\n"
            f"Серверы:\n" + "\n".join(servers)
        )
    else:
        await message.answer("❌ Ошибка при создании подписки. Обратитесь в поддержку.")

@dp.callback_query(F.data == "my_sub")
async def process_my_sub(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer()

    info = await get_active_subscription_info(user_id)
    if info:
        await callback.message.answer(
            f"📋 Ваша подписка:\n"
            f"Название: {info['subscription_name']}\n"
            f"Действует до: {info['expire_date'].strftime('%Y-%m-%d')}\n"
            f"Трафик: {info['traffic']}\n\n"
            f"Серверы:\n" + "\n".join(info['servers'])
        )
    else:
        await callback.message.answer("У вас нет активной подписки.")

@dp.callback_query(F.data == "support")
async def process_support(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("По всем вопросам обращайтесь: @your_support_username")

@dp.callback_query(F.data == "back_main")
async def process_back_main(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_keyboard()
    )

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin")
async def process_admin(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "Админ-панель:",
        reply_markup=admin_keyboard()
    )

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    stats = await get_user_stats()
    if "error" in stats:
        await callback.message.answer(stats["error"])
        return
    text = (
        f"📊 Статистика:\n"
        f"Всего пользователей: {stats['total_users']}\n"
        f"Активных платных: {stats['active_paid']}\n"
        f"Активных пробных: {stats['active_trial']}\n"
        f"Общий доход: {stats['revenue']}⭐\n"
        f"Файлов в users/: {stats['files_count']}"
    )
    await callback.message.answer(text)

@dp.callback_query(F.data == "admin_give")
async def admin_give(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await callback.message.answer(
        "Введите команду:\n/give <user_id> <days>\nНапример: /give 123456789 30"
    )

@dp.callback_query(F.data == "admin_revoke")
async def admin_revoke(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await callback.message.answer(
        "Введите команду:\n/revoke <user_id>\nНапример: /revoke 123456789"
    )

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Неверный формат. Используйте: /give <user_id> <days>")
        return
    try:
        target_user_id = int(args[1])
        days = int(args[2])
    except:
        await message.answer("Неверные аргументы")
        return

    servers = read_servers(SERVERS_FILE)
    if not servers:
        await message.answer("Серверы не найдены")
        return

    expire_date = datetime.now() + timedelta(days=days)
    success = create_user_file(
        user_id=target_user_id,
        kind="paid",
        servers=servers,
        subscription_name=f"Manual {days} days",
        expire_date=expire_date,
    )
    if success:
        await message.answer(f"✅ Подписка выдана пользователю {target_user_id} на {days} дней.")
    else:
        await message.answer("❌ Ошибка выдачи подписки.")

@dp.message(Command("revoke"))
async def cmd_revoke(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Неверный формат. Используйте: /revoke <user_id>")
        return
    try:
        target_user_id = int(args[1])
    except:
        await message.answer("Неверный user_id")
        return

    paid_path = get_user_file_path(target_user_id, "paid")
    if github_delete_file(paid_path, f"Revoked by admin for user {target_user_id}"):
        await message.answer(f"✅ Подписка пользователя {target_user_id} отозвана.")
    else:
        await message.answer("❌ Ошибка отзыва подписки.")

# ==================== ЗАПУСК ====================
async def main():
    # Инициализация репозитория
    if not github_get_file(SERVERS_FILE):
        github_put_file(SERVERS_FILE, "# Список серверов", "Init servers.txt")
    if not github_get_file(NO_SERVERS_FILE):
        github_put_file(NO_SERVERS_FILE, "# Список серверов для пробного периода", "Init no_servers.txt")
    if not github_get_file(REVENUE_FILE):
        github_put_file(REVENUE_FILE, "0", "Init revenue.txt")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())