#!/usr/bin/env python3
"""Аудит настройки Google Search Console и Яндекс.Вебмастера через API (только чтение).

Снимает фактическое состояние обоих кабинетов, чтобы точно знать, что уже настроено, а что докрутить:
  GSC:    список sitemap (когда отправлен, ошибки/предупреждения, сколько URL).
  Яндекс: подтверждение хоста, главное зеркало, список sitemap, число проблем сайта (диагностика).
Ничего не меняет. Итог — в лог (для Actions) и краткая сводка владельцу в Telegram (опц.).

Секреты — ТОЛЬКО из окружения: GSC_SA_JSON, GSC_SITE, YANDEX_OAUTH_TOKEN, YANDEX_HOST,
TELEGRAM_TOKEN, ALERT_CHAT_ID. Чего нет — тот блок помечается «нет ключа».
"""
import json
import os
import sys
import urllib.parse
import urllib.request

GSC_SITE = os.environ.get("GSC_SITE") or "https://ratescout.ru/"
Y_HOST = (os.environ.get("YANDEX_HOST") or "https://ratescout.ru").rstrip("/")
WM = "https://api.webmaster.yandex.net/v4"


def gsc_audit():
    sa = os.environ.get("GSC_SA_JSON")
    if not sa:
        return ["🔵 Google Search Console: нет ключа GSC_SA_JSON"]
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        url = f"https://www.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(GSC_SITE, safe='')}/sitemaps"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {creds.token}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            sm = json.load(r).get("sitemap", [])
    except Exception as e:                         # noqa: BLE001
        return [f"🔵 Google Search Console: ошибка API — {str(e)[:100]}"]
    L = ["🔵 Google Search Console"]
    if not sm:
        L.append("  ⚠️ sitemap НЕ отправлен — добавь https://ratescout.ru/sitemap.xml в Sitemaps")
        return L
    for s in sm:
        cnt = sum(int(c.get("submitted", 0)) for c in s.get("contents", []))
        L.append(f"  sitemap {s.get('path','?').replace('https://ratescout.ru','')}: "
                 f"URL {cnt}, ошибок {s.get('errors',0)}, предупр. {s.get('warnings',0)}, "
                 f"последняя отправка {s.get('lastSubmitted','?')[:10]}")
    return L


def _yget(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def yandex_audit():
    token = os.environ.get("YANDEX_OAUTH_TOKEN")
    if not token:
        return ["🟡 Яндекс.Вебмастер: нет ключа YANDEX_OAUTH_TOKEN"]
    try:
        uid = _yget(f"{WM}/user", token)["user_id"]
        hosts = _yget(f"{WM}/user/{uid}/hosts", token)["hosts"]
        host = next((h for h in hosts if h.get("ascii_host_url", "").rstrip("/") == Y_HOST), None) or \
            next((h for h in hosts if Y_HOST.split("//")[-1] in h.get("ascii_host_url", "")), None)
        hid = host["host_id"]
        base = f"{WM}/user/{uid}/hosts/{urllib.parse.quote(hid, safe='')}"
    except Exception as e:                         # noqa: BLE001
        return [f"🟡 Яндекс.Вебмастер: ошибка API — {str(e)[:100]}"]
    L = ["🟡 Яндекс.Вебмастер"]
    L.append(f"  подтверждён: {host.get('verified')}   главное зеркало: "
             f"{(host.get('main_mirror') or {}).get('ascii_host_url', host.get('ascii_host_url','?'))}")

    def one(fn, lbl):
        try:
            return fn()
        except Exception as e:                     # noqa: BLE001
            return f"  {lbl}: н/д ({str(e)[:50]})"

    def _sm():
        sm = _yget(f"{base}/sitemaps", token).get("sitemaps", [])
        if not sm:
            return "  ⚠️ sitemap не зарегистрирован — добавь в «Файлы Sitemap»"
        return "  sitemap: " + "; ".join(f"{s.get('sitemap_url','?').replace('https://ratescout.ru','')}"
                                         f" (URL {s.get('urls_count','?')})" for s in sm[:3])
    L.append(one(_sm, "sitemaps"))

    def _sum():
        s = _yget(f"{base}/summary", token)
        probs = s.get("site_problems", {}) or {}
        parts = ", ".join(f"{k}:{v}" for k, v in probs.items()) if isinstance(probs, dict) else str(probs)
        return f"  ИКС: {s.get('sqi','?')}   проблемы диагностики: {parts or 'нет'}"
    L.append(one(_sum, "summary"))
    return L


def send_telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("ALERT_CHAT_ID")
    if not tok or not chat:
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{tok}/sendMessage", data=data, method="POST"), timeout=30)
    except Exception:                              # noqa: BLE001
        pass


def main():
    text = "🔧 Аудит SEO-кабинетов\n\n" + "\n".join(gsc_audit()) + "\n\n" + "\n".join(yandex_audit())
    print(text)
    send_telegram(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
