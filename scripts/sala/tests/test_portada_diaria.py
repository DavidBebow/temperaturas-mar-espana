#!/usr/bin/env python3
"""Pruebas de la portada diaria (scripts/portada_prensa.py + scripts/portada_bloques.py): seis bloques siempre con contenido,
52 provincias con titular, el 25-11 real ya no sale «sin noticia», la misma historia no abre un tercer día y un empate no dice «el más».
Usan los datos del repositorio (sin red).  Uso: python -m pytest -q scripts/sala/tests/test_portada_diaria.py"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import portada_bloques as B  # noqa: E402
import portada_prensa as P   # noqa: E402

HOY = date(2026, 11, 25)
BLOQUES = ("carreras", "tal_dia_como_hoy", "espana_ayer", "provincias", "lo_que_viene")
_CACHE = {}


def _vacia():
    if "v" not in _CACHE:
        _CACHE["v"] = P.generar(HOY, escribir=False, hall={}, hoy_json={})
    return _CACHE["v"]


def _real():
    if "r" not in _CACHE:
        _CACHE["r"] = P.generar(HOY, escribir=False)
    return _CACHE["r"]


def test_hallazgos_vacio_sigue_dando_seis_bloques_con_contenido():
    s = _vacia()
    assert s["sin_noticia"] is False and "sin_noticia_texto" not in {k for k, v in s.items() if v and k == "sin_noticia_texto"}
    assert s["dato_del_dia"]["titular"] and s["dato_del_dia"]["sello"] in P.SELLOS
    assert s["carreras"]["piezas"] and 3 <= len(s["carreras"]["piezas"]) <= 6
    assert s["tal_dia_como_hoy"]["portada"]
    assert len(s["espana_ayer"]["cifras"]) == 6 and all(c["id"] for c in s["espana_ayer"]["cifras"])
    assert s["provincias"]["por_slug"] and s["lo_que_viene"]["prevision"]["textos"] and s["lo_que_viene"]["agenda"]
    assert s["generado_utc"] and all(k in s["dato_hasta"] for k in ("carreras", "espana_ayer", "lo_que_viene"))


def test_las_52_provincias_tienen_titular_y_cifras():
    pv = _vacia()["provincias"]["por_slug"]
    assert len(pv) == 52 == len(B.PROVINCIAS)
    for slug, v in pv.items():
        assert v["dato_del_dia"]["titular"], slug
        assert v["dato_del_dia"]["sello"] == "dato_del_dia" and v["cifras"] is not None


def test_el_25_de_noviembre_real_abre_con_dato_del_dia_y_no_con_sin_noticia():
    s = _real()
    d = s["dato_del_dia"]
    assert d["titular"] and d["sello"] in ("dato_del_dia", "excepcional", "en_seguimiento")
    assert s["sin_noticia"] is False and s["mas_historias"]
    assert all(m["sello"] in P.SELLOS for m in s["mas_historias"])
    assert not any("histór" in (m.get("titular") or "").lower() for m in [d] + s["mas_historias"])      # nunca «histórico»


def _cand(k, cifra, puntos=40, portada=False, emergencia=False):
    return {"_k": k, "_cifra": cifra, "titular": k, "puntuacion": {"puntos": puntos, "portada": portada, "mas": True, "puertas": {}, "medio": "x", "A": 0, "R": 0, "N": 0, "F": 0, "Q": 0},
            "rasgos": {"emergencia": emergencia}}


def _hist(k, cifra, dias):
    return [{"fecha": str(HOY - timedelta(days=i)), "clave": k, "cifra": P._cifra_txt({"_cifra": cifra}), "sello": "dato_del_dia"} for i in range(dias, 0, -1)]


def test_la_misma_historia_no_abre_un_tercer_dia_sin_cifra_nueva():
    h = _hist("a", {"n": 5}, 2)
    c = _cand("a", {"n": 5})
    assert P.seguidos(h, "a", HOY)[0] == 2
    assert P.sello_de(c, h, HOY) == "dato_del_dia" and not P.elegible(c, h, HOY, "dato_del_dia")
    nuevo = _cand("a", {"n": 6})                                    # cifra nueva: puede seguir, con sello «en seguimiento»
    assert P.sello_de(nuevo, h, HOY) == "en_seguimiento" and P.elegible(nuevo, h, HOY, "en_seguimiento")
    exc = _cand("a", {"n": 5}, puntos=70, portada=True)             # excepcional: no se aparta aunque repita
    assert P.sello_de(exc, h, HOY) == "excepcional" and P.elegible(exc, h, HOY, "excepcional")
    assert P.elegible(c, _hist("a", {"n": 5}, 1), HOY, "dato_del_dia")          # un solo día seguido sí puede repetir


def test_si_repite_sube_la_segunda_pieza():
    p = {"historia_del_dia": None, "mas": [_cand("a", {"n": 5}, 60), _cand("b", {"n": 1}, 50)], "datos_del_dia": [], "contexto": []}
    for c in p["mas"]:
        c["rasgos"]["ambito"] = "nacional"
        c["titular"] = f"Titular {c['_k']}"
    carreras = {"dato_hasta": "2026-11-20", "piezas": []}
    cab, mas, _ = P.bloque_dato_del_dia(p, [], carreras, HOY, B.RAIZ, _hist("a", {"n": 5}, 2), False)
    assert cab["clave"] == "b"                                          # «a» ya abrió dos días con la misma cifra: sube «b»
    cab, _, _ = P.bloque_dato_del_dia(p, [], carreras, HOY, B.RAIZ, _hist("a", {"n": 5}, 1), False)
    assert cab["clave"] == "a"


def test_un_empate_no_dice_el_mas():
    ini, hasta = date(2026, 1, 1), date(2026, 3, 31)
    serie = {}
    d = date(1980, 1, 1)
    while d <= date(2026, 12, 31):
        serie[d] = (20.0, 10.0, 0.0)           # misma media de máximas todos los años: la de 2026 empata con todas
        d += timedelta(days=1)
    a = B.analiza_periodo(serie, ini, hasta, "anio", 0)
    assert a and a["puesto_alto"] == 1 and a["empate_alto"]
    frase, _ = B._frase_calor("Ciudad", a, "lo que va de 2026")
    assert "va primera" not in frase and "iguala" in frase
    serie[date(2026, 2, 1)] = (30.0, 10.0, 0.0)  # ahora sí supera a todas: primera sin empate
    a2 = B.analiza_periodo(serie, ini, hasta, "anio", 0)
    assert not a2["empate_alto"] and "va primera" in B._frase_calor("Ciudad", a2, "lo que va de 2026")[0]


def test_rigor_prohibe_historico_y_el_mas_sin_primer_puesto():
    assert not P.rigor_ok({"titular": "El mes más cálido histórico"})
    assert not P.rigor_ok({"titular": "Madrid, el más cálido", "comparacion": {"puesto": 2, "de": 90}})
    assert P.rigor_ok({"titular": "Madrid, el más cálido", "comparacion": {"puesto": 1, "de": 90}})


def test_ningun_titular_de_provincia_rompe_el_rigor():
    for slug, v in _vacia()["provincias"]["por_slug"].items():
        assert "histór" not in v["dato_del_dia"]["titular"].lower(), slug


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
