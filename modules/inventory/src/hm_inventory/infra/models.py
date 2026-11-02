"""Modelos ORM do módulo inventory, todos no schema ``inventory``."""

from sqlalchemy.orm import DeclarativeBase

from hm_platform.db import schema_metadata


class Base(DeclarativeBase):
    metadata = schema_metadata("inventory")
