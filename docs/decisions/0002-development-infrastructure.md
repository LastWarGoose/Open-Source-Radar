# 0002. Инфраструктура разработки и пробная фоновая задача

Дата: 17 ноября 2026. Этап 1; локальный Docker Compose, один хост.

## Версии

Стек этапа 0 сохранён. Добавлены PostgreSQL `18.7-bookworm`, RabbitMQ
`4.4.0-management`, Redis `7.4.12-alpine`, Celery 5.7.0, SQLAlchemy 2.1.9,
psycopg 3.3.9, Alembic 1.20.1, redis-py 8.1.0, mypy 2.4.1,
ESLint 9.39.5 / eslint-config-next 16.4.6, Prettier 3.10.1.
Зависимости закреплены в `uv.lock` и `pnpm-lock.yaml`.

В решении 0001 для RabbitMQ предварительно выбрана 4.4.1. Docker Registry
не предоставил тег `4.4.1-management` при фактической загрузке. Используется
доступный конкретный тег `4.4.0-management`; он проверяется с Celery в этом этапе.
ESLint 10 не подходит peer-диапазонам плагинов выбранного Next.js, поэтому закреплена 9.39.5.

## Изоляция, хранение и запуск

- PostgreSQL один, базы и роли `catalog`, `repositories`, `security`, `workspace`
  раздельные. PUBLIC лишён доступа; роли не superuser и не создают базы/роли.
  Каждое приложение получает только пароль своей базы. Мигратор и тестовый
  контейнер получают четыре пароля для последовательного обслуживания владельцев.
- PostgreSQL 18 хранит volume на `/var/lib/postgresql`, RabbitMQ — на
  `/var/lib/rabbitmq` с постоянным hostname, Redis — на `/data` с AOF.
- `backend` — внутренняя сеть, host-портов у инфраструктуры и подграфов нет.
  Web находится в `edge`; Gateway соединяет сети. Порты 3000/4000 только loopback.
- Пароли создаёт `scripts/bootstrap.py`, `.env` исключён из Git и Docker context.
  Смена `.env` не меняет пароли существующих volumes: ротация требует отдельной операции.
- Начальная SQL-инициализация создаёт роли/базы. Отдельный Alembic runner применяет
  миграции каждого владельца. У Catalog созданы Job/outbox/receipt, у остальных
  пока только независимые стартовые ревизии. Модели предметной области — этап 2.
- Healthchecks проверяют PostgreSQL, RabbitMQ, Redis, готовность API, ответ worker,
  heartbeat dispatcher, Gateway и Web. Проект рассчитан на ручной локальный запуск.

## Доставка

`requestProbeJob` проверяет временный dev-токен в Catalog и атомарно сохраняет Job
и outbox. Уникальный request key защищает от повторного клика и конкурентных запросов.
Dispatcher берёт запись с `FOR UPDATE SKIP LOCKED`, публикует persistent JSON-сообщение
в durable очередь `catalog.probes` с publisher confirm, затем отмечает публикацию.
При ошибке брокера запись остаётся в outbox, задержка повторов растёт до 30 секунд.
Ожидание восстановления брокера не имеет общего срока; активные попытки ограничены
таймаутами и backoff. Это политика доставки локального стенда, не HTTP retry источников.

Публикация и commit PostgreSQL не атомарны: возможна повторная доставка. Worker
блокирует Job и в одной транзакции сохраняет уникальный receipt и `succeeded`.
Повтор не создаёт второй эффект. Late ack, prefetch 1, concurrency 2,
`reject_on_worker_lost`, soft/hard time limits 15/20 секунд; временная ошибка БД
повторяется максимум пять раз с backoff/jitter. Celery result backend не используется.
PostgreSQL — единственный источник состояния задания. Redis пока проверяется
отдельным TTL smoke; прикладное кеширование появится с моделью каталога.

JSON-логи Python содержат разрешённые поля, тип ошибки и correlation ID, без
произвольных заголовков, payload, SQL и текстов исключений. Gateway передаёт
санитизированный `x-request-id` в подграф; он сохраняется в Job и передаётся worker.
Это начало наблюдаемости, не OpenTelemetry tracing и не централизованный сбор логов.

## Границы проверки

Очередь на одном RabbitMQ-узле; нет обещания exactly-once или сохранности при потере
диска/хоста. Перезапуски контейнеров с volumes проверяются отдельно от аварии хоста.
Повтор после уже совершённого commit проверяется повторными сообщениями; точечное
убийство worker между commit и ack пока не моделируется.

Длительная недоступность БД, исчерпавшая worker retries, может оставить Job queued
с опубликованным outbox. Автоматическая сверка зависших заданий и терминальные
ошибки импорта относятся к этапу 3; до него этот probe не используется для реальных
импортов. API Security/Workspace, Beat и адаптеры внешних API ещё не реализованы.
Каталог и subscription этапа 0 по-прежнему используют демонстрационную память процесса.

## Основания

- [Celery: настройки ack, retry и доставки](https://docs.celeryq.dev/en/stable/userguide/configuration.html)
- [RabbitMQ: подтверждения потребителей и издателей](https://www.rabbitmq.com/docs/confirms)
- [PostgreSQL: привилегии](https://www.postgresql.org/docs/18/ddl-priv.html)
- [Образ PostgreSQL: расположение данных версии 18](https://hub.docker.com/_/postgres)
