# Decisiones de diseño

Aquí está el **porqué** de los cambios hechos al plugin desde su primera prueba real (6 y 7 de noviembre de 2026).
El `SPEC.md` dice qué hay que construir; estas notas explican por qué se cambió algo respecto a él o a la primera
versión, qué alternativas se descartaron y qué efectos tiene. Si una decisión te parece mal, léela antes de
revertirla: casi todas nacen de un resultado absurdo que apareció en un análisis real.

Cada nota tiene el mismo formato: **Contexto** (qué falló o qué se pidió), **Decisión**, **Alternativas descartadas**,
**Consecuencias** y **Dónde está** (archivos y commits).

## Índice

| Nº | Decisión | Versión |
|---|---|---|
| [0001](0001-probabilidades-coherentes.md) | Un solo modelo de trayectorias para todas las probabilidades (más tope suave a la diferencia valor/precio) | 0.2.0 |
| [0002](0002-base-de-doce-meses-y-balance-reciente.md) | Base de ingresos de los últimos doce meses y balance reciente | 0.2.0 - 0.3.0 |
| [0003](0003-cordura-piso-y-cierre-anticipado.md) | Cordura del modelo (aviso), piso de valor y cierre anticipado | 0.2.0 |
| [0004](0004-router-fuerza-sobre-prioridad.md) | Router: la fuerza de la señal manda sobre la prioridad | 0.2.0 - 0.2.2 |
| [0005](0005-ciclicas-con-crecimiento.md) | Cíclicas que crecen: DCF de 10 años con convergencia del margen | 0.2.0 |
| [0006](0006-ajustes-del-juez-sobre-la-base.md) | El juez puede ajustar la base del motor, con límites | 0.2.0 |
| [0007](0007-beneficio-operativo-de-respaldo.md) | Beneficio operativo aproximado cuando el emisor no lo publica | 0.2.1 |
| [0008](0008-veredicto-relativo-a-la-partida.md) | Veredicto relativo a la probabilidad de partida de cada acción | 0.3.0 |
| [0009](0009-versionado-y-puntuacion.md) | Versionado y exclusión de predicciones antiguas de la puntuación | 0.2.0 |
| [0010](0010-instalacion-desde-github.md) | Instalación desde GitHub con alcance de usuario | 0.1.0 - 0.2.x |
| [0011](0011-correcciones-de-datos.md) | Correcciones de datos: sector de Coca-Cola, deuda de Nucor, codificación y forense | 0.2.0 - 0.3.0 |
| [0012](0012-dcf-inverso-sin-raiz-barato.md) | DCF inverso sin raíz: distinguir caro de barato | 0.3.1 |
| [0013](0013-beta-mixta-sector-y-propia.md) | Beta del WACC: mezcla del sector y la propia | 0.3.2 |
| [0014](0014-version-claude-ai-por-lentes.md) | Versión para claude.ai por lentes (propuesta, no toca el motor) | - |

Backtest del caso mecánico: [backtest-del-motor.md](backtest-del-motor.md) (resultados en `backtest-resultados.json`).
| [pruebas](pruebas-realizadas.md) | Registro de las pruebas con acciones reales y lo que destaparon | - |
| [limitaciones](limitaciones-conocidas.md) | Lo que el plugin todavía no hace bien | - |

## Cómo añadir una decisión

Copia el formato de cualquier nota, numérala con el siguiente número libre y añádela al índice. Si la decisión cambia
una regla del `SPEC.md` (Parte A), actualiza también el SPEC y enlaza la nota desde allí.

Estas notas son documentación para quien mantiene el plugin: no se copian a `SKILL.md`, a `references/` ni a los
prompts de los agentes (ver `CLAUDE.md`).
