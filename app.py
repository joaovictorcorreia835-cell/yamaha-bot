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
# CONFIG - Z-API
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "").strip()
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "").strip()
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "").strip()
BASE_URL = os.getenv("BASE_URL", "").strip()

# Evita erro se vier vazio ou inválido
TEMPO_INATIVIDADE = int(os.getenv("TEMPO_INATIVIDADE", "43200") or 43200)

ARQUIVO_FOLLOWUP = os.getenv("ARQUIVO_FOLLOWUP", "clientes_disparo.xlsx").strip()
INTERVALO_WORKER_FOLLOWUP = int(os.getenv("INTERVALO_WORKER_FOLLOWUP", "300") or 300)
FOLLOWUP_1_HORAS = int(os.getenv("FOLLOWUP_1_HORAS", "48") or 48)
FOLLOWUP_2_DIAS = int(os.getenv("FOLLOWUP_2_DIAS", "5") or 5)

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
SANCES_MODO = (os.getenv("SANCES_MODO", "mock") or "mock").strip().lower()

# nao_configurado | enviado | erro
SANCES_SIMULAR_RESULTADO = (
    os.getenv("SANCES_SIMULAR_RESULTADO", "nao_configurado") or "nao_configurado"
).strip().lower()

SANCES_TIMEOUT = int(os.getenv("SANCES_TIMEOUT", "15") or 15)
SANCES_RETRY_MAX = int(os.getenv("SANCES_RETRY_MAX", "1") or 1)

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
# STATUS INTEGRACAO SANCES
# ==========================================
SANCES_STATUS_PENDENTE = "PENDENTE"
SANCES_STATUS_ENVIADO = "ENVIADO"
SANCES_STATUS_ERRO = "ERRO"
SANCES_STATUS_NAO_CONFIGURADO = "NAO_CONFIGURADO"

# ==========================================
# URLs Z-API
# ==========================================
if ZAPI_INSTANCE_ID and ZAPI_TOKEN:
    url_envio = (
        f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    )
    url_documento = (
        f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"
    )
else:
    url_envio = ""
    url_documento = ""

if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN or not ZAPI_CLIENT_TOKEN:
    print(
        "[ERRO] Z-API não configurada corretamente. "
        "Verifique ZAPI_INSTANCE_ID, ZAPI_TOKEN e ZAPI_CLIENT_TOKEN no .env"
    )

clientes = {}
mensagens_processadas = set()
fila_mensagens = deque(maxlen=5000)

followup_lock = threading.Lock()
worker_followup_iniciado = False

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


def normalizar_texto(texto):
    return limpar_texto(texto).lower()


# ==========================================
# 🔧 NOVO - APOIO ACESSÓRIOS
# ==========================================
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


def normalizar_modelo_acessorio(texto):
    texto = normalizar_texto(texto)
    texto = remover_acentos(texto)
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


def limpar_telefone(telefone):
    try:
        telefone = str(telefone or "").strip()
        telefone = (
            telefone.replace("@c.us", "")
            .replace("@s.whatsapp.net", "")
            .replace("@g.us", "")
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
    return "@g.us" in str(telefone or "")


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


def agora():
    return time.time()


def agora_datetime():
    return datetime.now()


def formatar_data_hora(dt=None):
    try:
        if dt is None:
            dt = datetime.now()
        elif not isinstance(dt, datetime):
            dt = parse_data_hora(dt) or datetime.now()
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return datetime.now().strftime("%d/%m/%Y %H:%M")


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


def data_texto_valida(valor):
    return parse_data_hora(valor) is not None


def normalizar_revisao_para_fluxo(valor):
    texto = limpar_opcao(valor)
    texto_norm = normalizar_texto(texto).replace(" ", "")

    mapa = {
        "1": "1",
        "1a": "1",
        "1ª": "1",
        "1o": "1",
        "primeira": "1",
        "2": "2",
        "2a": "2",
        "2ª": "2",
        "2o": "2",
        "segunda": "2",
        "3": "3",
        "3a": "3",
        "3ª": "3",
        "3o": "3",
        "terceira": "3",
        "4": "4",
        "4a": "4",
        "4ª": "4",
        "4o": "4",
        "quarta": "4",
        "5": "5",
        "5a": "5",
        "5ª": "5",
        "5o": "5",
        "quinta": "5",
    }

    if texto_norm in mapa:
        return mapa[texto_norm]

    if texto in ["1", "2", "3", "4", "5"]:
        return texto

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
    return MAPA_DIA_NUMERO.get(normalizar_texto(texto), "")


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


def normalizar_status(status):
    status = str(status or "").strip().upper()

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
        "POS_VENDA_ENVIADO": STATUS_POS_VENDA_ENVIADO,
        "ATENDIMENTO_HUMANO": STATUS_ATENDIMENTO_HUMANO,
        "HUMANO": STATUS_ATENDIMENTO_HUMANO,
        "ATENDIMENTO HUMANO": STATUS_ATENDIMENTO_HUMANO,
        "EM ATENDIMENTO": STATUS_NOVO_ATENDIMENTO,
    }

    return mapa.get(status, STATUS_NOVO_ATENDIMENTO)


def definir_status_cliente(telefone, status):
    if telefone not in clientes:
        clientes[telefone] = {}
    clientes[telefone]["status"] = normalizar_status(status)


def obter_status_cliente(telefone):
    if telefone not in clientes:
        return STATUS_NOVO_ATENDIMENTO
    return normalizar_status(clientes[telefone].get("status"))


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
        "km_atual": limpar_texto(dados.get("km_atual", "")),
        "data_agendada": limpar_texto(dados.get("data", "")),
        "horario": limpar_texto(dados.get("horario", "")),
        "observacao": limpar_texto(dados.get("observacao", "")),
        "itens": formatar_itens_adicionais_para_salvar(dados.get("itens", "")),
        "venda_adicional": formatar_itens_adicionais_para_salvar(
            dados.get("venda_adicional", "")
        ),
        "tipo_atendimento": limpar_texto(dados.get("tipo_atendimento", "")),
        "origem": "BOT_WHATSAPP",
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
            db.commit()

    except Exception as e:
        db.rollback()
        log_erro("Erro ao atualizar ultima mensagem cliente:", repr(e))

    finally:
        db.close()


def limpar_dados_fluxo_revisao(telefone):
    telefone = limpar_telefone(telefone)
    if not telefone:
        return

    iniciar_cliente(telefone)

    # 🔒 Preserva estado do atendimento humano
    atendimento_humano_ativo = clientes[telefone].get("atendimento_humano", False)
    etapa_atual = clientes[telefone].get("etapa", "")

    clientes[telefone]["modelo"] = ""
    clientes[telefone]["nome"] = ""
    clientes[telefone]["cpf"] = ""
    clientes[telefone]["ano"] = ""
    clientes[telefone]["revisao"] = ""
    clientes[telefone]["km_atual"] = ""
    clientes[telefone]["dia"] = ""
    clientes[telefone]["dia_texto"] = ""
    clientes[telefone]["data"] = ""
    clientes[telefone]["horario"] = ""
    clientes[telefone]["horarios_disponiveis"] = []
    clientes[telefone]["itens"] = ""
    clientes[telefone]["venda_adicional"] = ""
    clientes[telefone]["observacao"] = ""

    dados_cliente = clientes[telefone]
    dados_cliente["tipo_atendimento"] = ""
    dados_cliente["concluido"] = False
    dados_cliente["origem_etapa"] = ""
    dados_cliente["categoria_duvida"] = ""
    dados_cliente["etapa_retorno_duvida"] = ""

    # 🔥 NÃO destravar atendimento humano sem querer
    if not atendimento_humano_ativo and etapa_atual != "atendimento_humano":
        dados_cliente["atendimento_humano"] = False

    dados_cliente["sances_enviado"] = False
    dados_cliente["sances_status"] = SANCES_STATUS_PENDENTE
    dados_cliente["sances_protocolo"] = ""
    dados_cliente["sances_erro"] = ""
    dados_cliente["sances_data_envio"] = ""

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
    try:
        agora_atual = agora()

        for telefone in list(clientes.keys()):
            dados = clientes.get(telefone, {})
            ultima = dados.get("ultima_interacao", agora_atual)

            # 🔒 NÃO encerrar atendimento humano
            if (
                dados.get("atendimento_humano") is True
                or dados.get("etapa") == "atendimento_humano"
            ):
                continue

            if agora_atual - ultima > TEMPO_INATIVIDADE:
                resetar_cliente(telefone)

    except Exception as e:
        log_erro("Erro ao processar inatividade:", repr(e))


# ==========================================
# EXTRAÇÃO PAYLOAD
# ==========================================
def extrair_telefone(payload):
    try:
        telefone = (
            payload.get("phone")
            or payload.get("chatId")
            or payload.get("from")
            or payload.get("connectedPhone")
            or payload.get("remoteJid")
        )

        if not telefone:
            data = payload.get("data", {}) or {}
            telefone = (
                data.get("phone")
                or data.get("chatId")
                or data.get("from")
                or data.get("connectedPhone")
                or data.get("remoteJid")
            )

        if not telefone and isinstance(payload.get("sender"), dict):
            telefone = (
                payload.get("sender", {}).get("phone")
                or payload.get("sender", {}).get("id")
            )

        return limpar_telefone(telefone)

    except Exception as e:
        log_erro("Erro ao extrair telefone:", repr(e))
        return ""


def extrair_texto(payload):
    try:
        data = payload.get("data", {}) or {}

        candidatos = [
            data.get("text", {}).get("message") if isinstance(data.get("text"), dict) else None,
            data.get("text") if isinstance(data.get("text"), str) else None,
            data.get("body"),
            data.get("message"),
            data.get("caption"),
            data.get("extendedTextMessage", {}).get("text") if isinstance(data.get("extendedTextMessage"), dict) else None,
            data.get("conversation"),
            payload.get("text", {}).get("message") if isinstance(payload.get("text"), dict) else None,
            payload.get("text") if isinstance(payload.get("text"), str) else None,
            payload.get("body"),
            payload.get("message"),
            payload.get("caption"),
            payload.get("conversation"),
        ]

        for valor in candidatos:
            if valor is not None and str(valor).strip():
                return str(valor).strip()

        return ""

    except Exception as e:
        log_erro("Erro ao extrair texto:", repr(e))
        return ""


def extrair_message_id(payload):
    try:
        data = payload.get("data", {}) or {}
        return (
            data.get("id")
            or data.get("messageId")
            or payload.get("messageId")
            or payload.get("id")
            or ""
        )
    except Exception:
        return ""


def mensagem_ja_processada(message_id):
    if not message_id:
        return False
    return message_id in mensagens_processadas


def registrar_mensagem_processada(message_id):
    if not message_id:
        return

    if message_id in mensagens_processadas:
        return

    if len(fila_mensagens) >= fila_mensagens.maxlen:
        antigo = fila_mensagens.popleft()
        mensagens_processadas.discard(antigo)

    fila_mensagens.append(message_id)
    mensagens_processadas.add(message_id)


def evento_eh_do_proprio_bot(payload):
    try:
        data = payload.get("data", {}) or {}

        marcadores_true = [
            payload.get("fromMe"),
            payload.get("isFromMe"),
            payload.get("sentByMe"),
            data.get("fromMe"),
            data.get("isFromMe"),
            data.get("sentByMe"),
            data.get("isStatusReply"),
        ]

        return any(valor is True for valor in marcadores_true)

    except Exception as e:
        log_erro("Erro ao validar evento do próprio bot:", repr(e))
        return False


def extrair_tipo_mensagem(payload):
    try:
        data = payload.get("data", {}) or {}

        tipo = (
            data.get("type")
            or data.get("messageType")
            or payload.get("type")
            or payload.get("messageType")
            or ""
        )

        tipo = str(tipo).strip().lower()

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

        if data.get("audio") or data.get("ptt"):
            return "audio"

        return "text"

    except Exception as e:
        log_erro("Erro ao extrair tipo de mensagem:", repr(e))
        return "text"


# ==========================================
# ENVIO - Z-API WHATSAPP
# ==========================================
def url_zapi(endpoint):
    return (
        f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}"
        f"/token/{ZAPI_TOKEN}/{endpoint}"
    )


def headers_zapi():
    return {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN,
    }


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
            url_zapi("send-text"),
            json=payload,
            headers=headers_zapi(),
            timeout=30,
        )

        try:
            resposta_json = response.json()
        except Exception:
            resposta_json = response.text

        if response.status_code not in [200, 201]:
            log_erro("Falha envio mensagem Z-API:", response.status_code, resposta_json)
            return False

        log_info("Mensagem enviada Z-API:", telefone, response.status_code, resposta_json)
        return True

    except Exception as e:
        log_erro("Erro envio mensagem Z-API:", repr(e))
        return False


def enviar_pdf(telefone, arquivo, legenda=""):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            log_erro("Telefone inválido para envio de PDF.")
            return False

        if not zapi_configurada() or not BASE_URL:
            log_erro("Z-API/BASE_URL não configurados corretamente para envio de PDF.")
            return False

        if not arquivo:
            log_erro("Arquivo PDF não informado.")
            return False

        url_pdf = f"{BASE_URL}/pdf/{arquivo}"

        payload = {
            "phone": telefone,
            "document": url_pdf,
            "fileName": arquivo,
            "caption": legenda or "",
        }

        log_info("Enviando PDF Z-API:", url_pdf)

        response = requests.post(
            url_zapi("send-document/pdf"),
            json=payload,
            headers=headers_zapi(),
            timeout=30,
        )

        try:
            resposta_json = response.json()
        except Exception:
            resposta_json = response.text

        if response.status_code not in [200, 201]:
            log_erro("Falha envio PDF Z-API:", response.status_code, resposta_json)
            return False

        log_info("PDF enviado Z-API:", telefone, response.status_code, resposta_json)
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
            origem=limpar_texto(origem or "BOT"),
            status=normalizar_status(status),
            etapa=limpar_texto(etapa),
            atendimento_humano=bool(atendimento_humano),
            concluido=bool(concluido),
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
        "Estou aqui para te ajudar com seu atendimento.\n"
        "Escolha uma opção abaixo:\n\n"
        "1️⃣ Agendar Revisão\n"
        "2️⃣ Peças\n"
        "3️⃣ Acessórios\n"
        "4️⃣ Garantia\n"
        "5️⃣ Logista / Atacado\n"
        "6️⃣ Dúvidas\n"
        "7️⃣ Atendimento Humano\n\n"
        "Você pode responder com o *número da opção* ou me escrever o que precisa."
    )

    return enviar_mensagem(telefone, mensagem)


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

    if limpar_texto(texto_inicial):
        return enviar_mensagem(
            telefone,
            "🔩 *Peças*\n\n"
            "Perfeito, recebi sua solicitação 👍\n"
            "Nossa equipe vai verificar *valor* e *disponibilidade* para você.\n\n"
            "Se quiser complementar, pode me enviar:\n"
            "• modelo da moto\n"
            "• ano\n"
            "• peça desejada"
        )

    return enviar_mensagem(
        telefone,
        "🔩 *Peças*\n\n"
        "Me informe a *peça desejada* para eu registrar sua solicitação."
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

        log_info(
            f"Fluxo acessórios iniciado via IA | "
            f"Telefone={telefone} Modelo={clientes[telefone]['modelo']}"
        )

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
            "Perfeito 👍\n\n"
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
        "Se não quiser adicionar nada, digite *2*."
    )


def montar_resumo_confirmacao(telefone):
    telefone = limpar_telefone(telefone)
    dados = clientes.get(telefone, {})

    itens = formatar_itens_adicionais_para_salvar(
        dados.get("venda_adicional", "")
    )

    observacao = dados.get("observacao") or "Nenhuma"
    tipo_atendimento = dados.get("tipo_atendimento") or "Não informado"

    if limpar_texto(itens).upper() in [
        "",
        "NENHUM",
        "NAO",
        "NÃO",
        "SEM ITEM",
        "SEM ITENS",
        "2",
    ]:
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
        "Se estiver tudo certo, digite:\n"
        "*1* para confirmar agora ✅\n"
        "*2* para corrigir alguma informação"
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
        return (
            f"{resumo}"
            "Ótimo 😊\n\n"
            "Agora me informe seu *nome completo*."
        )

    if etapa == "revisao_cpf":
        return (
            "Perfeito.\n\n"
            "Agora preciso do seu *CPF com 11 números* para continuar o agendamento."
        )

    if etapa == "revisao_ano":
        return (
            "Certo 👍\n\n"
            "Me informe agora o *ano da sua moto*."
        )

    if etapa == "revisao_km":
        return (
            "Ótimo.\n\n"
            "Me informe a *quilometragem atual da moto*."
        )

    if etapa == "revisao_revisao":
        return (
            "🛠️ *Qual revisão você deseja agendar?*\n\n"
            "1 - 1ª Revisão\n"
            "2 - 2ª Revisão\n"
            "3 - 3ª Revisão\n"
            "4 - 4ª Revisão\n"
            "5 - 5ª Revisão ou acima"
        )

    if etapa == "revisao_dia":
        return (
            "📅 *Qual dia você prefere?*\n\n"
            "1 - Segunda\n"
            "2 - Terça\n"
            "3 - Quarta\n"
            "4 - Quinta\n"
            "5 - Sexta\n"
            "6 - Sábado"
        )

    if etapa == "revisao_data":
        return (
            "📆 Perfeito.\n\n"
            "Agora me informe a *data desejada* no formato *dd/mm/aaaa*."
        )

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
            if len(horario_limpo.split(":")[0]) == 1:
                horario_limpo = f"0{horario_limpo}"

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
        atendimento_humano=False,
        concluido=False,
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

            enviar_mensagem(
                telefone,
                mensagem_por_etapa_revisao(telefone, "revisao_dia"),
            )

            return True

        clientes[telefone]["horarios_disponiveis"] = horarios
        enviar_mensagem(telefone, montar_mensagem_horarios(horarios))
        return True

    enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, etapa))
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
        limite = limite_por_revisao(revisao)

        quantidade = (
            db.query(AgendamentoRevisao)
            .filter(
                AgendamentoRevisao.data_agendada == limpar_texto(data),
                AgendamentoRevisao.horario == limpar_texto(horario),
                AgendamentoRevisao.status == normalizar_status(STATUS_AGENDADO),
            )
            .count()
        )

        return quantidade < limite

    except Exception as e:
        log_erro("Erro capacidade:", repr(e))
        return True

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
        data_obj = datetime.strptime(data, "%d/%m/%Y")

        if data_obj.date() < datetime.now().date():
            return False

        # domingo
        if data_obj.weekday() == 6:
            return False

        return True

    except Exception:
        return False


def gerar_protocolo():
    return str(uuid.uuid4())[:8].upper()


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

        if not validar_data(data_agendada):
            log_erro("Data inválida ao salvar agendamento:", data_agendada)
            return False, ""

        if not verificar_capacidade(data_agendada, horario, revisao):
            log_erro(
                "Sem capacidade para salvar agendamento:",
                data_agendada,
                horario,
                revisao,
            )
            return False, ""

        protocolo = gerar_protocolo()

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

        agendamento = AgendamentoRevisao(
            protocolo=protocolo,
            telefone=telefone,
            nome=limpar_texto(dados.get("nome", "")),
            cpf=limpar_cpf(dados.get("cpf", "")),
            modelo=limpar_texto(dados.get("modelo", "")).upper(),
            ano=limpar_texto(dados.get("ano", "")),
            revisao=revisao,
            dia_semana=nome_dia(dados.get("dia", "")),
            data_agendada=data_agendada,
            horario=horario,
            itens=itens_formatados,
            venda_adicional=venda_formatada,
            status=normalizar_status(STATUS_AGENDADO),
            observacoes=observacao,
            origem="BOT",
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


def cancelar_agendamento(cpf, novo_status=STATUS_CANCELADO):
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
        dados["status"] = agendamento.status

        db.commit()

        log_info("Agendamento cancelado/reagendado:", dados)
        return dados

    except Exception as e:
        db.rollback()
        log_erro("Erro cancelar:", repr(e))
        return None

    finally:
        db.close()


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

        enviar_mensagem(
            telefone,
            "⚠️ Não localizei agendamento ativo para este CPF.\n\n"
            "Se quiser, posso iniciar um novo agendamento. Envie *quero agendar revisão*.",
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
        },
        atendimento_humano=False,
        concluido=False,
    )

    enviar_mensagem(
        telefone,
        "📋 *Agendamento localizado*\n\n"
        f"👤 {ag.get('nome', '')}\n"
        f"🏍️ {ag.get('modelo', '')}\n"
        f"📅 {ag.get('data_agendada', '')}\n"
        f"⏰ {ag.get('horario', '')}\n"
        f"📌 Protocolo: {ag.get('protocolo', '')}\n\n"
        "Equipe Motoshow Yamaha",
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

        ag_cancelado = cancelar_agendamento(cpf_limpo)

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

            enviar_mensagem(
                telefone,
                "⚠️ Não encontrei agendamento ativo para este CPF.",
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
            },
            atendimento_humano=False,
            concluido=True,
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

        enviar_mensagem(telefone, mensagem)
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

        enviar_mensagem(
            telefone,
            "⚠️ Não encontrei agendamento ativo para este CPF.",
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
        },
        atendimento_humano=False,
        concluido=False,
    )

    limpar_dados_fluxo_revisao(telefone)

    clientes[telefone]["modelo"] = limpar_texto(ag.get("modelo", "")).upper()
    clientes[telefone]["nome"] = limpar_texto(ag.get("nome", "")).upper()
    clientes[telefone]["cpf"] = limpar_cpf(ag.get("cpf", ""))
    clientes[telefone]["ano"] = limpar_texto(ag.get("ano", ""))
    clientes[telefone]["revisao"] = limpar_texto(ag.get("revisao", ""))
    clientes[telefone]["reagendamento"] = True
    clientes[telefone]["protocolo_antigo"] = ag.get("protocolo", "")

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

    enviar_mensagem(
        telefone,
        mensagem_por_etapa_revisao(telefone, "revisao_dia"),
    )

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
                data_criacao = getattr(ag, "data", None)

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
                    "Se precisar reagendar, responda esta mensagem."
                )

                enviado = enviar_mensagem(telefone, mensagem)

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
            atendimento_humano=False,
            concluido=False,
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

        setor = f"Dúvidas {limpar_texto(categoria)}".strip()

        return salvar_evento_atendimento(
            telefone=telefone,
            setor=setor,
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="duvida_respondida",
            dados={
                "observacao": (
                    f"Pergunta: {limpar_texto(pergunta)} | "
                    f"Resposta: {limpar_texto(resposta)}"
                )
            },
            atendimento_humano=False,
            concluido=True,
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

        enviar_mensagem(
            telefone,
            "Sem problema 👍 Vou te direcionar para a central de dúvidas "
            "e depois podemos voltar para o seu agendamento.",
        )

        enviar_mensagem(telefone, menu_duvidas())
        return True

    except Exception as e:
        log_erro("Erro ao encaminhar para menu de dúvidas:", repr(e))
        return False


def data_corresponde_ao_dia_escolhido(data_digitada, dia_escolhido):
    try:
        data_obj = datetime.strptime(limpar_texto(data_digitada), "%d/%m/%Y")
        dia_escolhido = str(dia_escolhido or "").strip()

        mapa = {
            "1": 0,
            "2": 1,
            "3": 2,
            "4": 3,
            "5": 4,
            "6": 5,
        }

        if dia_escolhido not in mapa:
            return False

        return data_obj.weekday() == mapa[dia_escolhido]

    except Exception as e:
        log_erro("Erro ao validar correspondência de dia/data:", repr(e))
        return False

# ==========================================
# WORKER
# ==========================================
def processar_fila_sances():
    db = SessionLocal()

    try:
        agora_time = datetime.now()

        agendamentos = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.sances_status.in_([
                SANCES_STATUS_PENDENTE,
                SANCES_STATUS_ERRO,
            ])
        ).all()

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
                ag.sances_erro = limpar_texto(retorno.get("erro", ""))

                if ag.sances_enviado:
                    ag.sances_data_envio = agora_time

                if hasattr(ag, "sances_tentativas"):
                    ag.sances_tentativas = tentativas + 1

                if hasattr(ag, "sances_ultima_tentativa"):
                    ag.sances_ultima_tentativa = agora_time

                if hasattr(ag, "sances_ultimo_retorno"):
                    ag.sances_ultimo_retorno = str(retorno)

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
        #     log_erro(
        #         "Worker erro em processar_followup_inteligente:",
        #         repr(e),
        #     )

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
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    log_info("Worker iniciado com sucesso.")


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
                Atendimento.data <= fim
            )

        elif filtro == "semana":
            inicio = datetime.combine(hoje - timedelta(days=7), datetime.min.time())
            fim = datetime.combine(hoje, datetime.max.time())
            query_atendimentos = query_atendimentos.filter(
                Atendimento.data >= inicio,
                Atendimento.data <= fim
            )

        elif filtro == "mes":
            inicio = datetime.combine(hoje.replace(day=1), datetime.min.time())
            fim = datetime.combine(hoje, datetime.max.time())
            query_atendimentos = query_atendimentos.filter(
                Atendimento.data >= inicio,
                Atendimento.data <= fim
            )

        atendimentos = query_atendimentos.all()

        agendamentos_lista = query_agendamentos.order_by(
            AgendamentoRevisao.id.desc()
        ).limit(50).all()

        total = len(atendimentos)

        total_revisoes = sum(
            1 for a in atendimentos
            if str(getattr(a, "setor", "") or "").lower() in ["revisão", "revisao"]
        )

        agendados = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "status", "") or "").upper() == "AGENDADO"
        )

        concluidos = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "status", "") or "").upper() in ["CONCLUIDO", "CONCLUÍDO", "FINALIZADO"]
        )

        cancelados = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "status", "") or "").upper() == "CANCELADO"
        )

        reagendados = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "status", "") or "").upper() == "REAGENDADO"
        )

        atendimento_humano = sum(
            1 for a in atendimentos
            if bool(getattr(a, "atendimento_humano", False))
        )

        duvidas_ia = sum(
            int(getattr(a, "duvidas_ia", 0) or 0)
            for a in atendimentos
        )

        sances_pendentes = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "sances_status", "") or "").upper() == "PENDENTE"
        )

        sances_enviados = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "sances_status", "") or "").upper() == "ENVIADO"
        )

        sances_erros = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "sances_status", "") or "").upper() == "ERRO"
        )

        sances_nao_configurado = sum(
            1 for ag in agendamentos_lista
            if str(getattr(ag, "sances_status", "") or "").upper() == "NAO_CONFIGURADO"
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
            itens = getattr(ag, "itens", "") or getattr(ag, "venda_adicional", "") or ""

            if not itens:
                continue

            partes = re.split(r",|;|\n|\+", str(itens))

            for item in partes:
                item_limpo = item.strip()

                if item_limpo and item_limpo.lower() not in ["nenhum", "não", "nao", "sem interesse"]:
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
            agendamentos=agendamentos_lista
        )

    except Exception as e:
        log_erro("Erro no dashboard:", repr(e))
        return f"Erro ao carregar dashboard: {e}", 500

    finally:
        db.close()

@app.route("/clientes")
def clientes():
    db = SessionLocal()

    try:
        atendimentos = (
            db.query(Atendimento)
            .order_by(Atendimento.id.desc())
            .limit(100)
            .all()
        )

        return render_template(
            "clientes.html",
            atendimentos=atendimentos
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


def tentar_interpretar_ia_no_menu(telefone, texto):
    telefone = limpar_telefone(telefone)
    if not telefone:
        return False

    iniciar_cliente(telefone)

    resposta_ia = obter_dados_extraidos_ia(texto)

    intencao = limpar_texto(resposta_ia.get("intencao", "")).lower()
    confianca = float(resposta_ia.get("confianca", 0.0) or 0.0)
    resposta_texto = limpar_texto(resposta_ia.get("resposta", ""))
    dados_extraidos = resposta_ia.get("dados_extraidos", {}) or {}

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
                resposta_duvida or "Não encontrei essa informação no momento."
            )

        enviar_mensagem(
            telefone,
            "Se quiser agendar sua revisão, me envie a mensagem em texto livre ou digite *1* no menu."
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

        enviar_mensagem(telefone, "🛡️ *Garantia*\n\nDescreva sua solicitação de garantia:")
        return True

    if intencao == "atacado":
        clientes[telefone]["etapa"] = "atacado"
        clientes[telefone]["atendimento_humano"] = False
        clientes[telefone]["ultima_interacao"] = agora()

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

        enviar_mensagem(telefone, "📦 *Logista / Atacado*\n\nDigite sua solicitação de atacado:")
        return True

    if intencao in ["duvidas", "duvida", "dúvidas", "dúvida"]:
        clientes[telefone]["etapa"] = "menu_duvidas"
        clientes[telefone]["ultima_interacao"] = agora()
        enviar_mensagem(telefone, menu_duvidas())
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
# WEBHOOK - Z-API
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # ==========================================
    # TESTE DO WEBHOOK NO RENDER / Z-API
    # ==========================================
    if request.method == "GET":
        return jsonify({
            "status": "ok",
            "message": "Webhook Z-API ativo"
        }), 200

    try:
        payload = request.get_json(silent=True) or {}
        log_info("PAYLOAD Z-API RECEBIDO:", payload)

        if evento_eh_do_proprio_bot(payload):
            return jsonify({
                "status": "ignorado",
                "motivo": "mensagem_do_proprio_bot"
            }), 200

        message_id, telefone, texto, tipo_mensagem = extrair_dados_zapi(payload)

        if not telefone:
            return jsonify({
                "status": "ignorado",
                "motivo": "sem_telefone"
            }), 200

        if telefone_eh_grupo(payload.get("chatId", "") or payload.get("from", "")):
            return jsonify({
                "status": "ignorado",
                "motivo": "grupo"
            }), 200

        if message_id and mensagem_ja_processada(message_id):
            return jsonify({
                "status": "ignorado",
                "motivo": "duplicado"
            }), 200

        telefone = limpar_telefone(telefone)
        texto = limpar_texto(texto or "")
        texto_normalizado = normalizar_texto(texto)
        texto_opcao = limpar_opcao(texto)

        if message_id:
            registrar_mensagem_processada(message_id)

        iniciar_cliente(telefone)

        if not texto.strip() and tipo_mensagem not in ["text", "button", "interactive"]:
            log_info(
                f"Evento ignorado sem texto útil. "
                f"Telefone={telefone} Tipo={tipo_mensagem}"
            )
            return jsonify({
                "status": "ignorado",
                "motivo": "evento_sem_texto_util"
            }), 200

        # ==========================================
        # TRAVA DE ATENDIMENTO HUMANO
        # ==========================================
        if (
            clientes[telefone].get("atendimento_humano", False)
            or atendimento_humano_ativo_no_banco(telefone)
        ):
            atualizar_interacao(telefone)
            atualizar_ultima_mensagem_cliente(telefone)
            resetar_followups_do_cliente(telefone)
            atualizar_retorno_na_planilha(telefone, texto)

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
                f"Cliente {telefone} está em atendimento humano. "
                f"Mensagem ignorada pelo bot. Tipo={tipo_mensagem}"
            )
            return jsonify({
                "status": "ignorado",
                "motivo": "atendimento_humano_ativo"
            }), 200

        # ==========================================
        # INATIVIDADE
        # ==========================================
        ultima_interacao = clientes[telefone].get("ultima_interacao", agora())

        if (
            clientes[telefone].get("etapa", "menu") != "menu"
            and not clientes[telefone].get("atendimento_humano", False)
            and (agora() - ultima_interacao) > TEMPO_INATIVIDADE
        ):
            resetar_cliente(telefone)
            enviar_mensagem(telefone, "Olá 👋\n\nVoltando ao menu principal.")
            enviar_menu(telefone)

            return jsonify({
                "status": "ok",
                "motivo": "timeout_retorno_menu"
            }), 200

        atualizar_interacao(telefone)
        atualizar_ultima_mensagem_cliente(telefone)
        resetar_followups_do_cliente(telefone)
        atualizar_retorno_na_planilha(telefone, texto)

        etapa = clientes[telefone].get("etapa", "menu")

        log_info(
            "CONTEXTO WEBHOOK Z-API:",
            {
                "telefone": telefone,
                "etapa": etapa,
                "texto": texto,
                "tipo_mensagem": tipo_mensagem,
            },
        )

        # ==========================================
        # ÁUDIO / MÍDIA
        # ==========================================
        if tipo_mensagem == "audio":
            enviar_mensagem(
                telefone,
                "🎧 Recebi seu áudio, mas no momento consigo interpretar melhor mensagens em texto.\n\n"
                "Por favor, envie sua solicitação digitada ou escolha uma opção do menu."
            )
            return jsonify({"status": "ok", "motivo": "audio_orientado"}), 200

        # ==========================================
        # RETORNO GLOBAL PARA MENU
        # ==========================================
        if texto_parece_menu_ou_saudacao(texto_normalizado):
            resetar_cliente(telefone)
            enviar_menu(telefone)
            return jsonify({"status": "ok", "motivo": "menu_global"}), 200

        # ==========================================
        # IA LIVRE SOMENTE EM CONTEXTO SEGURO
        # ==========================================
        if etapa in ["menu", "menu_duvidas"] or etapa_permite_ia_livre(etapa):
            interpretado = tentar_interpretar_ia_no_menu(telefone, texto)
            if interpretado:
                return jsonify({"status": "ok", "motivo": "ia_menu"}), 200

        # ==========================================
        # MENU PRINCIPAL
        # ==========================================
        if etapa == "menu":
            if texto_opcao == "1":
                iniciar_fluxo_revisao_por_intencao(telefone, {})
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok", "motivo": "menu_revisao"}), 200

            elif texto_opcao == "2":
                iniciar_fluxo_pecas(telefone)
                return jsonify({"status": "ok", "motivo": "menu_pecas"}), 200

            elif texto_opcao == "3":
                iniciar_fluxo_acessorios(telefone)
                return jsonify({"status": "ok", "motivo": "menu_acessorios"}), 200

            elif texto_opcao == "4":
                clientes[telefone]["etapa"] = "garantia"
                clientes[telefone]["ultima_interacao"] = agora()

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
                return jsonify({"status": "ok", "motivo": "menu_garantia"}), 200

            elif texto_opcao == "5":
                clientes[telefone]["etapa"] = "atacado"
                clientes[telefone]["ultima_interacao"] = agora()

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
                return jsonify({"status": "ok", "motivo": "menu_atacado"}), 200

            elif texto_opcao == "6":
                clientes[telefone]["etapa"] = "menu_duvidas"
                enviar_mensagem(telefone, menu_duvidas())
                return jsonify({"status": "ok", "motivo": "menu_duvidas"}), 200

            elif texto_opcao == "7":
                ativar_atendimento_humano(telefone)
                return jsonify({"status": "ok", "motivo": "menu_humano"}), 200

            enviar_menu(telefone)
            return jsonify({
                "status": "ok",
                "motivo": "texto_livre_menu_sem_acao"
            }), 200

        # ==========================================
        # FLUXO REVISÃO
        # ==========================================
        if etapa.startswith("revisao"):
            if etapa == "revisao_modelo":
                clientes[telefone]["modelo"] = texto.upper().strip()
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_nome":
                clientes[telefone]["nome"] = texto.upper().strip()
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_cpf":
                cpf = limpar_cpf(texto)

                if len(cpf) != 11:
                    enviar_mensagem(
                        telefone,
                        "⚠️ CPF inválido.\n\nEnvie apenas os *11 números do CPF* para continuar."
                    )
                    return jsonify({"status": "ok"}), 200

                clientes[telefone]["cpf"] = cpf
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_ano":
                ano = re.sub(r"\D", "", texto)

                if len(ano) != 4:
                    enviar_mensagem(
                        telefone,
                        "⚠️ Ano inválido.\n\nInforme o *ano da moto* com 4 números.\nExemplo: *2024*"
                    )
                    return jsonify({"status": "ok"}), 200

                clientes[telefone]["ano"] = ano
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_km":
                km = re.sub(r"\D", "", texto)

                if not km:
                    enviar_mensagem(
                        telefone,
                        "⚠️ Quilometragem inválida.\n\nInforme apenas números.\nExemplo: *6000*"
                    )
                    return jsonify({"status": "ok"}), 200

                clientes[telefone]["km_atual"] = km
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_revisao":
                revisao = normalizar_revisao_para_fluxo(texto)

                if revisao not in ["1", "2", "3", "4", "5"]:
                    enviar_mensagem(
                        telefone,
                        "⚠️ Opção inválida.\n\nDigite um número de *1 a 5* para escolher a revisão."
                    )
                    return jsonify({"status": "ok"}), 200

                clientes[telefone]["revisao"] = revisao
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_dia":
                dia = texto_opcao.strip()

                if dia not in ["1", "2", "3", "4", "5", "6"]:
                    dia = numero_dia_por_texto(texto)

                if dia not in ["1", "2", "3", "4", "5", "6"]:
                    enviar_mensagem(
                        telefone,
                        "⚠️ Dia inválido.\n\nEscolha uma opção de *1 a 6*."
                    )
                    return jsonify({"status": "ok"}), 200

                clientes[telefone]["dia"] = dia
                clientes[telefone]["dia_texto"] = nome_dia(dia)
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_data":
                data = texto.strip()

                if not re.match(r"^\d{2}/\d{2}/\d{4}$", data):
                    enviar_mensagem(
                        telefone,
                        "⚠️ Data inválida.\n\nEnvie no formato *DD/MM/AAAA*.\nExemplo: *25/04/2026*"
                    )
                    return jsonify({"status": "ok"}), 200

                if not validar_data(data):
                    enviar_mensagem(
                        telefone,
                        "⚠️ Data inválida.\n\nEscolha uma data futura e que não seja domingo."
                    )
                    return jsonify({"status": "ok"}), 200

                if not data_corresponde_ao_dia_escolhido(
                    data,
                    clientes[telefone].get("dia", "")
                ):
                    enviar_mensagem(
                        telefone,
                        "⚠️ A data informada não corresponde ao dia da semana escolhido.\n\n"
                        "Informe uma data compatível com o dia selecionado."
                    )
                    return jsonify({"status": "ok"}), 200

                clientes[telefone]["data"] = data
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_horario":
                horarios_disponiveis = clientes[telefone].get("horarios_disponiveis", [])

                if not horarios_disponiveis:
                    enviar_mensagem(
                        telefone,
                        "⚠️ Não encontrei horários disponíveis para essa escolha.\n\n"
                        "Vamos selecionar o dia novamente."
                    )
                    clientes[telefone]["dia"] = ""
                    clientes[telefone]["dia_texto"] = ""
                    clientes[telefone]["data"] = ""
                    clientes[telefone]["horarios_disponiveis"] = []
                    enviar_proxima_etapa_revisao(telefone)
                    return jsonify({"status": "ok"}), 200

                indice = re.sub(r"\D", "", texto_opcao)

                if not indice or not indice.isdigit():
                    enviar_mensagem(
                        telefone,
                        "⚠️ Opção inválida.\n\nResponda com o *número do horário* desejado."
                    )
                    return jsonify({"status": "ok"}), 200

                indice = int(indice)

                if indice < 1 or indice > len(horarios_disponiveis):
                    enviar_mensagem(
                        telefone,
                        "⚠️ Opção inválida.\n\nEscolha um número da lista de horários disponíveis."
                    )
                    return jsonify({"status": "ok"}), 200

                horario_escolhido = horarios_disponiveis[indice - 1]

                if not verificar_capacidade(
                    clientes[telefone].get("data", ""),
                    horario_escolhido,
                    clientes[telefone].get("revisao", "")
                ):
                    enviar_mensagem(
                        telefone,
                        "⚠️ Esse horário acabou de ficar indisponível.\n\nEscolha outro horário."
                    )

                    clientes[telefone]["horarios_disponiveis"] = [
                        h for h in horarios_disponiveis if h != horario_escolhido
                    ]

                    if clientes[telefone]["horarios_disponiveis"]:
                        enviar_mensagem(
                            telefone,
                            montar_mensagem_horarios(
                                clientes[telefone]["horarios_disponiveis"]
                            ),
                        )
                    else:
                        clientes[telefone]["horario"] = ""
                        clientes[telefone]["horarios_disponiveis"] = []
                        clientes[telefone]["dia"] = ""
                        clientes[telefone]["dia_texto"] = ""
                        clientes[telefone]["data"] = ""

                        enviar_mensagem(
                            telefone,
                            "⚠️ Não há mais horários disponíveis para essa data.\n\nVamos escolher outro dia."
                        )
                        enviar_proxima_etapa_revisao(telefone)

                    return jsonify({"status": "ok"}), 200

                clientes[telefone]["horario"] = horario_escolhido
                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_tipo_atendimento":
                opcao = texto_opcao.strip()

                if opcao == "1":
                    clientes[telefone]["tipo_atendimento"] = "AGUARDAR NA CONCESSIONÁRIA"
                elif opcao == "2":
                    clientes[telefone]["tipo_atendimento"] = "DEIXAR A MOTO E RETIRAR DEPOIS"
                else:
                    enviar_mensagem(
                        telefone,
                        "⚠️ Opção inválida.\n\n"
                        "Digite *1* para aguardar na concessionária ou *2* para deixar a moto e retirar depois."
                    )
                    return jsonify({"status": "ok"}), 200

                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_venda":
                resposta_venda = texto_normalizado.strip()

                if resposta_venda in ["2", "nao", "não", "nenhum", "nenhuma"]:
                    clientes[telefone]["venda_adicional"] = "Nenhum"
                    clientes[telefone]["itens"] = ""
                else:
                    clientes[telefone]["venda_adicional"] = texto.strip()
                    clientes[telefone]["itens"] = texto.strip()

                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_observacao":
                resposta_observacao = texto_normalizado.strip()

                if resposta_observacao in [
                    "2", "nao", "não", "nenhuma", "nenhum",
                    "sem observacao", "sem observação"
                ]:
                    clientes[telefone]["observacao"] = "Nenhuma"
                else:
                    clientes[telefone]["observacao"] = texto.strip()

                enviar_proxima_etapa_revisao(telefone)
                return jsonify({"status": "ok"}), 200

            elif etapa == "revisao_confirmacao":
                resposta = texto.strip().lower()

                if resposta in ["1", "sim", "confirmar", "confirmo"]:
                    try:
                        dados = clientes[telefone]
                        resultado_salvamento = salvar_agendamento(telefone, dados)

                        sucesso = False
                        protocolo = ""

                        if isinstance(resultado_salvamento, tuple):
                            sucesso = bool(resultado_salvamento[0])
                            protocolo = str(resultado_salvamento[1] or "")
                        elif isinstance(resultado_salvamento, str):
                            sucesso = True
                            protocolo = resultado_salvamento
                        elif resultado_salvamento is True:
                            sucesso = True

                        if sucesso:
                            enviar_mensagem(
                                telefone,
                                "✅ *Agendamento confirmado com sucesso*\n\n"
                                f"👤 {dados.get('nome', '').upper()}\n"
                                f"🏍️ {dados.get('modelo', '').upper()}\n"
                                f"📅 {dados.get('data', '')}\n"
                                f"⏰ {dados.get('horario', '')}\n"
                                f"📌 Protocolo: {protocolo}\n\n"
                                "📖 Lembrando de trazer o manual no momento da revisão para facilitar o atendimento.\n\n"
                                "🙏 Agradecemos por escolher a *Motoshow Yamaha* 🏍️"
                            )
                            resetar_cliente(telefone)

                        else:
                            enviar_mensagem(
                                telefone,
                                "❌ Erro ao salvar agendamento.\n\n"
                                "Verifique se o horário ainda está disponível e tente novamente."
                            )
                            log_erro(
                                "Falha no retorno do salvar_agendamento:",
                                repr(resultado_salvamento)
                            )

                    except Exception as e:
                        log_erro("ERRO AO CONFIRMAR AGENDAMENTO:", repr(e))
                        enviar_mensagem(
                            telefone,
                            "❌ Ocorreu um erro ao concluir seu agendamento.\n\nTente novamente em instantes."
                        )

                    return jsonify({"status": "ok"}), 200

                elif resposta in ["2", "nao", "não", "cancelar", "corrigir"]:
                    clientes[telefone]["horario"] = ""
                    clientes[telefone]["horarios_disponiveis"] = []
                    clientes[telefone]["tipo_atendimento"] = ""
                    clientes[telefone]["venda_adicional"] = ""
                    clientes[telefone]["observacao"] = ""

                    enviar_mensagem(
                        telefone,
                        "🔄 Tudo bem. Vamos ajustar as informações finais do agendamento."
                    )
                    enviar_proxima_etapa_revisao(telefone)
                    return jsonify({"status": "ok"}), 200

                enviar_mensagem(
                    telefone,
                    "Para confirmar, responda com *1*.\nSe quiser corrigir, responda com *2*."
                )
                return jsonify({"status": "ok"}), 200

            return jsonify({"status": "ok"}), 200

        # ==========================================
        # DÚVIDAS
        # ==========================================
        if etapa == "menu_duvidas":
            if texto_opcao == "1":
                clientes[telefone]["categoria_duvida"] = "revisoes"
                clientes[telefone]["etapa"] = "duvida_revisoes"

                enviar_mensagem(
                    telefone,
                    "📘 *Dúvidas sobre Revisões*\n\n"
                    "Envie sua dúvida em texto livre.\n\n"
                    "Exemplos:\n"
                    "• Qual o valor da revisão?\n"
                    "• O que troca na 2ª revisão?\n"
                    "• Quanto tempo demora?"
                )
                return jsonify({"status": "ok"}), 200

            elif texto_opcao == "2":
                clientes[telefone]["categoria_duvida"] = "garantia"
                clientes[telefone]["etapa"] = "duvida_garantia"

                enviar_mensagem(
                    telefone,
                    "📘 *Dúvidas sobre Garantia*\n\nEnvie sua dúvida em texto livre."
                )
                return jsonify({"status": "ok"}), 200

            elif texto_opcao == "3":
                clientes[telefone]["etapa"] = "menu"
                enviar_menu(telefone)
                return jsonify({"status": "ok"}), 200

            enviar_mensagem(telefone, menu_duvidas())
            return jsonify({"status": "ok"}), 200

        if etapa == "duvida_revisoes":
            resposta_duvida = responder_duvida_por_tabela(
                categoria="revisoes",
                pergunta_cliente=texto,
                modelo=clientes[telefone].get("modelo", ""),
                revisao=clientes[telefone].get("revisao", ""),
            )

            enviar_mensagem(
                telefone,
                resposta_duvida or "Não encontrei essa informação no momento."
            )

            salvar_duvida_dashboard(
                telefone,
                "Revisões",
                texto,
                resposta_duvida or ""
            )

            enviar_mensagem(
                telefone,
                "Se quiser fazer outra pergunta, pode me enviar agora.\n\n"
                "Para voltar ao menu principal, digite *menu*."
            )
            return jsonify({"status": "ok"}), 200

        if etapa == "duvida_garantia":
            resposta_duvida = responder_duvida_por_tabela(
                categoria="garantia",
                pergunta_cliente=texto,
                modelo=clientes[telefone].get("modelo", ""),
                revisao=clientes[telefone].get("revisao", ""),
            )

            enviar_mensagem(
                telefone,
                resposta_duvida or "Não encontrei essa informação no momento."
            )

            salvar_duvida_dashboard(
                telefone,
                "Garantia",
                texto,
                resposta_duvida or ""
            )

            enviar_mensagem(
                telefone,
                "Se quiser fazer outra pergunta, pode me enviar agora.\n\n"
                "Para voltar ao menu principal, digite *menu*."
            )
            return jsonify({"status": "ok"}), 200

        # ==========================================
        # PEÇAS / ACESSÓRIOS / GARANTIA / ATACADO
        # ==========================================
        if etapa == "pecas":
            clientes[telefone]["observacao"] = texto

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Peças",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="pecas_registrado",
                dados=clientes[telefone],
                atendimento_humano=False,
                concluido=True,
            )

            enviar_mensagem(
                telefone,
                "✅ *Solicitação de peças registrada com sucesso*\n\n"
                "Nossa equipe vai verificar valor e disponibilidade e retornar para você."
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "acessorios_modelo":
            modelo_informado = texto.strip()

            if not modelo_informado:
                enviar_mensagem(
                    telefone,
                    "⚠️ Não consegui identificar o modelo.\n\n"
                    "Me informe o *modelo da sua moto* para eu enviar o catálogo correto."
                )
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["modelo"] = modelo_informado.upper()

            arquivo_pdf = obter_pdf_acessorios_por_modelo(modelo_informado)
            clientes[telefone]["etapa"] = "acessorios_orcamento"

            if arquivo_pdf == PDF_ACESSORIOS_GERAL:
                enviar_mensagem(
                    telefone,
                    "📎 Não identifiquei com total certeza o modelo informado.\n"
                    "Vou te enviar o *catálogo geral de acessórios* para seguir com o atendimento."
                )
            else:
                enviar_mensagem(
                    telefone,
                    f"✅ Modelo identificado: *{clientes[telefone]['modelo']}*"
                )

            enviado = enviar_pdf(
                telefone,
                arquivo_pdf,
                "📎 Segue o catálogo de acessórios para sua moto."
            )

            clientes[telefone]["etapa"] = "acessorios_orcamento"

            if not enviado:
                enviar_mensagem(
                    telefone,
                    "⚠️ Não consegui enviar o catálogo agora.\n\n"
                    "Mas pode me informar mesmo assim *qual acessório você deseja para orçamento*."
                )
            else:
                enviar_mensagem(
                    telefone,
                    "Perfeito 👍\n\n"
                    "Agora me informe *qual acessório você deseja para orçamento*."
                )

            return jsonify({"status": "ok"}), 200

        if etapa == "acessorios_orcamento":
            acessorio_desejado = texto.strip()

            if not acessorio_desejado:
                enviar_mensagem(
                    telefone,
                    "⚠️ Me informe qual *acessório* você deseja para orçamento."
                )
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["itens"] = acessorio_desejado
            clientes[telefone]["venda_adicional"] = acessorio_desejado
            clientes[telefone]["observacao"] = (
                f"Solicitação de acessório: {acessorio_desejado}"
            )

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Acessórios",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="acessorios_orcamento_registrado",
                dados=clientes[telefone],
                atendimento_humano=False,
                concluido=True,
            )

            enviar_mensagem(
                telefone,
                "✅ *Solicitação de acessórios registrada com sucesso*\n\n"
                f"🏍️ *Modelo:* {clientes[telefone].get('modelo', '-')}\n"
                f"🛠️ *Acessório desejado:* {acessorio_desejado}\n\n"
                "Nossa equipe vai analisar e retornar com o orçamento."
            )

            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "garantia":
            clientes[telefone]["observacao"] = texto

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Garantia",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="garantia_registrada",
                dados=clientes[telefone],
                atendimento_humano=False,
                concluido=True,
            )

            enviar_mensagem(
                telefone,
                "✅ *Solicitação de garantia registrada com sucesso*\n\n"
                "Nossa equipe vai analisar e retornar para você."
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "atacado":
            clientes[telefone]["observacao"] = texto

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Logista / Atacado",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="atacado_registrado",
                dados=clientes[telefone],
                atendimento_humano=False,
                concluido=True,
            )

            enviar_mensagem(
                telefone,
                "✅ *Solicitação de atacado registrada com sucesso*\n\n"
                "Nossa equipe comercial vai analisar e retornar para você."
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        return jsonify({
            "status": "ok",
            "motivo": "nenhuma_acao_aplicada"
        }), 200

    except Exception as e:
        log_erro("ERRO NO WEBHOOK Z-API:", repr(e))
        return jsonify({
            "status": "erro",
            "detalhe": "falha interna no webhook"
        }), 200


# ==========================================
# INICIAR WORKER
# ==========================================
iniciar_worker()


# ==========================================
# START
# ==========================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
    )