"""Control de una ejecución de /analizar: los pasos deterministas del flujo (A3) en pocos comandos.

Uso CLI (desde SKILL.md, a través de py.sh):
    ejecucion.py iniciar  --entrada "$ARGUMENTS" --journal DIR [--fecha AAAA-MM-DD]
    ejecucion.py datos    --dir RUN_DIR
    ejecucion.py fusionar --dir RUN_DIR [--comprobar]
    ejecucion.py codigo   --dir RUN_DIR --modo M
    ejecucion.py fase     --fase datos|ciega|red_team|juez|cierre
    ejecucion.py congelar --dir RUN_DIR
    ejecucion.py escenarios --dir RUN_DIR --modo M
    ejecucion.py cerrar   --dir RUN_DIR --modo M --journal DIR [--modelos JSON]
    ejecucion.py terminar

  iniciar     extrae el ticker y el modo (el resto del texto se ignora y nunca se pasa a los subagentes), crea
              runs/<TICKER>/<fecha>/ y registra la ejecución activa para los hooks.
  datos       régimen macro (semanal) y datapack_base.json; dice qué campos debe buscar el agente datos.
  fusionar    añade datos_agente.json (lo que encontró el agente datos) a datapack_base.json → datapack.json.
              EDGAR prevalece: el agente solo rellena campos desconocidos o desactualizados.
  codigo      tasas base (insertadas al principio del datapack), router, sensibilidades, forense.py,
              checklist previo y motor_inicial.json.
  congelar    SHA-256 de las salidas de la fase ciega (hashes.json).
  escenarios  escenarios.py para cada analista (con ajustes.json si existe) y percentiles de sus drivers.
  cerrar      comprueba los hashes, agrega, baselines, checklist final, diario y resumen.md.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402

RE_TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,14}$")
MODOS_ENTRADA = {"rapido": "rapido", "rápido": "rapido", "completo": "completo"}
ARCHIVO_ACTIVA = "ejecucion_activa.json"
CONGELADOS = re.compile(r"^(analista_(A|B|N|B1)|forense)\.json$")
CAMPOS_EMPRESA_AGENTE = {"ratio_adr", "holding_declarada", "en_concurso"}
SECCIONES_AGENTE = ("trimestrales", "banca", "segmentos", "guidance", "hechos_recientes", "cambios",
                    "extractos_filings", "pipeline", "deuda", "holding_coste_anual")


# ---------------------------------------------------------------- entrada y ejecución activa

def parsear_entrada(texto: str) -> dict:
    """Primer token = ticker; si el segundo es 'rapido'/'completo', es el modo. Todo lo demás se ignora."""
    tokens = (texto or "").split()
    if not tokens or not RE_TICKER.match(tokens[0]):
        raise ValueError(f"No se reconoce un ticker al principio de: {texto!r}")
    modo = "completo"
    resto = tokens[1:]
    if resto and resto[0].lower() in MODOS_ENTRADA:
        modo = MODOS_ENTRADA[resto[0].lower()]
        resto = resto[1:]
    return {"ticker": tokens[0].upper(), "modo": modo, "ignorado": len(resto) > 0}


def ruta_activa() -> Path:
    return comun.dir_datos_plugin() / ARCHIVO_ACTIVA


def leer_activa() -> dict | None:
    r = ruta_activa()
    return comun.leer_json(r) if r.exists() else None


def directorio_ejecucion(journal: Path, ticker: str, fecha: str) -> Path:
    """runs/<TICKER>/<fecha>/; si ya hay una ejecución cerrada ese día, <fecha>-b, -c..."""
    base = journal / "runs" / ticker
    for sufijo in [""] + [f"-{c}" for c in "bcdefghijklmnopqrstuvwxyz"]:
        d = base / f"{fecha}{sufijo}"
        if not (d / "verdict.json").exists():
            return d
    raise ValueError(f"Demasiadas ejecuciones de {ticker} el {fecha}")


def resolver_journal(journal: str | Path) -> tuple[Path, str | None]:
    """journal_dir configurado o, si llega vacío o sin sustituir (`${user_config...}`), ~/analisis-acciones/journal."""
    texto = str(journal or "").strip()
    if not texto or "${" in texto or texto.startswith("$"):
        defecto = Path.home() / "analisis-acciones" / "journal"
        return defecto, f"journal_dir no está configurado: se usa {defecto}"
    return Path(texto), None


def iniciar(entrada: str, journal: Path | str, fecha: str | None = None) -> dict:
    journal, aviso = resolver_journal(journal)
    e = parsear_entrada(entrada)
    fecha = fecha or date.today().isoformat()
    d = directorio_ejecucion(journal, e["ticker"], fecha)
    d.mkdir(parents=True, exist_ok=True)
    activa = {"run_dir": str(d.resolve()), "ticker": e["ticker"], "modo": e["modo"], "fecha": fecha,
              "journal": str(journal.resolve()), "fase": "datos", "inicio": comun.ahora_iso(), "bloqueos_stop": {}}
    comun.escribir_json(ruta_activa(), activa)
    return {**activa, "texto_ignorado": e["ignorado"], **({"aviso_journal": aviso} if aviso else {})}


def cambiar_fase(fase: str) -> dict:
    a = leer_activa()
    if a is None:
        raise ValueError("No hay ninguna ejecución activa")
    a["fase"] = fase
    comun.escribir_json(ruta_activa(), a)
    return a


def terminar() -> dict:
    r = ruta_activa()
    a = leer_activa()
    r.unlink(missing_ok=True)
    return {"terminada": a["run_dir"] if a else None}


# ---------------------------------------------------------------- datos

def _router_y_criticos(dp: dict) -> tuple[dict, list[str]]:
    import gate
    import router

    r = router.clasificar(dp)
    return r, gate.faltan_criticos(dp, r["ruta"], comun.cargar_config())


def preparar_macro(d: Path, journal: Path) -> dict:
    """Régimen macro semanal compartido (journal/macro/) copiado al directorio de la ejecución."""
    import macro

    cfg = comun.cargar_config()
    maestro = journal / "macro" / "macro_regime.json"
    if not macro.vigente(maestro, cfg["macro"]["max_dias_regimen"]):
        comun.escribir_json(maestro, macro.regimen(cfg=cfg))
    shutil.copyfile(maestro, d / "macro_regime.json")
    return comun.leer_json(d / "macro_regime.json")


def trimestres_pendientes(dp: dict, cfg: dict | None = None) -> bool:
    """¿El último ejercicio anual de ingresos es antiguo y el datapack no trae trimestres posteriores?

    EDGAR (companyfacts anual) no trae los trimestres: sin ellos la base de ingresos sería la del último ejercicio."""
    from datetime import date

    from motor import inicial

    cfg = cfg or comun.cargar_config()
    anual = inicial._serie(dp, "ingresos")
    if not anual or not dp.get("fecha_analisis"):
        return False
    fin = date.fromisoformat(anual[-1]["fecha_dato"][:10])
    if (date.fromisoformat(dp["fecha_analisis"][:10]) - fin).days <= cfg["datos"]["base_max_meses"] * 30.4:
        return False
    t = (dp.get("trimestrales") or {}).get("ingresos") or {}
    trim = [] if comun.es_desconocido(t) else (t.get("serie") or [])
    return not any((date.fromisoformat(q["fecha_dato"][:10]) - fin).days > inicial.TOL_DIAS for q in trim)


def datos(d: Path, clientes: dict | None = None) -> dict:
    from datos import datapack_base
    import validar

    a = leer_activa() or {}
    ticker = a.get("ticker") or d.parent.name
    fecha = a.get("fecha") or d.name[:10]
    journal = Path(a["journal"]) if a.get("journal") else d.parents[2]
    reg = preparar_macro(d, journal) if not (clientes or {}).get("sin_macro") else {}
    dp, serie = datapack_base.construir(ticker, fecha=fecha, clientes=clientes)
    errores = validar.validar_objeto(dp, "datapack")
    if errores:
        raise ValueError("datapack_base no valida: " + "; ".join(errores[:5]))
    comun.escribir_json(d / "datapack_base.json", dp)
    if serie:
        comun.escribir_json(d / "precios_serie.json", serie)
    r, faltan = _router_y_criticos(dp)
    inexistente = comun.es_desconocido(dp["empresa"]) and comun.es_desconocido(dp["precios"])
    modo = a.get("modo", "completo")
    fuentes_caidas = sorted({c["campo"] for c in dp["campos_desconocidos"] if c.get("causa") == "source_down"})
    # Fuera de alcance por SIC o por historia insuficiente: no merece la pena buscar más datos.
    fuera = r["ruta"] == "fuera_de_alcance"
    pendientes = (not inexistente) and (not fuera) and trimestres_pendientes(dp)
    return {"ticker": ticker, "ruta_provisional": r["ruta"], "campos_criticos_faltan": faltan,
            "campos_desconocidos": dp["campos_desconocidos"], "ticker_inexistente": inexistente,
            "fuentes_caidas": fuentes_caidas,
            "fuera_de_alcance": fuera, "trimestrales_pendientes": pendientes,
            "necesita_agente_datos": (not inexistente) and (not fuera)
            and (modo == "completo" or bool(faltan) or pendientes),
            "macro": {k: reg.get(k, {}).get("etiqueta") for k in ("tipos", "credito", "curva")} if reg else None}


def _como_serie(v: dict) -> dict:
    """Una cifra suelta se convierte en serie de un punto; una serie o un desconocido se dejan igual."""
    if comun.es_desconocido(v) or "serie" in v:
        return v
    return {"concepto": v.get("concepto", "agente datos"), "serie": [v]}


def fusionar_datapack(base: dict, agente: dict) -> tuple[dict, list[str]]:
    """Datapack final y lista de avisos. Nunca sobrescribe una cifra de EDGAR vigente."""
    dp = copy.deepcopy(base)
    avisos: list[str] = []
    fund = dp.setdefault("fundamentales", {})
    for campo, v in (agente.get("fundamentales") or {}).items():
        actual = fund.get(campo)
        if actual and not comun.es_desconocido(actual) and not actual.get("desactualizada"):
            avisos.append(f"fundamentales.{campo}: EDGAR ya tiene el dato; se ignora el del agente")
            continue
        fund[campo] = _como_serie(v)
    for s in SECCIONES_AGENTE:
        if s in agente:
            dp[s] = agente[s]
    if isinstance(dp.get("empresa"), dict):
        for k, v in (agente.get("empresa") or {}).items():
            if k in CAMPOS_EMPRESA_AGENTE:
                dp["empresa"][k] = v
            else:
                avisos.append(f"empresa.{k}: el agente no puede cambiar este campo")
    rellenos = {c for c, v in fund.items() if not comun.es_desconocido(v)}
    desconocidos = [x for x in dp.get("campos_desconocidos", []) if x["campo"] not in rellenos]
    for x in agente.get("no_encontrados", []):
        if not any(y["campo"] == x["campo"] for y in desconocidos):
            desconocidos.append({"campo": x["campo"], "causa": x["causa"]})
    dp["campos_desconocidos"] = desconocidos
    dp["fuentes"] = dp.get("fuentes", []) + [f for f in agente.get("fuentes", []) if isinstance(f, dict) and f.get("url")]
    return dp, avisos


def fusionar(d: Path, comprobar: bool = False) -> dict:
    import validar

    base = comun.leer_json(d / "datapack_base.json")
    ruta_ag = d / "datos_agente.json"
    agente = comun.leer_json(ruta_ag) if ruta_ag.exists() else {}
    dp, avisos = fusionar_datapack(base, agente)
    errores = validar.validar_objeto(dp, "datapack")
    if errores:
        return {"valido": False, "errores": errores[:15], "avisos": avisos}
    if not comprobar:
        comun.escribir_json(d / "datapack.json", dp)
    r, faltan = _router_y_criticos(dp)
    return {"valido": True, "avisos": avisos, "campos_criticos_faltan": faltan, "ruta_provisional": r["ruta"]}


# ---------------------------------------------------------------- fase de código

def insertar_tasas_base(dp: dict, tb: dict) -> dict:
    """El datapack presenta primero las tasas base."""
    return {"tasas_base": tb, **{k: v for k, v in dp.items() if k != "tasas_base"}}


def codigo(d: Path, modo: str, motor_fx: Any = None) -> dict:
    import forense
    import gate
    import macro
    import router
    import tasas_base
    from motor import inicial

    ruta_dp = d / "datapack.json"
    if not ruta_dp.exists():
        shutil.copyfile(d / "datapack_base.json", ruta_dp)
    dp = comun.leer_json(ruta_dp)
    dp = insertar_tasas_base(dp, tasas_base.construir(dp))
    comun.escribir_json(ruta_dp, dp)
    previo_rt = comun.leer_json(d / "router.json") if (d / "router.json").exists() else None
    if previo_rt and previo_rt.get("confirmada"):
        rt = previo_rt                       # ruta ya confirmada tras consultar al analista: no se reclasifica
    else:
        rt = router.clasificar(dp)
        comun.escribir_json(d / "router.json", rt)
    sens: Any = None
    if (d / "precios_serie.json").exists():
        try:
            sens = macro.sensibilidades(dp, comun.leer_json(d / "precios_serie.json"))
            comun.escribir_json(d / "sensibilidades.json", sens)
        except (comun.ErrorDatos, KeyError, ValueError) as e:
            sens = {"error": str(e)}
    fm = forense.calcular(dp, rt["ruta"])
    comun.escribir_json(d / "forense_metricas.json", fm)
    previo = gate.evaluar(dp, rt, modo, "previo")
    comun.escribir_json(d / "gate_previo.json", previo)
    res: dict[str, Any] = {"ruta": rt["ruta"], "confianza": rt["confianza"], "requiere_confirmacion": rt["requiere_confirmacion"],
                           "alternativas": rt.get("alternativas", []), "motivo_ruta": rt["motivo"],
                           "gate_previo": {"pasa": previo["pasa"], "fallos": previo["fallos"]},
                           "banderas_forenses_graves": [b["bandera"] for b in fm["banderas"] if b.get("nivel") == "grave"],
                           "banderas_forenses_informativas": [b["bandera"] for b in fm["banderas"] if b.get("nivel") == "informativa"]}
    if not previo["pasa"]:
        res["siguiente"] = "cerrar (no_analizable): el checklist previo falla"
        return res
    try:
        mi = inicial.construir(dp, rt, comun.leer_json(d / "macro_regime.json"), fx_eur=motor_fx)
    except Exception as e:  # cualquier fallo del motor queda registrado y el checklist lo convierte en no_analizable
        comun.escribir_json(d / "motor_inicial.json", {"error": f"{type(e).__name__}: {e}"})
        res.update(error_motor=str(e), siguiente="cerrar (no_analizable): el motor no pudo construir la base")
        return res
    comun.escribir_json(d / "motor_inicial.json", mi)
    res.update(valor_mecanico=mi["caso_mecanico"]["valor"], precio=mi["base"]["precio0"],
               reverse_dcf=mi["reverse_dcf"]["principal"], avisos_motor=mi["supuestos"]["avisos"],
               siguiente="fase ciega")
    return res


def confirmar_ruta(d: Path, propuesta: str | None, dato_ref: str | None, motivo: str | None) -> dict:
    """Aplica la regla de router.confirmar y deja la ruta marcada como confirmada. Si cambia, hay que volver a
    ejecutar `codigo` (forense.py, checklist previo y motor dependen de la ruta)."""
    import router

    rt = comun.leer_json(d / "router.json")
    if propuesta is None and (d / "confirmacion_ruta.json").exists():
        c = comun.leer_json(d / "confirmacion_ruta.json")
        if not c.get("mantiene"):
            propuesta, dato_ref, motivo = c.get("ruta_propuesta"), c.get("dato_ref"), c.get("motivo")
    dec = router.confirmar(rt, propuesta, dato_ref, motivo)
    if dec["cambio"]:
        rt.update(ruta=dec["ruta"], motivo=f"{rt['motivo']} | cambio del analista: {dec['motivo']} ({dec['dato_ref']})",
                  metrica_e4=dec["metrica_e4"], confianza="media")
    rt.update(requiere_confirmacion=False, confirmada=True, decision_confirmacion=dec)
    comun.escribir_json(d / "router.json", rt)
    return {**dec, "repetir_codigo": dec["cambio"]}


# ---------------------------------------------------------------- hashes de la fase ciega

def congelar(d: Path) -> dict:
    hashes = {p.name: comun.sha256_archivo(p) for p in sorted(d.iterdir()) if CONGELADOS.match(p.name)}
    comun.escribir_json(d / "hashes.json", {"creado": comun.ahora_iso(), "archivos": hashes})
    return hashes


def verificar_congelados(d: Path) -> list[str]:
    ruta = d / "hashes.json"
    if not ruta.exists():
        return []
    cambios = []
    for nombre, h in comun.leer_json(ruta)["archivos"].items():
        p = d / nombre
        if not p.exists() or comun.sha256_archivo(p) != h:
            cambios.append(nombre)
    return cambios


# ---------------------------------------------------------------- escenarios

def percentiles_drivers(analista: dict, dp: dict) -> dict:
    """Percentil, z y bandera de cada driver con tasa base, calculados por código (tasas_base.py)."""
    import tasas_base

    ventas = tasas_base.ventas_musd(dp)
    res: dict[str, dict] = {}
    for e in analista["escenarios"]:
        res[e["nombre"]] = {}
        for nombre, drv in e["drivers"].items():
            if nombre not in tasas_base.ALIAS_DRIVER:
                continue
            v = drv["valor"]
            v = v[0] if isinstance(v, list) and v else v
            if not isinstance(v, (int, float)):
                continue
            ev = tasas_base.evaluar(nombre, float(v), ventas)
            if ev["estado"] == "ok":
                res[e["nombre"]][nombre] = {"percentil": ev["percentil"], "z": ev["z"], "bandera": ev["bandera"]}
    return res


def ejecutar_escenarios(d: Path, modo: str) -> dict:
    from motor import escenarios as esc

    motor = comun.leer_json(d / "motor_inicial.json")
    if "error" in motor:
        raise ValueError(f"motor_inicial.json tiene un error: {motor['error']}")
    dp = comun.leer_json(d / "datapack.json")
    ajustes = comun.leer_json(d / "ajustes.json") if (d / "ajustes.json").exists() else None
    hechos = {}
    for n in comun.analistas_de_modo(modo) + (["B1"] if modo == "completo" else []):
        f = d / f"analista_{n}.json"
        if not f.exists():
            continue
        analista = comun.leer_json(f)
        sin = esc.ejecutar(analista, motor)
        sin["percentiles_codigo"] = percentiles_drivers(analista, dp)
        if ajustes and n != "B1" and ajustes.get("ajustes"):
            comun.escribir_json(d / f"escenarios_{n}_sin_ajustes.json", sin)
            con = esc.ejecutar(analista, motor, ajustes)
            con["percentiles_codigo"] = sin["percentiles_codigo"]
            comun.escribir_json(d / f"escenarios_{n}.json", con)
            hechos[n] = {"p_E1": con["probabilidades"]["E1"], "p_E1_sin_ajustes": sin["probabilidades"]["E1"],
                         "ajustes": len(con["ajustes_aplicados"]), "modelo_fiable": con["cordura"]["fiable"]}
        else:
            comun.escribir_json(d / f"escenarios_{n}.json", sin)
            hechos[n] = {"p_E1": sin["probabilidades"]["E1"], "modelo_fiable": sin["cordura"]["fiable"]}
    if not hechos:
        raise FileNotFoundError("No hay salidas de analistas (analista_*.json)")
    bloquea = comun.cargar_config().get("cordura", {}).get("bloquea", False)
    principales = [hechos[n] for n in comun.analistas_de_modo(modo) if n in hechos]
    hechos["cierre_anticipado"] = bool(bloquea and principales and not any(h["modelo_fiable"] for h in principales))
    return hechos


# ---------------------------------------------------------------- cierre

def auditar_traza(d: Path) -> list[dict]:
    """Lecturas de salidas ajenas por analistas o el forense registradas en traza.jsonl (segunda capa tras los hooks)."""
    from hooks.guardia import PROHIBIDO_LEER, nombre_agente

    ruta = d / "traza.jsonl"
    if not ruta.exists():
        return []
    violaciones = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            t = json.loads(linea)
        except json.JSONDecodeError:
            continue
        agente = nombre_agente(t.get("agent_type"))
        if agente not in ("analista-fundamental", "forense") or t.get("tool") not in ("Read", "Grep"):
            continue
        objetivo = Path(t.get("args_resumidos", {}).get("file_path") or t.get("args_resumidos", {}).get("path") or "").name
        if objetivo and PROHIBIDO_LEER[agente].match(objetivo):
            violaciones.append({"agente": agente, "agent_id": t.get("agent_id"), "archivo": objetivo, "ts": t.get("ts")})
    return violaciones


def cerrar(d: Path, modo: str, journal: Path, modelos: dict | None = None) -> dict:
    import agregar
    import baselines
    import diario
    import gate

    cambios = verificar_congelados(d)
    if cambios:
        raise ValueError(f"Salidas de la fase ciega modificadas después de congelarlas: {cambios}")
    dp = comun.leer_json(d / "datapack.json") if (d / "datapack.json").exists() else comun.leer_json(d / "datapack_base.json")
    if (d / "router.json").exists():
        rt = comun.leer_json(d / "router.json")
    else:
        # Cierre anticipado (p. ej. ticker inexistente o fuentes caídas): el paso 4 nunca corrió, se clasifica aquí.
        import router
        rt = router.clasificar(dp)
        comun.escribir_json(d / "router.json", rt)
    tiene_escenarios = all((d / f"escenarios_{n}.json").exists() for n in comun.analistas_de_modo(modo))
    if tiene_escenarios:
        banderas = agregar.cargar_banderas(d)
        rev = agregar.cargar_reverse_dcf(d)
        ag = agregar.agregar(agregar.cargar_escenarios(d, comun.analistas_de_modo(modo)), modo, banderas=banderas,
                             reverse_dcf=rev)
        sin = [d / f"escenarios_{n}_sin_ajustes.json" for n in comun.analistas_de_modo(modo)]
        if all(p.exists() for p in sin):
            ag_sin = agregar.agregar({n: comun.leer_json(p) for n, p in zip(comun.analistas_de_modo(modo), sin)}, modo,
                                     banderas=banderas, reverse_dcf=rev)
            ag["p_final_sin_ajustes"] = ag_sin["p_final"]
        comun.escribir_json(d / "agregado.json", ag)
        b1 = None
        if (d / "escenarios_B1.json").exists():
            ag_b1 = agregar.agregar({"B1": comun.leer_json(d / "escenarios_B1.json")}, modo)
            comun.escribir_json(d / "agregado_B1.json", ag_b1)
            b1 = ag_b1["p_final"]
        comun.escribir_json(d / "baselines.json",
                            baselines.calcular(dp, rt["ruta"], (b1 or {}).get("E1"), b1_e4=(b1 or {}).get("E4")))
    previo = comun.leer_json(d / "gate_previo.json") if (d / "gate_previo.json").exists() else None
    if tiene_escenarios or (previo is not None and previo["pasa"]):
        # Checklist final; si faltan escenarios (p. ej. el motor falló), sus puntos dan el motivo real.
        datos_g = gate.cargar(d, modo)
        g = gate.evaluar(datos_g["dp"], datos_g["router"], modo, "final", datos_g["motor"], datos_g["analistas"],
                         datos_g["escenarios"], datos_g["forense"], datos_g["sintesis"])
        comun.escribir_json(d / "gate.json", g)
    elif previo is None:
        comun.escribir_json(d / "gate_previo.json", gate.evaluar(dp, rt, modo, "previo"))
    cruzadas = auditar_traza(d)
    comun.escribir_json(d / "auditoria_traza.json", {"lecturas_cruzadas": cruzadas})
    res = diario.cerrar(d, journal / diario.RUTA_DIARIO, modo, modelos)
    terminar()
    return {**res, "lecturas_cruzadas": cruzadas}


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Control de una ejecución de /analizar.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("iniciar")
    s.add_argument("--entrada", required=True)
    s.add_argument("--journal", required=True)
    s.add_argument("--fecha")
    for nombre in ("datos", "fusionar", "codigo", "congelar", "escenarios", "cerrar", "confirmar-ruta"):
        s = sub.add_parser(nombre)
        s.add_argument("--dir", required=True)
        if nombre in ("codigo", "escenarios", "cerrar"):
            s.add_argument("--modo", required=True, choices=comun.MODOS)
        if nombre == "cerrar":
            s.add_argument("--journal", required=True)
            s.add_argument("--modelos")
        if nombre == "fusionar":
            s.add_argument("--comprobar", action="store_true")
        if nombre == "confirmar-ruta":
            s.add_argument("--propuesta")
            s.add_argument("--dato-ref")
            s.add_argument("--motivo")
    s = sub.add_parser("fase")
    s.add_argument("--fase", required=True, choices=["datos", "ciega", "red_team", "juez", "cierre"])
    sub.add_parser("terminar")
    sub.add_parser("estado")
    a = p.parse_args(argv)
    try:
        if a.cmd == "iniciar":
            res = iniciar(a.entrada, a.journal, a.fecha)
        elif a.cmd == "datos":
            res = datos(Path(a.dir))
        elif a.cmd == "fusionar":
            res = fusionar(Path(a.dir), a.comprobar)
        elif a.cmd == "codigo":
            res = codigo(Path(a.dir), a.modo)
        elif a.cmd == "confirmar-ruta":
            res = confirmar_ruta(Path(a.dir), a.propuesta, a.dato_ref, a.motivo)
        elif a.cmd == "fase":
            res = cambiar_fase(a.fase)
        elif a.cmd == "congelar":
            res = congelar(Path(a.dir))
        elif a.cmd == "escenarios":
            res = ejecutar_escenarios(Path(a.dir), a.modo)
        elif a.cmd == "cerrar":
            res = cerrar(Path(a.dir), a.modo, Path(a.journal), json.loads(a.modelos) if a.modelos else None)
        elif a.cmd == "terminar":
            res = terminar()
        else:
            res = leer_activa() or {"activa": None}
    except (ValueError, FileNotFoundError, KeyError, comun.ErrorDatos) as e:
        comun.salir_con_error(f"{type(e).__name__}: {e}")
    print(comun.volcar_json(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
