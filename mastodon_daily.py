#!/usr/bin/env python3
"""Автопостинг дневной сводки в Mastodon (Fediverse). Берёт короткий текст из daily.json.

Секреты (GitHub Secrets), в коде их нет:
  MASTODON_URL    — база инстанса, напр. https://mastodon.social
  MASTODON_TOKEN  — access token приложения (scope: write:statuses, write:media)
Без секретов — сухой прогон. У Mastodon лимит статуса ~500 символов, поэтому постим короткий текст + картинку.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid

URL = (os.environ.get("MASTODON_URL") or "").rstrip("/")
TOKEN = os.environ.get("MASTODON_TOKEN")
SRC = os.environ.get("DAILY_JSON_URL", "https://ratescout.info.gf/daily.json")


def api(path, data=None, ctype=None):
    h = {"Authorization": f"Bearer {TOKEN}"}
    if ctype:
        h["Content-Type"] = ctype
    with urllib.request.urlopen(urllib.request.Request(URL + path, data=data, headers=h, method="POST"), timeout=60) as r:
        return json.load(r)


def upload_media(img):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\n".encode()
            + b'Content-Disposition: form-data; name="file"; filename="d.png"\r\n'
            + b"Content-Type: image/png\r\n\r\n" + img + b"\r\n" + f"--{b}--\r\n".encode())
    return api("/api/v2/media", data=body, ctype="multipart/form-data; boundary=" + b)["id"]


def main():
    try:
        with urllib.request.urlopen(SRC, timeout=30) as r:
            d = json.load(r)
    except Exception as e:                       # noqa: BLE001
        print(f"не удалось получить {SRC}: {e}")
        return 0
    if not d.get("has_data"):
        print("нет данных за сутки — публикация пропущена")
        return 0
    text = d.get("short") or d.get("caption", "")[:480]
    if not URL or not TOKEN:
        print("MASTODON_URL/MASTODON_TOKEN не заданы — сухой прогон (не публикую).\n--- пост ---")
        print(text)
        return 0
    fields = {"status": text}
    if d.get("image"):
        try:
            img = urllib.request.urlopen(d["image"], timeout=60).read()
            fields["media_ids[]"] = [upload_media(img)]
        except Exception as e:                   # noqa: BLE001
            print(f"медиа не загрузилось ({e}) — публикую без картинки")
    data = urllib.parse.urlencode(fields, doseq=True).encode()
    try:
        res = api("/api/v1/statuses", data=data, ctype="application/x-www-form-urlencoded")
        print("опубликовано:", res.get("url"))
        return 0
    except Exception as e:                        # noqa: BLE001
        print(f"ошибка публикации в Mastodon: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
