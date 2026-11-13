#!/usr/bin/env python3
"""One-shot file IPC round-trip probe for S.T.A.L.K.E.R. CoP 1.6.02.

The game-side Lua module accepts only: v1 <request_id> ping
and responds: v1 <request_id> ok pong_gpt_companion_ipc_probe_v1
No LLM, HTTP, sockets, or third-party Python packages are involved.
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
COMMAND_TMP_NAME = "gpt_companion_ipc_cmd.tmp"
REPLY_NAME = "gpt_companion_ipc_reply.txt"


def resolve_app_data_root(game_root: Path) -> Path:
    """Resolve $app_data_root$ from fsgame.ltx, using game_root as $fs_root$."""
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
        if len(fields) < 4:
            continue
        parent = fields[2].strip()
        relative = fields[3].strip().strip('"').strip()
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
        parent_alias, relative = entry
        base = resolve(parent_alias, seen | {alias}) if parent_alias else root
        if not relative:
            return base
        candidate = Path(relative.replace("\\", os.sep).replace("/", os.sep))
        return candidate if candidate.is_absolute() else base / candidate

    return resolve("$app_data_root$", set()).resolve()


def write_atomic(path_tmp: Path, path_final: Path, payload: str) -> None:
    # Flush the writable descriptor before exposing the complete final file.
    with path_tmp.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(path_tmp, path_final)


def run_probe(app_data_root: Path, timeout: float) -> int:
    if not app_data_root.is_dir():
        print(f"Папка $app_data_root$ не существует: {app_data_root}", file=sys.stderr)
        return 2

    command_path = app_data_root / COMMAND_NAME
    command_tmp = app_data_root / COMMAND_TMP_NAME
    reply_path = app_data_root / REPLY_NAME

    if command_path.exists():
        print(
            f"Уже есть необработанная команда: {command_path}. "
            "Не перезаписываю её.",
            file=sys.stderr,
        )
        return 2

    try:
        command_tmp.unlink(missing_ok=True)
        reply_path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"Не удалось очистить старые файлы IPC: {exc}", file=sys.stderr)
        return 2

    request_id = uuid.uuid4().hex[:16]
    command_line = f"{PROTOCOL} {request_id} ping\n"

    try:
        write_atomic(command_tmp, command_path, command_line)
    except OSError as exc:
        print(f"Не удалось записать IPC-команду: {exc}", file=sys.stderr)
        return 2

    print(f"Команда отправлена в игру. Ожидаю ответ (до {timeout:.0f} с)...")
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
                        reply_path.unlink(missing_ok=True)
                        if parts[2] == "ok" and parts[3] == "pong_gpt_companion_ipc_probe_v1":
                            print("IPC ROUND-TRIP OK")
                            print("Python -> файл команды -> Lua в CoP -> файл ответа -> Python")
                            return 0
                        print(f"Игра вернула неожиданный ответ: {lines[0]}", file=sys.stderr)
                        return 1
        except (OSError, PermissionError):
            # A transient read/replace race should not fail the probe.
            pass
        time.sleep(0.25)

    # Remove only our own still-pending request; never delete another request.
    try:
        if command_path.is_file():
            pending = command_path.read_text(encoding="ascii", errors="replace").strip()
            if pending == command_line.strip():
                command_path.unlink(missing_ok=True)
    except OSError:
        pass

    print(
        "Тайм-аут: игра не вернула pong. Проверь, что CoP запущен, "
        "загружена игра, установлены оба Lua-файла и нет Lua-ошибок.",
        file=sys.stderr,
    )
    print(f"$app_data_root$: {app_data_root}", file=sys.stderr)
    return 1


def main() -> int:
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
