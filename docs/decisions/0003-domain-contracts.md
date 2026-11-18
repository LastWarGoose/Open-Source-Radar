# 0003. Модель и контракты этапа 2

Дата: 17 ноября 2026. Контракт реализации этапа 2.

| Владелец | Сущности и ключи Federation |
|---|---|
| Catalog | Package `id=pypi:<normalized-name>`; Release `id=UUID`; DependencyRequirement; ImportJob (PyPI) |
| Repositories | Repository `id=github:<owner/repo>`; связи Package → Repository, многие-ко-многим |
| Security | Vulnerability `id` OSV; VersionScan по внешнему Release.id; алиасы и найденные advisory |
| Workspace | Collection, CollectionItem, Notification и тестовые владельцы; внешние ссылки Package.id |

Уникальные ключи и FK только внутри базы владельца. Все внешние ссылки разрешает
Hive через entity references; общий Python-пакет не содержит предметных ORM-моделей.

`packages(first=20, after, search, filter, sort)` возвращает `nodes/pageInfo`.
Сортировки NAME_ASC и UPDATED_DESC используют уникальный ID для разрешения равенств.
Курсор привязан к операции, родителю, фильтрам и сортировке; malformed/mismatched cursor
даёт BAD_USER_INPUT. Первая страница 20, максимум 100; вложенные связи тоже ограничены.
Пагинация не обещает неизменяемый снимок при параллельных обновлениях.

Имена нормализуются packaging по правилам PyPI, версии сравниваются Version, требования
сохраняют raw/specifier/extras/marker/URL без вычисления дерева установленного окружения.
Release имеет исходную и каноническую версию; эквивалентные версии не дублируются.
Поиск использует PostgreSQL FTS simple и подстроку нормализованного имени с pg_trgm.
Фильтры и сортировки касаются только собственных полей Catalog; сортировки по stars нет.

Nullable-поля: отсутствующий Package/Release/Repository/Collection → null; отсутствие
сканирования Release → null (не проверено); SUCCESS с пустыми findings означает только
успешную проверку без известных совпадений. UNKNOWN, FAILED и STALE не равны SUCCESS.
Удалённые nullable-секции позволяют GraphQL возвращать частичный ответ при отказе владельца.
Ошибки: BAD_USER_INPUT, UNAUTHENTICATED, FORBIDDEN, UNAVAILABLE, NOT_FOUND; исключения SQL скрыты.
Отсутствующая внешняя ссылка Package в подборке возвращает nullable `package: null`
и локализованную ошибку NOT_FOUND, сохраняя другие элементы. Прямой `package(id)`
для неизвестного ID возвращает null без ошибки. Это различие проверяется через Hive.

DataLoader создаётся на запрос. Пакетные чтения ограничивают число SQL-запросов
при вложенности; приватные загрузчики Workspace ограничены конкретным владельцем.
Публичному x-user-id доверия нет. До этапа 6 Workspace принимает только два dev-токена,
производных HMAC от локального DEV_ADMIN_TOKEN; они соответствуют двум фиксированным
тестовым владельцам. Токены не выдаются браузеру. Это fixture-доступ, не система входа.

Внешних запросов нет. Seed синтетический и идемпотентный, запускается явной командой;
первый Docker startup не выполняет импорт. Demo-сценарий этапа 0 сохраняется отдельно
от постоянного каталога. Job/outbox этапа 1 сохраняется; выполнение ImportJob — этап 3.

## Реализация и ограничения

Миграции `_0002` содержат замороженный PostgreSQL DDL и не импортируют изменяемые
ORM-модели. PostgreSQL FTS simple и pg_trgm индексируют поля Catalog; индексы
порядка добавлены для обновления пакетов и списка версий. Эквивалентные версии
получают один детерминированный UUID. Ранг релизов пересчитывается под блокировкой
пакета с использованием `packaging.Version`; стоимость пересчёта длинной истории
потребует измерения перед массовым импортом.

Общие алиасы advisory разрешаются в одну запись под транзакционными advisory locks;
слияние двух ранее существовавших конфликтующих групп требует отдельного решения.
Состояния FAILED/UNKNOWN не подменяются успешным пустым результатом.

Вложенные страницы используют DataLoader и один SQL UNION из ограниченных запросов
на пакет родителей. Это ограничивает число сетевых обращений к БД, но не делает
объём работы независимым от числа возвращаемых сущностей. Проверки 20/100 родителей
не являются нагрузочным испытанием. Глобальные лимиты глубины/стоимости и нагрузочные
пороги остаются этапом 5. Mutation CRUD Workspace и запуск ImportJob пока отсутствуют.

Основания: [packaging names](https://packaging.pypa.io/en/stable/utils.html),
[requirements](https://packaging.pypa.io/en/stable/requirements.html),
[versions](https://packaging.pypa.io/en/stable/version.html),
[Strawberry Federation](https://strawberry.rocks/docs/guides/federation).
