from datetime import datetime

from backend.app.schemas.common import OutputSchema


class AuditLogRead(OutputSchema):
    id: int
    actor_id: int | None
    actor_name: str | None
    action: str
    resource_type: str
    resource_id: int | None
    metadata: dict
    created_at: datetime


class AuditLogPage(OutputSchema):
    items: list[AuditLogRead]
    total: int
    skip: int
    limit: int
