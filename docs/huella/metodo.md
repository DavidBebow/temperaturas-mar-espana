# Huella climática del día · método

Índice de −5 a +5 que dice cuánto más (o menos) probable es la temperatura de un día en el clima de hoy que en el de
hace unas décadas. Lo calcula calentamientoglobal.es para las 52 capitales de provincia. Datos: AEMET y ERA5
(Copernicus/ECMWF). Licencia CC BY 4.0.

## Dos climas

- ANTES = 1961-1990 · AHORA = 1996-2025. El día de hoy no entra en ninguno de los dos.

## Qué estaciones entran

- Estación de AEMET con valores diarios validados: ≥ 25 años válidos en cada clima (año válido = ≥ 90 % de
  los días con máxima y mínima) y homogeneidad «ok» en el control de /cambio-climatico-en-<provincia>/. Si falta el control
  («sin control»), la capital entra con citabilidad media. Con homogeneidad «dudosa» no entra: su salto de serie se
  confundiría con cambio climático.
- Las capitales cuya estación no cumple (serie corta, homogeneidad dudosa o sin estación larga) usan el reanálisis ERA5 en
  la celda de la capital, con citabilidad media y la fuente dicha en cada texto. ERA5 anterior a 1979 es una
  retroextensión preliminar: limita el clima de ANTES en esas capitales.

## Variables diarias (tmax, tmin, tmed = (tmax + tmin)/2)

1. Para el día D, la ventana de cada clima son los ±15 días del calendario alrededor de D en cada año (≈ 900 valores por
   clima). Un año cuenta si tiene ≥ 28 de los 31 días; hacen falta ≥ 25 años.
2. Ajuste normal (media y desviación) a cada ventana. Se comprueba con Kolmogorov-Smirnov (p asintótico); si p < 0.01
   se usa la distribución empírica con suavizado por kernel gaussiano de ancho de Silverman.
   Para que el cociente compare lo comparable, si el normal se rechaza en uno de los dos climas se usa la empírica en los dos.
3. Para el valor observado x: si x ≥ media del clima de antes, lado cálido, p = P(X ≥ x); si no, lado frío, p = P(X ≤ x),
   en cada clima. Periodo de retorno T = 1 / (31 · p) años (31 días de ventana por año).
4. Cociente de probabilidad PR = p_ahora / p_antes. Intervalo del 90 %: 200 remuestreos de años de cada clima, cuantiles 5 y 95. Si el
   intervalo incluye 1, la diferencia no es significativa.
5. Cola: si x queda más allá del percentil 99.5 del clima de ahora, la cola normal subestima. Entonces se usa una
   GEV (scipy.stats.genextreme, parámetros por L-momentos) sobre los máximos anuales (o mínimos, en el lado frío) del
   mes de D en cada clima; T y PR son entonces los del extremo anual del mes (T = 1/p en años).
6. Probabilidades por debajo de 1/1000 años (1/(31·1000) por día) se acotan: por encima de 1000 años no se distingue.

## Variables mensuales

Media del mes (normal, mismo KS) y lluvia del mes (gamma ajustada por máxima verosimilitud a los meses con lluvia, con la
mezcla de ceros de McKee, como en el Monitor de sequía; la función de sequia.py no se importa porque está atada a su
estructura de datos y se copia el ajuste). Mes en curso: media hasta el último día con dato frente a los mismos días de
cada año de los dos climas (≥ 10 días con dato); si el mes empieza, el último mes cerrado. T = 1/p años.

## Índice de huella (de −5 a +5), con la temperatura media del día

Solo se asigna nivel distinto de 0 si el PR es significativo. Lado cálido: +1 PR ≥ 1.5, +2 ≥ 2,
+3 ≥ 3, +4 ≥ 4, +5 ≥ 5. Lado frío: los mismos umbrales sobre 1/PR (el frío se ha
vuelto menos probable). Si no, 0.

| Nivel | Color | Texto |
|---|---|---|
| +5 | #8b1a1a | Nivel +5: un día así es hoy al menos cinco veces más probable que en 1961-1990 por el calentamiento |
| +4 | #b8321c | Nivel +4: un día así es hoy al menos cuatro veces más probable que en 1961-1990 por el calentamiento |
| +3 | #e0552b | Nivel +3: un día así es hoy al menos tres veces más probable que en 1961-1990 por el calentamiento |
| +2 | #f0a04b | Nivel +2: un día así es hoy al menos el doble de probable que en 1961-1990 por el calentamiento |
| +1 | #f2d27a | Nivel +1: un día así es hoy al menos 1,5 veces más probable que en 1961-1990 por el calentamiento |
| +0 | #9fb6c8 | Nivel 0: dentro de lo que ya era normal |
| -1 | #9fb6c8 | Nivel −1: un frío así era antes al menos 1,5 veces más probable que ahora |
| -2 | #8fb8e8 | Nivel −2: un frío así era antes el doble de probable que ahora |
| -3 | #6694ca | Nivel −3: un frío así era antes al menos tres veces más probable que ahora |
| -4 | #3d70ac | Nivel −4: un frío así era antes al menos cuatro veces más probable que ahora |
| -5 | #1f4e8c | Nivel −5: un frío así era antes al menos cinco veces más probable que ahora |

## Límites

- Compara dos climas observados; no atribuye un día concreto a una causa. «Por el calentamiento» resume que la diferencia
  entre los dos climas es el calentamiento observado.
- Un día no es una muestra independiente: la ventana de ±15 días mezcla días vecinos que se parecen. El intervalo
  remuestrea años enteros para respetarlo.
- El dato del último día es validado en las estaciones de AEMET (con 10-20 días de retraso) y preliminar en ERA5 durante
  los primeros 6 días.
- Cada capital tiene su último día con dato: el resumen nacional usa el día más reciente con dato en ≥ 80 % de
  las capitales, y nunca habla «de España» por debajo de ese porcentaje.

## Cómo citar

calentamientoglobal.es, Huella climática del día, <capital>, <fecha del dato>, datos AEMET/ERA5, cálculo propio, CC BY 4.0.
