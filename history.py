#!/usr/bin/env python3
"""Накопление истории курсов RateScout → history.json (для графиков на страницах валют).

Один снимок В ДЕНЬ на валюту: «цена в USDT» = лучший курс `slug → tether-trc20`
(сколько USDT за 1 единицу). Отслеживаем валюты, у которых такой курс есть (в основном крипта).
history.json коммитится обратно в репозиторий в CI — так точки накапливаются между запусками.

Формат history.json:
  {"generated_at": <ts>, "unit": "USDT",
   "series": {"<slug>": [["YYYY-MM-DD", <rate:float>], ...]}}
Точки — по одной на дату (повторный запуск в тот же день перезаписывает значение), хранятся последние KEEP.
"""
import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
USDT = "tether-trc20"        # опорная валюта (стейблкоин ≈ доллар)
# Двухуровневое хранение: последние RECENT_H часов — почасово (детализация),
# старше — по одной точке в день (long-term), до KEEP_DAILY дней (~10 лет).
RECENT_H = 72
KEEP_DAILY = 3660


def _parse(k):
    try:
        return datetime.strptime(k, "%Y-%m-%d %H:00").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.strptime(k, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _compress(pts, now):
    """Старше RECENT_H — сжать до одной точки в день (последняя за день); недавние — как есть."""
    cutoff = now.timestamp() - RECENT_H * 3600
    old, recent = {}, []
    for k, v in pts:
        if _parse(k).timestamp() >= cutoff:
            recent.append([k, v])
        else:
            old[k[:10]] = [k[:10], v]        # последняя за дату побеждает (точки идут по возрастанию)
    daily = [old[d] for d in sorted(old)][-KEEP_DAILY:]
    return daily + recent

def _load(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return default


def main():
    cur = _load(os.path.join(ROOT, "currencies.json"), {"currencies": {}})["currencies"]
    rates = _load(os.path.join(ROOT, "rates.json"), {}).get("pairs", {})
    hist = _load(os.path.join(ROOT, "history.json"), {"unit": "USDT", "series": {}})
    series = hist.get("series", {})
    now = datetime.now(timezone.utc)
    bucket = now.strftime("%Y-%m-%d %H:00")  # почасовая корзина (UTC)

    added = 0
    for slug in cur:
        if slug == USDT:
            continue
        r = rates.get(f"{slug}>{USDT}")
        if not r:
            continue
        try:
            val = float(r["rate"])
        except (KeyError, ValueError, TypeError):
            continue
        if val <= 0:
            continue
        pts = series.get(slug, [])
        if pts and pts[-1][0] == bucket:     # точка за этот час уже есть — один снимок в час
            continue
        pts.append([bucket, val]); added += 1
        series[slug] = _compress(pts, now)   # почасово недавние + по дню старые

    if added == 0 and os.path.exists(os.path.join(ROOT, "history.json")):
        print(f"история: за {bucket} уже записано — файл не меняю (нет лишних коммитов)")
        return
    hist = {"generated_at": int(datetime.now(timezone.utc).timestamp()),
            "unit": "USDT", "series": series}
    json.dump(hist, open(os.path.join(ROOT, "history.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"история: серий {len(series)}, новых точек за {bucket}: {added}")


if __name__ == "__main__":
    main()
