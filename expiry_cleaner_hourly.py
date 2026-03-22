import os
import json
import subprocess
from datetime import datetime, timezone

BRANCH = "baza"
DB_FILE = "launcher_C.json"
SUPPORTED_BOTS = {"fisher", "cleaner", "mine", "factory"}


def now_utc():
    return datetime.now(timezone.utc)


def parse_expiry(value: str):
    if not value:
        return None
    if value.lower() == "never":
        return "never"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def load_db():
    if not os.path.isfile(DB_PATH):
        raise RuntimeError(f"Файл базы не найден: {DB_PATH}")

    with open(DB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "users" not in data or not isinstance(data["users"], list):
        data["users"] = []

    return data


def save_db(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
        print("[INFO] Изменений нет.")
        return

    git_run(["git", "commit", "-m", commit_message])
    git_run(["git", "push", "origin", BRANCH])
    print("[OK] Истекшие доступы очищены и отправлены в GitHub.")


def clean_expired():
    db = load_db()
    now = now_utc()
    changed = False

    for user in db["users"]:
        bot_access = user.get("bot_access")
        if not isinstance(bot_access, dict):
            continue

        for bot in SUPPORTED_BOTS:
            value = bot_access.get(bot, "")
            if not isinstance(value, str) or not value:
                continue

            parsed = parse_expiry(value)
            if parsed is None:
                continue
            if parsed == "never":
                continue

            if now >= parsed:
                bot_access[bot] = ""
                changed = True
                print(f"[EXPIRED] login={user.get('login')} bot={bot} expired_at={value}")

    if not changed:
        print("[INFO] Истекших доступов не найдено.")
        return

    save_db(db)
    git_sync("auto clear expired bot access hourly")


if __name__ == "__main__":
    clean_expired()