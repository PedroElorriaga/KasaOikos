"""CLI ``hm``; a configuração vem de ``HM_*`` (ver settings).

hm serve --host 0.0.0.0          # sobe a API com HM_WORKERS processos
hm migrate                       # sobe todos os módulos até a head
hm migrate down --yes            # desce todos até a base (apaga os dados!)
hm migrate current               # revisão atual de cada módulo
hm migrate revision identity -m "create users" --autogenerate
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

import uvicorn

from hm_api.modules import MIGRATIONS
from hm_platform import migrations
from hm_platform.db import create_engine
from hm_platform.logs import configure_logging
from hm_platform.settings import get_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hm")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="sobe a API (uvicorn)")
    serve.add_argument("--host", default="127.0.0.1", help="no container, 0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)

    migrate = commands.add_parser("migrate", help="migrações de todos os módulos")
    actions = migrate.add_subparsers(dest="action")
    actions.add_parser("up", help="sobe todos os módulos até a head (padrão)")
    down = actions.add_parser("down", help="desce todos os módulos até a base")
    down.add_argument("--yes", action="store_true", help="confirma a remoção dos dados")
    actions.add_parser("current", help="mostra a revisão atual de cada módulo")
    rev = actions.add_parser("revision", help="cria uma revisão em um módulo")
    rev.add_argument("module", choices=[m.name for m in MIGRATIONS])
    rev.add_argument("-m", "--message", required=True)
    rev.add_argument("--autogenerate", action="store_true")
    return parser


async def _migrate(args: argparse.Namespace) -> int:
    settings = get_settings()
    # O Alembic registra cada revisão aplicada. No stderr: o stdout é a saída do comando
    # (``hm migrate current``).
    configure_logging(settings.log_level, stream=sys.stderr)
    engine = create_engine(settings.db, "migrator", application_name="hm-migrate")
    try:
        match args.action:
            case None | "up":
                await migrations.upgrade(engine, MIGRATIONS)
            case "down":
                if not args.yes:
                    print("`hm migrate down` apaga as tabelas de todos os módulos; use --yes.")
                    return 2
                await migrations.downgrade(engine, MIGRATIONS)
            case "current":
                for name, revs in (await migrations.current(engine, MIGRATIONS)).items():
                    print(f"{name:<14} {', '.join(sorted(revs)) or '(base)'}")
            case "revision":
                module = next(m for m in MIGRATIONS if m.name == args.module)
                await migrations.revision(
                    engine, module, args.message, autogenerate=args.autogenerate
                )
    finally:
        await engine.dispose()
    return 0


def _serve(args: argparse.Namespace) -> int:
    settings = get_settings()
    # Com vários workers, este processo só supervisiona; cada worker monta a sua app
    # (e reconfigura o logging, agora com o envio OTLP).
    configure_logging(settings.log_level)
    uvicorn.run(
        "hm_api.main:create_production_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=settings.workers,
        # Os logs do uvicorn passam pelo nosso pipeline JSON (configurado acima e na
        # app), e o access log é o nosso: rota template e sem query string.
        log_config=None,
        access_log=False,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    match args.command:
        case "serve":
            return _serve(args)
        case "migrate":
            return asyncio.run(_migrate(args))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
