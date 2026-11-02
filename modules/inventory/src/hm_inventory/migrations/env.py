from hm_inventory.infra.models import Base
from hm_platform.migrations import run_env

run_env(Base.metadata)
