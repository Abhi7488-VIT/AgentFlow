"""
AgentFlow AI - User Schemas

Pydantic v2 models for user registration, login, profile updates, and token
responses. Single source of truth for all user-related schemas.
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_PATTERN = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"


class UserBase(BaseModel):
    """Shared user fields."""

    email: str = Field(..., max_length=255, description="User email address")
    full_name: str = Field(..., max_length=255, description="User full name")


class UserCreate(UserBase):
    """Schema for new user registration."""

    password: str = Field(
        ..., min_length=8, max_length=128, description="User password"
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(EMAIL_PATTERN, v):
            raise ValueError("Invalid email format")
        return v.lower().strip()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        return v.strip()


class UserLogin(BaseModel):
    """Schema for user login credentials."""

    email: str = Field(..., description="User email")
    password: str = Field(..., description="User password")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip()


class UserResponse(BaseModel):
    """Schema for user data in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    # Nullable in the database, so it must stay optional here.
    full_name: str | None = None
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Schema for JWT authentication token response."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserUpdate(BaseModel):
    """Schema for updating user profile fields."""

    full_name: str | None = Field(None, max_length=255)
    role: str | None = Field(None, pattern=r"^(admin|analyst|viewer)$")

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str | None) -> str | None:
        if v is not None:
            return v.strip()
        return v
