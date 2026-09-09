#!/usr/bin/env python3
"""Автопостинг контента из репо my-many/promo в ленту OK-группы: один элемент за запуск.
ВИДЕО и КАРТИНКИ (вперемешку, по имени). Очередь КРУГОВАЯ: после последнего — снова первый.
Подпись ЧЕРЕДУЕТСЯ: ratescout.info.gf → my-many.ru → по кругу.

Секреты (GitHub Secrets): OK_ACCESS_TOKEN (вечный), OK_APP_SECRET (session_secret_key), OK_GROUP_ID.
Состояние — ok_posted.json {"last": <имя>, "count": N} (коммитит воркфлоу). DRY_RUN=1 — не публикует.
"""
import json
import os
import tempfile
import urllib.request

import ok_api

DRY = os.environ.get("DRY_RUN") == "1"
UA = ok_api.UA
REPO = "sementsul/my-many"
FOLDER = "promo"
STATE = "ok_posted.json"
VID_EXT = (".mp4", ".mov", ".webm", ".m4v")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")

CAP_RS = (os.environ.get("OK_CAPTION_RS") or "").strip() or (
    "Мониторинг курсов обмена и обменников — RateScout.\n"
    "Лучший курс на обмен крипты и валюты в одном месте: https://ratescout.info.gf/?p=1116359\n\n"
    "#обмен #криптовалюта #курсывалют #ratescout")
CAP_MM = (os.environ.get("OK_CAPTION_MM") or "").strip() or (
    "MyMany — база выгодных цепочек обмена (арбитраж).\n"
    "Зарабатывай на разнице курсов, всё посчитано: https://my-many.ru/\n\n"
    "#арбитраж #обмен #криптовалюта #mymany")


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


def main():
    media = list_media()
    if not media:
        print("в promo нет медиа.")
        return 0
    names = [n for n, _ in media]
    last, count = load_state()
    idx = (names.index(last) + 1) % len(names) if last in names else 0   # КРУГ: после последнего → первый
    force = os.environ.get("FORCE_NAME")                                 # тест: запостить конкретный файл
    if force and force in names:
        idx = names.index(force)
    name, url = media[idx]
    caption = caption_for(count)
    who = "ratescout.info.gf" if count % 2 == 0 else "my-many.ru"
    kind = "видео" if name.lower().endswith(VID_EXT) else "картинка"
    print(f"медиа всего: {len(media)} | цикл-пост #{count} | след.[{idx}]: {name} ({kind}) | домен: {who}")
    print(f"подпись:\n{caption}\n")
    if DRY or not ok_api.TOKEN or not ok_api.GROUP:
        print("СУХОЙ ПРОГОН — не публикую." if DRY else "OK_ACCESS_TOKEN/OK_GROUP_ID не заданы — сухой прогон.")
        json.dump({"total": len(media), "count": count, "next": name, "kind": kind, "domain": who,
                   "caption": caption}, open("ok_dryrun.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return 0
    try:
        if name.lower().endswith(VID_EXT):
            vid = ok_api.upload_video(download(url, ".mp4"), name="RateScout")
            res_post = ok_api.post_group(caption, video_id=vid)
        else:
            with open(download(url, ".jpg"), "rb") as f:
                token = ok_api.upload_photo(f.read())
            res_post = ok_api.post_group(caption, photo_token=token)
        if not force:                            # форс-тест не двигает реальную очередь
            json.dump({"last": name, "count": count + 1}, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
        res = {"ok": True, "posted": name, "kind": kind, "domain": who, "topic": res_post, "forced": bool(force)}
        print(f"✅ опубликовано ({who}, {kind}): {name}")
    except Exception as e:                       # noqa: BLE001
        res = {"ok": False, "error": str(e), "next": name, "kind": kind}
        print(f"❌ ошибка публикации: {e}")
    json.dump(res, open("ok_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
