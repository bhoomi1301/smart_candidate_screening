from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from backend.app.schemas.common import InputSchema, OutputSchema


class RegisterInput(InputSchema):
    workspace_name: str = Field(min_length=2, max_length=160)
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    password_confirmation: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.password_confirmation:
            raise ValueError("Password confirmation does not match")
        return self


class LoginInput(InputSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserCreate(InputSchema):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    role: Literal["hr"] = "hr"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserRead(OutputSchema):
    id: int
    workspace_id: int
    full_name: str
    email: EmailStr
    role: Literal["admin", "hr"]
    is_active: bool
    created_at: datetime


class AuthResponse(OutputSchema):
    user: UserRead
    workspace_id: int
    access_expires_in: int
    refresh_expires_in: int
    csrf_token: str
