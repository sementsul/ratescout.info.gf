#!/usr/bin/env python3
"""Автопостинг дневной сводки в Blogger (Google Blogger API v3).

Секреты (GitHub Secrets), в коде их нет:
  BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN  — OAuth Desktop-приложения (scope blogger)
  BLOGGER_BLOG_ID  — числовой id блога
  BLOGGER_POST_ID  — (опц.) числовой id ОДНОГО поста, который обновляем на месте вместо создания новых.
                     Если пусто — скрипт создаёт пост и печатает его id: положи его в этот секрет,
                     дальше сводка будет ПЕРЕзаписывать один и тот же пост (один вечный URL).
Refresh-токен получается один раз (OAuth Playground), дальше CI сам меняет его на access-токен.
Без секретов — сухой прогон (печатает заголовок/HTML, не публикует).
"""
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

CID = os.environ.get("BLOGGER_CLIENT_ID")
CSEC = os.environ.get("BLOGGER_CLIENT_SECRET")
RTOK = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG = os.environ.get("BLOGGER_BLOG_ID")
PID = os.environ.get("BLOGGER_POST_ID")            # если задан — обновляем этот пост, а не плодим новые
SRC = os.environ.get("DAILY_JSON_URL", "https://ratescout.info.gf/daily.json")
# Стабильный заголовок вечного поста (не меняется по дням → стабильный URL и ранжирование).
# Можно переопределить секретом/переменной BLOGGER_POST_TITLE.
STABLE_TITLE = os.environ.get("BLOGGER_POST_TITLE", "Курсы криптовалют сегодня — сводка RateScout")


def access_token():
    data = urllib.parse.urlencode({"client_id": CID, "client_secret": CSEC,
                                   "refresh_token": RTOK, "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token",
                                                       data=data, method="POST"), timeout=30) as r:
        return json.load(r)["access_token"]


def _linkify(text):
    # обычные URL → кликабельные <a> (в HTML Blogger автолинка нет)
    return re.sub(r'(https?://[^\s<]+)', r'<a href="\1">\1</a>', text)


def _change_color(chg):
    c = chg.strip()
    if c.startswith("+"):
        return "#0a8a0a"   # рост — зелёный
    if c.startswith("-"):
        return "#c0392b"   # падение — красный
    return "#555"          # без изменения — серый


def render_full_list_table(fl):
    """Нижний блок «все валюты» из строк 'ТИКЕР: цена · изм% · обменников' → HTML-таблица.
    Стили только инлайновые (Blogger вырезает <style>). Неразобранные строки пропускаем."""
    heading = "Все валюты — цена USDT · изм. 24ч · обменников"
    rows = []
    for ln in fl.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("📋"):                       # строка-заголовок с количеством
            heading = s.lstrip("📋").strip().rstrip(":")
            continue
        if ": " not in s:
            continue
        tick, rest = s.split(": ", 1)
        cells = [p.strip() for p in rest.split(" · ")]
        if len(cells) != 3:                          # не наш формат — пропускаем
            continue
        price, chg, exch = cells
        bg = "#ffffff" if len(rows) % 2 == 0 else "#f7f7f7"
        rows.append(
            f'<tr style="background:{bg}">'
            f'<td style="padding:6px 10px;font-weight:600;white-space:nowrap">{html.escape(tick)}</td>'
            f'<td style="padding:6px 10px;text-align:right;white-space:nowrap">{html.escape(price)}</td>'
            f'<td style="padding:6px 10px;text-align:right;white-space:nowrap;color:{_change_color(chg)}">{html.escape(chg)}</td>'
            f'<td style="padding:6px 10px;text-align:right;white-space:nowrap;color:#777">{html.escape(exch)}</td>'
            f'</tr>')
    if not rows:
        return ""
    thead = ('<tr style="background:#eeeeee">'
             '<th style="padding:8px 10px;text-align:left;color:#222222;border-bottom:2px solid #cccccc">Валюта</th>'
             '<th style="padding:8px 10px;text-align:right;color:#222222;border-bottom:2px solid #cccccc">Цена, USDT</th>'
             '<th style="padding:8px 10px;text-align:right;color:#222222;border-bottom:2px solid #cccccc">Изм. 24ч</th>'
             '<th style="padding:8px 10px;text-align:right;color:#222222;border-bottom:2px solid #cccccc">Обменников</th>'
             '</tr>')
    return (f'<h3>{html.escape(heading)}</h3>'
            '<div style="overflow-x:auto">'
            '<table style="border-collapse:collapse;width:100%;font-size:14px;'
            'color:#222222;background:#ffffff;border:1px solid #dddddd">'
            f'<thead>{thead}</thead><tbody>{"".join(rows)}</tbody></table></div>')


def build_html(d):
    cap = _linkify(html.escape(d.get("caption", "")).replace("\n", "<br>"))
    img = f'<p><img src="{html.escape(d["image"])}" alt="Крипторынок за сутки" /></p>' if d.get("image") else ""
    parts = [img, f"<p>{cap}</p>"]
    if d.get("full_list"):
        parts.append(render_full_list_table(d["full_list"]))
    return "".join(parts)


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
    if not all([CID, CSEC, RTOK, BLOG]):
        print("Blogger-секреты не заданы — сухой прогон.\n--- заголовок ---")
        print(STABLE_TITLE)
        return 0
    body = json.dumps({"kind": "blogger#post", "title": STABLE_TITLE,
                       "content": build_html(d)}).encode()
    token = access_token()
    if PID:
        # ОБНОВЛЯЕМ существующий пост (один вечный URL, свежий контент)
        url = f"https://www.googleapis.com/blogger/v3/blogs/{BLOG}/posts/{PID}"
        method, action = "PATCH", "обновлён"
    else:
        # Первый раз: создаём пост и печатаем его id для секрета BLOGGER_POST_ID
        url = f"https://www.googleapis.com/blogger/v3/blogs/{BLOG}/posts/"
        method, action = "POST", "создан"
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            res = json.load(r)
        print(f"пост {action}:", res.get("url"))
        if not PID:
            print(f"⚠ ВАЖНО: положи этот id в GitHub-секрет BLOGGER_POST_ID — "
                  f"дальше пост будет обновляться, а не плодиться.\nBLOGGER_POST_ID = {res.get('id')}")
        return 0
    except Exception as e:                        # noqa: BLE001
        print(f"ошибка публикации в Blogger: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
