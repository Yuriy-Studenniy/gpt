# M1 — проверка файлового IPC с оригинальным CoP 1.6.02

Статус: probe подготовлен; игровой round-trip ещё не подтверждён  
Ветка: `world-model-completion`

## Что проверяем

Внешний Python-процесс отправляет тестовую строку в пользовательский каталог игры `$app_data_root$`. Скрипт Lua в CoP забирает команду из файла, формирует ответ и публикует его через временный файл + rename. Python должен получить ответ с тем же request ID.

Протокол намеренно минимальный:

- запрос: `v1 <request_id> ping`
- ответ: `v1 <request_id> ok pong_gpt_companion_ipc_probe_v1`

Никакая LLM, HTTP, socket, DLL или база данных в этом тесте не используется. Lua принимает только `ping`; произвольное выполнение команд невозможно.

## Установка временного probe

1. Сделай резервную копию текущего `gamedata/scripts/bind_stalker.script` и тестового сохранения.
2. Из ветки `world-model-completion` скопируй:
   - `bind_stalker.script` → `gamedata/scripts/bind_stalker.script`;
   - `gpt_companion_ipc_probe.script` → `gamedata/scripts/gpt_companion_ipc_probe.script`.
3. Остальные игровые файлы не меняй. Файл `tools/gpt_companion_ipc_probe.py` в игру не копируется.

## Запуск round-trip

1. Запусти оригинальный Call of Pripyat 1.6.02 и загрузи сохранение или новую игру. Дождись появления игрового мира.
2. На компьютере с игрой открой терминал в корне репозитория/скачанной копии и выполни:

   ```powershell
   python tools/gpt_companion_ipc_probe.py --game-root "C:\ПУТЬ\К\Call of Pripyat"
   ```

   Укажи реальную папку игры, где лежат `xrEngine.exe` и `fsgame.ltx`. Скрипт сам разбирает `fsgame.ltx` и разрешает `$app_data_root$`. Если это не сработает, найди значение alias `$app_data_root$` в `fsgame.ltx` и передай его напрямую через `--app-data-root "ПОЛНЫЙ\ПУТЬ"`.
3. Python создаст `gpt_companion_ipc_cmd.tmp`, переименует его в `gpt_companion_ipc_cmd.txt` и будет ждать ответ до 45 секунд.
4. Игровой actor binder проверяет командный файл не чаще раза в 500 мс. После получения ping Lua создаёт `gpt_companion_ipc_reply.tmp` и переименовывает его в `gpt_companion_ipc_reply.txt`.

## Ожидаемый результат

В терминале:

```text
IPC ROUND-TRIP OK
Python -> файл команды -> Lua в CoP -> файл ответа -> Python
```

В игровом логе ожидаются диагностические записи с окончаниями:

- `ipc_probe_command_received_<id>`
- `ipc_probe_reply_written_<id>`

Они могут выглядеть как `Unknown command: gpt_companion_diag_world_snapshot_ipc_probe_...`; для этого проекта такой вывод — ожидаемый канал диагностических маркеров.

## Если тест не прошёл

- Не продолжай менять файлы наугад. Сохрани вывод Python и последние строки `xray_administrator.log`.
- `ipc_probe_standard_io_unavailable` означает, что стандартные Lua `io/os` функции не доступны в этом runtime.
- `ipc_probe_path_init_failed_...` означает, что не разрешился `$app_data_root$` или не сработал `getFS():update_path()`.
- Python timeout при отсутствии Lua marker может означать, что binder hook не запущен, скрипт не загрузился или путь `$app_data_root$` отличается.
- Lua marker `command_received` без `reply_written` укажет на проблему записи ответа/rename.

После round-trip probe следует удалить или отключить. Это не production memory service и не доказательство работы LLM или долговременной памяти.
