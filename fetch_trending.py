#!/usr/bin/env python3
"""Тянет «что сейчас в тренде поиска» из CoinGecko (/search/trending, бесплатно) → trending.json.

Это свежий поисковый спрос по крипте (топ трендовых монет на CoinGecko) — не требует накопления, как GSC.
Сопоставляем трендовые монеты с нашими крипто-валютами по тикеру (symbol), чтобы можно было открыть/построить.
Ключ не нужен; опц. COINGECKO_KEY (demo) — против лимитов. Сбой — тихо пропускаем, сборка идёт без тренда.
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CUR = json.load(open(os.path.join(ROOT, "currencies.json"), encoding="utf-8"))["currencies"]
API = "https://api.coingecko.com/api/v3/search/trending"


def main():
    # symbol(верхний) -> наш slug (только крипта; первый по порядку выигрывает коллизию символа)
    sym2slug = {}
    for slug, info in CUR.items():
        if info.get("category") != "Криптовалюты":
            continue
        t = (info.get("ticker") or "").upper()
        if t and t not in sym2slug:
            sym2slug[t] = slug

    req = urllib.request.Request(API, headers={"User-Agent": "RateScout", "Accept": "application/json"})
    key = os.environ.get("COINGECKO_KEY")
    if key:
        req.add_header("x-cg-demo-api-key", key)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except Exception as e:  # noqa: BLE001
        print(f"CoinGecko trending: ошибка {e} — пропускаю")
        return 0

    coins = []
    for it in data.get("coins", []):
        item = it.get("item", {}) or {}
        sym = (item.get("symbol") or "").upper()
        chg = None
        d = item.get("data") or {}
        pc = d.get("price_change_percentage_24h")
        if isinstance(pc, dict):
            chg = pc.get("usd")
        coins.append({
            "name": item.get("name"),
            "symbol": sym,
            "rank": item.get("market_cap_rank"),
            "slug": sym2slug.get(sym, ""),   # наш slug, если валюта у нас есть
            "chg24h": chg,
        })
    out = os.path.join(ROOT, "trending.json")
    json.dump({"generated_at": int(time.time()), "coins": coins},
              open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"trending.json: {len(coins)} трендовых монет ({sum(1 for c in coins if c['slug'])} сопоставлено с нашими)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
