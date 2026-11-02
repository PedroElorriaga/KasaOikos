"""Modelos ORM do módulo tasks, todos no schema ``tasks``."""

from sqlalchemy.orm import DeclarativeBase

from hm_platform.db import schema_metadata


class Base(DeclarativeBase):
    metadata = schema_metadata("tasks")
