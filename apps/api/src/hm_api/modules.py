"""Módulos que compõem o monolito: routers e migrações, na ordem em que sobem."""

from fastapi import APIRouter

from hm_identity import public as identity
from hm_platform.migrations import ModuleMigrations

# identity primeiro: os outros módulos guardam ids de usuário e lar (sem FK, design D3).
MIGRATIONS: tuple[ModuleMigrations, ...] = tuple(
    ModuleMigrations(name=name, schema=name, script_location=f"hm_{name}:migrations")
    for name in ("identity", "finance", "tasks", "inventory", "notifications")
)

# Os demais módulos ainda não têm rotas; cada um entra aqui pelo seu ``public.router``.
ROUTERS: tuple[APIRouter, ...] = (identity.router,)
