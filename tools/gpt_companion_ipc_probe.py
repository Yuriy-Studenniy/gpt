#!/usr/bin/env python3
"""Одноразовая проверка файлового обмена с S.T.A.L.K.E.R. CoP 1.6.02.

Lua-обработчик игры принимает команду v1 <request_id> ping и возвращает
v1 <request_id> ok pong_gpt_companion_ipc_probe_v1.
LLM, HTTP, сокеты и сторонние Python-пакеты не используются.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path


PROTOCOL = "v1"
COMMAND_NAME = "gpt_companion_ipc_cmd.txt"
REPLY_NAME = "gpt_companion_ipc_reply.txt"
STATUS_NAME = "gpt_companion_ipc_status.txt"


def resolve_app_data_root(game_root: Path) -> Path:
    """Получить путь $app_data_root$ из fsgame.ltx относительно $fs_root$ игры."""
    fsgame_path = game_root / "fsgame.ltx"
    if not fsgame_path.is_file():
        raise FileNotFoundError(f"Не найден fsgame.ltx: {fsgame_path}")

    raw_fsgame = fsgame_path.read_bytes()
    fsgame_text = None
    for encoding in ("utf-8-sig", "cp1251", "cp1252"):
        try:
            fsgame_text = raw_fsgame.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if fsgame_text is None:
        raise UnicodeError("Не удалось прочитать fsgame.ltx как UTF-8 или ANSI")

    aliases: dict[str, tuple[str, str]] = {}
    for raw_line in fsgame_text.splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if not line or "=" not in line:
            continue
        alias, rhs = line.split("=", 1)
        alias = alias.strip()
        if not (alias.startswith("$") and alias.endswith("$")):
            continue
        fields = [part.strip() for part in rhs.split("|")]
        # В fsgame.ltx встречаются две формы корневого пути:
        #   $alias$ = ...| $parent_alias$| relative\\
        #   $alias$ = ...| C:\\absolute\\path\\
        # Во второй форме после разделения получается только три поля.
        if len(fields) < 3:
            continue
        parent = fields[2].strip().strip('"').strip()
        relative = fields[3].strip().strip('"').strip() if len(fields) >= 4 else ""
        aliases[alias] = (parent, relative)

    root = game_root.resolve()

    def resolve(alias: str, seen: set[str]) -> Path:
        if alias == "$fs_root$":
            return root
        if alias in seen:
            raise ValueError(f"Циклический путь в fsgame.ltx: {alias}")
        entry = aliases.get(alias)
        if entry is None:
            raise KeyError(f"Путь {alias} не найден в fsgame.ltx")
        parent, relative = entry
        if parent.startswith("$") and parent.endswith("$"):
            base = resolve(parent, seen | {alias})
        elif parent:
            parent_path = Path(parent.replace("\\", os.sep).replace("/", os.sep))
            base = parent_path if parent_path.is_absolute() else root / parent_path
        else:
            base = root
        if not relative:
            return base
        candidate = Path(relative.replace("\\", os.sep).replace("/", os.sep))
        return candidate if candidate.is_absolute() else base / candidate

    return resolve("$app_data_root$", set()).resolve()


def write_command(path: Path, payload: str) -> None:
    """Создать итоговый файл команды напрямую, без переименования временного файла.

    Такой способ повторяет уже проверенную ручную запись из PowerShell и
    исключает расхождения X-Ray при обнаружении файла после os.replace().
    Режим x не позволяет затереть чужую или ещё не обработанную команду.
    """
    with path.open("x", encoding="ascii", newline="\\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def run_probe(app_data_root: Path, timeout: float) -> int:
    if not app_data_root.is_dir():
        print(f"Папка $app_data_root$ не существует: {app_data_root}", file=sys.stderr)
        return 2

    command_path = app_data_root / COMMAND_NAME
    reply_path = app_data_root / REPLY_NAME
    status_path = app_data_root / STATUS_NAME

    if command_path.exists():
        print(
            f"Уже есть необработанная команда: {command_path}. "
            "Не перезаписываю её.",
            file=sys.stderr,
        )
        return 2

    request_id = uuid.uuid4().hex[:16]
    command_line = f"{PROTOCOL} {request_id} ping\\n"

    try:
        # Публикуем непосредственно итоговый файл: без временного имени и os.replace().
        write_command(command_path, command_line)
    except FileExistsError:
        print(
            f"Параллельно появилась необработанная команда: {command_path}. "
            "Не перезаписываю её.",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"Не удалось записать IPC-команду: {exc}", file=sys.stderr)
        return 2

    print(f"Команда отправлена в игру. ID={request_id}. Ожидаю ответ (до {timeout:.0f} с)...")
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            if reply_path.is_file():
                lines = reply_path.read_text(
                    encoding="ascii", errors="replace"
                ).splitlines()
                if lines:
                    parts = lines[0].split(" ", 3)
                    if len(parts) == 4 and parts[0] == PROTOCOL and parts[1] == request_id:
                        if parts[2] == "ok" and parts[3] == "pong_gpt_companion_ipc_probe_v1":
                            print("ОБМЕН IPC УСПЕШЕН")
                            print("Python -> файл команды -> Lua CoP -> файл ответа -> Python")
                            print(f"request_id={request_id}")
                            return 0
                        print(f"Игра вернула неожиданный ответ: {lines[0]}", file=sys.stderr)
                        return 1
        except OSError:
            # Кратковременная гонка при чтении/переименовании не должна проваливать проверку.
            pass
        time.sleep(0.25)

    # Не удалять команду по тайм-ауту: свёрнутая игра могла приостановиться
    # и обработать её только после возвращения в активный режим.
    print("Тайм-аут ожидания ответа; запрос и диагностические файлы сохранены.", file=sys.stderr)
    print(f"request_id: {request_id}", file=sys.stderr)
    print(f"$app_data_root$: {app_data_root}", file=sys.stderr)
    print(f"command_path: {command_path}", file=sys.stderr)
    print(f"command_still_present: {command_path.exists()}", file=sys.stderr)
    try:
        if command_path.is_file():
            command_stat = command_path.stat()
            command_contents = command_path.read_text(encoding="ascii", errors="replace").strip()
            print(f"command_file_size: {command_stat.st_size}", file=sys.stderr)
            print(f"command_file_mtime_ns: {command_stat.st_mtime_ns}", file=sys.stderr)
            print(f"command_file_content: {command_contents}", file=sys.stderr)
    except OSError as exc:
        print(f"Не удалось проверить командный файл: {exc}", file=sys.stderr)
    try:
        if status_path.is_file():
            print("Состояние Lua:", file=sys.stderr)
            print(status_path.read_text(encoding="utf-8", errors="replace").strip(), file=sys.stderr)
        else:
            print("Lua status: отсутствует или ещё не создан.", file=sys.stderr)
    except OSError as exc:
        print(f"Не удалось прочитать Lua status: {exc}", file=sys.stderr)
    try:
        if reply_path.is_file():
            print("Файл ответа (может содержать другой request ID):", file=sys.stderr)
            print(reply_path.read_text(encoding="ascii", errors="replace").strip(), file=sys.stderr)
    except OSError as exc:
        print(f"Не удалось прочитать reply: {exc}", file=sys.stderr)
    return 1

def configure_console_output() -> None:
    """Не допускать UnicodeEncodeError в фоновой задаче Windows PowerShell."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass


def main() -> int:
    configure_console_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--game-root",
        type=Path,
        help="Корневая папка CoP, где лежат xrEngine.exe и fsgame.ltx",
    )
    parser.add_argument(
        "--app-data-root",
        type=Path,
        help="Можно передать путь $app_data_root$ напрямую вместо --game-root",
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    if args.app_data_root is not None:
        app_data_root = args.app_data_root.expanduser().resolve()
    elif args.game_root is not None:
        try:
            app_data_root = resolve_app_data_root(args.game_root.expanduser())
        except (OSError, ValueError, KeyError) as exc:
            print(f"Не удалось определить $app_data_root$: {exc}", file=sys.stderr)
            return 2
    else:
        parser.error("Укажи --game-root или --app-data-root")

    return run_probe(app_data_root, max(1.0, args.timeout))


if __name__ == "__main__":
    raise SystemExit(main())
