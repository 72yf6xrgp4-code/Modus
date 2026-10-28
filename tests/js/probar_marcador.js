// Ejecuta el marcador (boton/marcador.txt) en una pagina local servida como
// si fuera winamax.es y escribe en stdout {alerta, url}. Todas las
// peticiones se interceptan: no sale nada hacia Winamax.
// Uso: node probar_marcador.js <html> <url_simulada> <marcador.txt> [borrar_global]
const fs = require("fs");
const { chromium } = require("playwright");
(async () => {
  const [html, url, marcadorTxt, borrar] = process.argv.slice(2);
  const cuerpo = fs.readFileSync(html, "utf-8");
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.route("**/*", (r) => r.request().url() === url
    ? r.fulfill({ status: 200, contentType: "text/html", body: cuerpo })
    : r.fulfill({ status: 204, body: "" }));
  let alerta = null, abierta = null;
  p.on("dialog", async (d) => { alerta = d.message(); await d.dismiss(); });
  await p.goto(url);
  await p.evaluate((borrar) => {
    window.open = (u) => { window.__abierta = u; return {}; };
    if (borrar === "1") { try { delete window.PRELOADED_STATE; } catch (e) {} window.PRELOADED_STATE = undefined; }
  }, borrar || "0");
  const codigo = decodeURIComponent(fs.readFileSync(marcadorTxt, "utf-8").trim().replace(/^javascript:/, ""));
  await p.evaluate(codigo);
  await p.waitForTimeout(200);
  abierta = await p.evaluate(() => window.__abierta || null);
  process.stdout.write(JSON.stringify({ alerta, url: abierta }));
  await b.close();
})();
