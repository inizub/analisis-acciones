# Juez: procedimiento

## 1. Verificar cada objeción

Para cada objeción de `objeciones.json`:

1. Abre el `dato_ref` que cita y comprueba la `prueba` que propone.
2. `validada` si el dato confirma la objeción; `rechazada` si el dato la contradice o no la sostiene.
3. Escribe el motivo en una frase y el `dato_ref` que usaste para decidir. Rechazar exige citar un dato.

## 2. Ajustes

Una objeción validada que cambia un input se convierte en un ajuste:

- `analista` (A, B o todos), `driver`, `escenario` (o todos), `valor_anterior` (el valor exacto que tenía el
  analista), `valor_nuevo`, `objecion_ref` y `motivo`.
- El nuevo valor es el que sostiene el dato, no un compromiso entre posiciones.
- Una objeción validada que no cambia ningún driver (por ejemplo, un riesgo ya recogido) no genera ajuste.
- No cambies probabilidades de escenarios con ajustes: solo drivers.

Si hay ajustes, ejecuta `motor/escenarios.py` con `--ajustes` (ver tu encargo) para ver cómo cambian el valor y las
probabilidades, y tenlo en cuenta al redactar las razones.

## 3. Razones, contraargumento e invalidación

- **Tres razones principales** del resultado, cada una apoyada en un dato.
- **Mejor contraargumento:** el más sólido de los que quedan tras la verificación (puede ser el del red team).
- **Criterios de invalidación** (al menos dos): un dato observable en los próximos informes, un umbral y el efecto
  esperado. Ejemplo: `{"dato": "ROE del T1", "umbral": "< 20 %", "efecto": "el escenario base deja de sostenerse; p(E1) baja de forma clara"}`.

## 4. Desacuerdos

Si A y B difieren en un driver o en la lectura del DCF inverso, anota el tema y la posición de cada uno. No elijas un
ganador si los datos no lo deciden.
