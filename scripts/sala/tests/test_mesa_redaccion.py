#!/usr/bin/env python3
"""Pruebas de la mesa de redacción (scripts/mesa_redaccion.py): agrupación, escala única, marcos grandes (H1) y día sin noticia.
Uso: python -m pytest -q scripts/sala/tests/test_mesa_redaccion.py"""
import sys
from datetime import datetime
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import mesa_redaccion as M  # noqa: E402

HOY = date(2026, 11, 25)


def _huella(terr, i):
    return {"id": f"huella-antes-raro-{i}", "serie": "huella", "tipo": "antes_raro", "indicador": "mes_media_alta", "ambito": "provincial",
            "territorio": terr, "fecha_dato": "2026-11-24", "cierre_mes": "en_curso", "citabilidad": "alta", "fuerza": 100.0,
            "titular": f"{terr} lleva en lo que va de noviembre…", "rareza": {"T_antes": 100, "T_ahora": 5 + i, "PR": 20}, "limites": ["x"]}


def test_agrupa_la_misma_historia_capital_a_capital():
    caps = ["Valencia", "Murcia", "Zaragoza", "Barcelona", "Las Palmas"]
    hs = [_huella(c, i) for i, c in enumerate(caps)] + [{"id": "otra", "serie": "compuestos", "tipo": "compuesto", "indicador": "x",
                                                           "ambito": "nacional", "territorio": "España", "fecha_dato": "2026-11-24", "titular": "t"}]
    g = M.agrupar(hs)
    nac = [h for h in g if h.get("agregada_por_mesa")]
    assert len(nac) == 1 and len(g) == 2
    assert len(nac[0]["versiones_provinciales"]) == 5
    assert nac[0]["titular"].startswith("En 5 capitales")
    assert not any(h.get("ambito") == "provincial" for h in g)     # las provinciales no compiten con la nacional


def test_dos_capitales_no_son_nacional():
    g = M.agrupar([_huella("Valencia", 0), _huella("Murcia", 1)])
    assert all(h["ambito"] == "provincial" for h in g)


def test_escala_0_100_y_puertas():
    alto = M.puntuar({"pob": 10_000_000, "n_lugares": 25, "ambito": "nacional", "fuente": "estacion", "puesto": 1, "n_anios": 101,
                      "edad": 8, "edad_disponible": 0, "calidad": "validado", "novedad": 1, "invalidar": "x", "plantilla": True,
                      "periodo_validado": True, "titular": "t"})
    assert 85 <= alto["puntos"] <= 100 and alto["portada"]
    rean = M.puntuar({"pob": 400_000, "ambito": "provincial", "fuente": "reanalisis", "puesto": 1, "n_anios": 87, "edad": 3,
                      "calidad": "reanalisis", "novedad": 1, "invalidar": "x", "plantilla": True, "titular": "Murcia bate por 3,2 °C su máxima"})
    assert not rean["puertas"]["se_sostiene"]                      # reanálisis sin decirlo en el titular: fuera
    corta = M.puntuar({"pob": 300_000, "ambito": "provincial", "fuente": "corta", "puesto": 1, "n_anios": 15, "edad": 1,
                       "calidad": "tiempo_real", "novedad": 1, "invalidar": "x", "plantilla": True, "titular": "Pego"})
    assert not corta["puertas"]["rareza"]                          # 15 otoños no es una serie que aguante
    ayer = M.puntuar({"pob": 10_000_000, "n_lugares": 25, "ambito": "nacional", "fuente": "estacion", "puesto": 1, "n_anios": 101,
                      "edad": 2, "calidad": "validado", "novedad": 0, "invalidar": "x", "plantilla": True, "titular": "t"})
    assert not ayer["portada"]                                     # lo que ayer ya era verdad con la misma cifra no es noticia


def test_h1_enero_octubre():
    """H1 (almacén 2, bloque D, 25-11): enero-octubre de 2026, el más cálido registrado en las capitales con serie de AEMET de ≥ 40 años,
    entre ellas Madrid-Retiro desde 1923. Con la serie del archivo público salen las 20 del almacén y alguna más."""
    hs = M.marcos_grandes(date(2026, 11, 5), lag=5, colas=("calor",))
    nac = [h for h in hs if h["tipo_mesa"] == "marco_nacional" and h["periodo"] == "anio"]
    assert len(nac) == 1
    assert nac[0]["titular"].startswith("Enero-octubre de 2026, el más cálido registrado en")
    assert "en Madrid, desde 1923" in nac[0]["titular"]
    caps = set(nac[0]["_miembros_territorios"])
    h1 = {"Madrid", "Zamora", "León", "Burgos", "Soria", "Salamanca", "Logroño", "Bilbao", "Cuenca", "Almería", "Ciudad Real",
          "Valladolid", "Ourense", "Castellón", "Pamplona", "Toledo", "Cáceres", "Lleida", "Ávila", "Murcia"}
    # Almería (25,92 °C, como en 2025) y Salamanca (23,09, como en 2017) empatan con su récord: «iguala», no «el más cálido»
    empates = {"Almería", "Salamanca"}
    assert h1 - empates <= caps and not (empates & caps)
    iguala = [h for h in hs if h["tipo_mesa"] == "marco_capital" and h["periodo"] == "anio" and h["territorio"] in empates]
    assert len(iguala) == 2 and all("iguala" in h["titular"] for h in iguala)


def test_dia_sin_noticia():
    c = {"titular": "Lo que va de 2026…", "clave": {"indicador": "marco:anio:calor", "territorio": "pais:es", "periodo": "2026-01-01"},
         "cifra": {"n_primeros": 25}, "marco": {"n_primeros": 25, "cerrado": False, "hito": None},
         "rasgos": {"pob": 9e6, "n_lugares": 25, "ambito": "nacional", "fuente": "estacion", "puesto": 1, "n_anios": 101, "edad": 8,
                    "calidad": "validado", "invalidar": "x", "plantilla": True, "periodo_validado": True, "titular": "t", "seccion": "noticia"}}
    emitidos = {}
    p1 = M.portada([dict(c, rasgos=dict(c["rasgos"]))], HOY, emitidos)
    assert p1["historia_del_dia"] is not None
    c2 = dict(c, marco={"n_primeros": 26, "cerrado": False, "hito": None}, rasgos=dict(c["rasgos"]))
    p2 = M.portada([c2], HOY, emitidos)                            # 25 → 26 capitales: no es noticia
    assert p2["sin_noticia"] and p2["historia_del_dia"] is None
    c3 = dict(c, marco={"n_primeros": 26, "cerrado": False, "hito": "2026-11-30"}, rasgos=dict(c["rasgos"]))
    assert M.portada([c3], HOY, emitidos)["historia_del_dia"] is not None   # se cierra el mes: sí


# ============================================================================ chat 2 (25-11-2026): decisión 5, día real, día roto y portada
import json  # noqa: E402
import shutil  # noqa: E402

import portada_prensa as P  # noqa: E402
import coherencia as C  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent.parent


def _raiz_tmp(tmp_path, hoy_json=True, hallazgos="real"):
    """Raíz de pruebas: solo docs/prensa con los JSON reales de la web (o rotos); el archivo de AEMET se lee del repo."""
    d = tmp_path / "docs" / "prensa" / "noticias"
    d.mkdir(parents=True)
    if hallazgos == "real":
        shutil.copy(RAIZ / "docs" / "prensa" / "hallazgos.json", tmp_path / "docs" / "prensa" / "hallazgos.json")
    elif hallazgos == "roto":
        (tmp_path / "docs" / "prensa" / "hallazgos.json").write_text('{"enviables": [{"id": ', encoding="utf-8")
    if hoy_json:
        shutil.copy(RAIZ / "docs" / "prensa" / "noticias" / "hoy.json", d / "hoy.json")
    return tmp_path


def test_hidro_solo_lluvia_y_sequia():
    """Decisión 5: el año hidrológico (cerrado el 30-9) no emite las colas calor y noches; el año natural sí."""
    hs = M.marcos_grandes(date(2026, 10, 8), lag=8)
    pares = {(h["periodo"], h["cola"]) for h in hs}
    assert ("hidro", "calor") not in pares and ("hidro", "noches") not in pares
    assert ("anio", "calor") in pares and ("anio", "noches") in pares
    assert M.COLAS_POR_PERIODO["hidro"] == ("lluvioso", "seco")


def test_agrupacion_real_antes_raro():
    """Con los hallazgos reales de hoy, las huellas «antes era raro» de cada capital pasan a una nacional con sus versiones dentro."""
    h = json.load(open(RAIZ / "docs" / "prensa" / "hallazgos.json"))
    lista = [x for x in h["enviables"] + h["locales"] if x.get("serie") == "huella" and x.get("tipo") == "antes_raro"
             and x.get("ambito") == "provincial" and x.get("indicador") == "mes_media_alta"]
    g = M.agrupar(lista)
    nac = [x for x in g if x.get("agregada_por_mesa")]
    assert len(nac) >= 1
    assert sum(len(x["versiones_provinciales"]) for x in nac) >= 20
    assert not [x for x in g if x.get("ambito") == "provincial" and x.get("indicador") == "mes_media_alta"
                and x["fecha_dato"][:7] == nac[0]["fecha_dato"][:7]]    # ninguna capital repetida fuera de su nacional


def test_escala_componentes_acotados_y_orden():
    base = {"pob": 1_000_000, "ambito": "provincial", "fuente": "estacion", "puesto": 1, "n_anios": 80, "edad": 1, "calidad": "validado",
            "novedad": 1, "invalidar": "x", "plantilla": True, "titular": "t"}
    a = M.puntuar(base)
    b = M.puntuar({**base, "n_anios": 8, "fuente": "corta"})
    c = M.puntuar({**base, "puesto": 3})
    assert all(0 <= a[k] <= 1 for k in "ARNFQ") and 0 <= a["puntos"] <= 100
    assert a["puntos"] > c["puntos"] > b["puntos"] or a["puntos"] > b["puntos"]
    em = M.puntuar({**base, "emergencia": True, "fuente": "sin_serie", "puesto": None, "n_anios": None})
    assert em["puertas"]["rareza"]                                  # la emergencia abre aunque no sea récord (decisión 1)


def test_dia_real_ya_no_sale_sin_noticia(tmp_path):
    """Día real (25-11-2026): con lo emitido ayer, ninguna historia es nueva. Desde el 26-11 eso ya no vacía la portada: abre el dato del día
    (sello «dato del día», no «excepcional»); relanzar el mismo día no cambia nada."""
    raiz = _raiz_tmp(tmp_path)
    ayer = P.generar(date(2026, 11, 24), raiz)             # primer día: el marco de 2026 abre
    assert not ayer["sin_noticia"] and "capitales" in ayer["historia_del_dia"]["titular"]
    hoy = P.generar(date(2026, 11, 25), raiz)
    assert hoy["sin_noticia"] is False and hoy["dato_del_dia"]["titular"] and hoy["dato_del_dia"]["sello"] == "dato_del_dia"
    assert hoy["retraso_validado_dias"] == 8
    otra = P.generar(date(2026, 11, 25), raiz)              # relanzado el mismo día: igual
    assert otra["dato_del_dia"]["titular"] == hoy["dato_del_dia"]["titular"] and otra["totales"] == hoy["totales"]
    assert json.load(open(raiz / "docs" / "prensa" / "portada.json"))["fecha"] == "2026-11-25"
    # la rutina está en «Datos del día», no en la portada; sin titulares repetidos por ciudad
    assert hoy["datos_del_dia"] and all(x["puntos"] >= 0 for x in hoy["datos_del_dia"])
    titulares = [x["titular"] for k in ("datos_del_dia", "contexto") for x in hoy[k]]
    assert len(titulares) == len(set(titulares))


def test_primer_dia_emite_y_guarda_ficheros(tmp_path):
    raiz = _raiz_tmp(tmp_path)
    s = P.generar(date(2026, 11, 25), raiz)
    d = s["historia_del_dia"]
    assert d and d["nota"] and (raiz / "docs" / d["nota"]).exists()
    assert d["grafico"] and (raiz / "docs" / d["grafico"]["svg"]).read_text().startswith("<svg")
    assert d["versiones_provinciales"] and d["citar"] and d["puertas"] and set(d["componentes"]) == set("ARNFQ")
    assert "NaN" not in json.dumps(s) and "None" not in json.dumps(s)


def test_dia_roto_no_cae(tmp_path):
    """Día roto: hallazgos.json truncado y sin noticias/hoy.json. La portada sale con lo que hay y dice qué falta."""
    raiz = _raiz_tmp(tmp_path, hoy_json=False, hallazgos="roto")
    P.generar(date(2026, 11, 24), raiz)
    s = P.generar(date(2026, 11, 25), raiz)
    assert s["sin_noticia"] is False and s["dato_del_dia"]["titular"]
    assert any("hallazgos.json" in a for a in s["avisos"]) and any("hoy.json" in a for a in s["avisos"])
    ruta = tmp_path / "docs" / "prensa" / "portada.json"
    assert json.load(open(ruta))["sin_noticia"] is False


def test_coherencia_hoy_del_clima_no_es_fecha():
    """Fallo huella-antes-raro-espana-2026-11-18: «hoy son al menos tres veces más probables» habla del clima actual."""
    t = ("11 capitales tuvieron el 18 de noviembre temperaturas medias que en 1961-1990 eran raras (una vez cada 10 años o menos) "
         "y hoy son al menos tres veces más probables")
    assert not C.fallo_hoy(t, "2026-11-18", datetime(2026, 11, 25, 12, 0, tzinfo=C.MADRID))
    assert C.fallo_hoy("Hoy llueve en Murcia", "2026-11-18", datetime(2026, 11, 25, 12, 0, tzinfo=C.MADRID))
