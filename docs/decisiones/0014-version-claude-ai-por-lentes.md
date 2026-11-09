# 0014. Versión para claude.ai por lentes (sin DCF como juez único)

**Estado:** propuesta, rama `claude-ai-lentes`. **Fecha:** 9-nov-2026.

## Contexto
El plugin no corre en un chat de claude.ai (sin subagentes, hooks ni `uv`; el modo degradado acaba en `no_analizable`)
y su veredicto depende de un DCF encogido hacia tasas base conservadoras. El backtest
(`backtest-del-motor.md`) muestra que ese DCF no discrimina (rho de Spearman 0,006 a 12 meses, 0,077 a 3 años) y que
mediana V/P = 0,64, es decir, trata como caras a las grandes empresas de crecimiento que luego rindieron más. El
propio backtest avisa de sesgo de supervivencia en ese resultado.

## Decisión
Añadir, sin tocar el plugin, `claude-ai/`: un skill y un script de biblioteca estándar (`lentes.py`) que combina
momentum, revisiones de estimaciones, calidad, valor y riesgo. El DCF inverso queda como información y no puede vetar.
El veredicto es simétrico (umbrales de exceso anual esperado de ±3 pp). Datos por el conector Alpha Vantage.

## Lo que NO se cambió y por qué
Los parámetros del motor del plugin (`tasas_base_k`, `z_no_atractiva`, `tope_desviacion`, `k`) siguen igual:
`CLAUDE.md` exige preguntar antes de cambiar decisiones de la Parte A, y el backtest indica que aflojarlos no mejora la
discriminación (correlación a 3 años 0,077 → 0,039 → 0,009). Hacerlo ahora sería cambiar por intuición.

## Alternativas descartadas
- Aflojar el encogimiento en el plugin: sin evidencia a favor (ver arriba).
- Calibrar pesos con el backtest actual: universo con sesgo de supervivencia.

## Consecuencias y límites
- Pesos y umbrales de `lentes.py` son heurísticos y no están calibrados; la prueba será el diario de predicciones.
- Independencia reducida: en claude.ai analista y abogado del diablo comparten contexto. Mitigación: los números salen
  del script y una objeción solo cambia cifras si es un error de datos.
- Solo empresas no financieras que informan en USD; datos mensuales; VT como sustituto de VWCE.
- Requiere ejecución de código activada en claude.ai.
- Respaldo FMP: los precios mensuales de FMP reproducen el resultado de Alpha Vantage (KO: exceso +3,87 % frente a
  +3,87 %, p12 55,51 % frente a 55,51 %). Los estados de FMP se convierten por nombres de campo reales, probados con
  muestras, pero no hay aún una ejecución completa con estados reales de FMP. Con el plan actual: 5 periodos por estado,
  sin VT (el índice se refresca desde Alpha Vantage una vez al mes) y sin historial de revisiones.

## Dónde está
`claude-ai/lentes.py`, `claude-ai/SKILL.md`, `claude-ai/README.md`; tests en `tests/test_lentes.py`.
