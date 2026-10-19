"""Mar y costa: las boyas de Puertos del Estado.

Solo cifras medidas por las boyas (Puertos del Estado, redes REDEXT/REDCOS, vía Copernicus Marine In Situ TAC):
  · docs/boyas_actual.json — dato del día, media de los últimos 7 días y máximos del año por boya;
  · docs/boyas_mapa.json   — serie de medias mensuales de cada boya y su valor más alto medido.

Comparaciones hechas aquí, a la vista: la media de los últimos 7 días frente a la media de los octubres (o del mes que
toque) con dato de la serie de la propia boya, solo si hay al menos 10; el puesto de un mes frente a los mismos meses de
su serie. No se usa la «anomalía reciente» ni la «normal» que trae el fichero (cálculo sin auditar, ver
partes_prensa.py), ni el nivel del mar por altimetría (referencia anual, no estacional), ni las olas de calor marinas de
NOAA Coral Reef Watch (dos fuentes mezcladas y un recuento de rachas propio): quedan fuera hasta revisarlos.
"""
from __future__ import annotations

import statistics as st

SECCION = "mar"

FUENTE = "Puertos del Estado (boyas REDEXT/REDCOS, vía Copernicus Marine)"
PAGINA = "https://calentamientoglobal.es/temperaturas-del-mar-espana-actualizado/"
MIN_MESES = 10          # meses iguales con dato para comparar o hablar de «la serie»
MIN_SERIE_MESES = 120   # meses con dato (≈10 años) para hablar del valor más alto de la serie
MAX_ANTIGUEDAD = 2      # días

# boya → provincias de la costa que tiene delante
PROV_BOYA = {
    "estaca_de_bares": ["15", "27"], "villano_sisargas": ["15"], "golfo_de_cadiz": ["21", "11"], "cabo_de_gata": ["04"],
    "cabo_de_palos": ["30"], "valencia": ["46"], "tarragona": ["43"], "cabo_begur": ["17"], "dragonera": ["07"],
    "mahon": ["07"], "gran_canaria": ["35"], "tenerife_sur": ["38"], "gijon": ["33"], "malaga": ["29"],
    "melilla": ["52"], "barcelona": ["08"], "alicante": ["03"],
}
NOMBRE = {"golfo_de_cadiz": "golfo de Cádiz", "malaga": "Málaga", "gijon": "Gijón", "melilla": "Melilla", "barcelona": "Barcelona"}
MESES_PLURAL = ["eneros", "febreros", "marzos", "abriles", "mayos", "junios", "julios", "agostos", "septiembres", "octubres",
                "noviembres", "diciembres"]


def _nombre(k, b):
    return NOMBRE.get(k) or b["nombre"].replace(" (costera)", "")


def _de_la_boya(k, nombre):
    costera = k in ("malaga", "gijon", "melilla", "barcelona")
    return f"la boya {'costera ' if costera else ''}{'del' if nombre.startswith('golfo') else 'de'} {nombre}"


def _en(k, nombre):
    return f"en el {nombre}" if nombre.startswith("golfo") else f"en {nombre}"


def _meses_de(M, b, mm):
    """[(año, media)] del mes mm ('10') en la serie mensual de la boya."""
    meses = M.get("meses") or []
    return [(meses[i][:4], v) for i, v in enumerate(b.get("serie") or []) if i < len(meses) and meses[i][5:] == mm and v is not None]


def _boyas(R):
    A = (R.leer(R.DOCS / "boyas_actual.json", {}) or {}).get("boyas") or {}
    M = R.leer(R.DOCS / "boyas_mapa.json", {}) or {}
    out = []
    for k, a in A.items():
        b = (M.get("boyas") or {}).get(k) or {}
        if a.get("temp") is None or (a.get("dias_antiguedad") or 0) > MAX_ANTIGUEDAD:
            continue
        fecha = a.get("fecha") or ""
        anio, mm = fecha[:4], fecha[5:7]
        previos = [(y, v) for y, v in _meses_de(M, b, mm) if y < anio]
        x = {"k": k, "a": a, "b": b, "nombre": _nombre(k, a), "fecha": fecha, "mes": int(mm), "previos": previos,
             "n_meses": sum(1 for v in (b.get("serie") or []) if v is not None)}
        if len(previos) >= MIN_MESES and a.get("temp_media_semana") is not None:
            sem = round(a["temp_media_semana"], 1)
            media = round(st.mean(v for _, v in previos), 1)
            x.update(sem=sem, media=media, dif=round(sem - media, 1), y0=previos[0][0], y1=previos[-1][0],
                     n_por_debajo=sum(1 for _, v in previos if round(v, 1) < sem), mes_max=max(previos, key=lambda t: t[1]))
        out.append(x)
    return out, M


# ---------------------------------------------------------------- hechos
def _hecho_semana(R, x, i):
    a, n = x["a"], x["nombre"]
    sobre = "por encima" if x["dif"] > 0 else "por debajo"
    dice = (f"{_de_la_boya(x['k'], n)[0].upper() + _de_la_boya(x['k'], n)[1:]} midió el agua a {R.d1(a['temp'])} °C el {R.dia(x['fecha'])}; de media, "
            f"{R.d1(x['sem'])} °C en los últimos 7 días, {R.d1(abs(x['dif']))} °C {sobre} de la media de sus {len(x['previos'])} "
            f"{MESES_PLURAL[x['mes'] - 1]} con dato ({x['y0']}-{x['y1']}), que es de {R.d1(x['media'])} °C.")
    return R.hecho(f"boya_{i}", dice, FUENTE, [f"{R.d1(a['temp'])} °C", f"{R.d1(x['sem'])} °C", f"{R.d1(abs(x['dif']))} °C", f"{R.d1(x['media'])} °C",
                                               str(len(x["previos"])), x["y0"], x["y1"]],
                   lugar=n, liga=[f"{R.d1(x['sem'])} °C", f"{R.d1(abs(x['dif']))} °C"])


def _hecho_solo_dato(R, x, i):
    a, n = x["a"], x["nombre"]
    dice = f"{_de_la_boya(x['k'], n)[0].upper() + _de_la_boya(x['k'], n)[1:]} midió el agua a {R.d1(a['temp'])} °C el {R.dia(x['fecha'])}."
    if a.get("temp_media_semana") is not None:
        dice = dice[:-1] + f"; de media, {R.d1(a['temp_media_semana'])} °C en los últimos 7 días."
    return R.hecho(f"boya_{i}", dice, FUENTE, [f"{R.d1(a['temp'])} °C"], lugar=n, liga=[f"{R.d1(a['temp'])} °C"])


def _hecho_mes_max(R, x, i):
    y, v = x["mes_max"]
    return R.hecho(f"boya_mesmax_{i}", f"En {_de_la_boya(x['k'], x['nombre'])}, el {MESES_PLURAL[x['mes'] - 1][:-1]} más cálido de su serie fue el de {y}, "
                   f"con {R.d1(v)} °C de media.", FUENTE, [f"{R.d1(v)} °C", y], lugar=x["nombre"], superlativo=True)


# ---------------------------------------------------------------- gráficos
def _grafico_dif(R, filas, nombre, titulo):
    """Barras: media de los últimos 7 días menos la media del mes en la serie de cada boya."""
    W, fila, ml, mr, mt = 640, 26, 168, 120, 22
    Hh = mt + fila * len(filas) + 34
    mx = max(1.0, max(abs(x["dif"]) for x in filas))
    neg = any(x["dif"] < 0 for x in filas)
    x0 = ml + ((W - ml - mr) * 0.25 if neg else 0)
    esc = (W - mr - x0 - 46) / mx
    s = [R._t(W - mr + 12, 12, "7 días · mes", 11, R.GRIS),
         f'<line x1="{x0:.1f}" x2="{x0:.1f}" y1="{mt - 4}" y2="{Hh - 28}" stroke="{R.TINTA}" stroke-width="1"></line>']
    for t in range(1, int(mx) + 1):
        s.append(f'<line x1="{x0 + t * esc:.1f}" x2="{x0 + t * esc:.1f}" y1="{mt - 4}" y2="{Hh - 28}" stroke="{R.RAYA}" stroke-width="1"></line>')
        s.append(R._t(x0 + t * esc, Hh - 10, f"+{t} °C", 11.5, R.GRIS, "middle"))
    for i, x in enumerate(filas):
        y = mt + i * fila
        dest = i < 3 and x["dif"] > 0
        s.append(R._t(ml - 10, y + 16, x["nombre"], 13, R.TINTA, "end", 600 if dest else 400))
        w = abs(x["dif"]) * esc
        xr = x0 if x["dif"] >= 0 else x0 - w
        color = R.CALOR if x["dif"] > 0 else R.LLUVIA
        s.append(f'<rect x="{xr:.1f}" y="{y + 4}" width="{max(w, 1):.1f}" height="16" fill="{color if dest or x["dif"] <= 0 else "#E3A487"}"></rect>')
        s.append(R._t(x0 + max(x["dif"], 0) * esc + 6, y + 16.5, f"{'+' if x['dif'] > 0 else ''}{R.d1(x['dif'])}", 12.5, R.TINTA, "start", 700 if dest else 500))
        s.append(R._t(W - mr + 12, y + 16.5, f"{R.d1(x['sem'])} · {R.d1(x['media'])}", 12, R.GRIS))
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, [(x["nombre"], x["fecha"], x["sem"], x["media"], x["dif"], len(x["previos"]), f"{x['y0']}-{x['y1']}") for x in filas],
                             ["boya", "fecha", "media_7_dias_C", "media_del_mes_en_la_serie_C", "diferencia_C", "meses_con_dato", "periodo"], titulo, [],
                             "Media de los últimos 7 días de cada boya frente a la media de ese mes en su propia serie (solo meses con dato; al menos 10). "
                             "Fuente: Puertos del Estado (vía Copernicus Marine). Cálculo: calentamientoglobal.es.")


def _grafico_serie_mes(R, x, previos, nombre, titulo, marca=None, marca_txt=""):
    """Barras año a año de un mes en la serie de una boya; opcional, una línea con el valor de ahora."""
    W, Hh, ml, mr, mt, mb = 640, 260, 40, 16, 24, 34
    vals = [v for _, v in previos] + ([marca] if marca is not None else [])
    lo, hi = int(min(vals)) - 1, int(max(vals)) + 1
    n = len(previos)
    bw = (W - ml - mr) / max(n, 1)
    Y = lambda v: mt + (hi - v) / (hi - lo) * (Hh - mt - mb)
    s = []
    for t in range(lo, hi + 1):
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{R.RAYA}" stroke-width="1"></line>')
        s.append(R._t(ml - 6, Y(t) + 4, f"{t}", 11, R.GRIS, "end"))
    tope = max(v for _, v in previos)
    for i, (y, v) in enumerate(previos):
        xx = ml + i * bw
        dest = v == tope or (marca is None and i == n - 1)
        s.append(f'<rect x="{xx + 1:.1f}" y="{Y(v):.1f}" width="{max(bw - 2, 1):.1f}" height="{Y(lo) - Y(v):.1f}" fill="{R.CALOR if dest else "#E3A487"}"></rect>')
        if i == 0 or i == n - 1 or (int(y) % 5 == 0 and 3 <= i <= n - 4):
            s.append(R._t(xx + bw / 2, Hh - mb + 16, y, 11, R.GRIS, "middle"))
    if marca is not None:
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(marca):.1f}" y2="{Y(marca):.1f}" stroke="{R.TINTA}" stroke-width="2" stroke-dasharray="6 4"></line>')
        s.append(R._t(W - mr, Y(marca) - 6, marca_txt, 12, R.TINTA, "end", 700))
    s.append(R._t(ml, 14, "°C", 11, R.GRIS))
    svg = R._svg(W, Hh, titulo, s)
    filas = [(y, v) for y, v in previos] + ([("ahora", marca)] if marca is not None else [])
    return R.guardar_grafico(nombre, svg, filas, ["anio", "media_mensual_C"], titulo,
                             [{"t": "banda", "c": "#E3A487", "l": "Media del mes, año a año"}] + ([{"t": "discontinua", "c": R.TINTA, "l": marca_txt}] if marca is not None else []),
                             f"Media mensual de la temperatura del agua medida por {_de_la_boya(x['k'], x['nombre'])} (solo años con dato). "
                             "Fuente: Puertos del Estado (vía Copernicus Marine). Cálculo: calentamientoglobal.es.")


def _pl(titular, subtitulo, hechos):
    return {"titular": titular, "subtitulo": subtitulo, "entradilla": hechos[0]["dice"], "cuerpo": [h["dice"] for h in hechos[1:]] or [hechos[0]["dice"]],
            "claves": [h["dice"] for h in hechos[:3]]}


def _ok(R, pl, hechos, que):
    e = R.verificar(pl, hechos)
    if e:
        R.LOG.append(f"mar · {que}: plantilla descartada: {e[:3]}")
    return not e


# ---------------------------------------------------------------- historia 1: el mar, boya a boya
def _historia_boyas(R, boyas):
    comp = sorted([x for x in boyas if "dif" in x], key=lambda x: -x["dif"])
    if len(comp) < 4:
        return None
    fecha = max(x["fecha"] for x in comp)
    mes_pl = MESES_PLURAL[comp[0]["mes"] - 1]
    mes = R.MESES[comp[0]["mes"] - 1]
    arriba = [x for x in comp if x["dif"] > 0]
    uno = [x for x in comp if x["dif"] >= 1]
    top = uno[:3]
    hechos = []
    if top:
        quien = (f"Las {len(comp)} boyas" if len(arriba) == len(comp) else f"{len(arriba)} de las {len(comp)} boyas")
        hechos.append(R.hecho("boyas_n", f"{quien} de Puertos del Estado con al menos {MIN_MESES} {mes_pl} de serie midieron el agua en "
                              f"los últimos 7 días por encima de la media de {mes} en su propia serie; en {len(uno)}, la diferencia fue de 1 °C o más.",
                              FUENTE, [str(len(arriba)), str(len(comp)), str(MIN_MESES), str(len(uno)), "1 °C"]))
    for i, x in enumerate(comp):
        hechos.append(_hecho_semana(R, x, i))
    calida = max(comp, key=lambda x: x["sem"])
    hechos.append(R.hecho("boyas_calida", f"El agua más templada de los últimos 7 días, en {_de_la_boya(calida['k'], calida['nombre'])}: {R.d1(calida['sem'])} °C de media.",
                          FUENTE, [f"{R.d1(calida['sem'])} °C"], lugar=calida["nombre"], superlativo=True, liga=[f"{R.d1(calida['sem'])} °C"]))
    x0 = comp[0]
    if x0["dif"] >= 0.5:
        tit = f"Las boyas de Puertos del Estado miden el mar hasta {R.d1(x0['dif'])} °C por encima de su media de {mes}"
    else:
        tit = f"El mar en las boyas de Puertos del Estado, cerca de su media de {mes}"
    if top:
        trozos = [f"a {R.d1(x['sem'])} °C {_en(x['k'], x['nombre'])}" for x in top]
        sub = "De media en los últimos 7 días, el agua estuvo " + R.lista_y(trozos) + "."
    else:
        sub = f"{_de_la_boya(x0['k'], x0['nombre'])[0].upper() + _de_la_boya(x0['k'], x0['nombre'])[1:]} es la que más se aleja de su media: {R.d1(x0['dif'])} °C."
    hechos.append(R.hecho("boyas_sub", sub, FUENTE, [f"{R.d1(x['sem'])} °C" for x in top] + [f"{R.d1(x0['dif'])} °C"]))
    orden = ([hechos[0]] if top else []) + [h for h in hechos if h["id"].startswith("boya_")][:6] + [h for h in hechos if h["id"] == "boyas_calida"] \
        + [h for h in hechos if h["id"].startswith("boya_")][6:8]   # el resto de boyas, en el gráfico y el CSV
    pl = {"titular": tit, "subtitulo": sub, "entradilla": orden[0]["dice"], "cuerpo": [h["dice"] for h in orden[1:]], "claves": [h["dice"] for h in orden[:3]]}
    if not _ok(R, pl, hechos, "boya a boya"):
        return None
    cif = [{"n": f"+{R.d1(x0['dif'])} °C", "l": f"{x0['nombre']}: últimos 7 días frente a la media de sus {mes_pl}", "tono": "calor"},
           {"n": f"{len(arriba)} de {len(comp)}", "l": f"boyas por encima de su media de {mes}", "tono": "calor"},
           {"n": f"{R.d1(calida['sem'])} °C", "l": f"el agua más templada, en {calida['nombre']} (media de 7 días)", "tono": "calor"}]
    puntos = 38 + min(18, 6 * max(0.0, x0["dif"] - 0.5)) + (4 if len(top) >= 5 else 0)
    h = R.historia("mar_boyas", f"{R.HOY.isoformat()}-mar-boya-a-boya", "Mar · boya a boya", "calor", puntos, hechos, pl, cif, fuentes=FUENTE,
                   metodo=(f"Media de los últimos 7 días de cada boya frente a la media de los {mes_pl} con dato de su propia serie (al menos {MIN_MESES}). "
                           "Las medias mensuales son las de los días con dato de cada mes."),
                   limites=["Las series de las boyas tienen meses sin dato; la media de comparación usa solo los que tienen.",
                            "Es la temperatura del agua en la boya, no la de toda la costa.",
                            "Una media de 7 días se compara con la media de un mes entero: es una referencia, no una anomalía climática oficial."],
                   pagina=PAGINA)
    h["fecha"] = fecha
    h["grafico"] = _grafico_dif(R, comp, h["id"], f"El mar en cada boya: últimos 7 días frente a la media de {mes_pl}")
    # versiones provinciales
    por_prov = {}
    for x in boyas:
        for cod in PROV_BOYA.get(x["k"], []):
            por_prov.setdefault(cod, []).append(x)
    for cod, xs in por_prov.items():
        v = _version_boyas(R, cod, xs, hechos[0] if top else None, mes_pl, h["id"])
        if v:
            h["provincias"][cod] = v
    return h


def lista(R, xs):
    return R.lista_y(xs)


def _version_boyas(R, cod, xs, nac, mes_pl, hid):
    xs = sorted(xs, key=lambda x: -x.get("dif", -99))
    x = xs[0]
    hechos = []
    for i, y in enumerate(xs):
        hechos.append(_hecho_semana(R, y, i) if "dif" in y else _hecho_solo_dato(R, y, i))
    if "dif" in x:
        hechos.append(_hecho_mes_max(R, x, 0))
        if x["dif"] > 0:
            if x["n_por_debajo"] == len(x["previos"]):
                # una semana no es un mes: se dice tal cual, sin hablar de récord (el mes se cierra el último día)
                hechos.append(R.hecho("boya_rango", f"Ninguno de los {len(x['previos'])} {mes_pl} de su serie ({x['y0']}-{x['y1']}) tuvo una media mensual "
                                      f"tan alta como la de estos últimos 7 días; la media del mes completo no se conocerá hasta que acabe {R.MESES[x['mes'] - 1]}.",
                                      FUENTE, [str(len(x["previos"])), x["y0"], x["y1"]], superlativo=True))
            else:
                hechos.append(R.hecho("boya_rango", f"La media de los últimos 7 días supera la media mensual de {x['n_por_debajo']} de los {len(x['previos'])} "
                                      f"{mes_pl} de su serie ({x['y0']}-{x['y1']}).", FUENTE, [str(x["n_por_debajo"]), str(len(x["previos"])), x["y0"], x["y1"]]))
    if nac:
        hechos.append(R.hecho("boyas_nac", "En el conjunto de España: " + nac["dice"][0].lower() + nac["dice"][1:], FUENTE, nac["valores"]))
    if "dif" in x and x["dif"] >= 0.5:
        tit = f"El mar {_en(x['k'], x['nombre'])}, a {R.d1(x['sem'])} °C en los últimos 7 días: {R.d1(x['dif'])} °C más que su media de {R.MESES[x['mes'] - 1]}"
        puntos = 34 + min(20, 7 * (x["dif"] - 0.5))
    elif "dif" in x:
        tit = f"El mar {_en(x['k'], x['nombre'])}, a {R.d1(x['sem'])} °C de media en los últimos 7 días, cerca de su media de {R.MESES[x['mes'] - 1]}"
        puntos = 26
    else:
        tit = f"{_de_la_boya(x['k'], x['nombre'])[0].upper() + _de_la_boya(x['k'], x['nombre'])[1:]} mide el agua a {R.d1(x['a']['temp'])} °C"
        puntos = 22
    sub = hechos[1]["dice"] if len(hechos) > 1 else ""
    pl = {"titular": tit, "subtitulo": sub, "entradilla": hechos[0]["dice"], "cuerpo": [h["dice"] for h in hechos[2:]] or [hechos[0]["dice"]],
          "claves": [h["dice"] for h in hechos[:3]]}
    if not _ok(R, pl, hechos, f"boyas {cod}"):
        return None
    cif = []
    if "dif" in x:
        cif = [{"n": f"{R.d1(x['sem'])} °C", "l": f"el agua en {x['nombre']}, media de los últimos 7 días", "tono": "calor"},
               {"n": f"{'+' if x['dif'] > 0 else ''}{R.d1(x['dif'])} °C", "l": f"frente a la media de sus {len(x['previos'])} {mes_pl} ({x['y0']}-{x['y1']})", "tono": "calor"}]
    else:
        cif = [{"n": f"{R.d1(x['a']['temp'])} °C", "l": f"el agua en {x['nombre']} el {R.dia(x['fecha'])}", "tono": "calor"}]
    v = {"provincia": R.nprov(cod), "slug": R.PROV[cod][1], "hechos": hechos, "plantilla": pl, "cifras": cif, "puntos": round(puntos, 1)}
    if "dif" in x:
        v["grafico"] = _grafico_serie_mes(R, x, x["previos"], f"{hid}-{cod}", f"El agua en {x['nombre']} en {mes_pl[:-1]}, año a año",
                                          marca=x["sem"], marca_txt=f"Últimos 7 días: {R.d1(x['sem'])} °C")
    return v


# ---------------------------------------------------------------- historia 2: el año de los récords en las boyas
def _historia_records(R, boyas, M):
    anio = R.HOY.year
    meses = M.get("meses") or []
    if not meses:
        return None
    ult = meses[-1]                      # último mes cerrado de la serie
    mm_ult = ult[5:7]
    recs, seps = [], []
    for x in boyas:
        b = x["b"]
        stt = b.get("stats") or {}
        rmax = stt.get("record_max") or {}
        if x["n_meses"] >= MIN_SERIE_MESES and str(rmax.get("fecha", ""))[:4] == str(anio) and (stt.get("max_anio_hist") or {}).get("anio") == anio:
            recs.append({**x, "rv": rmax["valor"], "rf": rmax["fecha"], "desde": (stt.get("inicio") or "")[:4]})
        mismos = _meses_de(M, b, mm_ult)
        este = [v for y, v in mismos if y == ult[:4]]
        if este and len(mismos) >= MIN_MESES:
            orden = sorted((v for _, v in mismos), reverse=True)
            puesto = orden.index(este[0]) + 1
            if puesto <= 2:
                seps.append({**x, "sv": este[0], "puesto": puesto, "n_sep": len(mismos), "s0": mismos[0][0]})
    if len(recs) < 2 and not any(s["puesto"] == 1 for s in seps):
        return None
    mes_nom = R.MESES[int(mm_ult) - 1]
    hechos = []
    recs.sort(key=lambda r: -r["rv"])
    if recs:
        hechos.append(R.hecho("rec_n", f"{len(recs)} boyas de Puertos del Estado con al menos 10 años de datos midieron en {anio} la temperatura del agua más alta "
                              f"de su serie: {R.lista_y([r['nombre'] for r in recs])}.", FUENTE, [str(len(recs)), "10", str(anio)], superlativo=True, record=True))
        for i, r in enumerate(recs):
            hechos.append(R.hecho(f"rec_{i}", f"{_de_la_boya(r['k'], r['nombre'])[0].upper() + _de_la_boya(r['k'], r['nombre'])[1:]} llegó a {R.d1(r['rv'])} °C "
                                  f"el {R.dia(r['rf'], semana=False)}, el valor más alto de su serie, que empieza en {r['desde']}.", FUENTE,
                                  [f"{R.d1(r['rv'])} °C", r["desde"]], lugar=r["nombre"], superlativo=True, record=True, liga=[f"{R.d1(r['rv'])} °C"]))
    primeros = [s for s in seps if s["puesto"] == 1]
    if primeros:
        hechos.append(R.hecho("sep_n", f"{mes_nom.capitalize()} de {ult[:4]} fue el {mes_nom} más cálido de la serie en {len(primeros)} boyas: "
                              f"{R.lista_y([s['nombre'] for s in primeros])}.", FUENTE, [str(len(primeros)), ult[:4]], superlativo=True, record=True))
        for i, s in enumerate(primeros):
            hechos.append(R.hecho(f"sep_{i}", f"En {_de_la_boya(s['k'], s['nombre'])}, el agua tuvo en {mes_nom} una media de {R.d1(s['sv'])} °C, la más alta de los "
                                  f"{s['n_sep']} {MESES_PLURAL[int(mm_ult) - 1]} con dato de su serie, que empieza en {s['s0']}.", FUENTE, [f"{R.d1(s['sv'])} °C", str(s["n_sep"]), s["s0"]],
                                  lugar=s["nombre"], superlativo=True, record=True, liga=[f"{R.d1(s['sv'])} °C"]))
    if recs:
        tit = f"{len(recs)} boyas de Puertos del Estado midieron en {anio} el agua más caliente de su serie"
        sub = " ".join(h["dice"] for h in hechos[1:3])
    else:
        tit = f"{mes_nom.capitalize()} de {ult[:4]}, el {mes_nom} más cálido de la serie en {len(primeros)} boyas de Puertos del Estado"
        sub = hechos[1]["dice"] if len(hechos) > 1 else ""
    pl = _pl(tit, sub, hechos)
    if not _ok(R, pl, hechos, "récords del año"):
        return None
    cif = []
    if recs:
        cif.append({"n": str(len(recs)), "l": f"boyas con el agua más caliente de su serie en {anio}", "tono": "calor"})
        cif.append({"n": f"{R.d1(recs[0]['rv'])} °C", "l": f"{recs[0]['nombre']}, el {R.dia(recs[0]['rf'], semana=False)}", "tono": "calor"})
    if primeros:
        cif.append({"n": str(len(primeros)), "l": f"boyas con el {mes_nom} más cálido de su serie", "tono": "calor"})
    fecha = f"{ult}-{30 if mm_ult in ('04', '06', '09', '11') else (28 if mm_ult == '02' else 31)}"
    h = R.historia("mar_records", f"{fecha}-mar-boyas-records-{anio}", "Mar · récords en las boyas", "calor", 46 + min(8, len(recs)) + (4 if primeros else 0),
                   hechos, pl, cif, fuentes=FUENTE,
                   metodo=(f"Valor más alto medido por cada boya en toda su serie (solo boyas con al menos 10 años de datos) y medias mensuales de {mes_nom} "
                           f"de cada año con dato (al menos {MIN_MESES})."),
                   limites=["Las series de las boyas tienen huecos: «el más alto de su serie» se refiere a los días y meses con dato.",
                            "Es la temperatura del agua en la boya, no la de toda la costa."],
                   pagina=PAGINA)
    h["fecha"] = fecha
    graf = max(primeros, key=lambda s: s["n_sep"]) if primeros else None
    if graf:
        h["grafico"] = _grafico_serie_mes(R, graf, _meses_de(M, graf["b"], mm_ult), h["id"],
                                          f"{mes_nom.capitalize()} en {_de_la_boya(graf['k'], graf['nombre'])}, año a año")
    # versiones provinciales
    for cod in sorted({c for x in recs + primeros for c in PROV_BOYA.get(x["k"], [])}):
        hv, nombres = [], []
        for i, r in enumerate([r for r in recs if cod in PROV_BOYA.get(r["k"], [])]):
            hv.append(next(hh for hh in hechos if hh["id"] == f"rec_{recs.index(r)}"))
            nombres.append(r["nombre"])
        for s in [s for s in primeros if cod in PROV_BOYA.get(s["k"], [])]:
            hv.append(next(hh for hh in hechos if hh["id"] == f"sep_{primeros.index(s)}"))
            nombres.append(s["nombre"])
        if not hv:
            continue
        hv.append(R.hecho("rec_nac", "En el conjunto de España: " + hechos[0]["dice"][0].lower() + hechos[0]["dice"][1:], FUENTE, hechos[0]["valores"],
                          superlativo=True, record=True))
        n0 = nombres[0]
        r0 = next((r for r in recs if r["nombre"] == n0), None)
        s0 = next((s for s in primeros if s["nombre"] == n0), None)
        if r0 and s0:
            tit_p = f"El agua en {n0} llegó en {anio} a {R.d1(r0['rv'])} °C, la más caliente desde que hay datos ({r0['desde']}), y {mes_nom} fue el más cálido de su serie"
        elif r0:
            tit_p = f"El agua en {n0} llegó a {R.d1(r0['rv'])} °C el {R.dia(r0['rf'], semana=False)}, la más caliente desde que hay datos ({r0['desde']})"
        else:
            tit_p = f"{mes_nom.capitalize()} de {ult[:4]}, el {mes_nom} con el agua más cálida en {n0} desde que hay datos ({s0['s0']})"
        pl_p = {"titular": tit_p, "subtitulo": hv[1]["dice"] if len(hv) > 2 else "", "entradilla": hv[0]["dice"], "cuerpo": [x["dice"] for x in hv[1:]],
                "claves": [x["dice"] for x in hv[:3]]}
        if not _ok(R, pl_p, hv, f"récords {cod}"):
            continue
        cif_p = ([{"n": f"{R.d1(r0['rv'])} °C", "l": f"{n0}, {R.dia(r0['rf'], semana=False)}: el agua más caliente de su serie, que empieza en {r0['desde']}", "tono": "calor"}] if r0 else []) + \
                ([{"n": f"{R.d1(s0['sv'])} °C", "l": f"media de {mes_nom} en {n0}, la más alta de sus {s0['n_sep']} {MESES_PLURAL[int(mm_ult) - 1]} con dato (desde {s0['s0']})", "tono": "calor"}] if s0 else [])
        v = {"provincia": R.nprov(cod), "slug": R.PROV[cod][1], "hechos": hv, "plantilla": pl_p, "cifras": cif_p,
             "puntos": round(42 + (6 if r0 else 0) + (6 if s0 else 0), 1)}
        x0 = s0 or next((x for x in boyas if x["nombre"] == n0), None)
        if x0:
            v["grafico"] = _grafico_serie_mes(R, x0, _meses_de(M, x0["b"], mm_ult), f"{h['id']}-{cod}", f"{mes_nom.capitalize()} en {n0}, año a año")
        h["provincias"][cod] = v
    return h


def generar(R, D):
    boyas, M = _boyas(R)
    if not boyas:
        R.LOG.append("mar: sin datos de boyas recientes")
        return []
    out = []
    for f in (_historia_boyas, ):
        h = f(R, boyas)
        if h:
            out.append(h)
    h = _historia_records(R, boyas, M)
    if h:
        out.append(h)
    return out
