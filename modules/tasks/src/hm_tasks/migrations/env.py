from hm_platform.migrations import run_env
from hm_tasks.infra.models import Base

run_env(Base.metadata)
