"""Corridas com commits reais (banco vazio exclusivo, sem a transação revertida dos outros testes).

- Tarefa 5.8: dois usuários aceitam o mesmo convite ao mesmo tempo → exatamente um vence.
- Regra do último admin (5.6) sob concorrência: dois admins rebaixam um ao outro.

Os testes "determinísticos" seguram a primeira transação aberta e verificam que a segunda
está de fato bloqueada esperando a trava; só então liberam a primeira. Sem o FOR UPDATE,
a segunda não esperaria e o resultado mudaria.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from hm_api.main import create_app
from hm_identity.domain.invites import hash_code
from hm_identity.domain.memberships import LastAdminError, ensure_an_admin_remains
from hm_identity.infra import memberships
from hm_platform import migrations
from hm_platform.db import create_engine, create_session_factory
from hm_platform.ids import uuid7
from hm_platform.migrations import ModuleMigrations
from hm_platform.rls import set_tenant_context
from hm_platform.roles import Role
from hm_platform.settings import DatabaseSettings, OTelSettings, Settings
from hm_platform.testing.tokens import FakeJWKS, TokenFactory

LOCK_WAIT = 0.5  # segundos: tempo para a 2ª transação chegar na trava


@dataclass
class LiveDatabase:
    settings: DatabaseSettings
    migrator: AsyncEngine
    app: AsyncEngine


@pytest_asyncio.fixture
async def live_db(
    empty_database_settings: DatabaseSettings, module_migrations: Sequence[ModuleMigrations]
) -> AsyncIterator[LiveDatabase]:
    migrator = create_engine(empty_database_settings, "migrator")
    app = create_engine(empty_database_settings, "app")
    await migrations.upgrade(migrator, module_migrations)
    try:
        yield LiveDatabase(empty_database_settings, migrator, app)
    finally:
        await app.dispose()
        await migrator.dispose()


async def seed(
    db: LiveDatabase, users: list[str], admins: list[str]
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """Usuários e um lar com os ``admins``, gravados (commit) como o seed faria (hm_migrator)."""
    ids = {name: uuid7() for name in users}
    household = uuid7()
    async with db.migrator.begin() as conn:
        for name, user_id in ids.items():
            await conn.execute(
                text("insert into identity.users (id, subject, name) values (:id, :sub, :name)"),
                {"id": user_id, "sub": f"kc-{name}", "name": name},
            )
        await conn.execute(
            text("insert into identity.households (id, name) values (:id, 'Lar')"),
            {"id": household},
        )
        for name in admins:
            await conn.execute(
                text("insert into identity.memberships values (:h, :u, 'admin')"),
                {"h": household, "u": ids[name]},
            )
    return household, ids


async def seed_invite(
    db: LiveDatabase, household: uuid.UUID, created_by: uuid.UUID, code: str
) -> None:
    async with db.migrator.begin() as conn:
        await conn.execute(
            text(
                "insert into identity.invites "
                "(id, household_id, code_hash, role, expires_at, created_by) "
                "values (:id, :h, :hash, 'member', now() + interval '7 days', :by)"
            ),
            {"id": uuid7(), "h": household, "hash": hash_code(code), "by": created_by},
        )


async def redeem(conn: AsyncConnection, user_id: uuid.UUID, code: str) -> str:
    await conn.execute(text("select set_config('app.user_id', :u, true)"), {"u": str(user_id)})
    outcome: str = await conn.scalar(
        text("select outcome from identity.redeem_invite(:h, :u)"),
        {"h": hash_code(code), "u": user_id},
    )
    return outcome


async def is_blocked(task: asyncio.Task[object]) -> bool:
    done, _ = await asyncio.wait({task}, timeout=LOCK_WAIT)
    return not done


# --- 5.8: aceite simultâneo do mesmo convite ---------------------------------------------


async def test_concurrent_accepts_of_same_invite_only_one_wins(live_db: LiveDatabase) -> None:
    household, ids = await seed(live_db, ["alice", "u1", "u2"], admins=["alice"])
    await seed_invite(live_db, household, ids["alice"], "the-code")

    async with live_db.app.connect() as first, live_db.app.connect() as second:
        await first.begin()
        assert await redeem(first, ids["u1"], "the-code") == "accepted"  # ainda sem commit

        await second.begin()
        racing = asyncio.create_task(redeem(second, ids["u2"], "the-code"))
        assert await is_blocked(racing), "o 2º aceite deveria esperar a trava do 1º"

        await first.commit()
        assert await racing == "gone"  # 410 na API
        await second.commit()

    async with live_db.migrator.connect() as conn:
        members = (await conn.scalars(text("select user_id from identity.memberships"))).all()
    assert set(members) == {ids["alice"], ids["u1"]}


async def test_concurrent_accepts_over_http_exactly_one_succeeds(
    live_db: LiveDatabase, fake_jwks: FakeJWKS, token_factory: TokenFactory, settings: Settings
) -> None:
    """Ponta a ponta, com a sessão real (commit por requisição) e várias rodadas."""
    live_settings = settings.model_copy(
        update={"db": live_db.settings, "otel": OTelSettings(enabled=False)}
    )
    app = create_app(live_settings, http_transport=fake_jwks.transport())

    def headers(name: str) -> dict[str, str]:
        token = token_factory.valid(sub=f"kc-live-{name}", email=f"{name}@example.com", name=name)
        return {"Authorization": f"Bearer {token}"}

    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        household = (
            await client.post("/households", headers=headers("owner"), json={"name": "Lar"})
        ).json()
        for round_ in range(5):
            invite = await client.post(
                f"/households/{household['id']}/invites", headers=headers("owner"), json={}
            )
            racers = [f"r{round_}a", f"r{round_}b"]
            for name in racers:  # provisiona antes, para a corrida ser só no aceite
                assert (await client.get("/me", headers=headers(name))).status_code == 200

            responses = await asyncio.gather(
                *(
                    client.post(
                        "/invites/accept", headers=headers(n), json={"code": invite.json()["code"]}
                    )
                    for n in racers
                )
            )

            assert sorted(r.status_code for r in responses) == [200, 410]

        members = await client.get(
            f"/households/{household['id']}/members", headers=headers("owner")
        )
        assert len(members.json()) == 1 + 5


# --- 5.6 sob concorrência: o lar nunca fica sem admin ------------------------------------


async def demote(
    session: AsyncSession, household: uuid.UUID, actor: uuid.UUID, target: uuid.UUID
) -> str:
    """O que o endpoint PATCH /members faz, passo a passo, numa transação já aberta."""
    await set_tenant_context(session, user_id=actor, household_id=household)
    admins = await memberships.lock_admins(session, household)
    try:
        ensure_an_admin_remains(admins, target, Role.MEMBER)
    except LastAdminError:
        return "409"
    found = await memberships.get_member(session, household, target)
    assert found is not None
    await memberships.set_role(session, found[0], Role.MEMBER)
    return "200"


async def test_two_admins_demoting_each_other_leave_one_admin(live_db: LiveDatabase) -> None:
    household, ids = await seed(live_db, ["alice", "dave"], admins=["alice", "dave"])
    sessions = create_session_factory(live_db.app)

    async with sessions() as first, sessions() as second:
        await first.begin()
        assert await demote(first, household, ids["alice"], ids["dave"]) == "200"  # sem commit

        await second.begin()
        racing = asyncio.create_task(demote(second, household, ids["dave"], ids["alice"]))
        assert await is_blocked(racing), "a 2ª alteração deveria esperar a trava dos admins"

        await first.commit()
        assert await racing == "409"
        await second.rollback()

    async with live_db.migrator.connect() as conn:
        admins = (
            await conn.scalars(
                text("select user_id from identity.memberships where role = 'admin'")
            )
        ).all()
    assert admins == [ids["alice"]]
