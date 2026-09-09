#!/usr/bin/env python3
"""VK ID (OAuth 2.1 + PKCE) — получить «вечный» refresh-токен для авто-постинга фото/видео в ВК.

Заточен под ТЕРМИНАЛ без браузера и без проброшенных портов: НИКАКОГО локального сервера/колбэка.
Схема — копипаст:
  1) скрипт печатает ссылку авторизации;
  2) открываешь её в браузере НА ЛЮБОМ устройстве (телефон/другой ПК), логинишься под админом группы,
     жмёшь «Разрешить»;
  3) VK перебросит на страницу-заглушку — её адрес будет вида
        https://oauth.vk.com/blank.html?code=...&device_id=...&state=...
     СКОПИРУЙ этот адрес целиком и вставь обратно в терминал;
  4) скрипт меняет code→refresh и (если есть gh) сам пишет секреты VK_REFRESH_TOKEN/VK_DEVICE_ID,
     иначе печатает их у тебя на экране (в чат НЕ кидай).

Запуск (ничего указывать не надо):  python3 vk_id_bootstrap.py

По умолчанию настроено на веб-приложение VK ID app_id=54760537 и redirect https://ratescout.info.gf/.
Перед запуском (ОДИН раз) в dev.vk.com у приложения 54760537 (тип «Веб-сайт») проверь:
   • приложение включено;
   • Базовый домен: ratescout.info.gf
   • Доверенный redirect URI: https://ratescout.info.gf/  (ровно так, со слэшем)

Переопределить при желании через env:
   VK_CLIENT_ID (54760537), VK_REDIRECT (https://ratescout.info.gf/), GH_REPO (sementsul/ratescout)
"""
import base64
import getpass
import hashlib
import json
import os
import secrets
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request

# Контекст TLS: берём корневые сертификаты из certifi, если он есть (частая беда Python на Windows —
# нет локального хранилища CA → SSLCertVerificationError). Если certifi нет — обычный дефолтный контекст,
# а при провале проверки в post() делаем разовый фолбэк без проверки (с предупреждением).
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:                                                 # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()
_SSL_INSECURE = None                                              # ленивый небезопасный контекст (последний фолбэк)

CLIENT_ID = os.environ.get("VK_CLIENT_ID", "54760537")            # веб-приложение VK ID (app id — не секрет)
REDIRECT = os.environ.get("VK_REDIRECT", "https://ratescout.info.gf/")  # свой домен = доверенный redirect у приложения
SCOPE = "video photos wall groups"
AUTH = "https://id.vk.com/authorize"
TOKEN = "https://id.vk.com/oauth2/auth"
REPO = os.environ.get("GH_REPO", "sementsul/ratescout")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def post(data):
    req = urllib.request.Request(TOKEN, data=urllib.parse.urlencode(data).encode(),
                                 headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})

    def _do(ctx):
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return json.load(r)

    try:
        return _do(_SSL_CTX)
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode("utf-8", "replace")}
    except ssl.SSLCertVerificationError:
        # на машине нет корневых CA (частая беда Python на Windows) — разово повторяем без проверки сертификата
        global _SSL_INSECURE
        if _SSL_INSECURE is None:
            print("⚠️ TLS: Python не может проверить сертификат (нет корневых CA на этой машине). "
                  "Повторяю запрос БЕЗ проверки сертификата. Для чистоты потом выполни: pip install certifi", flush=True)
            _SSL_INSECURE = ssl.create_default_context()
            _SSL_INSECURE.check_hostname = False
            _SSL_INSECURE.verify_mode = ssl.CERT_NONE
        try:
            return _do(_SSL_INSECURE)
        except urllib.error.HTTPError as e:
            return {"_http": e.code, "_body": e.read().decode("utf-8", "replace")}


def parse_pasted(text):
    """Из вставленного адреса (или голых параметров) достаём code/device_id/state."""
    text = text.strip()
    q = text.split("?", 1)[1] if "?" in text else text
    q = q.replace("#", "&")                       # на случай, если параметры во фрагменте
    return {k: v[0] for k, v in urllib.parse.parse_qs(q).items()}


def set_secret(name, val):
    """Пишем секрет через gh CLI (если установлен и залогинен). True — успех."""
    try:
        subprocess.run(["gh", "secret", "set", name, "--repo", REPO, "--body", val],
                       check=True, capture_output=True)
        return True
    except Exception:                             # noqa: BLE001 — gh нет/не залогинен/нет прав
        return False


def main():
    # Приложение типа «Веб-сайт» у VK ID — confidential client: на обмене кода нужен client_secret
    # («Защищённый ключ» из настроек приложения). Вводишь сам, скрыто; в чат/логи не попадёт.
    client_secret = os.environ.get("VK_CLIENT_SECRET")
    if not client_secret:
        try:
            client_secret = getpass.getpass(
                'Вставь «Защищённый ключ» (client_secret) приложения и Enter '
                '(ввод скрыт; если приложение публичное — просто Enter): ').strip()
        except Exception:                         # noqa: BLE001
            client_secret = ""

    verifier = b64url(secrets.token_bytes(48))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_hex(8)
    url = AUTH + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": CLIENT_ID, "scope": SCOPE,
        "redirect_uri": REDIRECT, "state": state,
        "code_challenge": challenge, "code_challenge_method": "s256"})

    print("\n=== VK ID: получение refresh-токена (копипаст, без портов) ===")
    print(f"redirect_uri (должен быть в «Доверенные redirect URI» приложения): {REDIRECT}\n")
    print("1) Открой ЭТУ ссылку в браузере (телефон/любой ПК), войди под админом группы и нажми «Разрешить»:\n")
    print(url + "\n")
    print("2) После «Разрешить» VK перебросит на страницу-заглушку — скопируй её АДРЕС ЦЕЛИКОМ")
    print("   (в нём будут code= и device_id=) и вставь сюда.\n")

    pasted = input("Вставь адрес (или строку с code=...&device_id=...): ").strip()
    print(f"(принято символов: {len(pasted)}; секрет введён: {'да' if client_secret else 'нет'})", flush=True)
    p = parse_pasted(pasted)
    code = p.get("code")
    device_id = p.get("device_id", "")
    if not code:
        print("\n❌ В том, что вставлено, нет параметра code. Скопируй адрес заглушки целиком и попробуй снова.")
        return
    if p.get("state") and p["state"] != state:
        print("\n❌ state не совпал — прерываю (возможная подмена/чужая ссылка).")
        return
    if not device_id:
        print("\n❌ Нет device_id в адресе — без него токен не обновить. Проверь тип приложения (нужен не Mini App).")
        return

    ex = {"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
          "client_id": CLIENT_ID, "device_id": device_id, "redirect_uri": REDIRECT, "state": state}
    if client_secret:
        ex["client_secret"] = client_secret
    r = post(ex)
    if "refresh_token" not in r:
        body = json.dumps(r, ensure_ascii=False)[:800]
        print("\n❌ Обмен code→токены не удался:", body, flush=True)
        try:                                      # дублируем ошибку в файл — в ней НЕТ токенов, безопасно
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vk_debug.txt"),
                      "w", encoding="utf-8") as f:
                f.write("Обмен code->токен не удался. Ответ VK:\n" + body + "\n")
        except Exception:                         # noqa: BLE001
            pass
        if not client_secret:
            print("Похоже, приложение типа «Веб-сайт» — ему нужен «Защищённый ключ» (client_secret). "
                  "Запусти снова и вставь его в скрытый запрос.")
        return
    refresh = r["refresh_token"]
    print("\n✅ Токены получены. access живёт", r.get("expires_in"), "сек. Выданный VK scope:", r.get("scope"))

    # тест ротации: обновим один раз (как в CI — БЕЗ scope; VK отклонял scope на refresh с invalid_scope)
    rf = {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": CLIENT_ID, "device_id": device_id}
    if client_secret:
        rf["client_secret"] = client_secret
    r2 = post(rf)
    if not r2.get("access_token"):                # фолбэк со scope, если без него не вышло
        rf["scope"] = SCOPE
        r2 = post(rf)
    rotated = ("refresh_token" in r2 and r2["refresh_token"] != refresh)
    latest = r2.get("refresh_token", refresh)

    # пробуем записать секреты сами (gh CLI); иначе — печатаем/пишем в файл для ручного добавления.
    # VK_CLIENT_ID тоже в секреты: refresh «привязан» к приложению — CI обязан обновлять его тем же id.
    # VK_CLIENT_SECRET нужен, если приложение «Веб-сайт» (confidential) — иначе CI не обновит токен.
    ok = set_secret("VK_REFRESH_TOKEN", latest) and set_secret("VK_DEVICE_ID", device_id) \
        and set_secret("VK_CLIENT_ID", CLIENT_ID) \
        and (set_secret("VK_CLIENT_SECRET", client_secret) if client_secret else True)
    print()
    if ok:
        names = "VK_REFRESH_TOKEN, VK_DEVICE_ID, VK_CLIENT_ID" + (", VK_CLIENT_SECRET" if client_secret else "")
        print(f"✅ Секреты ({names}) записаны в репозиторий {REPO} автоматически (gh).")
    else:
        # gh нет — сохраняем в локальный файл (в .gitignore), чтобы значения не потерялись при закрытии окна
        fn = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vk_secrets.txt")
        lines = [f"VK_REFRESH_TOKEN={latest}", f"VK_DEVICE_ID={device_id}", f"VK_CLIENT_ID={CLIENT_ID}"]
        if client_secret:
            lines.append(f"VK_CLIENT_SECRET={client_secret}")
        try:
            with open(fn, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            saved_to = f"\nТакже сохранил их в файл: {fn} (после переноса — УДАЛИ этот файл)."
        except Exception as e:                    # noqa: BLE001
            saved_to = f"\n(в файл записать не смог: {e} — скопируй из окна)"
        print("gh не установлен — добавь секреты ВРУЧНУЮ")
        print(f"(GitHub → {REPO} → Settings → Secrets and variables → Actions → New repository secret):")
        print("  VK_REFRESH_TOKEN =", latest)
        print("  VK_DEVICE_ID     =", device_id)
        print("  VK_CLIENT_ID     =", CLIENT_ID, "(это app id, не секрет — но CI берёт его отсюда)")
        if client_secret:
            print("  VK_CLIENT_SECRET = <тот «Защищённый ключ», что ты вводил> (нужен CI для обновления токена)")
        print(saved_to)
    print("\nrefresh ротируется:", "ДА (постер сам сохраняет новый через шаг workflow)" if rotated
          else "нет (можно хранить статично)")
    print("\nГотово. Запусти Actions → «VK daily digest» — в посте должна появиться картинка.")


if __name__ == "__main__":
    try:
        main()
    except Exception:                             # noqa: BLE001
        # ВАЖНО: печатаем ошибку ДО паузы, иначе traceback уходит ниже «Нажми Enter» и его не видно;
        # плюс дублируем в файл vk_debug.txt (в тексте ошибки токенов нет)
        import traceback
        tb = traceback.format_exc()
        print("\n❌ Скрипт упал с ошибкой:\n" + tb, flush=True)
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vk_debug.txt"),
                      "w", encoding="utf-8") as f:
                f.write(tb)
        except Exception:                         # noqa: BLE001
            pass
    finally:                                      # окно консоли (особенно на Windows) не закрываем,
        try:                                      # пока не увидишь результат
            input("\n— Нажми Enter, чтобы закрыть окно —")
        except EOFError:
            pass
