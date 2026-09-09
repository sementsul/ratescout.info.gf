#!/usr/bin/env python3
"""Авто-анонс новой статьи блога в день её выхода — в Telegram, ВК и Mastodon (со ссылкой).

Берёт article-today.json с боевого сайта (генерит build.py). Постит в те площадки, чьи секреты заданы.
Секреты (GitHub Secrets), в коде их нет:
  Telegram: TELEGRAM_TOKEN, TELEGRAM_CHANNEL
  VK:       VK_TOKEN, VK_GROUP_ID
  Mastodon: MASTODON_URL, MASTODON_TOKEN
Дзен получает саму статью через RSS-ленту — отдельный анонс не нужен. Без данных/секретов — пропуск/сухой прогон.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid

SRC = os.environ.get("ARTICLE_JSON_URL", "https://ratescout.info.gf/article-today.json")


def _post(url, data, ctype="application/x-www-form-urlencoded", headers=None):
    h = {"Content-Type": ctype}
    if headers:
        h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method="POST"), timeout=60) as r:
        return json.load(r)


def announce_telegram(d):
    tok, chan = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHANNEL")
    if not tok or not chan:
        return "TG: секретов нет"
    cap = f"📰 Новая статья: {d['title']}\n\n{d['excerpt']}\n\nЧитать → {d['url']}\n\n#крипта #обмен #статья"
    payload = {"chat_id": chan, "photo": d.get("image"), "caption": cap,
               "reply_markup": json.dumps({"inline_keyboard": [[{"text": "📖 Читать статью", "url": d["url"]}]]})}
    try:
        r = _post(f"https://api.telegram.org/bot{tok}/sendPhoto", urllib.parse.urlencode(payload).encode())
        return "TG: ок" if r.get("ok") else f"TG: {r}"
    except Exception as e:                        # noqa: BLE001
        return f"TG: ошибка {e}"


def announce_vk(d):
    tok, grp = os.environ.get("VK_TOKEN"), os.environ.get("VK_GROUP_ID")
    if not tok or not grp:
        return "VK: секретов нет"
    msg = f"📰 Новая статья: {d['title']}\n\n{d['excerpt']}\n\n{d['url']}"
    p = {"owner_id": "-" + str(grp), "from_group": 1, "message": msg,
         "access_token": tok, "v": "5.199"}
    try:
        r = _post("https://api.vk.com/method/wall.post", urllib.parse.urlencode(p).encode())
        return "VK: ок" if "response" in r else f"VK: {r.get('error')}"
    except Exception as e:                        # noqa: BLE001
        return f"VK: ошибка {e}"


def announce_mastodon(d):
    base, tok = (os.environ.get("MASTODON_URL") or "").rstrip("/"), os.environ.get("MASTODON_TOKEN")
    if not base or not tok:
        return "Mastodon: секретов нет"
    text = f"📰 {d['title']}\n{d['url']}\n#крипта #обмен"[:490]
    try:
        r = _post(base + "/api/v1/statuses", urllib.parse.urlencode({"status": text}).encode(),
                  headers={"Authorization": f"Bearer {tok}"})
        return f"Mastodon: {r.get('url', 'ок')}"
    except Exception as e:                        # noqa: BLE001
        return f"Mastodon: ошибка {e}"


def announce_owner(d):
    """Личный пинг владельцу в день выхода статьи (в дополнение к постам в каналы)."""
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("ALERT_CHAT_ID")
    if not tok or not chat:
        return "Owner: чата нет"
    text = f"📣 Сегодня вышла статья:\n{d['title']}\n{d['url']}\n\nАнонс отправлен в каналы."
    try:
        r = _post(f"https://api.telegram.org/bot{tok}/sendMessage",
                  urllib.parse.urlencode({"chat_id": chat, "text": text,
                                          "disable_web_page_preview": "true"}).encode())
        return "Owner: ок" if r.get("ok") else f"Owner: {r}"
    except Exception as e:                        # noqa: BLE001
        return f"Owner: ошибка {e}"


def main():
    try:
        with urllib.request.urlopen(SRC, timeout=30) as r:
            d = json.load(r)
    except Exception as e:                        # noqa: BLE001
        print(f"не удалось получить {SRC}: {e}")
        return 0
    if not d.get("has_data"):
        print("сегодня новой статьи нет — анонс пропущен")
        return 0
    print(f"анонс: {d['title']}")
    for fn in (announce_telegram, announce_vk, announce_mastodon, announce_owner):
        print(" ", fn(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
