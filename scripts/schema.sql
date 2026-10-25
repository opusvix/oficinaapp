-- schema.sql: DDL idempotente para OficinaApp (SQLite)
-- Tabelas principais com soft delete (deleted_at)

-- ──────────────────────────────────────────────────────────────────────────────
-- Perfis e permissões
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS perfil (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            VARCHAR(100) NOT NULL UNIQUE,
    descricao       TEXT,
    D_E_L_E_T       SMALLINT DEFAULT 0,
    datestamp_insert TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS modulo (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chave           VARCHAR(50) NOT NULL UNIQUE,  -- ex: 'clientes', 'estoque', 'os'
    nome            VARCHAR(100) NOT NULL,
    grupo           VARCHAR(100),                 -- ex: 'Cadastros', 'Produção'
    sub_grupo       VARCHAR(100),
    icone           VARCHAR(80),                  -- ex: 'ph-users'
    rota            VARCHAR(200),                 -- ex: '/clientes/'
    ordem           INTEGER DEFAULT 0,
    em_breve        SMALLINT DEFAULT 0,
    D_E_L_E_T       SMALLINT DEFAULT 0,
    datestamp_insert TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS permissoes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    id_perfil       INTEGER NOT NULL REFERENCES perfil(id),
    id_modulo       INTEGER NOT NULL REFERENCES modulo(id),
    pode_ver        SMALLINT DEFAULT 0,
    pode_editar     SMALLINT DEFAULT 0,
    D_E_L_E_T       SMALLINT DEFAULT 0,
    datestamp_insert TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id_perfil, id_modulo)
);

-- Auto-liberação por grupo (Auto_Liberacao_por_Grupo): o perfil marca "auto-liberar
-- VER/EDITAR" num grupo, e todo módulo NOVO que entrar nesse grupo já nasce liberado
-- pra ele (aplicar_auto_liberacoes no boot). Evita editar a matriz a cada módulo novo.
CREATE TABLE IF NOT EXISTS perfis_grupos_auto (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    id_perfil       INTEGER NOT NULL REFERENCES perfil(id),
    grupo           VARCHAR(80) NOT NULL,
    auto_ver        SMALLINT DEFAULT 0,
    auto_editar     SMALLINT DEFAULT 0,
    D_E_L_E_T       SMALLINT DEFAULT 0,
    datestamp_insert TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id_perfil, grupo)
);
CREATE INDEX IF NOT EXISTS idx_perfis_grupos_auto_perfil ON perfis_grupos_auto(id_perfil);

-- ──────────────────────────────────────────────────────────────────────────────
-- Usuários
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS usuario (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                    VARCHAR(150) NOT NULL,
    email                   VARCHAR(150) NOT NULL UNIQUE,
    senha_hash              VARCHAR(255) NOT NULL,
    id_perfil               INTEGER NOT NULL REFERENCES perfil(id),
    id_cliente              INTEGER,           -- NULL = admin/gestor vê todos
    ve_todos_clientes       SMALLINT DEFAULT 0,
    ativo                   SMALLINT DEFAULT 1,
    precisa_trocar_senha    SMALLINT DEFAULT 0,
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at              TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_usuario_email ON usuario(email) WHERE D_E_L_E_T = 0;

-- Tentativas de login (Forca_Bruta_Login): UMA LINHA POR TENTATIVA, sucesso ou
-- falha. Conta falhas por e-mail OU por IP na janela. No banco, não em session:
-- em session o atacante zera a conta apagando o cookie.
-- Tempos em epoch (INTEGER): comparação trivial, sem conversor de data.
-- (A tabela antiga login_tentativa, chave email|ip, ficou obsoleta.)
CREATE TABLE IF NOT EXISTS login_tentativas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           VARCHAR(150),
    ip              VARCHAR(45),
    sucesso         SMALLINT NOT NULL DEFAULT 0,
    quando          INTEGER NOT NULL            -- epoch
);
CREATE INDEX IF NOT EXISTS idx_login_tent_email ON login_tentativas(email, quando);
CREATE INDEX IF NOT EXISTS idx_login_tent_ip ON login_tentativas(ip, quando);

-- Controle de IP (Controle_de_IP): regras allow/block. expira_em NULL = permanente
-- (regra manual); bloqueio automático entra COM prazo, pra IP compartilhado não
-- virar sentença perpétua. Modo em configuracao.ip_protecao_modo (off|monitor|block).
CREATE TABLE IF NOT EXISTS ip_regras (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ip              VARCHAR(45) NOT NULL,
    tipo            VARCHAR(10) NOT NULL,       -- 'allow' ou 'block'
    descricao       VARCHAR(300),
    expira_em       INTEGER,                    -- epoch; NULL = permanente
    D_E_L_E_T       SMALLINT DEFAULT 0,
    usuario_insert  INTEGER,
    quando          INTEGER                     -- epoch
);
CREATE INDEX IF NOT EXISTS idx_ip_regras_ip ON ip_regras(ip, tipo) WHERE D_E_L_E_T = 0;

-- Auditoria (Principios): quem fez o quê, de onde. Nunca senha nem token.
CREATE TABLE IF NOT EXISTS logs_acesso (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    id_usuario      INTEGER,                    -- NULL = anônimo (login que falhou)
    acao            VARCHAR(40) NOT NULL,       -- LOGIN, LOGIN_FALHA, LOGOUT, ...
    detalhe         VARCHAR(300),
    ip              VARCHAR(45),
    quando          INTEGER NOT NULL            -- epoch
);
CREATE INDEX IF NOT EXISTS idx_logs_acesso_quando ON logs_acesso(quando);
CREATE INDEX IF NOT EXISTS idx_logs_acesso_usuario ON logs_acesso(id_usuario, quando);

-- Preferências de UI por usuário (colunas visíveis, linhas/página, ordenação
-- da TabelaAvancada). Valor em JSON, chave composta (usuario, chave).
CREATE TABLE IF NOT EXISTS usuario_preferencias (
    id_usuario      INTEGER NOT NULL REFERENCES usuario(id),
    chave           VARCHAR(80) NOT NULL,
    valor           TEXT,                                -- JSON
    atualizado_em   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id_usuario, chave)
);

-- ──────────────────────────────────────────────────────────────────────────────
-- Clientes e Equipamentos
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cliente (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social            VARCHAR(200) NOT NULL,
    nome_fantasia           VARCHAR(200),
    cpf_cnpj                VARCHAR(18),
    ie_rg                   VARCHAR(20),
    email                   VARCHAR(150),
    telefone1               VARCHAR(20),
    telefone2               VARCHAR(20),
    cep                     VARCHAR(9),
    logradouro              VARCHAR(200),
    numero                  VARCHAR(20),
    complemento             VARCHAR(100),
    bairro                  VARCHAR(100),
    cidade                  VARCHAR(100),
    uf                      VARCHAR(2),
    observacoes             TEXT,
    foto                    VARCHAR(255),               -- caminho em static/ (opcional)
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at              TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equipamento (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_cliente              INTEGER NOT NULL REFERENCES cliente(id),
    patrimonio              VARCHAR(50) NOT NULL,       -- Tag/Patrimônio (ex: ESG123)
    modelo                  VARCHAR(150),
    marca                   VARCHAR(100),
    numero_serie            VARCHAR(100),
    descricao               TEXT,
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at              TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_equipamento_unico
    ON equipamento(id_cliente, patrimonio) WHERE D_E_L_E_T = 0;

CREATE INDEX IF NOT EXISTS idx_equipamento_cliente ON equipamento(id_cliente) WHERE D_E_L_E_T = 0;

-- ──────────────────────────────────────────────────────────────────────────────
-- Estoque (Peças)
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS peca (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo                  VARCHAR(50) NOT NULL UNIQUE,
    descricao               VARCHAR(200) NOT NULL,
    unidade                 VARCHAR(10) DEFAULT 'UN',
    preco_custo             DECIMAL(12,2) DEFAULT 0,
    preco_venda             DECIMAL(12,2) DEFAULT 0,
    estoque_atual           DECIMAL(12,3) DEFAULT 0,
    estoque_minimo          DECIMAL(12,3) DEFAULT 0,
    localizacao             VARCHAR(100),
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at              TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movimento_estoque (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_peca                 INTEGER NOT NULL REFERENCES peca(id),
    tipo                    VARCHAR(10) NOT NULL,       -- 'ENTRADA' ou 'SAIDA'
    quantidade              DECIMAL(12,3) NOT NULL,
    id_origem               INTEGER,                    -- id da OS, compra, ajuste, etc
    origem_tipo             VARCHAR(30),                -- 'OS', 'COMPRA', 'AJUSTE', 'INVENTARIO'
    observacoes             TEXT,
    datestamp               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    D_E_L_E_T               SMALLINT DEFAULT 0
);

-- ──────────────────────────────────────────────────────────────────────────────
-- Ordens de Serviço
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ordem_servico (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_cliente              INTEGER NOT NULL REFERENCES cliente(id),
    id_equipamento          INTEGER REFERENCES equipamento(id),
    id_tecnico              INTEGER REFERENCES usuario(id),
    patrimonio              VARCHAR(50) NOT NULL,       -- obrigatório: ESG{idOS} se vazio
    status                  VARCHAR(30) DEFAULT 'aberta', -- aberta, avaliacao, aprovada, em_andamento, entregue, recusada
    descricao_inicial       TEXT,
    descricao_execucao      TEXT,
    orcamento_valor         DECIMAL(12,2) DEFAULT 0,
    orcamento_status        VARCHAR(10) DEFAULT 'pendente', -- pendente, aprovado, recusado
    os_token                VARCHAR(64) UNIQUE,         -- token público para aprovação cliente
    token_expira            TIMESTAMP,
    assinatura_cliente      TEXT,                       -- base64 canvas
    foto_antes              VARCHAR(255),               -- path arquivo
    foto_depois             VARCHAR(255),
    data_abertura           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_avaliacao          TIMESTAMP,
    data_aprovacao          TIMESTAMP,
    data_inicio             TIMESTAMP,
    data_entrega            TIMESTAMP,              -- quando o CLIENTE confirmou pelo link
    entrega_solicitada_em   TIMESTAMP,              -- técnico pediu a validação; zera se mexer na execução
    data_recusa             TIMESTAMP,
    custo_deslocamento      DECIMAL(12,2) DEFAULT 0,
    garantia_fabrica        SMALLINT DEFAULT 0,         -- 1 = OS em garantia: autoriza/cobra o fabricante, peça não baixa estoque
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at              TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_os_cliente ON ordem_servico(id_cliente) WHERE D_E_L_E_T = 0;
CREATE INDEX IF NOT EXISTS idx_os_tecnico ON ordem_servico(id_tecnico) WHERE D_E_L_E_T = 0;
CREATE INDEX IF NOT EXISTS idx_os_status ON ordem_servico(status) WHERE D_E_L_E_T = 0;
CREATE INDEX IF NOT EXISTS idx_os_token ON ordem_servico(os_token) WHERE os_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS item_os (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_os                   INTEGER NOT NULL REFERENCES ordem_servico(id),
    id_peca                 INTEGER REFERENCES peca(id),
    descricao               VARCHAR(200) NOT NULL,      -- permite digitar livre se não tem no estoque
    quantidade              DECIMAL(12,3) DEFAULT 1,
    preco_unitario          DECIMAL(12,2) DEFAULT 0,
    subtotal                DECIMAL(12,2) DEFAULT 0,
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ──────────────────────────────────────────────────────────────────────────────
-- Financeiro
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS financeiro (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_os                   INTEGER REFERENCES ordem_servico(id),
    tipo                    VARCHAR(20) NOT NULL,       -- 'RECEBER' ou 'PAGAR'
    descricao               VARCHAR(200),
    valor                   DECIMAL(12,2) NOT NULL,
    data_vencimento         DATE,
    data_pagamento          DATE,
    forma_pagamento         VARCHAR(30),                -- dinheiro, pix, cartao_debito, cartao_credito, boleto
    status                  VARCHAR(20) DEFAULT 'aberto', -- aberto, pago, cancelado, parcial
    parcela                 INTEGER DEFAULT 1,
    total_parcelas          INTEGER DEFAULT 1,
    observacoes             TEXT,
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at              TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fin_vencimento ON financeiro(data_vencimento) WHERE D_E_L_E_T = 0;
CREATE INDEX IF NOT EXISTS idx_fin_status ON financeiro(status) WHERE D_E_L_E_T = 0;
-- Colunas novas da Fase 7 (id_cliente, fornecedor, id_origem, usuario_baixa,
-- id_caixa) entram por core/db._migracoes: CREATE IF NOT EXISTS não altera tabela.

-- Caixa (Fase 7): uma sessão por abertura. Datas em UTC (core/tempo).
-- Saldo FÍSICO da gaveta = inicial + suprimentos - sangrias + recebido em dinheiro
-- - pago em dinheiro. Pix/cartão/boleto aparecem no resumo, não na gaveta.
CREATE TABLE IF NOT EXISTS caixa (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    aberto_em               TIMESTAMP NOT NULL,
    aberto_por              INTEGER REFERENCES usuario(id),
    saldo_inicial           DECIMAL(12,2) NOT NULL DEFAULT 0,
    fechado_em              TIMESTAMP,
    fechado_por             INTEGER REFERENCES usuario(id),
    saldo_calculado         DECIMAL(12,2),              -- o sistema diz quanto devia ter
    saldo_informado         DECIMAL(12,2),              -- o operador contou na gaveta
    diferenca               DECIMAL(12,2),              -- informado - calculado
    observacoes             TEXT,
    status                  VARCHAR(10) NOT NULL DEFAULT 'aberto', -- aberto, fechado
    D_E_L_E_T               SMALLINT DEFAULT 0
);
-- No máximo UM caixa aberto: o índice único parcial é a trava no banco
CREATE UNIQUE INDEX IF NOT EXISTS idx_caixa_um_aberto ON caixa(status) WHERE status = 'aberto' AND D_E_L_E_T = 0;

CREATE TABLE IF NOT EXISTS caixa_mov (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_caixa                INTEGER NOT NULL REFERENCES caixa(id),
    tipo                    VARCHAR(15) NOT NULL,       -- SUPRIMENTO, SANGRIA, RECEBIMENTO, PAGAMENTO
    forma_pagamento         VARCHAR(30) NOT NULL DEFAULT 'dinheiro',
    valor                   DECIMAL(12,2) NOT NULL,     -- sempre positivo; o tipo diz o sinal
    descricao               VARCHAR(200),
    id_financeiro           INTEGER REFERENCES financeiro(id),
    id_usuario              INTEGER REFERENCES usuario(id),
    quando                  TIMESTAMP NOT NULL,
    D_E_L_E_T               SMALLINT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_caixa_mov_caixa ON caixa_mov(id_caixa) WHERE D_E_L_E_T = 0;

-- ──────────────────────────────────────────────────────────────────────────────
-- Agenda / Rotas
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agenda (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_tecnico              INTEGER NOT NULL REFERENCES usuario(id),
    id_os                   INTEGER REFERENCES ordem_servico(id),
    data_hora_inicio        TIMESTAMP NOT NULL,
    data_hora_fim           TIMESTAMP,
    status                  VARCHAR(20) DEFAULT 'agendado', -- agendado, em_andamento, concluido, cancelado
    observacoes             TEXT,
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at              TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agenda_tecnico_data ON agenda(id_tecnico, data_hora_inicio) WHERE D_E_L_E_T = 0;

-- ──────────────────────────────────────────────────────────────────────────────
-- Configurações do sistema
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS configuracao (
    chave                   VARCHAR(100) PRIMARY KEY,
    valor                   TEXT,
    descricao               TEXT,
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ──────────────────────────────────────────────────────────────────────────────
-- Notificações (sino da topbar). Uma linha por usuário + evento.
-- Quem cria: core.menu.notificar() — OS aguardando aprovação, estoque no
-- mínimo, caixa a fechar, conta vencendo.
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS notificacao (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_usuario              INTEGER NOT NULL REFERENCES usuario(id),
    tipo                    VARCHAR(12) DEFAULT 'info',  -- info | aviso | sucesso | erro
    titulo                  VARCHAR(160) NOT NULL,
    mensagem                TEXT,
    rota                    VARCHAR(200),               -- destino do clique (começa com /)
    lida                    SMALLINT DEFAULT 0,
    D_E_L_E_T               SMALLINT DEFAULT 0,
    datestamp_insert        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notificacao_usuario
    ON notificacao(id_usuario, lida) WHERE D_E_L_E_T = 0;

-- ──────────────────────────────────────────────────────────────────────────────
-- Triggers para updated_at (opcional, SQLite não tem ON UPDATE automático)
-- ──────────────────────────────────────────────────────────────────────────────

-- Exemplo: CREATE TRIGGER trg_usuario_updated AFTER UPDATE ON usuario
-- BEGIN UPDATE usuario SET datestamp_insert = CURRENT_TIMESTAMP WHERE id = NEW.id; END;