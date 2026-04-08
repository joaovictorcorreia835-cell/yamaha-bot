from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
import os

# ==========================================
# CONFIG
# ==========================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


# ==========================================
# TABELA ATENDIMENTOS
# ==========================================

class Atendimento(Base):

    __tablename__ = "atendimentos"

    id = Column(Integer, primary_key=True)

    telefone = Column(String, index=True)

    nome = Column(String)

    setor = Column(String)

    modelo = Column(String)

    ano = Column(String)

    revisao = Column(String)

    dia_semana = Column(String)

    data_agendada = Column(String)

    horario = Column(String)

    cpf = Column(String)

    itens = Column(Text)

    venda_adicional = Column(String)

    origem = Column(String)

    status = Column(String)

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

    id = Column(Integer, primary_key=True)

    telefone = Column(String)

    nome = Column(String)

    modelo = Column(String)

    periodo = Column(String)

    status = Column(String, default="pendente")

    data_envio = Column(DateTime)


# ==========================================
# TABELA ATACADO
# ==========================================

class LeadAtacado(Base):

    __tablename__ = "leads_atacado"

    id = Column(Integer, primary_key=True)

    telefone = Column(String)

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
    Base.metadata.create_all(engine)