#!/bin/bash
# Banco da aplicação, roles e um schema por módulo (design D3/D4).
#   hm_migrator: dono do banco e dos schemas; roda migrações e o seed. Nunca é
#                usado pela API. Tem BYPASSRLS porque, com FORCE ROW LEVEL SECURITY,
#                o próprio dono das tabelas fica sujeito às políticas.
#   hm_app:      usado pela API; só DML, sem BYPASSRLS. Fica sujeito ao RLS.
# Sem "set" próprio: ver comentário em 01-keycloak.sh.

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v migrator_password="$HM_MIGRATOR_PASSWORD" \
  -v app_password="$HM_APP_PASSWORD" <<'EOSQL'
CREATE ROLE hm_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS
  PASSWORD :'migrator_password';
CREATE ROLE hm_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'app_password';

CREATE DATABASE home OWNER hm_migrator;
REVOKE ALL ON DATABASE home FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE home TO hm_app;

\connect home

-- Funções criadas pelo hm_migrator não ficam executáveis por PUBLIC; o hm_app
-- recebe EXECUTE por schema (ex.: identity.redeem_invite, design D7).
ALTER DEFAULT PRIVILEGES FOR ROLE hm_migrator REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

DO $$
DECLARE
  s text;
BEGIN
  FOREACH s IN ARRAY ARRAY['identity', 'finance', 'tasks', 'inventory', 'notifications'] LOOP
    EXECUTE format('CREATE SCHEMA %I AUTHORIZATION hm_migrator', s);
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO hm_app', s);
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE hm_migrator IN SCHEMA %I '
      'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hm_app', s);
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE hm_migrator IN SCHEMA %I '
      'GRANT USAGE, SELECT ON SEQUENCES TO hm_app', s);
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE hm_migrator IN SCHEMA %I '
      'GRANT EXECUTE ON FUNCTIONS TO hm_app', s);
  END LOOP;
END
$$;
EOSQL
