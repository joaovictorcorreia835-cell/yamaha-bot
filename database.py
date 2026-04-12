from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
import os

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

    ultima_interacao = Column(DateTime, default=datetime.now)
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
# ==========================================
class AgendamentoRevisao(Base):
    __tablename__ = "agendamentos_revisao"

    id = Column(Integer, primary_key=True, index=True)

    # Identificação
    protocolo = Column(String, unique=True, index=True)
    telefone = Column(String, index=True)
    nome = Column(String)
    cpf = Column(String, index=True)

    # Moto
    modelo = Column(String)
    ano = Column(String)
    revisao = Column(String)

    # Agendamento
    dia_semana = Column(String)
    data_agendada = Column(String, index=True)
    horario = Column(String, index=True)

    # Venda adicional
    itens = Column(Text)
    venda_adicional = Column(String)

    # Controle
    status = Column(String, default="AGENDADO")
    observacoes = Column(Text)

    origem = Column(String, default="BOT")

    # Controle automático
    lembrete_enviado = Column(Boolean, default=False)
    cancelado = Column(Boolean, default=False)
    reagendado = Column(Boolean, default=False)

    # Integração futura Sances
    codigo_sistema = Column(String)
    sincronizado = Column(Boolean, default=False)

    criado_em = Column(DateTime, default=datetime.now)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==========================================
# CRIAR BANCO
# ==========================================
def criar_banco():
    Base.metadata.create_all(bind=engine)