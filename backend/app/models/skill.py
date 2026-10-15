from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)

    candidate_links: Mapped[list["CandidateSkill"]] = relationship(back_populates="skill")
    job_links: Mapped[list["JobSkill"]] = relationship(back_populates="skill")
