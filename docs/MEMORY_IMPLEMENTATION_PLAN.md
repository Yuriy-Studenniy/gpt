# План реализации общей и личной памяти

Статус на 2026-11-15: M0 завершён; файловый IPC подтверждён в retail CoP; M2 journal foundation добавлен, проверка автоматизированных тестов ожидается.
Ветка: world-model-completion.

## 1. Результат аудита M0

- Ветка содержит Lua-код игры и проектную документацию, но не содержит отдельного внешнего Companion Runtime или LLM-сервиса.
- Штатные dialog_manager / xr_dialogs реализуют ванильные диалоги, а не свободный LLM-диалог.
- gpt_world хранит ограниченные сведения о знании мест и не является журналом диалогов.
- Полную историю нельзя помещать в actor PSTOR или расширять бинарный пакет sim_squad_scripted без отдельного аудита совместимости.
- Архитектура должна разделять внешний Runtime, долговременный журнал, retrieval, LLM provider adapter и тонкий игровой Lua bridge.

Подробная предметная модель: MEMORY_DESIGN.md.

## 2. Целевая архитектура

Один внешний Companion Runtime — один локальный процесс. Внутри него находятся:
1. стабильный API событий/диалога;
2. append-only журнал;
3. индексы и retrieval;
4. сборщик ограниченного контекста;
5. очередь фоновой консолидации;
6. адаптер выбранного LLM-провайдера.

Lua в игре остаётся тонким адаптером уникального Story ID gpt_companion_main. Никаких LLM, SQLite, HTTP или тяжёлых операций в actor_binder:update(), motivator_binder:update() либо NPC update_logic. Все результаты, пришедшие из Runtime, должны проверяться по request ID и возрасту запроса. Обычные NPC и ванильные диалоги остаются нетронутыми.

## 3. Контракт данных

### conversations
- conversation_id — устойчивый ID диалога;
- scope_id — профиль/кампания/ветка сохранения;
- created_at, updated_at;
- позднее: summary, summary_from_seq, summary_to_seq, version.

### messages
- message_id — глобально уникальный и идемпотентный ID события;
- conversation_id и возрастающий sequence;
- speaker: player, companion, external_assistant, npc или engine;
- исходный content, created_at, source и JSON metadata.

Исходные сообщения append-only. Исправления добавляют новую запись/связь, а не переписывают прошлое. Повторная доставка того же message_id с тем же payload возвращает исходную запись; повторное использование ID с другим payload — ошибка.

### memory_items (следующий слой)
- memory_id, scope_id, kind, subject_key;
- content, source_message_id / ссылка на game event;
- perspective: shared или companion_private;
- confidence, importance, status, created_at, last_confirmed_at, supersedes_id.

Обещания и открытые темы оформляются типами memory_items; отдельные таблицы добавляются только при обоснованной необходимости.

## 4. Хранилище и производительность

Для MVP используется SQLite во внешнем Runtime:
- транзакционная запись с уникальными ID и последовательностью на разговор;
- обычные B-tree индексы;
- WAL и busy timeout;
- FTS5 — только после проверки доступности в целевой сборке SQLite;
- без vector DB и embeddings на первом этапе.

Сырой журнал — источник истины. Hot cache, сводки и retrieval-индексы перестраиваемы. Критический путь ответа не делает отдельный LLM-вызов ради поиска памяти. Консолидация выполняется пакетно вне пути ответа. Размер контекста ограничивается явным token budget; p50/p95 задержки измеряются до фиксации SLA.

## 5. Реализация по этапам

| Этап | Объём | Критерий |
|---|---|---|
| M0. Контракт и аудит | Модель данных, границы Lua/Runtime, аудит текущих диалогов и сохранений | Контракт независим от модели; игровые скрипты не считаются LLM runtime |
| M1. IPC spike | File-based request/reply через $app_data_root$ в retail CoP | Lua читает команду и возвращает ответ с тем же request ID |
| M2. Runtime + журнал | Внешний Python package, SQLite, append/read API, идемпотентность | История переживает закрытие/перезапуск процесса и восстанавливается в исходном порядке |
| M3. Быстрый retrieval | Recent turns, hot cache, активные договорённости, точный/FTS поиск, token budget | Контекст остаётся ограниченным и собирается без LLM-вызова для поиска |
| M4. Первый LLM vertical slice | Один provider adapter и внешний test harness | Реальный разговор пишет/читает память и передаёт source IDs |
| M5. Игровой диалоговый мост | Подключение Runtime к уникальному companion через подтверждённый IPC | Можно поговорить с NPC; timeout/retry не блокируют игровой update |
| M6. Консолидация | Сводки, события/обещания, дедупликация, противоречия, открытые темы | Старый разговор сжимается без потери важных фактов |
| M7. Личная память и Character Core | Перспектива спутницы, эмоции, убеждения, отношения, цели | Персонаж отличает сказанное от собственного вывода и использует личный опыт |

M4 подключает модель через внешний harness сразу после M2–M3; не нужно ждать полного игрового моста. M5 позже подключает уже работающий Runtime к NPC.

## 6. Фактический статус IPC (M1)

В оригинальном CoP 1.6.02 пользователь подтвердил:
- actor_binder:update исполняется, io.open и getFS доступны;
- PowerShell создал командный файл с request ID, Lua прочитала и удалила его;
- Lua записала reply_tmp, переименовала результат в reply-файл и выставила reply_written;
- содержимое ответа содержало тот же request ID и ожидаемый pong payload.

Отдельный Python запуск ранее также создал команду, которую Lua прочитала. Сбой первого Python теста был осложнён кодировкой stdout PowerShell Job и тем, что прежний probe удалял status и pending command при старте/тайм-ауте. Python probe обновлён: timeout больше не удаляет запрос, status или reply; старый ответ игнорируется по несовпадающему ID. Есть локальные unit tests для эмуляции Python request/reply и сохранения запроса при timeout.

M1 считается подтверждённым по игровому транспортному контракту (файловый request/reply с корреляцией ID в реальном CoP). Полный запуск Python probe как одного процесса, который сам дождался ответа, остаётся интеграционной проверкой клиента, а не основанием снова гонять ручные ping. Не расширять диагностический smoke-test: перейти к M2, а окончательную интеграцию Python проверять вместе с Runtime.

## 7. Фактический статус M2

Добавлен package companion_runtime и SQLite journal foundation:
- conversations с scope_id и временными метками;
- append-only messages с message_id, conversation_id, sequence, speaker, content, source, timestamp и JSON metadata;
- SQLite WAL, foreign keys, busy timeout, транзакционная выдача sequence;
- повтор того же ID/payload идемпотентен; конфликт ID отклоняется;
- DB triggers запрещают UPDATE/DELETE сообщений;
- API append_message, get_message, list_messages, conversation_info, integrity_check и CLI init/append/recent/check.

Добавлены unit tests: восстановление после reopen, порядок, идемпотентность, conflict, append-only, ограниченное чтение, неизменность scope, конкурентные append и SQLite integrity; а также тесты Python IPC probe. Требуется прогнать tests в CI и исправлять конкретные падения. Пока не заявлять M2 завершённым: ещё нет runtime event loop, retrieval, provider adapter или связи журнала с игровым диалогом.

## 8. Ограничения, которые сохраняются

- Игровой движок остаётся источником объективного состояния; память персонажа хранит знание/перспективу, а не подменяет факты движка.
- Shared memory не равна личной интерпретации спутницы.
- В prompt не передаётся вся база; recent context и retrieval ограничены.
- Нет LLM-вызова на каждый тик или каждый поиск воспоминания.
- Нет сканирования всех объектов уровня, правок xr_motivator.script или NPC update_logic ради памяти.
- Перед production подключением IPC добавить версии протокола, retry/idempotency, timeout и защиту от устаревших ответов.
