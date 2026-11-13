import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["saude"])


@router.get("/health")
def health(request: Request) -> JSONResponse:
    """Responde 200 se a API e o banco estão no ar; 503 se o banco não responde."""
    engine: Engine = request.app.state.engine
    try:
        with engine.connect() as conexao:
            conexao.execute(text("SELECT 1"))
    except SQLAlchemyError as erro:
        # Só o nome da classe: a mensagem do driver traz host e usuário do banco.
        logger.warning("health: banco indisponível (%s)", type(erro).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "indisponivel"},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})
