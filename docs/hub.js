/* Hub de provincias · calentamientoglobal.es
   Subir a: docs/hub.js del repo temperaturas-mar-espana
   Servido en: https://davidbebow.github.io/temperaturas-mar-espana/hub.js
   Requiere en la pagina un <div id="cch-app"></div> y un <p id="cch-stamp"></p> */
(function(){
  "use strict";
  var BASE = "https://davidbebow.github.io/temperaturas-mar-espana/provincias/";

  /* --- Slugs del JSON que NO coinciden con el slug de WordPress ----------- */
  var SLUG_WP = {
    a_coruna:"a-coruna", ciudad_real:"ciudad-real", la_rioja:"la-rioja",
    las_palmas:"las-palmas", sc_tenerife:"santa-cruz-de-tenerife"
  };
  function urlProv(s){
    return "https://calentamientoglobal.es/cambio-climatico-en-" +
           (SLUG_WP[s] || s.replace(/_/g,"-")) + "/";
  }

  /* --- Utilidades -------------------------------------------------------- */
  function num(n,d){ if(n===null||n===undefined||isNaN(n)) return null;
    return Number(n).toFixed(d===undefined?1:d).replace(".",","); }
  function sig(n,d){ var v=num(n,d); if(v===null) return null; return (n>0?"+":"")+v; }
  /* Concordancia de numero: evita "1 dias consecutivos" en un titular. */
  function pl(n,s,p){ return n+" "+(Math.abs(n)===1? s : p); }
  /* Evita "Soria (Soria)" y "Melilla (costera) (Melilla)" cuando el punto de
     medicion y la provincia se llaman igual o empiezan igual. */
  function loc(d,nom){
    if(!nom) return d.provincia;
    if(nom===d.provincia || nom.indexOf(d.provincia)===0) return nom;
    return nom+" ("+d.provincia+")"; }
  function esc(s){ return String(s==null?"":s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
  function diaDelAnio(){ var h=new Date(), i=new Date(h.getFullYear(),0,0);
    return Math.floor((h-i)/86400000); }

  var U = {
    mar:"https://calentamientoglobal.es/temperaturas-del-mar-espana-actualizado/",
    nivel:"https://calentamientoglobal.es/nivel-del-mar-espana-ahora/",
    noches:"https://calentamientoglobal.es/noches-tropicales-espana/",
    canicula:"https://calentamientoglobal.es/canicula-en-espana-ahora/",
    firma:"https://calentamientoglobal.es/firma-climatica/",
    lluvias:"https://calentamientoglobal.es/lluvias-en-espana/",
    fuego:"https://calentamientoglobal.es/calentamientoglobal-es-incendios-forestales-espana-tiempo-real/",
    avisos:"https://calentamientoglobal.es/avisos-meteorologicos-activos/",
    aire:"https://calentamientoglobal.es/calidad-del-aire/",
    obs:"https://calentamientoglobal.es/observatorio-climatico/",
    m2050:"https://calentamientoglobal.es/tu-municipio-en-2050/",
    muertes:"https://calentamientoglobal.es/muertes-por-calor-espana/",
    embalses:"https://calentamientoglobal.es/embalses-espana/"
  };

  /* Extractores sobre indicadores */
  function maxBoya(d){ var b=(d.i.boyas||[]).filter(function(x){return x.temp!=null;});
    if(!b.length) return null; return b.sort(function(a,c){return c.temp-a.temp;})[0]; }
  /* Boya que MAS supera su propio record (no necesariamente la mas caliente:
     una provincia puede tener dos boyas y batir record solo la segunda). */
  function boyaRecord(d){
    var b=(d.i.boyas||[]).filter(function(x){
      return x.temp!=null && x.record_max && x.record_max.valor!=null && Math.sign(x.temp-x.record_max.valor)!==-1; });
    if(!b.length) return null;
    return b.sort(function(a,c){ return (c.temp-c.record_max.valor)-(a.temp-a.record_max.valor); })[0]; }
  /* Boya que mas rapido se calienta, que puede no ser la mas caliente. */
  function boyaTend(d){
    var b=(d.i.boyas||[]).filter(function(x){ return x.tendencia_decada!=null; });
    if(!b.length) return null;
    return b.sort(function(a,c){ return c.tendencia_decada-a.tendencia_decada; })[0]; }
  function maxMar(d){ var m=(d.i.mar||[]).filter(function(x){return x.anomalia!=null;});
    if(!m.length) return null; return m.sort(function(a,c){return c.anomalia-a.anomalia;})[0]; }
  function maxNivel(d){ var n=(d.i.nivel_mar||[]).filter(function(x){return x.desviacion_cm!=null;});
    if(!n.length) return null; return n.sort(function(a,c){return c.desviacion_cm-a.desviacion_cm;})[0]; }
  function maxNoc(d){ var n=(d.i.noches_tropicales||[]).filter(function(x){return x.nt_anyo!=null;});
    if(!n.length) return null; return n.sort(function(a,c){return c.nt_anyo-a.nt_anyo;})[0]; }
  function maxAire(d){ var a=(d.i.calidad_aire||[]).filter(function(x){return x.aqi_europeo!=null;});
    if(!a.length) return null; return a.sort(function(x,y){return y.aqi_europeo-x.aqi_europeo;})[0]; }

  /* ======================================================================
     DEFINICION DE RANKINGS
     val   -> numero comparable (o null si esa provincia no tiene el dato)
     cifra -> lo que se pinta grande
     desc  -> explicacion corta
     frase -> titular citable, listo para copiar
     ambito-> a cuantas provincias aplica realmente el ranking
     grupo -> "ccaa" agrupa por comunidad para no repetir (incendios)
     futuro-> true si el campo aun no existe en los JSON (se activa solo)
  ====================================================================== */
  var RANKINGS = [
  { id:"mar_temp", t:"El mar más caliente ahora", calor:true, url:U.mar,
    val:function(d){ var b=maxBoya(d); return b?b.temp:null; },
    cifra:function(d,v){ return num(v,2)+" °C"; },
    desc:function(d){ var b=maxBoya(d); return "Boya de "+b.nombre+", medición de hoy."; },
    frase:function(d,v){ var b=maxBoya(d);
      return "El agua más caliente de España se está midiendo ahora en la boya de "+loc(d,b.nombre)+": "+num(v,2)+" °C."; },
    amb:"Entre las provincias con boya de Puertos del Estado." },

  { id:"mar_record", t:"Boyas batiendo su récord histórico", calor:true, url:U.mar,
    val:function(d){ var b=boyaRecord(d); if(!b) return null;
      return +(b.temp-b.record_max.valor).toFixed(2); },
    cifra:function(d,v){ var b=boyaRecord(d); return num(b.temp,2)+" °C"; },
    desc:function(d){ var b=boyaRecord(d);
      return "Boya de "+b.nombre+". Supera el máximo de toda su serie ("+num(b.record_max.valor,2)+" °C, "+b.record_max.fecha.slice(0,4)+"), que arranca en "+b.inicio_serie.slice(0,4)+"."; },
    frase:function(d,v){ var b=boyaRecord(d);
      return "La boya de "+loc(d,b.nombre)+" está batiendo hoy su récord histórico: "+num(b.temp,2)+" °C, por encima del máximo de toda su serie ("+num(b.record_max.valor,2)+" °C en "+b.record_max.fecha.slice(0,4)+"), que se mide desde "+b.inicio_serie.slice(0,4)+"."; },
    amb:"Solo aparecen las boyas que hoy superan su propio récord. Cada serie arranca en un año distinto." },

  { id:"mar_anom", t:"Mayor anomalía del mar", calor:true, url:U.mar,
    val:function(d){ var m=maxMar(d); return m?m.anomalia:null; },
    cifra:function(d,v){ return sig(v,1)+" °C"; },
    desc:function(d){ var m=maxMar(d); return m.nombre+", a "+num(m.temperatura_actual,1)+" °C sobre su media histórica."; },
    frase:function(d,v){ var m=maxMar(d);
      return "El mar en "+loc(d,m.nombre)+" está a "+num(m.temperatura_actual,1)+" °C, "+sig(v,1)+" °C por encima de su media histórica."; },
    amb:"Entre las provincias costeras con punto de medición." },

  { id:"mar_tend", t:"El mar que más rápido se calienta", calor:true, url:U.mar,
    val:function(d){ var b=boyaTend(d); return b? b.tendencia_decada : null; },
    cifra:function(d,v){ return sig(v,2)+" °C"; },
    desc:function(d){ var b=boyaTend(d);
      return "Por década en la boya de "+b.nombre+" (serie desde "+b.inicio_serie.slice(0,4)+")."; },
    frase:function(d,v){ var b=boyaTend(d);
      return "El agua de la boya de "+loc(d,b.nombre)+" se calienta a "+sig(v,2)+" °C por década, la tendencia más rápida de España, sobre una serie iniciada en "+b.inicio_serie.slice(0,4)+"."; },
    amb:"Entre las boyas con serie suficiente para calcular tendencia." },

  { id:"nivel", t:"El nivel del mar más alto", url:U.nivel,
    val:function(d){ var n=maxNivel(d); return n?n.desviacion_cm:null; },
    cifra:function(d,v){ return sig(v,1)+" cm"; },
    desc:function(d){ var n=maxNivel(d);
      return n.nombre+", sobre la media 1993-2012 · "+n.dias_consecutivos+" días seguidos por encima."; },
    frase:function(d,v){ var n=maxNivel(d);
      return "El nivel del mar en "+loc(d,n.nombre)+" está "+sig(v,1)+" cm por encima de la media 1993-2012, y lleva "+pl(n.dias_consecutivos,"día consecutivo","días consecutivos")+" por encima de lo normal."; },
    amb:"Entre las provincias costeras con mareógrafo o altimetría." },

  { id:"nt_anio", t:"Más noches tropicales este año", calor:true, url:U.noches,
    val:function(d){ var n=maxNoc(d); return n?n.nt_anyo:null; },
    cifra:function(d,v){ return pl(v,"noche","noches"); },
    desc:function(d){ var n=maxNoc(d); return "En "+n.nombre+", acumuladas en lo que va de año ("+n.nt_mes+" este mes)."; },
    frase:function(d,v){ var n=maxNoc(d);
      return d.provincia+" acumula "+pl(v,"noche tropical","noches tropicales")+" en lo que va de año, la cifra más alta de España"+(n.nombre===d.provincia?"":", medidas en "+n.nombre)+"."; },
    amb:"Entre las provincias con estación de referencia nocturna." },

  { id:"nt_mes", t:"Más noches tropicales este mes", calor:true, url:U.noches,
    val:function(d){ var n=(d.i.noches_tropicales||[]).filter(function(x){return x.nt_mes!=null;});
      if(!n.length) return null; return n.sort(function(a,c){return c.nt_mes-a.nt_mes;})[0].nt_mes; },
    cifra:function(d,v){ return pl(v,"noche","noches"); },
    desc:function(d){ return "Noches por encima de 20 °C en lo que va de mes."; },
    frase:function(d,v){ return "En "+d.provincia+" ya se "+(v===1?"ha registrado":"han registrado")+" "+pl(v,"noche tropical","noches tropicales")+" este mes, más que en ninguna otra provincia."; },
    amb:"Entre las provincias con estación de referencia nocturna." },

  { id:"d32", t:"Más días por encima de 32 °C", calor:true, url:U.obs,
    val:function(d){ return d.i.dias32? d.i.dias32.actual : null; },
    cifra:function(d,v){ return pl(v,"día","días"); },
    desc:function(d){ return "Este año. Media 1991-2020: "+num(d.i.dias32.media_1991_2020,0)+" · Media 1961-1990: "+num(d.i.dias32.media_1961_1990,0)+"."; },
    frase:function(d,v){ return d.provincia+" suma ya "+pl(v,"día","días")+" por encima de 32 °C este año, frente a una media de "+num(d.i.dias32.media_1991_2020,0)+" en el periodo 1991-2020 y de "+num(d.i.dias32.media_1961_1990,0)+" en 1961-1990."; },
    amb:"Entre las provincias con serie de días cálidos." },

  { id:"d32_salto", t:"El mayor salto frente al clima de 1961-1990", calor:true, url:U.obs,
    val:function(d){ if(!d.i.dias32) return null;
      var b=d.i.dias32.media_1961_1990; if(b==null) return null;
      return +(d.i.dias32.actual-b).toFixed(1); },
    cifra:function(d,v){ return "+"+num(v,0)+(Math.round(v)===1?" día":" días"); },
    desc:function(d){ return "De diferencia entre este año ("+d.i.dias32.actual+") y la media 1961-1990 ("+num(d.i.dias32.media_1961_1990,0)+")."; },
    frase:function(d,v){ return d.provincia+" lleva "+num(v,0)+" días más por encima de 32 °C que la media de su periodo 1961-1990, el mayor salto de España: "+d.i.dias32.actual+" días este año frente a "+num(d.i.dias32.media_1961_1990,0)+" entonces."; },
    amb:"Entre las provincias con serie histórica comparable." },

  { id:"tmax", t:"La máxima más alta prevista hoy", calor:true, url:U.canicula,
    val:function(d){ return d.i.canicula? d.i.canicula.tmax_hoy : null; },
    cifra:function(d,v){ return num(v,1)+" °C"; },
    desc:function(d){ return "Previsión para hoy en la provincia · índice de calor "+d.i.canicula.icc+"/100."; },
    frase:function(d,v){ return "La máxima más alta prevista hoy en España es de "+num(v,1)+" °C, en "+d.provincia+"."; },
    amb:"Entre las 52 provincias." },

  { id:"icc", t:"El índice de calor más alto", calor:true, url:U.canicula,
    val:function(d){ return d.i.canicula? d.i.canicula.icc : null; },
    cifra:function(d,v){ return v+"/100"; },
    desc:function(d){ return d.i.canicula.nivel+" · máxima de "+num(d.i.canicula.tmax_hoy,1)+" °C hoy."; },
    frase:function(d,v){ return d.provincia+" registra hoy el índice de canícula más alto de España, "+v+" sobre 100, con una máxima prevista de "+num(d.i.canicula.tmax_hoy,1)+" °C."; },
    amb:"Entre las 52 provincias." },

  { id:"racha", t:"Más días seguidos de calor", calor:true, url:U.canicula,
    val:function(d){ var c=d.i.canicula;
      /* Una racha de 1-2 dias no es noticia: se exige un minimo de 3. */
      return (c && Math.sign(c.dias_consecutivos-3)!==-1)? c.dias_consecutivos : null; },
    cifra:function(d,v){ return pl(v,"día","días"); },
    desc:function(d){ return "Consecutivos por encima de su umbral de calor ("+num(d.i.canicula.ref_p90,1)+" °C)."; },
    frase:function(d,v){ return d.provincia+" encadena "+pl(v,"día consecutivo","días consecutivos")+" por encima de su umbral de calor, situado en "+num(d.i.canicula.ref_p90,1)+" °C: la racha más larga de España ahora mismo."; },
    amb:"Solo provincias que encadenan al menos 3 días de calor." },

  { id:"pr", t:"El calor más marcado por el cambio climático", calor:true, url:U.firma,
    val:function(d){ return (d.i.firma_climatica && d.i.firma_climatica.pr!=null)? d.i.firma_climatica.pr : null; },
    cifra:function(d,v){ return (d.i.firma_climatica.pr_tope?"≥":"")+num(v,0)+"×"; },
    desc:function(d){ return "Más probable hoy en "+d.i.firma_climatica.nombre+" que en un clima sin calentamiento."; },
    frase:function(d,v){ var f=d.i.firma_climatica;
      return "El calor de hoy en "+loc(d,f.nombre)+" es "+(f.pr_tope?"al menos ":"")+num(v,0)+" veces más probable por el cambio climático, que le añade "+sig(f.delta,1)+" °C a la máxima."; },
    amb:"Entre las 52 capitales de provincia." },

  { id:"delta", t:"Más grados añadidos por el cambio climático", calor:true, url:U.firma,
    val:function(d){ return (d.i.firma_climatica && d.i.firma_climatica.delta!=null)? d.i.firma_climatica.delta : null; },
    cifra:function(d,v){ return sig(v,1)+" °C"; },
    desc:function(d){ return "Atribuibles al calentamiento en la máxima de hoy en "+d.i.firma_climatica.nombre+"."; },
    frase:function(d,v){ var f=d.i.firma_climatica;
      return "De los "+num(f.tmax,1)+" °C que marca hoy "+loc(d,f.nombre)+", "+sig(v,1)+" °C son atribuibles al cambio climático."; },
    amb:"Entre las 52 capitales de provincia." },

  { id:"seca", t:"El mayor déficit de lluvia del año", url:U.lluvias,
    /* Solo entran las provincias que REALMENTE llevan deficit (anomalia < 0).
       Sin este filtro, un ano humedo en toda Espana coronaria como "la mas
       seca" a la menos lluviosa de las superavitarias, que es falso. */
    val:function(d){ var l=d.i.lluvias;
      return (l && l.anomalia_anual_pct!=null && Math.sign(l.anomalia_anual_pct)===-1)? -l.anomalia_anual_pct : null; },
    cifra:function(d,v){ return sig(-v,1)+" %"; },
    desc:function(d){ var l=d.i.lluvias;
      return "Lleva "+num(l.mm_anual,1)+" mm frente a los "+num(l.media_hasta_hoy_mm,1)+" mm normales a estas alturas."; },
    frase:function(d,v){ var l=d.i.lluvias;
      return d.provincia+" acumula "+num(l.mm_anual,1)+" mm de lluvia este año, un "+num(v,1)+" % por debajo de lo normal a estas alturas ("+num(l.media_hasta_hoy_mm,1)+" mm)."; },
    amb:"Solo provincias que llevan el año por debajo de su media." },

  { id:"humeda", t:"El mayor superávit de lluvia del año", url:U.lluvias,
    val:function(d){ var l=d.i.lluvias;
      return (l && l.anomalia_anual_pct!=null && Math.sign(l.anomalia_anual_pct)===1)? l.anomalia_anual_pct : null; },
    cifra:function(d,v){ return sig(v,1)+" %"; },
    desc:function(d){ var l=d.i.lluvias;
      return "Lleva "+num(l.mm_anual,1)+" mm frente a los "+num(l.media_hasta_hoy_mm,1)+" mm normales a estas alturas."; },
    frase:function(d,v){ var l=d.i.lluvias;
      return d.provincia+" es la provincia con más lluvia sobre lo normal de España: "+num(l.mm_anual,1)+" mm este año, un "+sig(v,1)+" % respecto a lo esperable a estas alturas."; },
    amb:"Solo provincias que llevan el año por encima de su media." },

  { id:"fuego", t:"Más focos de calor activos", calor:true, url:U.fuego, grupo:"ccaa",
    val:function(d){ return (d.i.incendios_ccaa && d.i.incendios_ccaa.focos_activos)? d.i.incendios_ccaa.focos_activos : null; },
    cifra:function(d,v){ return pl(v,"foco","focos"); },
    desc:function(d){ return "Detectados por satélite en "+d.i.incendios_ccaa.nombre+" en las últimas 48 h."; },
    frase:function(d,v){ return "Los satélites han detectado "+pl(v,"foco de calor activo","focos de calor activos")+" en "+d.i.incendios_ccaa.nombre+" en las últimas 48 horas, la cifra más alta de España."; },
    amb:"Dato por comunidad autónoma, no por provincia.",
    etiqueta:function(d){ return d.i.incendios_ccaa.nombre; } },

  { id:"avisos", t:"Más avisos de AEMET activos", url:U.avisos,
    val:function(d){ return (d.i.avisos && d.i.avisos.total)? d.i.avisos.total : null; },
    cifra:function(d,v){ return pl(v,"aviso","avisos"); },
    desc:function(d){ var a=d.i.avisos;
      return (a.rojos?a.rojos+" rojo(s) · ":"")+(a.naranjas?a.naranjas+" naranja(s) · ":"")+a.amarillos+" amarillo(s)."; },
    frase:function(d,v){ var a=d.i.avisos;
      return d.provincia+" tiene "+pl(v,"aviso meteorológico activo","avisos meteorológicos activos")+" de AEMET"+
        (a.rojos? ", "+(a.rojos===1?"uno de ellos rojo":a.rojos+" de ellos rojos")
                : (a.naranjas? ", "+(a.naranjas===1?"uno de ellos naranja":a.naranjas+" de ellos naranjas") : ""))+"."; },
    amb:"Solo provincias con avisos vigentes." },

  { id:"aire", t:"La peor calidad del aire", url:U.aire,
    val:function(d){ var a=maxAire(d); return a?a.aqi_europeo:null; },
    cifra:function(d,v){ var a=maxAire(d); return a.etiqueta; },
    desc:function(d){ var a=maxAire(d);
      return "Índice europeo "+a.aqi_europeo+" en "+a.nombre+(a.contaminante_dominante?" · dominante: "+a.contaminante_dominante:"")+"."; },
    frase:function(d,v){ var a=maxAire(d);
      return "La peor calidad del aire de España se mide hoy en "+loc(d,a.nombre)+": índice europeo "+a.aqi_europeo+", calificado como «"+a.etiqueta+"»"+(a.contaminante_dominante?", con "+a.contaminante_dominante+" como contaminante dominante":"")+"."; },
    amb:"Entre las provincias con estación de referencia." },

  { id:"nt2050", t:"El mayor aumento de noches tropicales a 2050", calor:true, url:U.m2050,
    val:function(d){ var m=d.i.capital_2050; if(!m||m.noches_tropicales_2050==null) return null;
      return m.noches_tropicales_2050-m.noches_tropicales_hoy; },
    cifra:function(d,v){ return "+"+(v===1?"1 noche":v+" noches"); },
    desc:function(d){ var m=d.i.capital_2050;
      return m.municipio+" pasaría de "+m.noches_tropicales_hoy+" a "+m.noches_tropicales_2050+" noches al año."; },
    frase:function(d,v){ var m=d.i.capital_2050;
      return loc(d,m.municipio)+" es la capital española que más noches tropicales ganaría de aquí a 2050: pasaría de "+m.noches_tropicales_hoy+" a "+m.noches_tropicales_2050+" al año, "+v+" más."; },
    amb:"Proyección a 2050 sobre las 52 capitales." },

  { id:"analogo", t:"La capital con el clima que más se desplaza", calor:true, url:U.m2050,
    val:function(d){ var m=d.i.capital_2050; if(!m||m.meses_secos_2050==null) return null;
      return +(m.meses_secos_2050-m.meses_secos_hoy).toFixed(1); },
    cifra:function(d,v){ return "+"+num(v,1)+" meses"; },
    desc:function(d){ var m=d.i.capital_2050;
      return m.municipio+" tendría en 2050 el clima de "+m.analogo_climatico+"."; },
    frase:function(d,v){ var m=d.i.capital_2050;
      return "En 2050 "+loc(d,m.municipio)+" tendrá un clima parecido al que hoy tiene "+m.analogo_climatico+", con "+num(v,1)+" meses secos más al año."; },
    amb:"Proyección a 2050 sobre las 52 capitales." },

  /* ---- Se activan solos cuando los JSON incluyan estos campos ---------- */
  { id:"embalses", t:"Los embalses más bajos", url:U.embalses, futuro:true,
    val:function(d){ return (d.i.embalses && d.i.embalses.pct_media!=null)? -d.i.embalses.pct_media : null; },
    cifra:function(d,v){ return num(-v,1)+" %"; },
    desc:function(d){ var e=d.i.embalses;
      return "De su capacidad"+(e.n_embalses?" ("+e.n_embalses+" embalses)":"")+
        (e.pct_hace_un_anio!=null?" · hace un año: "+num(e.pct_hace_un_anio,1)+" %":"")+"."; },
    frase:function(d,v){ var e=d.i.embalses;
      return "Los embalses de "+d.provincia+" están al "+num(-v,1)+" % de su capacidad"+
        (e.pct_hace_un_anio!=null?", frente al "+num(e.pct_hace_un_anio,1)+" % de hace un año":"")+"."; },
    amb:"Un embalse pertenece a una cuenca, no a una provincia: el agua que almacena puede abastecer a otra." },

  { id:"muertes", t:"Mayor mortalidad atribuida al calor", url:U.muertes, futuro:true,
    val:function(d){ var m=d.i.mortalidad_calor;
      if(!m||m.tasa_100k==null||m.fiabilidad==="baja") return null; return m.tasa_100k; },
    cifra:function(d,v){ return num(v,1); },
    desc:function(d){ var m=d.i.mortalidad_calor;
      return "Defunciones estimadas por 100.000 habitantes atribuibles al exceso de temperatura ("+m.atribuible_verano+" en total)."; },
    frase:function(d,v){ var m=d.i.mortalidad_calor;
      return "MoMo estima "+m.atribuible_verano+" defunciones atribuibles al exceso de temperatura en "+d.provincia+" este verano, una tasa de "+num(v,1)+" por cada 100.000 habitantes."; },
    amb:"Estimación de MoMo (ISCIII). No son muertes certificadas por calor. Se excluyen del ranking las provincias donde la estimación no es fiable por tamaño de población." }
  ];

  /* ======================================================================
     CARGA
  ====================================================================== */
  var app = document.getElementById("cch-app");

  fetch(BASE+"index.json",{cache:"no-store"})
    .then(function(r){ return r.json(); })
    .then(function(idx){
      document.getElementById("cch-stamp").innerHTML =
        "Datos actualizados el <b>"+esc(idx.fecha_legible)+"</b> · "+idx.total_provincias+
        " provincias · AEMET · Puertos del Estado · Copernicus · NASA FIRMS · NOAA · Open-Meteo";
      return Promise.all(idx.provincias.map(function(p){
        return fetch(BASE+p.slug+".json",{cache:"no-store"})
          .then(function(r){ return r.json(); })
          .then(function(j){ return {slug:p.slug, provincia:j.provincia, ccaa:j.ccaa,
                                     capital:j.capital, i:j.indicadores||{},
                                     top:p.top, novedades:p.novedades||[]}; })
          .catch(function(){ return {slug:p.slug, provincia:p.provincia, ccaa:p.ccaa,
                                     i:{}, top:p.top, novedades:[]}; });
      })).then(function(datos){ pintar(idx, datos); });
    })
    .catch(function(){
      app.innerHTML = '<div class="cch-err">No se han podido cargar los datos del observatorio en este momento. '+
        'Puedes consultar cada provincia desde el <a href="'+U.obs+'">Observatorio climático</a>.</div>';
    });

  /* ======================================================================
     CALCULO DE RANKINGS
  ====================================================================== */
  function calcular(datos){
    var out=[];
    RANKINGS.forEach(function(R){
      var lista=[];
      datos.forEach(function(d){
        var v=null;
        try{ v=R.val(d); }catch(e){ v=null; }
        if(v!==null && v!==undefined && !isNaN(v)) lista.push({d:d, v:v});
      });
      if(!lista.length) return;
      lista.sort(function(a,b){ return b.v-a.v; });

      /* Agrupar por CCAA cuando el dato es autonomico (incendios) */
      if(R.grupo==="ccaa"){
        var visto={}, filtrada=[];
        lista.forEach(function(x){
          var k = R.etiqueta? R.etiqueta(x.d) : x.d.ccaa;
          if(!visto[k]){ visto[k]=1; filtrada.push(x); }
        });
        lista=filtrada;
      }
      out.push({R:R, lista:lista, n:lista.length});
    });
    return out;
  }

  /* ======================================================================
     PINTADO
  ====================================================================== */
  function pintar(idx, datos){
    var rk = calcular(datos);
    var porId={}; rk.forEach(function(x){ porId[x.R.id]=x; });

    /* ---- Dato del dia: rotacion determinista por dia del ano ---------- */
    var pool = rk.filter(function(x){ return x.lista.length>=2; });
    var hero = pool.length ? pool[diaDelAnio() % pool.length] : null;
    var heroHtml="";
    if(hero){
      var g=hero.lista[0];
      heroHtml =
        '<div class="cch-hero">'+
          '<div class="k">El dato de hoy · '+esc(idx.fecha_legible.split(" ")[0])+'</div>'+
          '<div class="big">'+esc(hero.R.frase(g.d,g.v))+'</div>'+
          '<div class="who">'+esc(hero.R.amb)+' · <a href="'+urlProv(g.d.slug)+'">Ver la página de '+esc(g.d.provincia)+' →</a></div>'+
        '</div>';
    }

    /* ---- Tarjetas de record ------------------------------------------ */
    var recs = rk.map(function(x){
      var g=x.lista[0];
      var podio = x.lista.slice(1,4).map(function(y,k){
        return '<b>'+(k+2)+'.</b> '+esc(y.d.provincia)+' · '+esc(x.R.cifra(y.d,y.v));
      }).join("<br>");
      return '<div class="cch-rec'+(x.R.calor?" calor":"")+'">'+
        '<div class="t">'+esc(x.R.t)+'</div>'+
        '<div class="n">'+esc(x.R.cifra(g.d,g.v))+'</div>'+
        '<div class="p"><a href="'+urlProv(g.d.slug)+'">'+esc(g.d.provincia)+'</a></div>'+
        '<div class="d">'+esc(x.R.desc(g.d))+'</div>'+
        (podio?'<div class="pod">'+podio+'</div>':'')+
        '<div class="amb">'+esc(x.R.amb)+' · <a href="'+x.R.url+'">Ver herramienta →</a></div>'+
      '</div>';
    }).join("");

    /* ---- Titulares (orden rotado cada dia) ---------------------------- */
    var off = diaDelAnio() % Math.max(rk.length,1);
    var rot = rk.slice(off).concat(rk.slice(0,off));
    var tits = rot.map(function(x,k){
      var g=x.lista[0], f=x.R.frase(g.d,g.v);
      return '<div class="row"><span class="ix">'+(k+1)+'</span>'+
        '<span class="tx">'+esc(f)+
          '<span class="src">'+esc(x.R.amb)+' · Fuente: Observatorio Climático de calentamientoglobal.es · '+esc(idx.fecha_legible)+'</span>'+
        '</span>'+
        '<button class="cp" type="button" data-f="'+esc(f)+'">Copiar</button></div>';
    }).join("");

    /* ---- Fichas de las 52 -------------------------------------------- */
    var ccaas={}; datos.forEach(function(d){ if(d.ccaa) ccaas[d.ccaa]=1; });
    var opts = Object.keys(ccaas).sort(function(a,b){ return a.localeCompare(b,"es"); })
      .map(function(c){ return '<option value="'+esc(c)+'">'+esc(c)+'</option>'; }).join("");

    var orden = datos.slice().sort(function(a,b){ return a.provincia.localeCompare(b.provincia,"es"); });
    var fichas = orden.map(function(d){
      var mets=[], b=maxBoya(d), n=maxNoc(d);
      if(d.i.canicula) mets.push({v:num(d.i.canicula.tmax_hoy,1)+"°", l:"máx. hoy", c:1});
      if(b) mets.push({v:num(b.temp,1)+"°", l:"mar ahora", c:0});
      if(n) mets.push({v:n.nt_anyo, l:"noches trop.", c:0});
      if(!b && d.i.dias32) mets.push({v:d.i.dias32.actual, l:"días >32°", c:1});
      var mh = mets.slice(0,3).map(function(m){
        return '<div class="met"><div class="mv'+(m.c?" calor":"")+'">'+esc(m.v)+'</div><div class="ml">'+esc(m.l)+'</div></div>';
      }).join("");
      return '<a class="cch-card" href="'+urlProv(d.slug)+'" data-p="'+esc(d.provincia.toLowerCase())+'" data-c="'+esc(d.ccaa)+'">'+
        '<div class="pn">'+esc(d.provincia)+'</div>'+
        '<div class="cc">'+esc(d.ccaa)+'</div>'+
        '<div class="top">'+esc(d.top? d.top.replace(/ · \d+\.º día consecutivo/,"") : "Sin anomalías destacables hoy.")+'</div>'+
        (mh?'<div class="mets">'+mh+'</div>':'')+
        '<div class="go">Ver el observatorio de '+esc(d.provincia)+' →</div>'+
      '</a>';
    }).join("");

    /* ---- Tabla comparativa ------------------------------------------- */
    var COLS=[
      {k:"provincia", t:"Provincia", txt:true},
      {k:"ccaa", t:"Comunidad", txt:true},
      {k:"tmax", t:"Máx. hoy °C", f:function(d){ return d.i.canicula? d.i.canicula.tmax_hoy : null; }},
      {k:"icc", t:"Índice calor", f:function(d){ return d.i.canicula? d.i.canicula.icc : null; }},
      {k:"pr", t:"× por CC", f:function(d){ return d.i.firma_climatica? d.i.firma_climatica.pr : null; }, dec:0},
      {k:"delta", t:"°C por CC", f:function(d){ return d.i.firma_climatica? d.i.firma_climatica.delta : null; }},
      {k:"mar", t:"Mar °C", f:function(d){ var b=maxBoya(d); return b? b.temp : null; }},
      {k:"anom", t:"Anom. mar", f:function(d){ var m=maxMar(d); return m? m.anomalia : null; }},
      {k:"niv", t:"Nivel mar cm", f:function(d){ var n=maxNivel(d); return n? n.desviacion_cm : null; }},
      {k:"nt", t:"Noches trop.", f:function(d){ var n=maxNoc(d); return n? n.nt_anyo : null; }, dec:0},
      {k:"d32", t:"Días >32 °C", f:function(d){ return d.i.dias32? d.i.dias32.actual : null; }, dec:0},
      {k:"lluv", t:"Lluvia año %", f:function(d){ return d.i.lluvias? d.i.lluvias.anomalia_anual_pct : null; }},
      {k:"emb", t:"Embalses %", f:function(d){ return d.i.embalses? d.i.embalses.pct_media : null; }}
    ];
    var usadas = COLS.filter(function(c){
      if(c.txt) return true;
      return datos.some(function(d){ var v=c.f(d); return v!==null&&v!==undefined; });
    });
    var thead = usadas.map(function(c){ return '<th data-k="'+c.k+'">'+esc(c.t)+' <span class="ar">&#8597;</span></th>'; }).join("");
    var tbody = orden.map(function(d){
      return '<tr>'+usadas.map(function(c){
        if(c.k==="provincia") return '<td><a href="'+urlProv(d.slug)+'">'+esc(d.provincia)+'</a></td>';
        if(c.k==="ccaa") return '<td>'+esc(d.ccaa)+'</td>';
        var v=c.f(d);
        if(v===null||v===undefined) return '<td class="num na">—</td>';
        return '<td class="num" data-v="'+v+'">'+esc(num(v,c.dec===undefined?1:c.dec))+'</td>';
      }).join("")+'</tr>';
    }).join("");

    /* ---- Montaje ------------------------------------------------------ */
    app.innerHTML =
      heroHtml +

      '<h2>Los récords de España, hoy</h2>'+
      '<p class="h2sub">Cada tarjeta compara las 52 provincias en un indicador y se recalcula al abrir la página. Debajo del primer puesto aparecen el segundo, el tercero y el cuarto.</p>'+
      '<div class="cch-grid">'+recs+'</div>'+

      '<h2>Titulares listos para usar</h2>'+
      '<p class="h2sub">Frases completas, con la cifra, la unidad, el lugar y el ámbito del dato. Pensadas para copiar y pegar en una redacción. Si citas alguna, la licencia es CC-BY 4.0 y basta con mencionar «calentamientoglobal.es».</p>'+
      '<div class="cch-tit">'+tits+'</div>'+

      '<h2>Las 52 provincias</h2>'+
      '<p class="h2sub">Cada ficha lleva al observatorio de esa provincia, con su panel de datos en directo y su contexto climático propio.</p>'+
      '<div class="cch-tools">'+
        '<input type="search" id="cch-q" placeholder="Buscar provincia…" aria-label="Buscar provincia">'+
        '<select id="cch-cc" aria-label="Filtrar por comunidad autónoma"><option value="">Todas las comunidades</option>'+opts+'</select>'+
      '</div>'+
      '<div class="cch-prov" id="cch-prov">'+fichas+'</div>'+
      '<div class="cch-note" id="cch-nores" style="display:none">No hay ninguna provincia que coincida con esa búsqueda.</div>'+

      '<h2>Tabla comparativa</h2>'+
      '<p class="h2sub">Las 52 provincias y sus indicadores de hoy. Pulsa en cualquier cabecera para ordenar. Un guion significa que esa provincia no tiene ese indicador: las de interior no tienen boya ni nivel del mar.</p>'+
      '<div class="cch-wrap"><table class="cch-tbl"><thead><tr>'+thead+'</tr></thead><tbody id="cch-tb">'+tbody+'</tbody></table></div>'+

      '<div class="cch-note"><b>Sobre estas comparaciones.</b> Un ranking solo incluye a las provincias que disponen de ese indicador, y el ámbito real aparece escrito en cada tarjeta. Los focos de incendio se detectan por comunidad autónoma, no por provincia. El dato de un aviso, una boya o una estación describe el punto donde se mide, no toda la provincia. Y una cifra alta un día concreto es meteorología: el cambio climático se lee en la repetición, no en el récord aislado.</div>';

    activar();
  }

  /* ======================================================================
     INTERACCION
  ====================================================================== */
  function activar(){
    /* Copiar titular */
    app.addEventListener("click", function(e){
      var b=e.target.closest?e.target.closest(".cp"):null;
      if(!b) return;
      var txt=b.getAttribute("data-f");
      var ok=function(){ var o=b.textContent; b.textContent="Copiado"; setTimeout(function(){ b.textContent=o; },1600); };
      if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(txt).then(ok,ok); }
      else { var ta=document.createElement("textarea"); ta.value=txt; document.body.appendChild(ta);
             ta.select(); try{ document.execCommand("copy"); }catch(err){} document.body.removeChild(ta); ok(); }
    });

    /* Buscador + filtro */
    var q=document.getElementById("cch-q"), cc=document.getElementById("cch-cc"),
        cont=document.getElementById("cch-prov"), nores=document.getElementById("cch-nores");
    function filtrar(){
      var t=(q.value||"").toLowerCase()
        .normalize("NFD").replace(/[\u0300-\u036f]/g,"");
      var c=cc.value, vis=0;
      Array.prototype.forEach.call(cont.children, function(el){
        var p=(el.getAttribute("data-p")||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"");
        var ok=(!t||p.indexOf(t)!==-1) && (!c||el.getAttribute("data-c")===c);
        el.style.display = ok?"":"none"; if(ok) vis++;
      });
      nores.style.display = vis?"none":"block";
    }
    q.addEventListener("input",filtrar); cc.addEventListener("change",filtrar);

    /* Ordenar tabla */
    var tb=document.getElementById("cch-tb");
    Array.prototype.forEach.call(app.querySelectorAll(".cch-tbl th"), function(th,ix){
      var asc=false;
      th.addEventListener("click", function(){
        asc=!asc;
        var fs=Array.prototype.slice.call(tb.querySelectorAll("tr"));
        fs.sort(function(a,b){
          var ca=a.children[ix], cb=b.children[ix];
          var va=ca.hasAttribute("data-v")?parseFloat(ca.getAttribute("data-v")):null;
          var vb=cb.hasAttribute("data-v")?parseFloat(cb.getAttribute("data-v")):null;
          if(va===null&&vb===null) return ca.textContent.localeCompare(cb.textContent,"es")*(asc?1:-1);
          if(va===null) return 1; if(vb===null) return -1;
          return (asc? va-vb : vb-va);
        });
        fs.forEach(function(f){ tb.appendChild(f); });
      });
    });
  }
})();
