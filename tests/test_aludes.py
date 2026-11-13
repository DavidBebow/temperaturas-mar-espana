"""Prueba de scripts/nieve_aludes.py con el texto real de boletines de AEMET de tests/aludes_muestras/
(python tests/test_aludes.py). No lee ningún PDF: el texto de las muestras sustituye a la extracción de pypdf."""
import json
import re
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import nieve                      # noqa: E402
import nieve_aludes as A          # noqa: E402

M = Path(__file__).parent / "aludes_muestras" / "muestras.txt"
MUESTRAS = {}
for _t in M.read_text(encoding="utf-8").split("\n@@@ ")[1:]:
    _n, _, _c = _t.partition("\n")
    MUESTRAS[_n.strip()] = _c.rstrip("\n") + "\n"
MALO = re.compile(r"None|NaN|—|Array|nan\b")
HOY_REAL = datetime.fromisoformat("2026-11-13T13:45:00+01:00")
MACS = {m: (nieve.MACIZO_PAG[m]["slug"], nieve.MACIZOS[m][0]) for m in nieve.ORDEN_MACIZOS if m in nieve.MACIZO_PAG}


def txt(nombre: str) -> str:
    return MUESTRAS[nombre]


def parse(nombre: str) -> dict:
    return A.parsear(txt(nombre), A.POR_ID[nombre.split("_")[0]])


def datos_de(muestras: list[str], ahora: datetime) -> dict:
    return A.construir_json([parse(n) for n in muestras], ahora)


def en(dia: str, hora: str = "13:45") -> datetime:
    return datetime.fromisoformat(f"{dia}T{hora}:00+01:00")


class Lectura(unittest.TestCase):
    def test_pirineo_navarro_aragones(self):
        b = parse("pirineo-nav-ara_2026-01-28.txt")
        self.assertEqual((b["emitido"], b["valido_desde"], b["valido_hasta"]), ("2026-01-28",) * 2 + ("2026-01-29",))
        self.assertEqual((b["nivel"], b["nivel_texto"]), (3, "Notable"))
        self.assertEqual([z["nombre"] for z in b["subzonas"]], ["Navarra", "Jacetania", "Gállego", "Sobrarbe", "Ribagorza"])
        self.assertTrue(all(z["nivel"] == 3 for z in b["subzonas"]))
        self.assertEqual(b["situacion"], "Situación de nieve reciente, y de nieve venteada en cotas altas.")
        self.assertEqual(b["problemas"], ["Nieve reciente", "Placas de viento"])
        f = parse("pirineo-nav-ara_2026-02-03.txt")
        self.assertEqual((f["nivel"], f["valido_hasta"]), (4, "2026-02-04"))
        self.assertEqual(f["situacion"], "Problemas de placas de viento y capas débiles persistentes en cotas altas.")

    def test_correccion(self):
        b = parse("pirineo-nav-ara_2026-03-09.txt")
        self.assertEqual((b["emitido"], b["valido_hasta"], b["nivel"], b["correccion"]), ("2026-03-09", "2026-03-10", 3, True))

    def test_pirineo_catalan_con_zonas_de_nombre_compuesto(self):
        b = parse("pirineo-cat_2023-12-18.txt")
        z = {x["nombre"]: x["nivel"] for x in b["subzonas"]}
        self.assertEqual(z, {"Arán-Franja norte Pallaresa": 2, "Ribagorzana-Vall Fosca": 2, "Pallaresa": 2,
                             "Perafita-Puigpedrós": 1, "Ter-Freser": 1, "Vertiente norte Cadí-Moixeró": 1, "Prepirineo": 1})
        self.assertEqual((b["nivel"], b["valido_hasta"]), (2, "2023-12-19"))   # el máximo de las zonas
        self.assertEqual(b["situacion"], "Situación de nieve húmeda y de placas de viento.")

    def test_semanales(self):
        g = parse("guadarrama_2022-03-17.txt")
        self.assertEqual((g["nivel"], g["emitido"], g["valido_hasta"]), (2, "2022-03-17", "2022-03-18"))
        self.assertIn("Débil", g["cambio_nivel"])            # el paréntesis se anota, no se pinta
        p = parse("picos-europa_2021-02-26.txt")
        self.assertEqual((p["nivel"], p["valido_hasta"], p["subzonas"]), (3, "2021-02-26", []))
        c = parse("cordel-penalabra_2021-02-04.txt")
        self.assertEqual((c["nivel"], c["cambio_nivel"]), (1, None))
        c2 = parse("cordel-penalabra_2021-12-02.txt")
        self.assertEqual((c2["nivel"], c2["valido_hasta"]), (3, "2021-12-03"))

    def test_fin_de_campana_no_trae_nivel(self):
        fin = [n for n in sorted(MUESTRAS) if n.endswith("_fin.txt")]
        self.assertEqual(len(fin), 5)
        for n in fin:
            b = A.parsear(MUESTRAS[n], A.POR_ID[n.split("_")[0]])
            self.assertTrue(b["fin_campana"], n)
            self.assertIsNone(b["nivel"])
            self.assertFalse(A.vigente(b, date(2026, 5, 5)))
        self.assertEqual(parse("pirineo-cat_2026-05-04_fin.txt")["emitido"], "2026-05-04")

    def test_descarte_numero_y_palabra(self):
        with self.assertRaises(A.Descarte):
            A.nivel_de("3", "Limitado")
        with self.assertRaises(A.Descarte):
            A.nivel_de("7", "Notable")
        with self.assertRaises(A.Descarte):
            A.nivel_de(None, "Altísimo")
        self.assertEqual(A.nivel_de("3", "Notable"), 3)
        self.assertEqual(A.nivel_de(None, "Muy fuerte"), 5)
        malo = txt("picos-europa_2021-02-26.txt").replace("Notable\n(Limitado)", "2 Notable")
        with self.assertRaises(A.Descarte):
            A.parsear(malo, A.POR_ID["picos-europa"])

    def test_descarte_de_lo_que_no_casa(self):
        t = txt("pirineo-nav-ara_2026-01-28.txt")
        casos = {"día de la semana": t.replace("miércoles, 28", "jueves, 28"),
                 "sin validez": t.replace("Pronóstico hasta las 24 horas del jueves, día 29 de enero\n", ""),
                 "nivel desconocido": t.replace("Notable", "Alto", 1),
                 "tabla a medias": t.replace("Estado del manto y observaciones recientes", "Otra cosa"),
                 "otro documento": "Agencia Estatal de Meteorología\nInformación nivológica\nHola\n",
                 "vacío": ""}
        for nombre, mal in casos.items():
            with self.assertRaises(A.Descarte, msg=nombre):
                A.parsear(mal, A.POR_ID["pirineo-nav-ara"])
        d = A.interpretar([casos["nivel desconocido"], None], A.POR_ID["pirineo-nav-ara"])
        self.assertTrue(d["motivo_descartado"])
        self.assertFalse(A.vigente(d, date(2026, 1, 28)))

    def test_pypdf_sin_salto_de_linea_en_la_fila(self):
        t = txt("pirineo-nav-ara_2026-01-28.txt").replace("Notable\nPlacas de viento\nNieve reciente\n2026-01-28",
                                                         "Notable Placas de viento Nieve reciente 2026-01-28")
        b = A.parsear(t, A.POR_ID["pirineo-nav-ara"])
        self.assertEqual((b["nivel"], len(b["subzonas"])), (3, 5))


class Vigencia(unittest.TestCase):
    def test_con_la_fecha_de_hoy_todo_esta_caducado(self):
        muestras = sorted(MUESTRAS)
        d = datos_de(muestras, HOY_REAL)
        self.assertFalse(any(b["vigente"] for b in d["boletines"]))
        self.assertEqual((d["macizos"], d["provincias"]), ({}, {}))
        self.assertFalse(d["temporada"])
        for amb, cl, lu in (("hub", None, None), ("macizo", "pirineo", "el Pirineo"), ("provincia", "lleida", "Lleida"),
                            ("macizo", "central", "la sierra de Madrid y el Sistema Central")):
            h = A.bloque(d, amb, cl, lu, MACS, HOY_REAL)
            self.assertNotIn("cgnv-al-chip", h)
            self.assertNotIn("Notable", h)
            self.assertNotRegex(h, MALO)
        self.assertEqual(A.bloque(d, "hub", None, None, MACS, HOY_REAL), "")

    def test_fuera_de_temporada_una_linea_solo_en_las_paginas_con_boletin(self):
        d = datos_de(["pirineo-nav-ara_2026-01-28.txt"], HOY_REAL)
        h = A.bloque(d, "macizo", "pirineo", "el Pirineo", MACS, HOY_REAL)
        self.assertIn("AEMET publica el boletín de peligro de aludes de diciembre a mayo.", h)
        self.assertIn(A.URL_INDICE, h)
        self.assertEqual(A.bloque(d, "macizo", "galaico", "Galicia", MACS, HOY_REAL), "")
        self.assertEqual(A.bloque(d, "provincia", "murcia", "Murcia", MACS, HOY_REAL), "")
        self.assertEqual(A.bloque(d, "provincia", "barcelona", "Barcelona", MACS, HOY_REAL), "")

    def test_en_temporada_sin_boletin_en_vigor(self):
        ahora = en("2026-01-15")
        d = datos_de(["pirineo-nav-ara_2026-05-04_fin.txt", "pirineo-cat_2026-05-04_fin.txt"], ahora)
        self.assertTrue(d["temporada"])
        for amb, cl in (("macizo", "pirineo"), ("provincia", "huesca")):
            h = A.bloque(d, amb, cl, "x", MACS, ahora)
            self.assertIn("AEMET no tiene hoy un boletín de aludes en vigor para esta zona.", h)
            self.assertNotIn("cgnv-al-chip", h)
        self.assertEqual(A.bloque(d, "hub", None, None, MACS, ahora), "")

    def test_fecha_simulada_dentro_de_la_validez_pinta_el_nivel_correcto(self):
        ahora = en("2026-01-29", "09:00")             # el boletín del 28 vale hasta las 24 h del 29
        d = datos_de(["pirineo-nav-ara_2026-01-28.txt"], ahora)
        self.assertTrue(d["boletines"][0]["vigente"])
        h = A.bloque(d, "macizo", "pirineo", "el Pirineo", MACS, ahora)
        for s in ("3 · Notable", "Pirineo navarro y aragonés", "Navarra", "Ribagorza",
                  "válido hasta las 24 horas del 29 de enero de 2026", "emitido el 28 de enero de 2026",
                  "«Situación de nieve reciente, y de nieve venteada en cotas altas.» (AEMET)",
                  "Boletín completo de AEMET (PDF)", A.url_pdf(A.POR_ID["pirineo-nav-ara"]), A.ESCALA_PIE, "ICGC", "Conselh Generau d"):
            self.assertIn(s, h)
        self.assertNotRegex(h, MALO)
        self.assertNotRegex(h, r"<(svg|img|figure|dl|dt|dd|i)\b")
        # al día siguiente ya está caducado: no se pinta ni como referencia
        d2 = A.construir_json([parse("pirineo-nav-ara_2026-01-28.txt")], en("2026-01-30"))
        self.assertNotIn("cgnv-al-chip", A.bloque(d2, "macizo", "pirineo", "el Pirineo", MACS, en("2026-01-30")))

    def test_provincias_del_pirineo(self):
        ahora = en("2026-01-29")
        d = datos_de(["pirineo-nav-ara_2026-01-28.txt"], ahora)
        self.assertIn("3 · Notable", A.bloque(d, "provincia", "navarra", "Navarra", MACS, ahora))
        self.assertIn("3 · Notable", A.bloque(d, "provincia", "huesca", "Huesca", MACS, ahora))
        lleida = A.bloque(d, "provincia", "lleida", "Lleida", MACS, ahora)         # el boletín catalán no está vigente
        self.assertNotIn("cgnv-al-chip", lleida)
        self.assertIn("AEMET no tiene hoy un boletín de aludes en vigor", lleida)
        self.assertIn("ICGC", lleida)

    def test_semanal_valido_para_un_dia_y_tope_de_8_dias(self):
        g = parse("guadarrama_2022-03-17.txt")
        self.assertTrue(A.vigente(g, date(2022, 3, 17)))
        self.assertTrue(A.vigente(g, date(2022, 3, 18)))
        self.assertFalse(A.vigente(g, date(2022, 3, 19)))
        largo = {**g, "valido_hasta": "2022-04-30"}
        self.assertTrue(A.vigente(largo, date(2022, 3, 25)))
        self.assertFalse(A.vigente(largo, date(2022, 3, 26)))      # 9 días desde la emisión
        ahora = en("2022-03-18")
        d = A.construir_json([g], ahora)
        h = A.bloque(d, "macizo", "central", "la sierra de Madrid", MACS, ahora)
        self.assertIn("2 · Limitado", h)
        self.assertIn("válido para el 18 de marzo de 2022", h)
        self.assertNotIn("Débil", h)
        self.assertIn("cgnv-al-chip", A.bloque(d, "provincia", "segovia", "Segovia", MACS, ahora))
        self.assertNotIn("cgnv-al-chip", A.bloque(d, "provincia", "asturias", "Asturias", MACS, ahora))

    def test_emision_futura_o_sin_nivel_no_es_vigente(self):
        b = parse("pirineo-nav-ara_2026-01-28.txt")
        self.assertFalse(A.vigente(b, date(2026, 1, 27)))
        self.assertFalse(A.vigente({**b, "nivel": None}, date(2026, 1, 28)))
        self.assertFalse(A.vigente({**b, "nivel": 9}, date(2026, 1, 28)))
        self.assertFalse(A.vigente({**b, "motivo_descartado": "x"}, date(2026, 1, 28)))
        self.assertFalse(A.vigente({**b, "valido_hasta": "basura"}, date(2026, 1, 28)))


class Reparto(unittest.TestCase):
    def setUp(self):
        # todos los boletines de muestra, con la vigencia llevada a un mismo día, para probar solo el reparto
        self.hoy = date(2026, 1, 28)
        bs = []
        for n in ("pirineo-nav-ara_2026-01-28.txt", "pirineo-cat_2023-12-18.txt", "guadarrama_2022-03-17.txt",
                  "picos-europa_2021-02-26.txt", "cordel-penalabra_2021-02-04.txt"):
            b = parse(n)
            b.update(emitido="2026-01-28", valido_desde="2026-01-28", valido_hasta="2026-01-29")
            bs.append(b)
        self.bs = bs
        self.r = A.reparto(bs, self.hoy)

    def test_macizos(self):
        m = self.r["macizos"]
        self.assertEqual({k: v["nivel"] for k, v in m.items()}, {"pirineo": 3, "central": 2, "cantabrica": 3})
        self.assertEqual(m["pirineo"]["boletin"], "pirineo-nav-ara")
        self.assertEqual(m["cantabrica"]["boletin"], "picos-europa")
        self.assertNotIn("galaico", m)

    def test_provincias(self):
        p = self.r["provincias"]
        self.assertEqual({k: v["nivel"] for k, v in p.items()},
                         {"navarra": 3, "huesca": 3, "lleida": 2, "girona": 2, "madrid": 2, "segovia": 2,
                          "asturias": 3, "cantabria": 3, "leon": 3, "palencia": 1})
        self.assertEqual(p["cantabria"]["boletin"], "picos-europa")          # el más alto de los dos boletines
        self.assertEqual(p["palencia"]["boletin"], "cordel-penalabra")
        self.assertNotIn("barcelona", p)
        self.assertNotIn("murcia", p)

    def test_barcelona_solo_si_el_boletin_la_nombra(self):
        t = txt("pirineo-cat_2023-12-18.txt").replace("Prepirineo\nDébil", "Prepirineo de Barcelona\nDébil")
        self.assertIn("barcelona", A.parsear(t, A.POR_ID["pirineo-cat"])["provincias"])
        self.assertNotIn("barcelona", parse("pirineo-cat_2023-12-18.txt")["provincias"])

    def test_ficha_solo_en_macizos_con_boletin_vigente(self):
        ahora = en("2026-01-28")
        d = A.construir_json(self.bs, ahora)
        self.assertEqual(A.ficha_macizo(d, "pirineo", ahora),
                         {"nivel": 3, "nivel_texto": "Notable", "zona": "Pirineo navarro y aragonés",
                          "valido_hasta": "2026-01-29"})
        self.assertIsNone(A.ficha_macizo(d, "nevada", ahora))
        self.assertIsNone(A.ficha_macizo(d, "pirineo", en("2026-02-05")))          # caducado
        self.assertIsNone(A.ficha_macizo(None, "pirineo", ahora))

    def test_hub_lista_los_vigentes_con_enlace_al_macizo(self):
        ahora = en("2026-01-28")
        d = A.construir_json(self.bs, ahora)
        h = A.bloque(d, "hub", None, None, MACS, ahora)
        self.assertIn('<a href="/nieve/pirineo/">Pirineo navarro y aragonés</a>', h)
        self.assertIn('<a href="/nieve/sistema-central/">Sierra de Guadarrama</a>', h)
        self.assertIn("3 · Notable", h)
        self.assertNotRegex(h, MALO)


class Pasada(unittest.TestCase):
    def test_pasada_completa_con_descargas_simuladas(self):
        ahora = en("2026-01-28")
        cuerpo = {b["id"]: None for b in A.BOLETINES}
        cuerpo["pirineo-nav-ara"] = txt("pirineo-nav-ara_2026-01-28.txt")
        cuerpo["guadarrama"] = txt("guadarrama_2023-03-30_fin.txt")
        cuerpo["pirineo-cat"] = txt("pirineo-nav-ara_2026-01-28.txt").replace("Notable", "Alto", 1)   # no casa: se descarta

        def bajar(b):
            return (b["id"], cuerpo[b["id"]].encode() if cuerpo[b["id"]] else None, None if cuerpo[b["id"]] else "sin red")

        def od(area, clave):
            return area, {"meta": {"estado": 200}, "datos": f"respuesta del área {area}"}, None

        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            args = (t / "aludes.json", t / "hist.csv", t / "crudo", ahora)
            kw = dict(bajar=bajar, bajar_opendata=od, clave="x", leer=lambda b: (b.decode(), None))
            d, msg = A.actualizar(*args, **kw)
            por_id = {b["id"]: b for b in d["boletines"]}
            self.assertTrue(por_id["pirineo-nav-ara"]["vigente"])
            self.assertEqual(por_id["pirineo-nav-ara"]["nivel"], 3)
            self.assertIn("sin nivel reconocible", por_id["pirineo-cat"]["motivo_descartado"])
            self.assertIsNone(por_id["pirineo-cat"]["nivel"])
            self.assertTrue(por_id["guadarrama"]["fin_campana"])
            self.assertIsNone(por_id["guadarrama"]["nivel"])
            self.assertIn("descarga fallida", por_id["picos-europa"]["motivo_descartado"])
            self.assertEqual(d["macizos"], {"pirineo": {"nivel": 3, "nivel_texto": "Notable", "boletin": "pirineo-nav-ara",
                                                          "zona": "Pirineo navarro y aragonés", "valido_hasta": "2026-01-29"}})
            self.assertTrue(d["temporada"])
            self.assertEqual(json.loads((t / "aludes.json").read_text(encoding="utf-8"))["boletines"][0]["id"], "pirineo-nav-ara")
            # histórico: una línea por emisión nueva y no se repite
            self.assertEqual((t / "hist.csv").read_text().splitlines(), ["emitido,boletin,nivel_maximo", "2026-01-28,pirineo-nav-ara,3"])
            A.actualizar(*args, **kw)
            self.assertEqual(len((t / "hist.csv").read_text().splitlines()), 2)
            # texto crudo: se guarda una vez y no se repite si no cambia; OpenData de las áreas 0 y 1
            nombres = sorted(p.name for p in (t / "crudo").iterdir())
            self.assertEqual(len([n for n in nombres if n.startswith("pirineo-nav-ara_")]), 1)
            self.assertEqual(len([n for n in nombres if n.startswith("opendata_area0_") and n.endswith(".txt")]), 1)
            self.assertEqual(len([n for n in nombres if n.startswith("opendata_area1_") and n.endswith(".txt")]), 1)
            self.assertTrue(any(n.startswith("pirineo-cat_") for n in nombres))      # también el descartado
            cuerpo["pirineo-nav-ara"] += "\nlínea nueva"
            A.actualizar(*args, **{**kw, "bajar": bajar})
            self.assertEqual(len([p for p in (t / "crudo").iterdir() if p.name.startswith("pirineo-nav-ara_")]), 1)  # misma hora: mismo nombre
            # sin clave de OpenData no hay respuesta guardada y no pasa nada
            with tempfile.TemporaryDirectory() as t2:
                A.actualizar(Path(t2) / "a.json", Path(t2) / "h.csv", Path(t2) / "c", ahora, **{**kw, "clave": ""})
                self.assertFalse(any(p.name.startswith("opendata") for p in (Path(t2) / "c").iterdir()))

    def test_si_falla_la_descarga_se_conserva_el_boletin_anterior_pero_caduca(self):
        ahora = en("2026-01-28")
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            ok = lambda b: (b["id"], txt("pirineo-nav-ara_2026-01-28.txt").encode() if b["id"] == "pirineo-nav-ara" else None, None)
            mal = lambda b: (b["id"], None, "sin red")
            kw = dict(bajar_opendata=None, clave="", leer=lambda b: (b.decode(), None))
            A.actualizar(t / "a.json", t / "h.csv", t / "c", ahora, bajar=ok, **kw)
            d, msg = A.actualizar(t / "a.json", t / "h.csv", t / "c", en("2026-01-29", "07:00"), bajar=mal, **kw)
            self.assertIn("se conserva el anterior", msg)
            self.assertTrue(d["boletines"][0]["vigente"])
            d, _ = A.actualizar(t / "a.json", t / "h.csv", t / "c", en("2026-01-30", "07:00"), bajar=mal, **kw)
            self.assertFalse(d["boletines"][0]["vigente"])
            self.assertEqual(d["macizos"], {})

    def test_sin_pypdf_o_con_pdf_roto_no_se_publica_nada(self):
        ahora = en("2026-01-28")
        def roto(_):
            raise ValueError("no es un PDF")
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            d, msg = A.actualizar(t / "a.json", t / "h.csv", t / "c", ahora, bajar=lambda b: (b["id"], b"%PDF", None),
                                  bajar_opendata=None, clave="", leer=roto)
            self.assertFalse(any(b["vigente"] for b in d["boletines"]))
            self.assertIn("no se pudo leer el PDF", d["boletines"][0]["motivo_descartado"])


class Hub(unittest.TestCase):
    def test_pregunta_frecuente(self):
        n = len(nieve.FAQ_ALUDES.split())
        self.assertTrue(40 <= n <= 60, n)
        for s in ("1 Débil", "2 Limitado", "3 Notable", "4 Fuerte", "5 Muy fuerte"):
            self.assertIn(s, nieve.FAQ_ALUDES)

    def test_nieve_py_pinta_y_deja_la_ficha(self):
        nieve.ALUDES = datos_de(["pirineo-nav-ara_2026-01-28.txt"], en("2026-01-29"))
        ahora = nieve.AHORA
        try:
            nieve.AHORA = en("2026-01-29").astimezone()
            self.assertIn("3 · Notable", nieve.bloque_aludes("macizo", "pirineo", "el Pirineo"))
            self.assertEqual(nieve.bloque_aludes("macizo", "galaico", "Galicia"), "")
        finally:
            nieve.AHORA = ahora
        self.assertEqual(nieve.bloque_aludes("hub"), "")          # hoy (nov 2026) está caducado
        nieve.ALUDES = None
        self.assertEqual(nieve.bloque_aludes("hub"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
