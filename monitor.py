"""監控註冊頁是否開放,有變化就通知(給 GitHub Actions 用)。

判斷邏輯:
- open   : 頁面上出現含「密碼欄位」的表單 → 註冊可能開放了
- closed : 抓得到頁面,但沒有註冊表單
- error  : 連線失敗 / 被擋(403 等)
通知時機:狀態改變時;或在 closed 狀態下頁面文字有變動時(可關閉)。
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
NOTIFY_ON_TEXT_CHANGE = True  # 不想收到「文字有變動」通知就改成 False

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
    """回傳 (狀態, 內容雜湊, 說明)"""
    try:
        r = requests.get(URL, headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        return "error", "", f"連線失敗:{e}"
    if r.status_code != 200:
        return "error", "", f"HTTP {r.status_code}(可能擋了 GitHub 的 IP)"

    soup = BeautifulSoup(r.text, "html.parser")
    has_signup_form = any(
        form.find("input", {"type": "password"}) for form in soup.find_all("form")
    )
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    digest = hashlib.sha256(text.encode()).hexdigest()
    if has_signup_form:
        return "open", digest, "偵測到註冊表單"
    return "closed", digest, "目前沒有註冊表單"


def notify(msg: str) -> None:
    print(msg)
    sent = False
    try:
        if DISCORD_WEBHOOK:
            requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=15).raise_for_status()
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
    elif status != old["status"]:
        icon = "🚨" if status == "open" else "ℹ️"
        notify(f"{icon} 狀態變化:{old['status']} → {status}\n{note}\n{URL}")
    elif (
        NOTIFY_ON_TEXT_CHANGE
        and status == "closed"
        and digest
        and old.get("hash")
        and digest != old["hash"]
    ):
        notify(f"👀 頁面文字有變動(仍無註冊表單)\n{URL}")

    # error 時保留上次的 hash,避免暫時性失敗造成誤報
    new_hash = digest or (old or {}).get("hash", "")
    STATE_FILE.write_text(json.dumps({"status": status, "hash": new_hash}))


if __name__ == "__main__":
    main()
