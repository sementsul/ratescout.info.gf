#!/usr/bin/env python3
"""Рекомендации по SEO на основе запросов Google Search Console.

Берёт запросы из GSC, сопоставляет каждый с каталогом (валюта + получатель по словарю синонимов),
проверяет наличие реального курса и уже существующей страницы, и выдаёт РЕКОМЕНДАЦИИ:
  • СОЗДАТЬ  — по запросу есть спрос (показы) и реальный курс, но страницы-направления ещё нет;
  • УСИЛИТЬ  — страница есть, но она на 2-й странице выдачи (поз. 8–20) — доработать/перелинковать.
Ничего не публикует и не меняет автоматически — только советует. Решение за человеком (дисциплина CLAUDE.md).

Вывод: Markdown-файл SEO_OUT (для артефакта workflow) + компактная сводка владельцу в Telegram.
Секреты — ТОЛЬКО из окружения (в коде нет): GSC_SA_JSON, GSC_SITE, TELEGRAM_TOKEN, ALERT_CHAT_ID.
Без GSC_SA_JSON — сухой прогон на примерах (проверка сопоставления), без сети.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("GSC_SITE", "https://ratescout.ru/")
SEO_OUT = os.path.join(ROOT, "seo-recommendations.md")
API = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
LAG_DAYS, WINDOW = 3, 28          # окно 4 недели — чтобы накопить запросы
MIN_IMPR = 5                       # минимум показов, чтобы считать запрос спросом

CUR = json.load(open(os.path.join(ROOT, "currencies.json"), encoding="utf-8"))["currencies"]
RATES = {}
_rp = os.path.join(ROOT, "rates.json")
if os.path.exists(_rp):
    RATES = json.load(open(_rp, encoding="utf-8")).get("pairs", {})

# --- словарь синонимов: токен в запросе -> слаг каталога -------------------------------------------
CRYPTO_SYN = {
    "tether-trc20": ["usdt", "юсдт", "usdt trc20", "usdt трц20", "tether", "тезер", "тизер", "трц20"],
    "tether-erc20": ["usdt erc20", "usdt эрц20", "erc20"],
    "tether-bep20": ["usdt bep20", "bep20", "usdt bsc"],
    "tether-ton": ["usdt ton", "usdt тон"],
    "tether-polygon": ["usdt polygon", "usdt матик"],
    "bitcoin": ["btc", "биткоин", "биток", "битка", "бтк", "bitcoin"],
    "ethereum": ["eth", "эфир", "эфириум", "этериум", "ethereum"],
    "usd-coin": ["usdc", "usd coin", "юсдс"],
    "tron": ["trx", "трон", "тркс", "tron"],
    "litecoin": ["ltc", "лайткоин", "лтц", "litecoin"],
    "monero": ["xmr", "монеро", "monero"],
    "solana": ["sol", "солана", "solana"],
    "bitcoin-cash": ["bch", "bitcoin cash", "биткоин кэш"],
    "dogecoin": ["doge", "дож", "догикоин", "dogecoin"],
    "binance-coin": ["bnb", "бнб", "binance coin"],
    "dash": ["dash", "дэш", "даш"],
    "cardano": ["ada", "кардано", "cardano"],
    "ripple": ["xrp", "рипл", "ripple"],
}
RECV_SYN = {
    "sberbank": ["сбер", "сбербанк", "sber", "sberbank", "сбербанка", "сбере"],
    "tinkoff": ["тинькофф", "тинёк", "тинек", "т-банк", "тбанк", "tinkoff", "tbank", "т банк"],
    "sbp": ["сбп", "sbp", "быстрые платежи", "систему быстрых"],
    "cash-ruble": ["наличные", "наличка", "нал", "наличными", "cash", "кэш"],
    "visa-mastercard-rub": ["карта", "карту", "виза", "мастеркард", "visa", "mastercard", "на карту"],
    "mir": ["мир", "карту мир", "mir"],
    "alfaclick": ["альфа", "альфабанк", "альфа-банк", "alfa", "alfabank"],
    "vtb": ["втб", "vtb"],
    "gazprombank": ["газпром", "газпромбанк", "gazprom", "гпб"],
    "yoomoney": ["юмани", "юмоней", "yoomoney", "юmoney", "ю мани"],
    "raiffeisen-bank": ["райф", "райффайзен", "raiffeisen"],
    "ozon": ["озон", "ozon", "озон банк"],
    "kaspi-bank": ["каспи", "kaspi", "каспий"],
    "monobank": ["монобанк", "mono", "monobank"],
    "wise": ["wise", "вайз"],
    "paypal-usd": ["paypal", "пейпал", "пайпал"],
    "visa-mastercard-euro": ["евро", "eur", "euro"],
}
# длинные синонимы ищем раньше коротких, чтобы «usdt trc20» победил «usdt»
def _pairs(dic):
    out = []
    for slug, syns in dic.items():
        for s in syns:
            out.append((s, slug))
    out.sort(key=lambda x: -len(x[0]))
    return out
CRYPTO_TOK = _pairs(CRYPTO_SYN)
RECV_TOK = _pairs(RECV_SYN)


def _find(q, tokens):
    """Первый (самый длинный) синоним, встретившийся в запросе, → слаг. По границам слов."""
    for syn, slug in tokens:
        if re.search(r"(?<![а-яёa-z0-9])" + re.escape(syn) + r"(?![а-яёa-z0-9])", q):
            return slug, syn
    return None, None


def match_query(q):
    """Запрос -> (from_slug, to_slug) направление, либо None. Направление по глаголу интента."""
    ql = q.lower()
    c, _ = _find(ql, CRYPTO_TOK)
    r, _ = _find(ql, RECV_TOK)
    if not c or not r or c not in CUR or r not in CUR:
        return None
    buy = bool(re.search(r"(?<![а-я])(куп|приобрес|за |через |on |for )", ql))  # «купить BTC за рубли»
    order = (r, c) if buy else (c, r)                                             # иначе «вывести крипту на банк»
    if f"{order[0]}>{order[1]}" in RATES:
        return order
    rev = (order[1], order[0])
    if f"{rev[0]}>{rev[1]}" in RATES:
        return rev
    return None


# --- существующие страницы: берём из живого sitemap (источник правды о том, что уже есть) -----------
def existing_pairs():
    try:
        with urllib.request.urlopen("https://ratescout.ru/sitemap.xml", timeout=30) as r:
            xml = r.read().decode("utf-8", "ignore")
    except Exception:                              # noqa: BLE001
        return set()
    out = set()
    for m in re.findall(r"ratescout\.ru/obmen/([a-z0-9-]+)-([a-z0-9-]+)/", xml):
        # слаги валют могут содержать дефис — восстановим по каталогу
        pass
    # надёжнее: полный путь и сопоставление с каталогом
    for full in re.findall(r"ratescout\.ru/obmen/([a-z0-9-]+)/", xml):
        for f in CUR:
            if full.startswith(f + "-"):
                t = full[len(f) + 1:]
                if t in CUR:
                    out.add((f, t))
    return out


# --- GSC ------------------------------------------------------------------------------------------
def _token(sa_json):
    from google.oauth2 import service_account
    import google.auth.transport.requests
    creds = service_account.Credentials.from_service_account_info(json.loads(sa_json), scopes=[SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _gsc_queries(token):
    today = datetime.now(timezone.utc).date()
    end = today - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=WINDOW - 1)
    body = json.dumps({"startDate": start.isoformat(), "endDate": end.isoformat(),
                       "dimensions": ["query"], "rowLimit": 1000}).encode()
    url = API.format(site=urllib.parse.quote(SITE, safe=""))
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("rows", [])


def build_recommendations(rows):
    exist = existing_pairs()
    create, strengthen = {}, {}
    for x in rows:
        q = x["keys"][0]
        impr, pos = x["impressions"], x["position"]
        if impr < MIN_IMPR:
            continue
        pair = match_query(q)
        if not pair:
            continue
        key = pair
        if pair not in exist:
            d = create.setdefault(key, {"impr": 0, "pos": pos, "q": []})
            d["impr"] += impr
            d["pos"] = min(d["pos"], pos)
            d["q"].append(q)
        elif 8 <= pos <= 20:
            d = strengthen.setdefault(key, {"impr": 0, "pos": pos, "q": []})
            d["impr"] += impr
            d["pos"] = min(d["pos"], pos)
            d["q"].append(q)
    def rows_of(dct):
        return sorted(({"pair": k, **v} for k, v in dct.items()), key=lambda r: -r["impr"])
    return rows_of(create), rows_of(strengthen)


def _name(slug):
    return CUR.get(slug, {}).get("name", slug)


def render_md(create, strengthen, note=""):
    L = ["# SEO-рекомендации по запросам Search Console", ""]
    if note:
        L += [note, ""]
    L.append("## 🟢 Создать направления (есть спрос и курс, страницы нет)")
    if create:
        L.append("| Направление | URL | Показы | Лучш. поз. | Пример запроса |")
        L.append("|---|---|---:|---:|---|")
        for r in create[:40]:
            f, t = r["pair"]
            L.append(f"| {_name(f)} → {_name(t)} | `/obmen/{f}-{t}/` | {r['impr']} | {r['pos']:.0f} | {r['q'][0]} |")
    else:
        L.append("_Пока нет кандидатов (данные копятся или всё уже покрыто)._")
    L += ["", "## 🟡 Усилить страницы (есть, но на 2-й странице выдачи, поз. 8–20)"]
    if strengthen:
        L.append("| Направление | URL | Показы | Поз. | Пример запроса |")
        L.append("|---|---|---:|---:|---|")
        for r in strengthen[:40]:
            f, t = r["pair"]
            L.append(f"| {_name(f)} → {_name(t)} | `/obmen/{f}-{t}/` | {r['impr']} | {r['pos']:.0f} | {r['q'][0]} |")
    else:
        L.append("_Пока нет страниц на 2-й странице выдачи с заметными показами._")
    return "\n".join(L) + "\n"


def tg_summary(create, strengthen):
    L = ["🧭 SEO-рекомендации (Search Console)", ""]
    L.append(f"🟢 Создать: {len(create)} направлений   🟡 Усилить: {len(strengthen)}")
    if create:
        L += ["", "Топ «создать» (показы):"]
        for r in create[:8]:
            f, t = r["pair"]
            L.append(f"  {_name(f)}→{_name(t)} — {r['impr']} (поз.{r['pos']:.0f})")
    if strengthen:
        L += ["", "Топ «усилить»:"]
        for r in strengthen[:6]:
            f, t = r["pair"]
            L.append(f"  {_name(f)}→{_name(t)} — {r['impr']} (поз.{r['pos']:.0f})")
    L += ["", "Полный список — в артефакте workflow (seo-recommendations.md)."]
    return "\n".join(L)


def send_telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("ALERT_CHAT_ID")
    if not tok or not chat:
        print("Telegram не задан — сводка не отправлена.\n" + text)
        return
    for i in range(0, len(text), 3900):
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[i:i + 3900],
                                       "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"https://api.telegram.org/bot{tok}/sendMessage", data=data, method="POST"), timeout=30)
        except Exception as ex:                    # noqa: BLE001
            print(f"ошибка отправки: {ex}")
    print("сводка отправлена")


SAMPLE = ["обменять usdt на сбербанк", "купить биткоин за рубли", "usdt trc20 тинькофф",
          "вывести эфир на карту", "монеро наличные", "btc на сбп", "доллар сша"]


def main():
    sa = os.environ.get("GSC_SA_JSON")
    if not sa:
        print("GSC_SA_JSON не задан — сухой прогон сопоставления на примерах:")
        for q in SAMPLE:
            m = match_query(q)
            print(f"  «{q}» → " + (f"{m[0]} → {m[1]}" if m else "не распознано"))
        return 0
    try:
        rows = _gsc_queries(_token(sa))
        create, strengthen = build_recommendations(rows)
        md = render_md(create, strengthen, f"Запросов из GSC: {len(rows)} · порог показов: {MIN_IMPR}")
    except Exception as ex:                        # noqa: BLE001
        md = f"# SEO-рекомендации\n\n⚠️ Не собрались: {ex}\n"
        create = strengthen = []
        print(md)
    open(SEO_OUT, "w", encoding="utf-8").write(md)
    print(f"записано: {SEO_OUT}")
    send_telegram(tg_summary(create, strengthen) if (create or strengthen) else
                  "🧭 SEO-рекомендации: пока пусто — данные Search Console ещё копятся.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
