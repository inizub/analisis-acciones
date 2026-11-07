"""Agrega las probabilidades de los analistas y aplica las reglas del veredicto (A6.6, A1).

Uso CLI:
    python agregar.py --dir RUN_DIR --modo completo|rapido|degradado [--analistas A B] [--salida agregado.json]

Lee de RUN_DIR: escenarios_<X>.json (salida de escenarios.py de cada analista), motor_inicial.json (DCF inverso)
y forense.json o forense_metricas.json (banderas). Escribe agregado.json.

Por evento:
  p_agg = media de las p de A y B (mezcla de sus distribuciones: mantiene la coherencia entre eventos).
  El encogimiento hacia la tasa base ya va dentro de cada distribución (escenarios.simular mezcla los escenarios
  del analista con el escenario neutral, peso k): p_final = p_agg; E3 y E4 limitadas a [0,05; 0,95].
  Los percentiles de la rentabilidad relativa a 12 meses son los de la mezcla de A y B (no la media de percentiles).
  Con un solo analista (modo rápido o degradado) p_agg = p del analista.
  E4: la métrica la fija la ruta; si A y B proponen umbrales distintos, se usa la media y la p(E4) de cada analista se
  recalcula contra ese umbral común con sus propios escenarios.
Veredicto (de los números; el checklist de gate.py puede convertirlo en no_analizable):
  no_atractiva  p_final(E1) ≤ 0,40, o DCF inverso sin raíz, o el precio implica un driver con z > 3
  atractiva     p_final(E1) ≥ 0,55, exceso anual esperado ≥ +5 pp, pérdida bajista ≤ 50 % y sin banderas graves
  neutral       todo lo demás
Si se cumple a la vez alguna condición de no_atractiva y todas las de atractiva, gana no_atractiva (criterio
conservador: la spec no fija la precedencia).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402

EVENTOS = ["E0", "E1", "E2", "E3", "E4"]
EVENTOS_LIMITADOS = ["E3", "E4"]
EPS = 1e-9


def percentiles_mezcla(cuantiles: list[list[float]], ps=(5, 50, 95)) -> list[float]:
    """Percentiles de una mezcla a partes iguales de distribuciones dadas por sus cuantiles 1-99."""
    niveles = np.arange(1, 100) / 100
    xs = np.unique(np.concatenate([np.asarray(q, dtype=float) for q in cuantiles]))
    F = np.mean([np.interp(xs, q, niveles, left=0.0, right=1.0) for q in cuantiles], axis=0)
    return [float(np.interp(p / 100, F, xs)) for p in ps]


def limitar(p: float, clip: list[float]) -> float:
    return min(max(p, clip[0]), clip[1])


def media(valores: list[float]) -> float:
    return sum(valores) / len(valores)


def p_e4(esc: dict, umbral: float) -> float:
    """p(E4) = suma de las p de los escenarios cuya métrica E4 alcanza el umbral."""
    return sum(e["p"] for e in esc["escenarios"] if e["valor_metrica_e4"] >= umbral)


def metrica_e4_comun(escenarios: dict[str, dict]) -> dict:
    """Métrica y umbral únicos de E4. La métrica la fija la ruta, así que debe coincidir; el umbral es la media de
    los valores base propuestos, de modo que las p(E4) de A y B se refieren al mismo evento."""
    ms = [e["metrica_e4"] for e in escenarios.values()]
    if len({m["metrica"] for m in ms}) > 1:
        raise ValueError("Los analistas proponen métricas E4 distintas: " + ", ".join(sorted({m["metrica"] for m in ms})))
    return {**ms[0], "valor_base": media([m["valor_base"] for m in ms]),
            "valores_propuestos": {n: e["metrica_e4"]["valor_base"] for n, e in escenarios.items()}}


def condiciones_veredicto(p_e1: float, exceso_pp: float, perdida_bajista: float, banderas: list[dict],
                          reverse_dcf: dict | None, cfg: dict) -> dict:
    """Evalúa por separado cada condición de A1. Devuelve {'no_atractiva': {...}, 'atractiva': {...}}."""
    v = cfg["veredicto"]
    pc = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
    resultados = (reverse_dcf or {}).get("resultados") or []
    z_altos = [f"{r['driver']} (z={r['z']:.1f})" for r in resultados
               if r.get("z") is not None and r["z"] > v["z_no_atractiva"]]
    sin_raiz = (reverse_dcf or {}).get("sin_raiz")
    graves = [b["bandera"] for b in banderas if b.get("nivel") in comun.NIVELES_GRAVES]
    return {
        "no_atractiva": {
            f"p_final(E1) ≤ {pc(v['no_atractiva_p_E1'])}": p_e1 <= v["no_atractiva_p_E1"] + EPS,
            "DCF inverso sin raíz": sin_raiz is True,
            f"el precio implica un driver con z > {v['z_no_atractiva']}": bool(z_altos),
        },
        "atractiva": {
            f"p_final(E1) ≥ {pc(v['atractiva_p_E1'])}": p_e1 >= v["atractiva_p_E1"] - EPS,
            f"exceso anual esperado ≥ {v['atractiva_exceso_pp']} pp": exceso_pp >= v["atractiva_exceso_pp"] - EPS,
            f"pérdida en el escenario bajista ≤ {v['atractiva_max_perdida_bear']:.0%}":
                perdida_bajista <= v["atractiva_max_perdida_bear"] + EPS,
            "sin banderas forenses graves": not graves,
        },
        "detalle": {"z_altos": z_altos, "banderas_graves": graves, "dcf_inverso_disponible": reverse_dcf is not None},
    }


def veredicto(condiciones: dict) -> tuple[str, str]:
    """(veredicto, motivo) a partir de las condiciones."""
    no = [c for c, ok in condiciones["no_atractiva"].items() if ok]
    si = condiciones["atractiva"]
    if no:
        return "no_atractiva", "Se cumple: " + "; ".join(no)
    if all(si.values()):
        return "atractiva", "Se cumplen las cuatro condiciones de atractiva"
    faltan = [c for c, ok in si.items() if not ok]
    return "neutral", "No se cumple: " + "; ".join(faltan)


def agregar(escenarios: dict[str, dict], modo: str, cfg: dict | None = None, banderas: list[dict] | None = None,
            reverse_dcf: dict | None = None) -> dict:
    """`escenarios`: {nombre_analista: salida de escenarios.ejecutar}. Los analistas esperados dependen del modo,
    salvo que se pase un solo analista cualquiera (p. ej. B1), que se trata como analista único."""
    cfg = cfg or comun.cargar_config()
    ag = cfg["agregacion"]
    nombres = sorted(escenarios)
    if not nombres:
        raise ValueError("No hay salidas de escenarios que agregar")
    if len(nombres) > 1 and nombres != comun.analistas_de_modo("completo"):
        raise ValueError(f"Con varios analistas se esperan A y B (hay {nombres})")
    if len(nombres) == 1 and modo == "completo" and nombres != ["B1"]:
        raise ValueError("El modo completo exige las salidas de A y de B")
    base = escenarios[nombres[0]]
    por_analista = {n: {e: escenarios[n]["probabilidades"][e] for e in EVENTOS} for n in nombres}
    metrica_e4 = metrica_e4_comun(escenarios)
    for n in nombres:  # p(E4) de cada analista frente al umbral común
        por_analista[n]["E4"] = p_e4(escenarios[n], metrica_e4["valor_base"])

    p_agg, p_final, dispersion = {}, {}, {}
    for e in EVENTOS:
        ps = [por_analista[n][e] for n in nombres]
        p_agg[e] = media(ps)
        dispersion[e] = abs(ps[0] - ps[1]) if len(ps) > 1 else None
        p_final[e] = limitar(p_agg[e], ag["clip_E3_E4"]) if e in EVENTOS_LIMITADOS else p_agg[e]

    exceso = media([escenarios[n]["exceso_anual_esperado_pp"] for n in nombres])
    perdida = max(escenarios[n]["perdida_escenario_bajista"] for n in nombres)
    if all(escenarios[n].get("rel_12m_cuantiles") for n in nombres):
        percentiles = percentiles_mezcla([escenarios[n]["rel_12m_cuantiles"] for n in nombres])
    else:  # salidas antiguas sin cuantiles
        percentiles = [media([escenarios[n]["rel_12m_p5_p50_p95"][i] for n in nombres]) for i in range(3)]
    neutrales = [(escenarios[n].get("probabilidades_neutral") or {}).get("E1") for n in nombres]
    calculada = all(x is not None for x in neutrales)
    tasa_base = media(neutrales) if calculada else ag["tasa_base_exceso"]
    banderas = banderas or []
    cond = condiciones_veredicto(p_final["E1"], exceso, perdida, banderas, reverse_dcf, cfg)
    ver, motivo = veredicto(cond)
    return {
        "ticker": base["ticker"], "fecha_analisis": base["fecha_analisis"], "modo": modo, "analistas": nombres,
        "metrica_e4": metrica_e4, "p_por_analista": por_analista, "p_agg": p_agg, "p_final": p_final,
        "dispersion": dispersion,
        "exceso_anual_esperado_pp": exceso, "perdida_escenario_bajista": perdida, "rel_12m_p5_p50_p95": percentiles,
        "tasa_base": tasa_base, "tasa_base_tipo": "calculada" if calculada else "heuristica", "k": ag["k"],
        "veredicto": ver, "motivo_veredicto": motivo, "condiciones": cond,
    }


# ---------------------------------------------------------------- E/S

def cargar_banderas(directorio: Path) -> list[dict]:
    """Banderas del forense: forense.json (agente, ya incluye las cuantitativas) o, si no existe, las de forense.py."""
    f = directorio / "forense.json"
    if f.exists():
        return comun.leer_json(f)["banderas"]
    m = directorio / "forense_metricas.json"
    return comun.leer_json(m)["banderas"] if m.exists() else []


def cargar_escenarios(directorio: Path, analistas: list[str]) -> dict[str, dict]:
    res = {}
    for n in analistas:
        f = directorio / f"escenarios_{n}.json"
        if not f.exists():
            raise FileNotFoundError(f"Falta {f.name} en {directorio}")
        res[n] = comun.leer_json(f)
    return res


def cargar_reverse_dcf(directorio: Path) -> dict | None:
    m = directorio / "motor_inicial.json"
    return comun.leer_json(m).get("reverse_dcf") if m.exists() else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Agrega las probabilidades y aplica las reglas del veredicto.")
    p.add_argument("--dir", required=True)
    p.add_argument("--modo", required=True, choices=comun.MODOS)
    p.add_argument("--analistas", nargs="+", help="Por defecto, los del modo (A B en completo, N en el resto)")
    p.add_argument("--salida")
    a = p.parse_args(argv)
    d = Path(a.dir)
    try:
        analistas = a.analistas or comun.analistas_de_modo(a.modo)
        res = agregar(cargar_escenarios(d, analistas), a.modo, banderas=cargar_banderas(d),
                      reverse_dcf=cargar_reverse_dcf(d))
    except (ValueError, FileNotFoundError, KeyError) as e:
        comun.salir_con_error(f"{type(e).__name__}: {e}")
    destino = Path(a.salida) if a.salida else d / "agregado.json"
    comun.escribir_json(destino, res)
    print(destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
