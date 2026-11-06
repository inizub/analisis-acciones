import json

import pytest

import baselines
import comun
from artefactos import cifra, dp_completo
from dp_sintetico import crecer

CFG = comun.cargar_config()


def test_b0_es_la_tasa_base():
    assert baselines.b0(CFG) == 0.45


def test_b2_momentum():
    dp = dp_completo()
    dp["precios"]["metricas_eur"]["momentum_12_1_rel"] = cifra(0.05)
    assert baselines.b2(dp, CFG)[0] == 0.55
    dp["precios"]["metricas_eur"]["momentum_12_1_rel"] = cifra(-0.01)
    assert baselines.b2(dp, CFG)[0] == 0.40
    dp["precios"]["metricas_eur"]["momentum_12_1_rel"] = cifra(0.0)
    assert baselines.b2(dp, CFG)[0] == 0.40            # solo "superior" estricto
    dp["precios"]["metricas_eur"]["momentum_12_1_rel"] = comun.desconocido("not_covered")
    assert baselines.b2(dp, CFG)[0] is None
    dp["precios"] = comun.desconocido("source_down")
    assert baselines.b2(dp, CFG)[0] is None


def dp_valor(cap, ebit=1e9, deuda=0.0, caja=0.0, ev_ebit_sector=20.0):
    dp = dp_completo(beneficio_operativo=[ebit] * 10, deuda_total=[deuda] * 10, caja=[caja] * 10)
    dp["precios"]["capitalizacion"] = cifra(cap, "unidades", "USD")
    dp["damodaran"]["sector"]["valores"]["ev_ebitda.ev_ebit"] = cifra(ev_ebit_sector, "veces")
    return dp


@pytest.mark.parametrize("cap,esperado", [(10e9, 0.55), (16e9, 0.55), (16.1e9, 0.45), (23.9e9, 0.45), (24e9, 0.40),
                                          (40e9, 0.40)])
def test_b3_ev_ebit_frente_al_sector(cap, esperado):
    """EV/EBIT = cap/1e9; sector 20: razón ≤ 0,8 (≤ 16×) barato, ≥ 1,2 (≥ 24×) caro."""
    v, motivo = baselines.b3(dp_valor(cap), "general", CFG)
    assert v == esperado and "EV/EBIT / sector" in motivo


def test_b3_incluye_deuda_y_caja_en_el_ev():
    v, _ = baselines.b3(dp_valor(10e9, deuda=8e9, caja=0), "general", CFG)       # EV 18× → razón 0,9 → medio
    assert v == 0.45
    v, _ = baselines.b3(dp_valor(20e9, deuda=0, caja=8e9), "general", CFG)       # EV 12× → barato
    assert v == 0.55


def test_b3_no_calculable():
    assert baselines.b3(dp_valor(10e9, ebit=-1e8), "general", CFG)[0] is None
    dp = dp_valor(10e9)
    dp["precios"]["moneda"] = "EUR"                       # cotiza en una moneda distinta a la del informe
    assert baselines.b3(dp, "general", CFG)[0] is None
    dp = dp_valor(10e9)
    del dp["damodaran"]["sector"]["valores"]["ev_ebitda.ev_ebit"]
    assert baselines.b3(dp, "general", CFG)[0] is None


def test_b3_bancos_usa_pbv_entre_roe():
    """Sector: P/BV 2,0 con ROE 15 % → 13,3. Banco: P/BV = cap/patrimonio, ROE = BN/patrimonio."""
    def banco(cap, pat=10e9, bn=1.5e9):
        dp = dp_completo(patrimonio=[pat] * 10, beneficio_neto=[bn] * 10)
        dp["precios"]["capitalizacion"] = cifra(cap, "unidades", "USD")
        return dp
    assert baselines.b3(banco(15e9), "banco_credito", CFG)[0] == 0.55        # P/BV 1,5 / ROE 0,15 = 10 → razón 0,75
    assert baselines.b3(banco(20e9), "banco_credito", CFG)[0] == 0.45        # 13,3 → razón 1,0
    assert baselines.b3(banco(30e9), "banco_credito", CFG)[0] == 0.40        # 20 → razón 1,5
    assert baselines.b3(banco(15e9, bn=-1e8), "banco_credito", CFG)[0] is None


def test_calcular_y_cli(tmp_path, capsys):
    dp = dp_valor(16e9)
    r = baselines.calcular(dp, "general", b1=0.52, b1_e4=0.61)
    assert (r["B0"], r["B1"], r["B1_E4"], r["B2"], r["B3"], r["B0_E4"]) == (0.45, 0.52, 0.61, 0.55, 0.55, 0.5)
    assert baselines.calcular(dp, "general")["B1"] is None
    (tmp_path / "dp.json").write_text(json.dumps(dp), encoding="utf-8")
    (tmp_path / "b1.json").write_text(json.dumps({"p_final": {"E1": 0.5, "E4": 0.7}}), encoding="utf-8")
    assert baselines.main(["--datapack", str(tmp_path / "dp.json"), "--ruta", "general", "--b1", str(tmp_path / "b1.json"),
                           "--salida", str(tmp_path / "bl.json")]) == 0
    out = json.loads((tmp_path / "bl.json").read_text(encoding="utf-8"))
    assert out["B1"] == 0.5 and out["B1_E4"] == 0.7
