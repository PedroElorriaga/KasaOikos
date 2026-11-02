"""Spec platform/tenant-isolation, "Isolamento garantido pelo banco": SQL direto como hm_app."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from hm_platform.ids import uuid7
from hm_platform.rls import set_tenant_context

from .conftest import World


async def ids(session: AsyncSession, sql: str) -> set[uuid.UUID]:
    return set((await session.scalars(text(sql))).all())


async def insert_invite(
    session: AsyncSession, household_id: uuid.UUID, created_by: uuid.UUID
) -> None:
    await session.execute(
        text(
            "insert into identity.invites "
            "(id, household_id, code_hash, role, expires_at, created_by) "
            "values (:id, :h, :hash, 'member', :exp, :by)"
        ),
        {
            "id": uuid7(),
            "h": household_id,
            "hash": uuid.uuid4().hex,
            "exp": datetime.now(UTC) + timedelta(days=7),
            "by": created_by,
        },
    )


async def test_without_active_household_nothing_is_visible(
    db_session: AsyncSession, world: World
) -> None:
    # Cenário: Consulta sem lar ativo.
    await set_tenant_context(db_session, user_id=None, household_id=None)
    for table in ("households", "memberships", "invites"):
        assert await db_session.scalar(text(f"select count(*) from identity.{table}")) == 0


async def test_query_without_filter_sees_only_active_household(
    db_session: AsyncSession, world: World
) -> None:
    # Cenário: Consulta sem filtro de lar.
    for household, admin in ((world.household_a, world.alice), (world.household_b, world.carol)):
        await set_tenant_context(db_session, user_id=admin, household_id=household)
        await insert_invite(db_session, household, admin)

    await set_tenant_context(db_session, user_id=None, household_id=world.household_a)

    assert await ids(db_session, "select household_id from identity.invites") == {world.household_a}
    assert await ids(db_session, "select id from identity.households") == {world.household_a}
    assert await ids(db_session, "select user_id from identity.memberships") == {
        world.alice,
        world.bob,
    }


async def test_insert_into_other_household_is_rejected(
    db_session: AsyncSession, world: World
) -> None:
    # Cenário: Escrita em outro lar (INSERT).
    await set_tenant_context(db_session, user_id=world.alice, household_id=world.household_a)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with db_session.begin_nested():
            await insert_invite(db_session, world.household_b, world.alice)


async def test_update_of_other_household_is_rejected(
    db_session: AsyncSession, world: World
) -> None:
    # Cenário: Escrita em outro lar (UPDATE): a linha de B é invisível e mover uma linha
    # de A para B viola o WITH CHECK.
    await set_tenant_context(db_session, user_id=world.alice, household_id=world.household_a)

    result = await db_session.execute(
        text("update identity.households set name = 'hack' where id = :b"), {"b": world.household_b}
    )
    assert result.rowcount == 0  # type: ignore[attr-defined]

    with pytest.raises(DBAPIError, match="row-level security"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("update identity.memberships set household_id = :b where user_id = :bob"),
                {"b": world.household_b, "bob": world.bob},
            )


async def test_user_sees_own_memberships_and_households_across_households(
    db_session: AsyncSession, world: World
) -> None:
    # Base do GET /me: sem lar ativo, o usuário enxerga só os próprios vínculos.
    await set_tenant_context(db_session, user_id=world.carol, household_id=world.household_a)
    await db_session.execute(
        text(
            "insert into identity.memberships (household_id, user_id, role) "
            "values (:a, :c, 'member')"
        ),
        {"a": world.household_a, "c": world.carol},
    )

    await set_tenant_context(db_session, user_id=world.carol, household_id=None)

    assert await ids(db_session, "select household_id from identity.memberships") == {
        world.household_a,
        world.household_b,
    }
    assert await ids(db_session, "select user_id from identity.memberships") == {world.carol}
    assert await ids(db_session, "select id from identity.households") == {
        world.household_a,
        world.household_b,
    }


async def test_user_without_households_sees_nothing(db_session: AsyncSession, world: World) -> None:
    await set_tenant_context(db_session, user_id=world.dave, household_id=None)
    assert await ids(db_session, "select id from identity.households") == set()
    assert await ids(db_session, "select household_id from identity.memberships") == set()


async def test_cannot_add_own_membership_to_a_household_that_is_not_active(
    db_session: AsyncSession, world: World
) -> None:
    # A leitura aceita "user_id = eu", mas a escrita não: senão um bug na aplicação
    # bastaria para alguém se colocar como membro de qualquer lar.
    await set_tenant_context(db_session, user_id=world.dave, household_id=None)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "insert into identity.memberships (household_id, user_id, role) "
                    "values (:b, :d, 'admin')"
                ),
                {"b": world.household_b, "d": world.dave},
            )


async def test_empty_setting_from_previous_transaction_is_treated_as_no_household(
    app_engine: AsyncEngine, migrated_database: None
) -> None:
    # Depois de um SET LOCAL, a mesma conexão devolve '' (não NULL) na transação seguinte.
    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("select set_config('app.household_id', :h, true)"), {"h": str(uuid7())}
            )
        async with conn.begin():
            assert await conn.scalar(text("select current_setting('app.household_id', true)")) == ""
            # Sem o nullif das políticas, esta consulta falharia com
            # "invalid input syntax for type uuid".
            assert await conn.scalar(text("select count(*) from identity.invites")) == 0
