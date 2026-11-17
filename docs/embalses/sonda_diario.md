# Sonda del dato diario de embalses — 2026-11-17 20:02 UTC

No publica datos: solo anota qué responde cada fuente.

## Servicios y API

| Ámbito | Qué | Resultado |
|---|---|---|
| MITECO nacional | WMS capabilities | SI — XML; capas: WMS, embalses_et, embalses_et_estilo, EF.EnvironmentalMonitoringFacilities.Default |
| MITECO nacional | WFS capabilities | SI — XML; capas: agua:embalses_et, agua:rios_pfaf_cx1 |
| MITECO nacional | WMS antiguo (wms.mapama) | SI — XML; capas:  |
| MITECO nacional | Visor redes de seguimiento | NO — SSLError: HTTPSConnectionPool(host='www.mapa.gob.es', port=443): Max retries exceeded with url: /es/cartografia-y-sig/visores/visores-miteco (Caused by SSLError(SSLCertVe |
| Duero | CKAN package_show estado_embalse | SI — CKAN, 1 recursos |
| Duero | Recurso CKAN: Estado Embalses (JSON) | SI — JSON, 36 registros, campos: codigo, punto_control, cauce, sistema, municipio, provincia, utm_x, utm_y, utm_huso, altitud_masl, capacidad_hm3, superficie_ha, actualizacion, volumen_actual_hm3, volumen_actual_percent, superficie_actual_ha, q_vertido_actual_m3s |
| Duero | Ficha del dataset estado_embalse | SI — HTML «Portal de datos abiertos de la Confederación Hidrográfica del Duero», 0 tablas, 4 menciones hm3 |
| Guadalquivir | WFS explotacion_saih (10 features) | SI — JSON, 10 registros, campos: id, cod_punto, nom_estsup, utmx_estsu, utmy_estsu, huso_estsu, latitud, longitud, obs_estsup, pluviomet, termomet, tanq_eva, saica, nom_muni, nom_prov |
| Guadalquivir | WFS DescribeFeatureType | SI — XML; capas:  |
| Cataluna (ACA) | Socrata gn9e-3qhr, 20 filas mas recientes | SI — JSON, 20 registros, campos: dia, estaci, nivell_absolut, percentatge_volum_embassat, volum_embassat |
| Cataluna (ACA) | Socrata gn9e-3qhr, 3 filas mas antiguas | SI — JSON, 3 registros, campos: dia, estaci, nivell_absolut, percentatge_volum_embassat, volum_embassat |
| Andalucia (REDIAM) | Descarga 'Embalses al dia' | NO — SSLError: HTTPSConnectionPool(host='descargasrediam.cica.es', port=443): Max retries exceeded with url: /repo/s/RUR?path=%2F04_RECURSOS_NATURALES%2F04_AGUAS%2F01_SUPERFIC |
| Andalucia (REDIAM) | Ficha de metadatos | SI — HTML «Embalses al día. Datos diarios de reserva en embalses», 6 tablas, 0 menciones hm3 |
| MITECO nacional | WFS GetFeature agua:embalses_et (400) | SI — JSON, 400 registros, campos: idpunto, utm_x_30, utm_y_30, descripcion, idsaih, idtipo, baja, prot_civil, utm_x_et, utm_y_et, cod_demar, tipo |
| MITECO nacional | WFS DescribeFeatureType agua:embalses_et | SI — XML; capas:  |
| MITECO nacional | WMS GetFeatureInfo agua:embalses_et (toda la peninsula, 50) | SI — JSON, 50 registros, campos: Nombre, Cuenca SAIH, Tipo |

## Webs SAIH

| Cuenca | Página | HTTP | Tablas | hm³ | Fechas vistas |
|---|---|---|---|---|---|
| Ebro | https://www.saihebro.com/ | ConnectTimeout: HTTPSConnectionPool(host='www.saih |  |  |  |
| Ebro | https://www.saihebro.com/saihebro/index.php?url=/informes/partes | ConnectTimeout: HTTPSConnectionPool(host='www.saih |  |  |  |
| Tajo | https://saihtajo.chtajo.es/ | 200 | 0 | 0 |  |
| Guadiana | https://www.saihguadiana.com/ | 200 | 0 | 0 |  |
| Guadalquivir | https://www.chguadalquivir.es/saih/ | 200 | 65 | 4 | 17/11/2026 21:04 |
| Guadalquivir | https://www.chguadalquivir.es/saih/EmbalMapa.aspx | 200 | 54 | 2 | 17/11/2026 21:04 |
| Guadalquivir | https://www.chguadalquivir.es/saih/DatEmbZona.aspx | 200 | 54 | 0 | 17/11/2026 21:04 |
| Guadalquivir | https://www.chguadalquivir.es/saih/ListaRT.aspx | 200 | 54 | 0 | 17/11/2026 21:04 |
| Guadalquivir | https://www.chguadalquivir.es/saih/ResguardoEmbalses.aspx | 200 | 54 | 0 | 17/11/2026 21:04 |
| Duero | https://www.saihduero.es/ | SSLError: HTTPSConnectionPool(host='www.saihduero. |  |  |  |
| Duero | https://www.saihduero.es/situacion-embalses | SSLError: HTTPSConnectionPool(host='www.saihduero. |  |  |  |
| Jucar | https://saih.chj.es/ | 200 | 0 | 0 |  |
| Segura | https://saihweb.chsegura.es/ | 200 | 1 | 0 |  |
| Segura | https://www.chsegura.es/ | 200 | 2 | 3 |  |
| Segura | https://www.chsegura.es/es/cuenca/redes-de-control/estadisticas-hidrologicas/parte-diario/ | 200 | 1 | 0 |  |
| Segura | https://www.chsegura.es/es/cuenca/redes-de-control/estadisticas-hidrologicas/estado-de-emb | 200 | 5 | 8 | 15/11/2026, 01/12/2025, 01/01/2026 |
| Mino-Sil | https://saih.chminosil.es/ | SSLError: HTTPSConnectionPool(host='saih.chminosil |  |  |  |
| Cantabrico | https://www.chcantabrico.es/ | 200 | 0 | 0 |  |
| Cantabrico | https://www.chcantabrico.es/reservas-hidrol%C3%B3gicas | 200 | 0 | 0 |  |
| Cantabrico | https://www.chcantabrico.es/servicios/aprovechamientos-hidroelectricos | 200 | 0 | 0 | 31-12-2025 |
| Cantabrico | https://www.chcantabrico.es/gestion-cuencas/obras-hidraulicas/obras-hidraulicas-y-de-mejor | 200 | 0 | 0 |  |
| Andalucia (Hidrosur) | http://www.redhidrosurmedioambiente.es/saih/ | 200 | 0 | 0 | 17-11-2026 20:00 |
| Andalucia (Hidrosur) | https://www.redhidrosurmedioambiente.es/saih/informe/embalses | 200 | 1 | 3 | 29/05/2025 8:00, 17/11/2026, 17/11/2026 08:00 |
| Andalucia (Hidrosur) | https://www.redhidrosurmedioambiente.es/saih/resumen/embalses | 200 | 1 | 37 | 17-11-2026 20:00, 17/11/2026, 10/11/2026 |
| Galicia Costa | https://augasdegalicia.xunta.gal/ | 200 | 1 | 0 | 17/11/2026, 16/11/2026, 06/11/2026 |
| Galicia Costa | https://augasdegalicia.xunta.gal/seccion-tema/c/Control_caudais_reservas?content=/Portal-W | robots.txt no lo permite: no se pide |  |  |  |
| Galicia Costa | https://augasdegalicia.xunta.gal/seccion-tema/c/Control_caudais_reservas?content=/Portal-W | robots.txt no lo permite: no se pide |  |  |  |
| Pais Vasco (URA) | https://www.uragentzia.euskadi.eus/ | 200 | 0 | 0 |  |
