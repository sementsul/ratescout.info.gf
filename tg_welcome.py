#!/usr/bin/env python3
"""Разовая отправка приветственного поста в Telegram-канал (для закрепа).

Публикует статичный пост с кнопками (мини-приложение, обзор, графики, сайт). НЕ закрепляет сам —
закрепляет вручную владелец. Токен/канал — только из окружения (GitHub Secrets). Запуск: вручную (tg-welcome.yml).
Без секретов — сухой прогон (печатает, не публикует).
"""
import json
import os
import sys
import urllib.parse
import urllib.request

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL = os.environ.get("TELEGRAM_CHANNEL")
BASE = "https://ratescout.info.gf"
MINIAPP = "https://t.me/RateScoutRUBot/ratescout_ru"

CAPTION = (
    "📊 RateScout — курсы обмена криптовалют и ежедневный обзор рынка\n\n"
    "Каждый день: топ роста и падения за сутки с графиками. USDT, BTC, ETH и 300+ валют, "
    "выгодные направления обмена по данным мониторинга обменников.\n\n"
    "🚀 Мини-приложение: конвертер, поиск валют, топ за сутки.\n"
    "📰 Мы также в Дзене: https://dzen.ru/ratescout\n"
    "🅥 И во ВКонтакте: https://vk.com/ratescout\n"
    "🐘 Mastodon: https://mastodon.social/@ratescout_ru\n"
    "📝 Blog: https://blogger.ratescout.info.gf/\n\n"
    "ℹ️ Справочный сервис (мониторинг курсов), не обменный пункт. Не является финансовой рекомендацией."
)
BUTTONS = [
    [{"text": "🚀 Приложение", "url": MINIAPP}],
    [{"text": "📊 Обзор за сутки", "url": BASE + "/obzor/sutki/"}, {"text": "📈 Графики", "url": BASE + "/grafiki/"}],
    [{"text": "💱 Все курсы на сайте", "url": BASE + "/"}],
    [{"text": "📰 Дзен", "url": "https://dzen.ru/ratescout"},
     {"text": "🅥 ВКонтакте", "url": "https://vk.com/ratescout"}],
]


def main():
    if not TOKEN or not CHANNEL:
        print("TELEGRAM_TOKEN/TELEGRAM_CHANNEL не заданы — сухой прогон.\n--- пост ---")
        print(CAPTION)
        return 0
    payload = {
        "chat_id": CHANNEL,
        "photo": BASE + "/assets/og-image.png",
        "caption": CAPTION,
        "reply_markup": json.dumps({"inline_keyboard": BUTTONS}),
    }
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendPhoto" % TOKEN,
                                 data=urllib.parse.urlencode(payload).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except Exception as e:                      # noqa: BLE001
        print(f"ошибка отправки: {e}")
        return 1
    if res.get("ok"):
        mid = res["result"]["message_id"]
        print(f"опубликовано, message_id={mid}. Закрепи этот пост вручную в канале.")
        return 0
    print(f"ошибка Telegram: {res}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
