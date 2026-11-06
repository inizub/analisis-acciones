# CLAUDE.md

## Proyecto
Plugin de Claude Code `analisis-acciones`: recibe un ticker y devuelve un análisis de una acción con veredicto, probabilidades y registro en un diario de predicciones.

## Antes de cualquier tarea
1. Lee `SPEC.md`.
2. La **Parte A** es la especificación: es lo que hay que construir.
3. La **Parte B** es solo contexto. No la copies nunca a prompts de agentes, `SKILL.md` ni `references/`: estos contienen únicamente instrucciones operativas (qué hacer, con qué entradas, qué formato de salida).
4. Si una decisión de la Parte A es inviable o contradice la Parte B, pregunta antes de cambiarla.

## Cambios respecto a SPEC.md
- No se usará Gemini ni ningún modelo externo. En `assets/config.yaml`, `red_team_externo.activo: false`. El red team lo hace siempre el subagente `red-team` (Claude).
- No construyas `red_team_externo.py` hasta que se pida expresamente.
- El repo debe incluir `.claude-plugin/marketplace.json` en la raíz para poder instalarlo desde GitHub.

## Cómo trabajar
- Python ≥ 3.11 con `uv`. Dependencias en `requirements.txt`.
- Trabaja por bloques grandes, siguiendo el orden de la sección A15 del spec. Al terminar cada bloque: ejecuta `pytest`, corrige los fallos y haz commit con un mensaje descriptivo.
- Los scripts son deterministas, con CLI (`argparse`) y entrada/salida en JSON. Los cálculos van en código, nunca en el LLM.
- Nunca inventes ni estimes datos financieros. Lo que no se encuentra se marca `desconocido` con su causa.
- No subas a git claves, `.env`, cachés ni datos de ejecuciones. Crea el `.gitignore` en el primer bloque.
- Idioma: documentación, comentarios y mensajes en español.
- Antes de dar un bloque por terminado, muestra qué has creado y cómo se prueba.
