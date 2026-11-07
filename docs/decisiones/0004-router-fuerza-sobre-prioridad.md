# 0004. Router: la fuerza de la señal manda sobre la prioridad

**Estado:** aplicada (v0.2.0 a v0.2.2). **Fecha:** 7-nov-2026. **Commits:** `10baa37`, `6ec03ce`.

## Contexto
El SPEC (A8) fijaba una prioridad estricta: `crecimiento_perdidas` antes que `ciclica`. Pero `crecimiento_perdidas` se
dispara también solo porque el crecimiento de ventas supera el p90 de su clase, aunque sea por décimas. Resultado:
- **NVDA y Freeport** (cíclicas claras) iban a `crecimiento_perdidas`.
- **Valero** (refinería): su crecimiento de ventas a 5 años sigue al precio del crudo y le daba el mismo error.
Cada caso obligaba a una consulta extra al analista, y sin ella el valor salía desmedido (Valero: 520 USD frente a 354 con la ruta correcta).

## Decisión
- Las rutas **duras** (`fuera_de_alcance`, `banco_credito`, `biotech_precomercial`, `holding`) mantienen la prioridad estricta.
- Entre las blandas (`crecimiento_perdidas`, `ciclica`, `general`), una candidata de **fuerza alta gana a una de fuerza media**;
  la prioridad solo desempata a igual fuerza.
- Desempate a fuerza media: `ciclica` antes que `crecimiento_perdidas` (un crecimiento puntual es peor evidencia que un
  sector cíclico). A fuerza alta sigue el SPEC.
- Una alternativa **más débil** que la elegida ya no obliga a consultar al analista (confianza media); un conflicto entre
  candidatas de fuerza igual o mayor sí (confianza baja).

## Alternativas descartadas
- **Cambiar solo el umbral de crecimiento (p90):** es un número arbitrario y volvería a fallar en otro caso.
- **Quitar la señal de crecimiento:** perdería las empresas de crecimiento rápido con beneficios que sí encajan en esa ruta.

## Consecuencias
- Comprobado con los datapacks reales: NVDA, Freeport, Valero, Nucor → cíclica; Rivian → crecimiento_perdidas; KO, AAPL → general; NU → banco.
- Cambió el SPEC (A8, párrafo "Precedencia entre rutas").
- Queda por ver si algún caso real necesita otro ajuste; la mejor salvaguarda sigue siendo la consulta al analista.

## Dónde está
`scripts/router.py` (`RUTAS_DURAS`, `_desempate`, `rivales`), `tests/test_router.py`, `SPEC.md` A8.
