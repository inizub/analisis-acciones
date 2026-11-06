"""Resuelve las preguntas vencidas del diario con precios (yfinance) y filings (EDGAR) y aplica las cláusulas de anulación.

Uso CLI (apto para cron; no usa ningún LLM):
    python resolver.py resolver --diario predicciones.jsonl [--hoy 2027-11-10]
    python resolver.py pendientes --diario predicciones.jsonl
    python resolver.py manual --diario predicciones.jsonl --id ID --qid E4 --resultado 1 [--nota TEXTO]
    python resolver.py anular --diario predicciones.jsonl --id ID --qid E1 --causa opa|delisting|escision|sin_datos

Reglas:
  E0, E1, E2  RT(acción) − RT(VWCE.DE) > 0 en EUR, con cierres ajustados, desde el cierre de la fecha de referencia hasta
              el cierre de resolve_date.
  E3          el mínimo del retorno total en EUR de la acción desde la referencia hasta resolve_date ≤ −30 %.
  E4          métrica fundamental del ejercicio objetivo (crecimiento de ingresos o ROE) ≥ valor base, con el informe
              anual de EDGAR. El hito clínico solo se resuelve a mano.
Anulación: si pasa el plazo de espera y la serie de precios no llega a la fecha de resolución, la pregunta se anula con
causa `sin_datos` (puede ser una OPA, una exclusión de cotización o un fallo de datos: revisar y, si procede, usar
`anular` con la causa correcta). Las anulaciones manuales (`opa`, `delisting`, `escision`) las pone el usuario.
Cada resolución es una línea nueva del diario con `tipo: resolucion`. Es idempotente: no vuelve a resolver lo resuelto.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
import diario as dr  # noqa: E402
from datos.precios import precio_en  # noqa: E402


class Proveedor(Protocol):
    def series_eur(self, ticker_precio: str, benchmark: str) -> tuple[pd.Series, pd.Series]: ...

    def fundamentales(self, ticker: str) -> dict: ...


class ProveedorReal:
    """Precios de yfinance y fundamentales de EDGAR."""

    def __init__(self) -> None:
        self._precios = None

    def series_eur(self, ticker_precio: str, benchmark: str) -> tuple[pd.Series, pd.Series]:
        from datos.precios import ClientePrecios

        self._precios = self._precios or ClientePrecios()
        return self._precios.series_eur(ticker_precio, benchmark)

    def fundamentales(self, ticker: str) -> dict:
        from datos import edgar

        return edgar.obtener(ticker)["fundamentales"]


# ---------------------------------------------------------------- piezas puras

def cobertura(series: list[pd.Series], ref: date, fin: date, hoy: date, espera: int) -> tuple[str, str]:
    """('ok'|'pendiente'|'sin_datos', motivo). Con la serie actualizada, hay un cierre en o después de `fin`."""
    for s in series:
        if s.empty or s.index[0] > pd.Timestamp(ref) + pd.Timedelta(days=7):
            inicio = "vacía" if s.empty else f"empieza el {s.index[0].date()}"
            return "sin_datos", f"la serie de precios {inicio}, después de la fecha de referencia {ref}"
    for s in series:
        if s.index[-1] < pd.Timestamp(fin):
            if (hoy - fin).days < espera:
                return "pendiente", f"la serie llega al {s.index[-1].date()}, antes de {fin}"
            return "sin_datos", (f"la serie termina el {s.index[-1].date()}, antes de la fecha de resolución {fin} "
                                 "(posible OPA, exclusión de cotización o fallo de datos: revisar)")
    return "ok", ""


def retorno_total(serie: pd.Series, ref: date, fin: date) -> float:
    p0, p1 = precio_en(serie, pd.Timestamp(ref)), precio_en(serie, pd.Timestamp(fin))
    if not p0 or p1 is None:
        raise ValueError("serie sin precio en la fecha de referencia")
    return p1 / p0 - 1


def minimo_relativo(serie: pd.Series, ref: date, fin: date) -> float:
    """Mínimo del retorno total acumulado desde `ref` dentro de [ref, fin]."""
    p0 = precio_en(serie, pd.Timestamp(ref))
    ventana = serie.loc[pd.Timestamp(ref):pd.Timestamp(fin)]
    if not p0 or ventana.empty:
        raise ValueError("ventana de precios vacía")
    return float((ventana / p0).min() - 1)


def valor_e4(fund: dict, metrica: str, ejercicio: int) -> tuple[float | None, str]:
    """(valor, motivo_si_no_disponible) de la métrica E4 del ejercicio dado, desde las series de edgar.obtener."""
    def por_ejercicio(campo: str) -> dict[int, float]:
        s = fund.get(campo)
        if not s or comun.es_desconocido(s):
            return {}
        return {p["ejercicio"]: p["valor"] for p in s["serie"] if p.get("ejercicio") is not None}

    if metrica == "crecimiento_ingresos":
        ing = por_ejercicio("ingresos")
        if ejercicio not in ing or ejercicio - 1 not in ing or ing[ejercicio - 1] <= 0:
            return None, f"EDGAR aún no tiene los ingresos del ejercicio {ejercicio}"
        return ing[ejercicio] / ing[ejercicio - 1] - 1, ""
    if metrica == "roe":
        bn, pat = por_ejercicio("beneficio_neto"), por_ejercicio("patrimonio")
        if ejercicio not in bn or ejercicio not in pat or pat[ejercicio] <= 0:
            return None, f"EDGAR aún no tiene beneficio neto y patrimonio del ejercicio {ejercicio}"
        return bn[ejercicio] / pat[ejercicio], ""
    return None, f"métrica {metrica} sin resolución automática"


# ---------------------------------------------------------------- resolución de una pregunta

def _anulada(causa: str, motivo: str) -> dict:
    return {"estado": "anulada", "resultado": None, "causa": causa, "detalle": {"motivo": motivo},
            "resuelta_por": "automatico"}


def _resuelta(resultado: int, detalle: dict) -> dict:
    return {"estado": "resuelta", "resultado": resultado, "causa": None, "detalle": detalle, "resuelta_por": "automatico"}


def resolver_precios(q: dict, hoy: date, prov: Proveedor, espera: int) -> dict | None:
    d = q["detalle"]
    ref, fin = date.fromisoformat(d["fecha_ref"]), date.fromisoformat(q["resolve_date"])
    if hoy < fin:
        return None
    bench = d.get("benchmark") or comun.cargar_config()["eventos"]["benchmark"]
    try:
        acc, bn = prov.series_eur(d["ticker_precio"], bench)
    except comun.ErrorDatos as e:
        if e.causa == "not_covered" and (hoy - fin).days >= espera:
            return _anulada("sin_datos", f"yfinance no tiene {d['ticker_precio']}: {e}")
        return None
    series = [acc] if d["tipo"] == "caida" else [acc, bn]
    estado, motivo = cobertura(series, ref, fin, hoy, espera)
    if estado == "pendiente":
        return None
    if estado == "sin_datos":
        return _anulada("sin_datos", motivo)
    base = {"fecha_ref": str(ref), "fecha_fin": str(fin), "ticker_precio": d["ticker_precio"]}
    if d["tipo"] == "exceso_rt":
        ra, rb = retorno_total(acc, ref, fin), retorno_total(bn, ref, fin)
        return _resuelta(int(ra - rb > 0), {**base, "benchmark": bench, "rt_accion": ra, "rt_benchmark": rb,
                                            "diferencia": ra - rb})
    minimo = minimo_relativo(acc, ref, fin)
    return _resuelta(int(minimo <= d["umbral"]), {**base, "minimo_retorno": minimo, "umbral": d["umbral"]})


def resolver_e4(registro: dict, q: dict, hoy: date, prov: Proveedor, dias_espera: int) -> dict | None:
    d = q["detalle"]
    if d.get("manual"):
        return None
    esperado = date.fromisoformat(d["fin_ejercicio_esperado"])
    if hoy <= esperado + timedelta(days=dias_espera):
        return None
    try:
        fund = prov.fundamentales(registro["ticker"])
    except comun.ErrorDatos:
        return None
    valor, motivo = valor_e4(fund, d["metrica"], d["ejercicio_objetivo"])
    if valor is None:
        if hoy > esperado + timedelta(days=400):
            return _anulada("sin_datos", motivo + " (más de un año después del cierre esperado)")
        return None
    return _resuelta(int(valor >= d["valor_base"]), {"metrica": d["metrica"], "ejercicio": d["ejercicio_objetivo"],
                                                      "valor": valor, "valor_base": d["valor_base"]})


def resolver_pregunta(registro: dict, q: dict, hoy: date, prov: Proveedor, cfg: dict) -> dict | None:
    """Resolución de una pregunta, o None si todavía no se puede resolver."""
    if q["qid"] in ("E0", "E1", "E2", "E3"):
        return resolver_precios(q, hoy, prov, cfg["diario"]["dias_espera_datos"])
    return resolver_e4(registro, q, hoy, prov, cfg["diario"]["dias_espera_e4"])


# ---------------------------------------------------------------- diario

def _linea(diario: Path, id_: str, qid: str, res: dict) -> dict:
    return {"tipo": "resolucion", "id": id_, "qid": qid,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "hash_prev": dr.ultimo_hash(diario), **res}


def pendientes(registros: list[dict]) -> list[tuple[dict, dict]]:
    hechas = dr.resoluciones(registros)
    return [(r, q) for r in registros if dr.tipo(r) == "prediccion" for q in r["preguntas"]
            if (r["id"], q["qid"]) not in hechas]


def resolver_pendientes(diario: Path, hoy: date, prov: Proveedor, cfg: dict | None = None) -> dict:
    cfg = cfg or comun.cargar_config()
    resueltas, anuladas, omitidas = [], [], []
    for r, q in pendientes(dr.leer_registros(diario)):
        try:
            res = resolver_pregunta(r, q, hoy, prov, cfg)
        except (ValueError, KeyError, comun.ErrorDatos) as e:
            omitidas.append({"id": r["id"], "qid": q["qid"], "error": f"{type(e).__name__}: {e}"})
            continue
        if res is None:
            continue
        dr.anexar(diario, _linea(diario, r["id"], q["qid"], res))
        (resueltas if res["estado"] == "resuelta" else anuladas).append(
            {"id": r["id"], "qid": q["qid"], "resultado": res["resultado"], "causa": res["causa"]})
    return {"resueltas": resueltas, "anuladas": anuladas, "omitidas": omitidas,
            "pendientes": len(pendientes(dr.leer_registros(diario)))}


def _pregunta(diario: Path, id_: str, qid: str) -> tuple[dict, dict]:
    registros = dr.leer_registros(diario)
    for r, q in pendientes(registros):
        if r["id"] == id_ and q["qid"] == qid:
            return r, q
    raise ValueError(f"No hay una pregunta pendiente {id_}/{qid} en el diario")


def resolver_manual(diario: Path, id_: str, qid: str, resultado: int, nota: str | None = None) -> dict:
    if resultado not in (0, 1):
        raise ValueError("resultado debe ser 0 o 1")
    _pregunta(diario, id_, qid)
    return dr.anexar(diario, _linea(diario, id_, qid, {
        "estado": "resuelta", "resultado": resultado, "causa": None, "detalle": {"nota": nota},
        "resuelta_por": "manual"}))


def anular_manual(diario: Path, id_: str, qid: str, causa: str, nota: str | None = None,
                  cfg: dict | None = None) -> dict:
    validas = (cfg or comun.cargar_config())["diario"]["anular_si"]
    if causa not in validas:
        raise ValueError(f"causa de anulación no válida: {causa} (válidas: {validas})")
    _pregunta(diario, id_, qid)
    return dr.anexar(diario, _linea(diario, id_, qid, {
        "estado": "anulada", "resultado": None, "causa": causa, "detalle": {"nota": nota}, "resuelta_por": "manual"}))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Resuelve las predicciones vencidas del diario.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for nombre in ("resolver", "pendientes", "manual", "anular"):
        s = sub.add_parser(nombre)
        s.add_argument("--diario", required=True)
        if nombre == "resolver":
            s.add_argument("--hoy", help="Fecha de resolución AAAA-MM-DD (por defecto, hoy)")
        if nombre in ("manual", "anular"):
            s.add_argument("--id", required=True)
            s.add_argument("--qid", required=True, choices=["E0", "E1", "E2", "E3", "E4"])
            s.add_argument("--nota")
        if nombre == "manual":
            s.add_argument("--resultado", required=True, type=int, choices=[0, 1])
        if nombre == "anular":
            s.add_argument("--causa", required=True)
    a = p.parse_args(argv)
    diario = Path(a.diario)
    try:
        if a.cmd == "resolver":
            res = resolver_pendientes(diario, date.fromisoformat(a.hoy) if a.hoy else date.today(), ProveedorReal())
        elif a.cmd == "pendientes":
            res = [{"id": r["id"], "ticker": r["ticker"], "qid": q["qid"], "resolve_date": q["resolve_date"]}
                   for r, q in pendientes(dr.leer_registros(diario))]
        elif a.cmd == "manual":
            res = resolver_manual(diario, a.id, a.qid, a.resultado, a.nota)
        else:
            res = anular_manual(diario, a.id, a.qid, a.causa, a.nota)
    except (ValueError, FileNotFoundError, KeyError) as e:
        comun.salir_con_error(f"{type(e).__name__}: {e}")
    print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
