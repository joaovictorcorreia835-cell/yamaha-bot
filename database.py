from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///yamaha.db"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Atendimento(Base):
    __tablename__ = "atendimentos"

    id = Column(Integer, primary_key=True)
    telefone = Column(String)
    nome = Column(String)
    setor = Column(String)
    origem = Column(String)
    modelo = Column(String)
    revisao = Column(String)
    horario = Column(String)
    status = Column(String)
    atendimento_humano = Column(String)
    itens = Column(Text)
    data = Column(DateTime, default=datetime.utcnow)


def criar_banco():
    Base.metadata.create_all(bind=engine)