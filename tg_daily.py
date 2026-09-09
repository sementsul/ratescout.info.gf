#!/usr/bin/env python3
"""Публикация дневного дайджеста курсов в Telegram-канал.

Берёт готовый дайджест с боевого сайта (dist/daily.json, который генерит build.py) и постит в канал
через Telegram Bot API. Токен и канал — ТОЛЬКО из окружения (GitHub Secrets), в коде их нет.

Секреты (Settings → Secrets and variables → Actions):
  TELEGRAM_TOKEN    — токен бота от @BotFather
  TELEGRAM_CHANNEL  — @username канала (бот должен быть его администратором)

Без секретов — «сухой» прогон: печатает дайджест, ничего не публикует. Запускается раз в день (tg.yml).
"""
import json
import os
import sys
import urllib.parse
import urllib.request

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL = os.environ.get("TELEGRAM_CHANNEL")
SRC = os.environ.get("DAILY_JSON_URL", "https://ratescout.info.gf/daily.json")


def main():
    try:
        with urllib.request.urlopen(SRC, timeout=30) as r:
            d = json.load(r)
    except Exception as e:                      # noqa: BLE001 — сеть/парсинг, не валим воркфлоу
        print(f"не удалось получить {SRC}: {e}")
        return 0
    if not d.get("has_data"):
        print("нет данных за сутки — публикация пропущена")
        return 0
    caption = d["caption"]
    if not TOKEN or not CHANNEL:
        print("TELEGRAM_TOKEN/TELEGRAM_CHANNEL не заданы — сухой прогон (не публикую).\n--- дайджест ---")
        print(caption)
        return 0
    api = f"https://api.telegram.org/bot{TOKEN}/"
    if d.get("image"):
        method = "sendPhoto"
        payload = {"chat_id": CHANNEL, "photo": d["image"], "caption": caption}
    else:
        method = "sendMessage"
        payload = {"chat_id": CHANNEL, "text": caption, "disable_web_page_preview": "true"}
    if d.get("buttons"):                        # инлайн-кнопки-ссылки (обзор/приложение/графики/курсы)
        payload["reply_markup"] = json.dumps({"inline_keyboard": d["buttons"]})
    req = urllib.request.Request(api + method, data=urllib.parse.urlencode(payload).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
        print("опубликовано" if res.get("ok") else f"ошибка Telegram: {res}")
    except Exception as e:                      # noqa: BLE001
        print(f"ошибка отправки: {e}")
        return 1
    # полный список всех валют — текстом, разбитым на сообщения (в 4096 символов 330 строк не помещаются)
    fl = d.get("full_list")
    if fl:
        chunks, cur = [], ""
        for line in fl.split("\n"):
            if len(cur) + len(line) + 1 > 3900:
                chunks.append(cur)
                cur = ""
            cur += line + "\n"
        if cur.strip():
            chunks.append(cur)
        for i, ch in enumerate(chunks, 1):
            mp = {"chat_id": CHANNEL, "text": ch, "disable_web_page_preview": "true"}
            try:
                rr = urllib.request.Request(api + "sendMessage",
                                            data=urllib.parse.urlencode(mp).encode(), method="POST")
                with urllib.request.urlopen(rr, timeout=30) as r:
                    r2 = json.load(r)
                print(f"список {i}/{len(chunks)}: " + ("ок" if r2.get("ok") else f"ошибка {r2}"))
            except Exception as e:              # noqa: BLE001
                print(f"список {i} не отправлен: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
