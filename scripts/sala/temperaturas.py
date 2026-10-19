"""Temperaturas medidas en estaciones de AEMET (nada de reanálisis).

Historias:
  · Récord de días de más de 32 °C en el año (docs/dias32_estaciones.json): la estación principal de cada capital,
    con su serie anual desde 1961. Solo cuenta como récord frente a los años con datos completos (≥ 330 días) y si la
    serie tiene al menos 25 de esos años; como 2026 no ha terminado, la cifra solo puede subir («ya»).
  · Noches tropicales fuera del verano (docs/temperaturas_nocturnas.json): mínima diaria de 20 °C o más en la
    estación de AEMET de cada ciudad (valores climatológicos diarios, que AEMET publica con unos días de retraso).
  · A un paso del récord del mes (docs/records/hoy.json): estaciones con serie larga (30 años o más) que el día
    cerrado se quedaron a menos de 0,5 °C de su récord mensual. Los récords batidos son de g_records_estaciones.
"""
from __future__ import annotations

from datetime import date, timedelta

SECCION = "calor"

FUENTE32 = "AEMET OpenData · valores climatológicos diarios de la estación principal de cada capital"
FUENTE_NOCHE = "AEMET OpenData · valores climatológicos diarios"
FUENTE_REC = "AEMET OpenData · observación y valores climatológicos extremos"
PAGINA32 = "https://calentamientoglobal.es/dias-de-mas-de-32-grados/"
PAGINA_NOCHE = "https://calentamientoglobal.es/noches-tropicales/"
CANARIAS = {"35", "38"}

NOCHE_COD = {"sevilla": "41", "malaga": "29", "granada": "18", "cordoba": "14", "almeria": "04", "huelva": "21", "cadiz": "11",
             "jaen": "23", "motril": "18", "valencia": "46", "alicante": "03", "castellon": "12", "murcia": "30", "cartagena": "30",
             "lorca": "30", "barcelona": "08", "tarragona": "43", "lleida": "25", "girona": "17", "madrid": "28", "toledo": "45",
             "ciudad_real": "13", "albacete": "02", "valladolid": "47", "salamanca": "37", "burgos": "09", "leon": "24",
             "zaragoza": "50", "huesca": "22", "teruel": "44", "bilbao": "48", "san_sebastian": "20", "vitoria": "01", "vigo": "36",
             "coruna": "15", "santiago": "15", "oviedo": "33", "santander": "39", "pamplona": "31", "logrono": "26", "badajoz": "06",
             "caceres": "10", "palma": "07", "ibiza": "07", "mahon": "07", "las_palmas": "35", "santa_cruz_tf": "38", "ceuta": "51",
             "melilla": "52"}
NOCHE_NOMBRE = {"las_palmas": "Las Palmas de Gran Canaria", "santa_cruz_tf": "Santa Cruz de Tenerife", "san_sebastian": "San Sebastián",
                "vitoria": "Vitoria", "santiago": "Santiago de Compostela"}


def _capital(R, cod):
    return ((R.leer(R.PRENSA / "partes" / f"{cod}.json", {}) or {}).get("capital")) or R.nprov(cod)


def _donde(est, ciudad, forma="en"):
    """«Cáceres» y no «Cáceres, en Cáceres»: la ciudad solo se añade si la estación no la nombra ya."""
    import unicodedata
    n = lambda x: unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()
    if n(ciudad.split("-")[0].split(" de ")[0]) in n(est):
        return est
    return f"{est}, en {ciudad}" if forma == "en" else f"{est} ({ciudad})"


def _cod_de_slug(R, slug):
    m = {v[1].replace("-", "_"): k for k, v in R.PROV.items()}
    m.update({"sc_tenerife": "38", "santa_cruz_de_tenerife": "38"})
    return m.get(slug)


# ============================================================================ días de más de 32 °C
def _serie32(e, anio):
    ok = [(int(y), v[0]) for y, v in (e.get("anios") or {}).items() if int(y) < anio and v and len(v) >= 2 and v[1] >= 330]
    return sorted(ok)


def grafico32_nacional(R, filas, nombre):
    """Barras dobles: 2026 frente al máximo anterior de cada estación con récord."""
    W, fila, ml, mr, mt = 640, 30, 190, 70, 18
    Hh = mt + fila * len(filas) + 30
    mx = max(max(f["dias"], f["mx"]) for f in filas)
    X = lambda v: ml + v / mx * (W - ml - mr)
    c = []
    for i, f in enumerate(filas):
        y = mt + i * fila
        c.append(R._t(ml - 8, y + 15, f["capital"], 12, R.TINTA, "end", 600))
        c.append(f'<rect x="{ml}" y="{y + 3:.1f}" width="{X(f["dias"]) - ml:.1f}" height="11" fill="{R.CALOR}"/>')
        c.append(R._t(X(f["dias"]) + 5, y + 13, f["dias"], 11, R.TINTA, "start", 700))
        c.append(f'<rect x="{ml}" y="{y + 16:.1f}" width="{X(f["mx"]) - ml:.1f}" height="7" fill="#C9C1B6"/>')
        c.append(R._t(X(f["mx"]) + 5, y + 24, f'{f["mx"]} ({f["anio_mx"]})', 10, R.GRIS))
    svg = R._svg(W, Hh, "Días de más de 32 °C en 2026 frente al récord anterior de cada estación", c)
    leyenda = [{"t": "banda", "c": R.CALOR, "l": "2026, hasta mediados de octubre"}, {"t": "banda", "c": "#C9C1B6", "l": "Récord anterior (año)"}]
    pie = ("Días con máxima de más de 32 °C en la estación principal de AEMET de cada capital. Récord anterior: el año con más días entre "
           "los que tienen datos completos (330 días o más). Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.")
    return R.guardar_grafico(nombre, svg, [(f["capital"], f["est"], f["dias"], f["hasta"], f["mx"], f["anio_mx"]) for f in filas],
                             ["capital", "estacion_AEMET", "dias_2026", "hasta", "record_anterior_dias", "anio_record_anterior"],
                             "Días de más de 32 °C: 2026 frente al récord anterior", leyenda, pie)


def grafico32_serie(R, f, nombre):
    serie = f["serie"] + [(f["anio"], f["dias"])]
    W, Hh, ml, mr, mt, mb = 640, 260, 36, 12, 26, 30
    a0, a1 = serie[0][0], serie[-1][0]
    mx = max(v for _, v in serie) or 1
    n = a1 - a0 + 1
    bw = (W - ml - mr) / n
    X = lambda a: ml + (a - a0) * bw
    Y = lambda v: mt + (1 - v / mx) * (Hh - mt - mb)
    c = []
    for t in range(0, mx + 1, 20 if mx > 60 else 10):
        c.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{R.RAYA}" stroke-width="1"/>')
        c.append(R._t(ml - 5, Y(t) + 4, t, 10, R.GRIS, "end"))
    for a, v in serie:
        col = R.CALOR if a == f["anio"] else ("#9E9589" if a == f["anio_mx"] else "#D9D2C7")
        c.append(f'<rect x="{X(a) + bw * 0.12:.1f}" y="{Y(v):.1f}" width="{bw * 0.76:.1f}" height="{Y(0) - Y(v):.1f}" fill="{col}"/>')
    for a in range(a0 - a0 % 10 + 10, a1 + 1, 10):
        c.append(R._t(X(a) + bw / 2, Hh - mb + 16, a, 10, R.GRIS, "middle"))
    c.append(R._t(X(f["anio"]) + bw / 2, Y(f["dias"]) - 6, f"{f['anio']}: {f['dias']}", 11, R.CALOR, "end", 700))
    svg = R._svg(W, Hh, f"Días de más de 32 °C al año en la estación de AEMET de {f['est']}", c)
    leyenda = [{"t": "banda", "c": R.CALOR, "l": f"{f['anio']} (hasta el {R.dia(f['hasta'], semana=False)})"},
               {"t": "banda", "c": "#9E9589", "l": f"Récord anterior ({f['anio_mx']})"}]
    pie = (f"Días con máxima de más de 32 °C en la estación de AEMET de {f['est']}. Solo años con 330 días o más de dato. "
           f"Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.")
    return R.guardar_grafico(nombre, svg, serie, ["anio", "dias_mas_32C"], f"Días de más de 32 °C al año en {f['capital']}", leyenda, pie)


def historia_dias32(R):
    J = R.leer(R.DOCS / "dias32_estaciones.json", {}) or {}
    filas = []
    for slug, e in (J.get("estaciones") or {}).items():
        a = e.get("actual") or {}
        cod = _cod_de_slug(R, slug)
        if not cod or a.get("estacion_parada") or not a.get("dias") or not a.get("hasta"):
            continue
        serie = _serie32(e, a["anio"])
        if len(serie) < 25:
            continue
        mx = max(v for _, v in serie)
        anios_mx = [y for y, v in serie if v == mx]
        faltan = max(0, (a.get("dias_esperados") or 0) - (a.get("dias_con_dato") or 0))
        filas.append({"cod": cod, "slug": slug, "capital": _capital(R, cod), "est": e["estacion"], "dias": a["dias"], "anio": a["anio"],
                      "hasta": a["hasta"], "faltan": faltan, "serie": serie, "n": len(serie), "primero": serie[0][0], "mx": mx,
                      "anio_mx": anios_mx[-1], "anios_mx": anios_mx, "media": e.get("media_1991_2020")})
    if not filas:
        return None
    rec = sorted([f for f in filas if f["dias"] > f["mx"]], key=lambda f: -(f["dias"] - f["mx"]))
    iguala = [f for f in filas if f["dias"] == f["mx"] and f["dias"] >= 5]
    # «a N del récord» solo si no faltan días: con días sin dato, el récord podría estar ya batido
    cerca = [f for f in filas if 0 < f["mx"] - f["dias"] <= 3 and not f["faltan"] and f["dias"] >= 10 and f["media"] and f["dias"] >= 2 * f["media"]]
    if not rec:
        return None
    hoy = R.HOY.isoformat()
    anio = rec[0]["anio"]

    def _hecho_rec(f, i):
        al = "al menos " if f["faltan"] else ""
        ant = R.lista_y([str(y) for y in f["anios_mx"]])
        dice = (f"La estación de AEMET de {_donde(f['est'], f['capital'])} suma {al}{f['dias']} días con más de 32 °C en {f['anio']} hasta el "
                f"{R.dia(f['hasta'])}, la cifra más alta de los {f['n']} años con datos completos de su serie, que empieza en {f['primero']}; "
                f"el máximo anterior era de {f['mx']} días, en {ant}.")
        return R.hecho(f"d32_{i}", dice, FUENTE32, [str(f["dias"]), str(f["mx"]), str(f["n"]), str(f["primero"])] + [str(y) for y in f["anios_mx"]],
                       lugar=f["capital"], superlativo=True, record=True)

    def _hecho_media(f, i):
        if not f["media"]:
            return None
        return R.hecho(f"d32m_{i}", f"La media 1991-2020 de esa estación es de {R.f1(f['media'])} días al año.", FUENTE32, [R.f1(f["media"])])

    hechos = [R.hecho("d32_n", f"{len(rec)} de las {len(filas)} capitales cuya estación principal de AEMET tiene al menos 25 años completos de serie "
                      f"ya suman en {anio} más días con más de 32 °C que en cualquier año anterior de esa serie: "
                      f"{R.lista_y([f['capital'] for f in rec])}.", FUENTE32, [str(len(rec)), str(len(filas)), "25", str(anio)],
                      superlativo=True, record=True)]
    for i, f in enumerate(rec):
        hechos.append(_hecho_rec(f, i))
    if iguala:
        hechos.append(R.hecho("d32_ig", ("Iguala" if len(iguala) == 1 else "Igualan") + " su cifra más alta: " + "; ".join(
            f"{f['capital']} ({f['est']}), con {'al menos ' if f['faltan'] else ''}{f['dias']} días, como en {R.lista_y([str(y) for y in f['anios_mx']])}" for f in iguala) + ".",
            FUENTE32, [str(f["dias"]) for f in iguala] + [str(y) for f in iguala for y in f["anios_mx"]], superlativo=True))
    hechos.append(R.hecho("d32_def", "Se cuentan los días con temperatura máxima de más de 32 °C en la estación; el año no ha terminado, así que "
                          "las cifras de " + str(anio) + " todavía pueden subir.", FUENTE32, [str(anio)]))
    t3 = rec[:3]
    sub = "; ".join(f"{f['capital']}, {f['dias']} frente a {f['mx']} en {f['anio_mx']}" for f in t3) + "."
    hechos.append(R.hecho("d32_sub", sub[0].upper() + sub[1:], FUENTE32, [str(x) for f in t3 for x in (f["dias"], f["mx"], f["anio_mx"])]))
    tit = (f"{len(rec)} capitales ya han batido en {anio} su récord de días de más de 32 °C" if len(rec) > 1 else
           f"{rec[0]['capital']} ya ha batido en {anio} su récord de días de más de 32 °C")
    pl = {"titular": tit, "subtitulo": hechos[-1]["dice"], "entradilla": hechos[0]["dice"],
          "cuerpo": [h["dice"] for h in hechos[1:-1]], "claves": [hechos[0]["dice"], hechos[1]["dice"]]}
    top = rec[0]
    cifras = [{"n": str(len(rec)), "l": f"capitales con récord de días de más de 32 °C en {anio}", "tono": "calor"},
              {"n": str(top["dias"]), "l": f"días en {top['capital']} (récord anterior: {top['mx']}, en {top['anio_mx']})", "tono": "calor"}]
    metodo = ("Días con temperatura máxima de más de 32 °C en la estación principal de AEMET de cada capital (valores climatológicos diarios). "
              "Se compara el año en curso con los años de la serie con 330 días o más de dato; solo entran estaciones con 25 de esos años o más.")
    limites = ["El año no ha terminado: las cifras de " + str(anio) + " solo pueden subir.",
               "Cada estación tiene su propio inicio de serie; algunas empiezan después de 1961.",
               "Es la estación principal de la capital, no la media de la provincia."]
    h = R.historia("dias32_record", f"{hoy}-dias32-record", "Calor · récords del año en las capitales", "calor",
                   min(70, 50 + 1.5 * len(rec)), hechos, pl, cifras, FUENTE32, metodo, limites, PAGINA32)
    h["seccion"] = "calor"
    h["grafico"] = grafico32_nacional(R, rec[:12], h["id"])
    nac = R.hecho("d32_nac", hechos[0]["dice"], FUENTE32, hechos[0]["valores"], superlativo=True, record=True)
    for i, f in enumerate(rec):
        hv = [_hecho_rec(f, 0)]
        m = _hecho_media(f, 0)
        if m:
            hv.append(m)
        hv += [nac, hechos[-2]]
        al = "al menos " if f["faltan"] else ""
        plv = {"titular": f"{f['capital']} ya suma {al}{f['dias']} días de más de 32 °C en {anio}, récord de su serie desde {f['primero']}",
               "subtitulo": f"El máximo anterior era de {f['mx']} días, en {R.lista_y([str(y) for y in f['anios_mx']])}.",
               "entradilla": hv[0]["dice"], "cuerpo": [x["dice"] for x in hv[1:]], "claves": [hv[0]["dice"]]}
        hv.append(R.hecho("d32_ant", plv["subtitulo"], FUENTE32, [str(f["mx"])] + [str(y) for y in f["anios_mx"]], superlativo=True))
        v = {"provincia": R.nprov(f["cod"]), "slug": R.PROV[f["cod"]][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": f"{f['dias']}", "l": f"días de más de 32 °C en {anio} en {f['capital']} (hasta el {R.dia(f['hasta'], semana=False)})", "tono": "calor"},
                        {"n": f"{f['mx']}", "l": f"récord anterior, en {f['anio_mx']}", "tono": "calor"}],
             "puntos": round(min(68, 56 + (f["dias"] - f["mx"]) / 2), 1), "nivel": None}
        v["grafico"] = grafico32_serie(R, f, f"{h['id']}-{f['cod']}")
        h["provincias"][f["cod"]] = v
    for f in iguala + cerca:
        if f["cod"] in h["provincias"]:
            continue
        hv = []
        if f["dias"] == f["mx"]:
            al = "al menos " if f["faltan"] else ""
            dice = (f"La estación de AEMET de {_donde(f['est'], f['capital'])} suma {al}{f['dias']} días con más de 32 °C en {anio} hasta el {R.dia(f['hasta'])}: "
                    f"ya iguala la cifra más alta de los {f['n']} años con datos completos de su serie, que empieza en {f['primero']}, "
                    f"la de {R.lista_y([str(y) for y in f['anios_mx']])}.")
            tit = f"{f['capital']} ya iguala en {anio} su récord de días de más de 32 °C: {al}{f['dias']}"
            pts = 50
        else:
            dice = (f"La estación de AEMET de {_donde(f['est'], f['capital'])} suma {f['dias']} días con más de 32 °C en {anio} hasta el {R.dia(f['hasta'])}, "
                    f"a {f['mx'] - f['dias']} de la cifra más alta de los {f['n']} años con datos completos de su serie, que empieza en {f['primero']}: "
                    f"{f['mx']} días, en {R.lista_y([str(y) for y in f['anios_mx']])}.")
            tit = f"{f['capital']} suma {f['dias']} días de más de 32 °C en {anio}, a {f['mx'] - f['dias']} de su récord de {f['anio_mx']}"
            pts = 44
        hv.append(R.hecho("d32_0", dice, FUENTE32, [str(f["dias"]), str(f["mx"]), str(f["mx"] - f["dias"]), str(f["n"]), str(f["primero"])]
                          + [str(y) for y in f["anios_mx"]], lugar=f["capital"], superlativo=True, record=f["dias"] == f["mx"]))
        m = _hecho_media(f, 0)
        if m:
            hv.append(m)
        hv += [nac, hechos[-2]]
        plv = {"titular": tit, "subtitulo": hv[1]["dice"], "entradilla": hv[0]["dice"], "cuerpo": [x["dice"] for x in hv[1:]],
               "claves": [hv[0]["dice"]]}
        v = {"provincia": R.nprov(f["cod"]), "slug": R.PROV[f["cod"]][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": f"{f['dias']}", "l": f"días de más de 32 °C en {anio} en {f['capital']}", "tono": "calor"}],
             "puntos": pts, "nivel": None}
        v["grafico"] = grafico32_serie(R, f, f"{h['id']}-{f['cod']}")
        h["provincias"][f["cod"]] = v
    return h


# ============================================================================ noches tropicales
def _mes(m):
    return ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"][m - 1]


def grafico_noches(R, filas, nombre, mes):
    W, fila, ml, mr, mt = 640, 24, 200, 40, 10
    Hh = mt + fila * len(filas) + 24
    mx = max(f["nt"] for f in filas)
    X = lambda v: ml + v / mx * (W - ml - mr)
    c = []
    for i, f in enumerate(filas):
        y = mt + i * fila
        col = "#E6A88F" if f["cod"] in CANARIAS else R.CALOR
        c.append(R._t(ml - 8, y + 15, f["ciudad"], 12, R.TINTA, "end", 600 if i < 3 else 400))
        c.append(f'<rect x="{ml}" y="{y + 4:.1f}" width="{X(f["nt"]) - ml:.1f}" height="14" fill="{col}"/>')
        c.append(R._t(X(f["nt"]) + 5, y + 15, f["nt"], 11, R.TINTA, "start", 700))
    svg = R._svg(W, Hh, f"Noches tropicales en {mes} por ciudad", c)
    leyenda = [{"t": "banda", "c": R.CALOR, "l": "Península, Baleares, Ceuta y Melilla"}, {"t": "banda", "c": "#E6A88F", "l": "Canarias"}]
    pie = (f"Noches tropicales: mínima diaria de 20 °C o más en la estación de AEMET de cada ciudad, del 1 de {mes} al último día "
           "con dato validado de cada estación. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.")
    return R.guardar_grafico(nombre, svg, [(f["ciudad"], f["est"], f["nt"], f["hasta"], f["nt_anyo"]) for f in filas],
                             ["ciudad", "estacion_AEMET", f"noches_tropicales_{mes}", "hasta", "noches_tropicales_anio"],
                             f"Noches tropicales en {mes}", leyenda, pie)


def grafico_noches_ciudad(R, f, nombre):
    """La mínima de cada noche del mes, con la raya de los 20 °C: en color, las noches tropicales."""
    dias = f["dias"]
    W, Hh, ml, mr, mt, mb = 640, 240, 36, 16, 22, 30
    vals = [v for _, v in dias]
    y0, y1 = int(min(vals + [16])) - 2, int(max(vals + [20])) + 2
    paso = (W - ml - mr) / max(1, len(dias) - 1)
    X = lambda i: ml + 8 + i * (paso - 16 / max(1, len(dias) - 1))
    Y = lambda t: mt + (y1 - t) / (y1 - y0) * (Hh - mt - mb)
    c = []
    for t in range(y0, y1 + 1):
        if t % 2 == 0:
            c.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{R.RAYA}" stroke-width="1"/>')
            c.append(R._t(ml - 5, Y(t) + 4, t, 10, R.GRIS, "end"))
    c.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(20):.1f}" y2="{Y(20):.1f}" stroke="{R.TINTA}" stroke-width="1.5" stroke-dasharray="5 4"/>')
    c.append(R._t(W - mr, Y(20) - 5, "20 °C", 11, R.TINTA, "end", 700))
    c.append('<polyline points="' + " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(dias)) + f'" fill="none" stroke="#9E9589" stroke-width="1.5"/>')
    for i, (d, v) in enumerate(dias):
        col = R.CALOR if v >= 20 else "#C9C1B6"
        c.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{6 if v >= 20 else 4}" fill="{col}" stroke="#FFFFFF" stroke-width="1.5"/>')
        c.append(R._t(X(i), Hh - mb + 16, int(d[8:]), 10, R.GRIS, "middle"))
    svg = R._svg(W, Hh, f"Temperatura mínima diaria en la estación de AEMET de {f['est']}", c)
    leyenda = [{"t": "punto", "c": R.CALOR, "l": "Noche tropical (mínima de 20 °C o más)"}, {"t": "punto", "c": "#C9C1B6", "l": "Resto"}]
    pie = f"Mínima diaria en la estación de AEMET de {f['est']}. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es."
    return R.guardar_grafico(nombre, svg, dias, ["fecha", "minima_C"], f"La mínima de cada noche en {f['ciudad']}", leyenda, pie)


def historia_noches(R):
    J = R.leer(R.DOCS / "temperaturas_nocturnas.json", {}) or {}
    hoy = R.HOY
    filas = []
    for c in J.get("ciudades") or []:
        h = c.get("historico") or {}
        ult = c.get("ultimo_dato")
        cod = NOCHE_COD.get(c.get("id"))
        if not ult or not cod or ult < (hoy - timedelta(days=10)).isoformat():
            continue
        mes = date.fromisoformat(ult).month
        pref = ult[:7]
        dias = sorted((d, v["tmin"]) for d, v in h.items() if d.startswith(pref) and d <= ult and v.get("tmin") is not None)
        if not dias:
            continue
        nt = sum(1 for _, v in dias if v >= 20)
        dmax, vmax = max(dias, key=lambda x: (x[1], x[0]))
        filas.append({"cod": cod, "id": c["id"], "ciudad": NOCHE_NOMBRE.get(c["id"], c["nombre"]), "est": c["estacion"], "nt": nt,
                      "hasta": ult, "mes": mes, "nt_anyo": c.get("nt_anyo"), "dias": dias, "dmax": dmax, "vmax": vmax, "n_dias": len(dias)})
    if not filas:
        return None
    mes = max(f["mes"] for f in filas)
    filas = [f for f in filas if f["mes"] == mes]
    if mes in (6, 7, 8, 9):
        return None  # en verano la noche tropical es lo esperable: la historia es la de los récords
    con = sorted([f for f in filas if f["nt"] >= 1], key=lambda f: (-f["nt"], f["ciudad"]))
    pen = [f for f in con if f["cod"] not in CANARIAS]
    if len([f for f in pen if f["nt"] >= 3]) < 3:
        return None
    nmes = _mes(mes)
    anio = date.fromisoformat(filas[0]["hasta"]).year
    hasta_n = max(f["hasta"] for f in con)

    def _hecho_ciudad(f, i, con_anio=True):
        d = (f"La estación de AEMET de {_donde(f['est'], f['ciudad'], '()')} ha registrado {f['nt']} {'noche tropical' if f['nt'] == 1 else 'noches tropicales'} "
             f"(mínima de 20 °C o más) entre el 1 y el {date.fromisoformat(f['hasta']).day} de {nmes}")
        vals = [str(f["nt"]), "20 °C", str(date.fromisoformat(f["hasta"]).day)]
        if con_anio and f.get("nt_anyo"):
            d += f", y {f['nt_anyo']} en lo que va de {anio}"
            vals += [str(f["nt_anyo"]), str(anio)]
        return R.hecho(f"nt_{i}", d + ".", FUENTE_NOCHE, vals, lugar=f["ciudad"])

    def _hecho_max(f, i):
        v = f"{R.f1(f['vmax'])} °C"
        return R.hecho(f"ntx_{i}", f"En {f['ciudad']}, la mínima más alta de {nmes} hasta esa fecha fue de {v}, el {R.dia(f['dmax'])}.",
                       FUENTE_NOCHE, [v], lugar=f["ciudad"], superlativo=True, liga=[v])

    hechos = [R.hecho("nt_n", f"{len(con)} de las {len(filas)} ciudades que sigue el observatorio han tenido al menos una noche tropical "
                      f"(mínima de 20 °C o más) en lo que va de {nmes}, según los datos diarios de AEMET.", FUENTE_NOCHE,
                      [str(len(con)), str(len(filas)), "20 °C"])]
    for i, f in enumerate(pen[:6]):
        hechos.append(_hecho_ciudad(f, i))
    for i, f in enumerate(pen[:3]):
        hechos.append(_hecho_max(f, i))
    can = [f for f in con if f["cod"] in CANARIAS]
    if can:
        hechos.append(R.hecho("nt_can", f"En Canarias, "
                              + R.lista_y([f"{f['ciudad']} lleva {f['nt']} de {f['n_dias']} noches con dato" for f in can]) + ".",
                              FUENTE_NOCHE, [x for f in can for x in (str(f["nt"]), str(f["n_dias"]))]))
    anual = sorted([f for f in filas if f.get("nt_anyo")], key=lambda f: -f["nt_anyo"])[:3]
    if anual:
        hechos.append(R.hecho("nt_anio", f"En el conjunto de {anio}, la ciudad con más noches tropicales de las que sigue el observatorio es "
                              f"{anual[0]['ciudad']}, con {anual[0]['nt_anyo']}; le siguen " + R.lista_y([f"{f['ciudad']} ({f['nt_anyo']})" for f in anual[1:]]) + ".",
                              FUENTE_NOCHE, [str(f["nt_anyo"]) for f in anual] + [str(anio)], superlativo=True))
    hechos.append(R.hecho("nt_def", "AEMET llama noche tropical a la que no baja de 20 °C. Son valores climatológicos diarios, que AEMET publica "
                          "con unos días de retraso.", FUENTE_NOCHE, ["20 °C"]))
    a, b, c3 = pen[0], pen[1], pen[2]
    tit = (f"{a['ciudad']} suma {a['nt']} noches tropicales en lo que va de {nmes}; {b['ciudad']}, {b['nt']}, y {c3['ciudad']}, {c3['nt']}")
    pl = {"titular": tit, "subtitulo": hechos[0]["dice"], "entradilla": hechos[1]["dice"],
          "cuerpo": [" ".join(h["dice"] for h in hechos[2:2 + min(5, len(pen) - 1)])] + [h["dice"] for h in hechos[2 + min(5, len(pen) - 1):]],
          "claves": [hechos[1]["dice"], hechos[0]["dice"]]}
    cifras = [{"n": str(a["nt"]), "l": f"noches tropicales en {a['ciudad']} en {nmes} (hasta el día {date.fromisoformat(a['hasta']).day})", "tono": "calor"},
              {"n": str(len(con)), "l": f"de {len(filas)} ciudades con alguna noche tropical en {nmes}", "tono": "calor"}]
    metodo = ("Mínima diaria de la estación de AEMET de cada ciudad (valores climatológicos diarios); noche tropical = mínima de 20 °C o más. "
              "Cuenta desde el día 1 del mes hasta el último día con dato de cada estación.")
    limites = ["No hay aquí una referencia de lo normal para el mes: es un recuento, no una anomalía.",
               "Cada estación tiene su último día con dato; se dice en el texto."]
    h = R.historia("noches_tropicales", f"{R.HOY.isoformat()}-noches-tropicales", f"Calor · noches tropicales en {nmes}", "calor",
                   min(48, 32 + a["nt"]), hechos, pl, cifras, FUENTE_NOCHE, metodo, limites, PAGINA_NOCHE)
    h["seccion"] = "calor"
    h["fecha"] = hasta_n
    h["grafico"] = grafico_noches(R, con[:14], h["id"], nmes)
    nac = R.hecho("nt_nac", hechos[0]["dice"], FUENTE_NOCHE, hechos[0]["valores"])
    por_cod = {}
    for f in con:
        por_cod.setdefault(f["cod"], []).append(f)
    for cod, fs in por_cod.items():
        fs = sorted(fs, key=lambda f: -f["nt"])
        hv = [_hecho_ciudad(f, i) for i, f in enumerate(fs)] + [_hecho_max(fs[0], 0), nac, hechos[-1]]
        f0 = fs[0]
        anio_txt = f" y {f0['nt_anyo']} en lo que va de {anio}" if f0.get("nt_anyo") else ""
        plv = {"titular": f"{f0['ciudad']} suma {f0['nt']} {'noche tropical' if f0['nt'] == 1 else 'noches tropicales'} en {nmes}{anio_txt}",
               "subtitulo": hv[len(fs)]["dice"], "entradilla": hv[0]["dice"], "cuerpo": [x["dice"] for x in hv[1:]], "claves": [hv[0]["dice"]]}
        v = {"provincia": R.nprov(cod), "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": str(f0["nt"]), "l": f"noches tropicales en {f0['ciudad']} en {nmes}", "tono": "calor"}]
             + ([{"n": str(f0["nt_anyo"]), "l": f"en lo que va de {anio}", "tono": "calor"}] if f0.get("nt_anyo") else []),
             "puntos": round(min(46, 30 + 2 * f0["nt"]) - (8 if cod in CANARIAS else 0), 1), "nivel": None}
        v["grafico"] = grafico_noches_ciudad(R, f0, f"{h['id']}-{cod}")
        h["provincias"][cod] = v
    return h


# ============================================================================ a un paso del récord del mes
def historia_cerca_record(R):
    J = R.leer(R.DOCS / "records" / "hoy.json", {}) or {}
    ayer = J.get("ayer")
    if not ayer:
        return None
    ya = {x.get("idema") for k in ("records_hoy", "records_ayer", "records_recientes", "en_revision") for x in (J.get(k) or [])}
    anio = R.HOY.year
    cand = []
    for s in J.get("estaciones") or []:
        if s.get("id") in ya or not s.get("desde") or s["desde"] > anio - 30:
            continue
        d = s.get("ayer") or {}
        if (d.get("h") or 0) < 20:
            continue
        for k, var in (("dx", "máxima"), ("dn", "mínima")):
            v = d.get(k)
            if v is not None and -0.5 <= v < 0:
                cand.append((v, var, s, d))
    if not cand:
        return None
    cand.sort(key=lambda x: -x[0])
    mes = _mes(date.fromisoformat(ayer).month)
    hechos, provs = [], {}
    for i, (v, var, s, d) in enumerate(cand[:6]):
        val, rec, fr = (d["tx"], d["rx"], d["rxf"]) if var == "máxima" else (d["tn"], d["rn"], d["rnf"])
        a, b = f"{R.f1(val)} °C", f"{R.f1(rec)} °C"
        hechos.append(R.hecho(f"cr_{i}", f"La estación de AEMET de {s['n']} ({s['p']}) marcó el {R.dia(ayer)} una {var} de {a}, a {R.f1(abs(v))} °C "
                              f"de su récord de {var} para un mes de {mes}: {b}, el {R.dia(fr, anio=True, semana=False)}. Su tabla de extremos "
                              f"empieza en {s['desde']}.", FUENTE_REC, [a, b, f"{R.f1(abs(v))} °C", str(s["desde"])], lugar=s["n"],
                              liga=[a, b], superlativo=True))
        cod = next((c for c, pv in R.PROV.items() if R.sin_tildes(pv[0]).lower() == R.sin_tildes(s.get("p", "")).lower()), None)
        if cod:
            provs.setdefault(cod, []).append(hechos[-1])
    hechos.append(R.hecho("cr_def", "Son datos de observación en tiempo real de AEMET, de 0 a 24 horas UTC, que AEMET valida en unos días.", FUENTE_REC, ["0", "24"]))
    v0, var0, s0, d0 = cand[0]
    tit = f"{s0['n']} se quedó el {R.dia(ayer)} a {R.f1(abs(v0))} °C de su récord de {var0} para {mes}"
    pl = {"titular": tit, "subtitulo": hechos[1]["dice"] if len(hechos) > 2 else hechos[-1]["dice"], "entradilla": hechos[0]["dice"],
          "cuerpo": [h["dice"] for h in hechos[1:]], "claves": [hechos[0]["dice"]]}
    h = R.historia("cerca_record", f"{R.HOY.isoformat()}-cerca-record", "Calor y frío · a un paso del récord", "calor" if var0 == "máxima" else "lluvia",
                   46, hechos, pl, [{"n": f"{R.f1(abs(v0))} °C", "l": f"del récord de {var0} de {mes} en {s0['n']}", "tono": "calor"}],
                   FUENTE_REC, "Máxima y mínima del día (0-24 h UTC, 20 horas o más con dato) frente a los valores extremos del mes que publica AEMET "
                   "para cada estación con tabla de 30 años o más.", ["Dato provisional de observación; AEMET lo valida en 2-4 días."],
                   "https://calentamientoglobal.es/records-de-temperatura/")
    h["seccion"] = "calor"
    h["fecha"] = ayer
    for cod, hs in provs.items():
        plv = {"titular": hs[0]["dice"].split(":")[0].replace(f"La estación de AEMET de ", ""), "subtitulo": "", "entradilla": hs[0]["dice"],
               "cuerpo": [x["dice"] for x in hs[1:]] + [hechos[-1]["dice"]], "claves": [hs[0]["dice"]]}
        plv["titular"] = plv["titular"][0].upper() + plv["titular"][1:]
        h["provincias"][cod] = {"provincia": R.nprov(cod), "slug": R.PROV[cod][1], "hechos": hs + [hechos[-1]], "plantilla": plv,
                                "cifras": h["cifras"][:1] if hs[0] is hechos[0] else [], "puntos": 44, "nivel": None}
    return h


def generar(R, D):
    out = []
    for fn in (historia_dias32, historia_noches, historia_cerca_record):
        try:
            h = fn(R)
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"temperaturas/{fn.__name__}: {type(e).__name__}: {e}")
            h = None
        if h:
            out.append(h)
    return out
