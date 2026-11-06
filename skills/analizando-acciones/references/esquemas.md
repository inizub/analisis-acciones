# Formato de los archivos JSON

Índice:

1. Cifra (formato común)
2. datos_agente.json (agente datos)
3. analista_X.json (analistas)
4. forense.json (forense)
5. objeciones.json (red team)
6. ajustes.json (juez)
7. juez.json y sintesis.json
8. Archivos que genera el código (datapack, motor_inicial, escenarios, verdict)

Los esquemas completos están en `assets/schemas/`. Ratios y porcentajes siempre como fracción (8 % = `0.08`).
Fechas en formato `AAAA-MM-DD`.

## 1. Cifra

Cada dato numérico:

```json
{"valor": 1234000000, "unidad": "unidades", "moneda": "USD",
 "fuente_url": "https://www.sec.gov/...", "fecha_dato": "2025-12-31", "fecha_obtencion": "2026-11-06T10:00:00Z"}
```

- `unidad`: `unidades` (importes), `acciones`, `ratio`, `veces` (múltiplos), `por_accion`.
- `moneda`: la del documento; `null` para ratios y acciones.
- Un dato que no se encuentra: `{"desconocido": true, "causa": "not_covered"}` (causas: `not_covered`,
  `source_down`, `rate_limited`, `stale`).
- Una serie anual: `{"concepto": "texto", "serie": [cifra, cifra, ...]}` en orden cronológico.

## 2. datos_agente.json

Todas las claves son opcionales; incluye solo lo que encuentres.

```json
{
  "fundamentales": {"gasto_intereses": {"concepto": "Interest expense (10-K)", "serie": [<cifra>, <cifra>]}},
  "trimestrales": {"ingresos": {"concepto": "Ingresos trimestrales (6-K)", "serie": [<cifra con "periodo_inicio">]}},
  "banca": {"morosidad": <serie o cifra>, "coste_riesgo": <...>, "cet1": <...>, "cet1_requisito": <...>,
            "capital_total": <...>, "capital_total_requisito": <...>,
            "crecimiento_prestamos": <...>, "crecimiento_depositos": <...>},
  "segmentos": [{"nombre": "Brasil", "tipo": "geografia", "ingresos": <cifra>},
                {"nombre": "BRL", "tipo": "moneda", "ingresos": <cifra>},
                {"nombre": "Tarjetas", "tipo": "negocio", "ingresos": <cifra>, "beneficio_operativo": <cifra>,
                 "multiplo_ev_ebit": <cifra>, "industria_damodaran": "Banks (Regional)"}],
  "guidance": [{"metrica": "Crecimiento de ingresos 2026", "valor": <cifra>, "valor_max": <cifra>, "periodo": "FY2026"}],
  "hechos_recientes": [{"fecha": "2026-10-30", "tipo": "resultados", "resumen": "≤ 600 caracteres", "fuente_url": "https://..."}],
  "cambios": {"auditor": [<nota>], "politicas_contables": [<nota>], "factores_riesgo": [<nota>], "opinion_auditoria": [<nota>]},
  "extractos_filings": [{"fecha": "2026-04-08", "tema": "partes vinculadas", "resumen": "...", "fuente_url": "https://..."}],
  "pipeline": [{"nombre": "X-101", "fase": "III", "area": "oncology", "indicacion": "...", "ventas_pico": <cifra>,
                "proximo_hito": "Lectura de fase III en 2027", "fuente_url": "https://...", "fecha_dato": "2026-09-30"}],
  "deuda": {"tipo_variable_pct": <cifra>, "vencimientos_24m": <cifra>},
  "holding_coste_anual": <cifra>,
  "empresa": {"ratio_adr": <cifra en acciones>, "holding_declarada": false, "en_concurso": false},
  "no_encontrados": [{"campo": "banca.cet1_requisito", "causa": "not_covered"}],
  "fuentes": [{"url": "https://...", "retrieved_at": "2026-11-06T10:00:00Z", "published_at": "2026-10-30"}]
}
```

- `<nota>` = `{"fecha", "resumen", "fuente_url"}` y opcionalmente `tipo` o `tema`.
- `fundamentales`: solo campos que el datapack base tiene desconocidos o desactualizados (el resto se ignora).
- `pipeline.fase`: `I`, `II`, `III` o `NDA`. `pipeline.area`: allergy, autoimmune, cardiovascular, endocrine,
  gastroenterology, hematology, infectious_disease, metabolic, neurology, oncology, ophthalmology, others, psychiatry,
  respiratory, urology.
- `cet1_requisito`: el mínimo regulatorio total de CET1 de la entidad (incluidos colchones), como fracción.
- Si la entidad no publica CET1 (p. ej. conglomerados prudenciales de instituciones de pago), usa `capital_total`
  (ratio de capital regulatorio total) y `capital_total_requisito` (su mínimo). No pongas un ratio en el campo de otro.

## 3. analista_X.json

```json
{
  "ticker": "XYZ", "fecha_analisis": "2026-11-06", "encuadre": "A", "ruta": "general",
  "tipologia": "solida",
  "narrativa": "≤ 5 frases (20-1200 caracteres)",
  "moat": {"fuente": "costes_cambio", "amplitud": "estrecho",
           "evidencia": [{"afirmacion": "ROIC − WACC medio de 5 años de +8 pp", "dato_ref": "fundamentales.beneficio_operativo", "valor": 0.08}]},
  "gestion": {"valoracion": "adecuada", "evidencia": [{"afirmacion": "...", "dato_ref": "fundamentales.recompras"}]},
  "escenarios": [
    {"nombre": "bajista", "p": 0.25, "descripcion": "...",
     "drivers": {"crecimiento_ingresos": {"valor": 0.03, "justificacion": "...", "percentil_tasa_base": 40, "z": -0.3},
                 "margen_operativo": {"valor": 0.15, "justificacion": "...", "percentil_tasa_base": 45, "z": -0.1}},
     "valor_metrica_e4": 0.02,
     "perdida_permanente": {"descripcion": "...", "magnitud": 0.35}},
    {"nombre": "base", "p": 0.5, "descripcion": "...", "drivers": {...los mismos...}, "valor_metrica_e4": 0.08},
    {"nombre": "alcista", "p": 0.25, "descripcion": "...", "drivers": {...los mismos...}, "valor_metrica_e4": 0.13}
  ],
  "lectura_dcf_inverso": {"expectativa_implicita": "...", "opinion": "razonable", "argumento": "..."},
  "catalizador": {"descripcion": "...", "horizonte_meses": 6},
  "pre_mortem": ["causa 1", "causa 2", "causa 3"],
  "metrica_e4": {"metrica": "crecimiento_ingresos", "valor_base": 0.08, "unidad": "ratio", "periodo": "FY2026"}
}
```

- `encuadre`: `A`, `B` o `N`. `ruta`: la del encargo.
- `tipologia`: crecimiento_lento, solida, crecimiento_rapido, ciclica, recuperacion, activos_ocultos.
- `moat.fuente`: activos_intangibles, costes_cambio, efecto_red, ventaja_costes, escala_eficiente, ninguna.
  `moat.amplitud`: ninguno, estrecho, amplio.
- `gestion.valoracion`: buena, adecuada, deficiente, sin_evidencia.
- `lectura_dcf_inverso.opinion`: exigente, razonable, conservadora.
- `escenarios`: exactamente bajista, base y alcista; cada `p` entre 0 y 1 (sin incluirlos) y suman 1. Los tres con
  los mismos drivers. El bajista con `perdida_permanente`.
- Un driver: `valor` (número o lista de números anuales), `justificacion`, y opcionalmente `percentil_tasa_base`
  (0-100), `z`, `evidencia_excepcional` (obligatorio si z > 2) y `dato_ref`.
- `metrica_e4.metrica`: `crecimiento_ingresos`, `roe` o `hito_clinico`, según la ruta.
- Consulta de ruta: `confirmacion_ruta.json` = `{"mantiene": true}` o
  `{"mantiene": false, "ruta_propuesta": "ciclica", "dato_ref": "fundamentales.beneficio_operativo", "motivo": "..."}`.

## 4. forense.json

```json
{"ticker": "XYZ", "fecha_analisis": "2026-11-06",
 "banderas": [{"bandera": "FCO/beneficio neto de 3 años = 0,62", "nivel": "grave", "origen": "cuantitativa",
               "dato_ref": "forense_metricas.fco_beneficio_neto", "metrica": "fco_beneficio_neto", "justificacion": "..."}],
 "resumen": "≤ 800 caracteres"}
```

`nivel`: informativa, grave, invalidante. `origen`: cuantitativa, cualitativa.

## 5. objeciones.json

```json
{"ticker": "XYZ", "fecha_analisis": "2026-11-06", "fuente": "claude", "modelo": "sonnet",
 "objeciones": [{"id": "O1", "tipo": "supuesto_implausible", "dato_ref": "tasas_base.observados.crecimiento_ventas_5a",
                 "objecion": "...", "prueba": "cómo verificarla",
                 "impacto_estimado": {"driver": "crecimiento_ingresos", "escenario": "alcista", "analista": "A",
                                      "direccion": "baja", "magnitud": 0.03},
                 "severidad": "alta"}],
 "mejor_contraargumento": "...", "pre_mortem": ["...", "...", "..."]}
```

`tipo`: dato_erroneo, supuesto_implausible, riesgo_omitido, contradiccion_interna. `severidad`: baja, media, alta.
`impacto_estimado.escenario`: bajista, base, alcista o todos; `analista`: A, B o todos. Ids `O1`, `O2`…

## 6. ajustes.json

```json
{"ticker": "XYZ", "fecha_analisis": "2026-11-06",
 "ajustes": [{"analista": "A", "driver": "crecimiento_ingresos", "escenario": "alcista",
              "valor_anterior": 0.14, "valor_nuevo": 0.11, "objecion_ref": "O1", "motivo": "..."}]}
```

`valor_anterior` debe coincidir exactamente con el valor del analista (o `null` si no se comprueba);
`valor_nuevo` distinto de `valor_anterior`. `analista`: A, B o todos; `escenario`: bajista, base, alcista o todos.

## 7. juez.json y sintesis.json

```json
{"ticker": "XYZ", "fecha_analisis": "2026-11-06",
 "razones": ["razón 1", "razón 2", "razón 3"],
 "mejor_contraargumento": "...",
 "criterios_invalidacion": [{"dato": "ROE del T1", "umbral": "< 20 %", "efecto": "la tesis del escenario base deja de sostenerse"},
                            {"dato": "...", "umbral": 0.18, "efecto": "..."}],
 "desacuerdos": [{"tema": "...", "posicion_A": "...", "posicion_B": "..."}],
 "objeciones_verificadas": [{"id": "O1", "veredicto": "validada", "motivo": "...", "dato_ref": "..."}]}
```

Exactamente tres razones. Al menos dos criterios de invalidación. `sintesis.json` (modo rápido) usa el mismo formato
sin `desacuerdos` ni `objeciones_verificadas`.

## 8. Archivos que genera el código

- **datapack.json:** `tasas_base` (clase, `observados` con percentil, z y valor encogido, y `para_reverse_dcf` con la
  media y la desviación de la clase), `empresa`, `fundamentales` (series anuales de EDGAR), `precios` (precio, EUR,
  métricas relativas a VWCE), `damodaran` (ERP, prima país, sector, tabla de ratings), `verificacion_cruzada`,
  `campos_desconocidos`, `fuentes` y lo que añadió el agente datos.
- **motor_inicial.json:** `base` (inputs de valoración en la moneda del informe por acción ordinaria: precio0,
  ingresos0, wacc, márgenes, ventas_capital, crecimiento…), `caso_mecanico` (valor con drivers de tasas base),
  `reverse_dcf.principal` (driver implícito en el precio, su valor, percentil, z y `sin_raiz`) y `supuestos` (WACC,
  conversión de moneda y avisos).
- **escenarios_X.json:** valor por escenario y su relación con el precio, probabilidades E0-E4, percentiles del retorno
  relativo a 12 meses, exceso anual esperado y pérdida bajista.
- **verdict.json:** el veredicto, las preguntas E0-E4 preregistradas y todo lo anterior resumido; se añade al diario.
