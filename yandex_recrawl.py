#!/usr/bin/env python3
"""Отправка ключевых страниц на переобход в Яндекс.Вебмастере (recrawl queue).

Помогает Яндексу быстрее взять важные страницы в поиск. У Вебмастера суточная квота на переобход —
скрипт шлёт курированный список важных URL и останавливается, когда квота кончилась.

Секрет — ТОЛЬКО из окружения: YANDEX_OAUTH_TOKEN (доступ Вебмастер). YANDEX_HOST опц. (по умолч. https://ratescout.info.gf).
Итог печатает в лог (для Actions) и, если заданы TELEGRAM_TOKEN+ALERT_CHAT_ID, шлёт краткую сводку владельцу.
Без токена — сухой прогон (печатает, что отправил бы).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("YANDEX_OAUTH_TOKEN")
HOST = (os.environ.get("YANDEX_HOST") or "https://ratescout.info.gf").rstrip("/")
WM = "https://api.webmaster.yandex.net/v4"

# Курированный список важных страниц (по убыванию значимости). Квота ограничит фактическую отправку.
KEY_PATHS = [
    "/",
    # исправленные страницы (дубли title/desc) — в приоритет на переобход
    "/sravnenie/", "/sravnenie/bitcoin-vs-ethereum/", "/sravnenie/bitcoin-vs-tether-trc20/",
    "/sravnenie/ethereum-vs-tether-trc20/", "/sravnenie/tether-trc20-vs-tether-bep20/",
    "/slovar/", "/blog/page/2/", "/blog/page/3/",
    "/napravleniya/", "/svodka/", "/grafiki/", "/kursy/", "/blog/",
    "/valuta/bitcoin/", "/valuta/tether-trc20/", "/valuta/ethereum/",
    "/valuta/tether-bep20/", "/valuta/monero/", "/valuta/tron/",
    "/obmen/tether-trc20-sberbank/", "/obmen/tether-trc20-tinkoff/", "/obmen/tether-trc20-sbp/",
    "/obmen/bitcoin-sberbank/", "/obmen/ethereum-sberbank/", "/obmen/tether-polygon-cash-ruble/",
    "/en/",
]


def yget(url):
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def recrawl(base, full_url):
    """POST в очередь переобхода. Возвращает (ok, инфо/остаток квоты)."""
    body = json.dumps({"url": full_url}).encode()
    req = urllib.request.Request(f"{base}/recrawl/queue", data=body, method="POST",
                                 headers={"Authorization": f"OAuth {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        return True, d.get("quota_remainder")
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)
        except Exception:                          # noqa: BLE001
            err = {"error_message": e.reason}
        return False, err.get("error_code") or err.get("error_message") or str(e.code)
    except Exception as e:                         # noqa: BLE001 — сеть/таймаут: не роняем весь прогон
        return False, f"сбой запроса: {str(e)[:80]}"


def send_telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("ALERT_CHAT_ID")
    if not tok or not chat:
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{tok}/sendMessage", data=data, method="POST"), timeout=30)
    except Exception:                              # noqa: BLE001
        pass


def main():
    if not TOKEN:
        print("YANDEX_OAUTH_TOKEN не задан — сухой прогон. Отправил бы на переобход:")
        for p in KEY_PATHS:
            print("  ", HOST + p)
        return 0
    user_id = yget(f"{WM}/user")["user_id"]
    hosts = yget(f"{WM}/user/{user_id}/hosts")["hosts"]
    want = HOST
    host = next((h for h in hosts if h.get("ascii_host_url", "").rstrip("/") == want), None) or \
        next((h for h in hosts if want.split("//")[-1] in h.get("ascii_host_url", "")), None)
    if not host:
        print(f"host не найден в Вебмастере: {HOST}")
        return 1
    base = f"{WM}/user/{user_id}/hosts/{urllib.parse.quote(host['host_id'], safe='')}"

    sent, failed, stop = 0, 0, False
    for p in KEY_PATHS:
        url = HOST + p
        ok, info = recrawl(base, url)
        if ok:
            sent += 1
            print(f"  ✅ {p}  (осталось квоты: {info})")
            if isinstance(info, int) and info <= 0:
                stop = True
        else:
            failed += 1
            print(f"  ⛔ {p}  → {info}")
            if str(info).upper().find("QUOTA") >= 0 or info in ("429",):
                stop = True
        if stop:
            print("  квота исчерпана — останавливаюсь.")
            break
    summary = f"♻️ Переобход Яндекс: отправлено {sent}, не удалось {failed} (из {len(KEY_PATHS)} ключевых URL)."
    print(summary)
    send_telegram(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
