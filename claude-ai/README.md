# Versión para claude.ai (skill `analizar-accion-lentes`)

Alternativa al plugin de Claude Code que corre en un chat de claude.ai. No sustituye al plugin: ver
`docs/decisiones/0014-version-claude-ai-por-lentes.md`.

## Requisitos
- Ejecución de código activada (Settings → Capabilities). Sin ella `lentes.py` no corre.
- Conector Alpha Vantage (clave gratuita: 25 llamadas/día, 1/s, unas 4 acciones al día).
- Opcionales: Twelve Data o FMP como segunda fuente de números (requieren un lector en `lentes.py`, hoy solo lee el
  formato de Alpha Vantage) y Bigdata.com para verificar lo cualitativo en el paso del abogado del diablo.

## Archivos
- `SKILL.md`: instrucciones del skill (flujo, formato de respuesta, diario de predicciones).
- `lentes.py`: cálculo determinista, solo biblioteca estándar. `python lentes.py --help`.

## Prueba
`pytest skills/analizando-acciones/tests/test_lentes.py`
