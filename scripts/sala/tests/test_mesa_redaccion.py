#!/usr/bin/env python3
"""Pruebas de la mesa de redacción (scripts/mesa_redaccion.py): agrupación, escala única, marcos grandes (H1) y día sin noticia.
Uso: python -m pytest -q scripts/sala/tests/test_mesa_redaccion.py"""
import sys
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
