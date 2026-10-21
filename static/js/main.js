/* main.js - sidebar, tema, modais, popup, loading target, genéricos */

/* ── Tema (alternador On/Off) ───────────────────────────────────────────── */
/* Qualquer checkbox com [data-tema-toggle] troca o tema (topbar + home);
   aplicarTema() sincroniza todas, então nunca ficam uma ligada e outra não. */
function aplicarTema(tema) {
  document.documentElement.setAttribute("data-theme", tema);
  document.body && document.body.setAttribute("data-theme", tema);
  try { localStorage.setItem("tema", tema); } catch (e) {}
  document.querySelectorAll("[data-tema-toggle]").forEach(function (cb) {
    cb.checked = tema === "dark";
  });
}
(function initTema() {
  var salvo = null;
  try { salvo = localStorage.getItem("tema"); } catch (e) {}
  aplicarTema(salvo === "dark" ? "dark" : "light");
})();
document.addEventListener("change", function (e) {
  var t = e.target;
  if (t && t.matches && t.matches("[data-tema-toggle]")) {
    aplicarTema(t.checked ? "dark" : "light");
  }
});

/* ── Sidebar: abrir/fechar (mobile) e redimensionar (desktop) ───────────── */
(function initSidebar() {
  var sidebar = document.getElementById("sidebar");
  var resize = document.getElementById("sidebarResize");
  var menuBtn = document.getElementById("menuBtn");

  if (menuBtn && sidebar) {
    menuBtn.addEventListener("click", function () {
      var aberta = sidebar.classList.toggle("aberta");
      var ov = document.getElementById("sidebarOverlay");
      if (ov) ov.classList.toggle("visivel", aberta);
      menuBtn.setAttribute("aria-expanded", aberta ? "true" : "false");
    });
    var ov = document.getElementById("sidebarOverlay");
    if (ov) ov.addEventListener("click", function () {
      sidebar.classList.remove("aberta");
      ov.classList.remove("visivel");
      menuBtn.setAttribute("aria-expanded", "false");
    });
  }

  if (!resize || !sidebar) return;

  // Largura salva
  try {
    var w = parseInt(localStorage.getItem("sidebar_width"), 10);
    if (w && w >= 200 && w <= 480) setLargura(w);
  } catch (e) {}

  function setLargura(w) {
    document.documentElement.style.setProperty("--sidebar-width", w + "px");
  }

  var arrastando = false;
  resize.addEventListener("mousedown", function (e) {
    arrastando = true;
    resize.classList.add("arrastando");
    document.body.classList.add("sidebar-arrastando");
    e.preventDefault();
  });
  document.addEventListener("mousemove", function (e) {
    if (!arrastando) return;
    var w = Math.min(480, Math.max(200, e.clientX));
    setLargura(w);
  });
  document.addEventListener("mouseup", function () {
    if (!arrastando) return;
    arrastando = false;
    resize.classList.remove("arrastando");
    document.body.classList.remove("sidebar-arrastando");
    var w = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width"), 10);
    try { localStorage.setItem("sidebar_width", w); } catch (e) {}
  });
})();

/* ── Grupos da sidebar (acordeão) ───────────────────────────────────────── */
document.addEventListener("click", function (e) {
  var cab = e.target.closest(".grupo-cab, .sub-grupo-cab");
  if (cab) {
    var grupo = cab.closest(".grupo, .sub-grupo");
    if (grupo) {
      var aberto = grupo.classList.toggle("aberto");
      if (cab.classList.contains("grupo-cab") || cab.classList.contains("sub-grupo-cab")) {
        cab.setAttribute("aria-expanded", aberto ? "true" : "false");
      }
    }
  }
});

/* ── Modal genérico ─────────────────────────────────────────────────────── */
function abrirModal(id) {
  var m = document.getElementById(id);
  if (m) { m.classList.add("aberto"); document.body.style.overflow = "hidden"; }
}
function fecharModal(id) {
  var m = document.getElementById(id);
  if (m) { m.classList.remove("aberto"); document.body.style.overflow = ""; }
}
/* Padrao_Modal (30/07/2026): ESC não fecha modal e backdrop não fecha modal.
   O modal só sai pelo botão X ou por Cancelar ([data-fechar-modal]). */
document.addEventListener("click", function (e) {
  if (e.target.closest && e.target.closest("[data-fechar-modal]")) {
    var ov = e.target.closest(".modal-overlay");
    if (ov) { ov.classList.remove("aberto"); document.body.style.overflow = ""; }
  }
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") return;                      // ESC não fecha modal
});

/* ── Popup de confirmação (promise) ─────────────────────────────────────── */
function confirmarPopup(titulo, texto, textoOk) {
  return new Promise(function (resolve) {
    var ov = document.getElementById("popupOverlay");
    if (!ov) { resolve(window.confirm(titulo + "\n" + texto)); return; }
    ov.querySelector(".popup h3").textContent = titulo || "Confirmar";
    ov.querySelector(".popup p").textContent = texto || "";
    var btnOk = ov.querySelector("[data-popup-ok]");
    if (textoOk) btnOk.textContent = textoOk;
    ov.classList.add("aberto");
    function limpar() {
      ov.classList.remove("aberto");
      btnOk.removeEventListener("click", ok);
      ov.querySelector("[data-popup-cancelar]").removeEventListener("click", nao);
      ov.removeEventListener("click", fora);
    }
    function ok() { limpar(); resolve(true); }
    function nao() { limpar(); resolve(false); }
    function fora(e) { if (e.target === ov) nao(); }
    btnOk.addEventListener("click", ok);
    ov.querySelector("[data-popup-cancelar]").addEventListener("click", nao);
    ov.addEventListener("click", fora);
  });
}

/* ── Confirmação destrutiva (Padrao_Modal: .modal-sm.modal-confirm) ─────────
   Promessa como confirmarPopup, porém o modal NÃO fecha com ESC nem com
   clique no backdrop: só pelo X, Cancelar ou Confirmar (30/07/2026). */
function confirmarDestrutivo(titulo, texto, textoOk) {
  return new Promise(function (resolve) {
    var ov = document.getElementById("modalConfirm");
    if (!ov) { resolve(window.confirm((titulo || "Confirmar") + "\n" + (texto || ""))); return; }
    var btnOk = document.getElementById("modalConfirmOk");
    var btnCancelar = document.getElementById("modalConfirmCancelar");
    var btnFechar = document.getElementById("modalConfirmFechar");
    document.getElementById("modalConfirmTitulo").textContent = titulo || "Confirmar";
    document.getElementById("modalConfirmTexto").textContent = texto || "";
    btnOk.textContent = textoOk || "Confirmar";
    function limpar() {
      btnOk.removeEventListener("click", ok);
      btnCancelar.removeEventListener("click", nao);
      btnFechar.removeEventListener("click", nao);
    }
    function fim(resultado) { limpar(); fecharModal("modalConfirm"); resolve(resultado); }
    function ok() { fim(true); }
    function nao() { fim(false); }
    btnOk.addEventListener("click", ok);
    btnCancelar.addEventListener("click", nao);
    btnFechar.addEventListener("click", nao);
    abrirModal("modalConfirm");
    btnOk.focus();
  });
}

/* ── Loading em target (form/botão) ─────────────────────────────────────── */
function loadingOn(el) {
  if (!el) return;
  el.classList.add("loading-target");
  el.setAttribute("disabled", "disabled");
}
function loadingOff(el) {
  if (!el) return;
  el.classList.remove("loading-target");
  el.removeAttribute("disabled");
}

/* ── Submissão de form com loading ──────────────────────────────────────── */
document.addEventListener("submit", function (e) {
  var form = e.target;
  if (form.tagName !== "FORM" || form.dataset.noloading !== undefined) return;
  if (!form.checkValidity || !form.checkValidity()) return;
  var botao = e.submitter || form.querySelector("button[type=submit]");
  // O loading desabilita o botão, e controle desabilitado NÃO vai no corpo do
  // POST. Form que carrega a intenção no name/value do botão (ex. o público da
  // OS, que manda decisao=aprovar/recusar) perdia o dado e o backend abortava
  // 400. Clonamos num hidden antes de desabilitar.
  if (e.submitter && e.submitter.name && e.submitter.type === "submit") {
    var clonado = document.createElement("input");
    clonado.type = "hidden";
    clonado.name = e.submitter.name;
    clonado.value = e.submitter.value;
    form.appendChild(clonado);
  }
  loadingOn(botao || form);
});

/* ── CSRF: injeta token em todos os POST via fetch ──────────────────────── */
var CSRF_TOKEN = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
document.addEventListener("submit", function (e) {
  var form = e.target;
  if (form.tagName !== "FORM" || form.method.toUpperCase() !== "POST") return;
  if (form.querySelector('input[name="csrf_token"]')) return;
  var inp = document.createElement("input");
  inp.type = "hidden";
  inp.name = "csrf_token";
  inp.value = CSRF_TOKEN;
  form.appendChild(inp);
});

/* ── Máscaras simples (CPF/CNPJ, telefone, moeda) ───────────────────────── */
function mascara(el, tipo) {
  var v = (el.value || "").replace(/\D/g, "");
  if (tipo === "cpf") {
    v = v.slice(0, 11);
    el.value = v.replace(/(\d{3})(\d)/, "$1.$2")
      .replace(/(\d{3})(\d)/, "$1.$2")
      .replace(/(\d{3})(\d{1,2})$/, "$1-$2");
  } else if (tipo === "cnpj") {
    v = v.slice(0, 14);
    el.value = v.replace(/(\d{2})(\d)/, "$1.$2")
      .replace(/(\d{3})(\d)/, "$1.$2")
      .replace(/(\d{3})(\d)/, "$1/$2")
      .replace(/(\d{4})(\d{1,2})$/, "$1-$2");
  } else if (tipo === "telefone") {
    v = v.slice(0, 11);
    el.value = v.replace(/(\d{2})(\d)/, "($1) $2")
      .replace(/(\d{5})(\d)/, "$1-$2");
  }
}
document.addEventListener("input", function (e) {
  var el = e.target;
  if (el.dataset && el.dataset.mascara) mascara(el, el.dataset.mascara);
});

// ── Ações sem handler inline ─────────────────────────────────────────────────
// A CSP não aceita onclick= no HTML (sem 'unsafe-inline'). O elemento diz o que
// faz por data-* e este delegador chama a função global:
//   data-clique="fn"                  -> fn()
//   data-clique="fn" data-arg="x"     -> fn("x")   (só dígitos vira número: ids)
//   data-clique="fn" data-com-el      -> fn(elemento)
//   data-vai="/url"                   -> navega
//   data-digita="fn"                  -> fn(elemento) a cada digitação
// (data-acao é do tabela-avancada.js; por isso o nome é outro)
document.addEventListener("click", function (e) {
  var el = e.target.closest("[data-clique],[data-vai]");
  if (!el || el.disabled) return;
  if (el.dataset.vai) { window.location.href = el.dataset.vai; return; }
  var fn = window[el.dataset.clique];
  if (typeof fn !== "function") { console.warn("data-clique sem função:", el.dataset.clique); return; }
  if ("comEl" in el.dataset) return fn(el);
  if ("arg" in el.dataset) {
    var a = el.dataset.arg;
    return fn(/^\d+$/.test(a) ? Number(a) : a);
  }
  return fn();
});
document.addEventListener("input", function (e) {
  var el = e.target;
  if (!el.dataset || !el.dataset.digita) return;
  var fn = window[el.dataset.digita];
  if (typeof fn === "function") fn(el);
});