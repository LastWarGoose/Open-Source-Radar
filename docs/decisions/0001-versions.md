# 0001. Версии и границы этапа 0

Дата: 17 ноября 2026. Статус: принято; совместимость компонентов этапа 0 подтверждена. [Отчёт](../evidence/stage0-2026-11-17.md).

## Окружение

Windows 10 Pro 10.0.19045, 12 логических CPU, 16 497 397 760 байт RAM.
Docker Desktop: Engine 29.9.2, Compose 5.6.1, Linux backend, 12 CPU,
7 990 951 936 байт RAM. uv 0.13.7. Исходно Git-репозитория и Node в PATH не было.
Git инициализирован без изменения глобальных настроек и без remote.

## Закреплённая матрица

| Компонент | Версия | Проверка в этапе 0 |
|---|---|---|
| Python | 3.12.16 | Подграфы и тесты; локально и Linux-контейнеры |
| uv | 0.13.7 | `uv.lock`, frozen installation |
| Node.js | 24.22.3 LTS | Gateway, Next.js, инструменты |
| pnpm | 12.21.0 | `pnpm-lock.yaml`, frozen installation |
| Next.js | 16.4.6 | App Router, SSR, клиентская работа |
| React / React DOM | 19.3.1 | Интерфейс |
| TypeScript | 5.9.3 | Проверка типов |
| Apollo Client | 4.3.8 | Query, mutation, subscription |
| Apollo Next integration | 0.14.5 | Изоляция RSC-клиента по запросу |
| GraphQL JS | 16.15.0 | Общий диапазон Hive и composition; GraphQL 17 пока не выбираем |
| graphql-ws | 6.4.2 | `graphql-transport-ws`, reconnect |
| Strawberry | 0.341.2 | Federation 2.7, FastAPI, WebSocket |
| FastAPI / Uvicorn | 0.163.1 / 0.54.0 | Два отдельных ASGI-процесса |
| Hive Gateway | 2.15.2 | Единый публичный GraphQL endpoint |
| Apollo composition | 2.14.4 | Локальная композиция SDL без облачного реестра |
| Codegen CLI / client preset | 8.0.0 / 7.0.0 | TypedDocumentNode и клиентские типы |
| Playwright | 1.65.1 | Сквозной браузерный сценарий |
| Celery | 5.7.0 | Выбран для этапа 1; очередь ещё не проверяется |
| PostgreSQL | 18.7 | Выбран для этапа 1; хранение ещё не проверяется |
| RabbitMQ | 4.4.1 | Выбран для этапа 1; доставка ещё не проверяется |
| Redis | 7.4.12 | Выбран для этапа 1; кеш ещё не проверяется |

Транзитивные версии и хеши сохранены в lock-файлах. Tailwind/shadcn и полная
система оформления подключаются на этапе интерфейса; текущая страница использует
небольшой CSS для проверки сценария.

Hive 2.15.8 с автоматически выбранными зависимостями дал несовместимые peer ranges:
runtime требовал Envelop 5, а generic-auth — Envelop 6; OpenTelemetry SDK требовал
API ниже 1.10. Выбран Hive 2.15.2 с runtime 2.12.2, plugin-opentelemetry 1.5.4,
plugin-prometheus 2.2.4 и OpenTelemetry API 1.9.1. Эти версии закреплены overrides
в пределах заявленных диапазонов выбранного Hive; `pnpm peers check` проходит.
Предупреждения о deprecated транзитивных пакетах остаются задачей обновления стека;
модули полной телеметрии пока не включены.

## Транспорт и данные

HTTP POST для query/mutation; WebSocket с `graphql-transport-ws` для подписок
между браузером, Hive и Catalog. Hive дополняет каждое событие полями Repositories.
SSR использует отдельный Apollo-клиент на запрос и обращается к Hive.
Браузер использует Apollo Next provider, HTTP link и GraphQLWsLink.

Подписка сначала отдаёт текущий снимок. После подключения/переподключения клиент
повторяет query состояния. Промежуточные события могут объединяться; обещания
доставки истории нет. Состояние этапа 0 хранится в памяти одного Catalog-процесса
и сбрасывается при его перезапуске. Это техническая проверка, не реализация Job.

Два фиксированных пакета; значения stars вымышлены и явно помечены в интерфейсе.
Внешние API, импорт, пользователи и долговременное хранение не входят в этап 0.
Подграфы не имеют host-портов; web и gateway опубликованы только на loopback.
Неаутентифицированная демонстрационная mutation допустима только локально.

## Источники выбора

- [Node.js: жизненный цикл](https://nodejs.org/en/about/previous-releases)
- [Next.js: установка](https://nextjs.org/docs/app/getting-started/installation)
- [Apollo: интеграция Next.js](https://www.apollographql.com/docs/react/integrations/nextjs)
- [Strawberry Federation](https://strawberry.rocks/docs/federation/introduction)
- [Strawberry FastAPI](https://strawberry.rocks/docs/integrations/fastapi)
- [Hive Gateway](https://the-guild.dev/graphql/hive/docs/gateway)
- [Hive: федеративные подписки](https://the-guild.dev/graphql/hive/docs/gateway/subscriptions)
- [Celery: брокеры](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html)
- [PostgreSQL: поддерживаемые версии](https://www.postgresql.org/support/versioning/)
- [RabbitMQ: версии](https://www.rabbitmq.com/release-information)
- [Redis: release notes](https://github.com/redis/redis/releases)
- [pnpm: настройка сборки зависимостей](https://pnpm.io/settings/build)

Номера npm/PyPI проверены через официальные реестры пакетов. Совместимость
подтверждается результатами запуска в `docs/evidence/`, а не только документацией.
