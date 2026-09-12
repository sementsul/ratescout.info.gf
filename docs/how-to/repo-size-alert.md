# Памятка: бот-оповещение о размере репозитория

Воркфлоу `.github/workflows/repo-size-guard.yml` следит, чтобы репозиторий не дорос до лимита
GitHub (~1 ГБ). Работает сам, вмешиваться не нужно — пока не придёт сообщение в Telegram.

## Что делает
- **Раз в неделю** (понедельник, 06:00 UTC) читает размер репо через GitHub API.
- Если размер **≥ 400 МБ** — шлёт сообщение в Telegram-бот (тот же, что и watchdog).
- Если меньше — молчит (так будет годы; сейчас репо ~3 МБ).
- **Ничего не удаляет и не пушит** — только читает и уведомляет.

## Как выглядит сообщение
> ⚠️ Репозиторий sementsul/<repo>: 420 МБ (порог 400 МБ). Память в репо растёт — пора сделать
> ручной squash истории (см. docs/project-notes.md). Мягкий лимит GitHub ~1 ГБ.

## Что делать, когда пришло сообщение
Это не авария — просто сигнал «пора почистить историю». Порядок (займёт ~1 минуту):

```bash
cd <папка проекта>            # ratescout или numstore
git branch backup-before-squash          # страховка
git checkout --orphan squashed           # новая ветка без истории
git add -A
git commit -m "chore: сжатие истории (squash baseline)"
git branch -D main
git branch -m main
git push -f origin main                   # переписывает историю на сервере
```
После пуша GitHub пересоберёт сайт как обычно. Сайт и данные не страдают — сжимается только
журнал коммитов. Когда убедился, что всё ок, `backup-before-squash` можно удалить.

> ⚠️ `git push -f` переписывает историю прод-репо — это согласуется с ПМ (Денисом).

## Как проверить, что оповещение работает (разовый тест)
1. GitHub → вкладка **Actions** → слева **repo-size-guard** → кнопка **Run workflow**.
2. Порог не достигнут → в логе будет «ниже порога — ок», в Telegram ничего (это норма).
3. Чтобы увидеть само сообщение — временно поставь в файле `THRESHOLD_MB: "1"`, запусти, получи
   алерт в бот, потом верни `"400"`.

## Настройки
- **Порог:** переменная `THRESHOLD_MB` в `repo-size-guard.yml` (по умолчанию 400 МБ).
- **Куда шлёт:** секреты репо `TELEGRAM_TOKEN` (бот) + `ALERT_CHAT_ID` (твой личный чат с ботом) —
  те же, что использует watchdog. Если алерты не приходят — проверь, что оба секрета заданы
  (Settings → Secrets and variables → Actions).
- **Как узнать свой `ALERT_CHAT_ID`:** напиши боту любое сообщение, затем открой
  `https://api.telegram.org/bot<TELEGRAM_TOKEN>/getUpdates` — там будет `chat.id`.

## Защита ветки main и keep-alive кронов
Рекомендуемая защита `main` (Settings → Branches / Rules):
- ✅ **Block deletions** — от случайного сноса ветки.
- ✅ **Block force pushes** — от случайного `push -f`.
- ❌ **Require pull request / status checks** — НЕ включать: заблокирует прямые пуши.

**Почему нельзя require PR/checks:** кроны деплоя/данных пушат прямо в `main`, а keep-alive
(GitHub гасит scheduled-кроны после 60 дней «без активности»; коммиты `GITHUB_TOKEN` активностью
НЕ считаются) держится на **PAT-пуше** (`DEPLOY_TOKEN`). Require-PR/checks убьёт прямой PAT-пуш →
кроны уснут.

**Совместимость:** keep-alive PAT-пуш — обычный fast-forward, «Block force pushes» ему НЕ мешает.
Force-push нужен только для ручного squash → перед ним временно снять «Block force pushes»:
1. Settings → снять **Block force pushes**.
2. Squash (см. выше) → `git push -f origin main`.
3. Вернуть **Block force pushes**.
