"""Impacto: muertes atribuibles al calor (sistema MoMo del Instituto de Salud Carlos III).

Fuente: docs/calor_mortalidad.json (calor_mortalidad_generar.py, clima-scripts). Desde el 18-10-2026 los totales se
suman con los valores diarios sin redondear (`metodo_suma: diaria_sin_redondear`); si el fichero no lleva esa marca, no
se publica (auditoría del 17-10-2026: el redondeo diario desviaba los totales hasta 8 defunciones por provincia).

`historico_anual` es el total de junio a septiembre de cada verano: coincide, a ±1 por redondeo, con la suma de
`comparativa_mensual` 06-09 de cada año (comprobado 2015-2025). El verano en curso se suma aquí con los valores
exactos de `meses` (06-09), que es lo mismo que la suma de las 52 provincias (5.684,3 el 18-10-2026, igual que MoMo).

Los datos de desastres (docs/desastres_*.json) no se usan: el propio fichero avisa de que son una lista semilla con
valores aproximados que hay que sustituir por la exportación oficial del Consorcio antes de publicar.
"""
from __future__ import annotations

SECCION = "impacto"
PAGINA = "https://calentamientoglobal.es/muertes-por-calor-espana/"
MESES_VERANO = ("06", "07", "08", "09")
UMBRAL_PROVINCIA = 20  # como en los partes: por debajo, cifras muy pequeñas para una estimación estadística


def _grafico_veranos(R, serie, anio, nombre):
    """Barras: muertes atribuibles al calor de junio a septiembre, un verano por barra; el de este año, en color."""
    W, Hh, ml, mr, mt, mb = 640, 300, 52, 16, 26, 34
    mx = max(v for _, v in serie)
    tope = (int(mx / 1000) + 1) * 1000
    Y = lambda v: mt + (1 - v / tope) * (Hh - mt - mb)
    bw = (W - ml - mr) / len(serie)
    s = []
    for t in range(0, tope + 1, 1000):
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{R.RAYA}" stroke-width="1"></line>')
        s.append(R._t(ml - 6, Y(t) + 4, R.miles(t), 11, R.GRIS, "end"))
    for i, (a, v) in enumerate(serie):
        x0 = ml + i * bw + 5
        dest = a == anio
        s.append(f'<rect x="{x0:.1f}" y="{Y(v):.1f}" width="{bw - 10:.1f}" height="{Y(0) - Y(v):.1f}" fill="{R.CALOR if dest else "#E3A487"}"></rect>')
        s.append(R._t(x0 + (bw - 10) / 2, Hh - mb + 16, str(a), 11, R.TINTA if dest else R.GRIS, "middle", 700 if dest else 400))
        if dest or v == max(x for b, x in serie if b != anio):
            s.append(R._t(x0 + (bw - 10) / 2, Y(v) - 6, R.miles(v), 12, R.TINTA, "middle", 700))
    titulo = f"Muertes atribuibles al calor de junio a septiembre, {serie[0][0]}-{anio}"
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, [(a, v) for a, v in serie], ["verano", "muertes_atribuibles_calor_jun_sep"], titulo,
                             [{"t": "banda", "c": R.CALOR, "l": str(anio)}, {"t": "banda", "c": "#E3A487", "l": "Veranos anteriores"}],
                             "Estimación del sistema MoMo del Instituto de Salud Carlos III: defunciones atribuibles al exceso de temperatura "
                             "entre el 1 de junio y el 30 de septiembre. Fuente: MoMo (ISCIII). Gráfico: calentamientoglobal.es.")


def _grafico_meses_prov(R, nombre_prov, meses, anio, nombre):
    etiquetas = {"06": "Junio", "07": "Julio", "08": "Agosto", "09": "Septiembre"}
    vals = [(m, int(meses.get(m) or 0)) for m in MESES_VERANO]
    W, Hh, ml, mr, mt, mb = 640, 240, 40, 16, 26, 32
    mx = max(1, max(v for _, v in vals))
    Y = lambda v: mt + (1 - v / mx) * (Hh - mt - mb)
    bw = (W - ml - mr) / 4
    top = max(v for _, v in vals)
    s = [f'<line x1="{ml}" x2="{W - mr}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="{R.RAYA}" stroke-width="1"></line>']
    for i, (m, v) in enumerate(vals):
        x0 = ml + i * bw + 18
        dest = v == top and v > 0
        s.append(f'<rect x="{x0:.1f}" y="{Y(v):.1f}" width="{bw - 36:.1f}" height="{max(0.0, Y(0) - Y(v)):.1f}" fill="{R.CALOR if dest else "#E3A487"}"></rect>')
        s.append(R._t(x0 + (bw - 36) / 2, Y(v) - 6, str(v), 13, R.TINTA, "middle", 700 if dest else 500))
        s.append(R._t(x0 + (bw - 36) / 2, Hh - mb + 18, etiquetas[m], 12, R.GRIS, "middle"))
    titulo = f"Muertes atribuibles al calor en {nombre_prov}, verano de {anio}"
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, [(etiquetas[m], v) for m, v in vals], ["mes", "muertes_atribuibles_calor"], titulo, [],
                             "Estimación mensual del sistema MoMo del Instituto de Salud Carlos III (cada mes, redondeado una vez). "
                             "Fuente: MoMo (ISCIII). Gráfico: calentamientoglobal.es.")


def generar(R, D):
    C = R.leer(R.DOCS / "calor_mortalidad.json", {}) or {}
    if C.get("metodo_suma") != "diaria_sin_redondear":
        R.LOG.append("impacto: calor_mortalidad.json sin la suma diaria sin redondear; no se publica")
        return []
    meses = {m["mes"]: m for m in (C.get("meses") or [])}
    hist = {int(x["anio"]): int(x["atribuibles_calor"]) for x in (C.get("historico_anual") or []) if x.get("atribuibles_calor") is not None}
    provs = C.get("provincias") or {}
    if not hist or not provs:
        return []
    # el verano en curso: el último con los cuatro meses en `meses` y septiembre ya cerrado en las provincias
    periodos = {(p.get("desde"), p.get("hasta")) for p in provs.values()}
    if len(periodos) != 1:
        R.LOG.append(f"impacto: periodos provinciales distintos {sorted(periodos)}")
        return []
    desde, hasta = periodos.pop()
    anio = int(desde[:4])
    if not (desde == f"{anio}-06-01" and hasta == f"{anio}-09-30") or anio in hist:
        return []
    if not all(f"{anio}-{m}" in meses for m in MESES_VERANO):
        return []
    exacto = sum(float(meses[f"{anio}-{m}"].get("exacto", meses[f"{anio}-{m}"]["atribuibles"])) for m in MESES_VERANO)
    total = int(exacto + 0.5)
    suma_prov = sum(float(p.get("verano_exacto", p.get("verano") or 0)) for p in provs.values())
    if abs(suma_prov - exacto) > 2:
        R.LOG.append(f"impacto: la suma provincial ({suma_prov:.1f}) no cuadra con la nacional ({exacto:.1f})")
        return []
    a_max = max(hist, key=lambda a: hist[a])
    previo = hist[a_max]
    a0 = min(hist)
    record = total > previo
    mes_top = max(MESES_VERANO, key=lambda m: float(meses[f"{anio}-{m}"].get("exacto", 0)))
    v_top = int(meses[f"{anio}-{mes_top}"]["atribuibles"])
    mes_nom = R.MESES[int(mes_top) - 1]
    fuente = C.get("fuente") or "MoMo · Instituto de Salud Carlos III"
    act = (C.get("actualizado") or R.HOY.isoformat())[:10]
    periodo = f"entre el 1 de junio y el 30 de septiembre de {anio}"

    hechos = [
        R.hecho("mortalidad_verano", f"Las muertes atribuibles al calor en España {periodo} suman {R.miles(total)}, con los datos diarios del sistema MoMo "
                f"del Instituto de Salud Carlos III.", fuente, [R.miles(total), str(anio)]),
    ]
    if record:
        hechos.append(R.hecho("mortalidad_record", f"Es la cifra más alta de la serie de MoMo, que empieza en {a0}: la anterior más alta fue la de {a_max}, "
                              f"con {R.miles(previo)}, y la de este verano la supera en {R.miles(total - previo)}.", fuente,
                              [str(a0), str(a_max), R.miles(previo), R.miles(total - previo)], superlativo=True, record=True))
    else:
        hechos.append(R.hecho("mortalidad_contexto", f"La cifra más alta de la serie de MoMo, que empieza en {a0}, sigue siendo la de {a_max}, con {R.miles(previo)}.",
                              fuente, [str(a0), str(a_max), R.miles(previo)], superlativo=True))
    hechos.append(R.hecho("mortalidad_mes", f"El mes con más muertes atribuibles al calor fue {mes_nom}, con {R.miles(v_top)}.", fuente, [R.miles(v_top)], superlativo=True))
    orden = sorted(provs.items(), key=lambda kv: -float(kv[1].get("verano_exacto", kv[1].get("verano") or 0)))
    top3 = orden[:3]
    hechos.append(R.hecho("mortalidad_provincias", "Las provincias con más fueron " + R.lista_y([f"{p['nombre']} ({R.miles(p['verano'])})" for _, p in top3]) + ".",
                          fuente, [R.miles(p["verano"]) for _, p in top3], superlativo=True))
    hechos.append(R.hecho("mortalidad_metodo", "Son una estimación estadística del exceso de defunciones atribuible a la temperatura, no muertes por golpe de calor.",
                          fuente))
    if record:
        tit = f"El verano de {anio} deja {R.miles(total)} muertes atribuibles al calor, la cifra más alta de la serie, que empieza en {a0}"
    else:
        tit = f"El verano de {anio} deja {R.miles(total)} muertes atribuibles al calor en España, con datos de MoMo"
    pl = {"titular": tit, "subtitulo": hechos[1]["dice"], "entradilla": hechos[0]["dice"],
          "cuerpo": [hechos[1]["dice"] + " " + hechos[2]["dice"], hechos[3]["dice"] + " " + hechos[4]["dice"]],
          "claves": [h["dice"] for h in hechos[:4]]}
    cifras = [{"n": R.miles(total), "l": f"muertes atribuibles al calor en España {periodo} (MoMo)", "tono": "calor"},
              {"n": R.miles(previo), "l": f"en {a_max}, la más alta hasta {anio} en la serie, que empieza en {a0}", "tono": "calor"},
              {"n": R.miles(v_top), "l": f"en {mes_nom}, el mes con más", "tono": "calor"}]
    base = f"{hasta}-muertes-calor-verano"
    h = R.historia("mortalidad_calor", base, "Impacto · muertes por calor", "calor", 62 if record else 45, hechos, pl, cifras, fuentes=fuente,
                   metodo=(C.get("nota_metodo") or "") + " Verano: del 1 de junio al 30 de septiembre; total sumado con los valores diarios sin redondear.",
                   limites=["Estimación que el ISCIII revisa a medida que entran defunciones: citar como «según la estimación del sistema MoMo».",
                            "No son muertes por golpe de calor, sino el exceso de mortalidad que el modelo atribuye a la temperatura."],
                   pagina=PAGINA)
    h["seccion"] = SECCION
    h["fecha"] = act
    serie = sorted(hist.items()) + [(anio, total)]
    try:
        h["grafico"] = _grafico_veranos(R, serie, anio, base)
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"impacto: gráfico nacional: {e}")
    nac_ctx = R.hecho("mortalidad_nac", f"En toda España, las muertes atribuibles al calor en el mismo periodo suman {R.miles(total)} con los datos de MoMo"
                      + (f", la cifra más alta de la serie, que empieza en {a0}." if record else "."),
                      fuente, [R.miles(total), str(a0), str(anio)], superlativo=record, record=record)

    # versiones provinciales
    por_slug = {v[1]: k for k, v in R.PROV.items()}
    puestos = {slug: i + 1 for i, (slug, _) in enumerate(orden)}
    for slug, p in provs.items():
        cod = por_slug.get(slug) or por_slug.get(slug.replace("_", "-"))
        if not cod or (p.get("verano") or 0) < UMBRAL_PROVINCIA:
            continue
        P = R.nprov(cod)
        n = int(p["verano"])
        mp = p.get("meses") or {}
        m_top = max(MESES_VERANO, key=lambda m: int(mp.get(m) or 0))
        hv = [R.hecho("mortalidad_prov", f"Las muertes atribuibles al calor en {P} {periodo} suman {R.miles(n)}, con los datos diarios del sistema MoMo del Instituto de Salud Carlos III.",
                      fuente, [R.miles(n), str(anio)])]
        pu = puestos[slug]
        if pu <= 10:
            hv.append(R.hecho("mortalidad_puesto", f"Es la {'provincia con más muertes atribuibles al calor de España' if pu == 1 else f'{ORDINALES[pu]} provincia con más de España'} en ese periodo, "
                              f"con las cifras provinciales de MoMo.", fuente, [], superlativo=True))
        hv.append(R.hecho("mortalidad_prov_mes", f"El mes con más en {P} fue {R.MESES[int(m_top) - 1]}, con {R.miles(int(mp.get(m_top) or 0))}.", fuente,
                          [R.miles(int(mp.get(m_top) or 0))], superlativo=True))
        hv.append(nac_ctx)
        hv.append(hechos[-1])
        plv = {"titular": f"{P} suma {R.miles(n)} muertes atribuibles al calor en el verano de {anio}, con datos de MoMo",
               "subtitulo": hv[1]["dice"], "entradilla": hv[0]["dice"],
               "cuerpo": [" ".join(x["dice"] for x in hv[1:-2]), hv[-2]["dice"] + " " + hv[-1]["dice"]],
               "claves": [x["dice"] for x in hv[:3]]}
        v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": R.miles(n), "l": f"muertes atribuibles al calor en {P} {periodo} (MoMo)", "tono": "calor"},
                        {"n": R.miles(total), "l": "en toda España en el mismo periodo", "tono": "calor"}],
             "puntos": round(min(60.0, 30 + n / 25), 1)}
        try:
            v["grafico"] = _grafico_meses_prov(R, P, mp, anio, f"{base}-{cod}")
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"impacto: gráfico {cod}: {e}")
        h["provincias"][cod] = v
    return [h]


ORDINALES = {2: "segunda", 3: "tercera", 4: "cuarta", 5: "quinta", 6: "sexta", 7: "séptima", 8: "octava", 9: "novena", 10: "décima"}
