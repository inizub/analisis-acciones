import json

import numpy as np
import pytest

import comun


def test_cifra_y_desconocido():
    c = comun.cifra(1.5, "ratio", None, "https://x", "2025-12-31", "2026-01-01T00:00:00Z", concepto="X", nota=None)
    assert c == {"valor": 1.5, "unidad": "ratio", "moneda": None, "fuente_url": "https://x",
                 "fecha_dato": "2025-12-31", "fecha_obtencion": "2026-01-01T00:00:00Z", "concepto": "X"}
    with pytest.raises(ValueError):
        comun.cifra(None, "ratio", None, "u", "2025-01-01")
    d = comun.desconocido("rate_limited", "429")
    assert comun.es_desconocido(d) and d["causa"] == "rate_limited"
    with pytest.raises(ValueError):
        comun.desconocido("inventada")
    assert not comun.es_desconocido(c)


def test_error_datos_valida_causa():
    assert comun.ErrorDatos("x", "stale").causa == "stale"
    with pytest.raises(ValueError):
        comun.ErrorDatos("x", "otra")


def test_escribir_json_numpy_y_utf8(tmp_path):
    ruta = comun.escribir_json(tmp_path / "a" / "b.json", {"x": np.float64(1.5), "n": np.int64(3), "t": "año"})
    texto = ruta.read_text(encoding="utf-8")
    assert "año" in texto
    assert json.loads(texto) == {"x": 1.5, "n": 3, "t": "año"}
    assert not list(tmp_path.rglob("*.tmp"))


def test_user_agent_ascii(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Iñigo  Pérez inigo@example.com")
    assert comun.user_agent_sec() == "Inigo Perez inigo@example.com"
    monkeypatch.setenv("SEC_USER_AGENT", "Sin Email")
    with pytest.raises(comun.ErrorDatos):
        comun.user_agent_sec()


def test_variable_requerida_falta(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(comun.ErrorDatos, match="FRED_API_KEY"):
        comun.variable_requerida("FRED_API_KEY")


def test_dir_datos_plugin_usa_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "pd"))
    assert comun.dir_datos_plugin() == tmp_path / "pd"
    assert (tmp_path / "pd").is_dir()


def test_config_valores_iniciales():
    cfg = comun.cargar_config()
    assert cfg["red_team_externo"]["activo"] is False
    assert cfg["agregacion"] == {"tasa_base_exceso": 0.45, "k": 0.4, "clip_E3_E4": [0.05, 0.95]}
    assert cfg["escenarios"]["semilla"] == 42
    assert cfg["edgar"]["max_peticiones_seg"] <= 8
    assert set(cfg["cache_ttl_horas"]) >= {"companyfacts", "precios", "damodaran", "macro"}
    assert cfg["cache_ttl_horas"]["damodaran"] == 30 * 24 and cfg["cache_ttl_horas"]["macro"] == 7 * 24


def test_sha256(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"abc")
    assert comun.sha256_archivo(p) == "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert comun.sha256_texto("abc") == comun.sha256_archivo(p)


def test_leer_json_acepta_cp1252_y_lo_reescribe_en_utf8(tmp_path):
    f = tmp_path / "datos_agente.json"
    f.write_bytes('{"nota": "computación de Data Center"}'.encode("cp1252"))
    assert comun.leer_json(f) == {"nota": "computación de Data Center"}
    assert f.read_bytes().decode("utf-8") == '{"nota": "computación de Data Center"}'      # ya en UTF-8
    assert comun.leer_json(f) == {"nota": "computación de Data Center"}
