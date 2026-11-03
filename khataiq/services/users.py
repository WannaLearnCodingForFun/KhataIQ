"""Users within an org."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from khataiq import audit
from khataiq.errors import Conflict, NotFound
from khataiq.models import User
from khataiq.models.enums import UserRole
from khataiq.principal import Principal
from khataiq.security import hash_password


def get_user(s: Session, user_id: int) -> User:
    user = s.get(User, user_id)
    if user is None:
        raise NotFound("user not found")
    return user


def create_user(s: Session, actor: Principal, email: str, password: str,
                role: UserRole) -> User:
    user = User(org_id=actor.org_id, email=email.strip().lower(),
                password_hash=hash_password(password), role=role)
    s.add(user)
    try:
        with s.begin_nested():
            s.flush()
    except IntegrityError as exc:
        raise Conflict("a user with that email already exists") from exc
    audit.record(s, org_id=actor.org_id, actor_id=actor.id, action="user.create",
                 entity_type="user", entity_id=user.id,
                 after={"email": user.email, "role": user.role})
    return user
