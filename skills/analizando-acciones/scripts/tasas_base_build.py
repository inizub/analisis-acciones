"""Construye assets/base_rates.csv a partir de EDGAR `frames` (desde ~2009) para las clases de tamaño de ventas
sin tasas base publicadas, y añade las filas publicadas por Mauboussin y Callahan (2026).

Uso CLI:
    python tasas_base_build.py [--salida base_rates.csv] [--inicio 2009] [--fin 2025] [--solo-publicadas]

Métricas por clase de tamaño (ventas iniciales, M$):
  crecimiento_ventas_3a / _5a   TCAC de ventas entre t y t+3 / t+5
  margen_operativo              beneficio operativo / ventas en t
  roe                           beneficio neto / patrimonio en t (patrimonio > 0)
Se agrupan todos los años de inicio. Media y desviación típica se calculan winsorizando en [1, 99] percentiles;
los percentiles p10-p90 son los de los datos sin winsorizar.

Limitaciones (se anotan en la columna `notas` del CSV):
  - Sin sector: EDGAR frames no trae el código SIC. Todas las filas son sector `todos` y mezclan financieras.
  - Supervivencia: el crecimiento exige datos en t y en t+h, de modo que una empresa deslistada antes de t+h no
    entra. Las deslistadas con datos en frames sí cuentan hasta su último ejercicio.
  - Solo hechos us-gaap en USD (emisores 20-F con ifrs-full quedan fuera).
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
from datos.edgar import ClienteEdgar  # noqa: E402

RUTA_SALIDA = comun.DIR_ASSETS / "base_rates.csv"
COLUMNAS = ["clase_musd", "sector", "metrica", "n", "media", "desv", "p10", "p25", "p50", "p75", "p90", "fuente",
            "periodo", "notas"]
MIN_N = 30
VENTAS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
          "RevenueFromContractWithCustomerIncludingAssessedTax"]
FUENTE_MAUBOUSSIN = "mauboussin_2026"
FUENTE_CALCULO = "edgar_frames_calc"
NOTA_PUBLICADA = ("Mauboussin y Callahan, 'Bayes and Base Rates 2.0', 13-may-2026; EE. UU., ventas iniciales 2-5 mil M$, "
                  "1950-2025, n=19.264")


def etiqueta_clase(lo: float, hi: float | None) -> str:
    return f">{lo:g}" if hi is None else f"{lo:g}-{hi:g}"


def clases(limites: list[float]) -> list[tuple[float, float | None, str]]:
    res = []
    for i, lo in enumerate(limites):
        hi = limites[i + 1] if i + 1 < len(limites) else None
        res.append((lo, hi, etiqueta_clase(lo, hi)))
    return res


def clase_de(ventas_musd: float, limites: list[float]) -> str | None:
    if ventas_musd < limites[0]:
        return None
    for lo, hi, etiqueta in clases(limites):
        if ventas_musd >= lo and (hi is None or ventas_musd < hi):
            return etiqueta
    return None


def filas_publicadas() -> list[dict]:
    """Filas de Mauboussin y Callahan (2026) transcritas de A9 del spec. Verificar contra el PDF original."""
    base = {"clase_musd": "2000-5000", "fuente": FUENTE_MAUBOUSSIN, "periodo": "1950-2025", "p10": "", "p25": "",
            "p50": "", "p75": "", "p90": ""}
    return [
        {**base, "sector": "todos", "metrica": "crecimiento_ventas_5a", "n": 19264, "media": 0.069, "desv": 0.111,
         "notas": f"Nominal. {NOTA_PUBLICADA}"},
        {**base, "sector": "todos", "metrica": "crecimiento_ventas_5a_real", "n": 19264, "media": 0.037, "desv": 0.106,
         "notas": f"Real. {NOTA_PUBLICADA}"},
        {**base, "sector": "IT", "metrica": "crecimiento_ventas_5a", "n": "", "media": 0.061, "desv": 0.133,
         "notas": f"Nominal, sector IT. {NOTA_PUBLICADA}"},
    ]


# ---------------------------------------------------------------- descarga

def descargar(cliente: ClienteEdgar, inicio: int, fin: int, avance=None) -> dict[str, dict[tuple[int, int], float]]:
    """{metrica: {(cik, año): valor}}. Ventas: el primer concepto disponible por emisor y año."""
    datos: dict[str, dict[tuple[int, int], float]] = {"ventas": {}, "ebit": {}, "bn": {}, "patrimonio": {}}
    for anio in range(inicio, fin + 1):
        for concepto in VENTAS:
            for cik, val, _, _ in cliente.frame(concepto, "USD", f"CY{anio}"):
                if val and val > 0:
                    datos["ventas"].setdefault((cik, anio), float(val))
        for clave, concepto in (("ebit", "OperatingIncomeLoss"), ("bn", "NetIncomeLoss")):
            for cik, val, _, _ in cliente.frame(concepto, "USD", f"CY{anio}"):
                datos[clave].setdefault((cik, anio), float(val))
        for cik, val, _, _ in cliente.frame("StockholdersEquity", "USD", f"CY{anio}Q4I"):
            datos["patrimonio"].setdefault((cik, anio), float(val))
        if avance:
            avance(anio)
    return datos


# ---------------------------------------------------------------- observaciones y agregación

def observaciones(datos: dict, limites: list[float], ventas_min: float) -> pd.DataFrame:
    """Una fila por (emisor, año de inicio) con su clase y sus métricas."""
    filas = []
    ventas = datos["ventas"]
    for (cik, anio), v in ventas.items():
        v_musd = v / 1e6
        if v_musd < ventas_min:
            continue
        clase = clase_de(v_musd, limites)
        fila = {"cik": cik, "anio": anio, "clase": clase}
        for h in (3, 5):
            v2 = ventas.get((cik, anio + h))
            fila[f"crec{h}"] = (v2 / v) ** (1 / h) - 1 if v2 else np.nan
        ebit = datos["ebit"].get((cik, anio))
        fila["margen"] = ebit / v if ebit is not None else np.nan
        bn, pat = datos["bn"].get((cik, anio)), datos["patrimonio"].get((cik, anio))
        fila["roe"] = bn / pat if bn is not None and pat is not None and pat > 0 else np.nan
        filas.append(fila)
    return pd.DataFrame(filas)


METRICAS = {"crec3": "crecimiento_ventas_3a", "crec5": "crecimiento_ventas_5a", "margen": "margen_operativo",
            "roe": "roe"}


def resumen(valores: np.ndarray, winsor: tuple[float, float]) -> dict:
    lo, hi = np.percentile(valores, winsor)
    w = np.clip(valores, lo, hi)
    q = np.percentile(valores, [10, 25, 50, 75, 90])
    return {"n": int(len(valores)), "media": float(w.mean()), "desv": float(w.std(ddof=1)),
            "p10": float(q[0]), "p25": float(q[1]), "p50": float(q[2]), "p75": float(q[3]), "p90": float(q[4])}


def agregar(df: pd.DataFrame, limites: list[float], winsor: tuple[float, float], periodo: str) -> list[dict]:
    notas = ("Sin sector (mezcla financieras); sesgo de supervivencia (exige datos en t y t+h); "
             "solo us-gaap en USD; media y desv winsorizadas 1-99.")
    filas = []
    etiquetas = [e for _, _, e in clases(limites)] + ["todas"]
    for etiqueta in etiquetas:
        sub = df if etiqueta == "todas" else df[df["clase"] == etiqueta]
        for col, nombre in METRICAS.items():
            v = sub[col].replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
            if len(v) < MIN_N:
                continue
            filas.append({"clase_musd": etiqueta, "sector": "todos", "metrica": nombre, "fuente": FUENTE_CALCULO,
                          "periodo": periodo, "notas": notas, **resumen(v, winsor)})
    return filas


def escribir(filas: list[dict], ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, lineterminator="\n")
        w.writeheader()
        for fila in filas:
            w.writerow({k: (f"{v:.6f}" if isinstance(v, float) else v) for k, v in {c: fila.get(c, "") for c in COLUMNAS}.items()})
    return ruta


def construir(cliente: ClienteEdgar, inicio: int, fin: int, cfg: dict, avance=None) -> list[dict]:
    tb = cfg["tasas_base"]
    datos = descargar(cliente, inicio, fin, avance)
    df = observaciones(datos, tb["clases_musd"], tb["ventas_min_musd"])
    return filas_publicadas() + agregar(df, tb["clases_musd"], tuple(tb["winsor"]), f"{inicio}-{fin}")


def main(argv: list[str] | None = None) -> int:
    cfg = comun.cargar_config()
    p = argparse.ArgumentParser(description="Construye base_rates.csv con EDGAR frames.")
    p.add_argument("--salida", default=str(RUTA_SALIDA))
    p.add_argument("--inicio", type=int, default=cfg["tasas_base"]["anio_inicio"])
    p.add_argument("--fin", type=int, default=cfg["tasas_base"]["anio_fin"])
    p.add_argument("--solo-publicadas", action="store_true", help="Escribe solo las filas de Mauboussin (sin red)")
    a = p.parse_args(argv)
    try:
        if a.solo_publicadas:
            filas = filas_publicadas()
        else:
            filas = construir(ClienteEdgar(), a.inicio, a.fin, cfg,
                              avance=lambda y: print(f"  frames {y} descargados", file=sys.stderr))
    except comun.ErrorDatos as e:
        comun.salir_con_error(f"{e} [causa={e.causa}]")
    ruta = escribir(filas, Path(a.salida))
    print(comun.volcar_json({"salida": str(ruta), "filas": len(filas),
                             "calculadas": sum(1 for f in filas if f["fuente"] == FUENTE_CALCULO)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
