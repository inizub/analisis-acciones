# 0006. El juez puede ajustar la base del motor, con límites

**Estado:** aplicada (v0.2.0). **Fecha:** 7-nov-2026. **Commits:** `b6b3fa6`, `a360a9b`.

## Contexto
En la primera ejecución de NVDA, el red team detectó que la base de ingresos estaba desfasada y el juez validó la
objeción, pero el motor rechazaba el ajuste (`ErrorMotor: driver 'ingresos0' no existe`). También quedó sin poderse corregir
el tipo impositivo (16-18 % guiado frente al 25 % del motor).

En la segunda ejecución, el juez ya pudo ajustar `ingresos0` y lo hizo con una **estimación** (346 mil M, calculados con
el mínimo de la guía y un cuarto trimestre supuesto) en vez de los 303 mil M reportados: incumplía la regla de no
estimar datos financieros.

## Decisión
`escenarios.aplicar_ajustes_base` permite al juez ajustar dos inputs de la base (para todos los escenarios):
- **`tasa_impuestos`**: fracción menor que 0,6, con dato con fuente.
- **`ingresos0`**: **solo** si el motor no pudo calcular los últimos doce meses (`base_ingresos.metodo == "anual"`) y con
  una cifra reportada. Si la base ya es de doce meses reportados (`ttm`, `ttm_ingresos`), el ajuste se **rechaza**.
`agents/juez.md` lo explica.

## Alternativas descartadas
- **No permitir ajustar la base:** el juez veía errores reales y no podía actuar.
- **Permitir cualquier valor:** abre la puerta a estimaciones disfrazadas de corrección.

## Consecuencias
- El juez tiene menos margen: es la intención. El valor a vigilar sigue siendo la calidad de la objeción del red team.

## Dónde está
`scripts/motor/escenarios.py` (`AJUSTES_BASE`, `aplicar_ajustes_base`), `agents/juez.md`, `tests/test_escenarios.py`.
