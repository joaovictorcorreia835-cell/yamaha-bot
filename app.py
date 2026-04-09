from flask import Flask, request, jsonify, render_template_string, send_from_directory
import os
import re
import time
import json
import threading
import requests

from datetime import datetime, timedelta
from collections import defaultdict

from dotenv import load_dotenv

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    func
)
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

app = Flask(__name__)

# =========================================================
# CONFIG
# =========================================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "https://SEU-APP.onrender.com")
PORT = int(os.getenv("PORT", "5000"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha.db")

# Integração opcional com IA externa
IA_API_URL = os.getenv("IA_API_URL", "")
IA_API_KEY = os.getenv("IA_API_KEY", "")
IA_MODEL = os.getenv("IA_MODEL", "gpt-4o-mini")

URL_ENVIO = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
URL_DOCUMENTO = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"

TEMPO_INATIVIDADE = 900  # 15 minutos
INTERVALO_WORKER = 60    # worker follow-up a cada 60s

# =========================================================
# BANCO DE DADOS
# =========================================================
Base = declarative_base()

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine)


class Atendimento(Base):
    __tablename__ = "atendimentos"

    id = Column(Integer, primary_key=True)
    telefone = Column(String, index=True)
    nome = Column(String)
    cpf = Column(String)
    setor = Column(String)
    modelo = Column(String)
    ano = Column(String)
    revisao = Column(String)
    data_agendada = Column(String)
    horario = Column(String)
    itens = Column(Text)
    origem = Column(String, default="Menu Normal")
    status = Column(String, default="aberto")

    atendimento_humano = Column(Boolean, default=False)

    # Fase 2 / 3
    etapa_atual = Column(String)
    intencao = Column(String)
    resumo_ia = Column(Text)
    ultima_mensagem_cliente = Column(Text)

    ultima_interacao = Column(DateTime, default=datetime.now)
    proximo_followup = Column(DateTime, nullable=True)
    tentativas_followup = Column(Integer, default=0)
    tipo_followup = Column(String)
    status_lead = Column(String, default="novo")
    motivo_pausa = Column(String)
    followup_ativo = Column(Boolean, default=False)

    data = Column(DateTime, default=datetime.now)


def criar_banco():
    Base.metadata.create_all(bind=engine)


criar_banco()

# =========================================================
# MEMÓRIA EM TEMPO DE EXECUÇÃO
# =========================================================
clientes = {}
mensagens_processadas = {}
lock_processados = threading.Lock()

MODELOS_YAMAHA = [
    "Fazer 250", "FZ15", "Crosser", "Lander", "MT03", "MT07",
    "R15", "R3", "FLUO", "NEO", "NMAX", "TENERE 700", "AEROX"
]

MENU_PRINCIPAL = (
    "Olá 👋\n\n"
    "Bem-vindo ao *Pós-Vendas Motoshow Yamaha* 🏍️\n"
    "Estamos prontos para ajudar com revisões, peças, garantia e serviços.\n\n"
    "*Escolha uma opção:*\n"
    "1️⃣ Agendar Revisão\n"
    "2️⃣ Peças\n"
    "3️⃣ Acessórios\n"
    "4️⃣ Garantia\n"
    "5️⃣ Logista / Atacado\n"
    "6️⃣ Falar com Atendente\n\n"
    "Digite o número da opção desejada.\n\n"
    "*Equipe Motoshow Yamaha*"
)

SUBMENU_PECAS = (
    "🔧 *Peças Yamaha*\n\n"
    "1️⃣ Orçamento de Peças\n"
    "2️⃣ Consultar Disponibilidade\n"
    "3️⃣ Falar com Atendente\n"
    "4️⃣ Voltar ao Menu"
)

SUBMENU_ACESSORIOS = (
    "🛍️ *Acessórios Yamaha*\n\n"
    "1️⃣ Solicitar Orçamento\n"
    "2️⃣ Catálogo de Acessórios\n"
    "3️⃣ Falar com Atendente\n"
    "4️⃣ Voltar ao Menu"
)

SUBMENU_GARANTIA = (
    "🛡️ *Garantia*\n\n"
    "1️⃣ Nova Solicitação\n"
    "2️⃣ Acompanhar Garantia\n"
    "3️⃣ Falar com Atendente\n"
    "4️⃣ Voltar ao Menu"
)

SUBMENU_ATACADO = (
    "📦 *Logista / Atacado*\n\n"
    "1️⃣ Solicitar Cotação\n"
    "2️⃣ Cadastro de Logista\n"
    "3️⃣ Receber Catálogo PDF\n"
    "4️⃣ Falar com Consultor\n"
    "5️⃣ Voltar ao Menu"
)

# =========================================================
# LOG
# =========================================================
def log_info(*args):
    print("[INFO]", *args)


def log_erro(*args):
    print("[ERRO]", *args)


# =========================================================
# HELPERS GERAIS
# =========================================================
def agora():
    return datetime.now()


def limpar_texto(texto):
    if not texto:
        return ""
    return str(texto).strip()


def normalizar(texto):
    texto = limpar_texto(texto).lower()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def somente_numeros(valor):
    return re.sub(r"\D", "", str(valor or ""))


def telefone_eh_grupo(telefone):
    return "@g.us" in str(telefone or "")


def dentro_horario_comercial():
    agora_local = agora()
    weekday = agora_local.weekday()  # 0 seg ... 6 dom
    hora = agora_local.hour
    minuto = agora_local.minute

    minutos = hora * 60 + minuto

    if weekday <= 4:  # seg-sex
        return 8 * 60 <= minutos <= 18 * 60
    elif weekday == 5:  # sábado
        return 8 * 60 <= minutos <= 12 * 60
    return False


def evento_eh_do_proprio_bot(payload):
    try:
        if payload.get("fromMe") is True:
            return True

        data = payload.get("data", {})
        if isinstance(data, dict):
            if data.get("fromMe") is True:
                return True
            message = data.get("message", {})
            if isinstance(message, dict) and message.get("fromMe") is True:
                return True
    except Exception:
        pass
    return False


def extrair_telefone(payload):
    candidatos = [
        payload.get("phone"),
        payload.get("from"),
        payload.get("chatId"),
        payload.get("sender"),
    ]

    data = payload.get("data", {})
    if isinstance(data, dict):
        candidatos.extend([
            data.get("phone"),
            data.get("from"),
            data.get("chatId"),
            data.get("sender"),
        ])
        message = data.get("message", {})
        if isinstance(message, dict):
            candidatos.extend([
                message.get("phone"),
                message.get("from"),
                message.get("chatId"),
                message.get("sender"),
            ])

    for item in candidatos:
        if item:
            return str(item)
    return None


def extrair_message_id(payload):
    candidatos = [
        payload.get("messageId"),
        payload.get("id"),
        payload.get("msgId"),
    ]

    data = payload.get("data", {})
    if isinstance(data, dict):
        candidatos.extend([
            data.get("messageId"),
            data.get("id"),
            data.get("msgId"),
        ])

        message = data.get("message", {})
        if isinstance(message, dict):
            candidatos.extend([
                message.get("messageId"),
                message.get("id"),
                message.get("msgId"),
                message.get("_id"),
            ])

    for item in candidatos:
        if item:
            return str(item)

    return None


def extrair_mensagem_texto(payload):
    campos = []

    data = payload.get("data", {})
    if isinstance(data, dict):
        message = data.get("message", {})
        if isinstance(message, dict):
            campos.extend([
                message.get("text"),
                message.get("conversation"),
                message.get("caption"),
            ])
            extended = message.get("extendedTextMessage", {})
            if isinstance(extended, dict):
                campos.append(extended.get("text"))

    campos.extend([
        payload.get("text"),
        payload.get("message"),
        payload.get("body"),
        payload.get("caption"),
    ])

    for campo in campos:
        if isinstance(campo, str) and campo.strip():
            return campo.strip()

    return ""


def mensagem_ja_processada(message_id):
    if not message_id:
        return False

    with lock_processados:
        if message_id in mensagens_processadas:
            return True

        mensagens_processadas[message_id] = time.time()

        agora_ts = time.time()
        expirados = [
            chave for chave, ts in mensagens_processadas.items()
            if agora_ts - ts > 3600
        ]
        for chave in expirados:
            mensagens_processadas.pop(chave, None)

    return False


def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = {
            "telefone": telefone,
            "etapa": "menu",
            "origem": "Menu Normal",
            "modelo_moto": "",
            "nome_cliente": "",
            "cpf": "",
            "ano_moto": "",
            "revisao_numero": "",
            "dia_semana": "",
            "data_escolhida": "",
            "horario_escolhido": "",
            "itens_venda": "",
            "setor": "",
            "status_lead": "novo",
            "motivo_pausa": "",
            "ultima_interacao": agora(),
            "atendimento_humano": False,
            "ultima_mensagem_cliente": "",
            "resumo_ia": ""
        }


def resetar_cliente(telefone):
    origem = clientes.get(telefone, {}).get("origem", "Menu Normal")
    clientes[telefone] = {
        "telefone": telefone,
        "etapa": "menu",
        "origem": origem,
        "modelo_moto": "",
        "nome_cliente": "",
        "cpf": "",
        "ano_moto": "",
        "revisao_numero": "",
        "dia_semana": "",
        "data_escolhida": "",
        "horario_escolhido": "",
        "itens_venda": "",
        "setor": "",
        "status_lead": "novo",
        "motivo_pausa": "",
        "ultima_interacao": agora(),
        "atendimento_humano": False,
        "ultima_mensagem_cliente": "",
        "resumo_ia": ""
    }


def atualizar_interacao(telefone, texto_recebido=""):
    iniciar_cliente(telefone)
    clientes[telefone]["ultima_interacao"] = agora()
    if texto_recebido:
        clientes[telefone]["ultima_mensagem_cliente"] = texto_recebido

    db = SessionLocal()
    try:
        registro = (
            db.query(Atendimento)
            .filter(Atendimento.telefone == telefone)
            .order_by(Atendimento.id.desc())
            .first()
        )
        if registro:
            registro.ultima_interacao = agora()
            if texto_recebido:
                registro.ultima_mensagem_cliente = texto_recebido
            db.commit()
    except Exception as e:
        db.rollback()
        log_erro("Erro ao atualizar interação:", e)
    finally:
        db.close()
# =========================================================
# Z-API
# =========================================================
def enviar_mensagem(numero, mensagem):
    try:
        headers = {"Client-Token": ZAPI_CLIENT_TOKEN}
        payload = {
            "phone": numero,
            "message": mensagem
        }
        resposta = requests.post(URL_ENVIO, json=payload, headers=headers, timeout=20)
        log_info("Mensagem enviada:", numero, resposta.status_code, resposta.text[:300])
        return resposta.ok
    except Exception as e:
        log_erro("Erro ao enviar mensagem:", e)
        return False


def enviar_documento_pdf(numero, nome_arquivo, legenda="📄 Catálogo Atacado Motoshow Yamaha"):
    try:
        headers = {"Client-Token": ZAPI_CLIENT_TOKEN}
        url_pdf = f"{BASE_URL}/pdf/{nome_arquivo}"
        payload = {
            "phone": numero,
            "document": url_pdf,
            "fileName": nome_arquivo,
            "caption": legenda
        }
        resposta = requests.post(URL_DOCUMENTO, json=payload, headers=headers, timeout=30)
        log_info("Documento enviado:", numero, resposta.status_code, resposta.text[:300])
        return resposta.ok
    except Exception as e:
        log_erro("Erro ao enviar PDF:", e)
        return False


@app.route("/pdf/<path:arquivo>")
def servir_pdf(arquivo):
    return send_from_directory("static/pdfs", arquivo)


# =========================================================
# CAMADA CONVERSACIONAL / IA
# =========================================================
def chamar_ia_externa(prompt_sistema, prompt_usuario):
    """
    Integração opcional e genérica.
    Se IA_API_URL e IA_API_KEY não estiverem preenchidos, usa fallback local.
    """
    if not IA_API_URL or not IA_API_KEY:
        return None

    try:
        headers = {
            "Authorization": f"Bearer {IA_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": IA_MODEL,
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            "temperature": 0.4
        }

        resp = requests.post(IA_API_URL, headers=headers, json=payload, timeout=35)
        if not resp.ok:
            log_erro("IA externa retornou erro:", resp.status_code, resp.text[:300])
            return None

        data = resp.json()

        # Tentativa de parse mais comum
        if isinstance(data, dict):
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content")
                if content:
                    return str(content).strip()

            # fallback alternativo
            if "output_text" in data:
                return str(data["output_text"]).strip()

        return None

    except Exception as e:
        log_erro("Erro ao chamar IA externa:", e)
        return None


def classificar_intencao_local(texto):
    t = normalizar(texto)

    if any(p in t for p in ["atendente", "humano", "falar com alguem", "consultor"]):
        return "humano"
    if any(p in t for p in ["revisao", "agendar", "agendamento", "manutencao"]):
        return "revisao"
    if any(p in t for p in ["peca", "peças", "pecas", "disponibilidade", "codigo da peça", "código da peça"]):
        return "pecas"
    if any(p in t for p in ["acessorio", "acessório", "slider", "bau", "baú", "protetor"]):
        return "acessorios"
    if any(p in t for p in ["garantia", "cobertura", "solicitação de garantia"]):
        return "garantia"
    if any(p in t for p in ["atacado", "logista", "cotacao", "cotação", "catalogo", "catálogo"]):
        return "atacado"
    if any(p in t for p in ["oi", "ola", "olá", "bom dia", "boa tarde", "boa noite", "menu"]):
        return "menu"
    return "geral"


def gerar_resumo_local(dados):
    nome = dados.get("nome_cliente") or "Cliente"
    setor = dados.get("setor") or "não definido"
    modelo = dados.get("modelo_moto") or "não informado"
    etapa = dados.get("etapa") or "menu"
    revisao = dados.get("revisao_numero") or "não informada"
    ultima = dados.get("ultima_mensagem_cliente") or ""

    return (
        f"Cliente: {nome}. "
        f"Setor: {setor}. "
        f"Modelo: {modelo}. "
        f"Etapa atual: {etapa}. "
        f"Revisão: {revisao}. "
        f"Última mensagem do cliente: {ultima}"
    )


def gerar_resumo_ia(dados):
    prompt_sistema = (
        "Você resume atendimentos de pós-vendas de concessionária Yamaha. "
        "Gere um resumo curto, útil para retomar o cliente depois."
    )
    prompt_usuario = json.dumps(dados, ensure_ascii=False)

    resposta = chamar_ia_externa(prompt_sistema, prompt_usuario)
    if resposta:
        return resposta

    return gerar_resumo_local(dados)


def gerar_resposta_natural(telefone, mensagem_base, objetivo="resposta"):
    dados = clientes.get(telefone, {})
    nome = dados.get("nome_cliente") or ""
    setor = dados.get("setor") or ""

    prompt_sistema = (
        "Você é um assistente comercial cordial e profissional do Pós-Vendas Motoshow Yamaha. "
        "Reescreva a mensagem de forma natural, humana, objetiva e profissional, "
        "mantendo o sentido original e sem inventar informações."
    )
    prompt_usuario = (
        f"Objetivo: {objetivo}\n"
        f"Nome do cliente: {nome}\n"
        f"Setor: {setor}\n"
        f"Mensagem base: {mensagem_base}"
    )

    resposta = chamar_ia_externa(prompt_sistema, prompt_usuario)
    if resposta:
        return resposta

    return mensagem_base


def gerar_followup_inteligente(telefone):
    dados = clientes.get(telefone, {})
    nome = dados.get("nome_cliente") or "Tudo bem"
    setor = dados.get("setor") or "atendimento"
    modelo = dados.get("modelo_moto") or "sua Yamaha"
    revisao = dados.get("revisao_numero") or ""
    etapa = dados.get("etapa") or "menu"
    tentativas = dados.get("tentativas_followup", 0)
    resumo = dados.get("resumo_ia") or gerar_resumo_local(dados)

    prompt_sistema = (
        "Você cria mensagens curtas de follow-up para clientes de concessionária Yamaha. "
        "Tom: profissional, cordial, natural e comercial leve. "
        "Objetivo: retomar atendimento sem parecer insistente."
    )

    prompt_usuario = (
        f"Cliente: {nome}\n"
        f"Setor: {setor}\n"
        f"Modelo: {modelo}\n"
        f"Revisão: {revisao}\n"
        f"Etapa: {etapa}\n"
        f"Tentativas: {tentativas}\n"
        f"Resumo: {resumo}\n"
        f"Gere uma única mensagem curta de follow-up."
    )

    resposta = chamar_ia_externa(prompt_sistema, prompt_usuario)
    if resposta:
        return resposta

    if setor == "Revisão":
        if tentativas == 0:
            return (
                f"Olá {nome} 👋\n\n"
                f"Percebi que seu atendimento da revisão da {modelo} ficou em aberto.\n"
                f"Posso continuar seu agendamento por aqui?"
            )
        elif tentativas == 1:
            return (
                f"Olá {nome} 👋\n\n"
                f"Ainda consigo te ajudar com o agendamento da revisão da {modelo}.\n"
                f"Se quiser, eu já sigo com a próxima etapa."
            )
        else:
            return (
                f"Olá {nome} 👋\n\n"
                f"Estou passando para verificar se ainda deseja seguir com seu atendimento da {modelo}.\n"
                f"Se quiser continuar, é só me responder por aqui."
            )

    if setor == "Peças":
        return (
            f"Olá {nome} 👋\n\n"
            f"Estou retornando sobre sua solicitação de peças para a {modelo}.\n"
            f"Se quiser, posso deixar o atendimento encaminhado para a equipe."
        )

    if setor == "Acessórios":
        return (
            f"Olá {nome} 👋\n\n"
            f"Passando para saber se ainda deseja receber apoio sobre acessórios para a {modelo}.\n"
            f"Se quiser, continuo seu atendimento por aqui."
        )

    if setor == "Garantia":
        return (
            f"Olá {nome} 👋\n\n"
            f"Estou retornando sobre seu atendimento de garantia.\n"
            f"Se quiser, posso dar continuidade por aqui."
        )

    if setor == "Atacado":
        return (
            f"Olá {nome} 👋\n\n"
            f"Passando para verificar se ainda deseja seguir com o atendimento de atacado/logista.\n"
            f"Se quiser, posso continuar por aqui."
        )

    return (
        f"Olá {nome} 👋\n\n"
        f"Estou retornando seu atendimento com a equipe Motoshow Yamaha.\n"
        f"Se quiser continuar, é só me responder por aqui."
    )


# =========================================================
# BANCO - FUNÇÕES DE APOIO
# =========================================================
def obter_ou_criar_atendimento(telefone):
    db = SessionLocal()
    try:
        registro = (
            db.query(Atendimento)
            .filter(Atendimento.telefone == telefone)
            .order_by(Atendimento.id.desc())
            .first()
        )

        if not registro:
            registro = Atendimento(
                telefone=telefone,
                ultima_interacao=agora(),
                status="aberto",
                status_lead="novo"
            )
            db.add(registro)
            db.commit()
            db.refresh(registro)

        return registro.id
    except Exception as e:
        db.rollback()
        log_erro("Erro obter_ou_criar_atendimento:", e)
        return None
    finally:
        db.close()


def salvar_contexto_cliente(telefone):
    iniciar_cliente(telefone)
    dados = clientes[telefone]

    db = SessionLocal()
    try:
        registro = (
            db.query(Atendimento)
            .filter(Atendimento.telefone == telefone)
            .order_by(Atendimento.id.desc())
            .first()
        )

        if not registro:
            registro = Atendimento(telefone=telefone)
            db.add(registro)

        registro.nome = dados.get("nome_cliente")
        registro.cpf = dados.get("cpf")
        registro.setor = dados.get("setor")
        registro.modelo = dados.get("modelo_moto")
        registro.ano = dados.get("ano_moto")
        registro.revisao = dados.get("revisao_numero")
        registro.data_agendada = dados.get("data_escolhida")
        registro.horario = dados.get("horario_escolhido")
        registro.itens = dados.get("itens_venda")
        registro.origem = dados.get("origem", "Menu Normal")
        registro.etapa_atual = dados.get("etapa")
        registro.intencao = dados.get("setor")
        registro.ultima_interacao = dados.get("ultima_interacao", agora())
        registro.atendimento_humano = dados.get("atendimento_humano", False)
        registro.ultima_mensagem_cliente = dados.get("ultima_mensagem_cliente", "")
        registro.status_lead = dados.get("status_lead", "novo")
        registro.motivo_pausa = dados.get("motivo_pausa", "")
        registro.resumo_ia = gerar_resumo_ia(dados)

        db.commit()
    except Exception as e:
        db.rollback()
        log_erro("Erro salvar_contexto_cliente:", e)
    finally:
        db.close()


def atualizar_status_lead(telefone, status_lead, motivo_pausa=None):
    iniciar_cliente(telefone)
    clientes[telefone]["status_lead"] = status_lead
    if motivo_pausa is not None:
        clientes[telefone]["motivo_pausa"] = motivo_pausa

    db = SessionLocal()
    try:
        registro = (
            db.query(Atendimento)
            .filter(Atendimento.telefone == telefone)
            .order_by(Atendimento.id.desc())
            .first()
        )
        if registro:
            registro.status_lead = status_lead
            if motivo_pausa is not None:
                registro.motivo_pausa = motivo_pausa
            registro.ultima_interacao = agora()
            db.commit()
    except Exception as e:
        db.rollback()
        log_erro("Erro atualizar_status_lead:", e)
    finally:
        db.close()


def cancelar_followup(telefone):
    db = SessionLocal()
    try:
        registro = (
            db.query(Atendimento)
            .filter(Atendimento.telefone == telefone)
            .order_by(Atendimento.id.desc())
            .first()
        )
        if registro:
            registro.followup_ativo = False
            registro.proximo_followup = None
            db.commit()
    except Exception as e:
        db.rollback()
        log_erro("Erro cancelar_followup:", e)
    finally:
        db.close()
def agendar_followup(telefone, minutos=30, tipo_followup="reativacao_cliente", motivo="sem_resposta"):
    iniciar_cliente(telefone)
    clientes[telefone]["status_lead"] = "followup_pendente"
    clientes[telefone]["motivo_pausa"] = motivo

    db = SessionLocal()
    try:
        registro = (
            db.query(Atendimento)
            .filter(Atendimento.telefone == telefone)
            .order_by(Atendimento.id.desc())
            .first()
        )
        if not registro:
            registro = Atendimento(telefone=telefone)
            db.add(registro)

        registro.followup_ativo = True
        registro.proximo_followup = agora() + timedelta(minutes=minutos)
        registro.tipo_followup = tipo_followup
        registro.status_lead = "followup_pendente"
        registro.motivo_pausa = motivo
        registro.resumo_ia = gerar_resumo_ia(clientes[telefone])
        db.commit()
    except Exception as e:
        db.rollback()
        log_erro("Erro agendar_followup:", e)
    finally:
        db.close()


def ativar_atendimento_humano(telefone, setor="Humano"):
    iniciar_cliente(telefone)
    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["setor"] = setor
    clientes[telefone]["status_lead"] = "humano"
    clientes[telefone]["etapa"] = "atendimento_humano"

    cancelar_followup(telefone)
    salvar_contexto_cliente(telefone)

    enviar_mensagem(
        telefone,
        "👨‍💼 *Atendimento Humano*\n\n"
        "Seu atendimento foi direcionado para nossa equipe.\n"
        "Em instantes um consultor dará continuidade.\n\n"
        "*Equipe Motoshow Yamaha*"
    )


def encerrar_atendimento_convertido(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["status_lead"] = "convertido"
    cancelar_followup(telefone)
    salvar_contexto_cliente(telefone)
    atualizar_status_lead(telefone, "convertido")


def processar_inatividade():
    agora_local = agora()
    for telefone, dados in list(clientes.items()):
        ultima = dados.get("ultima_interacao")
        if not ultima:
            continue

        if dados.get("atendimento_humano"):
            continue

        delta = (agora_local - ultima).total_seconds()
        if delta >= TEMPO_INATIVIDADE and dados.get("etapa") != "menu":
            enviar_mensagem(
                telefone,
                "⏳ *Atendimento encerrado por inatividade*\n\n"
                "Seu atendimento foi pausado por falta de interação.\n"
                "Quando quiser continuar, envie *menu* e retomamos por aqui.\n\n"
                "*Equipe Motoshow Yamaha*"
            )

            dados["status_lead"] = "aguardando_cliente"
            dados["motivo_pausa"] = "inatividade"
            salvar_contexto_cliente(telefone)
            agendar_followup(telefone, minutos=60, tipo_followup="reativacao_cliente", motivo="inatividade")
            resetar_cliente(telefone)


def buscar_followups_pendentes():
    db = SessionLocal()
    try:
        return (
            db.query(Atendimento)
            .filter(
                Atendimento.followup_ativo == True,
                Atendimento.proximo_followup != None,
                Atendimento.proximo_followup <= agora(),
                Atendimento.status_lead.in_(["followup_pendente", "aguardando_cliente", "novo"])
            )
            .all()
        )
    except Exception as e:
        log_erro("Erro buscar_followups_pendentes:", e)
        return []
    finally:
        db.close()


def processar_followups():
    if not dentro_horario_comercial():
        return

    pendentes = buscar_followups_pendentes()
    if not pendentes:
        return

    db = SessionLocal()
    try:
        for registro in pendentes:
            if registro.tentativas_followup >= 3:
                registro.followup_ativo = False
                registro.status_lead = "sem_retorno"
                continue

            telefone = registro.telefone
            iniciar_cliente(telefone)

            # sincroniza memória básica
            clientes[telefone]["nome_cliente"] = registro.nome or clientes[telefone].get("nome_cliente", "")
            clientes[telefone]["setor"] = registro.setor or clientes[telefone].get("setor", "")
            clientes[telefone]["modelo_moto"] = registro.modelo or clientes[telefone].get("modelo_moto", "")
            clientes[telefone]["revisao_numero"] = registro.revisao or clientes[telefone].get("revisao_numero", "")
            clientes[telefone]["etapa"] = registro.etapa_atual or clientes[telefone].get("etapa", "menu")
            clientes[telefone]["resumo_ia"] = registro.resumo_ia or ""
            clientes[telefone]["tentativas_followup"] = registro.tentativas_followup or 0

            mensagem = gerar_followup_inteligente(telefone)
            ok = enviar_mensagem(telefone, mensagem)

            if ok:
                registro.tentativas_followup = (registro.tentativas_followup or 0) + 1
                registro.status_lead = "followup_enviado"

                if registro.tentativas_followup >= 3:
                    registro.followup_ativo = False
                    registro.proximo_followup = None
                else:
                    registro.followup_ativo = True
                    registro.proximo_followup = agora() + timedelta(hours=6)

        db.commit()
    except Exception as e:
        db.rollback()
        log_erro("Erro processar_followups:", e)
    finally:
        db.close()


def worker_followup():
    while True:
        try:
            processar_inatividade()
            processar_followups()
        except Exception as e:
            log_erro("Erro no worker:", e)

        time.sleep(INTERVALO_WORKER)


def iniciar_worker():
    t = threading.Thread(target=worker_followup, daemon=True)
    t.start()


# =========================================================
# REGRAS DE NEGÓCIO
# =========================================================
def obter_horarios_disponiveis(revisao_numero, dia_semana):
    revisao_txt = normalizar(revisao_numero)
    dia_txt = normalizar(dia_semana)

    primeira_ou_segunda = revisao_txt in ["1", "1a", "1ª", "2", "2a", "2ª"]

    if dia_txt in ["sabado", "sábado"]:
        if primeira_ou_segunda:
            return ["08:00", "09:00", "10:00"]
        return []

    if dia_txt in ["segunda", "terca", "terça", "quarta", "quinta", "sexta"]:
        if primeira_ou_segunda:
            return [
                "08:00", "09:00", "10:00", "11:00",
                "12:00", "13:00", "14:00", "15:00"
            ]
        return ["08:00"]

    return []


def montar_lista_modelos():
    linhas = ["🏍️ *Escolha o modelo da moto:*"]
    for i, modelo in enumerate(MODELOS_YAMAHA, start=1):
        linhas.append(f"{i}️⃣ {modelo}")
    return "\n".join(linhas)


def montar_lista_horarios(horarios):
    linhas = ["🕐 *Escolha o horário:*"]
    for i, h in enumerate(horarios, start=1):
        linhas.append(f"{i}️⃣ {h}")
    return "\n".join(linhas)


def menu_ou_saudacao(texto):
    t = normalizar(texto)
    gatilhos = ["menu", "oi", "ola", "olá", "bom dia", "boa tarde", "boa noite", "iniciar"]
    return any(g in t for g in gatilhos)


def confirmar_agendamento(telefone):
    d = clientes[telefone]
    resumo = (
        "✅ *Agendamento Registrado com Sucesso*\n\n"
        f"👤 *Nome:* {d.get('nome_cliente')}\n"
        f"🪪 *CPF:* {d.get('cpf')}\n"
        f"🏍️ *Modelo:* {d.get('modelo_moto')}\n"
        f"📅 *Revisão:* {d.get('revisao_numero')}\n"
        f"📆 *Dia:* {d.get('dia_semana')}\n"
        f"🗓️ *Data:* {d.get('data_escolhida')}\n"
        f"⏰ *Horário:* {d.get('horario_escolhido')}\n"
        f"🛍️ *Venda adicional:* {d.get('itens_venda') or 'Nenhum item'}\n\n"
        "Nossa equipe confirma com você por aqui.\n\n"
        "*Equipe Motoshow Yamaha*"
    )
    enviar_mensagem(telefone, gerar_resposta_natural(telefone, resumo, "confirmacao_agendamento"))
    encerrar_atendimento_convertido(telefone)
    resetar_cliente(telefone)


# =========================================================
# DASHBOARD V2
# =========================================================
@app.route("/")
def home():
    return "BOT YAMAHA ONLINE", 200


@app.route("/dashboard")
def dashboard():
    db = SessionLocal()
    try:
        total = db.query(func.count(Atendimento.id)).scalar() or 0
        humanos = db.query(func.count(Atendimento.id)).filter(Atendimento.atendimento_humano == True).scalar() or 0
        convertidos = db.query(func.count(Atendimento.id)).filter(Atendimento.status_lead == "convertido").scalar() or 0
        followups = db.query(func.count(Atendimento.id)).filter(Atendimento.tentativas_followup > 0).scalar() or 0

        por_setor = (
            db.query(Atendimento.setor, func.count(Atendimento.id))
            .group_by(Atendimento.setor)
            .all()
        )

        por_status = (
            db.query(Atendimento.status_lead, func.count(Atendimento.id))
            .group_by(Atendimento.status_lead)
            .all()
        )

        html = """
        <html>
        <head>
            <title>Dashboard CRM - Motoshow Yamaha</title>
            <style>
                body { font-family: Arial; background:#f4f6f9; margin:0; padding:20px; }
                h1 { color:#0a2c66; }
                .grid { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:24px; }
                .card { background:white; border-radius:16px; padding:20px; box-shadow:0 2px 12px rgba(0,0,0,0.08); }
                .num { font-size:32px; font-weight:bold; color:#0a2c66; }
                table { width:100%; border-collapse:collapse; background:white; border-radius:16px; overflow:hidden; }
                th, td { padding:12px; border-bottom:1px solid #eee; text-align:left; }
                th { background:#0a2c66; color:white; }
            </style>
        </head>
        <body>
            <h1>📊 Dashboard CRM - Pós-Vendas Motoshow Yamaha</h1>

            <div class="grid">
                <div class="card"><div>Total de Atendimentos</div><div class="num">{{ total }}</div></div>
                <div class="card"><div>Atendimento Humano</div><div class="num">{{ humanos }}</div></div>
                <div class="card"><div>Convertidos</div><div class="num">{{ convertidos }}</div></div>
                <div class="card"><div>Follow-ups Enviados</div><div class="num">{{ followups }}</div></div>
            </div>

            <div class="card" style="margin-bottom:24px;">
                <h2>Atendimentos por Setor</h2>
                <table>
                    <tr><th>Setor</th><th>Total</th></tr>
                    {% for setor, qtd in por_setor %}
                    <tr><td>{{ setor or 'Não informado' }}</td><td>{{ qtd }}</td></tr>
                    {% endfor %}
                </table>
            </div>

            <div class="card">
                <h2>Status do Lead</h2>
                <table>
                    <tr><th>Status</th><th>Total</th></tr>
                    {% for status, qtd in por_status %}
                    <tr><td>{{ status or 'Não informado' }}</td><td>{{ qtd }}</td></tr>
                    {% endfor %}
                </table>
            </div>
        </body>
        </html>
        """
        return render_template_string(
            html,
            total=total,
            humanos=humanos,
            convertidos=convertidos,
            followups=followups,
            por_setor=por_setor,
            por_status=por_status
        )
    finally:
        db.close()


# =========================================================
# WEBHOOK
# =========================================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    try:
        if evento_eh_do_proprio_bot(payload):
            return jsonify({"status": "ignorado", "motivo": "mensagem do proprio bot"}), 200

        telefone = extrair_telefone(payload)
        texto = limpar_texto(extrair_mensagem_texto(payload))
        message_id = extrair_message_id(payload)

        log_info("TELEFONE:", telefone)
        log_info("MESSAGE_ID:", message_id)
        log_info("TEXTO:", texto)

        if not telefone or telefone_eh_grupo(telefone):
            return jsonify({"status": "ignorado", "motivo": "grupo ou telefone inválido"}), 200

        if not texto:
            return jsonify({"status": "ignorado", "motivo": "evento sem texto"}), 200

        if message_id and mensagem_ja_processada(message_id):
            return jsonify({"status": "ignorado", "motivo": "mensagem duplicada"}), 200

        iniciar_cliente(telefone)
        atualizar_interacao(telefone, texto)

        cancelar_followup(telefone)

        if clientes[telefone].get("atendimento_humano"):
            return jsonify({"status": "ok", "motivo": "em_atendimento_humano"}), 200

        texto_normalizado = normalizar(texto)

        if menu_ou_saudacao(texto):
            if clientes[telefone]["etapa"] != "menu":
                resetar_cliente(telefone)
                enviar_mensagem(telefone, MENU_PRINCIPAL)
                salvar_contexto_cliente(telefone)
            return jsonify({"status": "ok", "rota": "menu"}), 200
        # Fase 2 - classificação básica de intenção a partir do texto livre
        if clientes[telefone]["etapa"] == "menu":
            intencao = classificar_intencao_local(texto)
            if intencao == "revisao":
                texto_normalizado = "1"
            elif intencao == "pecas":
                texto_normalizado = "2"
            elif intencao == "acessorios":
                texto_normalizado = "3"
            elif intencao == "garantia":
                texto_normalizado = "4"
            elif intencao == "atacado":
                texto_normalizado = "5"
            elif intencao == "humano":
                texto_normalizado = "6"

        etapa = clientes[telefone]["etapa"]

        # =================================================
        # MENU PRINCIPAL
        # =================================================
        if etapa == "menu":
            if texto_normalizado == "1":
                clientes[telefone]["setor"] = "Revisão"
                clientes[telefone]["etapa"] = "revisao_modelo"
                atualizar_status_lead(telefone, "em_atendimento")
                enviar_mensagem(telefone, montar_lista_modelos())
                salvar_contexto_cliente(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                clientes[telefone]["setor"] = "Peças"
                clientes[telefone]["etapa"] = "submenu_pecas"
                atualizar_status_lead(telefone, "em_atendimento")
                enviar_mensagem(telefone, SUBMENU_PECAS)
                salvar_contexto_cliente(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                clientes[telefone]["setor"] = "Acessórios"
                clientes[telefone]["etapa"] = "submenu_acessorios"
                atualizar_status_lead(telefone, "em_atendimento")
                enviar_mensagem(telefone, SUBMENU_ACESSORIOS)
                salvar_contexto_cliente(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                clientes[telefone]["setor"] = "Garantia"
                clientes[telefone]["etapa"] = "submenu_garantia"
                atualizar_status_lead(telefone, "em_atendimento")
                enviar_mensagem(telefone, SUBMENU_GARANTIA)
                salvar_contexto_cliente(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "5":
                clientes[telefone]["setor"] = "Atacado"
                clientes[telefone]["etapa"] = "submenu_atacado"
                atualizar_status_lead(telefone, "em_atendimento")
                enviar_mensagem(telefone, SUBMENU_ATACADO)
                salvar_contexto_cliente(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "6":
                ativar_atendimento_humano(telefone, setor="Atendimento Humano")
                return jsonify({"status": "ok"}), 200

            else:
                enviar_mensagem(telefone, MENU_PRINCIPAL)
                return jsonify({"status": "ok"}), 200

        # =================================================
        # FLUXO REVISÃO
        # =================================================
        elif etapa == "revisao_modelo":
            if texto_normalizado.isdigit() and 1 <= int(texto_normalizado) <= len(MODELOS_YAMAHA):
                clientes[telefone]["modelo_moto"] = MODELOS_YAMAHA[int(texto_normalizado) - 1]
            else:
                clientes[telefone]["modelo_moto"] = texto

            clientes[telefone]["etapa"] = "revisao_nome"
            salvar_contexto_cliente(telefone)
            agendar_followup(telefone, minutos=40, tipo_followup="revisao_abandonada", motivo="parou_no_fluxo")
            enviar_mensagem(
                telefone,
                "👤 *Agendamento de Revisão*\n\n"
                "Informe seu *nome completo*:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_nome":
            clientes[telefone]["nome_cliente"] = texto
            clientes[telefone]["etapa"] = "revisao_cpf"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(
                telefone,
                "🪪 Informe o *CPF do proprietário*:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_cpf":
            clientes[telefone]["cpf"] = somente_numeros(texto)
            clientes[telefone]["etapa"] = "revisao_ano"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(
                telefone,
                "📅 Informe o *ano da moto*:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_ano":
            clientes[telefone]["ano_moto"] = texto
            clientes[telefone]["etapa"] = "revisao_numero"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(
                telefone,
                "🔧 Informe qual revisão deseja agendar:\n\n"
                "Exemplo: *1ª, 2ª, 3ª...*"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_numero":
            clientes[telefone]["revisao_numero"] = texto
            clientes[telefone]["etapa"] = "revisao_dia"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(
                telefone,
                "📆 Informe o *dia da semana* desejado:\n\n"
                "segunda, terça, quarta, quinta, sexta ou sábado"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_dia":
            clientes[telefone]["dia_semana"] = texto
            clientes[telefone]["etapa"] = "revisao_data"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(
                telefone,
                "🗓️ Agora informe a *data desejada*.\n\n"
                "Exemplo: *15/04/2026*"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_data":
            clientes[telefone]["data_escolhida"] = texto
            horarios = obter_horarios_disponiveis(
                clientes[telefone]["revisao_numero"],
                clientes[telefone]["dia_semana"]
            )

            if not horarios:
                enviar_mensagem(
                    telefone,
                    "⚠️ Para essa revisão e esse dia informado não temos horários disponíveis.\n"
                    "Envie outro *dia da semana* para continuarmos."
                )
                clientes[telefone]["etapa"] = "revisao_dia"
                salvar_contexto_cliente(telefone)
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["horarios_disponiveis"] = horarios
            clientes[telefone]["etapa"] = "revisao_horario"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, montar_lista_horarios(horarios))
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_horario":
            horarios = clientes[telefone].get("horarios_disponiveis", [])
            if texto_normalizado.isdigit() and 1 <= int(texto_normalizado) <= len(horarios):
                clientes[telefone]["horario_escolhido"] = horarios[int(texto_normalizado) - 1]
                clientes[telefone]["etapa"] = "revisao_venda_adicional"
                salvar_contexto_cliente(telefone)
                enviar_mensagem(
                    telefone,
                    "🛍️ *Venda Adicional*\n\n"
                    "Deseja incluir algum item?\n\n"
                    "1️⃣ Protetor de motor\n"
                    "2️⃣ Slider\n"
                    "3️⃣ Suporte para celular\n"
                    "4️⃣ Baú\n"
                    "0️⃣ Nenhum item\n\n"
                    "Digite os números separados por vírgula."
                )
                return jsonify({"status": "ok"}), 200

            enviar_mensagem(telefone, "Escolha um número válido da lista de horários.")
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_venda_adicional":
            mapa_itens = {
                "1": "Protetor de motor",
                "2": "Slider",
                "3": "Suporte para celular",
                "4": "Baú",
                "0": "Nenhum item"
            }

            escolhidos = [x.strip() for x in texto.split(",") if x.strip()]
            itens = []

            for e in escolhidos:
                if e in mapa_itens and e != "0":
                    itens.append(mapa_itens[e])

            clientes[telefone]["itens_venda"] = ", ".join(itens) if itens else "Nenhum item"
            salvar_contexto_cliente(telefone)
            confirmar_agendamento(telefone)
            return jsonify({"status": "ok"}), 200

        # =================================================
        # SUBMENU PEÇAS
        # =================================================
        elif etapa == "submenu_pecas":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "pecas_nome_item"
                salvar_contexto_cliente(telefone)
                agendar_followup(telefone, minutos=60, tipo_followup="pecas_orcamento", motivo="orcamento_aberto")
                enviar_mensagem(telefone, "🔩 Informe o *nome da peça* desejada:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "pecas_disponibilidade"
                salvar_contexto_cliente(telefone)
                enviar_mensagem(telefone, "📦 Informe a *peça* que deseja consultar:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                ativar_atendimento_humano(telefone, setor="Peças")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                resetar_cliente(telefone)
                enviar_mensagem(telefone, MENU_PRINCIPAL)
                return jsonify({"status": "ok"}), 200

            enviar_mensagem(telefone, SUBMENU_PECAS)
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_nome_item":
            clientes[telefone]["itens_venda"] = texto
            clientes[telefone]["etapa"] = "pecas_modelo"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "🏍️ Informe o *modelo da moto*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_modelo":
            clientes[telefone]["modelo_moto"] = texto
            clientes[telefone]["etapa"] = "pecas_ano"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "📅 Informe o *ano da moto*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_ano":
            clientes[telefone]["ano_moto"] = texto
            clientes[telefone]["etapa"] = "pecas_cor"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "🎨 Informe a *cor da moto*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_cor":
            salvar_contexto_cliente(telefone)
            atualizar_status_lead(telefone, "aguardando_cliente", "aguardando_orcamento_pecas")
            enviar_mensagem(
                telefone,
                "✅ Sua solicitação de peças foi registrada.\n\n"
                "Nossa equipe irá analisar e retornar por aqui.\n\n"
                "*Equipe Motoshow Yamaha*"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_disponibilidade":
            clientes[telefone]["itens_venda"] = texto
            salvar_contexto_cliente(telefone)
            atualizar_status_lead(telefone, "aguardando_cliente", "consulta_disponibilidade")
            enviar_mensagem(
                telefone,
                "📋 Consulta registrada com sucesso.\n"
                "Nossa equipe vai verificar a disponibilidade e retornar por aqui."
            )
            return jsonify({"status": "ok"}), 200

        # =================================================
        # SUBMENU ACESSÓRIOS
        # =================================================
        elif etapa == "submenu_acessorios":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "acessorios_nome"
                salvar_contexto_cliente(telefone)
                agendar_followup(telefone, minutos=60, tipo_followup="acessorios_orcamento", motivo="orcamento_aberto")
                enviar_mensagem(telefone, "🛍️ Informe qual *acessório* deseja:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                ok = enviar_documento_pdf(
                    telefone,
                    "catalogo-atacado.pdf",
                    "📄 Catálogo Motoshow Yamaha"
                )
                if ok:
                    enviar_mensagem(telefone, "✅ Catálogo enviado com sucesso.")
                else:
                    enviar_mensagem(telefone, "⚠️ Não foi possível enviar o catálogo agora. Nossa equipe pode te ajudar.")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                ativar_atendimento_humano(telefone, setor="Acessórios")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                resetar_cliente(telefone)
                enviar_mensagem(telefone, MENU_PRINCIPAL)
                return jsonify({"status": "ok"}), 200

            enviar_mensagem(telefone, SUBMENU_ACESSORIOS)
            return jsonify({"status": "ok"}), 200

        elif etapa == "acessorios_nome":
            clientes[telefone]["itens_venda"] = texto
            clientes[telefone]["etapa"] = "acessorios_modelo"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "🏍️ Informe o *modelo da moto*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "acessorios_modelo":
            clientes[telefone]["modelo_moto"] = texto
            salvar_contexto_cliente(telefone)
            atualizar_status_lead(telefone, "aguardando_cliente", "orcamento_acessorios")
            enviar_mensagem(
                telefone,
                "✅ Solicitação registrada com sucesso.\n"
                "Nossa equipe retornará com as informações por aqui."
            )
            return jsonify({"status": "ok"}), 200

        # =================================================
        # SUBMENU GARANTIA
        # =================================================
        elif etapa == "submenu_garantia":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "garantia_nova_nome"
                salvar_contexto_cliente(telefone)
                enviar_mensagem(telefone, "🛡️ Informe seu *nome completo*:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "garantia_acompanhar_nome"
                salvar_contexto_cliente(telefone)
                enviar_mensagem(telefone, "📋 Informe seu *nome completo*:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                ativar_atendimento_humano(telefone, setor="Garantia")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                resetar_cliente(telefone)
                enviar_mensagem(telefone, MENU_PRINCIPAL)
                return jsonify({"status": "ok"}), 200

            enviar_mensagem(telefone, SUBMENU_GARANTIA)
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_nova_nome":
            clientes[telefone]["nome_cliente"] = texto
            clientes[telefone]["etapa"] = "garantia_nova_descricao"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "📝 Descreva o problema para sua solicitação de garantia:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_nova_descricao":
            clientes[telefone]["motivo_pausa"] = texto
            salvar_contexto_cliente(telefone)
            atualizar_status_lead(telefone, "aguardando_cliente", "garantia_nova")
            enviar_mensagem(
                telefone,
                "✅ Sua solicitação de garantia foi registrada.\n"
                "Nossa equipe irá analisar e retornar por aqui."
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_acompanhar_nome":
            clientes[telefone]["nome_cliente"] = texto
            clientes[telefone]["etapa"] = "garantia_acompanhar_cpf"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "🪪 Informe o *CPF* para localização:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_acompanhar_cpf":
            clientes[telefone]["cpf"] = somente_numeros(texto)
            salvar_contexto_cliente(telefone)
            atualizar_status_lead(telefone, "aguardando_cliente", "acompanhar_garantia")
            enviar_mensagem(
                telefone,
                "📋 Solicitação de acompanhamento registrada.\n"
                "Nossa equipe irá consultar e te retornar por aqui."
            )
            return jsonify({"status": "ok"}), 200

        # =================================================
        # SUBMENU ATACADO
        # =================================================
        elif etapa == "submenu_atacado":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "atacado_empresa"
                salvar_contexto_cliente(telefone)
                agendar_followup(telefone, minutos=90, tipo_followup="atacado_cotacao", motivo="cotacao_aberta")
                enviar_mensagem(telefone, "🏢 Informe o *nome da empresa*:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "logista_empresa"
                salvar_contexto_cliente(telefone)
                enviar_mensagem(telefone, "🏢 Informe o *nome da empresa* para cadastro:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                ok = enviar_documento_pdf(
                    telefone,
                    "catalogo-atacado.pdf",
                    "📄 Catálogo Atacado Motoshow Yamaha"
                )
                if ok:
                    enviar_mensagem(telefone, "✅ Catálogo enviado com sucesso.")
                else:
                    enviar_mensagem(telefone, "⚠️ Não foi possível enviar o catálogo agora.")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                ativar_atendimento_humano(telefone, setor="Atacado")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "5":
                resetar_cliente(telefone)
                enviar_mensagem(telefone, MENU_PRINCIPAL)
                return jsonify({"status": "ok"}), 200

            enviar_mensagem(telefone, SUBMENU_ATACADO)
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_empresa":
            clientes[telefone]["nome_cliente"] = texto
            clientes[telefone]["etapa"] = "atacado_cnpj"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "🧾 Informe o *CNPJ*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_cnpj":
            clientes[telefone]["cpf"] = somente_numeros(texto)
            clientes[telefone]["etapa"] = "atacado_cidade"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "📍 Informe a *cidade*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_cidade":
            clientes[telefone]["ano_moto"] = texto
            clientes[telefone]["etapa"] = "atacado_pecas"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "📦 Informe as *peças desejadas* (código ou modelo):")
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_pecas":
            clientes[telefone]["itens_venda"] = texto
            salvar_contexto_cliente(telefone)
            atualizar_status_lead(telefone, "aguardando_cliente", "cotacao_atacado")
            enviar_mensagem(
                telefone,
                "✅ Solicitação de cotação registrada com sucesso.\n"
                "Nossa equipe comercial retornará por aqui."
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "logista_empresa":
            clientes[telefone]["nome_cliente"] = texto
            clientes[telefone]["etapa"] = "logista_cnpj"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "🧾 Informe o *CNPJ*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "logista_cnpj":
            clientes[telefone]["cpf"] = somente_numeros(texto)
            clientes[telefone]["etapa"] = "logista_responsavel"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "👤 Informe o *nome do responsável*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "logista_responsavel":
            clientes[telefone]["etapa"] = "logista_cidade"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "📍 Informe a *cidade*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "logista_cidade":
            clientes[telefone]["etapa"] = "logista_telefone"
            salvar_contexto_cliente(telefone)
            enviar_mensagem(telefone, "📞 Informe o *telefone para contato*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "logista_telefone":
            salvar_contexto_cliente(telefone)
            atualizar_status_lead(telefone, "aguardando_cliente", "cadastro_logista")
            enviar_mensagem(
                telefone,
                "✅ Cadastro recebido com sucesso.\n"
                "Nossa equipe comercial irá retornar por aqui."
            )
            return jsonify({"status": "ok"}), 200

        # fallback
        enviar_mensagem(telefone, MENU_PRINCIPAL)
        return jsonify({"status": "ok", "fallback": True}), 200

    except Exception as e:
        log_erro("Erro no webhook:", e)
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# =========================================================
# START
# =========================================================
iniciar_worker()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)