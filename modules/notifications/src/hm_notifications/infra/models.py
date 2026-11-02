"""Modelos ORM do módulo notifications, todos no schema ``notifications``."""

from sqlalchemy.orm import DeclarativeBase

from hm_platform.db import schema_metadata


class Base(DeclarativeBase):
    metadata = schema_metadata("notifications")
