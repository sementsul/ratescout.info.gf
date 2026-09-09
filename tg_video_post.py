#!/usr/bin/env python3
"""Автопостинг роликов/картинок из репо my-many/promo в Telegram-канал: один элемент за запуск.
ВИДЕО и КАРТИНКИ (вперемешку, по имени). Очередь КРУГОВАЯ: после последнего — снова первый.
Подпись ЧЕРЕДУЕТСЯ: ratescout.info.gf → my-many.ru → по кругу.

Секреты (GitHub Secrets): TELEGRAM_TOKEN (бот, админ канала), TELEGRAM_CHANNEL (@username), GH_PAT.
Состояние — tg_posted.json {"last": <имя>, "count": N} (коммитит воркфлоу). DRY_RUN=1 — не публикует.
"""
import json
import os
import tempfile
import urllib.request
import uuid

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL = os.environ.get("TELEGRAM_CHANNEL")
DRY = os.environ.get("DRY_RUN") == "1"
API = f"https://api.telegram.org/bot{TOKEN}/" if TOKEN else None
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
REPO = "sementsul/my-many"
FOLDER = "promo"
STATE = "tg_posted.json"
VID_EXT = (".mp4", ".mov", ".webm", ".m4v")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")

CAP_RS = (os.environ.get("TG_CAPTION_RS") or "").strip() or (
    "Мониторинг курсов обмена и обменников — RateScout.\n"
    "Лучший курс на обмен крипты и валюты: https://ratescout.info.gf/?p=1116359")
CAP_MM = (os.environ.get("TG_CAPTION_MM") or "").strip() or (
    "MyMany — база выгодных цепочек обмена (арбитраж).\n"
    "Зарабатывай на разнице курсов, всё посчитано: https://my-many.ru/")


def caption_for(n):
    return CAP_RS if n % 2 == 0 else CAP_MM


def gh_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def list_media():
    items = gh_get(f"https://api.github.com/repos/{REPO}/contents/{FOLDER}")
    m = [(i["name"], i["download_url"]) for i in items
         if i.get("type") == "file" and i["name"].lower().endswith(VID_EXT + IMG_EXT)]
    m.sort(key=lambda x: x[0])
    return m


def load_state():
    try:
        d = json.load(open(STATE, encoding="utf-8"))
    except Exception:                            # noqa: BLE001
        return None, 0
    return d.get("last"), int(d.get("count", 0))


def download(url, suffix):
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r, \
            open(tmp.name, "wb") as f:
        f.write(r.read())
    return tmp.name


def send(method, fields, file_field, filename, ctype, data):
    """multipart POST в Telegram Bot API (sendVideo/sendPhoto)."""
    b = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    body += (f"--{b}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
             f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n" + f"--{b}--\r\n".encode()
    req = urllib.request.Request(API + method, data=body, method="POST", headers={
        "Content-Type": "multipart/form-data; boundary=" + b, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(res.get("description", res))
    return res["result"]


def main():
    media = list_media()
    if not media:
        print("в promo нет медиа.")
        return 0
    names = [n for n, _ in media]
    last, count = load_state()
    idx = (names.index(last) + 1) % len(names) if last in names else 0   # КРУГ: после последнего → первый
    force = os.environ.get("FORCE_NAME")                                 # тест: конкретный файл, очередь не трогаем
    if force and force in names:
        idx = names.index(force)
    name, url = media[idx]
    caption = caption_for(count)
    who = "ratescout.info.gf" if count % 2 == 0 else "my-many.ru"
    is_vid = name.lower().endswith(VID_EXT)
    kind = "видео" if is_vid else "картинка"
    print(f"медиа всего: {len(media)} | цикл-пост #{count} | след.[{idx}]: {name} ({kind}) | домен: {who}")
    print(f"подпись:\n{caption}\n")
    if DRY or not TOKEN or not CHANNEL:
        print("СУХОЙ ПРОГОН — не публикую." if DRY else "TELEGRAM_TOKEN/CHANNEL не заданы — сухой прогон.")
        json.dump({"total": len(media), "count": count, "next": name, "kind": kind, "domain": who,
                   "caption": caption}, open("tg_dryrun.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return 0
    try:
        path = download(url, ".mp4" if is_vid else ".jpg")
        with open(path, "rb") as f:
            data = f.read()
        if is_vid:
            r = send("sendVideo", {"chat_id": CHANNEL, "caption": caption, "supports_streaming": "true"},
                     "video", "v.mp4", "video/mp4", data)
        else:
            r = send("sendPhoto", {"chat_id": CHANNEL, "caption": caption},
                     "photo", "p.jpg", "image/jpeg", data)
        if not force:                            # форс-тест не двигает реальную очередь
            json.dump({"last": name, "count": count + 1}, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
        res = {"ok": True, "posted": name, "kind": kind, "domain": who,
               "message_id": r.get("message_id"), "forced": bool(force)}
        print(f"✅ опубликовано ({who}, {kind}): {name}")
    except Exception as e:                       # noqa: BLE001
        res = {"ok": False, "error": str(e), "next": name, "kind": kind}
        print(f"❌ ошибка публикации: {e}")
    json.dump(res, open("tg_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
