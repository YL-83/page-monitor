"""網頁監控(給 GitHub Actions 用)。

會通知的情況:
1. 🚨 頁面出現「可填密碼的表單」(註冊可能開放了)
2. 👀 頁面文字有任何變化
3. ⚠️ 抓不到頁面(連線失敗 / 被擋),只在剛開始失敗時通知一次
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://thisvid.com/signup/"
STATE_FILE = Path("state.json")

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def check() -> tuple[str, str, str]:
    """回傳 (狀態, 內容雜湊, 說明);狀態為 open / closed / error"""
    try:
        r = requests.get(URL, headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        return "error", "", f"連線失敗:{e}"
    if r.status_code != 200:
        return "error", "", f"HTTP {r.status_code}(可能擋了 GitHub 的 IP)"

    soup = BeautifulSoup(r.text, "html.parser")
    has_password_form = any(
        form.find("input", {"type": "password"}) for form in soup.find_all("form")
    )
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    digest = hashlib.sha256(text.encode()).hexdigest()
    if has_password_form:
        return "open", digest, "偵測到可填密碼的註冊表單"
    return "closed", digest, "目前沒有註冊表單"


def notify(msg: str) -> None:
    print(msg)
    sent = False
    try:
        if DISCORD_WEBHOOK:
            requests.post(
                DISCORD_WEBHOOK, json={"content": msg}, timeout=15
            ).raise_for_status()
            sent = True
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
                timeout=15,
            ).raise_for_status()
            sent = True
    except requests.RequestException as e:
        print("通知失敗:", e)
        sys.exit(1)  # 讓 workflow 顯示失敗,GitHub 也會寄信提醒你
    if not sent:
        print("(沒有設定通知管道,只印在 log)")


def main() -> None:
    status, digest, note = check()
    old = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else None
    print(f"狀態={status} 說明={note}")

    if old is None:
        notify(f"✅ 監控已啟動\n{URL}\n目前狀態:{status}({note})")
    elif status == "error":
        if old["status"] != "error":
            notify(f"⚠️ 抓不到頁面\n{note}\n{URL}")
    elif status == "open" and old["status"] != "open":
        notify(f"🚨 出現可填密碼的表單,註冊可能開放了!\n{URL}")
    elif old.get("hash") and digest != old["hash"]:
        extra = "(目前有註冊表單)" if status == "open" else ""
        notify(f"👀 網頁內容有變化{extra}\n{URL}")

    # 連線失敗時保留上次的雜湊,避免恢復後誤報
    new_hash = digest or (old or {}).get("hash", "")
    STATE_FILE.write_text(json.dumps({"status": status, "hash": new_hash}))


if __name__ == "__main__":
    main()
