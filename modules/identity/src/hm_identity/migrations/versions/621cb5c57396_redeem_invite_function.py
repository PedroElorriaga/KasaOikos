"""redeem invite function

Revision ID: 621cb5c57396
Revises: 492f19bec177
Create Date: 2026-10-21 22:37:52.931871

"""

from collections.abc import Sequence

from alembic import op

revision: str = '621cb5c57396'
down_revision: str | Sequence[str] | None = '492f19bec177'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Aceite de convite (design D4/D7). Quem aceita ainda não é membro do lar, então o RLS
# o impediria de ver o convite e de criar a própria membership. A função roda como o
# dono (SECURITY DEFINER = hm_migrator, que tem BYPASSRLS) e por isso é blindada:
# - search_path fixo e nomes qualificados: ninguém troca uma tabela por um objeto falso;
# - só aceita o próprio usuário autenticado da transação (app.user_id);
# - FOR UPDATE no convite: aceites simultâneos ficam em fila, só o primeiro vence;
# - checa "já é membro" antes de consumir o convite (ele continua válido nesse caso).
REDEEM_INVITE = """
CREATE FUNCTION identity.redeem_invite(p_code_hash text, p_user_id uuid)
RETURNS TABLE (outcome text, household_id uuid, role text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_invite identity.invites%ROWTYPE;
BEGIN
  IF p_user_id IS DISTINCT FROM nullif(current_setting('app.user_id', true), '')::uuid THEN
    RAISE EXCEPTION 'redeem_invite: user does not match the authenticated user';
  END IF;

  SELECT * INTO v_invite FROM identity.invites i WHERE i.code_hash = p_code_hash FOR UPDATE;
  IF NOT FOUND THEN
    RETURN QUERY SELECT 'not_found'::text, NULL::uuid, NULL::text;
    RETURN;
  END IF;

  IF v_invite.status <> 'pending' OR v_invite.expires_at <= now() THEN
    RETURN QUERY SELECT 'gone'::text, NULL::uuid, NULL::text;
    RETURN;
  END IF;

  IF EXISTS (
    SELECT 1 FROM identity.memberships m
    WHERE m.household_id = v_invite.household_id AND m.user_id = p_user_id
  ) THEN
    RETURN QUERY SELECT 'already_member'::text, v_invite.household_id, NULL::text;
    RETURN;
  END IF;

  UPDATE identity.invites
     SET status = 'accepted', accepted_by = p_user_id, accepted_at = now()
   WHERE id = v_invite.id;
  INSERT INTO identity.memberships (household_id, user_id, role)
  VALUES (v_invite.household_id, p_user_id, v_invite.role);

  RETURN QUERY SELECT 'accepted'::text, v_invite.household_id, v_invite.role::text;
END;
$$
"""


def upgrade() -> None:
    op.execute(REDEEM_INVITE)
    # Explícito, sem depender só dos default privileges do init: só a API executa.
    op.execute("REVOKE ALL ON FUNCTION identity.redeem_invite(text, uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION identity.redeem_invite(text, uuid) TO hm_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION identity.redeem_invite(text, uuid)")
