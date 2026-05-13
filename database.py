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

    observacoes = Column(Text, nullable=True)

    origem = Column(String, nullable=True)

    status = Column(String, index=True, nullable=True)

    etapa = Column(String, index=True, nullable=True)

    atendimento_humano = Column(Boolean, default=False)

    concluido = Column(Boolean, default=False)

    # ==========================================
    # IA / BOTÕES / INTERAÇÃO
    # ==========================================
    button_id = Column(String, nullable=True)

    intencao_ia = Column(String, nullable=True)

    id_envio_zapi = Column(String, nullable=True)

    status_retorno = Column(String, nullable=True)

    proxima_acao = Column(String, nullable=True)

    nivel_interesse = Column(String, nullable=True)

    # ==========================================
    # FOLLOW-UP
    # ==========================================
    followup_1 = Column(Boolean, default=False)

    followup_2 = Column(Boolean, default=False)

    followup_3 = Column(Boolean, default=False)

    followup_respondido = Column(Boolean, default=False)

    followup_recuperado = Column(Boolean, default=False)

    ultima_interacao = Column(DateTime, default=datetime.now)

    ultima_mensagem_cliente = Column(DateTime, nullable=True)

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

    status_retorno = Column(
        String,
        default="AGUARDANDO",
        index=True
    )

    button_id = Column(String, nullable=True)

    id_envio_zapi = Column(String, nullable=True)

    intencao_ia = Column(String, nullable=True)

    proxima_acao = Column(String, nullable=True)

    nivel_interesse = Column(String, nullable=True)

    observacoes = Column(Text, nullable=True)

    data_envio = Column(DateTime, nullable=True)

    data_retorno = Column(DateTime, nullable=True)

    ultima_interacao = Column(DateTime, nullable=True)

    criado_em = Column(DateTime, default=datetime.now, index=True)

    atualizado_em = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now
    )


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

    status_retorno = Column(
        String,
        default="AGUARDANDO",
        index=True
    )

    button_id = Column(String, nullable=True)

    id_envio_zapi = Column(String, nullable=True)

    intencao_ia = Column(String, nullable=True)

    proxima_acao = Column(String, nullable=True)

    nivel_interesse = Column(String, nullable=True)

    observacoes = Column(Text, nullable=True)

    data_envio = Column(DateTime, nullable=True)

    data_retorno = Column(DateTime, nullable=True)

    ultima_interacao = Column(DateTime, nullable=True)

    data = Column(DateTime, default=datetime.now, index=True)

    atualizado_em = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now
    )


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

    revisao = Column(String, index=True, nullable=True)

    dia_semana = Column(String, nullable=True)

    data_agendada = Column(String, index=True)

    horario = Column(String, index=True)

    itens = Column(Text, nullable=True)

    venda_adicional = Column(Text, nullable=True)

    status = Column(
        String,
        default="AGENDADO",
        index=True
    )

    observacoes = Column(Text, nullable=True)

    origem = Column(String, default="BOT")

    lembrete_enviado = Column(Boolean, default=False)

    # ==========================================
    # SANCES
    # ==========================================
    sances_status = Column(
        String,
        default="PENDENTE",
        index=True
    )

    sances_enviado = Column(Boolean, default=False)

    sances_protocolo = Column(String, default="")

    sances_erro = Column(Text, default="")

    sances_data_envio = Column(DateTime, nullable=True)

    # ==========================================
    # FILA / RETRY
    # ==========================================
    sances_tentativas = Column(Integer, default=0)

    sances_ultima_tentativa = Column(DateTime, nullable=True)

    sances_ultimo_retorno = Column(Text, default="")

    criado_em = Column(DateTime, default=datetime.now, index=True)

    atualizado_em = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now
    )


# ==========================================
# TABELA CATÁLOGO DE REVISÕES
# ==========================================
class RevisaoCatalogo(Base):
    __tablename__ = "revisoes_catalogo"

    id = Column(Integer, primary_key=True, index=True)

    modelo = Column(String, index=True, nullable=False)

    revisao_numero = Column(
        String,
        index=True,
        nullable=False
    )

    valor = Column(Float, nullable=True)

    tempo_estimado = Column(String, nullable=True)

    itens_trocados = Column(Text, nullable=True)

    itens_verificados = Column(Text, nullable=True)

    descricao_servico = Column(Text, nullable=True)

    observacoes = Column(Text, nullable=True)

    ativo = Column(Boolean, default=True, index=True)

    criado_em = Column(DateTime, default=datetime.now)

    atualizado_em = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now
    )


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

    atualizado_em = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now
    )


# ==========================================
# CRIAR BANCO
# ==========================================
def criar_banco():
    Base.metadata.create_all(bind=engine)