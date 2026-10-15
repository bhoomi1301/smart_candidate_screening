from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.skill import Skill
from backend.app.screening.normalization import normalize_items


def get_or_create_skill(db: Session, display_name: str) -> Skill:
    normalized = next(iter(normalize_items([display_name])))
    skill = db.scalar(select(Skill).where(Skill.normalized_name == normalized))
    if skill is None:
        skill = Skill(normalized_name=normalized, display_name=" ".join(display_name.split()).strip())
        db.add(skill)
        db.flush()
    return skill
