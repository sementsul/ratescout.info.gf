#!/usr/bin/env python3
"""Сторож RateScout — раз в день проверяет здоровье проекта и зовёт человека ТОЛЬКО когда что-то не так.

Проверки (по живому сайту + репозиторию):
  1. Главная отвечает 200.
  2. sitemap.xml отвечает 200.
  3. dzen.xml (RSS для Дзена) отвечает 200 и содержит хотя бы один <item> (лента не пустая).
  4. Свежесть курсов: widget-data.json.updated не старше MAX_STALE_H часов
     (иначе почасовая пересборка/загрузка данных BestChange встала).
  5. Запас статей: сколько статей блога с release в будущем ещё не вышло; мало (< LOW_QUEUE) → пора дописать.

Поведение:
  • всё в порядке → печатает «OK», выходит 0 (тишина);
  • есть проблемы → шлёт алерт в личку владельцу в Telegram (если заданы TELEGRAM_TOKEN + ALERT_CHAT_ID)
    И выходит с кодом 1 — запуск в Actions становится красным, GitHub сам присылает письмо владельцу.
    То есть базовый алерт (письмо) работает даже без ALERT_CHAT_ID.

Секреты берутся ТОЛЬКО из окружения (GitHub Secrets), в коде их нет:
  TELEGRAM_TOKEN — тот же бот, что у каналов;  ALERT_CHAT_ID — id личного чата владельца с ботом.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.environ.get("BASE_URL", "https://ratescout.ru")
MAX_STALE_H = int(os.environ.get("MAX_STALE_H", "8"))     # курсы старше стольких часов = тревога
LOW_QUEUE = int(os.environ.get("LOW_QUEUE", "5"))          # статей в запасе меньше = пора писать
UA = {"User-Agent": "RateScout-Watchdog"}


def _get(path, timeout=30):
    """GET по абсолютному или относительному пути; возвращает (код, тело-строка)."""
    url = path if path.startswith("http") else BASE + path
    try:
        with urllib.request.urlopen(urllib.request.Request(url + ("&" if "?" in url else "?") + "wd=1",
                                                           headers=UA), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except Exception as e:                        # noqa: BLE001
        return None, str(e)


def check_page(path, name):
    code, _ = _get(path)
    return None if code == 200 else f"{name}: не 200 ({code})"


def check_feed():
    code, body = _get("/dzen.xml")
    if code != 200:
        return f"dzen.xml: не 200 ({code})"
    if "<item" not in body:
        return "dzen.xml: лента пустая (нет <item>)"
    return None


def check_freshness():
    code, body = _get("/widget-data.json")
    if code != 200:
        return f"widget-data.json: не 200 ({code})"
    try:
        upd = json.loads(body)["updated"]                 # "YYYY-MM-DD HH:MM UTC"
        dt = datetime.strptime(upd, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except Exception as e:                        # noqa: BLE001
        return f"widget-data.json: не разобрать updated ({e})"
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if age_h > MAX_STALE_H:
        return f"курсы устарели: обновлены {upd} ({age_h:.1f} ч назад > {MAX_STALE_H} ч) — почасовая сборка встала?"
    return None


def check_aml():
    """Санкционный список OFAC для /aml/ должен быть полным (защита от неполной загрузки)."""
    code, body = _get("/aml-sanctions.json")
    if code != 200:
        return f"aml-sanctions.json: не 200 ({code}) — AML-чек без списка"
    try:
        cnt = json.loads(body).get("count", 0)
    except Exception as e:                        # noqa: BLE001
        return f"aml-sanctions.json: не разобрать ({e})"
    if cnt < 500:
        return f"санкционный список OFAC неполный: {cnt} адресов (< 500) — AML-чек может врать «чисто»"
    print(f"  санкционный список OFAC: {cnt} адресов — ок")
    return None


def check_queue():
    """Считает статьи с release в будущем (запас дрип-публикации). Работает по checkout репозитория."""
    today = datetime.now(timezone.utc).date()
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "articles")
    if not os.path.isdir(d):
        return "articles/: папка не найдена"
    future = 0
    for f in os.listdir(d):
        if not f.endswith(".md"):
            continue
        m = re.search(r"release:\s*(\d{4}-\d{2}-\d{2})", open(os.path.join(d, f), encoding="utf-8").read())
        if m and datetime.strptime(m.group(1), "%Y-%m-%d").date() > today:
            future += 1
    if future < LOW_QUEUE:
        return f"запас статей на исходе: в очереди {future} (< {LOW_QUEUE}) — пора дописать блок статей"
    print(f"  запас статей: {future} в очереди — ок")
    return None


def alert(problems):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("ALERT_CHAT_ID")
    if not tok or not chat:
        print("  (ALERT_CHAT_ID не задан — Telegram-алерт пропущен, сработает письмо GitHub о падении)")
        return
    text = "🚨 RateScout — сторож нашёл проблемы:\n\n" + "\n".join("• " + p for p in problems) + \
           f"\n\nПроверено: {BASE}"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"https://api.telegram.org/bot{tok}/sendMessage", data=data, method="POST"), timeout=30) as r:
            ok = json.load(r).get("ok")
        print("  Telegram-алерт отправлен" if ok else "  Telegram-алерт: ошибка ответа")
    except Exception as e:                        # noqa: BLE001
        print(f"  Telegram-алерт: ошибка {e}")


def main():
    if os.environ.get("WATCHDOG_TEST"):
        print("ТЕСТ-АЛЕРТ (проверка доставки, не поломка):")
        alert(["Это тестовый алерт сторожа — если ты его видишь, оповещение в Telegram работает."])
        return 0
    checks = [
        check_page("/", "главная"),
        check_page("/sitemap.xml", "sitemap.xml"),
        check_feed(),
        check_freshness(),
        check_aml(),
        check_queue(),
    ]
    problems = [p for p in checks if p]
    if not problems:
        print("OK — все проверки пройдены, проблем нет.")
        return 0
    print("НАЙДЕНЫ ПРОБЛЕМЫ:")
    for p in problems:
        print("  •", p)
    alert(problems)
    return 1


if __name__ == "__main__":
    sys.exit(main())
