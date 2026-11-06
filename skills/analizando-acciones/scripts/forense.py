"""Forense cuantitativo: métricas de calidad contable y banderas graves con umbrales de config.yaml (A6.5).

Uso CLI:
    python forense.py --datapack datapack.json [--ruta RUTA | --router router.json] [--salida forense_metricas.json]

Cada métrica tiene estado `evaluada`, `sin_datos` (falta algún campo o está desactualizado) o `no_aplica`
(la métrica no tiene sentido para la ruta o para esa empresa, p. ej. beneficio neto negativo). Una métrica
`evaluada` que cruza su umbral produce una bandera de nivel `grave`. Las banderas `invalidante` las asigna el
agente forense; este módulo nunca las genera.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402

# Métricas que no aplican a bancos (el balance y el flujo de caja de un banco no siguen la lógica industrial).
NO_BANCOS = {"fco_beneficio_neto", "devengos", "cxc_vs_ingresos", "inventario_vs_ingresos", "cobertura_intereses"}


# ---------------------------------------------------------------- acceso a series

def serie(dp: dict, campo: str) -> list[dict]:
    v = (dp.get("fundamentales") or {}).get(campo)
    return [] if not v or comun.es_desconocido(v) else v["serie"]


def desactualizada(dp: dict, campo: str) -> bool:
    v = (dp.get("fundamentales") or {}).get(campo)
    return bool(v) and not comun.es_desconocido(v) and v.get("desactualizada") is True


def alinear(dp: dict, campos: list[str], n: int) -> list[dict]:
    """Últimos `n` ejercicios con dato en todos los campos: [{fecha, campo: valor, ...}] en orden cronológico."""
    por_campo = {c: {p["fecha_dato"]: p["valor"] for p in serie(dp, c)} for c in campos}
    comunes = set.intersection(*(set(d) for d in por_campo.values())) if por_campo else set()
    return [{"fecha": f, **{c: por_campo[c][f] for c in campos}} for f in sorted(comunes)][-n:]


def _ok(valor: float, umbral: float, grave: bool, detalle: str, campos: list[str], **extra: Any) -> dict:
    return {"estado": "evaluada", "valor": valor, "umbral": umbral, "grave": grave, "detalle": detalle,
            "campos": campos, **extra}


def _sin_datos(detalle: str, campos: list[str]) -> dict:
    return {"estado": "sin_datos", "detalle": detalle, "campos": campos}


def _no_aplica(detalle: str, campos: list[str] | None = None) -> dict:
    return {"estado": "no_aplica", "detalle": detalle, "campos": campos or []}


def _faltan(dp: dict, campos: list[str]) -> str | None:
    """Motivo si algún campo falta o está desactualizado; None si todos están."""
    for c in campos:
        if not serie(dp, c):
            return f"falta {c}"
        if desactualizada(dp, c):
            return f"{c} desactualizado (último dato {dp['fundamentales'][c].get('ultimo_periodo')})"
    return None


# ---------------------------------------------------------------- métricas de la tabla A6.5

def fco_beneficio_neto(dp: dict, cfg: dict) -> dict:
    campos, n = ["fco", "beneficio_neto"], cfg["fco_bn_anios"]
    if m := _faltan(dp, campos):
        return _sin_datos(m, campos)
    filas = alinear(dp, campos, n)
    if len(filas) < n:
        return _sin_datos(f"se necesitan {n} ejercicios comunes (hay {len(filas)})", campos)
    bn, fco = sum(f["beneficio_neto"] for f in filas), sum(f["fco"] for f in filas)
    if bn <= 0:
        return _no_aplica(f"beneficio neto acumulado de {n} años no positivo", campos)
    r = fco / bn
    return _ok(r, cfg["fco_bn_min"], r < cfg["fco_bn_min"], f"FCO/BN acumulado {n} años = {r:.2f}", campos)


def devengos(dp: dict, cfg: dict) -> dict:
    campos = ["beneficio_neto", "fco", "activos_totales"]
    if m := _faltan(dp, campos):
        return _sin_datos(m, campos)
    filas = alinear(dp, campos, 2)
    if not filas:
        return _sin_datos("sin ejercicio común", campos)
    ult = filas[-1]
    activos = (filas[0]["activos_totales"] + ult["activos_totales"]) / 2 if len(filas) == 2 else ult["activos_totales"]
    if activos <= 0:
        return _no_aplica("activos no positivos", campos)
    v = (ult["beneficio_neto"] - ult["fco"]) / activos
    return _ok(v, cfg["devengos_max"], v > cfg["devengos_max"], f"(BN − FCO)/activos medios = {v:.1%}", campos)


def _gap(dp: dict, campo: str, umbral_pp: float, anios: int, nombre: str) -> dict:
    campos = [campo, "ingresos"]
    if m := _faltan(dp, campos):
        return _sin_datos(m, campos)
    filas = alinear(dp, campos, anios + 1)
    if len(filas) < anios + 1:
        return _sin_datos(f"se necesitan {anios + 1} ejercicios comunes (hay {len(filas)})", campos)
    gaps = []
    for a, b in zip(filas, filas[1:]):
        if a[campo] <= 0 or a["ingresos"] <= 0:
            return _no_aplica(f"{campo} o ingresos no positivos", campos)
        gaps.append(100 * ((b[campo] / a[campo] - 1) - (b["ingresos"] / a["ingresos"] - 1)))
    grave = all(g > umbral_pp for g in gaps)
    return _ok(min(gaps), umbral_pp, grave,
               f"{nombre}: diferencial de crecimiento (pp) en los últimos {anios} años = "
               + ", ".join(f"{g:.1f}" for g in gaps), campos, valores=gaps)


def cxc_vs_ingresos(dp: dict, cfg: dict) -> dict:
    return _gap(dp, "cxc", cfg["cxc_gap_pp"], cfg["gap_anios"], "cuentas a cobrar − ingresos")


def inventario_vs_ingresos(dp: dict, cfg: dict) -> dict:
    if not serie(dp, "inventario"):
        return _no_aplica("la empresa no reporta inventario", ["inventario"])
    return _gap(dp, "inventario", cfg["inv_gap_pp"], cfg["gap_anios"], "inventario − ingresos")


def sbc_ingresos(dp: dict, cfg: dict) -> dict:
    campos = ["sbc", "ingresos"]
    if m := _faltan(dp, campos):
        return _sin_datos(m, campos)
    f = alinear(dp, campos, 1)
    if not f or f[0]["ingresos"] <= 0:
        return _sin_datos("sin ejercicio común", campos)
    v = f[0]["sbc"] / f[0]["ingresos"]
    return _ok(v, cfg["sbc_max"], v > cfg["sbc_max"], f"SBC/ingresos = {v:.1%}", campos)


def dilucion(dp: dict, cfg: dict) -> dict:
    campos, n = ["acciones_diluidas"], cfg["dilucion_anios"]
    if m := _faltan(dp, campos):
        return _sin_datos(m, campos)
    s = [p["valor"] for p in serie(dp, "acciones_diluidas")]
    if len(s) < n + 1 or s[-n - 1] <= 0:
        return _sin_datos(f"se necesitan {n + 1} ejercicios", campos)
    v = (s[-1] / s[-n - 1]) ** (1 / n) - 1
    return _ok(v, cfg["dilucion_max"], v > cfg["dilucion_max"], f"dilución anual ({n} años) = {v:.1%}", campos)


def goodwill_activos(dp: dict, cfg: dict) -> dict:
    campos = ["goodwill", "activos_totales"]
    if not serie(dp, "goodwill"):
        return _no_aplica("la empresa no reporta goodwill", campos)
    if m := _faltan(dp, campos):
        return _sin_datos(m, campos)
    f = alinear(dp, campos, 2)
    if len(f) < 2:
        return _sin_datos("se necesitan 2 ejercicios comunes", campos)
    r0, r1 = (x["goodwill"] / x["activos_totales"] for x in f)
    creciente = r1 > r0
    return _ok(r1, cfg["goodwill_max"], r1 > cfg["goodwill_max"] and creciente,
               f"goodwill/activos = {r1:.1%} ({'creciente' if creciente else 'no creciente'}, antes {r0:.1%})", campos)


def cobertura_intereses(dp: dict, cfg: dict) -> dict:
    campos = ["beneficio_operativo", "gasto_intereses"]
    if m := _faltan(dp, campos):
        return _sin_datos(m, campos)
    f = alinear(dp, campos, 1)
    if not f:
        return _sin_datos("sin ejercicio común", campos)
    interes = abs(f[0]["gasto_intereses"])
    if interes == 0:
        return _no_aplica("sin gasto por intereses", campos)
    v = f[0]["beneficio_operativo"] / interes
    return _ok(v, cfg["cobertura_min"], v < cfg["cobertura_min"], f"EBIT/intereses = {v:.2f}", campos)


# ---------------------------------------------------------------- bancos

def _valores(x: Any) -> list[tuple[str, float]]:
    """Serie [(fecha, valor)] de una serie, una cifra o desconocido."""
    if not x or comun.es_desconocido(x):
        return []
    if "serie" in x:
        return [(p["fecha_dato"], p["valor"]) for p in x["serie"]]
    return [(x["fecha_dato"], x["valor"])]


def _tendencia_adversa(dp: dict, clave: str, nombre: str, cfg: dict) -> dict:
    n = cfg["banca_tendencia_anios"]
    v = _valores((dp.get("banca") or {}).get(clave))
    if len(v) < n + 1:
        return _sin_datos(f"{nombre}: se necesitan {n + 1} ejercicios (hay {len(v)})", [f"banca.{clave}"])
    ult = [x for _, x in sorted(v)][-(n + 1):]
    grave = all(b > a for a, b in zip(ult, ult[1:]))
    return _ok(ult[-1], ult[0], grave,
               f"{nombre} últimos {n + 1} ejercicios: " + " → ".join(f"{x:.2%}" for x in ult), [f"banca.{clave}"])


def morosidad(dp: dict, cfg: dict) -> dict:
    return _tendencia_adversa(dp, "morosidad", "morosidad", cfg)


def coste_riesgo(dp: dict, cfg: dict) -> dict:
    return _tendencia_adversa(dp, "coste_riesgo", "coste del riesgo", cfg)


def cet1(dp: dict, cfg: dict) -> dict:
    """CET1 frente a su requisito + margen; si el emisor no publica CET1, el ratio de capital total frente a su mínimo."""
    banca = dp.get("banca") or {}
    for nombre, clave in (("CET1", "cet1"), ("Capital total", "capital_total")):
        campos = [f"banca.{clave}", f"banca.{clave}_requisito"]
        v, req = _valores(banca.get(clave)), _valores(banca.get(f"{clave}_requisito"))
        if v and req:
            actual, requisito = sorted(v)[-1][1], sorted(req)[-1][1]
            minimo = requisito + cfg["banca_cet1_margen_pp"] / 100
            return _ok(actual, minimo, actual < minimo, f"{nombre} {actual:.2%} frente a requisito {requisito:.2%} + "
                       f"{cfg['banca_cet1_margen_pp']} pp", campos)
    return _sin_datos("faltan CET1 (o el ratio de capital total) y su requisito", ["banca.cet1", "banca.cet1_requisito"])


METRICAS = {
    "fco_beneficio_neto": fco_beneficio_neto, "devengos": devengos, "cxc_vs_ingresos": cxc_vs_ingresos,
    "inventario_vs_ingresos": inventario_vs_ingresos, "sbc_ingresos": sbc_ingresos, "dilucion": dilucion,
    "goodwill_activos": goodwill_activos, "cobertura_intereses": cobertura_intereses,
}
METRICAS_BANCA = {"morosidad": morosidad, "coste_riesgo": coste_riesgo, "cet1": cet1}


def calcular(dp: dict, ruta: str = "general", cfg: dict | None = None) -> dict:
    cfg = cfg or comun.cargar_config()["forense"]
    banco = ruta == "banco_credito"
    metricas: dict[str, dict] = {}
    for nombre, f in METRICAS.items():
        if banco and nombre in NO_BANCOS:
            metricas[nombre] = _no_aplica(f"no aplica a la ruta {ruta}")
        else:
            metricas[nombre] = f(dp, cfg)
    if banco:
        for nombre, f in METRICAS_BANCA.items():
            metricas[nombre] = f(dp, cfg)
    banderas = [{"bandera": m["detalle"], "nivel": "grave", "metrica": n, "valor": m["valor"], "umbral": m["umbral"]}
                for n, m in metricas.items() if m["estado"] == "evaluada" and m["grave"]]
    return {
        "ticker": dp.get("ticker"), "ruta": ruta, "metricas": metricas, "banderas": banderas,
        "resumen": {"graves": len(banderas),
                    "sin_datos": [n for n, m in metricas.items() if m["estado"] == "sin_datos"],
                    "no_aplica": [n for n, m in metricas.items() if m["estado"] == "no_aplica"]},
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Métricas forenses cuantitativas y banderas graves.")
    p.add_argument("--datapack", required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--ruta")
    g.add_argument("--router", help="router.json (se toma su campo ruta)")
    p.add_argument("--salida")
    a = p.parse_args(argv)
    try:
        ruta = a.ruta or (comun.leer_json(a.router)["ruta"] if a.router else "general")
        res = calcular(comun.leer_json(a.datapack), ruta)
    except (KeyError, FileNotFoundError) as e:
        comun.salir_con_error(f"{type(e).__name__}: {e}")
    if a.salida:
        comun.escribir_json(a.salida, res)
        print(a.salida)
    else:
        print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
