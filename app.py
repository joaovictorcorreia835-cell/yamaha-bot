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
# CONFIG
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "")

# Evita erro se vier vazio ou inválido
TEMPO_INATIVIDADE = int(os.getenv("TEMPO_INATIVIDADE", "43200") or 43200)

ARQUIVO_FOLLOWUP = os.getenv("ARQUIVO_FOLLOWUP", "clientes_disparo.xlsx")
INTERVALO_WORKER_FOLLOWUP = int(os.getenv("INTERVALO_WORKER_FOLLOWUP", "300") or 300)
FOLLOWUP_1_HORAS = int(os.getenv("FOLLOWUP_1_HORAS", "48") or 48)
FOLLOWUP_2_DIAS = int(os.getenv("FOLLOWUP_2_DIAS", "5") or 5)

# ==========================================
# CONFIG FUTURA SANCES
# mock | real
# ==========================================
SANCES_MODO = (os.getenv("SANCES_MODO", "mock") or "mock").strip().lower()

# Para simular comportamento futuro sem integração real:
# nao_configurado | enviado | erro
SANCES_SIMULAR_RESULTADO = (
    os.getenv("SANCES_SIMULAR_RESULTADO", "nao_configurado") or "nao_configurado"
).strip().lower()

# Proteção contra valor vazio
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
# Proteção caso alguma env não esteja definida
if ZAPI_INSTANCE_ID and ZAPI_TOKEN:
    url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"
else:
    url_envio = ""
    url_documento = ""

clientes = {}
mensagens_processadas = set()
fila_mensagens = deque(maxlen=2000)

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


def limpar_telefone(telefone):
    try:
        telefone = str(telefone or "").strip()
        telefone = (
            telefone
            .replace("@c.us", "")
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

        return f"R$ {valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
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
        "1": "1", "1a": "1", "1ª": "1", "1o": "1", "primeira": "1",
        "2": "2", "2a": "2", "2ª": "2", "2o": "2", "segunda": "2",
        "3": "3", "3a": "3", "3ª": "3", "3o": "3", "terceira": "3",
        "4": "4", "4a": "4", "4ª": "4", "4o": "4", "quarta": "4",
        "5": "5", "5a": "5", "5ª": "5", "5o": "5", "quinta": "5",
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

    if item_limpo in ["NENHUM", "NAO", "NÃO", "SEM ITEM", "SEM ITENS", "-", "OK", "SEM"]:
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
            f"retorno={retorno}"
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
        "venda_adicional": formatar_itens_adicionais_para_salvar(dados.get("venda_adicional", "")),
        "tipo_atendimento": limpar_texto(dados.get("tipo_atendimento", "")),
        "origem": "BOT_WHATSAPP"
    }


def retorno_padrao_sances():
    return {
        "sucesso": False,
        "status": SANCES_STATUS_PENDENTE,
        "protocolo_sances": "",
        "mensagem": "",
        "erro": ""
    }


def simular_envio_sances(payload):
    resultado = SANCES_SIMULAR_RESULTADO

    if resultado == "enviado":
        retorno = retorno_padrao_sances()
        retorno.update({
            "sucesso": True,
            "status": SANCES_STATUS_ENVIADO,
            "protocolo_sances": f"SCS-{uuid.uuid4().hex[:8].upper()}",
            "mensagem": "Agendamento enviado com sucesso ao Sances (modo mock).",
            "erro": ""
        })
        log_integracao_sances(
            telefone=payload.get("telefone", ""),
            acao="mock_envio_agendamento_sucesso",
            payload=payload,
            retorno=retorno
        )
        return retorno

    if resultado == "erro":
        retorno = retorno_padrao_sances()
        retorno.update({
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "protocolo_sances": "",
            "mensagem": "Falha simulada no envio ao Sances.",
            "erro": "Erro simulado de integração Sances"
        })
        log_integracao_sances(
            telefone=payload.get("telefone", ""),
            acao="mock_envio_agendamento_erro",
            payload=payload,
            retorno=retorno
        )
        return retorno

    retorno = retorno_padrao_sances()
    retorno.update({
        "sucesso": False,
        "status": SANCES_STATUS_NAO_CONFIGURADO,
        "protocolo_sances": "",
        "mensagem": "Integração com Sances ainda não configurada.",
        "erro": "Sances não configurado"
    })
    log_integracao_sances(
        telefone=payload.get("telefone", ""),
        acao="mock_envio_agendamento_nao_configurado",
        payload=payload,
        retorno=retorno
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
            retorno="Modo real selecionado, mas integração ainda não implementada."
        )

        retorno = retorno_padrao_sances()
        retorno.update({
            "sucesso": False,
            "status": SANCES_STATUS_NAO_CONFIGURADO,
            "protocolo_sances": "",
            "mensagem": "Modo real do Sances ainda não implementado.",
            "erro": "Integração real ainda não implementada"
        })
        return retorno

    except Exception as e:
        log_erro("Erro ao preparar envio para Sances:", repr(e))
        retorno = retorno_padrao_sances()
        retorno.update({
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "protocolo_sances": "",
            "mensagem": "Erro ao preparar integração com Sances.",
            "erro": repr(e)
        })
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
        "sances_data_envio": ""
    }


def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = estado_padrao_cliente()


def resetar_cliente(telefone):
    clientes[telefone] = estado_padrao_cliente()


def atualizar_interacao(telefone):
    telefone = limpar_telefone(telefone)
    if not telefone:
        return

    iniciar_cliente(telefone)
    clientes[telefone]["ultima_interacao"] = agora()

    db = SessionLocal()
    try:
        atendimento = db.query(Atendimento).filter(
            Atendimento.telefone == telefone,
            Atendimento.concluido == False
        ).order_by(Atendimento.id.desc()).first()

        if atendimento:
            atendimento.ultima_interacao = agora_datetime()
            db.commit()

    except Exception as e:
        db.rollback()
        log_erro("Erro ao atualizar interação no banco:", repr(e))

    finally:
        db.close()


def limpar_dados_fluxo_revisao(telefone):
    iniciar_cliente(telefone)

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
    dados_cliente["atendimento_humano"] = False

    dados_cliente["sances_enviado"] = False
    dados_cliente["sances_status"] = SANCES_STATUS_PENDENTE
    dados_cliente["sances_protocolo"] = ""
    dados_cliente["sances_erro"] = ""
    dados_cliente["sances_data_envio"] = ""

    definir_status_cliente(telefone, STATUS_AGENDAMENTO_INICIADO)


def ativar_atendimento_humano(telefone):
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
        concluido=False
    )

    enviar_mensagem(
        telefone,
        "👨‍💼 *Atendimento humano acionado*\n\n"
        "Perfeito, vou direcionar seu atendimento para nossa equipe.\n"
        "Daqui em diante, um atendente segue com você por aqui.\n\n"
        "Quando quiser voltar ao menu automático, é só enviar *menu*."
    )


def processar_inatividade():
    try:
        agora_atual = agora()

        for telefone in list(clientes.keys()):
            dados = clientes.get(telefone, {})
            ultima = dados.get("ultima_interacao", agora_atual)

            # não encerrar automaticamente atendimento humano
            if dados.get("atendimento_humano") is True or dados.get("etapa") == "atendimento_humano":
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

        if telefone:
            telefone = (
                str(telefone)
                .replace("@c.us", "")
                .replace("@s.whatsapp.net", "")
                .replace("@g.us", "")
                .strip()
            )

        return telefone

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


# ==========================================
# ENVIO
# ==========================================
def enviar_mensagem(telefone, mensagem):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            log_erro("Telefone inválido para envio de mensagem.")
            return False

        if not url_envio or not ZAPI_CLIENT_TOKEN:
            log_erro("Z-API não configurada corretamente para envio de mensagem.")
            return False

        headers = {
            "Client-Token": ZAPI_CLIENT_TOKEN,
            "Content-Type": "application/json"
        }

        payload = {
            "phone": telefone,
            "message": mensagem
        }

        response = requests.post(
            url_envio,
            json=payload,
            headers=headers,
            timeout=30
        )

        if response.status_code not in [200, 201]:
            log_erro("Falha envio mensagem:", response.status_code, response.text)

        log_info("Mensagem enviada:", telefone, response.status_code)
        return response.status_code in [200, 201]

    except Exception as e:
        log_erro("Erro envio mensagem:", repr(e))
        return False


def enviar_pdf(telefone, arquivo, legenda=""):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            log_erro("Telefone inválido para envio de PDF.")
            return False

        if not url_documento or not ZAPI_CLIENT_TOKEN or not BASE_URL:
            log_erro("Z-API/BASE_URL não configurada corretamente para envio de PDF.")
            return False

        headers = {
            "Client-Token": ZAPI_CLIENT_TOKEN,
            "Content-Type": "application/json"
        }

        url_pdf = f"{BASE_URL}/pdf/{arquivo}"

        payload = {
            "phone": telefone,
            "document": url_pdf,
            "fileName": arquivo,
            "caption": legenda
        }

        response = requests.post(
            url_documento,
            json=payload,
            headers=headers,
            timeout=30
        )

        if response.status_code not in [200, 201]:
            log_erro("Falha envio PDF:", response.status_code, response.text)
            return False

        log_info("PDF enviado:", telefone, response.status_code)
        return True

    except Exception as e:
        log_erro("Erro enviar PDF:", repr(e))
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
    origem="BOT"
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
        tipo_atendimento = limpar_texto(base.get("tipo_atendimento", ""))
        venda_adicional = formatar_itens_adicionais_para_salvar(base.get("venda_adicional", ""))
        itens = formatar_itens_adicionais_para_salvar(base.get("itens", venda_adicional))

        if venda_adicional.strip().upper() == "NENHUM":
            venda_adicional = ""
        if itens.strip().upper() == "NENHUM":
            itens = ""

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
            ultima_interacao=agora_datetime(),
            data=agora_datetime()
        )

        db.add(atendimento)
        db.commit()
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
    iniciar_cliente(telefone)
    clientes[telefone]["etapa"] = "menu"
    clientes[telefone]["atendimento_humano"] = False
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
    enviar_mensagem(telefone, mensagem)


def iniciar_fluxo_pecas(telefone, texto_inicial=""):
    iniciar_cliente(telefone)
    clientes[telefone]["etapa"] = "pecas"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["observacao"] = limpar_texto(texto_inicial)
    definir_status_cliente(telefone, STATUS_NOVO_ATENDIMENTO)

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Peças",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="pecas_iniciado",
        dados=clientes[telefone],
        atendimento_humano=False,
        concluido=False
    )

    if limpar_texto(texto_inicial):
        enviar_mensagem(
            telefone,
            "🔩 *Peças*\n\n"
            "Perfeito, recebi sua solicitação 👍\n"
            "Nossa equipe vai verificar *valor* e *disponibilidade* para você.\n\n"
            "Se quiser complementar, pode me enviar:\n"
            "• modelo da moto\n"
            "• ano\n"
            "• peça desejada"
        )
    else:
        enviar_mensagem(
            telefone,
            "🔩 *Peças*\n\n"
            "Me informe a *peça desejada* para eu registrar sua solicitação."
        )


def iniciar_fluxo_acessorios(telefone, texto_inicial=""):
    iniciar_cliente(telefone)
    clientes[telefone]["etapa"] = "acessorios"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["observacao"] = limpar_texto(texto_inicial)
    definir_status_cliente(telefone, STATUS_NOVO_ATENDIMENTO)

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Acessórios",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="acessorios_iniciado",
        dados=clientes[telefone],
        atendimento_humano=False,
        concluido=False
    )

    if limpar_texto(texto_inicial):
        enviar_mensagem(
            telefone,
            "🛵 *Acessórios*\n\n"
            "Perfeito, recebi sua solicitação 👍\n"
            "Se quiser, pode me enviar mais detalhes do acessório que procura."
        )
    else:
        enviar_mensagem(
            telefone,
            "🛵 *Acessórios*\n\n"
            "Me informe qual *acessório desejado* você procura."
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
    dados = clientes.get(telefone, {})

    itens = formatar_itens_adicionais_para_salvar(dados.get("venda_adicional", ""))
    observacao = dados.get("observacao") or "Nenhuma"
    tipo_atendimento = dados.get("tipo_atendimento") or "Não informado"

    if limpar_texto(itens).upper() in ["", "NENHUM", "NAO", "NÃO", "SEM ITEM", "SEM ITENS"]:
        itens = "Nenhum"

    if not limpar_texto(observacao):
        observacao = "Nenhuma"

    revisao = limpar_texto(dados.get("revisao", "-"))
    revisao_formatada = f"{revisao}ª" if revisao not in ["", "-"] else "-"

    return (
        "📋 *Confirmação do seu agendamento*\n\n"
        f"👤 *Nome:* {dados.get('nome', '-')}\n"
        f"📄 *CPF:* {dados.get('cpf', '-')}\n"
        f"🏍️ *Modelo:* {dados.get('modelo', '-')}\n"
        f"📅 *Ano:* {dados.get('ano', '-')}\n"
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

    if etapa == "revisao_tipo":
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
        "dados_extraidos": {}
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


def aplicar_dados_ia_no_cliente(telefone, dados_extraidos):
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
    item_adicional = formatar_itens_adicionais_para_salvar(
        dados_extraidos.get("item_adicional", "")
    )
    observacao = limpar_texto(dados_extraidos.get("observacao"))
    tipo_atendimento = limpar_texto(dados_extraidos.get("tipo_atendimento"))

    revisao_texto = normalizar_texto(revisao_bruta)
    if not revisao:
        if "5 mil" in revisao_texto or "5000" in revisao_texto:
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

    if data and not dados.get("data") and data_texto_valida(data):
        dados["data"] = data

    if horario and not dados.get("horario"):
        horario_limpo = horario.strip()
        if re.match(r"^\d{1,2}:\d{2}$", horario_limpo):
            dados["horario"] = horario_limpo

    if item_adicional and not dados.get("venda_adicional") and item_adicional_valido(item_adicional):
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


def enviar_proxima_etapa_com_contexto_ia(telefone):
    iniciar_cliente(telefone)

    etapa = primeira_etapa_pendente_revisao(telefone)
    clientes[telefone]["etapa"] = etapa

    resumo = montar_resumo_dados_ia_revisao(telefone)

    if etapa != "revisao_horario":
        clientes[telefone]["horarios_disponiveis"] = []

    if etapa == "revisao_horario":
        revisao = limpar_texto(clientes[telefone].get("revisao", ""))
        dia = limpar_texto(clientes[telefone].get("dia", ""))

        horarios = horarios_por_revisao(revisao, dia)

        if not horarios:
            clientes[telefone]["etapa"] = "revisao_dia"
            clientes[telefone]["horarios_disponiveis"] = []

            mensagem = (
                "⚠️ Não encontrei horários disponíveis para esse tipo de revisão nesse dia.\n\n"
                "Vamos escolher outro dia."
            )

            if resumo:
                mensagem = f"{resumo}\n\n{mensagem}"

            enviar_mensagem(telefone, mensagem)
            enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, "revisao_dia"))
            return

        clientes[telefone]["horarios_disponiveis"] = horarios

        if resumo:
            enviar_mensagem(
                telefone,
                f"{resumo}\n\nPerfeito 👍 Agora só falta você escolher um horário."
            )

        enviar_mensagem(telefone, montar_mensagem_horarios(horarios))
        return

    mensagem_etapa = mensagem_por_etapa_revisao(telefone, etapa)

    if resumo:
        enviar_mensagem(
            telefone,
            f"{resumo}\n\nPerfeito 👍 Agora só preciso de mais uma informação para continuar."
        )

    enviar_mensagem(telefone, mensagem_etapa)


# ==========================================
# FLUXO REVISÃO
# ==========================================
def primeira_etapa_pendente_revisao(telefone):
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
        return "revisao_tipo"
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
        concluido=False
    )

    proxima = primeira_etapa_pendente_revisao(telefone)
    clientes[telefone]["etapa"] = proxima
    return proxima


def enviar_proxima_etapa_revisao(telefone):
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
                "⚠️ Não há horários disponíveis para esse tipo de revisão neste dia.\n\nEscolha outro dia."
            )
            enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, "revisao_dia"))
            return

        clientes[telefone]["horarios_disponiveis"] = horarios
        enviar_mensagem(telefone, montar_mensagem_horarios(horarios))
        return

    enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, etapa))


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

        quantidade = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.data_agendada == limpar_texto(data),
            AgendamentoRevisao.horario == limpar_texto(horario),
            AgendamentoRevisao.status == STATUS_AGENDADO
        ).count()

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
            "15:00"
        ]

    return ["08:00"]


def validar_data(data):
    try:
        data_obj = datetime.strptime(data, "%d/%m/%Y")

        if data_obj.date() < datetime.now().date():
            return False

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
        protocolo = gerar_protocolo()

        itens_formatados = formatar_itens_adicionais_para_salvar(dados.get("itens", ""))
        venda_formatada = formatar_itens_adicionais_para_salvar(dados.get("venda_adicional", ""))

        agendamento = AgendamentoRevisao(
            protocolo=protocolo,
            telefone=limpar_telefone(telefone),
            nome=limpar_texto(dados.get("nome", "")),
            cpf=limpar_cpf(dados.get("cpf", "")),
            modelo=limpar_texto(dados.get("modelo", "")).upper(),
            ano=limpar_texto(dados.get("ano", "")),
            revisao=limpar_texto(dados.get("revisao", "")),
            dia_semana=nome_dia(dados.get("dia", "")),
            data_agendada=limpar_texto(dados.get("data", "")),
            horario=limpar_texto(dados.get("horario", "")),
            itens=itens_formatados,
            venda_adicional=venda_formatada,
            status=normalizar_status(STATUS_AGENDADO),
            observacoes=limpar_texto(dados.get("observacao", "")),
            origem="BOT",
            sances_status=SANCES_STATUS_PENDENTE,
            sances_enviado=False,
            sances_protocolo="",
            sances_erro="",
            sances_data_envio=None
        )

        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)

        log_info("Agendamento salvo:", protocolo)
        return protocolo

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        log_erro("Erro salvar agendamento:", repr(e))
        return None

    finally:
        db.close()


def salvar_atendimento_dashboard(telefone, dados):
    return salvar_evento_atendimento(
        telefone=telefone,
        setor="Revisão",
        status=STATUS_AGENDADO,
        etapa="revisao_finalizada",
        dados=dados,
        atendimento_humano=False,
        concluido=True
    )


# ==========================================
# CONSULTA / CANCELAMENTO / REAGENDAMENTO
# ==========================================
def buscar_agendamento_ativo(cpf):
    db = SessionLocal()

    try:
        cpf_limpo = limpar_cpf(cpf)

        if not cpf_limpo:
            return None

        agendamento = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.cpf == cpf_limpo,
            AgendamentoRevisao.status == normalizar_status(STATUS_AGENDADO)
        ).first()

        return agendamento

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

        agendamento = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.cpf == cpf_limpo,
            AgendamentoRevisao.status == normalizar_status(STATUS_AGENDADO)
        ).first()

        if not agendamento:
            return None

        protocolo = str(agendamento.protocolo or "")
        telefone = str(agendamento.telefone or "")
        nome = str(agendamento.nome or "")
        cpf_salvo = str(agendamento.cpf or "")
        modelo = str(agendamento.modelo or "")
        ano = str(agendamento.ano or "")
        revisao = str(agendamento.revisao or "")
        data_agendada = str(agendamento.data_agendada or "")
        horario = str(agendamento.horario or "")
        itens = str(agendamento.itens or "")
        venda_adicional = str(agendamento.venda_adicional or "")

        agendamento.status = normalizar_status(novo_status)

        dados = {
            "protocolo": protocolo,
            "telefone": telefone,
            "nome": nome,
            "cpf": cpf_salvo,
            "modelo": modelo,
            "ano": ano,
            "revisao": revisao,
            "data_agendada": data_agendada,
            "horario": horario,
            "itens": itens,
            "venda_adicional": venda_adicional,
            "status": agendamento.status,
        }

        db.commit()
        log_info("Agendamento cancelado:", dados)
        return dados

    except Exception as e:
        db.rollback()
        log_erro("Erro cancelar:", repr(e))
        return None

    finally:
        db.close()


def responder_consulta_agendamento(telefone, cpf):
    cpf_limpo = limpar_cpf(cpf)

    if not cpf_limpo or len(cpf_limpo) != 11:
        enviar_mensagem(
            telefone,
            "📄 Para consultar seu agendamento, informe seu *CPF com 11 números*."
        )
        clientes[telefone]["etapa"] = "consulta_agendamento_cpf"
        return

    ag = buscar_agendamento_por_cpf(cpf_limpo)

    if not ag:
        salvar_evento_atendimento(
            telefone=telefone,
            setor="Consulta Agendamento",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="consulta_agendamento_nao_localizado",
            dados={"cpf": cpf_limpo},
            atendimento_humano=False,
            concluido=False
        )

        enviar_mensagem(
            telefone,
            "⚠️ Não localizei agendamento ativo para este CPF.\n\n"
            "Se quiser, posso iniciar um novo agendamento. Envie *quero agendar revisão*."
        )
        resetar_cliente(telefone)
        return

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Consulta Agendamento",
        status=STATUS_AGENDADO,
        etapa="consulta_agendamento_localizado",
        dados={
            "nome": str(ag.nome or ""),
            "modelo": str(ag.modelo or ""),
            "ano": str(ag.ano or ""),
            "revisao": str(ag.revisao or ""),
            "cpf": str(ag.cpf or ""),
            "data": str(ag.data_agendada or ""),
            "horario": str(ag.horario or ""),
            "itens": str(ag.itens or ""),
            "venda_adicional": str(ag.venda_adicional or "")
        },
        atendimento_humano=False,
        concluido=False
    )

    enviar_mensagem(
        telefone,
        "📋 *Agendamento localizado*\n\n"
        f"👤 {str(ag.nome or '')}\n"
        f"🏍️ {str(ag.modelo or '')}\n"
        f"📅 {str(ag.data_agendada or '')}\n"
        f"⏰ {str(ag.horario or '')}\n"
        f"📌 Protocolo: {str(ag.protocolo or '')}\n\n"
        "Equipe Motoshow Yamaha"
    )

    resetar_cliente(telefone)


def responder_cancelamento_agendamento(telefone, cpf):
    try:
        cpf_limpo = limpar_cpf(cpf)

        if not cpf_limpo or len(cpf_limpo) != 11:
            enviar_mensagem(
                telefone,
                "📄 Para cancelar seu agendamento, informe seu *CPF com 11 números*."
            )
            clientes[telefone]["etapa"] = "cancelar_agendamento_cpf"
            return

        ag_cancelado = cancelar_agendamento(cpf_limpo)

        if not ag_cancelado:
            try:
                salvar_evento_atendimento(
                    telefone=telefone,
                    setor="Cancelamento",
                    status=STATUS_NOVO_ATENDIMENTO,
                    etapa="cancelamento_nao_localizado",
                    dados={"cpf": cpf_limpo},
                    atendimento_humano=False,
                    concluido=False
                )
            except Exception as e:
                log_erro("Erro ao salvar evento de cancelamento não localizado:", repr(e))

            enviar_mensagem(
                telefone,
                "⚠️ Não encontrei agendamento ativo para este CPF."
            )
            resetar_cliente(telefone)
            return

        try:
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
                    "venda_adicional": ag_cancelado.get("venda_adicional", "")
                },
                atendimento_humano=False,
                concluido=True
            )
        except Exception as e:
            log_erro("Erro ao salvar evento de cancelamento:", repr(e))

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

    except Exception as e:
        log_erro("Erro responder_cancelamento_agendamento:", repr(e))
        enviar_mensagem(
            telefone,
            "⚠️ O cancelamento foi processado, mas ocorreu uma falha ao finalizar a resposta. Envie *menu* para continuar."
        )
        resetar_cliente(telefone)


def iniciar_reagendamento(telefone, cpf):
    cpf_limpo = limpar_cpf(cpf)

    if not cpf_limpo or len(cpf_limpo) != 11:
        enviar_mensagem(
            telefone,
            "📄 Para reagendar, informe seu *CPF com 11 números*."
        )
        clientes[telefone]["etapa"] = "reagendar_agendamento_cpf"
        return

    ag = buscar_agendamento_por_cpf(cpf_limpo)

    if not ag:
        salvar_evento_atendimento(
            telefone=telefone,
            setor="Reagendamento",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="reagendamento_nao_localizado",
            dados={"cpf": cpf_limpo},
            atendimento_humano=False,
            concluido=False
        )

        enviar_mensagem(
            telefone,
            "⚠️ Não encontrei agendamento ativo para este CPF."
        )
        resetar_cliente(telefone)
        return

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Reagendamento",
        status=STATUS_REAGENDADO,
        etapa="reagendamento_iniciado",
        dados={
            "protocolo": str(ag.protocolo or ""),
            "nome": str(ag.nome or ""),
            "modelo": str(ag.modelo or ""),
            "ano": str(ag.ano or ""),
            "revisao": str(ag.revisao or ""),
            "cpf": str(ag.cpf or ""),
            "data": str(ag.data_agendada or ""),
            "horario": str(ag.horario or ""),
            "itens": str(ag.itens or ""),
            "venda_adicional": str(ag.venda_adicional or "")
        },
        atendimento_humano=False,
        concluido=False
    )

    limpar_dados_fluxo_revisao(telefone)

    clientes[telefone]["modelo"] = limpar_texto(ag.modelo).upper()
    clientes[telefone]["nome"] = limpar_texto(ag.nome).upper()
    clientes[telefone]["cpf"] = limpar_cpf(ag.cpf)
    clientes[telefone]["ano"] = limpar_texto(ag.ano)
    clientes[telefone]["revisao"] = limpar_texto(ag.revisao)
    clientes[telefone]["reagendamento"] = True
    clientes[telefone]["protocolo_antigo"] = str(ag.protocolo or "")

    cancelar_agendamento(clientes[telefone]["cpf"], novo_status=STATUS_REAGENDADO)
    definir_status_cliente(telefone, STATUS_REAGENDADO)

    clientes[telefone]["etapa"] = "revisao_dia"

    enviar_mensagem(
    telefone,
    "🔄 *Reagendamento iniciado* ..."
    )

    enviar_mensagem(
        telefone,
        mensagem_por_etapa_revisao(telefone, "revisao_dia")
    )

# ==========================================
# FOLLOW-UP / LEMBRETES
# ==========================================
def atualizar_retorno_na_planilha(telefone, texto):
    try:
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

            if "retorno" in colunas:
                coluna_retorno = colunas["retorno"]
            else:
                coluna_retorno = "retorno"
                df[coluna_retorno] = ""

            if "data_retorno" in colunas:
                coluna_data_retorno = colunas["data_retorno"]
            else:
                coluna_data_retorno = "data_retorno"
                df[coluna_data_retorno] = ""

            telefone_limpo = limpar_telefone(telefone)
            encontrou = False

            for idx in df.index:
                tel_planilha = limpar_telefone(df.at[idx, coluna_telefone])
                if tel_planilha == telefone_limpo:
                    df.at[idx, coluna_retorno] = limpar_texto(texto)
                    df.at[idx, coluna_data_retorno] = formatar_data_hora()
                    encontrou = True
                    break

            if encontrou:
                df.to_excel(ARQUIVO_FOLLOWUP, index=False)

    except Exception as e:
        log_erro("Erro ao atualizar retorno na planilha:", repr(e))


def processar_lembretes_agendamento():
    db = SessionLocal()

    try:
        agora_time = datetime.now()
        hoje = agora_time.date()

        agendamentos = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.status == normalizar_status(STATUS_AGENDADO),
            AgendamentoRevisao.lembrete_enviado == False
        ).all()

        houve_alteracao = False

        for ag in agendamentos:
            try:
                data_texto = limpar_texto(getattr(ag, "data_agendada", ""))
                if not data_texto:
                    continue

                try:
                    data_agendada = datetime.strptime(data_texto, "%d/%m/%Y").date()
                except Exception:
                    log_erro("Data inválida no lembrete:", repr(data_texto))
                    continue

                diferenca = (data_agendada - hoje).days
                data_criacao = getattr(ag, "data", None)

                # envia 1 dia antes, mas nunca logo após criar o agendamento
                if diferenca == 1 and data_criacao and (agora_time - data_criacao).total_seconds() > 3600:
                    mensagem = (
                        "🔔 *Lembrete de Revisão*\n\n"
                        f"Olá *{str(getattr(ag, 'nome', '') or '')}*\n\n"
                        f"📅 Data: {str(getattr(ag, 'data_agendada', '') or '')}\n"
                        f"⏰ Horário: {str(getattr(ag, 'horario', '') or '')}\n"
                        f"🏍️ Modelo: {str(getattr(ag, 'modelo', '') or '')}\n\n"
                        f"📌 Protocolo: {str(getattr(ag, 'protocolo', '') or '')}\n\n"
                        "Equipe Motoshow Yamaha"
                    )

                    enviado = enviar_mensagem(str(getattr(ag, "telefone", "") or ""), mensagem)
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


def processar_followup_inteligente():
    db = SessionLocal()

    try:
        agora_time = datetime.now()

        # janela permitida: 06:00 até 21:59
        if agora_time.hour < 6 or agora_time.hour >= 22:
            return

        atendimentos = db.query(Atendimento).filter(
            Atendimento.concluido == False
        ).order_by(Atendimento.id.desc()).all()

        telefones_processados = set()
        houve_alteracao = False

        TEMPO_FOLLOWUP_1 = 6 * 3600
        TEMPO_FOLLOWUP_2 = 24 * 3600
        TEMPO_FOLLOWUP_3 = 5 * 24 * 3600

        for at in atendimentos:
            try:
                telefone_bruto = getattr(at, "telefone", "")
                if not telefone_bruto:
                    continue

                telefone = limpar_telefone(telefone_bruto)
                if not telefone:
                    continue

                # evita múltiplos disparos para o mesmo número no mesmo ciclo
                if telefone in telefones_processados:
                    continue

                # não envia se estiver em atendimento humano
                if bool(getattr(at, "atendimento_humano", False)):
                    telefones_processados.add(telefone)
                    continue

                # não envia se já concluído
                if bool(getattr(at, "concluido", False)):
                    telefones_processados.add(telefone)
                    continue

                ultima = getattr(at, "ultima_interacao", None)
                if not ultima:
                    telefones_processados.add(telefone)
                    continue

                tempo_parado = (agora_time - ultima).total_seconds()

                followup_1 = bool(getattr(at, "followup_1", False))
                followup_2 = bool(getattr(at, "followup_2", False))
                followup_3 = bool(getattr(at, "followup_3", False))

                total_followups = int(followup_1) + int(followup_2) + int(followup_3)

                # máximo 3 mensagens por cliente
                if total_followups >= 3:
                    telefones_processados.add(telefone)
                    continue

                enviado = False

                # FOLLOW-UP 1 - após 6 horas sem resposta
                if tempo_parado >= TEMPO_FOLLOWUP_1 and not followup_1:
                    enviado = enviar_mensagem(
                        telefone,
                        "👋 Oi! Vi que você começou um atendimento e não finalizou.\n\n"
                        "Posso te ajudar a concluir rapidinho? 🚀"
                    )
                    if enviado:
                        at.followup_1 = True
                        houve_alteracao = True

                # FOLLOW-UP 2 - após 24 horas sem resposta
                elif tempo_parado >= TEMPO_FOLLOWUP_2 and followup_1 and not followup_2:
                    enviado = enviar_mensagem(
                        telefone,
                        "⏰ Só passando pra te lembrar da sua solicitação.\n\n"
                        "Se quiser, posso finalizar seu agendamento agora 👍"
                    )
                    if enviado:
                        at.followup_2 = True
                        houve_alteracao = True

                # FOLLOW-UP 3 - após 5 dias sem resposta
                elif tempo_parado >= TEMPO_FOLLOWUP_3 and followup_1 and followup_2 and not followup_3:
                    enviado = enviar_mensagem(
                        telefone,
                        "🚨 Última chamada!\n\n"
                        "Ainda quer agendar sua revisão?\n"
                        "Temos horários disponíveis essa semana 🏍️"
                    )
                    if enviado:
                        at.followup_3 = True
                        houve_alteracao = True

                telefones_processados.add(telefone)

            except Exception as e:
                log_erro("Erro follow-up individual:", repr(e))

        if houve_alteracao:
            db.commit()

    except Exception as e:
        db.rollback()
        log_erro("Erro geral follow-up inteligente:", repr(e))

    finally:
        db.close()
# ==========================================
# APOIO DÚVIDAS / REVISÃO / SANCES
# ==========================================
def encerrar_atendimento_humano(telefone):
    try:
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
            concluido=False
        )

        return True

    except Exception as e:
        log_erro("Erro ao encerrar atendimento humano:", repr(e))
        return False


def montar_dados_agendamento_para_reenvio(ag):
    try:
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
            "venda_adicional": formatar_itens_adicionais_para_salvar(getattr(ag, "venda_adicional", "")),
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

        ag = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.protocolo == protocolo_limpo
        ).first()

        return ag

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

        ag = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.protocolo == protocolo_limpo
        ).first()

        if not ag:
            return False

        agora_time = datetime.now()
        sucesso = bool(retorno_sances.get("sucesso", False))
        status = limpar_texto(retorno_sances.get("status", "")) or SANCES_STATUS_ERRO

        ag.sances_status = status
        ag.sances_enviado = sucesso
        ag.sances_protocolo = limpar_texto(retorno_sances.get("protocolo_sances", ""))
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
        setor = f"Dúvidas {limpar_texto(categoria)}".strip()

        return salvar_evento_atendimento(
            telefone=telefone,
            setor=setor,
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="duvida_respondida",
            dados={
                "observacao": f"Pergunta: {limpar_texto(pergunta)} | Resposta: {limpar_texto(resposta)}"
            },
            atendimento_humano=False,
            concluido=True
        )
    except Exception as e:
        log_erro("Erro salvar dúvida dashboard:", repr(e))
        return False


def mensagem_duvida_retorno_fluxo(telefone):
    iniciar_cliente(telefone)

    etapa_retorno = limpar_texto(clientes[telefone].get("etapa_retorno_duvida", ""))

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
        "revisao_tipo",
    }
    return etapa in etapas_permitidas


def encaminhar_para_menu_duvidas(telefone, etapa_atual=""):
    try:
        iniciar_cliente(telefone)
        clientes[telefone]["etapa_retorno_duvida"] = limpar_texto(etapa_atual)
        clientes[telefone]["etapa"] = "menu_duvidas"

        enviar_mensagem(
            telefone,
            "Sem problema 👍 Vou te direcionar para a central de dúvidas e depois podemos voltar para o seu agendamento."
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

        # weekday(): segunda=0 ... domingo=6
        mapa = {
            "1": 0,  # Segunda
            "2": 1,  # Terça
            "3": 2,  # Quarta
            "4": 3,  # Quinta
            "5": 4,  # Sexta
            "6": 5,  # Sábado
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
                SANCES_STATUS_ERRO
            ])
        ).all()

        for ag in agendamentos:
            try:
                tentativas = int(getattr(ag, "sances_tentativas", 0) or 0)
                ultima_tentativa = getattr(ag, "sances_ultima_tentativa", None)

                if tentativas >= SANCES_RETRY_MAX:
                    continue

                # evita retry em loop a cada ciclo do worker
                if ultima_tentativa:
                    if tentativas <= 1:
                        intervalo_minimo = 300   # 5 min
                    elif tentativas == 2:
                        intervalo_minimo = 900   # 15 min
                    else:
                        intervalo_minimo = 1800  # 30 min

                    segundos_desde_tentativa = (agora_time - ultima_tentativa).total_seconds()
                    if segundos_desde_tentativa < intervalo_minimo:
                        continue

                dados = montar_dados_agendamento_para_reenvio(ag)
                retorno = enviar_agendamento_para_sances(dados)

                ag.sances_status = retorno.get("status", SANCES_STATUS_ERRO)
                ag.sances_enviado = bool(retorno.get("sucesso", False))
                ag.sances_protocolo = retorno.get("protocolo_sances", "") or ""
                ag.sances_erro = retorno.get("erro", "") or ""
                ag.sances_data_envio = agora_time if ag.sances_enviado else getattr(ag, "sances_data_envio", None)

                ag.sances_tentativas = tentativas + 1
                ag.sances_ultima_tentativa = agora_time
                ag.sances_ultimo_retorno = str(retorno)

                db.commit()

                log_info(
                    "[SANCES WORKER] Reenvio processado:",
                    str(getattr(ag, "protocolo", "") or ""),
                    ag.sances_status,
                    f"Tentativa {ag.sances_tentativas}"
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

        try:
            processar_followup_inteligente()
        except Exception as e:
            log_erro("Worker erro em processar_followup_inteligente:", repr(e))

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


# ==========================================
# DASHBOARD
# ==========================================
@app.route("/dashboard")
def dashboard():
    db = SessionLocal()

    try:
        filtro = request.args.get("filtro", "hoje")

        hoje = datetime.now().date()
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        inicio_mes = hoje.replace(day=1)

        query = db.query(Atendimento)
        query_ag = db.query(AgendamentoRevisao)

        if filtro == "hoje":
            data_base = datetime.combine(hoje, datetime.min.time())
            query = query.filter(Atendimento.data >= data_base)
            query_ag = query_ag.filter(AgendamentoRevisao.criado_em >= data_base)

        elif filtro == "semana":
            data_base = datetime.combine(inicio_semana, datetime.min.time())
            query = query.filter(Atendimento.data >= data_base)
            query_ag = query_ag.filter(AgendamentoRevisao.criado_em >= data_base)

        elif filtro == "mes":
            data_base = datetime.combine(inicio_mes, datetime.min.time())
            query = query.filter(Atendimento.data >= data_base)
            query_ag = query_ag.filter(AgendamentoRevisao.criado_em >= data_base)

        total = query.count()
        total_revisoes = query.filter(Atendimento.setor == "Revisão").count()
        revisao = total_revisoes

        total_duvidas_revisoes = query.filter(Atendimento.setor == "Dúvidas Revisoes").count()
        total_duvidas_garantia = query.filter(Atendimento.setor == "Dúvidas Garantia").count()
        total_duvidas = total_duvidas_revisoes + total_duvidas_garantia

        agendados = query_ag.filter(AgendamentoRevisao.status == STATUS_AGENDADO).count()
        concluidos = query_ag.filter(
            AgendamentoRevisao.status.in_(["CONCLUIDO", "CONCLUÍDO", "Concluído", STATUS_FINALIZADO])
        ).count()
        atendimento_humano = query.filter(
            Atendimento.atendimento_humano == True
        ).count()

        cancelados = query_ag.filter(AgendamentoRevisao.status == STATUS_CANCELADO).count()
        reagendados = query_ag.filter(AgendamentoRevisao.status == STATUS_REAGENDADO).count()
        total_agendamentos_periodo = query_ag.count()

        sances_pendentes = query_ag.filter(AgendamentoRevisao.sances_status == SANCES_STATUS_PENDENTE).count()
        sances_enviados = query_ag.filter(AgendamentoRevisao.sances_status == SANCES_STATUS_ENVIADO).count()
        sances_erros = query_ag.filter(AgendamentoRevisao.sances_status == SANCES_STATUS_ERRO).count()
        sances_nao_configurado = query_ag.filter(AgendamentoRevisao.sances_status == SANCES_STATUS_NAO_CONFIGURADO).count()

        primeira = query.filter(
            Atendimento.setor == "Revisão",
            Atendimento.revisao == "1"
        ).count()
        segunda = query.filter(
            Atendimento.setor == "Revisão",
            Atendimento.revisao == "2"
        ).count()
        terceira = query.filter(
            Atendimento.setor == "Revisão",
            Atendimento.revisao == "3"
        ).count()
        quarta = query.filter(
            Atendimento.setor == "Revisão",
            Atendimento.revisao == "4"
        ).count()
        quinta = query.filter(
            Atendimento.setor == "Revisão",
            Atendimento.revisao.in_(["5", "6", "7", "8", "9", "10"])
        ).count()

        contador_itens = Counter()
        registros_itens = query.filter(
            Atendimento.setor == "Revisão"
        ).with_entities(Atendimento.venda_adicional).all()

        for item in registros_itens:
            valor = item[0] if isinstance(item, tuple) else item
            if not valor:
                continue

            lista_itens = extrair_itens_venda_real(valor)
            for i in lista_itens:
                contador_itens[i] += 1

        ranking_itens = contador_itens.most_common(20)
        total_itens_vendidos = sum(contador_itens.values())

        agendamentos = query_ag.order_by(
            AgendamentoRevisao.criado_em.desc()
        ).limit(20).all()

        duvidas_ia = total_duvidas

        return render_template(
            "dashboard.html",
            filtro_ativo=filtro,
            total=total or 0,
            revisao=revisao or 0,
            total_revisoes=total_revisoes or 0,
            total_duvidas=total_duvidas or 0,
            total_duvidas_revisoes=total_duvidas_revisoes or 0,
            total_duvidas_garantia=total_duvidas_garantia or 0,
            agendados=agendados or 0,
            cancelados=cancelados or 0,
            reagendados=reagendados or 0,
            concluidos=concluidos or 0,
            atendimento_humano=atendimento_humano or 0,
            duvidas_ia=duvidas_ia or 0,
            total_agendamentos_periodo=total_agendamentos_periodo or 0,
            primeira=primeira or 0,
            segunda=segunda or 0,
            terceira=terceira or 0,
            quarta=quarta or 0,
            quinta=quinta or 0,
            total_itens_vendidos=total_itens_vendidos or 0,
            ranking_itens=ranking_itens or [],
            agendamentos=agendamentos or [],
            sances_pendentes=sances_pendentes or 0,
            sances_enviados=sances_enviados or 0,
            sances_erros=sances_erros or 0,
            sances_nao_configurado=sances_nao_configurado or 0,
        )

    except Exception as e:
        log_erro("Dashboard erro:", repr(e))
        return "Erro dashboard", 500

    finally:
        db.close()


# ==========================================
# REENVIO MANUAL SANCES
# ==========================================
@app.route("/reenvio-sances/<protocolo>", methods=["POST"])
def reenvio_sances(protocolo):
    try:
        protocolo = limpar_texto(protocolo)

        if not protocolo:
            return jsonify({
                "ok": False,
                "mensagem": "Protocolo inválido."
            }), 400

        ag = buscar_agendamento_por_protocolo(protocolo)

        if not ag:
            return jsonify({
                "ok": False,
                "mensagem": "Agendamento não encontrado."
            }), 404

        dados_reenvio = montar_dados_agendamento_para_reenvio(ag)
        retorno_sances = enviar_agendamento_para_sances(dados_reenvio)

        atualizado = atualizar_status_sances_agendamento(protocolo, retorno_sances)

        if not atualizado:
            return jsonify({
                "ok": False,
                "mensagem": "Falha ao atualizar status do Sances no banco."
            }), 500

        return jsonify({
            "ok": True,
            "mensagem": "Reenvio processado com sucesso.",
            "status": retorno_sances.get("status", SANCES_STATUS_ERRO),
            "protocolo_sances": retorno_sances.get("protocolo_sances", ""),
            "erro": retorno_sances.get("erro", "")
        }), 200

    except Exception as e:
        log_erro("Erro na rota de reenvio Sances:", repr(e))
        return jsonify({
            "ok": False,
            "mensagem": "Erro interno ao reenviar para o Sances."
        }), 500


# ==========================================
# WEBHOOK
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Webhook ativo"}), 200

    payload = request.get_json(silent=True) or {}
    log_info("PAYLOAD RECEBIDO:", payload)

    if evento_eh_do_proprio_bot(payload):
        return jsonify({"status": "ignorado", "motivo": "proprio_bot"}), 200

    message_id = extrair_message_id(payload)
    telefone = extrair_telefone(payload)
    texto = extrair_texto(payload)

    if not telefone:
        return jsonify({"status": "ignorado", "motivo": "sem telefone"}), 200

    if telefone_eh_grupo(telefone):
        return jsonify({"status": "ignorado", "motivo": "grupo"}), 200

    if message_id and mensagem_ja_processada(message_id):
        return jsonify({"status": "ignorado", "motivo": "duplicado"}), 200

    telefone = limpar_telefone(telefone)
    texto = limpar_texto(texto)
    texto_normalizado = normalizar_texto(texto)
    texto_opcao = limpar_opcao(texto)

    if message_id:
        registrar_mensagem_processada(message_id)

    iniciar_cliente(telefone)

    ultima_interacao = clientes[telefone].get("ultima_interacao", agora())
    if (
        clientes[telefone].get("etapa") != "menu"
        and not clientes[telefone].get("atendimento_humano")
        and (agora() - ultima_interacao) > TEMPO_INATIVIDADE
    ):
        resetar_cliente(telefone)
        enviar_mensagem(
            telefone,
            "Olá 👋\n\n"
            "Como passou um tempo desde a última mensagem, vou te mostrar o menu novamente para seguir da melhor forma."
        )
        enviar_menu(telefone)
        return jsonify({"status": "ok"}), 200

    atualizar_interacao(telefone)
    atualizar_retorno_na_planilha(telefone, texto)

    # Persistência de atendimento humano via banco
    if atendimento_humano_ativo_no_banco(telefone):
        clientes[telefone]["atendimento_humano"] = True
        clientes[telefone]["etapa"] = "atendimento_humano"
        definir_status_cliente(telefone, STATUS_ATENDIMENTO_HUMANO)

        if texto_normalizado not in ["menu", "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]:
            return jsonify({"status": "ok", "modo": "atendimento_humano"}), 200

    if texto_normalizado in ["menu", "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]:
        encerrar_atendimento_humano(telefone)
        resetar_cliente(telefone)
        enviar_menu(telefone)
        return jsonify({"status": "ok"}), 200

    etapa = clientes[telefone]["etapa"]

    etapas_bloqueadas_ia = [
        "revisao_modelo",
        "revisao_nome",
        "revisao_cpf",
        "revisao_ano",
        "revisao_km",
        "revisao_revisao",
        "revisao_dia",
        "revisao_data",
        "revisao_horario",
        "revisao_venda",
        "revisao_observacao",
        "revisao_confirmacao"
    ]

    if etapa in etapas_bloqueadas_ia:
        resposta_ia = resposta_ia_vazia()
    else:
        resposta_ia = obter_dados_extraidos_ia(texto)

    intencao_ia = resposta_ia.get("intencao", "")
    dados_extraidos_ia = resposta_ia.get("dados_extraidos", {}) or {}

    # daqui para baixo segue o restante normal do seu fluxo
    # usando:
    # etapa
    # intencao_ia
    # dados_extraidos_ia
    # texto
    # texto_opcao
    # texto_normalizado
    # ==========================================
    # INTENÇÕES GERAIS
    # ==========================================
    if intencao_ia in ["humano", "falar_humano", "atendimento_humano"] and not etapa.startswith("revisao"):
        if etapa != "atendimento_humano":
            ativar_atendimento_humano(telefone)
        return jsonify({"status": "ok"}), 200

    if intencao_ia in ["consultar_agendamento", "acompanhar_agendamento"]:
        cpf = limpar_cpf(dados_extraidos_ia.get("cpf", "") or texto)
        responder_consulta_agendamento(telefone, cpf)
        return jsonify({"status": "ok"}), 200

    if intencao_ia == "cancelar_agendamento":
        cpf = limpar_cpf(dados_extraidos_ia.get("cpf", "") or texto)
        responder_cancelamento_agendamento(telefone, cpf)
        return jsonify({"status": "ok"}), 200

    if intencao_ia in ["reagendar_agendamento", "reagendar"]:
        cpf = limpar_cpf(dados_extraidos_ia.get("cpf", "") or texto)
        limpar_dados_fluxo_revisao(telefone)
        iniciar_reagendamento(telefone, cpf)
        return jsonify({"status": "ok"}), 200

    if etapa == "consulta_agendamento_cpf":
        responder_consulta_agendamento(telefone, texto)
        return jsonify({"status": "ok"}), 200

    if etapa == "cancelar_agendamento_cpf":
        responder_cancelamento_agendamento(telefone, texto)
        return jsonify({"status": "ok"}), 200

    if etapa == "reagendar_agendamento_cpf":
        iniciar_reagendamento(telefone, texto)
        return jsonify({"status": "ok"}), 200

    # ==========================================
    # SAÍDA RÁPIDA DE DÚVIDAS PARA PEÇAS / ACESSÓRIOS
    # ==========================================
    if etapa in ["menu_duvidas", "duvida_revisoes", "duvida_garantia", "duvida_pos_resposta"] and intencao_ia == "pecas":
        iniciar_fluxo_pecas(telefone, texto)
        return jsonify({"status": "ok"}), 200

    if etapa in ["menu_duvidas", "duvida_revisoes", "duvida_garantia", "duvida_pos_resposta"] and intencao_ia == "acessorios":
        iniciar_fluxo_acessorios(telefone, texto)
        return jsonify({"status": "ok"}), 200

    # ==========================================
    # MENU PRINCIPAL
    # ==========================================
    if etapa == "menu":
        if texto_opcao == "1":
            clientes[telefone]["atendimento_humano"] = False
            definir_status_cliente(telefone, STATUS_AGENDAMENTO_INICIADO)
            proxima = iniciar_fluxo_revisao_por_intencao(telefone, {})
            enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, proxima))
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "2":
            clientes[telefone]["atendimento_humano"] = False
            iniciar_fluxo_pecas(telefone)
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "3":
            clientes[telefone]["atendimento_humano"] = False
            iniciar_fluxo_acessorios(telefone)
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "4":
            clientes[telefone]["atendimento_humano"] = False
            clientes[telefone]["etapa"] = "garantia"
            salvar_evento_atendimento(
                telefone=telefone,
                setor="Garantia",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="garantia_iniciado",
                atendimento_humano=False,
                concluido=False
            )
            enviar_mensagem(telefone, "🛡️ *Garantia*\n\nDescreva sua solicitação:")
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "5":
            clientes[telefone]["atendimento_humano"] = False
            clientes[telefone]["etapa"] = "atacado"
            salvar_evento_atendimento(
                telefone=telefone,
                setor="Logista / Atacado",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="atacado_iniciado",
                atendimento_humano=False,
                concluido=False
            )
            enviar_mensagem(
                telefone,
                "📦 *Logista / Atacado*\n\n"
                "1 - Solicitar cotação\n"
                "2 - Cadastro de logista\n"
                "3 - Receber catálogo\n"
                "4 - Falar com consultor"
            )
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "6":
            clientes[telefone]["atendimento_humano"] = False
            clientes[telefone]["etapa"] = "menu_duvidas"
            enviar_mensagem(telefone, menu_duvidas())
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "7":
            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "agendar_revisao":
            clientes[telefone]["atendimento_humano"] = False
            definir_status_cliente(telefone, STATUS_AGENDAMENTO_INICIADO)
            iniciar_fluxo_revisao_por_intencao(telefone, dados_extraidos_ia)

            resumo = montar_resumo_dados_ia_revisao(telefone)
            if resumo:
                enviar_mensagem(
                    telefone,
                    "Perfeito 👍 Entendi seu pedido de agendamento e já adiantei algumas informações."
                )
            else:
                enviar_mensagem(
                    telefone,
                    "Perfeito 👍 Vou seguir com seu agendamento de revisão."
                )

            enviar_proxima_etapa_com_contexto_ia(telefone)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "pecas":
            clientes[telefone]["atendimento_humano"] = False
            iniciar_fluxo_pecas(telefone, texto)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "acessorios":
            clientes[telefone]["atendimento_humano"] = False
            iniciar_fluxo_acessorios(telefone, texto)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "duvidas":
            clientes[telefone]["atendimento_humano"] = False
            clientes[telefone]["etapa"] = "menu_duvidas"
            enviar_mensagem(telefone, menu_duvidas())
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "garantia":
            clientes[telefone]["atendimento_humano"] = False
            clientes[telefone]["etapa"] = "garantia"
            salvar_evento_atendimento(
                telefone=telefone,
                setor="Garantia",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="garantia_iniciado",
                atendimento_humano=False,
                concluido=False
            )
            enviar_mensagem(telefone, "🛡️ Descreva sua solicitação de garantia:")
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "atacado":
            clientes[telefone]["atendimento_humano"] = False
            clientes[telefone]["etapa"] = "atacado"
            salvar_evento_atendimento(
                telefone=telefone,
                setor="Logista / Atacado",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="atacado_iniciado",
                atendimento_humano=False,
                concluido=False
            )
            enviar_mensagem(
                telefone,
                "📦 *Logista / Atacado*\n\n"
                "1 - Solicitar cotação\n"
                "2 - Cadastro de logista\n"
                "3 - Receber catálogo\n"
                "4 - Falar com consultor"
            )
            return jsonify({"status": "ok"}), 200

        enviar_menu(telefone)
        return jsonify({"status": "ok"}), 200

    # ==========================================
    # MENU DÚVIDAS
    # ==========================================
    if etapa == "menu_duvidas":
        if texto_opcao == "1":
            clientes[telefone]["categoria_duvida"] = "revisoes"
            clientes[telefone]["etapa"] = "duvida_revisoes"
            enviar_mensagem(
                telefone,
                "📘 *Dúvidas sobre Revisões*\n\n"
                "Pode me enviar sua dúvida em texto livre.\n\n"
                "Exemplos:\n"
                "• Qual o valor da revisão?\n"
                "• O que troca na 2ª revisão?\n"
                "• Quanto tempo demora?\n"
                "• Com quantos km faz a revisão?"
            )
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "2":
            clientes[telefone]["categoria_duvida"] = "garantia"
            clientes[telefone]["etapa"] = "duvida_garantia"
            enviar_mensagem(
                telefone,
                "📘 *Dúvidas sobre Garantia*\n\n"
                "Pode me enviar sua dúvida em texto livre.\n\n"
                "Exemplos:\n"
                "• O que a garantia cobre?\n"
                "• Preciso levar documentos?\n"
                "• Posso perder a garantia?\n"
                "• Como funciona a análise?"
            )
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "3":
            resetar_cliente(telefone)
            enviar_menu(telefone)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "pecas":
            iniciar_fluxo_pecas(telefone, texto)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "acessorios":
            iniciar_fluxo_acessorios(telefone, texto)
            return jsonify({"status": "ok"}), 200

        enviar_mensagem(telefone, menu_duvidas())
        return jsonify({"status": "ok"}), 200

    # ==========================================
    # RESPOSTA DÚVIDAS
    # ==========================================
    if etapa in ["duvida_revisoes", "duvida_garantia"]:
        if intencao_ia == "pecas":
            iniciar_fluxo_pecas(telefone, texto)
            return jsonify({"status": "ok"}), 200

        if intencao_ia == "acessorios":
            iniciar_fluxo_acessorios(telefone, texto)
            return jsonify({"status": "ok"}), 200

        categoria = "revisoes" if etapa == "duvida_revisoes" else "garantia"

        resposta_duvida = responder_duvida_por_tabela(
            categoria=categoria,
            pergunta_cliente=texto,
            modelo=clientes[telefone].get("modelo", ""),
            revisao=clientes[telefone].get("revisao", "")
        )

        clientes[telefone]["duvidas_ia"] = int(clientes[telefone].get("duvidas_ia", 0) or 0) + 1

        salvar_duvida_dashboard(
            telefone=telefone,
            categoria="Revisoes" if categoria == "revisoes" else "Garantia",
            pergunta=texto,
            resposta=resposta_duvida
        )

        enviar_mensagem(telefone, resposta_duvida)

        clientes[telefone]["etapa"] = "duvida_pos_resposta"
        enviar_mensagem(telefone, mensagem_duvida_retorno_fluxo(telefone))
        return jsonify({"status": "ok"}), 200

    if etapa == "duvida_pos_resposta":
        if intencao_ia == "pecas":
            iniciar_fluxo_pecas(telefone, texto)
            return jsonify({"status": "ok"}), 200

        if intencao_ia == "acessorios":
            iniciar_fluxo_acessorios(telefone, texto)
            return jsonify({"status": "ok"}), 200

        etapa_retorno = clientes[telefone].get("etapa_retorno_duvida", "")

        if etapa_retorno and etapa_retorno.startswith("revisao"):
            if texto_opcao == "1":
                clientes[telefone]["etapa"] = etapa_retorno
                enviar_mensagem(telefone, "Perfeito 👍 Vamos continuar seu agendamento.")

                if etapa_retorno == "revisao_horario":
                    revisao = clientes[telefone]["revisao"]
                    dia = clientes[telefone]["dia"]
                    horarios = horarios_por_revisao(revisao, dia)
                    clientes[telefone]["horarios_disponiveis"] = horarios
                    enviar_mensagem(telefone, montar_mensagem_horarios(horarios))
                else:
                    enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, etapa_retorno))

                return jsonify({"status": "ok"}), 200

            elif texto_opcao == "2":
                clientes[telefone]["etapa"] = "menu_duvidas"
                enviar_mensagem(telefone, menu_duvidas())
                return jsonify({"status": "ok"}), 200

            elif texto_opcao == "3":
                ativar_atendimento_humano(telefone)
                return jsonify({"status": "ok"}), 200

            enviar_mensagem(telefone, mensagem_duvida_retorno_fluxo(telefone))
            return jsonify({"status": "ok"}), 200

        else:
            if texto_opcao == "1":
                clientes[telefone]["etapa"] = "menu_duvidas"
                enviar_mensagem(telefone, menu_duvidas())
                return jsonify({"status": "ok"}), 200

            elif texto_opcao == "2":
                resetar_cliente(telefone)
                enviar_menu(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_opcao == "3":
                ativar_atendimento_humano(telefone)
                return jsonify({"status": "ok"}), 200

            enviar_mensagem(telefone, mensagem_duvida_retorno_fluxo(telefone))
            return jsonify({"status": "ok"}), 200

    # ==========================================
    # FLUXO REVISÃO
    # ==========================================
    if etapa.startswith("revisao"):
        definir_status_cliente(telefone, STATUS_AGENDAMENTO_INICIADO)
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos_ia)

        etapas_bloqueadas_para_troca_setor = {
            "revisao_tipo",
            "revisao_dia",
            "revisao_data",
            "revisao_horario",
            "revisao_tipo_atendimento",
            "revisao_venda",
            "revisao_observacao",
            "revisao_confirmacao",
        }

        if etapa in etapas_bloqueadas_para_troca_setor and intencao_ia in ["pecas", "acessorios", "garantia", "atacado"]:
            intencao_ia = ""

        etapa_atualizada = primeira_etapa_pendente_revisao(telefone)

        if etapa_atualizada != etapa and etapa != "revisao_confirmacao":
            clientes[telefone]["etapa"] = etapa_atualizada
            enviar_proxima_etapa_com_contexto_ia(telefone)
            return jsonify({"status": "ok"}), 200

        texto_norm = normalizar_texto(texto)
        texto_limpo_opcao = limpar_opcao(texto)

        respostas_que_nao_sao_duvida = False

        if etapa == "revisao_tipo":
            if (
                normalizar_revisao_para_fluxo(texto) in ["1", "2", "3", "4", "5"]
                or "revisao" in texto_norm
                or "revisão" in texto_norm
                or "mil" in texto_norm
                or texto_limpo_opcao in ["1", "2", "3", "4", "5"]
            ):
                respostas_que_nao_sao_duvida = True

        elif etapa == "revisao_dia":
            if texto_limpo_opcao in ["1", "2", "3", "4", "5", "6"]:
                respostas_que_nao_sao_duvida = True

        elif etapa == "revisao_data":
            if re.match(r"^\d{2}/\d{2}/\d{4}$", texto.strip()):
                respostas_que_nao_sao_duvida = True

        elif etapa == "revisao_horario":
            if texto_limpo_opcao.isdigit():
                respostas_que_nao_sao_duvida = True

        elif etapa == "revisao_tipo_atendimento":
            if texto_limpo_opcao in ["1", "2"]:
                respostas_que_nao_sao_duvida = True

        elif etapa == "revisao_venda":
            if texto.strip():
                respostas_que_nao_sao_duvida = True

        elif etapa == "revisao_observacao":
            if texto.strip():
                respostas_que_nao_sao_duvida = True

        if (
            intencao_ia == "duvidas"
            and etapa_revisao_permite_ir_para_duvidas(etapa)
            and not respostas_que_nao_sao_duvida
        ):
            encaminhar_para_menu_duvidas(telefone, etapa_atual=etapa)
            return jsonify({"status": "ok"}), 200

        if intencao_ia in ["humano", "falar_humano", "atendimento_humano"]:
            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_modelo":
            if not clientes[telefone].get("modelo"):
                clientes[telefone]["modelo"] = texto.upper()
            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_nome":
            if not clientes[telefone].get("nome"):
                clientes[telefone]["nome"] = texto.upper()
            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_cpf":
            cpf = clientes[telefone].get("cpf") or limpar_cpf(texto)

            if len(cpf) != 11:
                enviar_mensagem(telefone, "⚠️ CPF inválido. Digite novamente com 11 números:")
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["cpf"] = cpf
            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_ano":
            ano = clientes[telefone].get("ano") or texto

            if not ano:
                enviar_mensagem(telefone, "⚠️ Informe o ano da moto.")
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["ano"] = ano
            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_km":
            km_atual = clientes[telefone].get("km_atual") or re.sub(r"\D", "", texto)

            if not km_atual:
                enviar_mensagem(telefone, "⚠️ Informe a quilometragem atual da moto.")
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["km_atual"] = km_atual
            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_tipo":
            revisao = clientes[telefone].get("revisao") or normalizar_revisao_para_fluxo(texto)

            if not revisao:
                if "5 mil" in texto_norm or "5000" in texto_norm:
                    revisao = "1"
                elif "10 mil" in texto_norm or "10000" in texto_norm:
                    revisao = "2"
                elif "15 mil" in texto_norm or "15000" in texto_norm:
                    revisao = "3"
                elif "20 mil" in texto_norm or "20000" in texto_norm:
                    revisao = "4"
                elif "25 mil" in texto_norm or "25000" in texto_norm:
                    revisao = "5"

            if revisao not in ["1", "2", "3", "4", "5"]:
                enviar_mensagem(
                    telefone,
                    "⚠️ Não consegui identificar a revisão.\n\n"
                    "Digite de 1 a 5 ou escreva algo como:\n"
                    "• 1ª revisão\n"
                    "• 2ª revisão\n"
                    "• revisão de 5 mil"
                )
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["revisao"] = revisao
            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_dia":
            dia = clientes[telefone].get("dia") or texto

            if dia not in ["1", "2", "3", "4", "5", "6"]:
                enviar_mensagem(telefone, "⚠️ Dia inválido. Digite de 1 a 6.")
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["dia"] = dia
            clientes[telefone]["dia_texto"] = nome_dia(dia)
            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_data":
            data_digitada = texto

            if not validar_data(data_digitada):
                enviar_mensagem(
                    telefone,
                    "⚠️ Data inválida.\n\nDigite novamente no formato *dd/mm/aaaa*."
                )
                return jsonify({"status": "ok"}), 200

            if not data_corresponde_ao_dia_escolhido(data_digitada, clientes[telefone]["dia"]):
                enviar_mensagem(
                    telefone,
                    "⚠️ A data informada não corresponde ao dia que você escolheu.\n\n"
                    f"Você escolheu *{clientes[telefone]['dia_texto']}*.\n"
                    "Digite uma data compatível no formato *dd/mm/aaaa*."
                )
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["data"] = data_digitada

            revisao = clientes[telefone]["revisao"]
            dia = clientes[telefone]["dia"]
            horarios = horarios_por_revisao(revisao, dia)

            clientes[telefone]["horarios_disponiveis"] = horarios
            clientes[telefone]["etapa"] = "revisao_horario"

            enviar_mensagem(telefone, montar_mensagem_horarios(horarios))
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_horario":
            horarios = clientes[telefone]["horarios_disponiveis"]

            try:
                idx = int(texto) - 1
                horario = horarios[idx]
            except Exception:
                enviar_mensagem(telefone, "⚠️ Escolha um horário válido.")
                return jsonify({"status": "ok"}), 200

            if not verificar_capacidade(clientes[telefone]["data"], horario, clientes[telefone]["revisao"]):
                enviar_mensagem(
                    telefone,
                    "⚠️ Esse horário acabou de ficar indisponível.\n\nEscolha outro horário:"
                )
                enviar_mensagem(telefone, montar_mensagem_horarios(horarios))
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["horario"] = horario
            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_tipo_atendimento":
            if texto == "1":
                clientes[telefone]["tipo_atendimento"] = "AGUARDAR NA CONCESSIONÁRIA"
            elif texto == "2":
                clientes[telefone]["tipo_atendimento"] = "DEIXAR A MOTO E RETIRAR DEPOIS"
            else:
                enviar_mensagem(telefone, "⚠️ Escolha 1 ou 2.")
                return jsonify({"status": "ok"}), 200

            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_venda":
            if texto == "2":
                clientes[telefone]["venda_adicional"] = "Nenhum"
                clientes[telefone]["itens"] = "Nenhum"
            else:
                venda_formatada = formatar_itens_adicionais_para_salvar(texto)
                clientes[telefone]["venda_adicional"] = venda_formatada
                clientes[telefone]["itens"] = venda_formatada

            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_observacao":
            if texto == "2":
                clientes[telefone]["observacao"] = "Nenhuma"
            else:
                clientes[telefone]["observacao"] = texto

            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "revisao_confirmacao":
            if texto == "1":
                dados = clientes[telefone]
                dados["telefone"] = telefone

                protocolo = salvar_agendamento(telefone, dados)
                if not protocolo:
                    enviar_mensagem(
                        telefone,
                        "❌ Ocorreu um erro ao salvar seu agendamento.\nTente novamente em instantes."
                    )
                    return jsonify({"status": "ok"}), 200

                definir_status_cliente(telefone, STATUS_AGENDADO)
                salvar_atendimento_dashboard(telefone, dados)

                mensagem_sances = ""

                try:
                    retorno_sances = enviar_agendamento_para_sances(dados)

                    clientes[telefone]["sances_status"] = retorno_sances.get("status", SANCES_STATUS_ERRO)
                    clientes[telefone]["sances_protocolo"] = retorno_sances.get("protocolo_sances", "")
                    clientes[telefone]["sances_erro"] = retorno_sances.get("erro", "")
                    clientes[telefone]["sances_data_envio"] = formatar_data_hora()
                    clientes[telefone]["sances_enviado"] = bool(retorno_sances.get("sucesso", False))

                    atualizar_status_sances_agendamento(protocolo, retorno_sances)

                    try:
                        mensagem_sances = montar_mensagem_status_sances(retorno_sances)
                    except Exception as e:
                        log_erro("Erro ao montar mensagem do Sances:", repr(e))
                        mensagem_sances = ""

                except Exception as e:
                    log_erro("Erro na integração com Sances:", repr(e))
                    clientes[telefone]["sances_status"] = SANCES_STATUS_ERRO
                    clientes[telefone]["sances_protocolo"] = ""
                    clientes[telefone]["sances_erro"] = repr(e)
                    clientes[telefone]["sances_data_envio"] = formatar_data_hora()
                    clientes[telefone]["sances_enviado"] = False
                    mensagem_sances = ""

                enviar_mensagem(
                    telefone,
                    "✅ *Agendamento confirmado com sucesso*\n\n"
                    f"👤 {dados['nome']}\n"
                    f"🏍️ {dados['modelo']}\n"
                    f"📅 {dados['data']}\n"
                    f"⏰ {dados['horario']}\n"
                    f"📌 Protocolo: {protocolo}"
                    f"{mensagem_sances}\n\n"
                    "Lembrando de trazer o manual no momento da revisão para facilitar o atendimento.\n\n"
                    "Agradecemos por escolher a *Motoshow Yamaha* 🏍️"
                )

                resetar_cliente(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto == "2":
                limpar_dados_fluxo_revisao(telefone)
                clientes[telefone]["etapa"] = "revisao_modelo"
                enviar_mensagem(
                    telefone,
                    "Perfeito. Vamos corrigir seu agendamento.\n\n"
                    "Informe novamente o *modelo da moto*:"
                )
                return jsonify({"status": "ok"}), 200

            else:
                enviar_mensagem(
                    telefone,
                    "⚠️ Digite *1* para confirmar ou *2* para corrigir."
                )
                return jsonify({"status": "ok"}), 200

    # ==========================================
    # PEÇAS / ACESSÓRIOS / GARANTIA / ATACADO
    # ==========================================
    if etapa == "pecas":
        salvar_evento_atendimento(
            telefone=telefone,
            setor="Peças",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="pecas_solicitada",
            dados={"observacao": texto},
            atendimento_humano=False,
            concluido=True
        )
        enviar_mensagem(
            telefone,
            "✅ Sua solicitação de peças foi registrada com sucesso.\n\n"
            "Nossa equipe vai continuar seu atendimento."
        )
        resetar_cliente(telefone)
        return jsonify({"status": "ok"}), 200

    if etapa == "acessorios":
        salvar_evento_atendimento(
            telefone=telefone,
            setor="Acessórios",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="acessorio_solicitado",
            dados={"observacao": texto},
            atendimento_humano=False,
            concluido=True
        )
        enviar_mensagem(
            telefone,
            "✅ Solicitação registrada.\nNossa equipe dará continuidade."
        )
        resetar_cliente(telefone)
        return jsonify({"status": "ok"}), 200

    if etapa == "garantia":
        salvar_evento_atendimento(
            telefone=telefone,
            setor="Garantia",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="garantia_solicitada",
            dados={"observacao": texto},
            atendimento_humano=False,
            concluido=True
        )
        enviar_mensagem(
            telefone,
            "✅ Sua solicitação de garantia foi registrada com sucesso.\n\n"
            "Nossa equipe vai continuar seu atendimento."
        )

        resetar_cliente(telefone)
        return jsonify({"status": "ok"}), 200

    if etapa == "atacado":
        if texto == "3":
            enviado = enviar_pdf(
                telefone,
                "catalogo-atacado.pdf",
                "📄 Catálogo Atacado Motoshow Yamaha"
            )

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Logista / Atacado",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="catalogo_atacado_enviado" if enviado else "catalogo_atacado_falha",
                atendimento_humano=False,
                concluido=True
            )

            if enviado:
                enviar_mensagem(telefone, "✅ Catálogo enviado com sucesso.")
            else:
                enviar_mensagem(
                    telefone,
                    "⚠️ Não consegui enviar o catálogo agora. Nossa equipe dará continuidade."
                )
        else:
            salvar_evento_atendimento(
                telefone=telefone,
                setor="Logista / Atacado",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="atacado_solicitado",
                dados={"observacao": texto},
                atendimento_humano=False,
                concluido=True
            )
            enviar_mensagem(
                telefone,
                "✅ Sua solicitação foi registrada com sucesso.\n\n"
                "Nossa equipe comercial vai continuar seu atendimento."
            )

        resetar_cliente(telefone)
        return jsonify({"status": "ok"}), 200

    if etapa == "atendimento_humano":
        return jsonify({"status": "ok"}), 200

    return jsonify({"status": "ok"}), 200


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
        port=int(os.getenv("PORT", 5000))
    )