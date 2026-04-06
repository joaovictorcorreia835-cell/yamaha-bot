import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Atendimento(Base):
    __tablename__ = "atendimentos"

    id = Column(Integer, primary_key=True, index=True)
    telefone = Column(String(30), index=True, nullable=False)
    nome = Column(String(150), nullable=True)
    setor = Column(String(50), nullable=True)
    origem = Column(String(50), nullable=True)
    modelo = Column(String(100), nullable=True)
    ano = Column(String(20), nullable=True)
    revisao = Column(String(50), nullable=True)
    horario = Column(String(20), nullable=True)
    status = Column(String(100), nullable=True)
    atendimento_humano = Column(String(10), default="Não")
    itens = Column(Text, nullable=True)
    cpf = Column(String(30), nullable=True)
    km_atual = Column(String(30), nullable=True)
    problema = Column(Text, nullable=True)
    peca_nome = Column(String(150), nullable=True)
    cor = Column(String(50), nullable=True)
    empresa = Column(String(150), nullable=True)
    cnpj = Column(String(50), nullable=True)
    cidade = Column(String(100), nullable=True)
    responsavel = Column(String(150), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)


def criar_banco():
    Base.metadata.create_all(bind=engine)


def salvar_atendimento(
    telefone,
    nome=None,
    setor=None,
    origem=None,
    modelo=None,
    ano=None,
    revisao=None,
    horario=None,
    status=None,
    atendimento_humano="Não",
    itens=None,
    cpf=None,
    km_atual=None,
    problema=None,
    peca_nome=None,
    cor=None,
    empresa=None,
    cnpj=None,
    cidade=None,
    responsavel=None
):
    session = SessionLocal()
    try:
        novo = Atendimento(
            telefone=telefone,
            nome=nome,
            setor=setor,
            origem=origem,
            modelo=modelo,
            ano=ano,
            revisao=revisao,
            horario=horario,
            status=status,
            atendimento_humano=atendimento_humano,
            itens=itens,
            cpf=cpf,
            km_atual=km_atual,
            problema=problema,
            peca_nome=peca_nome,
            cor=cor,
            empresa=empresa,
            cnpj=cnpj,
            cidade=cidade,
            responsavel=responsavel
        )
        session.add(novo)
        session.commit()
        session.refresh(novo)
        return novo
    except Exception as e:
        session.rollback()
        print(f"Erro ao salvar atendimento: {e}")
        return None
    finally:
        session.close()


def listar_atendimentos():
    session = SessionLocal()
    try:
        return session.query(Atendimento).order_by(Atendimento.criado_em.desc()).all()
    finally:
        session.close()


def total_atendimentos():
    session = SessionLocal()
    try:
        return session.query(Atendimento).count()
    finally:
        session.close()


def total_por_setor(nome_setor):
    session = SessionLocal()
    try:
        return session.query(Atendimento).filter(Atendimento.setor == nome_setor).count()
    finally:
        session.close()


def total_agendamentos_concluidos():
    session = SessionLocal()
    try:
        return session.query(Atendimento).filter(
            Atendimento.status == "Agendado"
        ).count()
    finally:
        session.close()


def total_atendimento_humano():
    session = SessionLocal()
    try:
        return session.query(Atendimento).filter(
            Atendimento.atendimento_humano == "Sim"
        ).count()
    finally:
        session.close()


def total_origem(nome_origem):
    session = SessionLocal()
    try:
        return session.query(Atendimento).filter(
            Atendimento.origem == nome_origem
        ).count()
    finally:
        session.close()


def revisoes_mais_solicitadas():
    session = SessionLocal()
    try:
        dados = {}
        registros = session.query(Atendimento).filter(Atendimento.revisao.isnot(None)).all()

        for item in registros:
            revisao = (item.revisao or "").strip()
            if revisao:
                dados[revisao] = dados.get(revisao, 0) + 1

        resultado = [
            {"revisao": revisao, "total": total}
            for revisao, total in sorted(dados.items(), key=lambda x: x[1], reverse=True)
        ]
        return resultado
    finally:
        session.close()


def itens_mais_vendidos():
    session = SessionLocal()
    try:
        contagem = {}
        registros = session.query(Atendimento).filter(Atendimento.itens.isnot(None)).all()

        for registro in registros:
            if not registro.itens:
                continue

            lista_itens = [i.strip() for i in registro.itens.split(",") if i.strip()]
            for item in lista_itens:
                contagem[item] = contagem.get(item, 0) + 1

        resultado = [
            {"nome": nome, "total": total}
            for nome, total in sorted(contagem.items(), key=lambda x: x[1], reverse=True)
        ]
        return resultado
    finally:
        session.close()