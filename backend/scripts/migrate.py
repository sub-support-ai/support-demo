"""
Надёжный запуск Alembic-миграций для docker-compose.

Проблема: `alembic upgrade head` падает при каждом старте если в БД
уже есть объекты с другими именами (constraint, index), чем ожидает
миграция. Это происходит на локальных БД с долгой историей, где ветки
миграций накатывались в разном порядке.

Решение этого скрипта:
  1. Запускает `alembic upgrade head` как subprocess.
  2. При успехе — выходит с кодом 0 (uvicorn стартует).
  3. При ошибке — диагностирует тип:
       * UndefinedObject (нет constraint/index) — сообщение + HINT.
       * DuplicateObject (constraint/index уже есть) — сообщение + HINT.
       * Другая ошибка — выводит traceback.
  4. Всегда выходит с кодом 1 при ошибке (docker compose перезапустит).

Запуск в docker-compose.dev.yml:
  command: python scripts/migrate.py && uvicorn ...
"""

import subprocess
import sys


def main() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )

    # Выводим stdout (INFO-строки alembic) всегда — для логов контейнера.
    if result.stdout:
        print(result.stdout, end="")

    if result.returncode == 0:
        return  # всё хорошо, uvicorn стартует

    # ── Диагностика ошибки ────────────────────────────────────────────────────
    stderr = result.stderr or ""
    stdout = result.stdout or ""
    combined = stdout + "\n" + stderr

    print("\n" + "═" * 60, flush=True)
    print("ALEMBIC MIGRATION FAILED", flush=True)
    print("═" * 60, flush=True)

    if "UndefinedObjectError" in combined or "does not exist" in combined:
        print(
            "\n⚠  Ошибка: миграция пытается удалить или изменить объект\n"
            "   (constraint, index, колонку), которого нет в БД.\n"
            "\n"
            "   Это происходит когда локальная БД была создана по другой\n"
            "   ветке миграций и объект называется иначе или отсутствует.\n"
            "\n"
            "   ВАРИАНТЫ РЕШЕНИЯ:\n"
            "   1. Сбросить БД (теряются данные):\n"
            "        docker compose -f docker-compose.dev.yml down -v\n"
            "        docker compose -f docker-compose.dev.yml up\n"
            "\n"
            "   2. Пометить миграцию как уже применённую (если схема\n"
            "      фактически уже в нужном состоянии):\n"
            "        docker compose -f docker-compose.dev.yml exec app \\\n"
            "          python -m alembic stamp head\n"
            "        docker compose -f docker-compose.dev.yml restart app\n",
            flush=True,
        )

    elif "DuplicateObject" in combined or "already exists" in combined:
        print(
            "\n⚠  Ошибка: миграция создаёт объект (constraint, index,\n"
            "   колонку), который уже существует в БД.\n"
            "\n"
            "   ВАРИАНТ РЕШЕНИЯ — пометить как применённую:\n"
            "     docker compose -f docker-compose.dev.yml exec app \\\n"
            "       python -m alembic stamp head\n"
            "     docker compose -f docker-compose.dev.yml restart app\n",
            flush=True,
        )

    else:
        print("\nПолный вывод ошибки:", flush=True)
        print(stderr, flush=True)

    print("═" * 60 + "\n", flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
