# Versión para claude.ai (skill `analizar-accion-lentes`)

Alternativa al plugin de Claude Code que corre en un chat de claude.ai. No sustituye al plugin: ver
`docs/decisiones/0014-version-claude-ai-por-lentes.md`.

## Requisitos
- Ejecución de código activada (Settings → Capabilities). Sin ella `lentes.py` no corre.
- Conector Alpha Vantage (clave gratuita: 25 llamadas/día, 1/s, unas 4 acciones al día).
- Respaldo FMP (ya soportado en `lentes.py`): precios y estados de la acción. Limitaciones con el plan actual: 5 periodos
  por estado, sin el ETF VT (el índice sale de Alpha Vantage) y sin historial de revisiones (lente vacía).
- Opcionales: Bigdata.com para verificar lo cualitativo en el paso del abogado del diablo; Twelve Data (sin lector aún).

## Archivos
- `SKILL.md`: instrucciones del skill (flujo, formato de respuesta, diario de predicciones).
- `lentes.py`: cálculo determinista, solo biblioteca estándar. `python lentes.py --help`.

## Prueba
`pytest skills/analizando-acciones/tests/test_lentes.py`
