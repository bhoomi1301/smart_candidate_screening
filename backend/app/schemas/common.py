from pydantic import BaseModel, ConfigDict

# Largest value of a PostgreSQL `integer` column. IDs and offsets above it are client errors (422), not database failures.
MAX_DB_INT = 2_147_483_647


class InputSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class OutputSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
