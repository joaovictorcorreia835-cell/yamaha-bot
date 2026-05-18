from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, Float, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

# ==========================================
# CONFIG
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


# ==========================================
# TABELA ATENDIMENTOS
# ==========================================
class Atendimento(Base):
    __tablename__ = "atendimentos"

    id = Column(Integer, primary_key=True, index=True)

    telefone = Column(String, index=True)
    nome = Column(String, nullable=True)
    setor = Column(String, index=True, nullable=True)

    modelo = Column(String, index=True, nullable=True)
    ano = Column(String, nullable=True)
    km_atual = Column(String, nullable=True)
    tipo_atendimento = Column(String, nullable=True)
    revisao = Column(String, index=True, nullable=True)
    cpf = Column(String, index=True, nullable=True)

    dia_semana = Column(String, nullable=True)
    data_agendada = Column(String, index=True, nullable=True)
    horario = Column(String, index=True, nullable=True)

    itens = Column(Text, nullable=True)
    venda_adicional = Column(Text, nullable=True)
    observacao = Column(Text, nullable=True)
    observacoes = Column(Text, nullable=True)

    origem = Column(String, nullable=True)
    status = Column(String, index=True, nullable=True)
    etapa = Column(String, index=True, nullable=True)
    status_comercial = Column(String, index=True, nullable=True)

    atendimento_humano = Column(Boolean, default=False)
    concluido = Column(Boolean, default=False)

    button_id = Column(String, nullable=True)
    intencao_ia = Column(String, nullable=True)
    id_envio_zapi = Column(String, nullable=True)
    tipo_envio = Column(String, nullable=True)
    status_retorno = Column(String, nullable=True)
    proxima_acao = Column(String, nullable=True)

    nivel_interesse = Column(String, nullable=True)
    temperatura_lead = Column(String, nullable=True)
    produto_interesse = Column(Text, nullable=True)
    oportunidade_comercial = Column(Boolean, default=False)
    cliente_recuperado = Column(Boolean, default=False)
    followup_nivel = Column(Integer, default=0)
    ultima_acao_ia = Column(String, nullable=True)
    valor_estimado = Column(Float, default=0)
    origem_ia = Column(String, nullable=True)

    followup_1 = Column(Boolean, default=False)
    followup_2 = Column(Boolean, default=False)
    followup_3 = Column(Boolean, default=False)
    followup_enviado = Column(Boolean, default=False)
    followup_respondido = Column(Boolean, default=False)
    followup_recuperado = Column(Boolean, default=False)

    ultima_interacao = Column(DateTime, default=datetime.now)
    ultima_mensagem_cliente = Column(Text, nullable=True)
    data_followup = Column(DateTime, nullable=True)

    data = Column(DateTime, default=datetime.now, index=True)


# ==========================================
# TABELA DISPAROS DE REVISÃO
# ==========================================
class Disparo(Base):
    __tablename__ = "disparos"

    id = Column(Integer, primary_key=True, index=True)

    telefone = Column(String, index=True)
    nome = Column(String, nullable=True)
    modelo = Column(String, nullable=True)
    periodo = Column(String, nullable=True)
    cpf = Column(String, nullable=True)
    chassi = Column(String, nullable=True)

    campanha = Column(String, index=True, nullable=True)
    origem = Column(String, default="BOT", index=True)

    status = Column(String, default="PENDENTE", index=True)
    status_retorno = Column(String, default="AGUARDANDO", index=True)

    button_id = Column(String, nullable=True)
    id_envio_zapi = Column(String, nullable=True)
    tipo_envio = Column(String, nullable=True)
    intencao_ia = Column(String, nullable=True)
    proxima_acao = Column(String, nullable=True)
    nivel_interesse = Column(String, nullable=True)

    observacoes = Column(Text, nullable=True)

    data_envio = Column(DateTime, nullable=True)
    data_retorno = Column(DateTime, nullable=True)
    ultima_interacao = Column(DateTime, nullable=True)

    criado_em = Column(DateTime, default=datetime.now, index=True)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# TABELA LEADS ATACADO
# ==========================================
class LeadAtacado(Base):
    __tablename__ = "leads_atacado"

    id = Column(Integer, primary_key=True, index=True)

    telefone = Column(String, index=True)
    empresa = Column(String, nullable=True)
    cnpj = Column(String, index=True, nullable=True)
    cidade = Column(String, nullable=True)
    responsavel = Column(String, nullable=True)

    campanha = Column(String, index=True, nullable=True)
    origem = Column(String, default="BOT", index=True)

    interesse = Column(Text, nullable=True)

    status = Column(String, default="NOVO", index=True)
    status_retorno = Column(String, default="AGUARDANDO", index=True)

    button_id = Column(String, nullable=True)
    id_envio_zapi = Column(String, nullable=True)
    tipo_envio = Column(String, nullable=True)
    intencao_ia = Column(String, nullable=True)
    proxima_acao = Column(String, nullable=True)
    nivel_interesse = Column(String, nullable=True)

    catalogo_enviado = Column(Boolean, default=False)
    data_catalogo_enviado = Column(DateTime, nullable=True)

    observacoes = Column(Text, nullable=True)

    data_envio = Column(DateTime, nullable=True)
    data_retorno = Column(DateTime, nullable=True)
    ultima_interacao = Column(DateTime, nullable=True)

    data = Column(DateTime, default=datetime.now, index=True)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# TABELA AGENDAMENTOS REVISAO
# ==========================================
class AgendamentoRevisao(Base):
    __tablename__ = "agendamentos_revisao"

    id = Column(Integer, primary_key=True, index=True)

    protocolo = Column(String, unique=True, index=True)
    telefone = Column(String, index=True)

    nome = Column(String, nullable=True)
    cpf = Column(String, index=True)

    modelo = Column(String, index=True, nullable=True)
    ano = Column(String, nullable=True)
    km_atual = Column(String, nullable=True)
    tipo_atendimento = Column(String, nullable=True)
    revisao = Column(String, index=True, nullable=True)

    dia_semana = Column(String, nullable=True)
    data_agendada = Column(String, index=True)
    horario = Column(String, index=True)

    itens = Column(Text, nullable=True)
    venda_adicional = Column(Text, nullable=True)

    status = Column(String, default="AGENDADO", index=True)

    observacoes = Column(Text, nullable=True)
    origem = Column(String, default="BOT")

    lembrete_enviado = Column(Boolean, default=False)

    sances_status = Column(String, default="PENDENTE", index=True)
    sances_enviado = Column(Boolean, default=False)
    sances_protocolo = Column(String, default="")
    sances_erro = Column(Text, default="")
    sances_data_envio = Column(DateTime, nullable=True)

    sances_tentativas = Column(Integer, default=0)
    sances_ultima_tentativa = Column(DateTime, nullable=True)
    sances_ultimo_retorno = Column(Text, default="")

    criado_em = Column(DateTime, default=datetime.now, index=True)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# TABELA CATÁLOGO DE REVISÕES
# ==========================================
class RevisaoCatalogo(Base):
    __tablename__ = "revisoes_catalogo"

    id = Column(Integer, primary_key=True, index=True)

    modelo = Column(String, index=True, nullable=False)
    revisao_numero = Column(String, index=True, nullable=False)

    valor = Column(Float, nullable=True)
    tempo_estimado = Column(String, nullable=True)

    itens_trocados = Column(Text, nullable=True)
    itens_verificados = Column(Text, nullable=True)
    descricao_servico = Column(Text, nullable=True)
    observacoes = Column(Text, nullable=True)

    ativo = Column(Boolean, default=True, index=True)

    criado_em = Column(DateTime, default=datetime.now)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# TABELA FAQ REVISÃO
# ==========================================
class FaqRevisao(Base):
    __tablename__ = "faq_revisao"

    id = Column(Integer, primary_key=True, index=True)

    categoria = Column(String, index=True)
    pergunta_chave = Column(String, index=True)
    resposta_base = Column(Text, nullable=True)

    ativo = Column(Boolean, default=True, index=True)

    criado_em = Column(DateTime, default=datetime.now)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# TABELA SUGESTÕES VENDA IA
# ==========================================
class SugestaoVenda(Base):
    __tablename__ = "sugestoes_venda"

    id = Column(Integer, primary_key=True, index=True)

    modelo = Column(String, index=True, nullable=True)

    km_min = Column(Integer, default=0)
    km_max = Column(Integer, default=999999)

    revisao = Column(String, nullable=True)

    produto = Column(String, nullable=False)
    mensagem = Column(Text, nullable=False)

    prioridade = Column(Integer, default=1)
    ativo = Column(Boolean, default=True)

    criado_em = Column(DateTime, default=datetime.now)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# TABELA FILA RPA / AUTOMAÇÃO
# ==========================================
class TarefaRPA(Base):
    __tablename__ = "tarefas_rpa"

    id = Column(Integer, primary_key=True, index=True)

    telefone = Column(String, index=True, nullable=True)
    tipo_tarefa = Column(String, index=True, nullable=False)
    dados_json = Column(Text, nullable=True)

    status_rpa = Column(String, default="RPA_PENDENTE", index=True)
    tentativas_rpa = Column(Integer, default=0)
    erro_rpa = Column(Text, nullable=True)

    origem = Column(String, default="BOT", index=True)
    prioridade = Column(Integer, default=5, index=True)
    resultado_json = Column(Text, nullable=True)

    data_criacao = Column(DateTime, default=datetime.now, index=True)
    data_processamento = Column(DateTime, nullable=True)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# CRIAR BANCO
# ==========================================
def migrar_colunas_followup():
    colunas = {
        coluna["name"]
        for coluna in inspect(engine).get_columns("atendimentos")
    }

    novas_colunas = {
        "followup_enviado": "BOOLEAN DEFAULT FALSE",
        "data_followup": "TIMESTAMP",
        "produto_interesse": "TEXT",
        "oportunidade_comercial": "BOOLEAN DEFAULT FALSE",
        "status_comercial": "VARCHAR",
        "km_atual": "VARCHAR",
        "tipo_atendimento": "VARCHAR",
    }

    with engine.begin() as conn:
        for nome, definicao in novas_colunas.items():
            if nome in colunas:
                continue

            conn.execute(text(f"ALTER TABLE atendimentos ADD COLUMN {nome} {definicao}"))


def migrar_colunas_sances():
    colunas = {
        coluna["name"]
        for coluna in inspect(engine).get_columns("agendamentos_revisao")
    }

    novas_colunas = {
        "km_atual": "VARCHAR",
        "tipo_atendimento": "VARCHAR",
        "sances_status": "VARCHAR DEFAULT 'PENDENTE'",
        "sances_enviado": "BOOLEAN DEFAULT FALSE",
        "sances_protocolo": "VARCHAR DEFAULT ''",
        "sances_erro": "TEXT DEFAULT ''",
        "sances_data_envio": "TIMESTAMP",
        "sances_tentativas": "INTEGER DEFAULT 0",
        "sances_ultima_tentativa": "TIMESTAMP",
        "sances_ultimo_retorno": "TEXT DEFAULT ''",
    }

    with engine.begin() as conn:
        for nome, definicao in novas_colunas.items():
            if nome in colunas:
                continue

            conn.execute(text(f"ALTER TABLE agendamentos_revisao ADD COLUMN {nome} {definicao}"))


def migrar_tabela_rpa():
    Base.metadata.create_all(bind=engine, tables=[TarefaRPA.__table__])


def criar_banco():
    Base.metadata.create_all(bind=engine)
    migrar_colunas_followup()
    migrar_colunas_sances()
    migrar_tabela_rpa()
