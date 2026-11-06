---
description: Resuelve las predicciones vencidas del diario y, si se pide, escribe el informe trimestral de puntuación
argument-hint: "[informe]"
---

1. Ejecuta:

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/skills/analizando-acciones/scripts/py.sh" "${CLAUDE_PLUGIN_DATA}" resolver.py resolver --diario "${user_config.journal_dir}/diario/predicciones.jsonl"
   ```

2. Muestra al usuario cuántas preguntas se han resuelto, cuántas se han anulado y por qué, y cuántas quedan
   pendientes. Si alguna anulación dice «posible OPA, exclusión de cotización o fallo de datos», pregúntale si sabe la
   causa; si la confirma, anula con esa causa usando `resolver.py anular` (ver `references/diario.md` del skill).

3. Si la entrada es `informe` ($ARGUMENTS), ejecuta también:

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/skills/analizando-acciones/scripts/py.sh" "${CLAUDE_PLUGIN_DATA}" puntuar.py informe --diario "${user_config.journal_dir}/diario/predicciones.jsonl"
   ```

   y muestra el informe que escribe en `${user_config.journal_dir}/diario/informes/`.

No interpretes los resultados más allá de lo que dice el informe.
