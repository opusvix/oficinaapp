/* service-worker.js - OficinaApp (Padrao_PWA_Notificacoes)
   Servido pela RAIZ (/service-worker.js, core/pwa.py) pra controlar o app todo.

   O que guarda: só arquivo estático (CSS, JS, fontes, ícones) e a página /offline.
   O que NUNCA guarda: tela com dado (OS, cliente, caixa), POST, /static/uploads
   (foto de equipamento de cliente). Celular de técnico troca de mão e o cache do
   navegador não some no logout.

   Estáticos: rede primeiro (deploy novo aparece na hora), cache se estiver sem rede.
   Telas: sempre rede; sem rede, mostra /offline. */

var CACHE = "oficina-v3";            // = core/pwa.py VERSAO_SW
var PRECACHE = [
  "/offline",
  "/static/css/tokens.css",
  "/static/css/base.css",
  "/static/css/layout.css",
  "/static/css/components.css",
  "/static/fonts/fonts.css",
  "/static/fonts/Inter-var-latin.woff2",
  "/static/fonts/Sora-var-latin.woff2",
  "/static/fonts/phosphor/style.css",
  "/static/fonts/phosphor/Phosphor.woff2",
  "/static/js/main.js",
  "/static/js/selectbusca.js",
  "/static/favicon.png",
  "/static/icons/icon-192.png"
];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) { return c.addAll(PRECACHE); }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (nomes) {
      return Promise.all(nomes.filter(function (n) { return n !== CACHE; }).map(function (n) { return caches.delete(n); }));
    }).then(function () { return self.clients.claim(); })
  );
});

function estaticoGuardavel(url) {
  return url.pathname.indexOf("/static/") === 0 && url.pathname.indexOf("/static/uploads/") !== 0;
}

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;                       // POST nunca passa pelo cache
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    // Tela: rede sempre. Uma navegação pode falhar por UMA conexão recusada (servidor
    // local sob várias requisições ao mesmo tempo); tenta DE NOVO antes de desistir.
    // Só mostra /offline quando realmente não dá — nunca uma tela antiga com dado.
    e.respondWith(
      fetch(req).catch(function () {
        return fetch(req).catch(function () { return caches.match("/offline"); });
      })
    );
    return;
  }

  if (estaticoGuardavel(url)) {
    e.respondWith(
      fetch(req).then(function (resp) {
        if (resp.ok) {
          var copia = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copia); });
        }
        return resp;
      }).catch(function () {
        return caches.match(req, { ignoreSearch: true });
      })
    );
  }
  // resto (API, upload, manifest): segue direto pra rede, sem cache
});
