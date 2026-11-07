# 0012. DCF inverso sin raíz: distinguir "demasiado caro" de "demasiado barato"

**Estado:** aplicada (v0.3.1). **Fecha:** 7-nov-2026.

## Contexto
La regla de "no atractiva" incluía "DCF inverso sin raíz", pensada para precios que ni con el mejor crecimiento del
rango (+60 %) se justifican. Pero "sin raíz" también ocurre en el sentido contrario: con el peor crecimiento (−20 %) el
modelo ya vale más que el precio. Es lo que pasó con Comcast (precio 24,4 frente a valor mecánico 40,8): el motor dio
p(E1) = 52 %, exceso +5,3 pp y pérdida bajista 0 %, y aun así el veredicto salió "no atractiva" por esa regla.
Una acción barata se castigaba como si fuera cara. Se descubrió al analizar una cesta de acciones baratas
(batería del 7-nov-2026).

## Decisión
Cada resolutor del DCF inverso devuelve `sentido` cuando no hay raíz: `"caro"` (ni con el valor más alto del rango se
alcanza el precio) o `"barato"` (ya con el valor más bajo el modelo supera el precio). La regla de "no atractiva" solo
se activa con `"caro"`. Los resolutores de años de ventaja siempre dan `"caro"`.

## Alternativas descartadas
- Quitar la regla: perdería la señal de precios imposibles de justificar.
- Tratar "barato" como condición propia de "atractiva": las cuatro condiciones numéricas ya cubren esa lectura y se
  evita duplicarla.

## Consecuencias
- Comcast pasa de "no atractiva" a "atractiva": primer veredicto atractivo con datos reales. Quedan avisos de datos
  (balance de hace 10 meses, definición de deuda distinta entre EDGAR y el agente) que conviene revisar antes de fiarse.
- Salidas antiguas sin `sentido` se interpretan como "caro" (comportamiento anterior).

## Archivos
`scripts/motor/reverse_dcf.py`, `scripts/motor/inicial.py`, `scripts/agregar.py`; tests en `tests/test_motor.py` y
`tests/test_agregar.py`.
