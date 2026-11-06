"""Generador de datapacks sintéticos para los tests de router, tasas base y forense."""
from __future__ import annotations

import comun


def serie(valores, anio_fin=2025, moneda="USD", unidad="unidades"):
    """Serie anual cronológica terminada en `anio_fin`; los valores None se omiten."""
    n = len(valores)
    puntos = []
    for i, v in enumerate(valores):
        if v is None:
            continue
        f = f"{anio_fin - (n - 1 - i)}-12-31"
        puntos.append(comun.cifra(v, unidad, moneda, "https://x", f, "2026-11-06T00:00:00Z", ejercicio=int(f[:4])))
    return {"concepto": "X", "serie": puntos}


def datapack(sic=7372, anios=10, moneda="USD", empresa_extra=None, segmentos=None, banca=None, deuda=None, **campos):
    """`campos`: nombre -> lista de valores (p. ej. ingresos=[100, 110, ...]). Los campos omitidos quedan sin serie."""
    fund = {c: serie(v, moneda=moneda, unidad="acciones" if c == "acciones_diluidas" else "unidades")
            for c, v in campos.items()}
    ing = fund.get("ingresos")
    dp = {
        "version_esquema": 1, "ticker": "XYZ", "fecha_analisis": "2026-11-06",
        "empresa": {"ticker": "XYZ", "nombre": "XYZ Inc", "sic": sic, "taxonomia": "us-gaap",
                    "anios_estados": len(ing["serie"]) if ing else anios, "moneda_informe": moneda,
                    **(empresa_extra or {})},
        "fundamentales": fund, "precios": comun.desconocido("source_down"), "campos_desconocidos": [], "fuentes": [],
    }
    if segmentos is not None:
        dp["segmentos"] = segmentos
    if banca is not None:
        dp["banca"] = banca
    if deuda is not None:
        dp["deuda"] = deuda
    return dp


def segmento(nombre, ingresos, tipo="negocio"):
    return {"nombre": nombre, "tipo": tipo,
            "ingresos": comun.cifra(ingresos, "unidades", "USD", "https://x", "2025-12-31", "2026-11-06T00:00:00Z")}


def cifra_banca(valores, anio_fin=2025):
    return serie(valores, anio_fin, moneda=None, unidad="ratio")


def crecer(base, tasa, n):
    return [base * (1 + tasa) ** i for i in range(n)]
