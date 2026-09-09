#!/usr/bin/env python3
"""Еженедельный отчёт Яндекса в Telegram: Вебмастер (индексация+запросы) + Метрика (трафик).

Оба API Яндекса авторизуются одним OAuth-токеном (в приложении на oauth.yandex.ru выдай оба доступа:
Вебмастер и Метрика). Отчёт уходит владельцу в личку (ALERT_CHAT_ID).

Секреты — ТОЛЬКО из окружения (в коде их нет):
  YANDEX_OAUTH_TOKEN   — OAuth-токен с доступами Вебмастер+Метрика
  YANDEX_METRIKA_COUNTER — id счётчика Метрики (по умолчанию 111586112)
  YANDEX_HOST          — хост в Вебмастере (по умолчанию https://ratescout.info.gf)
  TELEGRAM_TOKEN, ALERT_CHAT_ID — куда слать (тот же бот/чат, что у сторожа)
Без токена — сухой прогон (ничего не шлёт). Каждый под-запрос обёрнут: сбой одного не роняет весь отчёт.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TOKEN = os.environ.get("YANDEX_OAUTH_TOKEN")
# `or` — а не default в get(): незаданный секрет в CI приходит ПУСТОЙ строкой и затёр бы дефолт.
COUNTER = os.environ.get("YANDEX_METRIKA_COUNTER") or "111586112"
HOST = os.environ.get("YANDEX_HOST") or "https://ratescout.info.gf"
WM = "https://api.webmaster.yandex.net/v4"
MET = "https://api-metrika.yandex.net/stat/v1/data"


def yget(url):
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _last_value(hist):
    """Из [{date,value}] вернуть последнее значение; терпимо к разным обёрткам."""
    if isinstance(hist, dict):
        hist = hist.get("history") or hist.get("values") or []
    if not hist:
        return None
    last = hist[-1]
    return last.get("value") if isinstance(last, dict) else last


# --- Вебмастер ------------------------------------------------------------------------------------
def webmaster_report(stats):
    """stats — dict, куда складываем числа для сравнительного блока (insearch/clicks/shows)."""
    L = ["🔎 Яндекс.Вебмастер"]
    try:
        user_id = yget(f"{WM}/user")["user_id"]
    except Exception as e:                         # noqa: BLE001
        return "\n".join(L + [f"  н/д (user): {e}"])
    try:
        hosts = yget(f"{WM}/user/{user_id}/hosts")["hosts"]
        want = HOST.rstrip("/")
        host = next((h for h in hosts if h.get("ascii_host_url", "").rstrip("/") == want), None) or \
            next((h for h in hosts if want.split("//")[-1] in h.get("ascii_host_url", "")), None)
        host_id = host["host_id"]
    except Exception as e:                         # noqa: BLE001
        return "\n".join(L + [f"  н/д (hosts): {e}"])
    base = f"{WM}/user/{user_id}/hosts/{urllib.parse.quote(host_id, safe='')}"

    def sub(fn, label):
        try:
            return fn()
        except Exception as e:                     # noqa: BLE001
            return f"{label}: н/д ({str(e)[:60]})"

    def _summary():
        s = yget(f"{base}/summary")
        sqi = s.get("sqi", "?")
        probs = s.get("site_problems", {}) or {}
        pc = sum(v if isinstance(v, int) else 0 for v in probs.values()) if isinstance(probs, dict) else 0
        return f"ИКС: {sqi}" + (f" · проблем сайта: {pc}" if pc else "")
    L.append("  " + sub(_summary, "summary"))

    def _insearch():
        today = datetime.now(timezone.utc).date()
        frm = (today - timedelta(days=30)).isoformat()
        h = yget(f"{base}/search-urls/in-search/history?date_from={frm}&date_to={today.isoformat()}")
        v = _last_value(h)
        stats["insearch"] = v or 0
        return f"страниц в поиске: {v if v is not None else 0}" + \
               (" (Яндекс ещё не добавил в поиск — идёт обход)" if not v else "")
    L.append("  " + sub(_insearch, "in-search"))

    def _indexing():
        today = datetime.now(timezone.utc).date()
        frm = (today - timedelta(days=30)).isoformat()
        h = yget(f"{base}/indexing/history?date_from={frm}&date_to={today.isoformat()}"
                 f"&indexing_indicators=HTTP_2XX,HTTP_5XX")
        ind = h.get("indicators", {}) if isinstance(h, dict) else {}
        ok = sum(x.get("value", 0) for x in ind.get("HTTP_2XX", []))
        err = sum(x.get("value", 0) for x in ind.get("HTTP_5XX", []))
        return f"обход роботом (2XX за период): {ok}" + (f" · ошибки 5XX: {err}" if err else "")
    L.append("  " + sub(_indexing, "indexing"))

    def _queries():
        q = yget(f"{base}/search-queries/popular?order_by=TOTAL_SHOWS"
                 f"&query_indicator=TOTAL_SHOWS&query_indicator=TOTAL_CLICKS")
        rows = q.get("queries", [])
        stats["shows"] = sum((r.get("indicators", {}).get("TOTAL_SHOWS") or 0) for r in rows)
        stats["clicks"] = sum((r.get("indicators", {}).get("TOTAL_CLICKS") or 0) for r in rows)
        if not rows:
            return "топ-запросы: пока нет"
        out = ["  топ-запросы (показы·клики):"]
        for r in rows[:8]:
            ind = r.get("indicators", {})
            out.append(f"    {r.get('query_text','?')} — "
                       f"{ind.get('TOTAL_SHOWS','?')}·{ind.get('TOTAL_CLICKS','?')}")
        return "\n".join(out)
    L.append(sub(_queries, "  queries"))
    return "\n".join(L)


def gsc_totals():
    """Клики/показы Google Search Console за осевшую неделю (для сравнения). None — если нет ключа."""
    sa = os.environ.get("GSC_SA_JSON")
    if not sa:
        return None
    from google.oauth2 import service_account
    import google.auth.transport.requests
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    creds.refresh(google.auth.transport.requests.Request())
    site = os.environ.get("GSC_SITE") or "https://ratescout.info.gf/"
    today = datetime.now(timezone.utc).date()
    end = today - timedelta(days=3)
    start = end - timedelta(days=6)
    body = json.dumps({"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": []}).encode()
    url = f"https://www.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(site, safe='')}/searchAnalytics/query"
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r).get("rows", [])
    if rows:
        return rows[0].get("clicks", 0), rows[0].get("impressions", 0)
    return 0, 0


def compare_block(ystats):
    """Сравнительный блок Google vs Яндекс за 7 дней (поиск)."""
    try:
        g = gsc_totals()
    except Exception as e:                         # noqa: BLE001
        g = None
        print(f"gsc_totals: {e}")
    yc, ysh, yin = ystats.get("clicks", 0), ystats.get("shows", 0), ystats.get("insearch", 0)
    L = ["⚖️ Google vs Яндекс (7 дней, поиск)"]
    if g:
        L.append(f"  Клики:  Google {g[0]:.0f}  ·  Яндекс {yc:.0f}")
        L.append(f"  Показы: Google {g[1]:.0f}  ·  Яндекс {ysh:.0f}")
    else:
        L.append(f"  Яндекс: клики {yc:.0f} · показы {ysh:.0f}  (Google — нет ключа GSC)")
    L.append(f"  Страниц в поиске: Яндекс {yin:.0f}  ·  Google — см. отчёт GSC")
    return "\n".join(L)


# --- Метрика --------------------------------------------------------------------------------------
def _met(params):
    return yget(MET + "?" + urllib.parse.urlencode(params))


def metrika_report():
    L = ["📊 Яндекс.Метрика (7 дней)"]

    def sub(fn, label):
        try:
            return fn()
        except Exception as e:                     # noqa: BLE001
            return f"  {label}: н/д ({str(e)[:60]})"

    def _totals():
        cur = _met({"ids": COUNTER, "metrics": "ym:s:visits,ym:s:users",
                    "date1": "7daysAgo", "date2": "yesterday"})["totals"]
        prev = _met({"ids": COUNTER, "metrics": "ym:s:visits,ym:s:users",
                     "date1": "14daysAgo", "date2": "8daysAgo"})["totals"]
        def d(c, p):
            return "—" if not p else f"{(c-p)/p*100:+.0f}%"
        return (f"  Визиты: {cur[0]:.0f} ({d(cur[0], prev[0])})   "
                f"Посетители: {cur[1]:.0f} ({d(cur[1], prev[1])})")
    L.append(sub(_totals, "totals"))

    def _sources():
        d = _met({"ids": COUNTER, "metrics": "ym:s:visits", "dimensions": "ym:s:lastTrafficSource",
                  "date1": "7daysAgo", "date2": "yesterday", "sort": "-ym:s:visits", "limit": "5"})
        rows = d.get("data", [])
        if not rows:
            return "  источники: нет данных"
        out = ["  источники (визиты):"]
        for r in rows:
            out.append(f"    {r['dimensions'][0].get('name','?')} — {r['metrics'][0]:.0f}")
        return "\n".join(out)
    L.append(sub(_sources, "sources"))

    def _pages():
        d = _met({"ids": COUNTER, "metrics": "ym:s:pageviews", "dimensions": "ym:s:startURL",
                  "date1": "7daysAgo", "date2": "yesterday", "sort": "-ym:s:pageviews", "limit": "5"})
        rows = d.get("data", [])
        if not rows:
            return "  топ-страницы: нет данных"
        out = ["  топ-страницы (просмотры):"]
        for r in rows:
            u = r["dimensions"][0].get("name", "?").replace("https://ratescout.info.gf", "") or "/"
            out.append(f"    {u} — {r['metrics'][0]:.0f}")
        return "\n".join(out)
    L.append(sub(_pages, "pages"))
    return "\n".join(L)


def send_telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("ALERT_CHAT_ID")
    if not tok or not chat:
        print("Telegram не задан — отчёт не отправлен.\n" + text)
        return
    for i in range(0, len(text), 3900):
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[i:i + 3900],
                                       "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"https://api.telegram.org/bot{tok}/sendMessage", data=data, method="POST"), timeout=30)
        except Exception as ex:                    # noqa: BLE001
            print(f"ошибка отправки: {ex}")
    print("отчёт отправлен")


def main():
    if not TOKEN:
        print("YANDEX_OAUTH_TOKEN не задан — сухой прогон (Вебмастер+Метрика не запрашивались).")
        return 0
    ystats = {}
    wm = webmaster_report(ystats)
    text = compare_block(ystats) + "\n\n" + wm + "\n\n" + metrika_report()
    try:                                          # → Baserow (хаб статистики)
        import baserow
        tot = _met({"ids": COUNTER, "metrics": "ym:s:visits,ym:s:users,ym:s:pageviews,ym:s:bounceRate",
                    "date1": "7daysAgo", "date2": "yesterday"}).get("totals", [[None] * 4])[0]
        baserow.put_rows(baserow.stat_rows("ratescout", "Yandex", {
            "visits": tot[0], "users": tot[1], "pageviews": tot[2], "bounce_pct": tot[3]}))
    except Exception as _e:                        # noqa: BLE001
        print("baserow Yandex skip:", _e)
    print(text)
    send_telegram(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
