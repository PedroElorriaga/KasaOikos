"""Seed da baseline (tarefa 8.1; design D11): usuários no Keycloak, lares no Postgres.

    uv run python loadtest/seed.py --env-file infra/.env --households 1000

- **Usuários** entram no Keycloak pela Admin API em lote (*partial import*), com o
  hash da senha já calculado aqui: um PBKDF2 só, repetido em todos. Deixar o Keycloak
  calcular um Argon2 por usuário custa ~40 ms cada (2 min para 3.000 usuários).
- **Lares, usuários locais e memberships** entram direto no Postgres como
  ``hm_migrator`` (BYPASSRLS), com os mesmos e-mail e nome que o token terá: o
  provisionamento just-in-time da API não precisa escrever no primeiro acesso.
- **Idempotente e incremental**: os ids são determinísticos (UUIDv7 com timestamp
  fixo + hash do índice), o Keycloak pula usuários existentes e o SQL usa
  ``ON CONFLICT DO NOTHING``. Rodar de novo com mais lares só acrescenta os novos.

Contas sintéticas, só para laboratório: todas com a mesma senha (HM_SEED_USER_PASSWORD).
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import httpx

from hm_platform.ids import uuid7_from

from common import (
    DEFAULT_ENV_FILE,
    SEED_EMAIL_DOMAIN,
    keycloak_url,
    load_env,
    require,
    seed_username,
    server,
)

# Timestamp dos ids do seed (2026-01-01T00:00:00Z) + índice: ids ordenados e estáveis.
SEED_EPOCH_MS = 1_767_225_600_000
PBKDF2_ITERATIONS = 27_500
REALM = "home"


def seed_uuid(kind: str, index: int) -> uuid.UUID:
    digest = hashlib.sha256(f"home-manager-seed:{kind}:{index}".encode()).digest()
    return uuid7_from(SEED_EPOCH_MS + index, digest[:10])


@dataclass(frozen=True)
class SeedUser:
    index: int
    household: int
    member: int

    @property
    def username(self) -> str:
        return seed_username(self.household, self.member)

    @property
    def subject(self) -> str:  # o "sub" do token é o id do usuário no Keycloak
        return str(seed_uuid("keycloak-user", self.index))

    @property
    def email(self) -> str:
        return f"{self.username}@{SEED_EMAIL_DOMAIN}"

    @property
    def first_name(self) -> str:
        return "Seed"

    @property
    def last_name(self) -> str:
        return f"{self.household:05d}-{self.member}"

    @property
    def name(self) -> str:  # claim "name" do Keycloak: nome + sobrenome
        return f"{self.first_name} {self.last_name}"

    @property
    def role(self) -> str:
        return "admin" if self.member == 1 else "member"


def seed_users(households: int, members: int) -> list[SeedUser]:
    return [
        SeedUser(index=(h - 1) * members + (m - 1), household=h, member=m)
        for h in range(1, households + 1)
        for m in range(1, members + 1)
    ]


def password_credential(password: str) -> dict[str, object]:
    """Credencial no formato de armazenamento do Keycloak (provider pbkdf2-sha256)."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return {
        "type": "password",
        "temporary": False,
        "secretData": json.dumps(
            {
                "value": base64.b64encode(digest).decode(),
                "salt": base64.b64encode(salt).decode(),
                "additionalParameters": {},
            }
        ),
        "credentialData": json.dumps(
            {
                "hashIterations": PBKDF2_ITERATIONS,
                "algorithm": "pbkdf2-sha256",
                "additionalParameters": {},
            }
        ),
    }


def chunks[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def import_keycloak_users(
    env: dict[str, str], users: Sequence[SeedUser], password: str, batch: int
) -> tuple[int, int]:
    credential = password_credential(password)
    added = skipped = 0
    with httpx.Client(base_url=keycloak_url(env), timeout=120) as kc:
        for part in chunks(users, batch):
            # Token novo por lote: o do admin-cli vale só 60 s.
            token = (
                kc.post(
                    "/realms/master/protocol/openid-connect/token",
                    data={
                        "grant_type": "password",
                        "client_id": "admin-cli",
                        "username": env.get("KEYCLOAK_ADMIN_USER", "admin"),
                        "password": require(env, "KEYCLOAK_ADMIN_PASSWORD"),
                    },
                )
                .raise_for_status()
                .json()["access_token"]
            )
            result = (
                kc.post(
                    f"/admin/realms/{REALM}/partialImport",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "ifResourceExists": "SKIP",
                        "users": [
                            {
                                "id": u.subject,
                                "username": u.username,
                                "email": u.email,
                                "firstName": u.first_name,
                                "lastName": u.last_name,
                                "enabled": True,
                                "emailVerified": True,
                                "credentials": [credential],
                            }
                            for u in part
                        ],
                    },
                )
                .raise_for_status()
                .json()
            )
            added += result["added"]
            skipped += result["skipped"]
    return added, skipped


async def insert_rows(env: dict[str, str], users: Sequence[SeedUser], households: int) -> None:
    conn = await asyncpg.connect(
        host=server(env),
        port=int(env.get("POSTGRES_PORT", "5432")),
        database="home",
        user="hm_migrator",
        password=require(env, "HM_MIGRATOR_PASSWORD"),
    )
    try:
        async with conn.transaction():
            await conn.executemany(
                "insert into identity.users (id, subject, email, name) values ($1, $2, $3, $4)"
                " on conflict (subject) do nothing",
                [(seed_uuid("user", u.index), u.subject, u.email, u.name) for u in users],
            )
            # O usuário pode já existir com outro id (criado pela API num acesso anterior).
            user_ids = dict(
                await conn.fetch(
                    "select subject, id from identity.users where subject = any($1::text[])",
                    [u.subject for u in users],
                )
            )
            await conn.executemany(
                "insert into identity.households (id, name) values ($1, $2)"
                " on conflict (id) do nothing",
                [(seed_uuid("household", h), f"Seed {h:05d}") for h in range(1, households + 1)],
            )
            await conn.executemany(
                "insert into identity.memberships (household_id, user_id, role)"
                " values ($1, $2, $3) on conflict do nothing",
                [(seed_uuid("household", u.household), user_ids[u.subject], u.role) for u in users],
            )
        counts = await conn.fetchrow(
            """
            select
              (select count(*) from identity.users where email like '%@' || $1) as users,
              (select count(*) from identity.households where name like 'Seed %') as households,
              (select count(*) from identity.memberships m
                 join identity.users u on u.id = m.user_id
                where u.email like '%@' || $1) as memberships,
              (select count(*) from identity.memberships m
                 join identity.users u on u.id = m.user_id
                where u.email like '%@' || $1 and m.role = 'admin') as admins
            """,
            SEED_EMAIL_DOMAIN,
        )
        print("banco:", dict(counts))
    finally:
        await conn.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--households", type=int, default=1000)
    parser.add_argument("--members", type=int, default=3, help="por lar; o 1º é admin")
    parser.add_argument("--batch", type=int, default=500, help="usuários por partial import")
    args = parser.parse_args(argv)

    env = load_env(args.env_file if args.env_file.exists() else None)
    users = seed_users(args.households, args.members)
    print(f"alvo: {server(env)} · {args.households} lares × {args.members} membros")

    started = time.perf_counter()
    added, skipped = import_keycloak_users(
        env, users, require(env, "HM_SEED_USER_PASSWORD"), args.batch
    )
    print(
        f"keycloak: {added} criados, {skipped} já existiam ({time.perf_counter() - started:.1f} s)"
    )

    started = time.perf_counter()
    asyncio.run(insert_rows(env, users, args.households))
    print(f"banco em {time.perf_counter() - started:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
