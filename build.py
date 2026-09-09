#!/usr/bin/env python3
"""Генератор статического SEO-сайта RateScout (GitHub Pages) — RU + EN (i18n).

RU в корне (/), EN в /en/. hreflang между версиями, переключатель языка.
Данные (курсы/каталог/пары) общие; локализуются только тексты и внутренние ссылки.
"""
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape as xml_escape

# Генерация обложек статей (Pillow). Если библиотеки/шрифтов нет — мягкий фолбэк на общий og-image,
# сборка НЕ должна падать (ежечасный CI). Флаг COVERS_OK решает, генерим ли персональные обложки.
try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    _COVER_LIB = True
except ImportError:
    _COVER_LIB = False


def _find_font(name):
    for d in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/",
              "/usr/share/fonts/TTF/", "/Library/Fonts/"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


FONT_BOLD = _find_font("DejaVuSans-Bold.ttf")
FONT_REG = _find_font("DejaVuSans.ttf")
COVERS_OK = _COVER_LIB and bool(FONT_BOLD) and bool(FONT_REG)

try:
    import markdown as _md
    def md_render(s):
        return _md.markdown(s, extensions=["extra"])
except ImportError:
    def md_render(s):
        out = []
        for para in s.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            if para.startswith("## "):
                out.append(f"<h2>{para[3:]}</h2>")
            elif para.startswith("# "):
                out.append(f"<h1>{para[2:]}</h1>")
            elif para.startswith("- "):
                li = "".join(f"<li>{l[2:]}</li>" for l in para.splitlines() if l.startswith("- "))
                out.append(f"<ul>{li}</ul>")
            else:
                out.append(f"<p>{para}</p>")
        return "\n".join(out)

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
SITE = json.load(open(os.path.join(ROOT, "data.json"), encoding="utf-8"))["site"]
CAT = json.load(open(os.path.join(ROOT, "currencies.json"), encoding="utf-8"))
CUR = CAT["currencies"]
CATS = CAT["categories"]
S = SITE
BASE_URL = f"https://{S['domain']}"
REF = S["ref"]
INDEXNOW_KEY = "b394aeced6a92ed48a09e2bd30099905"  # публичный ключ IndexNow (ключ-файл на сайте)

LANGS = ["ru", "en"]
PREF = {"ru": "", "en": "/en"}
LOCALE = {"ru": "ru", "en": "en"}
BLOG_PER_PAGE = 6            # статей на страницу блога (пагинация 1 2 3 …)

# Версии ассетов для кеш-бастинга (хеш содержимого) — заполняется в main() до рендера.
# Стабильный путь /assets/app.js кешируется браузером; ?v=<hash> меняется только при
# изменении файла и заставляет подхватить новую версию (важно для ежечасных пересборок).
VER = {"css": "", "js": "", "cat": "", "mon": "", "alert": "", "term": "", "heat": ""}


def _h(s):
    return hashlib.md5(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()[:8]

# перевод категорий для EN
CAT_EN = {"Криптовалюты": "Cryptocurrencies", "Digital currencies": "Digital currencies",
          "Bank accounts and cards": "Bank accounts and cards", "Online banking": "Online banking",
          "Money transfers": "Money transfers", "Cash": "Cash", "Прочее": "Other"}
# перевод категорий для RU (исходные имена в дампе — на английском, кроме «Криптовалюты»)
CAT_RU = {"Криптовалюты": "Криптовалюты", "Digital currencies": "Электронные деньги",
          "Bank accounts and cards": "Банковские карты", "Online banking": "Онлайн-банкинг",
          "Money transfers": "Денежные переводы", "Cash": "Наличные", "Прочее": "Прочее"}


def cat_name(c, lang):
    return CAT_EN.get(c, c) if lang == "en" else CAT_RU.get(c, c)


# слаги категорийных хабов (/kategoriya/<slug>/)
CAT_SLUG = {"Криптовалюты": "kriptovalyuty", "Digital currencies": "cifrovye-valyuty",
            "Bank accounts and cards": "bankovskie-karty", "Online banking": "onlayn-banking",
            "Money transfers": "denezhnye-perevody", "Cash": "nalichnye", "Прочее": "prochee"}

# уникальные вступления для хаб-страниц категорий (RU/EN)
CAT_INTRO = {
    "Криптовалюты": ("Криптовалюты — цифровые активы в блокчейн-сетях: Bitcoin, Ethereum, стейблкоины (USDT, "
                     "USDC) и десятки других монет. При обмене важны сеть выпуска и её комиссия. Ниже — все "
                     "криптовалюты каталога; на странице каждой собраны курсы всех направлений и калькулятор.",
                     "Cryptocurrencies are digital assets on blockchain networks: Bitcoin, Ethereum, stablecoins "
                     "(USDT, USDC) and dozens more. When exchanging, the issuing network and its fee matter. Below "
                     "are all cryptocurrencies in the catalog; each page has rates for every direction and a calculator."),
    "Digital currencies": ("Электронные платёжные системы и цифровые кошельки: YooMoney, Advanced Cash, Capitalist "
                           "и другие. Ниже — все такие направления каталога с курсами обмена.",
                           "Electronic payment systems and digital wallets: YooMoney, Advanced Cash, Capitalist and "
                           "others. Below are all such directions in the catalog with exchange rates."),
    "Bank accounts and cards": ("Банковские карты и реквизиты: Visa/Mastercard, Мир, СБП, переводы на счёт. Ниже — "
                                "все карточные направления каталога с курсами обмена.",
                                "Bank cards and details: Visa/Mastercard, Mir, SBP, transfers to account. Below are "
                                "all card directions in the catalog with exchange rates."),
    "Online banking": ("Онлайн-банкинг: Сбербанк, Т-Банк, ВТБ, Альфа-Банк и другие банки. Ниже — все банковские "
                       "направления каталога; на странице каждого — курсы обмена и калькулятор.",
                       "Online banking: Sberbank, T-Bank, VTB, Alfa-Bank and other banks. Below are all bank "
                       "directions in the catalog; each page has exchange rates and a calculator."),
    "Money transfers": ("Системы денежных переводов. Ниже — все такие направления каталога с курсами обмена.",
                        "Money transfer systems. Below are all such directions in the catalog with exchange rates."),
    "Cash": ("Наличные в разных валютах. Ниже — все наличные направления каталога; обмен проходит в офисе обменника.",
             "Cash in various currencies. Below are all cash directions in the catalog; the exchange happens in the "
             "exchanger's office."),
    "Прочее": ("Прочие направления каталога.", "Other directions in the catalog."),
}


def cat_page(lang, cat):
    return f"{PREF[lang]}/kategoriya/{CAT_SLUG.get(cat, 'prochee')}/"


def bc_link(frm, to):
    f, t = CUR.get(frm, {}), CUR.get(to, {})
    if f.get("num") or t.get("num"):
        return f"https://www.bestchange.ru/index.php?mt=rates&from={f.get('id')}&to={t.get('id')}&p={REF}"
    return f"https://www.bestchange.ru/{frm}-to-{to}.html?p={REF}"


def cpage(lang, slug):
    return f"{PREF[lang]}/valuta/{slug}/"


def pair_url(lang, f, t):
    return f"{PREF[lang]}/obmen/{f}-{t}/"


def by_category():
    g = {c: [] for c in CATS}
    for slug, info in CUR.items():
        g.setdefault(info["category"], []).append((slug, info))
    for c in g:
        g[c].sort(key=lambda x: x[1]["name"])
    return g


GROUPED = by_category()

RATES = {}
RATES_GENERATED = 0
_rp = os.path.join(ROOT, "rates.json")
if os.path.exists(_rp):
    try:
        _rj = json.load(open(_rp, encoding="utf-8"))
        RATES = _rj.get("pairs", {})
        RATES_GENERATED = int(_rj.get("generated_at", 0) or 0)
    except (ValueError, OSError):
        RATES = {}


def updated_str(lang):
    """Метка свежести данных курсов (UTC) для отображения на страницах."""
    if not RATES_GENERATED:
        return ""
    dt = datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"Обновлено: {dt}" if lang == "ru" else f"Updated: {dt}"


def modified_iso():
    """ISO-дата последнего обновления курсов — для schema dateModified (свежесть)."""
    ts = RATES_GENERATED or int(datetime.now(timezone.utc).timestamp())
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def webpage_ld(title, path, lang):
    """Лёгкая WebPage-разметка с dateModified — сигнал свежести для страниц без своей WebPage-схемы."""
    return jsonld({"@context": "https://schema.org", "@type": "WebPage", "name": title,
                   "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang],
                   "dateModified": modified_iso(), "lastReviewed": modified_iso()})


GLOSSARY = []
_gp = os.path.join(ROOT, "glossary.json")
if os.path.exists(_gp):
    try:
        GLOSSARY = json.load(open(_gp, encoding="utf-8")).get("terms", [])
    except (ValueError, OSError):
        GLOSSARY = []
GLOSSARY_BY = {t["slug"]: t for t in GLOSSARY}


HISTORY = {}
_hp = os.path.join(ROOT, "history.json")
if os.path.exists(_hp):
    try:
        HISTORY = json.load(open(_hp, encoding="utf-8")).get("series", {})
    except (ValueError, OSError):
        HISTORY = {}

# Популярность направлений по данным Google Поиска (клики), ключ "from>to". Пишется раз в неделю
# workflow-ом SEO (gsc_report.py) и коммитится в репо; при отсутствии — ранжируем только по мониторингу.
POPULAR = {}
_pp = os.path.join(ROOT, "popular.json")
if os.path.exists(_pp):
    try:
        POPULAR = json.load(open(_pp, encoding="utf-8")).get("clicks", {})
    except (ValueError, OSError):
        POPULAR = {}

# Рыночные метрики из CoinGecko (fetch_market.py, ephemeral) — капитализация/объём/ATH по крипто-валютам.
MARKET = {}
_mp = os.path.join(ROOT, "market.json")
if os.path.exists(_mp):
    try:
        MARKET = json.load(open(_mp, encoding="utf-8")).get("coins", {})
    except (ValueError, OSError):
        MARKET = {}

# Трендовые монеты из CoinGecko (/search/trending, fetch_trending.py, ephemeral) — свежий поисковый спрос.
TRENDING = []
_tp = os.path.join(ROOT, "trending.json")
if os.path.exists(_tp):
    try:
        TRENDING = json.load(open(_tp, encoding="utf-8")).get("coins", [])
    except (ValueError, OSError):
        TRENDING = []

# Популярные поисковые запросы к сайту из Яндекс.Вебмастера (fetch_yandex_queries.py, ephemeral).
YANDEX_Q = []
_yp = os.path.join(ROOT, "yandex.json")
if os.path.exists(_yp):
    try:
        YANDEX_Q = json.load(open(_yp, encoding="utf-8")).get("queries", [])
    except (ValueError, OSError):
        YANDEX_Q = []

# Поисковые фразы из Яндекс.Метрики (fetch_metrika.py, ephemeral) — фразы по визитам из поиска.
METRIKA_Q = []
_mtp = os.path.join(ROOT, "metrika.json")
if os.path.exists(_mtp):
    try:
        METRIKA_Q = json.load(open(_mtp, encoding="utf-8")).get("phrases", [])
    except (ValueError, OSError):
        METRIKA_Q = []

# Индекс страха и жадности (fetch_fng.py, ephemeral) — {value, class, ts} или пусто.
FNG = {}
_fp = os.path.join(ROOT, "fng.json")
if os.path.exists(_fp):
    try:
        FNG = json.load(open(_fp, encoding="utf-8"))
    except (ValueError, OSError):
        FNG = {}

# % изменения по валютам за периоды — предрасчёт (для сортировки таблиц), заполняется в main()
CHG_BY = {}


def svg_chart(points):
    """Inline-SVG линия динамики (без JS/внешних либ). points=[[date,rate],...]."""
    vals = [p[1] for p in points]
    mn, mx = min(vals), max(vals)
    W, H, pad = 600.0, 120.0, 8.0
    span = (mx - mn) or (mx or 1.0)
    n = len(points)
    def xy(i, v):
        x = pad + (W - 2 * pad) * (i / (n - 1) if n > 1 else 0)
        y = pad + (H - 2 * pad) * (1 - (v - mn) / span)
        return f"{x:.1f},{y:.1f}"
    poly = " ".join(xy(i, v) for i, v in enumerate(vals))
    last_x = pad + (W - 2 * pad)
    last_y = pad + (H - 2 * pad) * (1 - (vals[-1] - mn) / span)
    return (f'<svg class="chart" viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none" '
            f'role="img" aria-label="rate chart">'
            f'<polyline fill="none" stroke="#55ff55" stroke-width="2" points="{poly}"/>'
            f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="#ffff55"/></svg>')


# периоды для фильтра роста/падения на /grafiki/ (ключ, дней)
CHART_PERIODS = [("24h", 1), ("7d", 7), ("30d", 30), ("1y", 365), ("3y", 1095), ("5y", 1825), ("10y", 3650)]


def _hist_time(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:00")
    except ValueError:
        return datetime.strptime(s, "%Y-%m-%d")


def _pct_over(pts, days):
    """% изменения цены за последние `days` (база — первая точка в окне; если данных меньше — от старта)."""
    if len(pts) < 2:
        return None
    cutoff = _hist_time(pts[-1][0]) - timedelta(days=days)
    base = None
    for k, v in pts:
        if _hist_time(k) >= cutoff:
            base = v
            break
    if base is None:
        base = pts[0][1]
    if not base:
        return None
    return (pts[-1][1] - base) / base * 100


def mini_spark(points):
    """Лёгкий спарклайн (мини-SVG без осей) для обзорной страницы графиков."""
    vals = [p[1] for p in points]
    mn, mx = min(vals), max(vals)
    span = (mx - mn) or (mx or 1.0)
    W, H = 120.0, 34.0
    n = len(points)
    poly = " ".join(f"{(i / (n - 1) * W if n > 1 else 0):.1f},{(2 + (1 - (v - mn) / span) * (H - 4)):.1f}"
                    for i, v in enumerate(vals))
    color = "#55ff55" if vals[-1] >= vals[0] else "#f55"
    return (f'<svg class="spark" viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{poly}"/></svg>')


def _usdt_price(slug):
    """Текущая цена валюты в USDT: прямой курс, иначе обратный (USDT→slug) с инверсией."""
    r = rate_of(slug, "tether-trc20")
    if r:
        try:
            v = float(r["rate"])
            if v > 0:
                return v, r.get("count", 0)
        except (ValueError, TypeError):
            pass
    rr = rate_of("tether-trc20", slug)
    if rr:
        try:
            v = float(rr["rate"])
            if v > 0:
                return 1.0 / v, rr.get("count", 0)
        except (ValueError, TypeError, ZeroDivisionError):
            pass
    return None, 0



def render_home(lang):
    total = len(CUR)
    cat_html = ""
    for c in CATS:
        items = "".join(f'<li><a href="{cpage(lang, slug)}">{info["name"]} <span>{info["ticker"]}</span></a></li>'
                        for slug, info in GROUPED.get(c, []))
        cat_html += (f'<h2 class="news"><a href="{cat_page(lang, c)}">{cat_name(c, lang)}</a> '
                     f'<span class="cnt">{len(GROUPED.get(c, []))}</span></h2><ul class="dlist">{items}</ul>')
    ld = jsonld({"@context": "https://schema.org", "@type": "WebSite", "name": S["name"],
                 "url": BASE_URL + PREF[lang] + "/", "inLanguage": LOCALE[lang], "description": S["tagline"]})
    org = jsonld({"@context": "https://schema.org", "@type": "Organization", "name": S["name"],
                  "url": BASE_URL, "logo": f"{BASE_URL}/assets/og-image.png",
                  "email": S.get("owner_email", ""),
                  # sameAs — привязка сущности к соцпрофилям (Knowledge Graph / entity для GEO/LLMO/NEO)
                  "sameAs": ["https://t.me/ratescout_kurs", "https://vk.com/ratescout",
                             "https://dzen.ru/ratescout"],
                  "contactPoint": {"@type": "ContactPoint", "contactType":
                                   ("customer support" if lang == "en" else "поддержка"),
                                   "email": S.get("owner_email", "")}})
    # Dataset — заявка в Google Dataset Search: наш открытый датасет курсов (обновляется ежечасно)
    ds_name = (f"Курсы обмена {total} валют — {S['name']}" if lang == "ru"
               else f"Exchange rates for {total} currencies — {S['name']}")
    ds_desc = (f"Открытый датасет курсов обмена криптовалют и валют по {total} валютам и их направлениям, "
               "собранный из мониторинга обменных пунктов BestChange. Обновляется ежечасно; цены валют — в USDT."
               if lang == "ru" else
               f"Open dataset of crypto and money exchange rates across {total} currencies and their directions, "
               "collected from the BestChange exchange monitor. Updated hourly; currency prices are in USDT.")
    dataset = jsonld({"@context": "https://schema.org", "@type": "Dataset", "name": ds_name,
                      "description": ds_desc, "url": BASE_URL + PREF[lang] + "/",
                      "inLanguage": LOCALE[lang], "isAccessibleForFree": True,
                      "license": "https://creativecommons.org/licenses/by/4.0/",
                      "creator": {"@type": "Organization", "name": S["name"], "url": BASE_URL},
                      "keywords": ["exchange rates", "cryptocurrency", "BestChange", "USDT", "курсы обмена"],
                      "dateModified": modified_iso(),
                      "distribution": [
                          {"@type": "DataDownload", "encodingFormat": "application/json",
                           "contentUrl": BASE_URL + "/prices.json"},
                          {"@type": "DataDownload", "encodingFormat": "application/json",
                           "contentUrl": BASE_URL + "/widget-data.json"}]})
    if lang == "ru":
        title = f"{S['name']} — справочник курсов обмена: {total} валют"
        desc = (f"Справочник курсов обмена криптовалют и денег по {total} валютам на основе мониторинга обменных "
                "пунктов BestChange. Все направления, AML-проверка криптоадресов.")
        intro = (f"Справочник курсов обмена криптовалют и валют. Данные собраны из мониторинга обменных пунктов "
                 f"<b>BestChange</b> по <b>{total}</b> валютам и приведены для ознакомления. "
                 f'<a href="/o-servise/">Что такое BestChange →</a>')
    else:
        title = f"{S['name']} — currency exchange rates directory: {total} currencies"
        desc = (f"Directory of crypto and money exchange rates across {total} currencies, based on BestChange "
                "exchange monitoring. All directions, crypto address AML check.")
        intro = (f"A directory of crypto and currency exchange rates. Data is collected from the <b>BestChange</b> "
                 f"exchange monitor across <b>{total}</b> currencies and provided for reference. "
                 f'<a href="/en/o-servise/">What is BestChange →</a>')
    pop = (f'<h2 class="news">{tr(lang,"popular")}</h2><ul class="dlist">'
           + "".join(pair_link_li(p, lang) for p in TOP[:16]) + "</ul>") if TOP else ""
    # GEO answer-first: датированный сводный факт (число валют/категорий + пример курса) для главной.
    _ld = datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d") if RATES_GENERATED else ""
    _btc = HISTORY.get("bitcoin") or []
    if lang == "ru":
        _ex = f" Например, 1 BTC ≈ {fmt_rate(_btc[-1][1])} USDT." if _btc else ""
        home_lead = (f"На {_ld} {S['name']} отслеживает справочные курсы обмена <b>{total}</b> криптовалют и валют "
                     f"в {len(CATS)} категориях по данным мониторинга BestChange (обновление ежечасно).{_ex}")
    else:
        _ex = f" For example, 1 BTC ≈ {fmt_rate(_btc[-1][1])} USDT." if _btc else ""
        home_lead = (f"As of {_ld}, {S['name']} tracks reference exchange rates for <b>{total}</b> cryptocurrencies "
                     f"and currencies across {len(CATS)} categories from BestChange monitoring (hourly updates).{_ex}")
    body = f"""{header(lang, "/")}
<div id="main">
  <pre class="ascii">  ____       _        ____                  _
 |  _ \\ __ _| |_ ___ / ___|  ___ ___  _   _| |_
 | |_) / _` | __/ _ \\\\___ \\ / __/ _ \\| | | | __|
 |  _ < (_| | ||  __/ ___) | (_| (_) | |_| | |_
 |_| \\_\\__,_|\\__\\___|____/ \\___\\___/ \\__,_|\\__|</pre>
  <div id="content">
    {trust_bar(lang)}
    <div class="mktwidgets">{halving_widget(lang)}</div>
    {pop}
    <h2 class="news">{tr(lang,'catalog')} <span class="cnt">{total}</span></h2>
    {cat_html}
  </div>
  <div id="sidebar">
    {converter_html(lang)}
    {search_box(lang)}
    {wallet_cta(lang)}
    <div class="sblock"><h3>{tr(lang,'sections')}</h3><ul>
      <li><a href="https://app.ratescout.info.gf">{'📱 Приложение' if lang=='ru' else '📱 App'}</a></li>
      <li><a href="{PREF[lang]}/napravleniya/">{tr(lang,'nav_dirs')}</a></li>
      <li><a href="{PREF[lang]}/lidery-rynka/">{tr(lang,'nav_leaders')}</a></li>
      <li><a href="{PREF[lang]}/heatmap/">{'Тепловая карта' if lang=='ru' else 'Heatmap'}</a></li>
      <li><a href="{PREF[lang]}/populyarnost/">{'Популярность по поиску' if lang=='ru' else 'Search popularity'}</a></li>
      <li><a href="{PREF[lang]}/monitor/">{'Про-монитор' if lang=='ru' else 'Pro monitor'}</a></li>
      <li><a href="{PREF[lang]}/tsepochki/">{'💱 Цепочки обмена' if lang=='ru' else '💱 Exchange chains'}</a></li>
      <li><a href="https://my-many.ru/?utm_source=ratescout&utm_medium=nav">{'💰 Арбитраж (MyMany)' if lang=='ru' else '💰 Arbitrage (MyMany)'}</a></li>
      <li><a href="{PREF[lang]}/alert/">{'Оповещения о курсе' if lang=='ru' else 'Rate alerts'}</a></li>
      <li><a href="{PREF[lang]}/nastroeniya/">{tr(lang,'nav_mood')}</a></li>
      <li><a href="{PREF[lang]}/sravnenie/">{tr(lang,'nav_compare')}</a></li>
      <li><a href="{PREF[lang]}/o-servise/">{tr(lang,'nav_about')}</a></li>
      <li><a href="{PREF[lang]}/aml/">{tr(lang,'nav_aml')}</a></li>
      <li><a href="{PREF[lang]}/kniga/">{'📖 Книги' if lang=='ru' else '📖 Books'}</a></li>
      <li><a href="{PREF[lang]}/vidzhet/">{tr(lang,'nav_widget')}</a></li>
      <li><a href="{PREF[lang]}/raskrytie/">{tr(lang,'nav_disc')}</a></li>
    </ul></div>
  </div>
  <div class="clearboth"></div>
</div>
{org}{dataset}
{footer(lang)}"""
    write(lang, "/", head(lang, title, desc, "/", ld) + body)

def render_directions(lang):
    """ТОП направлений обмена — data-driven листикл: ранжирование по числу обменников и резерву (факт из дампа)."""
    path = "/napravleniya/"
    cand = []
    for p in PAIR_PAGES:
        r = rate_of(p["from"], p["to"])
        if r and r.get("count"):
            cand.append((p["from"], p["to"], r))
    # ранжирование: сначала переходы из Google Поиска (если данные есть), затем факт мониторинга.
    def _pop(f, t):
        return POPULAR.get(f"{f}>{t}", 0)
    has_gsc = any(_pop(f, t) for f, t, _ in cand)
    cand.sort(key=lambda x: (_pop(x[0], x[1]), x[2].get("count", 0), x[2].get("reserve", 0) or 0), reverse=True)
    if lang == "ru":
        title = f"Самые популярные направления обмена — ТОП по обменникам | {S['name']}"
        desc = ("ТОП направлений обмена криптовалют и валют: ранжирование по числу обменников и резерву. "
                "Курсы из мониторинга BestChange, обновление ежечасно.")
        h1 = "Самые популярные направления обмена"
        lead = ("Направления обмена, ранжированные по числу обменников и суммарному резерву (данные мониторинга "
                "BestChange). Курс — лучший среди обменников, справочно.")
        cols = ("#", "Направление", "Курс", "Обменников", "Резерв")
        th_crub, th_ucard = "Криптовалюта → рубли", "Стейблкоины → карты/СБП"
        empty = "Направления появятся после загрузки данных."
    else:
        title = f"Most popular exchange directions — top by exchangers | {S['name']}"
        desc = ("Top exchange directions for crypto and money: ranked by number of exchangers and reserve. "
                "Rates from BestChange monitoring, hourly updates.")
        h1 = "Most popular exchange directions"
        lead = ("Exchange directions ranked by the number of exchangers and total reserve (BestChange monitoring "
                "data). Rate is the best among exchangers, for reference.")
        cols = ("#", "Direction", "Rate", "Exchangers", "Reserve")
        th_crub, th_ucard = "Crypto → rubles", "Stablecoins → cards/SBP"
        empty = "Directions will appear after data loads."
    srch_note = ""
    if has_gsc:
        srch_note = (" Порядок учитывает переходы из Google Поиска за последнее время." if lang == "ru"
                     else " The order factors in visits from Google Search over the recent period.")
    rows = []
    for i, (f, t, r) in enumerate(cand[:50], 1):
        fT, tT = CUR[f]["ticker"], CUR[t]["ticker"]
        clk = _pop(f, t)
        badge = (f' <span class="tk" title="{"переходов из поиска" if lang=="ru" else "search visits"}">🔍 {clk}</span>'
                 if clk else "")
        rows.append(f'<tr><td>{i}</td><td><a href="{pair_url(lang, f, t)}">{CUR[f]["name"]} '
                    f'<span class="tk">{fT}</span> → {CUR[t]["name"]} <span class="tk">{tT}</span></a>{badge}</td>'
                    f'<td>{fmt_rate(r["rate"])} {tT}</td><td>{r.get("count", 0)}</td>'
                    f'<td>{fmt_rate(r.get("reserve", 0))} {tT}</td></tr>')
    head_html = "".join(f"<th>{c}</th>" for c in cols)
    table = (f'<div class="rtbl-wrap"><table class="rtbl"><thead><tr>{head_html}</tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>') if rows else f"<p>{empty}</p>"

    def _theme(h, pairs):
        if not pairs:
            return ""
        lis = "".join(pair_link_li({"from": f, "to": t}, lang) for f, t, _ in pairs)
        return f'<h2 class="news">{h}</h2><ul class="dlist">{lis}</ul>'
    crypto_rub = [c for c in cand if CUR[c[0]]["category"] == "Криптовалюты" and c[1] in HI_RECV][:8]
    usdt_cards = [c for c in cand if c[0].startswith("tether")
                  and c[1] in ("visa-mastercard-rub", "sberbank", "tinkoff", "sbp", "mir")][:8]
    themes = _theme(th_crub, crypto_rub) + _theme(th_ucard, usdt_cards)
    il = itemlist_ld([(f'{CUR[f]["ticker"]} → {CUR[t]["ticker"]}', BASE_URL + pair_url(lang, f, t))
                      for f, t, _ in cand[:20]])
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    crumbs += jsonld({"@context": "https://schema.org", "@type": "CollectionPage", "name": h1,
                      "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang], "dateModified": modified_iso()})
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}{srch_note}</p>
    {trust_bar(lang)}
    {table}
    {themes}
  </div>
</div>
{il}{crumbs}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + body)


def render_market_leaders(lang):
    """Лидеры крипторынка по данным CoinGecko: капитализация, объём, движения за 7д. Рыночные факты, справочно."""
    path = "/lidery-rynka/"
    items = [(s, d) for s, d in MARKET.items() if s in CUR and d.get("mcap")]
    ru = lang == "ru"
    if ru:
        title = f"Лидеры крипторынка — капитализация, объём, движения | {S['name']}"
        desc = ("Топ криптовалют по капитализации и объёму торгов, лидеры роста и падения за 7 дней. "
                "Рыночные данные CoinGecko, обновление ежечасно.")
        h1, lead = "Лидеры крипторынка", ("Криптовалюты по капитализации и объёму торгов, а также лидеры "
                                          "движения за неделю. Рыночные данные — по CoinGecko, справочно.")
    else:
        title = f"Crypto market leaders — market cap, volume, movers | {S['name']}"
        desc = ("Top cryptocurrencies by market cap and trading volume, weekly gainers and losers. "
                "CoinGecko market data, hourly updates.")
        h1, lead = "Crypto market leaders", ("Cryptocurrencies by market cap and trading volume, plus weekly "
                                             "movers. Market data from CoinGecko, for reference.")

    def _nm(s):
        return f'<a href="{cpage(lang, s)}">{CUR[s]["name"]} <span class="tk">{CUR[s]["ticker"]}</span></a>'

    def _pct(v):
        return (f'<span class="{"up" if v >= 0 else "down"}">{"+" if v >= 0 else ""}{v:.1f}%</span>'
                if v is not None else "—")

    def _tbl(cols, rows_html):
        head_html = "".join(f"<th>{c}</th>" for c in cols)
        return (f'<div class="rtbl-wrap"><table class="rtbl"><thead><tr>{head_html}</tr></thead>'
                f'<tbody>{rows_html}</tbody></table></div>')

    blocks = ""
    if items:
        cap = sorted(items, key=lambda x: x[1].get("rank") or 9999)[:30]
        rows = "".join(f'<tr><td>{d.get("rank", "")}</td><td>{_nm(s)}</td><td>{_human_usd(d["mcap"], lang)}</td>'
                       f'<td>{_human_usd(d.get("vol", 0), lang)}</td><td>{_pct(d.get("chg7d"))}</td></tr>'
                       for s, d in cap)
        blocks += (f'<h2 class="news">{"По капитализации" if ru else "By market cap"}</h2>'
                   + _tbl(("#", "Валюта" if ru else "Currency", "Капитализация" if ru else "Market cap",
                           "Объём 24ч" if ru else "Vol 24h", "7д" if ru else "7d"), rows))
        vol = sorted(items, key=lambda x: x[1].get("vol") or 0, reverse=True)[:20]
        rows2 = "".join(f'<tr><td>{i}</td><td>{_nm(s)}</td><td>{_human_usd(d.get("vol", 0), lang)}</td>'
                        f'<td>{_human_usd(d["mcap"], lang)}</td></tr>' for i, (s, d) in enumerate(vol, 1))
        blocks += (f'<h2 class="news">{"По объёму торгов (24ч)" if ru else "By trading volume (24h)"}</h2>'
                   + _tbl(("#", "Валюта" if ru else "Currency", "Объём 24ч" if ru else "Vol 24h",
                           "Капитализация" if ru else "Market cap"), rows2))
        mv = [(s, d) for s, d in items if d.get("chg7d") is not None]
        if mv:
            gain = sorted(mv, key=lambda x: x[1]["chg7d"], reverse=True)[:10]
            loss = sorted(mv, key=lambda x: x[1]["chg7d"])[:10]

            def _ml(lst):
                return "".join(f'<tr><td>{_nm(s)}</td><td>{_pct(d["chg7d"])}</td></tr>' for s, d in lst)
            blocks += (f'<h2 class="news">{"Лидеры роста за 7д" if ru else "Top gainers (7d)"}</h2>'
                       + _tbl(("Валюта" if ru else "Currency", "7д" if ru else "7d"), _ml(gain)))
            blocks += (f'<h2 class="news">{"Лидеры падения за 7д" if ru else "Top losers (7d)"}</h2>'
                       + _tbl(("Валюта" if ru else "Currency", "7д" if ru else "7d"), _ml(loss)))
    else:
        blocks = f'<p class="updnote">{"Рыночные данные обновляются." if ru else "Market data updating."}</p>'

    cmp = compare_pairs()[:15]
    if cmp:
        cl = " · ".join(f'<a href="{PREF[lang]}/sravnenie/{a}-vs-{b}/">{CUR[a]["ticker"]} vs {CUR[b]["ticker"]}</a>'
                        for a, b in cmp)
        blocks += f'<h2 class="news">{"Сравнения валют" if ru else "Currency comparisons"}</h2><p class="dlist">{cl}</p>'

    src = "Источник рыночных данных: CoinGecko. Приведено справочно." if ru else \
          "Market data source: CoinGecko. For reference."
    il = itemlist_ld([(f'{CUR[s]["ticker"]}', BASE_URL + cpage(lang, s)) for s, _ in items[:20]]) if items else ""
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    crumbs += jsonld({"@context": "https://schema.org", "@type": "CollectionPage", "name": h1,
                      "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang], "dateModified": modified_iso()})
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}</p>
    {trust_bar(lang)}
    {blocks}
    <p class="updnote">{src}</p>
  </div>
</div>
{il}{crumbs}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + body)


def render_stablecoins(lang):
    """Депег-монитор: отклонение стейблкоинов от $1 (цена в USDT). Данные — _svodka_rows (мониторинг BestChange)."""
    path = "/stablecoins/"
    ru = lang == "ru"
    rows = _svodka_rows()
    best = {}
    for r in rows:
        tk = CUR[r[0]]["ticker"]
        if tk in STABLE_T and r[1] is not None and (tk not in best or r[2] > best[tk][2]):
            best[tk] = r
    items = sorted(best.values(), key=lambda r: abs((r[1] or 1) - 1), reverse=True)
    if ru:
        title = f"Стейблкоины — привязка к доллару (депег-монитор) | {S['name']}"
        desc = ("Мониторинг привязки стейблкоинов (USDT, USDC, DAI и др.) к $1: текущее отклонение цены и статус. "
                "Данные мониторинга BestChange, обновление ежечасно.")
        h1, lead = "Стейблкоины: привязка к доллару", ("Стейблкоины должны стоить около $1. Ниже — текущее "
            "отклонение их цены (в USDT) от доллара: чем больше отклонение, тем сильнее «депег». Справочно.")
        cols, ok_l, warn_l, bad_l = ("Стейблкоин", "Цена, USDT", "Откл. от $1", "Статус"), "в привязке", "лёгкий депег", "депег"
        empty = "Данные обновляются."
    else:
        title = f"Stablecoins — dollar peg (depeg monitor) | {S['name']}"
        desc = ("Stablecoin peg monitor (USDT, USDC, DAI and others) to $1: current price deviation and status. "
                "BestChange monitoring data, hourly updates.")
        h1, lead = "Stablecoins: dollar peg", ("Stablecoins should trade near $1. Below is the current deviation of "
            "their price (in USDT) from the dollar: the larger the deviation, the bigger the depeg. For reference.")
        cols, ok_l, warn_l, bad_l = ("Stablecoin", "Price, USDT", "Dev. from $1", "Status"), "on peg", "slight depeg", "depeg"
        empty = "Data updating."
    body = ""
    for s, p, _liq, _ in items:
        dev, ad = (p - 1) * 100, abs((p - 1) * 100)
        cls = "up" if dev >= 0 else "down"
        st = ok_l if ad < 0.5 else (warn_l if ad < 1.5 else bad_l)
        stc = ' class="down"' if ad >= 1.5 else ""
        body += (f'<tr><td><a href="{cpage(lang, s)}">{CUR[s]["name"]} <span class="tk">{CUR[s]["ticker"]}</span></a></td>'
                 f'<td>{p:.4f}</td><td class="{cls}">{"+" if dev >= 0 else ""}{dev:.2f}%</td><td{stc}>{st}</td></tr>')
    table = (f'<div class="rtbl-wrap"><table class="rtbl"><thead><tr>{"".join(f"<th>{c}</th>" for c in cols)}'
             f'</tr></thead><tbody>{body}</tbody></table></div>') if body else f'<p class="updnote">{empty}</p>'
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    bodyhtml = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}</p>
    {trust_bar(lang)}
    {table}
    <p class="updnote">{"Отклонение считается по цене стейблкоина в USDT. Значительный депег — повод проверить новости актива." if ru else "Deviation is measured by the stablecoin price in USDT. A large depeg is a reason to check the asset news."}</p>
  </div>
</div>
{crumbs}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + bodyhtml)


def _px(slug):
    h = HISTORY.get(slug) or []
    return h[-1][1] if h else None


def compare_pairs():
    """Неупорядоченные пары среди топ-20 крипто по капитализации (из MARKET) — для страниц сравнения."""
    coins = sorted(((s, d.get("rank") or 9999) for s, d in MARKET.items() if s in CUR), key=lambda x: x[1])
    slugs = [s for s, _ in coins[:20]]
    return [(slugs[i], slugs[j]) for i in range(len(slugs)) for j in range(i + 1, len(slugs))]


def render_compare_index(lang):
    """Хаб сравнения валют /sravnenie/: два выпадающих списка → переход на /sravnenie/A-vs-B/, + список пар (SEO/без JS)."""
    path = "/sravnenie/"
    ru = lang == "ru"
    coins = sorted(((s, d.get("rank") or 9999) for s, d in MARKET.items() if s in CUR), key=lambda x: x[1])
    slugs = [s for s, _ in coins[:20]]
    if not slugs:
        return
    opts = "".join(f'<option value="{i}">{CUR[s]["ticker"]} — {CUR[s]["name"]}</option>' for i, s in enumerate(slugs))
    opts_b = "".join(f'<option value="{i}"{" selected" if i == 1 else ""}>{CUR[s]["ticker"]} — {CUR[s]["name"]}</option>'
                     for i, s in enumerate(slugs))
    links = " · ".join(f'<a href="{PREF[lang]}/sravnenie/{a}-vs-{b}/">{CUR[a]["ticker"]} vs {CUR[b]["ticker"]}</a>'
                       for a, b in compare_pairs())
    js = ("(function(){var S=" + json.dumps(slugs) + ",B=" + json.dumps(PREF[lang] + "/sravnenie/") + ";"
          "var a=document.getElementById('cmpA'),b=document.getElementById('cmpB'),g=document.getElementById('cmpGo'),"
          "w=document.getElementById('cmpWarn');if(!g)return;"
          "g.addEventListener('click',function(){var i=+a.value,j=+b.value;"
          "if(i===j){w.hidden=false;return;}w.hidden=true;var lo=Math.min(i,j),hi=Math.max(i,j);"
          "location.href=B+S[lo]+'-vs-'+S[hi]+'/';});})();")
    if ru:
        title = f"Сравнение криптовалют — выберите две валюты | {S['name']}"
        desc = ("Сравните две криптовалюты по цене, изменению, капитализации, объёму и ATH. Выберите валюты — "
                "получите сравнение. Данные мониторинга BestChange и CoinGecko.")
        h1, lead = "Сравнение криптовалют", "Выберите две валюты — покажем их рядом по ключевым показателям."
        la, lb, btn, warn = "Первая валюта", "Вторая валюта", "Сравнить", "Выберите две разные валюты."
        poph = "Популярные сравнения"
    else:
        title = f"Compare cryptocurrencies — pick two coins | {S['name']}"
        desc = ("Compare two cryptocurrencies by price, change, market cap, volume and ATH. Pick coins — get the "
                "comparison. BestChange monitoring and CoinGecko data.")
        h1, lead = "Compare cryptocurrencies", "Pick two coins — we'll show them side by side on key metrics."
        la, lb, btn, warn = "First coin", "Second coin", "Compare", "Pick two different coins."
        poph = "Popular comparisons"
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    bodyhtml = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}</p>
    {trust_bar(lang)}
    <div class="conv dosblue dosborder">
      <p><label>{la}: <select id="cmpA">{opts}</select></label></p>
      <p><label>{lb}: <select id="cmpB">{opts_b}</select></label></p>
      <p><button id="cmpGo" type="button" class="cta">{btn}</button></p>
      <p id="cmpWarn" class="updnote" hidden style="color:#ffcc33">{warn}</p>
    </div>
    <h2 class="news">{poph}</h2>
    <p class="dlist">{links}</p>
  </div>
</div>
{crumbs}
<script>{js}</script>
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path, webpage_ld(title, path, lang)) + bodyhtml)


def render_compare(a, b, lang):
    """Сравнение двух валют: цена, изменения, капитализация, объём, ATH, RSI. Данные — наши + CoinGecko."""
    ia, ib = CUR.get(a), CUR.get(b)
    if not ia or not ib:
        return
    ta, tb = ia["ticker"], ib["ticker"]
    path = f"/sravnenie/{a}-vs-{b}/"
    ru = lang == "ru"
    ma, mb = MARKET.get(a, {}), MARKET.get(b, {})
    g1, g2 = currency_metrics(a) or {}, currency_metrics(b) or {}

    def pc(v):
        return f'<span class="{"up" if v >= 0 else "down"}">{"+" if v >= 0 else ""}{v:.1f}%</span>' if v is not None else "—"

    def usd(x):
        return _human_usd(x, lang) if x else "—"

    def ath(m):
        return f'{fmt_rate(m["ath"])} ({m["ath_chg"]:.0f}%)' if m.get("ath") else "—"
    metrics = [
        ("Цена, USDT" if ru else "Price, USDT", fmt_rate(_px(a)) if _px(a) else "—", fmt_rate(_px(b)) if _px(b) else "—"),
        ("Изм. 24ч" if ru else "Change 24h", pc(g1.get("24h")), pc(g2.get("24h"))),
        ("Изм. 7д" if ru else "Change 7d", pc(ma.get("chg7d")), pc(mb.get("chg7d"))),
        ("Изм. 30д" if ru else "Change 30d", pc(ma.get("chg30d")), pc(mb.get("chg30d"))),
        ("Капитализация" if ru else "Market cap", usd(ma.get("mcap")) + (f' #{ma["rank"]}' if ma.get("rank") else ""),
         usd(mb.get("mcap")) + (f' #{mb["rank"]}' if mb.get("rank") else "")),
        ("Объём 24ч" if ru else "Volume 24h", usd(ma.get("vol")), usd(mb.get("vol"))),
        ("Ист. максимум (ATH)" if ru else "All-time high", ath(ma), ath(mb)),
    ]
    if g1.get("rsi") is not None or g2.get("rsi") is not None:
        metrics.append(("RSI (14)", f'{g1["rsi"]:.0f}' if g1.get("rsi") is not None else "—",
                        f'{g2["rsi"]:.0f}' if g2.get("rsi") is not None else "—"))
    rows = "".join(f'<tr><td>{m}</td><td>{va}</td><td>{vb}</td></tr>' for m, va, vb in metrics)
    _pa = fmt_rate(_px(a)) if _px(a) else ""
    _pb = fmt_rate(_px(b)) if _px(b) else ""
    _cdh = ".".join(reversed(datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d").split("-"))) if RATES_GENERATED else ""
    _pref_ru = (f"{ia['name']} {_pa} USDT vs {ib['name']} {_pb} USDT" + (f" на {_cdh}" if _cdh else "") + ". ") if (_pa and _pb) else ""
    _pref_en = (f"{ia['name']} {_pa} USDT vs {ib['name']} {_pb} USDT. ") if (_pa and _pb) else ""
    if ru:
        title = f"{ia['name']} ({ta}) vs {ib['name']} ({tb}) — курсы и сравнение сегодня | {S['name']}"
        desc = (f"{_pref_ru}Сравнение {ia['name']} ({ta}) и {ib['name']} ({tb}): цена, изменение за 24ч/7д/30д, "
                f"капитализация, объём, ATH. Данные BestChange и CoinGecko.")
        h1, lead = f"{ia['name']} vs {ib['name']} — сравнение", (f"Сравнение {ia['name']} и {ib['name']} по ключевым показателям — "
            "цена, динамика, капитализация. Справочно, не рекомендация.")
        colh = ("Показатель", ta, tb)
    else:
        title = f"{ia['name']} ({ta}) vs {ib['name']} ({tb}) — rates and comparison today | {S['name']}"
        desc = (f"{_pref_en}Compare {ia['name']} ({ta}) and {ib['name']} ({tb}): price, 24h/7d/30d change, market cap, "
                f"volume, ATH. BestChange and CoinGecko data.")
        h1, lead = f"{ia['name']} vs {ib['name']} — comparison", (f"Comparing {ia['name']} and {ib['name']} on key metrics — "
            "price, dynamics, market cap. For reference, not advice.")
        colh = ("Metric", ta, tb)
    table = (f'<div class="rtbl-wrap"><table class="rtbl"><thead><tr>{"".join(f"<th>{c}</th>" for c in colh)}'
             f'</tr></thead><tbody>{rows}</tbody></table></div>')
    rel = (f'<p class="related"><a href="{cpage(lang, a)}">{ia["name"]} {ta}</a> · '
           f'<a href="{cpage(lang, b)}">{ib["name"]} {tb}</a> · '
           f'<a href="{PREF[lang]}/lidery-rynka/">{"Лидеры рынка" if ru else "Market leaders"}</a></p>')
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": f"{ta} vs {tb}", "item": BASE_URL + PREF[lang] + path}]})
    bodyhtml = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {ta} vs {tb}</nav>
    <h1>{h1}</h1><p>{lead}</p>
    {trust_bar(lang)}
    {table}
    {rel}
  </div>
</div>
{crumbs}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path, webpage_ld(title, path, lang)) + bodyhtml)


FNG_CLASS_RU = {"Extreme Fear": "Крайний страх", "Fear": "Страх", "Neutral": "Нейтрально",
                "Greed": "Жадность", "Extreme Greed": "Крайняя жадность"}


def _fng_color(v):
    return ("#ff5555" if v < 25 else "#ff9933" if v < 45 else "#ffdd33" if v < 55 else "#88dd44" if v < 75 else "#33cc33")


def fng_widget(lang):
    if "value" not in FNG:
        return ""
    v, ru = FNG["value"], lang == "ru"
    lab = FNG_CLASS_RU.get(FNG.get("class", ""), FNG.get("class", "")) if ru else FNG.get("class", "")
    col = _fng_color(v)
    h = "Индекс страха и жадности" if ru else "Fear & Greed Index"
    return (f'<div class="conv dosblue dosborder"><h3><a href="{PREF[lang]}/nastroeniya/">{h}</a></h3>'
            f'<p class="big" style="color:{col};margin:4px 0">{v}<span class="tk" style="color:{col}"> /100 · {lab}</span></p>'
            f'<div style="height:8px;background:#002;border:1px solid #55ffff">'
            f'<div style="height:100%;width:{v}%;background:{col}"></div></div></div>')


def render_fng(lang):
    path = "/nastroeniya/"
    ru = lang == "ru"
    if ru:
        title = f"Индекс страха и жадности криптовалют — сегодня | {S['name']}"
        desc = "Индекс страха и жадности (Crypto Fear & Greed) — настроение крипторынка сегодня по шкале 0–100. Источник: alternative.me."
        h1, lead = "Индекс страха и жадности", ("Индекс показывает настроение крипторынка по шкале 0–100: низкие "
            "значения — страх (часто рынок перепродан), высокие — жадность (перегрет). Это ориентир, не сигнал.")
        scale = [("0–24", "Крайний страх"), ("25–44", "Страх"), ("45–54", "Нейтрально"),
                 ("55–74", "Жадность"), ("75–100", "Крайняя жадность")]
        src = "Источник: alternative.me. Приведено справочно, не является рекомендацией."
    else:
        title = f"Crypto Fear & Greed Index — today | {S['name']}"
        desc = "Crypto Fear & Greed Index — market sentiment today on a 0–100 scale. Source: alternative.me."
        h1, lead = "Fear & Greed Index", ("The index shows crypto market sentiment on a 0–100 scale: low means fear "
            "(often oversold), high means greed (overheated). A guide, not a signal.")
        scale = [("0–24", "Extreme Fear"), ("25–44", "Fear"), ("45–54", "Neutral"),
                 ("55–74", "Greed"), ("75–100", "Extreme Greed")]
        src = "Source: alternative.me. For reference, not advice."
    scale_html = "".join(f'<tr><td>{r}</td><td>{n}</td></tr>' for r, n in scale)
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    bodyhtml = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}</p>
    {fng_widget(lang) or '<p class="updnote">' + ('Индекс обновляется.' if ru else 'Index updating.') + '</p>'}
    <h2 class="news">{"Шкала" if ru else "Scale"}</h2>
    <div class="rtbl-wrap"><table class="rtbl"><tbody>{scale_html}</tbody></table></div>
    <p class="updnote">{src}</p>
  </div>
</div>
{crumbs}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + bodyhtml)


_HALVING_JS = r"""(function(){var el=document.getElementById('halvingBox');if(!el)return;
var T=1050000,tgt=null,b=el.querySelector('.hvb'),t=el.querySelector('.hvt');
function f(s){s=Math.max(0,s|0);var d=(s/86400)|0,h=((s%86400)/3600)|0,m=((s%3600)/60)|0,x=s%60;return d+'д '+h+'ч '+m+'м '+x+'с';}
function tick(){if(tgt&&t)t.textContent=f((tgt-Date.now())/1000);}
function go(h){var bl=T-h;if(bl<0)bl=0;if(b)b.textContent=bl;tgt=Date.now()+bl*600000;tick();setInterval(tick,1000);}
fetch('https://mempool.space/api/blocks/tip/height').then(function(r){return r.text();}).then(function(x){go(parseInt(x,10));}).catch(function(){tgt=Date.UTC(2028,3,15);if(b)b.textContent='~';tick();setInterval(tick,1000);});})();"""


def halving_widget(lang):
    ru = lang == "ru"
    h = "До халвинга Bitcoin" if ru else "Bitcoin halving in"
    sub = "Блоков осталось" if ru else "Blocks left"
    return (f'<div id="halvingBox" class="conv dosblue dosborder"><h3><a href="{PREF[lang]}/halving/">{h}</a></h3>'
            f'<p class="big" style="margin:4px 0"><span class="hvt">…</span></p>'
            f'<p class="updnote">{sub}: <span class="hvb">…</span> → блок 1&nbsp;050&nbsp;000</p></div>'
            f'<script>{_HALVING_JS}</script>')


def render_halving(lang):
    path = "/halving/"
    ru = lang == "ru"
    if ru:
        title = f"Халвинг Bitcoin — сколько осталось (счётчик) | {S['name']}"
        desc = "Сколько осталось до следующего халвинга Bitcoin: счётчик по блокам и времени. Что такое халвинг и как он влияет на рынок."
        h1, lead = "Халвинг Bitcoin — обратный отсчёт", ("Халвинг — плановое сокращение награды за блок Bitcoin "
            "вдвое, происходит каждые 210 000 блоков (примерно раз в 4 года). Следующий — на блоке 1 050 000.")
        exp = ("<h2 class=\"news\">Что такое халвинг</h2><p>Каждые 210 000 блоков награда майнерам за блок "
               "уменьшается вдвое. Это снижает эмиссию новых BTC. Исторически халвинги связывают с рыночными циклами, "
               "но прямой гарантии движения цены нет — это не прогноз.</p>"
               + ("<p class=\"related\"><a href=\"/blog/halving-bitcoin/\">Подробнее о халвинге в блоге</a></p>"
                  if "halving-bitcoin" in PUB_SLUGS["ru"] else ""))
        src = "Счётчик оценочный: считается по текущей высоте блока и среднему времени блока (~10 мин)."
    else:
        title = f"Bitcoin halving countdown — time left | {S['name']}"
        desc = "How long until the next Bitcoin halving: a countdown by blocks and time. What halving is and how it affects the market."
        h1, lead = "Bitcoin halving countdown", ("Halving is the scheduled 50% cut of the Bitcoin block reward, "
            "every 210,000 blocks (about every 4 years). The next one is at block 1,050,000.")
        exp = ("<h2 class=\"news\">What is halving</h2><p>Every 210,000 blocks the miner block reward is cut in half, "
               "reducing new BTC issuance. Halvings are associated with market cycles, but there is no guaranteed price "
               "move — this is not a forecast.</p>")
        src = "Estimated countdown: based on the current block height and average block time (~10 min)."
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    bodyhtml = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}</p>
    {halving_widget(lang)}
    {exp}
    <p class="updnote">{src}</p>
  </div>
</div>
{crumbs}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + bodyhtml)


def render_charts_overview(lang):
    """Обзор рынка по ВСЕМ валютам: спарклайн+цена+изм где есть история; иначе цена/прочерк. SEO-хаб."""
    rows = []
    for slug, info in CUR.items():
        if slug == "tether-trc20":
            continue
        h = HISTORY.get(slug, [])
        price, liq = _usdt_price(slug)
        if len(h) >= 2:
            vals = [p[1] for p in h]
            chg = (vals[-1] - vals[0]) / vals[0] * 100 if vals[0] else 0
            per = {pk: _pct_over(h, dys) for pk, dys in CHART_PERIODS}
            rows.append((2, liq, slug, info, vals[-1], chg, h[-90:], per))
        elif price is not None:
            rows.append((1, liq, slug, info, price, None, None, {}))
        else:
            rows.append((0, 0, slug, info, None, None, None, {}))
    if not rows:
        return
    rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    path = "/grafiki/"
    if lang == "ru":
        title = f"Графики курсов криптовалют — динамика цен | {S['name']}"
        desc = "Графики динамики курсов криптовалют (цена в USDT): изменение, мини-графики по всем монетам. Обновление ежечасно."
        h1, lead = "Графики курсов", f"Динамика цен в USDT по {len(rows)} валютам. Обновляется ежечасно. Нажмите на валюту — полный интерактивный график."
        th = ("Валюта", "Цена (USDT)", "Изм.", "График")
        sorts = [("liq", "По ликвидности"), ("up", "Рост ↑"), ("down", "Падение ↓")]
        plbl = "Изменение за:"
        periods = [("all", "Всё"), ("24h", "24ч"), ("7d", "7д"), ("30d", "30д"),
                   ("1y", "1г"), ("3y", "3г"), ("5y", "5л"), ("10y", "10л")]
    else:
        title = f"Cryptocurrency rate charts — price trends | {S['name']}"
        desc = "Crypto rate charts (price in USDT): change and mini-charts for all coins. Hourly updates."
        h1, lead = "Rate charts", f"Price trends in USDT across {len(rows)} currencies. Hourly updates. Click a currency for the full interactive chart."
        th = ("Currency", "Price (USDT)", "Chg.", "Chart")
        sorts = [("liq", "By liquidity"), ("up", "Gainers ↑"), ("down", "Losers ↓")]
        plbl = "Change over:"
        periods = [("all", "All"), ("24h", "24h"), ("7d", "7d"), ("30d", "30d"),
                   ("1y", "1y"), ("3y", "3y"), ("5y", "5y"), ("10y", "10y")]
    trs = ""
    for _b, _liq, slug, info, price, chg, spark, per in rows:
        price_c = f'<b>{fmt_rate(price)}</b>' if price is not None else '<span class="nd">—</span>'
        if chg is None:
            chg_c = '<span class="nd">—</span>'
        else:
            cls = "up" if chg >= 0 else "down"
            sign = "+" if chg >= 0 else ""
            chg_c = f'<b class="{cls}">{sign}{chg:.1f}%</b>'
        spk_c = mini_spark(spark) if spark else '<span class="nd">—</span>'
        chg_a = "" if chg is None else f"{chg:.4f}"
        cat_k = CAT_SLUG.get(info["category"], "prochee")
        pattrs = "".join(f' data-c{pk}="{("" if per.get(pk) is None else f"{per[pk]:.4f}")}"' for pk, _ in CHART_PERIODS)
        trs += (f'<tr data-liq="{_liq}" data-chg="{chg_a}" data-cat="{cat_k}"{pattrs}><td class="d"><a href="{cpage(lang, slug)}">{info["name"]} <span>{info["ticker"]}</span></a></td>'
                f'<td class="num">{price_c}</td><td class="num chg-cell">{chg_c}</td><td class="spk">{spk_c}</td></tr>')
    sbtns = ""
    for sv, sl in sorts:
        son = ' class="on"' if sv == "liq" else ""
        sbtns += f'<button type="button" data-s="{sv}"{son}>{sl}</button>'
    filts = [("", "Все" if lang == "ru" else "All")] + [(CAT_SLUG[c], cat_name(c, lang)) for c in CATS]
    fbtns = ""
    for fv, fl in filts:
        fon = ' class="on"' if fv == "" else ""
        fbtns += f'<button type="button" data-f="{fv}"{fon}>{fl}</button>'
    pbtns = ""
    for pv, pl in periods:
        pon = ' class="on"' if pv == "all" else ""
        pbtns += f'<button type="button" data-p="{pv}"{pon}>{pl}</button>'
    ld = jsonld({"@context": "https://schema.org", "@type": "CollectionPage", "name": h1,
                 "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang], "dateModified": modified_iso()})
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1} <span class="cnt">{len(rows)}</span></h1><p>{lead}</p>
    <p class="updnote">{updated_str(lang)}</p>
    <div class="rsrange catbar">{fbtns}</div>
    <div class="rsrange sortbar">{sbtns}</div>
    <div class="perrow"><span class="ctllbl">{plbl}</span><span class="rsrange perbar">{pbtns}</span></div>
    <div class="rtbl-wrap"><table class="rtbl marktbl"><thead><tr>
      <th>{th[0]}</th><th>{th[1]}</th><th>{th[2]}</th><th>{th[3]}</th></tr></thead><tbody>{trs}</tbody></table></div>
  </div>
</div>
{ld}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path, ld) + body)


def render_relative(lang):
    """Страница относительных (кросс-)курсов: 1 базовая валюта → все остальные, с поиском/фильтром/сортировкой.
    Кросс-курс считается на клиенте через USDT (prices.json). Фильтры по всем валютам."""
    path = "/kursy/"
    if lang == "ru":
        title = f"Относительные курсы валют — 1 валюта к другим | {S['name']}"
        desc = "Относительные (кросс-) курсы валют: выберите базовую валюту и увидите её курс ко всем остальным. Фильтр по категориям, поиск."
        h1, lead = "Относительные курсы валют", "Выберите базовую валюту — увидите, сколько за 1 её единицу дают в других валютах (кросс-курс через USDT). Поиск и фильтр по всем валютам."
        blbl, ph, nores = "Базовая валюта:", "Поиск валюты: BTC, USDT, Sberbank…", "Ничего не найдено"
        th = ("Валюта", "Курс")
        rate_tpl = "Курс (1 {b} = …)"
        sorts = [("rate-desc", "Курс ↓"), ("rate-asc", "Курс ↑"), ("name", "А–Я")]
    else:
        title = f"Relative currency rates — 1 currency to others | {S['name']}"
        desc = "Relative (cross) currency rates: pick a base currency and see its rate to all others. Category filter, search."
        h1, lead = "Relative currency rates", "Pick a base currency — see how much 1 unit is worth in other currencies (cross rate via USDT). Search and filter across all currencies."
        blbl, ph, nores = "Base currency:", "Search currency: BTC, USDT, Sberbank…", "Nothing found"
        th = ("Currency", "Rate")
        rate_tpl = "Rate (1 {b} = …)"
        sorts = [("rate-desc", "Rate ↓"), ("rate-asc", "Rate ↑"), ("name", "A–Z")]

    def _btns(items, attr, default):
        out = ""
        for v, l in items:
            on = ' class="on"' if v == default else ""
            out += f'<button type="button" data-{attr}="{v}"{on}>{l}</button>'
        return out
    fbtns = _btns([("", "Все" if lang == "ru" else "All")] + [(CAT_SLUG[c], cat_name(c, lang)) for c in CATS], "f", "")
    sbtns = _btns(sorts, "s", "rate-desc")
    ld = jsonld({"@context": "https://schema.org", "@type": "CollectionPage", "name": h1,
                 "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang], "dateModified": modified_iso()})
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}</p>
    <div class="relbaserow"><label>{blbl} <select class="relbase" data-prefix="{PREF[lang]}"></select></label></div>
    <div class="rtsearchbox"><input class="relsearch" type="search" placeholder="{ph}" autocomplete="off" aria-label="{ph}"></div>
    <div class="rsrange relcat">{fbtns}</div>
    <div class="rsrange relsort">{sbtns}</div>
    <div class="rtbl-wrap"><table class="rtbl relmtbl"><thead><tr><th>{th[0]}</th><th class="rthd" data-tpl="{rate_tpl}">{th[1]}</th></tr></thead>
      <tbody class="relbody"></tbody></table></div>
    <p class="relnone updnote" hidden>{nores}</p>
    <p class="updnote">{updated_str(lang)}</p>
  </div>
</div>
{ld}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path, ld) + body)


def history_table(slug, lang):
    """Текстовая (индексируемая) таблица динамики курса из истории: закрытие/мин/макс/изм. к пред. периоду.
    Гранулярность адаптивная: пока истории < ~2 мес — по дням, дальше — по месяцам."""
    pts = HISTORY.get(slug, [])
    if len(pts) < 6:
        return ""
    def _d(s):
        return datetime.strptime(s[:10], "%Y-%m-%d")
    span = (_d(pts[-1][0]) - _d(pts[0][0])).days
    by_month = span >= 60
    keylen, keep = (7, 24) if by_month else (10, 60)   # YYYY-MM×24 или YYYY-MM-DD×60
    buckets, order = {}, []
    for k, v in pts:                      # точки по возрастанию даты
        key = k[:keylen]
        if key not in buckets:
            buckets[key] = {"min": v, "max": v, "close": v}
            order.append(key)
        d = buckets[key]
        d["close"] = v
        d["min"] = min(d["min"], v)
        d["max"] = max(d["max"], v)
    if len(order) < 2:
        return ""
    tk = CUR[slug]["ticker"]
    per_ru, per_en = ("месяцам", "Месяц") if by_month else ("дням", "Дата")
    if lang == "ru":
        h, cols = f"Курс {tk} по {per_ru} (USDT)", (per_en, "Закрытие", "Минимум", "Максимум", "Изм.")
        lead = f"Динамика цены {tk} в USDT по данным мониторинга BestChange (справочно)."
    else:
        h = f"{tk} {'monthly' if by_month else 'daily'} rate (USDT)"
        cols = ("Month" if by_month else "Date", "Close", "Low", "High", "Chg.")
        lead = f"{tk} price dynamics in USDT per BestChange monitoring data (for reference)."
    rows, prev = [], None
    for m in order[-keep:]:
        d = buckets[m]
        chg = "—"
        if prev:
            pc = (d["close"] - prev) / prev * 100
            cl = "up" if pc >= 0 else "down"
            chg = f'<b class="{cl}">{"+" if pc >= 0 else ""}{pc:.1f}%</b>'
        prev = d["close"]
        rows.append(f"<tr><td>{m}</td><td>{fmt_rate(d['close'])}</td><td>{fmt_rate(d['min'])}</td>"
                    f"<td>{fmt_rate(d['max'])}</td><td>{chg}</td></tr>")
    head_html = "".join(f"<th>{c}</th>" for c in cols)
    n = len(rows)
    pager = '<div class="histpager"></div>' if n > 10 else ""   # клиентская пагинация по 10 строк
    # свёрнутый список (details) — чтобы растущая таблица не удлиняла страницу
    return (f'<details class="histbox"><summary class="news">{h}<span class="cnt"> ({n})</span></summary>'
            f'<p class="updnote">{lead}</p>'
            f'<div class="rtbl-wrap"><table class="rtbl"><thead><tr>{head_html}</tr></thead>'
            f'<tbody>{"".join(reversed(rows))}</tbody></table></div>{pager}</details>')


def currency_chart(slug, info, lang):
    pts = HISTORY.get(slug, [])
    if len(pts) < 2:
        if lang == "ru":
            return (f'<h2 class="news">Динамика цены {info["ticker"]} (USDT)</h2>'
                    f'<p class="updnote">📈 Идёт накопление данных — график появится, когда наберётся история '
                    f'(точек сейчас: {len(pts)}). Обновляется ежедневно.</p>') if pts else ""
        return (f'<h2 class="news">{info["ticker"]} price trend (USDT)</h2>'
                f'<p class="updnote">📈 Collecting data — the chart will appear once history builds up '
                f'(points so far: {len(pts)}). Updated daily.</p>') if pts else ""
    data = pts[-2000:]                      # недавние почасовые + дневные (годы) — для интерактива
    vals = [p[1] for p in data]
    first, last = vals[0], vals[-1]
    chg = (last - first) / first * 100 if first else 0
    sign = "+" if chg >= 0 else ""
    cls = "up" if chg >= 0 else "down"
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    if lang == "ru":
        title = f"Динамика цены {info['ticker']} (USDT)"
        ranges = [("24h", "24ч"), ("7d", "7д"), ("30d", "30д"), ("1y", "1г"),
                  ("3y", "3г"), ("5y", "5л"), ("10y", "10л"), ("all", "Всё")]
        note = (f"1 {info['ticker']} = <b>{fmt_rate(last)}</b> USDT · за период: "
                f'<b class="{cls}">{sign}{chg:.1f}%</b>. Данные BestChange, обновление ежечасно. '
                "Наведите на график — покажет цену и время.")
    else:
        title = f"{info['ticker']} price trend (USDT)"
        ranges = [("24h", "24h"), ("7d", "7d"), ("30d", "30d"), ("1y", "1y"),
                  ("3y", "3y"), ("5y", "5y"), ("10y", "10y"), ("all", "All")]
        note = (f"1 {info['ticker']} = <b>{fmt_rate(last)}</b> USDT · change: "
                f'<b class="{cls}">{sign}{chg:.1f}%</b>. BestChange data, hourly. '
                "Hover the chart to see price and time.")
    # кнопка диапазона появляется, только когда истории хватает на этот период
    def _pt(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:00")
        except ValueError:
            return datetime.strptime(s, "%Y-%m-%d")
    span_days = (_pt(data[-1][0]) - _pt(data[0][0])).total_seconds() / 86400
    DURD = {"24h": 1, "7d": 7, "30d": 30, "1y": 365, "3y": 3 * 365, "5y": 5 * 365, "10y": 10 * 365, "all": 0}
    ranges = [(r, lbl) for r, lbl in ranges if r == "all" or span_days >= DURD[r]]
    btns = ""
    for r, lbl in ranges:
        on = ' class="on"' if r == "all" else ""
        btns += f'<button type="button" data-r="{r}"{on}>{lbl}</button>'
    mon_lbl = (f"📊 Сравнить {info['ticker']} с другими валютами в мониторе →" if lang == "ru"
               else f"📊 Compare {info['ticker']} with other currencies in the monitor →")
    open_mon = (f'<p class="openmon-wrap"><a class="openmon" href="{PREF[lang]}/monitor/?cur={slug}">{mon_lbl}</a></p>')
    return (f'<h2 class="news" id="chart">{title}</h2>'
            f'<div class="rschart-wrap" data-ticker="{info["ticker"]}" data-unit="USDT">'
            f'<div class="rsrange">{btns}</div>'
            f'<div class="rschart"><noscript>{svg_chart(pts[-90:])}</noscript></div>'
            f'<div class="rsperiod"></div>'
            f'<div class="rstip" hidden></div>'
            f'<script type="application/json" class="rschart-data">{data_json}</script>'
            f'</div>'
            f'<p class="updnote">{note}</p>'
            f'{open_mon}')


def pair_chart(f, t, lang):
    """График динамики курса пары (кросс-курс history[from]/history[to], выровненный по времени).
    Тот же интерактивный компонент, что на страницах валют. Нет истории по одной из валют — не рисуем."""
    base = "tether-trc20"                           # база истории (цена всех в USDT); своего ряда нет (=1)
    hf, ht = HISTORY.get(f) or [], HISTORY.get(t) or []
    if t == base and len(hf) >= 2:                   # X → USDT: ряд = цена X в USDT (напрямую)
        pts = [[d, v] for d, v in hf]
    elif f == base and len(ht) >= 2:                 # USDT → X: ряд = 1/цена X
        pts = [[d, 1.0 / v] for d, v in ht if v]
    elif len(hf) >= 2 and len(ht) >= 2:              # обе стороны есть → кросс-курс
        tmap = {d: v for d, v in ht}
        pts = [[d, vf / tmap[d]] for d, vf in hf if tmap.get(d)]
    else:
        return ""
    if len(pts) < 2:
        return ""
    # заякорить серию на текущий лучший курс: последняя точка = курс из шапки, тренд сохраняется
    r = rate_of(f, t)
    if r and r.get("rate") and pts[-1][1]:
        try:
            k = float(r["rate"]) / pts[-1][1]
            pts = [[d, v * k] for d, v in pts]
        except (TypeError, ValueError):
            pass
    fT, tT = CUR[f]["ticker"], CUR[t]["ticker"]
    data = pts[-2000:]
    vals = [p[1] for p in data]
    first, last = vals[0], vals[-1]
    chg = (last - first) / first * 100 if first else 0
    sign = "+" if chg >= 0 else ""
    cls = "up" if chg >= 0 else "down"
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    if lang == "ru":
        title = f"Динамика курса {fT} → {tT}"
        ranges = [("24h", "24ч"), ("7d", "7д"), ("30d", "30д"), ("1y", "1г"),
                  ("3y", "3г"), ("5y", "5л"), ("10y", "10л"), ("all", "Всё")]
        note = (f"1 {fT} = <b>{fmt_rate(last)}</b> {tT} · за период: "
                f'<b class="{cls}">{sign}{chg:.1f}%</b>. Кросс-курс по данным BestChange, обновление ежечасно. '
                "Наведите на график — покажет курс и время.")
    else:
        title = f"{fT} → {tT} rate trend"
        ranges = [("24h", "24h"), ("7d", "7d"), ("30d", "30d"), ("1y", "1y"),
                  ("3y", "3y"), ("5y", "5y"), ("10y", "10y"), ("all", "All")]
        note = (f"1 {fT} = <b>{fmt_rate(last)}</b> {tT} · change: "
                f'<b class="{cls}">{sign}{chg:.1f}%</b>. Cross-rate, BestChange data, hourly. '
                "Hover the chart to see rate and time.")

    def _pt(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:00")
        except ValueError:
            return datetime.strptime(s, "%Y-%m-%d")
    span_days = (_pt(data[-1][0]) - _pt(data[0][0])).total_seconds() / 86400
    DURD = {"24h": 1, "7d": 7, "30d": 30, "1y": 365, "3y": 3 * 365, "5y": 5 * 365, "10y": 10 * 365, "all": 0}
    ranges = [(r, lbl) for r, lbl in ranges if r == "all" or span_days >= DURD[r]]
    btns = ""
    for r, lbl in ranges:
        on = ' class="on"' if r == "all" else ""
        btns += f'<button type="button" data-r="{r}"{on}>{lbl}</button>'
    # кнопка в монитор: обе валюты пары, но только те, что реально есть в истории/мониторе
    mon_slugs = [s for s in dict.fromkeys((f, t)) if len(HISTORY.get(s) or []) >= 2]
    open_mon = ""
    if mon_slugs:
        mlbl = (f"📊 Сравнить {fT} и {tT} в мониторе →" if lang == "ru"
                else f"📊 Compare {fT} and {tT} in the monitor →")
        open_mon = (f'<p class="openmon-wrap"><a class="openmon" '
                    f'href="{PREF[lang]}/monitor/?cur={",".join(mon_slugs)}">{mlbl}</a></p>')
    return (f'<h2 class="news" id="chart">{title}</h2>'
            f'<div class="rschart-wrap" data-ticker="{fT}" data-unit="{tT}">'
            f'<div class="rsrange">{btns}</div>'
            f'<div class="rschart"><noscript>{svg_chart(pts[-90:])}</noscript></div>'
            f'<div class="rsperiod"></div>'
            f'<div class="rstip" hidden></div>'
            f'<script type="application/json" class="rschart-data">{data_json}</script>'
            f'</div>'
            f'<p class="updnote">{note}</p>'
            f'{open_mon}')


def _daily_closes(series):
    """Дневные закрытия из ряда [[дата,цена],...] — последняя цена за календарный день."""
    by_day = {}
    for ds, v in series:
        by_day[ds[:10]] = v
    return [by_day[d] for d in sorted(by_day)]


def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _rsi(closes, period=14):
    """RSI(14) по дневным закрытиям. None, пока истории мало (нужно ≥ period+1 точек, иначе значение крайнее/шумное)."""
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i - 1]
        gains += d if d > 0 else 0.0
        losses += -d if d < 0 else 0.0
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)


def currency_metrics(slug):
    """Технические показатели по ряду цен из HISTORY (все считаем сами, без внешних API). None — мало данных."""
    pts = HISTORY.get(slug) or []
    if len(pts) < 3:
        return None
    chg = CHG_BY.get(slug, {})
    closes = _daily_closes(pts)
    span = _span_days(pts)
    m = {}
    # показываем период, только если истории на него реально хватает (иначе 7д==30д при молодой истории)
    for pk, need in (("24h", 0), ("7d", 5), ("30d", 20)):
        if chg.get(pk) is not None and span >= need:
            m[pk] = chg[pk]
    # волатильность за 7д — стандартное отклонение доходностей (показываем при истории ≥ 5 дней)
    if span >= 5:
        win = _pwindow(pts, 7)
        dc = _daily_closes(win)
        seq = dc if len(dc) >= 3 else [v for _, v in win]
        rets = [seq[i] / seq[i - 1] - 1 for i in range(1, len(seq)) if seq[i - 1]]
        if rets:
            m["vol"] = _stdev(rets) * 100
    # диапазон макс–мin за доступную историю + позиция цены в нём
    allv = [v for _, v in pts]
    lo, hi, cur = min(allv), max(allv), allv[-1]
    m["low"], m["high"] = lo, hi
    if hi > lo:
        m["pos"] = (cur - lo) / (hi - lo) * 100
    # SMA(7) и тренд относительно неё
    if len(closes) >= 3:
        n = min(7, len(closes))
        sma = sum(closes[-n:]) / n
        m["sma"] = sma
        m["trend"] = "up" if closes[-1] > sma * 1.005 else ("down" if closes[-1] < sma * 0.995 else "flat")
    r = _rsi(closes)
    if r is not None:
        m["rsi"] = r
    return m or None


def currency_metrics_block(slug, info, lang):
    """Блок «Технические показатели» на странице валюты — всё посчитано по нашим данным, справочно (не сигнал)."""
    m = currency_metrics(slug)
    if not m:
        return ""
    ru, t = lang == "ru", info["ticker"]

    def pct(v):
        return f'<span class="{"up" if v >= 0 else "down"}">{"+" if v >= 0 else ""}{v:.1f}%</span>'
    rows = []
    if "24h" in m:
        rows.append(("Изменение за 24ч" if ru else "Change 24h", pct(m["24h"])))
    if "7d" in m:
        rows.append(("Изменение за 7д" if ru else "Change 7d", pct(m["7d"])))
    if "30d" in m:
        rows.append(("Изменение за 30д" if ru else "Change 30d", pct(m["30d"])))
    if "vol" in m:
        rows.append(("Волатильность (7д)" if ru else "Volatility (7d)", f'{m["vol"]:.1f}%'))
    if "trend" in m:
        lbl = {"up": ("Рост", "Uptrend"), "down": ("Снижение", "Downtrend"), "flat": ("Боковик", "Flat")}[m["trend"]]
        rows.append(("Тренд (SMA)" if ru else "Trend (SMA)", lbl[0] if ru else lbl[1]))
    if "rsi" in m:
        z = ""
        if m["rsi"] >= 70:
            z = " · зона перекупленности" if ru else " · overbought zone"
        elif m["rsi"] <= 30:
            z = " · зона перепроданности" if ru else " · oversold zone"
        rows.append(("RSI (14)", f'{m["rsi"]:.0f}{z}'))
    if "low" in m and "high" in m:
        rows.append(("Диапазон макс–мин" if ru else "Range (min–max)",
                     f'{fmt_rate(m["low"])} – {fmt_rate(m["high"])} USDT'))
    body = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
    h = f"Технические показатели {t}" if ru else f"{t} technical metrics"
    disc = ("Показатели рассчитаны по данным мониторинга BestChange, справочно. Не являются сигналом "
            "или финансовой рекомендацией." if ru else
            "Metrics computed from BestChange monitoring data, for reference. Not a signal or financial advice.")
    return (f'<h2 class="news">{h}</h2>'
            f'<div class="rtbl-wrap"><table class="rtbl"><tbody>{body}</tbody></table></div>'
            f'<p class="updnote">{disc}</p>')


def _human_usd(n, lang):
    """$1.28 трлн / $850 млрд … (RU) или T/B/M/K (EN)."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    for div, ru, en in ((1e12, "трлн", "T"), (1e9, "млрд", "B"), (1e6, "млн", "M"), (1e3, "тыс", "K")):
        if n >= div:
            return f"${n / div:.2f} {ru if lang == 'ru' else en}"
    return f"${n:.0f}"


def _human_num(n, lang):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    for div, ru, en in ((1e12, "трлн", "T"), (1e9, "млрд", "B"), (1e6, "млн", "M"), (1e3, "тыс", "K")):
        if n >= div:
            return f"{n / div:.2f} {ru if lang == 'ru' else en}"
    return f"{n:.0f}"


def market_block(slug, info, lang):
    """Блок «Рыночные данные» по CoinGecko (капитализация/объём/ATH/предложение). Факты рынка, с указанием источника."""
    d = MARKET.get(slug)
    if not d or not d.get("mcap"):
        return ""
    ru, t = lang == "ru", info["ticker"]
    rows = []
    cap = _human_usd(d["mcap"], lang)
    if d.get("rank"):
        cap += f' <span class="tk">#{d["rank"]}</span>'
    rows.append(("Капитализация" if ru else "Market cap", cap))
    if d.get("vol"):
        rows.append(("Объём торгов (24ч)" if ru else "Volume (24h)", _human_usd(d["vol"], lang)))
    if d.get("ath"):
        athc = d.get("ath_chg")
        note = f' <span class="down">{athc:.0f}% {"от ATH" if ru else "from ATH"}</span>' if athc is not None else ""
        rows.append(("Исторический максимум" if ru else "All-time high", f'{fmt_rate(d["ath"])} USD{note}'))
    if d.get("supply"):
        rows.append(("В обращении" if ru else "Circulating supply", f'{_human_num(d["supply"], lang)} {t}'))
    for pk, ru_l, en_l in (("chg7d", "Изменение 7д (биржи)", "Change 7d (market)"),
                           ("chg30d", "Изменение 30д (биржи)", "Change 30d (market)")):
        v = d.get(pk)
        if v is not None:
            cls = "up" if v >= 0 else "down"
            rows.append((ru_l if ru else en_l, f'<span class="{cls}">{"+" if v >= 0 else ""}{v:.1f}%</span>'))
    body = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
    h = f"Рыночные данные {t}" if ru else f"{t} market data"
    src = ("Источник: CoinGecko. Приведено справочно." if ru else "Source: CoinGecko. For reference.")
    return (f'<h2 class="news">{h}</h2>'
            f'<div class="rtbl-wrap"><table class="rtbl"><tbody>{body}</tbody></table></div>'
            f'<p class="updnote">{src}</p>')


def rate_of(frm, to):
    return RATES.get(f"{frm}>{to}")


TOP = []
_tp = os.path.join(ROOT, "top.json")
if os.path.exists(_tp):
    try:
        TOP = [p for p in json.load(open(_tp, encoding="utf-8")).get("pairs", [])
               if p.get("from") in CUR and p.get("to") in CUR]
    except (ValueError, OSError):
        TOP = []
TOP_SET = {(p["from"], p["to"]) for p in TOP}

# Высокоинтентные направления: топ-крипта ↔ главные банки/кошельки/наличные (только где есть реальный курс).
# Обе стороны: крипта→получатель («вывести USDT на Сбербанк») и получатель→крипта («купить BTC за рубли»).
# Каждая пара гейтится наличием курса в RATES — пустых страниц не создаём. Slug-и сверены с каталогом.
HI_CRYPTO = ["tether-trc20", "bitcoin", "ethereum", "tether-erc20", "tether-bep20", "usd-coin",
             "tron", "litecoin", "monero", "solana", "tether-polygon", "bitcoin-cash", "dogecoin",
             "tether-ton", "binance-coin", "dash", "cardano", "ripple"]
HI_RECV = ["sberbank", "tinkoff", "sbp", "cash-ruble", "visa-mastercard-rub", "mir", "alfaclick",
           "vtb", "gazprombank", "yoomoney", "raiffeisen-bank", "ozon", "visa-mastercard-usd",
           "visa-mastercard-euro", "wise", "paypal-usd", "kaspi-bank", "monobank", "capitalist"]
EXTRA_PAIRS = []
_ep_seen = set()
for _c in HI_CRYPTO:
    for _r in HI_RECV:
        for _f, _t in ((_c, _r), (_r, _c)):        # прямое (вывод) и обратное (покупка) направления
            if (_f in CUR and _t in CUR and (_f, _t) not in TOP_SET
                    and (_f, _t) not in _ep_seen and RATES.get(f"{_f}>{_t}")):
                _ep_seen.add((_f, _t))
                EXTRA_PAIRS.append({"from": _f, "to": _t})

# Все пары, для которых генерим страницы (топ + высокоинтентные), с дедупом.
PAIR_PAGES = TOP + EXTRA_PAIRS
_seen = set()
PAIR_PAGES = [p for p in PAIR_PAGES if not ((p["from"], p["to"]) in _seen or _seen.add((p["from"], p["to"])))]
PAIR_SET = {(p["from"], p["to"]) for p in PAIR_PAGES}

# RU-only расширение: страницы под ВСЕ направления с ≥ MIN_RU_COUNT обменников (кроме уже в PAIR_PAGES).
# Даёт большой SEO-охват + внутренние ссылки для конвертера; English оставляем компактным (только PAIR_PAGES).
MIN_RU_COUNT = 10
PAIR_PAGES_RU = []
for _k, _v in RATES.items():
    if (_v.get("count", 0) or 0) >= MIN_RU_COUNT:
        _f, _t = _k.split(">", 1)
        if _f in CUR and _t in CUR and (_f, _t) not in _seen:
            _seen.add((_f, _t))
            PAIR_PAGES_RU.append({"from": _f, "to": _t})
# Полное множество страниц-пар (для sitemap RU / конвертера / проверок ссылок).
PAIR_SET_ALL = PAIR_SET | {(p["from"], p["to"]) for p in PAIR_PAGES_RU}

# Карта: валюта → покрытые направления с её участием (для статической перелинковки со страниц валют).
DIRS_BY_CUR = {}
for _f, _t in PAIR_SET_ALL:
    _c = (RATES.get(f"{_f}>{_t}") or {}).get("count", 0) or 0
    DIRS_BY_CUR.setdefault(_f, []).append((_f, _t, _c))
    DIRS_BY_CUR.setdefault(_t, []).append((_f, _t, _c))

# Банковские хабы: «все монеты → конкретный получатель» (крупные RUB-направления).
# Страница /na/<slug>/ агрегирует крипто→этот банк с курсами — высокоинтентный money-лендинг.
BANK_HUB_LIST = ["sberbank", "tinkoff", "sbp", "cash-ruble", "visa-mastercard-rub",
                 "mir", "alfaclick", "vtb", "gazprombank", "yoomoney"]


# Пары для встраиваемого виджета: (ключ, from_slug, to_slug, показ_from, показ_to, url на нашем сайте)
WIDGET_PAIRS = [
    ("usdt-rub", "tether-trc20", "sberbank", "USDT", "RUB", "/na/sberbank/"),
    ("btc-rub", "bitcoin", "sberbank", "BTC", "RUB", "/obmen/bitcoin-sberbank/"),
    ("eth-rub", "ethereum", "sberbank", "ETH", "RUB", "/valuta/ethereum/"),
    ("btc-usdt", "bitcoin", "tether-trc20", "BTC", "USDT", "/obmen/bitcoin-tether-trc20/"),
    ("eth-usdt", "ethereum", "tether-trc20", "ETH", "USDT", "/valuta/ethereum/"),
    ("ton-usdt", "ton", "tether-trc20", "TON", "USDT", "/valuta/ton/"),
    ("trx-usdt", "tron", "tether-trc20", "TRX", "USDT", "/valuta/tron/"),
    ("ltc-usdt", "litecoin", "tether-trc20", "LTC", "USDT", "/valuta/litecoin/"),
]


def _crypto_rate_count(to_slug):
    return sum(1 for fs, _ in GROUPED.get("Криптовалюты", []) if RATES.get(f"{fs}>{to_slug}"))


# хабы, у которых реально ≥5 крипто-направлений (иначе не рендерим — не плодим тонкие)
BANK_HUBS = [b for b in BANK_HUB_LIST if b in CUR and _crypto_rate_count(b) >= 5]
BANK_HUB_SET = set(BANK_HUBS)


def fmt_rate(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return s
    if v >= 1000:
        return f"{v:,.0f}".replace(",", " ")
    if v >= 1:
        return f"{v:,.2f}".replace(",", " ")
    if v >= 0.01:
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return (f"{v:.12f}".rstrip("0").rstrip(".")) or "0"


# ---------------- переводы UI ----------------
TR = {
    "ru": {
        "nav_monitor": "Монитор", "nav_blog": "Блог", "nav_about": "Что такое BestChange",
        "nav_aml": "AML-проверка", "nav_disc": "Раскрытие", "nav_faq": "Вопросы", "nav_glossary": "Словарь", "nav_widget": "Виджеты", "nav_charts": "Графики", "nav_rates": "Курсы", "nav_dirs": "Направления", "nav_reviews": "Обзоры", "nav_svodka": "Сводка", "nav_articles": "Статьи", "nav_leaders": "Лидеры рынка", "nav_mood": "Индекс страха", "nav_compare": "Сравнение валют",
        "search_ph": "Поиск: BTC, USDT, Sberbank…", "search_aria": "Поиск валюты",
        "monitor": "Монитор", "sections": "Разделы", "all_cur": "Все валюты",
        "catalog": "Каталог валют", "total": "всего", "popular": "Популярные направления",
        "about_cur": "О валюте", "directions": "Направления обмена", "how_to": "Как обменять",
        "faq": "Частые вопросы", "useful": "Полезное", "open_dir": "Открыть направление →",
        "find_rate": "Открыть направление →", "calc": "Калькулятор направления",
        "give": "Отдаю", "get": "Получаю", "swap": "⇅ поменять",
        "ticker": "Тикер", "category": "Категория", "network": "Сеть",
        "glossary": "Словарь терминов", "usdt_nets": "Сети USDT", "fees": "Комиссии сетей", "aml_link": "AML-проверка",
        "open_bc": "Открыть направление в BestChange →",
        "blog_search_ph": "Поиск по статьям…", "blog_noresults": "Ничего не найдено. Попробуйте другой запрос.",
        "amount": "Сумма", "approx": "≈ получите", "get_cta": "Получить",
    },
    "en": {
        "nav_monitor": "Monitor", "nav_blog": "Blog", "nav_about": "What is BestChange",
        "nav_aml": "AML check", "nav_disc": "Disclosure", "nav_faq": "FAQ", "nav_glossary": "Glossary", "nav_widget": "Widgets", "nav_charts": "Charts", "nav_rates": "Rates", "nav_dirs": "Directions", "nav_reviews": "Reviews", "nav_svodka": "Summary", "nav_articles": "Articles", "nav_leaders": "Market leaders", "nav_mood": "Fear & Greed", "nav_compare": "Compare coins",
        "search_ph": "Search currency: BTC, USDT, Sberbank…", "search_aria": "Currency search",
        "monitor": "Monitor", "sections": "Sections", "all_cur": "All currencies",
        "catalog": "Currency catalog", "total": "total", "popular": "Popular directions",
        "about_cur": "About", "directions": "Exchange directions for", "how_to": "How to exchange",
        "faq": "FAQ", "useful": "Useful", "open_dir": "Open direction →",
        "find_rate": "Open direction →", "calc": "Direction calculator",
        "give": "Send", "get": "Receive", "swap": "⇅ swap",
        "ticker": "Ticker", "category": "Category", "network": "Network",
        "glossary": "Glossary", "usdt_nets": "USDT networks", "fees": "Network fees", "aml_link": "AML check",
        "open_bc": "Open direction on BestChange →",
        "blog_search_ph": "Search articles…", "blog_noresults": "Nothing found. Try a different query.",
        "amount": "Amount", "approx": "≈ you get", "get_cta": "Get",
    },
}


def tr(lang, key):
    return TR[lang][key]


# ---------------- вывод ----------------
def out_path(lang, path):
    """path вида '/valuta/x/' → файл в dist с учётом префикса языка."""
    p = (PREF[lang] + path).strip("/")
    return (p + "/index.html") if p else "index.html"


def write(lang, path, html):
    full = os.path.join(DIST, out_path(lang, path))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "w", encoding="utf-8").write(html)


def jsonld(o):
    return f'<script type="application/ld+json">{json.dumps(o, ensure_ascii=False)}</script>'


def howto_ld(name, steps):
    """HowTo-разметка из списка шагов (теги в тексте вычищаются)."""
    return jsonld({"@context": "https://schema.org", "@type": "HowTo", "name": name,
                   "step": [{"@type": "HowToStep", "position": i + 1,
                             "text": re.sub("<[^>]+>", "", s)} for i, s in enumerate(steps)]})


def itemlist_ld(items):
    """ItemList-разметка: items = [(name, absolute_url), ...]."""
    return jsonld({"@context": "https://schema.org", "@type": "ItemList",
                   "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "url": u}
                                       for i, (n, u) in enumerate(items)]})


def _plain_num(v):
    """Число → десятичная строка без научной нотации (для schema.org price). None если некорректно."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    s = ("%.12f" % v).rstrip("0").rstrip(".") if v < 1 else ("%.8f" % v).rstrip("0").rstrip(".")
    return s or None


def exchange_rate_ld(base_t, price, quote_t):
    """ExchangeRateSpecification — профильная schema.org для курса (1 base = price quote). '' если нет курса."""
    p = _plain_num(price)
    if not p:
        return ""
    return jsonld({"@context": "https://schema.org", "@type": "ExchangeRateSpecification",
                   "currency": base_t,
                   "currentExchangeRate": {"@type": "UnitPriceSpecification",
                                           "price": p, "priceCurrency": quote_t}})


def trust_bar(lang):
    """Полоса доверия/свежести: сколько валют и направлений в базе + когда обновлено + ссылка на методику."""
    nc, nd = len(CUR), len(RATES)
    if lang == "ru":
        intro = (f'<b>RateScout</b> — бесплатный справочник курсов обмена криптовалют и наличных '
                 f'по данным мониторинга обменников <b>BestChange</b>. В базе <b>{nc}</b> валют '
                 f'и <b>{nd}</b> направлений обмена; курсы обновляются <b>ежечасно</b> '
                 f'и приведены для справки (не оферта).')
        facts = (f'<span>Валют: <b>{nc}</b></span><span>Направлений: <b>{nd}</b></span>'
                 f'<span>{updated_str(lang)}</span>'
                 f'<span><a href="{PREF[lang]}/redakciya/">Методика и источник данных →</a></span>')
    else:
        intro = (f'<b>RateScout</b> is a free directory of crypto and cash exchange rates '
                 f'based on <b>BestChange</b> exchange-monitoring data. It tracks <b>{nc}</b> currencies '
                 f'and <b>{nd}</b> exchange directions; rates are updated <b>hourly</b> '
                 f'and provided for reference (not an offer).')
        facts = (f'<span>Currencies: <b>{nc}</b></span><span>Directions: <b>{nd}</b></span>'
                 f'<span>{updated_str(lang)}</span>'
                 f'<span><a href="{PREF[lang]}/redakciya/">Methodology &amp; data source →</a></span>')
    return (f'<section class="trustbar dosborder">'
            f'<p class="answer tb-intro">{intro}</p>'
            f'<div class="tb-facts">{facts}</div></section>')


METRIKA = """<!-- Yandex.Metrika counter -->
<script type="text/javascript">
   (function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
   m[i].l=1*new Date();
   for (var j = 0; j < document.scripts.length; j++) {if (document.scripts[j].src === r) { return; }}
   k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})
   (window, document,'script','https://mc.yandex.ru/metrika/tag.js?id=111586112', 'ym');
   ym(111586112, 'init', {ssr:true, webvisor:true, clickmap:true, ecommerce:"dataLayer", accurateTrackBounce:true, trackLinks:true});
</script>
<noscript><div><img src="https://mc.yandex.ru/watch/111586112" style="position:absolute; left:-9999px;" alt="" /></div></noscript>
<!-- /Yandex.Metrika counter -->"""

GTAG = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-PPN27D6JXS"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-PPN27D6JXS');
</script>
<!-- /Google tag -->"""

GTM_HEAD = """<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','GTM-N328Z8XP');</script>
<!-- End Google Tag Manager -->"""

GTM_BODY = """<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-N328Z8XP"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->"""

LIVEINTERNET = """<!--LiveInternet counter--><a href="https://www.liveinternet.ru/click"
target="_blank"><img id="licnt737E" width="88" height="31" style="border:0"
title="LiveInternet: показано число просмотров и посетителей за 24 часа"
src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAEALAAAAAABAAEAAAIBTAA7"
alt=""/></a><script>(function(d,s){d.getElementById("licnt737E").src=
"https://counter.yadro.ru/hit?t52.6;r"+escape(d.referrer)+
((typeof(s)=="undefined")?"":";s"+s.width+"*"+s.height+"*"+
(s.colorDepth?s.colorDepth:s.pixelDepth))+";u"+escape(d.URL)+
";h"+escape(d.title.substring(0,150))+";"+Math.random()})
(document,screen)</script><!--/LiveInternet-->"""


# Ранний выбор языка: если пользователь НЕ выбирал вручную (нет rs_lang) — редирект
# на версию под язык браузера (ru → корень, иначе → /en/). Ручной выбор (клик по .langsw)
# сохраняется в localStorage и отключает автоопределение. Ботов не трогаем (SEO).
LANGREDIR = """<script>(function(){try{
if(window.RS_NOTR)return;
var ua=navigator.userAgent||"";if(/bot|crawl|spider|slurp|bing|yandex|google/i.test(ua))return;
var p=location.pathname,isEn=p==="/en"||p.indexOf("/en/")===0,cur=isEn?"en":"ru";
var s=localStorage.getItem("rs_lang"),want;
if(s==="ru"||s==="en"){want=s;}else{var n=(navigator.languages&&navigator.languages[0])||navigator.language||"en";want=/^ru\\b/i.test(n)?"ru":"en";}
if(want===cur)return;
var t=want==="en"?("/en"+(p==="/"?"/":p)):p.replace(/^\\/en(\\/|$)/,"/");
location.replace(t+location.search+location.hash);
}catch(e){}})();</script>"""


def hreflangs(path):
    # Не рекламируем alternate на язык, для которого страницы нет (иначе GSC-ошибки + 404).
    tags = []
    for lg in LANGS:
        if lg == "en" and path in NO_EN:
            continue
        if lg == "ru" and path in NO_RU:
            continue
        tags.append(f'<link rel="alternate" hreflang="{LOCALE[lg]}" href="{BASE_URL}{PREF[lg]}{path}">')
    default = f"{BASE_URL}{PREF['en']}{path}" if path in NO_RU else f"{BASE_URL}{path}"
    tags.append(f'<link rel="alternate" hreflang="x-default" href="{default}">')
    return "\n".join(tags)


def head(lang, title, desc, path, extra="", og_image=None, og_w=1200, og_h=630):
    canonical = f"{BASE_URL}{PREF[lang]}{path}"
    og = og_image or f"{BASE_URL}/assets/og-image.png"
    # нет версии на другом языке → запрещаем авто-редирект (LANGREDIR) на несуществующую страницу
    other_missing = (path in NO_EN) if lang == "ru" else (path in NO_RU)
    langredir = ('<script>window.RS_NOTR=1;</script>' + LANGREDIR) if other_missing else LANGREDIR
    # автообнаружение RSS: RU — полная лента для Дзена/агрегаторов, EN — англоблоговый фид
    feed_href = f"{BASE_URL}/dzen.xml" if lang == "ru" else f"{BASE_URL}/en/blog/rss.xml"
    feed_title = f"{S['name']} — блог" if lang == "ru" else f"{S['name']} — Blog"
    return f"""<!doctype html>
<html lang="{LOCALE[lang]}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{GTM_HEAD}
{langredir}
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<link rel="alternate" type="application/rss+xml" title="{feed_title}" href="{feed_href}">
{hreflangs(path)}
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="{S['name']}">
<meta property="og:image" content="{og}">
<meta property="og:image:width" content="{og_w}">
<meta property="og:image:height" content="{og_h}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{og}">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
<meta name="yandex-verification" content="4b39ef5046fa7e8a">
<meta name="zen-verification" content="AvXwV96CkkGrgi2Dn4bnu0c3gAx52ezYYqNU79rdSigVe2IAJhfqL8E512dfovL5">
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#111111">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="https://mc.yandex.ru">
<link rel="dns-prefetch" href="https://mc.yandex.ru">
<link rel="preconnect" href="https://www.googletagmanager.com">
<link rel="dns-prefetch" href="https://www.googletagmanager.com">
<link rel="stylesheet" href="/assets/styles.css?v={VER['css']}">
{extra}
{METRIKA}
{GTAG}
</head>
<body>
{GTM_BODY}
<div id="wrapper">"""


def mobile_drawer(lang):
    """Мобильная шторка: вся навигация, сгруппированная по смыслу; каждая ссылка — отдельной строкой-кнопкой."""
    ru = lang == "ru"
    P = PREF[lang]

    def grp(title, items):
        links = "".join(f'<a href="{href}">{txt}</a>' for href, txt in items)
        return f'<div class="dgrp"><h4>{title}</h4>{links}</div>'

    groups = [
        grp("Курсы и обмен" if ru else "Rates & exchange", [
            (f"{P}/", tr(lang, 'nav_monitor')),
            (f"{P}/kursy/", tr(lang, 'nav_rates')),
            (f"{P}/napravleniya/", tr(lang, 'nav_dirs')),
            (f"{P}/sravnenie/", tr(lang, 'nav_compare')),
            (f"{P}/monitor/", "Про-монитор" if ru else "Pro monitor"),
            (f"{P}/alert/", "Оповещения о курсе" if ru else "Rate alerts")]),
        grp("Аналитика рынка" if ru else "Market analytics", [
            (f"{P}/svodka/", tr(lang, 'nav_svodka')),
            (f"{P}/obzor/sutki/", tr(lang, 'nav_reviews')),
            (f"{P}/lidery-rynka/", tr(lang, 'nav_leaders')),
            (f"{P}/nastroeniya/", tr(lang, 'nav_mood')),
            (f"{P}/grafiki/", tr(lang, 'nav_charts')),
            (f"{P}/heatmap/", "Тепловая карта" if ru else "Heatmap"),
            (f"{P}/tsepochki/", "💱 Цепочки обмена" if ru else "💱 Exchange chains"),
            ("https://my-many.ru/?utm_source=ratescout&utm_medium=nav", "💰 Арбитраж (MyMany)" if ru else "💰 Arbitrage (MyMany)"),
            (f"{P}/populyarnost/", "Популярность по поиску" if ru else "Search popularity"),
            (f"{P}/halving/", "Халвинг Bitcoin" if ru else "Bitcoin halving")]),
        grp("Инструменты" if ru else "Tools", [
            (f"{P}/aml/", tr(lang, 'nav_aml')),
            (f"{P}/vidzhet/", tr(lang, 'nav_widget')),
            ("https://app.ratescout.info.gf", "📱 Приложение" if ru else "📱 App")]),
        grp("Знания" if ru else "Learn", [
            (f"{P}/blog/", tr(lang, 'nav_blog')),
            (f"{P}/faq/", tr(lang, 'nav_faq')),
            (f"{P}/slovar/", tr(lang, 'nav_glossary')),
            (f"{P}/o-servise/", tr(lang, 'nav_about')),
            (f"{P}/kniga/", "📖 Книги" if ru else "📖 Books")]),
        grp("О сервисе" if ru else "About", [
            (f"{P}/raskrytie/", tr(lang, 'nav_disc')),
            (f"{P}/politika/", "Политика конфиденциальности" if ru else "Privacy policy")]),
    ]
    return f'<nav id="drawer">{"".join(groups)}</nav>'


def header(lang, path):
    other = "en" if lang == "ru" else "ru"
    other_missing = (path in NO_EN) if lang == "ru" else (path in NO_RU)
    switch = ("" if other_missing else
              f'<a class="langsw" data-lang="{other}" href="{PREF[other]}{path}">{"EN" if other == "en" else "RU"}</a>')
    return f"""<div id="header">
  <h1 id="logotop"><a href="{PREF[lang]}/"><span class="logo">[⇄]</span> {S['name']}<span class="tld">.ru</span></a></h1>
  {switch}
</div>
<input type="checkbox" id="navtgl" class="navcb" aria-hidden="true">
<label for="navtgl" class="navtgl-btn doscyan dosborder">☰ {tr(lang,'sections')}</label>
{mobile_drawer(lang)}
<div id="topnav" class="doscyan dosborder">
  <ul id="menu-top">
    <li><a href="{PREF[lang]}/">{tr(lang,'nav_monitor')}</a></li>
    <li><a href="{PREF[lang]}/blog/">{tr(lang,'nav_blog')}</a></li>
    <li><a href="{PREF[lang]}/grafiki/">{tr(lang,'nav_charts')}</a></li>
    <li><a href="{PREF[lang]}/obzor/sutki/">{tr(lang,'nav_reviews')}</a></li>
    <li><a href="{PREF[lang]}/svodka/">{tr(lang,'nav_svodka')}</a></li>
    <li><a href="{PREF[lang]}/kursy/">{tr(lang,'nav_rates')}</a></li>
    <li><a href="{PREF[lang]}/napravleniya/">{tr(lang,'nav_dirs')}</a></li>
    <li><a href="{PREF[lang]}/faq/">{tr(lang,'nav_faq')}</a></li>
    <li><a href="{PREF[lang]}/slovar/">{tr(lang,'nav_glossary')}</a></li>
    <li><a href="{PREF[lang]}/raskrytie/">{tr(lang,'nav_disc')}</a></li>
  </ul>
</div>"""


def search_box(lang):
    return f"""<div class="conv dosblue dosborder" id="search">
  <h3>{tr(lang,'search_aria')}</h3>
  <input id="q" type="search" data-prefix="{PREF[lang]}" placeholder="{tr(lang,'search_ph')}" autocomplete="off" aria-label="{tr(lang,'search_aria')}">
  <ul id="qres"></ul>
</div>"""


WALLET_URL = "https://telegram.me/wallet/start?startapp=ref-3-7ZelA1cR5QI"   # реф — только вне РФ
WALLET_PLAIN = "https://t.me/wallet"                                        # обычная ссылка (для всех, вкл. РФ)
# Гео-гейт (только при уверенном «не Россия»; РФ/неизвестно/сбой → как есть):
#  · раскрывает блоки .rs-partner-geo;  · подменяет href у .js-wallet-ref на реф (data-ref).
_GEO_JS = r"""(function(){var els=document.querySelectorAll('.rs-partner-geo'),refs=document.querySelectorAll('.js-wallet-ref');
if(!els.length&&!refs.length)return;
function show(cc){if(cc&&cc!=='RU'){for(var i=0;i<els.length;i++)els[i].hidden=false;
for(var j=0;j<refs.length;j++){if(refs[j].getAttribute('data-ref'))refs[j].href=refs[j].getAttribute('data-ref');}}}
try{var c=localStorage.getItem('rs_cc'),t=+localStorage.getItem('rs_cc_t')||0;
if(c&&(Date.now()-t)<86400000){show(c);return;}}catch(e){}
fetch('https://get.geojs.io/v1/ip/country.json').then(function(r){return r.json();}).then(function(d){
var cc=(d&&d.country)||'';try{localStorage.setItem('rs_cc',cc);localStorage.setItem('rs_cc_t',''+Date.now());}catch(e){}
show(cc);}).catch(function(){});})();"""


def partner_block(lang):
    """Только гео-JS в футере (один на страницу) — раскрывает партнёрские блоки .rs-partner-geo вне РФ.
    Саму ссылку из футера убрали; промо остаётся в CTA под поиском (wallet_cta)."""
    return f'<script>{_GEO_JS}</script>'


def donations_block(lang):
    """Крипто-донаты владельца. Гео-гейт (класс .rs-partner-geo): скрыт по умолчанию, показываем только вне РФ
    (в России публичный сбор крипты — серая зона). Адреса публичные (не секреты)."""
    rows = [("Bitcoin (BTC)", "bc1q37p5grfj4rlynxu82ld6zqyy6r59jcnqtm55xx"),
            ("TON (Toncoin)", "UQCMDVJBDsriYx1b0QEZk_1_ubEHQpdIfu0td13ateCxtZTl"),
            ("Ethereum (ETH)", "0x08D5E0819D04CA18f3BdbA2a3c8C26a4103abFD8"),
            ("TRON (TRX)", "TS8YEsYet7q6CGVs3KckuPsdAtR51dxRUw")]
    body = "".join(f'<tr><td>{n}</td><td><code>{a}</code></td></tr>' for n, a in rows)
    if lang == "ru":
        h, lead = "Поддержать проект", ("Проект развивается на энтузиазме. Если он вам полезен — можно поддержать "
                                        "в криптовалюте (по желанию, необязательно):")
    else:
        h, lead = "Support the project", ("The project runs on enthusiasm. If you find it useful, you can support "
                                          "it in crypto (optional):")
    return (f'<div class="rs-partner-geo" hidden><h2>{h}</h2><p>{lead}</p>'
            f'<div class="rtbl-wrap"><table class="rtbl"><tbody>{body}</tbody></table></div></div>')


def wallet_cta(lang):
    """CTA под поиском → информационный каталог кошельков (/koshelki/). Виден всем (это справка, не реклама)."""
    if lang == "ru":
        title, sub, btn = ("🔑 Криптокошелёк", "Где хранить и куда выводить крипту — подборка кошельков.",
                           "Каталог кошельков →")
    else:
        title, sub, btn = ("🔑 Crypto wallet", "Where to keep and cash out crypto — a pick of wallets.",
                           "Wallets catalog →")
    return (f'<div class="conv dosblue dosborder"><h3>{title}</h3><p class="updnote">{sub}</p>'
            f'<a class="cta" href="{PREF[lang]}/koshelki/">{btn}</a></div>')


def render_koshelki(lang):
    """Информационный каталог криптокошельков (справка, не реклама): нейтральные описания + обычные ссылки.
    Telegram Wallet — обычная ссылка (t.me/wallet) для всех; реф подставляется гео-JS ТОЛЬКО вне РФ (data-ref)."""
    path = "/koshelki/"
    ru = lang == "ru"
    # (имя, RU-описание, EN-описание, ссылка, is_tg)
    wallets = [
        ("Telegram Wallet", "Кошелёк прямо в Telegram, без установки приложений: TON, USDT, BTC.",
         "A wallet inside Telegram, no app install: TON, USDT, BTC.", WALLET_PLAIN, True),
        ("Trust Wallet", "Популярный мобильный мультивалютный кошелёк (самостоятельное хранение).",
         "Popular mobile multi-currency non-custodial wallet.", "https://trustwallet.com/", False),
        ("MetaMask", "Кошелёк для Ethereum и EVM-сетей — расширение браузера и приложение.",
         "Wallet for Ethereum and EVM networks — browser extension and app.", "https://metamask.io/", False),
        ("Ledger", "Аппаратный кошелёк (холодное хранение) для долгого хранения крупных сумм.",
         "Hardware wallet (cold storage) for long-term holding.", "https://www.ledger.com/", False),
        ("Exodus", "Десктоп- и мобильный мультивалютный кошелёк с обменом внутри.",
         "Desktop and mobile multi-currency wallet with built-in swaps.", "https://www.exodus.com/", False),
    ]
    if ru:
        title = f"Криптокошельки: где завести и как выбрать | {S['name']}"
        desc = ("Подборка криптокошельков для хранения и вывода: Telegram Wallet, Trust Wallet, MetaMask, Ledger, "
                "Exodus — нейтральные описания и официальные ссылки. Справочно.")
        h1, lead = "Криптокошельки — где завести", ("Чтобы менять и хранить криптовалюту, нужен кошелёк. Ниже — "
            "популярные варианты с короткими описаниями и официальными ссылками. Это справочная информация, "
            "не рекомендация; выбор — за вами.")
        coln = ("Кошелёк", "Описание", "")
        go = "Перейти"
    else:
        title = f"Crypto wallets: where to get one and how to choose | {S['name']}"
        desc = ("A pick of crypto wallets to keep and cash out: Telegram Wallet, Trust Wallet, MetaMask, Ledger, "
                "Exodus — neutral descriptions and official links. For reference.")
        h1, lead = "Crypto wallets — where to get one", ("To exchange and store crypto you need a wallet. Below are "
            "popular options with short descriptions and official links. This is reference info, not advice; "
            "the choice is yours.")
        coln = ("Wallet", "Description", "")
        go = "Open"
    rows = ""
    for name, dru, den, url, is_tg in wallets:
        d = dru if ru else den
        if is_tg:
            link = (f'<a class="js-wallet-ref" href="{url}" data-ref="{WALLET_URL}" target="_blank" '
                    f'rel="nofollow noopener">{go}</a>'
                    f'<span class="rs-partner-geo tk" hidden> · {"партнёрская" if ru else "affiliate"}</span>')
        else:
            link = f'<a href="{url}" target="_blank" rel="nofollow noopener">{go}</a>'
        rows += f'<tr><td><b>{name}</b></td><td>{d}</td><td>{link}</td></tr>'
    table = (f'<div class="rtbl-wrap"><table class="rtbl"><thead><tr>'
             f'{"".join(f"<th>{c}</th>" for c in coln)}</tr></thead><tbody>{rows}</tbody></table></div>')
    note = ("Ссылки ведут на официальные сайты кошельков. RateScout — справочный сервис, не связан с ними и не даёт "
            "финансовых рекомендаций. Храните seed-фразу в тайне." if ru else
            "Links lead to the wallets' official sites. RateScout is a reference service, not affiliated with them "
            "and gives no financial advice. Keep your seed phrase private.")
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}</p>
    {trust_bar(lang)}
    {table}
    <p class="updnote">{note}</p>
  </div>
</div>
{crumbs}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + body)


def footer(lang):
    if lang == "ru":
        disc = ("RateScout — независимый информационный сервис мониторинга курсов. Мы не обменный пункт и не "
                "проводим операции. Ссылки ведут в сервис BestChange (мониторинг курсов обменных пунктов); "
                "по партнёрской программе мы можем получать вознаграждение. Это не реклама от имени BestChange.")
        links = (f'<a href="/o-servise/">О сервисе</a> · <a href="/aml/">AML-проверка</a> · '
                 f'<a href="/vidzhet/">Виджет для сайта</a> · <a href="/redakciya/">О редакции</a> · <a href="https://blogger.ratescout.info.gf/" target="_blank" rel="noopener me">Блог на Blogger</a> · <a href="https://t.me/ratescout_kurs" target="_blank" rel="noopener me">Канал в Telegram</a> · <a href="https://ok.ru/group/70000057243663" target="_blank" rel="noopener me">Одноклассники</a> · <a href="https://mastodon.social/@ratescout_ru" target="_blank" rel="noopener me">Mastodon</a> · <a href="https://www.yell.ru/moscow/com/ratescout-ru_14524615/" target="_blank" rel="noopener me">Yell.ru</a> · <a href="/raskrytie/">Раскрытие и дисклеймеры</a> · <a href="/politika/">Политика конфиденциальности</a> · <a href="/usloviya/">Условия использования</a>')
        fine = ("18+. Информация носит справочный характер, не является рекламой, офертой или финансовой "
                f"рекомендацией. Курсы меняются. © {S['name']} {S['domain']}.<br>"
                f"<span class=\"erid\">Владелец сайта: {S.get('owner_status','')} {S.get('owner','')}, ИНН {S.get('owner_inn','')}.</span>")
    else:
        disc = ("RateScout is an independent rate-monitoring service. We are not an exchange office and do not "
                "process transactions. Links lead to BestChange (a monitor of exchange office rates); through the "
                "affiliate program we may earn a commission. This is not advertising on behalf of BestChange.")
        links = (f'<a href="/en/o-servise/">About</a> · <a href="/en/aml/">AML check</a> · '
                 f'<a href="/en/earn/">Earn with BestChange</a> · '
                 f'<a href="/en/vidzhet/">Site widget</a> · <a href="/en/redakciya/">Editorial</a> · <a href="https://blogger.ratescout.info.gf/" target="_blank" rel="noopener me">Blog on Blogger</a> · <a href="https://t.me/ratescout_kurs" target="_blank" rel="noopener me">Telegram channel</a> · <a href="https://ok.ru/group/70000057243663" target="_blank" rel="noopener me">Odnoklassniki</a> · <a href="https://mastodon.social/@ratescout_ru" target="_blank" rel="noopener me">Mastodon</a> · <a href="/en/raskrytie/">Disclosure</a> · <a href="/en/politika/">Privacy policy</a> · <a href="/en/usloviya/">Terms of Service</a>')
        fine = ("18+. Information is for reference only and is not advertising, an offer or financial advice. "
                f"Rates change. © {S['name']} {S['domain']}.<br>"
                f"<span class=\"erid\">Site owner: {S.get('owner','')} (self-employed, RU tax ID {S.get('owner_inn','')}).</span>")
    return f"""<div id="footer">
  <div class="disc">{disc}</div>
  <div class="links">{links}</div>
  {partner_block(lang)}
  <div class="fine">{fine}</div>
  <div class="counters">{LIVEINTERNET}</div>
</div>
</div>
<script src="/assets/catalog.js?v={VER['cat']}"></script>
<script src="/assets/app.js?v={VER['js']}"></script>
</body></html>"""


def outgoing_rates(slug):
    """Карта лучших курсов {to_slug: rate} из данной валюты — для калькулятора на её странице."""
    out = {}
    pref = slug + ">"
    for k, v in RATES.items():
        if k.startswith(pref):
            to = k[len(pref):]
            if to in CUR:
                out[to] = v["rate"]
    return out


def converter_html(lang, preset_from="", rates=None):
    amt = res = rjson = ""
    if rates:
        amt = (f'<label class="amt">{tr(lang,"amount")}'
               f'<input id="cAmt" type="number" min="0" step="any" value="1" inputmode="decimal"></label>')
        res = '<div class="cest" id="cOut"></div>'
        rjson = (f'<script type="application/json" id="convRates" data-owner="{preset_from}">'
                 f'{json.dumps(rates, ensure_ascii=False)}</script>')
    return f"""<div class="conv dosblue dosborder" id="conv" data-from="{preset_from}" data-prefix="{PREF[lang]}" data-open="{'Open' if lang=='en' else 'Открыть'}" data-approx="{tr(lang,'approx')}">
  <h3>{tr(lang,'calc')}</h3>
  <label>{tr(lang,'give')}<select id="cFrom"></select></label>
  <button class="swap" id="cSwap" type="button">{tr(lang,'swap')}</button>
  <label>{tr(lang,'get')}<select id="cTo"></select></label>
  {amt}
  {res}
  <a class="cta" id="cGo" href="https://www.bestchange.ru/?p={REF}" target="_blank" rel="nofollow noopener sponsored">{tr(lang,'find_rate')}</a>
</div>{rjson}"""


# ---------------- «О валюте» ----------------
NET = {"TRC20": "TRON (TRC20)", "ERC20": "Ethereum (ERC20)", "BEP20": "BNB Smart Chain (BEP20)",
       "BEP2": "Binance Chain (BEP2)", "POLYGON": "Polygon", "ARBITRUM": "Arbitrum",
       "OPTIMISM": "Optimism", "AVAX": "Avalanche", "AVALANCHE": "Avalanche", "SOL": "Solana",
       "SPL": "Solana (SPL)", "NEAR": "NEAR", "TON": "TON", "LN": "Lightning Network", "OMNI": "Omni"}
STABLE = {"USDT", "USDC", "DAI", "TUSD", "USDP", "BUSD", "PYUSD", "USDR", "USDQ", "UUSD", "USDS"}


def _net(name):
    toks = set(re.split(r"[^A-Za-z0-9]+", name.upper()))
    for k, v in NET.items():
        if k in toks:
            return v
    return None


def about_currency(slug, info, lang):
    name, ticker, cat = info["name"], info["ticker"], info["category"]
    net = _net(name)
    if lang == "ru":
        links = ['<a href="/blog/slovar-terminov-obmena/">Словарь терминов</a>']
        if cat == "Криптовалюты":
            kind = "стейблкоин, привязанный к доллару США" if ticker in STABLE else "криптовалюта"
            s = f"<b>{name}</b> ({ticker}) — {kind}."
            if net:
                s += f" Сеть выпуска — {net}; от выбора сети зависят комиссия и совместимость адресов."
            s += (f" Здесь собраны справочные курсы обмена {ticker} на другие криптовалюты, банки, платёжные "
                  f"системы и наличные — по данным мониторинга BestChange.")
            links = (['<a href="/blog/usdt-seti-trc20-erc20-bep20/">Сети USDT</a>'] if ticker in STABLE else []) + \
                    ['<a href="/blog/komissii-setey-tron-eth-bsc/">Комиссии сетей</a>',
                     '<a href="/blog/chto-takoe-aml-proverka/">AML-проверка</a>'] + links
        elif cat == "Bank accounts and cards":
            s = f"<b>{name}</b> ({ticker}) — банковская карта/реквизиты. Ниже — справочные курсы направлений с {name}."
        elif cat == "Online banking":
            s = f"<b>{name}</b> ({ticker}) — банк/онлайн-банкинг. Ниже — справочные курсы направлений с {name}."
        elif cat == "Money transfers":
            s = f"<b>{name}</b> ({ticker}) — система денежных переводов. Ниже — справочные курсы направлений."
        elif cat == "Cash":
            s = f"<b>{name}</b> ({ticker}) — наличные. Ниже — справочные курсы направлений с {name}."
        elif cat == "Digital currencies":
            s = f"<b>{name}</b> ({ticker}) — электронная платёжная система. Ниже — справочные курсы направлений."
        else:
            s = f"<b>{name}</b> ({ticker}). Ниже — справочные курсы направлений."
        facts = (f'<ul class="facts"><li>{tr(lang,"ticker")}: <b>{ticker}</b></li><li>{tr(lang,"category")}: {cat_name(cat,lang)}</li>'
                 + (f"<li>{tr(lang,'network')}: {net}</li>" if net else "") + "</ul>")
        used = "Полезное"
    else:
        links = ['<a href="/en/blog/slovar-terminov-obmena/">Glossary</a>']
        if cat == "Криптовалюты":
            kind = "a USD-pegged stablecoin" if ticker in STABLE else "a cryptocurrency"
            s = f"<b>{name}</b> ({ticker}) is {kind}."
            if net:
                s += f" Issued on {net}; the network affects transfer fees and address compatibility."
            s += (f" Below are reference exchange rates for {ticker} to other crypto, banks, payment systems and "
                  f"cash — based on BestChange monitoring data.")
            links = (['<a href="/en/blog/usdt-seti-trc20-erc20-bep20/">USDT networks</a>'] if ticker in STABLE else []) + \
                    ['<a href="/en/blog/komissii-setey-tron-eth-bsc/">Network fees</a>',
                     '<a href="/en/blog/chto-takoe-aml-proverka/">AML check</a>'] + links
        elif cat == "Bank accounts and cards":
            s = f"<b>{name}</b> ({ticker}) — a bank card / details. Reference rates for directions with {name} below."
        elif cat == "Online banking":
            s = f"<b>{name}</b> ({ticker}) — a bank / online banking. Reference rates for directions with {name} below."
        elif cat == "Money transfers":
            s = f"<b>{name}</b> ({ticker}) — a money transfer system. Reference rates for directions below."
        elif cat == "Cash":
            s = f"<b>{name}</b> ({ticker}) — cash. Reference rates for directions with {name} below."
        elif cat == "Digital currencies":
            s = f"<b>{name}</b> ({ticker}) — an electronic payment system. Reference rates for directions below."
        else:
            s = f"<b>{name}</b> ({ticker}). Reference rates for directions below."
        facts = (f'<ul class="facts"><li>{tr(lang,"ticker")}: <b>{ticker}</b></li><li>{tr(lang,"category")}: {cat_name(cat,lang)}</li>'
                 + (f"<li>{tr(lang,'network')}: {net}</li>" if net else "") + "</ul>")
        used = "Useful"
    return (f'<h2 class="news">{tr(lang,"about_cur")} {name}</h2><p>{s}</p>{facts}'
            f'<p class="related">{used}: {" · ".join(links)}</p>')


# ---------------- статьи/блог ----------------
def load_articles(lang):
    arts, d = [], os.path.join(ROOT, "articles", "en") if lang == "en" else os.path.join(ROOT, "articles")
    if not os.path.isdir(d):
        return arts
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        raw = open(os.path.join(d, fn), encoding="utf-8").read()
        meta, body = {}, raw
        if raw.startswith("---"):
            _, fm, body = raw.split("---", 2)
            for line in fm.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
        rel = meta.get("release")               # дрип: статья с датой релиза в будущем ещё не публикуется
        if rel:
            try:
                if datetime.strptime(rel[:10], "%Y-%m-%d").date() > datetime.now(timezone.utc).date():
                    continue
            except ValueError:
                pass
        meta["html"] = md_render(body.strip())
        if meta.get("slug"):
            arts.append(meta)
    arts.sort(key=lambda a: a.get("date", ""), reverse=True)
    return arts


ARTS = {lg: load_articles(lg) for lg in LANGS}

# Реестр путей БЕЗ версии на данном языке — чтобы не рекламировать/не редиректить на несуществующие
# страницы. Асимметрия ровно в двух местах: направления (EN — только PAIR_PAGES; RU — ещё PAIR_PAGES_RU)
# и статьи блога (наборы ARTS['ru'] / ARTS['en'] различаются, в т.ч. из-за дрип-релизов по датам).
_ru_pair_paths = {f"/obmen/{p['from']}-{p['to']}/" for p in PAIR_PAGES + PAIR_PAGES_RU}
_en_pair_paths = {f"/obmen/{p['from']}-{p['to']}/" for p in PAIR_PAGES}
_ru_art_paths = {f"/blog/{a['slug']}/" for a in ARTS["ru"]}
_en_art_paths = {f"/blog/{a['slug']}/" for a in ARTS["en"]}
NO_EN = (_ru_pair_paths - _en_pair_paths) | (_ru_art_paths - _en_art_paths) | {"/404"}
NO_RU = (_en_pair_paths - _ru_pair_paths) | (_en_art_paths - _ru_art_paths) | {"/earn/"}  # /earn/ — только EN (партнёрка для не-РФ)
PUB_SLUGS = {lg: {a["slug"] for a in ARTS[lg]} for lg in LANGS}


def popular_involving(slug, n=8):
    return [p for p in TOP if p["from"] == slug or p["to"] == slug][:n]


def pair_link_li(p, lang):
    return (f'<li><a href="{pair_url(lang, p["from"], p["to"])}">'
            f'{CUR[p["from"]]["name"]} <span>{CUR[p["from"]]["ticker"]}</span> → '
            f'{CUR[p["to"]]["name"]} <span>{CUR[p["to"]]["ticker"]}</span></a></li>')


def currency_directions(slug, lang):
    """Статический блок «Направления обмена {тикер}»: топ покрытых пар с этой валютой по ликвидности.
    Даёт входящие внутренние ссылки на страницы /obmen/ (для SEO). EN — только существующие 714 пар."""
    ds = DIRS_BY_CUR.get(slug, [])
    if lang == "en":
        ds = [d for d in ds if (d[0], d[1]) in PAIR_SET]
    if not ds:
        return ""
    ds = sorted(ds, key=lambda d: d[2], reverse=True)
    # SEO-перелинковка: линкуем ВСЕ направления валюты (иначе редкие пары — сироты без вх.ссылок).
    # Топ-30 показываем сразу, остальное — в <details> (в DOM → краулится, страница не раздувается).
    top, rest = ds[:30], ds[30:]
    h = (f"Направления обмена {CUR[slug]['ticker']}" if lang == "ru"
         else f"{CUR[slug]['ticker']} exchange directions")
    items = "".join(pair_link_li({"from": f, "to": t}, lang) for f, t, _ in top)
    out = f'<h2 class="news">{h}</h2><ul class="dlist">{items}</ul>'
    if rest:
        more = "".join(pair_link_li({"from": f, "to": t}, lang) for f, t, _ in rest)
        lbl = (f"Показать все {len(ds)} направлений {CUR[slug]['ticker']}" if lang == "ru"
               else f"Show all {len(ds)} {CUR[slug]['ticker']} directions")
        out += f'<details class="moredirs"><summary>{lbl}</summary><ul class="dlist">{more}</ul></details>'
    return out


def popular_block(slug, lang):
    pops = popular_involving(slug)
    if not pops:
        return ""
    return f'<h2 class="news">{tr(lang,"popular")}</h2><ul class="dlist">{"".join(pair_link_li(p, lang) for p in pops)}</ul>'


def related_currencies(slug, info, lang, n=8):
    """Похожие валюты: та же категория; для крипты — приоритет той же сети. Внутренняя перелинковка."""
    cat = info["category"]
    same = [(s, i) for s, i in GROUPED.get(cat, []) if s != slug]
    if not same:
        return ""
    net = _net(info["name"])
    if net:
        same.sort(key=lambda x: (0 if _net(x[1]["name"]) == net else 1, x[1]["name"]))
    picked = same[:n]
    items = "".join(f'<li><a href="{cpage(lang, s)}">{i["name"]} <span>{i["ticker"]}</span></a></li>'
                    for s, i in picked)
    h = "Похожие валюты" if lang == "ru" else "Similar currencies"
    return f'<h2 class="news">{h}</h2><ul class="dlist">{items}</ul>'


def rate_table(slug, info, lang, incoming=False, n=12):
    """Таблица направлений обмена (реферальные ссылки BestChange): поиск по валютам, фильтр категорий,
    сортировка (категории/ликвидность/рост/падение), период, заголовки по категориям.
    incoming=False — направления slug→X (страница валюты); True — X→slug (страница покупки)."""
    def _rate(o):
        return rate_of(o, slug) if incoming else rate_of(slug, o)

    def _link(o):
        return bc_link(o, slug) if incoming else bc_link(slug, o)
    rated, unrated = [], []
    for ts, ti in CUR.items():
        if ts == slug:
            continue
        r = _rate(ts)
        if r:
            rated.append((r.get("count", 0), ts, ti, r))
        else:
            unrated.append((ts, ti))
    if not rated and not unrated:
        return ""
    rated.sort(key=lambda x: x[0], reverse=True)
    unrated.sort(key=lambda x: x[1]["name"].lower())
    allrows = [(cnt, ts, ti, r) for cnt, ts, ti, r in rated] + [(0, ts, ti, None) for ts, ti in unrated]
    if lang == "ru":
        title = (f"Получить {info['ticker']} — курсы по всем валютам" if incoming
                 else f"Обмен {info['ticker']} — курсы по всем валютам")
        h = (("Отдаёте" if incoming else "Меняем на"), "Лучший курс", "Обменников", "Резерв", "Изм.")
        note = "Курс/резерв — по направлению из мониторинга BestChange; «Изм.» — динамика цены валюты за период. Обновление ежечасно. " + updated_str(lang)
        ph, nores, plbl = "Поиск по валютам: BTC, USDT, Sberbank…", "Ничего не найдено", "Изм. за:"
        sorts = [("cat", "По категориям"), ("liq", "По ликвидности"), ("up", "Рост ↑"), ("down", "Падение ↓")]
        periods = [("24h", "24ч"), ("7d", "7д"), ("30d", "30д"), ("1y", "1г"), ("3y", "3г"), ("5y", "5л"), ("10y", "10л")]
    else:
        title = (f"Get {info['ticker']} — rates for all currencies" if incoming
                 else f"Exchange {info['ticker']} — rates for all currencies")
        h = (("You send" if incoming else "Exchange to"), "Best rate", "Exchangers", "Reserve", "Chg.")
        note = "Rate/reserve — per direction from BestChange; “Chg.” — currency price change over the period. Hourly updates. " + updated_str(lang)
        ph, nores, plbl = "Search currencies: BTC, USDT, Sberbank…", "Nothing found", "Chg. over:"
        sorts = [("cat", "By category"), ("liq", "By liquidity"), ("up", "Gainers ↑"), ("down", "Losers ↓")]
        periods = [("24h", "24h"), ("7d", "7d"), ("30d", "30d"), ("1y", "1y"), ("3y", "3y"), ("5y", "5y"), ("10y", "10y")]

    def _btns(items, attr, default):
        out = ""
        for v, l in items:
            on = ' class="on"' if v == default else ""
            out += f'<button type="button" data-{attr}="{v}"{on}>{l}</button>'
        return out
    fbtns = _btns([("", "Все" if lang == "ru" else "All")] + [(CAT_SLUG[c], cat_name(c, lang)) for c in CATS], "f", "")
    sbtns = _btns(sorts, "s", "cat")
    pbtns = _btns(periods, "p", "24h")
    def _row(cnt, ts, ti, r):
        ds = f'{ti["name"]} {ti["ticker"]} {ts}'.lower().replace('"', "&quot;")
        cat_k = CAT_SLUG.get(ti["category"], "prochee")
        chg = CHG_BY.get(ts, {})
        pattrs = "".join(f' data-c{pk}="{("" if chg.get(pk) is None else f"{chg[pk]:.4f}")}"' for pk, _ in CHART_PERIODS)
        if r:
            rate_c, cnt_c, res_c = f'<b>{fmt_rate(r["rate"])}</b>', str(cnt), fmt_rate(r.get("reserve", 0))
        else:
            rate_c = cnt_c = res_c = '<span class="nd">—</span>'
        c24 = chg.get("24h")
        chg_c = ('<span class="nd">—</span>' if c24 is None
                 else f'<b class="{"up" if c24 >= 0 else "down"}">{"+" if c24 >= 0 else ""}{c24:.1f}%</b>')
        return (f'<tr class="rtrow" data-search="{ds}" data-cat="{cat_k}" data-liq="{cnt}"{pattrs}>'
                f'<td class="d"><a href="{_link(ts)}" target="_blank" rel="nofollow noopener sponsored">'
                f'{ti["name"]} <span class="op">{ti["ticker"]}</span></a></td>'
                f'<td class="num">{rate_c}</td><td class="num">{cnt_c}</td><td class="num">{res_c}</td>'
                f'<td class="num rtchg">{chg_c}</td></tr>')
    # группировка по категориям валют: строка-заголовок + валюты категории
    by_cat = {}
    for cnt, ts, ti, r in allrows:
        by_cat.setdefault(ti["category"], []).append((cnt, ts, ti, r))
    trs = ""
    for c in CATS:
        grp = by_cat.get(c)
        if not grp:
            continue
        grp.sort(key=lambda x: (0 if x[3] else 1, -(x[0] or 0), x[2]["name"].lower()))
        cat_k = CAT_SLUG.get(c, "prochee")
        trs += (f'<tr class="rtgroup" data-cat="{cat_k}"><td colspan="5">{cat_name(c, lang)} '
                f'<span class="cnt">{len(grp)}</span></td></tr>')
        for cnt, ts, ti, r in grp:
            trs += _row(cnt, ts, ti, r)
    return (f'<h2 class="news">{title}</h2>'
            f'<div class="rtsearchbox"><input class="rtsearch" data-prefix="{PREF[lang]}" type="search" placeholder="{ph}" autocomplete="off" aria-label="{ph}"></div>'
            f'<div class="rsrange rtcatbar">{fbtns}</div>'
            f'<div class="rsrange rtsortbar">{sbtns}</div>'
            f'<div class="perrow"><span class="ctllbl">{plbl}</span><span class="rsrange rtperbar">{pbtns}</span></div>'
            f'<div class="rtbl-wrap"><table class="rtbl ratetbl"><thead><tr>'
            f'<th>{h[0]}</th><th>{h[1]}</th><th>{h[2]}</th><th>{h[3]}</th><th>{h[4]}</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div>'
            f'<p class="rtnores updnote" hidden>{nores}</p>'
            f'<p class="updnote">{note}</p>')



def render_buy(slug, info, lang):
    """Страница покупки: все направления «источник → эта валюта» (как получить X) + CTA. SEO/конверсия."""
    name, ticker = info["name"], info["ticker"]
    path = f"/kupit/{slug}/"
    get_src = "bitcoin" if slug == "tether-trc20" else "tether-trc20"
    # CTR: живой курс + дата в сниппет
    _hc = HISTORY.get(slug, [])
    _ldc = datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d") if RATES_GENERATED else ""
    _dhc = ".".join(reversed(_ldc.split("-"))) if _ldc else ""
    _prc = fmt_rate(_hc[-1][1]) if (_hc and slug != "tether-trc20") else ""
    if lang == "ru":
        if _prc:
            title = f"Купить {name} ({ticker}) — курс {_prc} USDT сегодня | {S['name']}"
            desc = (f"Как купить {name} ({ticker}): курс {_prc} USDT на {_dhc}, все направления обмена на {ticker} "
                    f"из USDT, рублей и другой крипты по мониторингу BestChange. Обновление ежечасно.")
        else:
            title = f"Купить {name} ({ticker}) — направления и курсы сегодня | {S['name']}"
            desc = (f"Как купить {name} ({ticker}): все направления обмена на {ticker} с курсами из мониторинга "
                    f"BestChange, обновление ежечасно. За USDT, рубли, другую крипту.")
        h1 = f"Купить {name}"
        intro = (f"Справочник направлений, где можно <b>получить {name} ({ticker})</b>: обмен из других валют "
                 f"с курсами из мониторинга <b>BestChange</b>. Выберите, чем платите, ниже.")
        tt = ("Отдаёте", "Курс", "Обменников", "Резерв, всего")
        howh = f"Как купить {name}"
        steps = [f"Выберите, что отдаёте, в таблице или списке ниже.",
                 "В BestChange сравните курс, резерв и рейтинг обменников.",
                 f'Проверьте адрес получения {ticker}; для крупной суммы — <a href="{PREF[lang]}/aml/">AML-проверка</a>.',
                 f"Проведите обмен и получите {ticker} на свой кошелёк/счёт."]
        q1, a1 = f"Как выгоднее купить {name}?", f"Сравните направления по курсу и резерву в мониторинге BestChange и учтите комиссию сети. Часто выгодно покупать {ticker} за USDT."
        q2, a2 = f"Где получить {name} за рубли?", f"Выберите направление с рублёвым источником (карта/СБП/наличные) → {ticker} в списке ниже."
        back = f'<a href="{cpage(lang, slug)}">Обмен {name} (продать/все направления) →</a>'
        note = "Лучший курс среди обменников; резерв — суммарный. " + updated_str(lang)
    else:
        if _prc:
            title = f"Buy {name} ({ticker}) — {_prc} USDT rate today | {S['name']}"
            desc = (f"How to buy {name} ({ticker}): {_prc} USDT as of {_ldc}, all exchange directions to {ticker} "
                    f"from USDT, rubles or other crypto per BestChange monitoring. Hourly updates.")
        else:
            title = f"Buy {name} ({ticker}) — directions and rates today | {S['name']}"
            desc = (f"How to buy {name} ({ticker}): all exchange directions to {ticker} with rates from BestChange "
                    f"monitoring, hourly updates. For USDT, rubles or other crypto.")
        h1 = f"Buy {name}"
        intro = (f"A directory of directions where you can <b>get {name} ({ticker})</b>: exchange from other "
                 f"currencies with rates from the <b>BestChange</b> monitor. Choose what you pay with below.")
        tt = ("You send", "Rate", "Exchangers", "Total reserve")
        howh = f"How to buy {name}"
        steps = [f"Choose what you send in the table or list below.",
                 "On BestChange compare rate, reserve and exchanger rating.",
                 f'Check the receiving {ticker} address; for a large amount — an <a href="{PREF[lang]}/aml/">AML check</a>.',
                 f"Complete the exchange and receive {ticker} to your wallet/account."]
        q1, a1 = f"How to buy {name} cheaper?", f"Compare directions by rate and reserve in the BestChange monitor and factor in the network fee. Buying {ticker} for USDT is often favorable."
        q2, a2 = f"Where to get {name} for rubles?", f"Pick a direction with a ruble source (card/SBP/cash) → {ticker} in the list below."
        back = f'<a href="{cpage(lang, slug)}">Exchange {name} (sell / all directions) →</a>'
        note = "Best rate among exchangers; reserve is the total. " + updated_str(lang)
    get_btn = (f'<a class="cta cta-get" href="{bc_link(get_src, slug)}" target="_blank" '
               f'rel="nofollow noopener sponsored">{tr(lang,"get_cta")} {name} →</a>')
    faq = jsonld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q1, "acceptedAnswer": {"@type": "Answer", "text": a1}},
        {"@type": "Question", "name": q2, "acceptedAnswer": {"@type": "Answer", "text": re.sub("<[^>]+>", "", a2)}}]})
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    crumbs += jsonld({"@context": "https://schema.org", "@type": "WebPage", "name": title,
                      "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang],
                      "dateModified": modified_iso(), "lastReviewed": modified_iso(),
                      "reviewedBy": {"@type": "Organization", "name": S["name"], "url": BASE_URL}})
    _hb = HISTORY.get(slug) or []
    ers = exchange_rate_ld(ticker, _hb[-1][1], "USDT") if (_hb and slug != "tether-trc20") else ""
    steps_html = "".join(f"<li>{s}</li>" for s in steps)
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1} <span class="tk">{ticker}</span></h1>
    <p>{intro}</p>
    {trust_bar(lang)}
    <p class="getcta">{get_btn}</p>
    {rate_table(slug, info, lang, incoming=True)}
    <h2 class="news">{howh}</h2>
    <ol class="steps">{steps_html}</ol>
    {howto_ld(howh, steps)}
    <p class="related">{back}</p>
    <h2 class="news">{tr(lang,'faq')}</h2>
    <details><summary>{q1}</summary><p>{a1}</p></details>
    <details><summary>{q2}</summary><p>{a2}</p></details>
  </div>
</div>
{faq}{crumbs}{ers}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + body)


def render_currency(slug, info, lang):
    name, ticker = info["name"], info["ticker"]
    path = f"/valuta/{slug}/"
    # CTR: живой курс + дата + число направлений → кликабельный сниппет (title/description).
    _hc = HISTORY.get(slug, [])
    _ldc = datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d") if RATES_GENERATED else ""
    _dhc = ".".join(reversed(_ldc.split("-"))) if _ldc else ""
    _dc = DIRS_BY_CUR.get(slug, [])
    if lang == "en":
        _dc = [d for d in _dc if (d[0], d[1]) in PAIR_SET]
    _ndc = len(_dc)
    _prc = fmt_rate(_hc[-1][1]) if (_hc and slug != "tether-trc20") else ""
    if lang == "ru":
        if _prc:
            title = f"Курс {name} ({ticker}) сегодня — {_prc} USDT · обмен | {S['name']}"
            desc = (f"{name} ({ticker}) — {_prc} USDT на {_dhc}. Сравните курсы обмена в пунктах мониторинга "
                    f"BestChange по {_ndc} направлениям {ticker}. AML-проверка адреса, обновление ежечасно.")
        else:
            title = f"Обмен {name} ({ticker}) — {_ndc} направлений, курсы сегодня | {S['name']}"
            desc = (f"Обмен {name} ({ticker}): {_ndc} направлений обмена, курсы обменников из мониторинга "
                    f"BestChange, обновление ежечасно. AML-проверка адреса.")
        intro = (f"Справочная сводка курсов обмена <b>{name} ({ticker})</b> в обменниках из мониторинга "
                 f"<b>BestChange</b>. Выберите направление ниже; обмен совершается на сайте обменника.")
        steps = [f"Выберите направление обмена {ticker} выше.",
                 "В BestChange сравните курс, резерв и рейтинг обменников.",
                 f'Для крипто — сделайте <a href="{PREF[lang]}/aml/">AML-проверку адреса</a>.',
                 "Перейдите в выбранный обменник и проведите операцию."]
        faq_q1, faq_a1 = f"Как обменять {name} ({ticker})?", "Через мониторинг BestChange — он показывает курсы обменных пунктов."
        faq_q2, faq_a2 = f"Как проверить чистоту {ticker}?", "Обмен идёт в пунктах из мониторинга BestChange. Для крипто можно сделать AML-проверку адреса."
    else:
        if _prc:
            title = f"{name} ({ticker}) price today — {_prc} USDT · exchange | {S['name']}"
            desc = (f"{name} ({ticker}) — {_prc} USDT as of {_ldc}. Compare exchange rates across BestChange "
                    f"offices for {_ndc} {ticker} directions. Address AML check, hourly updates.")
        else:
            title = f"Exchange {name} ({ticker}) — {_ndc} directions, rates today | {S['name']}"
            desc = (f"Exchange {name} ({ticker}): {_ndc} directions, exchanger rates from BestChange monitoring, "
                    f"hourly updates. Address AML check.")
        intro = (f"Reference summary of <b>{name} ({ticker})</b> exchange rates in offices from the "
                 f"<b>BestChange</b> monitor. Pick a direction below; the exchange happens on the office's site.")
        steps = [f"Choose an exchange direction for {ticker} above.",
                 "On BestChange compare rate, reserve and exchanger rating.",
                 f'For crypto — do an <a href="{PREF[lang]}/aml/">AML check of the address</a>.',
                 "Go to the chosen exchanger and complete the operation."]
        faq_q1, faq_a1 = f"How to exchange {name} ({ticker})?", "Via the BestChange monitor — it shows exchange office rates."
        faq_q2, faq_a2 = f"How to check {ticker} cleanliness?", "The exchange runs in offices from BestChange monitoring. For crypto you can do an address AML check."
    faq = jsonld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": faq_q1, "acceptedAnswer": {"@type": "Answer", "text": faq_a1}},
        {"@type": "Question", "name": faq_q2, "acceptedAnswer": {"@type": "Answer", "text": faq_a2}}]})
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": f"{name} ({ticker})", "item": BASE_URL + PREF[lang] + path}]})
    crumbs += jsonld({"@context": "https://schema.org", "@type": "WebPage", "name": title,
                      "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang],
                      "dateModified": modified_iso(), "lastReviewed": modified_iso(),
                      # Speakable (AEO/голос): озвучиваемый фрагмент — ведущий факт-абзац
                      "speakable": {"@type": "SpeakableSpecification", "cssSelector": [".answer"]},
                      "reviewedBy": {"@type": "Organization", "name": S["name"], "url": BASE_URL}})
    # ExchangeRateSpecification: цена валюты в USDT (последняя точка истории)
    _hist = HISTORY.get(slug) or []
    ers = exchange_rate_ld(ticker, _hist[-1][1], "USDT") if (_hist and slug != "tether-trc20") else ""
    steps_html = "".join(f"<li>{s}</li>" for s in steps)
    get_btn = f'<a class="cta cta-get" href="{PREF[lang]}/kupit/{slug}/">{tr(lang,"get_cta")} {name} →</a>'
    _h = HISTORY.get(slug, [])
    getspark = ""
    if len(_h) >= 2:
        _v = [p[1] for p in _h]
        _chg = (_v[-1] - _v[0]) / _v[0] * 100 if _v[0] else 0
        _cls = "up" if _chg >= 0 else "down"
        _sign = "+" if _chg >= 0 else ""
        _lbl = "Полный график ниже" if lang == "ru" else "Full chart below"
        getspark = (f'<a class="getspark" href="#chart" title="{_lbl}">{mini_spark(_h[-90:])}'
                    f'<span class="chgpill {_cls}">{_sign}{_chg:.1f}%</span></a>')
    # GEO answer-first: первый экстрактируемый факт — датированный живой курс + число направлений.
    # Данные из истории/каталога (не копирайтинг). AI-движок цитирует ведущий абзац дословно.
    _dirs = DIRS_BY_CUR.get(slug, [])
    if lang == "en":
        _dirs = [d for d in _dirs if (d[0], d[1]) in PAIR_SET]
    _ndir = len(_dirs)
    _ld = datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d") if RATES_GENERATED else ""
    _vv = [p[1] for p in _h]
    _chgtxt = ""
    if len(_vv) >= 2 and _vv[0]:
        _c = (_vv[-1] - _vv[0]) / _vv[0] * 100
        _chgtxt = (f", изменение за период {'+' if _c >= 0 else ''}{_c:.1f}%" if lang == "ru"
                   else f", period change {'+' if _c >= 0 else ''}{_c:.1f}%")
    if _vv and slug != "tether-trc20":
        if lang == "ru":
            lead = (f"На {_ld} курс <b>{name} ({ticker})</b> ≈ <b>{fmt_rate(_vv[-1])} USDT</b> "
                    f"по мониторингу BestChange (обновление ежечасно){_chgtxt}. "
                    f"Доступно {_ndir} направлений обмена {ticker}.")
        else:
            lead = (f"As of {_ld}, <b>{name} ({ticker})</b> ≈ <b>{fmt_rate(_vv[-1])} USDT</b> "
                    f"per BestChange monitoring (hourly updates){_chgtxt}. "
                    f"{_ndir} exchange directions for {ticker} available.")
    else:
        lead = (f"<b>{name} ({ticker})</b>: на {S['name']} собрано {_ndir} направлений обмена {ticker} "
                f"по данным мониторинга BestChange (обновление ежечасно)."
                if lang == "ru" else
                f"<b>{name} ({ticker})</b>: {_ndir} {ticker} exchange directions on {S['name']} "
                f"per BestChange monitoring (hourly updates).")
    # GEO: 3-й дата-FAQ «сколько стоит сейчас» (когда есть курс) — расширяет FAQPage конкретным Q&A.
    faq3 = ""
    if _vv and slug != "tether-trc20":
        if lang == "ru":
            faq_q3 = f"Сколько стоит 1 {ticker} сейчас?"
            faq_a3 = f"На {_ld} — примерно {fmt_rate(_vv[-1])} USDT по данным мониторинга BestChange (обновление ежечасно)."
        else:
            faq_q3 = f"How much is 1 {ticker} now?"
            faq_a3 = f"As of {_ld} — about {fmt_rate(_vv[-1])} USDT per BestChange monitoring (hourly updates)."
        faq = jsonld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": faq_q1, "acceptedAnswer": {"@type": "Answer", "text": faq_a1}},
            {"@type": "Question", "name": faq_q2, "acceptedAnswer": {"@type": "Answer", "text": faq_a2}},
            {"@type": "Question", "name": faq_q3, "acceptedAnswer": {"@type": "Answer", "text": faq_a3}}]})
        faq3 = f"<details><summary>{faq_q3}</summary><p>{faq_a3}</p></details>"
    hub_cta = ""
    if slug in BANK_HUB_SET:
        hub_cta = (f'<p class="related"><a href="{PREF[lang]}/na/{slug}/">'
                   + (f'→ Обмен криптовалюты на {name} (все монеты)' if lang == "ru"
                      else f'→ Exchange crypto to {name} (all coins)') + '</a></p>')
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {name} <span class="tk">{ticker}</span></nav>
    <h1>{'Exchange' if lang=='en' else 'Обмен'} {name} <span class="tk">{ticker}</span></h1>
    <p class="answer">{lead}</p>
    <p>{intro}</p>
    {trust_bar(lang)}
    <div class="getcta">{get_btn}{getspark}</div>
    {hub_cta}
    {about_currency(slug, info, lang)}
    {currency_chart(slug, info, lang)}
    {market_block(slug, info, lang)}
    {currency_metrics_block(slug, info, lang)}
    {history_table(slug, lang)}
    {rate_table(slug, info, lang)}
    {currency_directions(slug, lang)}
    <h2 class="news">{tr(lang,'how_to')} {name}</h2>
    <ol class="steps">{steps_html}</ol>
    {howto_ld(tr(lang,'how_to') + ' ' + name, steps)}
    <h2 class="news">{tr(lang,'faq')}</h2>
    <details><summary>{faq_q1}</summary><p>{faq_a1}</p></details>
    <details><summary>{faq_q2}</summary><p>{faq_a2}</p></details>
    {faq3}
    {related_currencies(slug, info, lang)}
  </div>
  <div id="sidebar">
    {converter_html(lang, slug, outgoing_rates(slug))}
    {search_box(lang)}
    {wallet_cta(lang)}
    <div class="sblock"><h3>{tr(lang,'sections')}</h3><ul>
      <li><a href="https://app.ratescout.info.gf">{'📱 Приложение' if lang=='ru' else '📱 App'}</a></li>
      <li><a href="{PREF[lang]}/">{tr(lang,'all_cur')}</a></li>
      <li><a href="{PREF[lang]}/napravleniya/">{tr(lang,'nav_dirs')}</a></li>
      <li><a href="{PREF[lang]}/lidery-rynka/">{tr(lang,'nav_leaders')}</a></li>
      <li><a href="{PREF[lang]}/heatmap/">{'Тепловая карта' if lang=='ru' else 'Heatmap'}</a></li>
      <li><a href="{PREF[lang]}/populyarnost/">{'Популярность по поиску' if lang=='ru' else 'Search popularity'}</a></li>
      <li><a href="{PREF[lang]}/tsepochki/">{'💱 Цепочки обмена' if lang=='ru' else '💱 Exchange chains'}</a></li>
      <li><a href="https://my-many.ru/?utm_source=ratescout&utm_medium=nav">{'💰 Арбитраж (MyMany)' if lang=='ru' else '💰 Arbitrage (MyMany)'}</a></li>
      <li><a href="{PREF[lang]}/nastroeniya/">{tr(lang,'nav_mood')}</a></li>
      <li><a href="{PREF[lang]}/sravnenie/">{tr(lang,'nav_compare')}</a></li>
      <li><a href="{PREF[lang]}/aml/">{tr(lang,'nav_aml')}</a></li>
      <li><a href="{PREF[lang]}/kniga/">{'📖 Книги' if lang=='ru' else '📖 Books'}</a></li>
      <li><a href="{PREF[lang]}/o-servise/">{tr(lang,'nav_about')}</a></li>
      <li><a href="{PREF[lang]}/vidzhet/">{tr(lang,'nav_widget')}</a></li>
    </ul></div>
  </div>
  <div class="clearboth"></div>
</div>
{faq}{crumbs}{ers}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + body)


STABLE_T = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "FDUSD"}


def pair_unique(fi, ti, r, lang):
    """Уникальный на пару контент: категорийный абзац (по типам обеих валют) + таблица сумм + 3-й data-FAQ.
    Разводит 183 страницы пар, чтобы они не были near-duplicate (было ~86% совпадения)."""
    fN, fT, tN, tT = fi["name"], fi["ticker"], ti["name"], ti["ticker"]
    fc, tc = fi["category"] == "Криптовалюты", ti["category"] == "Криптовалюты"
    tstable = tT in STABLE_T
    fcat, tcat = cat_name(fi["category"], lang), cat_name(ti["category"], lang)
    if lang == "ru":
        if fc and tc:
            ctx = (f"Направление <b>{fN} → {tN}</b> — конвертация одной криптовалюты в другую (своп) без вывода в "
                   f"фиат. Обменники собирают курс {fT}/{tT} через пары к USDT и держат резерв в {tT}. Такой обмен "
                   f"выбирают, чтобы перейти из {fT} в {tT} — например зафиксировать прибыль "
                   f"{'в стейблкоине' if tstable else 'в '+tT} или сменить сеть.")
        elif fc and not tc:
            ctx = (f"Направление <b>{fN} → {tN}</b> — вывод криптовалюты {fT} в «{tcat}» ({tN}). Вы отдаёте {fT} с "
                   f"кошелька, обменник переводит эквивалент в {tT}. Курс и резерв {tT} у пунктов отличаются — "
                   f"мониторинг BestChange показывает лучшие. Перед крупной суммой проверьте адрес и лимиты.")
        elif not fc and tc:
            ctx = (f"Направление <b>{fN} → {tN}</b> — покупка криптовалюты {tT} за «{fcat}» ({fN}). Вы платите в {fT}, "
                   f"получаете {tT} на свой кошелёк. Сравните курс и комиссию сети получения {tT} перед обменом.")
        else:
            ctx = (f"Направление <b>{fN} → {tN}</b> — перевод между платёжными системами: «{fcat}» → «{tcat}». "
                   f"Обменники помогают, когда прямой перевод {fN} → {tN} недоступен или невыгоден.")
        h_ctx, amt_h, amt_cols = "Об этом направлении", "Сколько получите на текущем курсе", ("Отдаёте", "Получаете")
        q3 = f"Сколько обменников меняют {fN} на {tN}?"
        a3 = (f"Сейчас {r['count']} обменников по направлению {fT} → {tT}, суммарный резерв "
              f"{fmt_rate(r['reserve'])} {tT}." if r else "")
    else:
        if fc and tc:
            ctx = (f"The <b>{fN} → {tN}</b> direction is converting one cryptocurrency into another (a swap) without "
                   f"cashing out to fiat. Exchangers build the {fT}/{tT} rate via USDT pairs and hold a {tT} reserve. "
                   f"People pick it to move from {fT} to {tT} — e.g. to lock profit "
                   f"{'in a stablecoin' if tstable else 'in '+tT} or switch networks.")
        elif fc and not tc:
            ctx = (f"The <b>{fN} → {tN}</b> direction cashes out {fT} crypto into “{tcat}” ({tN}). You send {fT} from "
                   f"your wallet, the exchanger pays out the equivalent in {tT}. Rate and {tT} reserve vary by office — "
                   f"the BestChange monitor shows the best. Check the address and limits before a large amount.")
        elif not fc and tc:
            ctx = (f"The <b>{fN} → {tN}</b> direction buys {tT} crypto with “{fcat}” ({fN}). You pay in {fT} and "
                   f"receive {tT} to your wallet. Compare the rate and the receiving {tT} network fee before exchanging.")
        else:
            ctx = (f"The <b>{fN} → {tN}</b> direction transfers between payment systems: “{fcat}” → “{tcat}”. "
                   f"Exchangers help when a direct {fN} → {tN} transfer is unavailable or unfavorable.")
        h_ctx, amt_h, amt_cols = "About this direction", "How much you get at the current rate", ("You send", "You get")
        q3 = f"How many exchangers swap {fN} to {tN}?"
        a3 = (f"There are {r['count']} exchangers for {fT} → {tT} now, total reserve "
              f"{fmt_rate(r['reserve'])} {tT}." if r else "")
    amt_table = ""
    if r:
        rate = float(r["rate"])
        rws = "".join(f"<tr><td>{a} {fT}</td><td>{fmt_rate(a * rate)} {tT}</td></tr>" for a in (1, 10, 100, 1000))
        amt_table = (f'<p class="updnote">{amt_h}:</p><div class="rtbl-wrap"><table class="rtbl"><thead><tr>'
                     f'<th>{amt_cols[0]}</th><th>{amt_cols[1]}</th></tr></thead><tbody>{rws}</tbody></table></div>')
    html = f'<h2 class="news">{h_ctx}</h2><p>{ctx}</p>{amt_table}'
    return html, q3, a3


def render_pair(f, t, lang):
    fi, ti = CUR.get(f), CUR.get(t)
    if not fi or not ti:
        return
    fN, fT, tN, tT = fi["name"], fi["ticker"], ti["name"], ti["ticker"]
    path = f"/obmen/{f}-{t}/"
    r = rate_of(f, t)
    if lang == "ru":
        rate_line = ((f'<div class="big">{fmt_rate(r["rate"])} <span>{tT} за 1 {fT}</span></div>'
                      f'<div class="sub">по данным {r["count"]} обменников · резерв {fmt_rate(r["reserve"])} {tT}</div>')
                     if r else '<div class="sub">курс уточняется в мониторинге</div>')
        title = f"Обмен {fN} на {tN}" + (f" — курс {fmt_rate(r['rate'])} {tT}/{fT}" if r else "") + f" | {S['name']}"
        desc = (f"Обмен {fN} ({fT}) на {tN} ({tT}): " + (f"курс {fmt_rate(r['rate'])} {tT} за 1 {fT}, {r['count']} обменников, " if r else "")
                + "как обменять, AML-проверка адреса. Мониторинг BestChange.")
        h1 = f"Обмен {fN} <span class=\"tk\">{fT}</span> на {tN} <span class=\"tk\">{tT}</span>"
        h_how = f"Как обменять {fT} на {tT}"
        steps = [f"Откройте список обменников BestChange по направлению {fN} → {tN}.",
                 "Сравните курс, резерв и рейтинг обменников."] + \
                ([f'Для криптовалюты — сделайте <a href="{PREF[lang]}/aml/">AML-проверку адреса</a>.'] if fi["category"] == "Криптовалюты" else []) + \
                ["Проведите обмен на сайте выбранного обменника."]
        rev = f'<a href="{pair_url(lang, t, f)}">Обратный обмен: {tN} → {fN}</a> · ' if (t, f) in PAIR_SET else ""
        hub = f'<a href="{PREF[lang]}/na/{t}/">Все монеты → {tN}</a> · ' if t in BANK_HUB_SET else ""
        rel = f'{rev}{hub}<a href="{cpage(lang, f)}">О валюте {fN}</a> · <a href="{cpage(lang, t)}">О валюте {tN}</a>'
        q1 = f"Какой курс обмена {fN} на {tN}?"
        a1 = (f"Лучшее значение — <b>{fmt_rate(r['rate'])} {tT}</b> за 1 {fT} среди {r['count']} обменников. Справочно, меняется." if r else "Курс уточняется в мониторинге BestChange.")
        q2, a2 = "Безопасно ли это?", "Обмен идёт в пунктах из мониторинга BestChange с рейтингом и резервами. Для крипто рекомендуется AML-проверка адреса."
    else:
        rate_line = ((f'<div class="big">{fmt_rate(r["rate"])} <span>{tT} per 1 {fT}</span></div>'
                      f'<div class="sub">across {r["count"]} exchangers · reserve {fmt_rate(r["reserve"])} {tT}</div>')
                     if r else '<div class="sub">rate to be confirmed in the monitor</div>')
        title = f"Exchange {fN} to {tN}" + (f" — rate {fmt_rate(r['rate'])} {tT}/{fT}" if r else "") + f" | {S['name']}"
        desc = (f"Exchange {fN} ({fT}) to {tN} ({tT}): " + (f"rate {fmt_rate(r['rate'])} {tT} per 1 {fT}, {r['count']} exchangers, " if r else "")
                + "how to exchange, address AML check. BestChange monitor.")
        h1 = f"Exchange {fN} <span class=\"tk\">{fT}</span> to {tN} <span class=\"tk\">{tT}</span>"
        h_how = f"How to exchange {fT} to {tT}"
        steps = [f"Open the BestChange exchanger list for {fN} → {tN}.",
                 "Compare rate, reserve and exchanger rating."] + \
                ([f'For crypto — do an <a href="{PREF[lang]}/aml/">AML check of the address</a>.'] if fi["category"] == "Криптовалюты" else []) + \
                ["Complete the exchange on the chosen exchanger's site."]
        rev = f'<a href="{pair_url(lang, t, f)}">Reverse: {tN} → {fN}</a> · ' if (t, f) in PAIR_SET else ""
        hub = f'<a href="{PREF[lang]}/na/{t}/">All coins → {tN}</a> · ' if t in BANK_HUB_SET else ""
        rel = f'{rev}{hub}<a href="{cpage(lang, f)}">About {fN}</a> · <a href="{cpage(lang, t)}">About {tN}</a>'
        q1 = f"What is the {fN} to {tN} rate?"
        a1 = (f"Best value — <b>{fmt_rate(r['rate'])} {tT}</b> per 1 {fT} across {r['count']} exchangers. For reference, it changes." if r else "The rate is confirmed in the BestChange monitor.")
        q2, a2 = "Is it safe?", "The exchange runs in offices from BestChange monitoring with ratings and reserves. For crypto an address AML check is recommended."
    ctx_html, q3, a3 = pair_unique(fi, ti, r, lang)
    faq_items = [
        {"@type": "Question", "name": q1, "acceptedAnswer": {"@type": "Answer", "text": re.sub("<[^>]+>", "", a1)}},
        {"@type": "Question", "name": q2, "acceptedAnswer": {"@type": "Answer", "text": a2}}]
    if a3:
        faq_items.append({"@type": "Question", "name": q3,
                          "acceptedAnswer": {"@type": "Answer", "text": a3}})
    faq = jsonld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faq_items})
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": f"{fT} → {tT}", "item": BASE_URL + PREF[lang] + path}]})
    crumbs += jsonld({"@context": "https://schema.org", "@type": "WebPage", "name": title,
                      "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang],
                      "dateModified": modified_iso(), "lastReviewed": modified_iso(),
                      "speakable": {"@type": "SpeakableSpecification", "cssSelector": [".answer"]},
                      "reviewedBy": {"@type": "Organization", "name": S["name"], "url": BASE_URL}})
    ers = exchange_rate_ld(fT, r["rate"], tT) if r else ""
    steps_html = "".join(f"<li>{s}</li>" for s in steps)
    # GEO answer-first: датированное предложение с лучшим курсом направления (из данных мониторинга).
    _ld = datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d") if RATES_GENERATED else ""
    if r and lang == "ru":
        lead = (f"На {_ld} лучший курс обмена <b>{fN} ({fT})</b> на <b>{tN} ({tT})</b> ≈ "
                f"<b>{fmt_rate(r['rate'])} {tT}</b> за 1 {fT} по данным {r['count']} обменников из мониторинга "
                f"BestChange (резерв {fmt_rate(r['reserve'])} {tT}). Значение справочное, меняется.")
    elif r:
        lead = (f"As of {_ld}, the best {fN} ({fT}) → {tN} ({tT}) rate ≈ "
                f"<b>{fmt_rate(r['rate'])} {tT}</b> per 1 {fT} across {r['count']} exchangers in BestChange "
                f"monitoring (reserve {fmt_rate(r['reserve'])} {tT}). Reference value, changes over time.")
    elif lang == "ru":
        lead = (f"Курс обмена <b>{fN} ({fT})</b> на <b>{tN} ({tT})</b> уточняется в мониторинге BestChange; "
                f"обмен проходит на сайте выбранного обменника.")
    else:
        lead = (f"The <b>{fN} ({fT})</b> → <b>{tN} ({tT})</b> rate is confirmed in the BestChange monitor; "
                f"the exchange happens on the chosen exchanger's site.")
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {fT} → {tT}</nav>
    <h1>{h1}</h1>
    <p class="answer">{lead}</p>
    {trust_bar(lang)}
    <div class="rate-box">
      {rate_line}
      <a class="cta" href="{bc_link(f, t)}" target="_blank" rel="nofollow noopener sponsored">{tr(lang,'open_bc')}</a>
    </div>
    {ctx_html}
    {pair_chart(f, t, lang)}
    <h2 class="news">{h_how}</h2>
    <ol class="steps">{steps_html}</ol>
    {howto_ld(h_how, steps)}
    <p class="related">{rel} · <a href="{PREF[lang]}/blog/slovar-terminov-obmena/">{tr(lang,'glossary')}</a></p>
    {(lambda ps: (f'<h2 class="news">{("Другие направления " if lang=="ru" else "Other directions for ")+fT}</h2>'
                  f'<ul class="dlist">{"".join(pair_link_li(p, lang) for p in ps)}</ul>') if ps else "")(
        [p for p in popular_involving(f) if not (p["from"]==f and p["to"]==t)][:6])}
    <h2 class="news">{tr(lang,'faq')}</h2>
    <details><summary>{q1}</summary><p>{a1}</p></details>
    <details><summary>{q2}</summary><p>{a2}</p></details>
    {f'<details><summary>{q3}</summary><p>{a3}</p></details>' if a3 else ''}
  </div>
</div>
{faq}{crumbs}{ers}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + body)


def render_page(lang, slug, title, desc, body_html, crumb_title):
    path = f"/{slug}/"
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {crumb_title}</nav>
    {body_html}
  </div>
</div>
{footer(lang)}"""
    write(lang, path, head(lang, f"{title} | {S['name']}", desc, path, webpage_ld(title, path, lang)) + body)


def blog_page_path(lang, p):
    return f"{PREF[lang]}/blog/" if p == 1 else f"{PREF[lang]}/blog/page/{p}/"


def pager_html(lang, cur, pages):
    if pages <= 1:
        return ""
    parts = []
    if cur > 1:
        parts.append(f'<a class="pg-nav" href="{blog_page_path(lang, cur-1)}" rel="prev">←</a>')
    for p in range(1, pages + 1):
        if p == cur:
            parts.append(f'<span class="pg-cur">{p}</span>')
        else:
            parts.append(f'<a href="{blog_page_path(lang, p)}">{p}</a>')
    if cur < pages:
        parts.append(f'<a class="pg-nav" href="{blog_page_path(lang, cur+1)}" rel="next">→</a>')
    return f'<nav class="pager" aria-label="pagination">{"".join(parts)}</nav>'


def render_blog(lang):
    arts = ARTS[lang]
    if not arts:
        return
    def dsearch(a):
        return (a["title"] + " " + a.get("description", "") + " " + a["slug"]).lower().replace('"', "&quot;")
    # индекс ВСЕХ статей для сквозного поиска (встраивается в каждую страницу блога, ~15 записей)
    index = [{"t": a["title"], "d": a.get("description", ""), "dt": a.get("date", ""),
              "u": f"{PREF[lang]}/blog/{a['slug']}/",
              "k": (a["title"] + " " + a.get("description", "") + " " + a["slug"]).lower()} for a in arts]
    index_script = ('<script type="application/json" id="blogIndex">'
                    + json.dumps(index, ensure_ascii=False).replace("</", "<\\/") + '</script>')
    pages = (len(arts) + BLOG_PER_PAGE - 1) // BLOG_PER_PAGE
    if lang == "ru":
        base_title = f"Блог — гайды по обмену криптовалют и валют | {S['name']}"
        desc = "Статьи и гайды: сети USDT, комиссии, AML-проверка, словарь терминов обмена."
        h1, lead = "Блог", "Справочные материалы и гайды об обмене криптовалют и валют."
    else:
        base_title = f"Blog — crypto and currency exchange guides | {S['name']}"
        desc = "Articles and guides: USDT networks, fees, AML check, exchange glossary."
        h1, lead = "Blog", "Reference materials and guides on crypto and currency exchange."
    for p in range(1, pages + 1):
        path = ("/blog/" if p == 1 else f"/blog/page/{p}/")
        chunk = arts[(p - 1) * BLOG_PER_PAGE: p * BLOG_PER_PAGE]
        cards = "".join(
            f'<li data-search="{dsearch(a)}"><a href="{PREF[lang]}/blog/{a["slug"]}/">{a["title"]}</a>'
            f'<div class="apreview">{a.get("description","")}</div><div class="adate">{a.get("date","")}</div></li>'
            for a in chunk)
        title = base_title if p == 1 else (
            f"Блог, страница {p} | {S['name']}" if lang == "ru" else f"Blog, page {p} | {S['name']}")
        ld = jsonld({"@context": "https://schema.org", "@type": "Blog", "name": f"{S['name']} Blog",
                     "url": f"{BASE_URL}{PREF[lang]}/blog/"})
        ld += (f'\n<link rel="alternate" type="application/rss+xml" '
               f'title="{S["name"]} {"блог" if lang=="ru" else "blog"} RSS" '
               f'href="{PREF[lang]}/blog/rss.xml">')
        if p > 1:
            ld += f'\n<link rel="prev" href="{blog_page_path(lang, p-1)}">'
        if p < pages:
            ld += f'\n<link rel="next" href="{blog_page_path(lang, p+1)}">'
        pageinfo = "" if p == 1 else (f' <span class="pg-of">— страница {p} из {pages}</span>' if lang == "ru"
                                      else f' <span class="pg-of">— page {p} of {pages}</span>')
        body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / <a href="{PREF[lang]}/blog/">{h1}</a></nav>
    <h1>{h1}{pageinfo}</h1><p>{lead}</p>
    <div id="blogsearch" class="dosblue dosborder">
      <h3>{tr(lang,'blog_search_ph').rstrip('…')}</h3>
      <input id="bq" type="search" placeholder="{tr(lang,'blog_search_ph')}" autocomplete="off" aria-label="{tr(lang,'blog_search_ph')}">
    </div>
    <ul class="bloglist" id="bloglist">{cards}</ul>
    <p id="bnores" class="related" hidden>{tr(lang,'blog_noresults')}</p>
    {pager_html(lang, p, pages)}
    {index_script}
  </div>
</div>
{ld}
{footer(lang)}"""
        pdesc = desc if p == 1 else (desc + (f" Страница {p} из {pages}." if lang == "ru" else f" Page {p} of {pages}."))
        write(lang, path, head(lang, title, pdesc, path, ld) + body)


def render_rss(lang):
    arts = ARTS[lang]
    if not arts:
        return
    base = BASE_URL + PREF[lang]
    self_url = f"{base}/blog/rss.xml"
    ttl = f"{S['name']} — блог" if lang == "ru" else f"{S['name']} — Blog"
    dsc = ("Гайды по обмену криптовалют и валют." if lang == "ru"
           else "Guides on crypto and currency exchange.")
    items = ""
    for a in arts:
        try:
            y, m, d = (int(x) for x in a.get("date", "").split("-"))
            pub = format_datetime(datetime(y, m, d, tzinfo=timezone.utc))
        except (ValueError, TypeError):
            pub = ""
        url = f"{base}/blog/{a['slug']}/"
        items += (f"<item><title>{xml_escape(a['title'])}</title>"
                  f"<link>{url}</link><guid isPermaLink=\"true\">{url}</guid>"
                  + (f"<pubDate>{pub}</pubDate>" if pub else "")
                  + f"<description>{xml_escape(a.get('description',''))}</description></item>")
    rss = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
           f'<title>{xml_escape(ttl)}</title><link>{base}/blog/</link>'
           f'<description>{xml_escape(dsc)}</description><language>{LOCALE[lang]}</language>'
           f'<atom:link href="{self_url}" rel="self" type="application/rss+xml"/>'
           f'{items}</channel></rss>')
    full = os.path.join(DIST, (PREF[lang] + "/blog/rss.xml").strip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "w", encoding="utf-8").write(rss)


REVIEWS = [("sutki", 1, "сутки", "day"), ("nedelya", 7, "неделю", "week"), ("mesyac", 30, "месяц", "month")]
_PK = {1: "24h", 7: "7d", 30: "30d"}
_SID = {1: "sutki", 7: "nedelya", 30: "mesyac"}


def _span_days(pts):
    if len(pts) < 2:
        return 0
    return (_hist_time(pts[-1][0]) - _hist_time(pts[0][0])).days


def _pwindow(pts, days):
    cut = _hist_time(pts[-1][0]) - timedelta(days=days)
    w = [p for p in pts if _hist_time(p[0]) >= cut]
    return w if len(w) >= 2 else pts[-8:]


def review_content(lang, days, ru_word, en_word):
    """Авто-обзор рынка за период: топ роста/падения из истории (нужна история >= days у валюты).
    Возвращает dict {h1, desc, date, has_data, inner} — используется и страницей, и лентой Дзена."""
    pk = _PK[days]
    movers = []
    for slug, pts in HISTORY.items():
        if slug not in CUR or _span_days(pts) < days:
            continue
        if CUR[slug]["category"] != "Криптовалюты":     # это обзор рынка КРИПТОВАЛЮТ — фиат/банки не берём
            continue
        pct = CHG_BY.get(slug, {}).get(pk)
        if pct is None or abs(pct) > 300:               # отсев явных выбросов (артефакты тонкой истории)
            continue
        movers.append((slug, pct))
    now = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    if lang == "ru":
        h1 = f"Обзор рынка криптовалют за {ru_word}"
        desc = (f"Какие криптовалюты выросли и упали за {ru_word}: топ роста и падения с графиками. "
                f"Данные мониторинга BestChange, на {now}.")
    else:
        h1 = f"Crypto market review — past {en_word}"
        desc = (f"Which cryptocurrencies rose and fell over the past {en_word}: top gainers and losers with charts. "
                f"BestChange data, as of {now}.")
    if len(movers) < 5:                       # мало истории — честно показываем накопление, в Дзен не публикуем
        note = (f"Идёт накопление статистики — обзор появится, когда наберётся история за {ru_word} по большему "
                f"числу валют." if lang == "ru" else
                f"Collecting data — the review will appear once enough history for the past {en_word} accumulates.")
        return {"h1": h1, "desc": desc, "date": now, "has_data": False, "inner": f'<p class="updnote">{note}</p>'}
    movers.sort(key=lambda x: x[1], reverse=True)
    ups = [m for m in movers if m[1] > 0][:8]
    downs = sorted([m for m in movers if m[1] < 0], key=lambda x: x[1])[:8]
    n_up = sum(1 for m in movers if m[1] > 0)
    n_dn = sum(1 for m in movers if m[1] < 0)
    th = ("Валюта", "Изм.", "График") if lang == "ru" else ("Currency", "Chg.", "Chart")

    def _rows(items):
        out = ""
        for slug, pct in items:
            info = CUR[slug]
            cls = "up" if pct >= 0 else "down"
            sign = "+" if pct >= 0 else ""
            out += (f'<tr><td><a href="{cpage(lang, slug)}">{info["name"]} '
                    f'<span class="tk">{info["ticker"]}</span></a></td>'
                    f'<td class="{cls}">{sign}{pct:.1f}%</td>'
                    f'<td>{mini_spark(_pwindow(HISTORY[slug], days))}</td></tr>')
        return out

    def _tbl(items):
        return (f'<div class="rtbl-wrap"><table class="rtbl"><thead><tr>'
                f'<th>{th[0]}</th><th>{th[1]}</th><th>{th[2]}</th></tr></thead>'
                f'<tbody>{_rows(items)}</tbody></table></div>')
    up_lead = ", ".join(f'{CUR[s]["ticker"]} (+{p:.1f}%)' for s, p in ups[:3])
    dn_lead = ", ".join(f'{CUR[s]["ticker"]} ({p:.1f}%)' for s, p in downs[:3])
    if lang == "ru":
        summary = (f"За {ru_word} из {len(movers)} отслеживаемых валют выросли {n_up}, снизились {n_dn}. "
                   f"Лидеры роста: {up_lead}. Сильнее всех упали: {dn_lead}. "
                   f"Цены — в USDT по данным мониторинга BestChange.")
        h_up, h_dn, allc = "Топ роста", "Топ падения", "Все графики по валютам →"
    else:
        summary = (f"Over the past {en_word}, of {len(movers)} tracked currencies {n_up} rose and {n_dn} fell. "
                   f"Top gainers: {up_lead}. Biggest drops: {dn_lead}. Prices in USDT per BestChange monitoring.")
        h_up, h_dn, allc = "Top gainers", "Top losers", "All currency charts →"
    inner = (f'<p>{summary}</p>'
             f'<h2 class="news">{h_up}</h2>{_tbl(ups)}'
             f'<h2 class="news">{h_dn}</h2>{_tbl(downs)}'
             f'<p class="related"><a href="{PREF[lang]}/grafiki/">{allc}</a></p>')
    # Дзен-версия: без inline-SVG (Дзен их не поддерживает) и без таблицы с 8 ссылками (Дзен режет исходящие) —
    # текст + проценты списком + ОДНА заметная ссылка на полный обзор с графиками на сайте.
    sid = _SID[days]
    site_url = f"{BASE_URL}/obzor/{sid}/"
    _li = lambda items: "".join(
        f'<li>{CUR[s]["name"]} ({CUR[s]["ticker"]}): {"+" if p >= 0 else ""}{p:.1f}%</li>' for s, p in items)
    full = ("Полный обзор с интерактивными графиками — на сайте: " if lang == "ru"
            else "Full review with interactive charts on the site: ")
    dzen = (f'<p>{summary}</p>'
            f'<h3>{h_up}</h3><ul>{_li(ups)}</ul>'
            f'<h3>{h_dn}</h3><ul>{_li(downs)}</ul>'
            f'<p>{full}<a href="{site_url}">{site_url}</a></p>')
    return {"h1": h1, "desc": desc, "date": now, "has_data": True, "inner": inner, "dzen": dzen}


def render_review(lang, sid, days, ru_word, en_word):
    path = f"/obzor/{sid}/"
    rc = review_content(lang, days, ru_word, en_word)
    title = f"{rc['h1']} ({rc['date']}) | {S['name']}"
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": rc["h1"], "item": BASE_URL + PREF[lang] + path}]})
    crumbs += jsonld({"@context": "https://schema.org", "@type": "WebPage", "name": rc["h1"],
                      "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang], "dateModified": modified_iso()})
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {rc['h1']}</nav>
    <h1>{rc['h1']}</h1>
    {trust_bar(lang)}
    {rc['inner']}
  </div>
</div>
{crumbs}
{footer(lang)}"""
    # У обзора «за сутки» соц-превью = дневной график (1080×1080), с суточным cache-buster,
    # чтобы VK/соцсети не показывали вчерашнюю закэшированную карточку. Так же его цепляет автопост в VK.
    og_img, ogw, ogh = None, 1200, 630
    if sid == "sutki":
        suffix = "-en" if lang == "en" else ""
        # landscape 1200×630 (VK отбивает квадрат: link_photo_sizing_rule) — см. make_og_card.
        # URL БЕЗ query: VK определяет тип по расширению — .png?d=… он считает «не картинкой» → No photo given.
        og_img = f"{BASE_URL}/assets/daily-24h{suffix}-og.png"
        ogw, ogh = 1200, 630
    write(lang, path, head(lang, title, rc["desc"], path, og_image=og_img, og_w=ogw, og_h=ogh) + body)


def cover_url(slug, lang):
    """URL обложки статьи: персональная PNG, если генерация доступна, иначе общий og-image."""
    if COVERS_OK:
        return f"{BASE_URL}/assets/covers/{'en/' if lang == 'en' else ''}{slug}.png"
    return f"{BASE_URL}/assets/og-image.png"


def make_cover(out_path, title):
    """Рисует обложку 1200×630 с заголовком статьи в фирменном тёмном стиле."""
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (11, 11, 11))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 16, H], fill=(51, 204, 51))                 # зелёная акцент-полоса слева
    d.rectangle([0, 0, W - 1, H - 1], outline=(34, 90, 34), width=3)
    f_brand = ImageFont.truetype(FONT_BOLD, 34)
    f_title = ImageFont.truetype(FONT_BOLD, 60)
    f_foot = ImageFont.truetype(FONT_REG, 28)
    d.text((60, 52), "[⇄] RATESCOUT.RU", font=f_brand, fill=(85, 255, 255))
    # перенос заголовка по словам под ширину
    margin, maxw, lh = 60, W - 120, 76
    words, lines, cur = title.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f_title) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    lines = lines[:5]
    y = (H - lh * len(lines)) // 2 + 8
    for ln in lines:
        d.text((margin, y), ln, font=f_title, fill=(240, 240, 240))
        y += lh
    d.text((60, H - 72), "Гайды по обмену криптовалют и валют", font=f_foot, fill=(130, 130, 130))
    img.save(out_path, "PNG")


def write_favicons():
    """Растровые иконки в корне: /favicon.ico (16/32/48) + apple-touch-icon.png. Дизайн — DOS-бокс со
    стрелками обмена (как favicon.svg). Закрывает FAVICON_PROBLEM Яндекса (он ищет растровый /favicon.ico)."""
    if not _COVER_LIB:
        print("favicon: Pillow недоступен — остаётся только SVG")
        return
    S0 = 256
    img = Image.new("RGB", (S0, S0), (0, 0, 170))          # #0000aa — синий DOS-фон
    d = ImageDraw.Draw(img)
    cyan = (85, 255, 255)                                  # #55ffff — циан-рамка
    d.rectangle([14, 14, S0 - 15, S0 - 15], outline=cyan, width=14)   # внешняя рамка
    d.rectangle([44, 44, S0 - 45, S0 - 45], outline=cyan, width=6)    # внутренняя рамка
    # две стрелки обмена: верхняя вправо, нижняя влево
    d.line([(92, 104), (168, 104)], fill=cyan, width=12)
    d.polygon([(168, 88), (168, 120), (192, 104)], fill=cyan)         # → голова
    d.line([(88, 152), (164, 152)], fill=cyan, width=12)
    d.polygon([(88, 136), (88, 168), (64, 152)], fill=cyan)           # ← голова
    root = DIST
    img.save(os.path.join(root, "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    img.resize((180, 180)).save(os.path.join(root, "apple-touch-icon.png"))
    os.makedirs(os.path.join(root, "assets"), exist_ok=True)
    img.resize((32, 32)).save(os.path.join(root, "assets", "favicon-32.png"))
    print("favicon: /favicon.ico + apple-touch-icon.png сгенерированы")


def _use_custom_cover(src, dest):
    """Кастомная обложка от пользователя: нормализуем в 1080×1080 PNG (как генерённые)."""
    img = Image.open(src).convert("RGB")
    img = ImageOps.fit(img, (1080, 1080), Image.LANCZOS)
    img.save(dest, "PNG")


def write_covers():
    """Обложка для каждой статьи: кастомная из article_covers/<slug>.png, иначе генерим из заголовка."""
    if not COVERS_OK:
        print("обложки: Pillow/шрифты недоступны — использую общий og-image")
        return
    n, custom = 0, 0
    for lang in LANGS:
        d = os.path.join(DIST, "assets", "covers", "en" if lang == "en" else "")
        os.makedirs(d, exist_ok=True)
        for a in ARTS[lang]:
            dest = os.path.join(d, f"{a['slug']}.png")
            src = os.path.join(ROOT, "article_covers", f"{a['slug']}.png")
            if os.path.exists(src):
                try:
                    _use_custom_cover(src, dest); custom += 1
                except Exception:                  # noqa: BLE001 — битый файл → генерим из заголовка
                    make_cover(dest, a["title"])
            else:
                make_cover(dest, a["title"])
            n += 1
    print(f"обложки: сгенерировано {n} (из них кастомных {custom})")


def _svodka_rows():
    """Крипта с ценой в USDT, ликвидностью (число обменников к USDT) и изм. за 24ч."""
    rows = []
    for slug, info in CUR.items():
        if info["category"] != "Криптовалюты":
            continue
        price, liq = _usdt_price(slug)
        chg = CHG_BY.get(slug, {}).get("24h")
        if chg is not None and abs(chg) > 300:
            chg = None
        rows.append((slug, price, liq or 0, chg))
    return rows


def all_currencies_table(lang):
    """Полная сводная таблица по ВСЕМ валютам: цена USDT, изм.24ч, обменников, категория. Поиск/фильтр/сортировка."""
    items = []
    for slug, info in CUR.items():
        price, liq = _usdt_price(slug)
        if slug == "tether-trc20":
            price = 1.0
        chg = CHG_BY.get(slug, {}).get("24h")
        if chg is not None and abs(chg) > 300:
            chg = None
        items.append((slug, info, price, liq or 0, chg))
    items.sort(key=lambda x: x[3], reverse=True)                 # по умолчанию — ликвидность
    if lang == "ru":
        h = "Все валюты"
        ph = "Поиск: BTC, USDT, Sberbank…"
        cols = ("Валюта", "Категория", "Цена, USDT", "Изм. 24ч", "Обменников")
        sorts = [("liq", "Ликвидность"), ("price", "Цена"), ("up", "Рост"), ("down", "Падение"), ("name", "А–Я")]
        allb, nores = "Все", "Ничего не найдено"
    else:
        h = "All currencies"
        ph = "Search: BTC, USDT, Sberbank…"
        cols = ("Currency", "Category", "Price, USDT", "24h", "Exchangers")
        sorts = [("liq", "Liquidity"), ("price", "Price"), ("up", "Gainers"), ("down", "Losers"), ("name", "A–Z")]
        allb, nores = "All", "Nothing found"
    catb = "".join(f'<button type="button" data-f="{CAT_SLUG[c]}">{cat_name(c, lang)}</button>' for c in CATS)
    fbtns = f'<button type="button" data-f="" class="on">{allb}</button>' + catb
    sbtns = ""
    for v, l in sorts:
        on = ' class="on"' if v == "liq" else ""
        sbtns += f'<button type="button" data-s="{v}"{on}>{l}</button>'
    rws = ""
    for slug, info, price, liq, chg in items:
        cs = CAT_SLUG.get(info["category"], "prochee")
        pv = f"{price:.10f}".rstrip("0").rstrip(".") if price else ""
        if chg is None:
            chg_td, chg_a = "—", ""
        else:
            chg_td = f'<b class="{"up" if chg >= 0 else "down"}">{"+" if chg >= 0 else ""}{chg:.1f}%</b>'
            chg_a = f"{chg:.4f}"
        rws += (f'<tr class="acrow" data-search="{info["name"].lower()} {info["ticker"].lower()}" data-cat="{cs}" '
                f'data-name="{info["name"].lower()}" data-price="{pv}" data-chg="{chg_a}" data-liq="{liq}">'
                f'<td><a href="{cpage(lang, slug)}">{info["name"]} <span class="tk">{info["ticker"]}</span></a></td>'
                f'<td>{cat_name(info["category"], lang)}</td>'
                f'<td>{fmt_rate(price) if price else "—"}</td><td>{chg_td}</td><td>{liq}</td></tr>')
    thead = "".join(f"<th>{c}</th>" for c in cols)
    return (f'<h2 class="news">{h} <span class="cnt">{len(items)}</span></h2>'
            f'<div class="rtsearchbox"><input class="acsearch" type="search" placeholder="{ph}" autocomplete="off" aria-label="{ph}"></div>'
            f'<div class="rsrange accat">{fbtns}</div><div class="rsrange acsort">{sbtns}</div>'
            f'<div class="rtbl-wrap"><table class="rtbl allcurtbl"><thead><tr>{thead}</tr></thead><tbody>{rws}</tbody></table></div>'
            f'<p class="acnone updnote" hidden>{nores}</p>')


def render_svodka(lang):
    """Сводка рынка: 4 отчёта + полная таблица по всем валютам (поиск/фильтр/сортировка)."""
    path = "/svodka/"
    rows = _svodka_rows()
    if lang == "ru":
        h1 = "Сводка крипторынка"
        title = f"{h1} — ликвидность, стейблкоины, волатильность | {S['name']}"
        desc = ("Сводка крипторынка: индекс настроения, рейтинг ликвидности валют, привязка стейблкоинов к доллару "
                "и волатильность за сутки. Данные мониторинга BestChange.")
        t_liq = ("Валюта", "Обменников", "Цена, USDT")
        t_stb = ("Стейблкоин", "Цена, USDT", "Откл. от $1")
        t_vol = ("Валюта", "Изм. за 24ч")
        h_idx, h_liq, h_stb, h_vol = ("Индекс рынка", "Рейтинг ликвидности",
                                      "Стейблкоины: привязка к доллару", "Волатильность за сутки")
        allc = "Все графики по валютам →"
        idx_note = "Индекс появится с накоплением истории."
        stb_note = "Пока нет данных по стейблкоинам."
        mood_g, mood_r, mood_n = "🟢 Рынок в плюсе", "🔴 Рынок в минусе", "⚪ Смешанный рынок"
    else:
        h1 = "Crypto market summary"
        title = f"{h1} — liquidity, stablecoins, volatility | {S['name']}"
        desc = ("Crypto market summary: mood index, currency liquidity ranking, stablecoin peg to the dollar and "
                "24h volatility. BestChange monitoring data.")
        t_liq = ("Currency", "Exchangers", "Price, USDT")
        t_stb = ("Stablecoin", "Price, USDT", "Dev. from $1")
        t_vol = ("Currency", "24h change")
        h_idx, h_liq, h_stb, h_vol = ("Market index", "Liquidity ranking",
                                      "Stablecoins: peg to the dollar", "24h volatility")
        allc = "All currency charts →"
        idx_note = "The index will appear as history accumulates."
        stb_note = "No stablecoin data yet."
        mood_g, mood_r, mood_n = "🟢 Market up", "🔴 Market down", "⚪ Mixed market"

    def _lnk(slug):
        info = CUR[slug]
        return f'<a href="{cpage(lang, slug)}">{info["name"]} <span class="tk">{info["ticker"]}</span></a>'

    def _table(head, body):
        h = "".join(f"<th>{c}</th>" for c in head)
        return f'<div class="rtbl-wrap"><table class="rtbl"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'

    # 1) Индекс/настроение — по топ-20 ликвидным монетам с изм. за 24ч
    withchg = sorted([r for r in rows if r[3] is not None], key=lambda r: r[2], reverse=True)[:20]
    if len(withchg) >= 5:
        avg = sum(r[3] for r in withchg) / len(withchg)
        up = sum(1 for r in withchg if r[3] > 0)
        dn = sum(1 for r in withchg if r[3] < 0)
        mood = mood_g if avg > 0.3 else mood_r if avg < -0.3 else mood_n
        cls = "up" if avg >= 0 else "down"
        by = "Средний ход топ-%d ликвидных монет за сутки" % len(withchg) if lang == "ru" else \
             "Average move of the top-%d liquid coins over 24h" % len(withchg)
        rose = f"Выросли {up}, снизились {dn}." if lang == "ru" else f"{up} up, {dn} down."
        idx_html = (f'<p class="big">{mood}</p><p>{by}: '
                    f'<b class="{cls}">{"+" if avg >= 0 else ""}{avg:.2f}%</b>. {rose}</p>')
    else:
        idx_html = f'<p class="updnote">{idx_note}</p>'

    # 2) Ликвидность — топ по числу обменников к USDT
    liq_top = sorted(rows, key=lambda r: r[2], reverse=True)[:12]
    liq_body = "".join(f'<tr><td>{_lnk(s)}</td><td>{liq}</td>'
                       f'<td>{fmt_rate(p) if p else "—"}</td></tr>' for s, p, liq, _ in liq_top)

    # 3) Стейблкоины — отклонение цены в USDT от 1.0 (один тикер = одна строка, берём самую ликвидную сеть)
    _best = {}
    for r in rows:
        tk = CUR[r[0]]["ticker"]
        if tk in STABLE_T and tk != "USDT" and r[1] is not None and (tk not in _best or r[2] > _best[tk][2]):
            _best[tk] = r        # USDT — база (=1), в peg-отчёт не берём
    stbl = sorted(_best.values(), key=lambda r: abs(r[1] - 1))
    if stbl:
        stb_body = ""
        for s, p, _liq, _ in stbl:
            dev = (p - 1) * 100
            cls = "up" if dev >= 0 else "down"
            stb_body += (f'<tr><td>{_lnk(s)}</td><td>{p:.4f}</td>'
                         f'<td class="{cls}">{"+" if dev >= 0 else ""}{dev:.2f}%</td></tr>')
        stb_html = _table(t_stb, stb_body)
    else:
        stb_html = f'<p class="updnote">{stb_note}</p>'

    # 4) Волатильность — по абсолютному изменению за 24ч
    vol = sorted([r for r in rows if r[3] is not None], key=lambda r: abs(r[3]), reverse=True)[:10]
    if vol:
        vol_body = ""
        for s, _p, _liq, chg in vol:
            cls = "up" if chg >= 0 else "down"
            vol_body += f'<tr><td>{_lnk(s)}</td><td class="{cls}">{"+" if chg >= 0 else ""}{chg:.1f}%</td></tr>'
        vol_html = _table(t_vol, vol_body)
    else:
        vol_html = f'<p class="updnote">{idx_note}</p>'

    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    crumbs += jsonld({"@context": "https://schema.org", "@type": "CollectionPage", "name": h1,
                      "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang], "dateModified": modified_iso()})
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1>
    {trust_bar(lang)}
    <h2 class="news">{h_idx}</h2>{idx_html}
    <h2 class="news">{h_liq}</h2>{_table(t_liq, liq_body)}
    <h2 class="news">{h_stb}</h2>{stb_html}
    <h2 class="news">{h_vol}</h2>{vol_html}
    {all_currencies_table(lang)}
    <p class="related"><a href="{PREF[lang]}/grafiki/">{allc}</a></p>
  </div>
</div>
{crumbs}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + body)


def _daily_movers():
    """Крипто-движения за 24ч (та же логика, что в обзоре): категория Криптовалюты, отсев выбросов."""
    out = []
    for slug, pts in HISTORY.items():
        if slug not in CUR or _span_days(pts) < 1 or CUR[slug]["category"] != "Криптовалюты":
            continue
        pct = CHG_BY.get(slug, {}).get("24h")
        if pct is None or abs(pct) > 300:
            continue
        out.append((slug, pct))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def _spark_draw(dr, pts, box, color):
    vals = [p[1] for p in pts] or [0.0, 0.0]
    mn, mx = min(vals), max(vals)
    span = (mx - mn) or (mx or 1.0)
    x, y, w, h = box
    n = len(vals)
    xy = [(x + (i / (n - 1) if n > 1 else 0) * w, y + (1 - (v - mn) / span) * h) for i, v in enumerate(vals)]
    if len(xy) >= 2:
        dr.line(xy, fill=color, width=3, joint="curve")


def make_og_card(src_path, out_path, W=1200, H=630):
    """1200×630-карточка для соцсетей/VK из квадратной картинки (квадрат по центру на чёрном фоне).
    VK для превью-ссылок отбивает квадрат/портрет (link_photo_sizing_rule) — ему нужен landscape ~1200×630."""
    src = Image.open(src_path).convert("RGB")
    nh = H
    nw = max(1, round(src.width * H / src.height))
    src = src.resize((nw, nh))
    canvas = Image.new("RGB", (W, H), (11, 11, 11))
    canvas.paste(src, ((W - nw) // 2, (H - nh) // 2))
    canvas.save(out_path, "PNG")


def make_daily_image(out_path, date, gainers, losers, lang="ru"):
    """Картинка для Telegram: топ роста/падения за сутки с 24ч-графиками (без emoji — DejaVu их не рисует)."""
    lab = (("[⇄] Крипторынок за сутки", "▲ Топ роста", "▼ Топ падения", "Полный обзор: ratescout.info.gf/obzor/sutki")
           if lang == "ru" else
           ("[⇄] Crypto market · 24h", "▲ Top gainers", "▼ Top losers", "Full review: ratescout.info.gf/en/obzor/sutki"))
    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), (11, 11, 11))
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, 16, H], fill=(51, 204, 51))
    fb = ImageFont.truetype(FONT_BOLD, 46)
    fh = ImageFont.truetype(FONT_BOLD, 40)
    fr = ImageFont.truetype(FONT_BOLD, 36)
    ff = ImageFont.truetype(FONT_REG, 28)
    dr.text((56, 44), lab[0], font=fb, fill=(85, 255, 255))
    dr.text((56, 108), f"{date} · ratescout.info.gf", font=ff, fill=(150, 150, 150))

    def section(title, items, y0, col):
        dr.text((56, y0), title, font=fh, fill=col)
        y = y0 + 66
        for slug, pct in items[:5]:
            sign = "+" if pct >= 0 else ""
            dr.text((70, y), CUR[slug]["ticker"], font=fr, fill=(235, 235, 235))
            dr.text((320, y), f"{sign}{pct:.1f}%", font=fr, fill=col)
            _spark_draw(dr, _pwindow(HISTORY[slug], 1), (600, y + 8, 420, 40), col)
            y += 70
        return y
    y = section(lab[1], gainers, 190, (85, 255, 85))
    section(lab[2], losers, y + 40, (255, 95, 95))
    dr.text((56, H - 64), lab[3], font=ff, fill=(130, 130, 130))
    img.save(out_path, "PNG")


def make_weekly_image(out_path, date, stbl, liq, lang="ru"):
    """Картинка для воскресной «Сводки»: стейблкоины (откл. от $1) + ликвидность. Без emoji (DejaVu их не рисует)."""
    lab = (("[⇄] Сводка крипторынка", "Стейблкоины (откл. от $1)", "Ликвидность (обменников к USDT)",
            "Полная сводка: ratescout.info.gf/svodka") if lang == "ru" else
           ("[⇄] Crypto market summary", "Stablecoins (peg to $1)", "Liquidity (exchangers to USDT)",
            "Full summary: ratescout.info.gf/en/svodka"))
    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), (11, 11, 11))
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, 16, H], fill=(51, 204, 51))
    fb = ImageFont.truetype(FONT_BOLD, 46)
    fh = ImageFont.truetype(FONT_BOLD, 40)
    fr = ImageFont.truetype(FONT_BOLD, 34)
    ff = ImageFont.truetype(FONT_REG, 28)
    dr.text((56, 44), lab[0], font=fb, fill=(85, 255, 255))
    dr.text((56, 108), f"{date} · ratescout.info.gf", font=ff, fill=(150, 150, 150))
    y = 200
    dr.text((56, y), lab[1], font=fh, fill=(120, 200, 255))
    y += 66
    for s, p, _liq, _ in stbl:
        dev = (p - 1) * 100
        col = (85, 255, 85) if dev >= 0 else (255, 95, 95)
        dr.text((70, y), CUR[s]["ticker"], font=fr, fill=(235, 235, 235))
        dr.text((380, y), f"{p:.4f}", font=fr, fill=(200, 200, 200))
        dr.text((640, y), f"{'+' if dev >= 0 else ''}{dev:.2f}%", font=fr, fill=col)
        y += 62
    y += 44
    dr.text((56, y), lab[2], font=fh, fill=(255, 220, 120))
    y += 66
    for s, _p, lq, _ in liq:
        dr.text((70, y), CUR[s]["ticker"], font=fr, fill=(235, 235, 235))
        dr.text((380, y), str(lq), font=fr, fill=(120, 220, 160))
        y += 62
    dr.text((56, H - 64), lab[3], font=ff, fill=(130, 130, 130))
    img.save(out_path, "PNG")


def _digest_weekly(now_dt, out, fl=""):
    """Воскресная «Сводка» для Telegram: настроение + стейблкоины + ликвидность (вместо топ-движений)."""
    rows = _svodka_rows()
    withchg = sorted([r for r in rows if r[3] is not None], key=lambda r: r[2], reverse=True)[:20]
    best = {}
    for r in rows:
        tk = CUR[r[0]]["ticker"]
        if tk in STABLE_T and tk != "USDT" and r[1] is not None and (tk not in best or r[2] > best[tk][2]):
            best[tk] = r        # USDT — база (=1), не берём
    stbl = sorted(best.values(), key=lambda r: abs(r[1] - 1), reverse=True)[:5]
    liq = sorted(rows, key=lambda r: r[2], reverse=True)[:5]
    if len(withchg) < 5 and not stbl:
        json.dump({"has_data": False}, open(out, "w"))
        print("weekly: мало данных — сводка пропущена")
        return
    now = now_dt.strftime("%d.%m.%Y")
    if withchg:
        avg = sum(r[3] for r in withchg) / len(withchg)
        up = sum(1 for r in withchg if r[3] > 0)
        dn = sum(1 for r in withchg if r[3] < 0)
        mood = "🟢 в плюсе" if avg > 0.3 else "🔴 в минусе" if avg < -0.3 else "⚪ смешанный"
        idx_line = f"Настроение: {mood} (средний ход топ-{len(withchg)}: {'+' if avg >= 0 else ''}{avg:.2f}%, ↑{up}/↓{dn})"
    else:
        idx_line = "Настроение: данные накапливаются"
    allc = [r for r in rows if r[3] is not None]
    au = sum(1 for r in allc if r[3] > 0)
    ad = sum(1 for r in allc if r[3] < 0)
    agg_line = (f"📋 Валют в базе: {len(CUR)}. За сутки по крипте ({len(allc)} монет): выросли {au}, упали {ad}."
                if allc else f"📋 Валют в базе: {len(CUR)}.")
    img_url = ""
    if COVERS_OK:
        make_weekly_image(os.path.join(DIST, "assets", "daily-week.png"), now, stbl, liq)
        img_url = f"{BASE_URL}/assets/daily-week.png"
    lines = [f"🧭 Сводка крипторынка · {now}", "", agg_line, idx_line, ""]
    if stbl:
        lines.append("💵 Стейблкоины (откл. от $1):")
        lines += [f"• {CUR[s]['ticker']} {p:.4f} ({'+' if (p - 1) >= 0 else ''}{(p - 1) * 100:.2f}%)"
                  for s, p, _l, _c in stbl]
        lines.append("")
    lines.append("🏆 Ликвидность (обменников к USDT):")
    lines += [f"• {CUR[s]['ticker']} — {lq}" for s, _p, lq, _c in liq]
    lines += ["", f"📊 Полная таблица всех {len(CUR)} валют (поиск/сортировка) → {BASE_URL}/svodka/",
              "", "📢 Наши каналы: Telegram https://t.me/ratescout_kurs · Дзен https://dzen.ru/ratescout · ВК https://vk.com/ratescout · Mastodon https://mastodon.social/@ratescout_ru · Blogger https://blogger.ratescout.info.gf/", "", "#крипта #курсы #сводка"]
    short = (f"🧭 Сводка крипторынка {now}\n{idx_line}\n"
             f"Полная сводка → {BASE_URL}/svodka/\n#крипта #курсы")[:490]
    json.dump({"has_data": True, "caption": "\n".join(lines), "image": img_url,
               "url": f"{BASE_URL}/svodka/", "buttons": _digest_buttons("/svodka/"),
               "full_list": fl, "full_list_url": f"{BASE_URL}/daily-all.txt",
               "short": short, "title": f"Сводка крипторынка · {now}"},
              open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print("weekly: сводка готова")


def _digest_buttons(primary, lang="ru"):
    """Инлайн-кнопки-ссылки под постом в Telegram (URL-кнопки — работают в канале без сервера)."""
    pref = "/en" if lang == "en" else ""
    if lang == "ru":
        ptext = "📊 Обзор за сутки" if primary.endswith("/obzor/sutki/") else "📋 Все валюты"
        b_app, b_charts, b_rates = "🚀 Приложение", "📈 Графики", "💱 Все курсы"
    else:
        ptext = "📊 24h review" if primary.endswith("/obzor/sutki/") else "📋 All currencies"
        b_app, b_charts, b_rates = "🚀 App", "📈 Charts", "💱 All rates"
    return [
        [{"text": ptext, "url": BASE_URL + primary},
         {"text": b_app, "url": "https://t.me/RateScoutRUBot/ratescout_ru"}],
        [{"text": b_charts, "url": BASE_URL + pref + "/grafiki/"}, {"text": b_rates, "url": BASE_URL + pref + "/"}],
        [{"text": "📰 Дзен", "url": "https://dzen.ru/ratescout"},
         {"text": "🅥 ВКонтакте", "url": "https://vk.com/ratescout"}],
    ]


def _full_list_items():
    """Все валюты: (тикер, цена USDT, ликвидность, изм.24ч), сорт по ликвидности."""
    it = []
    for slug, info in CUR.items():
        price, liq = _usdt_price(slug)
        if slug == "tether-trc20":
            price = 1.0
        chg = CHG_BY.get(slug, {}).get("24h")
        if chg is not None and abs(chg) > 300:
            chg = None
        it.append((info["ticker"], price, liq or 0, chg))
    it.sort(key=lambda x: x[2], reverse=True)
    return it


def _fl_line(t, p, liq, chg):
    ps = fmt_rate(p) if p else "—"
    cs = (("+" if chg >= 0 else "") + f"{chg:.1f}%") if chg is not None else "—"
    return f"{t}: {ps} · {cs} · {liq}"


def full_list_text(lang="ru"):
    it = _full_list_items()
    h = (f"📋 Все валюты ({len(it)}) — цена USDT · изм.24ч · обменников:" if lang == "ru"
         else f"📋 All currencies ({len(it)}) — price USDT · 24h · exchangers:")
    return h + "\n\n" + "\n".join(_fl_line(*x) for x in it)


def full_list_html(lang="ru"):
    it = _full_list_items()
    h = ("📋 Все валюты — цена USDT · изм.24ч · обменников:" if lang == "ru"
         else "📋 All currencies — price USDT · 24h · exchangers:")
    return "<p><b>" + h + "</b><br>" + "<br>".join(_fl_line(*x) for x in it) + "</p>"


def write_daily_digest():
    """Дайджест для Telegram: dist/daily.json {caption,image,url,full_list,full_list_url} + картинка + полный
    список всех валют (dist/daily-all.txt). Воскресенье — «Сводка», будни — топ движений. Постит tg_daily.py."""
    now_dt = datetime.now(timezone.utc)
    fl = full_list_text()
    open(os.path.join(DIST, "daily-all.txt"), "w", encoding="utf-8").write(fl)   # полный список файлом (для TG)
    if now_dt.weekday() == 6:            # воскресенье — «Сводка недели» вместо топ-движений (разнообразие)
        _digest_weekly(now_dt, os.path.join(DIST, "daily.json"), fl)
        return
    movers = _daily_movers()
    gainers = [m for m in movers if m[1] > 0][:5]
    losers = sorted([m for m in movers if m[1] < 0], key=lambda x: x[1])[:5]
    out = os.path.join(DIST, "daily.json")
    if len(movers) < 5 or not (gainers or losers):
        json.dump({"has_data": False}, open(out, "w"))
        print("daily: данных мало — TG-дайджест пропустит")
        return
    now = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    img_url = ""
    if COVERS_OK:
        make_daily_image(os.path.join(DIST, "assets", "daily-24h.png"), now, gainers, losers)
        make_og_card(os.path.join(DIST, "assets", "daily-24h.png"),
                     os.path.join(DIST, "assets", "daily-24h-og.png"))   # 1200×630 для VK-карточки
        img_url = f"{BASE_URL}/assets/daily-24h.png"
    lines = [f"📊 Крипторынок за сутки · {now}", ""]
    lines.append("📈 Топ роста:")
    lines += [f"• {CUR[s]['ticker']} +{p:.1f}%" for s, p in gainers]
    lines += ["", "📉 Топ падения:"]
    lines += [f"• {CUR[s]['ticker']} {p:.1f}%" for s, p in losers]
    lines += ["", f"Полный обзор и графики → {BASE_URL}/obzor/sutki/",
              "", "📢 Наши каналы: Telegram https://t.me/ratescout_kurs · Дзен https://dzen.ru/ratescout · ВК https://vk.com/ratescout · Mastodon https://mastodon.social/@ratescout_ru · Blogger https://blogger.ratescout.info.gf/", "", "#крипта #курсы #обзор"]
    short = (f"📊 Крипторынок за сутки {now}\n📈 "
             + " · ".join(f"{CUR[s]['ticker']} +{p:.1f}%" for s, p in gainers[:3])
             + "\n📉 " + " · ".join(f"{CUR[s]['ticker']} {p:.1f}%" for s, p in losers[:3])
             + f"\nОбзор → {BASE_URL}/obzor/sutki/\n#крипта #курсы")[:490]
    json.dump({"has_data": True, "caption": "\n".join(lines), "image": img_url,
               "url": f"{BASE_URL}/obzor/sutki/", "buttons": _digest_buttons("/obzor/sutki/"),
               "full_list": fl, "full_list_url": f"{BASE_URL}/daily-all.txt",
               "short": short, "title": f"Крипторынок за сутки · {now}"},
              open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"daily: дайджест готов{' с картинкой' if img_url else ' (без картинки)'}")


def write_daily_digest_en():
    """Английский дайджест → dist/daily-en.json + daily-all-en.txt (для EN Telegram-канала). Ссылки на /en/."""
    now_dt = datetime.now(timezone.utc)
    fl = full_list_text("en")
    open(os.path.join(DIST, "daily-all-en.txt"), "w", encoding="utf-8").write(fl)
    out = os.path.join(DIST, "daily-en.json")
    now = now_dt.strftime("%d.%m.%Y")
    chans = ("📢 Our channels: Telegram https://t.me/ratescout_kurs · Дзен https://dzen.ru/ratescout · "
             "VK https://vk.com/ratescout · Mastodon https://mastodon.social/@ratescout_ru · "
             "Blogger https://blogger.ratescout.info.gf/")
    if now_dt.weekday() == 6:                     # воскресенье — сводка
        rows = _svodka_rows()
        withchg = sorted([r for r in rows if r[3] is not None], key=lambda r: r[2], reverse=True)[:20]
        best = {}
        for r in rows:
            tk = CUR[r[0]]["ticker"]
            if tk in STABLE_T and tk != "USDT" and r[1] is not None and (tk not in best or r[2] > best[tk][2]):
                best[tk] = r
        stbl = sorted(best.values(), key=lambda r: abs(r[1] - 1), reverse=True)[:5]
        liq = sorted(rows, key=lambda r: r[2], reverse=True)[:5]
        if len(withchg) < 5 and not stbl:
            json.dump({"has_data": False}, open(out, "w"))
            return
        if withchg:
            avg = sum(r[3] for r in withchg) / len(withchg)
            up = sum(1 for r in withchg if r[3] > 0)
            dn = sum(1 for r in withchg if r[3] < 0)
            mood = "🟢 up" if avg > 0.3 else "🔴 down" if avg < -0.3 else "⚪ mixed"
            idx_line = f"Sentiment: {mood} (avg top-{len(withchg)}: {'+' if avg >= 0 else ''}{avg:.2f}%, ↑{up}/↓{dn})"
        else:
            idx_line = "Sentiment: collecting data"
        allc = [r for r in rows if r[3] is not None]
        agg = (f"📋 Currencies tracked: {len(CUR)}. Over 24h (crypto, {len(allc)}): "
               f"{sum(1 for r in allc if r[3] > 0)} up, {sum(1 for r in allc if r[3] < 0)} down."
               if allc else f"📋 Currencies tracked: {len(CUR)}.")
        img_url = ""
        if COVERS_OK:
            make_weekly_image(os.path.join(DIST, "assets", "daily-week-en.png"), now, stbl, liq, lang="en")
            img_url = f"{BASE_URL}/assets/daily-week-en.png"
        lines = [f"🧭 Crypto market summary · {now}", "", agg, idx_line, ""]
        if stbl:
            lines.append("💵 Stablecoins (peg to $1):")
            lines += [f"• {CUR[s]['ticker']} {p:.4f} ({'+' if (p - 1) >= 0 else ''}{(p - 1) * 100:.2f}%)"
                      for s, p, _l, _c in stbl]
            lines.append("")
        lines.append("🏆 Liquidity (exchangers to USDT):")
        lines += [f"• {CUR[s]['ticker']} — {lq}" for s, _p, lq, _c in liq]
        lines += ["", f"📊 Full table of all {len(CUR)} currencies → {BASE_URL}/en/svodka/", "", chans, "", "#crypto #rates"]
        short = (f"🧭 Crypto market summary {now}\n{idx_line}\nFull summary → {BASE_URL}/en/svodka/\n#crypto")[:490]
        json.dump({"has_data": True, "caption": "\n".join(lines), "image": img_url,
                   "url": f"{BASE_URL}/en/svodka/", "buttons": _digest_buttons("/en/svodka/", "en"),
                   "full_list": fl, "full_list_url": f"{BASE_URL}/daily-all-en.txt",
                   "short": short, "title": f"Crypto market summary · {now}"},
                  open(out, "w", encoding="utf-8"), ensure_ascii=False)
        print("daily-en: сводка готова")
        return
    movers = _daily_movers()                       # будни — топ движений
    gainers = [m for m in movers if m[1] > 0][:5]
    losers = sorted([m for m in movers if m[1] < 0], key=lambda x: x[1])[:5]
    if len(movers) < 5 or not (gainers or losers):
        json.dump({"has_data": False}, open(out, "w"))
        return
    img_url = ""
    if COVERS_OK:
        make_daily_image(os.path.join(DIST, "assets", "daily-24h-en.png"), now, gainers, losers, lang="en")
        make_og_card(os.path.join(DIST, "assets", "daily-24h-en.png"),
                     os.path.join(DIST, "assets", "daily-24h-en-og.png"))   # 1200×630 для VK-карточки
        img_url = f"{BASE_URL}/assets/daily-24h-en.png"
    lines = [f"📊 Crypto market · 24h · {now}", "", "📈 Top gainers:"]
    lines += [f"• {CUR[s]['ticker']} +{p:.1f}%" for s, p in gainers]
    lines += ["", "📉 Top losers:"]
    lines += [f"• {CUR[s]['ticker']} {p:.1f}%" for s, p in losers]
    lines += ["", f"Full review & charts → {BASE_URL}/en/obzor/sutki/", "", chans, "", "#crypto #rates"]
    short = (f"📊 Crypto 24h {now}\n📈 " + " · ".join(f"{CUR[s]['ticker']} +{p:.1f}%" for s, p in gainers[:3])
             + "\n📉 " + " · ".join(f"{CUR[s]['ticker']} {p:.1f}%" for s, p in losers[:3])
             + f"\nReview → {BASE_URL}/en/obzor/sutki/\n#crypto")[:490]
    json.dump({"has_data": True, "caption": "\n".join(lines), "image": img_url,
               "url": f"{BASE_URL}/en/obzor/sutki/", "buttons": _digest_buttons("/en/obzor/sutki/", "en"),
               "full_list": fl, "full_list_url": f"{BASE_URL}/daily-all-en.txt",
               "short": short, "title": f"Crypto market · 24h · {now}"},
              open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print("daily-en: дайджест готов")


def write_article_announce():
    """article-today.json — статья(и) блога, вышедшая СЕГОДНЯ (release==сегодня), для авто-анонса в соцсети."""
    today = datetime.now(timezone.utc).date().isoformat()
    due = [a for a in ARTS["ru"] if (a.get("release") or "")[:10] == today]
    out = os.path.join(DIST, "article-today.json")
    if not due:
        json.dump({"has_data": False}, open(out, "w"))
        return
    a = due[0]
    slug = a["slug"]
    json.dump({"has_data": True, "title": a["title"], "url": f"{BASE_URL}/blog/{slug}/",
               "excerpt": a.get("description", ""),
               "image": f"{BASE_URL}/assets/covers/{slug}.png" if COVERS_OK else f"{BASE_URL}/assets/og-image.png"},
              open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"анонс статьи: {slug}")


def render_dzen_rss():
    """RSS-лента для авто-публикации в Дзене (RU): полный текст в content:encoded, абсолютные ссылки, обложка.
    Дзен требует именно полный HTML статьи, а не анонс; относительные ссылки на внешней платформе не работают."""
    arts = ARTS["ru"]
    if not arts:
        return
    author = S.get("owner_email", "") or "info@ratescout.info.gf"
    tg_promo = ('<p>📢 Ежедневные курсы и обзор рынка — в наших каналах: '
                'Telegram <a href="https://t.me/ratescout_kurs">t.me/ratescout_kurs</a> · '
                'ВКонтакте <a href="https://vk.com/ratescout">vk.com/ratescout</a> · '
                'Mastodon <a href="https://mastodon.social/@ratescout_ru">@ratescout_ru</a> · '
                'Blogger <a href="https://blogger.ratescout.info.gf/">blogger.ratescout.info.gf</a></p>')
    items = ""
    for a in arts:
        og = cover_url(a["slug"], "ru")
        try:
            y, m, d = (int(x) for x in a.get("date", "").split("-"))
            pub = format_datetime(datetime(y, m, d, tzinfo=timezone.utc))
        except (ValueError, TypeError):
            pub = ""
        url = f"{BASE_URL}/blog/{a['slug']}/"
        html = a["html"].replace('href="/', f'href="{BASE_URL}/')   # относительные ссылки → абсолютные
        items += ("<item>"
                  f"<title>{xml_escape(a['title'])}</title>"
                  f"<link>{url}</link><guid isPermaLink=\"true\">{url}</guid>"
                  + (f"<pubDate>{pub}</pubDate>" if pub else "")
                  + f"<author>{xml_escape(author)} ({xml_escape(S['name'])})</author>"
                  f"<description>{xml_escape(a.get('description',''))}</description>"
                  f"<enclosure url=\"{og}\" type=\"image/png\"/>"
                  f"<content:encoded><![CDATA[{html}{tg_promo}]]></content:encoded>"
                  "</item>")
    # авто-обзоры за неделю/месяц — попадают в Дзен только при наличии данных; guid по периоду
    # (ISO-неделя / год-месяц) → каждый новый период Дзен публикует как новый пост
    now_dt = datetime.now(timezone.utc)
    pubnow = format_datetime(now_dt)
    for sid, d, rw, ew in REVIEWS:
        rc = review_content("ru", d, rw, ew)
        if not rc["has_data"]:
            continue
        url = f"{BASE_URL}/obzor/{sid}/"
        pid = (now_dt.strftime("%Y-%m-%d") if d == 1
               else now_dt.strftime("%G-W%V") if d == 7 else now_dt.strftime("%Y-%m"))
        rhtml = rc["dzen"] + full_list_html()   # облегчённая версия + полный список всех валют текстом
        items += ("<item>"
                  f"<title>{xml_escape(rc['h1'])} ({rc['date']})</title>"
                  f"<link>{url}</link><guid isPermaLink=\"false\">{url}#{pid}</guid>"
                  f"<pubDate>{pubnow}</pubDate>"
                  f"<author>{xml_escape(author)} ({xml_escape(S['name'])})</author>"
                  f"<description>{xml_escape(rc['desc'])}</description>"
                  f"<enclosure url=\"{BASE_URL}/assets/og-image.png\" type=\"image/png\"/>"
                  f"<content:encoded><![CDATA[{rhtml}{tg_promo}]]></content:encoded>"
                  "</item>")
    feed = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
            'xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
            f'<title>{xml_escape(S["name"])} — блог</title>'
            f'<link>{BASE_URL}/blog/</link>'
            '<description>Гайды по обмену криптовалют и валют.</description>'
            '<language>ru</language>'
            f'<atom:link href="{BASE_URL}/dzen.xml" rel="self" type="application/rss+xml"/>'
            f'{items}</channel></rss>')
    open(os.path.join(DIST, "dzen.xml"), "w", encoding="utf-8").write(feed)


def render_article(a, lang):
    path = f"/blog/{a['slug']}/"
    title = f"{a['title']} | {S['name']}"
    desc = a.get("description", "")
    cover = cover_url(a["slug"], lang)
    art_ld = jsonld({"@context": "https://schema.org", "@type": "Article", "headline": a["title"],
                     "description": desc, "datePublished": a.get("date", ""),
                     "dateModified": a.get("modified", a.get("date", "")), "inLanguage": LOCALE[lang],
                     "image": cover,
                     "author": {"@type": "Organization", "name": S["name"]},
                     "publisher": {"@type": "Organization", "name": S["name"],
                                   "logo": {"@type": "ImageObject", "url": f"{BASE_URL}/assets/og-image.png"}},
                     "mainEntityOfPage": BASE_URL + PREF[lang] + path})
    back = "← All articles" if lang == "en" else "← Все статьи"
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / <a href="{PREF[lang]}/blog/">{tr(lang,'nav_blog')}</a> / {a['title']}</nav>
    <article class="post"><div class="adate">{'Опубликовано' if lang=='ru' else 'Published'}: {a.get('date','')} · <a href="{PREF[lang]}/redakciya/">{'Редакция ' if lang=='ru' else 'Editorial · '}{S['name']}</a></div>{a['html']}</article>
    <p><a href="{PREF[lang]}/blog/">{back}</a></p>
  </div>
</div>
{art_ld}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path, og_image=cover) + body)


FAQ_ITEMS = {
    "ru": [
        ("Какая сеть USDT самая дешёвая для перевода?",
         "Обычно TRC20 (TRON) — низкая и стабильная комиссия сети. BEP20 (BNB Smart Chain) тоже дешёвый. "
         "ERC20 (Ethereum) дороже, комиссия зависит от загрузки сети. Сеть отправителя и получателя должна совпадать."),
        ("Сколько идёт перевод USDT?",
         "В сети TRC20 перевод обычно приходит за 1–5 минут после подтверждений. Скорость зависит от сети и её загрузки, "
         "а также от числа подтверждений, которое требует получатель или обменник."),
        ("Что такое резерв обменника?",
         "Резерв — сколько валюты доступно у обменника по конкретному направлению прямо сейчас. Если резерв меньше вашей "
         "суммы, обмен не пройдёт или займёт время. Резерв смотрят вместе с курсом и рейтингом."),
        ("Чем обменник отличается от биржи?",
         "Обменник проводит операцию по фиксированному курсу и резерву — быстро и без регистрации ордеров. Биржа — это "
         "торговая площадка со стаканом заявок, где цену формируют покупатели и продавцы. Для разового обмена обычно берут обменник."),
        ("Как выбрать лучший курс обмена?",
         "Смотрите не только на верхний курс, но и на резерв, рейтинг и отзывы обменника, а также лимиты и комиссию сети. "
         "Слишком выгодный курс иногда означает маленький резерв или скрытые условия. Сравнить помогает мониторинг BestChange."),
        ("Что такое AML-проверка криптоадреса?",
         "AML-проверка оценивает связь адреса или транзакции с мошенничеством, даркнетом и санкциями. Её делают до приёма "
         "или обмена крупной суммы, чтобы снизить риск получить «грязные» монеты и блокировку средств."),
        ("Безопасен ли обмен криптовалюты через обменник?",
         "Риск снижается, если выбирать обменник с высоким рейтингом, историей и достаточным резервом из мониторинга, а для "
         "криптовалюты делать AML-проверку адреса. Гарантий не даёт никто — решение об обмене вы принимаете самостоятельно."),
        ("Что такое СБП и при чём тут обмен?",
         "СБП — Система быстрых платежей Банка России: мгновенные переводы между банками по номеру телефона. Многие обменники "
         "выдают рубли через СБП — это быстро и удобно; учитывайте лимиты вашего банка."),
    ],
    "en": [
        ("Which USDT network is the cheapest for transfers?",
         "Usually TRC20 (TRON) — a low, stable network fee. BEP20 (BNB Smart Chain) is also cheap. ERC20 (Ethereum) is "
         "pricier and its fee depends on network load. The sender's and recipient's network must match."),
        ("How long does a USDT transfer take?",
         "On TRC20 a transfer usually arrives within 1–5 minutes after confirmations. Speed depends on the network and its "
         "load, and on how many confirmations the recipient or exchanger requires."),
        ("What is an exchanger's reserve?",
         "Reserve is how much currency an exchanger has available for a given direction right now. If the reserve is smaller "
         "than your amount, the exchange won't go through or will take time. Check reserve together with the rate and rating."),
        ("How is an exchanger different from an exchange?",
         "An exchanger completes the operation at a fixed rate and reserve — fast and without placing orders. An exchange is "
         "a trading venue with an order book where buyers and sellers set the price. For a one-off swap people usually pick an exchanger."),
        ("How do I choose the best exchange rate?",
         "Look not only at the top rate but also at the exchanger's reserve, rating and reviews, plus limits and the network "
         "fee. A rate that's too good can mean a small reserve or hidden terms. The BestChange monitor helps compare."),
        ("What is a crypto address AML check?",
         "An AML check assesses an address or transaction for links to fraud, darknet and sanctions. It's done before "
         "receiving or exchanging a large amount to reduce the risk of getting 'dirty' coins and frozen funds."),
        ("Is exchanging crypto through an exchanger safe?",
         "Risk is lower if you pick an exchanger with a high rating, history and sufficient reserve from a monitor, and do an "
         "address AML check for crypto. No one guarantees anything — you decide to exchange on your own."),
        ("What is SBP and how does it relate to exchanging?",
         "SBP is Russia's Faster Payments System: instant transfers between banks by phone number. Many exchangers pay out "
         "rubles via SBP — fast and convenient; mind your bank's limits."),
    ],
}


def render_faq(lang):
    items = FAQ_ITEMS[lang]
    path = "/faq/"
    if lang == "ru":
        title = f"Частые вопросы об обмене криптовалют и валют | {S['name']}"
        desc = "Ответы на частые вопросы: сети USDT и комиссии, резерв, AML-проверка, СБП, как выбрать обменник и лучший курс."
        h1, lead = "Частые вопросы", "Короткие ответы на популярные вопросы об обмене криптовалют и валют."
    else:
        title = f"Frequently asked questions about crypto and currency exchange | {S['name']}"
        desc = "Answers to common questions: USDT networks and fees, reserve, AML check, SBP, how to choose an exchanger and the best rate."
        h1, lead = "Frequently asked questions", "Short answers to popular questions about crypto and currency exchange."
    qa = "".join(f'<details><summary>{q}</summary><p>{a}</p></details>' for q, a in items)
    faq_ld = jsonld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in items]})
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}</p>
    {qa}
  </div>
</div>
{faq_ld}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path, faq_ld + webpage_ld(title, path, lang)) + body)


def render_category(cat, lang):
    slug = CAT_SLUG.get(cat, "prochee")
    path = f"/kategoriya/{slug}/"
    curs = GROUPED.get(cat, [])
    if not curs:
        return
    cname = cat_name(cat, lang)
    intro = CAT_INTRO.get(cat, ("", ""))[0 if lang == "ru" else 1]
    items = "".join(f'<li><a href="{cpage(lang, s)}">{i["name"]} <span>{i["ticker"]}</span></a></li>'
                    for s, i in curs)
    if lang == "ru":
        title = f"{cname} — обмен: курсы и все направления ({len(curs)}) | {S['name']}"
        desc = f"{cname} для обмена: {len(curs)} направлений, курсы из мониторинга BestChange, калькулятор, все направления обмена."
        h1 = f"Обмен: {cname}"
        q1, a1 = f"Сколько {cname.lower()} доступно для обмена?", f"В каталоге {len(curs)} направлений категории «{cname}». На странице каждого — курсы всех направлений обмена."
        listh = f"Все направления категории «{cname}»"
    else:
        title = f"{cname} — exchange: rates and all directions ({len(curs)}) | {S['name']}"
        desc = f"{cname} for exchange: {len(curs)} directions, rates from BestChange monitoring, calculator, all exchange directions."
        h1 = f"Exchange: {cname}"
        q1, a1 = f"How many {cname.lower()} are available to exchange?", f"The catalog has {len(curs)} directions in the “{cname}” category. Each page lists rates for all exchange directions."
        listh = f"All directions in “{cname}”"
    _ld = datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d") if RATES_GENERATED else ""
    cat_lead = (f"На {_ld} в категории «<b>{cname}</b>» — <b>{len(curs)}</b> направлений обмена по данным мониторинга "
                f"BestChange (обновление ежечасно). На странице каждой валюты — курсы всех её направлений."
                if lang == "ru" else
                f"As of {_ld}, the “<b>{cname}</b>” category has <b>{len(curs)}</b> exchange directions per BestChange "
                f"monitoring (hourly updates). Each currency page lists rates for all its directions.")
    faq_ld = jsonld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q1, "acceptedAnswer": {"@type": "Answer", "text": a1}}]})
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": cname, "item": BASE_URL + PREF[lang] + path}]})
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {cname}</nav>
    <h1>{h1} <span class="cnt">{len(curs)}</span></h1>
    <p class="answer">{cat_lead}</p>
    <div class="dosblue dosborder">{intro}</div>
    <h2 class="news">{listh}</h2>
    <ul class="dlist">{items}</ul>
    <h2 class="news">{tr(lang,'faq')}</h2>
    <details><summary>{q1}</summary><p>{a1}</p></details>
  </div>
</div>
{faq_ld}{crumbs}{itemlist_ld([(i["name"], BASE_URL + cpage(lang, s)) for s, i in curs])}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path, webpage_ld(title, path, lang)) + body)


def _gterm(t, lang):
    return t["ru"] if lang == "ru" else t["en"]


def _gdef(t, lang):
    return t["def_ru"] if lang == "ru" else t["def_en"]


def render_widget_page(lang):
    """Страница /vidzhet/ — галерея виджетов (курс + конвертер): код для вставки + живое демо."""
    path = "/vidzhet/"
    def esc(c):
        return c.replace("<", "&lt;").replace(">", "&gt;")
    code_rate = ('<div class="ratescout-widget" data-pair="usdt-rub"></div>\n'
                 '<script src="' + BASE_URL + '/widget.js" async></script>')
    code_conv = ('<div class="ratescout-widget" data-widget="converter"></div>\n'
                 '<script src="' + BASE_URL + '/widget.js" async></script>')
    pairs_list = ", ".join(f"<code>{k}</code>" for k, *_ in WIDGET_PAIRS)
    if lang == "ru":
        title = f"Виджеты курсов и конвертер для сайта — бесплатно | {S['name']}"
        desc = "Бесплатные встраиваемые виджеты для сайта: живой курс обмена и мини-конвертер криптовалют. Вставьте код — обновляется автоматически."
        h1 = "Виджеты для вашего сайта"
        lead = ("Разместите на своём сайте живой курс или мини-конвертер обмена — обновляются автоматически, "
                "бесплатно. Достаточно вставить код в HTML страницы.")
        t_rate, t_conv, h_pairs, h_how = "Виджет курса", "Виджет-конвертер (ввод суммы)", "Доступные пары (data-pair)", "Как это работает"
        t_cfg, cfg_lead, l_give, l_get = "Конструктор виджета — любая пара", "Выберите любую пару из каталога проекта — получите готовый код и предпросмотр.", "Отдаю", "Получаю"
        how = ["Скопируйте код нужного виджета и вставьте в HTML страницы.",
               "Курс: <code>data-pair</code> (популярная) или <code>data-from</code>+<code>data-to</code> (любая пара). Конвертер: <code>data-widget=\"converter\"</code>.",
               "Скрипт сам подтянет актуальные курсы и обновит виджет.",
               "Несколько виджетов на странице — вставьте несколько блоков <code>div</code>."]
    else:
        title = f"Rate and converter widgets for your site — free | {S['name']}"
        desc = "Free embeddable widgets for your site: a live exchange rate and a mini crypto converter. Paste the code — updates automatically."
        h1 = "Widgets for your website"
        lead = ("Put a live rate or a mini exchange converter on your site — they update automatically, for free. "
                "Just paste the code into your page's HTML.")
        t_rate, t_conv, h_pairs, h_how = "Rate widget", "Converter widget (amount input)", "Available pairs (data-pair)", "How it works"
        t_cfg, cfg_lead, l_give, l_get = "Widget builder — any pair", "Pick any pair from the project catalog — get ready code and a preview.", "From", "To"
        how = ["Copy the code of the widget you want and paste it into your page's HTML.",
               "Rate: <code>data-pair</code> (popular) or <code>data-from</code>+<code>data-to</code> (any pair). Converter: <code>data-widget=\"converter\"</code>.",
               "The script pulls current rates and updates the widget.",
               "For several widgets on a page — add several <code>div</code> blocks."]
    how_html = "".join(f"<li>{s}</li>" for s in how)
    demo_style = "padding:14px;background:#0d0d0d;border:1px solid #333;margin:0 0 12px"
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1}</h1><p>{lead}</p>

    <h2 class="news">{t_cfg}</h2>
    <p>{cfg_lead}</p>
    <div class="conv dosblue dosborder" style="max-width:420px">
      <label>{l_give}<select id="cfgFrom"></select></label>
      <label>{l_get}<select id="cfgTo"></select></label>
    </div>
    <div style="{demo_style}"><div id="cfgPreview"></div></div>
    <pre class="code-embed"><code id="cfgCode"></code></pre>
    <script>
    (function(){{
      var fromS=document.getElementById('cfgFrom'),toS=document.getElementById('cfgTo'),
          prev=document.getElementById('cfgPreview'),code=document.getElementById('cfgCode');
      if(!fromS)return;
      var CARD="font:13px/1.4 system-ui,Arial,sans-serif;display:inline-block;border:1px solid #d0d5dd;border-radius:8px;padding:10px 14px;background:#fff;color:#111;min-width:210px";
      var LBL="font-size:11px;color:#667085;text-transform:uppercase;letter-spacing:.04em";
      var BIG="font-size:20px;font-weight:700;margin:2px 0";
      var LINK="color:#0a66c2;text-decoration:none;font-weight:600";
      var ATTR="display:block;margin-top:6px;font-size:11px;color:#98a2b3;text-decoration:none";
      function num(v){{v=parseFloat(String(v).replace(/\\s/g,''));return isNaN(v)?0:v;}}
      function fmt(v){{if(v>=1000)return v.toLocaleString('ru-RU',{{maximumFractionDigits:0}});if(v>=1)return v.toLocaleString('ru-RU',{{maximumFractionDigits:2}});return v.toFixed(6).replace(/0+$/,'').replace(/\\.$/,'');}}
      fetch('/widget-rates.json').then(function(r){{return r.json();}}).then(function(d){{
        var cur=d.cur,slugs=Object.keys(cur).sort(function(a,b){{return cur[a].n.localeCompare(cur[b].n);}});
        var opts=slugs.map(function(s){{return '<option value="'+s+'">'+cur[s].n+' ('+cur[s].t+')</option>';}}).join('');
        fromS.innerHTML=opts;toS.innerHTML=opts;
        if(cur['bitcoin'])fromS.value='bitcoin';if(cur['sberbank'])toS.value='sberbank';
        function upd(){{
          var f=fromS.value,t=toS.value,cf=cur[f],ct=cur[t],r=d.rates[f]&&d.rates[f][t];
          var rate=r?fmt(num(r)):'—';
          prev.innerHTML='<div style="'+CARD+'"><div style="'+LBL+'">'+cf.t+' → '+ct.t+'</div>'+
            '<div style="'+BIG+'">1 '+cf.t+' = '+rate+' '+ct.t+'</div>'+
            '<a href="{BASE_URL}/valuta/'+f+'/" target="_blank" rel="noopener" style="'+LINK+'">Обменять →</a>'+
            '<a href="{BASE_URL}/" target="_blank" rel="noopener" style="'+ATTR+'">Курсы: RateScout</a></div>';
          code.textContent='<div class="ratescout-widget" data-from="'+f+'" data-to="'+t+'"></div>\\n<script src="{BASE_URL}/widget.js" async><\\/script>';
        }}
        fromS.addEventListener('change',upd);toS.addEventListener('change',upd);upd();
      }}).catch(function(){{}});
    }})();
    </script>

    <h2 class="news">{t_conv}</h2>
    <div style="{demo_style}"><div class="ratescout-widget" data-widget="converter"></div></div>
    <pre class="code-embed"><code>{esc(code_conv)}</code></pre>

    <h2 class="news">{h_pairs}</h2>
    <p class="related">{pairs_list}</p>
    <h2 class="news">{h_how}</h2>
    <ol class="steps">{how_html}</ol>
    <script src="/widget.js" async></script>
  </div>
</div>
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + body)


def render_glossary(lang):
    if not GLOSSARY:
        return
    terms = sorted(GLOSSARY, key=lambda t: _gterm(t, lang).lower())
    # индекс /slovar/
    lidx = "".join(f'<li><a href="{PREF[lang]}/slovar/{t["slug"]}/">{_gterm(t, lang)}</a>'
                   f'<div class="apreview">{_gdef(t, lang)[:110]}…</div></li>' for t in terms)
    if lang == "ru":
        it, idesc = "Словарь терминов обмена криптовалют — определения А–Я", "Понятные определения терминов обмена: курс, резерв, спред, сеть, комиссия, AML, KYC, стейблкоин, эскроу и другие."
        ih1, ilead = "Словарь терминов", "Короткие понятные определения терминов, которые встречаются при обмене криптовалют и валют."
    else:
        it, idesc = "Glossary of crypto exchange terms — definitions A–Z", "Clear definitions of exchange terms: rate, reserve, spread, network, fee, AML, KYC, stablecoin, escrow and more."
        ih1, ilead = "Glossary", "Short, clear definitions of the terms you meet when exchanging crypto and currencies."
    ild = jsonld({"@context": "https://schema.org", "@type": "DefinedTermSet", "name": ih1,
                  "url": f"{BASE_URL}{PREF[lang]}/slovar/"})
    ibody = f"""{header(lang, "/slovar/")}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {ih1}</nav>
    <h1>{ih1} <span class="cnt">{len(terms)}</span></h1><p>{ilead}</p>
    <ul class="bloglist">{lidx}</ul>
  </div>
</div>
{ild}
{footer(lang)}"""
    write(lang, "/slovar/", head(lang, f"{it} | {S['name']}", idesc, "/slovar/", ild + webpage_ld(it, "/slovar/", lang)) + ibody)
    # страницы терминов
    for t in GLOSSARY:
        term, dfn, path = _gterm(t, lang), _gdef(t, lang), f"/slovar/{t['slug']}/"
        see = [GLOSSARY_BY[s] for s in t.get("see", []) if s in GLOSSARY_BY]
        see_html = ("".join(f'<li><a href="{PREF[lang]}/slovar/{s["slug"]}/">{_gterm(s, lang)}</a></li>' for s in see))
        seeh = ("См. также" if lang == "ru" else "See also")
        allh = ("Все термины" if lang == "ru" else "All terms")
        morh = ("Подробнее" if lang == "ru" else "In more detail")
        ext = t.get("ext_" + lang, "")
        title = f"{term} — что это простыми словами | {S['name']}" if lang == "ru" else f"{term} — meaning explained | {S['name']}"
        desc = (dfn[:155]).rsplit(" ", 1)[0] + "…"
        dt_ld = jsonld({"@context": "https://schema.org", "@type": "DefinedTerm", "name": term,
                        "description": dfn, "inDefinedTermSet": f"{BASE_URL}{PREF[lang]}/slovar/",
                        "url": BASE_URL + PREF[lang] + path})
        crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
            {"@type": "ListItem", "position": 2, "name": ("Словарь" if lang == "ru" else "Glossary"), "item": BASE_URL + PREF[lang] + "/slovar/"},
            {"@type": "ListItem", "position": 3, "name": term, "item": BASE_URL + PREF[lang] + path}]})
        body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / <a href="{PREF[lang]}/slovar/">{'Словарь' if lang=='ru' else 'Glossary'}</a> / {term}</nav>
    <h1>{term}</h1>
    <div class="dosblue dosborder">{dfn}</div>
    {f'<h2 class="news">{morh}</h2><p>{ext}</p>' if ext else ''}
    {f'<h2 class="news">{seeh}</h2><ul class="dlist">{see_html}</ul>' if see_html else ''}
    <p class="related"><a href="{PREF[lang]}/slovar/">← {allh}</a> · <a href="{PREF[lang]}/faq/">{tr(lang,'nav_faq')}</a> · <a href="{PREF[lang]}/">{tr(lang,'all_cur')}</a></p>
  </div>
</div>
{dt_ld}{crumbs}
{footer(lang)}"""
        write(lang, path, head(lang, title, desc, path, webpage_ld(title, path, lang)) + body)


def render_editorial(lang):
    """Страница «О редакции» — сигналы доверия (E-E-A-T) для YMYL-ниши."""
    owner = S.get("owner", "")
    email = S.get("owner_email", "")
    if lang == "ru":
        title = "О редакции RateScout — кто ведёт сайт и как мы работаем"
        desc = "Редакция RateScout: независимый справочник курсов обмена. Принципы, источники данных, обновление и контакты."
        body = f"""<h1>О редакции RateScout</h1>
<p><b>RateScout</b> — независимый информационный справочник курсов обмена криптовалют и валют. Мы не обменный
   пункт и не проводим операции: наша задача — собрать и понятно показать данные, чтобы вы приняли решение сами.</p>
<h2>Как мы работаем</h2>
<ul>
  <li><b>Источник данных</b> — мониторинг обменных пунктов <a href="{PREF[lang]}/o-servise/">BestChange</a>:
      курсы, резервы и число обменников. Курсы на сайте обновляются <b>ежечасно</b>.</li>
  <li><b>Нейтральность.</b> Мы не оцениваем обменники субъективно и не даём финансовых рекомендаций — только справочные данные.</li>
  <li><b>Прозрачность.</b> Ссылки на обмен ведут в BestChange; по партнёрской программе мы можем получать
      вознаграждение (<a href="{PREF[lang]}/raskrytie/">раскрытие</a>).</li>
  <li><b>Актуальность.</b> Гайды и справочные страницы поддерживаются в актуальном состоянии; на страницах
      курсов указано время последнего обновления.</li>
</ul>
<h2>Для кого это</h2>
<p>Для тех, кто обменивает криптовалюту и валюты и хочет быстро сориентироваться в курсах, сетях, комиссиях и
   безопасности (включая <a href="{PREF[lang]}/blog/chto-takoe-aml-proverka/">AML-проверку</a>).</p>
<h2>Владелец и контакты</h2>
<p>Владелец сайта: {S.get('owner_status','')} <b>{owner}</b>, ИНН {S.get('owner_inn','')}. Вопросы, уточнения,
   сообщения об ошибках в данных — на <a href="mailto:{email}">{email}</a>. Мы за обратную связь: если заметили
   неточность в курсе или тексте — напишите, поправим.</p>
<p class="related"><a href="{PREF[lang]}/raskrytie/">Раскрытие и дисклеймеры</a> ·
   <a href="{PREF[lang]}/politika/">Политика конфиденциальности</a></p>"""
        crumb = "О редакции"
    else:
        title = "About the RateScout editorial team — who runs the site and how"
        desc = "RateScout editorial team: an independent rate directory. Principles, data sources, updates and contacts."
        body = f"""<h1>About the RateScout editorial team</h1>
<p><b>RateScout</b> is an independent directory of crypto and currency exchange rates. We are not an exchange
   office and do not process transactions: our job is to collect and clearly present data so you can decide yourself.</p>
<h2>How we work</h2>
<ul>
  <li><b>Data source</b> — the <a href="{PREF[lang]}/o-servise/">BestChange</a> exchange monitor: rates,
      reserves and exchanger counts. Rates on the site update <b>hourly</b>.</li>
  <li><b>Neutrality.</b> We don't rate exchangers subjectively and don't give financial advice — reference data only.</li>
  <li><b>Transparency.</b> Exchange links lead to BestChange; through the affiliate program we may earn a
      commission (<a href="{PREF[lang]}/raskrytie/">disclosure</a>).</li>
  <li><b>Freshness.</b> Guides and reference pages are kept current; rate pages show the last update time.</li>
</ul>
<h2>Who it's for</h2>
<p>For anyone exchanging crypto and currencies who wants to quickly navigate rates, networks, fees and safety
   (including an <a href="{PREF[lang]}/blog/chto-takoe-aml-proverka/">AML check</a>).</p>
<h2>Owner and contacts</h2>
<p>Site owner: <b>{owner}</b> (self-employed, RU tax ID {S.get('owner_inn','')}). Questions, corrections and
   data-error reports — at <a href="mailto:{email}">{email}</a>. We welcome feedback: spotted an inaccuracy in a
   rate or text? Let us know and we'll fix it.</p>
<p class="related"><a href="{PREF[lang]}/raskrytie/">Disclosure</a> ·
   <a href="{PREF[lang]}/politika/">Privacy policy</a></p>"""
        crumb = "Editorial"
    render_page(lang, "redakciya", title, desc, body, crumb)


def render_bank_hub(to_slug, lang):
    ti = CUR.get(to_slug)
    if not ti:
        return
    name, tT = ti["name"], ti["ticker"]
    # все крипто-валюты с курсом → этот получатель, по популярности
    rows = []
    for fs, fi in GROUPED.get("Криптовалюты", []):
        r = rate_of(fs, to_slug)
        if r:
            rows.append((r.get("count", 0), fs, fi, r))
    if len(rows) < 5:
        return
    rows.sort(key=lambda x: x[0], reverse=True)
    path = f"/na/{to_slug}/"
    if lang == "ru":
        title = f"Обмен криптовалюты на {name} — курсы и все монеты ({len(rows)}) | {S['name']}"
        desc = (f"Обмен криптовалюты на {name}: {len(rows)} направлений, лучшие курсы из мониторинга BestChange. "
                f"USDT, Bitcoin, Ethereum и другие монеты на {name}. Калькулятор, AML-подсказки.")
        intro = (f"Собраны направления обмена криптовалюты на <b>{name}</b> с лучшими курсами из мониторинга "
                 f"<b>BestChange</b>. Выберите монету ниже — откроется список обменников по направлению.")
        h1 = f"Обмен криптовалюты на {name}"
        th = ("Монета", "Лучший курс", "Обменников", "Резерв, всего")
        openw, howh = "Открыть", f"Как обменять крипту на {name}"
        steps = [f"Выберите монету для обмена на {name} в таблице.",
                 "В BestChange сравните курс, резерв и рейтинг обменников.",
                 f'Для крипто — сделайте <a href="{PREF[lang]}/aml/">AML-проверку адреса</a>.',
                 f"Проведите обмен и получите средства на {name}."]
        note = "Лучший курс среди обменников; резерв — суммарный по направлению. " + updated_str(lang)
        q1 = f"Как обменять USDT на {name}?"
        a1 = f"Выберите направление USDT → {name} в таблице, сравните обменники в BestChange по курсу и резерву и проведите обмен."
        guide = f'<a href="{PREF[lang]}/blog/kak-obmenyat-usdt-na-rubli/">Пошаговый гайд по выводу в рубли</a>'
    else:
        title = f"Exchange crypto to {name} — rates and all coins ({len(rows)}) | {S['name']}"
        desc = (f"Exchange crypto to {name}: {len(rows)} directions, best rates from BestChange monitoring. "
                f"USDT, Bitcoin, Ethereum and other coins to {name}. Calculator, AML tips.")
        intro = (f"Directions to exchange crypto to <b>{name}</b> with the best rates from the <b>BestChange</b> "
                 f"monitor. Pick a coin below — the exchanger list for that direction opens.")
        h1 = f"Exchange crypto to {name}"
        th = ("Coin", "Best rate", "Exchangers", "Total reserve")
        openw, howh = "Open", f"How to exchange crypto to {name}"
        steps = [f"Pick a coin to exchange to {name} in the table.",
                 "On BestChange compare rate, reserve and exchanger rating.",
                 f'For crypto — do an <a href="{PREF[lang]}/aml/">address AML check</a>.',
                 f"Complete the exchange and receive funds to {name}."]
        note = "Best rate among exchangers; reserve is the total for the direction. " + updated_str(lang)
        q1 = f"How to exchange USDT to {name}?"
        a1 = f"Pick the USDT → {name} direction in the table, compare exchangers on BestChange by rate and reserve, and complete the exchange."
        guide = f'<a href="{PREF[lang]}/blog/kak-obmenyat-usdt-na-rubli/">Step-by-step cash-out guide</a>'
    trs = ""
    for cnt, fs, fi, r in rows:
        trs += (f'<tr><td class="d"><a href="{bc_link(fs, to_slug)}" target="_blank" rel="nofollow noopener sponsored">'
                f'{fi["name"]} <span>{fi["ticker"]}</span></a></td>'
                f'<td class="num"><b>{fmt_rate(r["rate"])}</b></td><td class="num">{cnt}</td>'
                f'<td class="num">{fmt_rate(r.get("reserve", 0))}</td></tr>')
    faq_ld = jsonld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q1, "acceptedAnswer": {"@type": "Answer", "text": a1}}]})
    crumbs = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr(lang, "monitor"), "item": BASE_URL + PREF[lang] + "/"},
        {"@type": "ListItem", "position": 2, "name": h1, "item": BASE_URL + PREF[lang] + path}]})
    crumbs += jsonld({"@context": "https://schema.org", "@type": "WebPage", "name": title,
                      "url": BASE_URL + PREF[lang] + path, "inLanguage": LOCALE[lang], "dateModified": modified_iso()})
    steps_html = "".join(f"<li>{s}</li>" for s in steps)
    body = f"""{header(lang, path)}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <nav class="crumbs"><a href="{PREF[lang]}/">{tr(lang,'monitor')}</a> / {h1}</nav>
    <h1>{h1} <span class="cnt">{len(rows)}</span></h1>
    <div class="dosblue dosborder">{intro}</div>
    <div class="rtbl-wrap"><table class="rtbl"><thead><tr>
      <th>{th[0]}</th><th>{th[1]}</th><th>{th[2]}</th><th>{th[3]}</th></tr></thead><tbody>{trs}</tbody></table></div>
    <p class="updnote">{note}</p>
    <h2 class="news">{howh}</h2>
    <ol class="steps">{steps_html}</ol>
    {howto_ld(howh, steps)}
    <p class="related">{guide} · <a href="{cpage(lang, to_slug)}">{'О ' if lang=='ru' else 'About '}{name}</a></p>
    <h2 class="news">{tr(lang,'faq')}</h2>
    <details><summary>{q1}</summary><p>{a1}</p></details>
  </div>
</div>
{faq_ld}{crumbs}{itemlist_ld([(fi["name"], BASE_URL + cpage(lang, fs)) for _c, fs, fi, _r in rows])}
{footer(lang)}"""
    write(lang, path, head(lang, title, desc, path) + body)


_AML_JS = r"""
var input=document.getElementById('amlAddr'),btn=document.getElementById('amlBtn'),out=document.getElementById('amlResult');
var S=null;
function det(a){
  if(/^0x[a-fA-F0-9]{40}$/.test(a))return{c:'ETH',e:'https://etherscan.io/address/'+a};
  if(/^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}$/.test(a))return{c:'BTC',e:'https://mempool.space/address/'+a};
  if(/^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(a))return{c:'TRON',e:'https://tronscan.org/#/address/'+a};
  if(/^(ltc1|[LM])[a-km-zA-HJ-NP-Z1-9]{25,60}$/.test(a))return{c:'LTC',e:'https://litecoinspace.org/address/'+a};
  if(/^4[0-9AB][0-9A-Za-z]{93}$/.test(a))return{c:'XMR',e:''};
  return null;
}
function esc(s){return String(s).replace(/[<>&"]/g,function(x){return{'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[x];});}
function load(cb){if(S)return cb();fetch('/aml-sanctions.json').then(function(r){return r.json();}).then(function(d){var a=d.addresses||[];S={set:new Set(a),low:new Set(a.map(function(x){return x.toLowerCase();})),n:d.count||0};cb();}).catch(function(){S={set:new Set(),low:new Set(),n:-1};cb();});}
function onchain(d,a,box){try{
  if(d.c==='BTC'){fetch('https://mempool.space/api/address/'+a).then(function(r){return r.json();}).then(function(x){var s=x.chain_stats||{};var bal=((s.funded_txo_sum||0)-(s.spent_txo_sum||0))/1e8;box.textContent=I.onchain+': '+I.tx+' '+(s.tx_count||0)+', '+I.bal+' '+bal.toFixed(8)+' BTC.';}).catch(function(){box.textContent=I.onchainFail;});}
  else if(d.c==='ETH'){fetch('https://eth.blockscout.com/api/v2/addresses/'+a).then(function(r){return r.json();}).then(function(x){var bal=x.coin_balance?(Number(x.coin_balance)/1e18).toFixed(6):'?';box.textContent=I.onchain+': '+I.bal+' '+bal+' ETH.';}).catch(function(){box.textContent=I.onchainFail;});}
  else{box.textContent='';}
}catch(e){box.textContent=I.onchainFail;}}
function check(){
  var a=(input.value||'').trim();if(!a){out.innerHTML='';return;}
  var d=det(a);
  if(!d){out.innerHTML='<div style="color:#ffcc33">'+esc(I.unrec)+'</div>';return;}
  load(function(){
    var bad=S.set.has(a)||S.low.has(a.toLowerCase());
    var h='<p>'+I.net+': <b>'+esc(d.c)+'</b></p>';
    if(S.n===-1)h+='<div style="color:#ffcc33">'+esc(I.listNA)+'</div>';
    else if(bad)h+='<div style="color:#ff5555;font-weight:700">'+esc(I.sanc)+'</div>';
    else h+='<div style="color:#55ff55;font-weight:700">'+esc(I.clean)+'</div>';
    if(d.e)h+='<p><a href="'+d.e+'" target="_blank" rel="nofollow noopener">'+esc(I.expl)+'</a></p>';
    h+='<div id="amlChain" class="updnote">'+esc(I.loading)+'</div>';
    out.innerHTML=h;onchain(d,a,document.getElementById('amlChain'));
  });
}
btn.addEventListener('click',check);
input.addEventListener('keydown',function(e){if(e.key==='Enter')check();});
"""


def geo_ref_script(elem_id, base):
    """Инлайн-скрипт (без внешних API): ссылке elem_id добавляет реф-метку ?p=REF (+rel sponsored)
    ТОЛЬКО для уверенно НЕ-российского часового пояса. РФ / неизвестно / JS off / бот → остаётся
    нейтральной (комплаенс-safe по умолчанию — рос. пользователи реф-ссылку не видят)."""
    return (
        '<script>(function(){try{'
        'var R=["Europe/Kaliningrad","Europe/Moscow","Europe/Simferopol","Europe/Kirov","Europe/Volgograd",'
        '"Europe/Astrakhan","Europe/Saratov","Europe/Ulyanovsk","Europe/Samara","Asia/Yekaterinburg","Asia/Omsk",'
        '"Asia/Novosibirsk","Asia/Barnaul","Asia/Tomsk","Asia/Novokuznetsk","Asia/Krasnoyarsk","Asia/Irkutsk",'
        '"Asia/Chita","Asia/Yakutsk","Asia/Khandyga","Asia/Vladivostok","Asia/Ust-Nera","Asia/Magadan",'
        '"Asia/Sakhalin","Asia/Srednekolymsk","Asia/Kamchatka","Asia/Anadyr"];'
        'var tz=(Intl.DateTimeFormat().resolvedOptions().timeZone)||"";'
        'var a=document.getElementById("' + elem_id + '");'
        'if(a&&tz&&R.indexOf(tz)===-1){a.href="' + base + '?p=' + str(REF) + '";a.rel="nofollow noopener sponsored";}'
        '}catch(e){}})();</script>')


def aml_checker(lang):
    """Клиентский AML-чек: валидация формата + санкционный список OFAC + базовые ончейн-данные. Честно, без скоринга."""
    ru = lang == "ru"
    cnt = 0
    try:
        cnt = json.load(open(os.path.join(ROOT, "aml-sanctions.json"), encoding="utf-8")).get("count", 0)
    except Exception:                              # noqa: BLE001
        cnt = 0
    i18n = {
        "ph": "Вставьте криптоадрес (BTC, ETH, TRON, LTC, XMR)" if ru else "Paste a crypto address (BTC, ETH, TRON, LTC, XMR)",
        "btn": "Проверить" if ru else "Check",
        "net": "Сеть" if ru else "Network",
        "unrec": ("Адрес не распознан. Поддерживаются BTC, ETH, TRON, LTC, XMR." if ru
                  else "Address not recognized. Supported: BTC, ETH, TRON, LTC, XMR."),
        "sanc": "⚠️ Адрес найден в санкционном списке OFAC" if ru else "⚠️ Address is in the OFAC sanctions list",
        "clean": "✅ В санкционном списке OFAC не найден" if ru else "✅ Not found in the OFAC sanctions list",
        "expl": "Посмотреть транзакции в эксплорере →" if ru else "View transactions in explorer →",
        "loading": "Загрузка ончейн-данных…" if ru else "Loading on-chain data…",
        "onchain": "Ончейн" if ru else "On-chain",
        "onchainFail": "Ончейн-данные недоступны — смотрите в эксплорере." if ru else "On-chain data unavailable — see the explorer.",
        "tx": "транзакций" if ru else "transactions",
        "bal": "баланс" if ru else "balance",
        "listNA": "Санкционный список сейчас недоступен — попробуйте позже." if ru else "Sanctions list unavailable now — try later.",
    }
    disc = ((f"Базовая проверка: формат адреса, санкционный список OFAC ({cnt} адресов, обновляется автоматически) "
             "и базовые ончейн-данные. Это НЕ полноценный AML-скоринг — миксеры, скам и даркнет не проверяются. "
             'Для <a id="amlFull" href="https://www.bestchange.ru/report/" target="_blank" rel="nofollow noopener">полной AML-проверки</a> '
             'воспользуйтесь специализированными сервисами. Результат справочный.') if ru else
            (f"Basic check: address format, OFAC sanctions list ({cnt} addresses, auto-updated) and basic on-chain "
             "data. This is NOT a full AML score — mixers, scams and darknet are not checked. "
             'For a <a id="amlFull" href="https://www.bestchange.ru/report/" target="_blank" rel="nofollow noopener">'
             'full AML check</a> use specialized services. For reference only.'))
    h = "Проверить адрес" if ru else "Check an address"
    form = (f'<h2 id="check">{h}</h2>'
            '<div class="amlbox" style="border:2px solid #55ffff;padding:14px;margin:10px 0;background:#001a1a">'
            f'<input id="amlAddr" type="text" autocomplete="off" spellcheck="false" placeholder="{i18n["ph"]}" '
            'style="width:100%;box-sizing:border-box;padding:9px;background:#000;color:#0f0;'
            'border:1px solid #55ffff;font-family:inherit">'
            f'<button id="amlBtn" type="button" style="margin-top:8px;padding:9px 18px;background:#0000aa;'
            f'color:#fff;border:1px solid #55ffff;cursor:pointer;font-family:inherit">{i18n["btn"]}</button>'
            '<div id="amlResult" style="margin-top:12px"></div>'
            f'<p class="updnote">{disc}</p></div>')
    # Гео-переключение реф-метки: HTML-ссылка нейтральная по умолчанию, ?p= только для не-РФ пояса.
    geo_js = geo_ref_script("amlFull", "https://www.bestchange.ru/report/")
    return form + "<script>(function(){var I=" + json.dumps(i18n, ensure_ascii=False) + ";" + _AML_JS + "})();</script>" + geo_js


def compliance_pages(lang):
    if lang == "ru":
        render_page(lang, "o-servise", "Что такое BestChange",
                    "BestChange — мониторинг обменных пунктов: справочная информация о курсах обмена криптовалют и валют.",
                    """<h1>Что такое BestChange</h1>
<p><b>BestChange</b> — мониторинг обменников электронных валют и криптовалют. Сервис собирает курсы, резервы и
   комиссии десятков обменных пунктов и показывает их значения в одном месте — не нужно обходить сайты вручную.</p>
<h2>Как это работает</h2>
<ol class="steps"><li>Выбираете направление обмена.</li><li>BestChange показывает обменники, отсортированные по курсу.</li>
<li>Смотрите курс, рейтинг, резерв и отзывы, выбираете подходящий пункт.</li><li>Переходите и проводите операцию на сайте обменника.</li></ol>
<h2>Про мониторинг</h2>
<p>В мониторинг попадают обменники с рейтингом и резервами. RateScout — независимый информационный сервис,
   который помогает сориентироваться и ведёт в BestChange к списку обменников. Сами обмен не проводим.</p>""",
                    "Что такое BestChange")
        render_page(lang, "aml", "AML-проверка криптоадреса — зачем и как",
                    "AML-проверка: как проверить криптоадрес на связь с мошенничеством и санкциями перед обменом.",
                    """<h1>AML-проверка криптоадреса</h1>
<p><b>AML</b> (Anti-Money Laundering) — проверка криптоадреса или транзакции на связь с мошенничеством, даркнетом,
   украденными средствами и санкциями. Снижает риск получить «грязные» монеты и блокировку на бирже.</p>
<h2>Когда делать</h2><ul><li>перед приёмом крупной суммы в крипте;</li><li>перед обменом крипты на рубли/наличные;</li>
<li>если контрагент незнаком.</li></ul>
<h2>Как проверить</h2>
<p>Полноценный AML-скоринг (миксеры, скам, даркнет) выполняют специализированные сервисы анализа блокчейна.
   Ниже — наша <b>базовая</b> проверка: формат адреса и официальный санкционный список OFAC.</p>
<p>Статус и детали конкретного перевода удобно проверять по его хэшу (TxID) в обозревателе сети — как это сделать,
   разобрано в статье <a href="/blog/kak-proverit-tranzakciyu-txid/">Как проверить транзакцию по TxID</a>.</p>""" + aml_checker(lang),
                    "AML-проверка")
        render_page(lang, "raskrytie", "Раскрытие информации и дисклеймеры",
                    "Партнёрское раскрытие и правовая информация RateScout.",
                    f"""<h1>Раскрытие информации и дисклеймеры</h1>
<h2>Партнёрское раскрытие</h2><p>RateScout — независимый информационный сервис. Ссылки ведут в BestChange; по
   партнёрской программе возможно вознаграждение. Это не реклама от имени BestChange. Отдельные сторонние сервисы
   могут быть помечены как «партнёрская ссылка» — по ним также возможно вознаграждение.</p>
<h2>Дисклеймер</h2><p>Информация справочная, не является финансовой/инвестиционной/юридической рекомендацией.
   Курсы меняются. Решение об обмене — самостоятельно и на свой риск. 18+.</p>
<h2>Соответствие законодательству</h2>
<ul><li><b>РФ:</b> сайт — информационный ресурс, активного продвижения не ведёт; маркировка рекламы (ERID/ОРД) не требуется. ПДн — по 152-ФЗ.</li>
<li><b>США:</b> affiliate-раскрытие по FTC; сервис недоступен под санкциями (OFAC).</li></ul>
<h2>Сведения о владельце сайта</h2>
<p>{S.get('owner_status','')} <b>{S.get('owner','')}</b>, ИНН {S.get('owner_inn','')}. Владелец не является
   обменным пунктом и не проводит операции. Контакт: {S.get('owner_email','')}.</p>
<h2>Официальные ресурсы</h2>
<p>Официальный блог сервиса: <a href="https://blogger.ratescout.info.gf/" target="_blank" rel="noopener me">blogger.ratescout.info.gf</a>.
   Telegram-канал: <a href="https://t.me/ratescout_kurs" target="_blank" rel="noopener me">t.me/ratescout_kurs</a>,
   ВКонтакте: <a href="https://vk.com/ratescout" target="_blank" rel="noopener me">vk.com/ratescout</a>,
   Mastodon: <a href="https://mastodon.social/@ratescout_ru" target="_blank" rel="noopener me">@ratescout_ru</a>.</p>"""
                    + donations_block(lang),
                    "Раскрытие")
        render_page(lang, "politika", "Политика конфиденциальности",
                    f"Политика обработки данных и cookie на сайте {S['domain']} (152-ФЗ).",
                    f"""<h1>Политика конфиденциальности</h1>
<p>Настоящая Политика описывает порядок обработки данных посетителей сайта {S['domain']}. Оператор:
   {S.get('owner_status','')} {S.get('owner','')}, ИНН {S.get('owner_inn','')}.</p>
<h2>Какие данные</h2><ul><li>технические данные браузера (IP, тип браузера/ОС, referer, дата/время);</li>
<li>обезличенная веб-аналитика;</li><li>cookie.</li></ul>
<h2>Аналитика</h2><p>Используются Яндекс.Метрика и Google Analytics (обезличенные данные). В составе Метрики —
   Вебвизор (запись действий на странице в обезличенном виде; поля с чувствительными данными маскируются).
   Cookie можно отключить в браузере.</p>
<h2>Права</h2><p>Запрос сведений, уточнение или удаление данных, отзыв согласия — на {S.get('owner_email','')}.
   Обработка — по 152-ФЗ. Актуальная редакция — на этой странице.</p>
<h2>Приложение автопубликации (соцсети, TikTok)</h2>
<p>Приложение RateScout публикует <b>собственный контент владельца</b> (сводки курсов, графики, видеообзоры) в
   подключённые владельцем аккаунты соцсетей через их официальные API. Оно использует доступ к аккаунту
   <b>исключительно</b> для публикации контента владельца и <b>не собирает, не хранит и не передаёт</b> персональные
   данные третьих лиц. Токены доступа хранятся в защищённых секретах и используются только для публикации; отозвать
   доступ можно в настройках соцсети в любой момент.</p>""",
                    "Политика")
        render_page(lang, "usloviya", "Условия использования",
                    f"Условия использования сайта {S['domain']} и приложения автопубликации RateScout.",
                    f"""<h1>Условия использования</h1>
<p>Используя сайт {S['domain']} и связанные приложения RateScout, вы принимаете настоящие Условия. Оператор:
   {S.get('owner_status','')} {S.get('owner','')}, ИНН {S.get('owner_inn','')}, контакт {S.get('owner_email','')}.</p>
<h2>Сервис</h2><p>RateScout — независимый информационный сервис мониторинга курсов. Данные справочные, не оферта и
   не финансовая/инвестиционная рекомендация. Решения об обмене — самостоятельно и на свой риск. 18+.</p>
<h2>Приложение автопубликации</h2><p>Приложение RateScout публикует <b>собственный контент владельца</b> (сводки
   курсов, графики, видеообзоры) в подключённые владельцем аккаунты социальных сетей (включая TikTok) через их
   официальные API. Доступ к аккаунту используется <b>только</b> для публикации контента, предоставленного владельцем;
   персональные данные третьих лиц не собираются и не передаются. Доступ можно отозвать в настройках соцсети в любой момент.</p>
<h2>Допустимое использование</h2><ul><li>соблюдать правила соцсетей и законодательство;</li>
   <li>не использовать сервис для спама, обмана или незаконных операций.</li></ul>
<h2>Ответственность</h2><p>Сервис предоставляется «как есть», без гарантий бесперебойности и точности. Владелец не несёт
   ответственности за решения, принятые на основе справочных данных.</p>
<h2>Изменения</h2><p>Актуальная редакция Условий — на этой странице. Вопросы: {S.get('owner_email','')}.</p>""",
                    "Условия")
    else:
        render_page(lang, "o-servise", "What is BestChange",
                    "BestChange — an exchange office monitor: reference information about crypto and currency exchange rates.",
                    """<h1>What is BestChange</h1>
<p><b>BestChange</b> is a monitor of e-currency and crypto exchange offices. It collects rates, reserves and
   fees from dozens of offices and shows them in one place — no need to check each site manually.</p>
<h2>How it works</h2>
<ol class="steps"><li>Choose an exchange direction.</li><li>BestChange shows exchangers sorted by rate.</li>
<li>Check rate, rating, reserve and reviews, pick a suitable office.</li><li>Go and complete the operation on the exchanger's site.</li></ol>
<h2>About the monitor</h2>
<p>Exchangers with ratings and reserves are listed. RateScout is an independent information service that helps you
   navigate and leads to the BestChange exchanger list. We do not process exchanges ourselves.</p>""",
                    "What is BestChange")
        render_page(lang, "earn", "Earn with BestChange — affiliate program for webmasters",
                    "Monetize crypto and finance traffic with the BestChange affiliate program: commission from "
                    "exchanges plus a share from referred webmasters. How to join.",
                    """<h1>Earn with BestChange</h1>
<p class="answer">BestChange runs an affiliate program: you earn a commission from every exchange made by users who
   follow your links, plus a share of the earnings of webmasters you refer (two-tier). Payouts in crypto and e-currencies.</p>
<h2>How it works</h2>
<ol class="steps"><li>Register in the BestChange affiliate program.</li>
<li>Place BestChange links or widgets on your site, blog or channel.</li>
<li>Earn a commission from every exchange made through your links.</li>
<li>Invite other webmasters and get a share of their earnings too.</li></ol>
<h2>Who it suits</h2>
<ul><li>owners of finance and crypto sites, blogs and Telegram channels;</li>
<li>traffic and arbitrage specialists;</li>
<li>anyone with an audience interested in crypto and currency exchange.</li></ul>
<h2>Join the program</h2>
<p><a id="bcPartner" class="cta" href="https://www.bestchange.ru/partner/" target="_blank" rel="nofollow noopener">Join the BestChange affiliate program &rarr;</a></p>
<p class="updnote">RateScout is an independent information service and a BestChange affiliate. The button leads to the
   official BestChange affiliate program. For reference only; not a job offer or financial advice.</p>"""
                    + geo_ref_script("bcPartner", "https://www.bestchange.ru/partner/"),
                    "Earn with BestChange")
        render_page(lang, "aml", "Crypto address AML check — why and how",
                    "AML check: how to verify a crypto address for links to fraud and sanctions before exchanging.",
                    """<h1>Crypto address AML check</h1>
<p><b>AML</b> (Anti-Money Laundering) is a check of a crypto address or transaction for links to fraud, darknet,
   stolen funds and sanctions. It reduces the risk of receiving "dirty" coins and getting funds frozen.</p>
<h2>When to do it</h2><ul><li>before receiving a large crypto amount;</li><li>before exchanging crypto to cash/bank;</li>
<li>if the counterparty is unknown.</li></ul>
<h2>How to check</h2>
<p>A full AML score (mixers, scams, darknet) is done by specialized blockchain analysis services. Below is our
   <b>basic</b> check: address format and the official OFAC sanctions list.</p>""" + aml_checker(lang),
                    "AML check")
        render_page(lang, "raskrytie", "Disclosure and disclaimers",
                    "Affiliate disclosure and legal information of RateScout.",
                    f"""<h1>Disclosure and disclaimers</h1>
<h2>Affiliate disclosure</h2><p>RateScout is an independent information service. Links lead to BestChange; through
   the affiliate program we may earn a commission. This is not advertising on behalf of BestChange (FTC disclosure).
   Some third-party services may be marked as an "affiliate link" — we may also earn a commission from those.</p>
<h2>Disclaimer</h2><p>Information is for reference and is not financial, investment or legal advice. Rates change.
   You decide to exchange on your own and at your own risk. 18+.</p>
<h2>Legal</h2><ul><li><b>US:</b> FTC affiliate disclosure; the service is unavailable to sanctioned persons/territories (OFAC).</li>
<li><b>RU:</b> informational resource; no active promotion.</li></ul>
<h2>Site owner</h2>
<p><b>{S.get('owner','')}</b> (self-employed, RU tax ID {S.get('owner_inn','')}). The owner is not an exchange
   office and does not process transactions. Contact: {S.get('owner_email','')}.</p>
<h2>Official resources</h2>
<p>Official service blog: <a href="https://blogger.ratescout.info.gf/" target="_blank" rel="noopener me">blogger.ratescout.info.gf</a>.
   Telegram channel: <a href="https://t.me/ratescout_kurs" target="_blank" rel="noopener me">t.me/ratescout_kurs</a>,
   VK: <a href="https://vk.com/ratescout" target="_blank" rel="noopener me">vk.com/ratescout</a>,
   Mastodon: <a href="https://mastodon.social/@ratescout_ru" target="_blank" rel="noopener me">@ratescout_ru</a>.</p>"""
                    + donations_block(lang),
                    "Disclosure")
        render_page(lang, "politika", "Privacy policy",
                    f"Data and cookie processing policy on {S['domain']}.",
                    f"""<h1>Privacy policy</h1>
<p>This policy describes how visitor data is processed on {S['domain']}. Operator: {S.get('owner','')}
   (self-employed, RU tax ID {S.get('owner_inn','')}).</p>
<h2>What data</h2><ul><li>technical browser data (IP, browser/OS, referer, date/time);</li>
<li>anonymised web analytics;</li><li>cookies.</li></ul>
<h2>Analytics</h2><p>Yandex.Metrica and Google Analytics are used (anonymised data). Metrica includes Webvisor
   (records on-page actions anonymously; fields with sensitive data are masked). Cookies can be disabled in the browser.</p>
<h2>Rights</h2><p>To request, correct or delete data, or withdraw consent — email {S.get('owner_email','')}.
   The current version is on this page.</p>
<h2>Auto-publishing app (social networks, TikTok)</h2>
<p>The RateScout application publishes the <b>owner's own content</b> (rate digests, charts, video reviews) to social
   accounts connected by the owner via their official APIs. It uses account access <b>solely</b> to publish the owner's
   content and <b>does not collect, store or share</b> personal data of third parties. Access tokens are kept in secure
   secrets and used only for publishing; access can be revoked anytime in the social network's settings.</p>""",
                    "Privacy")
        render_page(lang, "usloviya", "Terms of Service",
                    f"Terms of Service for {S['domain']} and the RateScout auto-publishing app.",
                    f"""<h1>Terms of Service</h1>
<p>By using {S['domain']} and related RateScout applications you accept these Terms. Operator: {S.get('owner','')}
   (self-employed, RU tax ID {S.get('owner_inn','')}), contact {S.get('owner_email','')}.</p>
<h2>Service</h2><p>RateScout is an independent exchange-rate monitoring service. Information is for reference only, not an
   offer and not financial or investment advice. You decide to exchange on your own and at your own risk. 18+.</p>
<h2>Auto-publishing app</h2><p>The RateScout application publishes the <b>owner's own content</b> (rate digests, charts,
   video reviews) to social accounts connected by the owner (including TikTok) via their official APIs. Account access is
   used <b>only</b> to publish content provided by the owner; personal data of third parties is not collected or shared.
   Access can be revoked at any time in the respective social network's settings.</p>
<h2>Acceptable use</h2><ul><li>comply with the social networks' rules and applicable law;</li>
   <li>do not use the service for spam, fraud or illegal operations.</li></ul>
<h2>Liability</h2><p>The service is provided "as is", without warranties of availability or accuracy. The owner is not
   liable for decisions made on the basis of reference data.</p>
<h2>Changes</h2><p>The current version of the Terms is on this page. Questions: {S.get('owner_email','')}.</p>""",
                    "Terms")


def build_catalog_js():
    cur = {slug: {"n": i["name"], "t": i["ticker"], "c": i["category"]} for slug, i in CUR.items()}
    return "window.__CATALOG__=" + json.dumps({"order": CATS, "cur": cur}, ensure_ascii=False) + \
           ";window.__REF__=" + json.dumps(REF) + ";"


def write_catalog_js(js):
    open(os.path.join(DIST, "assets", "catalog.js"), "w", encoding="utf-8").write(js)


MINIAPP_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>RateScout — курсы и конвертер</title>
<meta name="robots" content="noindex">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#0b0b0b;--fg:#eaeaea;--mut:#8a8a8a;--acc:#33cc33;--card:#141414;--bd:#264026}
*{box-sizing:border-box}
body{margin:0;padding:14px;font:16px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;
 background:var(--tg-theme-bg-color,var(--bg));color:var(--tg-theme-text-color,var(--fg))}
h1{font-size:20px;margin:4px 0 2px}
.mut{color:var(--tg-theme-hint-color,var(--mut));font-size:13px;margin:0 0 14px}
.card{background:var(--tg-theme-secondary-bg-color,var(--card));border:1px solid var(--bd);
 border-radius:12px;padding:14px;margin-bottom:12px}
label{display:block;font-size:12px;color:var(--mut);margin:8px 0 4px}
input,select{width:100%;padding:11px;border-radius:9px;border:1px solid var(--bd);
 background:var(--tg-theme-bg-color,#000);color:var(--tg-theme-text-color,var(--fg));font-size:16px}
.row{display:flex;gap:8px}.row>*{flex:1}
.swap{margin:8px 0;width:100%;padding:9px;border:1px solid var(--bd);border-radius:9px;
 background:transparent;color:var(--acc);font-size:14px;cursor:pointer}
.res{font-size:22px;font-weight:700;margin-top:12px;color:var(--acc)}
.res small{display:block;color:var(--mut);font-size:12px;font-weight:400;margin-top:2px}
.links{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.links a{display:block;text-align:center;padding:12px;border-radius:10px;text-decoration:none;
 background:var(--tg-theme-button-color,var(--acc));color:var(--tg-theme-button-text-color,#001500);font-weight:600;font-size:14px}
.links a.sec{background:transparent;border:1px solid var(--bd);color:var(--tg-theme-text-color,var(--fg))}
.foot{color:var(--mut);font-size:11px;text-align:center;margin-top:14px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{background:var(--tg-theme-bg-color,#000);border:1px solid var(--bd);border-radius:20px;
 padding:5px 10px;font-size:13px;cursor:pointer}
.chip b{color:var(--mut);margin-left:6px;font-weight:400}
.results{list-style:none;margin:8px 0 0;padding:0}
.results li{display:flex;align-items:center;gap:6px;padding:9px 4px;border-top:1px solid var(--bd);cursor:pointer}
.results li span{color:var(--mut);font-size:12px}
.results li b{margin-left:auto;font-weight:700}
.results li b.up{color:#3c3}.results li b.dn{color:#e55}
.mut2{color:var(--mut);border:0!important;cursor:default}
.tabs{display:flex;gap:8px;margin-bottom:4px}
.tabs button{flex:1;padding:9px;border:1px solid var(--bd);border-radius:9px;background:transparent;
 color:var(--tg-theme-text-color,var(--fg));font-size:13px;cursor:pointer}
.tabs button.on{background:var(--acc);color:#001500;border-color:var(--acc);font-weight:700}
</style>
</head>
<body>
<h1>RateScout</h1>
<p class="mut">Курсы обмена и конвертер · данные мониторинга BestChange</p>

<div class="card">
  <label>Сумма</label>
  <input id="amt" type="number" inputmode="decimal" value="1" min="0">
  <div class="row">
    <div><label>Отдаёте</label><select id="from"></select></div>
    <div><label>Получаете</label><select id="to"></select></div>
  </div>
  <div class="row">
    <button class="swap" id="swap">⇅ поменять</button>
    <button class="swap" id="fav">☆ в избранное</button>
  </div>
  <div class="res" id="res">—</div>
  <div class="chips" id="favs"></div>
</div>

<div class="card">
  <label>Поиск валюты</label>
  <input id="q" type="search" placeholder="BTC, USDT, Sberbank…" autocomplete="off">
  <ul class="results" id="qres"></ul>
</div>

<div class="card">
  <div class="tabs"><button id="tg-up" class="on">▲ Рост за сутки</button><button id="tg-dn">▼ Падение</button></div>
  <ul class="results" id="movers"></ul>
</div>

<div class="links">
  <a href="{{BASE}}/obzor/sutki/" data-ext>📊 Обзор за сутки</a>
  <a href="{{BASE}}/grafiki/" data-ext>📈 Графики</a>
  <a href="{{BASE}}/svodka/" class="sec" data-ext>🧭 Сводка</a>
  <a href="{{BASE}}/" class="sec" data-ext>💱 Все курсы</a>
</div>
<p class="foot">Справочный сервис (мониторинг курсов), не обменный пункт. Курсы меняются.</p>

<script>
var BASE='{{BASE}}';
var tg=window.Telegram&&window.Telegram.WebApp;
if(tg){try{tg.ready();tg.expand();}catch(e){}}
function open_(url){ if(tg&&tg.openLink){tg.openLink(url);}else{location.href=url;} }
document.querySelectorAll('a[data-ext]').forEach(function(a){
  a.addEventListener('click',function(ev){ev.preventDefault();open_(a.href);});
});
function openCur(s){ open_(BASE+'/valuta/'+s+'/'); }
var CUR={},KS=[],A=document.getElementById('amt'),F=document.getElementById('from'),T=document.getElementById('to'),R=document.getElementById('res');
function fmt(v){if(!isFinite(v))return '—';
 if(v>=1000)return v.toLocaleString('ru-RU',{maximumFractionDigits:0});
 if(v>=1)return v.toLocaleString('ru-RU',{maximumFractionDigits:2});
 if(v>=0.0001)return (+v.toFixed(6)).toString();
 return v.toFixed(12).replace(/0+$/,'').replace(/\\.$/,'')||'0';}
function calc(){var f=CUR[F.value],t=CUR[T.value],a=parseFloat(A.value);
 if(!f||!t||!(a>=0)){R.textContent='—';return;}
 var r=f.p/t.p;R.innerHTML=fmt(a*r)+' '+t.t+'<small>1 '+f.t+' = '+fmt(r)+' '+t.t+'</small>';}
[A,F,T].forEach(function(el){el.addEventListener('input',calc);el.addEventListener('change',calc);});
document.getElementById('swap').addEventListener('click',function(){var x=F.value;F.value=T.value;T.value=x;calc();});
// избранные пары (localStorage)
function favLoad(){try{return JSON.parse(localStorage.getItem('rs_fav')||'[]');}catch(e){return [];}}
function favSave(a){try{localStorage.setItem('rs_fav',JSON.stringify(a.slice(0,8)));}catch(e){}}
function favRender(){var a=favLoad(),el=document.getElementById('favs');
 el.innerHTML=a.map(function(p,i){var f=CUR[p.f],t=CUR[p.t];if(!f||!t)return '';
  return '<span class="chip" data-i="'+i+'">'+f.t+'→'+t.t+'<b data-x="'+i+'">×</b></span>';}).join('');
 el.querySelectorAll('.chip').forEach(function(c){c.addEventListener('click',function(ev){
   var a=favLoad();if(ev.target.hasAttribute('data-x')){a.splice(+ev.target.getAttribute('data-x'),1);favSave(a);favRender();return;}
   var p=a[+c.getAttribute('data-i')];F.value=p.f;T.value=p.t;calc();});});}
document.getElementById('fav').addEventListener('click',function(){var a=favLoad();
 if(!a.some(function(p){return p.f===F.value&&p.t===T.value;})){a.unshift({f:F.value,t:T.value});favSave(a);favRender();}});
// поиск валют
var Q=document.getElementById('q'),QR=document.getElementById('qres');
Q.addEventListener('input',function(){var v=Q.value.trim().toLowerCase();
 if(!v){QR.innerHTML='';return;}
 var hits=KS.filter(function(s){var c=CUR[s];return c.n.toLowerCase().indexOf(v)>=0||c.t.toLowerCase().indexOf(v)>=0||s.indexOf(v)>=0;}).slice(0,12);
 QR.innerHTML=hits.map(function(s){return '<li data-s="'+s+'">'+CUR[s].n+' <span>'+CUR[s].t+'</span></li>';}).join('');
 QR.querySelectorAll('li').forEach(function(li){li.addEventListener('click',function(){openCur(li.getAttribute('data-s'));});});});
// топ за сутки
function movers(up){var arr=KS.filter(function(s){return CUR[s].c==='kriptovalyuty'&&typeof CUR[s].g==='number';})
  .sort(function(a,b){return up?CUR[b].g-CUR[a].g:CUR[a].g-CUR[b].g;}).slice(0,7);
 var el=document.getElementById('movers');
 if(!arr.length){el.innerHTML='<li class="mut2">Данные накапливаются</li>';return;}
 el.innerHTML=arr.map(function(s){var g=CUR[s].g,c=g>=0?'up':'dn';
  return '<li data-s="'+s+'">'+CUR[s].n+' <span>'+CUR[s].t+'</span><b class="'+c+'">'+(g>=0?'+':'')+g+'%</b></li>';}).join('');
 el.querySelectorAll('li[data-s]').forEach(function(li){li.addEventListener('click',function(){openCur(li.getAttribute('data-s'));});});}
document.getElementById('tg-up').addEventListener('click',function(){this.classList.add('on');document.getElementById('tg-dn').classList.remove('on');movers(true);});
document.getElementById('tg-dn').addEventListener('click',function(){this.classList.add('on');document.getElementById('tg-up').classList.remove('on');movers(false);});
fetch(BASE+'/prices.json').then(function(r){return r.json();}).then(function(j){
 CUR=j.cur;KS=Object.keys(CUR).sort(function(a,b){return CUR[a].n.localeCompare(CUR[b].n);});
 var opt=KS.map(function(s){return '<option value="'+s+'">'+CUR[s].n+' ('+CUR[s].t+')</option>';}).join('');
 F.innerHTML=opt;T.innerHTML=opt;
 F.value=CUR['bitcoin']?'bitcoin':KS[0];
 T.value=CUR['sberbank']?'sberbank':(CUR['tether-trc20']?'tether-trc20':KS[1]);
 calc();favRender();movers(true);
}).catch(function(){R.textContent='Не удалось загрузить курсы';});
</script>
</body></html>"""


def render_miniapp():
    """Telegram Mini App — статичная страница /app/ (конвертер по prices.json + ссылки, тема Telegram)."""
    d = os.path.join(DIST, "app")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(MINIAPP_HTML.replace("{{BASE}}", BASE_URL))


def render_404():
    """Своя 404 (GitHub Pages отдаёт /404.html при отсутствии страницы). Пути абсолютные."""
    lang = "ru"
    pop = ["bitcoin", "tether-trc20", "ethereum", "litecoin", "tron"]
    pop_li = "".join(f'<li><a href="{cpage(lang, s)}">{CUR[s]["name"]} <span>{CUR[s]["ticker"]}</span></a></li>'
                     for s in pop if s in CUR)
    body = f"""{header(lang, "/404")}
<div id="main">
  <div id="content" style="float:none;width:100%">
    <h1>404 — страница не найдена</h1>
    <div class="dosblue dosborder">Похоже, такой страницы нет или она переехала. Ниже — куда пойти дальше.
      <br><span style="color:#cfe">Page not found — see the links below or go to the
      <a href="/en/">English version</a>.</span></div>
    <h2 class="news">Куда пойти</h2>
    <ul class="dlist">
      <li><a href="/">Главная — каталог курсов</a></li>
      <li><a href="/blog/">Блог — гайды по обмену</a></li>
      <li><a href="/faq/">Частые вопросы</a></li>
      <li><a href="/kategoriya/kriptovalyuty/">Все криптовалюты</a></li>
      <li><a href="/na/sberbank/">Обмен крипты на Сбербанк</a></li>
      <li><a href="/o-servise/">Что такое BestChange</a></li>
    </ul>
    <h2 class="news">Популярные валюты</h2>
    <ul class="dlist">{pop_li}</ul>
  </div>
</div>
{footer(lang)}"""
    html = head(lang, f"404 — страница не найдена | {S['name']}", "Страница не найдена.", "/404") + body
    open(os.path.join(DIST, "404.html"), "w", encoding="utf-8").write(html)


def static_files():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # lastmod: курсовые (hourly) страницы получают ТОЧНЫЙ момент обновления курсов (W3C datetime) —
    # честный сигнал свежести, меняется при смене данных; статике — дата (без ежечасной «болтанки»).
    lm_live = (datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
               if RATES_GENERATED else today)

    def u_entry(loc, freq, pri):
        lm = lm_live if freq == "hourly" else today
        return (f"  <url><loc>{BASE_URL}{loc}</loc><lastmod>{lm}</lastmod>"
                f"<changefreq>{freq}</changefreq><priority>{pri}</priority></url>")

    items = []
    for lg in LANGS:
        pr = PREF[lg]
        items.append(u_entry(pr + "/", "hourly", "1.0" if lg == "ru" else "0.9"))
        items += [u_entry(pr + f"/valuta/{s}/", "hourly", "0.6") for s in CUR]
        items += [u_entry(pr + f"/kupit/{s}/", "hourly", "0.6") for s in CUR]
        items += [u_entry(pr + f"/obmen/{p['from']}-{p['to']}/", "hourly", "0.8") for p in PAIR_PAGES]
        if lg == "ru":
            items += [u_entry(pr + f"/obmen/{p['from']}-{p['to']}/", "daily", "0.4") for p in PAIR_PAGES_RU]
        if ARTS[lg]:
            items.append(u_entry(pr + "/blog/", "weekly", "0.7"))
            _bpages = (len(ARTS[lg]) + BLOG_PER_PAGE - 1) // BLOG_PER_PAGE
            items += [u_entry(pr + f"/blog/page/{p}/", "weekly", "0.5") for p in range(2, _bpages + 1)]
            items += [u_entry(pr + f"/blog/{a['slug']}/", "monthly", "0.6") for a in ARTS[lg]]
        items += [u_entry(pr + f"/kategoriya/{CAT_SLUG[c]}/", "weekly", "0.7") for c in CATS]
        items += [u_entry(pr + f"/na/{b}/", "hourly", "0.8") for b in BANK_HUBS]
        items.append(u_entry(pr + "/faq/", "monthly", "0.6"))
        items.append(u_entry(pr + "/kniga/", "monthly", "0.5"))
        items.append(u_entry(pr + "/vidzhet/", "monthly", "0.5"))
        items.append(u_entry(pr + "/grafiki/", "hourly", "0.7"))
        items.append(u_entry(pr + "/heatmap/", "hourly", "0.7"))
        items.append(u_entry(pr + "/populyarnost/", "daily", "0.6"))
        items.append(u_entry(pr + "/monitor/", "hourly", "0.7"))
        items.append(u_entry(pr + "/tsepochki/", "hourly", "0.7"))
        items.append(u_entry(pr + "/alert/", "hourly", "0.6"))
        items.append(u_entry(pr + "/kursy/", "hourly", "0.6"))
        items.append(u_entry(pr + "/napravleniya/", "hourly", "0.7"))
        items.append(u_entry(pr + "/obzor/sutki/", "hourly", "0.6"))
        items.append(u_entry(pr + "/obzor/nedelya/", "daily", "0.6"))
        items.append(u_entry(pr + "/obzor/mesyac/", "weekly", "0.6"))
        items.append(u_entry(pr + "/svodka/", "hourly", "0.6"))
        items.append(u_entry(pr + "/lidery-rynka/", "hourly", "0.6"))
        items.append(u_entry(pr + "/koshelki/", "monthly", "0.5"))
        items.append(u_entry(pr + "/stablecoins/", "hourly", "0.6"))
        items.append(u_entry(pr + "/sravnenie/", "weekly", "0.6"))
        items.append(u_entry(pr + "/nastroeniya/", "daily", "0.6"))
        items.append(u_entry(pr + "/halving/", "daily", "0.6"))
        items += [u_entry(pr + f"/sravnenie/{_a}-vs-{_b}/", "daily", "0.5") for _a, _b in compare_pairs()]
        if GLOSSARY:
            items.append(u_entry(pr + "/slovar/", "weekly", "0.6"))
            items += [u_entry(pr + f"/slovar/{t['slug']}/", "monthly", "0.5") for t in GLOSSARY]
        items += [u_entry(pr + f"/{u}/", "monthly", "0.4") for u in ("o-servise", "aml", "raskrytie", "politika", "usloviya", "redakciya")]
        if lg == "en":
            items.append(u_entry(pr + "/earn/", "monthly", "0.5"))  # EN-only: партнёрка BestChange для не-РФ
    open(os.path.join(DIST, "sitemap.xml"), "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(items) + "\n</urlset>")
    # AI / answer-engine краулеры разрешаем ЯВНО (сигнал намерения для GEO): каждый именованный
    # user-agent читает только свой блок, поэтому дублируем Allow: / для каждого.
    _ai_bots = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-Web", "anthropic-ai",
                "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended",
                "CCBot", "Amazonbot", "Bytespider", "YandexAdditional"]
    _robots = "User-agent: *\nAllow: /\n\n# AI / answer engines\n"
    _robots += "".join(f"User-agent: {b}\nAllow: /\n\n" for b in _ai_bots)
    _robots += f"Sitemap: {BASE_URL}/sitemap.xml\n# LLM guidance: {BASE_URL}/llms.txt\n"
    open(os.path.join(DIST, "robots.txt"), "w", encoding="utf-8").write(_robots)
    open(os.path.join(DIST, "CNAME"), "w", encoding="utf-8").write(S["domain"] + "\n")
    open(os.path.join(DIST, "manifest.webmanifest"), "w", encoding="utf-8").write(json.dumps({
        "name": S["name"] + " — мониторинг курсов обмена", "short_name": S["name"],
        "description": S["tagline"], "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#111111", "theme_color": "#111111", "lang": "ru",
        "icons": [{"src": "/assets/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}]
    }, ensure_ascii=False, indent=2))
    open(os.path.join(DIST, "sw.js"), "w", encoding="utf-8").write(
        "const C='ratescout-v3';\n"
        "self.addEventListener('install',e=>self.skipWaiting());\n"
        # при активации новой версии — стереть старые кеши (иначе отдаются устаревшие страницы)
        "self.addEventListener('activate',e=>e.waitUntil("
        "caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k))))"
        ".then(()=>self.clients.claim())));\n"
        "self.addEventListener('fetch',e=>{const q=e.request;"
        # HTML-страницы (навигация) — ТОЛЬКО свежая сеть, кеш лишь как офлайн-запас; не храним устаревший HTML
        "if(q.mode==='navigate'||(q.headers.get('accept')||'').includes('text/html')){"
        "e.respondWith(fetch(q).catch(()=>caches.match(q)));return;}"
        # статика (css/js/данные, версионируются через ?v=hash) — сеть с обновлением кеша, офлайн-фолбэк
        "e.respondWith(fetch(q).then(r=>{const c=r.clone();caches.open(C).then(x=>x.put(q,c));return r})"
        ".catch(()=>caches.match(q)));});")
    open(os.path.join(DIST, ".nojekyll"), "w").write("")
    # карта покрытия направлений для конвертера: какие /obmen/ существуют (RU — все, EN — только 714).
    json.dump({"p": [f"{a}-{b}" for a, b in PAIR_SET_ALL]},
              open(os.path.join(DIST, "pairs.json"), "w"), separators=(",", ":"))
    os.makedirs(os.path.join(DIST, "en"), exist_ok=True)
    json.dump({"p": [f"{a}-{b}" for a, b in PAIR_SET]},
              open(os.path.join(DIST, "en", "pairs.json"), "w"), separators=(",", ":"))
    # IndexNow: ключ-файл (публичный, не секрет) для мгновенной переиндексации Яндекс/Bing
    open(os.path.join(DIST, INDEXNOW_KEY + ".txt"), "w").write(INDEXNOW_KEY)
    # санкционный список OFAC для клиентского AML-чека (ephemeral; кладём в dist, чтобы браузер мог фетчить)
    _amlp = os.path.join(ROOT, "aml-sanctions.json")
    if os.path.exists(_amlp):
        shutil.copy(_amlp, os.path.join(DIST, "aml-sanctions.json"))
    write_llms()
    write_widget()
    write_prices()


def write_prices():
    """prices.json — цена каждой валюты в USDT (для страницы относительных/кросс-курсов)."""
    m = {}
    for slug, info in CUR.items():
        if slug == "tether-trc20":
            continue
        p, _ = _usdt_price(slug)
        if p is not None:
            e = {"n": info["name"], "t": info["ticker"], "c": CAT_SLUG.get(info["category"], "prochee"), "p": p}
            g = CHG_BY.get(slug, {}).get("24h")     # изм. за 24ч (для «топ за сутки» в мини-аппе)
            if g is not None and abs(g) <= 300:
                e["g"] = round(g, 1)
            m[slug] = e
    ut = CUR.get("tether-trc20")
    if ut:
        m["tether-trc20"] = {"n": ut["name"], "t": ut["ticker"], "c": CAT_SLUG.get(ut["category"], "prochee"), "p": 1.0}
    open(os.path.join(DIST, "prices.json"), "w", encoding="utf-8").write(
        json.dumps({"cur": m}, ensure_ascii=False, separators=(",", ":")))




def write_llms():
    """llms.txt (llmstxt.org) — карта сайта для AI-систем/ответных движков."""
    B = BASE_URL
    pop = [s for s in ["bitcoin", "tether-trc20", "ethereum", "tether-erc20", "tether-bep20",
                       "litecoin", "monero", "tron", "usdcoin", "tether-ton"] if s in CUR]
    lines = [
        f"# {S['name']} — справочник курсов обмена криптовалют и валют",
        "",
        f"> Независимый справочник курсов обмена криптовалют и валют по данным мониторинга обменных пунктов "
        f"BestChange. Не обменный пункт: данные справочные, курсы обновляются ежечасно. Языки: RU ({B}/) и EN ({B}/en/).",
        "",
        "## Основные разделы",
        f"- [Главная — каталог курсов]({B}/): {len(CUR)} валют по категориям, живые курсы и калькулятор.",
        f"- [Частые вопросы (FAQ)]({B}/faq/): сети USDT, комиссии, AML, резерв, СБП, обменник vs биржа.",
        f"- [О редакции]({B}/redakciya/): кто ведёт сайт, источники данных, обновление, контакты.",
        f"- [Что такое BestChange]({B}/o-servise/): как устроен мониторинг обменников.",
        f"- [AML-проверка криптоадреса]({B}/aml/): зачем и как.",
        "",
        "## Категории валют",
    ]
    for c in CATS:
        n = len(GROUPED.get(c, []))
        if n:
            lines.append(f"- [{cat_name(c,'ru')}]({B}/kategoriya/{CAT_SLUG[c]}/): {n} направлений.")
    lines += ["", "## Популярные валюты"]
    for s in pop:
        lines.append(f"- [{CUR[s]['name']} ({CUR[s]['ticker']})]({B}/valuta/{s}/)")
    lines += ["", "## Обмен крипты на банки/получателей"]
    for b in BANK_HUBS:
        lines.append(f"- [Обмен криптовалюты на {CUR[b]['name']}]({B}/na/{b}/)")
    lines += ["", "## Блог (гайды)"]
    for a in ARTS["ru"]:
        lines.append(f"- [{a['title']}]({B}/blog/{a['slug']}/): {a.get('description','')}")
    lines += ["", "## Данные и фиды",
              f"- Sitemap: {B}/sitemap.xml",
              f"- RSS блога: {B}/blog/rss.xml",
              f"- Английская версия: {B}/en/", ""]
    open(os.path.join(DIST, "llms.txt"), "w", encoding="utf-8").write("\n".join(lines))


def write_widget():
    """Встраиваемый виджет курсов: widget-data.json (данные) + widget.js (скрипт для чужих сайтов)."""
    pairs = {}
    for key, f, t, df, dt, url in WIDGET_PAIRS:
        r = rate_of(f, t)
        if r:
            pairs[key] = {"from": df, "to": dt, "rate": fmt_rate(r["rate"]), "url": BASE_URL + url}
    data = {"updated": updated_str("en").replace("Updated: ", ""), "base": BASE_URL, "pairs": pairs}
    open(os.path.join(DIST, "widget-data.json"), "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False))
    src = open(os.path.join(ROOT, "widget.src.js"), encoding="utf-8").read()
    open(os.path.join(DIST, "widget.js"), "w", encoding="utf-8").write(src.replace("{{BASE}}", BASE_URL))
    # полная карта курсов для режима «любая пара»/конвертер (тянется только когда нужно)
    nested = {}
    for k, v in RATES.items():
        f, t = k.split(">", 1)
        if f in CUR and t in CUR:
            nested.setdefault(f, {})[t] = v["rate"]
    curmap = {s: {"n": i["name"], "t": i["ticker"]} for s, i in CUR.items()}
    open(os.path.join(DIST, "widget-rates.json"), "w", encoding="utf-8").write(
        json.dumps({"updated": data["updated"], "cur": curmap, "rates": nested},
                   ensure_ascii=False, separators=(",", ":")))


def copy_assets():
    dst = os.path.join(DIST, "assets")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(os.path.join(ROOT, "assets"), dst)
    # файлы книги (DOCX) — для страниц /kniga/ и /en/kniga/
    _bk = os.path.join(ROOT, "book")
    if os.path.isdir(_bk):
        _bd = os.path.join(DIST, "book")
        if os.path.isdir(_bd):
            shutil.rmtree(_bd)
        shutil.copytree(_bk, _bd)


def compute_chains():
    """Цепочки обмена (арбитраж) по данным BestChange: 2/3/4 звена A→…→A.
    Берём только ЛИКВИДНЫЕ леги (≥MINC обменников, резерв>0) и с курсом в пределах 0.66..1.5× справедливого
    (по цене валют в USDT) — иначе это битые/устаревшие данные, дающие фейковую «доходность». Дедуп по набору
    ТИКЕРОВ (варианты USDT-erc20/trc20/bep20 не плодим). Доходность = произведение курсов−1 (%). Риск% —
    эвристика: длиннее цепочка + меньше обменников + «слишком красивый» профит = выше риск (окно закроется быстрее)."""
    empty = {"2": [], "3": [], "4": [], "generated": RATES_GENERATED}
    if not RATES:
        return empty
    MINC = 5        # минимум обменников на КАЖДОМ шаге (консервативно: меньше «бумажных» окон)
    MAXRISK = 70    # цепочки с риском выше — не показываем (слишком ненадёжно)
    usd = {s: (h[-1][1] if h else None) for s, h in HISTORY.items()}
    R = {}                                   # R[a][b] = (rate, count) — только ликвидные/санитарные леги
    for k, v in RATES.items():
        if ">" not in k:
            continue
        a, b = k.split(">", 1)
        try:
            rate = float(v["rate"])
        except (ValueError, KeyError, TypeError):
            continue
        if rate <= 0:
            continue
        cnt = int(v.get("count", 0) or 0)
        if cnt < MINC or float(v.get("reserve", 0) or 0) <= 0:
            continue
        pa, pb = usd.get(a), usd.get(b)
        if pa and pb and pb > 0:             # сверка с USDT-справедливым курсом
            f = pa / pb
            if rate > f * 1.5 or rate < f * 0.66:
                continue
        R.setdefault(a, {})[b] = (rate, cnt)
    tkf = lambda s: (CUR.get(s, {}).get("ticker") or s)
    deg = sorted(R, key=lambda n: -len(R[n]))

    def risk(legs, minc, prof):
        base = {2: 8, 3: 20, 4: 35}[legs]
        liq = 30 if minc < 5 else 18 if minc < 10 else 10 if minc < 20 else 4 if minc < 40 else 0
        hot = 30 if prof > 15 else 18 if prof > 8 else 9 if prof > 4 else 3 if prof > 2 else 0
        return max(5, min(95, base + liq + hot))

    def pack(cyc, mc, prof):
        nodes = [{"slug": s, "name": CUR.get(s, {}).get("name", s), "tk": tkf(s)} for s in cyc + [cyc[0]]]
        legs = []
        for i in range(len(cyc)):
            a, b = cyc[i], cyc[(i + 1) % len(cyc)]
            r, c = R[a][b]
            legs.append({"count": c, "url": bc_link(a, b)})
        return {"nodes": nodes, "legs": legs, "profit": round(prof, 2),
                "risk": risk(len(cyc), mc, prof), "minCount": mc}

    def dedup_top(rows, n):
        rows.sort(key=lambda x: x[0], reverse=True)
        out, seen = [], set()
        for prof, cyc, mc in rows:
            tks = frozenset(tkf(s) for s in cyc)
            if len(tks) < len(cyc) or tks in seen:   # повтор тикера в цепочке / уже был такой набор
                continue
            p = pack(cyc, mc, prof)
            if p["risk"] > MAXRISK:                  # прячем слишком рискованные
                continue
            seen.add(tks)
            out.append(p)
            if len(out) >= n:
                break
        return out

    # 2 звена — туда-обратно A→B→A
    rt = []
    for a in R:
        for b, (r1, c1) in R[a].items():
            e = R.get(b, {}).get(a)
            if e and a < b:
                rt.append(((r1 * e[0] - 1) * 100, [a, b], min(c1, e[1])))
    # 3 звена — треугольник A→B→C→A (ядро 200 ликвиднейших)
    core3 = set(deg[:200])
    tri = []
    for a in core3:
        for b, (r1, c1) in R[a].items():
            Rb = R.get(b)
            if not Rb:
                continue
            for c, (r2, c2) in Rb.items():
                if c == a:
                    continue
                e = R.get(c, {}).get(a)
                if not e:
                    continue
                prof = (r1 * r2 * e[0] - 1) * 100
                if prof >= 0.2:
                    tri.append((prof, [a, b, c], min(c1, c2, e[1])))
    # 4 звена — A→B→C→D→A (ядро 40, иначе O(n⁴) слишком долго)
    core4 = deg[:40]
    cs = set(core4)
    quad = []
    for a in core4:
        for b, (r1, c1) in R[a].items():
            if b not in cs:
                continue
            for c, (r2, c2) in R.get(b, {}).items():
                if c not in cs or c == a:
                    continue
                for d, (r3, c3) in R.get(c, {}).items():
                    if d not in cs or d == a or d == b:
                        continue
                    e = R.get(d, {}).get(a)
                    if not e:
                        continue
                    prof = (r1 * r2 * r3 * e[0] - 1) * 100
                    if prof >= 0.5:
                        quad.append((prof, [a, b, c, d], min(c1, c2, c3, e[1])))
    return {"2": dedup_top(rt, 40), "3": dedup_top(tri, 40), "4": dedup_top(quad, 40),
            "generated": RATES_GENERATED}


CHAINS_JS = r"""(function(){
 var CH=__DATA__, TL=__L__, mode="3", sort="profit";
 var mc=document.getElementById("chModes");
 [["2",TL.m2],["3",TL.m3],["4",TL.m4]].forEach(function(m){
   var b=document.createElement("button"); b.textContent=m[1]; b.dataset.m=m[0];
   if(m[0]===mode)b.className="on";
   b.onclick=function(){mode=m[0];[].forEach.call(mc.children,function(x){x.className=x.dataset.m===mode?"on":""});render();};
   mc.appendChild(b);
 });
 document.querySelectorAll(".ch-sort button").forEach(function(b){
   b.onclick=function(){sort=b.dataset.s;
     document.querySelectorAll(".ch-sort button").forEach(function(x){x.className=x.dataset.s===sort?"on":"";});render();};
 });
 function rc(r){return r<30?"r-low":r<60?"r-mid":"r-high";}
 function rl(r){return r<30?TL.low:r<60?TL.mid:TL.high;}
 function riskColor(r){return r<30?"#8CFC8C":r<60?"#ffd24a":"#ff8a8a";}
 function bar(w,color){w=Math.max(2,Math.min(100,w));return "<span class='mbar-wrap'><i class='mbar-fill' style='width:"+w.toFixed(0)+"%;background:"+color+"'></i></span>";}
 function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");}
 function render(){
   var rows=(CH[mode]||[]).slice();
   rows.sort(function(a,b){return sort==="risk"?a.risk-b.risk:b.profit-a.profit;});
   var mp=rows.reduce(function(m,r){return r.profit>m?r.profit:m;},0)||1;
   document.querySelector("#chTbl thead").innerHTML=
     "<tr><th>"+TL.chain+"</th><th class='num'>"+TL.profit+"</th><th class='num'>"+TL.risk+"</th><th class='num'>"+TL.liq+"</th></tr>";
   var tb=rows.map(function(c){
     var path=c.nodes.map(function(n,i){
       return i<c.legs.length
         ? '<a href="'+c.legs[i].url+'" target="_blank" rel="nofollow sponsored" title="'+esc(n.name)+'">'+esc(n.tk)+'</a>'
         : '<b title="'+esc(n.name)+'">'+esc(n.tk)+'</b>';
     }).join(' <span class="arr">→</span> ');
     return "<tr><td class='ch-path'>"+path+"</td>"+
       "<td class='num prof'><span class='mval'>+"+c.profit.toFixed(2)+"%</span>"+bar(c.profit/mp*100,"#7CFC7C")+"</td>"+
       "<td class='num'><span class='badge "+rc(c.risk)+"'>"+c.risk+" "+rl(c.risk)+"</span>"+bar(c.risk,riskColor(c.risk))+"</td>"+
       "<td class='num'>≥"+c.minCount+"</td></tr>";
   }).join("");
   document.querySelector("#chTbl tbody").innerHTML=tb||("<tr><td colspan='4' class='mon-empty'>"+TL.empty+"</td></tr>");
 }
 var up=document.getElementById("chUpd");
 if(CH.generated&&up){var d=new Date(CH.generated*1000);up.textContent=TL.updated+" "+d.toISOString().slice(0,16).replace("T"," ")+" UTC";}
 render();
})();"""

CHAINS_CSS = """<style>
#chTbl{width:100%;border-collapse:collapse;font-size:14px}
#chTbl th,#chTbl td{padding:6px 8px;border-bottom:1px solid #245;text-align:left;vertical-align:top}
#chTbl td.num,#chTbl th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ch-path{line-height:1.9}
.ch-path a{white-space:nowrap}
.arr{color:#00aaaa;padding:0 1px}
.prof{color:#7CFC7C;font-weight:bold}
.badge{display:inline-block;padding:1px 7px;border-radius:3px;font-weight:bold;font-size:12px}
.r-low{background:#0a3d0a;color:#8CFC8C}.r-mid{background:#3d3300;color:#ffd24a}.r-high{background:#4d0a0a;color:#ff8a8a}
.ch-ctl{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin:10px 0}
.ch-ctl .rsrange button,.ch-sort button{background:#0a0f14;border:1px solid #245;color:#7cf;padding:4px 10px;cursor:pointer;margin-right:4px;border-radius:3px}
.ch-ctl .on{background:#00aaaa;color:#111;font-weight:bold}
#chWrap{overflow-x:auto;padding:0}
.ch-disc{padding:12px;margin-top:16px;color:#a8a8a8;font-size:13px}
.ch-disc b{color:#ffd24a}
.ch-cta{text-align:center;margin:16px 0}
.ch-cta a{display:inline-block;background:#00aaaa;color:#111;font-weight:bold;padding:6px 18px;text-decoration:none;border-radius:4px;font-size:14px}
.ch-cta a:hover{background:#55ffff}
.mbar-wrap{display:inline-block;width:56px;height:7px;background:#0a0f14;border:1px solid #245;border-radius:2px;vertical-align:middle;margin-left:7px;overflow:hidden}
.mbar-fill{display:block;height:100%}
.mval{display:inline-block;min-width:56px}
</style>"""


def render_chains(lang, chains):
    """Страница «Цепочки обмена» — арбитражные цепочки по BestChange (2/3/4 звена) с доходностью и % риска."""
    ru = lang == "ru"
    L = lambda r, e: r if ru else e
    data = json.dumps(chains, ensure_ascii=False)
    labels = json.dumps({
        "m2": L("2 звена (туда-обратно)", "2 legs (round-trip)"),
        "m3": L("3 звена (треугольник)", "3 legs (triangle)"),
        "m4": L("4 звена", "4 legs"),
        "chain": L("Цепочка обмена", "Exchange chain"),
        "profit": L("Доходность", "Profit"),
        "risk": L("Риск", "Risk"),
        "liq": L("Обменников", "Exchangers"),
        "low": L("низкий", "low"), "mid": L("средний", "med"), "high": L("высокий", "high"),
        "empty": L("Сейчас выгодных цепочек в этом режиме нет", "No profitable chains in this mode now"),
        "updated": L("Обновлено:", "Updated:"),
    }, ensure_ascii=False)
    js = CHAINS_JS.replace("__DATA__", data).replace("__L__", labels)
    title = L(f"Цепочки обмена валют — арбитраж и доходность | {S['name']}",
              f"Currency exchange chains — arbitrage & profit | {S['name']}")
    desc = L("Выгодные цепочки обмена валют (2/3/4 звена) по данным BestChange: доходность и оценка риска, "
             "обновление ежечасно. Ссылки на обменники по каждому шагу. Не финансовый совет, 18+.",
             "Profitable currency exchange chains (2/3/4 legs) from BestChange: profit and risk score, hourly "
             "updates. Exchanger links for every step. Not financial advice, 18+.")
    h1 = L("Цепочки обмена валют", "Currency exchange chains")
    lead = L("Цепочки обменов, где сумма курсов даёт плюс: обмениваешь по кругу A→B→C→A и возвращаешься с "
             "бо́льшим. Данные — лучшие курсы обменников BestChange, обновление ежечасно. Каждый шаг — ссылка на "
             "обменники. Рядом — оценка риска: чем длиннее цепочка, меньше обменников и «красивее» процент, тем выше.",
             "Exchange loops where the rates net positive: swap around A→B→C→A and come back with more. Data is "
             "the best BestChange exchanger rates, updated hourly. Each step links to exchangers. Next to each — a "
             "risk score: longer chains, fewer exchangers and 'too nice' a percent mean higher risk.")
    disc = L(
        "<b>Важно.</b> Доходность здесь <b>теоретическая</b> — по лучшим рекламируемым курсам обменников BestChange "
        "на момент обновления. Реальный результат почти всегда ниже: у обменника ограничены <b>резерв и лимиты</b>, "
        "нужна <b>верификация (KYC)</b>, перевод занимает время, есть <b>комиссии сети</b>, а курс за это время "
        "меняется — окно закрывается быстро. Региональные направления (карты AMD/KZT и т.п.) бывают с ограничениями. "
        "Это <b>не инвестиционная рекомендация и не оферта</b>. Проверяйте условия у самого обменника. 18+.<br>"
        "<b>Как считаем:</b> доходность = произведение курсов шагов минус 1. Берём только леги с <b>≥5 обменниками</b> и "
        "резервом, курс сверяем со «справедливым» (по цене в USDT) — битые курсы отбрасываем. Риск% растёт с длиной "
        "цепочки, падением числа обменников и завышенным профитом; самые рискованные (риск >70) не показываем.",
        "<b>Important.</b> Profit here is <b>theoretical</b> — based on the best advertised BestChange exchanger "
        "rates at update time. Real results are almost always lower: exchangers have limited <b>reserves and limits</b>, "
        "may require <b>KYC</b>, transfers take time, there are <b>network fees</b>, and the rate shifts meanwhile — "
        "the window closes fast. Regional directions (AMD/KZT cards etc.) may have restrictions. This is <b>not "
        "investment advice and not an offer</b>. Verify terms with the exchanger. 18+.<br>"
        "<b>Method:</b> profit = product of step rates minus 1. Only legs with <b>≥5 exchangers</b> and reserve are used, "
        "rates are sanity-checked against a 'fair' USDT-implied rate; broken rates are dropped. Risk% grows with "
        "chain length, fewer exchangers and inflated profit; the riskiest (risk >70) are hidden.")
    body = f"""
  <h1>{h1}</h1>
  <p class="lead">{lead}</p>
  <p class="updnote">{updated_str(lang)} · {L('данные','data')} BestChange</p>
  <div class="ch-ctl">
    <span class="rsrange" id="chModes"></span>
    <span class="ch-sort">{L('Сортировка', 'Sort')}:
      <button data-s="profit" class="on">{L('доходность', 'profit')}</button>
      <button data-s="risk">{L('риск', 'risk')}</button></span>
  </div>
  <div id="chWrap" class="dosborder"><table id="chTbl"><thead></thead><tbody></tbody></table></div>
  <p class="mon-note" id="chUpd"></p>
  <div class="ch-disc dosborder">{disc}</div>
  <div class="ch-cta"><a href="https://my-many.ru/?utm_source=ratescout&utm_medium=chains_cta">{L('Арбитраж', 'Arbitrage')}</a></div>
""" + CHAINS_CSS + "<script>" + js + "</script>"
    render_page(lang, "tsepochki", title, desc, body, h1)


def make_cli_txt():
    """Готовый ANSI-дашборд для консольного монитора → dist/cli.txt.
    Пользователь запускает встроенным curl/PowerShell (без установки), фид только печатается — не выполняется."""
    if not HISTORY:
        return
    R, G, RED, GR, CY, B, Y, W = "\033[0m", "\033[92m", "\033[91m", "\033[90m", "\033[96m", "\033[1m", "\033[93m", "\033[97m"
    SEP = CY + "=" * 79 + R

    def price(v):
        if v is None:
            return "—"
        a = abs(v)
        if a >= 1000:
            return f"{v:,.0f}".replace(",", " ")
        if a >= 1:
            return f"{v:.2f}"
        if a >= 0.01:
            return f"{v:.4f}"
        return f"{v:.6f}"

    def cp(pc):
        return f"{GR}   —  {R}" if pc is None else f"{(G if pc >= 0 else RED)}{'+' if pc >= 0 else ''}{pc:5.1f}%{R}"

    def heat_bg(pc):
        if pc is None:
            return 238
        t = max(-8.0, min(8.0, pc))
        if t >= 0:
            return 22 if t < 2 else (28 if t < 4 else (34 if t < 6 else 40))
        a = -t
        return 52 if a < 2 else (88 if a < 4 else (124 if a < 6 else 160))

    rows = []
    for slug, h in HISTORY.items():
        if slug == "tether-trc20" or len(h) < 2:
            continue
        info = CUR.get(slug) or {}
        by = CHG_BY.get(slug) or {}
        rows.append({"name": info.get("name", slug), "tk": info.get("ticker", ""), "price": h[-1][1],
                     "c24": by.get("24h"), "c7": by.get("7d"),
                     "rank": (MARKET.get(slug) or {}).get("rank") or 9999,
                     "crypto": info.get("category") == "Криптовалюты"})
    def dedup_tk(lst):  # по одной валюте на тикер (BTC/ETH/USDT-варианты не дублируем)
        seen, out = set(), []
        for r in lst:
            t = (r["tk"] or "").upper()
            if t and t in seen:
                continue
            seen.add(t)
            out.append(r)
        return out
    crypto_by_rank = dedup_tk(sorted([r for r in rows if r["crypto"]], key=lambda r: r["rank"]))
    watch = crypto_by_rank[:12]
    scored = sorted([r for r in rows if r["c24"] is not None], key=lambda r: r["c24"], reverse=True)
    gain, lose = scored[:12], list(reversed(scored[-12:]))
    heat = [r for r in crypto_by_rank if r["c24"] is not None][:30]
    heat.sort(key=lambda r: r["c24"], reverse=True)

    def wline(r):
        return f"  {r['name'][:18].ljust(18)} {GR}{r['tk'][:6].ljust(6)}{R} {price(r['price']).rjust(11)}  {cp(r['c24'])} {GR}24ч{R}  {cp(r['c7'])} {GR}7д{R}"

    def mline(r):
        return f"  {r['name'][:18].ljust(18)} {GR}{r['tk'][:6].ljust(6)}{R} {price(r['price']).rjust(11)}  {cp(r['c24'])}"

    def tile(r):
        pc = r["c24"]
        t = f"{(r['tk'][:5]):>5} {'+' if pc >= 0 else ''}{pc:.0f}%"
        return f"\033[48;5;{heat_bg(pc)}m{W} {t[:11].ljust(11)} {R}"

    ts = datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if RATES_GENERATED else ""
    L = [SEP, f"  {B}RateScout{R} — консольный монитор курсов   ·   {Y}{ts}{R}", SEP, "",
         f"  {CY}> WATCHLIST — топ-крипта по капитализации{R}"]
    L += [wline(r) for r in watch]
    L += ["", f"  {G}> ЛИДЕРЫ РОСТА (24ч){R}"]
    L += [mline(r) for r in gain]
    L += ["", f"  {RED}> ЛИДЕРЫ ПАДЕНИЯ (24ч){R}"]
    L += [mline(r) for r in lose]
    L += ["", f"  {CY}> ТЕПЛОВАЯ КАРТА — топ-крипта, изменение за 24ч{R}"]
    for i in range(0, len(heat), 6):
        L.append("  " + "".join(tile(r) for r in heat[i:i + 6]))
    L += ["", SEP,
          f"  {GR}Данные: мониторинг BestChange (цены в USDT), обновление ежечасно · ratescout.info.gf{R}",
          f"  {GR}Полный интерактивный монитор (панели, графики, скринер): https://ratescout.info.gf/monitor{R}",
          f"  {GR}Приложение и эта команда: https://app.ratescout.info.gf · не оферта, 18+{R}", ""]
    with open(os.path.join(DIST, "cli.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"✅ cli.txt: watchlist {len(watch)}, {len(gain)}↑/{len(lose)}↓, хитмап {len(heat)}")


def make_cli_pages():
    """Страницы для ИНТЕРАКТИВНОГО консольного монитора → dist/cli/*.txt + лаунчеры rs.ps1/rs.sh.
    Клиент по клавише тянет нужную готовую страницу (heat/movers × 24h/7d/30d, watch) — без парсинга и без установки."""
    if not HISTORY:
        return
    R, G, RED, GR, CY, B, Y, W = "\033[0m", "\033[92m", "\033[91m", "\033[90m", "\033[96m", "\033[1m", "\033[93m", "\033[97m"

    def price(v):
        if v is None:
            return "—"
        a = abs(v)
        return (f"{v:,.0f}".replace(",", " ") if a >= 1000 else f"{v:.2f}" if a >= 1 else f"{v:.4f}" if a >= 0.01 else f"{v:.6f}")

    def cp(pc):
        return f"{GR}   —  {R}" if pc is None else f"{(G if pc >= 0 else RED)}{'+' if pc >= 0 else ''}{pc:5.1f}%{R}"

    def heat_bg(pc):
        if pc is None:
            return 238
        t = max(-8.0, min(8.0, pc))
        return (22 if t < 2 else 28 if t < 4 else 34 if t < 6 else 40) if t >= 0 else (52 if -t < 2 else 88 if -t < 4 else 124 if -t < 6 else 160)

    rows = []
    for slug, h in HISTORY.items():
        if slug == "tether-trc20" or len(h) < 2:
            continue
        info = CUR.get(slug) or {}
        by = CHG_BY.get(slug) or {}
        rows.append({"name": info.get("name", slug), "tk": info.get("ticker", ""), "price": h[-1][1],
                     "c": {"24h": by.get("24h"), "7d": by.get("7d"), "30d": by.get("30d")},
                     "rank": (MARKET.get(slug) or {}).get("rank") or 9999,
                     "cat": info.get("category") or "Прочее", "crypto": info.get("category") == "Криптовалюты"})

    def dedup(lst):
        seen, out = set(), []
        for r in lst:
            t = (r["tk"] or "").upper()
            if t and t in seen:
                continue
            seen.add(t)
            out.append(r)
        return out
    crypto = dedup(sorted([r for r in rows if r["crypto"]], key=lambda r: r["rank"]))
    # все валюты, сгруппированные по типам (для тепловой карты «по типам»)
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["cat"], []).append(r)
    cat_order = list(CATS) + [c for c in by_cat if c not in CATS]
    ts = datetime.fromtimestamp(RATES_GENERATED, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if RATES_GENERATED else ""

    # ссылка на сайт с UTM-меткой (для аналитики переходов из консоли)
    SITE = "https://ratescout.info.gf/monitor/?utm_source=console&utm_medium=cli&utm_campaign=cli_monitor"

    def link(url, text):  # OSC 8 — кликабельная ссылка в совр. терминалах; где не поддержано — просто текст
        return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"

    def head(sub):
        return [CY + "=" * 158 + R, f"  {B}RateScout{R} · {sub} · {Y}{ts}{R}", CY + "=" * 158 + R,
                f"  {GR}Курсы обмена валют в обменниках (данные BestChange). Полный функционал — на сайте.{R}", ""]

    def foot():
        btn = link(SITE, "\033[46;30m ▶ Открыть сайт — полный монитор \033[0m")
        return ["", CY + "=" * 158 + R,
                f"  {W}[h]{GR}тепл.карта  {W}[w]{GR}watchlist  {W}[m]{GR}лидеры    период {W}[1]{GR}24ч {W}[2]{GR}7д {W}[3]{GR}30д    {W}[r]{GR}обновить  {W}[q]{GR}выход{R}",
                "  " + btn + f"   {CY}{SITE}{R}",
                f"  {GR}BestChange (цены в USDT), ежечасно · курсы обмена в обменниках · 18+{R}"]

    cdir = os.path.join(DIST, "cli")
    os.makedirs(cdir, exist_ok=True)

    def wr(name, lines):
        with open(os.path.join(cdir, name), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # --- раскладка в 2 колонки (шире, а не длиннее): паддинг по ВИДИМОЙ ширине (без ANSI) ---
    ansi_re = re.compile(r"\033\[[0-9;]*m")

    def vlen(s):
        return len(ansi_re.sub("", s))

    def padv(s, n):
        return s + " " * max(0, n - vlen(s))

    def pair(cells, cw):
        out = []
        for i in range(0, len(cells), 2):
            a = padv(cells[i], cw)
            b = cells[i + 1] if i + 1 < len(cells) else ""
            out.append("  " + a + "   " + b)
        return out

    def ml(r, per):  # ячейка мувера (без отступа, фикс. видимая ширина под 2 колонки)
        return f"{r['name'][:18].ljust(18)} {GR}{r['tk'][:6].ljust(6)}{R} {price(r['price']).rjust(11)}  {cp(r['c'][per])}"

    def tile(r, per):
        pc = r["c"][per]
        # крипта: тикер (BTC). фиат/банки/наличные: тикер = ВАЛЮТА (RUB/USD), name = способ (Cash/Sberbank);
        # показываем «ВАЛЮТА способ» — валюта первой, чтобы всегда была видна (иначе «Cash»×22 без валюты)
        lab = r["tk"] if r["crypto"] else f"{r['tk']} {r['name']}"
        txt = f"{lab[:13].ljust(13)} {'+' if pc >= 0 else ''}{pc:.0f}%"
        return f"\033[48;5;{heat_bg(pc)}m{W} {txt[:19].ljust(19)} {R}"
    for per, lbl in (("24h", "24ч"), ("7d", "7д"), ("30d", "30д")):
        L = head(f"тепловая карта · все валюты по типам · {lbl}")
        for c in cat_order:
            items = by_cat.get(c, [])
            if c == "Криптовалюты":
                items = dedup(sorted(items, key=lambda r: r["rank"]))
            items = [r for r in items if r["c"][per] is not None]
            items.sort(key=lambda r: r["c"][per], reverse=True)
            if not items:
                continue
            L += ["", f"  {CY}> {cat_name(c, 'ru').upper()}{R} {GR}({len(items)}){R}"]
            for i in range(0, len(items), 7):
                L.append("  " + "".join(tile(r, per) for r in items[i:i + 7]))
        wr(f"heat-{per}.txt", L + foot())
        M = head(f"движение · все валюты по типам (сорт. по изм.) · {lbl}")
        for c in cat_order:
            items = by_cat.get(c, [])
            if c == "Криптовалюты":
                items = dedup(sorted(items, key=lambda r: r["rank"]))
            items = [r for r in items if r["c"][per] is not None]
            items.sort(key=lambda r: r["c"][per], reverse=True)
            if not items:
                continue
            M += ["", f"  {CY}> {cat_name(c, 'ru').upper()}{R} {GR}({len(items)}){R}"]
            M += pair([ml(r, per) for r in items], 46)
        wr(f"movers-{per}.txt", M + foot())

    def wl(r):  # ячейка watchlist (без отступа, под 2 колонки)
        return f"{r['name'][:18].ljust(18)} {GR}{r['tk'][:6].ljust(6)}{R} {price(r['price']).rjust(11)}  {cp(r['c']['24h'])} {GR}24ч{R}  {cp(r['c']['7d'])} {GR}7д{R}"
    WL = head("watchlist · все валюты по типам")
    for c in cat_order:
        items = by_cat.get(c, [])
        items = dedup(sorted(items, key=lambda r: r["rank"])) if c == "Криптовалюты" else sorted(items, key=lambda r: (r["name"] or ""))
        if not items:
            continue
        WL += ["", f"  {CY}> {cat_name(c, 'ru').upper()}{R} {GR}({len(items)}){R}"]
        WL += pair([wl(r) for r in items], 62)
    wr("watch.txt", WL + foot())

    for fn in ("rs.ps1", "rs.sh"):
        src = os.path.join(ROOT, "console", fn)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(cdir, fn))
    print("✅ cli/: heat/movers×(24h/7d/30d) + watch + лаунчеры rs.ps1/rs.sh")


def make_monitor_json():
    """Данные для профессионального монитора → dist/data/monitor.json (курсы в USDT + названия валют)."""
    if not HISTORY:
        print("⚠️  history пуст — monitor.json пропущен"); return
    cur = {}
    present = set()
    for slug in HISTORY:
        info = CUR.get(slug) or {}
        c = info.get("category", "")
        cs = CAT_SLUG.get(c, "prochee")
        present.add(c)
        entry = {"n": info.get("name", slug), "t": info.get("ticker", ""), "cs": cs}
        # id/num — чтобы терминал мог собрать affiliate-ссылку BestChange для пар без своей страницы (см. bc_link)
        if info.get("id") is not None:
            entry["id"] = info["id"]
        if info.get("num"):
            entry["num"] = info["num"]
        cur[slug] = entry
    # категории (в порядке CATS), только те, что реально есть среди валют монитора, с локализ. названиями
    cats = [{"s": CAT_SLUG.get(c, "prochee"), "ru": cat_name(c, "ru"), "en": cat_name(c, "en")}
            for c in CATS if c in present]
    # «ядровые» пары (страницы /obmen/<from>-<to>/ есть в обеих локалях) — для кнопки «открыть на сайте»
    pairs = ["%s-%s" % (p["from"], p["to"]) for p in PAIR_PAGES if p["from"] in HISTORY and p["to"] in HISTORY]
    # popular.json (GSC): спрос из поиска по направлениям {"from>to": clicks}. Добавляем имена/id слугов,
    # которых нет среди валют монитора (фиат/платёжки), — чтобы панель «Спрос» показывала названия и ссылки.
    for _key in POPULAR:
        for _s in _key.split(">"):
            if _s not in cur:
                _i = CUR.get(_s) or {}
                _e = {"n": _i.get("name", _s), "t": _i.get("ticker", "")}
                if _i.get("id") is not None:
                    _e["id"] = _i["id"]
                if _i.get("num"):
                    _e["num"] = _i["num"]
                cur[_s] = _e
    # синтетический плоский ряд для базового USDT (цена в USDT ≡ 1) — чтобы и он строился в графике,
    # а не выкидывал на страницу сайта (единственная валюта без своего ряда — знаменатель).
    ser_out = dict(HISTORY)
    _axis = max(HISTORY.values(), key=len) if HISTORY else []
    for _s in list(cur):
        if _s not in ser_out and (cur[_s].get("t") or "").upper() == "USDT":
            ser_out[_s] = [[d, 1.0] for d, _v in _axis]
    os.makedirs(os.path.join(DIST, "data"), exist_ok=True)
    with open(os.path.join(DIST, "data", "monitor.json"), "w", encoding="utf-8") as f:
        json.dump({"unit": "USDT", "ref": REF, "cur": cur, "cats": cats, "pairs": pairs,
                   "popular": POPULAR, "trending": TRENDING, "yandex": YANDEX_Q, "metrika": METRIKA_Q, "series": ser_out},
                  f, ensure_ascii=False, separators=(",", ":"))
    print("✅ data/monitor.json: %d валют, %d кат., %d пар, %d GSC-напр., %d трендов, %d Яндекс-запр., %d Метрика-фраз"
          % (len(cur), len(cats), len(pairs), len(POPULAR), len(TRENDING), len(YANDEX_Q), len(METRIKA_Q)))


def render_alert(lang):
    """Оповещения о курсе пары A/B: выбор 2 валют, порог, направление, график пары, подписка в TG-бот."""
    if not HISTORY:
        return
    ru = lang == "ru"
    L = lambda r, e: r if ru else e
    title = L("Оповещения о курсе пары валют — сигнал в Telegram",
              "Currency pair rate alerts — Telegram signal")
    desc = L("Подпишитесь на курс пары валют: пришлём сигнал в Telegram, когда «1 A ≥/≤ порог B». Выбор валют, график пары, бесплатно — RateScout.",
             "Subscribe to a currency pair rate: get a Telegram signal when '1 A is above/below a threshold in B'. Pick currencies, pair chart, free — RateScout.")
    h1 = L("Оповещения о курсе пары", "Currency pair alerts")
    lead = L("Выберите две валюты и задайте порог: Telegram-бот пришлёт сигнал, когда 1 единица первой валюты станет выше или ниже заданного значения во второй. Единицу можно перевернуть кнопкой ⇄.",
             "Pick two currencies and set a threshold: the Telegram bot sends a signal when 1 unit of the first goes above or below the set amount in the second. Swap the unit with ⇄.")
    body = f"""
  <h1>{h1}</h1>
  <p class="lead">{lead}</p>
  <div id="alert" class="alert-wrap dosborder">
    <div class="alert-row">
      <label class="alert-cur">{L('Валюта','Currency')} A<br><select id="alertA"></select></label>
      <button id="alertSwap" type="button" class="mon-btn alert-swap" title="{L('Поменять местами','Swap')}">⇄</button>
      <label class="alert-cur">{L('в валюте','in currency')} B<br><select id="alertB"></select></label>
    </div>
    <div class="alert-row">
      <label class="alert-cur">{L('Условие','Condition')}<br><select id="alertDir"><option value="g">{L('1 A ≥ порога','1 A ≥ threshold')}</option><option value="l">{L('1 A ≤ порога','1 A ≤ threshold')}</option></select></label>
      <label class="alert-cur">{L('Порог (в B)','Threshold (in B)')}<br><input id="alertThr" type="text" inputmode="decimal" autocomplete="off"></label>
    </div>
    <p id="alertNow" class="alert-now"></p>
    <div id="alertChart" class="mon-chart dosborder"><p class="mon-empty">{L('Загружаю…','Loading…')}</p></div>
    <button id="alertSub" type="button" class="alert-sub">{L('🔔 Подписаться в Telegram','🔔 Subscribe in Telegram')}</button>
    <p class="alert-hint">{L('Оповещение придёт в бот','Alert arrives in the bot')} <b>@RateScoutRUBot</b>. {L('Бесплатно. Отписаться — командой /myalerts.','Free. Unsubscribe with /myalerts.')}</p>
  </div>
  <script src="/assets/alert.js?v={VER['alert']}"></script>
"""
    render_page(lang, "alert", title, desc, body, h1)


def render_heatmap(lang):
    """Тепловая карта по ВСЕМ валютам: плитки как в терминале (цвет = изменение за период), клик → страница валюты."""
    if not HISTORY:
        return
    ru = lang == "ru"
    L = lambda r, e: r if ru else e
    n = len([s for s in HISTORY if s != "tether-trc20"])
    title = L(f"Тепловая карта криптовалют — все валюты | {S['name']}",
              f"Crypto heatmap — all currencies | {S['name']}")
    desc = L("Тепловая карта курсов всех валют: рост и падение цветом за выбранный период (24ч…год). "
             "Данные мониторинга BestChange, обновление ежечасно.",
             "Heatmap of all currency rates: gains and losses by color over a chosen period (24h…year). "
             "BestChange monitoring data, hourly updates.")
    h1 = L("Тепловая карта валют", "Currency heatmap")
    lead = L(f"Все {n} валют одной картой: цвет плитки — изменение цены за период (зелёный — рост, красный — падение). "
             "Переключите период и категорию, нажмите плитку — откроется страница валюты.",
             f"All {n} currencies as one map: tile color is price change over the period (green — up, red — down). "
             "Switch period and category, click a tile to open the currency page.")
    body = f"""
  <h1>{h1}</h1>
  <p class="lead">{lead}</p>
  <div id="heatpage" class="dosborder">
    <div class="hp-ctl">
      <span id="hpRanges" class="mon-ranges"></span>
      <label class="hp-base">{L('Оценка в','Valued in')}: <select id="hpBase"></select></label>
      <input id="hpSearch" class="mon-search" placeholder="{L('поиск валюты…','search…')}" autocomplete="off">
    </div>
    <div id="hpCats" class="rsrange"></div>
    <div id="hpGrid" class="heat-grid"><p class="mon-empty">{L('Загружаю…','Loading…')}</p></div>
    <p id="hpNote" class="mon-note"></p>
  </div>
  <script src="/assets/heatmap.js?v={VER['heat']}"></script>
"""
    render_page(lang, "heatmap", title, desc, body, h1)


def render_popular(lang):
    """Популярность валют по поиску: агрегат кликов GSC (popular.json) по валютам + тренд CoinGecko. SEO-хаб."""
    if not HISTORY:
        return
    ru = lang == "ru"
    L = lambda r, e: r if ru else e
    # GSC: клики по направлениям → сумма по валютам
    agg = {}
    for key, clk in POPULAR.items():
        for s in key.split(">"):
            if s == "tether-trc20":
                continue
            agg[s] = agg.get(s, 0) + (clk or 0)
    gsc_rows = sorted(((s, c) for s, c in agg.items() if s in CUR), key=lambda x: -x[1])

    def cur_link(slug):
        info = CUR.get(slug) or {}
        nm = info.get("name", slug)
        tk = info.get("ticker", "")
        return f'<a href="{cpage(lang, slug)}">{nm}{(" <b>" + tk + "</b>") if tk else ""}</a>'

    def chg24(slug):
        v = CHG_BY.get(slug, {}).get("24h")
        if v is None:
            return "<td>—</td>"
        cls = "up" if v >= 0 else "dn"
        return f'<td class="{cls}">{"+" if v >= 0 else ""}{v:.1f}%</td>'

    if gsc_rows:
        head = L("<tr><th>#</th><th>Валюта</th><th>Спрос (клики)</th><th>24ч</th></tr>",
                 "<tr><th>#</th><th>Currency</th><th>Demand (clicks)</th><th>24h</th></tr>")
        body_rows = "".join(
            f'<tr><td>{i+1}</td><td>{cur_link(s)}</td><td>{c}</td>{chg24(s)}</tr>'
            for i, (s, c) in enumerate(gsc_rows))
        gsc_block = (f'<h2>{L("По запросам в Google (наш сайт)", "By Google queries (our site)")}</h2>'
                     f'<div class="rtbl-wrap"><table class="rtbl">{head}{body_rows}</table></div>')
    else:
        gsc_block = f'<p class="updnote">{L("Данные поиска накапливаются из Google Search Console — список появится здесь.", "Search data is accumulating from Google Search Console — the list will appear here.")}</p>'

    # CoinGecko trending
    if TRENDING:
        head2 = L("<tr><th>#</th><th>Монета</th><th>Ранг</th><th>24ч</th></tr>",
                  "<tr><th>#</th><th>Coin</th><th>Rank</th><th>24h</th></tr>")
        def tcell(c):
            nm = c.get("name") or c.get("symbol") or "?"
            sym = c.get("symbol") or ""
            slug = c.get("slug") or ""
            label = f'{nm}{(" <b>" + sym + "</b>") if sym else ""}'
            cell = f'<a href="{cpage(lang, slug)}">{label}</a>' if slug and slug in CUR else label
            ch = c.get("chg24h")
            chd = "—" if ch is None else f'{"+" if ch >= 0 else ""}{ch:.1f}%'
            chcls = "" if ch is None else (' class="up"' if ch >= 0 else ' class="dn"')
            return f'<td>{cell}</td><td>{c.get("rank") or "—"}</td><td{chcls}>{chd}</td>'
        rows2 = "".join(f'<tr><td>{i+1}</td>{tcell(c)}</tr>' for i, c in enumerate(TRENDING))
        trend_block = (f'<h2>{L("В тренде поиска (CoinGecko)", "Trending search (CoinGecko)")}</h2>'
                       f'<div class="rtbl-wrap"><table class="rtbl">{head2}{rows2}</table></div>')
    else:
        trend_block = ""

    title = L(f"Популярность валют по поиску — что ищут чаще | {S['name']}",
              f"Currency popularity by search — what people look up | {S['name']}")
    desc = L("Рейтинг популярности валют по данным поиска: что чаще ищут для обмена (Google Search Console) и что в тренде (CoinGecko).",
             "Currency popularity ranking from search data: what people look up to exchange (Google Search Console) and what is trending (CoinGecko).")
    h1 = L("Популярность валют по поиску", "Currency popularity by search")
    lead = L("Какие валюты и направления люди ищут чаще всего. Слева — спрос из Google по нашему сайту, ниже — что сейчас в тренде поиска по крипте. Нажмите валюту — её страница с курсами.",
             "Which currencies and directions people search for most. First — Google demand for our site, then what is trending in crypto search now. Click a currency for its rates page.")
    rel = L(f'<p class="related"><a href="{PREF[lang]}/monitor/">Профессиональный монитор</a> · <a href="{PREF[lang]}/heatmap/">Тепловая карта</a></p>',
            f'<p class="related"><a href="{PREF[lang]}/monitor/">Professional monitor</a> · <a href="{PREF[lang]}/heatmap/">Heatmap</a></p>')
    body = f'<h1>{h1}</h1><p class="lead">{lead}</p>{gsc_block}{trend_block}{rel}'
    render_page(lang, "populyarnost", title, desc, body, h1)


def render_monitor(lang):
    """Профессиональный монитор: графики многих валют на одной шкале + ре-база + линии/свечи + выбор галочками."""
    if not HISTORY:
        return
    ru = lang == "ru"
    L = lambda r, e: r if ru else e
    title = L("Профессиональный монитор курсов — все валюты на одном графике",
              "Professional rate monitor — all currencies on one chart")
    desc = L("Монитор курсов: графики валют на одной шкале, выбор базовой валюты (по умолчанию доллар), линии или свечи, выбор валют галочками — RateScout.",
             "Rate monitor: currency charts on one scale, base currency (USD by default), lines or candles, pick currencies with checkboxes — RateScout.")
    h1 = L("Профессиональный монитор курсов", "Professional rate monitor")
    lead = L("Биржевой терминал: несколько панелей (графики, watchlist, лидеры роста/падения, тепловая карта), которые можно двигать, менять размер и сохранять. Или классический вид — все валюты на одном графике.",
             "Trading-terminal view: several panels (charts, watchlist, top movers, heatmap) you can drag, resize and save. Or the classic view — all currencies on one chart.")
    faq_items = [
        ("Что такое профессиональный монитор курсов?",
         "Это бесплатный инструмент RateScout: показывает курсы валют по данным мониторинга обменников BestChange (цены в USDT, обновление ежечасно) и позволяет собрать свой «терминал» из панелей — графики, watchlist, лидеры роста/падения, тепловая карта, скринер, спрос из поиска. Установка и регистрация не нужны."),
        ("Это бесплатно и нужна ли регистрация?",
         "Полностью бесплатно и без регистрации. Монитор ничего не покупает и не продаёт — только показывает и сравнивает цифры."),
        ("Откуда данные и как часто обновляются?",
         "Из мониторинга обменников BestChange; цена каждой валюты дана в USDT, обновление ежечасно. Это справочные данные для сравнения, а не оферта — реальный курс подтверждается на стороне обменника."),
        ("Чем «Терминал» отличается от «Классики»?",
         "Классика — один график с выбором валют галочками. Терминал — многопанельный режим: несколько окон (графики, watchlist, муверы, тепловая карта, скринер, спрос), которые двигаются, меняют размер, выстраиваются в сетку и сохраняются."),
        ("Как добавить валюту на график?",
         "Кликните валюту в любом окне (в списке, тепловой карте, скринере, панели спроса) — она добавится на активный график; повторный клик уберёт её. Валюты, которые уже на графике, отмечены точкой во всех окнах."),
        ("Что такое «активный график»?",
         "Это окно графика, на которое вы нажали последним (оно подсвечено рамкой). Клики по валютам в других окнах отправляют их именно в активный график. Если графика ещё нет — первый клик по валюте создаёт новое окно."),
        ("Что значит «Оценка в»?",
         "Валюта, относительно которой считаются цена и изменение. По умолчанию USDT; можно выбрать любую — например BTC, и тогда динамика будет показана относительно биткоина. В терминале есть общий селектор, у тепловой карты может быть свой."),
        ("Можно ли сохранить рабочий стол и поделиться им?",
         "Да. Раскладка запоминается в браузере, а кнопка «Ссылка» кодирует весь набор окон в адрес — им можно поделиться или сохранить закладкой; по ссылке откроется тот же рабочий стол."),
        ("Работает ли на телефоне?",
         "Да, панели выстраиваются в одну колонку, а чтение и клики работают так же. Неудобные для маленького экрана функции (перетаскивание окон, полноэкранный режим) на мобильном скрыты."),
        ("Это обменник? Можно ли здесь обменять валюту?",
         "Нет. RateScout — независимый информационный сервис мониторинга курсов, обмен он не проводит. Выбрав направление, вы совершаете сделку на стороне обменника; там же сверьте курс и резерв. 18+."),
    ] if ru else [
        ("What is the professional rate monitor?",
         "It is a free RateScout tool: it shows currency rates from BestChange exchanger-monitoring data (prices in USDT, hourly updates) and lets you build your own terminal from panels — charts, watchlist, top movers, heatmap, screener, search demand. No install or sign-up."),
        ("Is it free and do I need to register?",
         "Fully free and no sign-up. The monitor buys and sells nothing — it only shows and compares numbers."),
        ("Where does the data come from and how often is it updated?",
         "From BestChange exchanger monitoring; each currency's price is in USDT, updated hourly. These are reference figures for comparison, not an offer — the real rate is confirmed on the exchanger side."),
        ("How is the Terminal different from Classic?",
         "Classic is a single chart with checkboxes. Terminal is a multi-panel mode: several windows (charts, watchlist, movers, heatmap, screener, demand) you can drag, resize, tile and save."),
        ("How do I add a currency to the chart?",
         "Click a currency in any window (a list, heatmap, screener, demand panel) — it is added to the active chart; click again to remove it. Currencies already on the chart are marked with a dot in every window."),
        ("What is the active chart?",
         "It is the chart window you clicked last (highlighted). Clicks on currencies in other windows go to the active chart. If no chart exists, the first click creates a new one."),
        ("What does Valued in mean?",
         "The currency price and change are measured against. USDT by default; pick any — e.g. BTC to see dynamics relative to bitcoin. The terminal has a global selector; the heatmap can have its own."),
        ("Can I save and share my workspace?",
         "Yes. The layout is remembered in the browser, and the Link button encodes the whole set of windows into a URL you can share or bookmark; the link reopens the same workspace."),
        ("Does it work on a phone?",
         "Yes — panels stack into a single column and reading and clicking work the same. Features awkward on a small screen (dragging windows, fullscreen) are hidden on mobile."),
        ("Is this an exchange? Can I swap here?",
         "No. RateScout is an independent rate-monitoring service and does not process exchanges. After choosing a direction you make the deal on the exchanger side; verify the rate and reserve there. 18+."),
    ]
    _qa = "".join(f'<details><summary>{q}</summary><p>{a}</p></details>' for q, a in faq_items)
    _faqld = jsonld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub("<[^>]+>", "", a)}}
        for q, a in faq_items]})
    faq_html = f'<h2 class="news">{L("Частые вопросы о мониторе", "Monitor FAQ")}</h2>{_qa}{_faqld}'
    body = f"""
  <h1>{h1}</h1>
  <p class="lead">{lead}</p>
  <div class="mon-mode">
    <button id="modeTerm" class="on" type="button">⊞ {L('Терминал','Terminal')}</button>
    <button id="modeClassic" type="button">{L('Классика','Classic')}</button>
  </div>
  <div id="terminal">
    <div id="termBar" class="term-bar"></div>
    <div id="termCanvas"></div>
  </div>
  <div id="monitor" class="mon-wrap">
    <div class="mon-main">
      <div class="mon-ctl">
        <label>{L('База','Base')}: <select id="monBase"></select></label>
        <label>{L('Тип','Type')}: <select id="monType"><option value="line">{L('Линии','Lines')}</option><option value="candle">{L('Свечи','Candles')}</option><option value="ratio">{L('Пара A/B','Pair A/B')}</option></select></label>
        <label class="mon-chk"><input id="monLog" type="checkbox"> {L('лог-шкала','log scale')}</label>
        <label class="mon-chk"><input id="monCorrChk" type="checkbox"> {L('корреляция','correlation')}</label>
        <span class="mon-exp"><button id="monCsv" type="button" class="mon-btn">CSV</button><button id="monPng" type="button" class="mon-btn">PNG</button><button id="monLink" type="button" class="mon-btn">{L('Ссылка','Link')}</button></span>
      </div>
      <div id="monRanges" class="mon-ranges"></div>
      <div id="monChart" class="mon-chart dosborder"><p class="mon-empty">{L('Загружаю…','Loading…')}</p></div>
      <div id="monLegend" class="mon-legend"></div>
      <p id="monNote" class="mon-note"></p>
      <div id="monStats" class="mon-stats"></div>
      <div id="monCorrBox" class="mon-corr"></div>
    </div>
    <aside class="mon-side dosborder">
      <div class="mon-side-h">{L('Валюты на графике','Currencies on chart')}</div>
      <div id="monPresets" class="mon-presets"></div>
      <div id="monCats" class="rsrange mon-cats"></div>
      <label class="mon-show-l">{L('Показывать','Show')}: <select id="monShow"><option value="all">{L('все','all')}</option><option value="sel">{L('выбранные','selected')}</option></select></label>
      <div class="mon-side-top">
        <input id="monSearch" class="mon-search" placeholder="{L('поиск валюты…','search…')}" autocomplete="off">
        <button id="monClear" type="button" class="mon-btn">{L('Очистить','Clear')}</button>
      </div>
      <div id="monList" class="mon-list"></div>
    </aside>
  </div>
  {faq_html}
  <script src="/assets/monitor.js?v={VER['mon']}"></script>
  <script src="/assets/terminal.js?v={VER['term']}"></script>
"""
    render_page(lang, "monitor", title, desc, body, h1)


def render_book(lang):
    """Страница книг RateScout: два издания с разделителем + скачивание DOCX.
    Позже DOCX-ссылки заменим на ссылки магазинов (блок stores у каждой книги)."""
    def blk(name, sub, lead, href, dl_label, stores):
        return (f'<section class="bookblk"><h2>{name}</h2><p class="sub">{sub}</p>{lead}'
                f'<p><a class="cta" href="{href}" download>{dl_label}</a></p>'
                f'<p class="updnote">{stores}</p></section>')
    if lang == "ru":
        title = "Книги RateScout — скачать (обмен криптовалюты и профессиональный монитор)"
        desc = ("Книги RateScout: практический гид «Обмен криптовалюты без потерь» и руководство "
                "«Профессиональный монитор криптокурсов». Скачать бесплатно.")
        h1 = "Книги RateScout"
        intro = ('<p class="lead">Практические книги автора Семенцул Максим — без хайпа и инвест-советов, только практика. 18+.</p>')
        stores_ru = ("Книга готовится к публикации в магазинах (Ridero, OZON, Bookmate, Яндекс Книги, "
                     "Wildberries и др.) — ссылки появятся здесь.")
        b1 = blk("Обмен криптовалюты без потерь",
                 "Практический гид по обмену через мониторинг обменников · Автор: Семенцул Максим",
                 ("<p>Как менять криптовалюту и деньги через мониторинг обменников — выгодно и без потерь. "
                  "Курс, резерв и рейтинг, выбор надёжного обменника, защита от мошенников, сети "
                  "(TRC20/ERC20/BEP20/TON), стейблкоины и AML. Чек-лист первого безопасного обмена, словарь и типичные ошибки.</p>"),
                 "/book/obmen-kriptovalyuty-RU.docx", "Скачать книгу (DOCX) →", stores_ru)
        b2 = blk("Профессиональный монитор криптокурсов",
                 "Как читать рынок обмена и собрать торговый терминал в браузере · Автор: Семенцул Максим",
                 ("<p>Полное руководство по профессиональному монитору RateScout: как читать цену в USDT, изменение и "
                  "волатильность; панели График, Watchlist, Муверы, Тепловая карта, Скринер и Спрос из поиска; активный "
                  "график, тайл-раскладка, темы, сохранение рабочего стола ссылкой. Сценарии поиска валют и пар под стратегию.</p>"),
                 "/book/professional-monitor-RU.docx", "Скачать книгу (DOCX) →", stores_ru)
        crumb = "Книги"
    else:
        title = "RateScout books — download (crypto exchange and professional monitor)"
        desc = ("RateScout books: the practical guide Crypto Exchange Without Losses and the manual "
                "Professional Crypto Rate Monitor. Download for free.")
        h1 = "RateScout books"
        intro = ('<p class="lead">Practical books by Maxim Sementsul — no hype, no investment advice, just practice. 18+.</p>')
        stores_en = ("The book is being prepared for publication in stores (Ridero, Amazon, Bookmate and others) — "
                     "links will appear here.")
        b1 = blk("Crypto Exchange Without Losses",
                 "A practical guide to exchanging via monitors · Author: Maxim Sementsul",
                 ("<p>How to exchange crypto and money through exchange monitors — profitably and without losses. "
                  "Rate, reserve and rating, picking a reliable exchanger, avoiding scammers, networks "
                  "(TRC20/ERC20/BEP20/TON), stablecoins and AML. A safe-first-exchange checklist, a glossary and common mistakes.</p>"),
                 "/book/crypto-exchange-EN.docx", "Download the book (DOCX) →", stores_en)
        b2 = blk("Professional Crypto Rate Monitor",
                 "How to read the exchange market and build a trading terminal in the browser · Author: Maxim Sementsul",
                 ("<p>A full manual for the RateScout professional monitor: reading price in USDT, change and volatility; "
                  "the Chart, Watchlist, Movers, Heatmap, Screener and Search-demand panels; the active chart, tiled layout, "
                  "themes, saving your workspace as a link. Scenarios for finding currencies and pairs by strategy.</p>"),
                 "/book/professional-monitor-EN.docx", "Download the book (DOCX) →", stores_en)
        crumb = "Books"
    body = f'<h1>{h1}</h1>{intro}{b1}<hr class="bkdiv">{b2}'
    render_page(lang, "kniga", title, desc, body, crumb)


def main():
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    # версии ассетов (кеш-бастинг) — до рендера, чтобы попали в head/footer
    catjs = build_catalog_js()
    VER["css"] = _h(open(os.path.join(ROOT, "assets", "styles.css"), encoding="utf-8").read())
    VER["js"] = _h(open(os.path.join(ROOT, "assets", "app.js"), encoding="utf-8").read())
    VER["cat"] = _h(catjs)
    VER["mon"] = _h(open(os.path.join(ROOT, "assets", "monitor.js"), encoding="utf-8").read())
    VER["alert"] = _h(open(os.path.join(ROOT, "assets", "alert.js"), encoding="utf-8").read())
    VER["term"] = _h(open(os.path.join(ROOT, "assets", "terminal.js"), encoding="utf-8").read())
    VER["heat"] = _h(open(os.path.join(ROOT, "assets", "heatmap.js"), encoding="utf-8").read())
    for _s in CUR:
        _hh = HISTORY.get(_s, [])
        if len(_hh) >= 2:
            CHG_BY[_s] = {pk: _pct_over(_hh, dys) for pk, dys in CHART_PERIODS}
    _chains = compute_chains()   # цепочки обмена (арбитраж) — считаем один раз, рендерим на обоих языках
    print(f"   цепочки: 2зв={len(_chains['2'])} 3зв={len(_chains['3'])} 4зв={len(_chains['4'])}")
    for lang in LANGS:
        render_home(lang)
        for slug, info in CUR.items():
            render_currency(slug, info, lang)
            render_buy(slug, info, lang)
        compliance_pages(lang)
        for _c in CATS:
            render_category(_c, lang)
        for _b in BANK_HUBS:
            render_bank_hub(_b, lang)
        render_editorial(lang)
        render_glossary(lang)
        render_charts_overview(lang)
        render_heatmap(lang)
        render_popular(lang)
        render_monitor(lang)
        render_chains(lang, _chains)
        render_alert(lang)
        render_relative(lang)
        render_directions(lang)
        for _sid, _d, _rw, _ew in REVIEWS:
            render_review(lang, _sid, _d, _rw, _ew)
        render_svodka(lang)
        render_market_leaders(lang)
        render_koshelki(lang)
        render_stablecoins(lang)
        render_fng(lang)
        render_halving(lang)
        render_compare_index(lang)
        for _ca, _cb in compare_pairs():
            render_compare(_ca, _cb, lang)
        render_widget_page(lang)
        render_book(lang)
        render_faq(lang)
        render_blog(lang)
        render_rss(lang)
        for a in ARTS[lang]:
            render_article(a, lang)
        for p in PAIR_PAGES:
            render_pair(p["from"], p["to"], lang)
        if lang == "ru":                    # RU-only расширение направлений (≥3 обменников)
            for p in PAIR_PAGES_RU:
                render_pair(p["from"], p["to"], lang)
    render_404()
    render_miniapp()
    static_files()
    copy_assets()
    make_monitor_json()     # dist/data/monitor.json для монитора
    if os.path.exists(_rp):  # публичный экспорт направленных курсов для MyMany (арбитражные цепочки)
        shutil.copy(_rp, os.path.join(DIST, "rates.json"))
    make_cli_txt()          # dist/cli.txt — простой фид (одна команда)
    make_cli_pages()        # dist/cli/*.txt + лаунчеры — интерактивный консольный монитор
    write_favicons()        # /favicon.ico + apple-touch (после copy_assets)
    write_covers()          # после copy_assets (он rmtree-ит dist/assets)
    write_daily_digest()    # dist/daily.json + daily-24h.png для Telegram (тоже после copy_assets)
    write_daily_digest_en() # dist/daily-en.json для английского Telegram-канала
    write_article_announce() # article-today.json — анонс вышедшей сегодня статьи
    render_dzen_rss()       # ссылается на обложки — после их генерации
    write_catalog_js(catjs)
    print(f"✅ dist/: {LANGS} × (главная + {len(CUR)} валют + {len(PAIR_PAGES)} пар + {1+len(ARTS['ru'])} блог + 4 инфо) + sitemap/robots")
    print(f"   asset ver: css={VER['css']} js={VER['js']} cat={VER['cat']}")


if __name__ == "__main__":
    main()
