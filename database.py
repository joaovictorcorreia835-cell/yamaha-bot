from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, Float
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

# ==========================================
# CONFIG
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha.db")

# Ajuste para Postgres do Render
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
    revisao = Column(String, index=True, nullable=True)
    cpf = Column(String, index=True, nullable=True)

    dia_semana = Column(String, nullable=True)
    data_agendada = Column(String, index=True, nullable=True)
    horario = Column(String, index=True, nullable=True)

    itens = Column(Text, nullable=True)
    venda_adicional = Column(Text, nullable=True)
    observacao = Column(Text, nullable=True)

    origem = Column(String, nullable=True)
    status = Column(String, index=True, nullable=True)
    etapa = Column(String, index=True, nullable=True)

    atendimento_humano = Column(Boolean, default=False)
    concluido = Column(Boolean, default=False)

    followup_1 = Column(Boolean, default=False)
    followup_2 = Column(Boolean, default=False)
    followup_3 = Column(Boolean, default=False)
    followup_respondido = Column(Boolean, default=False)
    followup_recuperado = Column(Boolean, default=False)

    ultima_interacao = Column(DateTime, default=datetime.now)
    ultima_mensagem_cliente = Column(DateTime, nullable=True)

    data = Column(DateTime, default=datetime.now, index=True)


# ==========================================
# TABELA DISPAROS
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

    status = Column(String, default="pendente", index=True)
    data_envio = Column(DateTime, nullable=True)


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
    interesse = Column(Text, nullable=True)

    status = Column(String, default="novo", index=True)
    data = Column(DateTime, default=datetime.now, index=True)


# ==========================================
# TABELA AGENDAMENTOS REVISAO
# Alinhada ao banco atual do Render
# + PREPARADA PARA INTEGRAÇÃO SANCES
# + CONTROLE DE TENTATIVAS
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

    # ==========================================
    # CAMPOS DE INTEGRAÇÃO SANCES
    # ==========================================
    sances_status = Column(String, default="PENDENTE", index=True)
    sances_enviado = Column(Boolean, default=False)
    sances_protocolo = Column(String, default="")
    sances_erro = Column(Text, default="")
    sances_data_envio = Column(DateTime, nullable=True)

    # ==========================================
    # CONTROLE DE RETRY / FILA SANCES
    # ==========================================
    sances_tentativas = Column(Integer, default=0)
    sances_ultima_tentativa = Column(DateTime, nullable=True)
    sances_ultimo_retorno = Column(Text, default="")

    criado_em = Column(DateTime, default=datetime.now, index=True)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# TABELA CATÁLOGO DE REVISÕES
# Base oficial para IA responder dúvidas
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
# Perguntas frequentes prontas para apoio
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
# CRIAR BANCO
# ==========================================
def criar_banco():
    Base.metadata.create_all(bind=engine)