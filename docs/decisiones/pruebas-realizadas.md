# Pruebas realizadas con acciones reales

Todas en modo rápido y con un diario de prueba aparte (el diario del usuario no se tocó). Cada fila indica qué parte del
plugin ejercitaba y qué fallo destapó. Fechas: 6-7 de noviembre de 2026.

| Acción | Qué probaba | Resultado | Fallo destapado y qué se hizo |
|---|---|---|---|
| **NVDA** (completo, 2 veces) | Empresa de crecimiento extremo | 1.ª: 81 % de caer ≥30 %; 2.ª: no atractiva | Base de ingresos desfasada, probabilidades incoherentes, ruta mal asignada, juez que estima ([0001](0001-probabilidades-coherentes.md) a [0006](0006-ajustes-del-juez-sobre-la-base.md)) |
| **KO** | Empresa estable de marca | no atractiva (32 % de batir, 10 % de caer ≥30 %) | Sector mal asignado (alcohólicas): SIC 2080; deuda desactualizada |
| **FCX** | Minera cíclica | no atractiva (36 %, 37 %) | Router la mandó a `crecimiento_perdidas` ([0004](0004-router-fuerza-sobre-prioridad.md)) |
| **NUE** | Cíclica sin beneficio operativo | no atractiva (38 %, 26 %) | Sin `OperatingIncomeLoss`; deuda con otro concepto ([0007](0007-beneficio-operativo-de-respaldo.md)) |
| **RIVN** | Empresa con pérdidas | `no_analizable` (el balance no sobrevive al bajista) | El motor abortaba con valores negativos ([0003](0003-cordura-piso-y-cierre-anticipado.md)) |
| **ABN.AS** | Banco europeo sin SEC | `no_analizable` | Sin datos primarios (HTTP 503); sin SIC el router no detecta un banco ([limitaciones](limitaciones-conocidas.md)) |
| **BRK-B** | Holding / aseguradora | `no_analizable` (fuera de alcance, SIC 6331) | Ninguno: es el comportamiento diseñado |
| **VZ** | Empresa estable, barata | **neutral** (46 %, 12 %) | Ninguno |
| **VLO** | Refinería cíclica, barata | **neutral** (41 %, 28 %) | Router por crecimiento que sigue al crudo ([0004](0004-router-fuerza-sobre-prioridad.md)) |

Las acciones se eligieron con un filtro de múltiplos reales (EV/EBITDA y rentabilidad de caja libre) sobre 30 acciones
estadounidenses para las candidatas baratas (Verizon, Valero).

## Lo que estas pruebas no demostraron
- Ningún análisis real salió **"atractiva"**. Se comprobó solo con acciones sintéticas ([0008](0008-veredicto-relativo-a-la-partida.md)).
- La fiabilidad de las probabilidades de caída (E3) frente a la realidad: eso lo medirá el diario cuando se resuelvan predicciones.
- Ninguna empresa con 20-F/ADR ni con moneda de informe distinta de USD/EUR.
