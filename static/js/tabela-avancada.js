// Ampliacao Fase 25. TabelaAvancada: cabecalho DENTRO do .tabela-wrap,
// menu sanduiche fixo (Filtro por coluna / Ordenar / Colunas / Exportar CSV /
// Exportar Excel / Linhas por pagina), rodape .oc-pag em grid 3 colunas,
// paginacao client-side, prefs persistidas via /api/preferencia/<prefKey>.
//
// Uso no template:
//   <div class="tabela-wrap" data-tabela data-pref-key="admin_alunos">
//     <div class="tabela-scroll">
//       <table class="tabela"> ... <th data-col-key="nome">Nome</th> ...
//         <tr data-nome="Ana" data-empresa="X" data-busca="Ana X"> ...
//       </table>
//     </div>
//   </div>
//   TabelaAvancada.init(el, {titulo:'Alunos', prefKey:'admin_alunos'})

(function (glb) {
  'use strict';

  var CFG_DEFAULT = {
    linhasPorPagina: [25, 50, 100, 250],
    padraoLinhas: 50,
  };

  function el(tag, attrs, filhos) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'html') e.innerHTML = attrs[k];
      else e.setAttribute(k, attrs[k]);
    }
    (filhos || []).forEach(function (f) { if (f) e.appendChild(f); });
    return e;
  }

  function csrfHeaders() {
    var h = {'Content-Type': 'application/json'};
    if (glb.CSRF_TOKEN) h['X-CSRFToken'] = glb.CSRF_TOKEN;
    return h;
  }

  function carregarPref(chave) {
    return fetch('/api/preferencia/' + encodeURIComponent(chave), {
      credentials: 'same-origin',
    }).then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });
  }

  function salvarPref(chave, v) {
    return fetch('/api/preferencia/' + encodeURIComponent(chave), {
      method: 'POST', credentials: 'same-origin',
      headers: csrfHeaders(), body: JSON.stringify(v || {}),
    }).catch(function () {});
  }

  function TabelaAvancada() {}

  TabelaAvancada.init = function (wrap, opts) {
    opts = opts || {};
    var prefKey = opts.prefKey || wrap.getAttribute('data-pref-key') || 'tabela';
    var titulo = opts.titulo || wrap.getAttribute('data-titulo') || 'Registros';

    var scroll = wrap.querySelector('.tabela-scroll') || wrap;
    var table = scroll.querySelector('table');
    if (!table) return;

    // Cabecalho: injeta DENTRO do wrap, ANTES do scroll.
    var tabelaCab = el('div', {'class': 'tabela-cab'});
    var tabTitulo = el('div', {'class': 'tabela-titulo', text: titulo});
    var tabInfo = el('div', {'class': 'tabela-info'});
    var tabAcoes = el('div', {'class': 'tabela-acoes'});

    var btnMenu = el('button', {
      'type': 'button', 'class': 'btn-tab-menu',
      'aria-label': 'Menu da tabela',
    });
    btnMenu.innerHTML = '<i class="ph ph-list"></i>';

    var menu = el('div', {'class': 'tab-menu', hidden: 'hidden', role: 'menu'});
    function it(label, iconClass, acao) {
      var b = el('button', {'type': 'button', 'class': 'tab-menu-item',
                            'data-acao': acao, role: 'menuitem'});
      b.innerHTML = '<i class="ph ' + iconClass + '"></i>' + label;
      return b;
    }
    function sep() { return el('div', {'class': 'tab-menu-sep'}); }
    menu.appendChild(it('Filtro por coluna', 'ph-funnel', 'filtro-coluna'));
    menu.appendChild(it('Ordenar', 'ph-arrows-down-up', 'ordenar'));
    menu.appendChild(it('Colunas', 'ph-columns', 'colunas'));
    menu.appendChild(sep());
    menu.appendChild(it('Exportar CSV', 'ph-file-csv', 'csv'));
    menu.appendChild(it('Exportar Excel', 'ph-file-xls', 'excel'));
    menu.appendChild(sep());
    menu.appendChild(it('Linhas por pagina', 'ph-list-numbers', 'linhas'));

    var menuWrap = el('div', {'class': 'tab-menu-wrap'});
    menuWrap.appendChild(btnMenu);
    menuWrap.appendChild(menu);
    tabAcoes.appendChild(menuWrap);

    tabelaCab.appendChild(tabTitulo);
    tabelaCab.appendChild(tabInfo);
    tabelaCab.appendChild(tabAcoes);
    wrap.insertBefore(tabelaCab, scroll);

    // Rodape .oc-pag grid 3 colunas
    var rodape = el('div', {'class': 'oc-pag', hidden: 'hidden'});
    var infoPag = el('div', {'class': 'oc-pag-info'});
    var ctrls = el('div', {'class': 'oc-pag-ctrls'});
    var espac = el('div', {'class': 'oc-pag-espac'});
    rodape.appendChild(infoPag);
    rodape.appendChild(ctrls);
    rodape.appendChild(espac);
    wrap.appendChild(rodape);

    var tbody = table.querySelector('tbody');
    var linhas = Array.prototype.slice.call(tbody ? tbody.querySelectorAll('tr') : []);
    var colunas = Array.prototype.slice.call(
      table.querySelectorAll('thead th[data-col-key]')
    ).map(function (th) {
      return {key: th.getAttribute('data-col-key'),
              label: th.textContent.trim(), th: th};
    });

    var estado = {
      pagina: 0,
      porPagina: CFG_DEFAULT.padraoLinhas,
      ocultas: {},
      filtro: '',
      ordena: null,
    };

    function aplicar() {
      var visiveis = linhas.filter(function (tr) {
        if (!estado.filtro) return true;
        var s = (tr.getAttribute('data-busca') || tr.textContent || '')
          .toLowerCase();
        return s.indexOf(estado.filtro.toLowerCase()) >= 0;
      });
      if (estado.ordena) {
        var ck = estado.ordena.col, dir = estado.ordena.dir === 'desc' ? -1 : 1;
        visiveis.sort(function (a, b) {
          var va = (a.getAttribute('data-' + ck) || a.cells[colIndex(ck)]?.textContent || '').toLowerCase();
          var vb = (b.getAttribute('data-' + ck) || b.cells[colIndex(ck)]?.textContent || '').toLowerCase();
          if (va < vb) return -1 * dir;
          if (va > vb) return 1 * dir;
          return 0;
        });
        visiveis.forEach(function (tr) { tbody.appendChild(tr); });
      }
      // Exportação usa ESTA lista (filtrada e ordenada, todas as páginas).
      // tr.hidden não serve: a paginação também esconde linha, e exportava só a página aberta.
      estado.filtradas = visiveis;
      linhas.forEach(function (tr) { tr.hidden = true; });
      var ini = estado.pagina * estado.porPagina;
      visiveis.slice(ini, ini + estado.porPagina).forEach(function (tr) {
        tr.hidden = false;
      });
      colunas.forEach(function (c, idx) {
        var esconde = !!estado.ocultas[c.key];
        c.th.style.display = esconde ? 'none' : '';
        linhas.forEach(function (tr) {
          if (tr.cells[idx]) tr.cells[idx].style.display = esconde ? 'none' : '';
        });
      });
      var total = visiveis.length;
      tabInfo.textContent = total + ' registro' + (total === 1 ? '' : 's');
      if (total > estado.porPagina) {
        rodape.hidden = false;
        infoPag.textContent = 'Mostrando ' + (ini + 1) + ' a '
          + Math.min(ini + estado.porPagina, total) + ' de ' + total;
        renderCtrls(Math.ceil(total / estado.porPagina));
      } else {
        rodape.hidden = true;
      }
    }

    function colIndex(k) {
      for (var i = 0; i < colunas.length; i++) if (colunas[i].key === k) return i;
      return -1;
    }

    function renderCtrls(paginas) {
      ctrls.innerHTML = '';
      function pgBtn(n, label) {
        var b = el('button', {'type': 'button', 'class':
          (n === estado.pagina ? 'oc-pg oc-pg-atual' : 'oc-pg')});
        b.textContent = label || String(n + 1);
        b.addEventListener('click', function () {
          estado.pagina = Math.max(0, Math.min(paginas - 1, n));
          aplicar();
          persistir();
        });
        return b;
      }
      ctrls.appendChild(pgBtn(0, '«'));
      ctrls.appendChild(pgBtn(Math.max(0, estado.pagina - 1), '‹'));
      var start = Math.max(0, estado.pagina - 2);
      var end = Math.min(paginas - 1, estado.pagina + 2);
      for (var i = start; i <= end; i++) ctrls.appendChild(pgBtn(i));
      ctrls.appendChild(pgBtn(Math.min(paginas - 1, estado.pagina + 1), '›'));
      ctrls.appendChild(pgBtn(paginas - 1, '»'));
    }

    function persistir() {
      salvarPref(prefKey, {
        porPagina: estado.porPagina,
        ocultas: estado.ocultas,
        ordena: estado.ordena,
      });
    }

    btnMenu.addEventListener('click', function (e) {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    document.addEventListener('click', function (e) {
      if (!menu.contains(e.target) && e.target !== btnMenu) menu.hidden = true;
    });

    menu.addEventListener('click', function (e) {
      var acao = e.target.closest('[data-acao]');
      if (!acao) return;
      menu.hidden = true;
      var a = acao.getAttribute('data-acao');
      if (a === 'csv') return exportarCsv();
      if (a === 'excel') return exportarExcel();
      if (a === 'filtro-coluna') {
        var s = prompt('Filtrar linhas por texto (todas as colunas):', estado.filtro || '');
        if (s === null) return;
        estado.filtro = s; estado.pagina = 0; aplicar();
      }
      if (a === 'ordenar') {
        var k = prompt('Ordenar por qual coluna? ' +
          colunas.map(function (c) { return c.key; }).join(', '),
          estado.ordena ? estado.ordena.col : '');
        if (!k) return;
        var d = prompt('Direcao (asc/desc)?', estado.ordena ? estado.ordena.dir : 'asc');
        if (colIndex(k) < 0) return;
        estado.ordena = {col: k, dir: (d === 'desc' ? 'desc' : 'asc')};
        aplicar(); persistir();
      }
      if (a === 'colunas') {
        var atual = colunas
          .filter(function (c) { return !estado.ocultas[c.key]; })
          .map(function (c) { return c.key; }).join(',');
        var novo = prompt(
          'Colunas visiveis (separe por virgula):\nDisponiveis: '
            + colunas.map(function (c) { return c.key; }).join(', '),
          atual);
        if (novo === null) return;
        var visi = novo.split(',').map(function (s) { return s.trim(); });
        estado.ocultas = {};
        colunas.forEach(function (c) {
          if (visi.indexOf(c.key) < 0) estado.ocultas[c.key] = true;
        });
        aplicar(); persistir();
      }
      if (a === 'linhas') {
        var n = prompt('Linhas por pagina (25/50/100/250):', estado.porPagina);
        var nn = parseInt(n, 10);
        if (!isNaN(nn) && nn > 0 && nn <= 5000) {
          estado.porPagina = nn; estado.pagina = 0; aplicar(); persistir();
        }
      }
    });

    function exportarCsv() {
      var visKeys = colunas.filter(function (c) { return !estado.ocultas[c.key]; });
      var linhasCsv = [visKeys.map(function (c) { return escCsv(c.label); }).join(',')];
      (estado.filtradas || linhas).forEach(function (tr) {
        var celulas = visKeys.map(function (c) {
          var idx = colIndex(c.key);
          return escCsv(tr.cells[idx] ? tr.cells[idx].textContent.trim() : '');
        });
        linhasCsv.push(celulas.join(','));
      });
      baixar(prefKey + '_' + hoje() + '.csv', linhasCsv.join('\n'),
             'text/csv;charset=utf-8');
    }

    function exportarExcel() {
      // .xls sem CDN: HTML simples que o Excel/LibreOffice abrem.
      var visKeys = colunas.filter(function (c) { return !estado.ocultas[c.key]; });
      var rows = [visKeys.map(function (c) { return '<th>' + esc(c.label) + '</th>'; }).join('')];
      (estado.filtradas || linhas).forEach(function (tr) {
        var cs = visKeys.map(function (c) {
          var idx = colIndex(c.key);
          return '<td>' + esc(tr.cells[idx] ? tr.cells[idx].textContent.trim() : '') + '</td>';
        }).join('');
        rows.push(cs);
      });
      var html = '<html><head><meta charset="UTF-8"></head><body>' +
        '<table><tr>' + rows[0] + '</tr>' +
        rows.slice(1).map(function (r) { return '<tr>' + r + '</tr>'; }).join('') +
        '</table></body></html>';
      baixar(prefKey + '_' + hoje() + '.xls', html,
             'application/vnd.ms-excel');
    }

    function baixar(nome, texto, mime) {
      var blob = new Blob([texto], {type: mime});
      var url = URL.createObjectURL(blob);
      var a = el('a', {href: url, download: nome});
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 0);
    }
    function esc(s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    }
    function escCsv(s) {
      var v = String(s || '');
      if (/[",\n]/.test(v)) v = '"' + v.replace(/"/g, '""') + '"';
      return v;
    }
    function hoje() {
      var d = new Date();
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
        + '-' + String(d.getDate()).padStart(2, '0');
    }

    carregarPref(prefKey).then(function (p) {
      if (p && p.porPagina) estado.porPagina = p.porPagina;
      if (p && p.ocultas) estado.ocultas = p.ocultas;
      if (p && p.ordena) estado.ordena = p.ordena;
      aplicar();
    });
  };

  TabelaAvancada.autoInit = function () {
    document.querySelectorAll('[data-tabela]').forEach(function (wrap) {
      TabelaAvancada.init(wrap);
    });
  };

  glb.TabelaAvancada = TabelaAvancada;
  if (document.readyState !== 'loading') TabelaAvancada.autoInit();
  else document.addEventListener('DOMContentLoaded', TabelaAvancada.autoInit);
})(window);
