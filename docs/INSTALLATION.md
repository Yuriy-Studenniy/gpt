# Установка AI Stalker Companion в Call of Pripyat 1.6.02

Целевая версия: **S.T.A.L.K.E.R.: Call of Pripyat 1.6.02, оригинальный X-Ray**.

> Репозиторий хранит исходники в плоском виде, а не в готовой структуре `gamedata`. Не копируй весь репозиторий целиком в папку игры: в нём находятся сотни файлов исходной игры, большинство из которых не нужно заменять.

## 1. Подготовка

1. Найди корневую папку CoP — там, где находятся `xrEngine.exe` и `fsgame.ltx`.
2. Сделай копию `fsgame.ltx`, тестового сохранения и всех перечисленных ниже файлов, если они уже распакованы в твоей `gamedata`.
3. Для первого запуска используй чистую CoP 1.6.02 без других крупных модификаций. Сборки на базе OpenXRay или другого мода этим набором не проверялись.
4. Получи актуальную ветку `main` репозитория.

## 2. Включи загрузку loose-файлов

Открой корневой `fsgame.ltx). Найди строку:

```ini
$game_data$ = false| true| $fs_root$| gamedata\\
```

Если первое значение у тебя `false`, поменяй только его:

```ini
$game_data$ = true| true| $fs_root$| gamedata\\
```

Если строка уже начинается с `true`, повторно менять её не нужно. Сохрани файл. Эта настройка позволяет игре читать файлы из папки `gamedata` поверх архивов игры.

## 3. Создай каталоги

В корне игры создай такую структуру:

```text
Call of Pripyat/
├─ fsgame.ltx
├─ xrEngine.exe
└─ gamedata/
   ├─ scripts/
   └─ configs/
      ├─ creatures/
      ├─ gameplay/
      └─ misc/
```

## 4. Скопируй файлы проекта

Пути слева — расположение файла в корне репозитория. Пути справа — куда его положить внутри папки игры.

### В `gamedata/scripts/`

- [bind_stalker.script](../bind_stalker.script) → `gamedata/scripts/bind_stalker.script`
- [release_body_manager.script](../release_body_manager.script) → `gamedata/scripts/release_body_manager.script`
- [sim_board.script](../sim_board.script) → `gamedata/scripts/sim_board.script`
- [sim_squad_scripted.script](../sim_squad_scripted.script) → `gamedata/scripts/sim_squad_scripted.script`
- [xr_corpse_detection.script](../xr_corpse_detection.script) → `gamedata/scripts/xr_corpse_detection.script`
- [xr_motivator.script](../xr_motivator.script) → `gamedata/scripts/xr_motivator.script`
- [gpt_companion_custom.ltx](../gpt_companion_custom.ltx) → `gamedata/scripts/gpt_companion_custom.ltx`

### В `gamedata/configs/creatures/`

- [spawn_sections_general.ltx](../spawn_sections_general.ltx) → `gamedata/configs/creatures/spawn_sections_general.ltx`

### В `gamedata/configs/misc/`

- [squad_descr.ltx](../squad_descr.ltx) → `gamedata/configs/misc/squad_descr.ltx`

### В `gamedata/configs/gameplay/`

- [npc_profile.xml](../npc_profile.xml) → `gamedata/configs/gameplay/npc_profile.xml`
- [character_desc_general.xml](../character_desc_general.xml) → `gamedata/configs/gameplay/character_desc_general.xml`

Итого: **11 файлов**.

## 5. Важное предупреждение о конфигурациях

В репозитории `spawn_sections_general.ltx`, `squad_descr.ltx`, `npc_profile.xml` и `character_desc_general.xml` — это полные файлы конфигурации CoP с добавленными записями спутника.

- На чистой распакованной CoP 1.6.02 можно использовать версии из репозитория как замену одноимённых ванильных loose-файлов.
- Если у тебя уже стоит другой мод или изменённая `gamedata`, **не заменяй эти четыре файла целиком**. Перенеси только companion-записи в соответствующие оригинальные файлы:
  - секцию `[gpt_companion_main]` в `spawn_sections_general.ltx`;
  - секцию `[gpt_companion_squad]` в `squad_descr.ltx`;
  - XML-узел `<character id="gpt_companion_main">` в `npc_profile.xml`;
  - XML-узел `<specific_character id="gpt_companion_main">` в `character_desc_general.xml`.
- Не добавляй одинаковые секции/XML-узлы дважды.

Остальные файлы Lua — полные файлы скриптов, а не фрагменты. Для чистой CoP используй версии из репозитория. При наличии другого мода эти Lua-файлы требуют ручного объединения с версиями того мода; простая замена может затереть его исправления.

## 6. Что не нужно копировать

- Весь репозиторий целиком.
- `modules.script` — ванильная загрузка уже подключает нужные companion/corpse/wounded модули.
- `system.ltx` — штатные include-записи уже подключают `creatures/spawn_sections.ltx` и `misc/squad_descr.ltx`, а профильные XML перечислены в секции profiles.
- Документы из `docs/`, `lua_help.script` и прочие не перечисленные файлы для работы спутника не нужны.

## 7. Первый запуск

1. Убедись, что все пути и имена файлов совпадают с инструкцией.
2. Запусти CoP 1.6.02 и загрузи копию сохранения (или начни тестовую новую игру).
3. После загрузки дай игре несколько секунд на инициализацию. В `bind_stalker.script` настройка спутника вызывается из обновления игрока.
4. Проверь лог игры. Ищи сообщения с префиксом `[GPT_COMPANION]`, например создание NPC, регистрацию squad или ошибку настройки.
5. Не проверяй остальные функции по отдельности — используй единый [игровой чек-лист](IN_GAME_TEST_CHECKLIST.md) для одного полного прогона.

Успешное появление NPC ещё не означает, что все функции главы 1 работают: online/offline, save/load, corpse reservations и поведение обычных NPC должны быть проверены по чек-листу.

## 8. Откат

Если игра не запускается или появляются ошибки:

1. Закрой игру.
2. Удали только установленные файлы проекта из `gamedata` (не удаляй чужие файлы модов).
3. Верни исходный `fsgame.ltx` из резервной копии.
4. Верни сохранение из резервной копии, если оно успело измениться.

Не продолжай основной сейв до прохождения теста на его копии.
