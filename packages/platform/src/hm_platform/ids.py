"""Identificadores UUIDv7 (RFC 9562), gerados na aplicação (design D3).

Os 48 bits iniciais são o timestamp Unix em milissegundos, então ids gerados em
sequência ficam próximos no índice B-tree (inserções no fim, não espalhadas).
Python 3.14 traz ``uuid.uuid7()``; ao migrar de versão, esta função pode delegar a ele.
"""

import os
import time
import uuid

_RAND_B_BITS = 62
_RAND_B_MASK = (1 << _RAND_B_BITS) - 1


def uuid7() -> uuid.UUID:
    return uuid7_from(time.time_ns() // 1_000_000, os.urandom(10))


def uuid7_from(unix_ms: int, random_bytes: bytes) -> uuid.UUID:
    """Monta um UUIDv7 com timestamp e bits aleatórios dados (o seed gera ids determinísticos)."""
    if len(random_bytes) != 10:
        raise ValueError("random_bytes deve ter 10 bytes (80 bits)")
    rand = int.from_bytes(random_bytes)  # 80 bits: 12 de rand_a + 62 de rand_b (+6 descartados)
    rand_a = rand >> 68
    rand_b = rand & _RAND_B_MASK
    value = (
        (unix_ms & 0xFFFF_FFFF_FFFF) << 80
        | 0x7 << 76  # versão
        | rand_a << 64
        | 0b10 << 62  # variante RFC 9562
        | rand_b
    )
    return uuid.UUID(int=value)


def uuid7_timestamp_ms(value: uuid.UUID) -> int:
    """Timestamp (ms desde a época Unix) embutido em um UUIDv7."""
    return value.int >> 80
