from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///yamaha.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Atendimento(Base):
    __tablename__ = "atendimentos"

    id = Column(Integer, primary_key=True, index=True)
    telefone = Column(String(30), index=True)
    nome = Column(String(150), default="")
    setor = Column(String(50), default="")
    origem = Column(String(50), default="menu normal")
    modelo = Column(String(100), default="")
    ano_modelo = Column(String(20), default="")
    revisao = Column(String(50), default="")
    data_agendamento = Column(String(30), default="")
    horario_agendamento = Column(String(20), default="")
    status = Column(String(100), default="aberto")
    atendimento_humano = Column(String(10), default="não")
    item_adicional = Column(Text, default="")
    etapa = Column(String(100), default="")
    cpf = Column(String(30), default="")
    criado_em = Column(DateTime, default=datetime.now)


def criar_banco():
    Base.metadata.create_all(bind=engine)