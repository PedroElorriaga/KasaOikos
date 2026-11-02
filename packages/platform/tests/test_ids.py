import time

import pytest

from hm_platform.ids import uuid7, uuid7_from, uuid7_timestamp_ms


def test_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"  # bits 10xx, mesmos da RFC 9562


def test_embeds_current_timestamp() -> None:
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000
    assert before <= uuid7_timestamp_ms(value) <= after


def test_ids_from_different_milliseconds_sort_by_time() -> None:
    ids = []
    for _ in range(5):
        ids.append(uuid7())
        time.sleep(0.002)
    assert ids == sorted(ids)
    assert ids == sorted(ids, key=str)  # a ordem vale também na forma textual


def test_ids_are_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000


def test_uuid7_from_is_deterministic_and_keeps_the_layout() -> None:
    value = uuid7_from(1_767_225_600_000, bytes(range(10)))
    assert value == uuid7_from(1_767_225_600_000, bytes(range(10)))
    assert (value.version, uuid7_timestamp_ms(value)) == (7, 1_767_225_600_000)
    assert value.variant == "specified in RFC 4122"
    with pytest.raises(ValueError, match="10 bytes"):
        uuid7_from(0, b"curto")
