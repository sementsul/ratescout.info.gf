#!/usr/bin/env python3
"""Тянет популярные поисковые запросы к сайту из Яндекс.Вебмастера (search-queries/popular) → yandex.json.

Официальный Webmaster API v4, тем же YANDEX_OAUTH_TOKEN, что и еженедельный отчёт (yandex_report.py) —
бесплатно и надёжно, без скрейпа и банов. Это реальный спрос из Яндекса: что люди вводят, чтобы найти сайт.
Секрет — только из окружения. Сбой — тихо пропускаем, сборка идёт без Яндекс-запросов.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("YANDEX_OAUTH_TOKEN")
HOST = os.environ.get("YANDEX_HOST") or "https://ratescout.info.gf"
WM = "https://api.webmaster.yandex.net/v4"


def _junk(q):
    """Отсеять не-запросы: URL/путь/бренд (не полезны как «спрос»)."""
    ql = (q or "").lower().strip()
    if not ql:
        return True
    if ql.startswith(("http", "www.", "/")):
        return True
    return "ratescout" in ql


def yget(url):
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    if not TOKEN:
        print("нет YANDEX_OAUTH_TOKEN — пропускаю"); return 0
    try:
        user_id = yget(f"{WM}/user")["user_id"]
        hosts = yget(f"{WM}/user/{user_id}/hosts")["hosts"]
        want = HOST.rstrip("/")
        host = next((h for h in hosts if h.get("ascii_host_url", "").rstrip("/") == want), None) or \
            next((h for h in hosts if want.split("//")[-1] in h.get("ascii_host_url", "")), None)
        host_id = host["host_id"]
        base = f"{WM}/user/{user_id}/hosts/{urllib.parse.quote(host_id, safe='')}"
        q = yget(f"{base}/search-queries/popular?order_by=TOTAL_SHOWS"
                 f"&query_indicator=TOTAL_SHOWS&query_indicator=TOTAL_CLICKS")
    except Exception as e:  # noqa: BLE001
        print(f"Яндекс.Вебмастер: ошибка {e} — пропускаю"); return 0

    queries = []
    for r in q.get("queries", []):
        ind = r.get("indicators", {}) or {}
        qt = r.get("query_text") or ""
        if _junk(qt):
            continue
        queries.append({"q": qt, "shows": ind.get("TOTAL_SHOWS"), "clicks": ind.get("TOTAL_CLICKS")})
    json.dump({"generated_at": int(time.time()), "queries": queries},
              open(os.path.join(ROOT, "yandex.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"yandex.json: {len(queries)} запросов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
