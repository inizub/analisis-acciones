"""DCF de la empresa (FCFF) a 10 años y WACC.

Cadena: crecimiento de ingresos → margen operativo → reinversión (Δventas / ratio ventas-capital) → impuestos.
Valor terminal con g ≤ Rf y ROIC terminal = WACC salvo moat documentado.

Uso CLI:
    python dcf.py ENTRADA.json [--salida SALIDA.json]
ENTRADA: {"wacc": {...} | número, "dcf": {...}} con los argumentos de wacc() y dcf_fcff().
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.comun_motor import ErrorMotor, exigir, finito, por_accion, serie_anual, trayectoria  # noqa: E402


def beta_reapalancada(beta_desapalancada: float, deuda_capital: float, tasa_impuestos: float) -> float:
    """Hamada: βL = βU · (1 + (1 − t) · D/E)."""
    exigir(deuda_capital >= 0, "D/E no puede ser negativo")
    return beta_desapalancada * (1 + (1 - tasa_impuestos) * deuda_capital)


def rating_sintetico(cobertura: float, tabla: Sequence[dict]) -> dict:
    """Rating y diferencial según la cobertura de intereses (EBIT / intereses).

    `tabla`: filas {cobertura_min, rating, diferencial}, p. ej. la tabla de ratings sintéticos de Damodaran.
    Se elige la fila con mayor cobertura_min ≤ cobertura.
    """
    exigir(len(tabla) > 0, "tabla de ratings vacía")
    filas = sorted(tabla, key=lambda f: f["cobertura_min"])
    elegida = filas[0]
    for f in filas:
        if cobertura >= f["cobertura_min"]:
            elegida = f
    return {"rating": elegida["rating"], "diferencial": elegida["diferencial"], "cobertura": cobertura}


def wacc(rf: float, erp: float, beta_desapalancada: float, deuda_capital: float, tasa_impuestos: float,
         coste_deuda_antes_impuestos: float | None = None, crp: float = 0.0, lambda_crp: float = 1.0,
         cobertura: float | None = None, tabla_ratings: Sequence[dict] | None = None) -> dict:
    """WACC con CAPM (Ke = Rf + βL·ERP + λ·CRP) y coste de deuda directo o por rating sintético (Rf + diferencial)."""
    for n, v in (("rf", rf), ("erp", erp), ("beta_desapalancada", beta_desapalancada), ("tasa_impuestos", tasa_impuestos)):
        finito(v, n)
    bl = beta_reapalancada(beta_desapalancada, deuda_capital, tasa_impuestos)
    ke = rf + bl * erp + lambda_crp * crp
    rating = None
    if coste_deuda_antes_impuestos is None:
        exigir(cobertura is not None and tabla_ratings is not None,
               "falta coste_deuda_antes_impuestos o (cobertura + tabla_ratings)")
        rating = rating_sintetico(cobertura, tabla_ratings)
        coste_deuda_antes_impuestos = rf + rating["diferencial"] + crp
    kd = coste_deuda_antes_impuestos * (1 - tasa_impuestos)
    peso_e = 1 / (1 + deuda_capital)
    w = peso_e * ke + (1 - peso_e) * kd
    return {"wacc": w, "ke": ke, "kd_despues_impuestos": kd, "kd_antes_impuestos": coste_deuda_antes_impuestos,
            "beta_apalancada": bl, "peso_patrimonio": peso_e, "rating_sintetico": rating}


def dcf_fcff(ingresos0: float, crecimiento: float | Sequence[float], margen_operativo: float | Sequence[float],
             ventas_capital: float, tasa_impuestos: float, wacc: float | Sequence[float], g_terminal: float, rf: float,
             deuda: float, caja: float, acciones: float, roic_terminal: float | None = None,
             margen_inicial: float | None = None, anios_convergencia_margen: int | None = None,
             moat_documentado: bool = False, otros_activos: float = 0.0, minoritarios: float = 0.0,
             tasa_impuestos_terminal: float | None = None, anios: int = 10) -> dict:
    """Valor por acción con FCFF a `anios` años.

    - crecimiento: escalar o lista anual.
    - margen_operativo: margen objetivo (escalar) o lista anual. Con `margen_inicial`, el margen converge
      linealmente al objetivo en `anios_convergencia_margen` años.
    - ROIC terminal: por defecto = WACC terminal; distinto solo si `moat_documentado`.
    """
    exigir(ingresos0 > 0, "ingresos0 debe ser positivo")
    exigir(ventas_capital > 0, "ventas_capital debe ser positivo")
    exigir(g_terminal <= rf + 1e-12, f"g_terminal ({g_terminal:.4f}) no puede superar Rf ({rf:.4f})")
    g = serie_anual(crecimiento, anios, "crecimiento")
    if isinstance(margen_operativo, (int, float)) and margen_inicial is not None:
        m = trayectoria(margen_inicial, margen_operativo, anios, anios_convergencia_margen)
    else:
        m = serie_anual(margen_operativo, anios, "margen_operativo")
    tasas = serie_anual(wacc, anios, "wacc")
    w_term = tasas[-1]
    exigir(w_term > g_terminal, "WACC terminal debe superar g_terminal")
    roic_t = roic_terminal if (moat_documentado and roic_terminal is not None) else w_term
    exigir(roic_t > 0, "ROIC terminal debe ser positivo")
    t_term = tasa_impuestos if tasa_impuestos_terminal is None else tasa_impuestos_terminal

    filas, ingresos, acumulado, vp = [], ingresos0, 1.0, 0.0
    for t in range(anios):
        nuevos = ingresos * (1 + g[t])
        ebit = nuevos * m[t]
        nopat = ebit * (1 - tasa_impuestos) if ebit > 0 else ebit
        reinversion = (nuevos - ingresos) / ventas_capital
        fcff = nopat - reinversion
        acumulado *= 1 + tasas[t]
        vp_t = fcff / acumulado
        vp += vp_t
        filas.append({"anio": t + 1, "crecimiento": g[t], "ingresos": nuevos, "margen": m[t], "ebit": ebit,
                      "nopat": nopat, "reinversion": reinversion, "fcff": fcff, "wacc": tasas[t], "vp": vp_t})
        ingresos = nuevos
    ebit_term = ingresos * (1 + g_terminal) * m[-1]
    nopat_term = ebit_term * (1 - t_term)
    tasa_reinv_term = g_terminal / roic_t if g_terminal > 0 else 0.0
    fcff_term = nopat_term * (1 - tasa_reinv_term)
    vt = fcff_term / (w_term - g_terminal)
    vp_vt = vt / acumulado
    valor_operativo = vp + vp_vt
    patrimonio = valor_operativo + caja + otros_activos - deuda - minoritarios
    return {
        "valor_por_accion": por_accion(patrimonio, acciones),
        "puente": {"vp_flujos": vp, "vp_valor_terminal": vp_vt, "valor_operativo": valor_operativo,
                   "caja": caja, "otros_activos": otros_activos, "deuda": deuda, "minoritarios": minoritarios,
                   "valor_patrimonio": patrimonio, "acciones": acciones},
        "supuestos": {"g_terminal": g_terminal, "roic_terminal": roic_t, "tasa_reinversion_terminal": tasa_reinv_term,
                      "wacc_terminal": w_term, "valor_terminal": vt, "peso_valor_terminal": vp_vt / valor_operativo
                      if valor_operativo else None, "ventas_capital": ventas_capital, "tasa_impuestos": tasa_impuestos},
        "flujos": filas,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DCF FCFF a 10 años.")
    p.add_argument("entrada")
    p.add_argument("--salida")
    a = p.parse_args(argv)
    e = json.loads(Path(a.entrada).read_text(encoding="utf-8"))
    try:
        res = {}
        args = dict(e["dcf"])
        if isinstance(e.get("wacc"), dict):
            res["wacc"] = wacc(**e["wacc"])
            args["wacc"] = res["wacc"]["wacc"]
        elif "wacc" in e:
            args["wacc"] = e["wacc"]
        res["dcf"] = dcf_fcff(**args)
    except (ErrorMotor, TypeError, KeyError) as err:
        print(json.dumps({"error": str(err)}, ensure_ascii=False), file=sys.stderr)
        return 1
    texto = json.dumps(res, ensure_ascii=False, indent=2)
    Path(a.salida).write_text(texto, encoding="utf-8") if a.salida else print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
