# 0009. Versionado y exclusión de predicciones antiguas de la puntuación

**Estado:** aplicada (v0.2.0). **Fecha:** 7-nov-2026. **Commit:** `08c99ed`.

## Contexto
Las predicciones guardadas hasta el 7-nov (AAPL, NU y NVDA) usaban un método de probabilidades incoherente
([0001](0001-probabilidades-coherentes.md)). Si se mezclaran con las nuevas, la puntuación de calibración (Brier, log score,
Diebold-Mariano) no serviría para decidir nada. Además, Claude Code decide si refrescar la copia instalada según la
**versión** del plugin, que seguía en 0.1.0.

## Decisión
- Versión subida a **0.2.0** (y a 0.2.1, 0.2.2 y 0.3.0 con los cambios posteriores). Se actualizan `plugin.json`,
  `marketplace.json`, `SKILL.md` y `README.md`.
- `puntuacion.version_minima` (config.yaml, 0.2.0): `puntuar.py` no puntúa las predicciones emitidas con una versión anterior.
  Siguen en el diario y el informe las cuenta aparte ("de versiones anteriores, no puntuadas"). Sin versión legible, no se excluye.
- **No se borró nada del diario:** está encadenado con hashes (`hash_prev`) y es el registro histórico.

## Alternativas descartadas
- **Borrar o reescribir las predicciones viejas:** rompe la cadena de hashes.
- **Marcarlas como no fiables con un registro de anulación:** innecesario; la exclusión por versión lo resuelve y es reversible.

## Consecuencias
- La entrada `NVDA-2026-11-07-a` (con el 81 %) queda en el diario pero sin influir en la puntuación.
- Si en el futuro cambia otra vez el método de forma que las predicciones no sean comparables, hay que subir `version_minima`.

## Dónde está
`scripts/puntuar.py` (`version_anterior`, `cargar_filas`), `assets/config.yaml` (`puntuacion.version_minima`), `.claude-plugin/`.
