# Контракт этапа 0

Схемы `catalog.graphql` и `repositories.graphql` экспортируются из Python.
`supergraph.graphql` получается композиционным инструментом, вручную не редактируется.
Стабильный ключ Package — `id`; в тестовом наборе `pypi:fastapi` и
`pypi:strawberry-graphql`. Это демонстрационные IDs, не утверждённая модель этапа 2.

| Поле | Владелец | Назначение |
|---|---|---|
| Package.id/name/summary/demoRevision | Catalog | Фиксированные данные и изменяемая ревизия |
| Package.repository | Repositories | Nullable-связь по ID пакета |
| Repository.* | Repositories | Фиксированные данные репозитория |
| Query.packages/package | Catalog | Два пакета или пакет по ID |
| Mutation.advanceDemo | Catalog | Увеличение ревизии, сигнал подписчикам |
| Subscription.packageUpdated | Catalog | Текущий снимок и последующие обновления |

Query, mutation и subscription клиента запрашивают `repository` и поэтому проверяют
разрешение сущности во втором процессе. Неизвестный ID в query возвращает null,
в mutation/subscription — GraphQL error. Ревизия не сохраняется между перезапусками.
Фиксированный список из двух элементов не является будущей пагинацией каталога.

Генерация: `uv run python -m scripts.export_schema`, `pnpm compose:schema`,
после запуска gateway — `pnpm codegen`. Клиентские операции находятся в
`apps/web/src/operations.graphql`, сгенерированные типы — в `apps/web/src/gql/`.
