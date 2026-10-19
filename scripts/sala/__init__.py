"""Generadores de historias de la sala de prensa (uno por tema).

Cada módulo de esta carpeta expone:

    SECCION = "agua"            # una de SECCIONES (abajo)
    def generar(R, D) -> list:  # R = módulo redaccion_prensa (ayudas), D = R.Datos()

y devuelve historias hechas con R.historia(...) — el mismo formato que las del motor:

    h = R.historia(tipo, id_, kicker, tono, puntos, hechos, plantilla, cifras, fuentes, metodo, limites, pagina)
    h["seccion"] = SECCION
    h["fecha"] = "AAAA-MM-DD"   # fecha del dato que es noticia (por defecto, hoy)
    h["grafico"] = R.guardar_grafico(...)       # SVG + CSV con los datos del gráfico
    h["provincias"][cod] = {"provincia", "slug", "hechos", "plantilla", "cifras", "puntos", "grafico"?, "nivel"?}
    h["ultima_hora"] = [{"hora": "13:00", "texto": "...", "tono": "lluvia|calor|aviso"}]   # opcional

Reglas (las mismas que el motor):
- Solo datos medidos o publicados por un organismo oficial (AEMET, MITECO, confederaciones, Puertos del Estado,
  NOAA, Copernicus, ISCIII, EEA/MITECO calidad del aire, NASA FIRMS…), citados como tales. Una cifra de un lugar solo
  sale si se midió en ese lugar. Nada de reanálisis (ERA5) ni modelos presentados como medida.
- Cada cifra del texto está en un hecho; la plantilla tiene que pasar R.verificar(plantilla, hechos) sin errores.
- Fechas absolutas (R.dia(iso)), litros por metro cuadrado = mm, coma decimal (R.f1), cifras con número.
- puntos: 100 emergencia nacional · 90 récord confirmado o lluvia extrema · 70-85 suceso fuerte · 50-65 anomalía
  notable · 30-45 contexto · <30 relleno (no sale en portada).
- Un generador que falla no rompe la pasada: el motor lo envuelve en try/except y lo apunta en el registro.
"""

SECCIONES = {
    "ultima": "Última hora",
    "agua": "Lluvia y agua",
    "calor": "Calor y frío",
    "mar": "Mar y costa",
    "aire": "Aire y fuego",
    "planeta": "El planeta",
    "impacto": "Impacto",
}
