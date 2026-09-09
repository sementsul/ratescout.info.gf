#!/usr/bin/env python3
"""Отчёт Google Analytics (GA4) за 28 дней в Telegram (владельцу в личку).

Показывает за последние 28 дней (endDate=yesterday):
  • сеансы / пользователи / просмотры / вовлечённость / ср. длительность сеанса;
  • топ-10 страниц по просмотрам;
  • топ каналов привлечения (organic/direct/referral/…);
  • топ-5 стран.

Секреты — ТОЛЬКО из окружения (GitHub Secrets), в коде их нет:
  GA4_PROPERTY_ID  — числовой ID ресурса GA4 (Admin → Property settings → Property ID)
  GA_SA_JSON       — JSON сервис-аккаунта с доступом к GA4 (или переиспользуем GSC_SA_JSON,
                     добавив его client_email в GA4 → Property Access Management как Viewer)
  TELEGRAM_TOKEN   — тот же бот, что у GSC-отчёта
  ALERT_CHAT_ID    — id личного чата владельца с ботом
Без секретов — сухой прогон (печатает, что сделал бы, ничего не шлёт).
"""
import json
import os
import sys
import urllib.parse
import urllib.request

PROP = os.environ.get("GA4_PROPERTY_ID", "")
SA = os.environ.get("GA_SA_JSON") or os.environ.get("GSC_SA_JSON")
SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
API = "https://analyticsdata.googleapis.com/v1beta/properties/{pid}:batchRunReports"
DAYS = 28


def access_token(sa_json):
    from google.oauth2 import service_account
    import google.auth.transport.requests
    creds = service_account.Credentials.from_service_account_info(json.loads(sa_json), scopes=[SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _req(metrics, dimensions=None, limit=10, order_metric=None):
    r = {"dateRanges": [{"startDate": f"{DAYS}daysAgo", "endDate": "yesterday"}],
         "metrics": [{"name": m} for m in metrics], "limit": limit}
    if dimensions:
        r["dimensions"] = [{"name": d} for d in dimensions]
    if order_metric:
        r["orderBys"] = [{"metric": {"metricName": order_metric}, "desc": True}]
    return r


def batch(token):
    body = json.dumps({"requests": [
        _req(["sessions", "totalUsers", "screenPageViews", "engagementRate", "averageSessionDuration"]),
        _req(["screenPageViews"], ["pagePath"], 10, "screenPageViews"),
        _req(["sessions"], ["sessionDefaultChannelGroup"], 8, "sessions"),
        _req(["sessions"], ["country"], 5, "sessions"),
    ]}).encode()
    url = API.format(pid=PROP)
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("reports", [])


def rows(rep):
    return rep.get("rows", []) if rep else []


def mv(row, i=0):
    return row["metricValues"][i]["value"]


def dv(row, i=0):
    return row["dimensionValues"][i]["value"]


def dur(sec):
    sec = int(float(sec or 0))
    return f"{sec // 60}м {sec % 60}с"


def short(u):
    return (u or "/") if len(u or "/") <= 40 else u[:39] + "…"


def build_report():
    reps = batch(access_token(SA))
    tot = rows(reps[0])
    if not tot:
        return "GA4: нет данных за период (проверь Property ID и доступ сервис-аккаунта)."
    t = tot[0]
    sessions, users, views, eng, avgdur = (mv(t, i) for i in range(5))
    try:                                          # → Baserow (хаб статистики)
        import baserow
        baserow.put_rows(baserow.stat_rows("ratescout", "GA", {
            "sessions": sessions, "users": users, "pageviews": views,
            "engagement_pct": float(eng) * 100 if eng else None, "avg_session_sec": avgdur}))
    except Exception as _e:                        # noqa: BLE001
        print("baserow GA skip:", _e)
    L = [f"📊 Google Analytics — {DAYS} дней (ratescout.info.gf)", ""]
    L.append(f"👥 Пользователи: {users}   Сеансы: {sessions}")
    L.append(f"👁 Просмотры: {views}   Вовлечённость: {float(eng) * 100:.0f}%   Ср. сеанс: {dur(avgdur)}")

    pages = rows(reps[1])
    if pages:
        L += ["", "📄 Топ-страницы (просмотры):"]
        for r in pages:
            L.append(f"  {short(dv(r))} — {mv(r)}")

    ch = rows(reps[2])
    if ch:
        L += ["", "🚪 Каналы привлечения (сеансы):"]
        for r in ch:
            L.append(f"  {dv(r)} — {mv(r)}")

    co = rows(reps[3])
    if co:
        L += ["", "🌍 Топ страны (сеансы):"]
        for r in co:
            L.append(f"  {dv(r)} — {mv(r)}")
    return "\n".join(L)


def send_telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("ALERT_CHAT_ID")
    if not tok or not chat:
        print("TELEGRAM_TOKEN/ALERT_CHAT_ID не заданы — не отправляю.\n--- отчёт ---\n" + text)
        return
    for i in range(0, len(text), 3900):
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[i:i + 3900],
                                       "disable_web_page_preview": "true"}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://api.telegram.org/bot{tok}/sendMessage", data=data, method="POST"), timeout=30) as r:
                print("отправлено" if json.load(r).get("ok") else "ошибка ответа Telegram")
        except Exception as ex:                    # noqa: BLE001
            print(f"ошибка отправки: {ex}")


def main():
    if SA:                       # печатаем email SA (НЕ секрет) — его и надо добавить в GA4 как Viewer
        try:
            print("СЕРВИС-АККАУНТ (добавь его в GA4 → Viewer):", json.loads(SA).get("client_email"))
        except Exception:        # noqa: BLE001
            print("не смог прочитать client_email из SA-JSON")
    if not PROP or not SA:
        print("GA4_PROPERTY_ID или GA_SA_JSON/GSC_SA_JSON не заданы — сухой прогон.")
        print(f"PROPERTY_ID: {PROP or '(нет)'} · сервис-аккаунт: {'есть' if SA else 'нет'}")
        return 0
    try:
        report = build_report()
    except Exception as ex:                        # noqa: BLE001
        report = f"⚠️ GA4-отчёт не собрался: {ex}"
        print(report)
    send_telegram(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
