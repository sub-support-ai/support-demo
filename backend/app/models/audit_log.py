from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Верхний предел длины колонки details.
# Экспортируем как модуль-level константу, чтобы сервис-слой
# (app/services/audit.py) обрезал JSON ровно до этого размера —
# один источник правды, без магических чисел в двух местах.
DETAILS_MAX_LEN = 500


class AuditLog(Base):
    """
    Журнал важных событий безопасности и бизнес-действий.

    Зачем: если завтра выясняется "пропал тикет #42" или "как этот юзер
    стал админом" — без журнала разборки идут по памяти. С журналом —
    один SELECT по user_id/action и картина восстанавливается.

    Что логируем (и НЕ логируем):
      ✓ login.success / login.failure — чтобы ловить попытки брутфорса
      ✓ user.register                 — кто и когда зашёл в систему
      ✓ ticket.create / ticket.delete — разбор "куда делся тикет"
      ✓ user.role_change              — кто и когда выдал админку
      ✗ GET /users/42                 — тысячи в день, это не аудит,
                                        а полный request-log (не делаем)

    Дизайн-решения:

    1) user_id — Optional и БЕЗ FK, с индексом.
       Почему Optional: при login.failure с несуществующим username
       пользователя нет. Пишем NULL + ip, чтобы видеть "с этого IP
       был брут-форс на несуществующие логины".
       Почему без FK: если юзера удалят (GDPR-запрос "забудьте меня"),
       мы НЕ хотим терять аудит. FK с ondelete=CASCADE уничтожил бы
       историю действий удалённого юзера — ровно то, что нужно сохранять.

    2) target_id/target_type — тоже без FK.
       Аудит про удаление тикета должен остаться, когда самого тикета
       уже нет. target_type хранит строку ("ticket"|"user"), чтобы потом
       понимать, что это за id.

    3) action как строка, не enum.
       Добавить новое событие = просто передать новую строку. Enum
       потребовал бы миграции БД на каждое новое действие.
       Принятая конвенция имён: "domain.verb" ("ticket.delete",
       "user.role_change"). Единообразно и читаемо.

    4) details оставлен строкой JSON, а не JSONB.
       JSONB есть только в Postgres, а в тестах мы используем SQLite.
       Писать туда будем json.dumps(...), читать — json.loads(...).
       Нагрузки типа "найди все события, где details.role='admin'"
       у нас не будет — SELECT всегда по (user_id, created_at).

    5) Индекс (user_id, created_at DESC).
       Главный запрос: "дай последние N событий юзера X" —
       без составного индекса это full scan по всей таблице.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Кто сделал действие. NULL если действие анонимное (например,
    # login.failure с несуществующим username — субъекта ещё нет).
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Что произошло: "login.success", "ticket.delete", ...
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # На что действие было направлено. Например, action="ticket.delete" →
    # target_type="ticket", target_id=42.
    target_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # IP клиента — нужен для login.failure без user_id (ловить брут-форс
    # по IP). Для всех событий полезно видеть "откуда".
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # 45 символов = потолок для IPv6 ("ffff:ffff:ffff:ffff:ffff:ffff:255.255.255.255").

    # Произвольный контекст как JSON-строка. Примеры:
    #   user.role_change → '{"from": "user", "to": "admin"}'
    #   ticket.create    → '{"department": "IT", "priority": "высокий"}'
    details: Mapped[str | None] = mapped_column(String(DETAILS_MAX_LEN), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
