#!/usr/bin/env python3
"""Тянет санкционный список крипто-адресов OFAC → aml-sanctions.json (для клиентского AML-чека).

Источник — публичный поддерживаемый репозиторий 0xB10C (адреса из списка OFAC SDN, по сетям).
Читаем через GitHub API с токеном (Accept: raw) — надёжно, без 429 на raw.githubusercontent в CI.
Аггрегируем адреса всех сетей в один список. Это ОФИЦИАЛЬНЫЙ санкционный список — факт, не скоринг.
Сбой сети — пропускаем эту сеть (лог), но не роняем весь список. Ephemeral (.gitignore), обновляется каждую сборку.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "0xB10C/ofac-sanctioned-digital-currency-addresses"
API = f"https://api.github.com/repos/{REPO}/contents/sanctioned_addresses_{{}}.txt?ref=lists"
# все реальные сети из ветки lists (крупные: XBT/ETH/TRX/USDT + мелкие)
CHAINS = ["XBT", "ETH", "TRX", "USDT", "USDC", "XMR", "LTC", "BCH", "DASH", "ZEC",
          "SOL", "ARB", "BSC", "ETC", "BSV", "BTG", "XRP", "XVG"]
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def fetch(chain):
    headers = {"Accept": "application/vnd.github.raw", "User-Agent": "RateScout-AML"}
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(API.format(chain), headers=headers), timeout=60) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 404:
                break
            time.sleep(2 * (attempt + 1))
        except Exception as e:                     # noqa: BLE001
            last = str(e)[:60]
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(last or "fail")


CRITICAL = {"XBT", "ETH", "TRX", "USDT"}         # без этих сетей список считаем неполным


def main():
    addrs, ok, per, failed = set(), 0, {}, set()
    for ch in CHAINS:
        try:
            got = [ln.strip() for ln in fetch(ch).splitlines() if ln.strip() and not ln.startswith("#")]
            got = [a for a in got if len(a) >= 20]
            per[ch] = len(got)
            addrs.update(got)
            ok += 1
        except Exception as e:                     # noqa: BLE001
            failed.add(ch)
            print(f"OFAC {ch}: пропуск ({e})")
        time.sleep(0.5)

    out = os.path.join(ROOT, "aml-sanctions.json")
    crit_fail = failed & CRITICAL
    degraded = bool(crit_fail) or len(addrs) < 500
    if degraded and os.path.exists(out):
        # НЕ перезаписываем полный список неполным — оставляем прошлый хороший (last-good)
        try:
            prev = json.load(open(out, encoding="utf-8")).get("count", 0)
        except (ValueError, OSError):
            prev = 0
        print(f"⚠️ неполный набор ({len(addrs)} адр., упали критичные: {sorted(crit_fail) or '—'}) — "
              f"оставляю прошлый список ({prev} адр.), не перезаписываю")
        return 0
    if degraded:
        print(f"⚠️ неполный набор ({len(addrs)} адр.) и нет прошлого файла — пишу что есть")
    json.dump({"updated": int(time.time()), "count": len(addrs), "addresses": sorted(addrs)},
              open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"aml-sanctions.json: {len(addrs)} адресов из {ok}/{len(CHAINS)} сетей "
          f"(XBT={per.get('XBT', 0)}, ETH={per.get('ETH', 0)}, TRX={per.get('TRX', 0)}, USDT={per.get('USDT', 0)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
