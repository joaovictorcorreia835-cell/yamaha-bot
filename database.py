from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
import os

# ==========================================
# CONFIG
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
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
    setor = Column(String, index=True)

    modelo = Column(String)
    ano = Column(String)
    revisao = Column(String, index=True)

    cpf = Column(String)
    chassi = Column(String)

    dia_semana = Column(String)
    data_agendada = Column(String)
    horario = Column(String)

    itens = Column(Text)
    venda_adicional = Column(String)

    origem = Column(String, default="Bot")
    status = Column(String, default="Em atendimento")
    etapa = Column(String)

    atendimento_humano = Column(Boolean, default=False)
    concluido = Column(Boolean, default=False)

    data = Column(DateTime, default=datetime.now)
    ultima_interacao = Column(DateTime, default=datetime.now)


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
# CRIAR BANCO
# ==========================================
def criar_banco():
    Base.metadata.create_all(bind=engine)