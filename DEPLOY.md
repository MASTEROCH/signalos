# Деплой SignalOS (живая ссылка)

GitHub Pages показывает только демо-фронт. Для рабочего SaaS нужен бэкенд-хостинг.
Репозиторий готов к деплою (Docker). Любой вариант даёт публичный URL за ~5 минут.

## Render.com (бесплатно, проще всего)
1. Зайди на https://render.com → войди через GitHub.
2. **New → Blueprint** → выбери репозиторий `MASTEROCH/signalos` → Apply.
   (Render прочитает `render.yaml`: web-сервис на Docker + диск 1GB для данных.)
3. Через пару минут получишь ссылку вида `https://signalos.onrender.com` — рабочую.
4. (Опц.) В Environment добавь `SIGNALOS_PLATFORM_KEY` = твой Anthropic-ключ,
   чтобы продавать токены (платформенный ИИ). Без него юзеры используют свой ключ.

## Railway.app (тоже просто)
1. https://railway.app → New Project → Deploy from GitHub → `MASTEROCH/signalos`.
2. Railway сам соберёт Dockerfile, выдаст домен в Settings → Generate Domain.
3. Добавь Volume на `/data` для постоянной БД.

## Fly.io / VPS
Любой хостинг с Docker: `docker build -t signalos . && docker run -p 8000:8000 -v $PWD/data:/data signalos`.

## Важно
- БД — SQLite в `/data`. Примонтируй диск/volume, иначе данные сбросятся при редеплое.
- Для своего домена (например signalos.app) — добавь его в настройках хостинга (CNAME).
