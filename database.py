from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
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

    telefone = Column(String)

    nome = Column(String)

    setor = Column(String)

    modelo = Column(String)

    ano = Column(String)

    revisao = Column(String)

    horario = Column(String)

    itens = Column(String)

    origem = Column(String)

    status = Column(String)

    atendimento_humano = Column(Boolean, default=False)

    data = Column(DateTime, default=datetime.now)


# ==========================================
# CRIAR BANCO
# ==========================================

def criar_banco():
    Base.metadata.create_all(engine)