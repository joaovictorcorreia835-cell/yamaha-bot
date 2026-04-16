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
TEMPO_INATIVIDADE = int(os.getenv("TEMPO_INATIVIDADE", "900"))

ARQUIVO_FOLLOWUP = os.getenv("ARQUIVO_FOLLOWUP", "clientes_disparo.xlsx")
INTERVALO_WORKER_FOLLOWUP = int(os.getenv("INTERVALO_WORKER_FOLLOWUP", "300"))
FOLLOWUP_1_HORAS = int(os.getenv("FOLLOWUP_1_HORAS", "48"))
FOLLOWUP_2_DIAS = int(os.getenv("FOLLOWUP_2_DIAS", "5"))

# ==========================================
# CONFIG FUTURA SANCES
# mock | real
# ==========================================
SANCES_MODO = os.getenv("SANCES_MODO", "mock").strip().lower()

# Para simular comportamento futuro sem integração real:
# nao_configurado | enviado | erro
SANCES_SIMULAR_RESULTADO = os.getenv("SANCES_SIMULAR_RESULTADO", "nao_configurado").strip().lower()

SANCES_TIMEOUT = int(os.getenv("SANCES_TIMEOUT", "15"))
SANCES_RETRY_MAX = int(os.getenv("SANCES_RETRY_MAX", "1"))

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
url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"

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
    pasta_pdfs = os.path.join(app.root_path, "static", "pdfs")
    return send_from_directory(pasta_pdfs, arquivo)


# ==========================================
# UTILITÁRIOS GERAIS
# ==========================================
def limpar_texto(texto):
    return str(texto or "").strip()


def normalizar_texto(texto):
    return limpar_texto(texto).lower()


def limpar_telefone(telefone):
    telefone = str(telefone or "").strip()
    telefone = telefone.replace("@c.us", "").replace("@s.whatsapp.net", "").replace("@g.us", "")
    return re.sub(r"\D", "", telefone)


def limpar_cpf(cpf):
    return re.sub(r"\D", "", str(cpf or ""))


def telefone_eh_grupo(telefone):
    return "@g.us" in str(telefone or "")


def limpar_opcao(texto):
    return (
        str(texto or "")
        .replace("️⃣", "")
        .replace("\u200e", "")
        .replace("\u200f", "")
        .strip()
    )


def agora():
    return time.time()


def agora_datetime():
    return datetime.now()


def formatar_data_hora(dt=None):
    dt = dt or datetime.now()
    return dt.strftime("%d/%m/%Y %H:%M")


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
    texto_norm = normalizar_texto(texto)

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

    return mapa.get(texto_norm, texto if texto in ["1", "2", "3", "4", "5"] else "")


MAPA_DIA_NUMERO = {
    "segunda": "1",
    "terca": "2",
    "terça": "2",
    "quarta": "3",
    "quinta": "4",
    "sexta": "5",
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
        "6": "Sábado"
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
        for v in valor:
            item = limpar_item_adicional(v)
            if item:
                itens.append(item)
        return itens

    texto = str(valor).strip()
    if not texto:
        return []

    texto = texto.replace("\n", ",").replace(";", ",").replace("|", ",")
    partes = [parte.strip() for parte in texto.split(",") if parte.strip()]

    itens_limpos = []
    for parte in partes:
        item = limpar_item_adicional(parte)
        if item:
            itens_limpos.append(item)

    return itens_limpos


def formatar_itens_adicionais_para_salvar(valor):
    itens = extrair_lista_itens_adicionais(valor)
    return ", ".join(itens)


def item_adicional_valido(item):
    item_limpo = limpar_item_adicional(item)

    if not item_limpo:
        return False

    if item_limpo in ["NENHUM", "NAO", "NÃO", "SEM ITEM", "SEM ITENS"]:
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
        protocolo_mock = f"SCS-{uuid.uuid4().hex[:8].upper()}"
        retorno = {
            "sucesso": True,
            "status": SANCES_STATUS_ENVIADO,
            "protocolo_sances": protocolo_mock,
            "mensagem": "Agendamento enviado com sucesso ao Sances (modo mock).",
            "erro": ""
        }
        log_integracao_sances(
            telefone=payload.get("telefone", ""),
            acao="mock_envio_agendamento_sucesso",
            payload=payload,
            retorno=retorno
        )
        return retorno

    if resultado == "erro":
        retorno = {
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "protocolo_sances": "",
            "mensagem": "Falha simulada no envio ao Sances.",
            "erro": "Erro simulado de integração Sances"
        }
        log_integracao_sances(
            telefone=payload.get("telefone", ""),
            acao="mock_envio_agendamento_erro",
            payload=payload,
            retorno=retorno
        )
        return retorno

    retorno = {
        "sucesso": False,
        "status": SANCES_STATUS_NAO_CONFIGURADO,
        "protocolo_sances": "",
        "mensagem": "Integração com Sances ainda não configurada.",
        "erro": "Sances não configurado"
    }
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

        # ==========================================
        # FUTURA INTEGRAÇÃO REAL
        # Aqui você vai plugar API, RPA ou outro método
        # ==========================================
        log_integracao_sances(
            telefone=payload.get("telefone", ""),
            acao="envio_real_nao_implementado",
            payload=payload,
            retorno="Modo real selecionado, mas integração ainda não implementada."
        )

        return {
            "sucesso": False,
            "status": SANCES_STATUS_NAO_CONFIGURADO,
            "protocolo_sances": "",
            "mensagem": "Modo real do Sances ainda não implementado.",
            "erro": "Integração real ainda não implementada"
        }

    except Exception as e:
        log_erro("Erro ao preparar envio para Sances:", repr(e))
        return {
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "protocolo_sances": "",
            "mensagem": "Erro ao preparar integração com Sances.",
            "erro": repr(e)
        }


def atualizar_status_sances_agendamento(protocolo, retorno_sances):
    db = SessionLocal()

    try:
        agendamento = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.protocolo == protocolo
        ).first()

        if not agendamento:
            log_erro("Agendamento não encontrado para atualizar status Sances:", protocolo)
            return False

        agendamento.sances_status = retorno_sances.get("status", SANCES_STATUS_ERRO)
        agendamento.sances_enviado = bool(retorno_sances.get("sucesso", False))
        agendamento.sances_protocolo = retorno_sances.get("protocolo_sances", "") or ""
        agendamento.sances_erro = retorno_sances.get("erro", "") or ""
        agendamento.sances_data_envio = datetime.now()

        db.commit()
        return True

    except Exception as e:
        db.rollback()
        log_erro("Erro ao atualizar status Sances do agendamento:", repr(e))
        return False

    finally:
        db.close()


def montar_mensagem_status_sances(retorno_sances):
    status = retorno_sances.get("status", SANCES_STATUS_PENDENTE)

    if status == SANCES_STATUS_ENVIADO:
        return (
            f"\n🔗 *Integração Sances:* enviada com sucesso"
            f"\n🧾 *Protocolo Sances:* {retorno_sances.get('protocolo_sances', '-')}"
        )

    if status == SANCES_STATUS_NAO_CONFIGURADO:
        return "\n🔗 *Integração Sances:* pendente de configuração"

    if status == SANCES_STATUS_ERRO:
        return "\n⚠️ *Integração Sances:* erro no envio"

    return f"\n🔗 *Integração Sances:* {status}"


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
    if telefone in clientes:
        clientes[telefone]["ultima_interacao"] = agora()


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
    clientes[telefone]["tipo_atendimento"] = ""
    clientes[telefone]["concluido"] = False
    clientes[telefone]["sances_enviado"] = False
    clientes[telefone]["sances_status"] = SANCES_STATUS_PENDENTE
    clientes[telefone]["sances_protocolo"] = ""
    clientes[telefone]["sances_erro"] = ""
    clientes[telefone]["sances_data_envio"] = ""
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
        "Nossa equipe seguirá com você por aqui.\n"
        "Quando quiser voltar ao menu automático, envie *menu*."
    )


def processar_inatividade():
    try:
        agora_atual = agora()

        for telefone in list(clientes.keys()):
            dados = clientes.get(telefone, {})
            ultima = dados.get("ultima_interacao", agora_atual)

            if agora_atual - ultima > TEMPO_INATIVIDADE:
                if dados.get("etapa") != "menu":
                    enviar_mensagem(
                        telefone,
                        "⏰ Seu atendimento foi encerrado por inatividade.\n\n"
                        "Quando quiser continuar, envie *menu*."
                    )
                resetar_cliente(telefone)

    except Exception as e:
        log_erro("Erro ao processar inatividade:", e)


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
        )

        if not telefone:
            data = payload.get("data", {}) or {}
            telefone = (
                data.get("phone")
                or data.get("chatId")
                or data.get("from")
                or data.get("connectedPhone")
            )

        if not telefone and isinstance(payload.get("sender"), dict):
            telefone = (
                payload.get("sender", {}).get("phone")
                or payload.get("sender", {}).get("id")
            )

        if telefone:
            telefone = str(telefone).replace("@c.us", "").replace("@s.whatsapp.net", "").strip()

        return telefone

    except Exception as e:
        log_erro("Erro ao extrair telefone:", e)
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
        log_erro("Erro ao extrair texto:", e)
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
        log_erro("Erro ao validar evento do próprio bot:", e)
        return False


# ==========================================
# ENVIO
# ==========================================
def enviar_mensagem(telefone, mensagem):
    try:
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

        log_info("Mensagem enviada:", telefone, response.status_code)
        return response.status_code in [200, 201]

    except Exception as e:
        log_erro("Erro envio mensagem:", e)
        return False


def enviar_pdf(telefone, arquivo, legenda=""):
    try:
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

        log_info("PDF enviado:", response.status_code)
        return response.status_code in [200, 201]

    except Exception as e:
        log_erro("Erro enviar PDF:", e)
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
        venda_adicional = formatar_itens_adicionais_para_salvar(base.get("venda_adicional", ""))
        itens = formatar_itens_adicionais_para_salvar(base.get("itens", venda_adicional))

        if venda_adicional.strip().upper() == "NENHUM":
            venda_adicional = ""
        if itens.strip().upper() == "NENHUM":
            itens = ""

        atendimento = Atendimento(
            telefone=telefone,
            nome=nome,
            setor=setor,
            modelo=modelo,
            ano=ano,
            revisao=revisao,
            cpf=cpf,
            dia_semana=nome_dia(dia) if dia else "",
            data_agendada=data_agendada,
            horario=horario,
            itens=itens,
            venda_adicional=venda_adicional,
            origem=origem,
            status=normalizar_status(status),
            etapa=etapa,
            atendimento_humano=atendimento_humano,
            concluido=concluido,
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
    mensagem = (
        "Olá 👋\n\n"
        "🏍️ *Pós-Vendas Motoshow Yamaha*\n\n"
        "Escolha uma opção:\n\n"
        "1️⃣ Agendar Revisão\n"
        "2️⃣ Peças\n"
        "3️⃣ Acessórios\n"
        "4️⃣ Garantia\n"
        "5️⃣ Logista / Atacado\n"
        "6️⃣ Dúvidas\n"
        "7️⃣ Atendimento Humano\n\n"
        "Equipe Motoshow Yamaha"
    )
    enviar_mensagem(telefone, mensagem)


def iniciar_fluxo_pecas(telefone, texto_inicial=""):
    iniciar_cliente(telefone)
    clientes[telefone]["etapa"] = "pecas"

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Peças",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="pecas_iniciado",
        dados={"observacao": texto_inicial},
        atendimento_humano=False,
        concluido=False
    )

    if limpar_texto(texto_inicial):
        enviar_mensagem(
            telefone,
            "🔩 *Peças*\n\n"
            "Perfeito, recebi sua solicitação.\n"
            "Nossa equipe vai verificar *valor* e *disponibilidade*.\n\n"
            "Se quiser complementar, envie:\n"
            "• modelo da moto\n"
            "• ano\n"
            "• peça desejada"
        )
    else:
        enviar_mensagem(telefone, "🔩 *Peças*\n\nInforme a peça desejada:")


def iniciar_fluxo_acessorios(telefone, texto_inicial=""):
    iniciar_cliente(telefone)
    clientes[telefone]["etapa"] = "acessorios"

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Acessórios",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="acessorios_iniciado",
        atendimento_humano=False,
        concluido=False
    )

    if limpar_texto(texto_inicial):
        enviar_mensagem(
            telefone,
            "🛵 *Acessórios*\n\n"
            "Perfeito, recebi sua solicitação.\n"
            "Envie mais detalhes do acessório desejado, se quiser."
        )
    else:
        enviar_mensagem(telefone, "🛵 *Acessórios*\n\nInforme o acessório desejado:")


def menu_duvidas():
    return (
        "📘 *Central de Dúvidas*\n\n"
        "Escolha uma opção:\n\n"
        "1️⃣ Dúvidas sobre Revisões\n"
        "2️⃣ Dúvidas sobre Garantia\n"
        "3️⃣ Voltar ao menu principal"
    )


def montar_mensagem_horarios(lista):
    msg = "⏰ *Escolha o horário disponível:*\n\n"
    for i, h in enumerate(lista, start=1):
        msg += f"{i} - {h}\n"
    return msg


def montar_mensagem_venda_adicional():
    return (
        "🛒 *Deseja adicionar algum item?*\n\n"
        "Sugestões:\n"
        "• Filtro de ar\n"
        "• Pastilha de freio\n"
        "• Slider\n"
        "• Protetor de motor\n\n"
        "Digite o item desejado.\n"
        "Se não quiser adicionar nada, digite *2*."
    )


def montar_resumo_confirmacao(telefone):
    dados = clientes.get(telefone, {})

    itens = dados.get("venda_adicional") or "Nenhum"
    observacao = dados.get("observacao") or "Nenhuma"
    tipo_atendimento = dados.get("tipo_atendimento") or "Não informado"

    return (
        "📋 *Confirmação do Agendamento*\n\n"
        f"👤 *Nome:* {dados.get('nome', '-')}\n"
        f"📄 *CPF:* {dados.get('cpf', '-')}\n"
        f"🏍️ *Modelo:* {dados.get('modelo', '-')}\n"
        f"📅 *Ano:* {dados.get('ano', '-')}\n"
        f"🔧 *Revisão:* {dados.get('revisao', '-')}ª\n"
        f"📍 *Dia:* {dados.get('dia_texto', '-')}\n"
        f"📆 *Data:* {dados.get('data', '-')}\n"
        f"⏰ *Horário:* {dados.get('horario', '-')}\n"
        f"🚶 *Atendimento:* {tipo_atendimento}\n"
        f"🛒 *Adicionais:* {itens}\n"
        f"📝 *Observação:* {observacao}\n\n"
        "Digite:\n"
        "*1* para confirmar\n"
        "*2* para corrigir"
    )


def mensagem_por_etapa_revisao(telefone, etapa):
    iniciar_cliente(telefone)
    dados = clientes[telefone]

    if etapa == "revisao_modelo":
        return "🔧 *Agendamento de Revisão*\n\nInforme o *modelo da moto*:"

    if etapa == "revisao_nome":
        resumo = f"🏍️ Modelo: {dados['modelo']}\n\n" if dados.get("modelo") else ""
        return f"{resumo}👤 Informe seu *nome completo*:"

    if etapa == "revisao_cpf":
        return "📄 Informe seu *CPF com 11 números*:"

    if etapa == "revisao_ano":
        return "📅 Informe o *ano da moto*:"

    if etapa == "revisao_km":
        return "🔢 Informe a *quilometragem atual* da moto:"

    if etapa == "revisao_tipo":
        return (
            "🛠️ *Qual revisão deseja agendar?*\n\n"
            "1 - 1ª Revisão\n"
            "2 - 2ª Revisão\n"
            "3 - 3ª Revisão\n"
            "4 - 4ª Revisão\n"
            "5 - 5ª Revisão ou acima"
        )

    if etapa == "revisao_dia":
        return (
            "📅 *Escolha o dia desejado:*\n\n"
            "1 - Segunda\n"
            "2 - Terça\n"
            "3 - Quarta\n"
            "4 - Quinta\n"
            "5 - Sexta\n"
            "6 - Sábado"
        )

    if etapa == "revisao_data":
        return "📆 Informe a *data desejada* no formato *dd/mm/aaaa*:"

    if etapa == "revisao_tipo_atendimento":
        return (
            "🏢 Como será o atendimento?\n\n"
            "1 - Vou aguardar na concessionária\n"
            "2 - Vou deixar a moto e retirar depois"
        )

    if etapa == "revisao_venda":
        return montar_mensagem_venda_adicional()

    if etapa == "revisao_observacao":
        return (
            "📝 Deseja adicionar alguma observação?\n\n"
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
        return resposta

    except Exception as e:
        log_erro("Erro ao classificar intenção:", e)
        return resposta_ia_vazia()


def aplicar_dados_ia_no_cliente(telefone, dados_extraidos):
    if not dados_extraidos:
        return

    iniciar_cliente(telefone)
    dados = clientes[telefone]

    modelo = limpar_texto(dados_extraidos.get("modelo"))
    nome = limpar_texto(dados_extraidos.get("nome"))
    cpf = limpar_cpf(dados_extraidos.get("cpf"))
    ano = limpar_texto(dados_extraidos.get("ano"))
    revisao = normalizar_revisao_para_fluxo(dados_extraidos.get("revisao"))
    km_atual = limpar_texto(
        dados_extraidos.get("km_atual") or dados_extraidos.get("km") or ""
    )
    dia_texto = limpar_texto(dados_extraidos.get("dia"))
    horario = limpar_texto(dados_extraidos.get("horario"))
    data = limpar_texto(dados_extraidos.get("data"))
    item_adicional = formatar_itens_adicionais_para_salvar(dados_extraidos.get("item_adicional", ""))
    observacao = limpar_texto(dados_extraidos.get("observacao"))
    tipo_atendimento = limpar_texto(dados_extraidos.get("tipo_atendimento"))

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

    if data and not dados.get("data"):
        dados["data"] = data

    if horario and not dados.get("horario"):
        dados["horario"] = horario

    if item_adicional and not dados.get("venda_adicional"):
        dados["itens"] = item_adicional
        dados["venda_adicional"] = item_adicional

    if observacao and not dados.get("observacao"):
        dados["observacao"] = observacao

    if tipo_atendimento and not dados.get("tipo_atendimento"):
        dados["tipo_atendimento"] = tipo_atendimento


def mensagem_duvida_retorno_fluxo(telefone):
    iniciar_cliente(telefone)
    etapa_retorno = clientes[telefone].get("etapa_retorno_duvida", "")

    if etapa_retorno and etapa_retorno.startswith("revisao"):
        return (
            "Se desejar, você pode:\n\n"
            "1️⃣ Continuar agendamento\n"
            "2️⃣ Fazer outra dúvida\n"
            "3️⃣ Falar com atendente"
        )

    return (
        "Se desejar, você pode:\n\n"
        "1️⃣ Fazer outra dúvida\n"
        "2️⃣ Voltar ao menu principal\n"
        "3️⃣ Falar com atendente"
    )


def encaminhar_para_menu_duvidas(telefone, etapa_atual=""):
    iniciar_cliente(telefone)
    clientes[telefone]["etapa_retorno_duvida"] = etapa_atual or clientes[telefone].get("etapa", "")
    clientes[telefone]["origem_etapa"] = etapa_atual or clientes[telefone].get("etapa", "")
    clientes[telefone]["etapa"] = "menu_duvidas"

    enviar_mensagem(
        telefone,
        "📘 Percebi que você enviou uma dúvida.\n\n"
        "Vou te direcionar para a central de dúvidas:"
    )
    enviar_mensagem(telefone, menu_duvidas())


def salvar_duvida_dashboard(telefone, categoria, pergunta, resposta):
    setor = f"Dúvidas {categoria.title()}"

    return salvar_evento_atendimento(
        telefone=telefone,
        setor=setor,
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="duvida_respondida",
        atendimento_humano=False,
        concluido=False
    )


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
    etapa = primeira_etapa_pendente_revisao(telefone)
    clientes[telefone]["etapa"] = etapa

    if etapa == "revisao_horario":
        revisao = clientes[telefone]["revisao"]
        dia = clientes[telefone]["dia"]

        horarios = horarios_por_revisao(revisao, dia)

        if not horarios:
            clientes[telefone]["etapa"] = "revisao_dia"
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
            AgendamentoRevisao.data_agendada == data,
            AgendamentoRevisao.horario == horario,
            AgendamentoRevisao.status == STATUS_AGENDADO
        ).count()

        return quantidade < limite

    except Exception as e:
        log_erro("Erro capacidade:", e)
        return True

    finally:
        db.close()


def horarios_por_revisao(revisao, dia):
    try:
        revisao = int(revisao)
    except Exception:
        revisao = 1

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
            telefone=telefone,
            nome=dados["nome"],
            cpf=dados["cpf"],
            modelo=dados["modelo"],
            ano=dados["ano"],
            revisao=dados["revisao"],
            dia_semana=nome_dia(dados["dia"]),
            data_agendada=dados["data"],
            horario=dados["horario"],
            itens=itens_formatados,
            venda_adicional=venda_formatada,
            status=STATUS_AGENDADO,
            observacoes=dados.get("observacao", ""),
            origem="BOT",
            sances_status=SANCES_STATUS_PENDENTE,
            sances_enviado=False,
            sances_protocolo="",
            sances_erro="",
            sances_data_envio=None
        )

        db.add(agendamento)
        db.commit()

        log_info("Agendamento salvo:", protocolo)
        return protocolo

    except Exception as e:
        db.rollback()
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
        agendamento = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.cpf == cpf,
            AgendamentoRevisao.status == STATUS_AGENDADO
        ).first()

        return agendamento

    except Exception as e:
        log_erro("Erro buscar agendamento:", e)
        return None

    finally:
        db.close()


def buscar_agendamento_por_cpf(cpf):
    return buscar_agendamento_ativo(cpf)


def cancelar_agendamento(cpf, novo_status=STATUS_CANCELADO):
    db = SessionLocal()

    try:
        agendamento = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.cpf == cpf,
            AgendamentoRevisao.status == STATUS_AGENDADO
        ).first()

        if not agendamento:
            return None

        agendamento.status = normalizar_status(novo_status)

        dados = {
            "protocolo": str(agendamento.protocolo or ""),
            "telefone": str(agendamento.telefone or ""),
            "nome": str(agendamento.nome or ""),
            "cpf": str(agendamento.cpf or ""),
            "modelo": str(agendamento.modelo or ""),
            "ano": str(agendamento.ano or ""),
            "revisao": str(agendamento.revisao or ""),
            "data_agendada": str(agendamento.data_agendada or ""),
            "horario": str(agendamento.horario or ""),
            "itens": str(agendamento.itens or ""),
            "venda_adicional": str(agendamento.venda_adicional or ""),
            "status": str(agendamento.status or ""),
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
            "nome": ag.nome,
            "modelo": ag.modelo,
            "ano": ag.ano,
            "revisao": ag.revisao,
            "cpf": ag.cpf,
            "data": ag.data_agendada,
            "horario": ag.horario,
            "itens": ag.itens,
            "venda_adicional": ag.venda_adicional
        },
        atendimento_humano=False,
        concluido=False
    )

    enviar_mensagem(
        telefone,
        "📋 *Agendamento localizado*\n\n"
        f"👤 {ag.nome}\n"
        f"🏍️ {ag.modelo}\n"
        f"📅 {ag.data_agendada}\n"
        f"⏰ {ag.horario}\n"
        f"📌 Protocolo: {ag.protocolo}\n\n"
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
            "nome": ag.nome,
            "modelo": ag.modelo,
            "ano": ag.ano,
            "revisao": ag.revisao,
            "cpf": ag.cpf,
            "data": ag.data_agendada,
            "horario": ag.horario,
            "itens": ag.itens,
            "venda_adicional": ag.venda_adicional
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

    cancelar_agendamento(clientes[telefone]["cpf"], novo_status=STATUS_REAGENDADO)
    definir_status_cliente(telefone, STATUS_REAGENDADO)

    clientes[telefone]["etapa"] = "revisao_dia"

    enviar_mensagem(
        telefone,
        "🔄 *Reagendamento iniciado*\n\n"
        f"👤 {clientes[telefone]['nome']}\n"
        f"🏍️ {clientes[telefone]['modelo']}\n"
        f"🛠️ Revisão: {clientes[telefone]['revisao']}ª\n\n"
        "Escolha o novo dia:"
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

        for idx in df.index:
            tel_planilha = limpar_telefone(df.at[idx, coluna_telefone])
            if tel_planilha == telefone_limpo:
                df.at[idx, coluna_retorno] = limpar_texto(texto)
                df.at[idx, coluna_data_retorno] = formatar_data_hora()
                break

        df.to_excel(ARQUIVO_FOLLOWUP, index=False)

    except Exception as e:
        log_erro("Erro ao atualizar retorno na planilha:", e)


def processar_lembretes_agendamento():
    db = SessionLocal()

    try:
        hoje = datetime.now().date()

        agendamentos = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.status == STATUS_AGENDADO,
            AgendamentoRevisao.lembrete_enviado == False
        ).all()

        for ag in agendamentos:
            try:
                data_agendada = datetime.strptime(ag.data_agendada, "%d/%m/%Y").date()
                diferenca = (data_agendada - hoje).days

                if diferenca == 1:
                    mensagem = (
                        "🔔 *Lembrete de Revisão*\n\n"
                        f"Olá *{ag.nome}*\n\n"
                        f"📅 Data: {ag.data_agendada}\n"
                        f"⏰ Horário: {ag.horario}\n"
                        f"🏍️ Modelo: {ag.modelo}\n\n"
                        f"📌 Protocolo: {ag.protocolo}\n\n"
                        "Equipe Motoshow Yamaha"
                    )

                    enviar_mensagem(ag.telefone, mensagem)
                    ag.lembrete_enviado = True

            except Exception as e:
                log_erro("Erro lembrete individual:", e)

        db.commit()

    except Exception as e:
        log_erro("Erro geral lembrete:", e)

    finally:
        db.close()


# ==========================================
# WORKER
# ==========================================
def worker():
    while True:
        try:
            processar_inatividade()
            processar_lembretes_agendamento()
        except Exception as e:
            log_erro("Worker erro:", e)

        time.sleep(30)


def iniciar_worker():
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


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
            total=total,
            revisao=revisao,
            total_revisoes=total_revisoes,
            total_duvidas=total_duvidas,
            total_duvidas_revisoes=total_duvidas_revisoes,
            total_duvidas_garantia=total_duvidas_garantia,
            agendados=agendados,
            cancelados=cancelados,
            reagendados=reagendados,
            concluidos=concluidos,
            atendimento_humano=atendimento_humano,
            duvidas_ia=duvidas_ia,
            total_agendamentos_periodo=total_agendamentos_periodo,
            primeira=primeira,
            segunda=segunda,
            terceira=terceira,
            quarta=quarta,
            quinta=quinta,
            total_itens_vendidos=total_itens_vendidos,
            ranking_itens=ranking_itens,
            agendamentos=agendamentos,
            sances_pendentes=sances_pendentes,
            sances_enviados=sances_enviados,
            sances_erros=sances_erros,
            sances_nao_configurado=sances_nao_configurado,
        )

    except Exception as e:
        log_erro("Dashboard erro:", e)
        return "Erro dashboard", 500

    finally:
        db.close()


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
    if mensagem_ja_processada(message_id):
        return jsonify({"status": "ignorado", "motivo": "duplicado"}), 200

    telefone = extrair_telefone(payload)
    texto = extrair_texto(payload)

    if not telefone:
        return jsonify({"status": "ignorado", "motivo": "sem telefone"}), 200

    if telefone_eh_grupo(telefone):
        return jsonify({"status": "ignorado", "motivo": "grupo"}), 200

    telefone = limpar_telefone(telefone)
    texto = limpar_texto(texto)
    texto_normalizado = normalizar_texto(texto)
    texto_opcao = limpar_opcao(texto)

    registrar_mensagem_processada(message_id)

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)
    atualizar_retorno_na_planilha(telefone, texto)

    resposta_ia = obter_dados_extraidos_ia(texto)
    intencao_ia = resposta_ia.get("intencao", "")
    dados_extraidos_ia = resposta_ia.get("dados_extraidos", {}) or {}

    if texto_normalizado in ["menu", "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]:
        resetar_cliente(telefone)
        enviar_menu(telefone)
        return jsonify({"status": "ok"}), 200

    etapa = clientes[telefone]["etapa"]

    # ==========================================
    # INTENÇÕES GERAIS
    # ==========================================
    if intencao_ia in ["humano", "falar_humano", "atendimento_humano"] and not etapa.startswith("revisao"):
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
            definir_status_cliente(telefone, STATUS_AGENDAMENTO_INICIADO)
            proxima = iniciar_fluxo_revisao_por_intencao(telefone, {})
            enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, proxima))
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "2":
            iniciar_fluxo_pecas(telefone)
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "3":
            iniciar_fluxo_acessorios(telefone)
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "4":
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
            clientes[telefone]["etapa"] = "menu_duvidas"
            enviar_mensagem(telefone, menu_duvidas())
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "7":
            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "agendar_revisao":
            definir_status_cliente(telefone, STATUS_AGENDAMENTO_INICIADO)
            proxima = iniciar_fluxo_revisao_por_intencao(telefone, dados_extraidos_ia)
            enviar_mensagem(telefone, "Perfeito 👍 Vou seguir com seu agendamento de revisão.")
            if proxima == "revisao_horario":
                enviar_proxima_etapa_revisao(telefone)
            else:
                enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, proxima))
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "pecas":
            iniciar_fluxo_pecas(telefone, texto)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "acessorios":
            iniciar_fluxo_acessorios(telefone, texto)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "duvidas":
            clientes[telefone]["etapa"] = "menu_duvidas"
            enviar_mensagem(telefone, menu_duvidas())
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "garantia":
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
                "Envie sua dúvida em texto livre.\n\n"
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
                "Envie sua dúvida em texto livre.\n\n"
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

        if intencao_ia == "duvidas" and etapa_revisao_permite_ir_para_duvidas(etapa):
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

            if revisao not in ["1", "2", "3", "4", "5"]:
                enviar_mensagem(telefone, "⚠️ Opção inválida. Digite de 1 a 5.")
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

                retorno_sances = enviar_agendamento_para_sances(dados)

                clientes[telefone]["sances_status"] = retorno_sances.get("status", SANCES_STATUS_ERRO)
                clientes[telefone]["sances_protocolo"] = retorno_sances.get("protocolo_sances", "")
                clientes[telefone]["sances_erro"] = retorno_sances.get("erro", "")
                clientes[telefone]["sances_data_envio"] = formatar_data_hora()
                clientes[telefone]["sances_enviado"] = bool(retorno_sances.get("sucesso"))

                atualizar_status_sances_agendamento(protocolo, retorno_sances)

                definir_status_cliente(telefone, STATUS_AGENDADO)
                salvar_atendimento_dashboard(telefone, dados)

                mensagem_sances = montar_mensagem_status_sances(retorno_sances)

                enviar_mensagem(
                    telefone,
                    "✅ *Agendamento Confirmado*\n\n"
                    f"👤 {dados['nome']}\n"
                    f"🏍️ {dados['modelo']}\n"
                    f"📅 {dados['data']}\n"
                    f"⏰ {dados['horario']}\n"
                    f"📌 Protocolo: {protocolo}"
                    f"{mensagem_sances}\n\n"
                    "Lembrando de trazer o manual no momento da revisão para facilitar o atendimento.\n\n"
                    "Obrigado por escolher a Motoshow Yamaha 🏍️\n"
                    "Equipe Motoshow Yamaha"
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
            "✅ Solicitação de peças registrada.\nNossa equipe dará continuidade."
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
            "✅ Solicitação registrada.\nNossa equipe dará continuidade."
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
                "✅ Solicitação registrada.\nNossa equipe dará continuidade."
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