/* pwa.js - registra o service worker servido da RAIZ (core/pwa.py).
   Incluído só no layout logado (base.html). */
(function () {
  "use strict";
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(function (err) {
      // Sem SW o app funciona igual, só não instala nem mostra a tela offline
      if (window.console) console.warn("[PWA] service worker não registrou:", err);
    });
  });
})();
