#!/usr/bin/env python3
"""Индекс страха и жадности (Crypto Fear & Greed) из бесплатного API alternative.me → fng.json для сборки.

Ключ не нужен. Сбой — сборка идёт без индекса (блок просто не рендерится). Ephemeral (.gitignore).
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    try:
        req = urllib.request.Request("https://api.alternative.me/fng/?limit=1",
                                     headers={"User-Agent": "RateScout"})
        d = json.load(urllib.request.urlopen(req, timeout=30))["data"][0]
        out = {"value": int(d["value"]), "class": d.get("value_classification", ""), "ts": int(d["timestamp"])}
    except Exception as e:                         # noqa: BLE001
        print(f"fng: ошибка {e}")
        return 0
    json.dump(out, open(os.path.join(ROOT, "fng.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"fng: {out['value']} ({out['class']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
