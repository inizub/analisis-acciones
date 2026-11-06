"""Diario de predicciones (A10): ensamblado del verdict.json, línea append-only con cadena de hashes y resumen.md.

Uso CLI:
    python diario.py cerrar --dir RUN_DIR --diario predicciones.jsonl --modo completo|rapido|degradado
        [--modelos '{"analista": "claude-sonnet-5-5", ...}']
    python diario.py verificar --diario predicciones.jsonl
    python diario.py resumen --verdict verdict.json

El diario es un JSONL append-only. Cada línea lleva `hash_prev` (SHA-256 de la línea anterior, sin el salto de línea).
Tipos de línea:
  predicción  el verdict.json completo (sin campo `tipo`). Sus preguntas quedan preregistradas.
  update      {"tipo": "update", "id": <id de la predicción abierta>, ..., "verdict": {...}}: una revisión del mismo
              ticker mientras su predicción sigue abierta. No es una pregunta nueva y no se puntúa aparte.
  resolución  {"tipo": "resolucion", "id", "qid", "estado": "resuelta"|"anulada", "resultado": 0|1|null, ...}
              (las escribe resolver.py; el campo `resolucion` de la predicción original queda vacío).
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
import validar  # noqa: E402

RUTA_DIARIO = Path("diario") / "predicciones.jsonl"
DIAS_ESPERA_E4 = 20


# ---------------------------------------------------------------- fechas y E/S del diario

def sumar_meses(f: date, meses: int) -> date:
    """f + meses, ajustando el día al último del mes si hace falta (31-ene + 1 mes = 28/29-feb)."""
    m = f.month - 1 + meses
    anio, mes = f.year + m // 12, m % 12 + 1
    return date(anio, mes, min(f.day, calendar.monthrange(anio, mes)[1]))


def serializar(registro: dict) -> str:
    return json.dumps(registro, ensure_ascii=False, separators=(",", ":"), default=comun._serializar)


def leer_lineas(ruta: Path) -> list[str]:
    if not Path(ruta).exists():
        return []
    return [l for l in Path(ruta).read_text(encoding="utf-8").split("\n") if l.strip()]


def leer_registros(ruta: Path) -> list[dict]:
    return [json.loads(l) for l in leer_lineas(ruta)]


def ultimo_hash(ruta: Path) -> str | None:
    lineas = leer_lineas(ruta)
    return comun.sha256_texto(lineas[-1]) if lineas else None


def verificar_cadena(ruta: Path) -> dict:
    """Comprueba que cada línea apunta al hash de la anterior. Devuelve {ok, lineas, error?}."""
    previo = None
    lineas = leer_lineas(ruta)
    for i, l in enumerate(lineas, start=1):
        try:
            hp = json.loads(l).get("hash_prev")
        except json.JSONDecodeError:
            return {"ok": False, "lineas": len(lineas), "error": f"línea {i}: JSON inválido"}
        if hp != previo:
            return {"ok": False, "lineas": len(lineas), "error": f"línea {i}: hash_prev {hp} ≠ esperado {previo}"}
        previo = comun.sha256_texto(l)
    return {"ok": True, "lineas": len(lineas)}


def anexar(ruta: Path, registro: dict) -> dict:
    """Añade una línea. Exige que `hash_prev` coincida con la última línea del diario (cadena intacta)."""
    ruta = Path(ruta)
    esperado = ultimo_hash(ruta)
    if registro.get("hash_prev") != esperado:
        raise ValueError(f"hash_prev del registro ({registro.get('hash_prev')}) ≠ último hash del diario ({esperado}): "
                         "el diario cambió mientras se ensamblaba")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write(serializar(registro) + "\n")
    return registro


def tipo(registro: dict) -> str:
    return registro.get("tipo", "prediccion")


def ids_usados(registros: list[dict]) -> set[str]:
    ids = set()
    for r in registros:
        if tipo(r) == "prediccion":
            ids.add(r["id"])
        elif tipo(r) == "update":
            ids.add(r["verdict"]["id"])
    return ids


def siguiente_id(registros: list[dict], ticker: str, fecha: str) -> str:
    usados = ids_usados(registros)
    for letra in "abcdefghijklmnopqrstuvwxyz":
        candidato = f"{ticker}-{fecha}-{letra}"
        if candidato not in usados:
            return candidato
    raise ValueError(f"Más de 26 análisis de {ticker} el {fecha}")


def resoluciones(registros: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["id"], r["qid"]): r for r in registros if tipo(r) == "resolucion"}


def prediccion_abierta(registros: list[dict], ticker: str, hoy: date) -> dict | None:
    """Última predicción del ticker con E1 aún sin vencer ni resolver."""
    res = resoluciones(registros)
    for r in reversed(registros):
        if tipo(r) != "prediccion" or r["ticker"] != ticker:
            continue
        e1 = next((q for q in r["preguntas"] if q["qid"] == "E1"), None)
        if e1 and e1["resolve_date"] and date.fromisoformat(e1["resolve_date"]) > hoy and (r["id"], "E1") not in res:
            return r
    return None


# ---------------------------------------------------------------- preguntas

def _ultimo_punto(dp: dict, campo: str) -> dict | None:
    v = (dp.get("fundamentales") or {}).get(campo)
    return v["serie"][-1] if v and not comun.es_desconocido(v) and v.get("serie") else None


def _texto_e4(m: dict) -> str:
    if m["metrica"] == "crecimiento_ingresos":
        return f"Crecimiento de ingresos {m['periodo']} ≥ {_pc(m['valor_base'], 1)}"
    if m["metrica"] == "roe":
        return f"ROE {m['periodo']} ≥ {_pc(m['valor_base'], 1)}"
    return f"Hito clínico {m['periodo']}: {m.get('descripcion') or m['valor_base']}"


def construir_preguntas(dp: dict, fecha: str, p_final: dict, metrica_e4: dict, cfg: dict) -> list[dict]:
    """E0-E4 con su fecha de resolución, fuente, cláusulas de anulación y los datos que necesita resolver.py."""
    ev, anular = cfg["eventos"], cfg["diario"]["anular_si"]
    f0 = date.fromisoformat(fecha)
    t = dp["ticker"]
    tp = (dp.get("precios") or {}).get("ticker_precio") or t
    bench = ev["benchmark"]
    preguntas = []
    for qid, meses in (("E0", ev["E0_meses"]), ("E1", ev["E1_meses"]), ("E2", ev["E2_meses"])):
        fin = sumar_meses(f0, meses)
        preguntas.append({
            "qid": qid, "texto": f"RT({t})-RT({bench}) en EUR > 0, {f0}→{fin}", "p": p_final[qid],
            "resolve_date": fin.isoformat(), "fuente_resolucion": "yfinance cierres ajustados en EUR",
            "anular_si": anular,
            "detalle": {"tipo": "exceso_rt", "ticker_precio": tp, "benchmark": bench, "fecha_ref": fecha, "meses": meses}})
    fin3 = sumar_meses(f0, ev["E1_meses"])
    preguntas.append({
        "qid": "E3", "texto": f"{t} cae ≥ {_pc(abs(ev['E3_caida']))} desde el cierre del {f0} antes de {fin3} (en EUR)",
        "p": p_final["E3"], "resolve_date": fin3.isoformat(),
        "fuente_resolucion": "yfinance cierres ajustados en EUR", "anular_si": anular,
        "detalle": {"tipo": "caida", "umbral": ev["E3_caida"], "ticker_precio": tp, "fecha_ref": fecha,
                    "meses": ev["E1_meses"]}})
    ult = _ultimo_punto(dp, "ingresos")
    fin_ej = sumar_meses(date.fromisoformat(ult["fecha_dato"]), 12) if ult else sumar_meses(f0, 12)
    ej = (ult["ejercicio"] + 1) if ult and ult.get("ejercicio") else fin_ej.year
    manual = metrica_e4["metrica"] == "hito_clinico"
    preguntas.append({
        "qid": "E4", "texto": _texto_e4(metrica_e4), "p": p_final["E4"], "resolve_date": None,
        "fuente_resolucion": "revisión manual del hito clínico" if manual else "EDGAR informe anual (10-K/20-F)",
        "anular_si": anular,
        "detalle": {"tipo": "metrica_fundamental", "metrica": metrica_e4["metrica"], "valor_base": metrica_e4["valor_base"],
                    "unidad": metrica_e4["unidad"], "periodo": metrica_e4["periodo"], "ejercicio_objetivo": ej,
                    "fin_ejercicio_esperado": fin_ej.isoformat(), "manual": manual}})
    return preguntas


# ---------------------------------------------------------------- ensamblado

def _snapshot_valor(c: Any, fuente: str = "yfinance") -> dict:
    if not c or comun.es_desconocido(c):
        return {"valor": None, "moneda": None, "fuente": None, "ts": None}
    return {"valor": c["valor"], "moneda": c.get("moneda"), "fuente": fuente, "ts": c["fecha_dato"]}


def _banderas(art: dict) -> list[dict]:
    fuente = art.get("forense") or art.get("forense_metricas") or {}
    return [{"bandera": b["bandera"], "nivel": b["nivel"]} for b in fuente.get("banderas", [])]


def _red_team(art: dict, modo: str) -> dict:
    obj = art.get("objeciones")
    if modo == "rapido" or not obj:   # en rápido no hay red team; en completo y degradado, sí
        return {"fuente": "ninguno", "objeciones": []}
    veredictos = {o["id"]: o["veredicto"] for o in (art.get("sintesis") or {}).get("objeciones_verificadas", [])}
    ajustes = {a["objecion_ref"]: a for a in (art.get("ajustes") or {}).get("ajustes", [])}
    items = []
    for o in obj["objeciones"]:
        aj = ajustes.get(o["id"])
        items.append({"objecion": o["objecion"], "dato_ref": o["dato_ref"],
                      "validada": veredictos.get(o["id"]) == "validada",
                      "ajuste": None if not aj else {k: aj[k] for k in ("analista", "driver", "escenario", "valor_anterior", "valor_nuevo")}})
    return {"fuente": obj["fuente"], "objeciones": items}


def _escenarios_valoracion(art: dict) -> list[dict]:
    res = []
    for n, esc in art["escenarios"].items():
        drivers = {e["nombre"]: e["drivers"] for e in (art.get("analistas", {}).get(n) or {}).get("escenarios", [])}
        codigo = esc.get("percentiles_codigo") or {}
        for e in esc["escenarios"]:
            # Percentiles calculados por código (tasas_base.py) si existen; si no, los que citó el analista.
            if e["nombre"] in codigo:
                pcts = {d: v["percentil"] for d, v in codigo[e["nombre"]].items()}
            else:
                pcts = {d: v.get("percentil_tasa_base") for d, v in drivers.get(e["nombre"], {}).items()}
            res.append({"nombre": e["nombre"], "analista": n, "p": e["p"], "valor": e["valor"],
                        "drivers": e["drivers_usados"], "percentiles_tasa_base": pcts})
    return res


def _valoracion(art: dict) -> dict:
    ag = art["agregado"]
    base = next(iter(art["escenarios"].values()))
    rd = ((art.get("motor") or {}).get("reverse_dcf") or {}).get("principal") or {}
    return {"metodo": base["metodo"], "escenarios": _escenarios_valoracion(art),
            "reverse_dcf": {"driver": rd.get("driver"), "valor": rd.get("valor"), "percentil": rd.get("percentil"),
                            "sin_raiz": bool(rd.get("sin_raiz", True))},
            "exceso_anual_esperado_pp": ag["exceso_anual_esperado_pp"], "rel_12m_p5_p50_p95": ag["rel_12m_p5_p50_p95"],
            "perdida_escenario_bajista": ag["perdida_escenario_bajista"]}


def _agregacion(art: dict, cfg: dict) -> dict:
    ag = art.get("agregado")
    if not ag:
        a = cfg["agregacion"]
        return {"tasa_base": a["tasa_base_exceso"], "tasa_base_tipo": "heuristica", "k": a["k"]}
    res = {f"p_{n}": ag["p_por_analista"][n] for n in ag["analistas"]}
    res.update(p_agg=ag["p_agg"], p_final=ag["p_final"], dispersion=ag["dispersion"], tasa_base=ag["tasa_base"],
               tasa_base_tipo=ag["tasa_base_tipo"], k=ag["k"])
    if "p_final_sin_ajustes" in ag:  # para medir cuánto mueven las objeciones validadas (regla de 18 meses, A12)
        res["p_final_sin_ajustes"] = ag["p_final_sin_ajustes"]
    return res


def ensamblar_verdict(art: dict, modo: str, modelos: dict | None, id_: str, hash_prev: str | None,
                      created_at: str, cfg: dict | None = None) -> dict:
    """verdict.json a partir de los artefactos de la ejecución. `art` usa las claves de gate.cargar más
    agregado, gate, objeciones, ajustes, baselines y forense_metricas (las ausentes pueden ser None)."""
    cfg = cfg or comun.cargar_config()
    dp, gate, ag = art["dp"], art["gate"], art.get("agregado")
    ver = "no_analizable" if (not gate["pasa"] or ag is None) else ag["veredicto"]
    motivo = None
    if ver == "no_analizable":
        motivo = "; ".join(gate["fallos"]) if gate["fallos"] else "No hay agregado de probabilidades"
    sint = art.get("sintesis") or {}
    default_modelos = {"datos": cfg["modelos"]["datos"], "analista": cfg["modelos"]["analista"],
                       "forense": cfg["modelos"]["forense"] if modo == "completo" else None,
                       "red_team": cfg["modelos"]["red_team_fallback"] if modo == "completo" else None,
                       "juez": cfg["modelos"]["juez"] if modo == "completo" else None}
    precios = dp.get("precios") if not comun.es_desconocido(dp.get("precios")) else None
    bl = art.get("baselines") or {}
    verdict = {
        "id": id_, "created_at": created_at, "hash_prev": hash_prev,
        "skill": {"version": comun.version_plugin(), "hash_prompts": comun.hash_prompts(),
                  "hash_config": comun.hash_config(), "modo": modo},
        "modelos": {**default_modelos, **(modelos or {})},
        "ticker": dp["ticker"], "ruta_sectorial": art["router"]["ruta"],
        # Sin independencia en modo degradado o si la auditoría de la traza encontró lecturas cruzadas.
        "independencia": modo != "degradado" and not (art.get("auditoria") or {}).get("lecturas_cruzadas"),
        "input_snapshot": {
            "precio": _snapshot_valor(precios and precios.get("precio")),
            "fx_eur": _snapshot_valor(precios and precios.get("fx_eur")),
            "fuentes": [{"url": f["url"], "retrieved_at": f.get("retrieved_at"), "published_at": f.get("published_at")}
                        for f in dp.get("fuentes", [])],
            "campos_desconocidos": dp.get("campos_desconocidos", [])},
        "veredicto": ver, "motivo_no_analizable": motivo,
        "valoracion": None if ver == "no_analizable" else _valoracion(art),
        "agregacion": _agregacion(art, cfg),
        "preguntas": [] if ver == "no_analizable" else construir_preguntas(
            dp, dp["fecha_analisis"], ag["p_final"], ag["metrica_e4"], cfg),
        "razones": sint.get("razones", []), "mejor_contraargumento": sint.get("mejor_contraargumento"),
        "criterios_invalidacion": sint.get("criterios_invalidacion", []),
        "red_team": _red_team(art, modo), "banderas_forenses": _banderas(art),
        "checklist": {"pasa": gate["pasa"], "fallos": gate["fallos"], "avisos": gate.get("avisos", [])},
        "baselines": {"B0": bl.get("B0", cfg["agregacion"]["tasa_base_exceso"]), "B1": bl.get("B1"), "B2": bl.get("B2"),
                      "B3": bl.get("B3"), "B0_E4": bl.get("B0_E4", cfg["baselines"]["b0_e4"]),
                      "B1_E4": bl.get("B1_E4")},
        "updates": [], "resolucion": {},
    }
    if ag is not None and ver != "no_analizable":
        verdict["motivo_veredicto"] = ag["motivo_veredicto"]
    return verdict


# ---------------------------------------------------------------- resumen

def _pc(x: float | None, dec: int = 0) -> str:
    return "n/d" if x is None else f"{100 * x:.{dec}f} %".replace(".", ",")


def _fmt_driver(driver: str, valor: float) -> str:
    if driver in ("crecimiento_ingresos", "margen_operativo", "roe"):
        return _pc(valor, 1)
    if driver == "anios_ventaja":
        return f"{valor:.0f} años"
    return f"{valor:.2f}×".replace(".", ",")


def resumen_md(v: dict) -> str:
    L = [f"# {v['ticker']}: {v['veredicto'].replace('_', ' ')}", "",
         f"`{v['id']}` · modo {v['skill']['modo']} · ruta {v['ruta_sectorial']}"
         + (f" · método {v['valoracion']['metodo']}" if v.get("valoracion") else ""), "",
         "> Herramienta de análisis y estudio personal. No es asesoramiento financiero.", ""]
    if v["veredicto"] == "no_analizable":
        L += ["## Por qué no se puede analizar", ""] + [f"- {f}" for f in (v["checklist"]["fallos"] or [v["motivo_no_analizable"]])]
    else:
        pr = {q["qid"]: q for q in v["preguntas"]}
        val = v["valoracion"]
        L += [v.get("motivo_veredicto", ""), "", "## Probabilidades frente a VWCE (EUR, con dividendos)", "",
              "| Evento | p |", "|---|---|"]
        for qid, nombre in (("E0", "bate a VWCE a 6 meses"), ("E1", "bate a VWCE a 12 meses (principal)"),
                            ("E2", "bate a VWCE a 36 meses"), ("E3", "cae ≥ 30 % en 12 meses"), ("E4", pr["E4"]["texto"])):
            L.append(f"| {qid} {nombre} | {_pc(pr[qid]['p'])} |")
        p5, p50, p95 = val["rel_12m_p5_p50_p95"]
        rd = val["reverse_dcf"]
        L += ["", f"- Exceso de rentabilidad anual esperado: {val['exceso_anual_esperado_pp']:+.1f} pp".replace(".", ","),
              f"- Retorno relativo a 12 meses (p5 / p50 / p95): {_pc(p5)} / {_pc(p50)} / {_pc(p95)}",
              f"- Pérdida en el escenario bajista: {_pc(val['perdida_escenario_bajista'])}",
              "- DCF inverso: " + ("sin solución en rangos razonables" if rd["sin_raiz"] else
                                   f"{rd['driver'].replace('_', ' ')} implícito en el precio = {_fmt_driver(rd['driver'], rd['valor'])}"
                                   + (f" (percentil {rd['percentil']:.0f} de su clase)" if rd.get("percentil") is not None else ""))]
        if v["razones"]:
            L += ["", "## Razones", ""] + [f"{i}. {r}" for i, r in enumerate(v["razones"], 1)]
        if v["mejor_contraargumento"]:
            L += ["", "## Mejor contraargumento", "", v["mejor_contraargumento"]]
        if v["criterios_invalidacion"]:
            L += ["", "## Qué invalidaría la tesis", ""] + [
                f"- {c['dato']} {c['umbral']}: {c['efecto']}" for c in v["criterios_invalidacion"]]
    if v["banderas_forenses"]:
        L += ["", "## Banderas forenses", ""] + [f"- ({b['nivel']}) {b['bandera']}" for b in v["banderas_forenses"]]
    avisos = v["checklist"].get("avisos") or []
    if avisos:
        L += ["", "## Avisos del checklist", ""] + [f"- {a}" for a in avisos]
    bl = v["baselines"]
    L += ["", f"Baselines (p de batir a VWCE): B0 {bl['B0']:.2f} · B1 {bl['B1'] if bl['B1'] is None else round(bl['B1'], 2)} · "
              f"B2 {bl['B2']} · B3 {bl['B3']}", ""]
    return "\n".join(L).replace("None", "n/d")


# ---------------------------------------------------------------- cierre de una ejecución

def cargar_artefactos(d: Path, modo: str) -> dict:
    import gate as g

    art = g.cargar(d, modo)
    art["gate"] = g._leer(d, "gate.json", "gate_previo.json")
    art["agregado"] = g._leer(d, "agregado.json")
    art["objeciones"] = g._leer(d, "objeciones.json")
    art["ajustes"] = g._leer(d, "ajustes.json")
    art["baselines"] = g._leer(d, "baselines.json")
    art["forense_metricas"] = g._leer(d, "forense_metricas.json")
    art["auditoria"] = g._leer(d, "auditoria_traza.json")
    return art


def cerrar(d: Path, diario: Path, modo: str, modelos: dict | None = None, ahora: datetime | None = None,
           cfg: dict | None = None) -> dict:
    """Ensambla verdict.json, lo valida, añade la línea al diario y escribe resumen.md. Nada se escribe si no valida."""
    cfg = cfg or comun.cargar_config()
    art = cargar_artefactos(d, modo)
    for k in ("dp", "router", "gate"):
        if art[k] is None:
            raise FileNotFoundError(f"Falta el artefacto '{k}' en {d} (datapack.json, router.json, gate.json)")
    ahora = ahora or datetime.now(timezone.utc)
    registros = leer_registros(diario)
    fecha = art["dp"]["fecha_analisis"]
    verdict = ensamblar_verdict(art, modo, modelos, siguiente_id(registros, art["dp"]["ticker"], fecha),
                                ultimo_hash(diario), ahora.replace(microsecond=0).isoformat().replace("+00:00", "Z"), cfg)
    errores = validar.validar_objeto(verdict, "verdict")
    if errores:
        raise ValueError("verdict.json no valida: " + "; ".join(errores[:8]))
    abierta = prediccion_abierta(registros, verdict["ticker"], date.fromisoformat(fecha)) \
        if verdict["veredicto"] != "no_analizable" else None
    comun.escribir_json(d / "verdict.json", verdict)
    if abierta:
        anexar(diario, {"tipo": "update", "id": abierta["id"], "created_at": verdict["created_at"],
                        "hash_prev": verdict["hash_prev"], "verdict": verdict})
    else:
        anexar(diario, verdict)
    (d / "resumen.md").write_text(resumen_md(verdict), encoding="utf-8")
    return {"id": verdict["id"], "veredicto": verdict["veredicto"], "update_de": abierta["id"] if abierta else None,
            "verdict": str(d / "verdict.json"), "resumen": str(d / "resumen.md"), "diario": str(diario)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diario de predicciones.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cerrar")
    c.add_argument("--dir", required=True)
    c.add_argument("--diario", required=True)
    c.add_argument("--modo", required=True, choices=comun.MODOS)
    c.add_argument("--modelos", help="JSON con los identificadores de modelo usados")
    v = sub.add_parser("verificar")
    v.add_argument("--diario", required=True)
    r = sub.add_parser("resumen")
    r.add_argument("--verdict", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "cerrar":
            res = cerrar(Path(a.dir), Path(a.diario), a.modo, json.loads(a.modelos) if a.modelos else None)
        elif a.cmd == "verificar":
            res = verificar_cadena(Path(a.diario))
            print(comun.volcar_json(res))
            return 0 if res["ok"] else 1
        else:
            print(resumen_md(comun.leer_json(a.verdict)))
            return 0
    except (ValueError, FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        comun.salir_con_error(f"{type(e).__name__}: {e}")
    print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
