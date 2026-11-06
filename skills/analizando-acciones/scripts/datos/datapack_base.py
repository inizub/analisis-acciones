"""Genera datapack_base.json combinando edgar.py, precios.py y damodaran.py.

Uso CLI:
    python datapack_base.py TICKER --dir RUN_DIR [--ticker-precio SAP.DE] [--pais Brazil]

Escribe en RUN_DIR:
  - datapack_base.json   (validado contra el esquema datapack)
  - precios_serie.json   (serie diaria en EUR de la acción y de VWCE; no la leen los agentes)
Imprime un resumen JSON con la ruta, los campos desconocidos y las discrepancias.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun  # noqa: E402
from datos import damodaran, edgar, precios  # noqa: E402

CAMPOS_CRUZADOS = ("ingresos", "beneficio_neto", "acciones_diluidas")
TOLERANCIA_FECHA_DIAS = 10


def verificacion_cruzada(fund: dict, secundarios: Any, tolerancia: float) -> dict:
    """Compara el último ejercicio común entre EDGAR y yfinance. Si difieren > tolerancia, prevalece EDGAR."""
    res: dict[str, dict] = {}
    anual = secundarios.get("anual", {}) if isinstance(secundarios, dict) and not comun.es_desconocido(secundarios) else {}
    for campo in CAMPOS_CRUZADOS:
        f = fund.get(campo)
        if not f or comun.es_desconocido(f) or campo not in anual:
            res[campo] = {"estado": "sin_comparar", "motivo": "falta una de las dos fuentes"}
            continue
        sec = {date.fromisoformat(k): v for k, v in anual[campo].items()}
        comparado = None
        for p in reversed(f["serie"]):
            fin = date.fromisoformat(p["fecha_dato"])
            cerca = [d for d in sec if abs((d - fin).days) <= TOLERANCIA_FECHA_DIAS]
            if cerca:
                comparado = (p, sec[cerca[0]])
                break
        if comparado is None:
            res[campo] = {"estado": "sin_comparar", "motivo": "sin ejercicio común"}
            continue
        p, v2 = comparado
        v1 = p["valor"]
        dif = abs(v1 - v2) / abs(v1) if v1 else (0.0 if v2 == 0 else float("inf"))
        res[campo] = {
            "fecha_dato": p["fecha_dato"], "edgar": v1, "secundaria": v2, "diferencia_rel": dif,
            "estado": "ok" if dif <= tolerancia else "discrepancia_resuelta_edgar",
        }
    return res


def construir(ticker: str, ticker_precio: str | None = None, pais: str | None = None,
              fecha: str | None = None, clientes: dict | None = None) -> tuple[dict, dict | None]:
    """Devuelve (datapack_base, serie_eur). `clientes` permite inyectar edgar/precios/damodaran en tests."""
    clientes = clientes or {}
    cfg = comun.cargar_config()
    t = ticker.strip().upper()
    ed = edgar.obtener(t, cliente=clientes.get("edgar"))
    desconocidos = list(ed["desconocidos"])
    fuentes = list(ed["fuentes"])
    empresa = ed["empresa"]

    tp = ticker_precio or (edgar.normalizar_ticker(t) if not comun.es_desconocido(empresa) else t)
    serie = None
    try:
        pr = (clientes.get("precios") or precios.ClientePrecios()).obtener(tp, cfg["eventos"]["benchmark"])
        seccion_precios = pr["precios"]
        serie = pr.get("serie_eur")
        secundarios = pr["fundamentales_secundarios"]
        desconocidos += pr["desconocidos"]
        fuentes += pr["fuentes"]
    except comun.ErrorDatos as e:
        seccion_precios = comun.desconocido(e.causa, str(e))
        secundarios = comun.desconocido(e.causa, str(e))
        desconocidos.append({"campo": "precios", "causa": e.causa})

    sic = empresa.get("sic") if not comun.es_desconocido(empresa) else None
    pais_ef = pais or (empresa.get("pais_negocio") if not comun.es_desconocido(empresa) else None)
    try:
        dam = damodaran.construir_seccion(sic, pais_ef, clientes.get("damodaran"))
        desconocidos += dam.pop("desconocidos")
        fuentes.append({"url": dam["erp_madura"]["fuente_url"], "retrieved_at": dam["erp_madura"]["fecha_obtencion"]})
    except comun.ErrorDatos as e:
        dam = comun.desconocido(e.causa, str(e))
        desconocidos.append({"campo": "damodaran", "causa": e.causa})

    datapack = {
        "version_esquema": 1,
        "ticker": t,
        "fecha_analisis": fecha or comun.hoy_iso(),
        "creado": comun.ahora_iso(),
        "empresa": empresa,
        "fundamentales": ed["fundamentales"],
        "precios": seccion_precios,
        "damodaran": dam,
        "verificacion_cruzada": verificacion_cruzada(ed["fundamentales"], secundarios, cfg["datos"]["discrepancia_max"]),
        "campos_desconocidos": _unicos(desconocidos),
        "fuentes": fuentes,
    }
    return datapack, serie


def _unicos(lista: list[dict]) -> list[dict]:
    vistos, res = set(), []
    for d in lista:
        k = (d["campo"], d["causa"])
        if k not in vistos:
            vistos.add(k)
            res.append(d)
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Construye datapack_base.json para un ticker.")
    p.add_argument("ticker")
    p.add_argument("--dir", required=True, help="Directorio de la ejecución (runs/<TICKER>/<fecha>/)")
    p.add_argument("--ticker-precio", help="Ticker de yfinance si difiere (p. ej. SAP.DE)")
    p.add_argument("--pais", help="País para la prima de riesgo (por defecto, el de la sede en EDGAR)")
    a = p.parse_args(argv)
    from validar import validar_objeto

    try:
        dp, serie = construir(a.ticker, a.ticker_precio, a.pais)
    except comun.ErrorDatos as e:
        comun.salir_con_error(f"{e} [causa={e.causa}]")
    errores = validar_objeto(dp, "datapack")
    if errores:
        comun.salir_con_error("datapack_base no valida: " + "; ".join(errores[:10]))
    d = Path(a.dir)
    ruta = comun.escribir_json(d / "datapack_base.json", dp)
    if serie:
        comun.escribir_json(d / "precios_serie.json", serie)
    discrepancias = {k: v for k, v in dp["verificacion_cruzada"].items() if v["estado"] != "ok"}
    print(comun.volcar_json({"datapack_base": str(ruta), "campos_desconocidos": dp["campos_desconocidos"],
                             "verificacion_cruzada_no_ok": discrepancias}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
