#!/bin/bash
# Banco e role próprios do Keycloak, separados do banco da aplicação.
# Sem "set" próprio: o entrypoint do Postgres faz source deste arquivo quando ele
# não é executável (caso comum em clones no Windows) e já roda com -Eeo pipefail.

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v kc_password="$KEYCLOAK_DB_PASSWORD" <<'EOSQL'
CREATE ROLE keycloak LOGIN PASSWORD :'kc_password';
CREATE DATABASE keycloak OWNER keycloak;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
EOSQL
