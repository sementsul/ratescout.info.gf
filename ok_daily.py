#!/usr/bin/env python3
"""Автопостинг дневной сводки курсов в ленту OK-группы (тот же daily.json, что VK/Telegram/Дзен).

Секреты (GitHub Secrets): OK_ACCESS_TOKEN (вечный), OK_APP_SECRET (session_secret_key), OK_GROUP_ID.
Без секретов — сухой прогон (печатает текст, не публикует). Запуск раз в день (ok.yml).
Пост в ленту группы через mediatopic.post: текст + картинка (если есть).
"""
import json
import os
import sys
import urllib.request

import ok_api

SRC = os.environ.get("DAILY_JSON_URL", "https://ratescout.info.gf/daily.json")


def main():
    try:
        with urllib.request.urlopen(SRC, timeout=30) as r:
            d = json.load(r)
    except Exception as e:                        # noqa: BLE001
        print(f"не удалось получить {SRC}: {e}")
        return 0
    if not d.get("has_data"):
        print("нет данных за сутки — публикация пропущена")
        return 0
    msg = d["caption"]
    if d.get("full_list"):                        # полный список текстом
        msg = msg + "\n\n" + d["full_list"]
        if len(msg) > 15800:
            msg = msg[:15800] + "\n…полный список: " + d.get("url", "")
    if not ok_api.TOKEN or not ok_api.GROUP:
        print("OK_ACCESS_TOKEN/OK_GROUP_ID не заданы — сухой прогон (не публикую).\n--- пост ---")
        print(msg)
        return 0
    token = None
    if d.get("image"):
        try:
            img = urllib.request.urlopen(urllib.request.Request(
                d["image"], headers={"User-Agent": ok_api.UA}), timeout=90).read()
            token = ok_api.upload_photo(img)
        except Exception as e:                    # noqa: BLE001
            print(f"фото в OK не загрузилось ({e}) — публикую без картинки")
    print(f"длина сообщения OK: {len(msg)} символов")
    try:
        res = ok_api.post_group(msg, photo_token=token)
        print(f"опубликовано в OK: {res}")
        return 0
    except Exception as e:                        # noqa: BLE001
        print(f"ошибка публикации в OK: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
