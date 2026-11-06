import pytest

import comun
from datos.cache import CacheDisco, TokenBucket, con_backoff


class Reloj:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.t += s


def test_ttl_por_fuente(tmp_path):
    r = Reloj()
    c = CacheDisco(tmp_path, ttl_horas={"precios": 12, "damodaran": 720}, reloj=r)
    c.guardar("precios", "k", {"a": 1})
    c.guardar("damodaran", "k", {"b": 2})
    assert c.obtener("precios", "k") == {"a": 1}
    r.t += 13 * 3600
    assert c.obtener("precios", "k") is None
    assert c.obtener("precios", "k", permitir_caducado=True) == {"a": 1}
    assert c.obtener("damodaran", "k") == {"b": 2}
    assert not c.vigente("precios", "k") and c.vigente("damodaran", "k")


def test_fuente_sin_ttl_falla(tmp_path):
    c = CacheDisco(tmp_path, ttl_horas={"precios": 1})
    with pytest.raises(KeyError):
        c.guardar("desconocida", "k", 1)


def test_bytes(tmp_path):
    c = CacheDisco(tmp_path, ttl_horas={"damodaran": 1})
    c.guardar_bytes("damodaran", "url", b"\x00\x01xls")
    assert c.obtener_bytes("damodaran", "url") == b"\x00\x01xls"
    assert c.obtener_bytes("damodaran", "otra") is None


def test_obtener_o_calcular_usa_caducada_si_la_fuente_falla(tmp_path):
    r = Reloj()
    c = CacheDisco(tmp_path, ttl_horas={"precios": 1}, reloj=r)
    v, info = c.obtener_o_calcular("precios", "k", lambda: 5)
    assert (v, info["origen"]) == (5, "red")
    v, info = c.obtener_o_calcular("precios", "k", lambda: 6)
    assert (v, info["origen"]) == (5, "cache")
    r.t += 7200

    def falla():
        raise comun.ErrorDatos("caída", "source_down")

    v, info = c.obtener_o_calcular("precios", "k", falla)
    assert (v, info["origen"]) == (5, "cache_caducada")
    with pytest.raises(comun.ErrorDatos):
        c.obtener_o_calcular("precios", "otra", falla)


def test_limpiar_solo_caducados(tmp_path):
    r = Reloj()
    c = CacheDisco(tmp_path, ttl_horas={"precios": 1, "macro": 100}, reloj=r)
    c.guardar("precios", "a", 1)
    c.guardar("macro", "b", 2)
    r.t += 2 * 3600
    assert c.limpiar(solo_caducados=True) == 1
    assert c.obtener("macro", "b") == 2
    assert c.info()["precios"]["entradas"] == 0


def test_token_bucket_limita_a_8_por_segundo():
    r = Reloj(0.0)
    b = TokenBucket(8, reloj=r, dormir=r.dormir)
    for _ in range(8):
        assert b.adquirir() == 0.0  # ráfaga inicial
    for _ in range(16):
        b.adquirir()
    # 16 peticiones adicionales a 8/s requieren ~2 s
    assert r.t == pytest.approx(2.0, abs=1e-9)


def test_token_bucket_tasa_invalida():
    with pytest.raises(ValueError):
        TokenBucket(0)


def test_backoff_exponencial():
    esperas, intentos = [], []

    def f():
        intentos.append(1)
        if len(intentos) < 4:
            raise comun.ErrorDatos("x", "rate_limited")
        return "ok"

    assert con_backoff(f, reintentos=5, espera_base=2, excepciones=(comun.ErrorDatos,), dormir=esperas.append) == "ok"
    assert esperas == [2, 4, 8]


def test_backoff_relanza_tras_agotar():
    esperas = []

    def f():
        raise comun.ErrorDatos("x", "source_down")

    with pytest.raises(comun.ErrorDatos):
        con_backoff(f, reintentos=2, espera_base=1, excepciones=(comun.ErrorDatos,), dormir=esperas.append)
    assert esperas == [1, 2]


def test_backoff_no_captura_otras_excepciones():
    with pytest.raises(ZeroDivisionError):
        con_backoff(lambda: 1 / 0, reintentos=3, excepciones=(comun.ErrorDatos,), dormir=lambda s: None)
