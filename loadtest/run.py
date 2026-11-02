"""Roda um cenário do k6 com o contexto da execução (tarefa 8.2; design D11).

    uv run python loadtest/run.py smoke --env-file infra/.env
    uv run python loadtest/run.py read-heavy --rate 200 --duration 5m --save

Monta o id da execução (data, git sha, cenário), mede a latência de rede até a API,
passa configuração e segredos ao k6 por variáveis de ambiente (não pela linha de
comando) e envia as métricas ao Prometheus por remote write. O resultado vai para
``loadtest/.tmp/`` ou, com ``--save``, para ``loadtest/results/`` (versionado).
"""

import argparse
import os
import shutil
import socket
import statistics
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from common import DEFAULT_ENV_FILE, LOADTEST_DIR, keycloak_url, load_env, require, server

SCENARIOS_DIR = LOADTEST_DIR / "scenarios"
RESULTS_DIR = LOADTEST_DIR / "results"
SCRATCH_DIR = LOADTEST_DIR / ".tmp"


def git_sha() -> str:
    """sha curto do HEAD, com ``-dirty`` se houver mudanças não commitadas."""
    git = shutil.which("git")
    if git is None:
        return "nogit"
    head = subprocess.run(
        [git, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    if head.returncode != 0:
        return "nocommit"
    status = subprocess.run(
        [git, "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    return head.stdout.strip() + ("-dirty" if status.stdout.strip() else "")


def tcp_rtt_ms(host: str, port: int, samples: int = 10) -> float | None:
    """Mediana do tempo de abrir uma conexão TCP: um "ping" que passa por firewall e
    não depende do formato (localizado) da saída do ``ping`` do Windows."""
    times = []
    for _ in range(samples):
        started = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=2):
                times.append((time.perf_counter() - started) * 1000)
        except OSError:
            return None
    return round(statistics.median(times), 3)


def scenario_file(name: str) -> Path:
    path = Path(name)
    if path.suffix == ".js" and path.exists():
        return path.resolve()
    path = SCENARIOS_DIR / f"{name}.js"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in SCENARIOS_DIR.glob("*.js")))
        raise SystemExit(f"cenário {name!r} não existe (disponíveis: {available})")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", help="nome em loadtest/scenarios/ ou caminho de um .js")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--save", action="store_true", help="grava em loadtest/results/")
    parser.add_argument("--rate", type=int, help="iterações/s nos cenários de arrival rate")
    parser.add_argument("--duration", help="duração da fase principal (ex.: 5m)")
    parser.add_argument("--token-pool", type=int, help="lares cujos usuários recebem token")
    parser.add_argument("--no-prometheus", action="store_true", help="sem remote write")
    args = parser.parse_args(argv)

    env = load_env(args.env_file if args.env_file.exists() else None)
    script = scenario_file(args.scenario)
    host = server(env)
    api_port = int(env.get("API_PORT", "8000"))

    started = datetime.now(UTC)
    sha = git_sha()
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{sha}-{script.stem}"
    result_file = (RESULTS_DIR if args.save else SCRATCH_DIR) / f"{run_id}.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    rtt = tcp_rtt_ms(host, api_port)
    if rtt is None:
        raise SystemExit(f"API inacessível em {host}:{api_port}")

    k6_env = {
        **os.environ,
        "API_URL": f"http://{host}:{api_port}",
        "KEYCLOAK_URL": keycloak_url(env),
        "HM_LOADTEST_CLIENT_SECRET": require(env, "HM_LOADTEST_CLIENT_SECRET"),
        "HM_SEED_USER_PASSWORD": require(env, "HM_SEED_USER_PASSWORD"),
        "SEED_HOUSEHOLDS": env.get("SEED_HOUSEHOLDS", "1000"),
        "RUN_ID": run_id,
        "RUN_SCENARIO": script.stem,
        "RUN_STARTED_AT": started.isoformat(),
        "RUN_GIT_SHA": sha,
        "RUN_RTT_MS": str(rtt),
        # Configuração da API no alvo: as mesmas chaves do infra/.env do servidor.
        "RUN_WORKERS": env.get("HM_WORKERS", "2"),
        "RUN_DB_POOL_SIZE": env.get("HM_DB_POOL_SIZE", "10"),
        "RUN_RESULT_FILE": str(result_file),
    }
    for key, value in (("RATE", args.rate), ("DURATION", args.duration)):
        if value is not None:
            k6_env[key] = str(value)
    if args.token_pool is not None:
        k6_env["TOKEN_POOL"] = str(args.token_pool)

    command = [shutil.which("k6") or "k6", "run", "--tag", f"testid={run_id}"]
    if not args.no_prometheus:
        prometheus = f"http://{host}:{env.get('PROMETHEUS_PORT', '9090')}"
        k6_env["K6_PROMETHEUS_RW_SERVER_URL"] = f"{prometheus}/api/v1/write"
        # Histograma nativo: os percentis do k6 saem do PromQL, como os da API, em
        # vez de valores já calculados pelo k6 (que não se agregam nem se recortam).
        k6_env["K6_FEATURES"] = "native-histograms"
        command += ["--out", "experimental-prometheus-rw"]
    command.append(str(script))

    print(f"{run_id} · alvo {host} · RTT TCP {rtt} ms · resultado em {result_file}")
    sys.stdout.flush()
    return subprocess.run(command, env=k6_env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
