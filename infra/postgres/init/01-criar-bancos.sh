#!/bin/bash
# Roda DENTRO do container do Postgres, só na primeira subida (volume vazio).
# Cria um banco e um usuário por consumidor (menor privilégio):
#   - `app`      → dono APP_DB_USER      (API)
#   - `keycloak` → dono KEYCLOAK_DB_USER (Keycloak)
# Nenhum dos dois é superusuário nem cria bancos/papéis, e um não conecta no banco do outro.
#
# O entrypoint do Postgres pode executar ou fazer `source` deste arquivo, por isso
# ele não usa `exit` nem altera opções do shell.

: "${APP_DB_USER:?APP_DB_USER não definido}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD não definido}"
: "${KEYCLOAK_DB_USER:?KEYCLOAK_DB_USER não definido}"
: "${KEYCLOAK_DB_PASSWORD:?KEYCLOAK_DB_PASSWORD não definido}"

# Os valores entram como variáveis do psql (:"ident" e :'literal'), que fazem o
# escape correto; nada de montar SQL concatenando texto. O heredoc com aspas
# impede o shell de expandir qualquer coisa dentro do SQL.
psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v app_user="$APP_DB_USER" \
  -v app_password="$APP_DB_PASSWORD" \
  -v kc_user="$KEYCLOAK_DB_USER" \
  -v kc_password="$KEYCLOAK_DB_PASSWORD" <<'EOSQL'
CREATE ROLE :"app_user" WITH LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE DATABASE app OWNER :"app_user";
REVOKE ALL ON DATABASE app FROM PUBLIC;

CREATE ROLE :"kc_user" WITH LOGIN PASSWORD :'kc_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE DATABASE keycloak OWNER :"kc_user";
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
EOSQL
