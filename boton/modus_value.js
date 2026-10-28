/*
 * Boton "Modus value" (marcador del navegador).
 *
 * Se pulsa a mano con un partido de Modus abierto en la web de Winamax. Lee
 * SOLO las cuotas que ya estan en esa pagina (el estado PRELOADED_STATE que
 * la propia pagina trae) y abre la app (Value Bets) con el partido y las
 * cuotas. No hace ninguna peticion a Winamax, no inicia sesion, no toca el
 * boleto y no apuesta. Si no encuentra las cuotas lo dice y no envia nada.
 *
 * Este archivo es la fuente legible. El marcador que se instala es
 * boton/marcador.txt (generado con: python boton/construir.py).
 */
(function () {
  var APP = "https://modusapp.streamlit.app/";

  function aviso(msg) {
    alert("Modus value: " + msg);
  }

  /* Estado de la pagina sacado del <script> (por si la pagina ya no
     tiene la variable global, p. ej. una pagina guardada con Ctrl+S). */
  function estadoDeScripts() {
    var ss = document.getElementsByTagName("script");
    for (var i = 0; i < ss.length; i++) {
      var t = ss[i].textContent || "";
      var k = t.indexOf("PRELOADED_STATE");
      if (k < 0) continue;
      var a = t.indexOf("{", k);
      if (a < 0) continue;
      var prof = 0, enCad = false, esc = false;
      for (var j = a; j < t.length; j++) {
        var c = t.charAt(j);
        if (enCad) {
          if (esc) esc = false;
          else if (c === "\\") esc = true;
          else if (c === "\"") enCad = false;
          continue;
        }
        if (c === "\"") enCad = true;
        else if (c === "{") prof++;
        else if (c === "}") {
          prof--;
          if (prof === 0) {
            try { return JSON.parse(t.slice(a, j + 1)); } catch (e) { break; }
          }
        }
      }
    }
    return null;
  }

  function cuota(v) {
    if (v && typeof v === "object") v = v.odds != null ? v.odds : v.value;
    v = parseFloat(v);
    return v > 1 ? v : null;
  }

  function lista(v) {
    return Object.prototype.toString.call(v) === "[object Array]" ? v : [];
  }

  /* Partido de la pagina: el de la URL (/match/123) o, si no la hay, el
     unico partido del estado que tenga apuestas. */
  function buscarPartido(st, idUrl) {
    if (!st || typeof st !== "object" || !st.matches) return null;
    var id = idUrl;
    if (!id) {
      var conApuestas = [];
      for (var k in st.matches) {
        if (st.matches[k] && lista(st.matches[k].bets).length) conApuestas.push(k);
      }
      if (conApuestas.length === 1) id = conApuestas[0];
    }
    var p = id && st.matches[id];
    return p && lista(p.bets).length ? { st: st, p: p, id: String(id) } : null;
  }

  try {
    var m = location.pathname.match(/\/match\/(\d+)/);
    var idUrl = m ? m[1] : null;
    var dato = buscarPartido(window.PRELOADED_STATE, idUrl) ||
               buscarPartido(estadoDeScripts(), idUrl);
    if (!dato) {
      return aviso("no encuentro las cuotas de un partido en esta página. " +
                   "Abre la página del partido en Winamax, recárgala y vuelve a pulsar. " +
                   "No se ha enviado nada.");
    }
    var st = dato.st, p = dato.p, mercados = [];
    var bets = lista(p.bets);
    for (var i = 0; i < bets.length; i++) {
      var b = st.bets && st.bets[bets[i]];
      if (!b || b.available === false) continue;
      var sal = [], outs = lista(b.outcomes);
      for (var j = 0; j < outs.length; j++) {
        var o = st.outcomes && st.outcomes[outs[j]];
        var c = cuota(st.odds && st.odds[outs[j]]);
        if (o && c) sal.push([String(o.label || ""), String(o.code || ""), c]);
      }
      if (sal.length) mercados.push([String(b.betTitle || ""), sal]);
    }
    if (!mercados.length || !p.competitor1Name || !p.competitor2Name) {
      return aviso("he encontrado el partido pero ninguna cuota. " +
                   "Puede que Winamax haya cambiado su página o que los mercados estén cerrados. " +
                   "No se ha enviado nada.");
    }
    var datos = {
      v: 1, id: dato.id,
      c1: String(p.competitor1Name), c2: String(p.competitor2Name),
      t: p.matchStart || 0, s: String(p.status || ""),
      h: Math.round(Date.now() / 1000), m: mercados
    };
    var b64 = btoa(unescape(encodeURIComponent(JSON.stringify(datos))))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    var url = APP + "?seccion=value&wm=" + b64;
    var w = window.open(url, "_blank");
    if (!w) location.href = url;
  } catch (e) {
    aviso("error leyendo la página (" + e.message + "). No se ha enviado nada.");
  }
})();
