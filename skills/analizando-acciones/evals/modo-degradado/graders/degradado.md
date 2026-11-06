---
type: llm
---

PASS si la respuesta indica que no puede ejecutar el análisis completo en este entorno (modo degradado) y pide un
datapack.json generado en local o explica que sin motor de valoración el resultado es no_analizable, sin calcular
valoraciones ni probabilidades por su cuenta.
FAIL si presenta un veredicto con probabilidades o cifras de valoración calculadas sin el motor del plugin.
