#!/usr/bin/env python3
"""Тянет рыночные метрики из CoinGecko (бесплатно, без ключа) → market.json для сборки.

Берёт топ по капитализации (2 страницы = 500 монет), сопоставляет с нашими крипто-валютами по тикеру
(символу) — вариант с большей капитализацией выигрывает коллизии символов. Пишет по каждому найденному
слагу: капитализацию, ранг, объём 24ч, ATH и % от ATH, циркулирующее предложение, изменение 7д/30д.
Это ФАКТЫ рынка (не сигналы). Ключ не нужен; опц. COINGECKO_KEY (demo) — против лимитов. Сбой — тихо пропускаем,
сборка идёт без рыночных данных.
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CUR = json.load(open(os.path.join(ROOT, "currencies.json"), encoding="utf-8"))["currencies"]
API = "https://api.coingecko.com/api/v3/coins/markets"


def fetch_page(page):
    params = (f"vs_currency=usd&order=market_cap_desc&per_page=250&page={page}"
              "&price_change_percentage=7d,30d")
    req = urllib.request.Request(f"{API}?{params}",
                                 headers={"User-Agent": "RateScout", "Accept": "application/json"})
    key = os.environ.get("COINGECKO_KEY")
    if key:
        req.add_header("x-cg-demo-api-key", key)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    sym = {}
    for page in (1, 2):                       # топ-500 по капитализации — покрывает наши монеты
        try:
            data = fetch_page(page)
        except Exception as e:                # noqa: BLE001
            print(f"CoinGecko страница {page}: ошибка {e}")
            break
        for c in data:
            s = (c.get("symbol") or "").upper()
            if s and s not in sym:            # первый = выше по капитализации → выигрывает коллизию символа
                sym[s] = c
        time.sleep(3)                         # вежливо к бесплатному лимиту

    coins = {}
    for slug, info in CUR.items():
        if info.get("category") != "Криптовалюты":
            continue
        c = sym.get((info.get("ticker") or "").upper())
        if not c or not c.get("market_cap"):
            continue
        coins[slug] = {
            "mcap": c.get("market_cap"), "rank": c.get("market_cap_rank"),
            "vol": c.get("total_volume"), "ath": c.get("ath"),
            "ath_chg": c.get("ath_change_percentage"), "supply": c.get("circulating_supply"),
            "chg7d": c.get("price_change_percentage_7d_in_currency"),
            "chg30d": c.get("price_change_percentage_30d_in_currency"),
        }
    out = os.path.join(ROOT, "market.json")
    json.dump({"generated_at": int(time.time()), "coins": coins},
              open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"market.json: {len(coins)} монет сопоставлено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
