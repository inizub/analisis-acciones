---
description: Un ticker que no existe debe dar no_analizable sin agentes ni cifras inventadas
tags: [e2e, error]
runs: 1
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

/analisis-acciones:analizar ZZZQX rapido
