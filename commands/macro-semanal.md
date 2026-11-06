---
description: Actualiza el régimen macro semanal (tipos, crédito, curva, tasa sin riesgo en EUR y ERP)
---

Ejecuta:

```
bash "${CLAUDE_PLUGIN_ROOT}/skills/analizando-acciones/scripts/py.sh" "${CLAUDE_PLUGIN_DATA}" macro.py regimen --salida "${user_config.journal_dir}/macro/macro_regime.json"
```

Muestra al usuario las etiquetas de tipos, crédito y curva, la tasa sin riesgo en USD y en EUR, la ERP y la fecha de
cada dato. Si algún campo es `desconocido`, di cuál y su causa. No añadas interpretaciones propias.
