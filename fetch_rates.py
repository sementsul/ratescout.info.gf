#!/usr/bin/env python3
"""Обновление данных RateScout из публичного дампа BestChange (api.bestchange.ru/info.zip).

Делает две вещи из ОДНОГО дампа (без ключа):
  1) СИНХРОНИЗИРУЕТ каталог валют currencies.json из bm_cy.dat — добавляет новые валюты,
     убирает удалённые, обновляет категории. Существующие слаги/URL сохраняются (стабильный SEO).
  2) СЧИТАЕТ курсы из bm_rates.dat → rates.json (лучший курс/резерв/число обменников на пару).

Формат bm_cy.dat (cp1251, ';'):  id ; code ; name ; ticker ; iso ; CAT ; bitmask
  CAT: 0=Криптовалюты 1=Digital currencies 2=Bank accounts and cards 3=Online banking 4=Money transfers 5=Cash
Формат bm_rates.dat: id_from ; id_to ; id_exch ; rate_from ; rate_to ; reserve ; …

🔴 Ключ (BESTCHANGE_API_KEY) для дампа НЕ нужен. Если задан BESTCHANGE_RATES_URL — берём его.
"""
import io
import json
import os
import re
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_URL = "http://api.bestchange.ru/info.zip"
CATCODE = {"0": "Криптовалюты", "1": "Digital currencies", "2": "Bank accounts and cards",
           "3": "Online banking", "4": "Money transfers", "5": "Cash"}
CAT_ORDER = ["Криптовалюты", "Digital currencies", "Bank accounts and cards",
             "Online banking", "Money transfers", "Cash", "Прочее"]


def download(url, key=None):
    if key:
        url = url.replace("{key}", key)
    req = urllib.request.Request(url, headers={"User-Agent": "RateScout/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _member(zf, suffix):
    n = next((n for n in zf.namelist() if n.endswith(suffix)), None)
    return zf.read(n).decode("cp1251", "replace") if n else None


def _slugify(s, cid, taken):
    base = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or f"cur{cid}"
    slug = base
    if slug in taken:
        slug = f"{base}-{cid}"
    return slug


def sync_catalog(zf):
    """Обновить currencies.json из bm_cy.dat: +новые, -удалённые, категории. Слаги существующих сохраняем."""
    cy = _member(zf, "bm_cy.dat")
    if not cy:
        print("⚠️ в дампе нет bm_cy.dat — каталог не синхронизирован")
        return
    path = os.path.join(ROOT, "currencies.json")
    existing = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"currencies": {}}
    ex_by_id = {info["id"]: (slug, info) for slug, info in existing["currencies"].items()}

    out, taken = {}, set(existing["currencies"].keys())
    added, kept = 0, 0
    for line in cy.splitlines():
        p = line.split(";")
        if len(p) < 6:
            continue
        try:
            cid = int(p[0])
        except ValueError:
            continue
        name, ticker, cat = p[2].strip(), p[3].strip(), CATCODE.get(p[5], "Прочее")
        if cid in ex_by_id:                      # существующая — сохраняем слаг/bc/имя, обновляем категорию
            slug, info = ex_by_id[cid]
            info = dict(info); info["category"] = cat
            out[slug] = info; kept += 1
        else:                                    # новая — добавляем (deep-link будет числовым)
            slug = _slugify(ticker or name, cid, taken)
            taken.add(slug)
            out[slug] = {"id": cid, "name": name, "ticker": ticker, "category": cat, "num": True}
            added += 1
    removed = len(existing["currencies"]) - kept
    cats = [c for c in CAT_ORDER if any(v["category"] == c for v in out.values())]
    json.dump({"categories": cats, "currencies": out},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"каталог: всего {len(out)} (сохранено {kept}, добавлено {added}, удалено {removed})")


def id2slug():
    cat = json.load(open(os.path.join(ROOT, "currencies.json"), encoding="utf-8"))
    return {info["id"]: slug for slug, info in cat["currencies"].items()}


def build_top(zf, i2s, limit=100):
    """Топ-популярные направления из bm_top.dat (id_from;id_to;вес) → список слаг-пар (по популярности)."""
    txt = _member(zf, "bm_top.dat")
    if not txt:
        return []
    out = []
    for line in txt.splitlines():
        p = line.split(";")
        if len(p) < 2:
            continue
        try:
            fid, tid = int(p[0]), int(p[1])
        except ValueError:
            continue
        fs, ts = i2s.get(fid), i2s.get(tid)
        if fs and ts and fs != ts:
            out.append({"from": fs, "to": ts, "w": p[2].strip() if len(p) > 2 else ""})
        if len(out) >= limit:
            break
    return out


def fmt(v):
    return "0" if v == 0 else f"{v:.6g}"


def build_pairs(rates_text, i2s):
    agg = {}
    for line in rates_text.splitlines():
        p = line.split(";")
        if len(p) < 6:
            continue
        try:
            fid, tid = int(p[0]), int(p[1])
            rf, rt = float(p[3]), float(p[4])
            reserve = float(p[5]) if p[5] else 0.0
        except ValueError:
            continue
        if rf <= 0:
            continue
        gpg = rt / rf
        a = agg.get((fid, tid))
        if a is None:
            agg[(fid, tid)] = [gpg, 1, reserve]
        else:
            a[1] += 1; a[2] += reserve
            if gpg > a[0]:
                a[0] = gpg
    pairs = {}
    for (fid, tid), (gpg, cnt, res) in agg.items():
        fs, ts = i2s.get(fid), i2s.get(tid)
        if fs and ts:
            pairs[f"{fs}>{ts}"] = {"rate": fmt(gpg), "count": cnt, "reserve": fmt(res)}
    return pairs


def main():
    key = os.environ.get("BESTCHANGE_API_KEY") or None
    url = os.environ.get("BESTCHANGE_RATES_URL") or DEFAULT_URL
    raw = download(url, key)
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise SystemExit("❌ ответ не ZIP — проверь BESTCHANGE_RATES_URL")

    sync_catalog(zf)                                     # 1) каталог валют (+/-)
    rates_text = _member(zf, "bm_rates.dat")             # 2) курсы
    if rates_text is None:
        raise SystemExit("❌ в дампе нет bm_rates.dat")
    i2s = id2slug()
    pairs = build_pairs(rates_text, i2s)
    json.dump({"generated_at": int(time.time()), "pairs": pairs},
              open(os.path.join(ROOT, "rates.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"курсы: направлений {len(pairs)}")

    top = build_top(zf, i2s)                             # 3) топ-направления для лендингов
    json.dump({"pairs": top}, open(os.path.join(ROOT, "top.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"топ-направлений: {len(top)}")


if __name__ == "__main__":
    main()
