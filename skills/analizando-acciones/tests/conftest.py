"""Configuración común de pytest: rutas, entorno aislado y fixtures."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DIR_TESTS = Path(__file__).resolve().parent
DIR_SCRIPTS = DIR_TESTS.parent / "scripts"
DIR_FIXTURES = DIR_TESTS / "fixtures"
if str(DIR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DIR_SCRIPTS))


@pytest.fixture(autouse=True)
def entorno_aislado(tmp_path, monkeypatch):
    """Ningún test toca la caché real ni depende de las claves del usuario."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin_data"))
    monkeypatch.setenv("SEC_USER_AGENT", "Prueba Tests prueba@example.com")
    monkeypatch.setenv("FRED_API_KEY", "clave_de_prueba")
    import comun

    monkeypatch.setattr(comun, "RUTA_ENV", tmp_path / "no_existe.env")
    yield


def cargar_fixture(nombre: str):
    return json.loads((DIR_FIXTURES / nombre).read_text(encoding="utf-8"))


@pytest.fixture
def fixture():
    return cargar_fixture


@pytest.fixture
def cache_tmp(tmp_path):
    from datos.cache import CacheDisco

    return CacheDisco(tmp_path / "cache", ttl_horas={"companyfacts": 24, "submissions": 24, "tickers": 24,
                                                       "precios": 12, "damodaran": 720, "macro": 168})
