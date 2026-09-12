#!/usr/bin/env python3
"""Запись/чтение статистики сайтов в Baserow (одна таблица-хаб для всех кронов).

Секрет BASEROW_TOKEN (database-токен Baserow, права rows). Таблица — BASEROW_TABLE (по умолч. 1182998),
колонки: date, site, source, metric, value, note. 🔴 Обязателен браузерный User-Agent: без него
Cloudflare перед api.baserow.io отдаёт 403. Без токена — тихий no-op (кроны не ломаются).
"""
import datetime
import json
import os
import urllib.error
import urllib.request

_TOKEN = (os.environ.get("BASEROW_TOKEN") or "").strip()
_TABLE = os.environ.get("BASEROW_TABLE", "1182998")
_BASE = "https://api.baserow.io/api/database"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")


def _hdr():
    return {"Authorization": "Token " + _TOKEN, "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": _UA}


def stat_rows(site, source, metrics, date=None):
    """metrics = {metric_name: value} → список строк для put_rows (нечисловые/None пропускаются)."""
    d = date or datetime.date.today().isoformat()
    out = []
    for m, v in metrics.items():
        if v is None:
            continue
        try:
            val = float(v)
        except (ValueError, TypeError):
            continue
        out.append({"date": d, "site": site, "source": source, "metric": m, "value": val})
    return out


def put_rows(rows):
    """Пишет строки батчем. Возвращает True/False. Без токена — no-op (True)."""
    if not _TOKEN:
        print(f"BASEROW_TOKEN не задан — в базу не пишу ({len(rows)} строк).")
        return True
    if not rows:
        return True
    url = f"{_BASE}/rows/table/{_TABLE}/batch/?user_field_names=true"
    body = json.dumps({"items": rows}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers=_hdr())
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            n = len(json.load(r).get("items", []))
        print(f"Baserow: записано {n} строк ({rows[0].get('source')}).")
        return True
    except urllib.error.HTTPError as e:
        print(f"Baserow write error {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
        return False
    except Exception as e:                       # noqa: BLE001
        print(f"Baserow write exc: {e}")
        return False


def read_rows(source=None, site=None, size=200):
    """Чтение из базы (пример для крона, который забирает инфо обратно)."""
    if not _TOKEN:
        return []
    url = f"{_BASE}/rows/table/{_TABLE}/?user_field_names=true&size={size}&order_by=-date"
    req = urllib.request.Request(url, headers=_hdr())
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            items = json.load(r).get("results", [])
    except Exception as e:                        # noqa: BLE001
        print(f"Baserow read exc: {e}")
        return []
    return [x for x in items
            if (not source or x.get("source") == source) and (not site or x.get("site") == site)]


if __name__ == "__main__":               # ручной тест: python3 baserow.py  → запись+чтение
    ok = put_rows(stat_rows("test", "manual", {"ping": 1}))
    print("write ok:", ok, "| последних строк:", len(read_rows()))
