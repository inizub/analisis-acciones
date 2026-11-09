"""Pruebas de claude-ai/lentes.py (funciones puras, sin datos de red)."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

RUTA = Path(__file__).resolve().parents[3] / "claude-ai" / "lentes.py"
spec = importlib.util.spec_from_file_location("lentes", RUTA)
lentes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lentes)

DCF = dict(ingresos0=100.0, g=0.10, margen0=0.20, margen_obj=0.25, vc=2.0, t=0.21, wacc=0.09,
           g_term=0.03, roic_term=0.12, deuda=0.0, caja=0.0, acciones=10.0)


def test_phi_simetria():
    assert abs(lentes.phi(0) - 0.5) < 1e-12
    assert abs(lentes.phi(1.3) + lentes.phi(-1.3) - 1) < 1e-12


def test_dcf_crece_con_el_crecimiento():
    bajo = lentes.dcf(**{**DCF, "g": 0.02})
    alto = lentes.dcf(**{**DCF, "g": 0.20})
    assert alto > bajo > 0


def test_dcf_sin_valor_si_wacc_no_supera_g_terminal():
    assert lentes.dcf(**{**DCF, "wacc": 0.03}) is None


def test_dcf_caja_y_deuda_ajustan_por_accion():
    base = lentes.dcf(**DCF)
    con_caja = lentes.dcf(**{**DCF, "caja": 50.0})
    assert math.isclose(con_caja - base, 5.0, rel_tol=1e-9)


def test_biseccion_encuentra_la_raiz():
    raiz, estado = lentes.biseccion(lambda x: x - 0.37, -0.2, 0.6)
    assert estado == "ok" and abs(raiz - 0.37) < 1e-6


def test_biseccion_distingue_caro_de_barato():
    # f(lo) > 0: ya con el valor más bajo del rango se supera el precio -> barato
    assert lentes.biseccion(lambda x: 1.0 + x, 0.0, 1.0) == (None, "barato")
    # f(hi) < 0: ni con el valor más alto se alcanza el precio -> caro
    assert lentes.biseccion(lambda x: -1.0 - x, 0.0, 1.0) == (None, "caro")
