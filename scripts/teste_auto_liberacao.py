"""Prova da auto-liberação por grupo (Auto_Liberacao_por_Grupo).

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_auto_liberacao.py
Sai com código 1 se algum caso falhar.
"""
import os
import re
import sys
import tempfile

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bcrypt  # noqa: E402
from app import create_app  # noqa: E402
from core.auth import aplicar_auto_liberacoes  # noqa: E402

app = create_app()
falhas = []


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


def sql(q, p=()):
    with app.app_context():
        from core.db import get_db
        db = get_db()
        r = db.execute(q, p).fetchall()
        db.commit()
        return r


def perm(id_perfil, id_modulo):
    r = sql("SELECT pode_ver, pode_editar FROM permissoes WHERE id_perfil = ? AND id_modulo = ?",
            (id_perfil, id_modulo))
    return (r[0][0], r[0][1]) if r else None


# ── 1. Seed: Admin auto-libera todo grupo existente ─────────────────────────
grupos = {r[0] for r in sql("SELECT DISTINCT COALESCE(grupo,'Outros') FROM modulo WHERE D_E_L_E_T = 0")}
regras_admin = {r[0] for r in sql("SELECT grupo FROM perfis_grupos_auto WHERE id_perfil = 1 AND auto_ver = 1")}
chk("Admin tem regra de auto-liberar em todos os grupos (seed)", grupos <= regras_admin, grupos - regras_admin)
chk("técnico (perfil 2) não tem auto-liberação por padrão",
    len(sql("SELECT 1 FROM perfis_grupos_auto WHERE id_perfil = 2 AND (auto_ver = 1 OR auto_editar = 1)")) == 0)

# ── 2. Módulo NOVO num grupo do admin nasce liberado no boot ────────────────
nid = sql("INSERT INTO modulo (chave, nome, grupo, icone, rota, ordem, em_breve) "
          "VALUES ('relatorio_z', 'Relatório Z', 'Relatórios', 'ph-chart-pie', '/relatorios/z', 99, 0) RETURNING id")[0][0]
chk("antes de aplicar, o módulo novo não tem permissão nenhuma", perm(1, nid) is None)
with app.app_context():
    aplicar_auto_liberacoes()
chk("depois do boot, Admin já VÊ e EDITA o módulo novo (grupo Relatórios auto)", perm(1, nid) == (1, 1), perm(1, nid))
chk("o técnico (sem auto) continua sem o módulo novo", perm(2, nid) is None)

# idempotente: rodar de novo não duplica nem muda
with app.app_context():
    aplicar_auto_liberacoes()
chk("aplicar de novo é idempotente (uma linha só)",
    len(sql("SELECT 1 FROM permissoes WHERE id_perfil = 1 AND id_modulo = ?", (nid,))) == 1)

# ── 3. Respeita decisão manual: não reabre o que foi fechado ────────────────
# admin fecha o módulo novo de propósito (linha 0/0, como o UPSERT da matriz faz)
sql("UPDATE permissoes SET pode_ver = 0, pode_editar = 0 WHERE id_perfil = 1 AND id_modulo = ?", (nid,))
with app.app_context():
    aplicar_auto_liberacoes()
chk("módulo fechado à mão (0/0) NÃO é reaberto pela auto-liberação", perm(1, nid) == (0, 0), perm(1, nid))

# ── 4. Grupo novo entra no seed do admin no próximo boot ────────────────────
sql("INSERT INTO modulo (chave, nome, grupo, icone, rota, ordem, em_breve) "
    "VALUES ('cftv', 'CFTV', 'Monitoramento', 'ph-video-camera', '/cftv', 10, 0)")
# o seed (admin auto em todo grupo) roda a cada boot: recria o app pra simular reboot
app2 = create_app()
with app2.app_context():
    from core.db import get_db
    tem = get_db().execute("SELECT auto_ver FROM perfis_grupos_auto WHERE id_perfil = 1 AND grupo = 'Monitoramento'").fetchone()
    cftv = get_db().execute("SELECT id FROM modulo WHERE chave = 'cftv'").fetchone()[0]
    cftv_perm = get_db().execute("SELECT pode_ver, pode_editar FROM permissoes WHERE id_perfil = 1 AND id_modulo = ?", (cftv,)).fetchone()
chk("grupo novo (Monitoramento) ganha regra de auto do Admin no reboot", tem is not None and tem[0] == 1)
chk("e o módulo desse grupo novo já nasce liberado pro Admin", tuple(cftv_perm) == (1, 1) if cftv_perm else False, cftv_perm)

# ── 5. Tela de permissões: toggles por grupo salvam e aplicam ───────────────
sql("UPDATE usuario SET precisa_trocar_senha = 0")
h = bcrypt.hashpw(b"SenhaTecnico2026", bcrypt.gensalt()).decode()
sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
    "VALUES ('Tec', 'tec@teste.local', ?, 2, 0)", (h,))
adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
TK = re.search(rb'name="csrf-token" content="([^"]+)"', adm.get("/admin/perfis").data).group(1).decode()

html = adm.get("/admin/perfis/2/permissoes").data.decode()
chk("tela de permissões mostra os toggles de auto por grupo", 'name="autover_0"' in html and "auto-liberação" in html)

# ordem dos grupos como a tela monta: primeira aparição por modulo.id (igual _carregar)
def ordem_grupos():
    vistos = []
    for r in sql("SELECT COALESCE(grupo,'Outros') AS g FROM modulo WHERE D_E_L_E_T=0 ORDER BY id"):
        if r[0] not in vistos:
            vistos.append(r[0])
    return [{"nome": g} for g in vistos]
grps = ordem_grupos()
idx_rel = [i for i, g in enumerate(grps) if g["nome"] == "Relatórios"][0]
# marca auto VER em Relatórios pro técnico, salvando a matriz (todos desmarcados)
form = {"csrf_token": TK, f"autover_{idx_rel}": "1"}
for i, g in enumerate(grps):
    form[f"grupo_{i}"] = g["nome"]
adm.post("/admin/perfis/2/permissoes", data=form)
chk("técnico passou a ter auto-liberar VER no grupo Relatórios",
    tuple(sql("SELECT auto_ver, auto_editar FROM perfis_grupos_auto WHERE id_perfil = 2 AND grupo = 'Relatórios'")[0]) == (1, 0))

# agora um módulo NOVO em Relatórios nasce VER pro técnico
novo2 = sql("INSERT INTO modulo (chave, nome, grupo, icone, rota, ordem, em_breve) "
            "VALUES ('relatorio_y', 'Relatório Y', 'Relatórios', 'ph-chart-line', '/relatorios/y', 98, 0) RETURNING id")[0][0]
with app.app_context():
    aplicar_auto_liberacoes()
chk("módulo novo em Relatórios nasce VER (não EDITAR) pro técnico", perm(2, novo2) == (1, 0), perm(2, novo2))

# desmarca a auto do técnico: módulo novo seguinte não é liberado
form2 = {"csrf_token": TK}
for i, g in enumerate(grps):
    form2[f"grupo_{i}"] = g["nome"]
adm.post("/admin/perfis/2/permissoes", data=form2)
chk("desmarcar a auto do técnico zera a regra",
    tuple(sql("SELECT auto_ver, auto_editar FROM perfis_grupos_auto WHERE id_perfil = 2 AND grupo = 'Relatórios'")[0]) == (0, 0))
novo3 = sql("INSERT INTO modulo (chave, nome, grupo, icone, rota, ordem, em_breve) "
            "VALUES ('relatorio_x', 'Relatório X', 'Relatórios', 'ph-chart-bar', '/relatorios/x', 97, 0) RETURNING id")[0][0]
with app.app_context():
    aplicar_auto_liberacoes()
chk("sem auto, o módulo novo seguinte NÃO é liberado pro técnico", perm(2, novo3) is None)

# ── 6. Segurança: técnico não salva permissões ──────────────────────────────
tec = app.test_client()
tec.post("/auth/login", data={"email": "tec@teste.local", "senha": "SenhaTecnico2026"})
TKT = re.search(rb'name="csrf-token" content="([^"]+)"', tec.get("/home").data).group(1).decode()
antes = sql("SELECT COUNT(*) FROM perfis_grupos_auto WHERE id_perfil = 2")[0][0]
r = tec.post("/admin/perfis/2/permissoes", data={"csrf_token": TKT, "grupo_0": "Relatórios", "autover_0": "1"})
chk("técnico não salva permissões -> 403", r.status_code == 403)
chk("nada mudou nas regras de auto", sql("SELECT COUNT(*) FROM perfis_grupos_auto WHERE id_perfil = 2")[0][0] == antes)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
