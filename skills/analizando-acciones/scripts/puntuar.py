"""Puntúa las predicciones resueltas del diario (A6.8, A12) y escribe el informe trimestral.

Uso CLI:
    python puntuar.py informe --diario predicciones.jsonl [--salida-dir diario/informes] [--hoy AAAA-MM-DD]
    python puntuar.py resumen --diario predicciones.jsonl         (JSON con las métricas, sin escribir archivos)

Para cada evento (E0-E4) y modo (completo, rápido, degradado: el degradado se puntúa aparte):
  - log score medio (p limitada a [0,02; 0,98]; más alto es mejor) y Brier medio (más bajo es mejor)
  - Brier skill score frente a B0 = 1 − Brier / Brier(B0)
  - pendiente de calibración: regresión logística del resultado sobre logit(p); ideal: pendiente 1, intercepto 0
  - comparación por pares con cada baseline (B0-B3): Diebold-Mariano con corrección de Harvey-Leybourne-Newbold y
    varianza HAC de Bartlett con h−1 retardos, sobre la pérdida de Brier y la de log, ordenando por fecha de emisión
Se puntúa la probabilidad preregistrada de la predicción original; los updates y las anuladas no cuentan.
Baselines: E0-E2 usan B0-B3; E4 usa B0_E4 y B1_E4; E3 no tiene baselines.
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
import diario as dr  # noqa: E402

BASELINES = ["B0", "B1", "B2", "B3"]


# ---------------------------------------------------------------- datos

def baseline_de(bl: dict, qid: str, nombre: str) -> float | None:
    """Probabilidad del baseline para el evento, o None si no aplica."""
    if qid in ("E0", "E1", "E2"):
        return bl.get(nombre)
    if qid == "E4":
        return {"B0": bl.get("B0_E4"), "B1": bl.get("B1_E4")}.get(nombre)
    return None


def _ts(texto: str) -> pd.Timestamp:
    t = pd.Timestamp(texto)
    return t.tz_convert(None) if t.tzinfo else t


def _version(v: str | None) -> tuple[int, ...] | None:
    """'0.2.1' → (0, 2, 1); None si no es una versión numérica."""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return None


def version_anterior(registro: dict, minima: str | None) -> bool:
    """¿La predicción se emitió con una versión del plugin anterior a la mínima? Sin versión legible, no se excluye."""
    if not minima:
        return False
    v, m = _version((registro.get("skill") or {}).get("version")), _version(minima)
    return v is not None and m is not None and v < m


def cargar_filas(registros: list[dict], version_minima: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Una fila por pregunta resuelta de cada predicción original, y un recuento global del diario.

    Las predicciones de versiones anteriores a `version_minima` se cuentan aparte y no se puntúan."""
    res = dr.resoluciones(registros)
    filas, cuenta = [], {"predicciones": 0, "no_analizables": 0, "updates": 0, "resueltas": 0, "anuladas": 0,
                         "pendientes": 0, "version_anterior": 0}
    for r in registros:
        t = dr.tipo(r)
        if t == "update":
            cuenta["updates"] += 1
        if t != "prediccion":
            continue
        if r["veredicto"] == "no_analizable":
            cuenta["no_analizables"] += 1
            continue
        if version_anterior(r, version_minima):
            cuenta["version_anterior"] += 1
            continue
        cuenta["predicciones"] += 1
        for q in r["preguntas"]:
            rs = res.get((r["id"], q["qid"]))
            if rs is None:
                cuenta["pendientes"] += 1
            elif rs["estado"] == "anulada":
                cuenta["anuladas"] += 1
            else:
                cuenta["resueltas"] += 1
                fila = {"id": r["id"], "ticker": r["ticker"], "modo": r["skill"]["modo"], "qid": q["qid"],
                        "p": q["p"], "y": rs["resultado"], "emitida": _ts(r["created_at"])}
                for b in BASELINES:
                    fila[b] = baseline_de(r["baselines"], q["qid"], b)
                filas.append(fila)
    cols = ["id", "ticker", "modo", "qid", "p", "y", "emitida", *BASELINES]
    return pd.DataFrame(filas, columns=cols), cuenta


# ---------------------------------------------------------------- métricas

def limitar(p: np.ndarray, clip: list[float]) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), clip[0], clip[1])


def perdida_brier(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (np.asarray(p, dtype=float) - y) ** 2


def perdida_log(p: np.ndarray, y: np.ndarray, clip: list[float]) -> np.ndarray:
    q = limitar(p, clip)
    return -(y * np.log(q) + (1 - y) * np.log(1 - q))


def metricas(p: np.ndarray, y: np.ndarray, clip: list[float]) -> dict:
    return {"n": int(len(y)), "tasa_observada": float(np.mean(y)), "p_media": float(np.mean(p)),
            "log_score": float(-np.mean(perdida_log(p, y, clip))), "brier": float(np.mean(perdida_brier(p, y)))}


def brier_skill(brier_modelo: float, brier_ref: float) -> float | None:
    return None if brier_ref <= 0 else 1 - brier_modelo / brier_ref


def calibracion(p: np.ndarray, y: np.ndarray, clip: list[float], min_n: int) -> dict | None:
    """Regresión logística y ~ a + b·logit(p) por IRLS con una pequeña penalización ridge."""
    if len(y) < min_n or y.min() == y.max():
        return None
    q = limitar(p, clip)
    x = np.log(q / (1 - q))
    X = np.column_stack([np.ones_like(x), x])
    beta = np.zeros(2)
    for _ in range(100):
        mu = 1 / (1 + np.exp(-X @ beta))
        W = mu * (1 - mu)
        H = X.T @ (X * W[:, None]) + 1e-6 * np.eye(2)
        paso = np.linalg.solve(H, X.T @ (y - mu))
        beta = beta + paso
        if np.max(np.abs(paso)) < 1e-10:
            break
    return {"intercepto": float(beta[0]), "pendiente": float(beta[1]), "n": int(len(y))}


def varianza_hac(d: np.ndarray, h: int) -> float:
    """Varianza de largo plazo de Bartlett con h−1 retardos: γ0 + 2·Σ (1 − k/h)·γk."""
    n = len(d)
    c = d - d.mean()
    v = float(np.sum(c * c) / n)
    for k in range(1, h):
        v += 2 * (1 - k / h) * float(np.sum(c[k:] * c[:-k]) / n)
    return v


def diebold_mariano(perd_modelo: np.ndarray, perd_base: np.ndarray, h: int, min_n: int) -> dict | None:
    """Test de igual precisión predictiva. d = pérdida del modelo − pérdida del baseline: d medio < 0 favorece al modelo.
    Corrección HLN: DM·√((n + 1 − 2h + h(h−1)/n)/n), contrastada con una t de Student de n−1 grados. Devuelve None si
    n < min_n, si n ≤ 2h (la corrección deja de estar definida) o si la varianza HAC no es positiva."""
    d = np.asarray(perd_modelo, dtype=float) - np.asarray(perd_base, dtype=float)
    n = len(d)
    if n < min_n or n <= 2 * h:
        return None
    lrv = varianza_hac(d, h)
    if lrv <= 1e-15:
        return None
    dm = float(d.mean() / math.sqrt(lrv / n))
    hln = dm * math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return {"n": n, "h": h, "diferencia_media": float(d.mean()), "dm": dm, "dm_hln": hln,
            "p_valor": float(2 * (1 - stats.t.cdf(abs(hln), n - 1)))}


def puntuar_grupo(g: pd.DataFrame, qid: str, cfg: dict) -> dict:
    pc = cfg["puntuacion"]
    clip = pc["clip_log"]
    g = g.sort_values("emitida")
    p, y = g["p"].to_numpy(float), g["y"].to_numpy(float)
    res: dict[str, Any] = {"qid": qid, "modo": g["modo"].iloc[0], **metricas(p, y, clip)}
    res["calibracion"] = calibracion(p, y, clip, pc["min_n_calibracion"])
    res["baselines"], res["comparaciones"] = {}, {}
    h = pc["h_pasos"][qid]
    for b in BASELINES:
        gb = g[g[b].notna()]
        if gb.empty:
            continue
        pb, yb, pm = gb[b].to_numpy(float), gb["y"].to_numpy(float), gb["p"].to_numpy(float)
        mb = metricas(pb, yb, clip)
        mm = metricas(pm, yb, clip)
        res["baselines"][b] = {**mb, "brier_modelo_mismas_filas": mm["brier"], "log_score_modelo_mismas_filas": mm["log_score"]}
        res["comparaciones"][b] = {
            "brier": diebold_mariano(perdida_brier(pm, yb), perdida_brier(pb, yb), h, pc["min_n_dm"]),
            "log": diebold_mariano(perdida_log(pm, yb, clip), perdida_log(pb, yb, clip), h, pc["min_n_dm"])}
    b0 = res["baselines"].get("B0")
    res["bss_vs_B0"] = brier_skill(b0["brier_modelo_mismas_filas"], b0["brier"]) if b0 else None
    return res


def puntuar(registros: list[dict], cfg: dict | None = None) -> dict:
    cfg = cfg or comun.cargar_config()
    df, cuenta = cargar_filas(registros, cfg["puntuacion"].get("version_minima"))
    grupos = []
    for (qid, modo), g in df.groupby(["qid", "modo"], sort=True):
        grupos.append(puntuar_grupo(g, qid, cfg))
    return {"generado": comun.ahora_iso(), "cuenta": cuenta, "grupos": grupos}


# ---------------------------------------------------------------- informe

def trimestre(f: date) -> str:
    return f"{f.year}-T{(f.month - 1) // 3 + 1}"


def _f(x: float | None, dec: int = 3) -> str:
    return "n/d" if x is None else f"{x:.{dec}f}".replace(".", ",")


def informe_md(res: dict, etiqueta: str) -> str:
    c = res["cuenta"]
    L = [f"# Informe de puntuación {etiqueta}", "",
         f"Predicciones: {c['predicciones']} · no analizables: {c['no_analizables']} · updates: {c['updates']}"
         + (f" · de versiones anteriores (no puntuadas): {c['version_anterior']}" if c.get("version_anterior") else ""), "",
         f"Preguntas: {c['resueltas']} resueltas · {c['anuladas']} anuladas · {c['pendientes']} pendientes", ""]
    if not res["grupos"]:
        return "\n".join(L + ["Todavía no hay preguntas resueltas que puntuar.", ""])
    L += ["## Métricas por evento y modo", "",
          "| Evento | Modo | n | Tasa observada | p media | Log score | Brier | BSS vs B0 | Pendiente calib. |",
          "|---|---|---|---|---|---|---|---|---|"]
    for g in res["grupos"]:
        cal = g["calibracion"]
        L.append(f"| {g['qid']} | {g['modo']} | {g['n']} | {_f(g['tasa_observada'], 2)} | {_f(g['p_media'], 2)} | "
                 f"{_f(g['log_score'])} | {_f(g['brier'])} | {_f(g['bss_vs_B0'])} | "
                 f"{_f(cal['pendiente'], 2) if cal else 'n/d'} |")
    L += ["", "## Comparación con los baselines (Brier, Diebold-Mariano con corrección HLN)", "",
          "Diferencia media = Brier del modelo − Brier del baseline en las mismas filas; negativa favorece al modelo.", "",
          "| Evento | Modo | Baseline | n | Brier baseline | Brier modelo | Dif. media | p-valor |", "|---|---|---|---|---|---|---|---|"]
    for g in res["grupos"]:
        for b, m in g["baselines"].items():
            dm = g["comparaciones"][b]["brier"]
            L.append(f"| {g['qid']} | {g['modo']} | {b} | {m['n']} | {_f(m['brier'])} | {_f(m['brier_modelo_mismas_filas'])} | "
                     f"{_f(dm['diferencia_media'], 4) if dm else 'n/d'} | {_f(dm['p_valor']) if dm else 'n/d'} |")
    L += ["", "n/d = datos insuficientes para el test (se exigen n ≥ 10 y n > 2h) o varianza nula.", ""]
    return "\n".join(L)


def escribir_informe(diario: Path, salida_dir: Path, hoy: date, cfg: dict | None = None) -> dict:
    res = puntuar(dr.leer_registros(diario), cfg)
    etiqueta = trimestre(hoy)
    salida_dir.mkdir(parents=True, exist_ok=True)
    md, js = salida_dir / f"{etiqueta}.md", salida_dir / f"{etiqueta}.json"
    md.write_text(informe_md(res, etiqueta), encoding="utf-8")
    comun.escribir_json(js, res)
    return {"informe": str(md), "datos": str(js), "grupos": len(res["grupos"]), **res["cuenta"]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Puntuación de las predicciones resueltas.")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("informe")
    i.add_argument("--diario", required=True)
    i.add_argument("--salida-dir")
    i.add_argument("--hoy")
    r = sub.add_parser("resumen")
    r.add_argument("--diario", required=True)
    a = p.parse_args(argv)
    diario = Path(a.diario)
    try:
        if a.cmd == "informe":
            salida = Path(a.salida_dir) if a.salida_dir else diario.parent / "informes"
            res = escribir_informe(diario, salida, date.fromisoformat(a.hoy) if a.hoy else date.today())
        else:
            res = puntuar(dr.leer_registros(diario))
    except (ValueError, FileNotFoundError, KeyError) as e:
        comun.salir_con_error(f"{type(e).__name__}: {e}")
    print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
