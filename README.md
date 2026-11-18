# Open Source Radar

[![Проверки main](https://github.com/LastWarGoose/Open-Source-Radar/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LastWarGoose/Open-Source-Radar/actions/workflows/ci.yml?query=branch%3Amain)

Open Source Radar помогает выбрать Python-библиотеку. В каталоге можно искать по названию и описанию, фильтровать по лицензии и сортировать по звёздам GitHub. В карточке собраны версии и зависимости из PyPI, репозитории GitHub и известные уязвимости OSV с версиями исправлений. До четырёх пакетов можно сравнить по общей ссылке. В личном кабинете доступны подборки и уведомления.

## Локальный запуск

Понадобятся Docker с Linux-контейнерами, Docker Compose и Python 3.12. Из корня репозитория выполните

```sh
python scripts/bootstrap.py
docker compose up --build -d --wait
```

Откройте [сайт](http://localhost:3000/), [личный кабинет](http://localhost:3000/account) или [GraphQL](http://localhost:4000/graphql). Новый экземпляр запускается с пустым каталогом. Пакеты загружаются фоновым импортом. Для наполнения используйте [порядок назначения администратора](docs/decisions/0007-accounts.md) и [протокол импорта](docs/decisions/0006-bulk-import.md).

```sh
docker compose ps
docker compose logs --tail 50 web gateway
docker compose down
```

Обычная остановка сохраняет базу. Сохраните созданный `.env` вместе с локальными томами. Порты сайта и шлюза привязаны к loopback.

## Разработка и проверки

```sh
uv sync --frozen
pnpm install --frozen-lockfile
uv run pytest -q
pnpm lint
pnpm typecheck
pnpm build
```

После изменений GraphQL выполните `uv run python -m scripts.export_schema`, `pnpm compose:schema`, пересоберите подграфы и шлюз, затем запустите `pnpm codegen`. Браузерные проверки с тестовыми записями и отключением сервисов запускайте на отдельном стенде. [Полный сценарий CI](.github/workflows/ci.yml) · [план проверок](docx/TEST_PLAN.md).

## Документация

- [Архитектура и владельцы данных](docx/ARCHITECTURE.md) · [этапы проекта](docx/DEVELOPMENT_PLAN.md).
- [Публичный каталог и сравнение](docs/decisions/0005-public-site.md) · [контракты GraphQL](docs/decisions/0003-domain-contracts.md).
- [Источники данных](docs/decisions/0004-source-imports.md) · [массовый импорт](docs/decisions/0006-bulk-import.md) · [замеры на 10 002 пакетах](docs/evidence/stage5-2026-11-17.md).
- [Мониторинг и восстановление](docs/decisions/0008-observability.md) · [результаты нагрузочных испытаний](docs/evidence/stage7-2026-11-18.md).
- [Версии стека](docs/decisions/0001-versions.md) · [локальная инфраструктура](docs/decisions/0002-development-infrastructure.md).
