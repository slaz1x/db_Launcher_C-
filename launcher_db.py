import os
import json
import hashlib
import argparse
import secrets
import string
import subprocess
from datetime import datetime, timezone, timedelta

BRANCH = "baza"
DB_FILE = "launcher_C.json"

SUPPORTED_BOTS = {"fisher", "cleaner", "mine", "factory"}
SUPPORTED_PLANS = {"1d", "3d", "7d", "30d", "never"}

PLAN_TO_DELTA = {
    "1d": timedelta(days=1),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_expiry(value: str):
    if not value:
        return None
    if value.lower() == "never":
        return "never"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def plan_to_expiry(plan: str) -> str:
    plan = plan.strip().lower()
    if plan not in SUPPORTED_PLANS:
        raise ValueError(f"Недопустимый план: {plan}")

    if plan == "never":
        return "never"

    expires = now_utc() + PLAN_TO_DELTA[plan]
    return to_iso(expires)


def detect_repo_root():
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        shell=False
    )
    if result.returncode != 0:
        raise RuntimeError("Не удалось определить корень git-репозитория. Запусти скрипт внутри клона репозитория.")
    return result.stdout.strip()


REPO_DIR = detect_repo_root()
DB_PATH = os.path.join(REPO_DIR, DB_FILE)


def ensure_repo():
    if not os.path.isfile(DB_PATH):
        raise RuntimeError(f"Файл базы не найден: {DB_PATH}")


def load_db():
    ensure_repo()
    with open(DB_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {"users": []}

    if "users" not in data or not isinstance(data["users"], list):
        data["users"] = []

    return data


def save_db(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_password():
    alphabet = string.ascii_uppercase + string.digits
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def ensure_user_shape(user):
    if "bot_access" not in user or not isinstance(user["bot_access"], dict):
        user["bot_access"] = {}

    for bot in SUPPORTED_BOTS:
        value = user["bot_access"].get(bot, "")
        if not isinstance(value, str):
            value = ""
        value = value.strip()
        if value.lower() == "never":
            value = "never"
        elif value:
            parsed = parse_expiry(value)
            if parsed is None:
                value = ""
        user["bot_access"][bot] = value

    if "active" not in user:
        user["active"] = True
    if "expires_at" not in user:
        user["expires_at"] = "never"
    if "plan" not in user:
        user["plan"] = "Amazing Launcher"
    if "issued_at" not in user:
        user["issued_at"] = now_iso()

    return user


def find_user(db, login):
    for user in db["users"]:
        if user.get("login", "").lower() == login.lower():
            return user
    return None


def git_run(args):
    result = subprocess.run(
        args,
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
        shell=False
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Команда завершилась с ошибкой:\n{' '.join(args)}\n\nstdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
    return result.stdout.strip()


def git_sync(commit_message):
    git_run(["git", "checkout", BRANCH])
    git_run(["git", "pull", "origin", BRANCH])
    git_run(["git", "add", DB_FILE])

    status = git_run(["git", "status", "--porcelain"])
    if not status:
        print("[INFO] Изменений нет, commit/push не нужен.")
        return

    git_run(["git", "commit", "-m", commit_message])
    git_run(["git", "push", "origin", BRANCH])
    print("[OK] Изменения отправлены в GitHub.")


def add_user(login, hwid):
    db = load_db()

    if find_user(db, login):
        print(f"[ERROR] Пользователь '{login}' уже существует.")
        return

    password = generate_password()
    password_hash = hash_password(password)

    user = {
        "login": login,
        "password_hash": password_hash,
        "hwid": hwid,
        "issued_at": now_iso(),
        "expires_at": "never",
        "plan": "Amazing Launcher",
        "active": True,
        "bot_access": {
            "fisher": "",
            "cleaner": "",
            "mine": "",
            "factory": ""
        }
    }

    db["users"].append(user)
    save_db(db)
    git_sync(f"add user {login}")

    print("[OK] Пользователь добавлен.")
    print(f"login:    {login}")
    print(f"password: {password}")
    print(f"hwid:     {hwid}")


def set_hwid(login, hwid):
    db = load_db()
    user = find_user(db, login)

    if not user:
        print(f"[ERROR] Пользователь '{login}' не найден.")
        return

    ensure_user_shape(user)
    user["hwid"] = hwid
    save_db(db)
    git_sync(f"update hwid for {login}")
    print(f"[OK] HWID обновлен для {login}.")


def grant_bot(login, bot, plan):
    if bot not in SUPPORTED_BOTS:
        print(f"[ERROR] Неизвестный бот: {bot}")
        return

    plan = plan.strip().lower()
    if plan not in SUPPORTED_PLANS:
        print(f"[ERROR] Недопустимый план: {plan}")
        return

    db = load_db()
    user = find_user(db, login)

    if not user:
        print(f"[ERROR] Пользователь '{login}' не найден.")
        return

    ensure_user_shape(user)

    expiry_value = plan_to_expiry(plan)
    user["bot_access"][bot] = expiry_value

    save_db(db)
    git_sync(f"grant {bot} {plan} for {login}")

    print(f"[OK] Выдан доступ: {login} -> {bot}")
    print(f"[INFO] План: {plan}")
    print(f"[INFO] Истекает: {expiry_value}")


def revoke_bot(login, bot):
    if bot not in SUPPORTED_BOTS:
        print(f"[ERROR] Неизвестный бот: {bot}")
        return

    db = load_db()
    user = find_user(db, login)

    if not user:
        print(f"[ERROR] Пользователь '{login}' не найден.")
        return

    ensure_user_shape(user)
    user["bot_access"][bot] = ""
    save_db(db)
    git_sync(f"revoke {bot} for {login}")
    print(f"[OK] Доступ отключен: {login} -> {bot}")


def activate_user(login):
    db = load_db()
    user = find_user(db, login)

    if not user:
        print(f"[ERROR] Пользователь '{login}' не найден.")
        return

    ensure_user_shape(user)
    user["active"] = True
    save_db(db)
    git_sync(f"activate user {login}")
    print(f"[OK] Пользователь {login} активирован.")


def deactivate_user(login):
    db = load_db()
    user = find_user(db, login)

    if not user:
        print(f"[ERROR] Пользователь '{login}' не найден.")
        return

    ensure_user_shape(user)
    user["active"] = False
    save_db(db)
    git_sync(f"deactivate user {login}")
    print(f"[OK] Пользователь {login} деактивирован.")


def list_users():
    db = load_db()

    if not db["users"]:
        print("[INFO] База пуста.")
        return

    for i, raw_user in enumerate(db["users"], 1):
        user = ensure_user_shape(raw_user)
        bots = ", ".join(
            f"{bot}={user['bot_access'].get(bot, '') or '-'}"
            for bot in sorted(SUPPORTED_BOTS)
        )

        print(
            f"{i}. login={user.get('login')} | "
            f"hwid={user.get('hwid')} | "
            f"active={user.get('active')} | "
            f"expires_at={user.get('expires_at')} | "
            f"bots: {bots}"
        )


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    add_parser = sub.add_parser("add")
    add_parser.add_argument("--login", required=True)
    add_parser.add_argument("--hwid", required=True)

    hwid_parser = sub.add_parser("set-hwid")
    hwid_parser.add_argument("--login", required=True)
    hwid_parser.add_argument("--hwid", required=True)

    grant_parser = sub.add_parser("grant")
    grant_parser.add_argument("--login", required=True)
    grant_parser.add_argument("--bot", required=True, choices=sorted(SUPPORTED_BOTS))
    grant_parser.add_argument("--plan", required=True, choices=["1d", "3d", "7d", "30d", "never"])

    revoke_parser = sub.add_parser("revoke")
    revoke_parser.add_argument("--login", required=True)
    revoke_parser.add_argument("--bot", required=True, choices=sorted(SUPPORTED_BOTS))

    activate_parser = sub.add_parser("activate")
    activate_parser.add_argument("--login", required=True)

    deactivate_parser = sub.add_parser("deactivate")
    deactivate_parser.add_argument("--login", required=True)

    sub.add_parser("list")

    args = parser.parse_args()

    if args.command == "add":
        add_user(args.login, args.hwid)
    elif args.command == "set-hwid":
        set_hwid(args.login, args.hwid)
    elif args.command == "grant":
        grant_bot(args.login, args.bot, args.plan)
    elif args.command == "revoke":
        revoke_bot(args.login, args.bot)
    elif args.command == "activate":
        activate_user(args.login)
    elif args.command == "deactivate":
        deactivate_user(args.login)
    elif args.command == "list":
        list_users()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()