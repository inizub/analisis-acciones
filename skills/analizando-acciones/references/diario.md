# Diario de predicciones

## Dónde está

`JOURNAL/diario/predicciones.jsonl`: una línea por análisis, append-only, con `hash_prev` (SHA-256 de la línea
anterior). Comprobar que nadie lo ha modificado: `PY diario.py verificar --diario "JOURNAL/diario/predicciones.jsonl"`.

Tipos de línea: predicción (el verdict.json), `update` (un nuevo análisis del mismo ticker mientras su E1 sigue
abierto; no se puntúa aparte) y `resolucion` (la escribe `resolver.py`).

## Eventos

Todos en rentabilidad total en EUR, con dividendos, desde el cierre del día del análisis. Benchmark: VWCE.DE.

| Evento | Pregunta | Horizonte |
|---|---|---|
| E0 | RT(acción) − RT(VWCE) > 0 | 6 meses |
| E1 | RT(acción) − RT(VWCE) > 0 (principal) | 12 meses |
| E2 | RT(acción) − RT(VWCE) > 0 | 36 meses |
| E3 | La acción cae ≥ 30 % desde el precio de entrada en algún momento | 12 meses |
| E4 | La métrica fundamental del próximo ejercicio ≥ el valor base | próximo informe anual |

## Anulación

Una pregunta se anula (no cuenta para la puntuación) por OPA o fusión, exclusión de cotización, escisión o falta de
datos para resolverla. `resolver.py` anula sola la falta de datos; las demás causas las pones tú:

```
PY resolver.py anular --diario "JOURNAL/diario/predicciones.jsonl" --id <ID> --qid E1 --causa opa --nota "..."
```

## Resolver

Semanal (puede ir en cron, no usa ningún modelo):

```
PY resolver.py resolver --diario "JOURNAL/diario/predicciones.jsonl"
PY resolver.py pendientes --diario "JOURNAL/diario/predicciones.jsonl"
```

Los hitos clínicos (E4 de biotech) se resuelven a mano:

```
PY resolver.py manual --diario "JOURNAL/diario/predicciones.jsonl" --id <ID> --qid E4 --resultado 1 --nota "..."
```

## Puntuar

Trimestral:

```
PY puntuar.py informe --diario "JOURNAL/diario/predicciones.jsonl"
```

Escribe `JOURNAL/diario/informes/AAAA-Tn.md` y `.json` con log score y Brier por evento y modo, Brier skill score
frente a B0, pendiente de calibración y comparación con los baselines (Diebold-Mariano). El modo degradado se puntúa
aparte.
