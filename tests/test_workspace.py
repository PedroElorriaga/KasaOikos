"""Garante que todos os pacotes do workspace são importáveis."""

import importlib

import pytest

PACKAGES = [
    "hm_api",
    "hm_platform",
    "hm_identity",
    "hm_finance",
    "hm_tasks",
    "hm_inventory",
    "hm_notifications",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_is_importable(name: str) -> None:
    assert importlib.import_module(name)
