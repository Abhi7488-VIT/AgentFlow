"""Tests for role assignment on signup.

Previously every registration was created with role="admin", which made
the require_role("admin") checks on the admin and monitoring routes
meaningless. Only the bootstrap account should be an admin.
"""

import pytest
from sqlalchemy import select

from app.models.user import User
from app.schemas.user import UserCreate
from app.services.auth_service import authenticate_user, create_user
from tests.conftest import TestSessionLocal


def _new_user(email: str) -> UserCreate:
    return UserCreate(email=email, password="Correct-Horse-Battery9", full_name="Test User")


@pytest.mark.asyncio
class TestRoleAssignment:
    async def test_first_user_bootstraps_as_admin(self):
        async with TestSessionLocal() as db:
            user = await create_user(db, _new_user("first@example.com"))
            assert user.role == "admin"

    async def test_subsequent_users_are_not_admins(self):
        async with TestSessionLocal() as db:
            first = await create_user(db, _new_user("first@example.com"))
            second = await create_user(db, _new_user("second@example.com"))
            third = await create_user(db, _new_user("third@example.com"))

        assert first.role == "admin"
        assert second.role == "viewer"
        assert third.role == "viewer"

    async def test_privilege_cannot_be_gained_by_registering(self):
        """The actual vulnerability: signing up must not grant admin."""
        async with TestSessionLocal() as db:
            await create_user(db, _new_user("owner@example.com"))
            attacker = await create_user(db, _new_user("attacker@example.com"))

            result = await db.execute(
                select(User).where(User.email == "attacker@example.com")
            )
            persisted = result.scalar_one()

        assert attacker.role == "viewer"
        assert persisted.role == "viewer", "role must not be admin in the database either"


@pytest.mark.asyncio
class TestAuthentication:
    async def test_correct_password_authenticates(self):
        async with TestSessionLocal() as db:
            await create_user(db, _new_user("user@example.com"))
            user = await authenticate_user(db, "user@example.com", "Correct-Horse-Battery9")

        assert user is not None
        assert user.email == "user@example.com"

    async def test_wrong_password_is_rejected(self):
        async with TestSessionLocal() as db:
            await create_user(db, _new_user("user@example.com"))
            assert await authenticate_user(db, "user@example.com", "wrong") is None

    async def test_unknown_email_is_rejected(self):
        async with TestSessionLocal() as db:
            assert await authenticate_user(db, "nobody@example.com", "whatever") is None

    async def test_password_is_not_stored_in_plaintext(self):
        async with TestSessionLocal() as db:
            user = await create_user(db, _new_user("user@example.com"))

        assert user.hashed_password != "Correct-Horse-Battery9"
        assert len(user.hashed_password) > 20
