"""
Импорт моделей, чтобы они регистрировались в `Base.metadata`.

`app.main` делает `import app.models`, поэтому этот модуль обязан импортировать
все SQLAlchemy-модели, иначе `create_all()` создаст только часть таблиц.

Порядок важен: модели без внешних ключей идут первыми.
"""

from app.models.agent import Agent  # noqa: F401
from app.models.ai_fallback_event import AIFallbackEvent  # noqa: F401
from app.models.ai_job import AIJob  # noqa: F401
from app.models.ai_log import AILog  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.conversation import Conversation  # noqa: F401
from app.models.knowledge_article import KnowledgeArticle  # noqa: F401
from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob  # noqa: F401
from app.models.message import Message  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.response import Response  # noqa: F401
from app.models.response_template import ResponseTemplate  # noqa: F401
from app.models.ticket import Ticket  # noqa: F401
from app.models.ticket_comment import TicketComment  # noqa: F401
from app.models.ticket_rating import TicketRating  # noqa: F401
from app.models.user import User  # noqa: F401
