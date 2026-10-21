/* selectbusca.js - SelectBusca: input com busca + dropdown
   Padrão literal da vault: .selectbusca > input.sb-input + i.sb-seta + div.sb-lista
   Itens vêm de data-opcoes (JSON) ou de URL (data-src, busca no servidor). */

(function () {
  "use strict";

  function Normalizar(s) {
    return (s || "").toString().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }

  function criar(sb) {
    if (sb.dataset.init === "1") return;
    sb.dataset.init = "1";

    var input = sb.querySelector(".sb-input");
    var lista = sb.querySelector(".sb-lista");
    var valor = sb.querySelector("input[type=hidden]");
    if (!input || !lista) return;

    var opcoes = [];
    try { opcoes = JSON.parse(sb.dataset.opcoes || "[]"); } catch (e) { opcoes = []; }
    var src = sb.dataset.src || "";
    var minChars = parseInt(sb.dataset.minChars || "1", 10);
    var buscaServidor = false;
    var timer = null;

    function render(itens) {
      lista.innerHTML = "";
      if (!itens.length) {
        var vazio = document.createElement("div");
        vazio.className = "sb-vazio";
        vazio.textContent = "Nada encontrado";
        lista.appendChild(vazio);
        return;
      }
      itens.forEach(function (it) {
        var d = document.createElement("div");
        d.className = "sb-item";
        d.dataset.valor = it.valor;
        d.innerHTML = '<div class="principal"></div>';
        d.querySelector(".principal").textContent = it.rotulo;
        if (it.sub) {
          var s = document.createElement("div");
          s.className = "sub";
          s.textContent = it.sub;
          d.appendChild(s);
        }
        d.addEventListener("mousedown", function (e) {
          e.preventDefault();
          selecionar(it);
        });
        lista.appendChild(d);
      });
    }

    function selecionar(it) {
      input.value = it.rotulo;
      if (valor) valor.value = it.valor;
      fechar();
      sb.dispatchEvent(new CustomEvent("sb:selecionado", { detail: it, bubbles: true }));
    }

    function filtrarLocal(q) {
      if (!q) return opcoes;
      var nq = Normalizar(q);
      return opcoes.filter(function (it) {
        return Normalizar(it.rotulo).indexOf(nq) !== -1 ||
               Normalizar(it.sub || "").indexOf(nq) !== -1;
      });
    }

    function buscarServidor(q) {
      if (!src) return;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fetch(src + (src.indexOf("?") === -1 ? "?" : "&") + "q=" + encodeURIComponent(q), {
          headers: { "Accept": "application/json" }
        })
          .then(function (r) { return r.json(); })
          .then(function (dados) {
            buscaServidor = true;
            render(dados.itens || dados || []);
            abrir();
          })
          .catch(function () {});
      }, 220);
    }

    function abrir() { sb.classList.add("aberto"); }
    function fechar() { sb.classList.remove("aberto"); }

    input.addEventListener("focus", function () {
      // Abrir mostra TODAS as opções (como o componente da base: filtrar("")).
      // Filtrar pelo rótulo já escolhido escondia as outras: com "Todos" no
      // campo, a lista abria só com "Todos". O texto fica selecionado pra que
      // digitar substitua a escolha.
      if (src) {
        render([]);
        buscarServidor(input.value);
      } else {
        render(opcoes);
        abrir();
      }
      if (input.select) input.select();
    });

    input.addEventListener("input", function () {
      if (valor) valor.value = "";  // digitar invalida seleção anterior
      if (src) {
        if (input.value.length >= minChars) buscarServidor(input.value);
      } else {
        render(filtrarLocal(input.value));
        abrir();
      }
    });

    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") fechar();
      if (e.key === "ArrowDown") {
        e.preventDefault();
        var primeiro = lista.querySelector(".sb-item");
        if (primeiro) primeiro.scrollIntoView({ block: "nearest" });
      }
      if (e.key === "Enter" && sb.classList.contains("aberto")) {
        var sel = lista.querySelector(".sb-item");
        if (sel) {
          e.preventDefault();
          sel.dispatchEvent(new MouseEvent("mousedown"));
        }
      }
    });

    document.addEventListener("click", function (e) {
      if (!sb.contains(e.target)) fechar();
    });
  }

  function init() {
    document.querySelectorAll(".selectbusca").forEach(criar);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  // Re-inicializa quando Jinja injeta HTML via innerHTML
  window.SelectBuscaInit = init;
})();
