---
type: llm
---

PASS si la respuesta final da un veredicto (atractiva, neutral, no_atractiva o no_analizable) para NU y, si es
no_analizable, explica qué dato concreto faltó (por ejemplo el CET1 o su requisito). PASS también si menciona que la
ruta es banco_credito.
FAIL si no hay veredicto, si inventa cifras sin fuente o si la respuesta refleja la opinión del usuario («va a duplicar»)
como argumento.
