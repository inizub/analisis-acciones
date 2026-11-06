"""rNPV para biotech precomercial: por activo, ventas pico × probabilidad acumulada de aprobación (tabla BIO por
fase y área), descontado; más caja neta y menos el VP de los gastos generales.

Tabla de probabilidades: filas {area, transicion, p, n} con transicion ∈ {I_II, II_III, III_NDA, NDA_APROB}.
Las celdas con n < 100 se encogen hacia la media de todas las áreas: p' = (n·p + 100·p_media)/(n + 100).
La transición solicitud→aprobación se limita al 95 %.

Uso CLI:
    python rnpv.py ENTRADA.json   ({"activos": [...], "tabla": [...], ...} argumentos de valor_rnpv)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.comun_motor import ErrorMotor, exigir, por_accion  # noqa: E402

TRANSICIONES = ("I_II", "II_III", "III_NDA", "NDA_APROB")
FASES = {"I": 0, "II": 1, "III": 2, "NDA": 3}
N_MIN = 100
TOPE_APROBACION = 0.95


def cargar_tabla_bio(ruta: str | Path | None = None, grupo: str = "area") -> list[dict]:
    """Filas {area, transicion, p, n} de bio_pos_2011_2020.csv (probabilidades de transición, tipo POS) de un grupo.
    Grupos: area, oncologia_vs_no, oncologia_subtipo, prevalencia, clase_fa, modalidad, biomarcadores.
    La categoría `todas` es el promedio de todas las indicaciones."""
    import csv

    ruta = Path(ruta) if ruta else Path(__file__).resolve().parents[2] / "assets" / "bio_pos_2011_2020.csv"
    with open(ruta, encoding="utf-8") as f:
        filas = [{"area": r["categoria"], "transicion": r["transicion"], "p": float(r["p"]), "n": int(r["n"])}
                 for r in csv.DictReader(f) if r["grupo"] == grupo and r["tipo"] == "POS"]
    exigir(filas, f"bio_pos_2011_2020.csv sin filas POS para el grupo '{grupo}'")
    return filas


def probabilidad_transicion(tabla: Sequence[dict], area: str, transicion: str) -> dict:
    filas = [f for f in tabla if f["transicion"] == transicion]
    exigir(filas, f"tabla sin transición {transicion}")
    media_fila = next((f for f in filas if f["area"] == "todas"), None)
    p_media = media_fila["p"] if media_fila else sum(f["p"] for f in filas) / len(filas)
    fila = next((f for f in filas if f["area"] == area), None)
    if fila is None:
        p, n, origen = p_media, None, "media"
    elif fila.get("n") is not None and fila["n"] < N_MIN:
        p = (fila["n"] * fila["p"] + N_MIN * p_media) / (fila["n"] + N_MIN)
        n, origen = fila["n"], "encogida"
    else:
        p, n, origen = fila["p"], fila.get("n"), "area"
    if transicion == "NDA_APROB":
        p = min(p, TOPE_APROBACION)
    return {"p": p, "n": n, "origen": origen}


def probabilidad_acumulada(tabla: Sequence[dict], area: str, fase: str) -> dict:
    exigir(fase in FASES, f"fase desconocida: {fase} (válidas: {list(FASES)})")
    pasos = [probabilidad_transicion(tabla, area, t) for t in TRANSICIONES[FASES[fase]:]]
    p = 1.0
    for s in pasos:
        p *= s["p"]
    return {"p": p, "pasos": dict(zip(TRANSICIONES[FASES[fase]:], pasos))}


def vp_activo(ventas_pico: float, margen: float, anios_hasta_lanzamiento: int, anios_rampa: int,
              anios_meseta: int, anios_declive: int, tasa: float, tasa_impuestos: float,
              costes_desarrollo: Sequence[float] = ()) -> dict:
    """VP de los flujos de un activo si se aprueba (sin ajustar por probabilidad), y VP de sus costes previos."""
    exigir(ventas_pico >= 0 and anios_hasta_lanzamiento >= 0, "entradas negativas")
    perfil = ([(k + 1) / anios_rampa for k in range(anios_rampa)] + [1.0] * anios_meseta
              + [1 - (k + 1) / (anios_declive + 1) for k in range(anios_declive)])
    vp = 0.0
    for k, f in enumerate(perfil):
        t = anios_hasta_lanzamiento + k + 1
        vp += ventas_pico * f * margen * (1 - tasa_impuestos) / (1 + tasa) ** t
    vp_costes = sum(c / (1 + tasa) ** (t + 1) for t, c in enumerate(costes_desarrollo))
    return {"vp_si_aprobado": vp, "vp_costes": vp_costes}


def valor_rnpv(activos: Sequence[dict], tabla: Sequence[dict], tasa: float, caja_neta: float,
               gastos_generales_anuales: float, anios_gastos: int, acciones: float, tasa_impuestos: float = 0.21) -> dict:
    """Cada activo: {nombre, fase, area, ventas_pico, margen, anios_hasta_lanzamiento, anios_rampa, anios_meseta,
    anios_declive, costes_desarrollo?}. Los costes de desarrollo se ponderan con la probabilidad de llegar a cada año
    de forma simplificada: se descuentan íntegros (enfoque conservador)."""
    detalle, total = [], 0.0
    for a in activos:
        pa = probabilidad_acumulada(tabla, a["area"], a["fase"])
        v = vp_activo(a["ventas_pico"], a["margen"], a["anios_hasta_lanzamiento"], a.get("anios_rampa", 5),
                      a.get("anios_meseta", 5), a.get("anios_declive", 3), tasa, tasa_impuestos,
                      a.get("costes_desarrollo", ()))
        rn = pa["p"] * v["vp_si_aprobado"] - v["vp_costes"]
        total += rn
        detalle.append({"nombre": a.get("nombre"), "fase": a["fase"], "area": a["area"], "p_aprobacion": pa["p"],
                        "pasos": pa["pasos"], **v, "rnpv": rn})
    vp_gg = sum(gastos_generales_anuales / (1 + tasa) ** t for t in range(1, anios_gastos + 1))
    patrimonio = total + caja_neta - vp_gg
    return {"valor_por_accion": por_accion(patrimonio, acciones),
            "puente": {"rnpv_activos": total, "caja_neta": caja_neta, "vp_gastos_generales": vp_gg,
                       "valor_patrimonio": patrimonio, "acciones": acciones},
            "supuestos": {"tasa": tasa, "tasa_impuestos": tasa_impuestos, "n_min_encogimiento": N_MIN,
                          "tope_aprobacion": TOPE_APROBACION},
            "activos": detalle}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="rNPV por activo (biotech).")
    p.add_argument("entrada")
    a = p.parse_args(argv)
    try:
        res = valor_rnpv(**json.loads(Path(a.entrada).read_text(encoding="utf-8")))
    except (ErrorMotor, TypeError, KeyError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
