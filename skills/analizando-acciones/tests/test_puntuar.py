import json
import math
from datetime import date

import numpy as np
import pytest

import comun
import diario as dr
import puntuar

CFG = comun.cargar_config()
CLIP = CFG["puntuacion"]["clip_log"]


# ---------------------------------------------------------------- métricas básicas

def test_baseline_de_segun_el_evento():
    bl = {"B0": .45, "B1": .5, "B2": .55, "B3": .4, "B0_E4": .5, "B1_E4": .6}
    assert [puntuar.baseline_de(bl, "E1", b) for b in ("B0", "B1", "B2", "B3")] == [.45, .5, .55, .4]
    assert [puntuar.baseline_de(bl, "E4", b) for b in ("B0", "B1", "B2", "B3")] == [.5, .6, None, None]
    assert [puntuar.baseline_de(bl, "E3", b) for b in ("B0", "B1", "B2", "B3")] == [None] * 4


def test_log_score_y_brier_a_mano():
    p, y = np.array([.8, .2]), np.array([1.0, 0.0])
    m = puntuar.metricas(p, y, CLIP)
    assert m["log_score"] == pytest.approx(math.log(.8)) and m["brier"] == pytest.approx(0.04)
    assert m["n"] == 2 and m["tasa_observada"] == .5 and m["p_media"] == .5


def test_el_log_score_limita_las_probabilidades_extremas():
    m = puntuar.metricas(np.array([1.0]), np.array([0.0]), CLIP)       # certeza equivocada
    assert m["log_score"] == pytest.approx(math.log(0.02)) and m["brier"] == 1.0
    m = puntuar.metricas(np.array([0.0]), np.array([1.0]), CLIP)
    assert m["log_score"] == pytest.approx(math.log(0.02))
    assert puntuar.metricas(np.array([1.0]), np.array([1.0]), CLIP)["log_score"] == pytest.approx(math.log(0.98))


def test_brier_skill_score():
    assert puntuar.brier_skill(0.20, 0.25) == pytest.approx(0.20)
    assert puntuar.brier_skill(0.30, 0.25) == pytest.approx(-0.20)
    assert puntuar.brier_skill(0.0, 0.25) == 1.0 and puntuar.brier_skill(0.1, 0.0) is None


# ---------------------------------------------------------------- calibración

def muestra(n, f_verdadera, semilla=4):
    rng = np.random.default_rng(semilla)
    p = rng.uniform(0.05, 0.95, n)
    return p, (rng.uniform(size=n) < f_verdadera(p)).astype(float)


def test_calibracion_pendiente_uno_si_esta_calibrada():
    p, y = muestra(6000, lambda p: p)
    c = puntuar.calibracion(p, y, CLIP, 20)
    assert c["pendiente"] == pytest.approx(1.0, abs=0.12) and c["intercepto"] == pytest.approx(0.0, abs=0.12)


def test_calibracion_pendiente_menor_que_uno_si_es_sobreconfiada():
    """El modelo da probabilidades demasiado extremas: la verdad se parece a 0,5 + 0,4·(p − 0,5)."""
    p, y = muestra(6000, lambda p: 0.5 + 0.4 * (p - 0.5))
    assert puntuar.calibracion(p, y, CLIP, 20)["pendiente"] == pytest.approx(0.4, abs=0.1)


def test_calibracion_exige_muestra_y_dos_clases():
    p, y = muestra(19, lambda p: p)
    assert puntuar.calibracion(p, y, CLIP, 20) is None
    assert puntuar.calibracion(np.full(50, .5), np.ones(50), CLIP, 20) is None
    c = puntuar.calibracion(np.full(50, .5), np.tile([0., 1.], 25), CLIP, 20)       # p constante: pendiente ≈ 0
    assert abs(c["pendiente"]) < 1e-3


# ---------------------------------------------------------------- Diebold-Mariano

def test_varianza_hac():
    d = np.array([1.0, -1.0] * 50)
    assert puntuar.varianza_hac(d, 1) == pytest.approx(1.0)                  # h = 1: varianza muestral
    assert puntuar.varianza_hac(d, 2) == pytest.approx(1 / 100, abs=1e-12)   # 1 + 2·(1 − 1/2)·γ1 con γ1 = −99/100
    rng = np.random.default_rng(1)
    ruido = rng.normal(size=2000)
    assert puntuar.varianza_hac(ruido, 5) == pytest.approx(1.0, abs=0.15)    # iid: la varianza de largo plazo ≈ varianza


def test_dm_favorece_al_modelo_mejor():
    rng = np.random.default_rng(2)
    n = 120
    base = rng.uniform(0.1, 0.4, n)
    modelo = base - 0.05 + rng.normal(0, 0.02, n)           # pérdida del modelo menor en media
    r = puntuar.diebold_mariano(modelo, base, 1, 10)
    assert r["diferencia_media"] < 0 and r["dm"] < -3 and r["p_valor"] < 0.01 and r["n"] == n
    peor = puntuar.diebold_mariano(base, modelo, 1, 10)
    assert peor["dm"] == pytest.approx(-r["dm"]) and peor["p_valor"] == pytest.approx(r["p_valor"])


def test_correccion_hln_para_h_1():
    rng = np.random.default_rng(3)
    a, b = rng.uniform(size=60), rng.uniform(size=60)
    r = puntuar.diebold_mariano(a, b, 1, 10)
    assert r["dm_hln"] == pytest.approx(r["dm"] * math.sqrt((60 + 1 - 2) / 60))
    from scipy import stats
    assert r["p_valor"] == pytest.approx(2 * (1 - stats.t.cdf(abs(r["dm_hln"]), 59)))


def test_dm_devuelve_none_sin_datos_suficientes_o_sin_varianza():
    x = np.linspace(0, 1, 30)
    assert puntuar.diebold_mariano(x[:9], x[:9][::-1], 1, 10) is None        # n < 10
    assert puntuar.diebold_mariano(x[:24], x[:24][::-1], 12, 10) is None     # n ≤ 2h
    assert puntuar.diebold_mariano(x[:25], x[:25][::-1] ** 2, 12, 10) is not None            # n = 25 > 2h
    assert puntuar.diebold_mariano(x + 0.1, x, 1, 10) is None                # d constante: varianza nula


# ---------------------------------------------------------------- diario completo

def prediccion(i, modo="completo", p=.5, baselines=None, veredicto="neutral", ticker=None, qid="E1"):
    return {"id": f"T{i}-2025-01-01-a", "created_at": f"{2024 + i // 12}-{i % 12 + 1:02d}-01T00:00:00Z", "hash_prev": None,
            "ticker": ticker or f"T{i}", "veredicto": veredicto, "skill": {"modo": modo},
            "preguntas": [{"qid": qid, "p": p}],
            "baselines": baselines if baselines is not None else {"B0": .45, "B1": .5, "B2": .55, "B3": .45,
                                                                   "B0_E4": .5, "B1_E4": .6}}


def resolucion(pred, y, estado="resuelta", qid="E1"):
    return {"tipo": "resolucion", "id": pred["id"], "qid": qid, "estado": estado, "resultado": y if estado == "resuelta" else None,
            "hash_prev": None}


def diario_sintetico(n=100, modo="completo", semilla=7):
    rng = np.random.default_rng(semilla)
    regs = []
    for i in range(n):
        verdadera = rng.uniform(0.2, 0.8)
        pr = prediccion(i, modo, p=round(verdadera, 4))
        regs += [pr, resolucion(pr, int(rng.uniform() < verdadera))]
    return regs


def test_cargar_filas_ignora_updates_anuladas_pendientes_y_no_analizables():
    p1, p2, p3, p4 = (prediccion(i) for i in range(4))
    regs = [p1, resolucion(p1, 1), p2, resolucion(p2, None, "anulada"), p3,
            {"tipo": "update", "id": p1["id"], "verdict": {"id": "x"}},
            prediccion(9, veredicto="no_analizable") | {"preguntas": []}, p4, resolucion(p4, 0)]
    df, cuenta = puntuar.cargar_filas(regs)
    assert list(df["id"]) == [p1["id"], p4["id"]] and list(df["y"]) == [1, 0]
    assert cuenta == {"predicciones": 4, "no_analizables": 1, "updates": 1, "resueltas": 2, "anuladas": 1, "pendientes": 1}


def test_se_puntua_la_probabilidad_preregistrada():
    p = prediccion(0, p=.7)
    upd = {"tipo": "update", "id": p["id"], "verdict": {"id": "otro", "preguntas": [{"qid": "E1", "p": .1}]}}
    df, _ = puntuar.cargar_filas([p, upd, resolucion(p, 1)])
    assert list(df["p"]) == [.7]


def test_puntuar_agrupa_por_evento_y_modo():
    regs = diario_sintetico(40, "completo") + diario_sintetico(40, "degradado", semilla=8)
    # los ids de las dos series coinciden: se desplazan para que no choquen
    for r in regs[80:]:
        r["id"] = "D" + r["id"]
    res = puntuar.puntuar(regs, CFG)
    assert [(g["qid"], g["modo"]) for g in res["grupos"]] == [("E1", "completo"), ("E1", "degradado")]
    assert all(g["n"] == 40 for g in res["grupos"])
    assert res["cuenta"]["resueltas"] == 80


def test_puntuar_con_baselines_bss_y_dm():
    res = puntuar.puntuar(diario_sintetico(100), CFG)
    g = res["grupos"][0]
    assert g["n"] == 100 and set(g["baselines"]) == {"B0", "B1", "B2", "B3"}
    assert g["baselines"]["B0"]["n"] == 100 and g["baselines"]["B0"]["p_media"] == pytest.approx(0.45)
    # El modelo usa la probabilidad verdadera y B0 es constante: gana en Brier, así que el BSS es positivo.
    assert g["bss_vs_B0"] > 0
    dm = g["comparaciones"]["B0"]["brier"]
    assert dm["h"] == 12 and dm["n"] == 100 and dm["diferencia_media"] < 0 and 0 < dm["p_valor"] < 1
    assert g["comparaciones"]["B0"]["log"]["diferencia_media"] < 0
    assert g["calibracion"] is not None and g["calibracion"]["n"] == 100


def test_pocas_resoluciones_dejan_el_test_en_n_d():
    g = puntuar.puntuar(diario_sintetico(15), CFG)["grupos"][0]
    assert g["comparaciones"]["B0"]["brier"] is None and g["calibracion"] is None
    assert g["baselines"]["B0"]["n"] == 15 and g["bss_vs_B0"] is not None


def test_baselines_ausentes_en_algunas_filas():
    regs = []
    for i in range(30):
        bl = {"B0": .45, "B1": None, "B2": None, "B3": None} if i < 10 else None
        pr = prediccion(i, p=.5, baselines=bl)
        regs += [pr, resolucion(pr, i % 2)]
    g = puntuar.puntuar(regs, CFG)["grupos"][0]
    assert g["baselines"]["B0"]["n"] == 30 and g["baselines"]["B1"]["n"] == 20 and g["baselines"]["B2"]["n"] == 20


def test_e4_usa_b0_e4_y_b1_e4_y_e3_no_tiene_baselines():
    regs = []
    for i in range(12):
        for qid in ("E3", "E4"):
            pr = prediccion(i * 10 + (qid == "E4"), qid=qid, p=.3)
            regs += [pr, resolucion(pr, int(i % 3 == 0), qid=qid)]
    res = {g["qid"]: g for g in puntuar.puntuar(regs, CFG)["grupos"]}
    assert set(res["E4"]["baselines"]) == {"B0", "B1"} and res["E4"]["baselines"]["B0"]["p_media"] == .5
    assert res["E4"]["baselines"]["B1"]["p_media"] == pytest.approx(.6)
    assert res["E3"]["baselines"] == {} and res["E3"]["bss_vs_B0"] is None


# ---------------------------------------------------------------- informe

def test_trimestre():
    assert [puntuar.trimestre(date(2026, m, 1)) for m in (1, 3, 4, 6, 7, 9, 10, 12)] == [
        "2026-T1", "2026-T1", "2026-T2", "2026-T2", "2026-T3", "2026-T3", "2026-T4", "2026-T4"]


def test_informe_escribe_markdown_y_json(tmp_path):
    diario = tmp_path / "diario" / "predicciones.jsonl"
    prev = None
    for r in diario_sintetico(30):
        r["hash_prev"] = prev
        dr.anexar(diario, r)
        prev = dr.ultimo_hash(diario)
    salida = puntuar.escribir_informe(diario, tmp_path / "informes", date(2026, 11, 6), CFG)
    assert salida["informe"].endswith("2026-T4.md") and salida["resueltas"] == 30 and salida["grupos"] == 1
    md = (tmp_path / "informes" / "2026-T4.md").read_text(encoding="utf-8")
    assert "# Informe de puntuación 2026-T4" in md and "| E1 | completo | 30 |" in md and "Diebold-Mariano" in md
    datos = json.loads((tmp_path / "informes" / "2026-T4.json").read_text(encoding="utf-8"))
    assert datos["cuenta"]["resueltas"] == 30


def test_informe_con_diario_vacio(tmp_path):
    salida = puntuar.escribir_informe(tmp_path / "no_existe.jsonl", tmp_path / "inf", date(2026, 2, 1), CFG)
    assert salida["grupos"] == 0
    assert "Todavía no hay preguntas resueltas" in (tmp_path / "inf" / "2026-T1.md").read_text(encoding="utf-8")


def test_cli(tmp_path, capsys):
    diario = tmp_path / "d" / "p.jsonl"
    prev = None
    for r in diario_sintetico(12):
        r["hash_prev"] = prev
        dr.anexar(diario, r)
        prev = dr.ultimo_hash(diario)
    assert puntuar.main(["resumen", "--diario", str(diario)]) == 0
    assert json.loads(capsys.readouterr().out)["cuenta"]["resueltas"] == 12
    assert puntuar.main(["informe", "--diario", str(diario), "--hoy", "2026-05-01"]) == 0
    assert (tmp_path / "d" / "informes" / "2026-T2.md").exists()
