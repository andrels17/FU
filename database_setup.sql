-- ============================================
-- SCHEMA DO BANCO DE DADOS - FOLLOW-UP DE COMPRAS
-- ============================================

-- Tabela de Usuários
CREATE TABLE IF NOT EXISTS usuarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    nome VARCHAR(255) NOT NULL,
    senha_hash VARCHAR(255) NOT NULL,
    perfil VARCHAR(20) NOT NULL CHECK (perfil IN ('admin', 'coordenador')),
    ativo BOOLEAN DEFAULT true,
    criado_em TIMESTAMP DEFAULT NOW(),
    atualizado_em TIMESTAMP DEFAULT NOW()
);

-- Tabela de Fornecedores
CREATE TABLE IF NOT EXISTS fornecedores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cod_fornecedor INTEGER UNIQUE NOT NULL,
    nome VARCHAR(500) NOT NULL,
    nome_fantasia VARCHAR(500),
    cnpj VARCHAR(20),
    cidade VARCHAR(255),
    uf VARCHAR(2),
    ie VARCHAR(50),
    endereco TEXT,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    ativo BOOLEAN DEFAULT true,
    criado_em TIMESTAMP DEFAULT NOW(),
    atualizado_em TIMESTAMP DEFAULT NOW()
);

-- Índices para fornecedores
CREATE INDEX IF NOT EXISTS idx_fornecedores_cod ON fornecedores(cod_fornecedor);
CREATE INDEX IF NOT EXISTS idx_fornecedores_cidade_uf ON fornecedores(cidade, uf);

-- Tabela de Pedidos (Follow-up)
CREATE TABLE IF NOT EXISTS pedidos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Identificação
    nr_solicitacao VARCHAR(50),
    nr_oc VARCHAR(50),
    
    -- Departamento e Equipamento
    departamento VARCHAR(255),
    cod_equipamento VARCHAR(100),
    
    -- Material
    cod_material VARCHAR(100),
    descricao TEXT NOT NULL,
    
    -- Quantidades
    qtde_solicitada DECIMAL(10, 2) NOT NULL,
    qtde_entregue DECIMAL(10, 2) DEFAULT 0,
    qtde_pendente DECIMAL(10, 2),
    entregue BOOLEAN DEFAULT false,
    
    -- Datas
    data_solicitacao DATE,
    data_oc DATE,
    prazo_entrega VARCHAR(50),
    previsao_entrega DATE,
    data_entrega_real DATE,
    
    -- Status e Valores
    status VARCHAR(50) NOT NULL DEFAULT 'Sem OC',
    valor_ultima_compra DECIMAL(15, 2),
    valor_total DECIMAL(15, 2),
    
    -- Fornecedor (relacionamento)
    fornecedor_id UUID REFERENCES fornecedores(id),
    
    -- Observações
    observacoes TEXT,
    
    -- Auditoria
    criado_por UUID REFERENCES usuarios(id),
    atualizado_por UUID REFERENCES usuarios(id),
    criado_em TIMESTAMP DEFAULT NOW(),
    atualizado_em TIMESTAMP DEFAULT NOW()
);

-- Índices para pedidos
CREATE INDEX IF NOT EXISTS idx_pedidos_nr_solicitacao ON pedidos(nr_solicitacao);
CREATE INDEX IF NOT EXISTS idx_pedidos_nr_oc ON pedidos(nr_oc);
CREATE INDEX IF NOT EXISTS idx_pedidos_departamento ON pedidos(departamento);
CREATE INDEX IF NOT EXISTS idx_pedidos_status ON pedidos(status);
CREATE INDEX IF NOT EXISTS idx_pedidos_fornecedor ON pedidos(fornecedor_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_datas ON pedidos(data_solicitacao, previsao_entrega);

-- Tabela de Histórico de Entregas
CREATE TABLE IF NOT EXISTS historico_entregas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_id UUID REFERENCES pedidos(id) ON DELETE CASCADE,
    qtde_entregue DECIMAL(10, 2) NOT NULL,
    data_entrega DATE NOT NULL,
    observacoes TEXT,
    usuario_id UUID REFERENCES usuarios(id),
    criado_em TIMESTAMP DEFAULT NOW()
);

-- Índice para histórico
CREATE INDEX IF NOT EXISTS idx_historico_pedido ON historico_entregas(pedido_id);

-- Tabela de Anexos
CREATE TABLE IF NOT EXISTS anexos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_id UUID REFERENCES pedidos(id) ON DELETE CASCADE,
    nome_arquivo VARCHAR(500) NOT NULL,
    tipo_arquivo VARCHAR(100),
    tamanho_bytes INTEGER,
    url_storage TEXT NOT NULL,
    descricao TEXT,
    usuario_id UUID REFERENCES usuarios(id),
    criado_em TIMESTAMP DEFAULT NOW()
);

-- Índice para anexos
CREATE INDEX IF NOT EXISTS idx_anexos_pedido ON anexos(pedido_id);

-- Tabela de Log de Importações
CREATE TABLE IF NOT EXISTS log_importacoes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id UUID REFERENCES usuarios(id),
    nome_arquivo VARCHAR(500),
    registros_processados INTEGER,
    registros_inseridos INTEGER,
    registros_atualizados INTEGER,
    registros_erro INTEGER,
    detalhes_erro TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- TRIGGERS PARA ATUALIZAÇÃO AUTOMÁTICA
-- ============================================

-- Trigger para atualizar qtde_pendente automaticamente
CREATE OR REPLACE FUNCTION atualizar_qtde_pendente()
RETURNS TRIGGER AS $$
BEGIN
    NEW.qtde_pendente = NEW.qtde_solicitada - NEW.qtde_entregue;
    
    -- Marcar como entregue se quantidade pendente <= 0
    IF NEW.qtde_pendente <= 0 THEN
        NEW.entregue = true;
        NEW.status = 'Entregue';
    ELSE
        NEW.entregue = false;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_atualizar_qtde_pendente
    BEFORE INSERT OR UPDATE OF qtde_solicitada, qtde_entregue
    ON pedidos
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_qtde_pendente();

-- Trigger para atualizar timestamp
CREATE OR REPLACE FUNCTION atualizar_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.atualizado_em = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_pedidos_timestamp
    BEFORE UPDATE ON pedidos
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_timestamp();

CREATE TRIGGER trigger_fornecedores_timestamp
    BEFORE UPDATE ON fornecedores
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_timestamp();

CREATE TRIGGER trigger_usuarios_timestamp
    BEFORE UPDATE ON usuarios
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_timestamp();

-- ============================================
-- VIEWS ÚTEIS
-- ============================================

-- View de pedidos com informações do fornecedor
CREATE OR REPLACE VIEW vw_pedidos_completo AS
SELECT 
    p.*,
    f.cod_fornecedor,
    f.nome as fornecedor_nome,
    f.nome_fantasia as fornecedor_nome_fantasia,
    f.cidade as fornecedor_cidade,
    f.uf as fornecedor_uf,
    f.endereco as fornecedor_endereco,
    f.latitude as fornecedor_latitude,
    f.longitude as fornecedor_longitude,
    CASE 
        WHEN p.previsao_entrega < CURRENT_DATE AND NOT p.entregue THEN true
        ELSE false
    END as atrasado
FROM pedidos p
LEFT JOIN fornecedores f ON p.fornecedor_id = f.id;

-- View de estatísticas por departamento
CREATE OR REPLACE VIEW vw_stats_departamento AS
SELECT 
    departamento,
    COUNT(*) as total_pedidos,
    COUNT(*) FILTER (WHERE entregue = true) as pedidos_entregues,
    COUNT(*) FILTER (WHERE entregue = false) as pedidos_pendentes,
    COUNT(*) FILTER (WHERE previsao_entrega < CURRENT_DATE AND entregue = false) as pedidos_atrasados,
    SUM(valor_total) as valor_total,
    SUM(valor_total) FILTER (WHERE entregue = true) as valor_entregue,
    SUM(valor_total) FILTER (WHERE entregue = false) as valor_pendente
FROM pedidos
WHERE departamento IS NOT NULL
GROUP BY departamento;

-- View de estatísticas por fornecedor
CREATE OR REPLACE VIEW vw_stats_fornecedor AS
SELECT 
    f.id as fornecedor_id,
    f.cod_fornecedor,
    f.nome as fornecedor_nome,
    f.cidade,
    f.uf,
    COUNT(p.id) as total_pedidos,
    COUNT(p.id) FILTER (WHERE p.entregue = true) as pedidos_entregues,
    COUNT(p.id) FILTER (WHERE p.entregue = false) as pedidos_pendentes,
    SUM(p.valor_total) as valor_total,
    AVG(CASE 
        WHEN p.data_entrega_real IS NOT NULL AND p.previsao_entrega IS NOT NULL 
        THEN p.data_entrega_real - p.previsao_entrega 
    END) as media_atraso_dias
FROM fornecedores f
LEFT JOIN pedidos p ON f.id = p.fornecedor_id
GROUP BY f.id, f.cod_fornecedor, f.nome, f.cidade, f.uf;

-- ============================================
-- POLÍTICAS DE SEGURANÇA (Row Level Security)
-- ============================================

-- Habilitar RLS
ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE pedidos ENABLE ROW LEVEL SECURITY;
ALTER TABLE fornecedores ENABLE ROW LEVEL SECURITY;
ALTER TABLE historico_entregas ENABLE ROW LEVEL SECURITY;
ALTER TABLE anexos ENABLE ROW LEVEL SECURITY;

-- Políticas para usuários (apenas admin pode gerenciar)
CREATE POLICY "Admin pode ver todos usuários" ON usuarios
    FOR SELECT USING (auth.jwt()->>'email' IN (SELECT email FROM usuarios WHERE perfil = 'admin'));

CREATE POLICY "Admin pode inserir usuários" ON usuarios
    FOR INSERT WITH CHECK (auth.jwt()->>'email' IN (SELECT email FROM usuarios WHERE perfil = 'admin'));

CREATE POLICY "Admin pode atualizar usuários" ON usuarios
    FOR UPDATE USING (auth.jwt()->>'email' IN (SELECT email FROM usuarios WHERE perfil = 'admin'));

-- Políticas para pedidos (admin pode tudo, coordenador só visualiza)
CREATE POLICY "Todos podem ver pedidos" ON pedidos
    FOR SELECT USING (true);

CREATE POLICY "Admin pode inserir pedidos" ON pedidos
    FOR INSERT WITH CHECK (auth.jwt()->>'email' IN (SELECT email FROM usuarios WHERE perfil = 'admin'));

CREATE POLICY "Admin pode atualizar pedidos" ON pedidos
    FOR UPDATE USING (auth.jwt()->>'email' IN (SELECT email FROM usuarios WHERE perfil = 'admin'));

CREATE POLICY "Admin pode deletar pedidos" ON pedidos
    FOR DELETE USING (auth.jwt()->>'email' IN (SELECT email FROM usuarios WHERE perfil = 'admin'));

-- Políticas para fornecedores (todos podem ver)
CREATE POLICY "Todos podem ver fornecedores" ON fornecedores
    FOR SELECT USING (true);

CREATE POLICY "Admin pode gerenciar fornecedores" ON fornecedores
    FOR ALL USING (auth.jwt()->>'email' IN (SELECT email FROM usuarios WHERE perfil = 'admin'));

-- Políticas para histórico e anexos
CREATE POLICY "Todos podem ver histórico" ON historico_entregas
    FOR SELECT USING (true);

CREATE POLICY "Admin pode inserir histórico" ON historico_entregas
    FOR INSERT WITH CHECK (auth.jwt()->>'email' IN (SELECT email FROM usuarios WHERE perfil = 'admin'));

CREATE POLICY "Todos podem ver anexos" ON anexos
    FOR SELECT USING (true);

CREATE POLICY "Admin pode gerenciar anexos" ON anexos
    FOR ALL USING (auth.jwt()->>'email' IN (SELECT email FROM usuarios WHERE perfil = 'admin'));

-- ============================================
-- COMENTÁRIOS NAS TABELAS
-- ============================================

COMMENT ON TABLE pedidos IS 'Tabela principal de pedidos de compra e follow-up';
COMMENT ON TABLE fornecedores IS 'Cadastro de fornecedores';
COMMENT ON TABLE usuarios IS 'Usuários do sistema com controle de acesso';
COMMENT ON TABLE historico_entregas IS 'Histórico de entregas parciais dos pedidos';
COMMENT ON TABLE anexos IS 'Anexos dos pedidos (notas fiscais, boletos, etc)';
COMMENT ON TABLE log_importacoes IS 'Log de importações em massa de pedidos';
