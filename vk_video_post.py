#!/usr/bin/env python3
"""Автопостинг контента из репо my-many/promo на стену VK-группы: один элемент за запуск.
Поддерживает ВИДЕО и КАРТИНКИ (вперемешку, по имени). Очередь КРУГОВАЯ: после последнего — снова первый.
Подпись ЧЕРЕДУЕТСЯ: ratescout.info.gf → my-many.ru → и по кругу.

Секреты (GitHub Secrets):
  VK_USER_TOKEN — пользовательский токен (video/photos/wall; сообщество фото/видео не грузит), бессрочный.
  VK_GROUP_ID   — числовой id группы (без минуса).
Состояние — vk_posted.json {"last": <имя>, "count": N} (коммитит воркфлоу). DRY_RUN=1 — не публикует.
"""
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

from vk_token import fresh_user_token   # свежий VK ID access из refresh (общий helper)

TOKEN = os.environ.get("VK_USER_TOKEN")
GROUP = os.environ.get("VK_GROUP_ID")
DRY = os.environ.get("DRY_RUN") == "1"
API = "https://api.vk.com/method/"
V = "5.199"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
REPO = "sementsul/my-many"
FOLDER = "promo"
STATE = "vk_posted.json"
VID_EXT = (".mp4", ".mov", ".webm", ".m4v")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")

CAP_RS = (os.environ.get("VK_CAPTION_RS") or "").strip() or (
    "Мониторинг курсов обмена и обменников — RateScout.\n"
    "Лучший курс на обмен крипты и валюты в одном месте: https://ratescout.info.gf/?p=1116359\n\n"
    "#обмен #криптовалюта #курсывалют #ratescout")
CAP_MM = (os.environ.get("VK_CAPTION_MM") or "").strip() or (
    "MyMany — база выгодных цепочек обмена (арбитраж).\n"
    "Зарабатывай на разнице курсов, всё посчитано: https://my-many.ru/\n\n"
    "#арбитраж #обмен #криптовалюта #mymany")


def caption_for(n):
    return CAP_RS if n % 2 == 0 else CAP_MM


def vk(method, params):
    p = dict(params)
    p["access_token"] = TOKEN
    p["v"] = V
    req = urllib.request.Request(API + method, data=urllib.parse.urlencode(p).encode(),
                                 method="POST", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.load(r)
    if "error" in res:
        raise RuntimeError(res["error"].get("error_msg", res["error"]))
    return res["response"]


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
    if "posted" in d and "last" not in d:        # миграция со старого формата (список)
        p = sorted(d.get("posted", []))
        return (p[-1] if p else None), len(p)
    return d.get("last"), int(d.get("count", 0))


def download(url, suffix):
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r, \
            open(tmp.name, "wb") as f:
        f.write(r.read())
    return tmp.name


def _multipart(field, filename, ctype, data):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\n".encode()
            + f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode()
            + f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n"
            + f"--{b}--\r\n".encode())
    return b, body


def upload_video(path, caption):
    saved = vk("video.save", {"group_id": GROUP, "name": "RateScout", "description": caption,
                              "wallpost": 0, "is_private": 0, "repeat": 0})
    with open(path, "rb") as f:
        data = f.read()
    b, body = _multipart("video_file", "v.mp4", "video/mp4", data)
    req = urllib.request.Request(saved["upload_url"], data=body, headers={
        "Content-Type": "multipart/form-data; boundary=" + b, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        r.read()
    return f"video{saved['owner_id']}_{saved['video_id']}"


def upload_image(path):
    up = vk("photos.getWallUploadServer", {"group_id": GROUP})
    with open(path, "rb") as f:
        data = f.read()
    b, body = _multipart("photo", "p.jpg", "image/jpeg", data)
    req = urllib.request.Request(up["upload_url"], data=body, headers={
        "Content-Type": "multipart/form-data; boundary=" + b, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        ur = json.load(r)
    saved = vk("photos.saveWallPhoto", {"group_id": GROUP, "server": ur["server"],
                                        "photo": ur["photo"], "hash": ur["hash"]})[0]
    return f"photo{saved['owner_id']}_{saved['id']}"


def main():
    global TOKEN
    media = list_media()
    if not media:
        print("в promo нет медиа.")
        return 0
    names = [n for n, _ in media]
    last, count = load_state()
    idx = (names.index(last) + 1) % len(names) if last in names else 0   # КРУГ: после последнего → первый
    name, url = media[idx]
    caption = caption_for(count)
    who = "ratescout.info.gf" if count % 2 == 0 else "my-many.ru"
    kind = "видео" if name.lower().endswith(VID_EXT) else "картинка"
    print(f"медиа всего: {len(media)} | цикл-пост #{count} | след.[{idx}]: {name} ({kind}) | домен: {who}")
    print(f"подпись:\n{caption}\n")
    if not DRY:                                  # для реальной публикации берём свежий VK ID access из refresh
        try:
            fresh = fresh_user_token()           # None, если refresh-секретов нет
        except Exception as e:                   # noqa: BLE001
            fresh = None
            print(f"❗ обновление токена из VK ID refresh не удалось ({type(e).__name__}: {e}) — пробую VK_USER_TOKEN")
        if fresh:
            TOKEN = fresh
            print("токен: свежий VK ID access из refresh")
        elif TOKEN:
            print("токен: статичный VK_USER_TOKEN (refresh-секретов нет; VK ID access живёт ~1ч → может протухнуть).")
    if DRY or not TOKEN or not GROUP:
        print("СУХОЙ ПРОГОН — не публикую." if DRY else "VK_USER_TOKEN/VK_GROUP_ID не заданы — сухой прогон.")
        json.dump({"total": len(media), "count": count, "next": name, "kind": kind, "domain": who,
                   "caption": caption}, open("vk_dryrun.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return 0
    try:
        if name.lower().endswith(VID_EXT):
            att = upload_video(download(url, ".mp4"), caption)
        else:
            att = upload_image(download(url, ".jpg"))
        post = vk("wall.post", {"owner_id": "-" + str(GROUP), "from_group": 1,
                                "message": caption, "attachments": att})
        json.dump({"last": name, "count": count + 1}, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
        res = {"ok": True, "posted": name, "kind": kind, "domain": who, "att": att,
               "post_id": post.get("post_id")}
        print(f"✅ опубликовано ({who}, {kind}): {name} ({att})")
    except Exception as e:                       # noqa: BLE001
        res = {"ok": False, "error": str(e), "next": name, "kind": kind}
        print(f"❌ ошибка публикации: {e}")
    json.dump(res, open("vk_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
