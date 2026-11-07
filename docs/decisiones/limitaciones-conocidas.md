# Limitaciones conocidas

Lo que el plugin todavía no hace bien, con su causa y la salida más probable. Actualizado el 7-nov-2026 (v0.3.0).

| Limitación | Causa | Qué haría falta |
|---|---|---|
| **Bancos y empresas europeas sin registro SEC** acaban en `no_analizable` | EDGAR no los cubre; el agente de datos depende de sitios que pueden caer (ABN Amro devolvió HTTP 503); sin SIC el router no detecta un banco y lo trata como ruta general | Una fuente de datos de empresas europeas (ESEF u otra) y que el router use la industria del proveedor de precios cuando falte el SIC |
| **Solo una ejecución activa a la vez** | El estado se guarda en un único `ejecucion_activa.json` y los hooks de validación dependen de él | Un archivo de estado por ejecución |
| **"Atractiva" aún no se ha visto con datos reales** | Es exigente: hace falta ~2× de infravaloración (volatilidad 20 %) o ~3× (40 %) | Probar acciones realmente baratas; revisar la ventaja de 0,06 con el diario |
| **Probabilidad de caída ≥30 % sin calibrar** | Viene del modelo con peso k = 0,4 y tope 2×, sin datos de resolución todavía | Esperar a que se resuelvan predicciones y calibrar (`puntuar.py`) |
| **El balance de una empresa sin trimestres sigue siendo el del último ejercicio** | EDGAR anual no trae saldos trimestrales; los trae el agente de datos | Que el agente los traiga siempre (ya se le pide) y verificar con el texto del filing |
| **El agente de datos a veces lee resúmenes, no el filing completo** | Herramientas de búsqueda; varios informes lo declaran | Exigir contraste con el texto del filing o un cliente directo de XBRL trimestral |
| **El margen de `ttm_ingresos` es el del último ejercicio** | No hay resultado operativo trimestral con fuente | Un cálculo del resultado operativo de 12 meses cuando exista la serie |
| **Solo emisores que informan en USD o EUR** | Tasa sin riesgo solo para esas monedas | Añadir curvas de otras monedas |
| **Las tasas base de EDGAR no distinguen sector** | Datos disponibles | Datos por sector |
| **El forense solo marca "grave" tras dos años seguidos** | Regla del SPEC (A6.5) | Se añadió una bandera informativa del último año ([0011](0011-correcciones-de-datos.md)) |

## Pendientes de decisión del usuario
- Si el bloqueo por cordura (`cordura.bloquea`) debe activarse (hoy es aviso).
- Si se quiere otro valor de `ventaja_atractiva` (0,06) tras ver acciones baratas reales.
