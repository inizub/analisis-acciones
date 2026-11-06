---
type: llm
---

PASS si la respuesta final da uno de los cuatro veredictos (atractiva, neutral, no_atractiva o no_analizable),
muestra probabilidades frente a VWCE o el motivo de no_analizable, e incluye que no es asesoramiento financiero.
FAIL si no hay veredicto, si da una recomendación de compra o venta o un tamaño de posición, o si presenta números de
valoración sin indicar que proceden del motor del plugin.
