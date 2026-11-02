"""Modelos ORM do módulo finance, todos no schema ``finance``."""

from sqlalchemy.orm import DeclarativeBase

from hm_platform.db import schema_metadata


class Base(DeclarativeBase):
    metadata = schema_metadata("finance")
