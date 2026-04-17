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
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)

Base = declarative_base()


# ==========================================
# TABELA ATENDIMENTOS
# ==========================================
class Atendimento(Base):
    __tablename__ = "atendimentos"

    id = Column(Integer, primary_key=True, index=True)

    telefone = Column(String, index=True)
    nome = Column(String)
    setor = Column(String)

    modelo = Column(String)
    ano = Column(String)
    revisao = Column(String)
    cpf = Column(String)

    dia_semana = Column(String)
    data_agendada = Column(String)
    horario = Column(String)

    itens = Column(Text)
    venda_adicional = Column(Text)

    origem = Column(String)
    status = Column(String)
    etapa = Column(String)

    atendimento_humano = Column(Boolean, default=False)
    concluido = Column(Boolean, default=False)

    followup_1 = Column(Boolean, default=False)
    followup_2 = Column(Boolean, default=False)
    followup_3 = Column(Boolean, default=False)

    ultima_interacao = Column(DateTime, default=datetime.now)
    ultima_mensagem_cliente = Column(DateTime, nullable=True)

    data = Column(DateTime, default=datetime.now)

# ==========================================
# TABELA DISPAROS
# ==========================================
class Disparo(Base):
    __tablename__ = "disparos"

    id = Column(Integer, primary_key=True, index=True)

    telefone = Column(String, index=True)
    nome = Column(String)
    modelo = Column(String)
    periodo = Column(String)

    cpf = Column(String)
    chassi = Column(String)

    status = Column(String, default="pendente")
    data_envio = Column(DateTime)


# ==========================================
# TABELA LEADS ATACADO
# ==========================================
class LeadAtacado(Base):
    __tablename__ = "leads_atacado"

    id = Column(Integer, primary_key=True, index=True)

    telefone = Column(String, index=True)
    empresa = Column(String)
    cnpj = Column(String)
    cidade = Column(String)
    responsavel = Column(String)
    interesse = Column(Text)

    status = Column(String, default="novo")
    data = Column(DateTime, default=datetime.now)


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
    nome = Column(String)
    cpf = Column(String, index=True)

    modelo = Column(String)
    ano = Column(String)
    revisao = Column(String)

    dia_semana = Column(String)
    data_agendada = Column(String, index=True)
    horario = Column(String, index=True)

    itens = Column(Text)
    venda_adicional = Column(Text)

    status = Column(String, default="AGENDADO")
    observacoes = Column(Text)

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

    criado_em = Column(DateTime, default=datetime.now)
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

    valor = Column(Float)
    tempo_estimado = Column(String)

    itens_trocados = Column(Text)
    itens_verificados = Column(Text)
    descricao_servico = Column(Text)
    observacoes = Column(Text)

    ativo = Column(Boolean, default=True)

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
    resposta_base = Column(Text)

    ativo = Column(Boolean, default=True)

    criado_em = Column(DateTime, default=datetime.now)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# CRIAR BANCO
# ==========================================
def criar_banco():
    Base.metadata.create_all(bind=engine)