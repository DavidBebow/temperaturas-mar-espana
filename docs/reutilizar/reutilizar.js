/*! reutilizar.js 1.1.0 · 1-11-2026 · calentamientoglobal.es · CC BY 4.0 */
(function () {
  'use strict';
  var BASE0 = 'https://davidbebow.github.io/temperaturas-mar-espana/';
  var WEB = 'https://calentamientoglobal.es';
  var Q = new URLSearchParams(location.search);
  var HOY = new Date().toISOString().slice(0, 10);
  var EVENTOS = { abrir: 'reutilizar_abrir', descarga: 'descarga_datos', insertar: 'insertar_copiado', citar: 'cita_copiada' };
  var cacheJ = {};

  function log() { try { console.log.apply(console, ['[reutilizar]'].concat([].slice.call(arguments))); } catch (e) {} }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function limpia(s) { return String(s || '').replace(/[<>"'&\s\/\\?#]/g, ''); }
  function fechaEs(iso) { var p = String(iso).slice(0, 10).split('-'); return p[2] + '/' + p[1] + '/' + p[0]; }

  function getJSON(url) {
    if (!cacheJ[url]) cacheJ[url] = fetch(url).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    return cacheJ[url];
  }
  // A Coruña vive como a_coruña.json: probamos las variantes de normalización unicode.
  function getJSONvar(base, tpl, slug) {
    var vars = [slug, slug.normalize('NFC'), slug.normalize('NFD')].filter(function (v, i, a) { return a.indexOf(v) === i; });
    var i = 0;
    function prueba() {
      var u = base + tpl.replace('{slug}', encodeURIComponent(vars[i]));
      return getJSON(u).catch(function (e) { if (++i < vars.length) return prueba(); throw e; });
    }
    return prueba();
  }

  /* ---------- 1. Resolver la herramienta ---------- */
  function ruta() {
    var p = location.pathname, k = p.indexOf('/temperaturas-mar-espana/');
    p = k >= 0 ? p.slice(k + 25) : p.replace(/^\//, '');
    try { p = decodeURIComponent(p); } catch (e) {}
    p = p.normalize('NFC');
    if (!p || /\/$/.test(p)) p += 'index.html';
    return p;
  }
  function casa(cat, rel) {
    var hs = cat.herramientas, i, h, j;
    for (i = 0; i < hs.length; i++) {
      h = hs[i];
      var lista = [h.widget].concat(h.alt || []);
      for (j = 0; j < lista.length; j++) if (lista[j] === rel) return { h: h, rel: rel };
    }
    for (i = 0; i < hs.length; i++) {
      h = hs[i];
      if (h.widget.indexOf('{slug}') < 0) continue;
      var re = new RegExp('^' + h.widget.replace(/[.*+?^$()|[\]\\]/g, '\\$&').replace('{slug}', '([^/]+)') + '$');
      var m = re.exec(rel);
      if (m) return { h: h, rel: rel, slugFichero: m[1] };
    }
    return null;
  }
  function slugDe(r) {
    var h = r.h, s = null;
    if (h.parametro) s = Q.get(h.parametro);
    if (!s && r.slugFichero) s = r.slugFichero;
    return s ? limpia(s.normalize('NFC')).toLowerCase() : '';
  }

  /* ---------- 2. Datos de la herramienta ---------- */
  function resuelve(cat, r) {
    var h = r.h, slug = slugDe(r), base = cat.base || BASE0;
    var T = { id: h.id, slug: slug, porFichero: !!(r.slugFichero && !(h.parametro && Q.get(h.parametro))), base: base, h: h, rel: r.rel, ga4: cat.ga4 || '', titulo: h.titulo || h.id, pagina: h.pagina || WEB + '/', fecha: HOY, consulta: true, fuente: h.fuente || '', fc: h.fuente_corta || String(h.fuente || '').split(' · ')[0] };
    var sl = slug.replace(/_/g, '-');
    if (h.pagina_patron) T.pagina = h.pagina_patron.replace('{slug}', (h.alias_slug && h.alias_slug[sl]) || sl);
    var jsonUrl = h.json ? base + h.json.replace('{slug}', encodeURIComponent(slug)) : '';
    T.jsonUrl = jsonUrl;
    var tareas = [];
    if (h.json) tareas.push(getJSONvar(base, h.json, slug).then(function (d) {
      T.datos = d;
      var ks = h.campo_fecha || [];
      for (var i = 0; i < ks.length; i++) {
        var v = d && d[ks[i]];
        if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v)) { T.fecha = v.slice(0, 10); T.consulta = false; break; }
      }
    }).catch(function () { log('sin JSON de datos para', h.id); }));
    if (h.pagina_de) tareas.push(getJSONvar(base, h.pagina_de.json, slug).then(function (d) { if (d && d[h.pagina_de.campo]) T.pagina = d[h.pagina_de.campo]; }).catch(function () {}));
    if (h.titulo_de) tareas.push(getJSONvar(base, h.titulo_de.json, slug).then(function (d) {
      var v = d && d[h.titulo_de.campo];
      if (v) T.titulo = (h.titulo_de.plantilla || '{valor}').replace('{valor}', v);
    }).catch(function () {}));
    return Promise.all(tareas).then(function () { return T; });
  }

  /* ---------- 3. Contexto ---------- */
  function origenPadre() {
    try { if (location.ancestorOrigins && location.ancestorOrigins.length) return location.ancestorOrigins[0]; } catch (e) {}
    try { return document.referrer ? new URL(document.referrer).origin : ''; } catch (e) { return ''; }
  }
  var PADRE = origenPadre();
  var ENCASA = PADRE === WEB || PADRE === 'https://www.calentamientoglobal.es' || (document.referrer || '').indexOf(WEB) === 0;
  function modo() {
    if (Q.get('captura') === '1') return 'captura';
    // viento y caudal ya usan ?embed=1 dentro de WordPress: si el padre es la web, es «propio».
    if (ENCASA) return 'propio';
    if (Q.get('embed') === '1') return 'embed';
    return 'externo';
  }

  /* ---------- 7. Eventos ---------- */
  var gtagListo = false;
  function cargaGtag(T) {
    if (gtagListo || !T.ga4) return;
    gtagListo = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    gtag('consent', 'default', { analytics_storage: 'denied', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied' });
    gtag('js', new Date());
    gtag('config', T.ga4, { send_page_view: false, page_location: T.pagina, page_title: T.titulo, storage: 'none' });
    var s = document.createElement('script');
    s.async = true; s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(T.ga4);
    document.head.appendChild(s);
  }
  function sitioExterno() { try { return PADRE ? new URL(PADRE).host : 'directo'; } catch (e) { return 'directo'; } }
  function evento(T, M, accion, extra) {
    extra = extra || {};
    var msg = { cg: 'reutilizar', accion: accion, herramienta: T.id, formato: extra.formato || '', pagina: T.pagina };
    try { if (parent !== window) parent.postMessage(msg, '*'); } catch (e) {}
    if (!ENCASA && T.ga4 && (M === 'externo' || M === 'embed')) {
      cargaGtag(T);
      var p = { herramienta: T.id, pagina_herramienta: T.pagina, sitio_externo: sitioExterno() };
      if (extra.formato) p.formato = extra.formato;
      gtag('event', EVENTOS[accion] || accion, p);
    }
  }

  /* ---------- CSV ---------- */
  function esPlano(o) { return o && typeof o === 'object' && !Array.isArray(o); }
  function arraysDeObjetos(d, prof, ruta, out) {
    if (Array.isArray(d)) { if (d.length && d.every(esPlano)) out.push({ ruta: ruta, rows: d }); return; }
    if (!esPlano(d) || prof > 2) return;
    Object.keys(d).forEach(function (k) { arraysDeObjetos(d[k], prof + 1, ruta + '/' + k, out); });
  }
  function filasCSV(d) {
    var c = []; arraysDeObjetos(d, 0, '', c);
    if (c.length) { c.sort(function (a, b) { return b.rows.length - a.rows.length; }); return c[0].rows; }
    // Alternativa: diccionario de objetos {clave:{...}} → una fila por clave.
    var best = null;
    if (esPlano(d)) Object.keys(d).forEach(function (k) {
      var v = d[k];
      if (esPlano(v)) { var ks = Object.keys(v); if (ks.length > 3 && ks.every(function (x) { return esPlano(v[x]); }) && (!best || ks.length > best.n)) best = { k: k, n: ks.length }; }
    });
    if (best) return Object.keys(d[best.k]).map(function (x) { var o = { clave: x }; var s = d[best.k][x]; Object.keys(s).forEach(function (y) { o[y] = s[y]; }); return o; });
    return null;
  }
  function aplana(row) {
    var o = {};
    Object.keys(row).forEach(function (k) {
      var v = row[k];
      if (Array.isArray(v)) return;
      if (esPlano(v)) { Object.keys(v).forEach(function (s) { var w = v[s]; if (w === null || typeof w !== 'object') o[k + '.' + s] = w; }); return; }
      o[k] = v;
    });
    return o;
  }
  function celda(v) { if (v === null || v === undefined) return ''; v = String(v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function construyeCSV(T) {
    var rows = null;
    if (T.datos && T.h.csv_ruta && Array.isArray(T.datos[T.h.csv_ruta]) && T.datos[T.h.csv_ruta].every(esPlano)) rows = T.datos[T.h.csv_ruta];
    if (!rows && T.datos) rows = filasCSV(T.datos);
    if (!rows) return null;
    var fl = rows.map(aplana), cols = [];
    fl.forEach(function (r) { Object.keys(r).forEach(function (k) { if (cols.indexOf(k) < 0) cols.push(k); }); });
    var out = ['# Fuente: calentamientoglobal.es con datos de ' + T.fuente + ' · CC BY 4.0 · ' + T.pagina, cols.map(celda).join(',')];
    fl.forEach(function (r) { out.push(cols.map(function (c) { return celda(r[c]); }).join(',')); });
    return '﻿' + out.join('\n') + '\n';
  }
  function nombreBase(T) { return T.id + (T.slug ? '-' + T.slug : ''); }
  // El índice del bloque F usa claves sin tildes (a_coruña -> a_coruna), igual que los nombres de los PNG.
  function clavePng(T) { return nombreBase(T).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, ''); }

  /* ---------- Textos de inserción y cita ---------- */
  function urlWidget(T) {
    var ruta = T.rel.split('/').map(encodeURIComponent).join('/');
    var ps = [];
    if (T.h.parametro && T.slug && !T.porFichero) ps.push(T.h.parametro + '=' + encodeURIComponent(T.slug));
    ps.push('embed=1');
    return T.base + ruta + '?' + ps.join('&');
  }
  function codigoInsertar(T) {
    return '<iframe src="' + urlWidget(T) + '" width="100%" height="' + (T.h.alto_embed || 700) + '" style="border:0" loading="lazy" title="' + esc(T.titulo) + ' · calentamientoglobal.es"></iframe>' +
      '<p style="font:13px/1.4 sans-serif;margin:6px 0 0">Gráfico: <a href="' + T.pagina + '">' + esc(T.titulo) + ' · CalentamientoGlobal.es</a> · datos ' + esc(T.fc) + ' · CC BY 4.0</p>';
  }
  function textoCita(T) {
    return 'CalentamientoGlobal.es (' + new Date().getFullYear() + '). ' + T.titulo + ', con datos de ' + T.fuente + '. ' + T.pagina + ' · consultado el ' + fechaEs(HOY) + ' · CC BY 4.0';
  }

  /* ---------- Estilos ---------- */
  var CSS = ':host{all:initial}*{box-sizing:border-box}' +
    '.f{font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#e8f1f8}' +
    '.pil{position:fixed;z-index:2147483000;background:rgba(12,33,51,.94);color:#e8f1f8;border:1px solid rgba(191,230,255,.16);border-radius:999px;padding:9px 15px;font:600 13px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;cursor:pointer;box-shadow:0 4px 18px rgba(0,0,0,.28)}' +
    '.pil:hover{background:#0c2133;border-color:rgba(191,230,255,.4)}.pil:focus-visible,.b:focus-visible,.x:focus-visible,a:focus-visible{outline:2px solid #bfe6ff;outline-offset:2px}' +
    '.pab-c{bottom:12px;left:50%;transform:translateX(-50%)}.pab-i{bottom:12px;left:12px}.pab-d{bottom:12px;right:12px}.par-d{top:12px;right:12px}' +
    '.vel{position:fixed;inset:0;z-index:2147483001;background:rgba(0,0,0,.18)}' +
    '.pan{position:fixed;z-index:2147483002;width:min(440px,calc(100vw - 24px));max-height:90vh;overflow:auto;background:#0c2133;color:#e8f1f8;border:1px solid rgba(191,230,255,.16);border-radius:22px;padding:18px 18px 16px;box-shadow:0 12px 40px rgba(0,0,0,.45)}' +
    '.pan.pab-c{bottom:56px;left:50%;transform:translateX(-50%)}.pan.pab-i{bottom:56px;left:12px;transform:none}.pan.pab-d{bottom:56px;right:12px;left:auto;transform:none}.pan.par-d{top:56px;right:12px;bottom:auto;left:auto;transform:none}' +
    '.cab{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:6px}.cab h2{margin:0;font:700 16px/1.25 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}' +
    '.x{background:transparent;border:0;color:#9fb6c8;font-size:22px;line-height:1;cursor:pointer;padding:2px 6px;border-radius:8px}.x:hover{color:#e8f1f8}' +
    '.sub{margin:0 0 12px;font-size:12.5px;color:#9fb6c8}.sec{border-top:1px solid rgba(191,230,255,.16);padding:12px 0 2px}' +
    '.sec h3{margin:0 0 8px;font:600 11.5px/1 -apple-system,BlinkMacSystemFont,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#9fb6c8}' +
    '.fila{display:flex;flex-wrap:wrap;gap:8px;align-items:center}' +
    '.b{font:600 13.5px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#0c2133;background:#bfe6ff;border:0;border-radius:999px;padding:10px 15px;cursor:pointer;text-decoration:none;display:inline-block}.b:hover{background:#d8f0ff}' +
    '.b.s{background:rgba(255,255,255,.08);color:#e8f1f8;border:1px solid rgba(191,230,255,.3)}.b.s:hover{background:rgba(255,255,255,.14)}' +
    'textarea{width:100%;height:108px;margin:0 0 8px;background:#081a29;color:#e8f1f8;border:1px solid rgba(191,230,255,.3);border-radius:14px;padding:10px;font:12px/1.45 ui-monospace,Menlo,Consolas,monospace;resize:vertical}' +
    '.ok{font-size:13px;color:#bfe6ff;opacity:0;transition:opacity .2s}.ok.on{opacity:1}.min{width:100%;border-radius:12px;margin:0 0 10px;display:block;border:1px solid rgba(191,230,255,.16)}' +
    '.pie{position:fixed;left:0;right:0;bottom:0;height:34px;z-index:2147483000;background:rgba(12,33,51,.94);color:#e8f1f8;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 12px;font:12.5px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;border-top:1px solid rgba(191,230,255,.16)}' +
    '.pie a{color:#bfe6ff;font-weight:600;text-decoration:none;white-space:nowrap}.pie a:hover{text-decoration:underline}.pie .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pie img,.cap img{display:block}' +
    '.cap{position:fixed;left:0;right:0;bottom:0;height:64px;z-index:2147483000;background:#0c2133;color:#e8f1f8;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 22px;font:13px/1.35 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;border-top:2px solid #bfe6ff}' +
    '.cap b{font-size:16px;display:block}.cap .m{color:#9fb6c8;font-size:12px}' +
    '@media (max-width:600px){.pan,.pan.pab-c,.pan.pab-i,.pan.pab-d,.pan.par-d{left:0;right:0;bottom:0;top:auto;width:auto;max-height:90vh;border-radius:22px 22px 0 0;transform:none}.pie{font-size:11.5px}}';

  function host() {
    var h = document.createElement('div');
    h.id = 'cg-reutilizar';
    h.style.cssText = 'position:fixed;top:0;left:0;width:0;height:0;z-index:2147483000';
    (document.documentElement).appendChild(h);
    var sr = h.attachShadow({ mode: 'open' });
    var st = document.createElement('style'); st.textContent = CSS; sr.appendChild(st);
    return sr;
  }
  function relleno(px) { var s = document.createElement('style'); s.textContent = 'body{padding-bottom:' + px + 'px!important}'; document.head.appendChild(s); }
  function logo(T, alto, cb) {
    getJSON(T.base + 'reutilizar/patrocinio.json?v=' + HOY).then(function (p) {
      var e = p && (p[T.id + (T.slug ? '-' + T.slug : '')] || p[T.id]);
      cb(e && e.logo_url ? '<a href="' + esc(e.url || '#') + '" target="_blank" rel="noopener sponsored"><img src="' + esc(e.logo_url) + '" alt="' + esc(e.nombre || '') + '" style="height:' + alto + 'px"></a>' : '');
    }).catch(function () { cb(''); });
  }

  /* ---------- 5. Embed ---------- */
  function pintaEmbed(T) {
    relleno(34);
    var sr = host();
    logo(T, 22, function (lg) {
      var d = document.createElement('div'); d.className = 'pie';
      d.innerHTML = '<span class="t">Fuente: calentamientoglobal.es · datos ' + esc(T.fc) + ' · CC BY 4.0 · <a href="' + esc(T.pagina) + '" target="_top">Ver en calentamientoglobal.es ↗</a></span>' + lg;
      sr.appendChild(d);
    });
  }

  /* ---------- 6. Captura ---------- */
  function pintaCaptura(T) {
    relleno(64);
    var sr = host();
    logo(T, 40, function (lg) {
      var d = document.createElement('div'); d.className = 'cap';
      var ruta = T.pagina.replace(/^https?:\/\//, '');
      d.innerHTML = '<div><b>' + esc(T.titulo) + '</b><span class="m">Dato: ' + esc(fechaEs(T.fecha)) + (T.consulta ? ' (consulta)' : '') + ' · ' + esc(ruta) + ' · datos ' + esc(T.fuente) + ' · CC BY 4.0</span></div>' + lg;
      sr.appendChild(d);
      window.__cgCapturaLista = true;
    });
  }

  /* ---------- 4. Modo propio ---------- */
  function pintaPropio(T) {
    var sr = host(), pos = T.h.posicion || 'abajo-centro';
    if (window.innerHeight < 220) pos = 'arriba-derecha';
    var cls = { 'abajo-centro': 'pab-c', 'abajo-izquierda': 'pab-i', 'abajo-derecha': 'pab-d', 'arriba-derecha': 'par-d' }[pos] || 'pab-c';
    var pil = document.createElement('button');
    pil.type = 'button'; pil.className = 'pil ' + cls; pil.textContent = '⤓ Datos · Insertar · Citar';
    pil.setAttribute('aria-label', 'Datos, insertar y citar: descargar, insertar o citar ' + T.titulo);
    sr.appendChild(pil);
    var abierto = null;

    function cierra() { if (!abierto) return; abierto.v.remove(); abierto.p.remove(); abierto = null; document.removeEventListener('keydown', tecla, true); pil.focus(); }
    function tecla(e) { if (e.key === 'Escape') { e.stopPropagation(); cierra(); } }

    function abre() {
      if (abierto) return cierra();
      evento(T, 'propio', 'abrir');
      var v = document.createElement('div'); v.className = 'vel'; v.addEventListener('click', cierra);
      var p = document.createElement('div'); p.className = 'pan f ' + cls;
      p.setAttribute('role', 'dialog'); p.setAttribute('aria-modal', 'true'); p.setAttribute('aria-label', 'Datos, insertar y citar ' + T.titulo);
      var csv = construyeCSV(T);
      p.innerHTML =
        '<div class="cab"><h2>' + esc(T.titulo) + '</h2><button type="button" class="x" aria-label="Cerrar">×</button></div>' +
        '<p class="sub">Datos de ' + esc(T.fuente) + ' · ' + esc(fechaEs(T.fecha)) + (T.consulta ? ' (consulta)' : '') + ' · licencia CC BY 4.0</p>' +
        '<div class="sec" id="s-d"><h3>Descargar</h3><div class="fila" id="f-d"></div></div>' +
        '<div class="sec"><h3>Insertar</h3><textarea id="t-i" readonly aria-label="Código para insertar"></textarea><div class="fila"><button type="button" class="b" id="b-i">Copiar código</button><span class="ok" id="ok-i" role="status">Copiado</span></div></div>' +
        '<div class="sec"><h3>Citar</h3><textarea id="t-c" readonly aria-label="Texto de cita" style="height:74px"></textarea><div class="fila"><button type="button" class="b" id="b-c">Copiar cita</button><span class="ok" id="ok-c" role="status">Copiado</span></div></div>';
      p.querySelector('#t-i').value = codigoInsertar(T);
      p.querySelector('#t-c').value = textoCita(T);
      var fd = p.querySelector('#f-d');

      function botonEnlace(txt, href, extra, fmt, nuevaPestana) {
        var a = document.createElement('a'); a.className = 'b' + (extra ? ' ' + extra : ''); a.textContent = txt; a.href = href;
        if (nuevaPestana) { a.target = '_blank'; a.rel = 'noopener'; }
        a.addEventListener('click', function () { evento(T, 'propio', 'descarga', { formato: fmt }); });
        fd.appendChild(a); return a;
      }
      // PNG del día: solo si el índice del bloque F tiene entrada para esta herramienta/variante.
      getJSON(T.base + 'capturas/indice.json?v=' + HOY).then(function (ix) {
        var e = ix && ix.capturas && (ix.capturas[clavePng(T)] || ix.capturas[T.id]);
        if (!e || !e.url || !abierto) return;
        var a = botonEnlace('PNG del día', e.url, '', 'png', true);
        fd.insertBefore(a, fd.firstChild);
        // Miniatura de la captura del día encima de los botones (ancho 100 %; si falla la carga, se quita).
        var th = document.createElement('a'); th.href = e.url; th.target = '_blank'; th.rel = 'noopener';
        th.setAttribute('aria-label', 'Abrir la captura del día en tamaño completo');
        th.style.cssText = 'display:block;margin:0 0 10px;border-radius:12px;overflow:hidden;border:1px solid rgba(191,230,255,.16);line-height:0';
        var im = document.createElement('img'); im.src = e.url; im.loading = 'lazy'; im.alt = 'Captura del día: ' + T.titulo;
        im.style.cssText = 'width:100%;height:auto;display:block';
        im.addEventListener('error', function () { th.remove(); });
        th.appendChild(im);
        th.addEventListener('click', function () { evento(T, 'propio', 'descarga', { formato: 'png' }); });
        var sd = p.querySelector('#s-d'); sd.insertBefore(th, sd.querySelector('#f-d'));
      }).catch(function () {});
      if (csv) {
        var bc = document.createElement('button'); bc.type = 'button'; bc.className = 'b s'; bc.textContent = 'CSV';
        bc.addEventListener('click', function () {
          evento(T, 'propio', 'descarga', { formato: 'csv' });
          var bl = new Blob([csv], { type: 'text/csv;charset=utf-8' }), u = URL.createObjectURL(bl), a = document.createElement('a');
          a.href = u; a.download = nombreBase(T) + '-' + T.fecha + '.csv'; p.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(u); }, 4000);
        });
        fd.appendChild(bc);
      }
      if (T.jsonUrl && T.datos) { var aj = botonEnlace('JSON', T.jsonUrl, 's', 'json', false); aj.setAttribute('download', nombreBase(T) + '-' + T.fecha + '.json'); }
      if (!fd.children.length) fd.innerHTML = '<span class="sub" style="margin:0">Datos no disponibles para descarga directa.</span>';

      function copia(texto, okId, acc) {
        var ok = p.querySelector(okId);
        var fin = function () { ok.classList.add('on'); setTimeout(function () { ok.classList.remove('on'); }, 2000); evento(T, 'propio', acc); };
        var fb = function () { var t = document.createElement('textarea'); t.value = texto; p.appendChild(t); t.select(); try { document.execCommand('copy'); } catch (e) {} t.remove(); fin(); };
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(texto).then(fin, fb); else fb();
      }
      p.querySelector('#b-i').addEventListener('click', function () { copia(codigoInsertar(T), '#ok-i', 'insertar'); });
      p.querySelector('#b-c').addEventListener('click', function () { copia(textoCita(T), '#ok-c', 'citar'); });
      p.querySelector('.x').addEventListener('click', cierra);
      sr.appendChild(v); sr.appendChild(p);
      abierto = { v: v, p: p };
      document.addEventListener('keydown', tecla, true);
      p.querySelector('.x').focus();
    }
    pil.addEventListener('click', abre);
  }

  /* ---------- Arranque ---------- */
  function arranca() {
    getJSON(BASE0 + 'reutilizar/herramientas.json?v=' + HOY).then(function (cat) {
      var rel = ruta(), r = casa(cat, rel);
      if (!r) { log('sin entrada en el catálogo para', rel); return; }
      if (r.h.pastilla === false && modo() === 'propio') { log('pastilla desactivada para', r.h.id); return; }
      return resuelve(cat, r).then(function (T) {
        var M = modo();
        log('modo', M, T.id, T.slug || '');
        if (M === 'captura') return pintaCaptura(T);
        if (M === 'embed') { pintaEmbed(T); cargaGtagVista(T); return; }
        if (M === 'externo') { cargaGtagVista(T); return; }
        pintaPropio(T);
      });
    }).catch(function (e) { log('no se pudo iniciar', e && e.message); });
  }
  function cargaGtagVista(T) {
    if (ENCASA || !T.ga4) return;
    cargaGtag(T);
    gtag('event', 'insercion_vista', { herramienta: T.id, pagina_herramienta: T.pagina, sitio_externo: sitioExterno() });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arranca); else arranca();
})();
