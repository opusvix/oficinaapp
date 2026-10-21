-- seed.sql: dados iniciais para OficinaApp
-- Perfis, módulos, matriz VER/EDITAR, admin inicial (bootstrap_admin cuida do usuário)

-- ──────────────────────────────────────────────────────────────────────────────
-- Perfis (id fixo para blindagem: admin=1)
-- ──────────────────────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO perfil (id, nome, descricao) VALUES
(1, 'Administrador', 'Acesso total ao sistema: relatórios, financeiro, aprovação de descontos, liberação de estoque, gestão de usuários e permissões.'),
(2, 'Técnico', 'Acesso mobile: rotas designadas, abrir/baixar OS, fotos antes/depois, registrar peças usadas.'),
(3, 'Cliente', 'Acesso via link público: visualizar status da OS, APROVAR ou RECUSAR orçamentos.');

-- ──────────────────────────────────────────────────────────────────────────────
-- Módulos do sistema (chave = identificador para permissionamento)
-- ──────────────────────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO modulo (id, chave, nome, grupo, sub_grupo, icone, rota, ordem, em_breve) VALUES
-- Auth / Admin
(1,  'auth',        'Usuários e Permissões', 'Administração', 'Segurança', 'ph-users-gear', '/admin/usuarios', 10, 0),
(2,  'perfis',      'Perfis e Permissões',   'Administração', 'Segurança', 'ph-shield-check', '/admin/perfis', 20, 0),
(3,  'modulos',     'Módulos do Sistema',    'Administração', 'Configuração', 'ph-puzzle-piece', '/admin/modulos', 30, 0),
(4,  'config',      'Configurações Gerais',  'Administração', 'Configuração', 'ph-gear-six', '/admin/config', 40, 0),
(5,  'seguranca',   'Segurança',             'Administração', 'Configuração', 'ph-lock-key', '/admin/seguranca', 50, 0),

-- Cadastros
(11, 'clientes',    'Clientes',              'Cadastros', 'Pessoas', 'ph-building', '/clientes', 10, 0),
(12, 'equipamentos', 'Equipamentos',         'Cadastros', 'Pessoas', 'ph-cpu', '/equipamentos', 20, 0),
(13, 'pecas',       'Peças / Estoque',       'Cadastros', 'Produtos', 'ph-package', '/estoque', 30, 0),

-- Operacional
(21, 'os',          'Ordens de Serviço',     'Operacional', 'OS', 'ph-wrench', '/os', 10, 0),
(22, 'agenda',      'Agenda e Rotas',        'Operacional', 'OS', 'ph-calendar', '/agenda', 20, 0),

-- Financeiro
(31, 'financeiro',  'Financeiro / PDV',      'Financeiro', 'Movimentação', 'ph-coins', '/financeiro', 10, 0),
(32, 'caixa',       'Controle de Caixa',     'Financeiro', 'Movimentação', 'ph-cash-register', '/financeiro/caixa', 20, 0),
(33, 'contas_pagar','Contas a Pagar',        'Financeiro', 'Movimentação', 'ph-arrow-down-left', '/financeiro/pagar', 30, 0),
(34, 'contas_receber','Contas a Receber',    'Financeiro', 'Movimentação', 'ph-arrow-up-right', '/financeiro/receber', 40, 0),

-- Relatórios
(41, 'relatorios',  'Relatórios e Dashboards','Relatórios', 'Visão Geral', 'ph-chart-bar', '/relatorios', 10, 0),

-- Ajuda (Fase 9: modules/leiame, Estrutura_de_Pastas app local)
(51, 'leiame',      'Guia rápido',           'Ajuda', 'Ajuda', 'ph-book-open', '/leiame', 10, 0);

-- ──────────────────────────────────────────────────────────────────────────────
-- Matriz VER / EDITAR por perfil
-- Regra: EDITAR implica VER
-- Perfil 1 (Administrador): VER=1, EDITAR=1 em tudo
-- Perfil 2 (Técnico): VER em operacional, EDITAR em OS (suas)
-- Perfil 3 (Cliente): VER apenas em link público (OS via token), sem módulos internos
-- ──────────────────────────────────────────────────────────────────────────────

-- Administrador: tudo
INSERT OR IGNORE INTO permissoes (id_perfil, id_modulo, pode_ver, pode_editar) VALUES
(1, 1, 1, 1),   -- auth
(1, 2, 1, 1),   -- perfis
(1, 3, 1, 1),   -- modulos
(1, 4, 1, 1),   -- config
(1, 5, 1, 1),   -- seguranca
(1, 11, 1, 1),  -- clientes
(1, 12, 1, 1),  -- equipamentos
(1, 13, 1, 1),  -- pecas/estoque
(1, 21, 1, 1),  -- os
(1, 22, 1, 1),  -- agenda
(1, 31, 1, 1),  -- financeiro
(1, 32, 1, 1),  -- caixa
(1, 33, 1, 1),  -- contas_pagar
(1, 34, 1, 1),  -- contas_receber
(1, 41, 1, 1);

-- Auto-liberação (Auto_Liberacao_por_Grupo): Admin auto-libera tudo. Grupo novo
-- que surgir re-entra aqui no proximo boot (seed roda sempre, INSERT OR IGNORE).
INSERT OR IGNORE INTO perfis_grupos_auto (id_perfil, grupo, auto_ver, auto_editar)
SELECT DISTINCT 1, COALESCE(grupo, 'Outros'), 1, 1 FROM modulo WHERE D_E_L_E_T = 0;  -- relatorios

-- Técnico: vê clientes/equipamentos (readonly), edita OS (suas), vê agenda
INSERT OR IGNORE INTO permissoes (id_perfil, id_modulo, pode_ver, pode_editar) VALUES
(2, 11, 1, 0),  -- clientes (ver)
(2, 12, 1, 0),  -- equipamentos (ver)
(2, 13, 1, 0),  -- estoque (ver peças)
(2, 21, 1, 1),  -- OS (ver e editar as suas - backend filtra por id_tecnico)
(2, 22, 1, 0),  -- agenda (ver)
(2, 31, 1, 0);  -- financeiro (ver resumo)

-- Guia rápido: todo perfil interno lê (Fase 9)
INSERT OR IGNORE INTO permissoes (id_perfil, id_modulo, pode_ver, pode_editar) VALUES
(1, 51, 1, 1),
(2, 51, 1, 0);

-- Cliente: não tem acesso a módulos internos (acessa via token público /os/public/<token>)
-- Nenhuma permissão na tabela para perfil 3

-- ──────────────────────────────────────────────────────────────────────────────
-- Configurações iniciais do sistema
-- ──────────────────────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO configuracao (chave, valor, descricao) VALUES
('empresa_nome', 'OficinaApp', 'Nome fantasia da empresa'),
('empresa_tagline', 'Gestão de Assistência Técnica', 'Slogan/tagline'),
('cor_primaria', '#3387E9', 'Cor primária da marca (hex)'),
('tema_padrao', 'light', 'Tema padrão: light ou dark'),
('os_token_expira_dias', '7', 'Dias de validade do token de aprovação OS'),
('upload_max_mb', '5', 'Tamanho máximo de upload em MB'),
('upload_tipos', 'image/*', 'Tipos MIME permitidos para upload'),
('pagination_default', '50', 'Linhas por página padrão (10, 50, 100, 500)'),
('session_timeout_min', '60', 'Minutos sem uso até exigir login de novo (0 desliga)'),
('max_login_tentativas', '5', 'Falhas de login (por e-mail ou por IP) antes de bloquear'),
('lockout_janela_min', '15', 'Janela do bloqueio de login, em minutos'),
('ip_protecao_modo', 'off', 'Controle de IP: off (nada), monitor (só registra), block (barra a blocklist)');

-- ──────────────────────────────────────────────────────────────────────────────
-- Observação: o usuário admin inicial NÃO é criado aqui.
-- Ele nasce via bootstrap_admin() no core/auth.py lendo variáveis de ambiente:
-- ADMIN_EMAIL, ADMIN_SENHA_INICIAL (opcional, vazio = sorteada), ADMIN_RESET_SENHA
-- ──────────────────────────────────────────────────────────────────────────────