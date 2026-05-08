# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, send_from_directory, render_template
import requests
import os
import time
import re
import threading
import uuid
from datetime import datetime, timedelta
from collections import Counter, deque

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from database import criar_banco, SessionLocal, Atendimento, AgendamentoRevisao
from ia_intencao import classificar_intencao, responder_duvida_por_tabela

app = Flask(__name__)
criar_banco()

# ==========================================
# ESTADO EM MEMÓRIA DOS CLIENTES
# ==========================================
clientes = {}

# ==========================================
# LOCK DO FOLLOW-UP
# ==========================================
followup_lock = threading.Lock()

# ==========================================
# CONTROLE DE MENSAGENS PROCESSADAS
# ==========================================
mensagens_processadas = set()
fila_mensagens_processadas = deque(maxlen=5000)


# ==========================================
# CONFIG - Z-API
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "").strip()
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "").strip()
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "").strip()

BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")

URL_ZAPI_SEND_TEXT = (
    f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}"
    f"/token/{ZAPI_TOKEN}/send-text"
)

URL_ZAPI_SEND_BUTTON_LIST = (
    f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}"
    f"/token/{ZAPI_TOKEN}/send-button-list"
)

URL_ZAPI_SEND_DOCUMENT = (
    f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}"
    f"/token/{ZAPI_TOKEN}/send-document/pdf"
)

if not ZAPI_INSTANCE_ID:
    print("[ERRO] ZAPI_INSTANCE_ID não configurado no .env ou Render.", flush=True)

if not ZAPI_TOKEN:
    print("[ERRO] ZAPI_TOKEN não configurado no .env ou Render.", flush=True)

if not ZAPI_CLIENT_TOKEN:
    print("[ERRO] ZAPI_CLIENT_TOKEN não configurado no .env ou Render.", flush=True)

if not BASE_URL:
    print("[ERRO] BASE_URL não configurada no .env ou Render.", flush=True)


# ==========================================
# HEADERS Z-API
# ==========================================
def headers_zapi():
    return {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN,
    }


# ==========================================
# VARIÁVEIS DE AMBIENTE SEGURAS
# ==========================================
def env_int(nome, padrao):
    try:
        valor = str(os.getenv(nome, padrao)).strip()
        return int(valor)
    except Exception:
        return padrao


TEMPO_INATIVIDADE = env_int("TEMPO_INATIVIDADE", 43200)

ARQUIVO_FOLLOWUP = os.getenv("ARQUIVO_FOLLOWUP", "clientes_disparo.xlsx").strip()

INTERVALO_WORKER_FOLLOWUP = env_int("INTERVALO_WORKER_FOLLOWUP", 300)

FOLLOWUP_1_HORAS = env_int("FOLLOWUP_1_HORAS", 48)

FOLLOWUP_2_DIAS = env_int("FOLLOWUP_2_DIAS", 5)


# ==========================================
# PDFS DE ACESSÓRIOS POR MODELO
# ==========================================
MAPA_PDF_ACESSORIOS = {
    "fz15": "acessorios_fz15.pdf",
    "f z 15": "acessorios_fz15.pdf",

    "fz25": "acessorios_fz25.pdf",
    "fazer 250": "acessorios_fz25.pdf",
    "fazer250": "acessorios_fz25.pdf",
    "fazer": "acessorios_fz25.pdf",

    "crosser": "acessorios_crosser.pdf",

    "lander": "acessorios_lander.pdf",
    "lander 250": "acessorios_lander.pdf",

    "tenere": "acessorios_tenere700.pdf",
    "teneré": "acessorios_tenere700.pdf",
    "tenere 700": "acessorios_tenere700.pdf",
    "teneré 700": "acessorios_tenere700.pdf",
    "tenere700": "acessorios_tenere700.pdf",
    "teneré700": "acessorios_tenere700.pdf",
    "t7": "acessorios_tenere700.pdf",

    "aerox": "acessorios_aerox.pdf",

    "factor": "acessorios_factor.pdf",
}

PDF_ACESSORIOS_GERAL = "acessorios.pdf"


# ==========================================
# CONFIG FUTURA SANCES
# mock | real
# ==========================================
SANCES_MODO = (
    os.getenv("SANCES_MODO", "mock") or "mock"
).strip().lower()

SANCES_SIMULAR_RESULTADO = (
    os.getenv(
        "SANCES_SIMULAR_RESULTADO",
        "nao_configurado"
    ) or "nao_configurado"
).strip().lower()

SANCES_TIMEOUT = env_int("SANCES_TIMEOUT", 15)

SANCES_RETRY_MAX = env_int("SANCES_RETRY_MAX", 1)


# ==========================================
# STATUS OFICIAIS DO CRM POS-VENDA
# ==========================================
STATUS_NOVO_ATENDIMENTO = "NOVO_ATENDIMENTO"
STATUS_AGENDAMENTO_INICIADO = "AGENDAMENTO_INICIADO"
STATUS_AGENDADO = "AGENDADO"
STATUS_CONFIRMADO = "CONFIRMADO"
STATUS_REAGENDADO = "REAGENDADO"
STATUS_CANCELADO = "CANCELADO"
STATUS_NAO_COMPARECEU = "NAO_COMPARECEU"
STATUS_EM_EXECUCAO = "EM_EXECUCAO"
STATUS_FINALIZADO = "FINALIZADO"
STATUS_POS_VENDA_ENVIADO = "POS_VENDA_ENVIADO"
STATUS_ATENDIMENTO_HUMANO = "ATENDIMENTO_HUMANO"


# ==========================================
# STATUS INTEGRAÇÃO SANCES
# ==========================================
SANCES_STATUS_PENDENTE = "PENDENTE"
SANCES_STATUS_ENVIADO = "ENVIADO"
SANCES_STATUS_ERRO = "ERRO"
SANCES_STATUS_NAO_CONFIGURADO = "NAO_CONFIGURADO"

# ==========================================
# HOME
# ==========================================
@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"


# ==========================================
# LOG
# ==========================================
def log_info(*args):
    print("[INFO]", *args, flush=True)


def log_erro(*args):
    print("[ERRO]", *args, flush=True)


# ==========================================
# PDFS
# ==========================================
@app.route("/pdf/<path:arquivo>")
def servir_pdf(arquivo):
    try:
        pasta_pdfs = os.path.join(app.root_path, "static", "pdfs")

        arquivo = os.path.basename(str(arquivo or "").strip())

        if not arquivo:
            return "Arquivo inválido", 400

        caminho_arquivo = os.path.join(pasta_pdfs, arquivo)

        if not os.path.exists(caminho_arquivo):
            log_erro("PDF não encontrado:", caminho_arquivo)
            return "Arquivo não encontrado", 404

        return send_from_directory(pasta_pdfs, arquivo)

    except Exception as e:
        log_erro("Erro ao servir PDF:", repr(e))
        return "Erro ao carregar arquivo", 500


# ==========================================
# UTILITÁRIOS GERAIS
# ==========================================
def limpar_texto(texto):
    try:
        return str(texto or "").strip()
    except Exception:
        return ""


def remover_acentos(texto):
    try:
        import unicodedata
        texto = str(texto or "")
        return "".join(
            c for c in unicodedata.normalize("NFD", texto)
            if unicodedata.category(c) != "Mn"
        )
    except Exception:
        return str(texto or "")


def normalizar_texto(texto):
    try:
        texto = limpar_texto(texto).lower()
        texto = remover_acentos(texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto
    except Exception:
        return ""


def limpar_telefone(telefone):
    try:
        telefone = str(telefone or "").strip()
        telefone = (
            telefone.replace("@c.us", "")
            .replace("@s.whatsapp.net", "")
            .replace("@g.us", "")
            .replace("@lid", "")
        )
        return re.sub(r"\D", "", telefone)
    except Exception:
        return ""


def limpar_cpf(cpf):
    try:
        return re.sub(r"\D", "", str(cpf or ""))
    except Exception:
        return ""


def telefone_eh_grupo(telefone):
    texto = str(telefone or "").lower()
    return "@g.us" in texto or texto.endswith("@g.us") or "g.us" in texto


def limpar_opcao(texto):
    try:
        return (
            str(texto or "")
            .replace("️⃣", "")
            .replace("\u200e", "")
            .replace("\u200f", "")
            .strip()
        )
    except Exception:
        return ""


def normalizar_botao_zapi(texto):
    texto_norm = normalizar_texto(texto)
    texto_norm = texto_norm.replace("-", "_").replace(" ", "_").upper()

    mapa = {
        "AGENDAR": "AGENDAR_REVISAO",
        "AGENDAR_REVISAO": "AGENDAR_REVISAO",
        "AGENDAR_REVISÃO": "AGENDAR_REVISAO",

        "FALAR_CONSULTOR": "FALAR_CONSULTOR",
        "FALAR_COM_CONSULTOR": "FALAR_CONSULTOR",
        "CONSULTOR": "FALAR_CONSULTOR",

        "DEPOIS": "DEPOIS",

        "ATACADO_TABELA": "ATACADO_TABELA",
        "QUERO_TABELA": "ATACADO_TABELA",
        "TABELA": "ATACADO_TABELA",

        "ATACADO_CONSULTOR": "ATACADO_CONSULTOR",
        "ATACADO_DEPOIS": "ATACADO_DEPOIS",
    }

    return mapa.get(texto_norm, "")


def agora():
    return time.time()


def agora_datetime():
    return datetime.now()


def parse_data_hora(valor):
    if valor is None:
        return None

    if isinstance(valor, datetime):
        return valor

    texto = str(valor).strip()
    if not texto:
        return None

    formatos = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]

    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt)
        except Exception:
            continue

    try:
        convertido = pd.to_datetime(texto, dayfirst=True, errors="coerce")
        if pd.isna(convertido):
            return None
        return convertido.to_pydatetime()
    except Exception:
        return None


def formatar_data_hora(dt=None):
    try:
        if dt is None:
            dt = datetime.now()
        elif not isinstance(dt, datetime):
            dt = parse_data_hora(dt) or datetime.now()
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return datetime.now().strftime("%d/%m/%Y %H:%M")


def data_texto_valida(valor):
    return parse_data_hora(valor) is not None


def formatar_valor_brl(valor):
    try:
        if isinstance(valor, (int, float)):
            valor_float = float(valor)
        else:
            valor_texto = str(valor).replace("R$", "").strip()
            if "," in valor_texto:
                valor_texto = valor_texto.replace(".", "").replace(",", ".")
            valor_float = float(valor_texto)

        return (
            f"R$ {valor_float:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
    except Exception:
        return f"R$ {valor}"


# ==========================================
# APOIO ACESSÓRIOS
# ==========================================
def normalizar_modelo_acessorio(texto):
    texto = normalizar_texto(texto)
    texto = re.sub(r"[^a-zA-Z0-9\s]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def obter_pdf_acessorios_por_modelo(modelo):
    modelo_norm = normalizar_modelo_acessorio(modelo)

    if not modelo_norm:
        return PDF_ACESSORIOS_GERAL

    for chave, arquivo in MAPA_PDF_ACESSORIOS.items():
        chave_norm = normalizar_modelo_acessorio(chave)
        if chave_norm in modelo_norm:
            return arquivo

    return PDF_ACESSORIOS_GERAL


# ==========================================
# REVISÃO / DATAS / OPÇÕES
# ==========================================
def normalizar_revisao_para_fluxo(valor):
    texto = limpar_opcao(valor)
    texto_norm = normalizar_texto(texto).replace(" ", "")

    mapa = {
        "1": "1",
        "1a": "1",
        "1ª": "1",
        "1o": "1",
        "primeira": "1",
        "primeirarevisao": "1",
        "primeirarevisão": "1",

        "2": "2",
        "2a": "2",
        "2ª": "2",
        "2o": "2",
        "segunda": "2",
        "segundarevisao": "2",
        "segundarevisão": "2",

        "3": "3",
        "3a": "3",
        "3ª": "3",
        "3o": "3",
        "terceira": "3",
        "terceirarevisao": "3",
        "terceirarevisão": "3",

        "4": "4",
        "4a": "4",
        "4ª": "4",
        "4o": "4",
        "quarta": "4",
        "quartarevisao": "4",
        "quartarevisão": "4",

        "5": "5",
        "5a": "5",
        "5ª": "5",
        "5o": "5",
        "quinta": "5",
        "quintarevisao": "5",
        "quintarevisão": "5",
    }

    if texto_norm in mapa:
        return mapa[texto_norm]

    return ""


MAPA_DIA_NUMERO = {
    "segunda": "1",
    "segunda-feira": "1",
    "terca": "2",
    "terça": "2",
    "terca-feira": "2",
    "terça-feira": "2",
    "quarta": "3",
    "quarta-feira": "3",
    "quinta": "4",
    "quinta-feira": "4",
    "sexta": "5",
    "sexta-feira": "5",
    "sabado": "6",
    "sábado": "6",
}


def nome_dia(numero):
    mapa = {
        "1": "Segunda",
        "2": "Terça",
        "3": "Quarta",
        "4": "Quinta",
        "5": "Sexta",
        "6": "Sábado",
    }
    return mapa.get(str(numero), "")


def numero_dia_por_texto(texto):
    texto_norm = normalizar_texto(texto)
    return MAPA_DIA_NUMERO.get(texto_norm, "")


# ==========================================
# ITENS ADICIONAIS / VENDA
# ==========================================
def limpar_item_adicional(item):
    item = str(item or "").strip()
    item = (
        item.replace("[", "")
        .replace("]", "")
        .replace("(", "")
        .replace(")", "")
        .replace("{", "")
        .replace("}", "")
        .replace('"', "")
        .replace("'", "")
        .strip()
    )
    item = re.sub(r"\s+", " ", item).strip(" ,.-")
    return item.upper()


def extrair_lista_itens_adicionais(valor):
    if valor is None:
        return []

    if isinstance(valor, (list, tuple, set)):
        itens = []
        vistos = set()

        for v in valor:
            item = limpar_item_adicional(v)

            if item and item not in vistos:
                itens.append(item)
                vistos.add(item)

        return itens

    texto = str(valor).strip()

    if not texto:
        return []

    texto = texto.replace("\n", ",").replace(";", ",").replace("|", ",")

    partes = [parte.strip() for parte in texto.split(",") if parte.strip()]

    itens_limpos = []
    vistos = set()

    for parte in partes:
        item = limpar_item_adicional(parte)

        if item and item not in vistos:
            itens_limpos.append(item)
            vistos.add(item)

    return itens_limpos


def formatar_itens_adicionais_para_salvar(valor):
    itens = extrair_lista_itens_adicionais(valor)
    return ", ".join(itens)


def item_adicional_valido(item):
    item_limpo = limpar_item_adicional(item)

    if not item_limpo:
        return False

    if item_limpo in [
        "NENHUM",
        "NAO",
        "NÃO",
        "SEM ITEM",
        "SEM ITENS",
        "-",
        "OK",
        "SEM",
    ]:
        return False

    return True


def extrair_itens_venda_real(valor):
    itens = extrair_lista_itens_adicionais(valor)
    return [item for item in itens if item_adicional_valido(item)]


# ==========================================
# STATUS CRM
# ==========================================
def normalizar_status(status):
    status = str(status or "").strip().upper()

    if not status:
        return ""

    mapa = {
        "NOVO": STATUS_NOVO_ATENDIMENTO,
        "NOVO_ATENDIMENTO": STATUS_NOVO_ATENDIMENTO,

        "INICIADO": STATUS_AGENDAMENTO_INICIADO,
        "AGENDAMENTO_INICIADO": STATUS_AGENDAMENTO_INICIADO,

        "AGENDADO": STATUS_AGENDADO,
        "AGENDADA": STATUS_AGENDADO,

        "CONFIRMADO": STATUS_CONFIRMADO,
        "CONFIRMADA": STATUS_CONFIRMADO,

        "REAGENDADO": STATUS_REAGENDADO,
        "REAGENDADA": STATUS_REAGENDADO,

        "CANCELADO": STATUS_CANCELADO,
        "CANCELADA": STATUS_CANCELADO,

        "NAO_COMPARECEU": STATUS_NAO_COMPARECEU,
        "NÃO_COMPARECEU": STATUS_NAO_COMPARECEU,

        "EM_EXECUCAO": STATUS_EM_EXECUCAO,
        "EM EXECUCAO": STATUS_EM_EXECUCAO,
        "EM EXECUÇÃO": STATUS_EM_EXECUCAO,

        "FINALIZADO": STATUS_FINALIZADO,
        "FINALIZADA": STATUS_FINALIZADO,
        "CONCLUIDO": STATUS_FINALIZADO,
        "CONCLUÍDO": STATUS_FINALIZADO,

        "POS_VENDA_ENVIADO": STATUS_POS_VENDA_ENVIADO,

        "ATENDIMENTO_HUMANO": STATUS_ATENDIMENTO_HUMANO,
        "HUMANO": STATUS_ATENDIMENTO_HUMANO,
        "ATENDIMENTO HUMANO": STATUS_ATENDIMENTO_HUMANO,

        "EM ATENDIMENTO": STATUS_NOVO_ATENDIMENTO,
    }

    return mapa.get(status, status)


def definir_status_cliente(telefone, status):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    if telefone not in clientes:
        clientes[telefone] = {}

    clientes[telefone]["status"] = normalizar_status(status)


def obter_status_cliente(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone or telefone not in clientes:
        return STATUS_NOVO_ATENDIMENTO

    return normalizar_status(clientes[telefone].get("status")) or STATUS_NOVO_ATENDIMENTO


def atendimento_humano_ativo_no_banco(telefone):
    db = SessionLocal()

    try:
        telefone_limpo = limpar_telefone(telefone)

        if not telefone_limpo:
            return False

        atendimento = (
            db.query(Atendimento)
            .filter(Atendimento.telefone == telefone_limpo)
            .order_by(Atendimento.id.desc())
            .first()
        )

        if not atendimento:
            return False

        if getattr(atendimento, "atendimento_humano", False):
            return True

        status_atendimento = normalizar_status(getattr(atendimento, "status", ""))

        return status_atendimento == STATUS_ATENDIMENTO_HUMANO

    except Exception as e:
        log_erro("Erro ao verificar atendimento humano no banco:", repr(e))
        return False

    finally:
        db.close()


# ==========================================
# SANCES
# ==========================================
def log_integracao_sances(telefone, acao, payload=None, retorno=None):
    try:
        log_info(
            "[SANCES]",
            f"telefone={telefone}",
            f"acao={acao}",
            f"payload={payload}",
            f"retorno={retorno}",
        )
    except Exception as e:
        log_erro("Erro no log da integração Sances:", repr(e))


def montar_payload_sances(dados):
    return {
        "nome": limpar_texto(dados.get("nome", "")),
        "telefone": limpar_telefone(dados.get("telefone", "")),
        "cpf": limpar_cpf(dados.get("cpf", "")),
        "modelo": limpar_texto(dados.get("modelo", "")),
        "ano": limpar_texto(dados.get("ano", "")),
        "revisao": limpar_texto(dados.get("revisao", "")),
        "km_atual": limpar_texto(
            dados.get("km_atual", "") or dados.get("km", "")
        ),
        "data_agendada": limpar_texto(
            dados.get("data_agendada", "") or dados.get("data", "")
        ),
        "horario": limpar_texto(dados.get("horario", "")),
        "observacao": limpar_texto(
            dados.get("observacao", "") or dados.get("observacoes", "")
        ),
        "itens": formatar_itens_adicionais_para_salvar(
            dados.get("itens", "")
        ),
        "venda_adicional": formatar_itens_adicionais_para_salvar(
            dados.get("venda_adicional", "")
        ),
        "tipo_atendimento": limpar_texto(dados.get("tipo_atendimento", "")),
        "origem": limpar_texto(dados.get("origem", "")) or "BOT_WHATSAPP",
    }


def retorno_padrao_sances():
    return {
        "sucesso": False,
        "status": SANCES_STATUS_PENDENTE,
        "protocolo_sances": "",
        "mensagem": "",
        "erro": "",
    }


def simular_envio_sances(payload):
    resultado = SANCES_SIMULAR_RESULTADO

    if resultado == "enviado":
        retorno = retorno_padrao_sances()
        retorno.update(
            {
                "sucesso": True,
                "status": SANCES_STATUS_ENVIADO,
                "protocolo_sances": f"SCS-{uuid.uuid4().hex[:8].upper()}",
                "mensagem": "Agendamento enviado com sucesso ao Sances (modo mock).",
                "erro": "",
            }
        )

        log_integracao_sances(
            telefone=payload.get("telefone", ""),
            acao="mock_envio_agendamento_sucesso",
            payload=payload,
            retorno=retorno,
        )

        return retorno

    if resultado == "erro":
        retorno = retorno_padrao_sances()
        retorno.update(
            {
                "sucesso": False,
                "status": SANCES_STATUS_ERRO,
                "protocolo_sances": "",
                "mensagem": "Falha simulada no envio ao Sances.",
                "erro": "Erro simulado de integração Sances",
            }
        )

        log_integracao_sances(
            telefone=payload.get("telefone", ""),
            acao="mock_envio_agendamento_erro",
            payload=payload,
            retorno=retorno,
        )

        return retorno

    retorno = retorno_padrao_sances()
    retorno.update(
        {
            "sucesso": False,
            "status": SANCES_STATUS_NAO_CONFIGURADO,
            "protocolo_sances": "",
            "mensagem": "Integração com Sances ainda não configurada.",
            "erro": "Sances não configurado",
        }
    )

    log_integracao_sances(
        telefone=payload.get("telefone", ""),
        acao="mock_envio_agendamento_nao_configurado",
        payload=payload,
        retorno=retorno,
    )

    return retorno


def enviar_agendamento_para_sances(dados_agendamento):
    try:
        payload = montar_payload_sances(dados_agendamento)

        if SANCES_MODO != "real":
            return simular_envio_sances(payload)

        log_integracao_sances(
            telefone=payload.get("telefone", ""),
            acao="envio_real_nao_implementado",
            payload=payload,
            retorno="Modo real selecionado, mas integração ainda não implementada.",
        )

        retorno = retorno_padrao_sances()
        retorno.update(
            {
                "sucesso": False,
                "status": SANCES_STATUS_NAO_CONFIGURADO,
                "protocolo_sances": "",
                "mensagem": "Modo real do Sances ainda não implementado.",
                "erro": "Integração real ainda não implementada",
            }
        )

        return retorno

    except Exception as e:
        log_erro("Erro ao preparar envio para Sances:", repr(e))

        retorno = retorno_padrao_sances()
        retorno.update(
            {
                "sucesso": False,
                "status": SANCES_STATUS_ERRO,
                "protocolo_sances": "",
                "mensagem": "Erro ao preparar integração com Sances.",
                "erro": repr(e),
            }
        )

        return retorno
    
# ==========================================
# CONTROLE DE ESTADO
# ==========================================
def estado_padrao_cliente():
    return {
        "etapa": "menu",
        "status": STATUS_NOVO_ATENDIMENTO,
        "ultima_interacao": agora(),
        "atendimento_humano": False,

        "modelo": "",
        "nome": "",
        "cpf": "",
        "ano": "",
        "revisao": "",
        "km_atual": "",
        "dia": "",
        "dia_texto": "",
        "data": "",
        "horario": "",
        "horarios_disponiveis": [],

        "itens": "",
        "venda_adicional": "",
        "observacao": "",
        "tipo_atendimento": "",

        "duvidas_ia": 0,
        "concluido": False,
        "origem_etapa": "",
        "categoria_duvida": "",
        "etapa_retorno_duvida": "",

        "button_id": "",
        "intencao_ia": "",
        "status_retorno": "",
        "proxima_acao": "",
        "nivel_interesse": "",

        "sances_enviado": False,
        "sances_status": SANCES_STATUS_PENDENTE,
        "sances_protocolo": "",
        "sances_erro": "",
        "sances_data_envio": "",
    }


def iniciar_cliente(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    if telefone not in clientes:
        clientes[telefone] = estado_padrao_cliente()


def resetar_cliente(telefone, preservar_humano=False):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    atendimento_humano = False

    if telefone in clientes:
        atendimento_humano = clientes[telefone].get("atendimento_humano", False)

    clientes[telefone] = estado_padrao_cliente()

    if preservar_humano and atendimento_humano:
        clientes[telefone]["atendimento_humano"] = True
        clientes[telefone]["etapa"] = "atendimento_humano"
        clientes[telefone]["ultima_interacao"] = agora()
        definir_status_cliente(telefone, STATUS_ATENDIMENTO_HUMANO)


def atualizar_interacao(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    iniciar_cliente(telefone)

    clientes[telefone]["ultima_interacao"] = agora()

    db = SessionLocal()

    try:
        atendimento = (
            db.query(Atendimento)
            .filter(
                Atendimento.telefone == telefone,
                Atendimento.concluido == False,
            )
            .order_by(Atendimento.id.desc())
            .first()
        )

        if atendimento:
            atendimento.ultima_interacao = agora_datetime()
            db.commit()

    except Exception as e:
        db.rollback()
        log_erro("Erro ao atualizar interação no banco:", repr(e))

    finally:
        db.close()


def atualizar_ultima_mensagem_cliente(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    iniciar_cliente(telefone)

    db = SessionLocal()

    try:
        atendimento = (
            db.query(Atendimento)
            .filter(
                Atendimento.telefone == telefone,
                Atendimento.concluido == False,
            )
            .order_by(Atendimento.id.desc())
            .first()
        )

        if atendimento:
            atendimento.ultima_mensagem_cliente = agora_datetime()
            atendimento.ultima_interacao = agora_datetime()
            db.commit()

    except Exception as e:
        db.rollback()
        log_erro("Erro ao atualizar última mensagem cliente:", repr(e))

    finally:
        db.close()


def limpar_dados_fluxo_revisao(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    iniciar_cliente(telefone)

    atendimento_humano_ativo = clientes[telefone].get("atendimento_humano", False)
    etapa_atual = clientes[telefone].get("etapa", "")

    campos_limpar = [
        "modelo",
        "nome",
        "cpf",
        "ano",
        "revisao",
        "km_atual",
        "dia",
        "dia_texto",
        "data",
        "horario",
        "itens",
        "venda_adicional",
        "observacao",
        "tipo_atendimento",
        "origem_etapa",
        "categoria_duvida",
        "etapa_retorno_duvida",
        "button_id",
        "intencao_ia",
        "status_retorno",
        "proxima_acao",
        "nivel_interesse",
    ]

    for campo in campos_limpar:
        clientes[telefone][campo] = ""

    clientes[telefone]["horarios_disponiveis"] = []
    clientes[telefone]["concluido"] = False

    if not atendimento_humano_ativo and etapa_atual != "atendimento_humano":
        clientes[telefone]["atendimento_humano"] = False

    clientes[telefone]["sances_enviado"] = False
    clientes[telefone]["sances_status"] = SANCES_STATUS_PENDENTE
    clientes[telefone]["sances_protocolo"] = ""
    clientes[telefone]["sances_erro"] = ""
    clientes[telefone]["sances_data_envio"] = ""

    definir_status_cliente(telefone, STATUS_AGENDAMENTO_INICIADO)


def ativar_atendimento_humano(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    iniciar_cliente(telefone)

    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["etapa"] = "atendimento_humano"
    clientes[telefone]["ultima_interacao"] = agora()

    definir_status_cliente(telefone, STATUS_ATENDIMENTO_HUMANO)

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Atendimento Humano",
        status=STATUS_ATENDIMENTO_HUMANO,
        etapa="atendimento_humano",
        atendimento_humano=True,
        concluido=False,
    )

    enviar_mensagem(
        telefone,
        "👨‍💼 *Atendimento humano acionado*\n\n"
        "Perfeito, vou direcionar seu atendimento para nossa equipe.\n"
        "Daqui em diante, um atendente segue com você por aqui.\n\n"
        "Quando quiser voltar ao menu automático, é só enviar *menu*.",
    )


def processar_inatividade():
    global clientes

    try:
        agora_atual = agora()

        if not isinstance(clientes, dict):
            log_erro("ERRO: clientes não é dicionário. Tipo atual:", type(clientes))
            return

        for telefone in list(clientes.keys()):
            dados = clientes.get(telefone, {})

            if not isinstance(dados, dict):
                continue

            ultima = dados.get("ultima_interacao")

            if not ultima:
                continue

            if (
                dados.get("atendimento_humano") is True
                or dados.get("etapa") == "atendimento_humano"
            ):
                continue

            try:
                tempo_parado = agora_atual - float(ultima)
            except Exception:
                continue

            if tempo_parado > TEMPO_INATIVIDADE:
                resetar_cliente(telefone)

    except Exception as e:
        log_erro("Erro ao processar inatividade:", repr(e))


# ==========================================
# EXTRAÇÃO PAYLOAD - Z-API
# ==========================================
def extrair_button_id(payload):
    try:
        candidatos = [
            payload.get("buttonId"),
            payload.get("selectedButtonId"),
            payload.get("selectedId"),
            payload.get("id"),

            payload.get("button", {}).get("id")
            if isinstance(payload.get("button"), dict) else None,

            payload.get("buttonsResponseMessage", {}).get("selectedButtonId")
            if isinstance(payload.get("buttonsResponseMessage"), dict) else None,

            payload.get("listResponseMessage", {})
            .get("singleSelectReply", {})
            .get("selectedRowId")
            if isinstance(payload.get("listResponseMessage"), dict) else None,

            payload.get("message", {})
            .get("buttonsResponseMessage", {})
            .get("selectedButtonId")
            if isinstance(payload.get("message"), dict) else None,

            payload.get("message", {})
            .get("listResponseMessage", {})
            .get("singleSelectReply", {})
            .get("selectedRowId")
            if isinstance(payload.get("message"), dict) else None,
        ]

        data = payload.get("data", {}) or {}

        if isinstance(data, dict):
            candidatos.extend([
                data.get("buttonId"),
                data.get("selectedButtonId"),
                data.get("selectedId"),
                data.get("id"),

                data.get("button", {}).get("id")
                if isinstance(data.get("button"), dict) else None,

                data.get("buttonsResponseMessage", {}).get("selectedButtonId")
                if isinstance(data.get("buttonsResponseMessage"), dict) else None,

                data.get("listResponseMessage", {})
                .get("singleSelectReply", {})
                .get("selectedRowId")
                if isinstance(data.get("listResponseMessage"), dict) else None,
            ])

        for valor in candidatos:
            if valor is not None and str(valor).strip():
                return str(valor).strip()

        return ""

    except Exception as e:
        log_erro("Erro ao extrair button_id Z-API:", repr(e))
        return ""


def extrair_telefone(payload):
    try:
        telefone = (
            payload.get("phone")
            or payload.get("from")
            or payload.get("sender")
            or payload.get("chatId")
            or payload.get("participantPhone")
            or payload.get("connectedPhone")
            or payload.get("mommentPhone")
        )

        data = payload.get("data", {}) or {}

        if not telefone and isinstance(data, dict):
            telefone = (
                data.get("phone")
                or data.get("from")
                or data.get("sender")
                or data.get("chatId")
                or data.get("participantPhone")
            )

        return limpar_telefone(telefone)

    except Exception as e:
        log_erro("Erro ao extrair telefone Z-API:", repr(e))
        return ""


def extrair_texto(payload):
    try:
        button_id = extrair_button_id(payload)

        if button_id:
            return button_id

        candidatos = [
            payload.get("text", {}).get("message")
            if isinstance(payload.get("text"), dict) else None,

            payload.get("text")
            if isinstance(payload.get("text"), str) else None,

            payload.get("message"),
            payload.get("body"),
            payload.get("caption"),
            payload.get("messageBody"),

            payload.get("image", {}).get("caption")
            if isinstance(payload.get("image"), dict) else None,

            payload.get("video", {}).get("caption")
            if isinstance(payload.get("video"), dict) else None,

            payload.get("document", {}).get("caption")
            if isinstance(payload.get("document"), dict) else None,
        ]

        data = payload.get("data", {}) or {}

        if isinstance(data, dict):
            candidatos.extend([
                data.get("text", {}).get("message")
                if isinstance(data.get("text"), dict) else None,

                data.get("text")
                if isinstance(data.get("text"), str) else None,

                data.get("message"),
                data.get("body"),
                data.get("caption"),
                data.get("messageBody"),
            ])

        for valor in candidatos:
            if valor is not None and str(valor).strip():
                return str(valor).strip()

        return ""

    except Exception as e:
        log_erro("Erro ao extrair texto Z-API:", repr(e))
        return ""


def extrair_message_id(payload):
    try:
        data = payload.get("data", {}) or {}

        message_id = (
            payload.get("messageId")
            or payload.get("id")
            or payload.get("zaapId")
            or payload.get("messageID")
        )

        if not message_id and isinstance(data, dict):
            message_id = (
                data.get("messageId")
                or data.get("id")
                or data.get("zaapId")
                or data.get("messageID")
            )

        if not message_id:
            telefone = extrair_telefone(payload)
            texto = extrair_texto(payload)

            timestamp = str(
                payload.get("momment")
                or payload.get("timestamp")
                or time.time()
            )

            message_id = f"{telefone}-{texto[:30]}-{timestamp}"

        return str(message_id or "")

    except Exception:
        return ""


def mensagem_ja_processada(message_id):
    try:
        if not message_id:
            return False

        return message_id in mensagens_processadas

    except Exception as e:
        log_erro("Erro mensagem_ja_processada:", repr(e))
        return False


def registrar_mensagem_processada(message_id):
    try:
        if not message_id:
            return

        if message_id in mensagens_processadas:
            return

        mensagens_processadas.add(message_id)
        fila_mensagens_processadas.append(message_id)

        while len(fila_mensagens_processadas) > 4000:
            antigo = fila_mensagens_processadas.popleft()
            mensagens_processadas.discard(antigo)

    except Exception as e:
        log_erro("Erro registrar_mensagem_processada:", repr(e))


def evento_eh_do_proprio_bot(payload):
    try:
        data = payload.get("data", {}) or {}

        marcadores_true = [
            payload.get("fromMe"),
            payload.get("isFromMe"),
            payload.get("sentByMe"),
            payload.get("fromApi"),
            payload.get("isNewsletter"),

            data.get("fromMe")
            if isinstance(data, dict) else None,

            data.get("isFromMe")
            if isinstance(data, dict) else None,

            data.get("sentByMe")
            if isinstance(data, dict) else None,

            data.get("fromApi")
            if isinstance(data, dict) else None,
        ]

        return any(valor is True for valor in marcadores_true)

    except Exception as e:
        log_erro("Erro ao validar evento do próprio bot:", repr(e))
        return False


def extrair_tipo_mensagem(payload):
    try:
        button_id = extrair_button_id(payload)

        if button_id:
            return "button"

        tipo = (
            payload.get("type")
            or payload.get("messageType")
            or payload.get("typeMessage")
            or ""
        )

        data = payload.get("data", {}) or {}

        if not tipo and isinstance(data, dict):
            tipo = (
                data.get("type")
                or data.get("messageType")
                or data.get("typeMessage")
                or ""
            )

        tipo = str(tipo or "").strip().lower()

        if "button" in tipo or "buttons" in tipo:
            return "button"

        if "audio" in tipo or "ptt" in tipo:
            return "audio"

        if "image" in tipo:
            return "image"

        if "video" in tipo:
            return "video"

        if "document" in tipo:
            return "document"

        if "text" in tipo or "conversation" in tipo:
            return "text"

        if payload.get("audio"):
            return "audio"

        if payload.get("image"):
            return "image"

        if payload.get("video"):
            return "video"

        if payload.get("document"):
            return "document"

        if extrair_texto(payload):
            return "text"

        return "unknown"

    except Exception as e:
        log_erro("Erro ao extrair tipo de mensagem Z-API:", repr(e))
        return "text"
    
# ==========================================
# ENVIO - Z-API WHATSAPP
# ==========================================
def zapi_configurada():
    return bool(ZAPI_INSTANCE_ID and ZAPI_TOKEN and ZAPI_CLIENT_TOKEN)


def enviar_mensagem(telefone, mensagem):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            log_erro("Telefone inválido para envio de mensagem.")
            return False

        if not zapi_configurada():
            log_erro("Z-API não configurada corretamente.")
            return False

        payload = {
            "phone": telefone,
            "message": mensagem,
        }

        response = requests.post(
            URL_ZAPI_SEND_TEXT,
            json=payload,
            headers=headers_zapi(),
            timeout=30,
        )

        try:
            resposta_json = response.json()
        except Exception:
            resposta_json = response.text

        log_info("STATUS MENSAGEM Z-API:", response.status_code)
        log_info("RESPOSTA MENSAGEM Z-API:", resposta_json)

        if response.status_code not in [200, 201]:
            log_erro("Falha envio mensagem Z-API:", response.status_code, resposta_json)
            return False

        return True

    except Exception as e:
        log_erro("Erro envio mensagem Z-API:", repr(e))
        return False


def enviar_mensagem_botoes(telefone, mensagem, botoes):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            log_erro("Telefone inválido para envio de botões.")
            return False

        if not zapi_configurada():
            log_erro("Z-API não configurada corretamente para botões.")
            return False

        botoes_formatados = []

        for botao in botoes[:3]:
            label = limpar_texto(botao.get("label", ""))[:20]
            button_id = limpar_texto(botao.get("id", ""))

            if label and button_id:
                botoes_formatados.append({
                    "label": label,
                    "id": button_id,
                })

        if not botoes_formatados:
            return enviar_mensagem(telefone, mensagem)

        payload = {
            "phone": telefone,
            "message": mensagem,
            "buttonList": {
                "buttons": botoes_formatados
            }
        }

        response = requests.post(
            URL_ZAPI_SEND_BUTTON_LIST,
            json=payload,
            headers=headers_zapi(),
            timeout=30,
        )

        try:
            resposta_json = response.json()
        except Exception:
            resposta_json = response.text

        log_info("STATUS BOTÕES Z-API:", response.status_code)
        log_info("RESPOSTA BOTÕES Z-API:", resposta_json)

        if response.status_code not in [200, 201]:
            log_erro("Falha envio botões Z-API:", response.status_code, resposta_json)
            return enviar_mensagem(telefone, mensagem)

        return True

    except Exception as e:
        log_erro("Erro envio botões Z-API:", repr(e))
        return enviar_mensagem(telefone, mensagem)


def enviar_pdf(telefone, arquivo, legenda=""):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            log_erro("Telefone inválido para envio de PDF.")
            return False

        if not zapi_configurada():
            log_erro("Z-API não configurada corretamente para envio de PDF.")
            return False

        if not BASE_URL:
            log_erro("BASE_URL não configurada para envio de PDF.")
            return False

        if not arquivo:
            log_erro("Arquivo PDF não informado.")
            return False

        arquivo = str(arquivo).strip().lstrip("/")
        url_pdf = f"{BASE_URL}/pdf/{arquivo}"

        payload = {
            "phone": telefone,
            "document": url_pdf,
            "fileName": arquivo,
            "caption": legenda or "",
        }

        log_info("Enviando PDF Z-API:", url_pdf)

        response = requests.post(
            URL_ZAPI_SEND_DOCUMENT,
            json=payload,
            headers=headers_zapi(),
            timeout=30,
        )

        try:
            resposta_json = response.json()
        except Exception:
            resposta_json = response.text

        log_info("STATUS PDF Z-API:", response.status_code)
        log_info("RESPOSTA PDF Z-API:", resposta_json)

        if response.status_code not in [200, 201]:
            log_erro("Falha envio PDF Z-API:", response.status_code, resposta_json)
            return False

        return True

    except Exception as e:
        log_erro("Erro enviar PDF Z-API:", repr(e))
        return False


# ==========================================
# SALVAMENTO DE EVENTOS / DASHBOARD
# ==========================================
def salvar_evento_atendimento(
    telefone,
    setor,
    status,
    etapa,
    dados=None,
    atendimento_humano=False,
    concluido=False,
    origem="BOT",
):
    db = SessionLocal()

    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            log_erro("Telefone inválido ao salvar evento de atendimento.")
            return False

        iniciar_cliente(telefone)

        base = dados or clientes.get(telefone, {}) or {}

        nome = limpar_texto(base.get("nome", ""))
        modelo = limpar_texto(base.get("modelo", ""))
        ano = limpar_texto(base.get("ano", ""))
        revisao = limpar_texto(base.get("revisao", ""))
        cpf = limpar_cpf(base.get("cpf", ""))
        dia = limpar_texto(base.get("dia", ""))
        data_agendada = limpar_texto(base.get("data", ""))
        horario = limpar_texto(base.get("horario", ""))

        venda_adicional = formatar_itens_adicionais_para_salvar(
            base.get("venda_adicional", "")
        )

        itens = formatar_itens_adicionais_para_salvar(
            base.get("itens", venda_adicional)
        )

        if venda_adicional.strip().upper() in ["NENHUM", "NAO", "NÃO", "2"]:
            venda_adicional = ""

        if itens.strip().upper() in ["NENHUM", "NAO", "NÃO", "2"]:
            itens = ""

        agora_db = agora_datetime()

        atendimento = Atendimento(
            telefone=telefone,
            nome=nome,
            setor=limpar_texto(setor),
            modelo=modelo,
            ano=ano,
            revisao=revisao,
            cpf=cpf,
            dia_semana=nome_dia(dia) if dia else "",
            data_agendada=data_agendada,
            horario=horario,
            itens=itens,
            venda_adicional=venda_adicional,
            observacao=limpar_texto(base.get("observacao", "")),
            observacoes=limpar_texto(base.get("observacao", "")),
            origem=limpar_texto(origem or base.get("origem", "BOT") or "BOT"),
            status=normalizar_status(status),
            etapa=limpar_texto(etapa),
            atendimento_humano=bool(atendimento_humano),
            concluido=bool(concluido),
            button_id=limpar_texto(base.get("button_id", "")),
            intencao_ia=limpar_texto(base.get("intencao_ia", "")),
            id_envio_zapi=limpar_texto(base.get("id_envio_zapi", "")),
            status_retorno=limpar_texto(base.get("status_retorno", "")),
            proxima_acao=limpar_texto(base.get("proxima_acao", "")),
            nivel_interesse=limpar_texto(base.get("nivel_interesse", "")),
            ultima_interacao=agora_db,
            ultima_mensagem_cliente=agora_db,
            data=agora_db,
        )

        db.add(atendimento)
        db.commit()

        log_info("Evento salvo:", telefone, setor, etapa)
        return True

    except Exception as e:
        db.rollback()
        log_erro("Erro salvar evento atendimento:", repr(e))
        return False

    finally:
        db.close()


# ==========================================
# MENU / MENSAGENS
# ==========================================
def enviar_menu(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["etapa"] = "menu"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["ultima_interacao"] = agora()

    definir_status_cliente(telefone, STATUS_NOVO_ATENDIMENTO)

    mensagem = (
        "Olá 👋\n\n"
        "Seja bem-vindo ao *Pós-Vendas Motoshow Yamaha* 🏍️\n\n"
        "Escolha uma opção abaixo ou me escreva o que precisa:\n\n"
        "1️⃣ Agendar Revisão\n"
        "2️⃣ Peças\n"
        "3️⃣ Acessórios\n"
        "4️⃣ Garantia\n"
        "5️⃣ Logista / Atacado\n"
        "6️⃣ Dúvidas\n"
        "7️⃣ Atendimento Humano"
    )

    botoes = [
        {"label": "Agendar revisão", "id": "MENU_REVISAO"},
        {"label": "Peças", "id": "MENU_PECAS"},
        {"label": "Atendimento", "id": "MENU_HUMANO"},
    ]

    return enviar_mensagem_botoes(telefone, mensagem, botoes)


def iniciar_fluxo_pecas(telefone, texto_inicial=""):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["etapa"] = "pecas"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["observacao"] = limpar_texto(texto_inicial)
    clientes[telefone]["ultima_interacao"] = agora()

    definir_status_cliente(telefone, STATUS_NOVO_ATENDIMENTO)

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Peças",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="pecas_iniciado",
        dados=clientes[telefone],
        atendimento_humano=False,
        concluido=False,
    )

    return enviar_mensagem(
        telefone,
        "🔩 *Peças*\n\n"
        "Me informe a *peça desejada* para eu registrar sua solicitação.\n\n"
        "Se puder, envie também:\n"
        "• modelo da moto\n"
        "• ano\n"
        "• peça desejada"
    )


def iniciar_fluxo_acessorios(telefone, texto_inicial=""):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["etapa"] = "acessorios_modelo"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["ultima_interacao"] = agora()
    clientes[telefone]["observacao"] = ""
    clientes[telefone]["modelo"] = ""
    clientes[telefone]["itens"] = ""
    clientes[telefone]["venda_adicional"] = ""

    definir_status_cliente(telefone, STATUS_NOVO_ATENDIMENTO)

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Acessórios",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="acessorios_iniciado",
        dados=clientes[telefone],
        atendimento_humano=False,
        concluido=False,
    )

    if limpar_texto(texto_inicial):
        modelo_informado = limpar_texto(texto_inicial).upper()

        clientes[telefone]["modelo"] = modelo_informado
        clientes[telefone]["etapa"] = "acessorios_orcamento"
        clientes[telefone]["ultima_interacao"] = agora()

        arquivo_pdf = obter_pdf_acessorios_por_modelo(modelo_informado)

        enviar_mensagem(
            telefone,
            "🛵 *Acessórios Yamaha*\n\n"
            f"Perfeito. Identifiquei o modelo como *{modelo_informado}*."
        )

        enviado = enviar_pdf(
            telefone,
            arquivo_pdf,
            "📎 Segue o catálogo de acessórios do modelo informado."
        )

        if not enviado:
            enviar_mensagem(
                telefone,
                "⚠️ Não consegui enviar o catálogo agora, mas vamos continuar seu atendimento."
            )

        enviar_mensagem(
            telefone,
            "Agora me informe *qual acessório você deseja para orçamento*."
        )

        return True

    return enviar_mensagem(
        telefone,
        "🛵 *Acessórios*\n\n"
        "Para eu te enviar o catálogo correto, me informe o *modelo da sua moto*.\n\n"
        "Exemplos:\n"
        "• FZ15\n"
        "• FZ25\n"
        "• Crosser\n"
        "• Lander\n"
        "• Factor\n"
        "• Tenere 700\n"
        "• Aerox"
    )


def menu_duvidas():
    return (
        "📘 *Central de Dúvidas*\n\n"
        "Posso te ajudar com informações rápidas sobre:\n\n"
        "1️⃣ Dúvidas sobre Revisões\n"
        "2️⃣ Dúvidas sobre Garantia\n"
        "3️⃣ Voltar ao menu principal\n\n"
        "Escolha uma opção para eu te ajudar melhor."
    )


def montar_mensagem_horarios(lista):
    if not lista:
        return "⚠️ No momento não encontrei horários disponíveis para essa opção."

    msg = "⏰ *Estes são os horários disponíveis:*\n\n"

    for i, h in enumerate(lista, start=1):
        msg += f"{i} - {h}\n"

    msg += "\nMe responda com o *número do horário* que você prefere."

    return msg


def montar_mensagem_venda_adicional():
    return (
        "🛒 *Deseja aproveitar para incluir algum item no atendimento?*\n\n"
        "Sugestões que muitos clientes pedem:\n"
        "• Filtro de ar\n"
        "• Pastilha de freio\n"
        "• Slider\n"
        "• Protetor de motor\n\n"
        "Se quiser incluir algum, é só digitar o nome do item.\n"
        "Se não quiser adicionar nada, clique em *Sem item* ou digite *2*."
    )


def montar_resumo_confirmacao(telefone):
    telefone = limpar_telefone(telefone)

    dados = clientes.get(telefone, {})

    itens = formatar_itens_adicionais_para_salvar(
        dados.get("venda_adicional", "")
    )

    observacao = dados.get("observacao") or "Nenhuma"
    tipo_atendimento = dados.get("tipo_atendimento") or "Não informado"

    if limpar_texto(itens).upper() in ["", "NENHUM", "NAO", "NÃO", "SEM ITEM", "SEM ITENS", "2"]:
        itens = "Nenhum"

    if not limpar_texto(observacao) or limpar_texto(observacao) == "2":
        observacao = "Nenhuma"

    revisao = limpar_texto(dados.get("revisao", "-"))
    revisao_formatada = f"{revisao}ª" if revisao not in ["", "-"] else "-"

    return (
        "📋 *Confirmação do seu agendamento*\n\n"
        f"👤 *Nome:* {dados.get('nome', '-')}\n"
        f"📄 *CPF:* {dados.get('cpf', '-')}\n"
        f"🏍️ *Modelo:* {dados.get('modelo', '-')}\n"
        f"📅 *Ano:* {dados.get('ano', '-')}\n"
        f"🔢 *KM:* {dados.get('km_atual', '-')}\n"
        f"🔧 *Revisão:* {revisao_formatada}\n"
        f"📍 *Dia:* {dados.get('dia_texto', '-')}\n"
        f"📆 *Data:* {dados.get('data', '-')}\n"
        f"⏰ *Horário:* {dados.get('horario', '-')}\n"
        f"🚶 *Atendimento:* {tipo_atendimento}\n"
        f"🛒 *Adicionais:* {itens}\n"
        f"📝 *Observação:* {observacao}\n\n"
        "Confirme abaixo ou digite:\n"
        "*1* para confirmar ✅\n"
        "*2* para corrigir"
    )


def mensagem_por_etapa_revisao(telefone, etapa):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return "Vamos continuar seu agendamento."

    iniciar_cliente(telefone)

    dados = clientes[telefone]

    if etapa == "revisao_modelo":
        return (
            "🔧 *Agendamento de Revisão*\n\n"
            "Perfeito 👍\n"
            "Para eu seguir com seu atendimento, me informe o *modelo da sua moto*."
        )

    if etapa == "revisao_nome":
        resumo = f"🏍️ Modelo: {dados['modelo']}\n\n" if dados.get("modelo") else ""
        return f"{resumo}Ótimo 😊\n\nAgora me informe seu *nome completo*."

    if etapa == "revisao_cpf":
        return "Perfeito.\n\nAgora preciso do seu *CPF com 11 números* para continuar o agendamento."

    if etapa == "revisao_ano":
        return "Certo 👍\n\nMe informe agora o *ano da sua moto*."

    if etapa == "revisao_km":
        return "Ótimo.\n\nMe informe a *quilometragem atual da moto*."

    if etapa == "revisao_revisao":
        return (
            "🛠️ *Qual revisão você deseja agendar?*\n\n"
            "1 - 1ª Revisão\n"
            "2 - 2ª Revisão\n"
            "3 - 3ª Revisão\n"
            "4 - 4ª Revisão\n"
            "5 - 5ª Revisão ou acima\n\n"
            "Responda com o número da revisão."
        )

    if etapa == "revisao_dia":
        return (
            "📅 *Qual dia você prefere?*\n\n"
            "1 - Segunda\n"
            "2 - Terça\n"
            "3 - Quarta\n"
            "4 - Quinta\n"
            "5 - Sexta\n"
            "6 - Sábado\n\n"
            "Responda com o número do dia."
        )

    if etapa == "revisao_data":
        return "📆 Perfeito.\n\nAgora me informe a *data desejada* no formato *dd/mm/aaaa*."

    if etapa == "revisao_tipo_atendimento":
        return (
            "🏢 Me diga como será seu atendimento:\n\n"
            "1 - Vou aguardar na concessionária\n"
            "2 - Vou deixar a moto e retirar depois"
        )

    if etapa == "revisao_venda":
        return montar_mensagem_venda_adicional()

    if etapa == "revisao_observacao":
        return (
            "📝 Se quiser, você também pode me passar alguma observação para o atendimento.\n\n"
            "Exemplos:\n"
            "• moto com barulho\n"
            "• verificar freio\n"
            "• cliente vai aguardar\n\n"
            "Se não quiser adicionar observação, digite *2*."
        )

    if etapa == "revisao_confirmacao":
        return montar_resumo_confirmacao(telefone)

    return "Vamos continuar seu agendamento."


def enviar_mensagem_etapa_revisao(telefone, etapa):
    mensagem = mensagem_por_etapa_revisao(telefone, etapa)

    if etapa == "revisao_tipo_atendimento":
        return enviar_mensagem_botoes(
            telefone,
            mensagem,
            [
                {"label": "Aguardar", "id": "TIPO_AGUARDAR"},
                {"label": "Deixar moto", "id": "TIPO_DEIXAR"},
            ],
        )

    if etapa == "revisao_venda":
        return enviar_mensagem_botoes(
            telefone,
            mensagem,
            [
                {"label": "Adicionar item", "id": "ADICIONAR_ITEM"},
                {"label": "Sem item", "id": "SEM_ITEM"},
            ],
        )

    if etapa == "revisao_confirmacao":
        return enviar_mensagem_botoes(
            telefone,
            mensagem,
            [
                {"label": "Confirmar", "id": "CONFIRMAR_AGENDAMENTO"},
                {"label": "Corrigir", "id": "CORRIGIR_AGENDAMENTO"},
            ],
        )

    return enviar_mensagem(telefone, mensagem)
# ==========================================
# APOIO IA
# ==========================================
def resposta_ia_vazia():
    return {
        "intencao": "",
        "confianca": 0.0,
        "resposta": "",
        "proxima_etapa": "",
        "dados_extraidos": {},
    }


def obter_dados_extraidos_ia(texto):
    try:
        resposta = classificar_intencao(texto)

        if not isinstance(resposta, dict):
            return resposta_ia_vazia()

        resposta.setdefault("dados_extraidos", {})
        resposta.setdefault("intencao", "")
        resposta.setdefault("confianca", 0.0)
        resposta.setdefault("resposta", "")
        resposta.setdefault("proxima_etapa", "")

        if not isinstance(resposta.get("dados_extraidos"), dict):
            resposta["dados_extraidos"] = {}

        return resposta

    except Exception as e:
        log_erro("Erro ao classificar intenção:", repr(e))
        return resposta_ia_vazia()


def normalizar_data_para_fluxo(data):
    try:
        data_obj = parse_data_hora(data)

        if not data_obj:
            return ""

        return data_obj.strftime("%d/%m/%Y")

    except Exception:
        return ""


def aplicar_dados_ia_no_cliente(telefone, dados_extraidos):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    if not dados_extraidos or not isinstance(dados_extraidos, dict):
        return

    iniciar_cliente(telefone)

    dados = clientes[telefone]

    botao_zapi = limpar_texto(
        dados_extraidos.get("botao_zapi")
        or dados_extraidos.get("button_id")
        or ""
    )

    if botao_zapi:
        dados["button_id"] = botao_zapi

    modelo = limpar_texto(dados_extraidos.get("modelo"))
    nome = limpar_texto(dados_extraidos.get("nome"))
    cpf = limpar_cpf(dados_extraidos.get("cpf"))
    ano = limpar_texto(dados_extraidos.get("ano"))

    revisao_bruta = limpar_texto(dados_extraidos.get("revisao"))
    revisao = normalizar_revisao_para_fluxo(revisao_bruta)

    km_atual = limpar_texto(
        dados_extraidos.get("km_atual") or dados_extraidos.get("km") or ""
    )

    dia_texto = limpar_texto(dados_extraidos.get("dia"))
    horario = limpar_texto(dados_extraidos.get("horario"))
    data = limpar_texto(dados_extraidos.get("data"))
    data_normalizada = normalizar_data_para_fluxo(data)

    item_adicional = formatar_itens_adicionais_para_salvar(
        dados_extraidos.get("item_adicional", "")
    )

    observacao = limpar_texto(dados_extraidos.get("observacao"))
    tipo_atendimento = limpar_texto(dados_extraidos.get("tipo_atendimento"))

    # Evita salvar ID de botão como observação
    if normalizar_botao_zapi(observacao):
        observacao = ""

    revisao_texto = normalizar_texto(revisao_bruta)

    if not revisao:
        if "1000" in revisao_texto or "1 mil" in revisao_texto:
            revisao = "1"
        elif "3000" in revisao_texto or "3 mil" in revisao_texto:
            revisao = "2"
        elif "6000" in revisao_texto or "6 mil" in revisao_texto:
            revisao = "3"
        elif "9000" in revisao_texto or "9 mil" in revisao_texto:
            revisao = "4"
        elif "12000" in revisao_texto or "12 mil" in revisao_texto:
            revisao = "5"
        elif "5 mil" in revisao_texto or "5000" in revisao_texto:
            revisao = "1"
        elif "10 mil" in revisao_texto or "10000" in revisao_texto:
            revisao = "2"
        elif "15 mil" in revisao_texto or "15000" in revisao_texto:
            revisao = "3"
        elif "20 mil" in revisao_texto or "20000" in revisao_texto:
            revisao = "4"
        elif "25 mil" in revisao_texto or "25000" in revisao_texto:
            revisao = "5"

    if dia_texto in ["1", "2", "3", "4", "5", "6"]:
        dia_numero = dia_texto
    else:
        dia_numero = numero_dia_por_texto(dia_texto) if dia_texto else ""

    if modelo and not dados.get("modelo"):
        dados["modelo"] = modelo.upper()

    if nome and not dados.get("nome"):
        dados["nome"] = nome.upper()

    if cpf and len(cpf) == 11 and not dados.get("cpf"):
        dados["cpf"] = cpf

    if ano and not dados.get("ano"):
        dados["ano"] = ano

    if km_atual and not dados.get("km_atual"):
        dados["km_atual"] = km_atual

    if revisao and not dados.get("revisao"):
        dados["revisao"] = revisao

    if dia_numero and not dados.get("dia"):
        dados["dia"] = dia_numero
        dados["dia_texto"] = nome_dia(dia_numero)

    if data_normalizada and not dados.get("data"):
        dados["data"] = data_normalizada

    if horario and not dados.get("horario"):
        horario_limpo = horario.strip()

        if re.match(r"^\d{1,2}:\d{2}$", horario_limpo):
            hora, minuto = horario_limpo.split(":")
            horario_limpo = f"{int(hora):02d}:{minuto}"
            dados["horario"] = horario_limpo

    if (
        item_adicional
        and not dados.get("venda_adicional")
        and item_adicional_valido(item_adicional)
    ):
        dados["itens"] = item_adicional
        dados["venda_adicional"] = item_adicional

    if observacao and not dados.get("observacao"):
        dados["observacao"] = observacao

    if tipo_atendimento and not dados.get("tipo_atendimento"):
        tipo_norm = normalizar_texto(tipo_atendimento)

        if "aguardar" in tipo_norm:
            dados["tipo_atendimento"] = "AGUARDAR NA CONCESSIONÁRIA"

        elif "deixar" in tipo_norm or "retirar depois" in tipo_norm:
            dados["tipo_atendimento"] = "DEIXAR A MOTO E RETIRAR DEPOIS"

        else:
            dados["tipo_atendimento"] = tipo_atendimento


def montar_resumo_dados_ia_revisao(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return ""

    iniciar_cliente(telefone)

    dados = clientes[telefone]

    partes = []

    if dados.get("modelo"):
        partes.append(f"🏍️ Modelo: {dados['modelo']}")

    if dados.get("ano"):
        partes.append(f"📅 Ano: {dados['ano']}")

    if dados.get("revisao"):
        partes.append(f"🔧 Revisão: {dados['revisao']}ª")

    if dados.get("dia_texto"):
        partes.append(f"📍 Dia: {dados['dia_texto']}")

    if dados.get("data"):
        partes.append(f"📆 Data: {dados['data']}")

    if dados.get("horario"):
        partes.append(f"⏰ Horário: {dados['horario']}")

    if dados.get("km_atual"):
        partes.append(f"🔢 KM: {dados['km_atual']}")

    if not partes:
        return ""

    return "Já identifiquei estas informações do seu pedido:\n\n" + "\n".join(partes)


# ==========================================
# FLUXO REVISÃO
# ==========================================
def primeira_etapa_pendente_revisao(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return "revisao_modelo"

    iniciar_cliente(telefone)

    dados = clientes[telefone]

    if not dados.get("modelo"):
        return "revisao_modelo"

    if not dados.get("nome"):
        return "revisao_nome"

    if not dados.get("cpf"):
        return "revisao_cpf"

    if not dados.get("ano"):
        return "revisao_ano"

    if not dados.get("km_atual"):
        return "revisao_km"

    if not dados.get("revisao"):
        return "revisao_revisao"

    if not dados.get("dia"):
        return "revisao_dia"

    if not dados.get("data"):
        return "revisao_data"

    if not dados.get("horario"):
        return "revisao_horario"

    if not dados.get("tipo_atendimento"):
        return "revisao_tipo_atendimento"

    if dados.get("venda_adicional", "") == "":
        return "revisao_venda"

    if dados.get("observacao", "") == "":
        return "revisao_observacao"

    return "revisao_confirmacao"


def iniciar_fluxo_revisao_por_intencao(telefone, dados_extraidos=None):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return ""

    limpar_dados_fluxo_revisao(telefone)

    if dados_extraidos:
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos)

    definir_status_cliente(telefone, STATUS_AGENDAMENTO_INICIADO)

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Revisão",
        status=STATUS_AGENDAMENTO_INICIADO,
        etapa="revisao_iniciada",
        dados=clientes.get(telefone, {}),
        atendimento_humano=False,
        concluido=False,
        origem=clientes.get(telefone, {}).get("origem", "BOT"),
    )

    proxima = primeira_etapa_pendente_revisao(telefone)

    clientes[telefone]["etapa"] = proxima

    return proxima


def enviar_proxima_etapa_revisao(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    etapa = primeira_etapa_pendente_revisao(telefone)

    clientes[telefone]["etapa"] = etapa

    if etapa != "revisao_horario":
        clientes[telefone]["horarios_disponiveis"] = []

    if etapa == "revisao_horario":
        revisao = limpar_texto(clientes[telefone].get("revisao", ""))
        dia = limpar_texto(clientes[telefone].get("dia", ""))

        horarios = horarios_por_revisao(revisao, dia)

        if not horarios:
            clientes[telefone]["etapa"] = "revisao_dia"
            clientes[telefone]["horarios_disponiveis"] = []

            enviar_mensagem(
                telefone,
                "⚠️ Não há horários disponíveis para esse tipo de revisão neste dia.\n\n"
                "Escolha outro dia.",
            )

            enviar_mensagem_etapa_revisao(telefone, "revisao_dia")

            return True

        clientes[telefone]["horarios_disponiveis"] = horarios

        enviar_mensagem(
            telefone,
            montar_mensagem_horarios(horarios)
        )

        return True

    enviar_mensagem_etapa_revisao(telefone, etapa)

    return True
# ==========================================
# CAPACIDADE / HORÁRIOS
# ==========================================
def limite_por_revisao(revisao):
    try:
        revisao = int(revisao)
    except Exception:
        revisao = 1

    if revisao <= 2:
        return 10

    return 7


def verificar_capacidade(data, horario, revisao):
    db = SessionLocal()

    try:
        data = limpar_texto(data)
        horario = limpar_texto(horario)
        revisao = limpar_texto(revisao)

        if not data or not horario:
            return False

        limite = limite_por_revisao(revisao)

        quantidade = (
            db.query(AgendamentoRevisao)
            .filter(
                AgendamentoRevisao.data_agendada == data,
                AgendamentoRevisao.horario == horario,
                AgendamentoRevisao.status == normalizar_status(STATUS_AGENDADO),
            )
            .count()
        )

        return quantidade < limite

    except Exception as e:
        log_erro("Erro capacidade:", repr(e))
        return False

    finally:
        db.close()


def horarios_por_revisao(revisao, dia):
    try:
        revisao = int(revisao)
    except Exception:
        revisao = 1

    dia = str(dia or "").strip()

    if dia not in ["1", "2", "3", "4", "5", "6"]:
        return []

    if dia == "6":
        if revisao <= 2:
            return ["08:00", "09:00", "10:00"]

        return []

    if revisao <= 2:
        return [
            "08:00",
            "09:00",
            "10:00",
            "11:00",
            "12:00",
            "13:00",
            "14:00",
            "15:00",
        ]

    return ["08:00"]


def validar_data(data):
    try:
        data_obj = datetime.strptime(limpar_texto(data), "%d/%m/%Y")

        if data_obj.date() < datetime.now().date():
            return False

        if data_obj.weekday() == 6:
            return False

        return True

    except Exception:
        return False


def data_bate_com_dia_semana(data, dia_numero):
    try:
        data_obj = datetime.strptime(limpar_texto(data), "%d/%m/%Y")

        # Python: segunda=0 / domingo=6
        # Bot: segunda=1 / sábado=6
        dia_real = str(data_obj.weekday() + 1)

        return dia_real == str(dia_numero)

    except Exception:
        return False


def gerar_protocolo():
    return f"REV-{uuid.uuid4().hex[:8].upper()}"


def gerar_protocolo_unico(db):
    for _ in range(5):
        protocolo = gerar_protocolo()

        existe = (
            db.query(AgendamentoRevisao)
            .filter(AgendamentoRevisao.protocolo == protocolo)
            .first()
        )

        if not existe:
            return protocolo

    return gerar_protocolo()


# ==========================================
# SALVAMENTO
# ==========================================
def salvar_agendamento(telefone, dados):
    db = SessionLocal()

    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            log_erro("Telefone inválido ao salvar agendamento.")
            return False, ""

        data_agendada = limpar_texto(dados.get("data", ""))
        horario = limpar_texto(dados.get("horario", ""))
        revisao = limpar_texto(dados.get("revisao", ""))
        dia = limpar_texto(dados.get("dia", ""))

        if not validar_data(data_agendada):
            log_erro("Data inválida ao salvar agendamento:", data_agendada)
            return False, ""

        if dia and not data_bate_com_dia_semana(data_agendada, dia):
            log_erro(
                "Data não bate com dia escolhido:",
                data_agendada,
                dia,
                nome_dia(dia),
            )
            return False, ""

        horarios_validos = horarios_por_revisao(revisao, dia)

        if horario not in horarios_validos:
            log_erro(
                "Horário inválido para revisão/dia:",
                horario,
                revisao,
                dia,
            )
            return False, ""

        if not verificar_capacidade(data_agendada, horario, revisao):
            log_erro(
                "Sem capacidade para salvar agendamento:",
                data_agendada,
                horario,
                revisao,
            )
            return False, ""

        protocolo = gerar_protocolo_unico(db)

        itens_formatados = formatar_itens_adicionais_para_salvar(
            dados.get("itens", "")
        )

        venda_formatada = formatar_itens_adicionais_para_salvar(
            dados.get("venda_adicional", "")
        )

        if limpar_texto(itens_formatados).upper() in ["", "NENHUM", "NAO", "NÃO", "2"]:
            itens_formatados = ""

        if limpar_texto(venda_formatada).upper() in ["", "NENHUM", "NAO", "NÃO", "2"]:
            venda_formatada = "Nenhum"

        observacao = limpar_texto(dados.get("observacao", ""))

        if observacao.strip().upper() in ["", "NENHUMA", "NENHUM", "NAO", "NÃO", "2"]:
            observacao = "Nenhuma"

        origem = limpar_texto(dados.get("origem", "")) or "BOT"

        agendamento = AgendamentoRevisao(
            protocolo=protocolo,
            telefone=telefone,
            nome=limpar_texto(dados.get("nome", "")),
            cpf=limpar_cpf(dados.get("cpf", "")),
            modelo=limpar_texto(dados.get("modelo", "")).upper(),
            ano=limpar_texto(dados.get("ano", "")),
            revisao=revisao,
            dia_semana=nome_dia(dia),
            data_agendada=data_agendada,
            horario=horario,
            itens=itens_formatados,
            venda_adicional=venda_formatada,
            status=normalizar_status(STATUS_AGENDADO),
            observacoes=observacao,
            origem=origem,
            sances_status=SANCES_STATUS_PENDENTE,
            sances_enviado=False,
            sances_protocolo="",
            sances_erro="",
            sances_data_envio=None,
        )

        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)

        try:
            salvar_atendimento_dashboard(telefone, dados)
        except Exception as e:
            log_erro("Erro ao salvar atendimento no dashboard:", repr(e))

        log_info("Agendamento salvo:", protocolo)

        return True, protocolo

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        log_erro("Erro salvar agendamento:", repr(e))
        return False, ""

    finally:
        db.close()


def salvar_atendimento_dashboard(telefone, dados):
    telefone = limpar_telefone(telefone)

    return salvar_evento_atendimento(
        telefone=telefone,
        setor="Revisão",
        status=STATUS_AGENDADO,
        etapa="revisao_finalizada",
        dados=dados,
        atendimento_humano=False,
        concluido=True,
        origem=limpar_texto(dados.get("origem", "")) or "BOT",
    )
# ==========================================
# CONSULTA / CANCELAMENTO / REAGENDAMENTO
# ==========================================
def agendamento_para_dict(agendamento):
    if not agendamento:
        return None

    return {
        "protocolo": str(agendamento.protocolo or ""),
        "telefone": str(agendamento.telefone or ""),
        "nome": str(agendamento.nome or ""),
        "cpf": str(agendamento.cpf or ""),
        "modelo": str(agendamento.modelo or ""),
        "ano": str(agendamento.ano or ""),
        "revisao": str(agendamento.revisao or ""),
        "dia_semana": str(getattr(agendamento, "dia_semana", "") or ""),
        "data_agendada": str(agendamento.data_agendada or ""),
        "horario": str(agendamento.horario or ""),
        "itens": str(agendamento.itens or ""),
        "venda_adicional": str(agendamento.venda_adicional or ""),
        "status": str(agendamento.status or ""),
        "origem": str(getattr(agendamento, "origem", "") or "BOT"),
    }


def buscar_agendamento_ativo(cpf):
    db = SessionLocal()

    try:
        cpf_limpo = limpar_cpf(cpf)

        if not cpf_limpo:
            return None

        agendamento = (
            db.query(AgendamentoRevisao)
            .filter(
                AgendamentoRevisao.cpf == cpf_limpo,
                AgendamentoRevisao.status == normalizar_status(STATUS_AGENDADO),
            )
            .order_by(AgendamentoRevisao.id.desc())
            .first()
        )

        return agendamento_para_dict(agendamento)

    except Exception as e:
        log_erro("Erro buscar agendamento:", repr(e))
        return None

    finally:
        db.close()


def buscar_agendamento_por_cpf(cpf):
    return buscar_agendamento_ativo(cpf)


def alterar_status_agendamento(cpf, novo_status):
    db = SessionLocal()

    try:
        cpf_limpo = limpar_cpf(cpf)

        if not cpf_limpo:
            return None

        agendamento = (
            db.query(AgendamentoRevisao)
            .filter(
                AgendamentoRevisao.cpf == cpf_limpo,
                AgendamentoRevisao.status == normalizar_status(STATUS_AGENDADO),
            )
            .order_by(AgendamentoRevisao.id.desc())
            .first()
        )

        if not agendamento:
            return None

        dados = agendamento_para_dict(agendamento)

        agendamento.status = normalizar_status(novo_status)

        if hasattr(agendamento, "atualizado_em"):
            agendamento.atualizado_em = agora_datetime()

        dados["status"] = agendamento.status

        db.commit()

        log_info("Status do agendamento alterado:", dados)

        return dados

    except Exception as e:
        db.rollback()
        log_erro("Erro alterar status agendamento:", repr(e))
        return None

    finally:
        db.close()


def cancelar_agendamento(cpf, novo_status=STATUS_CANCELADO):
    return alterar_status_agendamento(cpf, novo_status)


def responder_consulta_agendamento(telefone, cpf):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    cpf_limpo = limpar_cpf(cpf)

    if not cpf_limpo or len(cpf_limpo) != 11:
        enviar_mensagem(
            telefone,
            "📄 Para consultar seu agendamento, informe seu *CPF com 11 números*.",
        )

        clientes[telefone]["etapa"] = "consulta_agendamento_cpf"

        return True

    ag = buscar_agendamento_por_cpf(cpf_limpo)

    if not ag:
        salvar_evento_atendimento(
            telefone=telefone,
            setor="Consulta Agendamento",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="consulta_agendamento_nao_localizado",
            dados={"cpf": cpf_limpo},
            atendimento_humano=False,
            concluido=False,
        )

        enviar_mensagem_botoes(
            telefone,
            "⚠️ Não localizei agendamento ativo para este CPF.\n\n"
            "Deseja iniciar um novo agendamento?",
            [
                {"label": "Agendar revisão", "id": "AGENDAR_REVISAO"},
                {"label": "Menu", "id": "MENU"},
            ],
        )

        resetar_cliente(telefone)

        return True

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Consulta Agendamento",
        status=STATUS_AGENDADO,
        etapa="consulta_agendamento_localizado",
        dados={
            "nome": ag.get("nome", ""),
            "modelo": ag.get("modelo", ""),
            "ano": ag.get("ano", ""),
            "revisao": ag.get("revisao", ""),
            "cpf": ag.get("cpf", ""),
            "data": ag.get("data_agendada", ""),
            "horario": ag.get("horario", ""),
            "itens": ag.get("itens", ""),
            "venda_adicional": ag.get("venda_adicional", ""),
            "origem": ag.get("origem", "BOT"),
        },
        atendimento_humano=False,
        concluido=False,
        origem=ag.get("origem", "BOT"),
    )

    enviar_mensagem_botoes(
        telefone,
        "📋 *Agendamento localizado*\n\n"
        f"👤 {ag.get('nome', '')}\n"
        f"🏍️ {ag.get('modelo', '')}\n"
        f"📅 {ag.get('data_agendada', '')}\n"
        f"⏰ {ag.get('horario', '')}\n"
        f"📌 Protocolo: {ag.get('protocolo', '')}\n\n"
        "O que deseja fazer?",
        [
            {"label": "Reagendar", "id": "REAGENDAR_AGENDAMENTO"},
            {"label": "Cancelar", "id": "CANCELAR_AGENDAMENTO"},
            {"label": "Menu", "id": "MENU"},
        ],
    )

    resetar_cliente(telefone)

    return True


def responder_cancelamento_agendamento(telefone, cpf):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            return False

        iniciar_cliente(telefone)

        cpf_limpo = limpar_cpf(cpf)

        if not cpf_limpo or len(cpf_limpo) != 11:
            enviar_mensagem(
                telefone,
                "📄 Para cancelar seu agendamento, informe seu *CPF com 11 números*.",
            )

            clientes[telefone]["etapa"] = "cancelar_agendamento_cpf"

            return True

        ag_cancelado = cancelar_agendamento(cpf_limpo, STATUS_CANCELADO)

        if not ag_cancelado:
            salvar_evento_atendimento(
                telefone=telefone,
                setor="Cancelamento",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="cancelamento_nao_localizado",
                dados={"cpf": cpf_limpo},
                atendimento_humano=False,
                concluido=False,
            )

            enviar_mensagem_botoes(
                telefone,
                "⚠️ Não encontrei agendamento ativo para este CPF.\n\n"
                "Deseja voltar ao menu?",
                [
                    {"label": "Menu", "id": "MENU"},
                    {"label": "Humano", "id": "MENU_HUMANO"},
                ],
            )

            resetar_cliente(telefone)

            return True

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Cancelamento",
            status=STATUS_CANCELADO,
            etapa="agendamento_cancelado",
            dados={
                "protocolo": ag_cancelado.get("protocolo", ""),
                "nome": ag_cancelado.get("nome", ""),
                "modelo": ag_cancelado.get("modelo", ""),
                "ano": ag_cancelado.get("ano", ""),
                "revisao": ag_cancelado.get("revisao", ""),
                "cpf": ag_cancelado.get("cpf", ""),
                "data": ag_cancelado.get("data_agendada", ""),
                "horario": ag_cancelado.get("horario", ""),
                "itens": ag_cancelado.get("itens", ""),
                "venda_adicional": ag_cancelado.get("venda_adicional", ""),
                "origem": ag_cancelado.get("origem", "BOT"),
            },
            atendimento_humano=False,
            concluido=True,
            origem=ag_cancelado.get("origem", "BOT"),
        )

        mensagem = (
            "✅ *Agendamento cancelado com sucesso*\n\n"
            f"👤 {ag_cancelado.get('nome', '')}\n"
            f"🏍️ {ag_cancelado.get('modelo', '')}\n"
            f"📅 {ag_cancelado.get('data_agendada', '')}\n"
            f"⏰ {ag_cancelado.get('horario', '')}\n"
            f"📌 Protocolo: {ag_cancelado.get('protocolo', '')}\n\n"
            "Equipe Motoshow Yamaha"
        )

        enviar_mensagem_botoes(
            telefone,
            mensagem,
            [
                {"label": "Novo agendamento", "id": "AGENDAR_REVISAO"},
                {"label": "Menu", "id": "MENU"},
            ],
        )

        resetar_cliente(telefone)

        return True

    except Exception as e:
        log_erro("Erro responder_cancelamento_agendamento:", repr(e))

        enviar_mensagem(
            telefone,
            "⚠️ O cancelamento foi processado, mas ocorreu uma falha ao finalizar a resposta. Envie *menu* para continuar.",
        )

        resetar_cliente(telefone)

        return False


def iniciar_reagendamento(telefone, cpf):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    cpf_limpo = limpar_cpf(cpf)

    if not cpf_limpo or len(cpf_limpo) != 11:
        enviar_mensagem(
            telefone,
            "📄 Para reagendar, informe seu *CPF com 11 números*.",
        )

        clientes[telefone]["etapa"] = "reagendar_agendamento_cpf"

        return True

    ag = buscar_agendamento_por_cpf(cpf_limpo)

    if not ag:
        salvar_evento_atendimento(
            telefone=telefone,
            setor="Reagendamento",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="reagendamento_nao_localizado",
            dados={"cpf": cpf_limpo},
            atendimento_humano=False,
            concluido=False,
        )

        enviar_mensagem_botoes(
            telefone,
            "⚠️ Não encontrei agendamento ativo para este CPF.\n\n"
            "Deseja iniciar um novo agendamento?",
            [
                {"label": "Agendar revisão", "id": "AGENDAR_REVISAO"},
                {"label": "Menu", "id": "MENU"},
            ],
        )

        resetar_cliente(telefone)

        return True

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Reagendamento",
        status=STATUS_REAGENDADO,
        etapa="reagendamento_iniciado",
        dados={
            "protocolo": ag.get("protocolo", ""),
            "nome": ag.get("nome", ""),
            "modelo": ag.get("modelo", ""),
            "ano": ag.get("ano", ""),
            "revisao": ag.get("revisao", ""),
            "cpf": ag.get("cpf", ""),
            "data": ag.get("data_agendada", ""),
            "horario": ag.get("horario", ""),
            "itens": ag.get("itens", ""),
            "venda_adicional": ag.get("venda_adicional", ""),
            "origem": ag.get("origem", "BOT"),
        },
        atendimento_humano=False,
        concluido=False,
        origem=ag.get("origem", "BOT"),
    )

    limpar_dados_fluxo_revisao(telefone)

    clientes[telefone]["modelo"] = limpar_texto(ag.get("modelo", "")).upper()
    clientes[telefone]["nome"] = limpar_texto(ag.get("nome", "")).upper()
    clientes[telefone]["cpf"] = limpar_cpf(ag.get("cpf", ""))
    clientes[telefone]["ano"] = limpar_texto(ag.get("ano", ""))
    clientes[telefone]["revisao"] = limpar_texto(ag.get("revisao", ""))
    clientes[telefone]["reagendamento"] = True
    clientes[telefone]["protocolo_antigo"] = ag.get("protocolo", "")
    clientes[telefone]["origem"] = ag.get("origem", "BOT")

    cancelar_agendamento(
        clientes[telefone]["cpf"],
        novo_status=STATUS_REAGENDADO,
    )

    definir_status_cliente(telefone, STATUS_REAGENDADO)

    clientes[telefone]["etapa"] = "revisao_dia"

    enviar_mensagem(
        telefone,
        "🔄 *Reagendamento iniciado*\n\n"
        "Encontrei seu agendamento anterior e vou te ajudar a escolher uma nova data.",
    )

    enviar_mensagem_etapa_revisao(telefone, "revisao_dia")

    return True


# ==========================================
# FOLLOW-UP / LEMBRETES - VERSÃO INTELIGENTE
# ==========================================
def atualizar_retorno_na_planilha(telefone, texto):
    try:
        telefone = limpar_telefone(telefone)
        texto = limpar_texto(texto)

        if not telefone or not texto:
            return

        with followup_lock:
            if not os.path.exists(ARQUIVO_FOLLOWUP):
                return

            df = pd.read_excel(ARQUIVO_FOLLOWUP)

            if df.empty:
                return

            colunas = {str(c).strip().lower(): c for c in df.columns}
            coluna_telefone = None

            for chave in ["telefone", "fone", "whatsapp", "celular", "numero"]:
                if chave in colunas:
                    coluna_telefone = colunas[chave]
                    break

            if not coluna_telefone:
                return

            coluna_retorno = colunas.get("retorno", "retorno")
            coluna_data_retorno = colunas.get("data_retorno", "data_retorno")

            if coluna_retorno not in df.columns:
                df[coluna_retorno] = ""

            if coluna_data_retorno not in df.columns:
                df[coluna_data_retorno] = ""

            for idx in df.index:
                tel_planilha = limpar_telefone(df.at[idx, coluna_telefone])

                if tel_planilha == telefone:
                    df.at[idx, coluna_retorno] = texto
                    df.at[idx, coluna_data_retorno] = formatar_data_hora()
                    df.to_excel(ARQUIVO_FOLLOWUP, index=False)
                    return

    except Exception as e:
        log_erro("Erro ao atualizar retorno na planilha:", repr(e))


def processar_lembretes_agendamento():
    db = SessionLocal()

    try:
        agora_time = datetime.now()
        hoje = agora_time.date()
        houve_alteracao = False

        agendamentos = (
            db.query(AgendamentoRevisao)
            .filter(
                AgendamentoRevisao.status == normalizar_status(STATUS_AGENDADO),
                AgendamentoRevisao.lembrete_enviado == False,
            )
            .all()
        )

        for ag in agendamentos:
            try:
                telefone = limpar_telefone(getattr(ag, "telefone", "") or "")

                if not telefone:
                    continue

                data_texto = limpar_texto(getattr(ag, "data_agendada", "") or "")

                if not data_texto:
                    continue

                try:
                    data_agendada = datetime.strptime(data_texto, "%d/%m/%Y").date()
                except Exception:
                    log_erro("Data inválida no lembrete:", repr(data_texto))
                    continue

                diferenca = (data_agendada - hoje).days

                data_criacao = (
                    getattr(ag, "criado_em", None)
                    or getattr(ag, "data", None)
                )

                if diferenca != 1:
                    continue

                if data_criacao:
                    try:
                        if (agora_time - data_criacao).total_seconds() < 3600:
                            continue
                    except Exception:
                        pass

                mensagem = (
                    "🔔 *Lembrete de Revisão Motoshow Yamaha*\n\n"
                    f"Olá *{str(getattr(ag, 'nome', '') or '').upper()}*, passando para lembrar do seu agendamento:\n\n"
                    f"🏍️ *Modelo:* {str(getattr(ag, 'modelo', '') or '').upper()}\n"
                    f"📅 *Data:* {str(getattr(ag, 'data_agendada', '') or '')}\n"
                    f"⏰ *Horário:* {str(getattr(ag, 'horario', '') or '')}\n"
                    f"📌 *Protocolo:* {str(getattr(ag, 'protocolo', '') or '')}\n\n"
                    "📖 Lembre-se de trazer o manual da moto.\n\n"
                    "Se precisar reagendar, clique abaixo ou responda esta mensagem."
                )

                enviado = enviar_mensagem_botoes(
                    telefone,
                    mensagem,
                    [
                        {"label": "Reagendar", "id": "REAGENDAR_AGENDAMENTO"},
                        {"label": "Humano", "id": "MENU_HUMANO"},
                    ],
                )

                if enviado:
                    ag.lembrete_enviado = True
                    houve_alteracao = True

            except Exception as e:
                log_erro("Erro lembrete individual:", repr(e))

        if houve_alteracao:
            db.commit()

    except Exception as e:
        db.rollback()
        log_erro("Erro geral lembrete:", repr(e))

    finally:
        db.close()


def escolher_mensagem_followup(at):
    setor = str(getattr(at, "setor", "") or "").strip().lower()
    etapa = str(getattr(at, "etapa", "") or "").strip().lower()
    modelo = str(getattr(at, "modelo", "") or "").strip().upper()

    if "revis" in setor or etapa.startswith("revisao"):
        if modelo:
            return (
                "👋 Oi! Vi que você começou o agendamento de revisão da sua moto "
                f"*{modelo}*, mas ainda não finalizou.\n\n"
                "Quer que eu te ajude a concluir agora? É rapidinho 🏍️"
            )

        return (
            "👋 Oi! Vi que você começou um agendamento de revisão, mas ainda não finalizou.\n\n"
            "Quer que eu te ajude a concluir agora? É rapidinho 🏍️"
        )

    if "acess" in setor or "acessorios" in etapa:
        return (
            "👋 Oi! Vi que você estava olhando acessórios Yamaha.\n\n"
            "Quer que eu te ajude com um orçamento?"
        )

    if "pec" in setor or "pecas" in etapa:
        return (
            "👋 Oi! Vi que você começou uma solicitação de peças.\n\n"
            "Quer me enviar o item que precisa para continuarmos?"
        )

    if "garantia" in setor or "garantia" in etapa:
        return (
            "👋 Oi! Vi que você começou uma solicitação de garantia.\n\n"
            "Pode me enviar os detalhes para eu te ajudar?"
        )

    if "atacado" in setor or "atacado" in etapa:
        return (
            "👋 Oi! Vi que você começou um atendimento de atacado.\n\n"
            "Quer continuar sua solicitação?"
        )

    return (
        "👋 Oi! Vi que você começou um atendimento e não finalizou.\n\n"
        "Posso te ajudar a concluir rapidinho? 🚀"
    )


def processar_followup_inteligente():
    # FOLLOW-UP DESATIVADO TEMPORARIAMENTE
    return

# ==========================================
# APOIO DÚVIDAS / REVISÃO / SANCES
# ==========================================
def encerrar_atendimento_humano(telefone):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            return False

        iniciar_cliente(telefone)

        clientes[telefone]["atendimento_humano"] = False

        if clientes[telefone].get("etapa") == "atendimento_humano":
            clientes[telefone]["etapa"] = "menu"

        definir_status_cliente(telefone, STATUS_NOVO_ATENDIMENTO)

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Atendimento Humano",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="atendimento_humano_encerrado",
            dados=clientes.get(telefone, {}),
            atendimento_humano=False,
            concluido=False,
            origem=clientes.get(telefone, {}).get("origem", "BOT"),
        )

        return True

    except Exception as e:
        log_erro("Erro ao encerrar atendimento humano:", repr(e))
        return False


def montar_dados_agendamento_para_reenvio(ag):
    try:
        if not ag:
            return {}

        if isinstance(ag, dict):
            return {
                "telefone": limpar_telefone(ag.get("telefone", "")),
                "nome": limpar_texto(ag.get("nome", "")),
                "cpf": limpar_cpf(ag.get("cpf", "")),
                "modelo": limpar_texto(ag.get("modelo", "")),
                "ano": limpar_texto(ag.get("ano", "")),
                "revisao": limpar_texto(ag.get("revisao", "")),
                "dia": "",
                "data": limpar_texto(ag.get("data_agendada", "") or ag.get("data", "")),
                "horario": limpar_texto(ag.get("horario", "")),
                "itens": formatar_itens_adicionais_para_salvar(ag.get("itens", "")),
                "venda_adicional": formatar_itens_adicionais_para_salvar(
                    ag.get("venda_adicional", "")
                ),
                "observacao": limpar_texto(
                    ag.get("observacoes", "") or ag.get("observacao", "")
                ),
                "tipo_atendimento": limpar_texto(ag.get("tipo_atendimento", "")),
                "protocolo": limpar_texto(ag.get("protocolo", "")),
                "origem": limpar_texto(ag.get("origem", "")) or "BOT",
            }

        return {
            "telefone": limpar_telefone(getattr(ag, "telefone", "")),
            "nome": limpar_texto(getattr(ag, "nome", "")),
            "cpf": limpar_cpf(getattr(ag, "cpf", "")),
            "modelo": limpar_texto(getattr(ag, "modelo", "")),
            "ano": limpar_texto(getattr(ag, "ano", "")),
            "revisao": limpar_texto(getattr(ag, "revisao", "")),
            "dia": "",
            "data": limpar_texto(getattr(ag, "data_agendada", "")),
            "horario": limpar_texto(getattr(ag, "horario", "")),
            "itens": formatar_itens_adicionais_para_salvar(getattr(ag, "itens", "")),
            "venda_adicional": formatar_itens_adicionais_para_salvar(
                getattr(ag, "venda_adicional", "")
            ),
            "observacao": limpar_texto(
                getattr(ag, "observacoes", "") or getattr(ag, "observacao", "")
            ),
            "tipo_atendimento": limpar_texto(getattr(ag, "tipo_atendimento", "")),
            "protocolo": limpar_texto(getattr(ag, "protocolo", "")),
            "origem": limpar_texto(getattr(ag, "origem", "")) or "BOT",
        }

    except Exception as e:
        log_erro("Erro ao montar dados para reenvio Sances:", repr(e))
        return {}


def buscar_agendamento_por_protocolo(protocolo):
    db = SessionLocal()

    try:
        protocolo_limpo = limpar_texto(protocolo).upper()

        if not protocolo_limpo:
            return None

        ag = (
            db.query(AgendamentoRevisao)
            .filter(AgendamentoRevisao.protocolo == protocolo_limpo)
            .order_by(AgendamentoRevisao.id.desc())
            .first()
        )

        return agendamento_para_dict(ag)

    except Exception as e:
        log_erro("Erro buscar agendamento por protocolo:", repr(e))
        return None

    finally:
        db.close()


def atualizar_status_sances_agendamento(protocolo, retorno_sances):
    db = SessionLocal()

    try:
        protocolo_limpo = limpar_texto(protocolo).upper()

        if not protocolo_limpo:
            return False

        if not isinstance(retorno_sances, dict):
            retorno_sances = {}

        ag = (
            db.query(AgendamentoRevisao)
            .filter(AgendamentoRevisao.protocolo == protocolo_limpo)
            .order_by(AgendamentoRevisao.id.desc())
            .first()
        )

        if not ag:
            return False

        agora_time = datetime.now()
        sucesso = bool(retorno_sances.get("sucesso", False))

        status = (
            limpar_texto(retorno_sances.get("status", ""))
            or SANCES_STATUS_ERRO
        ).upper()

        ag.sances_status = status
        ag.sances_enviado = sucesso
        ag.sances_protocolo = limpar_texto(
            retorno_sances.get("protocolo_sances", "")
        )
        ag.sances_erro = limpar_texto(retorno_sances.get("erro", ""))

        if sucesso:
            ag.sances_data_envio = agora_time

        if hasattr(ag, "sances_tentativas"):
            ag.sances_tentativas = int(getattr(ag, "sances_tentativas", 0) or 0) + 1

        if hasattr(ag, "sances_ultima_tentativa"):
            ag.sances_ultima_tentativa = agora_time

        if hasattr(ag, "sances_ultimo_retorno"):
            ag.sances_ultimo_retorno = str(retorno_sances)

        if hasattr(ag, "atualizado_em"):
            ag.atualizado_em = agora_time

        db.commit()

        return True

    except Exception as e:
        db.rollback()
        log_erro("Erro atualizar status Sances:", repr(e))
        return False

    finally:
        db.close()


def salvar_duvida_dashboard(telefone, categoria, pergunta, resposta):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            return False

        iniciar_cliente(telefone)

        setor = f"Dúvidas {limpar_texto(categoria)}".strip()

        clientes[telefone]["duvidas_ia"] = int(
            clientes[telefone].get("duvidas_ia", 0) or 0
        ) + 1
        clientes[telefone]["intencao_ia"] = "duvidas"

        return salvar_evento_atendimento(
            telefone=telefone,
            setor=setor,
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="duvida_respondida",
            dados={
                **clientes.get(telefone, {}),
                "observacao": (
                    f"Pergunta: {limpar_texto(pergunta)} | "
                    f"Resposta: {limpar_texto(resposta)}"
                ),
            },
            atendimento_humano=False,
            concluido=True,
            origem=clientes.get(telefone, {}).get("origem", "BOT"),
        )

    except Exception as e:
        log_erro("Erro salvar dúvida dashboard:", repr(e))
        return False


def mensagem_duvida_retorno_fluxo(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return ""

    iniciar_cliente(telefone)

    etapa_retorno = limpar_texto(
        clientes[telefone].get("etapa_retorno_duvida", "")
    )

    if etapa_retorno and etapa_retorno.startswith("revisao"):
        return (
            "Posso continuar te ajudando por aqui 👇\n\n"
            "1 - Continuar meu agendamento\n"
            "2 - Fazer outra dúvida\n"
            "3 - Falar com atendimento humano"
        )

    return (
        "Posso continuar te ajudando por aqui 👇\n\n"
        "1 - Fazer outra dúvida\n"
        "2 - Voltar ao menu principal\n"
        "3 - Falar com atendimento humano"
    )


def enviar_duvida_retorno_fluxo(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    etapa_retorno = limpar_texto(
        clientes[telefone].get("etapa_retorno_duvida", "")
    )

    mensagem = mensagem_duvida_retorno_fluxo(telefone)

    if etapa_retorno and etapa_retorno.startswith("revisao"):
        return enviar_mensagem_botoes(
            telefone,
            mensagem,
            [
                {"label": "Continuar", "id": "DUVIDA_CONTINUAR"},
                {"label": "Outra dúvida", "id": "DUVIDA_OUTRA"},
                {"label": "Humano", "id": "MENU_HUMANO"},
            ],
        )

    return enviar_mensagem_botoes(
        telefone,
        mensagem,
        [
            {"label": "Outra dúvida", "id": "DUVIDA_OUTRA"},
            {"label": "Menu", "id": "MENU"},
            {"label": "Humano", "id": "MENU_HUMANO"},
        ],
    )


def etapa_revisao_permite_ir_para_duvidas(etapa):
    etapas_permitidas = {
        "revisao_modelo",
        "revisao_nome",
        "revisao_cpf",
        "revisao_ano",
        "revisao_km",
        "revisao_revisao",
    }

    return etapa in etapas_permitidas


def encaminhar_para_menu_duvidas(telefone, etapa_atual=""):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            return False

        iniciar_cliente(telefone)

        clientes[telefone]["etapa_retorno_duvida"] = limpar_texto(etapa_atual)
        clientes[telefone]["etapa"] = "menu_duvidas"
        clientes[telefone]["intencao_ia"] = "duvidas"

        enviar_mensagem(
            telefone,
            "Sem problema 👍 Vou te direcionar para a central de dúvidas "
            "e depois podemos voltar para o seu agendamento.",
        )

        return enviar_mensagem_botoes(
            telefone,
            menu_duvidas(),
            [
                {"label": "Revisões", "id": "DUVIDA_REVISOES"},
                {"label": "Garantia", "id": "DUVIDA_GARANTIA"},
                {"label": "Menu", "id": "MENU"},
            ],
        )

    except Exception as e:
        log_erro("Erro ao encaminhar para menu de dúvidas:", repr(e))
        return False


def data_corresponde_ao_dia_escolhido(data_digitada, dia_escolhido):
    return data_bate_com_dia_semana(data_digitada, dia_escolhido)
# ==========================================
# WORKER
# ==========================================
worker_followup_iniciado = False


def processar_fila_sances():
    db = SessionLocal()

    try:
        agora_time = datetime.now()

        agendamentos = (
            db.query(AgendamentoRevisao)
            .filter(
                AgendamentoRevisao.sances_status.in_([
                    SANCES_STATUS_PENDENTE,
                    SANCES_STATUS_ERRO,
                ])
            )
            .all()
        )

        for ag in agendamentos:
            try:
                tentativas = int(getattr(ag, "sances_tentativas", 0) or 0)
                ultima_tentativa = getattr(ag, "sances_ultima_tentativa", None)

                if tentativas >= SANCES_RETRY_MAX:
                    continue

                if ultima_tentativa:
                    if tentativas <= 1:
                        intervalo_minimo = 300
                    elif tentativas == 2:
                        intervalo_minimo = 900
                    else:
                        intervalo_minimo = 1800

                    try:
                        segundos_desde_tentativa = (
                            agora_time - ultima_tentativa
                        ).total_seconds()

                        if segundos_desde_tentativa < intervalo_minimo:
                            continue

                    except Exception:
                        pass

                dados = montar_dados_agendamento_para_reenvio(ag)

                if not dados or not dados.get("telefone"):
                    log_erro(
                        "Dados inválidos para reenvio Sances:",
                        getattr(ag, "protocolo", ""),
                    )
                    continue

                retorno = enviar_agendamento_para_sances(dados)

                if not isinstance(retorno, dict):
                    retorno = {
                        "sucesso": False,
                        "status": SANCES_STATUS_ERRO,
                        "protocolo_sances": "",
                        "erro": "Retorno inválido da integração Sances",
                    }

                ag.sances_status = limpar_texto(
                    retorno.get("status", SANCES_STATUS_ERRO)
                ).upper() or SANCES_STATUS_ERRO

                ag.sances_enviado = bool(retorno.get("sucesso", False))

                ag.sances_protocolo = limpar_texto(
                    retorno.get("protocolo_sances", "")
                )

                ag.sances_erro = limpar_texto(
                    retorno.get("erro", "")
                )

                if ag.sances_enviado:
                    ag.sances_data_envio = agora_time

                if hasattr(ag, "sances_tentativas"):
                    ag.sances_tentativas = tentativas + 1

                if hasattr(ag, "sances_ultima_tentativa"):
                    ag.sances_ultima_tentativa = agora_time

                if hasattr(ag, "sances_ultimo_retorno"):
                    ag.sances_ultimo_retorno = str(retorno)

                if hasattr(ag, "atualizado_em"):
                    ag.atualizado_em = agora_time

                db.commit()

                log_info(
                    "[SANCES WORKER] Reenvio processado:",
                    str(getattr(ag, "protocolo", "") or ""),
                    ag.sances_status,
                    f"Tentativa {getattr(ag, 'sances_tentativas', '')}",
                )

            except Exception as e:
                db.rollback()
                log_erro("Erro no retry Sances:", repr(e))

    except Exception as e:
        log_erro("Erro geral fila Sances:", repr(e))

    finally:
        db.close()


def worker():
    while True:
        try:
            processar_inatividade()
        except Exception as e:
            log_erro("Worker erro em processar_inatividade:", repr(e))

        try:
            processar_lembretes_agendamento()
        except Exception as e:
            log_erro("Worker erro em processar_lembretes_agendamento:", repr(e))

        # FOLLOW-UP DESATIVADO TEMPORARIAMENTE
        # try:
        #     processar_followup_inteligente()
        # except Exception as e:
        #     log_erro("Worker erro em processar_followup_inteligente:", repr(e))

        try:
            processar_fila_sances()
        except Exception as e:
            log_erro("Worker erro em processar_fila_sances:", repr(e))

        time.sleep(300)


def iniciar_worker():
    global worker_followup_iniciado

    if worker_followup_iniciado:
        return

    worker_followup_iniciado = True

    thread = threading.Thread(
        target=worker,
        daemon=True,
    )

    thread.start()

    log_info("Worker iniciado com sucesso.")


# ==========================================
# DASHBOARD
# ==========================================
@app.route("/dashboard")
def dashboard():
    db = SessionLocal()

    try:
        filtro = request.args.get("filtro", "hoje")
        hoje = datetime.now().date()

        query_atendimentos = db.query(Atendimento)
        query_agendamentos = db.query(AgendamentoRevisao)

        if filtro == "hoje":
            inicio = datetime.combine(hoje, datetime.min.time())
            fim = datetime.combine(hoje, datetime.max.time())

            query_atendimentos = query_atendimentos.filter(
                Atendimento.data >= inicio,
                Atendimento.data <= fim,
            )

            query_agendamentos = query_agendamentos.filter(
                AgendamentoRevisao.criado_em >= inicio,
                AgendamentoRevisao.criado_em <= fim,
            )

        elif filtro == "semana":
            inicio = datetime.combine(
                hoje - timedelta(days=7),
                datetime.min.time(),
            )
            fim = datetime.combine(hoje, datetime.max.time())

            query_atendimentos = query_atendimentos.filter(
                Atendimento.data >= inicio,
                Atendimento.data <= fim,
            )

            query_agendamentos = query_agendamentos.filter(
                AgendamentoRevisao.criado_em >= inicio,
                AgendamentoRevisao.criado_em <= fim,
            )

        elif filtro == "mes":
            inicio = datetime.combine(
                hoje.replace(day=1),
                datetime.min.time(),
            )
            fim = datetime.combine(hoje, datetime.max.time())

            query_atendimentos = query_atendimentos.filter(
                Atendimento.data >= inicio,
                Atendimento.data <= fim,
            )

            query_agendamentos = query_agendamentos.filter(
                AgendamentoRevisao.criado_em >= inicio,
                AgendamentoRevisao.criado_em <= fim,
            )

        atendimentos = query_atendimentos.all()

        agendamentos_lista = (
            query_agendamentos
            .order_by(AgendamentoRevisao.id.desc())
            .limit(50)
            .all()
        )

        total = len(atendimentos)

        total_revisoes = sum(
            1 for a in atendimentos
            if str(getattr(a, "setor", "") or "").lower() in [
                "revisão",
                "revisao",
            ]
        )

        agendados = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "status", "") or "").upper() == STATUS_AGENDADO
        )

        concluidos = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "status", "") or "").upper() in [
                "CONCLUIDO",
                "CONCLUÍDO",
                STATUS_FINALIZADO,
            ]
        )

        cancelados = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "status", "") or "").upper() == STATUS_CANCELADO
        )

        reagendados = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "status", "") or "").upper() == STATUS_REAGENDADO
        )

        atendimento_humano = sum(
            1 for a in atendimentos
            if bool(getattr(a, "atendimento_humano", False))
        )

        duvidas_ia = sum(
            1 for a in atendimentos
            if "dúvida" in str(getattr(a, "setor", "") or "").lower()
            or "duvida" in str(getattr(a, "setor", "") or "").lower()
            or str(getattr(a, "intencao_ia", "") or "").lower() == "duvidas"
        )

        sances_pendentes = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "sances_status", "") or "").upper() == SANCES_STATUS_PENDENTE
        )

        sances_enviados = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "sances_status", "") or "").upper() == SANCES_STATUS_ENVIADO
        )

        sances_erros = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "sances_status", "") or "").upper() == SANCES_STATUS_ERRO
        )

        sances_nao_configurado = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "sances_status", "") or "").upper() == SANCES_STATUS_NAO_CONFIGURADO
        )

        primeira = segunda = terceira = quarta = quinta = 0

        for ag in agendamentos_lista:
            rev = str(getattr(ag, "revisao", "") or "").strip()

            if rev == "1":
                primeira += 1
            elif rev == "2":
                segunda += 1
            elif rev == "3":
                terceira += 1
            elif rev == "4":
                quarta += 1
            elif rev:
                quinta += 1

        contador_itens = Counter()

        for ag in agendamentos_lista:
            itens = (
                getattr(ag, "itens", "")
                or getattr(ag, "venda_adicional", "")
                or ""
            )

            if not itens:
                continue

            partes = re.split(r",|;|\n|\+", str(itens))

            for item in partes:
                item_limpo = item.strip()

                if item_limpo and item_limpo.lower() not in [
                    "nenhum",
                    "não",
                    "nao",
                    "sem interesse",
                ]:
                    contador_itens[item_limpo] += 1

        ranking_itens = contador_itens.most_common(10)
        total_itens_vendidos = sum(contador_itens.values())
        total_agendamentos_periodo = len(agendamentos_lista)

        return render_template(
            "dashboard.html",
            filtro_ativo=filtro,
            total=total,
            total_revisoes=total_revisoes,
            revisao=total_revisoes,
            sances_pendentes=sances_pendentes,
            sances_enviados=sances_enviados,
            sances_erros=sances_erros,
            sances_nao_configurado=sances_nao_configurado,
            agendados=agendados,
            concluidos=concluidos,
            cancelados=cancelados,
            reagendados=reagendados,
            atendimento_humano=atendimento_humano,
            duvidas_ia=duvidas_ia,
            total_itens_vendidos=total_itens_vendidos,
            total_agendamentos_periodo=total_agendamentos_periodo,
            primeira=primeira,
            segunda=segunda,
            terceira=terceira,
            quarta=quarta,
            quinta=quinta,
            ranking_itens=ranking_itens,
            agendamentos=agendamentos_lista,
        )

    except Exception as e:
        log_erro("Erro no dashboard:", repr(e))
        return f"Erro ao carregar dashboard: {e}", 500

    finally:
        db.close()


# ==========================================
# CLIENTES CRM
# ==========================================
@app.route("/clientes")
def pagina_clientes():
    db = SessionLocal()

    try:
        atendimentos = (
            db.query(Atendimento)
            .order_by(Atendimento.id.desc())
            .limit(150)
            .all()
        )

        return render_template(
            "clientes.html",
            atendimentos=atendimentos,
        )

    except Exception as e:
        log_erro("Erro na tela de clientes:", repr(e))
        return f"Erro: {e}", 500

    finally:
        db.close()


# ==========================================
# REENVIO MANUAL SANCES
# ==========================================
@app.route("/reenvio-sances/<protocolo>", methods=["POST"])
def reenvio_sances(protocolo):
    try:
        protocolo = limpar_texto(protocolo).upper()

        if not protocolo:
            return jsonify({
                "ok": False,
                "mensagem": "Protocolo inválido.",
            }), 400

        ag = buscar_agendamento_por_protocolo(protocolo)

        if not ag:
            return jsonify({
                "ok": False,
                "mensagem": "Agendamento não encontrado.",
            }), 404

        dados_reenvio = montar_dados_agendamento_para_reenvio(ag)

        if not dados_reenvio or not dados_reenvio.get("telefone"):
            return jsonify({
                "ok": False,
                "mensagem": "Dados inválidos para reenvio.",
            }), 400

        retorno_sances = enviar_agendamento_para_sances(dados_reenvio)

        if not isinstance(retorno_sances, dict):
            retorno_sances = {
                "sucesso": False,
                "status": SANCES_STATUS_ERRO,
                "protocolo_sances": "",
                "erro": "Retorno inválido do Sances.",
            }

        atualizado = atualizar_status_sances_agendamento(
            protocolo,
            retorno_sances,
        )

        if not atualizado:
            return jsonify({
                "ok": False,
                "mensagem": "Falha ao atualizar status do Sances no banco.",
            }), 500

        return jsonify({
            "ok": True,
            "mensagem": "Reenvio processado com sucesso.",
            "status": retorno_sances.get("status", SANCES_STATUS_ERRO),
            "protocolo_sances": retorno_sances.get("protocolo_sances", ""),
            "erro": retorno_sances.get("erro", ""),
        }), 200

    except Exception as e:
        log_erro("Erro na rota de reenvio Sances:", repr(e))

        return jsonify({
            "ok": False,
            "mensagem": "Erro interno ao reenviar para o Sances.",
        }), 500
# ==========================================
# FOLLOW-UP INTELIGENTE (V2)
# ==========================================
def identificar_contexto_followup(at):
    setor = limpar_texto(getattr(at, "setor", "") or "").lower()
    etapa = limpar_texto(getattr(at, "etapa", "") or "").lower()
    status = normalizar_status(getattr(at, "status", "") or "")

    if status == normalizar_status(STATUS_AGENDADO):
        return "agendado"

    if "revisao_confirmacao" in etapa:
        return "fechamento_revisao"

    if (
        "revisao_horario" in etapa
        or "revisao_data" in etapa
        or "revisao_dia" in etapa
    ):
        return "agenda_revisao"

    if etapa.startswith("revisao") or setor in ["revisão", "revisao"]:
        return "revisao"

    if setor in ["peças", "pecas"] or etapa == "pecas":
        return "pecas"

    if setor in ["acessórios", "acessorios"] or etapa in [
        "acessorios",
        "acessorios_modelo",
        "acessorios_orcamento",
    ]:
        return "acessorios"

    if setor == "garantia" or etapa == "garantia":
        return "garantia"

    if "atacado" in setor or "logista" in setor or etapa == "atacado":
        return "atacado"

    if "duvida" in etapa or "dúvida" in setor or "duvida" in setor:
        return "duvidas"

    return "geral"


def obter_tempos_followup_por_contexto(contexto):
    tempos = {
        "fechamento_revisao": 90 * 60,
        "agenda_revisao": 90 * 60,
        "revisao": 90 * 60,
        "pecas": 90 * 60,
        "acessorios": 90 * 60,
        "garantia": 90 * 60,
        "atacado": 90 * 60,
        "duvidas": 90 * 60,
        "geral": 90 * 60,
    }

    return float(tempos.get(contexto, 90 * 60))


def montar_mensagem_followup_inteligente(at):
    contexto = identificar_contexto_followup(at)
    nome = limpar_texto(getattr(at, "nome", "") or "").title()
    modelo = limpar_texto(getattr(at, "modelo", "") or "").upper()

    saudacao = f"Oi, {nome}! " if nome else "Oi! "

    mensagens = {
        "fechamento_revisao": (
            saudacao +
            "vi que seu agendamento de revisão não foi finalizado.\n\n"
            "Se quiser, posso continuar de onde parou para concluir seu atendimento 🛠️🏍️"
        ),
        "agenda_revisao": (
            saudacao +
            "vi que você começou seu agendamento de revisão e não concluiu.\n\n"
            "Posso continuar com você agora? 🚀"
        ),
        "revisao": (
            saudacao +
            (
                f"vi que você iniciou um atendimento de revisão da *{modelo}* e não finalizou.\n\n"
                if modelo else
                "vi que você iniciou um atendimento de revisão e não finalizou.\n\n"
            ) +
            "Quer continuar agora?"
        ),
        "pecas": (
            saudacao +
            "vi que você iniciou uma solicitação de peças e não finalizou.\n\n"
            "Se quiser, posso continuar seu atendimento agora 🔧"
        ),
        "acessorios": (
            saudacao +
            "vi que você iniciou uma solicitação de acessórios e não finalizou.\n\n"
            "Se quiser, posso continuar seu atendimento agora 🏍️"
        ),
        "garantia": (
            saudacao +
            "vi que você iniciou uma solicitação de garantia e não finalizou.\n\n"
            "Se quiser, posso continuar seu atendimento agora."
        ),
        "atacado": (
            saudacao +
            "vi que você iniciou uma solicitação comercial e não finalizou.\n\n"
            "Se quiser, posso continuar seu atendimento agora."
        ),
        "duvidas": (
            saudacao +
            "vi que você iniciou uma dúvida e não finalizou o atendimento.\n\n"
            "Posso continuar te ajudando agora?"
        ),
        "geral": (
            saudacao +
            "vi que você começou um atendimento e não finalizou.\n\n"
            "Posso te ajudar a concluir agora?"
        ),
    }

    return mensagens.get(contexto, mensagens["geral"])


def resetar_followups_do_cliente(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    db = SessionLocal()

    try:
        atendimento = (
            db.query(Atendimento)
            .filter(
                Atendimento.telefone == telefone,
                Atendimento.concluido == False,
            )
            .order_by(Atendimento.id.desc())
            .first()
        )

        if atendimento:
            atendimento.followup_1 = False

            if hasattr(atendimento, "followup_2"):
                atendimento.followup_2 = False

            if hasattr(atendimento, "followup_3"):
                atendimento.followup_3 = False

            atendimento.ultima_interacao = datetime.now()

            if hasattr(atendimento, "ultima_mensagem_cliente"):
                atendimento.ultima_mensagem_cliente = datetime.now()

            if hasattr(atendimento, "followup_respondido"):
                atendimento.followup_respondido = True

            if hasattr(atendimento, "followup_recuperado"):
                atendimento.followup_recuperado = True

            db.commit()

            return True

        return False

    except Exception as e:
        db.rollback()
        log_erro("Erro reset followup:", repr(e))
        return False

    finally:
        db.close()


def processar_followup_inteligente():
    # FOLLOW-UP DESATIVADO TEMPORARIAMENTE
    return


# ==========================================
# CONTROLE SEGURO DA IA NO WEBHOOK
# ==========================================
def etapa_permite_ia_livre(etapa):
    etapas_bloqueadas = [
        "revisao_modelo",
        "revisao_nome",
        "revisao_cpf",
        "revisao_ano",
        "revisao_km",
        "revisao_revisao",
        "revisao_dia",
        "revisao_data",
        "revisao_horario",
        "revisao_tipo_atendimento",
        "revisao_venda",
        "revisao_observacao",
        "revisao_confirmacao",
        "acessorios_modelo",
        "acessorios_orcamento",
        "atendimento_humano",
    ]

    return etapa not in etapas_bloqueadas


def texto_parece_menu_ou_saudacao(texto_normalizado):
    return texto_normalizado in [
        "menu",
        "inicio",
        "início",
        "voltar",
        "oi",
        "ola",
        "olá",
        "bom dia",
        "boa tarde",
        "boa noite",
    ]


def interpretar_botao_menu_rapido(telefone, button_id):
    telefone = limpar_telefone(telefone)
    button_id = limpar_texto(button_id).upper()

    if not telefone or not button_id:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["button_id"] = button_id
    clientes[telefone]["ultima_interacao"] = agora()

    if button_id in ["MENU", "VOLTAR_MENU"]:
        enviar_menu(telefone)
        return True

    if button_id in ["MENU_REVISAO", "AGENDAR_REVISAO"]:
        proxima = iniciar_fluxo_revisao_por_intencao(telefone, {})
        enviar_proxima_etapa_revisao(telefone)
        return True

    if button_id == "MENU_PECAS":
        iniciar_fluxo_pecas(telefone)
        return True

    if button_id == "MENU_ACESSORIOS":
        iniciar_fluxo_acessorios(telefone)
        return True

    if button_id == "MENU_GARANTIA":
        clientes[telefone]["etapa"] = "garantia"
        clientes[telefone]["intencao_ia"] = "garantia"

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Garantia",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="garantia_iniciada",
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=False,
        )

        enviar_mensagem(
            telefone,
            "🛡️ *Garantia*\n\nDescreva sua solicitação de garantia:"
        )

        return True

    if button_id == "MENU_ATACADO":
        clientes[telefone]["etapa"] = "atacado"
        clientes[telefone]["intencao_ia"] = "atacado"

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Logista / Atacado",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="atacado_iniciado",
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=False,
        )

        enviar_mensagem(
            telefone,
            "📦 *Logista / Atacado*\n\nDigite sua solicitação de atacado:"
        )

        return True

    if button_id in ["MENU_DUVIDAS", "DUVIDA_OUTRA"]:
        encaminhar_para_menu_duvidas(telefone, clientes[telefone].get("etapa", ""))
        return True

    if button_id == "DUVIDA_REVISOES":
        clientes[telefone]["etapa"] = "duvidas_revisoes"
        clientes[telefone]["categoria_duvida"] = "revisoes"
        clientes[telefone]["intencao_ia"] = "duvidas"

        enviar_mensagem(
            telefone,
            "📘 *Dúvidas sobre Revisões*\n\n"
            "Pode me enviar sua dúvida sobre revisão."
        )

        return True

    if button_id == "DUVIDA_GARANTIA":
        clientes[telefone]["etapa"] = "duvidas_garantia"
        clientes[telefone]["categoria_duvida"] = "garantia"
        clientes[telefone]["intencao_ia"] = "duvidas"

        enviar_mensagem(
            telefone,
            "🛡️ *Dúvidas sobre Garantia*\n\n"
            "Pode me enviar sua dúvida sobre garantia."
        )

        return True

    if button_id == "DUVIDA_CONTINUAR":
        etapa_retorno = limpar_texto(clientes[telefone].get("etapa_retorno_duvida", ""))

        if etapa_retorno:
            clientes[telefone]["etapa"] = etapa_retorno
            enviar_proxima_etapa_revisao(telefone)
            return True

        enviar_menu(telefone)
        return True

    if button_id == "MENU_HUMANO":
        ativar_atendimento_humano(telefone)
        return True

    return False


def tentar_interpretar_ia_no_menu(telefone, texto):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    button_id = normalizar_botao_zapi(texto)

    if button_id:
        clientes[telefone]["button_id"] = button_id

        if interpretar_botao_menu_rapido(telefone, button_id):
            return True

    resposta_ia = obter_dados_extraidos_ia(texto)

    intencao = limpar_texto(resposta_ia.get("intencao", "")).lower()
    confianca = float(resposta_ia.get("confianca", 0.0) or 0.0)
    resposta_texto = limpar_texto(resposta_ia.get("resposta", ""))
    dados_extraidos = resposta_ia.get("dados_extraidos", {}) or {}

    clientes[telefone]["intencao_ia"] = intencao

    log_info(
        "IA WEBHOOK:",
        {
            "telefone": telefone,
            "intencao": intencao,
            "confianca": confianca,
            "dados_extraidos": dados_extraidos,
        },
    )

    if confianca < 0.55 and intencao not in [
        "agendar_revisao",
        "valor_revisao",
        "pecas",
        "acessorios",
        "garantia",
        "atacado",
        "humano",
        "duvidas",
        "duvida",
        "dúvidas",
        "dúvida",
    ]:
        return False

    if intencao == "agendar_revisao":
        iniciar_fluxo_revisao_por_intencao(telefone, dados_extraidos)

        resumo = montar_resumo_dados_ia_revisao(telefone)

        if resumo:
            enviar_mensagem(telefone, resumo)

        enviar_proxima_etapa_revisao(telefone)

        return True

    if intencao == "valor_revisao":
        clientes[telefone]["etapa"] = "menu_duvidas"
        clientes[telefone]["categoria_duvida"] = "revisoes"

        if resposta_texto:
            enviar_mensagem(telefone, resposta_texto)
        else:
            resposta_duvida = responder_duvida_por_tabela(
                categoria="revisoes",
                pergunta_cliente=texto,
                modelo=dados_extraidos.get("modelo", ""),
                revisao=dados_extraidos.get("revisao", ""),
            )

            enviar_mensagem(
                telefone,
                resposta_duvida or "Não encontrei essa informação no momento.",
            )

        enviar_mensagem_botoes(
            telefone,
            "Deseja agendar sua revisão agora?",
            [
                {"label": "Agendar", "id": "AGENDAR_REVISAO"},
                {"label": "Menu", "id": "MENU"},
                {"label": "Humano", "id": "MENU_HUMANO"},
            ],
        )

        return True

    if intencao == "pecas":
        iniciar_fluxo_pecas(telefone, texto)
        return True

    if intencao == "acessorios":
        modelo_ia = ""

        if isinstance(dados_extraidos, dict):
            modelo_ia = limpar_texto(dados_extraidos.get("modelo", ""))

        if modelo_ia:
            iniciar_fluxo_acessorios(telefone, modelo_ia)
        else:
            iniciar_fluxo_acessorios(telefone)

        return True

    if intencao == "garantia":
        clientes[telefone]["etapa"] = "garantia"
        clientes[telefone]["atendimento_humano"] = False
        clientes[telefone]["ultima_interacao"] = agora()
        clientes[telefone]["intencao_ia"] = "garantia"

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Garantia",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="garantia_iniciada",
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=False,
        )

        if resposta_texto:
            enviar_mensagem(telefone, resposta_texto)

        enviar_mensagem(
            telefone,
            "🛡️ *Garantia*\n\nDescreva sua solicitação de garantia:"
        )

        return True

    if intencao == "atacado":
        clientes[telefone]["etapa"] = "atacado"
        clientes[telefone]["atendimento_humano"] = False
        clientes[telefone]["ultima_interacao"] = agora()
        clientes[telefone]["intencao_ia"] = "atacado"

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Logista / Atacado",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="atacado_iniciado",
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=False,
        )

        if resposta_texto:
            enviar_mensagem(telefone, resposta_texto)

        enviar_mensagem(
            telefone,
            "📦 *Logista / Atacado*\n\nDigite sua solicitação de atacado:"
        )

        return True

    if intencao in ["duvidas", "duvida", "dúvidas", "dúvida"]:
        clientes[telefone]["etapa"] = "menu_duvidas"
        clientes[telefone]["ultima_interacao"] = agora()
        clientes[telefone]["intencao_ia"] = "duvidas"

        encaminhar_para_menu_duvidas(telefone, clientes[telefone].get("etapa", ""))

        return True

    if intencao == "humano":
        ativar_atendimento_humano(telefone)
        return True

    return False
# ==========================================
# EXTRAÇÃO Z-API WEBHOOK
# ==========================================
def extrair_dados_zapi(payload):
    try:
        message_id = extrair_message_id(payload)
        telefone = extrair_telefone(payload)
        texto = extrair_texto(payload)
        tipo_mensagem = extrair_tipo_mensagem(payload)

        telefone = limpar_telefone(telefone)
        texto = limpar_texto(texto)
        tipo_mensagem = limpar_texto(tipo_mensagem).lower() or "text"

        return message_id, telefone, texto, tipo_mensagem

    except Exception as e:
        log_erro("Erro ao extrair dados Z-API:", repr(e))
        return "", "", "", "text"


# ==========================================
# CONTROLE DUPLICIDADE MENSAGENS
# ==========================================
def mensagem_ja_processada(message_id):
    try:
        if not message_id:
            return False

        return message_id in mensagens_processadas

    except Exception as e:
        log_erro("Erro mensagem_ja_processada:", repr(e))
        return False


def registrar_mensagem_processada(message_id):
    try:
        if not message_id:
            return

        if message_id in mensagens_processadas:
            return

        if len(fila_mensagens_processadas) >= fila_mensagens_processadas.maxlen:
            antigo = fila_mensagens_processadas.popleft()
            mensagens_processadas.discard(antigo)

        fila_mensagens_processadas.append(message_id)
        mensagens_processadas.add(message_id)

    except Exception as e:
        log_erro("Erro registrar_mensagem_processada:", repr(e))

# ==========================================
# WEBHOOK - Z-API
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    # ==========================================
    # VERIFICAÇÃO
    # ==========================================
    if request.method == "GET":
        return jsonify({
            "status": "online",
            "message": "Webhook Z-API ativo"
        }), 200

    try:
        payload = request.get_json(silent=True) or {}

        log_info("PAYLOAD Z-API:", payload)

        # ==========================================
        # IGNORA EVENTOS DO PRÓPRIO BOT
        # ==========================================
        if evento_eh_do_proprio_bot(payload):
            return jsonify({
                "status": "ignorado",
                "motivo": "mensagem_proprio_bot"
            }), 200

        # ==========================================
        # EXTRAÇÃO
        # ==========================================
        message_id, telefone, texto, tipo_mensagem = extrair_dados_zapi(payload)

        telefone = limpar_telefone(telefone)
        texto = limpar_texto(texto)

        texto_normalizado = normalizar_texto(texto)
        texto_opcao = limpar_opcao(texto)

        if not telefone:
            return jsonify({
                "status": "ignorado",
                "motivo": "telefone_invalido"
            }), 200

        # ==========================================
        # IGNORA GRUPOS
        # ==========================================
        if telefone_eh_grupo(str(payload)):
            return jsonify({
                "status": "ignorado",
                "motivo": "grupo"
            }), 200

        # ==========================================
        # DUPLICIDADE
        # ==========================================
        if message_id and mensagem_ja_processada(message_id):
            return jsonify({
                "status": "ignorado",
                "motivo": "duplicado"
            }), 200

        if message_id:
            registrar_mensagem_processada(message_id)

        # ==========================================
        # INICIA CLIENTE
        # ==========================================
        iniciar_cliente(telefone)

        # ==========================================
        # IGNORA EVENTOS SEM TEXTO
        # ==========================================
        if (
            not texto.strip()
            and tipo_mensagem not in [
                "text",
                "extendedTextMessage",
                "conversation",
                "button"
            ]
        ):
            log_info(
                f"Evento ignorado sem texto útil | "
                f"Telefone={telefone} Tipo={tipo_mensagem}"
            )

            return jsonify({
                "status": "ignorado",
                "motivo": "evento_sem_texto"
            }), 200

        # ==========================================
        # TRAVA HUMANO
        # ==========================================
        if (
            clientes[telefone].get("atendimento_humano", False)
            or atendimento_humano_ativo_no_banco(telefone)
        ):

            atualizar_interacao(telefone)
            atualizar_ultima_mensagem_cliente(telefone)

            if texto_normalizado == "menu":
                encerrar_atendimento_humano(telefone)

                clientes[telefone]["atendimento_humano"] = False
                clientes[telefone]["etapa"] = "menu"

                enviar_mensagem(
                    telefone,
                    "✅ Atendimento automático reativado.\n\nVoltando ao menu principal."
                )

                enviar_menu(telefone)

                return jsonify({
                    "status": "ok",
                    "motivo": "retorno_menu"
                }), 200

            log_info(
                f"Cliente em atendimento humano: {telefone}"
            )

            return jsonify({
                "status": "ignorado",
                "motivo": "atendimento_humano"
            }), 200

        # ==========================================
        # TIMEOUT
        # ==========================================
        ultima_interacao = clientes[telefone].get(
            "ultima_interacao",
            agora()
        )

        if (
            clientes[telefone].get("etapa", "menu") != "menu"
            and not clientes[telefone].get("atendimento_humano", False)
            and (agora() - ultima_interacao) > TEMPO_INATIVIDADE
        ):

            resetar_cliente(telefone)

            enviar_mensagem(
                telefone,
                "Olá 👋\n\nVoltando ao menu principal."
            )

            enviar_menu(telefone)

            return jsonify({
                "status": "ok",
                "motivo": "timeout"
            }), 200

        atualizar_interacao(telefone)
        atualizar_ultima_mensagem_cliente(telefone)
        resetar_followups_do_cliente(telefone)

        etapa = clientes[telefone].get("etapa", "menu")

        log_info({
            "telefone": telefone,
            "etapa": etapa,
            "texto": texto,
            "tipo": tipo_mensagem,
        })

        # ==========================================
        # ÁUDIO
        # ==========================================
        if tipo_mensagem == "audio":
            enviar_mensagem(
                telefone,
                "🎧 Recebi seu áudio.\n\n"
                "No momento consigo interpretar melhor mensagens em texto.\n\n"
                "Digite sua solicitação ou envie *menu*."
            )

            return jsonify({
                "status": "ok",
                "motivo": "audio"
            }), 200

        # ==========================================
        # MENU GLOBAL
        # ==========================================
        if texto_parece_menu_ou_saudacao(texto_normalizado):
            resetar_cliente(telefone)
            enviar_menu(telefone)

            return jsonify({
                "status": "ok",
                "motivo": "menu_global"
            }), 200

        # ==========================================
        # IA LIVRE
        # ==========================================
        if (
            etapa in ["menu", "menu_duvidas"]
            or etapa_permite_ia_livre(etapa)
        ):

            interpretado = tentar_interpretar_ia_no_menu(
                telefone,
                texto
            )

            if interpretado:
                return jsonify({
                    "status": "ok",
                    "motivo": "ia"
                }), 200

        # ==========================================
        # MENU
        # ==========================================
        if etapa == "menu":

            if texto_opcao == "1":
                iniciar_fluxo_revisao_por_intencao(
                    telefone,
                    {}
                )

                enviar_proxima_etapa_revisao(telefone)

                return jsonify({
                    "status": "ok",
                    "motivo": "revisao"
                }), 200

            elif texto_opcao == "2":
                iniciar_fluxo_pecas(telefone)

                return jsonify({
                    "status": "ok",
                    "motivo": "pecas"
                }), 200

            elif texto_opcao == "3":
                iniciar_fluxo_acessorios(telefone)

                return jsonify({
                    "status": "ok",
                    "motivo": "acessorios"
                }), 200

            elif texto_opcao == "4":

                clientes[telefone]["etapa"] = "garantia"

                salvar_evento_atendimento(
                    telefone=telefone,
                    setor="Garantia",
                    status=STATUS_NOVO_ATENDIMENTO,
                    etapa="garantia_iniciada",
                    dados=clientes[telefone],
                    atendimento_humano=False,
                    concluido=False,
                )

                enviar_mensagem(
                    telefone,
                    "🛡️ *Garantia*\n\n"
                    "Descreva sua solicitação:"
                )

                return jsonify({
                    "status": "ok",
                    "motivo": "garantia"
                }), 200

            elif texto_opcao == "5":

                clientes[telefone]["etapa"] = "atacado"

                salvar_evento_atendimento(
                    telefone=telefone,
                    setor="Logista / Atacado",
                    status=STATUS_NOVO_ATENDIMENTO,
                    etapa="atacado_iniciado",
                    dados=clientes[telefone],
                    atendimento_humano=False,
                    concluido=False,
                )

                enviar_mensagem(
                    telefone,
                    "📦 *Logista / Atacado*\n\n"
                    "Digite sua solicitação."
                )

                return jsonify({
                    "status": "ok",
                    "motivo": "atacado"
                }), 200

            elif texto_opcao == "6":

                clientes[telefone]["etapa"] = "menu_duvidas"

                enviar_mensagem(
                    telefone,
                    menu_duvidas()
                )

                return jsonify({
                    "status": "ok",
                    "motivo": "duvidas"
                }), 200

            elif texto_opcao == "7":

                ativar_atendimento_humano(telefone)

                return jsonify({
                    "status": "ok",
                    "motivo": "humano"
                }), 200

            enviar_menu(telefone)

            return jsonify({
                "status": "ok",
                "motivo": "menu_reenviado"
            }), 200

        # ==========================================
        # AQUI CONTINUA:
        # FLUXO REVISÃO
        # DÚVIDAS
        # PEÇAS
        # ACESSÓRIOS
        # GARANTIA
        # ATACADO
        # CONFIRMAÇÃO
        # EXATAMENTE COMO JÁ ESTÁ NO SEU CÓDIGO
        # ==========================================

        return jsonify({
            "status": "ok"
        }), 200

    except Exception as e:

        log_erro(
            "ERRO WEBHOOK Z-API:",
            repr(e)
        )

        return jsonify({
            "status": "erro",
            "mensagem": "erro interno"
        }), 200

# ==========================================
# CONTROLE WORKER
# ==========================================
worker_followup_iniciado = False


# ==========================================
# INICIAR WORKER
# ==========================================
try:
    iniciar_worker()

except Exception as e:
    log_erro(
        "Erro ao iniciar worker:",
        repr(e)
    )


# ==========================================
# START
# ==========================================
if __name__ == "__main__":

    try:
        porta = int(os.getenv("PORT", 5000))

    except Exception:
        porta = 5000

    log_info(
        f"BOT YAMAHA ONLINE iniciado na porta {porta}"
    )

    app.run(
        host="0.0.0.0",
        port=porta,
        debug=False,
        threaded=True,
    )