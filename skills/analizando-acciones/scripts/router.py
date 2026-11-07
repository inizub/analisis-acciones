"""Router sectorial: asigna la ruta de valoración de un ticker (A8) a partir del datapack.

Uso CLI:
    python router.py clasificar --datapack datapack.json [--salida router.json]
    python router.py confirmar --router router.json --propuesta RUTA --dato-ref CAMPO [--motivo TEXTO]

Salida de `clasificar`: {ruta, motivo, confianza, requiere_confirmacion, metrica_e4, candidatas[], evidencia{}}.

Prioridad de reglas (la primera que se cumple decide):
  fuera_de_alcance > banco_credito > biotech_precomercial > holding > crecimiento_perdidas > ciclica > general
Salvedad (noviembre de 2026): entre crecimiento_perdidas, ciclica y general, una candidata de fuerza alta gana a una de
fuerza media, y la prioridad solo desempata a igual fuerza. Ejemplo: NVDA o Freeport crecen algo por encima del p90 de su
clase (crecimiento_perdidas, media) pero son cíclicas claras (alta): antes se les asignaba crecimiento_perdidas.

Confianza:
  alta   regla clara y sin alternativas (o ruta general sin ninguna otra regla disparada y con datos completos)
  media  la ruta elegida se apoya en evidencia indirecta y no hay alternativas
  baja   hay otras rutas candidatas que podrían aplicar, o faltan datos para evaluar las reglas
Con confianza baja, el orquestador pide al analista que mantenga la ruta o proponga otra con un dato (`confirmar`).

Regla de confirmación (`confirmar`): la ruta propuesta por el analista solo se acepta si está entre las candidatas
disparadas por el código y se acompaña de un dato_ref no vacío; en cualquier otro caso se mantiene la del router.
`fuera_de_alcance` nunca se anula por propuesta del analista.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
import tasas_base  # noqa: E402
from datos import damodaran  # noqa: E402

PRIORIDAD = ["fuera_de_alcance", "banco_credito", "biotech_precomercial", "holding", "crecimiento_perdidas", "ciclica",
             "general"]
EXCLUYENTES = {"fuera_de_alcance", "banco_credito", "biotech_precomercial"}
RUTAS_DURAS = EXCLUYENTES | {"holding"}      # prioridad estricta; entre las demás, la fuerza manda sobre la prioridad
METRICA_E4 = {"general": "crecimiento_ingresos", "crecimiento_perdidas": "crecimiento_ingresos",
              "ciclica": "crecimiento_ingresos", "banco_credito": "roe", "biotech_precomercial": "hito_clinico",
              "holding": "crecimiento_ingresos", "fuera_de_alcance": None}


def _serie(dp: dict, campo: str) -> list[dict]:
    v = (dp.get("fundamentales") or {}).get(campo)
    return [] if not v or comun.es_desconocido(v) else v["serie"]


def _por_fecha(serie: list[dict]) -> dict[str, float]:
    return {p["fecha_dato"]: p["valor"] for p in serie}


def margenes(dp: dict) -> list[float]:
    """Margen operativo por ejercicio (solo ejercicios con ingresos > 0 y beneficio operativo conocido)."""
    ing, ebit = _por_fecha(_serie(dp, "ingresos")), _por_fecha(_serie(dp, "beneficio_operativo"))
    return [ebit[f] / ing[f] for f in sorted(ing) if f in ebit and ing[f] > 0]


def ebit_ultimos(dp: dict, n: int) -> list[float]:
    return [p["valor"] for p in _serie(dp, "beneficio_operativo")][-n:]


def segmentos_materiales(dp: dict, peso_min: float) -> list[dict]:
    segs = [s for s in dp.get("segmentos") or [] if s.get("tipo") == "negocio"]
    total = sum(s["ingresos"]["valor"] for s in segs if not comun.es_desconocido(s["ingresos"]))
    res = []
    for s in segs:
        if comun.es_desconocido(s["ingresos"]):
            continue
        peso = s["peso"]["valor"] if s.get("peso") and not comun.es_desconocido(s["peso"]) else (
            s["ingresos"]["valor"] / total if total else 0)
        if peso > peso_min:
            res.append({"nombre": s["nombre"], "peso": peso})
    return res


def _tiene_banca(dp: dict) -> bool:
    return all(_serie(dp, c) for c in ("prestamos", "depositos"))


def _crecimiento_vs_p90(dp: dict, cfg: dict, tabla) -> dict | None:
    """Crecimiento de ventas del emisor frente al p90 de su clase (5 años; 3 años si no hay 6 ejercicios)."""
    obs = tasas_base.observados(dp)
    v = tasas_base.ventas_musd(dp)
    clase = tasas_base.clase_tamano(v, cfg["tasas_base"]["clases_musd"])
    for metrica in ("crecimiento_ventas_5a", "crecimiento_ventas_3a"):
        valor = obs.get(metrica)
        if valor is None:
            continue
        fila, _ = tasas_base.buscar_fila(tabla, metrica, clase)
        if fila is None:
            continue
        return {"metrica": metrica, "valor": valor, "p90_clase": tasas_base.p90(fila), "clase": fila["clase_musd"]}
    return None


def clasificar(dp: dict, cfg: dict | None = None, tabla=None) -> dict:
    cfg = cfg or comun.cargar_config()
    r = cfg["router"]
    candidatas: list[dict] = []
    evidencia: dict[str, Any] = {}
    huecos: list[str] = []

    empresa = dp.get("empresa")
    if comun.es_desconocido(empresa):
        return {"ruta": "general", "motivo": "El emisor no está en EDGAR: sin SIC ni estados financieros para clasificar",
                "confianza": "baja", "requiere_confirmacion": True, "metrica_e4": METRICA_E4["general"],
                "candidatas": [], "evidencia": {"empresa": "desconocida"},
                "huecos": ["empresa"]}

    sic = empresa.get("sic")
    clas = damodaran.clasificar_sic(sic)
    evidencia["sic"] = {"sic": sic, "industria_damodaran": clas["industria_damodaran"], "ruta_sic": clas["ruta_sic"],
                        "ciclica_sic": clas["ciclica_sic"]}
    anios = empresa.get("anios_estados", 0)
    ing = _serie(dp, "ingresos")

    # fuera_de_alcance
    if clas["ruta_sic"] == "fuera_de_alcance":
        candidatas.append({"ruta": "fuera_de_alcance", "fuerza": "alta", "motivo": f"SIC {sic}: {clas['motivo']}"})
    if anios < r["anios_estados_min"]:
        candidatas.append({"ruta": "fuera_de_alcance", "fuerza": "alta",
                           "motivo": f"Solo {anios} años de estados financieros (mínimo {r['anios_estados_min']})"})
    if empresa.get("en_concurso") is True:
        candidatas.append({"ruta": "fuera_de_alcance", "fuerza": "alta", "motivo": "Empresa en concurso"})

    # banco_credito
    if clas["ruta_sic"] == "banco_credito":
        if _tiene_banca(dp):
            candidatas.append({"ruta": "banco_credito", "fuerza": "alta",
                               "motivo": f"SIC {sic} con préstamos y depósitos de clientes en el balance"})
        else:
            candidatas.append({"ruta": "banco_credito", "fuerza": "media",
                               "motivo": f"SIC {sic} (crédito/servicios financieros) sin datos de préstamos y depósitos"})

    # biotech
    if clas["ruta_sic"] == "biotech_candidata":
        ventas = tasas_base.ventas_musd(dp)
        if ventas is None and ing:
            huecos.append("ingresos en USD")
            candidatas.append({"ruta": "biotech_precomercial", "fuerza": "media",
                               "motivo": f"SIC {sic} (biotecnología); ingresos en {ing[-1].get('moneda')}, no comparables con el umbral"})
        elif ventas is not None and ventas < r["biotech_ingresos_max_musd"]:
            candidatas.append({"ruta": "biotech_precomercial", "fuerza": "alta",
                               "motivo": f"SIC {sic} con ingresos de {ventas:.1f} M$ (< {r['biotech_ingresos_max_musd']} M$)"})
        elif ventas is None:
            huecos.append("ingresos")
        evidencia["ingresos_musd"] = ventas

    # holding
    mats = segmentos_materiales(dp, r["holding_peso_min"])
    if empresa.get("holding_declarada") is True:
        candidatas.append({"ruta": "holding", "fuerza": "alta", "motivo": "Holding declarada por la empresa"})
    elif len(mats) >= r["holding_min_segmentos"]:
        candidatas.append({"ruta": "holding", "fuerza": "media",
                           "motivo": f"{len(mats)} segmentos de negocio con más del {r['holding_peso_min']:.0%} de los ingresos"})
    evidencia["segmentos_materiales"] = mats

    # crecimiento_perdidas
    ebits = ebit_ultimos(dp, r["ebit_ventana_anios"])
    if len(ebits) >= r["ebit_ventana_anios"]:
        neg = sum(1 for e in ebits if e < 0)
        evidencia["ebit_negativo_ultimos"] = f"{neg} de {len(ebits)}"
        if neg >= r["ebit_negativo_min_anios"]:
            candidatas.append({"ruta": "crecimiento_perdidas", "fuerza": "alta",
                               "motivo": f"EBIT negativo en {neg} de los últimos {len(ebits)} ejercicios"})
    elif not _serie(dp, "beneficio_operativo") and clas["ruta_sic"] != "banco_credito":
        huecos.append("beneficio_operativo")
    cr = _crecimiento_vs_p90(dp, cfg, tabla if tabla is not None else _tabla_o_none())
    if cr:
        evidencia["crecimiento"] = cr
        if cr["valor"] > cr["p90_clase"]:
            candidatas.append({"ruta": "crecimiento_perdidas", "fuerza": "media",
                               "motivo": f"{cr['metrica']} {cr['valor']:.1%} > p{r['crecimiento_percentil']} de su clase "
                                         f"({cr['p90_clase']:.1%})"})

    # ciclica
    m = margenes(dp)
    desv = statistics.stdev(m[-10:]) if len(m[-10:]) >= r["ciclica_min_anios"] else None
    evidencia["desv_margen_operativo"] = desv
    por_margen = desv is not None and desv > r["ciclica_desv_margen"]
    if clas["ciclica_sic"] and por_margen:
        candidatas.append({"ruta": "ciclica", "fuerza": "alta",
                           "motivo": f"Sector cíclico ({clas['industria_damodaran']}) y desv. típica del margen {desv:.1%}"})
    elif clas["ciclica_sic"]:
        candidatas.append({"ruta": "ciclica", "fuerza": "media",
                           "motivo": f"Sector cíclico ({clas['industria_damodaran']})" +
                                     ("" if desv is None else f"; desv. típica del margen {desv:.1%} bajo el umbral")})
    elif por_margen:
        candidatas.append({"ruta": "ciclica", "fuerza": "media",
                           "motivo": f"Desv. típica del margen operativo de {len(m[-10:])} años {desv:.1%} > "
                                     f"{r['ciclica_desv_margen']:.1%}"})

    if not ing:
        huecos.append("ingresos")

    # decisión
    orden = {ruta: i for i, ruta in enumerate(PRIORIDAD)}
    candidatas.sort(key=lambda c: (0, orden[c["ruta"]], 0, 0) if c["ruta"] in RUTAS_DURAS
                    else (1, 0, c["fuerza"] != "alta", orden[c["ruta"]]))
    if candidatas:
        elegida = candidatas[0]
        ruta, fuerza, motivo = elegida["ruta"], elegida["fuerza"], elegida["motivo"]
    else:
        ruta, fuerza, motivo = "general", "alta", "Ninguna regla específica se cumple: ruta por defecto"
    alternativas = sorted({c["ruta"] for c in candidatas if c["ruta"] != ruta})
    if ruta in EXCLUYENTES and fuerza == "alta":
        alternativas = []
    # Conflicto real: otra candidata de fuerza igual o mayor. Una alternativa más débil no obliga a consultar.
    rivales = [c for c in candidatas if c["ruta"] != ruta and (c["fuerza"] == "alta" or fuerza == "media")]
    if ruta in EXCLUYENTES and fuerza == "alta":
        rivales = []
    if huecos or rivales:
        confianza = "baja"
    elif fuerza == "media" or alternativas:
        confianza = "media"
    else:
        confianza = "alta"
    return {"ruta": ruta, "motivo": motivo, "confianza": confianza, "requiere_confirmacion": confianza == "baja",
            "metrica_e4": METRICA_E4[ruta], "alternativas": alternativas, "candidatas": candidatas,
            "evidencia": evidencia, "huecos": huecos}


def _tabla_o_none():
    try:
        return tasas_base.cargar_tabla()
    except comun.ErrorDatos:
        return ()


def confirmar(router: dict, propuesta: str | None, dato_ref: str | None = None, motivo: str | None = None) -> dict:
    """Decisión final de ruta tras la consulta al analista. Devuelve {ruta, cambio, motivo}."""
    original = router["ruta"]
    if not propuesta or propuesta == original:
        return {"ruta": original, "cambio": False, "motivo": "El analista mantiene la ruta del router"}
    if propuesta not in PRIORIDAD:
        return {"ruta": original, "cambio": False, "motivo": f"Ruta propuesta desconocida: {propuesta}"}
    if original == "fuera_de_alcance":
        return {"ruta": original, "cambio": False, "motivo": "fuera_de_alcance no se anula por propuesta del analista"}
    candidatas = {c["ruta"] for c in router.get("candidatas", [])}
    if propuesta != "general" and propuesta not in candidatas:
        return {"ruta": original, "cambio": False,
                "motivo": f"{propuesta} no está entre las rutas candidatas del código ({sorted(candidatas) or 'ninguna'})"}
    if not dato_ref or not dato_ref.strip():
        return {"ruta": original, "cambio": False, "motivo": "La propuesta no cita un dato_ref"}
    return {"ruta": propuesta, "cambio": True, "dato_ref": dato_ref, "motivo": motivo or "Cambio aceptado por regla",
            "metrica_e4": METRICA_E4[propuesta]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Router sectorial.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clasificar")
    c.add_argument("--datapack", required=True)
    c.add_argument("--salida")
    f = sub.add_parser("confirmar")
    f.add_argument("--router", required=True)
    f.add_argument("--propuesta")
    f.add_argument("--dato-ref")
    f.add_argument("--motivo")
    f.add_argument("--salida")
    a = p.parse_args(argv)
    try:
        if a.cmd == "clasificar":
            res = clasificar(comun.leer_json(a.datapack))
        else:
            res = confirmar(comun.leer_json(a.router), a.propuesta, a.dato_ref, a.motivo)
    except (comun.ErrorDatos, KeyError, FileNotFoundError) as e:
        comun.salir_con_error(f"{type(e).__name__}: {e}")
    if a.salida:
        comun.escribir_json(a.salida, res)
        print(a.salida)
    else:
        print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
