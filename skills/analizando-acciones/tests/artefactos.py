"""Ejecución sintética completa (todos los artefactos de RUN_DIR) para los tests de agregar, gate, diario y resolver."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import agregar
import comun
import gate
from conftest import DIR_FIXTURES
from dp_sintetico import crecer, datapack

MM = 1_000_000_000
EJEMPLOS = DIR_FIXTURES / "ejemplos"


def ejemplo(nombre: str) -> dict:
    return json.loads((EJEMPLOS / nombre).read_text(encoding="utf-8"))


def cifra(v, unidad="ratio", moneda=None, f="2026-11-05"):
    return comun.cifra(v, unidad, moneda, "https://x", f, "2026-11-06T00:00:00Z")


def dp_completo(ticker="XYZ", fecha="2026-11-06", antiguedad=1, sic=7372, **campos):
    ing = crecer(10 * MM, 0.05, 10)
    base = dict(ingresos=ing, beneficio_operativo=[i * 0.20 for i in ing], beneficio_neto=[i * 0.12 for i in ing],
                fco=[i * 0.14 for i in ing], acciones_diluidas=[1e9] * 10, deuda_total=[5 * MM] * 10,
                caja=[3 * MM] * 10, gasto_intereses=[2e8] * 10, patrimonio=[i * 0.6 for i in ing],
                activos_totales=[i * 1.5 for i in ing])
    base.update(campos)
    dp = datapack(sic=sic, **base)
    dp.update(ticker=ticker, fecha_analisis=fecha)
    dp["empresa"]["ticker"] = ticker
    dp["precios"] = {
        "ticker_precio": ticker, "moneda": "USD", "precio": cifra(100.0, "por_accion", "USD"),
        "precio_eur": cifra(89.3, "por_accion", "EUR"), "fx_eur": cifra(1.12, "USD_por_EUR"),
        "capitalizacion": cifra(1e11, "unidades", "USD"), "antiguedad_dias": antiguedad,
        "metricas_eur": {"momentum_12_1_rel": cifra(0.05), "vol_rel_3a": cifra(0.25), "vol_3a": cifra(0.30)}}
    dp["damodaran"] = {
        "erp_madura": cifra(0.0423, "ratio", "USD"),
        "prima_pais": {"pais": "United States", "crp": cifra(0.0035), "tasa_impuestos": cifra(0.25)},
        "sector": {"industria": "Software (System & Application)", "region": "us",
                   "valores": {"betas.beta_desapalancada": cifra(1.1, "veces"),
                               "betas.beta_desapalancada_caja": cifra(1.15, "veces"), "betas.beta": cifra(1.2, "veces"),
                               "ev_ebitda.ev_ebit": cifra(20.0, "veces"), "pbv.pbv": cifra(2.0, "veces"),
                               "pbv.roe": cifra(0.15), "wacc.coste_deuda": cifra(0.055),
                               "capex.ventas_capital": cifra(1.8, "veces")}},
        "tabla_ratings": {"fuente_url": "https://x", "fecha_obtencion": "2026-11-06T00:00:00Z", "filas": [
            {"cobertura_min": -100000.0, "rating": "D2/D", "diferencial": 0.19},
            {"cobertura_min": 1.5, "rating": "B2/B", "diferencial": 0.0321},
            {"cobertura_min": 3.0, "rating": "A3/A-", "diferencial": 0.0089},
            {"cobertura_min": 8.5, "rating": "Aaa/AAA", "diferencial": 0.004}]}}
    dp["verificacion_cruzada"] = {c: {"estado": "ok", "diferencia_rel": 0.0} for c in ("ingresos", "beneficio_neto", "acciones_diluidas")}
    dp["fuentes"] = [{"url": "https://x", "retrieved_at": "2026-11-06T00:00:00Z"}]
    dp["campos_desconocidos"] = []
    return dp


def router(ruta="general"):
    return {"ruta": ruta, "motivo": "test", "confianza": "alta", "requiere_confirmacion": False,
            "metrica_e4": "crecimiento_ingresos", "candidatas": [], "alternativas": [], "evidencia": {}, "huecos": []}


def analista(encuadre="A"):
    a = ejemplo("analista_A.json")
    a["encuadre"] = encuadre
    return a


def escenarios(nombre="A", e0=.50, e1=.60, e2=.55, e3=.10, e4=.75, exceso=6.0, perdida=.30, rel=(-.35, .02, .40),
               e4_base=.08, e4_valores=(.02, .08, .13), margen_bajista=.15):
    ps = (.25, .50, .25)
    vals = (70.0, 105.0, 140.0)
    return {
        "ticker": "XYZ", "fecha_analisis": "2026-11-06", "analista": nombre, "ruta": "general", "metodo": "dcf_fcff",
        "precio0": 100.0,
        "escenarios": [{"nombre": n, "p": p, "valor": v, "valor_sobre_p0": v / 100, "metodo": "dcf_fcff",
                        "drivers_usados": {"crecimiento_ingresos": [0.05], "margen_operativo": m},
                        "valor_metrica_e4": e}
                       for n, p, v, e, m in zip(("bajista", "base", "alcista"), ps, vals, e4_valores,
                                                (margen_bajista, .20, .25))],
        "probabilidades": {"E0": e0, "E1": e1, "E2": e2, "E3": e3, "E4": e4},
        "rel_12m_p5_p50_p95": list(rel), "exceso_anual_esperado_pp": exceso, "rentabilidad_anual_esperada": 0.1,
        "perdida_escenario_bajista": perdida,
        "metrica_e4": {"metrica": "crecimiento_ingresos", "valor_base": e4_base, "unidad": "ratio", "periodo": "FY2026"},
        "ajustes_aplicados": [], "parametros": {}}


def motor(sin_raiz=False, z=0.4):
    principal = {"driver": "crecimiento_ingresos", "valor": None if sin_raiz else 0.09, "percentil": None if sin_raiz else 65.0,
                 "z": None if sin_raiz else z, "sin_raiz": sin_raiz}
    return {"base": {"ruta": "general", "precio0": 100.0, "ingresos0": 10 * MM * 1.05 ** 9},
            "reverse_dcf": {"principal": principal, "resultados": [principal], "sin_raiz": sin_raiz}}


def sintesis():
    return {"ticker": "XYZ", "fecha_analisis": "2026-11-06",
            "razones": ["Crecimiento en línea con la tasa base de su clase", "Márgenes estables frente al sector",
                        "Valoración razonable según el DCF inverso"],
            "mejor_contraargumento": "El precio ya descuenta el escenario base y deja poco margen de seguridad.",
            "criterios_invalidacion": [{"dato": "Retención neta", "umbral": "< 100 %", "efecto": "p(E1) → < 0,40"},
                                       {"dato": "Margen operativo T1", "umbral": 0.18, "efecto": "p(E1) → < 0,42"}],
            "objeciones_verificadas": [{"id": "O1", "veredicto": "validada", "motivo": "El 14 % está en el percentil 80",
                                        "dato_ref": "fundamentales.ingresos"}]}


def forense(banderas=None):
    return {"ticker": "XYZ", "fecha_analisis": "2026-11-06", "banderas": banderas if banderas is not None else [
        {"bandera": "SBC/ingresos 2,9 %", "nivel": "informativa", "origen": "cuantitativa", "dato_ref": "fundamentales.sbc"}]}


def run(modo="completo", **ov) -> dict:
    """Artefactos de una ejecución sana. `ov` sobrescribe artefactos por nombre (p. ej. dp=..., forense=...)."""
    esperados = comun.analistas_de_modo(modo)
    art = {"dp": dp_completo(), "router": router(), "motor": motor(),
           "analistas": {n: analista(n) for n in esperados},
           "escenarios": {n: escenarios(n, e1=.75 if modo == "completo" else .75, exceso=8.0) for n in esperados},
           "forense": forense(), "sintesis": sintesis(), "objeciones": ejemplo("objeciones.json"),
           "ajustes": ejemplo("ajustes.json"),
           "baselines": {"B0": .45, "B1": .52, "B2": .55, "B3": .45, "B0_E4": .5, "B1_E4": .6},
           "forense_metricas": None}
    art.update(ov)
    banderas = art["forense"]["banderas"] if art["forense"] else []
    art["agregado"] = agregar.agregar(art["escenarios"], modo, banderas=banderas,
                                      reverse_dcf=(art["motor"] or {}).get("reverse_dcf"))
    art["gate"] = gate.evaluar(art["dp"], art["router"], modo, "final", art["motor"], art["analistas"],
                               art["escenarios"], art["forense"], art["sintesis"])
    return art


def escribir_run(d: Path, art: dict) -> Path:
    """Escribe los artefactos con los nombres estándar de RUN_DIR."""
    d.mkdir(parents=True, exist_ok=True)

    def w(nombre, obj):
        if obj is not None:
            (d / nombre).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    w("datapack.json", art["dp"])
    w("router.json", art["router"])
    w("motor_inicial.json", art["motor"])
    for n, a in art["analistas"].items():
        w(f"analista_{n}.json", a)
    for n, e in art["escenarios"].items():
        w(f"escenarios_{n}.json", e)
    for k, nombre in (("forense", "forense.json"), ("sintesis", "juez.json"), ("objeciones", "objeciones.json"),
                      ("ajustes", "ajustes.json"), ("baselines", "baselines.json"), ("agregado", "agregado.json"),
                      ("gate", "gate.json"), ("forense_metricas", "forense_metricas.json")):
        w(nombre, art.get(k))
    return d
