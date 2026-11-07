# 0013. Beta del WACC: mezcla de la del sector y la propia de la acción

**Estado:** aplicada (v0.3.2). **Fecha:** 7-nov-2026. Aprobada por el usuario.

## Contexto
El WACC usaba solo la beta desapalancada del sector de Damodaran. Damodaran clasifica a Alphabet en "Software
(Internet)", un grupo de 29 empresas (muchas pequeñas y especulativas) con beta desapalancada 1,55. Resultado: beta
reapalancada 1,63 y WACC 11,8 % para una empresa cuya beta propia frente a VWCE ronda 0,94. Un WACC tan alto hunde el
valor de las grandes empresas de calidad, y el usuario sospechaba (con razón en parte) que el modelo castigaba de más a
las acciones muy recomendadas.

## Decisión
La beta desapalancada que entra en el WACC es `peso_propia · β_propia_desapalancada + (1 − peso_propia) · β_sector`, con
`peso_propia = 0,5` (config `beta`). La beta propia es la de los retornos semanales a 3 años frente a VWCE
(`beta_3a` en `datos/precios.py`), con ajuste de Blume (0,67·β + 0,33), limitada a [0,4; 2,5] y desapalancada con la
deuda/capitalización actual. Sin beta propia, o con `peso_propia = 0`, se usa solo el sector. Si ambas difieren más de
0,5 se avisa. Solo afecta a las rutas con DCF por WACC (general, crecimiento_perdidas, cíclica).

## Alternativas descartadas
- Usar solo la beta propia: es ruidosa (3 años de datos semanales) y está medida frente a VWCE, no frente al mercado
  estadounidense de Damodaran.
- Mantener solo el sector: penaliza sistemáticamente a las grandes empresas clasificadas con pequeñas especulativas.
- Bancos, biotech y holdings quedan como estaban (no usan este WACC o tienen muy poco historial fiable).

## Consecuencias
- Alphabet: WACC 11,8 % → 10,3 %; valor mecánico 69 → 82 USD; crecimiento implícito 33 % → 28 %. Sigue "no
  atractiva": la beta no es el factor dominante.
- El moat ya se tenía en cuenta: si el analista documenta un moat con evidencia, `roic_terminal` mayor que el WACC entra
  en los escenarios (`escenarios.py`). Solo el `valor_mecanico` de referencia lo ignora, y no influye en el veredicto.
- Pendiente: validar con un backtest si el modelo sigue siendo demasiado conservador.

## Archivos
`scripts/datos/precios.py`, `scripts/motor/inicial.py`, `assets/config.yaml`; SPEC A6 (WACC); tests en
`tests/test_precios.py` y `tests/test_inicial.py`.
