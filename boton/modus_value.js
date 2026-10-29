/*
 * Boton "Modus value" (marcador del navegador).
 *
 * Se pulsa a mano con un partido de Modus abierto en la web de Winamax. Lee
 * SOLO las cuotas que ya estan en esa pagina y abre la app (Value Bets) con
 * el partido y las cuotas. No hace ninguna peticion a Winamax, no inicia
 * sesion, no toca el boleto y no apuesta. Si no encuentra las cuotas lo dice
 * y no envia nada.
 *
 * De donde salen las cuotas:
 *  1) Los botones de cuota que se ven en pantalla (data-testid
 *     "odd-button-<id>" dentro de cada mercado "match-group-<partido>-<id>").
 *     Estan siempre al dia, tambien si has llegado al partido navegando
 *     dentro de Winamax (sin recargar).
 *  2) El estado que la pagina trae al cargarse (PRELOADED_STATE): sirve para
 *     completar los mercados que no se ven (la lista solo pinta los que
 *     estan cerca de la pantalla), pero SOLO si es de este mismo partido y
 *     la pagina se cargo en este partido. Si llegaste navegando dentro de
 *     Winamax, ese estado es de la pagina anterior y sus cuotas son viejas:
 *     solo se usa lo que se ve.
 *
 * Manda tambien su VERSION: si la app tiene una mas nueva, te avisa de que
 * reinstales el marcador (el marcador guarda una copia del codigo y no se
 * actualiza solo).
 *
 * Este archivo es la fuente legible. El marcador que se instala es
 * boton/marcador.txt (generado con: python boton/construir.py).
 */
(function () {
  var APP = "https://modusapp.streamlit.app/";
  var VERSION = 3;

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

  /* Mercados del partido que se ven en pantalla:
     {matchId, mercados: {betId: {titulo, salidas: {outcomeId: [label, cuota]}}}} */
  function leerPantalla(idUrl) {
    var res = { matchId: idUrl, mercados: {}, n: 0 };
    var grupos = document.querySelectorAll(".bet-group-template");
    for (var i = 0; i < grupos.length; i++) {
      var g = grupos[i];
      var botones = g.querySelectorAll('[data-testid^="odd-button-"]');
      var ids = {}, salidas = {}, ns = 0;
      for (var j = 0; j < botones.length; j++) {
        var oid = botones[j].getAttribute("data-testid").replace("odd-button-", "");
        ids[oid] = 1;
        var v = botones[j].querySelector(".odd-button-value");
        if (!v) continue;
        var c = cuota(String(v.innerText || v.textContent || "").replace(",", "."));
        var cont = v.parentElement && v.parentElement.previousElementSibling;
        var label = cont ? (cont.innerText || cont.textContent || "").trim() : "";
        if (c && label) { salidas[oid] = [label, c]; ns++; }
      }
      /* La marca del mercado es match-group-<partido>-<apuesta>; las de
         cada salida llevan el id de la salida y se ignoran */
      var anclas = g.querySelectorAll('[data-anchorid^="match-group-"]'), mid = null, bid = null;
      for (var k = 0; k < anclas.length; k++) {
        var partes = anclas[k].getAttribute("data-anchorid").split("-");
        if (partes[2] && partes[3] && !ids[partes[3]]) { mid = partes[2]; bid = partes[3]; break; }
      }
      if (!mid || !ns) continue;
      if (res.matchId && mid !== String(res.matchId)) continue;
      res.matchId = mid;
      /* Titulo: subiendo desde el bloque, el primer hermano anterior que no
         tiene cuotas */
      var el = g, titulo = "";
      while (el && el.parentElement && !titulo) {
        var padre = el.parentElement, primero = padre.firstElementChild;
        if (primero && primero !== el && !primero.querySelector('[data-testid^="odd-button-"]')) {
          titulo = (primero.innerText || primero.textContent || "").trim().split("\n")[0];
        }
        el = padre;
      }
      if (!titulo) continue;
      var previo = res.mercados[bid];
      if (previo) { for (var o in salidas) previo.salidas[o] = salidas[o]; }
      else res.mercados[bid] = { titulo: titulo, salidas: salidas };
      res.n += ns;
    }
    return res;
  }

  /* Nombres de los jugadores desde el titulo de la pestana:
     "Derek Coulson - Andy Baetens | MODUS Super Series | ..." */
  function nombresDelTitulo() {
    var t = String(document.title || "").split("|")[0].split(" - ");
    return t.length === 2 ? [t[0].trim(), t[1].trim()] : null;
  }

  /* ¿Se cargo la pagina en otra direccion y has llegado aqui navegando?
     Y cuantos segundos hace que se cargo. */
  function carga() {
    var r = { navegada: false, edad: 0 };
    try {
      var nav = performance.getEntriesByType("navigation")[0];
      if (nav && nav.name) {
        var a = document.createElement("a");
        a.href = nav.name;
        r.navegada = a.pathname !== location.pathname;
      }
      r.edad = Math.round(performance.now() / 1000);
    } catch (e) {}
    return r;
  }

  try {
    var cg = carga();
    var m = location.pathname.match(/\/match\/(\d+)/);
    var idUrl = m ? m[1] : null;
    var pant = leerPantalla(idUrl);
    var idPartido = idUrl || pant.matchId;
    var dato = buscarPartido(window.PRELOADED_STATE, idPartido) ||
               buscarPartido(estadoDeScripts(), idPartido);
    if (dato && pant.matchId && dato.id !== String(pant.matchId)) dato = null;  /* otro partido */

    var mercados = [], vistos = {}, fuente, enPantalla = [], nEstado = 0;
    /* Llegaste navegando y se ven cuotas: el estado es de la pagina
       anterior; de el solo se usan los nombres y la hora */
    var usarEstado = dato && !(cg.navegada && pant.n);
    if (usarEstado) {
      /* Estructura del estado; cuotas de la pantalla cuando se ven (al dia) */
      var st = dato.st, p = dato.p, bets = lista(p.bets);
      for (var i = 0; i < bets.length; i++) {
        var b = st.bets && st.bets[bets[i]];
        if (!b || b.available === false) continue;
        var enPant = pant.mercados[String(bets[i])];
        var sal = [], outs = lista(b.outcomes);
        for (var j = 0; j < outs.length; j++) {
          var o = st.outcomes && st.outcomes[outs[j]];
          var vp = enPant && enPant.salidas[String(outs[j])];
          var c = vp ? vp[1] : cuota(st.odds && st.odds[outs[j]]);
          if (o && c) sal.push([String(o.label || ""), String(o.code || ""), c]);
        }
        if (sal.length) {
          mercados.push([String(b.betTitle || ""), sal]);
          if (!enPant) nEstado++;
        }
        vistos[String(bets[i])] = 1;
      }
      fuente = "pagina";
    }
    /* Mercados que solo estan en pantalla (llegaste navegando, o Winamax
       los ha publicado despues de cargar la pagina). Van PRIMERO: si el
       mismo mercado sale dos veces, la app se queda con el primero, y estos
       son los mas recientes. */
    for (var bid in pant.mercados) {
      if (vistos[bid]) continue;
      var mp = pant.mercados[bid], sp = [];
      for (var oid in mp.salidas) sp.push([mp.salidas[oid][0], "", mp.salidas[oid][1]]);
      enPantalla.push([mp.titulo, sp]);
    }
    mercados = enPantalla.concat(mercados);
    if (!usarEstado) fuente = "pantalla";

    var nombres = dato ? [dato.p.competitor1Name, dato.p.competitor2Name] : nombresDelTitulo();
    if (!mercados.length || !nombres || !nombres[0] || !nombres[1]) {
      return aviso("no encuentro las cuotas de un partido en esta página. " +
                   "Abre el partido en Winamax y espera a que se vean las cuotas. " +
                   "No se ha enviado nada.");
    }
    var datos = {
      v: 1, id: String(idPartido || ""),
      c1: String(nombres[0]), c2: String(nombres[1]),
      t: dato ? (dato.p.matchStart || 0) : 0, s: dato ? String(dato.p.status || "") : "",
      h: Math.round(Date.now() / 1000), f: fuente, m: mercados,
      b: VERSION, e: cg.edad, ne: nEstado
    };
    var b64 = btoa(unescape(encodeURIComponent(JSON.stringify(datos))))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    var url = APP + "?seccion=value&wm=" + b64;
    /* Siempre la misma pestana de Modus (la primera vez la abre; despues
       carga el partido nuevo en ella) */
    var w = window.open(url, "modus_app");
    if (!w) location.href = url;
  } catch (e) {
    aviso("error leyendo la página (" + e.message + "). No se ha enviado nada.");
  }
})();
