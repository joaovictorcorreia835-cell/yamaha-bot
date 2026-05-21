# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify, send_from_directory, send_file, render_template, redirect

import requests
import os
import time
import re
import threading
import uuid
import json
import io

from datetime import datetime, timedelta
from collections import Counter, deque

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import or_

load_dotenv()

from database import criar_banco, SessionLocal, Atendimento, AgendamentoRevisao, LeadAtacado, TarefaRPA, RPAFila
from ia_intencao import classificar_intencao, responder_duvida_por_tabela

try:
    from ferramentas_ia import responder_ia
except Exception as e:
    responder_ia = None
    print("[ERRO] Não foi possível importar ferramentas_ia:", repr(e), flush=True)

try:
    from ia_comercial import (
        gerar_resposta_comercial,
        classificar_temperatura_lead,
        gerar_mensagem_followup,
        gerar_mensagem_recuperacao,
        gerar_mensagem_venda_adicional,
        gerar_mensagem_atacado,
        classificar_parceiro_atacado,
        recomendar_produtos_atacado,
    )
except Exception as e:
    gerar_resposta_comercial = None
    classificar_temperatura_lead = None
    gerar_mensagem_followup = None
    gerar_mensagem_recuperacao = None
    gerar_mensagem_venda_adicional = None
    gerar_mensagem_atacado = None
    classificar_parceiro_atacado = None
    recomendar_produtos_atacado = None
    print("[ERRO] Não foi possível importar ia_comercial:", repr(e), flush=True)

try:
    from ia_duvidas import responder_duvida_manual, responder_duvida_manual_com_ia
except Exception as e:
    responder_duvida_manual = None
    responder_duvida_manual_com_ia = None
    print("[ERRO] Não foi possível importar ia_duvidas:", repr(e), flush=True)


# ==========================================
# APP FLASK
# ==========================================
app = Flask(__name__)

try:
    criar_banco()
    print("[INFO] Banco verificado/criado com sucesso.", flush=True)
except Exception as e:
    print("[ERRO] Erro ao criar/verificar banco:", repr(e), flush=True)


# ==========================================
# ESTADO EM MEMÓRIA DOS CLIENTES
# ==========================================
clientes = {}


# ==========================================
# LOCKS / WORKERS
# ==========================================
followup_lock = threading.Lock()
worker_followup_iniciado = False
worker_sances_iniciado = False


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

ZAPI_BASE = (
    f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}"
    f"/token/{ZAPI_TOKEN}"
)

URL_ZAPI_SEND_TEXT = f"{ZAPI_BASE}/send-text"
URL_ZAPI_SEND_DOCUMENT = f"{ZAPI_BASE}/send-document/pdf"
URL_ZAPI_SEND_BUTTON_LIST = f"{ZAPI_BASE}/send-button-list"

PDF_CATALOGO_ATACADO = os.getenv(
    "PDF_CATALOGO_ATACADO",
    "catalogo_atacado.pdf"
).strip()

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
    "fz 15": "acessorios_fz15.pdf",
    "f z 15": "acessorios_fz15.pdf",
    "fazer 150": "acessorios_fz15.pdf",

    "fz25": "acessorios_fz25.pdf",
    "fz 25": "acessorios_fz25.pdf",
    "f z 25": "acessorios_fz25.pdf",
    "fazer 250": "acessorios_fz25.pdf",
    "fazer250": "acessorios_fz25.pdf",
    "fazer 25": "acessorios_fz25.pdf",
    "fazer": "acessorios_fz25.pdf",

    "crosser": "acessorios_crosser.pdf",
    "xtz crosser": "acessorios_crosser.pdf",
    "xtz 150": "acessorios_crosser.pdf",

    "lander": "acessorios_lander.pdf",
    "lander 250": "acessorios_lander.pdf",
    "xtz lander": "acessorios_lander.pdf",
    "xtz 250": "acessorios_lander.pdf",

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
# ==========================================
SANCES_TIMEOUT = env_int("SANCES_TIMEOUT", 15)
SANCES_RETRY_MAX = env_int("SANCES_RETRY_MAX", 3)
SANCES_URL = os.getenv(
    "SANCES_URL",
    "https://api.sancesturbo.com.br/integracao/oficina/agendar"
).strip()
SANCES_API_URL = os.getenv(
    "SANCES_API_URL",
    SANCES_URL
).strip() or SANCES_URL
SANCES_CLIENTES_URL = os.getenv(
    "SANCES_CLIENTES_URL",
    "https://api.sancesturbo.com.br/integracao/cadastros/clientes"
).strip()
SANCES_VEICULOS_URL = os.getenv(
    "SANCES_VEICULOS_URL",
    "https://api.sancesturbo.com.br/integracao/veiculos"
).strip()
SANCES_ESTOQUE_URL = os.getenv(
    "SANCES_ESTOQUE_URL",
    "https://api.sancesturbo.com.br/integracao/estoque"
).strip()
SANCES_POS_VENDA_URL = os.getenv(
    "SANCES_POS_VENDA_URL",
    "https://api.sancesturbo.com.br/integracao/posVenda"
).strip()
SANCES_NEGOCIACAO_URL = os.getenv(
    "SANCES_NEGOCIACAO_URL",
    "https://api.sancesturbo.com.br/integracao/veiculos/getNegociacao"
).strip()
SANCES_GET_VENDAS_URL = os.getenv(
    "SANCES_GET_VENDAS_URL",
    "https://api.sancesturbo.com.br/integracao/vendas"
).strip()
SANCES_TOKEN = os.getenv("SANCES_TOKEN", "").strip()
SANCES_EMPRESA = env_int("SANCES_EMPRESA", 1)
SANCES_LIMIT = env_int("SANCES_LIMIT", 20)
SANCES_OFFSET = env_int("SANCES_OFFSET", 4)
SANCES_ESTOQUE_LIMIT = env_int("SANCES_ESTOQUE_LIMIT", 20)
SANCES_ESTOQUE_OFFSET = env_int("SANCES_ESTOQUE_OFFSET", 0)
SANCES_ESTOQUE_ATIVO = env_int("SANCES_ESTOQUE_ATIVO", 1)


# ==========================================
# CONFIG FUTURA RPA / AUTOMAÇÃO SEGURA
# ==========================================
RPA_MODO = os.getenv("RPA_MODO", "mock").strip().lower()
RPA_RETRY_MAX = env_int("RPA_RETRY_MAX", 3)
RPA_LOTE_MAX = env_int("RPA_LOTE_MAX", 10)


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
SANCES_STATUS_PENDENTE_DADOS = "PENDENTE_DADOS"


# ==========================================
# STATUS AUTOMAÇÃO RPA
# ==========================================
RPA_PENDENTE = "PENDENTE"
RPA_EM_EXECUCAO = "PROCESSANDO"
RPA_CONCLUIDO = "CONCLUIDO"
RPA_ERRO = "ERRO"
RPA_CANCELADO = "CANCELADO"
RPA_AGUARDANDO_HUMANO = RPA_CANCELADO

RPA_TIPOS_PREPARADOS = {
    "followup_revisao",
    "cobranca_orcamento",
    "envio_catalogo",
    "recuperacao_cliente",
    "lembrete_agendamento",
    "consulta_sances",
    "envio_pecas",
    "disparo_atacado",
    "consultar_disponibilidade_peca",
    "registrar_solicitacao_orcamento",
    "registrar_pos_venda",
    "atualizar_status_crm",
    "gerar_tarefa_consultor",
    "cotacao_atacado",
    "analise_garantia",
    "confirmacao_revisao",
}


INTENCOES_PRIORITARIAS = {
    "garantia",
    "consultar_garantia",
    "acompanhar_garantia",
    "status_os",
    "acompanhar_os",
    "atendimento_humano",
    "humano",
    "menu",
    "cancelar",
    "cancelar_agendamento",
    "cancelar_revisao",
}


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
# SANCES - CONSULTA DE AGENDAMENTOS
# ==========================================
def consultar_agendamentos_sances(
    data_inicial,
    data_final,
    codigo_situacao=None,
    placa=None,
    cpf_cliente=None,
):
    try:
        data_inicial = limpar_texto(data_inicial)
        data_final = limpar_texto(data_final)

        if not data_inicial or not data_final:
            return {
                "sucesso": False,
                "mensagem": "Informe data inicial e data final.",
                "dados": [],
                "erro": "Parâmetros obrigatórios ausentes",
            }

        if not SANCES_API_URL:
            return {
                "sucesso": False,
                "mensagem": "API Sances não configurada.",
                "dados": [],
                "erro": "SANCES_API_URL não configurada",
            }

        if not SANCES_TOKEN:
            return {
                "sucesso": False,
                "mensagem": "Token Sances não configurado.",
                "dados": [],
                "erro": "SANCES_TOKEN não configurado",
            }

        params = {
            "data_agendamento_inicial": data_inicial,
            "data_agendamento_final": data_final,
            "limit": 100,
            "offset": 0,
        }

        if codigo_situacao:
            params["codigo_situacao"] = limpar_texto(codigo_situacao)

        if placa:
            params["placa_veiculo"] = limpar_texto(placa).upper()

        if cpf_cliente:
            params["cpf_cnpj_cliente"] = limpar_texto(cpf_cliente)

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }

        log_info("[SANCES] Consulta de agendamentos iniciada:", params)

        response = requests.get(
            SANCES_API_URL,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        sucesso = 200 <= response.status_code < 300

        if isinstance(retorno_json, list):
            dados = retorno_json
            mensagem = ""
            erro = ""
        elif isinstance(retorno_json, dict):
            dados = (
                retorno_json.get("dados")
                or retorno_json.get("agendamentos")
                or retorno_json.get("data")
                or []
            )
            mensagem = limpar_texto(
                retorno_json.get("mensagem")
                or retorno_json.get("message")
                or ""
            )
            erro = limpar_texto(
                retorno_json.get("erro")
                or retorno_json.get("error")
                or ""
            )
        else:
            dados = []
            mensagem = ""
            erro = ""

        if not isinstance(dados, list):
            dados = [dados]

        if not sucesso and not erro:
            erro = f"HTTP {response.status_code}"

        resultado = {
            "sucesso": sucesso,
            "mensagem": mensagem,
            "dados": dados if sucesso else [],
            "erro": "" if sucesso else erro,
        }

        log_info("[SANCES] Consulta de agendamentos concluída:", resultado)
        return resultado

    except requests.Timeout:
        resultado = {
            "sucesso": False,
            "mensagem": "Timeout ao consultar agendamentos Sances.",
            "dados": [],
            "erro": f"Timeout Sances apos {SANCES_TIMEOUT}s",
        }
        log_erro("[SANCES] Timeout consulta agendamentos:", resultado)
        return resultado

    except Exception as e:
        resultado = {
            "sucesso": False,
            "mensagem": "Erro ao consultar agendamentos Sances.",
            "dados": [],
            "erro": repr(e),
        }
        log_erro("[SANCES] Erro consulta agendamentos:", repr(e))
        return resultado


@app.route("/sances/agendamentos", methods=["GET"])
def rota_consultar_agendamentos_sances():
    resultado = consultar_agendamentos_sances(
        data_inicial=request.args.get("inicio", ""),
        data_final=request.args.get("fim", ""),
        codigo_situacao=request.args.get("codigo_situacao"),
        placa=request.args.get("placa"),
        cpf_cliente=request.args.get("cpf_cliente"),
    )

    return jsonify(resultado)


@app.route("/sances/teste-agendamento", methods=["POST"])
def rota_teste_agendamento_sances():
    dados = request.get_json(silent=True) or {}

    if not dados:
        dados = {
            "data": request.form.get("data", ""),
            "horario": request.form.get("horario", ""),
            "nome": request.form.get("nome", ""),
            "telefone": request.form.get("telefone", ""),
            "modelo": request.form.get("modelo", ""),
            "km_atual": request.form.get("km_atual", ""),
            "observacao": request.form.get("observacao", ""),
            "revisao": request.form.get("revisao", ""),
            "placa": request.form.get("placa", ""),
            "chassi": request.form.get("chassi", ""),
        }

    resultado = enviar_agendamento_para_sances(dados)
    return jsonify(resultado)


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
    try:
        texto = str(telefone or "").lower()
        return "@g.us" in texto or texto.endswith("@g.us") or "g.us" in texto
    except Exception:
        return False


def limpar_opcao(texto):
    try:
        texto = str(texto or "").strip()

        mapa_emojis = {
            "1️⃣": "1",
            "2️⃣": "2",
            "3️⃣": "3",
            "4️⃣": "4",
            "5️⃣": "5",
            "6️⃣": "6",
            "7️⃣": "7",
            "8️⃣": "8",
            "9️⃣": "9",
            "0️⃣": "0",
        }

        for emoji, numero in mapa_emojis.items():
            texto = texto.replace(emoji, numero)

        texto = texto.replace("️⃣", "")
        texto = texto.replace("\u200e", "").replace("\u200f", "")
        texto = texto.replace("*", "").replace("_", "").strip()

        return texto

    except Exception:
        return ""


# ==========================================
# MENU INICIAL POR NUMERAÇÃO
# ==========================================
def menu_inicial():
    return """👋 Olá! Seja bem-vindo(a) à Motoshow Yamaha.

Como posso te ajudar hoje?

1️⃣ Agendar Revisão
2️⃣ Peças
3️⃣ Acessórios
4️⃣ Garantia
5️⃣ Logista / Atacado
6️⃣ Dúvidas
7️⃣ Atendimento Humano

Digite apenas o número da opção desejada."""


# ==========================================
# NORMALIZAR OPÇÕES DE MENU / BOTÕES
# ==========================================
def normalizar_opcao_menu(texto):
    try:
        texto_norm = normalizar_texto(texto)
        texto_norm = texto_norm.replace("-", "_")
        texto_norm = texto_norm.replace("/", "_")
        texto_norm = texto_norm.replace(" ", "_")
        texto_norm = texto_norm.upper()

        mapa = {
            "MENU": "MENU",
            "VOLTAR": "MENU",
            "VOLTAR_MENU": "MENU",
            "VOLTAR_AO_MENU": "MENU",
            "INICIO": "MENU",
            "COMECAR": "MENU",
            "COMEÇAR": "MENU",
            "REINICIAR": "MENU",

            "1": "OPCAO_1",
            "2": "OPCAO_2",
            "3": "OPCAO_3",
            "4": "OPCAO_4",
            "5": "OPCAO_5",
            "6": "OPCAO_6",
            "7": "OPCAO_7",

            "MENU_REVISAO": "OPCAO_1",
            "REVISAO": "OPCAO_1",
            "REVISÃO": "OPCAO_1",

            "MENU_PECAS": "OPCAO_2",
            "PECAS": "OPCAO_2",
            "PEÇAS": "OPCAO_2",

            "MENU_ACESSORIOS": "OPCAO_3",
            "ACESSORIOS": "OPCAO_3",
            "ACESSÓRIOS": "OPCAO_3",

            "MENU_GARANTIA": "OPCAO_4",
            "GARANTIA": "OPCAO_4",

            "MENU_ATACADO": "OPCAO_5",
            "ATACADO": "OPCAO_5",
            "LOGISTA": "OPCAO_5",
            "LOJISTA": "OPCAO_5",

            "MENU_DUVIDAS": "OPCAO_6",
            "DUVIDAS": "OPCAO_6",
            "DÚVIDAS": "OPCAO_6",

            "MENU_HUMANO": "OPCAO_7",
            "HUMANO": "OPCAO_7",
            "ATENDENTE": "OPCAO_7",
            "ATENDIMENTO_HUMANO": "OPCAO_7",

            "AGENDAR": "AGENDAR_REVISAO",
            "AGENDAR_REVISAO": "AGENDAR_REVISAO",
            "MARCAR_REVISAO": "AGENDAR_REVISAO",

            "FALAR_CONSULTOR": "FALAR_CONSULTOR",
            "FALAR_COM_CONSULTOR": "FALAR_CONSULTOR",
            "CONSULTOR": "FALAR_CONSULTOR",

            "DEPOIS": "DEPOIS",

            "ATACADO_TABELA": "ATACADO_TABELA",
            "QUERO_TABELA": "ATACADO_TABELA",
            "TABELA": "ATACADO_TABELA",
            "RECEBER_CATALOGO": "ATACADO_TABELA",
            "RECEBER_CATALOGO_DE_ATACADO": "ATACADO_TABELA",

            "ATACADO_CONSULTOR": "ATACADO_CONSULTOR",
            "CONSULTOR_ATACADO": "ATACADO_CONSULTOR",
            "ATACADO_DEPOIS": "ATACADO_DEPOIS",

            "TIPO_AGUARDAR": "TIPO_AGUARDAR",
            "AGUARDAR": "TIPO_AGUARDAR",
            "AGUARDAR_NA_CONCESSIONARIA": "TIPO_AGUARDAR",

            "TIPO_DEIXAR": "TIPO_DEIXAR",
            "DEIXAR": "TIPO_DEIXAR",
            "DEIXAR_A_MOTO": "TIPO_DEIXAR",
            "RETIRAR_DEPOIS": "TIPO_DEIXAR",

            "ADICIONAR_ITEM": "ADICIONAR_ITEM",
            "SIM_ADICIONAR": "ADICIONAR_ITEM",
            "SEM_ITEM": "SEM_ITEM",
            "NAO": "SEM_ITEM",
            "NÃO": "SEM_ITEM",

            "CONFIRMAR_AGENDAMENTO": "CONFIRMAR_AGENDAMENTO",
            "CONFIRMAR": "CONFIRMAR_AGENDAMENTO",
            "SIM_CONFIRMAR": "CONFIRMAR_AGENDAMENTO",

            "CORRIGIR_AGENDAMENTO": "CORRIGIR_AGENDAMENTO",
            "CORRIGIR": "CORRIGIR_AGENDAMENTO",

            # Central de dúvidas
            "DUVIDAS_REVISAO": "DUVIDAS_REVISAO",
            "DUVIDA_REVISAO": "DUVIDAS_REVISAO",
            "DUVIDAS_SOBRE_REVISAO": "DUVIDAS_REVISAO",
            "DUVIDAS_SOBRE_REVISOES": "DUVIDAS_REVISAO",
            "REVISOES": "DUVIDAS_REVISAO",

            "DUVIDAS_GARANTIA": "DUVIDAS_GARANTIA",
            "DUVIDA_GARANTIA": "DUVIDAS_GARANTIA",
            "DUVIDAS_SOBRE_GARANTIA": "DUVIDAS_GARANTIA",

            "MAIS_DUVIDAS": "MAIS_DUVIDAS",
            "TIRAR_MAIS_DUVIDAS": "MAIS_DUVIDAS",
        }

        return mapa.get(texto_norm, "")

    except Exception:
        return ""


def normalizar_botao_zapi(texto):
    return normalizar_opcao_menu(texto)


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
# IA COMERCIAL - FASE 1
# ==========================================
def etapa_bloqueia_ia_comercial(etapa):
    etapa = limpar_texto(etapa).lower()

    return etapa in [
        "revisao_modelo",
        "revisao_nome",
        "revisao_cpf",
        "revisao_escolher_veiculo",
        "revisao_placa_chassi",
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

        "duvidas_menu",
        "duvidas",
        "duvidas_revisao",
        "duvidas_garantia",
        "duvida_manual",
        "duvida_pos_resposta",
        "duvidas_retorno",

        "pecas",
        "acessorios",
        "garantia",
        "garantia_menu",
        "garantia_nova_nome",
        "garantia_nova_modelo",
        "garantia_nova_ano",
        "garantia_nova_km",
        "garantia_nova_descricao",
        "garantia_acompanhar_nome",
        "garantia_acompanhar_modelo",
        "garantia_acompanhar_cpf",
        "garantia_acompanhar_descricao",
        "garantia_consulta_cpf",
        "garantia_escolher_os",
        "atacado",
        "atacado_cotacao",
        "atacado_cotacao_itens",
        "atacado_cadastro",
        "atacado_empresa",
        "atacado_responsavel",
        "atacado_cidade",
        "atacado_cnpj",
        "atacado_telefone_comercial",
        "atacado_segmento",
        "atacado_produtos_interesse",
        "atacado_cadastro_empresa",
        "atacado_cadastro_responsavel",
        "atacado_cadastro_cidade",
        "atacado_cadastro_cnpj",
        "atacado_cadastro_telefone",
        "atacado_cadastro_segmento",
        "atacado_cadastro_produtos",
        "atacado_catalogo_enviado",
        "atacado_catalogo_erro",
        "atendimento_humano",
    ]


def atualizar_dados_ia_cliente(telefone, texto="", intencao="", resposta_ia=None):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            return

        iniciar_cliente(telefone)

        resposta_ia = resposta_ia or {}

        if classificar_temperatura_lead:
            temperatura = (
                resposta_ia.get("temperatura_lead")
                or classificar_temperatura_lead(texto, intencao)
            )
        else:
            temperatura = resposta_ia.get("temperatura_lead") or "MORNO"

        clientes[telefone]["temperatura_lead"] = temperatura
        clientes[telefone]["nivel_interesse"] = resposta_ia.get("nivel_interesse") or "MEDIO"
        clientes[telefone]["proxima_acao"] = resposta_ia.get("proxima_acao") or ""
        clientes[telefone]["produto_interesse"] = resposta_ia.get("produto_interesse") or ""
        clientes[telefone]["oportunidade_comercial"] = bool(resposta_ia.get("oportunidade_comercial", False))
        clientes[telefone]["status_comercial"] = resposta_ia.get("status_comercial") or ""
        clientes[telefone]["ultima_acao_ia"] = "IA_COMERCIAL"

    except Exception as e:
        log_erro("Erro atualizar_dados_ia_cliente:", repr(e))


def responder_com_ia_comercial(telefone, texto, intencao="", modelo=""):
    try:
        if not gerar_resposta_comercial:
            return False

        telefone = limpar_telefone(telefone)
        texto = limpar_texto(texto)

        if not telefone or not texto:
            return False

        iniciar_cliente(telefone)

        dados = clientes[telefone]
        memoria = dados.get("memoria_cliente", {}) or buscar_memoria_cliente(telefone)

        if dados.get("atendimento_humano"):
            return False

        if etapa_bloqueia_ia_comercial(dados.get("etapa", "")):
            return False

        nome = dados.get("nome", "") or memoria.get("nome", "")
        modelo = modelo or dados.get("modelo", "") or memoria.get("modelo", "")

        resposta_ia = gerar_resposta_comercial(
            texto=texto,
            modelo=modelo,
            intencao=intencao,
            nome=nome,
        )

        if not isinstance(resposta_ia, dict):
            return False

        atualizar_dados_ia_cliente(
            telefone=telefone,
            texto=texto,
            intencao=intencao,
            resposta_ia=resposta_ia,
        )

        clientes[telefone]["resposta_ia"] = limpar_texto(
            resposta_ia.get("resposta", "")
        )

        resposta = limpar_texto(resposta_ia.get("resposta", ""))

        if not resposta:
            return False

        enviar_mensagem(telefone, resposta)

        if resposta_ia.get("encaminhar_humano"):
            clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
            clientes[telefone]["atendimento_humano"] = True
            clientes[telefone]["etapa"] = "atendimento_humano"

        salvar_evento_atendimento(
            telefone=telefone,
            setor="IA_COMERCIAL",
            status=clientes[telefone].get("status_comercial") or "IA_COMERCIAL_RESPONDEU",
            etapa=dados.get("etapa", "menu"),
            dados=dados,
            atendimento_humano=bool(resposta_ia.get("encaminhar_humano")),
            concluido=False,
            origem=dados.get("origem", "BOT"),
            observacao=f"Interesse: {resposta_ia.get('interesse', '')}",
            intencao_ia=intencao,
        )

        if resposta_ia.get("encaminhar_humano"):
            ativar_atendimento_humano(telefone)

        return True

    except Exception as e:
        log_erro("Erro responder_com_ia_comercial:", repr(e))
        return False


def enviar_venda_adicional_ia(telefone):
    try:
        if not gerar_mensagem_venda_adicional:
            return False

        telefone = limpar_telefone(telefone)

        if not telefone:
            return False

        iniciar_cliente(telefone)

        dados = clientes[telefone]

        if dados.get("atendimento_humano"):
            return False

        mensagem = gerar_mensagem_venda_adicional(
            modelo=dados.get("modelo", ""),
            revisao=dados.get("revisao", ""),
            km_atual=dados.get("km_atual", ""),
        )

        if not mensagem:
            return False

        enviar_mensagem(
            telefone,
            mensagem + "\n\n1️⃣ Sim\n2️⃣ Não\n\nDigite apenas o número da opção desejada."
        )

        salvar_evento_atendimento(
            telefone=telefone,
            setor="VENDA_ADICIONAL_IA",
            status="VENDA_ADICIONAL_ENVIADA",
            etapa=dados.get("etapa", ""),
            dados=dados,
            atendimento_humano=False,
            concluido=False,
            origem=dados.get("origem", "BOT"),
            observacao=dados.get("modelo", ""),
        )

        return True

    except Exception as e:
        log_erro("Erro enviar_venda_adicional_ia:", repr(e))
        return False


def enviar_catalogo_atacado(telefone):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            return False

        iniciar_cliente(telefone)

        enviado = enviar_pdf(
            telefone,
            PDF_CATALOGO_ATACADO,
            "📎 Catálogo de atacado Motoshow Yamaha"
        )

        clientes[telefone]["etapa"] = "atacado_catalogo_enviado"
        clientes[telefone]["intencao_ia"] = "atacado"
        clientes[telefone]["proxima_acao"] = "ATACADO_COTACAO_ITENS"
        clientes[telefone]["proxima_acao_atacado"] = "AGUARDAR_LISTA_COTACAO"
        clientes[telefone]["catalogo_enviado"] = True
        clientes[telefone]["nivel_interesse_atacado"] = "PARCEIRO_MORNO"
        clientes[telefone]["nivel_interesse"] = "MEDIO"
        clientes[telefone]["temperatura_lead"] = "MORNO"
        clientes[telefone]["ultima_interacao"] = agora()

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Logista / Atacado",
            status="CATALOGO_ATACADO_ENVIADO" if enviado else "ERRO_ENVIO_CATALOGO_ATACADO",
            etapa="atacado_catalogo_enviado" if enviado else "atacado_catalogo_erro",
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=False,
            origem=clientes[telefone].get("origem", "Campanha Atacado"),
            observacao=PDF_CATALOGO_ATACADO,
            intencao_ia="atacado",
        )

        salvar_lead_atacado(
            telefone,
            status="CATALOGO_ENVIADO",
            mensagem="Catálogo de atacado enviado.",
        )

        if not enviado:
            enviar_mensagem(
                telefone,
                "⚠️ Não consegui enviar o catálogo agora, mas vamos continuar seu atendimento."
            )

        enviar_mensagem(
            telefone,
            "📎 Segue nosso catálogo de atacado.\n\n"
            "Você deseja cotação de alguma peça ou produto?\n"
            "Se sim, envie a lista dos itens por aqui. 😊"
        )

        clientes[telefone]["etapa"] = "atacado_catalogo_enviado"

        return enviado

    except Exception as e:
        log_erro("Erro enviar_catalogo_atacado:", repr(e))
        return False


def classificar_atacado_estado(telefone, mensagem=""):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return "PARCEIRO_FRIO"

    iniciar_cliente(telefone)
    dados = clientes.get(telefone, {})

    if classificar_parceiro_atacado:
        try:
            nivel = classificar_parceiro_atacado(dados, mensagem)
        except Exception as e:
            log_erro("Erro classificar parceiro atacado:", repr(e))
            nivel = ""
    else:
        nivel = ""

    if not nivel:
        texto_norm = normalizar_texto(mensagem)

        if dados.get("itens_cotacao") or "cotacao" in texto_norm or "orcamento" in texto_norm:
            nivel = "PARCEIRO_QUENTE"
        elif dados.get("empresa") or dados.get("cnpj"):
            nivel = "NOVO_PARCEIRO"
        elif dados.get("etapa") == "atacado_catalogo_enviado" or "catalogo" in texto_norm:
            nivel = "PARCEIRO_MORNO"
        else:
            nivel = "PARCEIRO_FRIO"

    clientes[telefone]["nivel_interesse_atacado"] = nivel
    clientes[telefone]["nivel_interesse"] = {
        "PARCEIRO_QUENTE": "ALTO",
        "PARCEIRO_MORNO": "MEDIO",
        "PARCEIRO_FRIO": "BAIXO",
        "NOVO_PARCEIRO": "MEDIO",
    }.get(nivel, clientes[telefone].get("nivel_interesse", "MEDIO"))
    clientes[telefone]["temperatura_lead"] = {
        "PARCEIRO_QUENTE": "QUENTE",
        "PARCEIRO_MORNO": "MORNO",
        "PARCEIRO_FRIO": "FRIO",
        "NOVO_PARCEIRO": "MORNO",
    }.get(nivel, clientes[telefone].get("temperatura_lead", "MORNO"))

    return nivel


def atualizar_recomendacoes_atacado(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return []

    iniciar_cliente(telefone)
    dados = clientes.get(telefone, {})
    historico = []

    memoria = dados.get("memoria_cliente", {}) or {}

    if memoria.get("pecas"):
        historico.extend(memoria.get("pecas", []))

    if memoria.get("acessorios"):
        historico.extend(memoria.get("acessorios", []))

    if recomendar_produtos_atacado:
        try:
            recomendacoes = recomendar_produtos_atacado(
                dados.get("segmento", ""),
                dados.get("produtos_interesse", "") or dados.get("itens_cotacao", ""),
                historico,
            )
        except Exception as e:
            log_erro("Erro recomendar produtos atacado:", repr(e))
            recomendacoes = []
    else:
        recomendacoes = []

    if not recomendacoes:
        recomendacoes = [
            "óleo Yamalube",
            "filtros",
            "kit relação",
            "pastilhas",
            "kits de revisão",
            "acessórios Yamaha",
        ]

    clientes[telefone]["recomendacoes_atacado"] = recomendacoes

    return recomendacoes


def mensagem_atacado_ia(tipo, telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return ""

    iniciar_cliente(telefone)
    dados = dict(clientes.get(telefone, {}))
    dados["historico"] = atualizar_recomendacoes_atacado(telefone)

    if gerar_mensagem_atacado:
        try:
            return limpar_texto(gerar_mensagem_atacado(tipo, dados))
        except Exception as e:
            log_erro("Erro gerar mensagem atacado:", repr(e))

    fallback = {
        "catalogo_enviado": (
            "📎 Segue nosso catálogo de atacado.\n\n"
            "Você deseja cotação de alguma peça ou produto?\n"
            "Se sim, envie a lista dos itens por aqui. 😊"
        ),
        "cotacao_recebida": (
            "Recebi sua lista de itens para cotação. Vou encaminhar para um consultor comercial "
            "priorizar seu atendimento. 🤝"
        ),
        "cadastro_parceiro": (
            "✅ Cadastro de parceiro recebido com sucesso.\n\n"
            "Nossa equipe comercial irá analisar seus dados e continuará o atendimento por aqui. 🤝"
        ),
        "followup_catalogo": (
            "Olá 😊 conseguiu verificar nosso catálogo de atacado? Se quiser, pode me enviar "
            "a lista de peças ou produtos que deseja cotar que nossa equipe comercial te ajuda."
        ),
        "followup_cotacao": (
            "Olá 😊 passando para confirmar se ainda deseja seguir com a cotação de atacado. "
            "Nossa equipe comercial pode continuar te ajudando por aqui."
        ),
    }

    return fallback.get(tipo, "")


def salvar_lead_atacado(telefone, status="NOVO", mensagem=""):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)
    dados = clientes.get(telefone, {})
    nivel = dados.get("nivel_interesse_atacado") or classificar_atacado_estado(telefone, mensagem)
    recomendacoes = atualizar_recomendacoes_atacado(telefone)
    agora_db = agora_datetime()
    db = SessionLocal()

    try:
        lead = (
            db.query(LeadAtacado)
            .filter(LeadAtacado.telefone == telefone)
            .order_by(LeadAtacado.id.desc())
            .first()
        )

        if not lead:
            lead = LeadAtacado(telefone=telefone)

        lead.empresa = limpar_texto(dados.get("empresa", ""))
        lead.responsavel = limpar_texto(dados.get("responsavel", "") or dados.get("nome", ""))
        lead.cidade = limpar_texto(dados.get("cidade", ""))
        lead.cnpj = limpar_texto(dados.get("cnpj", ""))
        lead.segmento = limpar_texto(dados.get("segmento", ""))
        lead.telefone_comercial = limpar_texto(dados.get("telefone_comercial", ""))
        lead.interesse = limpar_texto(
            dados.get("produtos_interesse", "")
            or dados.get("itens_cotacao", "")
            or dados.get("produto_interesse", "")
            or mensagem
        )
        lead.produtos_interesse = limpar_texto(dados.get("produtos_interesse", ""))
        lead.itens_cotacao = limpar_texto(dados.get("itens_cotacao", "") or dados.get("itens", ""))
        lead.status = limpar_texto(status or nivel or "NOVO")
        lead.origem = "atacado"
        lead.intencao_ia = "atacado"
        lead.nivel_interesse = limpar_texto(dados.get("nivel_interesse", ""))
        lead.nivel_interesse_atacado = nivel
        lead.proxima_acao = limpar_texto(dados.get("proxima_acao", ""))
        lead.proxima_acao_atacado = limpar_texto(dados.get("proxima_acao_atacado", ""))
        lead.catalogo_enviado = dados.get("etapa") == "atacado_catalogo_enviado" or bool(dados.get("catalogo_enviado"))

        if lead.catalogo_enviado and not getattr(lead, "data_catalogo_enviado", None):
            lead.data_catalogo_enviado = agora_db

        lead.observacoes = "\n".join([
            f"Classificação atacado: {nivel}",
            f"Recomendações: {', '.join(recomendacoes)}",
            f"Última mensagem: {limpar_texto(mensagem)}",
        ]).strip()
        lead.ultima_interacao = agora_db
        lead.data_ultimo_contato = agora_db

        db.add(lead)
        db.commit()

        log_info("Lead atacado salvo:", {"telefone": telefone, "nivel": nivel, "status": status})
        return True

    except Exception as e:
        db.rollback()
        log_erro("Erro salvar lead atacado:", repr(e))
        return False

    finally:
        db.close()


def menu_atacado():
    return (
        "📦 *Central Atacado Motoshow Yamaha*\n\n"
        "1️⃣ Solicitar Catálogo de Atacado\n"
        "2️⃣ Solicitar Cotação de Peças\n"
        "3️⃣ Cadastro de Novo Parceiro\n"
        "4️⃣ Falar com Consultor\n"
        "5️⃣ Voltar ao Menu Principal\n\n"
        "Digite apenas o número da opção desejada."
    )


def iniciar_fluxo_atacado(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)
    carregar_memoria_cliente_no_estado(telefone)

    clientes[telefone]["etapa"] = "atacado"
    clientes[telefone]["intencao_ia"] = "atacado"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["ultima_interacao"] = agora()
    clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO
    clientes[telefone]["itens_cotacao"] = ""
    clientes[telefone]["empresa"] = ""
    clientes[telefone]["responsavel"] = ""
    clientes[telefone]["cidade"] = ""
    clientes[telefone]["cnpj"] = ""
    clientes[telefone]["telefone_comercial"] = ""
    clientes[telefone]["segmento"] = ""
    clientes[telefone]["produtos_interesse"] = ""

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Logista / Atacado",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="atacado_iniciado",
        dados=clientes[telefone],
        atendimento_humano=False,
        concluido=False,
        origem=clientes[telefone].get("origem", "BOT"),
    )

    enviar_mensagem_memoria_cliente(telefone, "atacado")
    return enviar_mensagem(telefone, menu_atacado())


def finalizar_atacado_com_humano(telefone, etapa_evento, mensagem):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["etapa"] = "atendimento_humano"
    clientes[telefone]["ultima_interacao"] = agora()

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Logista / Atacado",
        status=STATUS_ATENDIMENTO_HUMANO,
        etapa=etapa_evento,
        dados=clientes[telefone],
        atendimento_humano=True,
        concluido=False,
        origem=clientes[telefone].get("origem", "BOT"),
    )

    if mensagem:
        enviar_mensagem(telefone, mensagem)

    return True


def mensagem_cotacao_atacado_recebida():
    return (
        "✅ Cotação recebida com sucesso.\n\n"
        "Nossa equipe comercial irá analisar os itens e continuará o atendimento por aqui. 🤝"
    )


def resumo_cadastro_atacado(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return ""

    iniciar_cliente(telefone)
    dados = clientes.get(telefone, {})

    return (
        "📋 *Resumo do Cadastro de Parceiro*\n\n"
        f"Empresa: {dados.get('empresa', '-') or '-'}\n"
        f"Responsável: {dados.get('responsavel', '-') or '-'}\n"
        f"Cidade: {dados.get('cidade', '-') or '-'}\n"
        f"CNPJ: {dados.get('cnpj', '-') or '-'}\n"
        f"Telefone comercial: {dados.get('telefone_comercial', '-') or '-'}\n"
        f"Segmento: {dados.get('segmento', '-') or '-'}\n"
        f"Produtos de interesse: {dados.get('produtos_interesse', '-') or '-'}\n\n"
        "✅ Cadastro de parceiro recebido com sucesso.\n\n"
        "Nossa equipe comercial irá analisar seus dados e continuará o atendimento por aqui. 🤝"
    )


def processar_fluxo_atacado(telefone, texto, texto_opcao=""):
    telefone = limpar_telefone(telefone)
    texto = limpar_texto(texto)
    texto_opcao = limpar_opcao(texto_opcao or texto)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    etapa = limpar_texto(clientes[telefone].get("etapa", "")).lower()
    clientes[telefone]["intencao_ia"] = "atacado"
    clientes[telefone]["ultima_interacao"] = agora()

    if etapa == "atacado":
        if texto_opcao == "1":
            classificar_atacado_estado(telefone, "catalogo")
            enviar_catalogo_atacado(telefone)
            return True

        if texto_opcao == "2":
            clientes[telefone]["etapa"] = "atacado_cotacao_itens"
            clientes[telefone]["proxima_acao_atacado"] = "AGUARDAR_LISTA_COTACAO"
            classificar_atacado_estado(telefone, "cotacao")
            salvar_lead_atacado(telefone, status="AGUARDANDO_COTACAO", mensagem=texto)
            enviar_mensagem(
                telefone,
                "Envie a lista das peças/produtos que deseja cotar."
            )
            return True

        if texto_opcao == "3":
            clientes[telefone]["etapa"] = "atacado_cadastro_empresa"
            clientes[telefone]["proxima_acao_atacado"] = "CONCLUIR_CADASTRO_PARCEIRO"
            clientes[telefone]["nivel_interesse_atacado"] = "NOVO_PARCEIRO"
            classificar_atacado_estado(telefone, "cadastro")
            salvar_lead_atacado(telefone, status="CADASTRO_INICIADO", mensagem=texto)
            enviar_mensagem(telefone, "Informe o *nome da empresa*.")
            return True

        if texto_opcao == "4":
            clientes[telefone]["nivel_interesse_atacado"] = "PARCEIRO_QUENTE"
            clientes[telefone]["proxima_acao_atacado"] = "CONSULTOR_COMERCIAL"
            salvar_lead_atacado(telefone, status="CONSULTOR_SOLICITADO", mensagem=texto)
            finalizar_atacado_com_humano(
                telefone=telefone,
                etapa_evento="atacado_consultor",
                mensagem=(
                    "Perfeito! Vou encaminhar seu atendimento para um consultor comercial.\n\n"
                    "Quando quiser voltar ao menu automático, envie *menu*."
                ),
            )
            return True

        if texto_opcao == "5":
            enviar_menu_principal(telefone)
            return True

        enviar_mensagem(telefone, menu_atacado())
        return True

    if etapa in ["atacado_catalogo_enviado", "atacado_cotacao", "atacado_cotacao_itens"]:
        if not texto:
            enviar_mensagem(
                telefone,
                "Envie a lista das peças/produtos que deseja cotar."
            )
            return True

        clientes[telefone]["itens_cotacao"] = texto
        clientes[telefone]["itens"] = texto
        clientes[telefone]["observacao"] = texto
        clientes[telefone]["produto_interesse"] = texto
        clientes[telefone]["oportunidade_comercial"] = True
        clientes[telefone]["nivel_interesse"] = "ALTO"
        clientes[telefone]["temperatura_lead"] = "QUENTE"
        clientes[telefone]["nivel_interesse_atacado"] = "PARCEIRO_QUENTE"
        clientes[telefone]["proxima_acao"] = "ENCAMINHAR_CONSULTOR"
        clientes[telefone]["proxima_acao_atacado"] = "PRIORIZAR_CONSULTOR_COMERCIAL"
        clientes[telefone]["status_comercial"] = "COTACAO_ATACADO"
        classificar_atacado_estado(telefone, texto)
        salvar_lead_atacado(telefone, status="COTACAO_RECEBIDA", mensagem=texto)

        finalizar_atacado_com_humano(
            telefone=telefone,
            etapa_evento="atacado_cotacao_itens",
            mensagem=mensagem_atacado_ia("cotacao_recebida", telefone) or mensagem_cotacao_atacado_recebida(),
        )
        return True

    if etapa == "atacado_catalogo_erro":
        clientes[telefone]["etapa"] = "atacado_cotacao_itens"
        return processar_fluxo_atacado(telefone, texto, texto_opcao)

    if etapa in ["atacado_cadastro", "atacado_empresa", "atacado_cadastro_empresa"]:
        clientes[telefone]["empresa"] = texto
        clientes[telefone]["nivel_interesse_atacado"] = "NOVO_PARCEIRO"
        clientes[telefone]["proxima_acao_atacado"] = "COLETAR_RESPONSAVEL"
        clientes[telefone]["etapa"] = "atacado_cadastro_responsavel"
        salvar_lead_atacado(telefone, status="CADASTRO_EM_ANDAMENTO", mensagem=texto)
        enviar_mensagem(telefone, "Informe o *nome do responsável*.")
        return True

    if etapa in ["atacado_responsavel", "atacado_cadastro_responsavel"]:
        clientes[telefone]["responsavel"] = texto
        clientes[telefone]["proxima_acao_atacado"] = "COLETAR_CIDADE"
        clientes[telefone]["etapa"] = "atacado_cadastro_cidade"
        salvar_lead_atacado(telefone, status="CADASTRO_EM_ANDAMENTO", mensagem=texto)
        enviar_mensagem(telefone, "Informe a *cidade*.")
        return True

    if etapa in ["atacado_cidade", "atacado_cadastro_cidade"]:
        clientes[telefone]["cidade"] = texto
        clientes[telefone]["proxima_acao_atacado"] = "COLETAR_CNPJ"
        clientes[telefone]["etapa"] = "atacado_cadastro_cnpj"
        salvar_lead_atacado(telefone, status="CADASTRO_EM_ANDAMENTO", mensagem=texto)
        enviar_mensagem(telefone, "Informe o *CNPJ*.")
        return True

    if etapa in ["atacado_cnpj", "atacado_cadastro_cnpj"]:
        clientes[telefone]["cnpj"] = texto
        clientes[telefone]["proxima_acao_atacado"] = "COLETAR_TELEFONE_COMERCIAL"
        clientes[telefone]["etapa"] = "atacado_cadastro_telefone"
        salvar_lead_atacado(telefone, status="CADASTRO_EM_ANDAMENTO", mensagem=texto)
        enviar_mensagem(telefone, "Informe o *telefone comercial*.")
        return True

    if etapa in ["atacado_telefone_comercial", "atacado_cadastro_telefone"]:
        clientes[telefone]["telefone_comercial"] = texto
        clientes[telefone]["proxima_acao_atacado"] = "COLETAR_SEGMENTO"
        clientes[telefone]["etapa"] = "atacado_cadastro_segmento"
        salvar_lead_atacado(telefone, status="CADASTRO_EM_ANDAMENTO", mensagem=texto)
        enviar_mensagem(telefone, "Informe o *segmento da empresa*.")
        return True

    if etapa in ["atacado_segmento", "atacado_cadastro_segmento"]:
        clientes[telefone]["segmento"] = texto
        atualizar_recomendacoes_atacado(telefone)
        clientes[telefone]["proxima_acao_atacado"] = "COLETAR_PRODUTOS_INTERESSE"
        clientes[telefone]["etapa"] = "atacado_cadastro_produtos"
        salvar_lead_atacado(telefone, status="CADASTRO_EM_ANDAMENTO", mensagem=texto)
        enviar_mensagem(
            telefone,
            "Quais produtos tem interesse em comprar no atacado?"
        )
        return True

    if etapa in ["atacado_produtos_interesse", "atacado_cadastro_produtos"]:
        clientes[telefone]["produtos_interesse"] = texto
        clientes[telefone]["observacao"] = texto
        clientes[telefone]["nivel_interesse_atacado"] = "NOVO_PARCEIRO"
        clientes[telefone]["proxima_acao_atacado"] = "ANALISAR_CADASTRO_PARCEIRO"
        atualizar_recomendacoes_atacado(telefone)
        salvar_lead_atacado(telefone, status="CADASTRO_RECEBIDO", mensagem=texto)

        finalizar_atacado_com_humano(
            telefone=telefone,
            etapa_evento="atacado_cadastro_parceiro",
            mensagem=resumo_cadastro_atacado(telefone),
        )
        return True

    return False


def processar_followups_inteligentes():
    try:
        if not gerar_mensagem_followup:
            return

        agora_time = time.time()

        for telefone, dados in list(clientes.items()):
            try:
                if dados.get("atendimento_humano"):
                    continue

                if etapa_bloqueia_ia_comercial(dados.get("etapa", "")):
                    continue

                status = dados.get("status", "")

                if status in [
                    STATUS_AGENDADO,
                    STATUS_CONFIRMADO,
                    STATUS_FINALIZADO,
                    STATUS_CANCELADO,
                    STATUS_ATENDIMENTO_HUMANO,
                ]:
                    continue

                ultima_interacao = dados.get("ultima_interacao") or agora_time
                tempo_parado = agora_time - float(ultima_interacao)
                followup_nivel = int(dados.get("followup_nivel", 0) or 0)

                modelo = dados.get("modelo", "")
                nome = dados.get("nome", "")

                if tempo_parado >= 1800 and followup_nivel < 1:
                    mensagem = gerar_mensagem_followup(
                        nivel=1,
                        modelo=modelo,
                        nome=nome,
                    )

                    enviar_mensagem(telefone, mensagem)

                    dados["followup_nivel"] = 1
                    dados["ultima_acao_ia"] = "FOLLOWUP_1"

                    salvar_evento_atendimento(
                        telefone=telefone,
                        setor="FOLLOWUP_IA",
                        status="FOLLOWUP_1_ENVIADO",
                        etapa=dados.get("etapa", ""),
                        dados=dados,
                        atendimento_humano=False,
                        concluido=False,
                        origem=dados.get("origem", "BOT"),
                        observacao="Cliente parado há 30 minutos",
                    )

                    continue

                if tempo_parado >= 86400 and followup_nivel < 2:
                    mensagem = gerar_mensagem_followup(
                        nivel=2,
                        modelo=modelo,
                        nome=nome,
                    )

                    enviar_mensagem(telefone, mensagem)

                    dados["followup_nivel"] = 2
                    dados["ultima_acao_ia"] = "FOLLOWUP_2"

                    salvar_evento_atendimento(
                        telefone=telefone,
                        setor="FOLLOWUP_IA",
                        status="FOLLOWUP_2_ENVIADO",
                        etapa=dados.get("etapa", ""),
                        dados=dados,
                        atendimento_humano=False,
                        concluido=False,
                        origem=dados.get("origem", "BOT"),
                        observacao="Cliente parado há 24 horas",
                    )

                    continue

                if tempo_parado >= 259200 and followup_nivel < 3:
                    mensagem = gerar_mensagem_followup(
                        nivel=3,
                        modelo=modelo,
                        nome=nome,
                    )

                    enviar_mensagem(telefone, mensagem)

                    dados["followup_nivel"] = 3
                    dados["ultima_acao_ia"] = "FOLLOWUP_3"

                    salvar_evento_atendimento(
                        telefone=telefone,
                        setor="FOLLOWUP_IA",
                        status="FOLLOWUP_3_ENVIADO",
                        etapa=dados.get("etapa", ""),
                        dados=dados,
                        atendimento_humano=False,
                        concluido=False,
                        origem=dados.get("origem", "BOT"),
                        observacao="Cliente parado há 3 dias",
                    )

            except Exception as e:
                log_erro("Erro follow-up IA cliente:", telefone, repr(e))

    except Exception as e:
        log_erro("Erro processar_followups_inteligentes:", repr(e))


def processar_recuperacao_clientes():
    db = SessionLocal()

    try:
        if not gerar_mensagem_recuperacao:
            return

        limite = datetime.now() - timedelta(days=90)
        janela_reenvio = datetime.now() - timedelta(days=30)

        agendamentos = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.criado_em <= limite
        ).limit(50).all()

        for ag in agendamentos:
            try:
                telefone = limpar_telefone(getattr(ag, "telefone", ""))

                if not telefone:
                    continue

                if cliente_em_atendimento_humano(telefone):
                    continue

                recuperacao_recente = (
                    db.query(Atendimento)
                    .filter(Atendimento.telefone == telefone)
                    .filter(Atendimento.setor == "RECUPERACAO_IA")
                    .filter(Atendimento.data >= janela_reenvio)
                    .first()
                )

                if recuperacao_recente:
                    continue

                mensagem = gerar_mensagem_recuperacao(
                    modelo=getattr(ag, "modelo", ""),
                    nome=getattr(ag, "nome", ""),
                )

                if not mensagem:
                    continue

                retorno_zapi = enviar_mensagem(telefone, mensagem)

                log_info(
                    "RECUPERACAO IA enviada:",
                    {
                        "telefone": telefone,
                        "mensagem": mensagem,
                        "retorno_zapi": retorno_zapi,
                    },
                )

                if not retorno_zapi:
                    continue

                salvar_evento_atendimento(
                    telefone=telefone,
                    setor="RECUPERACAO_IA",
                    status="RECUPERACAO_ENVIADA",
                    etapa="recuperacao_ia",
                    dados={
                        "telefone": telefone,
                        "nome": getattr(ag, "nome", ""),
                        "modelo": getattr(ag, "modelo", ""),
                        "followup_enviado": True,
                        "followup_respondido": False,
                        "data_followup": agora_datetime(),
                        "proxima_acao": "RECUPERAR_CLIENTE_REVISAO",
                        "nivel_interesse": "MORNO",
                    },
                    atendimento_humano=False,
                    concluido=False,
                    origem="IA_RECUPERACAO",
                    observacao=getattr(ag, "protocolo", ""),
                )

            except Exception as e:
                log_erro("Erro recuperação IA cliente:", repr(e))

    except Exception as e:
        log_erro("Erro processar_recuperacao_clientes:", repr(e))

    finally:
        db.close()


# ==========================================
# CONTROLE DE BLOQUEIO DE IA NO FLUXO
# ==========================================
ETAPAS_COLETA_RESTRITA = {
    "revisao_modelo",
    "revisao_nome",
    "revisao_cpf",
    "revisao_escolher_veiculo",
    "revisao_placa_chassi",
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

    "duvidas_menu",
    "duvidas",
    "duvidas_revisao",
    "duvidas_garantia",
    "duvida_manual",
    "duvida_pos_resposta",
    "duvidas_retorno",

    "cancelar_agendamento",
    "reagendar_agendamento",
    "consultar_agendamento",
    "consulta_agendamento_cpf",
    "cancelar_agendamento_cpf",
    "reagendar_agendamento_cpf",

    "pecas",
    "acessorios",
    "garantia",
    "garantia_menu",
    "garantia_nova_nome",
    "garantia_nova_modelo",
    "garantia_nova_ano",
    "garantia_nova_km",
    "garantia_nova_descricao",
    "garantia_acompanhar_nome",
    "garantia_acompanhar_modelo",
    "garantia_acompanhar_cpf",
    "garantia_acompanhar_descricao",
    "garantia_consulta_cpf",
    "garantia_escolher_os",
    "atacado",
    "atacado_cotacao",
    "atacado_cotacao_itens",
    "atacado_cadastro",
    "atacado_empresa",
    "atacado_responsavel",
    "atacado_cidade",
    "atacado_cnpj",
    "atacado_telefone_comercial",
    "atacado_segmento",
    "atacado_produtos_interesse",
    "atacado_cadastro_empresa",
    "atacado_cadastro_responsavel",
    "atacado_cadastro_cidade",
    "atacado_cadastro_cnpj",
    "atacado_cadastro_telefone",
    "atacado_cadastro_segmento",
    "atacado_cadastro_produtos",
    "atacado_catalogo_enviado",
    "atacado_catalogo_erro",
    "atendimento_humano",
}


def cliente_em_atendimento_humano(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    try:
        dados_cliente = clientes.get(telefone, {})

        if dados_cliente.get("atendimento_humano"):
            return True

        if normalizar_status(dados_cliente.get("status", "")) == STATUS_ATENDIMENTO_HUMANO:
            return True

        if limpar_texto(dados_cliente.get("etapa", "")).lower() == "atendimento_humano":
            return True

    except Exception:
        pass

    return atendimento_humano_ativo_no_banco(telefone)


def deve_bloquear_ia_no_fluxo(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    try:
        dados = clientes.get(telefone, {})
        etapa = limpar_texto(dados.get("etapa", "")).lower()

        return etapa in ETAPAS_COLETA_RESTRITA

    except Exception:
        return False


def texto_pede_menu(texto):
    texto_norm = normalizar_texto(texto)

    return texto_norm in [
        "menu",
        "voltar",
        "voltar menu",
        "voltar ao menu",
        "inicio",
        "iniciar",
        "comecar",
        "começar",
        "reiniciar",
    ]


def texto_pede_humano(texto):
    texto_norm = normalizar_texto(texto)

    gatilhos = [
        "humano",
        "atendente",
        "consultor",
        "falar com alguem",
        "falar com alguém",
        "quero atendimento",
        "falar com vendedor",
        "falar com consultor",
        "preciso de ajuda humana",
    ]

    return any(normalizar_texto(g) in texto_norm for g in gatilhos)


def classificar_intencao_prioritaria(texto):
    texto_norm = normalizar_texto(texto)

    if not texto_norm:
        return ""

    try:
        resposta = classificar_intencao(texto) or {}
    except Exception as e:
        log_erro("Erro ao classificar intenção prioritária:", repr(e))
        resposta = {}

    intencao = limpar_texto(resposta.get("intencao", "")).lower()

    try:
        confianca = float(resposta.get("confianca", 0) or 0)
    except Exception:
        confianca = 0

    aliases = {
        "consultar_garantia": "acompanhar_garantia",
        "garantia_acompanhar": "acompanhar_garantia",
        "humano": "atendimento_humano",
        "cancelar_revisao": "cancelar",
        "cancelar_agendamento": "cancelar",
    }
    intencao = aliases.get(intencao, intencao)

    if intencao in INTENCOES_PRIORITARIAS and confianca >= 0.55:
        return intencao

    if texto_pede_menu(texto):
        return "menu"

    if texto_pede_humano(texto):
        return "atendimento_humano"

    if texto_norm in ["cancelar", "cancela", "cancelamento", "cancelar revisao", "cancelar revisão"]:
        return "cancelar"

    if (
        ("os" in texto_norm or "ordem de servico" in texto_norm or "ordem de serviço" in texto_norm)
        and any(termo in texto_norm for termo in ["consultar", "acompanhar", "status", "aberta", "andamento"])
    ):
        return "acompanhar_os"

    if "garantia" in texto_norm and any(
        termo in texto_norm
        for termo in ["consultar", "acompanhar", "status", "processo", "como esta", "como está"]
    ):
        return "acompanhar_garantia"

    return ""


def interromper_fluxo_revisao_por_intencao_prioritaria(telefone, texto):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    etapa_atual = limpar_texto(clientes.get(telefone, {}).get("etapa", "")).lower()

    if not etapa_atual.startswith("revisao_"):
        return False

    intencao = classificar_intencao_prioritaria(texto)

    if not intencao:
        return False

    log_info(
        "INTENÇÃO PRIORITÁRIA INTERROMPEU REVISÃO:",
        {"telefone": telefone, "intencao": intencao, "etapa_anterior": etapa_atual},
    )

    limpar_dados_fluxo_revisao(telefone)

    if intencao == "menu":
        resetar_cliente(telefone)
        enviar_menu(telefone)
        return True

    if intencao == "cancelar":
        resetar_cliente(telefone)
        enviar_mensagem(telefone, "Atendimento de revisão cancelado. Voltando ao menu principal.")
        enviar_menu(telefone)
        return True

    if intencao == "atendimento_humano":
        clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
        clientes[telefone]["atendimento_humano"] = True
        clientes[telefone]["etapa"] = "atendimento_humano"
        enviar_mensagem(telefone, "Certo. Vou direcionar você para um atendente.")
        ativar_atendimento_humano(telefone)
        return True

    if intencao in ["acompanhar_garantia", "consultar_garantia", "status_os", "acompanhar_os"]:
        iniciar_cliente(telefone)
        clientes[telefone]["intencao_ia"] = "acompanhar_garantia"
        clientes[telefone]["etapa"] = "garantia_consulta_cpf"
        clientes[telefone]["atendimento_humano"] = False
        clientes[telefone]["cpf"] = ""
        clientes[telefone]["garantia_os_sances"] = []
        enviar_mensagem(
            telefone,
            "Certo. Vou consultar no Sances.\n\nInforme seu *CPF* com 11 números."
        )
        return True

    if intencao == "garantia":
        iniciar_fluxo_garantia(telefone)
        return True

    return False

# ==========================================
# APOIO ACESSÓRIOS
# ==========================================
def normalizar_modelo_acessorio(texto):
    try:
        texto = normalizar_texto(texto)
        texto = re.sub(r"[^a-zA-Z0-9\s]", "", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto
    except Exception:
        return ""


def obter_pdf_acessorios_por_modelo(modelo):
    try:
        modelo_norm = normalizar_modelo_acessorio(modelo)

        if not modelo_norm:
            return PDF_ACESSORIOS_GERAL

        for chave, arquivo in MAPA_PDF_ACESSORIOS.items():
            chave_norm = normalizar_modelo_acessorio(chave)

            if chave_norm and chave_norm in modelo_norm:
                return arquivo

        return PDF_ACESSORIOS_GERAL

    except Exception as e:
        log_erro("Erro ao obter PDF acessórios:", repr(e))
        return PDF_ACESSORIOS_GERAL


# ==========================================
# REVISÃO / DATAS / OPÇÕES
# ==========================================
ITENS_PRE_ORCAMENTO = {
    "relacao": "Relação",
    "kit relacao": "Kit relação",
    "corrente": "Corrente",
    "coroa": "Coroa",
    "pinhao": "Pinhão",
    "oleo": "Óleo",
    "yamalube": "Óleo Yamalube",
    "10w40": "Óleo 10W40",
    "20w50": "Óleo 20W50",
    "10w-40": "Óleo 10W40",
    "20w-50": "Óleo 20W50",
    "lubrificante": "Lubrificante",
    "filtro de oleo": "Filtro de óleo",
    "filtro oleo": "Filtro de óleo",
    "filtro de ar": "Filtro de ar",
    "filtro": "Filtro",
    "pastilha de freio": "Pastilha de freio",
    "pastilha": "Pastilha de freio",
    "pneu": "Pneu",
    "vela": "Vela",
    "bateria": "Bateria",
    "cabo": "Cabo",
    "lampada": "Lâmpada",
    "slider": "Slider",
    "protetor de motor": "Protetor de motor",
    "protetor motor": "Protetor de motor",
    "protetor de carenagem": "Protetor de carenagem",
    "bau": "Baú",
    "bagageiro": "Bagageiro",
    "suporte de celular": "Suporte de celular",
    "bolha": "Bolha",
    "manopla": "Manopla",
    "retrovisor": "Retrovisor",
    "revisao complementar": "Revisão complementar",
}


TERMOS_ORCAMENTO = [
    "orcamento",
    "orçamento",
    "cotacao",
    "cotação",
    "cotar",
    "preco",
    "preço",
    "valor",
    "quanto fica",
    "quanto custa",
    "tem ",
    "estoque",
    "tem estoque",
    "disponivel",
    "disponível",
    "preciso de",
    "quero comprar",
    "disponibilidade",
]


def identificar_modelo_pre_orcamento(texto, telefone=""):
    texto_norm = normalizar_texto(texto)
    aliases = {
        "FAZER 250": ["fazer 250", "fz25", "fz 25", "fazer250"],
        "FZ15": ["fz15", "fz 15", "fazer 150"],
        "CROSSER": ["crosser", "xtz 150"],
        "LANDER": ["lander", "lander 250", "xtz 250"],
        "FACTOR": ["factor", "factor 150", "factor 125"],
        "NMAX": ["nmax"],
        "NEO": ["neo"],
        "FLUO": ["fluo"],
        "AEROX": ["aerox"],
        "TENERE 700": ["tenere 700", "teneré 700", "tenere", "t7"],
        "MT-03": ["mt03", "mt 03", "mt-03"],
        "MT-07": ["mt07", "mt 07", "mt-07"],
        "R15": ["r15", "r 15"],
        "R3": ["r3", "r 3"],
    }

    for modelo, lista_alias in aliases.items():
        if any(alias in texto_norm for alias in lista_alias):
            return modelo

    telefone = limpar_telefone(telefone)

    if telefone and telefone in clientes:
        memoria = clientes[telefone].get("memoria_cliente", {}) or {}
        return limpar_texto(clientes[telefone].get("modelo", "") or memoria.get("modelo", "")).upper()

    return ""


def extrair_ano_pre_orcamento(texto, telefone=""):
    texto_norm = normalizar_texto(texto)
    match = re.search(r"\b(20[0-3][0-9]|19[8-9][0-9])\b", texto_norm)

    if match:
        return match.group(1)

    telefone = limpar_telefone(telefone)

    if telefone and telefone in clientes:
        memoria = clientes[telefone].get("memoria_cliente", {}) or {}
        return limpar_texto(clientes[telefone].get("ano", "") or memoria.get("ano", ""))

    return ""


def extrair_quantidade_pre_orcamento(texto):
    texto_norm = normalizar_texto(texto)
    padroes = [
        r"\b(\d{1,3})\s*(?:x|un|unidade|unidades|peca|pecas|peça|peças|filtro|filtros|kit|kits)\b",
        r"\b(?:quero|preciso|cotar|comprar)\s+(\d{1,3})\b",
    ]

    for padrao in padroes:
        match = re.search(padrao, texto_norm)

        if match:
            return match.group(1)

    return "1"


def extrair_itens_pre_orcamento(texto):
    texto_norm = normalizar_texto(texto)
    encontrados = []

    for chave, nome in sorted(ITENS_PRE_ORCAMENTO.items(), key=lambda item: len(item[0]), reverse=True):
        if chave in texto_norm and nome not in encontrados:
            if any(chave in normalizar_texto(item) or normalizar_texto(item) in chave for item in encontrados):
                continue

            encontrados.append(nome)

    if encontrados:
        return encontrados

    padrao = re.search(
        r"(?:preciso de|quero orcamento de|quero orçamento de|orcamento de|orçamento de|quanto fica o|quanto fica a|quanto custa o|quanto custa a|tem)\s+(.+?)(?:\s+da\s+|\s+do\s+|\s+para\s+|$)",
        texto_norm,
    )

    if padrao:
        item = limpar_texto(padrao.group(1))
        item = re.sub(r"\b(minha|meu|uma|um|de|da|do)\b", "", item).strip()

        if item and len(item) >= 3:
            return [item.title()]

    return []


def identificar_setor_pre_orcamento(texto, itens):
    texto_norm = normalizar_texto(texto)
    itens_norm = normalizar_texto(" ".join(itens))

    if any(t in texto_norm for t in ["atacado", "lojista", "logista", "revenda", "oficina", "cotar 10", "cotar dez"]):
        return "atacado"

    if any(t in texto_norm or t in itens_norm for t in [
        "acessorio",
        "acessório",
        "slider",
        "protetor",
        "bau",
        "bagageiro",
        "suporte",
        "bolha",
    ]):
        return "acessórios"

    if "revisao complementar" in texto_norm or "revisão complementar" in texto_norm:
        return "revisão"

    return "peças"


def identificar_urgencia_pre_orcamento(texto):
    texto_norm = normalizar_texto(texto)

    if any(t in texto_norm for t in ["urgente", "hoje", "agora", "imediato", "o quanto antes"]):
        return "urgente"

    if any(t in texto_norm for t in ["amanha", "amanhã", "essa semana"]):
        return "moderada"

    return ""


def texto_parece_valor_revisao_pre_orcamento(texto):
    texto_norm = normalizar_texto(texto)

    tem_revisao = any(t in texto_norm for t in ["revisao", "revisão", "revisar"])
    tem_valor = any(t in texto_norm for t in ["valor", "preco", "preço", "quanto custa", "quanto fica"])
    tem_item = bool(extrair_itens_pre_orcamento(texto_norm))

    return tem_revisao and tem_valor and not tem_item


def texto_parece_pre_orcamento(texto):
    texto_norm = normalizar_texto(texto)

    if not texto_norm or texto_parece_menu_ou_saudacao(texto_norm):
        return False

    if texto_parece_valor_revisao_pre_orcamento(texto_norm):
        return False

    tem_termo_orcamento = any(termo in texto_norm for termo in TERMOS_ORCAMENTO)
    tem_item = bool(extrair_itens_pre_orcamento(texto_norm))
    tem_atacado = any(t in texto_norm for t in ["atacado", "lojista", "logista", "cotar"])

    return (tem_termo_orcamento and (tem_item or tem_atacado)) or (tem_item and "preciso" in texto_norm)


def montar_pre_orcamento(texto_cliente, telefone):
    telefone = limpar_telefone(telefone)
    texto_cliente = limpar_texto(texto_cliente)
    iniciar_cliente(telefone)

    pendente = clientes[telefone].get("pre_orcamento_pendente", {}) or {}
    texto_completo = " ".join([
        limpar_texto(pendente.get("texto_original", "")),
        texto_cliente,
    ]).strip()

    modelo = limpar_texto(pendente.get("modelo", "") or identificar_modelo_pre_orcamento(texto_completo, telefone)).upper()
    ano = limpar_texto(pendente.get("ano", "") or extrair_ano_pre_orcamento(texto_completo, telefone))
    itens = pendente.get("itens", []) or extrair_itens_pre_orcamento(texto_completo)
    quantidade = limpar_texto(pendente.get("quantidade", "") or extrair_quantidade_pre_orcamento(texto_completo))
    setor = limpar_texto(pendente.get("setor", "") or identificar_setor_pre_orcamento(texto_completo, itens))
    urgencia = limpar_texto(pendente.get("urgencia", "") or identificar_urgencia_pre_orcamento(texto_completo))

    if not modelo:
        clientes[telefone]["etapa"] = "pre_orcamento_modelo"
        clientes[telefone]["pre_orcamento_pendente"] = {
            "texto_original": texto_completo,
            "itens": itens,
            "quantidade": quantidade,
            "setor": setor,
            "urgencia": urgencia,
        }
        enviar_mensagem(
            telefone,
            "Qual o modelo e ano da sua moto para eu montar o pré-orçamento corretamente?"
        )
        return {"ok": False, "pendente": "modelo"}

    if not itens:
        clientes[telefone]["etapa"] = "pre_orcamento_item"
        clientes[telefone]["pre_orcamento_pendente"] = {
            "texto_original": texto_completo,
            "modelo": modelo,
            "ano": ano,
            "quantidade": quantidade,
            "setor": setor,
            "urgencia": urgencia,
        }
        enviar_mensagem(
            telefone,
            "Qual peça ou acessório você deseja orçamento?"
        )
        return {"ok": False, "pendente": "item"}

    pre_orcamento = {
        "modelo": modelo,
        "ano": ano,
        "itens": itens,
        "quantidade": quantidade or "1",
        "setor": setor,
        "urgencia": urgencia,
        "observacao": texto_completo,
        "status": "PRE_ORCAMENTO",
    }

    clientes[telefone]["pre_orcamento"] = pre_orcamento
    clientes[telefone]["pre_orcamento_pendente"] = {}
    clientes[telefone]["modelo"] = modelo
    clientes[telefone]["ano"] = ano
    clientes[telefone]["itens"] = ", ".join(itens)
    clientes[telefone]["quantidade"] = quantidade or "1"
    clientes[telefone]["observacao"] = texto_completo
    clientes[telefone]["produto_interesse"] = ", ".join(itens)
    clientes[telefone]["intencao_ia"] = "orcamento"
    clientes[telefone]["proxima_acao"] = "consultor_finalizar_orcamento"
    clientes[telefone]["nivel_interesse"] = "QUENTE"
    clientes[telefone]["temperatura_lead"] = "QUENTE"
    clientes[telefone]["oportunidade_comercial"] = True
    clientes[telefone]["status_comercial"] = "PRE_ORCAMENTO"
    clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["etapa"] = "atendimento_humano"
    clientes[telefone]["ultima_interacao"] = agora()

    setor_evento = {
        "peças": "Peças",
        "acessórios": "Acessórios",
        "atacado": "Logista / Atacado",
        "revisão": "Revisão",
    }.get(setor, "Peças")

    salvar_evento_atendimento(
        telefone=telefone,
        setor=setor_evento,
        status="PRE_ORCAMENTO",
        etapa="pre_orcamento",
        dados=clientes[telefone],
        atendimento_humano=True,
        concluido=False,
        origem=clientes[telefone].get("origem", "BOT"),
        observacao=texto_completo,
        intencao_ia="orcamento",
    )

    if setor == "atacado":
        clientes[telefone]["itens_cotacao"] = ", ".join(itens)
        clientes[telefone]["nivel_interesse_atacado"] = "PARCEIRO_QUENTE"
        clientes[telefone]["proxima_acao_atacado"] = "PRIORIZAR_CONSULTOR_COMERCIAL"
        salvar_lead_atacado(telefone, status="PRE_ORCAMENTO_ATACADO", mensagem=texto_completo)

    linhas = [
        "✅ Entendi! Separei sua solicitação de orçamento:",
        "",
        f"🏍️ Modelo: {modelo}",
    ]

    if ano:
        linhas.append(f"📅 Ano: {ano}")

    linhas.extend([
        f"🧩 Item: {', '.join(itens)}",
        f"📦 Quantidade: {quantidade or '1'}",
    ])

    if urgencia:
        linhas.append(f"⏱️ Urgência: {urgencia}")

    linhas.extend([
        "",
        "Vou encaminhar para um consultor verificar preço e disponibilidade no sistema. 🤝",
    ])

    enviar_mensagem(telefone, "\n".join(linhas))
    return {"ok": True, "pre_orcamento": pre_orcamento}


def normalizar_revisao_para_fluxo(valor):
    try:
        texto = limpar_opcao(valor)
        texto_norm = normalizar_texto(texto).replace(" ", "")

        mapa = {
            "1": "1", "1a": "1", "1o": "1", "1ª": "1", "1º": "1",
            "primeira": "1", "primeirarevisao": "1",

            "2": "2", "2a": "2", "2o": "2", "2ª": "2", "2º": "2",
            "segunda": "2", "segundarevisao": "2",

            "3": "3", "3a": "3", "3o": "3", "3ª": "3", "3º": "3",
            "terceira": "3", "terceirarevisao": "3",

            "4": "4", "4a": "4", "4o": "4", "4ª": "4", "4º": "4",
            "quarta": "4", "quartarevisao": "4",

            "5": "5", "5a": "5", "5o": "5", "5ª": "5", "5º": "5",
            "quinta": "5", "quintarevisao": "5",
        }

        return mapa.get(texto_norm, "")

    except Exception:
        return ""


MAPA_DIA_NUMERO = {
    "segunda": "1",
    "segunda-feira": "1",
    "segunda feira": "1",

    "terca": "2",
    "terça": "2",
    "terca-feira": "2",
    "terça-feira": "2",
    "terca feira": "2",
    "terça feira": "2",

    "quarta": "3",
    "quarta-feira": "3",
    "quarta feira": "3",

    "quinta": "4",
    "quinta-feira": "4",
    "quinta feira": "4",

    "sexta": "5",
    "sexta-feira": "5",
    "sexta feira": "5",

    "sabado": "6",
    "sábado": "6",
    "sabado-feira": "6",
    "sábado-feira": "6",
    "sabado feira": "6",
    "sábado feira": "6",
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
    try:
        texto_limpo = limpar_opcao(texto)

        if texto_limpo in ["1", "2", "3", "4", "5", "6"]:
            return texto_limpo

        texto_norm = normalizar_texto(texto_limpo)
        return MAPA_DIA_NUMERO.get(texto_norm, "")
    except Exception:
        return ""


# ==========================================
# ITENS ADICIONAIS / VENDA
# ==========================================
def limpar_item_adicional(item):
    try:
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

    except Exception:
        return ""


def extrair_lista_itens_adicionais(valor):
    try:
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

        texto = texto.replace("\n", ",")
        texto = texto.replace(";", ",")
        texto = texto.replace("|", ",")
        texto = texto.replace("+", ",")
        texto = texto.replace("/", ",")

        partes = [
            parte.strip()
            for parte in texto.split(",")
            if parte.strip()
        ]

        itens_limpos = []
        vistos = set()

        for parte in partes:
            item = limpar_item_adicional(parte)

            if item and item not in vistos:
                itens_limpos.append(item)
                vistos.add(item)

        return itens_limpos

    except Exception:
        return []


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
        "SEM",
        "NADA",
        "-",
        "OK",
        "2",
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
        "NAO COMPARECEU": STATUS_NAO_COMPARECEU,
        "NÃO COMPARECEU": STATUS_NAO_COMPARECEU,

        "EM_EXECUCAO": STATUS_EM_EXECUCAO,
        "EM EXECUCAO": STATUS_EM_EXECUCAO,
        "EM EXECUÇÃO": STATUS_EM_EXECUCAO,

        "FINALIZADO": STATUS_FINALIZADO,
        "FINALIZADA": STATUS_FINALIZADO,
        "CONCLUIDO": STATUS_FINALIZADO,
        "CONCLUÍDO": STATUS_FINALIZADO,

        "POS_VENDA_ENVIADO": STATUS_POS_VENDA_ENVIADO,
        "POS VENDA ENVIADO": STATUS_POS_VENDA_ENVIADO,

        "ATENDIMENTO_HUMANO": STATUS_ATENDIMENTO_HUMANO,
        "ATENDIMENTO HUMANO": STATUS_ATENDIMENTO_HUMANO,
        "HUMANO": STATUS_ATENDIMENTO_HUMANO,
    }

    return mapa.get(status, status)


def definir_status_cliente(telefone, status):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    iniciar_cliente(telefone)
    clientes[telefone]["status"] = normalizar_status(status)


def obter_status_cliente(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone or telefone not in clientes:
        return STATUS_NOVO_ATENDIMENTO

    return normalizar_status(
        clientes[telefone].get("status", "")
    ) or STATUS_NOVO_ATENDIMENTO


def atendimento_humano_ativo_no_banco(telefone):
    telefone_limpo = limpar_telefone(telefone)

    if not telefone_limpo:
        return False

    db = SessionLocal()

    try:
        atendimento = (
            db.query(Atendimento)
            .filter(
                Atendimento.telefone == telefone_limpo,
                Atendimento.concluido == False,
            )
            .order_by(Atendimento.id.desc())
            .first()
        )

        if not atendimento:
            return False

        if bool(getattr(atendimento, "atendimento_humano", False)):
            return True

        status_atendimento = normalizar_status(
            getattr(atendimento, "status", "")
        )

        etapa_atendimento = str(
            getattr(atendimento, "etapa", "") or ""
        ).strip().lower()

        if etapa_atendimento == "atendimento_humano":
            return True

        return status_atendimento == STATUS_ATENDIMENTO_HUMANO

    except Exception as e:
        log_erro("Erro ao verificar atendimento humano no banco:", repr(e))
        return False

    finally:
        db.close()


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
        "placa": "",
        "chassi": "",
        "ano": "",
        "proprietario": "",
        "revisao": "",
        "km_atual": "",
        "dia": "",
        "dia_texto": "",
        "data": "",
        "horario": "",
        "horarios_disponiveis": [],
        "acessorio_desejado": "",

        "itens": "",
        "itens_cotacao": "",
        "venda_adicional": "",
        "observacao": "",
        "tipo_atendimento": "",
        "empresa": "",
        "responsavel": "",
        "cidade": "",
        "cnpj": "",
        "telefone_comercial": "",
        "segmento": "",
        "produtos_interesse": "",

        "duvidas_ia": 0,
        "concluido": False,
        "origem_etapa": "",
        "categoria_duvida": "",
        "etapa_retorno_duvida": "",

        "button_id": "",
        "opcao_menu": "",

        "tipo_mensagem": "text",
        "intencao_ia": "",
        "id_envio_zapi": "",
        "status_retorno": "",
        "codigo_cliente": "",
        "codigo_veiculo": "",
        "veiculos_sances": [],
        "origem_veiculos_sances": "",
        "garantia_os_sances": [],

        "proxima_acao": "",
        "nivel_interesse": "",
        "temperatura_lead": "",
        "produto_interesse": "",
        "oportunidade_comercial": False,
        "status_comercial": "",
        "ultima_acao_ia": "",
        "followup_nivel": 0,
        "cliente_recuperado": False,
        "valor_estimado": 0,
        "origem_ia": "",

        "ultima_mensagem_cliente": "",
        "acessorio_desejado": "",

        "sances_enviado": False,
        "sances_status": SANCES_STATUS_PENDENTE,
        "sances_protocolo": "",
        "sances_erro": "",
        "sances_data_envio": "",

        "memoria_cliente": {},
        "memoria_usada": False,
        "modelo_memoria": "",
        "nome_memoria": "",
        "ano_memoria": "",

        "nivel_interesse_atacado": "",
        "proxima_acao_atacado": "",
        "data_ultimo_contato_atacado": "",
        "recomendacoes_atacado": [],

        "pre_orcamento": {},
        "pre_orcamento_pendente": {},
    }


def iniciar_cliente(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    if telefone not in clientes:
        clientes[telefone] = estado_padrao_cliente()


def primeiro_valor(*valores):
    for valor in valores:
        valor = limpar_texto(valor)

        if valor:
            return valor

    return ""


def nivel_cliente_por_historico(atendimentos):
    if not atendimentos:
        return "novo"

    for at in atendimentos:
        temperatura = normalizar_texto(getattr(at, "temperatura_lead", ""))
        nivel = normalizar_texto(getattr(at, "nivel_interesse", ""))

        if temperatura == "quente" or nivel in ["alto", "quente"]:
            return "quente"

    for at in atendimentos:
        temperatura = normalizar_texto(getattr(at, "temperatura_lead", ""))
        nivel = normalizar_texto(getattr(at, "nivel_interesse", ""))

        if temperatura == "morno" or nivel in ["medio", "morno"]:
            return "morno"

    if len(atendimentos) >= 2:
        return "recorrente"

    for at in atendimentos:
        temperatura = normalizar_texto(getattr(at, "temperatura_lead", ""))
        nivel = normalizar_texto(getattr(at, "nivel_interesse", ""))

        if temperatura == "frio" or nivel in ["baixo", "frio"]:
            return "frio"

    return "novo"


def lista_unica_memoria(valores, limite=6):
    itens = []
    vistos = set()

    for valor in valores:
        valor = limpar_texto(valor)

        if not valor:
            continue

        for item in re.split(r",|;|\n|\+", valor):
            item = limpar_item_adicional(item)
            chave = normalizar_texto(item)

            if not item or chave in vistos:
                continue

            vistos.add(chave)
            itens.append(item)

            if len(itens) >= limite:
                return itens

    return itens


def buscar_memoria_cliente(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return {}

    db = SessionLocal()

    try:
        atendimentos = (
            db.query(Atendimento)
            .filter(Atendimento.telefone == telefone)
            .order_by(Atendimento.id.desc())
            .limit(50)
            .all()
        )

        agendamentos = (
            db.query(AgendamentoRevisao)
            .filter(AgendamentoRevisao.telefone == telefone)
            .order_by(AgendamentoRevisao.id.desc())
            .limit(20)
            .all()
        )

        ultimo_at = atendimentos[0] if atendimentos else None
        ultimo_ag = agendamentos[0] if agendamentos else None

        revisoes = [
            ag for ag in agendamentos
            if limpar_texto(getattr(ag, "revisao", ""))
            or limpar_texto(getattr(ag, "data_agendada", ""))
        ]

        ultima_revisao = revisoes[0] if revisoes else None

        setores = [
            limpar_texto(getattr(at, "setor", ""))
            for at in atendimentos
            if limpar_texto(getattr(at, "setor", ""))
        ]

        historico_garantia = [
            at for at in atendimentos
            if "garantia" in normalizar_texto(getattr(at, "setor", ""))
            or "garantia" in normalizar_texto(getattr(at, "etapa", ""))
        ]

        historico_atacado = [
            at for at in atendimentos
            if "atacado" in normalizar_texto(getattr(at, "setor", ""))
            or "logista" in normalizar_texto(getattr(at, "setor", ""))
            or "atacado" in normalizar_texto(getattr(at, "etapa", ""))
        ]

        pecas = lista_unica_memoria(
            [
                getattr(at, "produto_interesse", "")
                or getattr(at, "itens", "")
                or getattr(at, "observacao", "")
                for at in atendimentos
                if "peca" in normalizar_texto(getattr(at, "setor", ""))
                or normalizar_texto(getattr(at, "intencao_ia", "")) in ["pecas", "orcamento"]
            ]
        )

        acessorios = lista_unica_memoria(
            [
                getattr(at, "produto_interesse", "")
                or getattr(at, "itens", "")
                or getattr(at, "observacao", "")
                for at in atendimentos
                if "acessorio" in normalizar_texto(getattr(at, "setor", ""))
                or normalizar_texto(getattr(at, "intencao_ia", "")) == "acessorios"
            ]
        )

        memoria = {
            "telefone": telefone,
            "nome": primeiro_valor(
                getattr(ultimo_at, "nome", "") if ultimo_at else "",
                getattr(ultimo_ag, "nome", "") if ultimo_ag else "",
            ),
            "modelo": primeiro_valor(
                getattr(ultimo_at, "modelo", "") if ultimo_at else "",
                getattr(ultimo_ag, "modelo", "") if ultimo_ag else "",
            ),
            "ano": primeiro_valor(
                getattr(ultimo_at, "ano", "") if ultimo_at else "",
                getattr(ultimo_ag, "ano", "") if ultimo_ag else "",
            ),
            "ultima_revisao": limpar_texto(
                getattr(ultima_revisao, "revisao", "") if ultima_revisao else ""
            ),
            "data_ultima_revisao": limpar_texto(
                getattr(ultima_revisao, "data_agendada", "") if ultima_revisao else ""
            ),
            "pecas": pecas,
            "acessorios": acessorios,
            "historico_garantia": len(historico_garantia),
            "historico_atacado": len(historico_atacado),
            "nivel_cliente": nivel_cliente_por_historico(atendimentos),
            "ultima_interacao": (
                (
                    getattr(ultimo_at, "ultima_interacao", None)
                    or getattr(ultimo_at, "data", None)
                )
                if ultimo_at
                else None
            ),
            "setor_recente": setores[0] if setores else "",
            "status_atual": limpar_texto(
                getattr(ultimo_at, "status", "") if ultimo_at else ""
            ),
            "nivel_interesse": limpar_texto(
                getattr(ultimo_at, "nivel_interesse", "") if ultimo_at else ""
            ),
            "observacoes": primeiro_valor(
                getattr(ultimo_at, "observacoes", "") if ultimo_at else "",
                getattr(ultimo_at, "observacao", "") if ultimo_at else "",
            )[:500],
            "total_atendimentos": len(atendimentos),
            "total_agendamentos": len(agendamentos),
        }

        return memoria

    except Exception as e:
        log_erro("Erro buscar_memoria_cliente:", repr(e))
        return {}

    finally:
        db.close()


def atualizar_memoria_cliente(telefone, dados=None):
    telefone = limpar_telefone(telefone)
    dados = dados or {}

    if not telefone:
        return {}

    iniciar_cliente(telefone)

    memoria = buscar_memoria_cliente(telefone)

    if dados:
        for chave in [
            "nome",
            "modelo",
            "ano",
            "ultima_revisao",
            "data_ultima_revisao",
            "nivel_cliente",
            "nivel_interesse",
            "setor_recente",
            "status_atual",
            "observacoes",
        ]:
            valor = limpar_texto(dados.get(chave, ""))

            if valor:
                memoria[chave] = valor

    clientes[telefone]["memoria_cliente"] = memoria
    clientes[telefone]["nome_memoria"] = limpar_texto(memoria.get("nome", ""))
    clientes[telefone]["modelo_memoria"] = limpar_texto(memoria.get("modelo", ""))
    clientes[telefone]["ano_memoria"] = limpar_texto(memoria.get("ano", ""))

    return memoria


def carregar_memoria_cliente_no_estado(telefone):
    memoria = atualizar_memoria_cliente(telefone)

    if not memoria:
        return {}

    if not clientes[telefone].get("nome") and memoria.get("nome"):
        clientes[telefone]["nome_memoria"] = memoria.get("nome", "")

    if not clientes[telefone].get("modelo") and memoria.get("modelo"):
        clientes[telefone]["modelo_memoria"] = memoria.get("modelo", "")

    if not clientes[telefone].get("ano") and memoria.get("ano"):
        clientes[telefone]["ano_memoria"] = memoria.get("ano", "")

    return memoria


def mensagem_memoria_cliente(telefone, contexto="geral"):
    telefone = limpar_telefone(telefone)

    if not telefone or telefone not in clientes:
        return ""

    memoria = clientes[telefone].get("memoria_cliente", {}) or {}

    if not memoria or clientes[telefone].get("memoria_usada"):
        return ""

    nome = limpar_texto(memoria.get("nome", "")).split(" ")[0]
    modelo = limpar_texto(memoria.get("modelo", "")).upper()
    ultima_revisao = limpar_texto(memoria.get("ultima_revisao", ""))
    data_ultima = limpar_texto(memoria.get("data_ultima_revisao", ""))
    nivel = limpar_texto(memoria.get("nivel_cliente", ""))

    if not any([nome, modelo, ultima_revisao, nivel and nivel != "novo"]):
        return ""

    clientes[telefone]["memoria_usada"] = True

    saudacao = f"{nome}, " if nome else ""

    if contexto == "revisao" and modelo:
        if ultima_revisao:
            complemento_data = f" em {data_ultima}" if data_ultima else ""
            return (
                f"{saudacao}vi aqui que sua última revisão registrada foi a "
                f"{ultima_revisao}ª da *{modelo}*{complemento_data}. "
                "Posso te ajudar com o próximo agendamento."
            )

        return f"{saudacao}vi aqui que você costuma falar sobre sua *{modelo}*. 😊"

    if contexto in ["pecas", "acessorios"] and modelo:
        return f"{saudacao}vi aqui que seu histórico mais recente é com a *{modelo}*. 😊"

    if contexto == "atacado" and memoria.get("historico_atacado", 0):
        return f"{saudacao}vi aqui que você já teve atendimento comercial de atacado com a gente."

    if contexto == "garantia" and memoria.get("historico_garantia", 0):
        return f"{saudacao}vi aqui que você já teve atendimento de garantia registrado conosco."

    if modelo:
        return f"{saudacao}vi aqui que você costuma falar sobre sua *{modelo}*. 😊"

    return ""


def enviar_mensagem_memoria_cliente(telefone, contexto="geral"):
    mensagem = mensagem_memoria_cliente(telefone, contexto)

    if mensagem:
        enviar_mensagem(telefone, mensagem)
        return True

    return False


def resetar_cliente(telefone, preservar_humano=False):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    atendimento_humano = False

    if telefone in clientes:
        atendimento_humano = bool(clientes[telefone].get("atendimento_humano", False))

    clientes[telefone] = estado_padrao_cliente()

    if preservar_humano and atendimento_humano:
        clientes[telefone]["atendimento_humano"] = True
        clientes[telefone]["etapa"] = "atendimento_humano"
        clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
        clientes[telefone]["ultima_interacao"] = agora()


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

        if atendimento and hasattr(atendimento, "ultima_interacao"):
            atendimento.ultima_interacao = agora_datetime()
            db.commit()

    except Exception as e:
        db.rollback()
        log_erro("Erro ao atualizar interação no banco:", repr(e))

    finally:
        db.close()


def atualizar_ultima_mensagem_cliente(telefone, texto=""):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    iniciar_cliente(telefone)

    texto = limpar_texto(texto)

    if texto:
        clientes[telefone]["ultima_mensagem_cliente"] = texto

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
            agora_dt = agora_datetime()

            if hasattr(atendimento, "ultima_mensagem_cliente"):
                atendimento.ultima_mensagem_cliente = texto or ""

            if hasattr(atendimento, "ultima_interacao"):
                atendimento.ultima_interacao = agora_dt

            if hasattr(atendimento, "followup_respondido"):
                atendimento.followup_respondido = True

            if (
                hasattr(atendimento, "followup_enviado")
                and bool(getattr(atendimento, "followup_enviado", False))
                and hasattr(atendimento, "followup_recuperado")
            ):
                atendimento.followup_recuperado = True
                clientes[telefone]["followup_recuperado"] = True

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

    atendimento_humano_ativo = bool(clientes[telefone].get("atendimento_humano", False))

    campos_limpar = [
        "modelo",
        "nome",
        "cpf",
        "placa",
        "chassi",
        "ano",
        "proprietario",
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
        "opcao_menu",
        "intencao_ia",
        "id_envio_zapi",
        "status_retorno",
        "codigo_cliente",
        "codigo_veiculo",
        "proxima_acao",
        "nivel_interesse",
        "temperatura_lead",
        "produto_interesse",
        "status_comercial",
        "ultima_acao_ia",
        "origem_ia",
        "ultima_mensagem_cliente",
    ]

    for campo in campos_limpar:
        clientes[telefone][campo] = ""

    clientes[telefone]["veiculos_sances"] = []
    clientes[telefone]["origem_veiculos_sances"] = ""
    clientes[telefone]["garantia_os_sances"] = []
    clientes[telefone]["horarios_disponiveis"] = []
    clientes[telefone]["concluido"] = False
    clientes[telefone]["followup_nivel"] = 0
    clientes[telefone]["oportunidade_comercial"] = False
    clientes[telefone]["cliente_recuperado"] = False
    clientes[telefone]["valor_estimado"] = 0

    clientes[telefone]["sances_enviado"] = False
    clientes[telefone]["sances_status"] = SANCES_STATUS_PENDENTE
    clientes[telefone]["sances_protocolo"] = ""
    clientes[telefone]["sances_erro"] = ""
    clientes[telefone]["sances_data_envio"] = ""

    if atendimento_humano_ativo:
        clientes[telefone]["atendimento_humano"] = True
        clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
        clientes[telefone]["etapa"] = "atendimento_humano"
    else:
        clientes[telefone]["atendimento_humano"] = False
        clientes[telefone]["status"] = STATUS_AGENDAMENTO_INICIADO
        clientes[telefone]["etapa"] = "revisao_modelo"

    clientes[telefone]["ultima_interacao"] = agora()


def ativar_atendimento_humano(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    iniciar_cliente(telefone)

    if clientes[telefone].get("atendimento_humano"):
        return

    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["etapa"] = "atendimento_humano"
    clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
    clientes[telefone]["ultima_interacao"] = agora()

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Atendimento Humano",
        status=STATUS_ATENDIMENTO_HUMANO,
        etapa="atendimento_humano",
        dados=clientes[telefone],
        atendimento_humano=True,
        concluido=False,
    )

    enviar_mensagem(
        telefone,
        "👨‍💼 *Atendimento humano acionado*\n\n"
        "Perfeito, vou direcionar seu atendimento para nossa equipe.\n"
        "Daqui em diante, um atendente segue com você por aqui.\n\n"
        "Quando quiser voltar ao menu automático, é só enviar *menu*."
    )


def desativar_atendimento_humano(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return

    iniciar_cliente(telefone)

    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["etapa"] = "menu"
    clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO
    clientes[telefone]["ultima_interacao"] = agora()

    db = SessionLocal()

    try:
        atendimentos = (
            db.query(Atendimento)
            .filter(
                Atendimento.telefone == telefone,
                Atendimento.atendimento_humano == True,
                Atendimento.concluido == False,
            )
            .all()
        )

        for atendimento in atendimentos:
            atendimento.atendimento_humano = False
            atendimento.concluido = True
            atendimento.status = STATUS_FINALIZADO
            atendimento.etapa = "menu"

            if hasattr(atendimento, "ultima_interacao"):
                atendimento.ultima_interacao = agora_datetime()

        db.commit()

    except Exception as e:
        db.rollback()
        log_erro("Erro ao desativar atendimento humano:", repr(e))

    finally:
        db.close()


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
                or normalizar_status(dados.get("status", "")) == STATUS_ATENDIMENTO_HUMANO
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
        data = payload.get("data", {}) or {}
        message = payload.get("message", {}) or {}

        candidatos = [
            payload.get("buttonId"),
            payload.get("selectedButtonId"),
            payload.get("selectedId"),
            payload.get("selectedRowId"),

            payload.get("buttonsResponseMessage", {}).get("buttonId")
            if isinstance(payload.get("buttonsResponseMessage"), dict) else None,

            payload.get("buttonsResponseMessage", {}).get("selectedButtonId")
            if isinstance(payload.get("buttonsResponseMessage"), dict) else None,

            payload.get("buttonsResponseMessage", {}).get("message")
            if isinstance(payload.get("buttonsResponseMessage"), dict) else None,

            payload.get("listResponseMessage", {})
            .get("singleSelectReply", {})
            .get("selectedRowId")
            if isinstance(payload.get("listResponseMessage"), dict) else None,

            payload.get("button", {}).get("id")
            if isinstance(payload.get("button"), dict) else None,

            payload.get("button", {}).get("text")
            if isinstance(payload.get("button"), dict) else None,
        ]

        if isinstance(message, dict):
            candidatos.extend([
                message.get("buttonId"),
                message.get("selectedButtonId"),
                message.get("selectedId"),
                message.get("selectedRowId"),

                message.get("buttonsResponseMessage", {}).get("buttonId")
                if isinstance(message.get("buttonsResponseMessage"), dict) else None,

                message.get("buttonsResponseMessage", {}).get("selectedButtonId")
                if isinstance(message.get("buttonsResponseMessage"), dict) else None,

                message.get("buttonsResponseMessage", {}).get("message")
                if isinstance(message.get("buttonsResponseMessage"), dict) else None,

                message.get("listResponseMessage", {})
                .get("singleSelectReply", {})
                .get("selectedRowId")
                if isinstance(message.get("listResponseMessage"), dict) else None,

                message.get("button", {}).get("id")
                if isinstance(message.get("button"), dict) else None,

                message.get("button", {}).get("text")
                if isinstance(message.get("button"), dict) else None,
            ])

        if isinstance(data, dict):
            data_message = data.get("message", {}) or {}

            candidatos.extend([
                data.get("buttonId"),
                data.get("selectedButtonId"),
                data.get("selectedId"),
                data.get("selectedRowId"),

                data.get("buttonsResponseMessage", {}).get("buttonId")
                if isinstance(data.get("buttonsResponseMessage"), dict) else None,

                data.get("buttonsResponseMessage", {}).get("selectedButtonId")
                if isinstance(data.get("buttonsResponseMessage"), dict) else None,

                data.get("buttonsResponseMessage", {}).get("message")
                if isinstance(data.get("buttonsResponseMessage"), dict) else None,

                data.get("listResponseMessage", {})
                .get("singleSelectReply", {})
                .get("selectedRowId")
                if isinstance(data.get("listResponseMessage"), dict) else None,

                data.get("button", {}).get("id")
                if isinstance(data.get("button"), dict) else None,

                data.get("button", {}).get("text")
                if isinstance(data.get("button"), dict) else None,
            ])

            if isinstance(data_message, dict):
                candidatos.extend([
                    data_message.get("buttonId"),
                    data_message.get("selectedButtonId"),
                    data_message.get("selectedId"),
                    data_message.get("selectedRowId"),

                    data_message.get("buttonsResponseMessage", {}).get("buttonId")
                    if isinstance(data_message.get("buttonsResponseMessage"), dict) else None,

                    data_message.get("buttonsResponseMessage", {}).get("selectedButtonId")
                    if isinstance(data_message.get("buttonsResponseMessage"), dict) else None,

                    data_message.get("buttonsResponseMessage", {}).get("message")
                    if isinstance(data_message.get("buttonsResponseMessage"), dict) else None,

                    data_message.get("listResponseMessage", {})
                    .get("singleSelectReply", {})
                    .get("selectedRowId")
                    if isinstance(data_message.get("listResponseMessage"), dict) else None,

                    data_message.get("button", {}).get("id")
                    if isinstance(data_message.get("button"), dict) else None,

                    data_message.get("button", {}).get("text")
                    if isinstance(data_message.get("button"), dict) else None,
                ])

        for valor in candidatos:
            valor = limpar_texto(valor)
            if valor:
                return valor

        return ""

    except Exception as e:
        log_erro("Erro ao extrair opção/botão Z-API:", repr(e))
        return ""


def extrair_telefone(payload):
    try:
        data = payload.get("data", {}) or {}

        candidatos = [
            payload.get("phone"),
            payload.get("from"),
            payload.get("sender"),
            payload.get("chatId"),
            payload.get("participantPhone"),
            payload.get("author"),
            payload.get("remoteJid"),
        ]

        if isinstance(data, dict):
            candidatos.extend([
                data.get("phone"),
                data.get("from"),
                data.get("sender"),
                data.get("chatId"),
                data.get("participantPhone"),
                data.get("author"),
                data.get("remoteJid"),
            ])

        for telefone in candidatos:
            telefone_limpo = limpar_telefone(telefone)
            if telefone_limpo:
                return telefone_limpo

        return ""

    except Exception as e:
        log_erro("Erro ao extrair telefone Z-API:", repr(e))
        return ""


def payload_tem_midia(payload, tipo=""):
    try:
        data = payload.get("data", {}) or {}

        if tipo:
            if payload.get(tipo):
                return True

            if isinstance(data, dict) and data.get(tipo):
                return True

            return False

        for chave in ["audio", "image", "video", "document"]:
            if payload.get(chave):
                return True

            if isinstance(data, dict) and data.get(chave):
                return True

        return False

    except Exception:
        return False


def extrair_texto(payload):
    try:
        button_id = extrair_button_id(payload)

        if button_id:
            return button_id

        data = payload.get("data", {}) or {}

        candidatos = [
            payload.get("text", {}).get("message")
            if isinstance(payload.get("text"), dict) else None,

            payload.get("text")
            if isinstance(payload.get("text"), str) else None,

            payload.get("message")
            if isinstance(payload.get("message"), str) else None,

            payload.get("body"),
            payload.get("caption"),
            payload.get("messageBody"),
            payload.get("content"),

            payload.get("buttonsResponseMessage", {}).get("message")
            if isinstance(payload.get("buttonsResponseMessage"), dict) else None,

            payload.get("image", {}).get("caption")
            if isinstance(payload.get("image"), dict) else None,

            payload.get("video", {}).get("caption")
            if isinstance(payload.get("video"), dict) else None,

            payload.get("document", {}).get("caption")
            if isinstance(payload.get("document"), dict) else None,
        ]

        if isinstance(data, dict):
            data_message = data.get("message", {}) or {}

            candidatos.extend([
                data.get("text", {}).get("message")
                if isinstance(data.get("text"), dict) else None,

                data.get("text")
                if isinstance(data.get("text"), str) else None,

                data.get("message")
                if isinstance(data.get("message"), str) else None,

                data.get("body"),
                data.get("caption"),
                data.get("messageBody"),
                data.get("content"),

                data.get("buttonsResponseMessage", {}).get("message")
                if isinstance(data.get("buttonsResponseMessage"), dict) else None,

                data.get("image", {}).get("caption")
                if isinstance(data.get("image"), dict) else None,

                data.get("video", {}).get("caption")
                if isinstance(data.get("video"), dict) else None,

                data.get("document", {}).get("caption")
                if isinstance(data.get("document"), dict) else None,
            ])

            if isinstance(data_message, dict):
                candidatos.extend([
                    data_message.get("conversation"),
                    data_message.get("extendedTextMessage", {}).get("text")
                    if isinstance(data_message.get("extendedTextMessage"), dict) else None,

                    data_message.get("text", {}).get("message")
                    if isinstance(data_message.get("text"), dict) else None,

                    data_message.get("text")
                    if isinstance(data_message.get("text"), str) else None,

                    data_message.get("body"),
                    data_message.get("caption"),
                    data_message.get("messageBody"),
                    data_message.get("content"),
                ])

        for valor in candidatos:
            valor = limpar_texto(valor)
            if valor:
                return valor

        return ""

    except Exception as e:
        log_erro("Erro ao extrair texto Z-API:", repr(e))
        return ""


def extrair_message_id(payload):
    try:
        data = payload.get("data", {}) or {}

        message_id = (
            payload.get("messageId")
            or payload.get("messageID")
            or payload.get("zaapId")
            or payload.get("id")
        )

        if not message_id and isinstance(data, dict):
            message_id = (
                data.get("messageId")
                or data.get("messageID")
                or data.get("zaapId")
                or data.get("id")
            )

        if not message_id:
            telefone = extrair_telefone(payload)
            texto = extrair_texto(payload)
            tipo = str(payload.get("type") or payload.get("event") or "")

            timestamp = str(
                payload.get("momment")
                or payload.get("moment")
                or payload.get("timestamp")
                or payload.get("createdAt")
                or time.time()
            )

            message_id = f"{telefone}-{tipo}-{texto[:50]}-{timestamp}"

        return str(message_id or "").strip()

    except Exception as e:
        log_erro("Erro ao extrair message_id Z-API:", repr(e))
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
        message_id = str(message_id or "").strip()

        if not message_id:
            return

        if message_id in mensagens_processadas:
            return

        mensagens_processadas.add(message_id)
        fila_mensagens_processadas.append(message_id)

        while len(mensagens_processadas) > fila_mensagens_processadas.maxlen:
            antigo = fila_mensagens_processadas.popleft()
            mensagens_processadas.discard(antigo)

    except Exception as e:
        log_erro("Erro registrar_mensagem_processada:", repr(e))


def valor_verdadeiro(valor):
    try:
        if valor is True:
            return True

        texto = str(valor or "").strip().lower()

        return texto in ["true", "1", "sim", "yes", "y"]

    except Exception:
        return False


def evento_eh_do_proprio_bot(payload):
    try:
        data = payload.get("data", {}) or {}

        marcadores = [
            payload.get("fromMe"),
            payload.get("isFromMe"),
            payload.get("sentByMe"),
            payload.get("fromApi"),
            payload.get("isNewsletter"),
            payload.get("isStatusReply"),

            data.get("fromMe") if isinstance(data, dict) else None,
            data.get("isFromMe") if isinstance(data, dict) else None,
            data.get("sentByMe") if isinstance(data, dict) else None,
            data.get("fromApi") if isinstance(data, dict) else None,
            data.get("isNewsletter") if isinstance(data, dict) else None,
            data.get("isStatusReply") if isinstance(data, dict) else None,
        ]

        if any(valor_verdadeiro(v) for v in marcadores):
            return True

        phone = limpar_telefone(payload.get("phone"))
        connected = limpar_telefone(payload.get("connectedPhone"))

        if phone and connected and phone == connected:
            return True

        return False

    except Exception as e:
        log_erro("Erro ao validar evento do próprio bot:", repr(e))
        return False


def extrair_tipo_mensagem(payload):
    try:
        button_id = extrair_button_id(payload)

        if button_id:
            return "button"

        data = payload.get("data", {}) or {}

        if payload_tem_midia(payload, "audio"):
            return "audio"

        if payload_tem_midia(payload, "image"):
            return "image"

        if payload_tem_midia(payload, "video"):
            return "video"

        if payload_tem_midia(payload, "document"):
            return "document"

        tipo = (
            payload.get("type")
            or payload.get("messageType")
            or payload.get("typeMessage")
            or payload.get("event")
            or ""
        )

        if not tipo and isinstance(data, dict):
            tipo = (
                data.get("type")
                or data.get("messageType")
                or data.get("typeMessage")
                or data.get("event")
                or ""
            )

        tipo = str(tipo or "").strip().lower()
        texto = extrair_texto(payload)

        if tipo == "receivedcallback" and (texto or payload_tem_midia(payload)):
            if texto:
                return "text"
            return "media"

        callbacks = [
            "deliverycallback",
            "sentcallback",
            "readcallback",
            "statuscallback",
            "message-status",
            "messagestatus",
            "sentmessage",
            "deliveredmessage",
            "readmessage",
            "receivedack",
        ]

        if tipo in callbacks:
            return "callback"

        if ("callback" in tipo or "status" in tipo) and not texto and not payload_tem_midia(payload):
            return "callback"

        if "button" in tipo or "buttons" in tipo or "listresponse" in tipo:
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

        if texto:
            return "text"

        return "unknown"

    except Exception as e:
        log_erro("Erro ao extrair tipo de mensagem Z-API:", repr(e))
        return "unknown"


def evento_deve_ser_ignorado(payload):
    try:
        button_id = extrair_button_id(payload)

        if button_id:
            return False

        if evento_eh_do_proprio_bot(payload):
            log_info("Evento do próprio bot/API ignorado.")
            return True

        tipo = str(
            payload.get("type")
            or payload.get("messageType")
            or payload.get("typeMessage")
            or payload.get("event")
            or ""
        ).strip().lower()

        data = payload.get("data", {}) or {}

        tipo_data = ""
        if isinstance(data, dict):
            tipo_data = str(
                data.get("type")
                or data.get("messageType")
                or data.get("typeMessage")
                or data.get("event")
                or ""
            ).strip().lower()

        texto = extrair_texto(payload)
        tem_midia = payload_tem_midia(payload)

        if tipo == "receivedcallback" and (texto or tem_midia):
            return False

        if tipo_data == "receivedcallback" and (texto or tem_midia):
            return False

        eventos_ignorados = [
            "deliverycallback",
            "sentcallback",
            "readcallback",
            "statuscallback",
            "message-status",
            "messagestatus",
            "sentmessage",
            "deliveredmessage",
            "readmessage",
            "receivedack",
        ]

        if tipo in eventos_ignorados or tipo_data in eventos_ignorados:
            log_info("Callback Z-API ignorado:", tipo or tipo_data)
            return True

        if ("callback" in tipo or "status" in tipo) and not texto and not tem_midia:
            log_info("Callback Z-API ignorado:", tipo)
            return True

        if ("callback" in tipo_data or "status" in tipo_data) and not texto and not tem_midia:
            log_info("Callback Z-API ignorado:", tipo_data)
            return True

        return False

    except Exception as e:
        log_erro("Erro evento_deve_ser_ignorado:", repr(e))
        return False


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
        return "", "", "", "unknown"
# ==========================================
# ENVIO - Z-API WHATSAPP
# ==========================================
def zapi_configurada():
    return bool(ZAPI_INSTANCE_ID and ZAPI_TOKEN and ZAPI_CLIENT_TOKEN)


def resposta_zapi_sucesso(status_code, resposta):
    try:
        if status_code not in [200, 201, 202]:
            return False

        if isinstance(resposta, dict):
            if resposta.get("error") is True:
                return False

            if resposta.get("success") is False:
                return False

            if resposta.get("erro") is True:
                return False

            mensagem_erro = str(
                resposta.get("message")
                or resposta.get("msg")
                or resposta.get("errorMessage")
                or resposta.get("error")
                or ""
            ).lower()

            erros = [
                "not connected",
                "instance not connected",
                "unauthorized",
                "invalid token",
                "client-token",
                "forbidden",
                "bad request",
            ]

            if any(erro in mensagem_erro for erro in erros):
                return False

        return True

    except Exception:
        return status_code in [200, 201, 202]


def extrair_id_envio_zapi(resposta):
    try:
        if not isinstance(resposta, dict):
            return ""

        return (
            resposta.get("messageId")
            or resposta.get("messageID")
            or resposta.get("id")
            or resposta.get("zaapId")
            or resposta.get("message_id")
            or ""
        )

    except Exception:
        return ""


def normalizar_botoes_zapi(botoes=None):
    botoes_formatados = []

    try:
        for index, botao in enumerate((botoes or [])[:9], start=1):
            if not isinstance(botao, dict):
                continue

            label = limpar_texto(botao.get("label", ""))[:80]
            button_id = limpar_texto(
                botao.get("id")
                or botao.get("button_id")
                or botao.get("value")
                or f"OPCAO_{index}"
            )[:80]

            if not label:
                continue

            botoes_formatados.append({
                "id": button_id,
                "label": label,
            })

    except Exception as e:
        log_erro("Erro ao normalizar botões Z-API:", repr(e))

    return botoes_formatados


def formatar_botoes_para_texto(botoes=None):
    try:
        botoes_formatados = normalizar_botoes_zapi(botoes)

        if not botoes_formatados:
            return ""

        texto = "\n\n"

        for i, botao in enumerate(botoes_formatados, start=1):
            label = limpar_texto(botao.get("label", ""))
            if label:
                texto += f"{i}️⃣ {label}\n"

        texto += "\nDigite apenas o número da opção desejada."

        return texto

    except Exception:
        return ""


def enviar_mensagem_texto_zapi(telefone, mensagem):
    try:
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

        log_info("STATUS TEXTO Z-API:", response.status_code)
        log_info("RESPOSTA TEXTO Z-API:", resposta_json)

        if not resposta_zapi_sucesso(response.status_code, resposta_json):
            return False, resposta_json, ""

        return True, resposta_json, extrair_id_envio_zapi(resposta_json)

    except Exception as e:
        log_erro("Erro envio texto Z-API:", repr(e))
        return False, repr(e), ""


def enviar_mensagem_botoes_zapi(telefone, mensagem, botoes=None):
    try:
        mensagem_final = mensagem + formatar_botoes_para_texto(botoes)

        return enviar_mensagem_texto_zapi(
            telefone=telefone,
            mensagem=mensagem_final,
        )

    except Exception as e:
        log_erro("Erro fallback botões para texto Z-API:", repr(e))
        return False, repr(e), ""


def enviar_mensagem(telefone, mensagem, botoes=None):
    try:
        telefone = limpar_telefone(telefone)
        mensagem = str(mensagem or "").strip()

        if not telefone:
            log_erro("Telefone inválido para envio de mensagem.")
            return False

        if not mensagem:
            log_erro("Mensagem vazia não enviada.")
            return False

        if not zapi_configurada():
            log_erro("Z-API não configurada corretamente.")
            return False

        botoes = botoes or []

        if botoes:
            mensagem = mensagem + formatar_botoes_para_texto(botoes)

        enviado_texto, resposta_texto, id_texto = enviar_mensagem_texto_zapi(
            telefone=telefone,
            mensagem=mensagem,
        )

        if not enviado_texto:
            log_erro("Falha envio mensagem Z-API:", resposta_texto)
            return False

        return True

    except Exception as e:
        log_erro("Erro envio mensagem Z-API:", repr(e))
        return False


def enviar_mensagem_botoes(telefone, mensagem, botoes=None):
    return enviar_mensagem(
        telefone=telefone,
        mensagem=mensagem,
        botoes=botoes or []
    )


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

        arquivo = os.path.basename(str(arquivo).strip().lstrip("/"))

        if not arquivo.lower().endswith(".pdf"):
            log_erro("Arquivo informado não é PDF:", arquivo)
            return False

        pasta_pdfs = os.path.join(app.root_path, "static", "pdfs")
        caminho_pdf = os.path.join(pasta_pdfs, arquivo)

        if not os.path.exists(caminho_pdf):
            log_erro("PDF não encontrado localmente:", caminho_pdf)
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

        if not resposta_zapi_sucesso(response.status_code, resposta_json):
            log_erro(
                "Falha envio PDF Z-API:",
                response.status_code,
                resposta_json
            )
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
    etapa="",
    dados=None,
    atendimento_humano=False,
    concluido=False,
    origem="BOT",
    observacao="",
    intencao_ia="",
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

        data_agendada = limpar_texto(
            base.get("data_agendada", "") or base.get("data", "")
        )

        horario = limpar_texto(base.get("horario", ""))

        venda_adicional = formatar_itens_adicionais_para_salvar(
            base.get("venda_adicional", "")
        )

        itens = formatar_itens_adicionais_para_salvar(
            base.get("itens", "") or venda_adicional
        )

        valores_vazios = [
            "NENHUM",
            "NAO",
            "NÃO",
            "SEM ITEM",
            "SEM ITENS",
            "2",
            "-",
            "OK",
            "SEM",
            "NADA",
        ]

        if venda_adicional.strip().upper() in valores_vazios:
            venda_adicional = ""

        if itens.strip().upper() in valores_vazios:
            itens = ""

        agora_db = agora_datetime()

        atendimento = Atendimento()

        def setar(campo, valor):
            try:
                if hasattr(atendimento, campo):
                    setattr(atendimento, campo, valor)
            except Exception as e:
                log_erro(
                    f"Erro ao setar campo {campo} em Atendimento:",
                    repr(e)
                )

        setar("telefone", telefone)
        setar("nome", nome)
        setar("setor", limpar_texto(setor))
        setar("modelo", modelo)
        setar("ano", ano)
        setar("revisao", revisao)
        setar("cpf", cpf)
        setar("dia_semana", nome_dia(dia) if dia else "")
        setar("data_agendada", data_agendada)
        setar("horario", horario)
        setar("itens", itens)
        setar("venda_adicional", venda_adicional)

        observacoes = limpar_texto(
            observacao
            or base.get("observacoes", "")
            or base.get("observacao", "")
        )

        setar("observacao", observacoes)
        setar("observacoes", observacoes)
        setar("quantidade", limpar_texto(base.get("quantidade", "")))

        pre_orcamento = base.get("pre_orcamento", {})

        if pre_orcamento:
            try:
                setar(
                    "pre_orcamento_json",
                    json.dumps(pre_orcamento, ensure_ascii=False),
                )
            except Exception:
                setar("pre_orcamento_json", limpar_texto(pre_orcamento))

        setar(
            "origem",
            limpar_texto(
                origem
                or base.get("origem", "BOT")
                or "BOT"
            )
        )

        setar("status", normalizar_status(status))
        setar("status_comercial", limpar_texto(base.get("status_comercial", "")))

        setar(
            "etapa",
            limpar_texto(
                etapa or base.get("etapa", "")
            )
        )

        setar("atendimento_humano", bool(atendimento_humano))
        setar("concluido", bool(concluido))

        opcao_menu = limpar_texto(
            base.get("opcao_menu", "")
            or base.get("button_id", "")
        )

        setar("button_id", opcao_menu)

        setar(
            "tipo_mensagem",
            limpar_texto(base.get("tipo_mensagem", "text"))
        )

        setar(
            "intencao_ia",
            limpar_texto(
                intencao_ia
                or base.get("intencao_ia", "")
            )
        )

        setar(
            "resposta_ia",
            limpar_texto(base.get("resposta_ia", "") or base.get("resposta", ""))
        )

        setar(
            "confianca_ia",
            limpar_texto(base.get("confianca_ia", "") or base.get("confianca", ""))
        )

        setar(
            "assunto_ia",
            limpar_texto(base.get("assunto_ia", "") or base.get("assunto", ""))
        )

        setar(
            "fonte_ia",
            limpar_texto(base.get("fonte_ia", "") or base.get("fonte", ""))
        )

        setar(
            "modelo_ia",
            limpar_texto(base.get("modelo_ia", ""))
        )

        setar(
            "pergunta_ia",
            limpar_texto(base.get("pergunta_ia", "") or base.get("pergunta", ""))
        )

        setar(
            "id_envio_zapi",
            limpar_texto(base.get("id_envio_zapi", ""))
        )

        setar(
            "status_retorno",
            limpar_texto(base.get("status_retorno", ""))
        )

        setar(
            "proxima_acao",
            limpar_texto(base.get("proxima_acao", ""))
        )

        setar(
            "nivel_interesse",
            limpar_texto(base.get("nivel_interesse", ""))
        )

        setar(
            "temperatura_lead",
            limpar_texto(base.get("temperatura_lead", ""))
        )

        setar(
            "produto_interesse",
            limpar_texto(base.get("produto_interesse", ""))
        )

        setar(
            "oportunidade_comercial",
            bool(base.get("oportunidade_comercial", False))
        )

        setar(
            "cliente_recuperado",
            bool(base.get("cliente_recuperado", False))
        )

        try:
            setar(
                "followup_nivel",
                int(base.get("followup_nivel", 0) or 0)
            )
        except Exception:
            setar("followup_nivel", 0)

        setar("followup_enviado", bool(base.get("followup_enviado", False)))
        setar("followup_respondido", bool(base.get("followup_respondido", False)))
        setar("followup_recuperado", bool(base.get("followup_recuperado", False)))

        data_followup = base.get("data_followup")

        if isinstance(data_followup, datetime):
            setar("data_followup", data_followup)

        setar(
            "ultima_acao_ia",
            limpar_texto(base.get("ultima_acao_ia", ""))
        )

        try:
            setar(
                "valor_estimado",
                float(base.get("valor_estimado", 0) or 0)
            )
        except Exception:
            setar("valor_estimado", 0)

        setar(
            "origem_ia",
            limpar_texto(base.get("origem_ia", ""))
        )

        ultima_msg = limpar_texto(base.get("ultima_mensagem_cliente", ""))

        setar("ultima_interacao", agora_db)
        setar("ultima_mensagem_cliente", ultima_msg)
        setar("data", agora_db)

        db.add(atendimento)
        db.commit()

        log_info("Evento salvo:", telefone, setor, etapa)

        try:
            dados_rpa = dict(base)
            dados_rpa.update({
                "setor": limpar_texto(setor),
                "status": normalizar_status(status),
                "etapa": limpar_texto(etapa or base.get("etapa", "")),
                "nome": nome,
                "modelo": modelo,
                "cpf": cpf,
                "itens": itens,
                "produto_interesse": limpar_texto(base.get("produto_interesse", "")),
                "intencao_ia": limpar_texto(intencao_ia or base.get("intencao_ia", "")),
                "temperatura_lead": limpar_texto(base.get("temperatura_lead", "")),
                "oportunidade_comercial": bool(base.get("oportunidade_comercial", False)),
                "status_comercial": limpar_texto(base.get("status_comercial", "")),
                "ultima_mensagem_cliente": ultima_msg,
            })

            deve_criar_rpa = (
                bool(dados_rpa.get("oportunidade_comercial", False))
                or normalizar_texto(dados_rpa.get("temperatura_lead", "")) == "quente"
                or normalizar_texto(dados_rpa.get("intencao_ia", "")) in [
                    "orcamento",
                    "pecas",
                    "acessorios",
                    "garantia",
                    "acompanhar_garantia",
                    "atacado",
                ]
                or any(
                    termo in normalizar_texto(ultima_msg)
                    for termo in [
                        "orcamento",
                        "orçamento",
                        "cotacao",
                        "cotação",
                        "garantia",
                        "status do agendamento",
                        "os",
                    ]
                )
            )

            if deve_criar_rpa:
                criar_tarefa_rpa_de_atendimento(telefone, dados_rpa, ultima_msg)

        except Exception as e:
            log_erro("[RPA] Erro ao avaliar tarefa do atendimento:", repr(e))

        try:
            atualizar_memoria_cliente(
                telefone,
                {
                    "nome": nome,
                    "modelo": modelo,
                    "ano": ano,
                    "ultima_revisao": revisao,
                    "data_ultima_revisao": data_agendada,
                    "nivel_interesse": limpar_texto(base.get("nivel_interesse", "")),
                    "setor_recente": limpar_texto(setor),
                    "status_atual": normalizar_status(status),
                    "observacoes": observacoes,
                },
            )
        except Exception as e:
            log_erro("Erro ao atualizar memória do cliente:", repr(e))

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
def botoes_menu_principal():
    return [
        {"id": "OPCAO_1", "label": "Agendar Revisão"},
        {"id": "OPCAO_2", "label": "Peças"},
        {"id": "OPCAO_3", "label": "Acessórios"},
        {"id": "OPCAO_4", "label": "Garantia"},
        {"id": "OPCAO_5", "label": "Logista / Atacado"},
        {"id": "OPCAO_6", "label": "Dúvidas"},
        {"id": "OPCAO_7", "label": "Atendimento Humano"},
    ]


def enviar_menu(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    try:
        desativar_atendimento_humano(telefone)
    except Exception:
        pass

    iniciar_cliente(telefone)

    clientes[telefone]["etapa"] = "menu"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["ultima_interacao"] = agora()
    clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO
    clientes[telefone]["categoria_duvida"] = ""
    clientes[telefone]["etapa_retorno_duvida"] = ""

    return enviar_mensagem(telefone, menu_inicial())


def enviar_menu_principal(telefone):
    return enviar_menu(telefone)


def menu_garantia():
    return (
        "🛡️ *Garantia Motoshow Yamaha*\n\n"
        "1️⃣ Nova Solicitação\n"
        "2️⃣ Acompanhar Garantia\n"
        "3️⃣ Falar com Atendente\n"
        "4️⃣ Voltar ao Menu Principal\n\n"
        "Digite apenas o número da opção desejada."
    )


def enviar_menu_garantia(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["etapa"] = "garantia_menu"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO
    clientes[telefone]["ultima_interacao"] = agora()

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Garantia",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="garantia_menu",
        dados=clientes[telefone],
        atendimento_humano=False,
        concluido=False,
        origem=clientes[telefone].get("origem", "BOT"),
    )

    return enviar_mensagem(telefone, menu_garantia())


def iniciar_fluxo_garantia(telefone):
    iniciar_cliente(telefone)
    carregar_memoria_cliente_no_estado(telefone)
    clientes[telefone]["intencao_ia"] = "garantia"
    clientes[telefone]["ultima_interacao"] = agora()
    clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["nome"] = ""
    clientes[telefone]["modelo"] = ""
    clientes[telefone]["cpf"] = ""
    clientes[telefone]["ano"] = ""
    clientes[telefone]["km_atual"] = ""
    clientes[telefone]["observacao"] = ""

    enviar_mensagem_memoria_cliente(telefone, "garantia")
    return enviar_menu_garantia(telefone)


def montar_resumo_solicitacao_garantia(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return "Não consegui montar o resumo da solicitação de garantia."

    iniciar_cliente(telefone)
    dados = clientes.get(telefone, {})

    return (
        "📋 *Resumo da Solicitação de Garantia*\n\n"
        f"👤 Nome: {dados.get('nome', '-') or '-'}\n"
        f"🏍️ Modelo: {dados.get('modelo', '-') or '-'}\n"
        f"📅 Ano: {dados.get('ano', '-') or '-'}\n"
        f"🔢 Quilometragem atual: {dados.get('km_atual', '-') or '-'}\n"
        f"📝 Descrição do problema: {dados.get('observacao', '-') or '-'}\n\n"
        "Sua solicitação foi registrada e será encaminhada à equipe de garantia.\n"
        "Digite *menu* para voltar ao menu principal quando quiser."
    )


def montar_resumo_acompanhamento_garantia(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return "Não consegui montar o resumo do acompanhamento de garantia."

    iniciar_cliente(telefone)
    dados = clientes.get(telefone, {})

    return (
        "📋 *Resumo do Acompanhamento de Garantia*\n\n"
        f"👤 Nome: {dados.get('nome', '-') or '-'}\n"
        f"🏍️ Modelo: {dados.get('modelo', '-') or '-'}\n"
        f"📄 CPF: {dados.get('cpf', '-') or '-'}\n"
        f"📝 Descrição / protocolo: {dados.get('observacao', '-') or '-'}\n\n"
        "Sua solicitação foi registrada e nossa equipe de garantia irá verificar.\n"
        "Digite *menu* para voltar ao menu principal quando quiser."
    )


def finalizar_garantia_com_humano(telefone, etapa_evento, resumo):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["etapa"] = "atendimento_humano"
    clientes[telefone]["ultima_interacao"] = agora()

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Garantia",
        status=STATUS_ATENDIMENTO_HUMANO,
        etapa=etapa_evento,
        dados=clientes[telefone],
        atendimento_humano=True,
        concluido=False,
        origem=clientes[telefone].get("origem", "BOT"),
    )

    enviar_mensagem(telefone, resumo)
    ativar_atendimento_humano(telefone)
    return True


def consultar_garantia_por_cpf_fluxo(telefone, cpf):
    telefone = limpar_telefone(telefone)
    cpf_limpo = limpar_cpf(cpf)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    if len(cpf_limpo) != 11:
        enviar_mensagem(telefone, "Informe um *CPF válido* com 11 números.")
        return True

    clientes[telefone]["cpf"] = cpf_limpo
    ordens = buscar_os_garantia_por_cpf(cpf_limpo)

    if len(ordens) == 1:
        clientes[telefone]["garantia_os_sances"] = []
        clientes[telefone]["etapa"] = "menu"

        resposta = montar_resposta_status_garantia(ordens[0])
        enviar_mensagem(telefone, resposta)

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Garantia",
            status=STATUS_FINALIZADO,
            etapa="garantia_consulta_sances",
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=True,
            origem=clientes[telefone].get("origem", "BOT"),
        )
        return True

    if len(ordens) > 1:
        clientes[telefone]["garantia_os_sances"] = ordens[:9]
        clientes[telefone]["etapa"] = "garantia_escolher_os"
        enviar_mensagem(telefone, montar_lista_os_garantia(ordens))
        return True

    clientes[telefone]["garantia_os_sances"] = []
    clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["etapa"] = "atendimento_humano"

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Garantia",
        status=STATUS_ATENDIMENTO_HUMANO,
        etapa="garantia_consulta_nao_encontrada",
        dados=clientes[telefone],
        atendimento_humano=True,
        concluido=False,
        origem=clientes[telefone].get("origem", "BOT"),
    )

    enviar_mensagem(
        telefone,
        "Não encontrei processo de garantia em aberto para este CPF. Vou direcionar você para um atendente."
    )
    ativar_atendimento_humano(telefone)
    return True


def processar_fluxo_garantia(telefone, texto, texto_opcao=""):
    telefone = limpar_telefone(telefone)
    texto = limpar_texto(texto)
    texto_opcao = limpar_opcao(texto_opcao or texto)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    etapa = limpar_texto(clientes[telefone].get("etapa", "")).lower()
    clientes[telefone]["intencao_ia"] = "garantia"
    clientes[telefone]["ultima_interacao"] = agora()

    if etapa == "garantia_menu":
        if texto_opcao == "1":
            clientes[telefone]["etapa"] = "garantia_nova_nome"
            clientes[telefone]["nome"] = ""
            clientes[telefone]["modelo"] = ""
            clientes[telefone]["ano"] = ""
            clientes[telefone]["km_atual"] = ""
            clientes[telefone]["observacao"] = ""
            enviar_mensagem(telefone, "Informe seu *nome completo*.")
            return True

        if texto_opcao == "2":
            clientes[telefone]["etapa"] = "garantia_consulta_cpf"
            clientes[telefone]["nome"] = ""
            clientes[telefone]["modelo"] = ""
            clientes[telefone]["cpf"] = ""
            clientes[telefone]["observacao"] = ""
            clientes[telefone]["garantia_os_sances"] = []
            enviar_mensagem(telefone, "Informe seu *CPF* com 11 números para consultar a garantia.")
            return True

        if texto_opcao == "3":
            clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
            clientes[telefone]["atendimento_humano"] = True
            clientes[telefone]["etapa"] = "atendimento_humano"

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Garantia",
                status=STATUS_ATENDIMENTO_HUMANO,
                etapa="garantia_atendente",
                dados=clientes[telefone],
                atendimento_humano=True,
                concluido=False,
                origem=clientes[telefone].get("origem", "BOT"),
            )

            enviar_mensagem(
                telefone,
                "Atendimento de garantia encaminhado para um consultor.\n\n"
                "Quando quiser voltar ao menu automatico, envie *menu*."
            )
            ativar_atendimento_humano(telefone)
            return True

        if texto_opcao == "4":
            enviar_menu_principal(telefone)
            return True

        enviar_menu_garantia(telefone)
        return True

    if etapa == "garantia_nova_nome":
        clientes[telefone]["nome"] = texto
        clientes[telefone]["etapa"] = "garantia_nova_modelo"
        enviar_mensagem(telefone, "Informe o *modelo da moto*.")
        return True

    if etapa == "garantia_nova_modelo":
        clientes[telefone]["modelo"] = texto.upper()
        clientes[telefone]["etapa"] = "garantia_nova_ano"
        enviar_mensagem(telefone, "Informe o *ano da moto*.")
        return True

    if etapa == "garantia_nova_ano":
        clientes[telefone]["ano"] = texto
        clientes[telefone]["etapa"] = "garantia_nova_km"
        enviar_mensagem(telefone, "Informe a *quilometragem atual*.")
        return True

    if etapa == "garantia_nova_km":
        clientes[telefone]["km_atual"] = texto
        clientes[telefone]["etapa"] = "garantia_nova_descricao"
        enviar_mensagem(telefone, "Descreva o *problema apresentado*.")
        return True

    if etapa == "garantia_nova_descricao":
        clientes[telefone]["observacao"] = texto
        resumo = montar_resumo_solicitacao_garantia(telefone)
        finalizar_garantia_com_humano(
            telefone=telefone,
            etapa_evento="garantia_nova_solicitacao",
            resumo=resumo,
        )
        return True

    if etapa == "garantia_acompanhar_nome":
        clientes[telefone]["nome"] = texto
        clientes[telefone]["etapa"] = "garantia_acompanhar_modelo"
        enviar_mensagem(telefone, "Informe o *modelo da moto*.")
        return True

    if etapa == "garantia_acompanhar_modelo":
        clientes[telefone]["modelo"] = texto.upper()
        clientes[telefone]["etapa"] = "garantia_acompanhar_cpf"
        enviar_mensagem(telefone, "Informe seu *CPF*.")
        return True

    if etapa == "garantia_acompanhar_cpf":
        return consultar_garantia_por_cpf_fluxo(telefone, texto)

    if etapa == "garantia_acompanhar_descricao":
        clientes[telefone]["observacao"] = texto
        resumo = montar_resumo_acompanhamento_garantia(telefone)
        finalizar_garantia_com_humano(
            telefone=telefone,
            etapa_evento="garantia_acompanhamento",
            resumo=resumo,
        )
        return True

    if etapa == "garantia_consulta_cpf":
        return consultar_garantia_por_cpf_fluxo(telefone, texto)

    if etapa == "garantia_escolher_os":
        ordens = clientes[telefone].get("garantia_os_sances") or []

        try:
            indice = int(texto_opcao)
        except Exception:
            indice = 0

        if indice < 1 or indice > len(ordens):
            enviar_mensagem(telefone, montar_lista_os_garantia(ordens))
            return True

        os_data = ordens[indice - 1]
        clientes[telefone]["garantia_os_sances"] = []
        clientes[telefone]["etapa"] = "menu"

        enviar_mensagem(telefone, montar_resposta_status_garantia(os_data))

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Garantia",
            status=STATUS_FINALIZADO,
            etapa="garantia_consulta_sances",
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=True,
            origem=clientes[telefone].get("origem", "BOT"),
        )
        return True

    return False


def iniciar_fluxo_pecas(telefone, texto_inicial=""):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)
    carregar_memoria_cliente_no_estado(telefone)

    clientes[telefone]["etapa"] = "pecas"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["observacao"] = limpar_texto(texto_inicial)
    clientes[telefone]["ultima_interacao"] = agora()
    clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Peças",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="pecas_iniciado",
        dados=clientes[telefone],
        atendimento_humano=False,
        concluido=False,
    )

    enviar_mensagem_memoria_cliente(telefone, "pecas")

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
    carregar_memoria_cliente_no_estado(telefone)

    clientes[telefone]["etapa"] = "acessorios_modelo"
    clientes[telefone]["atendimento_humano"] = False
    clientes[telefone]["ultima_interacao"] = agora()
    clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO
    clientes[telefone]["observacao"] = ""
    clientes[telefone]["modelo"] = ""
    clientes[telefone]["itens"] = ""
    clientes[telefone]["venda_adicional"] = ""
    clientes[telefone]["acessorio_desejado"] = ""
    clientes[telefone]["intencao_ia"] = "acessorios"

    salvar_evento_atendimento(
        telefone=telefone,
        setor="Acessórios",
        status=STATUS_NOVO_ATENDIMENTO,
        etapa="acessorios_iniciado",
        dados=clientes[telefone],
        atendimento_humano=False,
        concluido=False,
    )

    texto_inicial = limpar_texto(texto_inicial)

    if texto_inicial:
        modelo_informado = texto_inicial.upper()

        clientes[telefone]["modelo"] = modelo_informado
        clientes[telefone]["etapa"] = "acessorios_orcamento"
        clientes[telefone]["ultima_interacao"] = agora()
        clientes[telefone]["proxima_acao"] = "ACESSORIOS_ORCAMENTO"

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
            "Qual acessório você deseja receber orçamento? 😊"
        )

        return True

    enviar_mensagem_memoria_cliente(telefone, "acessorios")

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
        "Digite apenas o número da opção desejada."
    )


def botoes_menu_duvidas():
    return [
        {"id": "DUVIDAS_REVISAO", "label": "Dúvidas Revisões"},
        {"id": "DUVIDAS_GARANTIA", "label": "Dúvidas Garantia"},
        {"id": "MENU", "label": "Voltar ao menu"},
    ]


def enviar_menu_duvidas(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["etapa"] = "duvidas_menu"
    clientes[telefone]["categoria_duvida"] = ""
    clientes[telefone]["ultima_interacao"] = agora()
    clientes[telefone]["atendimento_humano"] = False

    return enviar_mensagem(telefone, menu_duvidas())


MODELOS_DUVIDAS_MANUAL = {
    "crosser": ["crosser", "xtz 150"],
    "crypton": ["crypton"],
    "factor": ["factor"],
    "factor 125": ["factor 125", "factor125"],
    "factor 150": ["factor 150", "factor150"],
    "fz15": ["fz15", "fz 15", "fazer 150"],
    "fz25": ["fz25", "fz 25", "fazer 250", "fazer"],
    "fluo": ["fluo"],
    "lander": ["lander", "lander 250", "xtz 250"],
    "mt03": ["mt03", "mt 03", "mt-03"],
    "mt07": ["mt07", "mt 07", "mt-07"],
    "nmax": ["nmax"],
    "r15": ["r15", "r 15"],
    "r3": ["r3", "r 3"],
}


def identificar_modelo_duvida_manual(pergunta="", modelo_salvo=""):
    texto = normalizar_texto(f"{pergunta} {modelo_salvo}")

    if not texto:
        return ""

    for modelo, aliases in sorted(MODELOS_DUVIDAS_MANUAL.items(), key=lambda item: len(item[0]), reverse=True):
        for alias in aliases:
            alias_norm = normalizar_texto(alias)

            if alias_norm and re.search(rf"(^|\s){re.escape(alias_norm)}($|\s)", texto):
                return modelo

    return limpar_texto(modelo_salvo)


def resposta_duvida_manual_segura(modelo, pergunta):
    funcao_resposta = responder_duvida_manual_com_ia or responder_duvida_manual

    if not funcao_resposta:
        return None

    try:
        resultado = funcao_resposta(modelo, pergunta)

        if not isinstance(resultado, dict):
            return None

        fontes_seguras = {
            "manual_pdf",
            "manual_pdf_ia",
            "manual_pdf_resumo_local",
        }

        if resultado.get("encontrou") and resultado.get("fonte") in fontes_seguras:
            resposta = limpar_texto(resultado.get("resposta", ""))
            return resposta or None

        return None

    except Exception as e:
        log_erro("Erro ao consultar manual PDF:", repr(e))
        return None


def processar_pergunta_duvida_manual(telefone, texto, categoria="manual"):
    telefone = limpar_telefone(telefone)
    texto = limpar_texto(texto)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["intencao_ia"] = "duvidas"
    clientes[telefone]["categoria_duvida"] = categoria or "manual"
    clientes[telefone]["ultima_interacao"] = agora()

    modelo_duvida = identificar_modelo_duvida_manual(
        pergunta=texto,
        modelo_salvo=(
            clientes[telefone].get("modelo", "")
            or clientes[telefone].get("modelo_memoria", "")
            or (clientes[telefone].get("memoria_cliente", {}) or {}).get("modelo", "")
        ),
    )

    resposta = resposta_duvida_manual_segura(
        modelo=modelo_duvida,
        pergunta=texto,
    )

    salvar_duvida_dashboard(
        telefone=telefone,
        categoria=categoria or "manual",
        pergunta=texto,
        resposta=resposta or "",
    )

    if not resposta:
        mensagem_sem_resposta = (
            "Não encontrei essa informação com segurança no manual. "
            "Vou encaminhar para um consultor te ajudar melhor. 🤝"
        )

        enviar_mensagem(telefone, mensagem_sem_resposta)
        ativar_atendimento_humano(telefone)
        return True

    enviar_mensagem(telefone, resposta)
    enviar_duvida_retorno_fluxo(telefone)
    return True


def montar_mensagem_horarios(lista):
    if not lista:
        return "⚠️ No momento não encontrei horários disponíveis para essa opção."

    msg = "⏰ *Estes são os horários disponíveis:*\n\n"

    for i, h in enumerate(lista, start=1):
        msg += f"{i}️⃣ {h}\n"

    msg += "\nMe responda com o *número do horário* que você prefere."

    return msg
# ==========================================
# VENDA ADICIONAL IA - FASE 1
# ==========================================
def montar_mensagem_venda_adicional(telefone=""):
    try:
        telefone = limpar_telefone(telefone)

        modelo = ""
        revisao = ""
        km_atual = ""

        if telefone and telefone in clientes:
            modelo = clientes[telefone].get("modelo", "")
            revisao = clientes[telefone].get("revisao", "")
            km_atual = clientes[telefone].get("km_atual", "")

        if gerar_mensagem_venda_adicional:
            mensagem_ia = gerar_mensagem_venda_adicional(
                modelo=modelo,
                revisao=revisao,
                km_atual=km_atual
            )

            if mensagem_ia:
                return (
                    "🛒 *Venda adicional inteligente*\n\n"
                    f"{mensagem_ia}\n\n"
                    "Digite o item desejado ou responda:\n\n"
                    "1️⃣ Sim, incluir avaliação\n"
                    "2️⃣ Não, somente revisão\n\n"
                    "Digite apenas o número da opção desejada."
                )

    except Exception as e:
        log_erro("Erro montar_mensagem_venda_adicional:", repr(e))

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

    if not telefone:
        return "Não consegui montar o resumo do agendamento."

    iniciar_cliente(telefone)
    dados = clientes.get(telefone, {})

    itens = formatar_itens_adicionais_para_salvar(
        dados.get("venda_adicional", "") or dados.get("itens", "")
    )

    observacao = dados.get("observacao") or "Nenhuma"
    tipo_atendimento = dados.get("tipo_atendimento") or "Não informado"

    if limpar_texto(itens).upper() in [
        "", "NENHUM", "NAO", "NÃO", "SEM ITEM", "SEM ITENS", "2", "OK", "SEM", "NADA"
    ]:
        itens = "Nenhum"

    if not limpar_texto(observacao) or limpar_texto(observacao) == "2":
        observacao = "Nenhuma"

    revisao = limpar_texto(dados.get("revisao", "-"))
    revisao_formatada = f"{revisao}ª" if revisao not in ["", "-"] else "-"

    return (
        "📋 *Confirmação do seu agendamento*\n\n"
        f"👤 *Nome:* {dados.get('nome', '-') or '-'}\n"
        f"📄 *CPF:* {dados.get('cpf', '-') or '-'}\n"
        f"🏍️ *Modelo:* {dados.get('modelo', '-') or '-'}\n"
        f"🔢 *Placa/Chassi:* {dados.get('placa') or dados.get('chassi') or '-'}\n"
        f"📅 *Ano:* {dados.get('ano', '-') or '-'}\n"
        f"🔢 *KM:* {dados.get('km_atual', '-') or '-'}\n"
        f"🔧 *Revisão:* {revisao_formatada}\n"
        f"📍 *Dia:* {dados.get('dia_texto', '-') or '-'}\n"
        f"📆 *Data:* {dados.get('data', '-') or '-'}\n"
        f"⏰ *Horário:* {dados.get('horario', '-') or '-'}\n"
        f"🚶 *Atendimento:* {tipo_atendimento}\n"
        f"🛒 *Adicionais:* {itens}\n"
        f"📝 *Observação:* {observacao}\n\n"
        "Confirme digitando:\n\n"
        "1️⃣ Confirmar ✅\n"
        "2️⃣ Corrigir\n\n"
        "Digite apenas o número da opção desejada."
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

    if etapa == "revisao_placa_chassi":
        return (
            "Não consegui localizar sua moto automaticamente pelo CPF.\n\n"
            "Para enviar o agendamento ao Sances, informe a *placa* ou o *chassi* da moto."
        )

    if etapa == "revisao_ano":
        return "Certo 👍\n\nMe informe agora o *ano da sua moto*."

    if etapa == "revisao_km":
        return "Ótimo.\n\nMe informe a *quilometragem atual da moto*."

    if etapa == "revisao_revisao":
        return (
            "🛠️ *Qual revisão você deseja agendar?*\n\n"
            "1️⃣ 1ª Revisão\n"
            "2️⃣ 2ª Revisão\n"
            "3️⃣ 3ª Revisão\n"
            "4️⃣ 4ª Revisão\n"
            "5️⃣ 5ª Revisão ou acima\n\n"
            "Digite apenas o número da revisão."
        )

    if etapa == "revisao_dia":
        return (
            "📅 *Qual dia você prefere?*\n\n"
            "1️⃣ Segunda\n"
            "2️⃣ Terça\n"
            "3️⃣ Quarta\n"
            "4️⃣ Quinta\n"
            "5️⃣ Sexta\n"
            "6️⃣ Sábado\n\n"
            "Digite apenas o número do dia."
        )

    if etapa == "revisao_data":
        return "📆 Perfeito.\n\nAgora me informe a *data desejada* no formato *dd/mm/aaaa*."

    if etapa == "revisao_horario":
        return "⏰ Agora escolha um dos horários disponíveis enviados acima."

    if etapa == "revisao_tipo_atendimento":
        return (
            "🏢 Me diga como será seu atendimento:\n\n"
            "1️⃣ Vou aguardar na concessionária\n"
            "2️⃣ Vou deixar a moto e retirar depois\n\n"
            "Digite apenas o número da opção desejada."
        )

    if etapa == "revisao_venda":
        return montar_mensagem_venda_adicional(telefone)

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
# ENVIO ETAPAS REVISÃO
# ==========================================
def enviar_mensagem_etapa_revisao(telefone, etapa):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["ultima_interacao"] = agora()
    clientes[telefone]["etapa"] = etapa

    try:
        mensagem = mensagem_por_etapa_revisao(telefone, etapa)

        enviado = enviar_mensagem(
            telefone,
            mensagem
        )

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Revisão",
            status=obter_status_cliente(telefone),
            etapa=etapa,
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=False,
        )

        return enviado

    except Exception as e:
        log_erro("Erro enviar_mensagem_etapa_revisao:", repr(e))
        return False

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


def revisao_por_km_aproximado(km):
    try:
        km_int = int(re.sub(r"\D", "", str(km or "")))

        if not km_int:
            return ""

        if 900 <= km_int <= 1100:
            return "1"

        if 4500 <= km_int <= 5500:
            return "2"

        if 9500 <= km_int <= 10500:
            return "3"

        if 14500 <= km_int <= 15500:
            return "4"

        if km_int >= 19000:
            return "5"

        return ""

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

    etapa_atual = limpar_texto(dados.get("etapa", "")).lower()

    opcao_menu = limpar_texto(
        dados_extraidos.get("opcao_menu")
        or dados_extraidos.get("botao_zapi")
        or dados_extraidos.get("button_id")
        or ""
    )

    opcao_menu_normalizada = normalizar_opcao_menu(opcao_menu)

    if opcao_menu_normalizada:
        dados["opcao_menu"] = opcao_menu_normalizada
        dados["button_id"] = opcao_menu_normalizada
    elif opcao_menu:
        dados["opcao_menu"] = opcao_menu
        dados["button_id"] = opcao_menu

    modelo = limpar_texto(dados_extraidos.get("modelo"))
    nome = limpar_texto(dados_extraidos.get("nome"))
    cpf = limpar_cpf(dados_extraidos.get("cpf"))
    ano = limpar_texto(dados_extraidos.get("ano"))
    placa = limpar_texto(dados_extraidos.get("placa")).upper()
    chassi = limpar_texto(dados_extraidos.get("chassi")).upper()

    revisao_bruta = limpar_texto(dados_extraidos.get("revisao"))
    revisao = normalizar_revisao_para_fluxo(revisao_bruta)

    km_atual = limpar_texto(
        dados_extraidos.get("km_atual")
        or dados_extraidos.get("km")
        or ""
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

    if normalizar_opcao_menu(observacao):
        observacao = ""

    if not revisao and km_atual:
        revisao = revisao_por_km_aproximado(km_atual)

    if dia_texto in ["1", "2", "3", "4", "5", "6"]:
        dia_numero = dia_texto
    else:
        dia_numero = numero_dia_por_texto(dia_texto) if dia_texto else ""

    etapas_modelo = ["menu", "revisao_modelo", "acessorios_modelo", "pecas"]
    etapas_nome = ["revisao_nome", "menu"]
    etapas_cpf = ["revisao_cpf", "menu"]
    etapas_ano = ["revisao_ano", "menu", "pecas"]
    etapas_km = ["revisao_km", "menu"]
    etapas_revisao = ["revisao_revisao", "menu"]
    etapas_dia = ["revisao_dia", "menu"]
    etapas_data = ["revisao_data", "menu"]
    etapas_horario = ["revisao_horario", "menu"]
    etapas_venda = ["revisao_venda", "menu"]
    etapas_observacao = ["revisao_observacao", "menu", "pecas", "acessorios_orcamento"]
    etapas_tipo = ["revisao_tipo_atendimento", "menu"]

    if modelo and not dados.get("modelo") and etapa_atual in etapas_modelo:
        dados["modelo"] = modelo.upper()

    if nome and not dados.get("nome") and etapa_atual in etapas_nome:
        dados["nome"] = nome.upper()

    if cpf and len(cpf) == 11 and not dados.get("cpf") and etapa_atual in etapas_cpf:
        dados["cpf"] = cpf

    if placa and not dados.get("placa"):
        dados["placa"] = placa

    if chassi and not dados.get("chassi"):
        dados["chassi"] = chassi

    if ano and not dados.get("ano") and etapa_atual in etapas_ano:
        dados["ano"] = ano

    if km_atual and not dados.get("km_atual") and etapa_atual in etapas_km:
        dados["km_atual"] = km_atual

    if revisao and not dados.get("revisao") and etapa_atual in etapas_revisao:
        dados["revisao"] = revisao

    if dia_numero and not dados.get("dia") and etapa_atual in etapas_dia:
        dados["dia"] = dia_numero
        dados["dia_texto"] = nome_dia(dia_numero)

    if data_normalizada and not dados.get("data") and etapa_atual in etapas_data:
        dados["data"] = data_normalizada

    if horario and not dados.get("horario") and etapa_atual in etapas_horario:
        horario_limpo = horario.strip()

        if re.match(r"^\d{1,2}:\d{2}$", horario_limpo):
            hora, minuto = horario_limpo.split(":")
            horario_limpo = f"{int(hora):02d}:{minuto}"
            dados["horario"] = horario_limpo

    if (
        item_adicional
        and not dados.get("venda_adicional")
        and item_adicional_valido(item_adicional)
        and etapa_atual in etapas_venda
    ):
        dados["itens"] = item_adicional
        dados["venda_adicional"] = item_adicional

    if observacao and not dados.get("observacao") and etapa_atual in etapas_observacao:
        obs_norm = normalizar_texto(observacao)

        bloqueadas_obs = [
            "1", "2", "3", "4", "5", "6", "7",
            "sim", "nao", "não", "ok", "menu",
            "agendar", "consultor", "humano"
        ]

        if obs_norm not in bloqueadas_obs and len(obs_norm) >= 8:
            dados["observacao"] = observacao

    if tipo_atendimento and not dados.get("tipo_atendimento") and etapa_atual in etapas_tipo:
        tipo_norm = normalizar_texto(tipo_atendimento)

        if "aguardar" in tipo_norm:
            dados["tipo_atendimento"] = "AGUARDAR NA CONCESSIONÁRIA"

        elif "deixar" in tipo_norm or "retirar depois" in tipo_norm:
            dados["tipo_atendimento"] = "DEIXAR A MOTO E RETIRAR DEPOIS"

        else:
            dados["tipo_atendimento"] = tipo_atendimento


# ==========================================
# IA COMERCIAL - FASE 1
# ==========================================
def aplicar_ia_comercial(telefone, texto):
    try:
        telefone = limpar_telefone(telefone)
        texto = limpar_texto(texto)

        if not telefone or not texto:
            return

        iniciar_cliente(telefone)

        if not gerar_resposta_comercial:
            return

        if clientes[telefone].get("atendimento_humano"):
            return

        if deve_bloquear_ia_no_fluxo(telefone):
            return

        modelo = clientes[telefone].get("modelo", "")
        intencao = clientes[telefone].get("intencao_ia", "")

        resposta = gerar_resposta_comercial(
            texto=texto,
            modelo=modelo,
            intencao=intencao,
            nome=clientes[telefone].get("nome", "")
        )

        if not isinstance(resposta, dict):
            return

        clientes[telefone]["nivel_interesse"] = limpar_texto(
            resposta.get("nivel_interesse", "")
        )

        clientes[telefone]["proxima_acao"] = limpar_texto(
            resposta.get("proxima_acao", "")
        )

        clientes[telefone]["temperatura_lead"] = limpar_texto(
            resposta.get("temperatura_lead", "")
        )

        clientes[telefone]["produto_interesse"] = limpar_texto(
            resposta.get("produto_interesse", "")
        )

        clientes[telefone]["oportunidade_comercial"] = bool(
            resposta.get("oportunidade_comercial", False)
        )

        clientes[telefone]["status_comercial"] = limpar_texto(
            resposta.get("status_comercial", "")
        )

        clientes[telefone]["intencao_ia"] = limpar_texto(
            resposta.get("interesse", "")
        )

        clientes[telefone]["ultima_acao_ia"] = "IA_COMERCIAL"

        nivel = limpar_texto(
            resposta.get("nivel_interesse", "")
        ).upper()

        if nivel == "ALTO" or resposta.get("encaminhar_humano"):
            salvar_evento_atendimento(
                telefone=telefone,
                setor="IA_COMERCIAL",
                status=clientes[telefone].get("status_comercial") or STATUS_AGENDAMENTO_INICIADO,
                etapa="lead_quente_detectado",
                dados=clientes[telefone],
                atendimento_humano=bool(resposta.get("encaminhar_humano", False)),
                concluido=False,
            )

    except Exception as e:
        log_erro("Erro aplicar_ia_comercial:", repr(e))


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

    return (
        "✅ Já identifiquei estas informações do seu pedido:\n\n"
        + "\n".join(partes)
    )


# ==========================================
# FLUXO REVISÃO
# ==========================================
def primeira_etapa_pendente_revisao(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return "revisao_modelo"

    iniciar_cliente(telefone)
    dados = clientes.get(telefone, {}) or {}

    if not limpar_texto(dados.get("modelo", "")):
        return "revisao_modelo"

    if not limpar_texto(dados.get("nome", "")):
        return "revisao_nome"

    if len(limpar_cpf(dados.get("cpf", ""))) != 11:
        return "revisao_cpf"

    if not limpar_texto(dados.get("placa", "")) and not limpar_texto(dados.get("chassi", "")):
        return "revisao_placa_chassi"

    if not limpar_texto(dados.get("ano", "")):
        return "revisao_ano"

    if not limpar_texto(dados.get("km_atual", "")):
        return "revisao_km"

    if not limpar_texto(dados.get("revisao", "")):
        return "revisao_revisao"

    if not limpar_texto(dados.get("dia", "")):
        return "revisao_dia"

    if not limpar_texto(dados.get("data", "")):
        return "revisao_data"

    if not limpar_texto(dados.get("horario", "")):
        return "revisao_horario"

    if not limpar_texto(dados.get("tipo_atendimento", "")):
        return "revisao_tipo_atendimento"

    if dados.get("venda_etapa_concluida") is not True:
        return "revisao_venda"

    if dados.get("observacao_etapa_concluida") is not True:
        return "revisao_observacao"

    return "revisao_confirmacao"


def iniciar_fluxo_revisao_por_intencao(telefone, dados_extraidos=None):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return ""

    iniciar_cliente(telefone)
    memoria = carregar_memoria_cliente_no_estado(telefone)

    origem_atual = clientes[telefone].get("origem", "BOT")
    atendimento_humano_atual = clientes[telefone].get("atendimento_humano", False)

    limpar_dados_fluxo_revisao(telefone)

    clientes[telefone]["origem"] = origem_atual or "BOT"
    clientes[telefone]["atendimento_humano"] = atendimento_humano_atual
    clientes[telefone]["venda_etapa_concluida"] = False
    clientes[telefone]["observacao_etapa_concluida"] = False
    clientes[telefone]["status"] = STATUS_AGENDAMENTO_INICIADO
    clientes[telefone]["etapa"] = "revisao_modelo"
    clientes[telefone]["ultima_interacao"] = agora()

    if dados_extraidos:
        aplicar_dados_ia_no_cliente(
            telefone,
            dados_extraidos
        )

    if not clientes[telefone].get("modelo") and memoria.get("modelo"):
        clientes[telefone]["modelo"] = memoria.get("modelo", "")

    if not clientes[telefone].get("ano") and memoria.get("ano"):
        clientes[telefone]["ano"] = memoria.get("ano", "")

    if not clientes[telefone].get("nome") and memoria.get("nome"):
        clientes[telefone]["nome"] = memoria.get("nome", "")

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

    enviar_mensagem_memoria_cliente(telefone, "revisao")

    proxima = primeira_etapa_pendente_revisao(telefone)
    clientes[telefone]["etapa"] = proxima

    return proxima


def botoes_horarios_disponiveis(horarios):
    botoes = []

    try:
        for i, horario in enumerate((horarios or [])[:9], start=1):
            botoes.append({
                "id": str(i),
                "label": horario
            })

    except Exception:
        pass

    return botoes


def enviar_proxima_etapa_revisao(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    etapa = primeira_etapa_pendente_revisao(telefone)

    clientes[telefone]["etapa"] = etapa
    clientes[telefone]["ultima_interacao"] = agora()

    if etapa != "revisao_horario":
        clientes[telefone]["horarios_disponiveis"] = []

    if etapa == "revisao_horario":
        revisao = limpar_texto(
            clientes[telefone].get("revisao", "")
        )

        dia = limpar_texto(
            clientes[telefone].get("dia", "")
        )

        data = limpar_texto(
            clientes[telefone].get("data", "")
        )

        if not validar_data(data):
            clientes[telefone]["data"] = ""
            clientes[telefone]["horario"] = ""
            clientes[telefone]["horarios_disponiveis"] = []
            clientes[telefone]["etapa"] = "revisao_data"

            enviar_mensagem(
                telefone,
                "⚠️ A data informada não é válida, está no passado ou caiu em domingo.\n\n"
                "Informe outra data no formato *dd/mm/aaaa*."
            )

            return True

        if dia and not data_bate_com_dia_semana(data, dia):
            clientes[telefone]["data"] = ""
            clientes[telefone]["horario"] = ""
            clientes[telefone]["horarios_disponiveis"] = []
            clientes[telefone]["etapa"] = "revisao_data"

            enviar_mensagem(
                telefone,
                f"⚠️ A data informada não corresponde ao dia escolhido (*{nome_dia(dia)}*).\n\n"
                "Informe uma data correta no formato *dd/mm/aaaa*."
            )

            return True

        horarios_base = horarios_por_revisao(
            revisao,
            dia
        )

        horarios = [
            h for h in horarios_base
            if verificar_capacidade(data, h, revisao)
        ]

        if not horarios:
            clientes[telefone]["etapa"] = "revisao_data"
            clientes[telefone]["horario"] = ""
            clientes[telefone]["horarios_disponiveis"] = []

            enviar_mensagem(
                telefone,
                "⚠️ Não há horários disponíveis para essa data.\n\n"
                "Por favor, escolha outra data para o agendamento."
            )

            enviar_mensagem_etapa_revisao(
                telefone,
                "revisao_data"
            )

            return True

        clientes[telefone]["horarios_disponiveis"] = horarios

        enviar_mensagem(
            telefone,
            montar_mensagem_horarios(horarios)
        )

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Revisão",
            status=obter_status_cliente(telefone),
            etapa="revisao_horario",
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=False,
        )

        return True

    enviar_mensagem_etapa_revisao(
        telefone,
        etapa
    )

    return True


# ==========================================
# CAPACIDADE / HORÁRIOS
# ==========================================
def limite_por_revisao(revisao):
    try:
        revisao = int(limpar_texto(revisao))
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
                AgendamentoRevisao.status.in_([
                    STATUS_AGENDADO,
                    STATUS_CONFIRMADO,
                    normalizar_status(STATUS_AGENDADO),
                    normalizar_status(STATUS_CONFIRMADO),
                ]),
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
        revisao = int(limpar_texto(revisao))
    except Exception:
        revisao = 1

    dia = limpar_texto(dia)

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


def obter_horarios_disponiveis(revisao, dia):
    """
    Retorna lista de horários disponíveis para uma revisão e dia específicos.
    Wrapper para horarios_por_revisao() com melhor nomenclatura.
    """
    return horarios_por_revisao(revisao, dia)


def extrair_tipo_atendimento(texto):
    """
    Extrai o tipo de atendimento a partir do texto do cliente.
    Retorna: "AGUARDAR NA CONCESSIONÁRIA" ou "DEIXAR A MOTO E RETIRAR DEPOIS"
    """
    try:
        texto_norm = normalizar_texto(texto).lower()

        aguardar_patterns = [
            "aguardar", "esperar", "ficar", "fico", "vou ficar",
            "vou aguardar", "vou esperar", "concessionaria", "concessionária",
            "loja", "atender"
        ]

        deixar_patterns = [
            "deixar", "retirar depois", "depois", "retirar mais tarde",
            "volto depois", "busco depois", "vou deixar", "sair",
            "deixar moto", "deixa"
        ]

        if any(pattern in texto_norm for pattern in aguardar_patterns):
            return "AGUARDAR NA CONCESSIONÁRIA"

        if any(pattern in texto_norm for pattern in deixar_patterns):
            return "DEIXAR A MOTO E RETIRAR DEPOIS"

        return ""

    except Exception as e:
        log_erro("Erro ao extrair tipo de atendimento:", repr(e))
        return ""


def montar_data_hora_agendamento_sances(dados):
    try:
        dados = dados or {}
        data = limpar_texto(
            dados.get("data", "")
            or dados.get("data_agendada", "")
        )
        horario = limpar_texto(dados.get("horario", ""))

        if not data or not horario:
            return ""

        if re.match(r"^\d{4}-\d{2}-\d{2}$", data):
            data_obj = datetime.strptime(data, "%Y-%m-%d")
        else:
            data_obj = datetime.strptime(data, "%d/%m/%Y")

        if re.match(r"^\d{1,2}:\d{2}$", horario):
            hora, minuto = horario.split(":")
            horario = f"{int(hora):02d}:{minuto}:00"
        elif re.match(r"^\d{1,2}:\d{2}:\d{2}$", horario):
            partes = horario.split(":")
            horario = f"{int(partes[0]):02d}:{partes[1]}:{partes[2]}"
        else:
            return ""

        return f"{data_obj.strftime('%Y-%m-%d')} {horario}"

    except Exception as e:
        log_erro("[SANCES] Erro ao montar data/hora:", repr(e))
        return ""


def km_sances(valor):
    try:
        numeros = re.sub(r"\D", "", str(valor or ""))
        return int(numeros) if numeros else 0
    except Exception:
        return 0


def extrair_codigo_cliente_sances(retorno_json):
    try:
        if isinstance(retorno_json, list):
            item = retorno_json[0] if retorno_json else {}
        elif isinstance(retorno_json, dict):
            dados = (
                retorno_json.get("dados")
                or retorno_json.get("clientes")
                or retorno_json.get("data")
                or retorno_json.get("resultado")
                or retorno_json
            )

            if isinstance(dados, list):
                item = dados[0] if dados else {}
            elif isinstance(dados, dict):
                item = dados
            else:
                item = {}
        else:
            item = {}

        if not isinstance(item, dict):
            return ""

        return limpar_texto(
            item.get("codigo_cliente")
            or item.get("codigoCliente")
            or item.get("codigo")
            or item.get("id")
            or item.get("id_cliente")
            or item.get("idCliente")
            or ""
        )

    except Exception:
        return ""


def buscar_codigo_cliente_sances_por_cpf(cpf):
    try:
        cpf_limpo = limpar_cpf(cpf)

        if not cpf_limpo:
            return ""

        if not SANCES_CLIENTES_URL:
            log_info("[SANCES] Consulta cliente ignorada: SANCES_CLIENTES_URL nao configurada")
            return ""

        if not SANCES_TOKEN:
            log_info("[SANCES] Consulta cliente ignorada: SANCES_TOKEN nao configurado")
            return ""

        params = {
            "cpf_cnpj_cliente": cpf_limpo,
            "cpf": cpf_limpo,
            "cpfCnpj": cpf_limpo,
        }

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }

        log_info("[SANCES] Consulta cliente por CPF iniciada:", cpf_limpo)

        response = requests.get(
            SANCES_CLIENTES_URL,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status consulta cliente:", response.status_code)
        log_info("[SANCES] Resposta consulta cliente:", retorno_json)

        if not (200 <= response.status_code < 300):
            return ""

        codigo_cliente = extrair_codigo_cliente_sances(retorno_json)
        log_info("[SANCES] Codigo cliente localizado:", codigo_cliente or "-")
        return codigo_cliente

    except requests.Timeout:
        log_erro("[SANCES] Timeout consulta cliente por CPF")
        return ""

    except Exception as e:
        log_erro("[SANCES] Erro consulta cliente por CPF:", repr(e))
        return ""


def obter_lista_clientes_sances(retorno_json):
    if isinstance(retorno_json, list):
        return retorno_json

    if not isinstance(retorno_json, dict):
        return []

    for chave in ["dados", "clientes", "data", "resultado", "items", "registros"]:
        valor = retorno_json.get(chave)
        if isinstance(valor, list):
            return valor
        if isinstance(valor, dict):
            return [valor]

    return [retorno_json] if retorno_json else []


def telefone_cliente_sances(cliente, item=None):
    cliente = cliente if isinstance(cliente, dict) else {}
    item = item if isinstance(item, dict) else {}
    contato = cliente.get("contato") if isinstance(cliente.get("contato"), dict) else {}
    telefone_cliente = cliente.get("telefone") if isinstance(cliente.get("telefone"), dict) else {}
    telefone_item = item.get("telefone") if isinstance(item.get("telefone"), dict) else {}

    return limpar_telefone(
        contato.get("telefone_celular")
        or contato.get("celular")
        or contato.get("telefone")
        or telefone_cliente.get("celular")
        or telefone_cliente.get("comercial")
        or telefone_cliente.get("residencial")
        or telefone_item.get("celular")
        or telefone_item.get("comercial")
        or telefone_item.get("residencial")
        or cliente.get("telefone_celular")
        or (cliente.get("telefone") if not isinstance(cliente.get("telefone"), dict) else "")
        or cliente.get("celular")
        or item.get("telefone_celular")
        or (item.get("telefone") if not isinstance(item.get("telefone"), dict) else "")
        or item.get("celular")
        or ""
    )


def data_compra_sances(item, veiculo=None):
    item = item if isinstance(item, dict) else {}
    veiculo = veiculo if isinstance(veiculo, dict) else {}

    return limpar_texto(
        veiculo.get("data_compra")
        or veiculo.get("dataCompra")
        or veiculo.get("data_faturamento")
        or item.get("data_compra")
        or item.get("dataCompra")
        or item.get("data_fechamento")
        or item.get("data_aprovacao")
        or item.get("data_faturamento")
        or item.get("data_cadastro")
        or item.get("criado_em")
        or ""
    )


def montar_linhas_clientes_sances(retorno_json):
    linhas = []

    for item in obter_lista_clientes_sances(retorno_json):
        if not isinstance(item, dict):
            continue

        cliente = item.get("cliente") if isinstance(item.get("cliente"), dict) else item
        veiculos = item.get("veiculos") or item.get("veículos") or item.get("motos") or []

        if isinstance(veiculos, dict):
            veiculos = [veiculos]
        elif not isinstance(veiculos, list) or not veiculos:
            veiculos = [{}]

        nome = limpar_texto(
            cliente.get("nome")
            or cliente.get("nome_cliente")
            or item.get("nome_cliente")
            or item.get("cliente")
            or ""
        )
        telefone = telefone_cliente_sances(cliente, item)

        for veiculo in veiculos:
            veiculo = veiculo if isinstance(veiculo, dict) else {}
            linhas.append({
                "codigo_cliente": limpar_texto(
                    cliente.get("codigo_cliente")
                    or cliente.get("codigoCliente")
                    or item.get("codigo_cliente")
                    or item.get("codigoCliente")
                    or item.get("codigo")
                    or item.get("id")
                    or ""
                ),
                "data_compra": data_compra_sances(item, veiculo),
                "nome": nome,
                "telefone": telefone,
                "chassi": limpar_texto(
                    veiculo.get("chassi")
                    or veiculo.get("chassi_serie")
                    or veiculo.get("chassiSerie")
                    or item.get("chassi")
                    or item.get("chassi_serie")
                    or ""
                ).upper(),
                "modelo_moto": limpar_texto(
                    veiculo.get("modelo")
                    or veiculo.get("descricao_modelo")
                    or veiculo.get("descricao_modelo_veiculo")
                    or item.get("modelo")
                    or item.get("descricao_modelo")
                    or item.get("descricao_modelo_veiculo")
                    or ""
                ).upper(),
            })

    return linhas


def consultar_clientes_sances_para_planilha(data_inicio="", data_fim="", limit=500, offset=0):
    try:
        if not SANCES_CLIENTES_URL:
            return {
                "sucesso": False,
                "mensagem": "Endpoint de clientes Sances não configurado.",
                "linhas": [],
                "erro": "SANCES_CLIENTES_URL não configurada",
            }

        if not SANCES_TOKEN:
            return {
                "sucesso": False,
                "mensagem": "Token Sances não configurado.",
                "linhas": [],
                "erro": "SANCES_TOKEN não configurado",
            }

        params = {
            "limit": int(limit or 500),
            "offset": int(offset or 0),
        }
        data_inicio = limpar_texto(data_inicio)
        data_fim = limpar_texto(data_fim)

        if data_inicio:
            params["data_compra_inicio"] = data_inicio
            params["data_inicio"] = data_inicio

        if data_fim:
            params["data_compra_fim"] = data_fim
            params["data_fim"] = data_fim

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }

        log_info("[SANCES] Consulta clientes para planilha iniciada:", params)

        response = requests.get(
            SANCES_CLIENTES_URL,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status clientes planilha:", response.status_code)

        if not (200 <= response.status_code < 300):
            return {
                "sucesso": False,
                "mensagem": "Erro ao consultar clientes no Sances.",
                "linhas": [],
                "erro": f"HTTP {response.status_code}",
            }

        linhas = montar_linhas_clientes_sances(retorno_json)
        linhas = sorted(linhas, key=lambda item: limpar_texto(item.get("data_compra", "")))

        return {
            "sucesso": True,
            "mensagem": "Clientes consultados no Sances.",
            "linhas": linhas,
            "erro": "",
        }

    except requests.Timeout:
        return {
            "sucesso": False,
            "mensagem": "Timeout ao consultar clientes no Sances.",
            "linhas": [],
            "erro": f"Timeout Sances apos {SANCES_TIMEOUT}s",
        }

    except Exception as e:
        log_erro("[SANCES] Erro consulta clientes planilha:", repr(e))
        return {
            "sucesso": False,
            "mensagem": "Erro ao consultar clientes no Sances.",
            "linhas": [],
            "erro": repr(e),
        }


def formatar_data_venda_excel(valor):
    valor = limpar_texto(valor)

    if not valor:
        return ""

    try:
        data = pd.to_datetime(valor, errors="coerce", dayfirst=False)

        if pd.isna(data):
            data = pd.to_datetime(valor, errors="coerce", dayfirst=True)

        if pd.isna(data):
            return valor

        return data.strftime("%d/%m/%Y")

    except Exception:
        return valor


def lista_dados_sances(retorno_json):
    if isinstance(retorno_json, list):
        return retorno_json

    if not isinstance(retorno_json, dict):
        return []

    for chave in ["dados", "vendas", "data", "resultado", "items", "registros"]:
        valor = retorno_json.get(chave)

        if isinstance(valor, list):
            return valor

        if isinstance(valor, dict):
            return [valor]

    return []


def telefone_venda_sances(venda):
    venda = venda if isinstance(venda, dict) else {}
    cliente = venda.get("cliente") if isinstance(venda.get("cliente"), dict) else {}
    contato = cliente.get("contato") if isinstance(cliente.get("contato"), dict) else {}
    telefone = cliente.get("telefone") if isinstance(cliente.get("telefone"), dict) else {}

    return limpar_telefone(
        venda.get("telefone_cliente")
        or venda.get("telefone")
        or venda.get("celular")
        or contato.get("telefone_celular")
        or contato.get("celular")
        or contato.get("telefone")
        or telefone.get("celular")
        or telefone.get("comercial")
        or telefone.get("residencial")
        or cliente.get("telefone_celular")
        or cliente.get("telefone")
        or cliente.get("celular")
        or ""
    )


def linhas_venda_sances(venda):
    venda = venda if isinstance(venda, dict) else {}
    cliente = venda.get("cliente") if isinstance(venda.get("cliente"), dict) else {}
    veiculos = (
        venda.get("veiculos")
        or venda.get("veículos")
        or venda.get("motos")
        or venda.get("itens")
        or []
    )

    if isinstance(veiculos, dict):
        veiculos = [veiculos]

    if not isinstance(veiculos, list) or not veiculos:
        veiculos = [venda]

    nome_cliente = limpar_texto(
        venda.get("nome_cliente")
        or venda.get("cliente_nome")
        or cliente.get("nome")
        or cliente.get("nome_cliente")
        or ""
    )
    telefone_cliente = telefone_venda_sances(venda)
    data_finalizacao = limpar_texto(
        venda.get("data_finalizacao")
        or venda.get("dataFinalizacao")
        or venda.get("data_fechamento")
        or venda.get("data_aprovacao")
        or venda.get("data_faturamento")
        or ""
    )

    if not data_finalizacao:
        return []

    linhas = []

    for veiculo in veiculos:
        veiculo = veiculo if isinstance(veiculo, dict) else {}
        linhas.append({
            "nome_cliente": nome_cliente,
            "telefone_cliente": telefone_cliente,
            "modelo": limpar_texto(
                veiculo.get("modelo")
                or veiculo.get("descricao_modelo")
                or veiculo.get("descricao_modelo_veiculo")
                or venda.get("modelo")
                or venda.get("descricao_modelo")
                or ""
            ).upper(),
            "chassi": limpar_texto(
                veiculo.get("chassi")
                or veiculo.get("chassi_serie")
                or veiculo.get("chassiSerie")
                or venda.get("chassi")
                or venda.get("chassi_serie")
                or ""
            ).upper(),
            "data_finalizacao": data_finalizacao,
        })

    return linhas


def buscar_vendas_sances(data_inicio, data_fim):
    try:
        data_inicio = limpar_texto(data_inicio)
        data_fim = limpar_texto(data_fim)

        if not SANCES_GET_VENDAS_URL:
            return {
                "sucesso": False,
                "mensagem": "Endpoint GetVendas do Sances não configurado.",
                "vendas": [],
                "erro": "SANCES_GET_VENDAS_URL não configurada",
            }

        if not SANCES_TOKEN:
            return {
                "sucesso": False,
                "mensagem": "Token Sances não configurado.",
                "vendas": [],
                "erro": "SANCES_TOKEN não configurado",
            }

        params = {
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "dataInicio": data_inicio,
            "dataFim": data_fim,
            "data_finalizacao_inicio": data_inicio,
            "data_finalizacao_fim": data_fim,
            "dataFinalizacaoInicio": data_inicio,
            "dataFinalizacaoFim": data_fim,
        }
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }

        log_info("[SANCES] Consulta GetVendas iniciada:", params)

        response = requests.get(
            SANCES_GET_VENDAS_URL,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status GetVendas:", response.status_code)
        log_info("[SANCES] Resposta GetVendas:", retorno_json)

        if not (200 <= response.status_code < 300):
            return {
                "sucesso": False,
                "mensagem": "Erro ao consultar GetVendas no Sances.",
                "vendas": [],
                "erro": f"HTTP {response.status_code}",
            }

        vendas = []

        for venda in lista_dados_sances(retorno_json):
            vendas.extend(linhas_venda_sances(venda))

        return {
            "sucesso": True,
            "mensagem": "Vendas consultadas no Sances.",
            "vendas": vendas,
            "erro": "",
        }

    except requests.Timeout:
        return {
            "sucesso": False,
            "mensagem": "Timeout ao consultar GetVendas no Sances.",
            "vendas": [],
            "erro": f"Timeout Sances apos {SANCES_TIMEOUT}s",
        }

    except Exception as e:
        log_erro("[SANCES] Erro consultar GetVendas:", repr(e))
        return {
            "sucesso": False,
            "mensagem": "Erro ao consultar GetVendas no Sances.",
            "vendas": [],
            "erro": repr(e),
        }


def gerar_excel_vendas_sances(caminho, data_inicio, data_fim):
    consulta = buscar_vendas_sances(data_inicio, data_fim)

    if not consulta.get("sucesso"):
        return False, consulta

    vendas = consulta.get("vendas", []) or []
    linhas = [
        {
            "Nome Cliente": venda.get("nome_cliente", ""),
            "Telefone": venda.get("telefone_cliente", ""),
            "Modelo": venda.get("modelo", ""),
            "Chassi": venda.get("chassi", ""),
            "Data Venda": formatar_data_venda_excel(venda.get("data_finalizacao", "")),
        }
        for venda in vendas
        if limpar_texto(venda.get("data_finalizacao", ""))
    ]

    df = pd.DataFrame(
        linhas,
        columns=["Nome Cliente", "Telefone", "Modelo", "Chassi", "Data Venda"],
    )
    df.to_excel(caminho, index=False, engine="openpyxl")

    return True, {
        "sucesso": True,
        "mensagem": "Relatório de vendas gerado.",
        "arquivo": caminho,
        "total": len(df),
    }


def extrair_veiculos_sances(retorno_json):
    try:
        if isinstance(retorno_json, list):
            itens = retorno_json
        elif isinstance(retorno_json, dict):
            dados = (
                retorno_json.get("dados")
                or retorno_json.get("veiculos")
                or retorno_json.get("veículos")
                or retorno_json.get("data")
                or retorno_json.get("resultado")
                or retorno_json.get("items")
                or retorno_json.get("registros")
                or []
            )

            if isinstance(dados, list):
                itens = dados
            elif isinstance(dados, dict):
                itens = [dados]
            else:
                itens = []
        else:
            itens = []

        veiculos = []

        for item in itens:
            if not isinstance(item, dict):
                continue

            veiculos_item = (
                item.get("veiculos")
                or item.get("veÃ­culos")
                or item.get("veiculos_cliente")
                or item.get("veiculosCliente")
            )

            if isinstance(veiculos_item, list):
                for veiculo_item in veiculos_item:
                    if not isinstance(veiculo_item, dict):
                        continue

                    veiculo_normalizado = dict(veiculo_item)
                    veiculo_normalizado.setdefault("codigo_cliente", item.get("codigo_cliente", ""))
                    veiculo_normalizado.setdefault("codigoCliente", item.get("codigoCliente", ""))
                    veiculo_normalizado.setdefault("codigo_proprietario", item.get("codigo_proprietario", ""))
                    veiculo_normalizado.setdefault("codigoProprietario", item.get("codigoProprietario", ""))
                    veiculo_normalizado.setdefault("id_cliente", item.get("id_cliente", ""))
                    veiculo_normalizado.setdefault("idCliente", item.get("idCliente", ""))
                    veiculo_normalizado.setdefault("nome_cliente", item.get("nome_cliente", ""))
                    veiculo_normalizado.setdefault("nome_proprietario", item.get("nome_proprietario", ""))
                    veiculo_normalizado.setdefault("proprietario", item.get("proprietario", ""))
                    itens.append(veiculo_normalizado)
                continue

            if isinstance(veiculos_item, dict):
                veiculo_normalizado = dict(veiculos_item)
                veiculo_normalizado.setdefault("codigo_cliente", item.get("codigo_cliente", ""))
                veiculo_normalizado.setdefault("codigoCliente", item.get("codigoCliente", ""))
                veiculo_normalizado.setdefault("codigo_proprietario", item.get("codigo_proprietario", ""))
                veiculo_normalizado.setdefault("codigoProprietario", item.get("codigoProprietario", ""))
                veiculo_normalizado.setdefault("id_cliente", item.get("id_cliente", ""))
                veiculo_normalizado.setdefault("idCliente", item.get("idCliente", ""))
                veiculo_normalizado.setdefault("nome_cliente", item.get("nome_cliente", ""))
                veiculo_normalizado.setdefault("nome_proprietario", item.get("nome_proprietario", ""))
                veiculo_normalizado.setdefault("proprietario", item.get("proprietario", ""))
                itens.append(veiculo_normalizado)
                continue

            placa = limpar_texto(
                item.get("placa_veiculo")
                or item.get("placa")
                or item.get("placaVeiculo")
                or ""
            ).upper()
            chassi = limpar_texto(
                item.get("chassi_serie")
                or item.get("chassi")
                or item.get("chassiSerie")
                or item.get("serie")
                or ""
            ).upper()
            modelo = limpar_texto(
                item.get("descricao_modelo")
                or item.get("descricao_modelo_veiculo")
                or item.get("descricaoModeloVeiculo")
                or item.get("modelo")
                or item.get("modelo_veiculo")
                or item.get("descricaoModelo")
                or ""
            ).upper()
            ano_fabricacao = limpar_texto(
                item.get("ano_fabricacao")
                or item.get("ano_fabricacao_veiculo")
                or item.get("anoFabricacaoVeiculo")
                or ""
            )
            ano_modelo = limpar_texto(
                item.get("ano_modelo")
                or item.get("ano_modelo_veiculo")
                or item.get("anoModelo")
                or item.get("anoModeloVeiculo")
                or ""
            )
            ano = limpar_texto(item.get("ano") or "")
            if ano_fabricacao and ano_modelo:
                ano = f"{ano_fabricacao}/{ano_modelo}"
            elif not ano:
                ano = ano_modelo or ano_fabricacao
            codigo_veiculo = limpar_texto(
                item.get("codigo_veiculo")
                or item.get("codigoVeiculo")
                or item.get("codigo_veiculo_sances")
                or item.get("codigoVeiculoSances")
                or item.get("id")
                or ""
            )
            codigo_cliente = limpar_texto(
                item.get("codigo_cliente")
                or item.get("codigoCliente")
                or item.get("codigo_proprietario")
                or item.get("codigoProprietario")
                or item.get("id_cliente")
                or item.get("idCliente")
                or ""
            )
            km = limpar_texto(
                item.get("km")
                or item.get("km_atual")
                or item.get("km_entrada")
                or item.get("quilometragem")
                or item.get("quilometragem_atual")
                or item.get("quilometragemAtual")
                or ""
            )
            cliente = item.get("cliente") if isinstance(item.get("cliente"), dict) else {}
            proprietario = limpar_texto(
                item.get("proprietario")
                or item.get("nome_proprietario")
                or item.get("nomeProprietario")
                or item.get("nome_cliente")
                or item.get("nomeCliente")
                or cliente.get("nome")
                or cliente.get("nome_cliente")
                or ""
            )

            if placa or chassi or modelo:
                veiculos.append({
                    "placa": placa,
                    "chassi": chassi,
                    "modelo": modelo,
                    "ano": ano,
                    "km_atual": km,
                    "proprietario": proprietario,
                    "codigo_veiculo": codigo_veiculo,
                    "codigo_cliente": codigo_cliente,
                })

        return veiculos

    except Exception as e:
        log_erro("[SANCES] Erro extrair veiculos:", repr(e))
        return []


def buscar_veiculos_sances_por_cpf(cpf):
    try:
        cpf_limpo = limpar_cpf(cpf)

        if not cpf_limpo:
            return []

        if not SANCES_VEICULOS_URL:
            log_info("[SANCES] Consulta veiculos ignorada: SANCES_VEICULOS_URL nao configurada")
            return []

        if not SANCES_TOKEN:
            log_info("[SANCES] Consulta veiculos ignorada: SANCES_TOKEN nao configurado")
            return []

        params = {
            "cpf_cnpj_cliente": cpf_limpo,
            "cpf": cpf_limpo,
            "cpfCnpj": cpf_limpo,
        }

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }

        log_info("[SANCES] Consulta veiculos por CPF iniciada:", cpf_limpo)

        response = requests.get(
            SANCES_VEICULOS_URL,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status consulta veiculos:", response.status_code)
        log_info("[SANCES] Resposta consulta veiculos:", retorno_json)

        if not (200 <= response.status_code < 300):
            return []

        return extrair_veiculos_sances(retorno_json)

    except requests.Timeout:
        log_erro("[SANCES] Timeout consulta veiculos por CPF")
        return []

    except Exception as e:
        log_erro("[SANCES] Erro consulta veiculos por CPF:", repr(e))
        return []


def buscar_veiculos_sances_por_telefone(telefone):
    try:
        telefone_limpo = limpar_telefone(telefone)

        if not telefone_limpo:
            return []

        if not SANCES_VEICULOS_URL:
            log_info("[SANCES] Consulta veiculos por telefone ignorada: SANCES_VEICULOS_URL nao configurada")
            return []

        if not SANCES_TOKEN:
            log_info("[SANCES] Consulta veiculos por telefone ignorada: SANCES_TOKEN nao configurado")
            return []

        params = {
            "telefone": telefone_limpo,
            "telefone_cliente": telefone_limpo,
            "celular": telefone_limpo,
        }

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }

        log_info("[SANCES] Consulta veiculos por telefone iniciada:", telefone_limpo)

        response = requests.get(
            SANCES_VEICULOS_URL,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status consulta veiculos por telefone:", response.status_code)
        log_info("[SANCES] Resposta consulta veiculos por telefone:", retorno_json)

        if not (200 <= response.status_code < 300):
            return []

        return extrair_veiculos_sances(retorno_json)

    except requests.Timeout:
        log_erro("[SANCES] Timeout consulta veiculos por telefone")
        return []

    except Exception as e:
        log_erro("[SANCES] Erro consulta veiculos por telefone:", repr(e))
        return []


def deduplicar_veiculos_identificados(veiculos):
    unicos = []
    vistos = set()

    for veiculo in veiculos or []:
        if not isinstance(veiculo, dict):
            continue

        placa = limpar_texto(veiculo.get("placa", "")).upper()
        chassi = limpar_texto(veiculo.get("chassi", "")).upper()
        modelo = limpar_texto(veiculo.get("modelo", "")).upper()
        ano = limpar_texto(veiculo.get("ano", ""))

        if not placa and not chassi:
            continue

        chave = chassi or placa or f"{modelo}|{ano}"

        if chave in vistos:
            continue

        vistos.add(chave)
        unicos.append(veiculo)

    return unicos


def montar_veiculo_historico(registro):
    if not registro:
        return {}

    placa = limpar_texto(getattr(registro, "placa", "") or "").upper()
    chassi = limpar_texto(getattr(registro, "chassi", "") or "").upper()

    if not placa and not chassi:
        return {}

    return {
        "placa": placa,
        "chassi": chassi,
        "modelo": limpar_texto(getattr(registro, "modelo", "") or "").upper(),
        "ano": limpar_texto(getattr(registro, "ano", "") or ""),
        "km_atual": limpar_texto(getattr(registro, "km_atual", "") or ""),
        "proprietario": limpar_texto(getattr(registro, "nome", "") or ""),
        "codigo_veiculo": "",
        "codigo_cliente": "",
        "origem": "CRM",
    }


def buscar_veiculos_historico_crm(telefone="", cpf=""):
    telefone_limpo = limpar_telefone(telefone)
    cpf_limpo = limpar_cpf(cpf)

    if not telefone_limpo and not cpf_limpo:
        return []

    db = SessionLocal()

    try:
        veiculos = []

        filtros_agendamento = []
        filtros_atendimento = []

        if telefone_limpo:
            filtros_agendamento.append(AgendamentoRevisao.telefone == telefone_limpo)
            filtros_atendimento.append(Atendimento.telefone == telefone_limpo)

        if cpf_limpo:
            filtros_agendamento.append(AgendamentoRevisao.cpf == cpf_limpo)
            filtros_atendimento.append(Atendimento.cpf == cpf_limpo)

        if filtros_agendamento:
            agendamentos = (
                db.query(AgendamentoRevisao)
                .filter(or_(*filtros_agendamento))
                .order_by(AgendamentoRevisao.criado_em.desc())
                .limit(10)
                .all()
            )
            veiculos.extend(montar_veiculo_historico(item) for item in agendamentos)

        if filtros_atendimento:
            atendimentos = (
                db.query(Atendimento)
                .filter(or_(*filtros_atendimento))
                .order_by(Atendimento.data.desc())
                .limit(10)
                .all()
            )
            veiculos.extend(montar_veiculo_historico(item) for item in atendimentos)

        return deduplicar_veiculos_identificados(veiculos)

    except Exception as e:
        log_erro("Erro ao buscar veiculos no historico CRM:", repr(e))
        return []

    finally:
        db.close()


def buscar_veiculos_revisao(telefone, cpf):
    veiculos = deduplicar_veiculos_identificados(buscar_veiculos_sances_por_cpf(cpf))
    if veiculos:
        return veiculos, "SANCES_CPF"

    veiculos = deduplicar_veiculos_identificados(buscar_veiculos_sances_por_telefone(telefone))
    if veiculos:
        return veiculos, "SANCES_TELEFONE"

    veiculos = buscar_veiculos_historico_crm(telefone=telefone, cpf=cpf)
    if veiculos:
        return veiculos, "CRM"

    return [], ""


def final_chassi(chassi):
    chassi = limpar_texto(chassi).upper()
    return chassi[-4:] if len(chassi) >= 4 else chassi


def mensagem_veiculo_localizado(veiculo):
    veiculo = veiculo if isinstance(veiculo, dict) else {}
    modelo = limpar_texto(veiculo.get("modelo", "")).upper()
    ano = limpar_texto(veiculo.get("ano", ""))
    placa = limpar_texto(veiculo.get("placa", "")).upper()
    chassi = limpar_texto(veiculo.get("chassi", "")).upper()

    linhas = ["Encontrei sua moto 😊"]

    if modelo:
        linhas.append(f"Modelo: {modelo}")

    if ano:
        linhas.append(f"Ano: {ano}")

    if chassi:
        linhas.append(f"Chassi final: {final_chassi(chassi)}")
    elif placa:
        linhas.append(f"Placa: {placa}")

    return "\n".join(linhas)


def aplicar_veiculo_sances_no_cliente(telefone, veiculo):
    telefone = limpar_telefone(telefone)

    if not telefone or not isinstance(veiculo, dict):
        return False

    iniciar_cliente(telefone)
    dados = clientes[telefone]

    placa = limpar_texto(veiculo.get("placa", "")).upper()
    chassi = limpar_texto(veiculo.get("chassi", "")).upper()
    modelo = limpar_texto(veiculo.get("modelo", "")).upper()
    ano = limpar_texto(veiculo.get("ano", ""))
    km_atual = limpar_texto(veiculo.get("km_atual", "") or veiculo.get("km", ""))
    proprietario = limpar_texto(veiculo.get("proprietario", "") or veiculo.get("nome_proprietario", ""))
    codigo_veiculo = limpar_texto(veiculo.get("codigo_veiculo", ""))
    codigo_cliente = limpar_texto(veiculo.get("codigo_cliente", ""))

    if placa:
        dados["placa"] = placa

    if chassi:
        dados["chassi"] = chassi

    if modelo:
        dados["modelo"] = modelo

    if ano:
        dados["ano"] = ano

    if km_atual:
        dados["km_atual"] = km_atual

    if proprietario:
        dados["proprietario"] = proprietario

        if not limpar_texto(dados.get("nome", "")):
            dados["nome"] = proprietario.title()

    if codigo_veiculo:
        dados["codigo_veiculo"] = codigo_veiculo

    if codigo_cliente:
        dados["codigo_cliente"] = codigo_cliente

    return bool(placa or chassi)


def montar_opcoes_veiculos_sances(veiculos):
    linhas = [
        "Localizei mais de uma moto no seu cadastro.\n",
        "Digite o nÃºmero da moto que deseja agendar:\n",
    ]

    for indice, veiculo in enumerate((veiculos or [])[:9], start=1):
        chassi = limpar_texto(veiculo.get("chassi", "")).upper()
        descricao = " / ".join([
            valor for valor in [
                limpar_texto(veiculo.get("placa", "")),
                limpar_texto(veiculo.get("modelo", "")),
                limpar_texto(veiculo.get("ano", "")),
                f"chassi final {final_chassi(chassi)}" if chassi else "",
            ]
            if valor
        ])
        linhas.append(f"{indice} - {descricao or 'Moto sem descriÃ§Ã£o'}")

    return "\n".join(linhas)


def montar_payload_agendamento_sances(dados):
    dados = dados or {}
    revisao = limpar_texto(dados.get("revisao", ""))
    solicitacao = f"Revisão da {revisao}" if revisao else "Revisão"
    observacao = limpar_texto(
        dados.get("observacao", "")
        or dados.get("observacoes", "")
    )

    return {
        "data_hora_agendamento": montar_data_hora_agendamento_sances(dados),
        "codigo_empresa": SANCES_EMPRESA,
        "codigo_consultor": 52423,
        "codigo_midia": 1,
        "codigo_assunto": 10006,
        "codigo_cliente": dados.get("codigo_cliente") or None,
        "cpf_cnpj_cliente": limpar_cpf(dados.get("cpf", "")),
        "cpf_cliente": limpar_cpf(dados.get("cpf", "")),
        "nome_cliente": limpar_texto(dados.get("nome", "")),
        "telefone_contato": limpar_telefone(dados.get("telefone", "")),
        "codigo_veiculo": dados.get("codigo_veiculo") or None,
        "placa_veiculo": limpar_texto(dados.get("placa", "")).upper(),
        "chassi_serie": limpar_texto(dados.get("chassi", "")),
        "quilometragem": km_sances(dados.get("km_atual", "")),
        "codigo_modelo": None,
        "descricao_modelo": limpar_texto(dados.get("modelo", "")),
        "solicitacao_cliente": solicitacao,
        "observacao": observacao,
    }


def validar_payload_agendamento_sances(payload):
    try:
        payload = payload or {}

        obrigatorios = [
            "data_hora_agendamento",
            "codigo_empresa",
            "codigo_consultor",
            "codigo_midia",
            "codigo_assunto",
            "nome_cliente",
            "telefone_contato",
            "quilometragem",
            "descricao_modelo",
            "solicitacao_cliente",
        ]

        ausentes = []

        for campo in obrigatorios:
            valor = payload.get(campo)

            if campo == "quilometragem":
                if valor is None:
                    ausentes.append(campo)
                continue

            if valor in [None, ""]:
                ausentes.append(campo)

        if ausentes:
            return False, SANCES_STATUS_ERRO, f"Campos obrigatórios ausentes: {', '.join(ausentes)}"

        if (
            not payload.get("codigo_veiculo")
            and not payload.get("placa_veiculo")
            and not payload.get("chassi_serie")
        ):
            return False, SANCES_STATUS_PENDENTE_DADOS, "Sem codigo do veiculo, placa ou chassi para envio ao Sances"

        return True, "", ""

    except Exception as e:
        log_erro("[SANCES] Erro validar payload:", repr(e))
        return False, SANCES_STATUS_ERRO, repr(e)


def enviar_agendamento_para_sances(dados):
    """
    Cria agendamento na integração real Sances.
    Retorna dict com: sucesso, status, mensagem, dados, erro.
    Mantém protocolo_sances para compatibilidade com o dashboard/retry.
    """
    try:
        if not isinstance(dados, dict):
            return {
                "sucesso": False,
                "status": SANCES_STATUS_ERRO,
                "mensagem": "Dados inválidos para envio Sances.",
                "dados": {},
                "protocolo_sances": "",
                "erro": "Dados inválidos para envio Sances",
            }

        log_info("[SANCES] Envio iniciado:", dados.get("protocolo", ""))
        log_info("[SANCES] Dados completos do fluxo:", dados)

        endpoint_sances = limpar_texto(SANCES_URL or SANCES_API_URL)

        if not endpoint_sances:
            retorno = {
                "sucesso": False,
                "status": SANCES_STATUS_NAO_CONFIGURADO,
                "mensagem": "API Sances não configurada.",
                "dados": {},
                "protocolo_sances": "",
                "erro": "SANCES_URL/SANCES_API_URL não configurada",
            }
            log_info("[SANCES] Retorno recebido:", retorno)
            return retorno

        if not SANCES_TOKEN:
            retorno = {
                "sucesso": False,
                "status": SANCES_STATUS_NAO_CONFIGURADO,
                "mensagem": "Token Sances não configurado.",
                "dados": {},
                "protocolo_sances": "",
                "erro": "SANCES_TOKEN não configurado",
            }
            log_info("[SANCES] Retorno recebido:", retorno)
            return retorno

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
            "Content-Type": "application/json",
        }

        if not dados.get("codigo_cliente"):
            codigo_cliente = buscar_codigo_cliente_sances_por_cpf(
                dados.get("cpf", "")
            )

            if codigo_cliente:
                dados["codigo_cliente"] = codigo_cliente

        if (
            not dados.get("codigo_veiculo")
            and not limpar_texto(dados.get("placa", ""))
            and not limpar_texto(dados.get("chassi", ""))
        ):
            veiculos = buscar_veiculos_sances_por_cpf(dados.get("cpf", ""))

            if len(veiculos) == 1:
                veiculo = veiculos[0]
                dados["placa"] = limpar_texto(veiculo.get("placa", "")).upper()
                dados["chassi"] = limpar_texto(veiculo.get("chassi", "")).upper()
                dados["codigo_veiculo"] = limpar_texto(veiculo.get("codigo_veiculo", ""))

                if not dados.get("modelo"):
                    dados["modelo"] = limpar_texto(veiculo.get("modelo", "")).upper()

                if not dados.get("ano"):
                    dados["ano"] = limpar_texto(veiculo.get("ano", ""))

                if veiculo.get("codigo_cliente") and not dados.get("codigo_cliente"):
                    dados["codigo_cliente"] = limpar_texto(veiculo.get("codigo_cliente", ""))

            elif len(veiculos) > 1:
                retorno = {
                    "sucesso": False,
                    "status": SANCES_STATUS_PENDENTE_DADOS,
                    "mensagem": "Mais de uma moto localizada para o CPF. Informe placa ou chassi para concluir o envio ao Sances.",
                    "dados": {},
                    "protocolo_sances": "",
                    "erro": "Mais de uma moto localizada para o CPF",
                }
                log_info("[SANCES] Retorno recebido:", retorno)
                return retorno

        payload = montar_payload_agendamento_sances(dados)
        log_info("[SANCES] Payload montado:", payload)

        payload_valido, status_payload, erro_payload = validar_payload_agendamento_sances(payload)

        if not payload_valido:
            retorno = {
                "sucesso": False,
                "status": SANCES_STATUS_ERRO,
                "mensagem": erro_payload,
                "dados": {
                    "status_validacao": status_payload,
                    "payload": payload,
                },
                "protocolo_sances": "",
                "erro": erro_payload,
            }
            log_erro("[SANCES] Payload inválido:", retorno)
            return retorno

        log_info("[SANCES] Payload enviado:", payload)

        response = requests.post(
            endpoint_sances,
            json=payload,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        log_info("[SANCES] Status code:", response.status_code)
        log_info("[SANCES] Resposta texto:", response.text)

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Resposta do Sances:", retorno_json)

        sucesso = 200 <= response.status_code < 300
        protocolo_sances = limpar_texto(
            retorno_json.get("protocolo")
            or retorno_json.get("protocolo_sances")
            or retorno_json.get("id")
            or retorno_json.get("codigo_agendamento")
            or ""
        )
        mensagem = limpar_texto(
            retorno_json.get("mensagem")
            or retorno_json.get("message")
            or ""
        )
        erro = "" if sucesso else limpar_texto(
            retorno_json.get("erro")
            or retorno_json.get("error")
            or retorno_json.get("message")
            or f"HTTP {response.status_code}"
        )

        retorno = {
            "sucesso": sucesso,
            "status": SANCES_STATUS_ENVIADO if sucesso else SANCES_STATUS_ERRO,
            "mensagem": mensagem or ("Agendamento enviado ao Sances." if sucesso else "Erro no envio ao Sances."),
            "dados": {
                "endpoint": endpoint_sances,
                "status_code": response.status_code,
                "payload": payload,
                "resposta": retorno_json,
                "resposta_texto": response.text[:2000],
            },
            "protocolo_sances": protocolo_sances,
            "erro": erro,
        }
        log_info("[SANCES] Retorno recebido:", retorno)
        return retorno

    except requests.Timeout:
        retorno = {
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "mensagem": "Timeout ao enviar agendamento para Sances.",
            "dados": {
                "endpoint": limpar_texto(SANCES_URL or SANCES_API_URL),
                "timeout": SANCES_TIMEOUT,
            },
            "protocolo_sances": "",
            "erro": f"Timeout Sances apos {SANCES_TIMEOUT}s",
        }
        log_erro("[SANCES] Timeout:", retorno)
        return retorno

    except Exception as e:
        import traceback

        log_erro("[SANCES] Exception completa:", traceback.format_exc())

        retorno = {
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "mensagem": "Erro ao enviar agendamento para Sances.",
            "dados": {
                "endpoint": limpar_texto(SANCES_URL or SANCES_API_URL),
            },
            "protocolo_sances": "",
            "erro": repr(e),
        }
        log_erro("Erro ao enviar agendamento para Sances:", repr(e))
        return retorno


def consultar_pos_venda_sances(
    cpf_cliente=None,
    placa=None,
    protocolo=None,
    ordem_servico=None,
    codigo_empresa=None,
):
    try:
        params = {}

        if cpf_cliente:
            params["cpf_cnpj_cliente"] = limpar_cpf(cpf_cliente)

        if placa:
            params["placa_veiculo"] = limpar_texto(placa).upper()

        if protocolo:
            params["protocolo"] = limpar_texto(protocolo)

        if ordem_servico:
            params["ordem_servico"] = limpar_texto(ordem_servico)
            params["numero_os"] = limpar_texto(ordem_servico)

        if codigo_empresa:
            params["codigo_empresa"] = codigo_empresa
            params["codigoEmpresa"] = codigo_empresa

        if not params:
            return {
                "sucesso": False,
                "mensagem": "Informe CPF/CNPJ, placa, protocolo ou O.S. para consulta.",
                "dados": [],
                "erro": "Parâmetros de consulta ausentes",
            }

        if not SANCES_POS_VENDA_URL:
            return {
                "sucesso": False,
                "mensagem": "Endpoint de pós-venda Sances não configurado.",
                "dados": [],
                "erro": "SANCES_POS_VENDA_URL não configurada",
            }

        if not SANCES_TOKEN:
            return {
                "sucesso": False,
                "mensagem": "Token Sances não configurado.",
                "dados": [],
                "erro": "SANCES_TOKEN não configurado",
            }

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }

        log_info("[SANCES] Consulta pós-venda/O.S. iniciada:", params)

        response = requests.get(
            SANCES_POS_VENDA_URL,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status pós-venda/O.S.:", response.status_code)
        log_info("[SANCES] Resposta pós-venda/O.S.:", retorno_json)

        sucesso = 200 <= response.status_code < 300
        dados = obter_lista_estoque_sances(retorno_json)

        if sucesso and not dados and isinstance(retorno_json, dict):
            dados = [retorno_json]

        mensagem = ""
        erro = ""

        if isinstance(retorno_json, dict):
            mensagem = limpar_texto(retorno_json.get("mensagem") or retorno_json.get("message") or "")
            erro = limpar_texto(retorno_json.get("erro") or retorno_json.get("error") or "")

        if not sucesso and not erro:
            erro = f"HTTP {response.status_code}"

        resumo = {
            "sucesso": sucesso,
            "mensagem": mensagem,
            "dados": dados if sucesso else [],
            "erro": "" if sucesso else erro,
        }

    except requests.Timeout:
        return {
            "sucesso": False,
            "mensagem": "Timeout ao consultar pós-venda/O.S. Sances.",
            "dados": [],
            "erro": f"Timeout Sances apos {SANCES_TIMEOUT}s",
        }

    except Exception as e:
        log_erro("[SANCES] Erro consulta pós-venda/O.S.:", repr(e))
        return {
            "sucesso": False,
            "mensagem": "Erro ao consultar pós-venda/O.S. Sances.",
            "dados": [],
            "erro": repr(e),
        }


def consultar_negociacao_sances(codigo_negociacao):
    try:
        codigo = limpar_texto(codigo_negociacao)

        if not codigo:
            return {
                "sucesso": False,
                "mensagem": "Código da negociação não informado.",
                "dados": {},
                "erro": "codigo_negociacao ausente",
            }

        if not SANCES_NEGOCIACAO_URL:
            return {
                "sucesso": False,
                "mensagem": "Endpoint de negociação Sances não configurado.",
                "dados": {},
                "erro": "SANCES_NEGOCIACAO_URL não configurada",
            }

        if not SANCES_TOKEN:
            return {
                "sucesso": False,
                "mensagem": "Token Sances não configurado.",
                "dados": {},
                "erro": "SANCES_TOKEN não configurado",
            }

        params = {
            "codigoNegociacao": codigo,
        }
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }

        log_info("[SANCES] Consulta negociação iniciada:", params)

        response = requests.get(
            SANCES_NEGOCIACAO_URL,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status negociação:", response.status_code)
        log_info("[SANCES] Resposta negociação:", retorno_json)

        sucesso_http = 200 <= response.status_code < 300
        sucesso_api = bool(retorno_json.get("sucesso", sucesso_http)) if isinstance(retorno_json, dict) else sucesso_http

        mensagem = ""
        erro = ""

        if isinstance(retorno_json, dict):
            mensagem = limpar_texto(
                retorno_json.get("mensagemUsuarioFinal")
                or retorno_json.get("mensagem")
                or retorno_json.get("message")
                or ""
            )
            erro = limpar_texto(retorno_json.get("erro") or retorno_json.get("error") or "")

        if not sucesso_http and not erro:
            erro = f"HTTP {response.status_code}"

        return {
            "sucesso": sucesso_http and sucesso_api,
            "mensagem": mensagem,
            "dados": retorno_json,
            "erro": "" if sucesso_http and sucesso_api else erro,
        }

    except requests.Timeout:
        return {
            "sucesso": False,
            "mensagem": "Timeout ao consultar negociação Sances.",
            "dados": {},
            "erro": f"Timeout Sances apos {SANCES_TIMEOUT}s",
        }

    except Exception as e:
        log_erro("[SANCES] Erro consulta negociação:", repr(e))
        return {
            "sucesso": False,
            "mensagem": "Erro ao consultar negociação Sances.",
            "dados": {},
            "erro": repr(e),
        }


def consultar_ordens_servico_sances():
    try:
        endpoint_pos_venda = limpar_texto(
            os.getenv("SANCES_POS_VENDA_URL", "")
            or SANCES_API_URL
            or SANCES_POS_VENDA_URL
        )

        if not endpoint_pos_venda:
            return {
                "sucesso": False,
                "configurado": False,
                "mensagem": "A consulta real ao Sances ainda não está configurada.",
                "total_abertas": 0,
                "ordens": [],
                "erro": "SANCES_API_URL/SANCES_POS_VENDA_URL não configurada",
            }

        if not SANCES_TOKEN:
            return {
                "sucesso": False,
                "configurado": False,
                "mensagem": "A consulta real ao Sances ainda não está configurada.",
                "total_abertas": 0,
                "ordens": [],
                "erro": "SANCES_TOKEN não configurado",
            }

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }
        params = {
            "limit": SANCES_LIMIT,
            "offset": SANCES_OFFSET,
        }

        log_info("[SANCES] Consulta real OS abertas iniciada:", endpoint_pos_venda, params)

        response = requests.get(
            endpoint_pos_venda,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status consulta OS abertas:", response.status_code)
        log_info("[SANCES] Resposta consulta OS abertas:", retorno_json)

        if not (200 <= response.status_code < 300):
            return {
                "sucesso": False,
                "configurado": True,
                "mensagem": "Não consegui consultar as ordens de serviço no Sances agora.",
                "total_abertas": 0,
                "ordens": [],
                "erro": f"HTTP {response.status_code}",
            }

        dados = []

        if isinstance(retorno_json, dict):
            dados = retorno_json.get("dados") or []
        elif isinstance(retorno_json, list):
            dados = retorno_json

        if isinstance(dados, dict):
            dados = [dados]

        ordens_abertas = []

        for registro in dados or []:
            if not isinstance(registro, dict):
                continue

            descricao_tipo = limpar_texto(registro.get("descricao_tipo", ""))

            if normalizar_texto(descricao_tipo) != "ordem de servico":
                continue

            situacao = limpar_texto(registro.get("situacao", ""))
            situacao_norm = normalizar_texto(situacao)

            if situacao_norm in ["fechada", "cancelada", "cancelado"]:
                continue

            modelo = limpar_texto(
                registro.get("descricao_modelo_veiculo")
                or registro.get("modelo")
                or registro.get("descricao_modelo")
                or ""
            )
            placa = limpar_texto(registro.get("placa_veiculo") or registro.get("placa") or "")
            moto = " / ".join([valor for valor in [placa, modelo] if valor])

            ordens_abertas.append({
                "numero": registro.get("numero") or registro.get("ordem_servico") or registro.get("codigo"),
                "cliente": limpar_texto(registro.get("nome_cliente") or registro.get("cliente") or ""),
                "moto": moto,
                "data_entrada": limpar_texto(registro.get("data_entrada") or ""),
                "situacao": situacao,
            })

        return {
            "sucesso": True,
            "configurado": True,
            "mensagem": "Registros de pós vendas consultados.",
            "total_abertas": len(ordens_abertas),
            "ordens": ordens_abertas,
            "erro": "",
        }

    except requests.Timeout:
        return {
            "sucesso": False,
            "configurado": True,
            "mensagem": "Timeout ao consultar ordens de serviço no Sances.",
            "total_abertas": 0,
            "ordens": [],
            "erro": f"Timeout Sances apos {SANCES_TIMEOUT}s",
        }

    except Exception as e:
        log_erro("[SANCES] Erro consultar OS abertas:", repr(e))
        return {
            "sucesso": False,
            "configurado": True,
            "mensagem": "Erro ao consultar ordens de serviço no Sances.",
            "total_abertas": 0,
            "ordens": [],
            "erro": repr(e),
        }


def dados_lista_sances(retorno_json):
    if isinstance(retorno_json, list):
        return retorno_json

    if not isinstance(retorno_json, dict):
        return []

    dados = retorno_json.get("dados") or retorno_json.get("data") or retorno_json.get("resultado") or []

    if isinstance(dados, dict):
        return [dados]

    return dados if isinstance(dados, list) else []


def filtrar_os_garantia_aberta(lista_os):
    ordens = []

    for registro in lista_os or []:
        if not isinstance(registro, dict):
            continue

        descricao_tipo = normalizar_texto(registro.get("descricao_tipo", ""))

        if descricao_tipo and descricao_tipo != "ordem de servico":
            continue

        situacao = normalizar_texto(registro.get("situacao", ""))

        if situacao in ["fechada", "cancelada", "cancelado"]:
            continue

        texto_garantia = normalizar_texto(" ".join([
            limpar_texto(registro.get("descricao_tipo_os", "")),
            limpar_texto(registro.get("tipo_os", "")),
            limpar_texto(registro.get("solicitacao_cliente", "")),
            limpar_texto(registro.get("defeito_averiguado", "")),
            limpar_texto(registro.get("observacao", "")),
            limpar_texto(registro.get("observacao_nota", "")),
        ]))

        if "garantia" not in texto_garantia:
            continue

        ordens.append(registro)

    return ordens


def buscar_os_garantia_por_cpf(cpf):
    cpf_limpo = limpar_cpf(cpf)

    if len(cpf_limpo) != 11:
        return []

    try:
        endpoint_pos_venda = limpar_texto(
            os.getenv("SANCES_POS_VENDA_URL", "")
            or SANCES_POS_VENDA_URL
            or SANCES_API_URL
        )

        if not endpoint_pos_venda or not SANCES_TOKEN:
            log_info("[SANCES] Consulta garantia ignorada: endpoint/token nao configurado")
            return []

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }
        params = {
            "limit": SANCES_LIMIT,
            "offset": SANCES_OFFSET,
            "cpf": cpf_limpo,
            "cpf_cliente": cpf_limpo,
            "cpf_cnpj_cliente": cpf_limpo,
            "cpfCnpj": cpf_limpo,
        }

        log_info("[SANCES] Consulta OS garantia por CPF iniciada:", cpf_limpo)

        response = requests.get(
            endpoint_pos_venda,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status OS garantia:", response.status_code)
        log_info("[SANCES] Resposta OS garantia:", retorno_json)

        if not (200 <= response.status_code < 300):
            return []

        return filtrar_os_garantia_aberta(dados_lista_sances(retorno_json))

    except requests.Timeout:
        log_erro("[SANCES] Timeout consulta OS garantia por CPF")
        return []

    except Exception as e:
        log_erro("[SANCES] Erro consulta OS garantia por CPF:", repr(e))
        return []


def extrair_numero_processo_garantia(texto):
    texto = limpar_texto(texto)

    if not texto:
        return ""

    padroes = [
        r"(?:processo|protocolo)\s*(?:de\s*)?(?:garantia)?\s*[:#-]?\s*([A-Za-z0-9./-]{4,})",
        r"garantia\s*[:#-]?\s*([A-Za-z0-9./-]{4,})",
    ]

    for padrao in padroes:
        encontrado = re.search(padrao, texto, flags=re.IGNORECASE)

        if encontrado:
            return limpar_texto(encontrado.group(1))

    return ""


def montar_resumo_os_garantia(os_data):
    os_data = os_data if isinstance(os_data, dict) else {}

    modelo = limpar_texto(
        os_data.get("descricao_modelo_veiculo")
        or os_data.get("modelo")
        or os_data.get("descricao_modelo")
        or ""
    )
    chassi = limpar_texto(os_data.get("chassi") or os_data.get("chassi_serie") or "")

    return {
        "numero": limpar_texto(os_data.get("numero") or os_data.get("ordem_servico") or os_data.get("codigo") or ""),
        "situacao": limpar_texto(os_data.get("situacao") or ""),
        "cliente": limpar_texto(os_data.get("nome_cliente") or os_data.get("cliente") or os_data.get("nome_proprietario") or ""),
        "modelo": modelo,
        "chassi": chassi.upper(),
        "solicitacao_cliente": limpar_texto(os_data.get("solicitacao_cliente") or ""),
        "defeito_averiguado": limpar_texto(os_data.get("defeito_averiguado") or ""),
        "observacao": limpar_texto(os_data.get("observacao") or os_data.get("observacao_nota") or ""),
    }


def montar_resposta_status_garantia(os_data):
    dados = montar_resumo_os_garantia(os_data)
    processo = extrair_numero_processo_garantia(dados.get("observacao", ""))

    linhas = ["Localizei seu processo de garantia no Sances."]

    if dados.get("numero"):
        linhas.append(f"OS: {dados['numero']}")

    if processo:
        linhas.append(f"Processo de garantia: {processo}")

    if dados.get("situacao"):
        linhas.append(f"Situação: {dados['situacao']}")

    if dados.get("cliente"):
        linhas.append(f"Cliente: {dados['cliente']}")

    if dados.get("modelo"):
        linhas.append(f"Moto: {dados['modelo']}")

    if dados.get("chassi"):
        linhas.append(f"Chassi final: {dados['chassi'][-4:]}")

    observacao = dados.get("observacao", "")

    if observacao:
        linhas.append(f"\nObservação da OS:\n{observacao}")
    elif dados.get("defeito_averiguado"):
        linhas.append(f"\nDefeito averiguado:\n{dados['defeito_averiguado']}")
    elif dados.get("solicitacao_cliente"):
        linhas.append(f"\nSolicitação registrada:\n{dados['solicitacao_cliente']}")

    linhas.append("\nSe precisar de mais detalhes, posso direcionar você para um atendente.")

    return "\n".join(linhas)


def montar_lista_os_garantia(ordens):
    linhas = [
        "Encontrei mais de uma OS de garantia em aberto.",
        "Digite o número da opção que deseja consultar:\n",
    ]

    for indice, os_data in enumerate((ordens or [])[:9], start=1):
        resumo = montar_resumo_os_garantia(os_data)
        descricao = " / ".join([
            valor for valor in [
                f"OS {resumo.get('numero')}" if resumo.get("numero") else "",
                resumo.get("situacao", ""),
                resumo.get("modelo", ""),
            ]
            if valor
        ])
        linhas.append(f"{indice} - {descricao or 'OS de garantia'}")

    return "\n".join(linhas)


def valor_numero_pos_venda(valor):
    try:
        if isinstance(valor, (int, float)):
            return float(valor)

        texto = limpar_texto(valor)
        if not texto:
            return 0.0

        texto = texto.replace("R$", "").replace(".", "").replace(",", ".")
        return float(re.sub(r"[^0-9.-]", "", texto) or 0)

    except Exception:
        return 0.0


def formatar_moeda_pos_venda(valor):
    try:
        valor = float(valor or 0)
        texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {texto}"
    except Exception:
        return "R$ 0,00"


def item_pos_venda_cancelado(item):
    try:
        if not isinstance(item, dict):
            return False

        if bool(item.get("cancelado", False)):
            return True

        status = normalizar_texto(
            item.get("situacao", "")
            or item.get("status", "")
            or item.get("descricao_situacao", "")
        )

        return any(termo in status for termo in ["cancelado", "cancelada", "excluido", "excluida"])

    except Exception:
        return False


def obter_lista_pos_venda(registro, chaves):
    try:
        for chave in chaves:
            valor = registro.get(chave)
            if isinstance(valor, list):
                return valor

        for grupo in ["orcamento", "os", "ordem_servico", "ordemServico", "dados"]:
            dados = registro.get(grupo)
            if isinstance(dados, dict):
                for chave in chaves:
                    valor = dados.get(chave)
                    if isinstance(valor, list):
                        return valor

        return []

    except Exception:
        return []


def resumir_item_pos_venda(item):
    try:
        if not isinstance(item, dict):
            return {}

        descricao = limpar_texto(
            item.get("descricao")
            or item.get("nome")
            or item.get("descricao_item")
            or item.get("descricao_peca")
            or item.get("descricao_servico")
            or item.get("produto")
            or item.get("servico")
            or ""
        )

        quantidade = item.get("quantidade", item.get("qtde", item.get("qtd", 1)))
        valor_total = valor_numero_pos_venda(
            item.get("valor_total")
            or item.get("total")
            or item.get("valor_liquido")
            or item.get("valor")
            or 0
        )

        return {
            "descricao": descricao,
            "quantidade": quantidade,
            "valor_total": valor_total,
        }

    except Exception as e:
        log_erro("Erro resumir_item_pos_venda:", repr(e))
        return {}


def resumo_pos_venda_finalizado(situacao, data_saida=""):
    situacao_norm = normalizar_texto(situacao)

    if data_saida:
        return True

    termos_finalizado = [
        "finalizado",
        "concluido",
        "encerrado",
        "faturado",
        "entregue",
        "retirado",
    ]

    return any(termo in situacao_norm for termo in termos_finalizado)


def resumir_pos_venda_para_ia(registro):
    """
    Resume retorno de pós-venda Sances para uso em resposta de IA.
    Recebe JSON com orçamento/O.S., peças, serviços e notas.
    """
    try:
        if not isinstance(registro, dict):
            registro = {}

        pecas_raw = obter_lista_pos_venda(
            registro,
            ["pecas", "peças", "itens_pecas", "itensPecas", "produtos", "itens_produtos"],
        )
        servicos_raw = obter_lista_pos_venda(
            registro,
            ["servicos", "serviços", "itens_servicos", "itensServicos", "mao_obra", "servicos_os"],
        )

        pecas = [
            item
            for item in (resumir_item_pos_venda(p) for p in pecas_raw if not item_pos_venda_cancelado(p))
            if item.get("descricao")
        ]
        servicos = [
            item
            for item in (resumir_item_pos_venda(s) for s in servicos_raw if not item_pos_venda_cancelado(s))
            if item.get("descricao")
        ]

        total_geral = valor_numero_pos_venda(
            registro.get("total_geral")
            or registro.get("valor_total")
            or registro.get("total")
            or registro.get("valor_liquido")
            or 0
        )

        if not total_geral:
            total_geral = sum(p.get("valor_total", 0) for p in pecas)
            total_geral += sum(s.get("valor_total", 0) for s in servicos)

        situacao = limpar_texto(
            registro.get("situacao")
            or registro.get("descricao_situacao")
            or registro.get("status")
            or ""
        )
        data_saida = limpar_texto(registro.get("data_saida") or registro.get("data_fechamento") or "")

        return {
            "descricao_tipo": limpar_texto(
                registro.get("descricao_tipo")
                or registro.get("tipo")
                or registro.get("tipo_atendimento")
                or ""
            ),
            "situacao": situacao,
            "nome_cliente": limpar_texto(registro.get("nome_cliente") or registro.get("cliente") or ""),
            "placa_veiculo": limpar_texto(registro.get("placa_veiculo") or registro.get("placa") or "").upper(),
            "descricao_modelo_veiculo": limpar_texto(
                registro.get("descricao_modelo_veiculo")
                or registro.get("modelo_veiculo")
                or registro.get("modelo")
                or ""
            ),
            "solicitacao_cliente": limpar_texto(
                registro.get("solicitacao_cliente")
                or registro.get("solicitacao")
                or registro.get("observacao_cliente")
                or ""
            ),
            "pecas": pecas,
            "servicos": servicos,
            "total_geral": total_geral,
            "total_geral_formatado": formatar_moeda_pos_venda(total_geral),
            "nome_consultor": limpar_texto(registro.get("nome_consultor") or registro.get("consultor") or ""),
            "data_entrada": limpar_texto(registro.get("data_entrada") or registro.get("data_abertura") or ""),
            "data_saida": data_saida,
            "finalizado": resumo_pos_venda_finalizado(situacao, data_saida),
        }

    except Exception as e:
        log_erro("Erro resumir_pos_venda_para_ia:", repr(e))
        return {
            "descricao_tipo": "",
            "situacao": "",
            "nome_cliente": "",
            "placa_veiculo": "",
            "descricao_modelo_veiculo": "",
            "solicitacao_cliente": "",
            "pecas": [],
            "servicos": [],
            "total_geral": 0,
            "total_geral_formatado": "R$ 0,00",
            "nome_consultor": "",
            "data_entrada": "",
            "data_saida": "",
            "finalizado": False,
        }


def montar_resposta_pos_venda_ia(resumo):
    try:
        resumo = resumo or {}
        linhas = []

        nome = limpar_texto(resumo.get("nome_cliente", ""))
        if nome:
            linhas.append(f"Olá, {nome}! Consultei seu atendimento por aqui.")
        else:
            linhas.append("Consultei seu atendimento por aqui.")

        tipo = limpar_texto(resumo.get("descricao_tipo", ""))
        situacao = limpar_texto(resumo.get("situacao", ""))

        if tipo:
            linhas.append(f"Tipo do atendimento: {tipo}.")

        if situacao:
            linhas.append(f"Situação atual: {situacao}.")

        placa = limpar_texto(resumo.get("placa_veiculo", ""))
        modelo = limpar_texto(resumo.get("descricao_modelo_veiculo", ""))
        if placa or modelo:
            veiculo = " / ".join([v for v in [placa, modelo] if v])
            linhas.append(f"Veículo: {veiculo}.")

        pecas = resumo.get("pecas", []) or []
        if pecas:
            linhas.append("Peças não canceladas:")
            for item in pecas[:8]:
                valor = formatar_moeda_pos_venda(item.get("valor_total", 0))
                linhas.append(f"- {item.get('descricao')} ({item.get('quantidade', 1)}): {valor}")

        servicos = resumo.get("servicos", []) or []
        if servicos:
            linhas.append("Serviços não cancelados:")
            for item in servicos[:8]:
                valor = formatar_moeda_pos_venda(item.get("valor_total", 0))
                linhas.append(f"- {item.get('descricao')} ({item.get('quantidade', 1)}): {valor}")

        linhas.append(
            "Valor total: "
            f"{resumo.get('total_geral_formatado') or formatar_moeda_pos_venda(resumo.get('total_geral', 0))}."
        )

        consultor = limpar_texto(resumo.get("nome_consultor", ""))
        if consultor:
            linhas.append(f"Consultor responsável: {consultor}.")

        if resumo.get("finalizado"):
            linhas.append("O atendimento consta como finalizado.")
        else:
            linhas.append("O atendimento ainda está em andamento.")

        return "\n".join(linhas)

    except Exception as e:
        log_erro("Erro montar_resposta_pos_venda_ia:", repr(e))
        return "Consultei seu atendimento, mas não consegui montar o resumo completo agora."


def numero_sances(valor, padrao=0):
    try:
        if isinstance(valor, (int, float)):
            return valor

        texto = limpar_texto(valor)
        if not texto:
            return padrao

        texto = texto.replace("R$", "").replace(".", "").replace(",", ".")
        numero = float(re.sub(r"[^0-9.-]", "", texto) or padrao)

        if numero.is_integer():
            return int(numero)

        return numero

    except Exception:
        return padrao


def obter_lista_estoque_sances(retorno_json):
    if isinstance(retorno_json, list):
        return retorno_json

    if not isinstance(retorno_json, dict):
        return []

    for chave in ["dados", "produtos", "itens", "data", "resultado", "estoque"]:
        valor = retorno_json.get(chave)
        if isinstance(valor, list):
            return valor

    return []


def consultar_estoque_sances(termo="", codigo_empresa=None):
    try:
        termo = limpar_texto(termo)

        if not SANCES_ESTOQUE_URL:
            return {
                "sucesso": False,
                "mensagem": "Endpoint de estoque Sances não configurado.",
                "dados": [],
                "erro": "SANCES_ESTOQUE_URL não configurada",
            }

        if not SANCES_TOKEN:
            return {
                "sucesso": False,
                "mensagem": "Token Sances não configurado.",
                "dados": [],
                "erro": "SANCES_TOKEN não configurado",
            }

        params = {
            "limit": SANCES_ESTOQUE_LIMIT,
            "offset": SANCES_ESTOQUE_OFFSET,
            "ativo": SANCES_ESTOQUE_ATIVO,
        }

        if termo:
            params["termo"] = termo
            params["descricao"] = termo
            params["referencia"] = termo
            params["codigo"] = termo
            params["codigoBarras"] = termo

        if codigo_empresa:
            params["codigoEmpresa"] = codigo_empresa
            params["codigo_empresa"] = codigo_empresa

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {SANCES_TOKEN}",
        }

        log_info("[SANCES] Consulta de estoque iniciada:", params)

        response = requests.get(
            SANCES_ESTOQUE_URL,
            params=params,
            headers=headers,
            timeout=SANCES_TIMEOUT,
        )

        try:
            retorno_json = response.json()
        except Exception:
            retorno_json = {}

        log_info("[SANCES] Status estoque:", response.status_code)
        log_info("[SANCES] Resposta estoque:", retorno_json)

        sucesso = 200 <= response.status_code < 300
        dados = obter_lista_estoque_sances(retorno_json)
        termo_norm = normalizar_texto(termo)

        if termo_norm:
            dados = [
                item for item in dados
                if termo_norm in normalizar_texto(
                    " ".join([
                        limpar_texto(item.get("descricao") or item.get("nome") or item.get("descricaoProduto") or ""),
                        limpar_texto(item.get("referencia") or item.get("referência") or item.get("codigoReferencia") or ""),
                        limpar_texto(item.get("codigo") or item.get("codigoProduto") or item.get("id") or ""),
                        limpar_texto(item.get("codigoBarras") or item.get("codigo_barras") or item.get("ean") or ""),
                    ])
                )
            ]

        resumos = [
            resumir_item_estoque_para_ia(item, codigo_empresa=codigo_empresa)
            for item in dados
        ]
        resumos = [item for item in resumos if item]

        mensagem = ""
        erro = ""

        if isinstance(retorno_json, dict):
            mensagem = limpar_texto(retorno_json.get("mensagem") or retorno_json.get("message") or "")
            erro = limpar_texto(retorno_json.get("erro") or retorno_json.get("error") or "")

        if not sucesso and not erro:
            erro = f"HTTP {response.status_code}"

        return {
            "sucesso": sucesso,
            "mensagem": mensagem,
            "dados": resumos if sucesso else [],
            "erro": "" if sucesso else erro,
        }

    except requests.Timeout:
        return {
            "sucesso": False,
            "mensagem": "Timeout ao consultar estoque Sances.",
            "dados": [],
            "erro": f"Timeout Sances apos {SANCES_TIMEOUT}s",
        }

    except Exception as e:
        log_erro("[SANCES] Erro consulta estoque:", repr(e))
        return {
            "sucesso": False,
            "mensagem": "Erro ao consultar estoque Sances.",
            "dados": [],
            "erro": repr(e),
        }


def lista_dict_sances(item, chaves):
    if not isinstance(item, dict):
        return []

    for chave in chaves:
        valor = item.get(chave)
        if isinstance(valor, list):
            return [v for v in valor if isinstance(v, dict)]

    return []


def escolher_registro_empresa_sances(lista, codigo_empresa=None):
    if not lista:
        return {}

    if codigo_empresa:
        codigo = str(codigo_empresa)
        for registro in lista:
            codigo_registro = str(
                registro.get("codigoEmpresa")
                or registro.get("codigo_empresa")
                or registro.get("empresa")
                or ""
            )
            if codigo_registro == codigo:
                return registro

    return lista[0]


def resumir_item_estoque_para_ia(item, codigo_empresa=None):
    try:
        if not isinstance(item, dict):
            item = {}

        precos = lista_dict_sances(item, ["precos", "preços", "tabelasPreco", "tabelas_preco"])
        estoques = lista_dict_sances(item, ["estoques", "saldos", "empresas", "estoqueEmpresas"])

        preco_empresa = escolher_registro_empresa_sances(precos, codigo_empresa)
        estoque_empresa = escolher_registro_empresa_sances(estoques, codigo_empresa)

        codigo_empresa_item = (
            codigo_empresa
            or estoque_empresa.get("codigoEmpresa")
            or estoque_empresa.get("codigo_empresa")
            or preco_empresa.get("codigoEmpresa")
            or preco_empresa.get("codigo_empresa")
            or item.get("codigoEmpresa")
            or item.get("codigo_empresa")
            or ""
        )

        resumo = {
            "codigo": limpar_texto(item.get("codigo") or item.get("codigoProduto") or item.get("id") or ""),
            "descricao": limpar_texto(item.get("descricao") or item.get("nome") or item.get("descricaoProduto") or ""),
            "referencia": limpar_texto(item.get("referencia") or item.get("referência") or item.get("codigoReferencia") or ""),
            "codigoBarras": limpar_texto(item.get("codigoBarras") or item.get("codigo_barras") or item.get("ean") or ""),
            "descricaoCategoria": limpar_texto(item.get("descricaoCategoria") or item.get("categoria") or ""),
            "preco_varejo": numero_sances(
                preco_empresa.get("precoVarejo")
                or preco_empresa.get("preco_varejo")
                or item.get("precoVarejo")
                or item.get("preco_varejo")
                or item.get("valor_varejo")
                or 0
            ),
            "preco_atacado": numero_sances(
                preco_empresa.get("precoAtacado")
                or preco_empresa.get("preco_atacado")
                or item.get("precoAtacado")
                or item.get("preco_atacado")
                or 0
            ),
            "preco_promocao": numero_sances(
                preco_empresa.get("precoPromocao")
                or preco_empresa.get("preco_promocao")
                or item.get("precoPromocao")
                or item.get("preco_promocao")
                or 0
            ),
            "estoque_disponivel": numero_sances(
                estoque_empresa.get("disponivel")
                or estoque_empresa.get("estoqueDisponivel")
                or estoque_empresa.get("estoque_disponivel")
                or estoque_empresa.get("quantidade")
                or estoque_empresa.get("saldo")
                or estoque_empresa.get("qtde")
                or item.get("estoqueDisponivel")
                or item.get("estoque_disponivel")
                or item.get("disponivel")
                or item.get("quantidade")
                or item.get("saldo")
                or item.get("qtde")
                or 0
            ),
            "reservado": numero_sances(estoque_empresa.get("reservado") or item.get("reservado") or 0),
            "transito": numero_sances(
                estoque_empresa.get("transito")
                or estoque_empresa.get("trânsito")
                or estoque_empresa.get("emTransito")
                or item.get("transito")
                or 0
            ),
            "pedido": numero_sances(estoque_empresa.get("pedido") or estoque_empresa.get("emPedido") or item.get("pedido") or 0),
            "bo": numero_sances(estoque_empresa.get("BO") or estoque_empresa.get("bo") or item.get("BO") or item.get("bo") or 0),
            "codigoEmpresa": limpar_texto(codigo_empresa_item),
            "empresa": limpar_texto(
                estoque_empresa.get("apelido")
                or estoque_empresa.get("empresa")
                or estoque_empresa.get("nomeEmpresa")
                or item.get("apelido")
                or item.get("empresa")
                or ""
            ),
        }
        resumo["estoque"] = resumo["estoque_disponivel"]
        resumo["quantidade"] = resumo["estoque_disponivel"]
        resumo["valor"] = (
            resumo["preco_promocao"]
            or resumo["preco_varejo"]
            or resumo["preco_atacado"]
            or numero_sances(item.get("valor") or item.get("preco") or item.get("preco_unitario") or 0)
        )
        return resumo

    except Exception as e:
        log_erro("Erro resumir_item_estoque_para_ia:", repr(e))
        return {}


def montar_resposta_estoque_ia(resumos):
    try:
        if isinstance(resumos, dict):
            resumos = [resumos]

        resumos = [r for r in (resumos or []) if isinstance(r, dict)]

        if not resumos:
            return (
                "Não encontrei estoque para esse item agora. "
                "Posso pedir para um consultor verificar a previsão e uma alternativa compatível."
            )

        linhas = []

        if len(resumos) == 1:
            item = resumos[0]
            linhas.append(f"Encontrei: {item.get('descricao') or 'peça consultada'}.")

            if item.get("referencia"):
                linhas.append(f"Referência: {item.get('referencia')}.")

            disponivel = numero_sances(item.get("estoque_disponivel", 0))
            linhas.append(f"Estoque disponível: {disponivel}.")

            if item.get("preco_varejo"):
                linhas.append(f"Preço varejo: {formatar_moeda_pos_venda(item.get('preco_varejo'))}.")

            if item.get("preco_atacado"):
                linhas.append(f"Preço atacado: {formatar_moeda_pos_venda(item.get('preco_atacado'))}.")

            if disponivel <= 0:
                linhas.append("No momento não consta estoque disponível. Posso verificar a previsão com um consultor.")

            return "\n".join(linhas)

        linhas.append("Encontrei algumas opções:")

        for item in resumos[:5]:
            disponivel = numero_sances(item.get("estoque_disponivel", 0))
            referencia = f" | Ref.: {item.get('referencia')}" if item.get("referencia") else ""
            varejo = (
                f" | Varejo: {formatar_moeda_pos_venda(item.get('preco_varejo'))}"
                if item.get("preco_varejo")
                else ""
            )
            atacado = (
                f" | Atacado: {formatar_moeda_pos_venda(item.get('preco_atacado'))}"
                if item.get("preco_atacado")
                else ""
            )

            linhas.append(
                f"- {item.get('descricao') or 'Item'}{referencia} | Estoque: {disponivel}{varejo}{atacado}"
            )

        if any(numero_sances(item.get("estoque_disponivel", 0)) <= 0 for item in resumos[:5]):
            linhas.append("Para os itens sem estoque, posso verificar previsão com um consultor.")

        return "\n".join(linhas)

    except Exception as e:
        log_erro("Erro montar_resposta_estoque_ia:", repr(e))
        return "Consultei o estoque, mas não consegui montar a resposta completa agora."


CATALOGO_ATACADO_TEXTO_CACHE = {
    "arquivo": "",
    "mtime": 0,
    "texto": "",
    "linhas": [],
}


def extrair_peca_modelo_do_texto(texto):
    try:
        texto_original = limpar_texto(texto)
        texto_norm = normalizar_texto(texto_original)

        modelos = {
            "lander": "LANDER",
            "xtz 250": "LANDER",
            "fazer 250": "FAZER 250",
            "fz25": "FAZER 250",
            "fz 25": "FAZER 250",
            "fazer 150": "FZ15",
            "fz15": "FZ15",
            "fz 15": "FZ15",
            "crosser": "CROSSER",
            "xtz 150": "CROSSER",
            "factor": "FACTOR",
            "nmax": "NMAX",
            "neo": "NEO",
            "fluo": "FLUO",
            "aerox": "AEROX",
            "tenere": "TENERE 700",
            "teneré": "TENERE 700",
            "tenere 700": "TENERE 700",
            "t7": "TENERE 700",
            "mt03": "MT-03",
            "mt 03": "MT-03",
            "mt-03": "MT-03",
            "r15": "R15",
            "r3": "R3",
        }

        modelo = ""
        for chave, valor in modelos.items():
            if chave in texto_norm:
                modelo = valor
                break

        termo = texto_norm
        termo = re.sub(
            r"\b(tem|voce tem|vocês tem|preciso|quero|valor|preco|preço|quanto|custa|da|do|de|para|pra)\b",
            " ",
            termo,
        )

        for chave in modelos:
            termo = termo.replace(chave, " ")

        termo = re.sub(r"[^a-z0-9\s./-]", " ", termo)
        termo = re.sub(r"\s+", " ", termo).strip()

        return {
            "termo_peca": termo,
            "modelo": modelo,
            "texto_original": texto_original,
        }

    except Exception as e:
        log_erro("Erro extrair_peca_modelo_do_texto:", repr(e))
        return {
            "termo_peca": "",
            "modelo": "",
            "texto_original": limpar_texto(texto),
        }


def carregar_texto_catalogo_atacado():
    try:
        caminho_pdf = os.path.join(app.root_path, "static", "pdfs", "catalogo_atacado.pdf")

        if not os.path.exists(caminho_pdf):
            log_erro("Catálogo atacado não encontrado:", caminho_pdf)
            return []

        mtime = os.path.getmtime(caminho_pdf)

        if (
            CATALOGO_ATACADO_TEXTO_CACHE.get("arquivo") == caminho_pdf
            and CATALOGO_ATACADO_TEXTO_CACHE.get("mtime") == mtime
            and CATALOGO_ATACADO_TEXTO_CACHE.get("linhas")
        ):
            return CATALOGO_ATACADO_TEXTO_CACHE.get("linhas", [])

        import pdfplumber

        linhas = []
        with pdfplumber.open(caminho_pdf) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text() or ""
                for linha in texto.splitlines():
                    linha = limpar_texto(linha)
                    if linha:
                        linhas.append(linha)

        CATALOGO_ATACADO_TEXTO_CACHE.update({
            "arquivo": caminho_pdf,
            "mtime": mtime,
            "texto": "\n".join(linhas),
            "linhas": linhas,
        })

        return linhas

    except Exception as e:
        log_erro("Erro carregar_texto_catalogo_atacado:", repr(e))
        return []


def pontuar_linha_catalogo(linha_norm, termo_norm, modelo_norm):
    score = 0

    termos = [t for t in termo_norm.split() if len(t) >= 2]
    for termo in termos:
        if termo in linha_norm:
            score += 3

    if modelo_norm and modelo_norm in linha_norm:
        score += 8

    if termo_norm and termo_norm in linha_norm:
        score += 5

    return score


def extrair_referencia_catalogo(linha):
    try:
        candidatos = re.findall(r"\b[A-Z0-9][A-Z0-9./-]{4,}\b", linha.upper())
        ignorar = {
            "YAMAHA", "LANDER", "FAZER", "CROSSER", "FACTOR", "TENERE",
            "AEROX", "NMAX", "NEO", "FLUO", "MODELO", "CODIGO", "PRECO",
        }

        for candidato in candidatos:
            if candidato in ignorar:
                continue
            if re.search(r"\d", candidato):
                return candidato

        return candidatos[0] if candidatos else ""

    except Exception:
        return ""


def buscar_referencia_no_catalogo(termo_peca, modelo):
    try:
        termo_peca = limpar_texto(termo_peca)
        modelo = limpar_texto(modelo)

        if not termo_peca:
            return {
                "encontrado": False,
                "referencia": "",
                "descricao": "",
                "modelo": modelo,
                "linha_catalogo": "",
                "erro": "Termo da peça vazio",
            }

        linhas = carregar_texto_catalogo_atacado()
        termo_norm = normalizar_texto(termo_peca)
        modelo_norm = normalizar_texto(modelo)

        melhor = {
            "score": 0,
            "linha": "",
            "referencia": "",
        }

        for linha in linhas:
            linha_norm = normalizar_texto(linha)
            score = pontuar_linha_catalogo(linha_norm, termo_norm, modelo_norm)

            if score <= melhor["score"]:
                continue

            referencia = extrair_referencia_catalogo(linha)
            if not referencia:
                continue

            melhor = {
                "score": score,
                "linha": linha,
                "referencia": referencia,
            }

        if not melhor.get("referencia"):
            return {
                "encontrado": False,
                "referencia": "",
                "descricao": termo_peca,
                "modelo": modelo,
                "linha_catalogo": "",
                "erro": "Referência não encontrada no catálogo",
            }

        return {
            "encontrado": True,
            "referencia": melhor["referencia"],
            "descricao": termo_peca,
            "modelo": modelo,
            "linha_catalogo": melhor["linha"],
            "erro": "",
        }

    except Exception as e:
        log_erro("Erro buscar_referencia_no_catalogo:", repr(e))
        return {
            "encontrado": False,
            "referencia": "",
            "descricao": limpar_texto(termo_peca),
            "modelo": limpar_texto(modelo),
            "linha_catalogo": "",
            "erro": repr(e),
        }


def consultar_estoque_sances_por_referencia(referencia):
    try:
        referencia = limpar_texto(referencia)

        if not referencia:
            return {
                "sucesso": False,
                "mensagem": "Referência não informada.",
                "dados": [],
                "erro": "Referência vazia",
            }

        return consultar_estoque_sances(referencia)

    except Exception as e:
        log_erro("Erro consultar_estoque_sances_por_referencia:", repr(e))
        return {
            "sucesso": False,
            "mensagem": "Erro ao consultar estoque por referência.",
            "dados": [],
            "erro": repr(e),
        }


def responder_estoque_peca_por_ia(texto_cliente):
    try:
        extraido = extrair_peca_modelo_do_texto(texto_cliente)
        termo_peca = extraido.get("termo_peca", "")
        modelo = extraido.get("modelo", "")

        if not termo_peca:
            return {
                "sucesso": False,
                "encaminhar_humano": True,
                "mensagem": "Não consegui identificar a peça. Vou encaminhar para um consultor te ajudar.",
                "dados": {
                    "extraido": extraido,
                },
                "erro": "Peça não identificada",
            }

        referencia = buscar_referencia_no_catalogo(termo_peca, modelo)

        if not referencia.get("encontrado"):
            return {
                "sucesso": False,
                "encaminhar_humano": True,
                "mensagem": "Não encontrei essa referência no catálogo agora. Vou encaminhar para um consultor verificar para você.",
                "dados": {
                    "extraido": extraido,
                    "catalogo": referencia,
                },
                "erro": referencia.get("erro", ""),
            }

        estoque = consultar_estoque_sances_por_referencia(referencia.get("referencia", ""))

        if not estoque.get("sucesso"):
            return {
                "sucesso": False,
                "encaminhar_humano": True,
                "mensagem": "Encontrei a referência no catálogo, mas não consegui consultar o estoque agora. Vou encaminhar para um consultor confirmar.",
                "dados": {
                    "extraido": extraido,
                    "catalogo": referencia,
                    "estoque": estoque,
                },
                "erro": estoque.get("erro", ""),
            }

        resumos = [
            resumir_item_estoque_para_ia(item)
            for item in estoque.get("dados", [])
        ]
        resumos = [r for r in resumos if r]

        resposta_estoque = montar_resposta_estoque_ia(resumos)
        primeiro = resumos[0] if resumos else {}

        linhas = [
            f"Peça: {primeiro.get('descricao') or termo_peca}",
        ]

        if modelo:
            linhas.append(f"Modelo: {modelo}.")

        linhas.append(f"Referência encontrada: {referencia.get('referencia')}.")

        if primeiro.get("empresa"):
            linhas.append(f"Unidade: {primeiro.get('empresa')}.")

        linhas.append(resposta_estoque)

        sem_estoque = not resumos or all(numero_sances(r.get("estoque_disponivel", 0)) <= 0 for r in resumos)

        if sem_estoque:
            linhas.append("Como não consta estoque disponível, vou encaminhar para um consultor verificar previsão ou alternativa.")

        return {
            "sucesso": bool(resumos) and not sem_estoque,
            "encaminhar_humano": sem_estoque,
            "mensagem": "\n".join(linhas),
            "dados": {
                "extraido": extraido,
                "catalogo": referencia,
                "estoque": estoque,
                "resumos": resumos,
            },
            "erro": "",
        }

    except Exception as e:
        log_erro("Erro responder_estoque_peca_por_ia:", repr(e))
        return {
            "sucesso": False,
            "encaminhar_humano": True,
            "mensagem": "Não consegui consultar essa peça agora. Vou encaminhar para um consultor te ajudar.",
            "dados": {},
            "erro": repr(e),
        }


def validar_data(data):
    try:
        data_obj = datetime.strptime(
            limpar_texto(data),
            "%d/%m/%Y"
        )

        if data_obj.date() < datetime.now().date():
            return False

        if data_obj.weekday() == 6:
            return False

        return True

    except Exception:
        return False


def data_bate_com_dia_semana(data, dia_numero):
    try:
        data_obj = datetime.strptime(
            limpar_texto(data),
            "%d/%m/%Y"
        )

        dia_real = str(data_obj.weekday() + 1)

        return dia_real == str(dia_numero)

    except Exception:
        return False


def gerar_protocolo():
    return f"REV-{uuid.uuid4().hex[:8].upper()}"


def gerar_protocolo_unico(db):
    try:
        for _ in range(10):
            protocolo = gerar_protocolo()

            existe = (
                db.query(AgendamentoRevisao)
                .filter(
                    AgendamentoRevisao.protocolo == protocolo
                )
                .first()
            )

            if not existe:
                return protocolo

        return gerar_protocolo()

    except Exception:
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

        dados = dados or {}

        data_agendada = limpar_texto(dados.get("data", ""))
        horario = limpar_texto(dados.get("horario", ""))
        revisao = limpar_texto(dados.get("revisao", ""))
        dia = limpar_texto(dados.get("dia", ""))

        if not validar_data(data_agendada):
            log_erro("Data inválida ao salvar agendamento:", data_agendada)
            return False, ""

        if dia and not data_bate_com_dia_semana(data_agendada, dia):
            log_erro("Data não bate com dia escolhido:", data_agendada, dia, nome_dia(dia))
            return False, ""

        horarios_validos = horarios_por_revisao(revisao, dia)

        if horario not in horarios_validos:
            log_erro("Horário inválido para revisão/dia:", horario, revisao, dia)
            return False, ""

        if not verificar_capacidade(data_agendada, horario, revisao):
            log_erro("Sem capacidade para salvar agendamento:", data_agendada, horario, revisao)
            return False, ""

        protocolo = gerar_protocolo_unico(db)

        itens_formatados = formatar_itens_adicionais_para_salvar(
            dados.get("itens", "")
        )

        venda_formatada = formatar_itens_adicionais_para_salvar(
            dados.get("venda_adicional", "")
        )

        vazios = [
            "", "NENHUM", "NENHUMA", "NAO", "NÃO",
            "SEM ITEM", "SEM ITENS", "2", "-", "OK", "SEM", "NADA"
        ]

        if limpar_texto(itens_formatados).upper() in vazios:
            itens_formatados = ""

        if limpar_texto(venda_formatada).upper() in vazios:
            venda_formatada = "Nenhum"

        observacao = limpar_texto(dados.get("observacao", ""))

        if observacao.upper() in [
            "", "NENHUMA", "NENHUM", "NAO", "NÃO",
            "SEM OBSERVACAO", "SEM OBSERVAÇÃO", "2", "-", "OK", "SEM", "NADA"
        ]:
            observacao = "Nenhuma"

        origem = limpar_texto(dados.get("origem", "")) or "BOT"

        agendamento = AgendamentoRevisao()

        def setar(campo, valor):
            try:
                if hasattr(agendamento, campo):
                    setattr(agendamento, campo, valor)
            except Exception as e:
                log_erro(f"Erro ao setar campo {campo} em Agendamento:", repr(e))

        setar("protocolo", protocolo)
        setar("telefone", telefone)
        setar("nome", limpar_texto(dados.get("nome", "")).upper())
        setar("cpf", limpar_cpf(dados.get("cpf", "")))
        setar("modelo", limpar_texto(dados.get("modelo", "")).upper())
        setar("placa", limpar_texto(dados.get("placa", "")).upper())
        setar("chassi", limpar_texto(dados.get("chassi", "")).upper())
        setar("ano", limpar_texto(dados.get("ano", "")))
        setar("km_atual", limpar_texto(dados.get("km_atual", "")))
        setar("tipo_atendimento", limpar_texto(dados.get("tipo_atendimento", "")))
        setar("revisao", revisao)
        setar("dia_semana", nome_dia(dia))
        setar("data_agendada", data_agendada)
        setar("horario", horario)
        setar("itens", itens_formatados)
        setar("venda_adicional", venda_formatada)
        setar("status", normalizar_status(STATUS_AGENDADO))
        setar("observacoes", observacao)
        setar("origem", origem)

        setar("sances_status", SANCES_STATUS_PENDENTE)
        setar("sances_enviado", False)
        setar("sances_protocolo", "")
        setar("sances_erro", "")
        setar("sances_data_envio", None)
        setar("sances_tentativas", 0)
        setar("sances_ultima_tentativa", None)
        setar("sances_ultimo_retorno", "")

        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)

        try:
            dados_evento = dict(dados)
            dados_evento["protocolo"] = protocolo
            dados_evento["status"] = STATUS_AGENDADO
            dados_evento["data"] = data_agendada
            dados_evento["horario"] = horario
            dados_evento["itens"] = itens_formatados
            dados_evento["venda_adicional"] = venda_formatada
            dados_evento["observacao"] = observacao
            dados_evento["origem"] = origem

            salvar_atendimento_dashboard(telefone, dados_evento)

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
    dados = dados or {}

    return salvar_evento_atendimento(
        telefone=telefone,
        setor="Revisão",
        status=STATUS_AGENDADO,
        etapa="revisao_finalizada",
        dados=dados,
        atendimento_humano=False,
        concluido=True,
        origem=limpar_texto(dados.get("origem", "")) or "BOT",
        observacao=limpar_texto(dados.get("observacao", "")),
        intencao_ia=limpar_texto(dados.get("intencao_ia", "")),
    )
# ==========================================
# CONSULTA / CANCELAMENTO / REAGENDAMENTO
# ==========================================
def agendamento_para_dict(agendamento):
    if not agendamento:
        return None

    try:
        return {
            "protocolo": str(getattr(agendamento, "protocolo", "") or ""),
            "telefone": str(getattr(agendamento, "telefone", "") or ""),
            "nome": str(getattr(agendamento, "nome", "") or ""),
            "cpf": str(getattr(agendamento, "cpf", "") or ""),
            "modelo": str(getattr(agendamento, "modelo", "") or ""),
            "ano": str(getattr(agendamento, "ano", "") or ""),
            "km_atual": str(getattr(agendamento, "km_atual", "") or ""),
            "tipo_atendimento": str(getattr(agendamento, "tipo_atendimento", "") or ""),
            "revisao": str(getattr(agendamento, "revisao", "") or ""),
            "dia_semana": str(getattr(agendamento, "dia_semana", "") or ""),
            "data_agendada": str(getattr(agendamento, "data_agendada", "") or ""),
            "horario": str(getattr(agendamento, "horario", "") or ""),
            "itens": str(getattr(agendamento, "itens", "") or ""),
            "venda_adicional": str(getattr(agendamento, "venda_adicional", "") or ""),
            "observacoes": str(getattr(agendamento, "observacoes", "") or ""),
            "status": str(getattr(agendamento, "status", "") or ""),
            "origem": str(getattr(agendamento, "origem", "") or "BOT"),
            "sances_status": str(getattr(agendamento, "sances_status", "") or ""),
            "sances_enviado": bool(getattr(agendamento, "sances_enviado", False)),
            "sances_protocolo": str(getattr(agendamento, "sances_protocolo", "") or ""),
            "sances_erro": str(getattr(agendamento, "sances_erro", "") or ""),
            "sances_tentativas": int(getattr(agendamento, "sances_tentativas", 0) or 0),
        }

    except Exception as e:
        log_erro("Erro ao converter agendamento para dict:", repr(e))
        return None


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
                AgendamentoRevisao.status.in_([
                    STATUS_AGENDADO,
                    STATUS_CONFIRMADO,
                    normalizar_status(STATUS_AGENDADO),
                    normalizar_status(STATUS_CONFIRMADO),
                ]),
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
                AgendamentoRevisao.status.in_([
                    STATUS_AGENDADO,
                    STATUS_CONFIRMADO,
                    normalizar_status(STATUS_AGENDADO),
                    normalizar_status(STATUS_CONFIRMADO),
                ]),
            )
            .order_by(AgendamentoRevisao.id.desc())
            .first()
        )

        if not agendamento:
            return None

        agendamento.status = normalizar_status(novo_status)

        if normalizar_status(novo_status) in [
            normalizar_status(STATUS_CANCELADO),
            normalizar_status(STATUS_REAGENDADO),
            normalizar_status(STATUS_CONFIRMADO),
        ]:
            if hasattr(agendamento, "sances_status"):
                agendamento.sances_status = SANCES_STATUS_PENDENTE

            if hasattr(agendamento, "sances_enviado"):
                agendamento.sances_enviado = False

            if hasattr(agendamento, "sances_erro"):
                agendamento.sances_erro = (
                    "Aguardando integração operacional de "
                    f"{normalizar_status(novo_status).lower()}."
                )

        if hasattr(agendamento, "atualizado_em"):
            agendamento.atualizado_em = agora_datetime()

        db.commit()
        db.refresh(agendamento)

        dados = agendamento_para_dict(agendamento) or {}

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


def botoes_pos_consulta_agendamento():
    return [
        {"id": "REAGENDAR_AGENDAMENTO", "label": "Reagendar"},
        {"id": "CANCELAR_AGENDAMENTO", "label": "Cancelar"},
        {"id": "MENU", "label": "Menu principal"},
    ]


def botoes_novo_agendamento_menu():
    return [
        {"id": "AGENDAR_REVISAO", "label": "Agendar revisão"},
        {"id": "MENU", "label": "Menu principal"},
    ]


def botoes_cancelamento_menu():
    return [
        {"id": "AGENDAR_REVISAO", "label": "Novo agendamento"},
        {"id": "MENU", "label": "Menu principal"},
    ]


def responder_consulta_agendamento(telefone, cpf):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    cpf_limpo = limpar_cpf(cpf)

    if not cpf_limpo or len(cpf_limpo) != 11:
        enviar_mensagem(
            telefone,
            "📄 Para consultar seu agendamento, informe seu *CPF com 11 números*."
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

        resetar_cliente(telefone)

        enviar_mensagem(
            telefone,
            "⚠️ Não localizei agendamento ativo para este CPF.\n\n"
            "Deseja iniciar um novo agendamento?\n\n"
            "1️⃣ Agendar revisão\n"
            "2️⃣ Voltar ao menu\n\n"
            "Digite apenas o número da opção desejada."
        )

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

    enviar_mensagem(
        telefone,
        "📋 *Agendamento localizado*\n\n"
        f"👤 {ag.get('nome', '')}\n"
        f"🏍️ {ag.get('modelo', '')}\n"
        f"🔧 Revisão: {ag.get('revisao', '')}ª\n"
        f"📅 {ag.get('data_agendada', '')}\n"
        f"⏰ {ag.get('horario', '')}\n"
        f"📌 Protocolo: {ag.get('protocolo', '')}\n\n"
        "O que deseja fazer?\n\n"
        "1️⃣ Reagendar\n"
        "2️⃣ Cancelar\n"
        "3️⃣ Menu principal\n\n"
        "Digite apenas o número da opção desejada."
    )

    clientes[telefone]["cpf"] = cpf_limpo
    clientes[telefone]["etapa"] = "pos_consulta_agendamento"
    clientes[telefone]["ultima_interacao"] = agora()

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
                "📄 Para cancelar seu agendamento, informe seu *CPF com 11 números*."
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

            resetar_cliente(telefone)

            enviar_mensagem(
                telefone,
                "⚠️ Não encontrei agendamento ativo para este CPF.\n\n"
                "Deseja voltar ao menu?\n\n"
                "1️⃣ Menu principal\n"
                "2️⃣ Atendimento humano\n\n"
                "Digite apenas o número da opção desejada."
            )

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

        resetar_cliente(telefone)

        enviar_mensagem(
            telefone,
            "✅ *Agendamento cancelado com sucesso*\n\n"
            f"👤 {ag_cancelado.get('nome', '')}\n"
            f"🏍️ {ag_cancelado.get('modelo', '')}\n"
            f"📅 {ag_cancelado.get('data_agendada', '')}\n"
            f"⏰ {ag_cancelado.get('horario', '')}\n"
            f"📌 Protocolo: {ag_cancelado.get('protocolo', '')}\n\n"
            "Equipe Motoshow Yamaha\n\n"
            "1️⃣ Novo agendamento\n"
            "2️⃣ Menu principal\n\n"
            "Digite apenas o número da opção desejada."
        )

        return True

    except Exception as e:
        log_erro("Erro responder_cancelamento_agendamento:", repr(e))

        try:
            enviar_mensagem(
                telefone,
                "⚠️ O cancelamento foi processado, mas ocorreu uma falha ao finalizar a resposta. Envie *menu* para continuar."
            )
            resetar_cliente(telefone)
        except Exception:
            pass

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
            "📄 Para reagendar, informe seu *CPF com 11 números*."
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

        resetar_cliente(telefone)

        enviar_mensagem(
            telefone,
            "⚠️ Não encontrei agendamento ativo para este CPF.\n\n"
            "Deseja iniciar um novo agendamento?\n\n"
            "1️⃣ Agendar revisão\n"
            "2️⃣ Voltar ao menu\n\n"
            "Digite apenas o número da opção desejada."
        )

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

    cancelar_agendamento(cpf_limpo, novo_status=STATUS_REAGENDADO)

    limpar_dados_fluxo_revisao(telefone)

    clientes[telefone]["modelo"] = limpar_texto(ag.get("modelo", "")).upper()
    clientes[telefone]["nome"] = limpar_texto(ag.get("nome", "")).upper()
    clientes[telefone]["cpf"] = limpar_cpf(ag.get("cpf", ""))
    clientes[telefone]["ano"] = limpar_texto(ag.get("ano", ""))
    clientes[telefone]["revisao"] = limpar_texto(ag.get("revisao", ""))
    clientes[telefone]["reagendamento"] = True
    clientes[telefone]["protocolo_antigo"] = ag.get("protocolo", "")
    clientes[telefone]["origem"] = ag.get("origem", "BOT")
    clientes[telefone]["status"] = STATUS_REAGENDADO
    clientes[telefone]["venda_etapa_concluida"] = True
    clientes[telefone]["observacao_etapa_concluida"] = True
    clientes[telefone]["ultima_interacao"] = agora()
    clientes[telefone]["etapa"] = "revisao_dia"

    enviar_mensagem(
        telefone,
        "🔄 *Reagendamento iniciado*\n\n"
        "Encontrei seu agendamento anterior e vou te ajudar a escolher uma nova data."
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
            return False

        if not ARQUIVO_FOLLOWUP:
            return False

        with followup_lock:
            if not os.path.exists(ARQUIVO_FOLLOWUP):
                return False

            df = pd.read_excel(ARQUIVO_FOLLOWUP, dtype=str).fillna("")

            if df.empty:
                return False

            colunas = {str(c).strip().lower(): c for c in df.columns}
            coluna_telefone = None

            for chave in ["telefone", "fone", "whatsapp", "celular", "numero", "número"]:
                if chave in colunas:
                    coluna_telefone = colunas[chave]
                    break

            if not coluna_telefone:
                return False

            coluna_retorno = colunas.get("retorno") or "STATUS_RETORNO"
            coluna_data_retorno = colunas.get("data_retorno") or "DATA_RETORNO"
            coluna_ultima_interacao = colunas.get("ultima_interacao") or "ULTIMA_INTERACAO"

            for coluna in [coluna_retorno, coluna_data_retorno, coluna_ultima_interacao]:
                if coluna not in df.columns:
                    df[coluna] = ""

            for idx in df.index:
                tel_planilha = limpar_telefone(df.at[idx, coluna_telefone])

                if tel_planilha == telefone:
                    agora_fmt = formatar_data_hora()
                    df.at[idx, coluna_retorno] = "RESPONDEU"
                    df.at[idx, coluna_data_retorno] = agora_fmt
                    df.at[idx, coluna_ultima_interacao] = agora_fmt

                    if "OBS" in df.columns:
                        df.at[idx, "OBS"] = texto

                    df.to_excel(ARQUIVO_FOLLOWUP, index=False)
                    return True

            return False

    except Exception as e:
        log_erro("Erro ao atualizar retorno na planilha:", repr(e))
        return False


def processar_lembretes_agendamento():
    db = SessionLocal()

    try:
        agora_time = datetime.now()
        hoje = agora_time.date()
        houve_alteracao = False

        query = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.status.in_([
                STATUS_AGENDADO,
                STATUS_CONFIRMADO,
                normalizar_status(STATUS_AGENDADO),
                normalizar_status(STATUS_CONFIRMADO),
            ])
        )

        if hasattr(AgendamentoRevisao, "lembrete_enviado"):
            query = query.filter(AgendamentoRevisao.lembrete_enviado == False)

        agendamentos = query.all()

        for ag in agendamentos:
            try:
                telefone = limpar_telefone(getattr(ag, "telefone", "") or "")

                if not telefone:
                    continue

                if cliente_em_atendimento_humano(telefone):
                    continue

                if hasattr(ag, "lembrete_enviado") and bool(getattr(ag, "lembrete_enviado", False)):
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

                if diferenca != 1:
                    continue

                data_criacao = (
                    getattr(ag, "criado_em", None)
                    or getattr(ag, "created_at", None)
                    or getattr(ag, "data", None)
                )

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
                    "Escolha uma opção:\n\n"
                    "1️⃣ Confirmar presença\n"
                    "2️⃣ Reagendar\n"
                    "3️⃣ Falar com consultor\n\n"
                    "Digite apenas o número da opção desejada."
                )

                enviado = enviar_mensagem(telefone, mensagem)

                if enviado and hasattr(ag, "lembrete_enviado"):
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

    if "acess" in setor or "acessorios" in etapa or "acessórios" in etapa:
        return (
            "👋 Oi! Vi que você estava olhando acessórios Yamaha.\n\n"
            "Quer que eu te ajude com um orçamento?"
        )

    if "pec" in setor or "peç" in setor or "pecas" in etapa or "peças" in etapa:
        return (
            "👋 Oi! Vi que você começou uma solicitação de peças.\n\n"
            "Quer me enviar o item que precisa para continuarmos?"
        )

    if "garantia" in setor or "garantia" in etapa:
        return (
            "👋 Oi! Vi que você começou uma solicitação de garantia.\n\n"
            "Pode me enviar os detalhes para eu te ajudar?"
        )

    if "atacado" in setor or "atacado" in etapa or "logista" in setor:
        return (
            "👋 Oi! Vi que você começou um atendimento de atacado.\n\n"
            "Quer continuar sua solicitação?"
        )

    return (
        "👋 Oi! Vi que você começou um atendimento e não finalizou.\n\n"
        "Posso te ajudar a concluir rapidinho? 🚀"
    )


def processar_followup_inteligente():
    try:
        processar_followups_banco()
        return True

    except Exception as e:
        log_erro("Erro processar_followup_inteligente:", repr(e))
        return False

# ==========================================
# APOIO DÚVIDAS / REVISÃO / SANCES
# ==========================================
def encerrar_atendimento_humano(telefone):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            return False

        try:
            desativar_atendimento_humano(telefone)
        except Exception:
            iniciar_cliente(telefone)
            clientes[telefone]["atendimento_humano"] = False
            clientes[telefone]["etapa"] = "menu"
            clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Atendimento Humano",
            status=STATUS_NOVO_ATENDIMENTO,
            etapa="atendimento_humano_encerrado",
            dados=clientes.get(telefone, {}),
            atendimento_humano=False,
            concluido=True,
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
                "placa": limpar_texto(ag.get("placa", "")),
                "chassi": limpar_texto(ag.get("chassi", "")),
                "ano": limpar_texto(ag.get("ano", "")),
                "revisao": limpar_texto(ag.get("revisao", "")),
                "dia": limpar_texto(ag.get("dia", "")),
                "data": limpar_texto(ag.get("data_agendada", "") or ag.get("data", "")),
                "horario": limpar_texto(ag.get("horario", "")),
                "itens": formatar_itens_adicionais_para_salvar(ag.get("itens", "")),
                "venda_adicional": formatar_itens_adicionais_para_salvar(ag.get("venda_adicional", "")),
                "observacao": limpar_texto(ag.get("observacoes", "") or ag.get("observacao", "")),
                "tipo_atendimento": limpar_texto(ag.get("tipo_atendimento", "")),
                "protocolo": limpar_texto(ag.get("protocolo", "")),
                "origem": limpar_texto(ag.get("origem", "")) or "BOT",
            }

        return {
            "telefone": limpar_telefone(getattr(ag, "telefone", "")),
            "nome": limpar_texto(getattr(ag, "nome", "")),
            "cpf": limpar_cpf(getattr(ag, "cpf", "")),
            "modelo": limpar_texto(getattr(ag, "modelo", "")),
            "placa": limpar_texto(getattr(ag, "placa", "")),
            "chassi": limpar_texto(getattr(ag, "chassi", "")),
            "ano": limpar_texto(getattr(ag, "ano", "")),
            "revisao": limpar_texto(getattr(ag, "revisao", "")),
            "dia": "",
            "data": limpar_texto(getattr(ag, "data_agendada", "")),
            "horario": limpar_texto(getattr(ag, "horario", "")),
            "itens": formatar_itens_adicionais_para_salvar(getattr(ag, "itens", "")),
            "venda_adicional": formatar_itens_adicionais_para_salvar(getattr(ag, "venda_adicional", "")),
            "observacao": limpar_texto(getattr(ag, "observacoes", "") or getattr(ag, "observacao", "")),
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

        if hasattr(ag, "sances_status"):
            ag.sances_status = status

        if hasattr(ag, "sances_enviado"):
            ag.sances_enviado = sucesso

        if hasattr(ag, "sances_protocolo"):
            dados_retorno = retorno_sances.get("dados", {}) or {}
            if not isinstance(dados_retorno, dict):
                dados_retorno = {}
            resposta_retorno = dados_retorno.get("resposta", {}) or {}
            if not isinstance(resposta_retorno, dict):
                resposta_retorno = {}

            ag.sances_protocolo = limpar_texto(
                retorno_sances.get("protocolo_sances", "")
                or dados_retorno.get("protocolo", "")
                or dados_retorno.get("id", "")
                or dados_retorno.get("codigo_agendamento", "")
                or resposta_retorno.get("protocolo", "")
                or resposta_retorno.get("id", "")
                or resposta_retorno.get("codigo_agendamento", "")
            )

        if hasattr(ag, "sances_erro"):
            ag.sances_erro = limpar_texto(retorno_sances.get("erro", ""))

        if sucesso and hasattr(ag, "sances_data_envio"):
            ag.sances_data_envio = agora_time

        if hasattr(ag, "sances_tentativas"):
            ag.sances_tentativas = int(getattr(ag, "sances_tentativas", 0) or 0) + 1

        if hasattr(ag, "sances_ultima_tentativa"):
            ag.sances_ultima_tentativa = agora_time

        if hasattr(ag, "sances_ultimo_retorno"):
            ag.sances_ultimo_retorno = json.dumps(
                retorno_sances,
                ensure_ascii=False,
                default=str,
            )

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


def enviar_agendamento_salvo_para_sances(protocolo):
    protocolo = limpar_texto(protocolo).upper()

    if not protocolo:
        return {
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "protocolo_sances": "",
            "erro": "Protocolo vazio para envio Sances",
        }

    ag = buscar_agendamento_por_protocolo(protocolo)

    if not ag:
        return {
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "protocolo_sances": "",
            "erro": "Agendamento não encontrado para envio Sances",
        }

    dados = montar_dados_agendamento_para_reenvio(ag)

    log_info("[SANCES] Envio operacional iniciado:", protocolo)
    retorno = enviar_agendamento_para_sances(dados)

    if not isinstance(retorno, dict):
        retorno = {
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "protocolo_sances": "",
            "erro": "Retorno inválido da integração Sances",
        }

    retorno["status"] = limpar_texto(
        retorno.get("status", SANCES_STATUS_ERRO)
    ).upper() or SANCES_STATUS_ERRO

    atualizar_status_sances_agendamento(protocolo, retorno)
    log_info("[SANCES] Envio operacional concluído:", protocolo, retorno)
    return retorno


def mensagem_confirmacao_sances(retorno_sances):
    retorno_sances = retorno_sances or {}
    status = limpar_texto(retorno_sances.get("status", "")).upper()

    if status == SANCES_STATUS_ENVIADO:
        return "Seu agendamento foi registrado e enviado para validação no sistema Sances."

    if status == SANCES_STATUS_NAO_CONFIGURADO:
        return (
            "Seu agendamento foi registrado em nossa agenda interna e será validado "
            "no sistema da concessionária."
        )

    if status == SANCES_STATUS_PENDENTE:
        return (
            "Seu agendamento foi registrado em nossa agenda interna e ficou pendente "
            "de validação no sistema da concessionária."
        )

    return (
        "Seu agendamento foi registrado em nossa agenda interna e será validado "
        "no sistema da concessionária."
    )


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
                "pergunta_ia": limpar_texto(pergunta),
                "resposta_ia": limpar_texto(resposta),
                "assunto_ia": limpar_texto(categoria),
                "fonte_ia": "manual_ou_base",
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

    return (
        "Posso continuar te ajudando por aqui 👇\n\n"
        "1️⃣ Fazer outra dúvida\n"
        "2️⃣ Voltar ao menu principal\n"
        "3️⃣ Falar com atendimento humano\n\n"
        "Digite apenas o número da opção desejada."
    )


def botoes_duvida_retorno_fluxo(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return []

    iniciar_cliente(telefone)

    return [
        {"id": "DUVIDA_OUTRA", "label": "Outra dúvida"},
        {"id": "MENU", "label": "Menu principal"},
        {"id": "MENU_HUMANO", "label": "Atendimento humano"},
    ]


def enviar_duvida_retorno_fluxo(telefone):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    clientes[telefone]["etapa"] = "duvida_pos_resposta"
    clientes[telefone]["ultima_interacao"] = agora()

    mensagem = mensagem_duvida_retorno_fluxo(telefone)

    return enviar_mensagem(
        telefone,
        mensagem
    )


def etapa_revisao_permite_ir_para_duvidas(etapa):
    etapa = limpar_texto(etapa)

    etapas_bloqueadas = {
        "revisao_confirmacao",
    }

    return etapa not in etapas_bloqueadas


def encaminhar_para_menu_duvidas(telefone, etapa_atual=""):
    try:
        telefone = limpar_telefone(telefone)

        if not telefone:
            return False

        iniciar_cliente(telefone)

        etapa_atual = limpar_texto(etapa_atual)

        if etapa_atual in [
            "duvidas_revisao",
            "duvidas_garantia",
            "duvida_manual",
            "duvida_pos_resposta",
        ]:
            return False

        if etapa_atual.startswith("revisao") and not etapa_revisao_permite_ir_para_duvidas(etapa_atual):
            return False

        clientes[telefone]["etapa_retorno_duvida"] = etapa_atual
        clientes[telefone]["etapa"] = "duvidas_menu"
        clientes[telefone]["intencao_ia"] = "duvidas"
        clientes[telefone]["ultima_interacao"] = agora()

        enviar_mensagem(
            telefone,
            "Sem problema 👍 Vou te direcionar para a central de dúvidas "
            "e depois podemos voltar para o seu atendimento."
        )

        try:
            return enviar_menu_duvidas(telefone)
        except Exception:
            return enviar_mensagem(
                telefone,
                menu_duvidas()
            )

    except Exception as e:
        log_erro("Erro ao encaminhar para menu de dúvidas:", repr(e))
        return False


def data_corresponde_ao_dia_escolhido(data_digitada, dia_escolhido):
    return data_bate_com_dia_semana(data_digitada, dia_escolhido)
# ==========================================
# WORKER
# ==========================================
ultima_recuperacao_ia = ""


def dados_json_rpa(dados):
    try:
        if isinstance(dados, str):
            return dados

        return json.dumps(dados or {}, ensure_ascii=False, default=str)

    except Exception:
        return "{}"


def carregar_json_rpa(valor):
    try:
        if isinstance(valor, dict):
            return valor

        return json.loads(valor or "{}")

    except Exception:
        return {}


def identificar_tarefa_operacional(texto, contexto=None):
    contexto = contexto or {}
    texto_norm = normalizar_texto(texto or "")

    if not texto_norm:
        return ""

    if "sumiu" in texto_norm or "parado" in texto_norm or "sem resposta" in texto_norm:
        return "followup_revisao"

    if "catalogo" in texto_norm or "catálogo" in texto_norm:
        return "envio_catalogo"

    if "atacado" in texto_norm or "lojista" in texto_norm:
        return "disparo_atacado"

    if "os" in texto_norm or "ordem de servico" in texto_norm or "ordem de serviço" in texto_norm or "sances" in texto_norm:
        return "consulta_sances"

    if "garantia" in texto_norm and any(p in texto_norm for p in ["status", "acompanhar", "protocolo", "consulta"]):
        return "consulta_sances"

    if "garantia" in texto_norm and any(p in texto_norm for p in ["problema", "analise", "análise", "defeito"]):
        return "consulta_sances"

    if "disponivel" in texto_norm or "disponível" in texto_norm or "tem peca" in texto_norm or "tem peça" in texto_norm:
        return "envio_pecas"

    if "orcamento" in texto_norm or "orçamento" in texto_norm or "cotacao" in texto_norm or "cotação" in texto_norm:
        if "atacado" in texto_norm or "lojista" in texto_norm:
            return "disparo_atacado"
        return "cobranca_orcamento"

    if "status" in texto_norm and "agend" in texto_norm:
        return "consulta_sances"

    if "pos venda" in texto_norm or "pós venda" in texto_norm or "pos-venda" in texto_norm:
        return "recuperacao_cliente"

    if normalizar_texto(contexto.get("temperatura_lead", "")) == "quente":
        return "recuperacao_cliente"

    if bool(contexto.get("oportunidade_comercial", False)):
        return "recuperacao_cliente"

    return ""


def dados_minimos_rpa(tipo_tarefa, dados):
    dados = dados or {}
    telefone = limpar_telefone(dados.get("telefone", ""))

    if not telefone:
        return False, "telefone obrigatório"

    if tipo_tarefa in [
        "registrar_solicitacao_orcamento",
        "consultar_disponibilidade_peca",
        "cotacao_atacado",
        "cobranca_orcamento",
        "envio_pecas",
        "envio_catalogo",
        "disparo_atacado",
    ]:
        itens = limpar_texto(
            dados.get("itens")
            or dados.get("produto")
            or dados.get("produto_interesse")
            or dados.get("mensagem")
            or ""
        )

        if not itens:
            return False, "produto/itens obrigatórios"

    if tipo_tarefa in ["consultar_status_agendamento", "confirmacao_revisao", "followup_revisao", "lembrete_agendamento"]:
        identificador = limpar_texto(
            dados.get("protocolo")
            or dados.get("cpf")
            or dados.get("data_agendada")
            or dados.get("mensagem")
            or ""
        )

        if not identificador:
            return False, "protocolo, cpf ou dados do agendamento obrigatórios"

    if tipo_tarefa in ["consultar_garantia", "analise_garantia"]:
        identificador = limpar_texto(
            dados.get("protocolo")
            or dados.get("cpf")
            or dados.get("descricao")
            or dados.get("mensagem")
            or ""
        )

        if not identificador:
            return False, "protocolo, cpf ou descrição obrigatórios"

    if tipo_tarefa in ["consultar_os", "consulta_sances"]:
        identificador = limpar_texto(
            dados.get("os")
            or dados.get("protocolo")
            or dados.get("cpf")
            or dados.get("mensagem")
            or ""
        )

        if not identificador:
            return False, "OS, protocolo ou cpf obrigatórios"

    return True, ""


def criar_tarefa_rpa(telefone, tipo_tarefa, dados=None, origem="BOT", prioridade=5):
    telefone = limpar_telefone(telefone)
    tipo_tarefa = limpar_texto(tipo_tarefa)
    dados = dados or {}

    if telefone:
        dados.setdefault("telefone", telefone)

    db = SessionLocal()

    try:
        if not tipo_tarefa or tipo_tarefa not in RPA_TIPOS_PREPARADOS:
            log_erro("[RPA] Tipo de tarefa não preparado:", tipo_tarefa)
            return None

        valido, erro = dados_minimos_rpa(tipo_tarefa, dados)
        status = RPA_PENDENTE if valido else RPA_AGUARDANDO_HUMANO

        existente = (
            db.query(RPAFila)
            .filter(RPAFila.telefone == telefone)
            .filter(RPAFila.tipo_rpa == tipo_tarefa)
            .filter(RPAFila.status.in_([
                RPA_PENDENTE,
                RPA_EM_EXECUCAO,
                RPA_AGUARDANDO_HUMANO,
            ]))
            .order_by(RPAFila.id.desc())
            .first()
        )

        if existente:
            log_info("[RPA] Tarefa já existe:", existente.id, tipo_tarefa, telefone)
            return existente.id

        tarefa = RPAFila(
            telefone=telefone,
            cliente=limpar_texto(dados.get("nome") or dados.get("cliente") or ""),
            tipo_rpa=tipo_tarefa,
            payload_json=dados_json_rpa(dados),
            status=status,
            tentativa=0,
            erro=erro,
            origem=limpar_texto(origem or "BOT") or "BOT",
            prioridade=int(prioridade or 5),
        )

        db.add(tarefa)
        db.commit()
        db.refresh(tarefa)

        log_info(
            "[RPA] Tarefa criada:",
            tarefa.id,
            tipo_tarefa,
            status,
            telefone,
        )

        if status == RPA_AGUARDANDO_HUMANO and telefone:
            try:
                enviar_mensagem(telefone, mensagem_fallback_rpa())
            except Exception as e:
                log_erro("[RPA] Falha ao enviar fallback humano:", repr(e))

        return tarefa.id

    except Exception as e:
        db.rollback()
        log_erro("[RPA] Erro ao criar tarefa:", repr(e))
        return None

    finally:
        db.close()


def criar_tarefa_rpa_de_atendimento(telefone, dados, texto=""):
    dados = dados or {}

    contexto = {
        "temperatura_lead": dados.get("temperatura_lead", ""),
        "oportunidade_comercial": bool(dados.get("oportunidade_comercial", False)),
    }

    tipo_tarefa = identificar_tarefa_operacional(
        texto
        or dados.get("ultima_mensagem_cliente", "")
        or dados.get("observacao", "")
        or dados.get("itens", "")
        or dados.get("produto_interesse", ""),
        contexto,
    )

    if not tipo_tarefa:
        return None

    payload = {
        "telefone": telefone,
        "nome": dados.get("nome", ""),
        "modelo": dados.get("modelo", ""),
        "cpf": dados.get("cpf", ""),
        "protocolo": dados.get("protocolo", ""),
        "produto_interesse": dados.get("produto_interesse", ""),
        "itens": dados.get("itens", ""),
        "mensagem": texto or dados.get("ultima_mensagem_cliente", ""),
        "setor": dados.get("setor", ""),
        "status_comercial": dados.get("status_comercial", ""),
    }

    return criar_tarefa_rpa(
        telefone=telefone,
        tipo_tarefa=tipo_tarefa,
        dados=payload,
        origem="IA_COMERCIAL",
        prioridade=3 if contexto["oportunidade_comercial"] else 5,
    )


def criar_rpa_ia(telefone, tipo_rpa, payload=None, origem="IA", prioridade=5):
    payload = payload or {}
    payload.setdefault("origem_ia", origem)

    return criar_tarefa_rpa(
        telefone=telefone,
        tipo_tarefa=tipo_rpa,
        dados=payload,
        origem=origem,
        prioridade=prioridade,
    )


def executar_tarefa_rpa_mock(tipo_tarefa, dados):
    valido, erro = dados_minimos_rpa(tipo_tarefa, dados)

    if not valido:
        return {
            "ok": False,
            "status": RPA_AGUARDANDO_HUMANO,
            "erro": erro,
            "resultado": {},
        }

    if tipo_tarefa in [
        "consultar_status_agendamento",
        "consultar_os",
        "consultar_garantia",
        "consultar_disponibilidade_peca",
    ]:
        return {
            "ok": False,
            "status": RPA_AGUARDANDO_HUMANO,
            "erro": "Integração externa ainda não configurada. Necessário consultor.",
            "resultado": {
                "acao_segura": "encaminhar_consultor",
                "mensagem": "Sem retorno real de sistema externo.",
            },
        }

    return {
        "ok": True,
        "status": RPA_CONCLUIDO,
        "erro": "",
        "resultado": {
            "acao_segura": "tarefa_registrada",
            "observacao": "Tarefa registrada no CRM para continuidade operacional.",
        },
    }


def executar_tarefa_rpa_inteligente(tipo_rpa, dados):
    valido, erro = dados_minimos_rpa(tipo_rpa, dados)

    if not valido:
        return {
            "ok": False,
            "status": RPA_CANCELADO,
            "erro": erro,
            "resultado": {"acao": "aguardar_dados"},
        }

    telefone = limpar_telefone(dados.get("telefone", ""))
    mensagem = ""
    resultado = {"tipo_rpa": tipo_rpa}

    if tipo_rpa == "followup_revisao":
        mensagem = "Olá! Passando para saber se você ainda deseja ajuda para concluir o agendamento da revisão."

    elif tipo_rpa == "cobranca_orcamento":
        mensagem = "Olá! Conseguiu avaliar o orçamento? Posso te ajudar com alguma dúvida ou encaminhar para um consultor."

    elif tipo_rpa == "envio_catalogo":
        mensagem = "Olá! Separei o atendimento para envio de catálogo. Um consultor pode te mandar as opções mais adequadas."

    elif tipo_rpa == "recuperacao_cliente":
        mensagem = "Olá! Vi que seu atendimento ficou parado e estou por aqui para continuar te ajudando."

    elif tipo_rpa == "lembrete_agendamento":
        mensagem = "Olá! Passando para lembrar do seu agendamento e confirmar se está tudo certo."

    elif tipo_rpa == "envio_pecas":
        termo = limpar_texto(dados.get("itens") or dados.get("produto_interesse") or dados.get("mensagem") or "")
        estoque = consultar_estoque_sances(termo)
        resultado["estoque"] = estoque
        mensagem = "Recebi sua solicitação de peça e registrei a consulta para conferência."

    elif tipo_rpa == "consulta_sances":
        resultado["consulta"] = "consulta_sances_registrada"
        mensagem = "Sua consulta ao sistema foi registrada para continuidade operacional."

    elif tipo_rpa == "disparo_atacado":
        mensagem = "Olá! Registrei seu interesse para atendimento de atacado e vamos dar sequência."

    else:
        resultado["acao"] = "registrada"

    if telefone and mensagem:
        retorno_zapi = enviar_mensagem(telefone, mensagem)
        resultado["mensagem_enviada"] = bool(retorno_zapi)
        resultado["retorno_zapi"] = retorno_zapi

        if not retorno_zapi:
            return {
                "ok": False,
                "status": RPA_ERRO,
                "erro": "Falha ao enviar mensagem automática.",
                "resultado": resultado,
            }

    return {
        "ok": True,
        "status": RPA_CONCLUIDO,
        "erro": "",
        "resultado": resultado,
    }


def processar_fila_rpa():
    db = SessionLocal()

    try:
        tarefas = (
            db.query(RPAFila)
            .filter(RPAFila.status == RPA_PENDENTE)
            .order_by(RPAFila.prioridade.asc(), RPAFila.id.asc())
            .limit(max(1, RPA_LOTE_MAX))
            .all()
        )

        for tarefa in tarefas:
            try:
                if int(getattr(tarefa, "tentativa", 0) or 0) >= RPA_RETRY_MAX:
                    tarefa.status = RPA_CANCELADO
                    tarefa.erro = "Limite de tentativas atingido."
                    tarefa.executado_em = agora_datetime()
                    db.commit()
                    continue

                tarefa.status = RPA_EM_EXECUCAO
                tarefa.tentativa = int(getattr(tarefa, "tentativa", 0) or 0) + 1
                tarefa.executado_em = agora_datetime()
                db.commit()

                tipo_tarefa = limpar_texto(getattr(tarefa, "tipo_rpa", ""))
                dados = carregar_json_rpa(getattr(tarefa, "payload_json", ""))

                log_info("[RPA] Processando tarefa:", tarefa.id, tipo_tarefa)

                retorno = executar_tarefa_rpa_inteligente(tipo_tarefa, dados)

                tarefa.status = limpar_texto(
                    retorno.get("status", RPA_ERRO)
                ) or RPA_ERRO
                tarefa.erro = limpar_texto(retorno.get("erro", ""))
                tarefa.resposta = dados_json_rpa(retorno.get("resultado", {}))
                tarefa.executado_em = agora_datetime()

                db.commit()

                if tarefa.status == RPA_CANCELADO:
                    telefone = limpar_telefone(getattr(tarefa, "telefone", ""))

                    if telefone:
                        try:
                            enviar_mensagem(telefone, mensagem_fallback_rpa())
                        except Exception as e:
                            log_erro("[RPA] Falha ao enviar fallback humano:", repr(e))

                log_info(
                    "[RPA] Tarefa processada:",
                    tarefa.id,
                    tarefa.status,
                    tarefa.erro,
                )

            except Exception as e:
                db.rollback()
                log_erro("[RPA] Erro ao processar tarefa:", repr(e))

                try:
                    tarefa.status = RPA_ERRO
                    tarefa.erro = limpar_texto(repr(e))
                    tarefa.executado_em = agora_datetime()
                    db.commit()
                except Exception:
                    db.rollback()

    except Exception as e:
        log_erro("[RPA] Erro geral fila:", repr(e))

    finally:
        db.close()


def mensagem_fallback_rpa():
    return "Vou encaminhar sua solicitação para um consultor continuar o atendimento com segurança. 🤝"


def processar_fila_sances():
    db = SessionLocal()

    try:
        agora_time = datetime.now()

        try:
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
        except Exception as e:
            log_erro(
                "Fila Sances ignorada. Verifique se as colunas Sances existem no banco:",
                repr(e),
            )
            return

        for ag in agendamentos:
            try:
                protocolo = limpar_texto(getattr(ag, "protocolo", ""))

                if not protocolo:
                    continue

                status_atual = limpar_texto(
                    getattr(ag, "sances_status", "")
                ).upper()

                if status_atual == SANCES_STATUS_NAO_CONFIGURADO:
                    continue

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
                    log_erro("Dados inválidos para reenvio Sances:", protocolo)
                    continue

                retorno = enviar_agendamento_para_sances(dados)

                if not isinstance(retorno, dict):
                    retorno = {
                        "sucesso": False,
                        "status": SANCES_STATUS_ERRO,
                        "protocolo_sances": "",
                        "erro": "Retorno inválido da integração Sances",
                    }

                atualizado = atualizar_status_sances_agendamento(
                    protocolo,
                    retorno
                )

                if not atualizado:
                    log_erro("Falha ao atualizar status Sances no worker:", protocolo)
                    continue

                log_info(
                    "[SANCES WORKER] Reenvio processado:",
                    protocolo,
                    limpar_texto(retorno.get("status", SANCES_STATUS_ERRO)).upper(),
                    f"Tentativa {tentativas + 1}",
                )

            except Exception as e:
                log_erro("Erro no retry Sances:", repr(e))

    except Exception as e:
        log_erro("Erro geral fila Sances:", repr(e))

    finally:
        db.close()


def worker():
    global ultima_recuperacao_ia

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
            hora_atual = datetime.now().hour
            chave_recuperacao = datetime.now().strftime("%Y-%m-%d")

            if hora_atual == 9 and ultima_recuperacao_ia != chave_recuperacao:
                processar_recuperacao_clientes()
                ultima_recuperacao_ia = chave_recuperacao

        except Exception as e:
            log_erro("Worker erro em processar_recuperacao_clientes:", repr(e))

        try:
            processar_fila_sances()
        except Exception as e:
            log_erro("Worker erro em processar_fila_sances:", repr(e))

        try:
            processar_fila_rpa()
        except Exception as e:
            log_erro("Worker erro em processar_fila_rpa:", repr(e))

        intervalo = env_int("INTERVALO_WORKER", 300)
        time.sleep(max(30, intervalo))


def iniciar_worker():
    global worker_followup_iniciado

    try:
        if worker_followup_iniciado:
            log_info("Worker já estava iniciado.")
            return

        worker_followup_iniciado = True

        thread = threading.Thread(
            target=worker,
            daemon=True,
            name="yamaha_worker"
        )

        thread.start()

        log_info("Worker iniciado com sucesso.")

    except Exception as e:
        worker_followup_iniciado = False
        log_erro("Erro ao iniciar worker:", repr(e))


# ==========================================
# DASHBOARD
# ==========================================
def intervalo_periodo_crm(filtro="hoje"):
    filtro = limpar_texto(filtro or "hoje").lower()
    hoje = agora_datetime().date()

    if filtro == "hoje":
        inicio = datetime.combine(hoje, datetime.min.time())
        fim = datetime.combine(hoje, datetime.max.time())
        return filtro, inicio, fim

    if filtro == "semana":
        inicio = datetime.combine(hoje - timedelta(days=7), datetime.min.time())
        fim = datetime.combine(hoje, datetime.max.time())
        return filtro, inicio, fim

    if filtro == "mes":
        inicio = datetime.combine(hoje.replace(day=1), datetime.min.time())
        fim = datetime.combine(hoje, datetime.max.time())
        return filtro, inicio, fim

    return "total", None, None


def aplicar_periodo_crm(query, modelo, inicio, fim):
    if not inicio or not fim:
        return query

    campo_data = None

    if hasattr(modelo, "data"):
        campo_data = modelo.data
    elif hasattr(modelo, "criado_em"):
        campo_data = modelo.criado_em
    elif hasattr(modelo, "data_criacao"):
        campo_data = modelo.data_criacao

    if campo_data is None:
        return query

    return query.filter(campo_data >= inicio, campo_data <= fim)


def normalizar_periodo_gestor(pergunta, filtro_padrao="hoje"):
    texto = normalizar_texto(pergunta or "")

    if "semana" in texto or "ultimos 7" in texto or "ultimos sete" in texto:
        return "semana"

    if "mes" in texto or "mensal" in texto or "este mes" in texto:
        return "mes"

    if "total" in texto or "geral" in texto or "todos" in texto or "historico" in texto:
        return "total"

    if "hoje" in texto or "dia" in texto:
        return "hoje"

    return filtro_padrao or "hoje"


def texto_ranking_valido(valor):
    valor = limpar_texto(valor)
    normalizado = normalizar_texto(valor)

    if not valor:
        return False

    if normalizado in ["nao informado", "nenhum", "none", "null", "-"]:
        return False

    return True


def adicionar_ranking(contador, valor, peso=1):
    valor = limpar_texto(valor)

    if texto_ranking_valido(valor):
        contador[valor] += peso


def montar_metricas_crm(filtro="hoje"):
    db = SessionLocal()

    try:
        filtro, inicio, fim = intervalo_periodo_crm(filtro)

        query_atendimentos = aplicar_periodo_crm(
            db.query(Atendimento),
            Atendimento,
            inicio,
            fim,
        )

        query_agendamentos = aplicar_periodo_crm(
            db.query(AgendamentoRevisao),
            AgendamentoRevisao,
            inicio,
            fim,
        )

        query_rpa = aplicar_periodo_crm(
            db.query(RPAFila),
            RPAFila,
            inicio,
            fim,
        )

        query_leads_atacado = aplicar_periodo_crm(
            db.query(LeadAtacado),
            LeadAtacado,
            inicio,
            fim,
        )

        atendimentos = query_atendimentos.all()
        agendamentos = query_agendamentos.order_by(
            AgendamentoRevisao.id.desc()
        ).all()
        tarefas_rpa = query_rpa.order_by(RPAFila.id.desc()).all()
        leads_atacado_lista = query_leads_atacado.order_by(LeadAtacado.id.desc()).all()

        def status_atendimento(obj):
            return normalizar_status(getattr(obj, "status", "") or "")

        def status_sances_ag(obj):
            status = limpar_texto(getattr(obj, "sances_status", "")).upper()
            return status or SANCES_STATUS_NAO_CONFIGURADO

        total_atendimentos = len(atendimentos)
        total_agendamentos = len(agendamentos)

        total_revisoes = sum(
            1 for a in atendimentos
            if "revis" in normalizar_texto(getattr(a, "setor", ""))
            or normalizar_texto(getattr(a, "intencao_ia", "")) in [
                "agendar_revisao",
                "valor_revisao",
                "revisao",
            ]
        )

        agendados = sum(
            1 for ag in agendamentos
            if status_atendimento(ag) == normalizar_status(STATUS_AGENDADO)
        )
        confirmados = sum(
            1 for ag in agendamentos
            if status_atendimento(ag) == normalizar_status(STATUS_CONFIRMADO)
        )
        concluidos = sum(
            1 for ag in agendamentos
            if status_atendimento(ag) in [
                normalizar_status("CONCLUIDO"),
                normalizar_status("CONCLUÍDO"),
                normalizar_status(STATUS_FINALIZADO),
            ]
        )
        cancelados = sum(
            1 for ag in agendamentos
            if status_atendimento(ag) == normalizar_status(STATUS_CANCELADO)
        )
        reagendados = sum(
            1 for ag in agendamentos
            if status_atendimento(ag) == normalizar_status(STATUS_REAGENDADO)
        )

        atendimento_humano = sum(
            1 for a in atendimentos
            if bool(getattr(a, "atendimento_humano", False))
        )

        duvidas_ia = sum(
            1 for a in atendimentos
            if (
                "duvida" in normalizar_texto(getattr(a, "setor", ""))
                or normalizar_texto(getattr(a, "intencao_ia", "")) in [
                    "duvidas",
                    "duvida",
                    "duvida_manual",
                ]
            )
        )

        ia_conversando = sum(
            1 for a in atendimentos
            if texto_ranking_valido(getattr(a, "intencao_ia", ""))
            or texto_ranking_valido(getattr(a, "origem_ia", ""))
            or texto_ranking_valido(getattr(a, "ultima_acao_ia", ""))
        )

        leads_atacado = sum(
            1 for a in atendimentos
            if "atacado" in normalizar_texto(getattr(a, "setor", ""))
            or normalizar_texto(getattr(a, "intencao_ia", "")) == "atacado"
        ) or len(leads_atacado_lista)

        parceiros_quentes_atacado = sum(
            1 for lead in leads_atacado_lista
            if normalizar_texto(getattr(lead, "nivel_interesse_atacado", "")) == "parceiro_quente"
            or normalizar_texto(getattr(lead, "nivel_interesse", "")) in ["alto", "quente"]
            or "cotacao" in normalizar_texto(getattr(lead, "status", ""))
        )

        parceiros_mornos_atacado = sum(
            1 for lead in leads_atacado_lista
            if normalizar_texto(getattr(lead, "nivel_interesse_atacado", "")) == "parceiro_morno"
        )

        parceiros_frios_atacado = sum(
            1 for lead in leads_atacado_lista
            if normalizar_texto(getattr(lead, "nivel_interesse_atacado", "")) == "parceiro_frio"
        )

        novos_parceiros_atacado = sum(
            1 for lead in leads_atacado_lista
            if normalizar_texto(getattr(lead, "nivel_interesse_atacado", "")) == "novo_parceiro"
            or "cadastro" in normalizar_texto(getattr(lead, "status", ""))
        )

        cotacoes_atacado_recebidas = sum(
            1 for lead in leads_atacado_lista
            if limpar_texto(getattr(lead, "itens_cotacao", ""))
            or "cotacao" in normalizar_texto(getattr(lead, "status", ""))
        )

        leads_comerciais = sum(
            1 for a in atendimentos
            if normalizar_texto(getattr(a, "intencao_ia", "")) in [
                "pecas",
                "acessorios",
                "atacado",
                "orcamento",
                "valor_revisao",
            ]
            or bool(getattr(a, "oportunidade_comercial", False))
            or texto_ranking_valido(getattr(a, "status_comercial", ""))
        )

        leads_quentes = sum(
            1 for a in atendimentos
            if normalizar_texto(getattr(a, "temperatura_lead", "")) == "quente"
            or normalizar_texto(getattr(a, "nivel_interesse", "")) in ["alto", "quente"]
            or bool(getattr(a, "oportunidade_comercial", False))
        )

        oportunidades_comerciais = sum(
            1 for a in atendimentos
            if bool(getattr(a, "oportunidade_comercial", False))
        )

        pre_orcamentos_criados = sum(
            1 for a in atendimentos
            if normalizar_texto(getattr(a, "status_comercial", "")) == "pre_orcamento"
            or normalizar_status(getattr(a, "status", "")) == "PRE_ORCAMENTO"
            or limpar_texto(getattr(a, "pre_orcamento_json", ""))
        )

        leads_quentes_orcamento = sum(
            1 for a in atendimentos
            if normalizar_texto(getattr(a, "intencao_ia", "")) == "orcamento"
            and (
                normalizar_texto(getattr(a, "temperatura_lead", "")) == "quente"
                or normalizar_texto(getattr(a, "nivel_interesse", "")) in ["alto", "quente"]
            )
        )

        orcamentos_pendentes_consultor = sum(
            1 for a in atendimentos
            if (
                normalizar_texto(getattr(a, "proxima_acao", "")) == "consultor_finalizar_orcamento"
                or normalizar_texto(getattr(a, "status_comercial", "")) == "pre_orcamento"
            )
            and not bool(getattr(a, "concluido", False))
        )

        followups_pendentes_lista = [
            a for a in atendimentos
            if not bool(getattr(a, "atendimento_humano", False))
            and not bool(getattr(a, "concluido", False))
            and not bool(getattr(a, "followup_respondido", False))
        ]

        contador_setores = Counter()
        contador_modelos = Counter()
        contador_produtos = Counter()
        contador_cidades_atacado = Counter()
        contador_produtos_atacado = Counter()

        for at in atendimentos:
            adicionar_ranking(contador_setores, getattr(at, "setor", ""))
            adicionar_ranking(contador_modelos, getattr(at, "modelo", ""))
            adicionar_ranking(contador_produtos, getattr(at, "produto_interesse", ""))

            itens = " ".join([
                limpar_texto(getattr(at, "itens", "")),
                limpar_texto(getattr(at, "venda_adicional", "")),
            ])

            for item in re.split(r",|;|\n|\+", itens):
                item_limpo = limpar_item_adicional(item)

                if item_adicional_valido(item_limpo):
                    contador_produtos[item_limpo] += 1

        primeira = segunda = terceira = quarta = quinta = 0
        contador_itens = Counter()

        for ag in agendamentos:
            rev = limpar_texto(getattr(ag, "revisao", ""))
            rev = rev.replace("ª", "").replace("º", "").replace("°", "")

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

            adicionar_ranking(contador_modelos, getattr(ag, "modelo", ""))

            itens = (
                getattr(ag, "itens", "")
                or getattr(ag, "venda_adicional", "")
                or ""
            )

            for item in re.split(r",|;|\n|\+", str(itens)):
                item_limpo = limpar_item_adicional(item)

                if item_adicional_valido(item_limpo):
                    contador_itens[item_limpo] += 1
                    contador_produtos[item_limpo] += 1

        for lead in leads_atacado_lista:
            adicionar_ranking(contador_cidades_atacado, getattr(lead, "cidade", ""))

            itens_lead = " ".join([
                limpar_texto(getattr(lead, "produtos_interesse", "")),
                limpar_texto(getattr(lead, "itens_cotacao", "")),
                limpar_texto(getattr(lead, "interesse", "")),
            ])

            for item in re.split(r",|;|\n|\+", itens_lead):
                item_limpo = limpar_item_adicional(item)

                if item_adicional_valido(item_limpo):
                    contador_produtos_atacado[item_limpo] += 1
                    contador_produtos[item_limpo] += 1

        taxa_conversao = 0
        taxa_agenda_ativa = 0

        if total_revisoes > 0:
            taxa_conversao = round(
                ((agendados + confirmados + concluidos) / total_revisoes) * 100,
                1,
            )

        if total_agendamentos > 0:
            taxa_agenda_ativa = round(
                ((agendados + confirmados + concluidos) / total_agendamentos) * 100,
                1,
            )

        sances_pendentes = sum(
            1 for ag in agendamentos
            if status_sances_ag(ag) == SANCES_STATUS_PENDENTE
        )
        sances_enviados = sum(
            1 for ag in agendamentos
            if status_sances_ag(ag) == SANCES_STATUS_ENVIADO
        )
        sances_erros = sum(
            1 for ag in agendamentos
            if status_sances_ag(ag) == SANCES_STATUS_ERRO
        )
        sances_nao_configurado = sum(
            1 for ag in agendamentos
            if status_sances_ag(ag) == SANCES_STATUS_NAO_CONFIGURADO
        )

        rpa_pendentes = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_PENDENTE
        )
        rpa_em_execucao = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_EM_EXECUCAO
        )
        rpa_concluidas = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_CONCLUIDO
        )
        rpa_erros = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_ERRO
        )
        rpa_aguardando_humano = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_AGUARDANDO_HUMANO
        )

        return {
            "filtro": filtro,
            "total": total_atendimentos,
            "total_revisoes": total_revisoes,
            "agendados": agendados,
            "confirmados": confirmados,
            "concluidos": concluidos,
            "cancelados": cancelados,
            "reagendados": reagendados,
            "atendimento_humano": atendimento_humano,
            "duvidas_ia": duvidas_ia,
            "ia_conversando": ia_conversando,
            "leads_atacado": leads_atacado,
            "parceiros_quentes_atacado": parceiros_quentes_atacado,
            "parceiros_mornos_atacado": parceiros_mornos_atacado,
            "parceiros_frios_atacado": parceiros_frios_atacado,
            "novos_parceiros_atacado": novos_parceiros_atacado,
            "cotacoes_atacado_recebidas": cotacoes_atacado_recebidas,
            "leads_comerciais": leads_comerciais,
            "leads_quentes": leads_quentes,
            "oportunidades_comerciais": oportunidades_comerciais,
            "pre_orcamentos_criados": pre_orcamentos_criados,
            "leads_quentes_orcamento": leads_quentes_orcamento,
            "orcamentos_pendentes_consultor": orcamentos_pendentes_consultor,
            "followups_pendentes": len(followups_pendentes_lista),
            "followups_pendentes_lista": followups_pendentes_lista[:10],
            "sances_pendentes": sances_pendentes,
            "sances_enviados": sances_enviados,
            "sances_erros": sances_erros,
            "sances_nao_configurado": sances_nao_configurado,
            "rpa_pendentes": rpa_pendentes,
            "rpa_em_execucao": rpa_em_execucao,
            "rpa_concluidas": rpa_concluidas,
            "rpa_erros": rpa_erros,
            "rpa_aguardando_humano": rpa_aguardando_humano,
            "tarefas_rpa": tarefas_rpa[:20],
            "primeira": primeira,
            "segunda": segunda,
            "terceira": terceira,
            "quarta": quarta,
            "quinta": quinta,
            "ranking_itens": contador_itens.most_common(10),
            "ranking_modelos": contador_modelos.most_common(10),
            "ranking_setores": contador_setores.most_common(10),
            "ranking_produtos": contador_produtos.most_common(10),
            "ranking_cidades_atacado": contador_cidades_atacado.most_common(10),
            "ranking_produtos_atacado": contador_produtos_atacado.most_common(10),
            "leads_atacado_lista": leads_atacado_lista[:20],
            "total_itens_vendidos": sum(contador_itens.values()),
            "total_agendamentos_periodo": total_agendamentos,
            "taxa_conversao": taxa_conversao,
            "taxa_agenda_ativa": taxa_agenda_ativa,
            "atendimentos": atendimentos,
            "agendamentos": agendamentos,
        }

    except Exception as e:
        log_erro("Erro ao montar metricas CRM:", repr(e))
        return {
            "filtro": filtro,
            "total": 0,
            "total_revisoes": 0,
            "agendados": 0,
            "confirmados": 0,
            "concluidos": 0,
            "cancelados": 0,
            "reagendados": 0,
            "atendimento_humano": 0,
            "duvidas_ia": 0,
            "ia_conversando": 0,
            "leads_atacado": 0,
            "parceiros_quentes_atacado": 0,
            "parceiros_mornos_atacado": 0,
            "parceiros_frios_atacado": 0,
            "novos_parceiros_atacado": 0,
            "cotacoes_atacado_recebidas": 0,
            "leads_comerciais": 0,
            "leads_quentes": 0,
            "oportunidades_comerciais": 0,
            "pre_orcamentos_criados": 0,
            "leads_quentes_orcamento": 0,
            "orcamentos_pendentes_consultor": 0,
            "followups_pendentes": 0,
            "followups_pendentes_lista": [],
            "sances_pendentes": 0,
            "sances_enviados": 0,
            "sances_erros": 0,
            "sances_nao_configurado": 0,
            "rpa_pendentes": 0,
            "rpa_em_execucao": 0,
            "rpa_concluidas": 0,
            "rpa_erros": 0,
            "rpa_aguardando_humano": 0,
            "tarefas_rpa": [],
            "primeira": 0,
            "segunda": 0,
            "terceira": 0,
            "quarta": 0,
            "quinta": 0,
            "ranking_itens": [],
            "ranking_modelos": [],
            "ranking_setores": [],
            "ranking_produtos": [],
            "ranking_cidades_atacado": [],
            "ranking_produtos_atacado": [],
            "leads_atacado_lista": [],
            "total_itens_vendidos": 0,
            "total_agendamentos_periodo": 0,
            "taxa_conversao": 0,
            "taxa_agenda_ativa": 0,
            "atendimentos": [],
            "agendamentos": [],
        }

    finally:
        db.close()


def responder_gestor_crm(pergunta, filtro_padrao="hoje"):
    pergunta_original = limpar_texto(pergunta)

    if not pergunta_original:
        return ""

    try:
        filtro = normalizar_periodo_gestor(pergunta_original, filtro_padrao)
        log_info("[IA_GESTOR] pergunta:", pergunta_original)

        texto = normalizar_texto(pergunta_original)

        pergunta_os_sances = (
            (
                "ordem de servico" in texto
                or "ordens de servico" in texto
                or re.search(r"(^|\W)os($|\W)", texto)
            )
            and (
                "sances" in texto
                or "aberta" in texto
                or "abertas" in texto
                or "aberto" in texto
                or "em aberto" in texto
            )
        )

        if pergunta_os_sances:
            log_info("[IA_GESTOR] consulta:", "ordens_servico_sances")
            consulta_os = consultar_ordens_servico_sances()

            if not consulta_os.get("configurado", True):
                resposta = "A consulta real ao Sances ainda não está configurada."
                log_info("[IA_GESTOR] resposta:", resposta)
                return resposta

            if not consulta_os.get("sucesso"):
                resposta = consulta_os.get("mensagem") or "Não consegui consultar as ordens de serviço no Sances agora."
                log_info("[IA_GESTOR] resposta:", resposta)
                return resposta

            total_abertas = int(consulta_os.get("total_abertas", 0) or 0)
            linhas = [f"Existem {total_abertas} ordens de serviço em aberto no Sances."]

            for ordem in (consulta_os.get("ordens") or [])[:5]:
                numero = limpar_texto(ordem.get("numero", "")) or "-"
                cliente = limpar_texto(ordem.get("cliente", "")) or "Cliente não informado"
                moto = limpar_texto(ordem.get("moto", "")) or "Moto não informada"
                situacao = limpar_texto(ordem.get("situacao", "")) or "Situação não informada"
                data_entrada = limpar_texto(ordem.get("data_entrada", "")) or "-"
                linhas.append(f"- OS {numero}: {cliente} | {moto} | {data_entrada} | {situacao}")

            resposta = "\n".join(linhas)
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        metricas = montar_metricas_crm(filtro)
        log_info("[IA_GESTOR] consulta:", f"metricas_crm periodo={filtro}")

        periodo_label = {
            "hoje": "hoje",
            "semana": "nos últimos 7 dias",
            "mes": "neste mês",
            "total": "no histórico",
        }.get(filtro, "no período")

        def resposta_numero(label, valor):
            return f"{label} {periodo_label}: {valor}."

        pergunta_estoque_sances = (
            "estoque" in texto
            or "tem peca" in texto
            or "tem peça" in pergunta_original.lower()
            or "referencia" in texto
            or "referência" in pergunta_original.lower()
        )

        if pergunta_estoque_sances:
            termo_estoque = pergunta_original
            termo_estoque = re.sub(r"(?i)\b(consulta|consultar|estoque|tem|peca|peça|referencia|referência|no|na|do|da|sances)\b", " ", termo_estoque)
            termo_estoque = re.sub(r"(?i)\b(o|a|os|as|um|uma|de|para|por|codigo|código)\b", " ", termo_estoque)
            termo_estoque = re.sub(r"[?!.:,;]+", " ", termo_estoque)
            termo_estoque = limpar_texto(re.sub(r"\s+", " ", termo_estoque))

            log_info("[IA_GESTOR] consulta:", f"estoque_sances termo={termo_estoque}")
            consulta_estoque = consultar_estoque_sances(termo_estoque)

            if not consulta_estoque.get("sucesso"):
                resposta = consulta_estoque.get("mensagem") or "Não consegui consultar o estoque no Sances agora."
                log_info("[IA_GESTOR] resposta:", resposta)
                return resposta

            itens = consulta_estoque.get("dados") or []

            if not itens:
                resposta = "Não encontrei esse item no estoque do Sances."
                log_info("[IA_GESTOR] resposta:", resposta)
                return resposta

            linhas = [f"Encontrei {len(itens)} item(ns) no estoque do Sances."]

            for item in itens[:5]:
                codigo = limpar_texto(item.get("codigo", "")) or "-"
                descricao = limpar_texto(item.get("descricao", "")) or "Descrição não informada"
                referencia = limpar_texto(item.get("referencia", "")) or "-"
                estoque = item.get("estoque") if item.get("estoque") is not None else item.get("estoque_disponivel", 0)
                valor = numero_sances(item.get("valor", 0))
                valor_texto = f" | valor {formatar_valor_brl(valor)}" if valor else ""
                linhas.append(f"- {codigo} | {descricao} | ref. {referencia} | estoque {estoque}{valor_texto}")

            resposta = "\n".join(linhas)
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "follow" in texto:
            pendentes = metricas.get("followups_pendentes", 0)
            lista = metricas.get("followups_pendentes_lista", [])

            if not pendentes:
                resposta = f"Não há clientes pendentes de follow-up {periodo_label}."
            else:
                linhas = [
                    f"Encontrei {pendentes} cliente(s) com follow-up pendente {periodo_label}."
                ]

                for at in lista[:5]:
                    nome = limpar_texto(getattr(at, "nome", "")) or "Cliente sem nome"
                    telefone = limpar_texto(getattr(at, "telefone", "")) or "-"
                    setor = limpar_texto(getattr(at, "setor", "")) or "Sem setor"
                    linhas.append(f"- {nome} ({telefone}) - {setor}")

                resposta = "\n".join(linhas)

            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "modelo" in texto and ("mais" in texto or "ranking" in texto or "pediu" in texto):
            ranking = metricas.get("ranking_modelos", [])

            if not ranking:
                resposta = "Não encontrei modelos suficientes no CRM para responder com segurança."
            else:
                modelo, qtd = ranking[0]
                resposta = f"O modelo mais citado {periodo_label} foi {modelo}, com {qtd} ocorrência(s)."

            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "setor" in texto or "procura" in texto:
            ranking = metricas.get("ranking_setores", [])

            if not ranking:
                resposta = "Não encontrei setores suficientes no CRM para responder com segurança."
            else:
                setor, qtd = ranking[0]
                resposta = f"O setor com mais procura {periodo_label} foi {setor}, com {qtd} atendimento(s)."

            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "produto" in texto or "acessorio" in texto or "acessório" in texto or "peca" in texto or "peça" in texto:
            ranking = metricas.get("ranking_produtos", [])

            if not ranking:
                resposta = "Não encontrei produtos suficientes no CRM para responder com segurança."
            else:
                produto, qtd = ranking[0]
                resposta = f"O produto/acessório mais citado {periodo_label} foi {produto}, com {qtd} ocorrência(s)."

            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "humano" in texto or "atendente" in texto or "consultor" in texto:
            resposta = resposta_numero(
                "Clientes encaminhados para atendimento humano",
                metricas.get("atendimento_humano", 0),
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "atacado" in texto or "lojista" in texto:
            resposta = resposta_numero(
                "Leads de atacado registrados",
                metricas.get("leads_atacado", 0),
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "quente" in texto or "lead" in texto or "comercial" in texto:
            resposta = (
                f"Leads comerciais {periodo_label}: {metricas.get('leads_comerciais', 0)}. "
                f"Leads quentes: {metricas.get('leads_quentes', 0)}. "
                f"Oportunidades comerciais: {metricas.get('oportunidades_comerciais', 0)}."
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "conversao" in texto or "conversão" in texto or "taxa" in texto:
            resposta = f"A taxa de conversão em agendamento {periodo_label} está em {metricas.get('taxa_conversao', 0)}%."
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "cancel" in texto:
            resposta = resposta_numero(
                "Revisões canceladas",
                metricas.get("cancelados", 0),
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "reagend" in texto:
            resposta = resposta_numero(
                "Revisões reagendadas",
                metricas.get("reagendados", 0),
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "sances" in texto:
            resposta = (
                f"Status Sances {periodo_label}: "
                f"{metricas.get('sances_enviados', 0)} enviado(s), "
                f"{metricas.get('sances_pendentes', 0)} pendente(s), "
                f"{metricas.get('sances_erros', 0)} com erro e "
                f"{metricas.get('sances_nao_configurado', 0)} não configurado(s)."
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "rpa" in texto or "automacao" in texto or "automação" in texto or "tarefa" in texto:
            resposta = (
                f"Automações {periodo_label}: "
                f"{metricas.get('rpa_pendentes', 0)} pendente(s), "
                f"{metricas.get('rpa_concluidas', 0)} concluída(s), "
                f"{metricas.get('rpa_erros', 0)} com erro e "
                f"{metricas.get('rpa_aguardando_humano', 0)} aguardando humano."
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "revis" in texto or "agenda" in texto:
            resposta = (
                f"Revisões/agendamentos {periodo_label}: "
                f"{metricas.get('total_agendamentos_periodo', 0)} registro(s), "
                f"{metricas.get('agendados', 0)} agendado(s), "
                f"{metricas.get('confirmados', 0)} confirmado(s), "
                f"{metricas.get('concluidos', 0)} finalizado(s)."
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "duvida" in texto or "dúvida" in texto:
            resposta = resposta_numero(
                "Dúvidas respondidas pela IA",
                metricas.get("duvidas_ia", 0),
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        if "atendimento" in texto or "cliente" in texto:
            resposta = resposta_numero(
                "Total de atendimentos",
                metricas.get("total", 0),
            )
            log_info("[IA_GESTOR] resposta:", resposta)
            return resposta

        resposta = (
            f"Resumo CRM {periodo_label}: {metricas.get('total', 0)} atendimento(s), "
            f"{metricas.get('total_agendamentos_periodo', 0)} agendamento(s), "
            f"{metricas.get('atendimento_humano', 0)} atendimento(s) humano(s), "
            f"{metricas.get('leads_quentes', 0)} lead(s) quente(s) e "
            f"{metricas.get('followups_pendentes', 0)} follow-up(s) pendente(s)."
        )
        log_info("[IA_GESTOR] resposta:", resposta)
        return resposta

    except Exception as e:
        log_erro("[IA_GESTOR] erro de consulta:", repr(e))
        return "Não encontrei dados suficientes no CRM para responder com segurança."


@app.route("/api/gestor-crm", methods=["GET", "POST"])
def api_gestor_crm():
    try:
        dados = request.get_json(silent=True) or {}
        pergunta = (
            dados.get("pergunta")
            or request.form.get("pergunta")
            or request.args.get("pergunta")
            or ""
        )
        filtro = request.args.get("filtro") or dados.get("filtro") or "hoje"
        resposta = responder_gestor_crm(pergunta, filtro)

        return jsonify({
            "ok": True,
            "pergunta": pergunta,
            "resposta": resposta,
        }), 200

    except Exception as e:
        log_erro("[IA_GESTOR] erro rota:", repr(e))

        return jsonify({
            "ok": False,
            "resposta": "Não encontrei dados suficientes no CRM para responder com segurança.",
        }), 500


@app.route("/exportar-clientes-sances.xlsx", methods=["GET"])
def exportar_clientes_sances_xlsx():
    try:
        data_inicio = limpar_texto(request.args.get("data_inicio", ""))
        data_fim = limpar_texto(request.args.get("data_fim", ""))
        limit = env_int("SANCES_CLIENTES_LIMIT", 500)
        offset = 0

        try:
            if request.args.get("limit"):
                limit = int(request.args.get("limit"))
            if request.args.get("offset"):
                offset = int(request.args.get("offset"))
        except Exception:
            limit = 500
            offset = 0

        consulta = consultar_clientes_sances_para_planilha(
            data_inicio=data_inicio,
            data_fim=data_fim,
            limit=limit,
            offset=offset,
        )

        if not consulta.get("sucesso"):
            return jsonify({
                "ok": False,
                "mensagem": consulta.get("mensagem", "Falha ao consultar clientes Sances."),
                "erro": consulta.get("erro", ""),
            }), 500

        linhas = consulta.get("linhas", []) or []
        df = pd.DataFrame(
            linhas,
            columns=["codigo_cliente", "data_compra", "nome", "telefone", "chassi", "modelo_moto"],
        )
        df = df.rename(columns={
            "codigo_cliente": "Código cliente",
            "data_compra": "Data de compra",
            "nome": "Nome",
            "telefone": "Telefone",
            "chassi": "Chassi",
            "modelo_moto": "Modelo da moto",
        })

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Clientes Sances")

        buffer.seek(0)

        nome_arquivo = "clientes_sances_por_data_compra.xlsx"

        return send_file(
            buffer,
            as_attachment=True,
            download_name=nome_arquivo,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        log_erro("[SANCES] Erro exportar planilha clientes:", repr(e))
        return jsonify({
            "ok": False,
            "mensagem": "Erro ao gerar planilha de clientes Sances.",
            "erro": repr(e),
        }), 500


@app.route("/relatorio/vendas", methods=["GET"])
def relatorio_vendas_sances():
    data_inicio = "2025-10-01"
    data_fim = "2026-01-01"
    nome_arquivo = "relatorio_vendas_out2025_jan2026.xlsx"

    try:
        pasta_tmp = "/tmp" if os.path.isdir("/tmp") else os.getenv("TEMP", ".")
        caminho = os.path.join(pasta_tmp, nome_arquivo)

        sucesso, resultado = gerar_excel_vendas_sances(
            caminho=caminho,
            data_inicio=data_inicio,
            data_fim=data_fim,
        )

        if not sucesso:
            return jsonify({
                "ok": False,
                "mensagem": resultado.get("mensagem", "Falha ao gerar relatório de vendas."),
                "erro": resultado.get("erro", ""),
            }), 500

        return send_file(
            caminho,
            as_attachment=True,
            download_name=nome_arquivo,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        log_erro("[SANCES] Erro rota relatório vendas:", repr(e))
        return jsonify({
            "ok": False,
            "mensagem": "Erro ao gerar relatório de vendas do Sances.",
            "erro": repr(e),
        }), 500


@app.route("/reprocessar-rpa/<int:tarefa_id>", methods=["POST"])
def reprocessar_rpa(tarefa_id):
    db = SessionLocal()

    try:
        tarefa = (
            db.query(RPAFila)
            .filter(RPAFila.id == tarefa_id)
            .first()
        )

        if not tarefa:
            return jsonify({
                "ok": False,
                "mensagem": "Tarefa RPA não encontrada.",
            }), 404

        status_atual = limpar_texto(getattr(tarefa, "status_rpa", ""))

        if status_atual == RPA_CONCLUIDO:
            return jsonify({
                "ok": False,
                "mensagem": "Tarefa RPA já foi concluída.",
            }), 400

        tarefa.status = RPA_PENDENTE
        tarefa.erro = ""
        tarefa.executado_em = None
        db.commit()

        log_info("[RPA] Reprocessamento solicitado:", tarefa_id)

        return jsonify({
            "ok": True,
            "mensagem": "Tarefa RPA recolocada na fila com segurança.",
        }), 200

    except Exception as e:
        db.rollback()
        log_erro("[RPA] Erro no reprocessamento:", repr(e))

        return jsonify({
            "ok": False,
            "mensagem": "Erro ao reprocessar tarefa RPA.",
        }), 500

    finally:
        db.close()


@app.route("/dashboard.html")
def dashboard_html_redirect():
    return redirect("/dashboard", code=302)


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    db = SessionLocal()

    try:
        if request.method == "POST":
            filtro = limpar_texto(request.form.get("filtro", "hoje")).lower()
            pergunta_gestor_form = limpar_texto(
                request.form.get("pergunta_gestor", "")
            )
        else:
            filtro = limpar_texto(request.args.get("filtro", "hoje")).lower()
            pergunta_gestor_form = limpar_texto(
                request.args.get("pergunta_gestor", "")
            )

        hoje = agora_datetime().date()

        query_atendimentos = db.query(Atendimento)
        query_agendamentos = db.query(AgendamentoRevisao)
        query_rpa = db.query(RPAFila)
        query_leads_atacado = db.query(LeadAtacado)

        if filtro == "hoje":
            inicio = datetime.combine(hoje, datetime.min.time())
            fim = datetime.combine(hoje, datetime.max.time())

        elif filtro == "semana":
            inicio = datetime.combine(
                hoje - timedelta(days=7),
                datetime.min.time(),
            )
            fim = datetime.combine(hoje, datetime.max.time())

        elif filtro == "mes":
            inicio = datetime.combine(
                hoje.replace(day=1),
                datetime.min.time(),
            )
            fim = datetime.combine(hoje, datetime.max.time())

        else:
            inicio = None
            fim = None
            filtro = "total"

        if inicio and fim:
            if hasattr(Atendimento, "data"):
                query_atendimentos = query_atendimentos.filter(
                    Atendimento.data >= inicio,
                    Atendimento.data <= fim,
                )

            if hasattr(AgendamentoRevisao, "criado_em"):
                query_agendamentos = query_agendamentos.filter(
                    AgendamentoRevisao.criado_em >= inicio,
                    AgendamentoRevisao.criado_em <= fim,
                )

            if hasattr(RPAFila, "criado_em"):
                query_rpa = query_rpa.filter(
                    RPAFila.criado_em >= inicio,
                    RPAFila.criado_em <= fim,
                )

            if hasattr(LeadAtacado, "data"):
                query_leads_atacado = query_leads_atacado.filter(
                    LeadAtacado.data >= inicio,
                    LeadAtacado.data <= fim,
                )

        atendimentos = query_atendimentos.all()

        agendamentos_lista = (
            query_agendamentos
            .order_by(AgendamentoRevisao.id.desc())
            .limit(100)
            .all()
        )

        tarefas_rpa = (
            query_rpa
            .order_by(RPAFila.id.desc())
            .limit(50)
            .all()
        )

        leads_atacado_lista = (
            query_leads_atacado
            .order_by(LeadAtacado.id.desc())
            .limit(120)
            .all()
        )

        total = len(atendimentos)

        total_revisoes = sum(
            1 for a in atendimentos
            if "revis" in normalizar_texto(getattr(a, "setor", ""))
        )

        def status_ag(obj):
            return normalizar_status(getattr(obj, "status", "") or "")

        agendados = sum(
            1 for ag in agendamentos_lista
            if status_ag(ag) == normalizar_status(STATUS_AGENDADO)
        )

        confirmados = sum(
            1 for ag in agendamentos_lista
            if status_ag(ag) == normalizar_status(STATUS_CONFIRMADO)
        )

        concluidos = sum(
            1 for ag in agendamentos_lista
            if status_ag(ag) in [
                normalizar_status("CONCLUIDO"),
                normalizar_status("CONCLUÍDO"),
                normalizar_status(STATUS_FINALIZADO),
            ]
        )

        cancelados = sum(
            1 for ag in agendamentos_lista
            if status_ag(ag) == normalizar_status(STATUS_CANCELADO)
        )

        reagendados = sum(
            1 for ag in agendamentos_lista
            if status_ag(ag) == normalizar_status(STATUS_REAGENDADO)
        )

        atendimento_humano = sum(
            1 for a in atendimentos
            if bool(getattr(a, "atendimento_humano", False))
        )

        duvidas_ia = sum(
            1 for a in atendimentos
            if (
                "duvida" in normalizar_texto(getattr(a, "setor", ""))
                or "duvidas" in normalizar_texto(getattr(a, "setor", ""))
                or normalizar_texto(getattr(a, "intencao_ia", "")) in ["duvidas", "duvida"]
            )
        )

        ia_conversando = sum(
            1 for a in atendimentos
            if texto_ranking_valido(getattr(a, "intencao_ia", ""))
            or texto_ranking_valido(getattr(a, "origem_ia", ""))
            or texto_ranking_valido(getattr(a, "ultima_acao_ia", ""))
        )

        leads_atacado = sum(
            1 for a in atendimentos
            if "atacado" in normalizar_texto(getattr(a, "setor", ""))
            or normalizar_texto(getattr(a, "intencao_ia", "")) == "atacado"
        ) or len(leads_atacado_lista)

        parceiros_quentes_atacado = sum(
            1 for lead in leads_atacado_lista
            if normalizar_texto(getattr(lead, "nivel_interesse_atacado", "")) == "parceiro_quente"
            or normalizar_texto(getattr(lead, "nivel_interesse", "")) in ["alto", "quente"]
            or "cotacao" in normalizar_texto(getattr(lead, "status", ""))
        )

        parceiros_mornos_atacado = sum(
            1 for lead in leads_atacado_lista
            if normalizar_texto(getattr(lead, "nivel_interesse_atacado", "")) == "parceiro_morno"
        )

        parceiros_frios_atacado = sum(
            1 for lead in leads_atacado_lista
            if normalizar_texto(getattr(lead, "nivel_interesse_atacado", "")) == "parceiro_frio"
        )

        novos_parceiros_atacado = sum(
            1 for lead in leads_atacado_lista
            if normalizar_texto(getattr(lead, "nivel_interesse_atacado", "")) == "novo_parceiro"
            or "cadastro" in normalizar_texto(getattr(lead, "status", ""))
        )

        cotacoes_atacado_recebidas = sum(
            1 for lead in leads_atacado_lista
            if limpar_texto(getattr(lead, "itens_cotacao", ""))
            or "cotacao" in normalizar_texto(getattr(lead, "status", ""))
        )

        leads_comerciais = sum(
            1 for a in atendimentos
            if normalizar_texto(getattr(a, "intencao_ia", "")) in [
                "pecas",
                "acessorios",
                "atacado",
                "orcamento",
                "valor_revisao",
            ]
            or bool(getattr(a, "oportunidade_comercial", False))
            or texto_ranking_valido(getattr(a, "status_comercial", ""))
        )

        leads_quentes = sum(
            1 for a in atendimentos
            if normalizar_texto(getattr(a, "temperatura_lead", "")) == "quente"
            or normalizar_texto(getattr(a, "nivel_interesse", "")) in ["alto", "quente"]
            or bool(getattr(a, "oportunidade_comercial", False))
        )

        oportunidades_comerciais = sum(
            1 for a in atendimentos
            if bool(getattr(a, "oportunidade_comercial", False))
        )

        pre_orcamentos_criados = sum(
            1 for a in atendimentos
            if normalizar_texto(getattr(a, "status_comercial", "")) == "pre_orcamento"
            or normalizar_status(getattr(a, "status", "")) == "PRE_ORCAMENTO"
            or limpar_texto(getattr(a, "pre_orcamento_json", ""))
        )

        leads_quentes_orcamento = sum(
            1 for a in atendimentos
            if normalizar_texto(getattr(a, "intencao_ia", "")) == "orcamento"
            and (
                normalizar_texto(getattr(a, "temperatura_lead", "")) == "quente"
                or normalizar_texto(getattr(a, "nivel_interesse", "")) in ["alto", "quente"]
            )
        )

        orcamentos_pendentes_consultor = sum(
            1 for a in atendimentos
            if (
                normalizar_texto(getattr(a, "proxima_acao", "")) == "consultor_finalizar_orcamento"
                or normalizar_texto(getattr(a, "status_comercial", "")) == "pre_orcamento"
            )
            and not bool(getattr(a, "concluido", False))
        )

        followups_pendentes_lista = [
            a for a in atendimentos
            if not bool(getattr(a, "atendimento_humano", False))
            and not bool(getattr(a, "concluido", False))
            and not bool(getattr(a, "followup_respondido", False))
        ]

        followups_pendentes = len(followups_pendentes_lista)

        def status_sances_ag(ag):
            status = limpar_texto(getattr(ag, "sances_status", "")).upper()
            return status or SANCES_STATUS_NAO_CONFIGURADO

        sances_pendentes = sum(
            1 for ag in agendamentos_lista
            if status_sances_ag(ag) == SANCES_STATUS_PENDENTE
        )

        sances_enviados = sum(
            1 for ag in agendamentos_lista
            if status_sances_ag(ag) == SANCES_STATUS_ENVIADO
        )

        sances_erros = sum(
            1 for ag in agendamentos_lista
            if status_sances_ag(ag) == SANCES_STATUS_ERRO
        )

        sances_nao_configurado = sum(
            1 for ag in agendamentos_lista
            if status_sances_ag(ag) == SANCES_STATUS_NAO_CONFIGURADO
        )

        rpa_pendentes = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_PENDENTE
        )
        rpa_em_execucao = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_EM_EXECUCAO
        )
        rpa_concluidas = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_CONCLUIDO
        )
        rpa_erros = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_ERRO
        )
        rpa_aguardando_humano = sum(
            1 for tarefa in tarefas_rpa
            if limpar_texto(getattr(tarefa, "status_rpa", "")) == RPA_AGUARDANDO_HUMANO
        )

        primeira = segunda = terceira = quarta = quinta = 0

        for ag in agendamentos_lista:
            rev = limpar_texto(getattr(ag, "revisao", ""))
            rev = rev.replace("ª", "").replace("º", "").replace("°", "")

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
        contador_setores = Counter()
        contador_modelos = Counter()
        contador_produtos = Counter()
        contador_cidades_atacado = Counter()
        contador_produtos_atacado = Counter()

        for at in atendimentos:
            adicionar_ranking(contador_setores, getattr(at, "setor", ""))
            adicionar_ranking(contador_modelos, getattr(at, "modelo", ""))
            adicionar_ranking(contador_produtos, getattr(at, "produto_interesse", ""))

            itens_atendimento = " ".join([
                limpar_texto(getattr(at, "itens", "")),
                limpar_texto(getattr(at, "venda_adicional", "")),
            ])

            for item in re.split(r",|;|\n|\+", itens_atendimento):
                item_limpo = limpar_item_adicional(item)

                if item_adicional_valido(item_limpo):
                    contador_produtos[item_limpo] += 1

        for ag in agendamentos_lista:
            adicionar_ranking(contador_modelos, getattr(ag, "modelo", ""))

            itens = (
                getattr(ag, "itens", "")
                or getattr(ag, "venda_adicional", "")
                or ""
            )

            if not itens:
                continue

            partes = re.split(r",|;|\n|\+", str(itens))

            for item in partes:
                item_limpo = limpar_item_adicional(item)

                if item_adicional_valido(item_limpo):
                    contador_itens[item_limpo] += 1
                    contador_produtos[item_limpo] += 1

        for lead in leads_atacado_lista:
            adicionar_ranking(contador_cidades_atacado, getattr(lead, "cidade", ""))

            itens_lead = " ".join([
                limpar_texto(getattr(lead, "produtos_interesse", "")),
                limpar_texto(getattr(lead, "itens_cotacao", "")),
                limpar_texto(getattr(lead, "interesse", "")),
            ])

            for item in re.split(r",|;|\n|\+", itens_lead):
                item_limpo = limpar_item_adicional(item)

                if item_adicional_valido(item_limpo):
                    contador_produtos_atacado[item_limpo] += 1
                    contador_produtos[item_limpo] += 1

        ranking_itens = contador_itens.most_common(10)
        ranking_modelos = contador_modelos.most_common(10)
        ranking_setores = contador_setores.most_common(10)
        ranking_produtos = contador_produtos.most_common(10)
        ranking_cidades_atacado = contador_cidades_atacado.most_common(10)
        ranking_produtos_atacado = contador_produtos_atacado.most_common(10)
        total_itens_vendidos = sum(contador_itens.values())
        total_agendamentos_periodo = len(agendamentos_lista)

        pergunta_gestor = pergunta_gestor_form
        resposta_gestor = ""

        if pergunta_gestor:
            resposta_gestor = responder_gestor_crm(pergunta_gestor, filtro)

        atendimentos_ia = [
            a for a in sorted(
                atendimentos,
                key=lambda item: getattr(item, "id", 0) or 0,
                reverse=True,
            )
            if texto_ranking_valido(getattr(a, "intencao_ia", ""))
            or texto_ranking_valido(getattr(a, "ultima_mensagem_cliente", ""))
        ][:80]

        taxa_conversao = 0
        taxa_agenda_ativa = 0

        try:
            if total_revisoes > 0:
                taxa_conversao = round(
                    ((agendados + confirmados + concluidos) / total_revisoes) * 100,
                    1,
                )
        except Exception:
            taxa_conversao = 0

        try:
            if total_agendamentos_periodo > 0:
                taxa_agenda_ativa = round(
                    ((agendados + confirmados + concluidos) / total_agendamentos_periodo) * 100,
                    1,
                )
        except Exception:
            taxa_agenda_ativa = 0

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
            rpa_pendentes=rpa_pendentes,
            rpa_em_execucao=rpa_em_execucao,
            rpa_concluidas=rpa_concluidas,
            rpa_erros=rpa_erros,
            rpa_aguardando_humano=rpa_aguardando_humano,
            tarefas_rpa=tarefas_rpa,
            agendados=agendados,
            confirmados=confirmados,
            concluidos=concluidos,
            cancelados=cancelados,
            reagendados=reagendados,
            atendimento_humano=atendimento_humano,
            duvidas_ia=duvidas_ia,
            ia_conversando=ia_conversando,
            leads_atacado=leads_atacado,
            parceiros_quentes_atacado=parceiros_quentes_atacado,
            parceiros_mornos_atacado=parceiros_mornos_atacado,
            parceiros_frios_atacado=parceiros_frios_atacado,
            novos_parceiros_atacado=novos_parceiros_atacado,
            cotacoes_atacado_recebidas=cotacoes_atacado_recebidas,
            leads_comerciais=leads_comerciais,
            leads_quentes=leads_quentes,
            oportunidades_comerciais=oportunidades_comerciais,
            pre_orcamentos_criados=pre_orcamentos_criados,
            leads_quentes_orcamento=leads_quentes_orcamento,
            orcamentos_pendentes_consultor=orcamentos_pendentes_consultor,
            followups_pendentes=followups_pendentes,
            followups_pendentes_lista=followups_pendentes_lista[:10],
            total_itens_vendidos=total_itens_vendidos,
            total_agendamentos_periodo=total_agendamentos_periodo,
            taxa_conversao=taxa_conversao,
            taxa_agenda_ativa=taxa_agenda_ativa,
            primeira=primeira,
            segunda=segunda,
            terceira=terceira,
            quarta=quarta,
            quinta=quinta,
            ranking_itens=ranking_itens,
            ranking_modelos=ranking_modelos,
            ranking_setores=ranking_setores,
            ranking_produtos=ranking_produtos,
            ranking_cidades_atacado=ranking_cidades_atacado,
            ranking_produtos_atacado=ranking_produtos_atacado,
            leads_atacado_lista=leads_atacado_lista,
            agendamentos=agendamentos_lista,
            atendimentos_ia=atendimentos_ia,
            pergunta_gestor=pergunta_gestor,
            resposta_gestor=resposta_gestor,
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

        memorias_por_telefone = {}

        for atendimento in atendimentos:
            telefone_atendimento = limpar_telefone(getattr(atendimento, "telefone", ""))

            try:
                if telefone_atendimento not in memorias_por_telefone:
                    memorias_por_telefone[telefone_atendimento] = buscar_memoria_cliente(
                        telefone_atendimento
                    )

                memoria = memorias_por_telefone.get(telefone_atendimento, {})
            except Exception:
                memoria = {}

            atendimento.memoria_modelo = memoria.get("modelo", "")
            atendimento.memoria_ano = memoria.get("ano", "")
            atendimento.memoria_setor = memoria.get("setor_recente", "")
            atendimento.memoria_status = memoria.get("status_atual", "")
            atendimento.memoria_nivel = memoria.get("nivel_cliente", "")
            atendimento.memoria_interesse = memoria.get("nivel_interesse", "")
            atendimento.memoria_ultima_revisao = memoria.get("ultima_revisao", "")
            atendimento.memoria_data_ultima_revisao = memoria.get("data_ultima_revisao", "")
            atendimento.memoria_pecas = ", ".join(memoria.get("pecas", [])[:3])
            atendimento.memoria_acessorios = ", ".join(memoria.get("acessorios", [])[:3])

        total_clientes_memoria = len({
            limpar_telefone(getattr(atendimento, "telefone", ""))
            for atendimento in atendimentos
            if limpar_telefone(getattr(atendimento, "telefone", ""))
        })

        return render_template(
            "clientes.html",
            atendimentos=atendimentos,
            total_clientes_memoria=total_clientes_memoria,
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

        status_atual = limpar_texto(
            ag.get("sances_status", "")
        ).upper()

        if status_atual == SANCES_STATUS_ENVIADO:
            return jsonify({
                "ok": False,
                "mensagem": "Este agendamento já foi enviado ao Sances.",
            }), 400

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

        status_sances = limpar_texto(
            retorno_sances.get("status", SANCES_STATUS_ERRO)
        ).upper() or SANCES_STATUS_ERRO

        retorno_sances["status"] = status_sances

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
            "status": status_sances,
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
    setor = normalizar_texto(getattr(at, "setor", "") or "")
    etapa = normalizar_texto(getattr(at, "etapa", "") or "")
    status = normalizar_status(getattr(at, "status", "") or "")

    if status == normalizar_status(STATUS_FINALIZADO) and ("revis" in setor or "revis" in etapa):
        return "pos_revisao"

    if status in [
        normalizar_status(STATUS_AGENDADO),
        normalizar_status(STATUS_CONFIRMADO),
        normalizar_status(STATUS_FINALIZADO),
        normalizar_status(STATUS_CANCELADO),
        normalizar_status(STATUS_ATENDIMENTO_HUMANO),
    ]:
        return "ignorar"

    if "revisao_confirmacao" in etapa:
        return "fechamento_revisao"

    if (
        "revisao_horario" in etapa
        or "revisao_data" in etapa
        or "revisao_dia" in etapa
    ):
        return "agenda_revisao"

    if etapa.startswith("revisao") or "revis" in setor:
        return "revisao"

    if "peca" in setor or "pecas" in etapa:
        return "pecas"

    if (
        "acessorio" in setor
        or "acessorios" in etapa
        or etapa in [
            "acessorios_modelo",
            "acessorios_orcamento",
        ]
    ):
        return "acessorios"

    if "garantia" in setor or "garantia" in etapa:
        return "garantia"

    if "atacado" in setor or "logista" in setor or "lojista" in setor:
        return "atacado"

    if "duvida" in etapa or "duvida" in setor:
        return "duvidas"

    return "geral"


def obter_tempos_followup_por_contexto(contexto):
    tempos = {
        "ignorar": 0,
        "fechamento_revisao": 90 * 60,
        "agenda_revisao": 90 * 60,
        "revisao": 90 * 60,
        "pecas": 90 * 60,
        "acessorios": 90 * 60,
        "garantia": 90 * 60,
        "atacado": 90 * 60,
        "duvidas": 90 * 60,
        "pos_revisao": 24 * 60 * 60,
        "geral": 90 * 60,
    }

    return float(tempos.get(contexto, 90 * 60))


def montar_mensagem_followup_inteligente(at):
    contexto = identificar_contexto_followup(at)

    if contexto == "ignorar":
        return ""

    telefone_memoria = limpar_telefone(getattr(at, "telefone", "") or "")
    memoria = buscar_memoria_cliente(telefone_memoria) if telefone_memoria else {}
    nome = limpar_texto(getattr(at, "nome", "") or memoria.get("nome", "")).title()
    modelo = limpar_texto(getattr(at, "modelo", "") or memoria.get("modelo", "")).upper()
    pecas_memoria = memoria.get("pecas", []) or []
    acessorios_memoria = memoria.get("acessorios", []) or []

    saudacao = f"Oi, {nome}! " if nome else "Oi! "

    if contexto == "atacado":
        etapa_atacado = normalizar_texto(getattr(at, "etapa", "") or "")
        status_atacado = normalizar_texto(getattr(at, "status", "") or "")

        if "catalogo" in etapa_atacado or "catalogo" in status_atacado:
            tipo_atacado = "followup_catalogo"
        elif "cotacao" in etapa_atacado or "cotacao" in status_atacado:
            tipo_atacado = "followup_cotacao"
        elif "cadastro" in etapa_atacado or "cadastro" in status_atacado:
            tipo_atacado = "cadastro_parceiro"
        else:
            tipo_atacado = "followup_catalogo"

        mensagem_atacado = ""

        if gerar_mensagem_atacado:
            try:
                mensagem_atacado = limpar_texto(
                    gerar_mensagem_atacado(
                        tipo_atacado,
                        {
                            "nome": nome,
                            "empresa": getattr(at, "empresa", ""),
                            "segmento": getattr(at, "segmento", ""),
                            "itens_cotacao": getattr(at, "itens", "") or getattr(at, "produto_interesse", ""),
                        },
                    )
                )
            except Exception as e:
                log_erro("Erro follow-up atacado IA:", repr(e))

        if not mensagem_atacado:
            mensagem_atacado = (
                f"{saudacao}conseguiu verificar nosso catálogo de atacado?\n\n"
                "Se quiser, pode me enviar a lista de peças ou produtos que deseja cotar "
                "que nossa equipe comercial te ajuda."
            )

        return (
            mensagem_atacado +
            "\n\n1️⃣ Continuar atendimento\n"
            "2️⃣ Falar com consultor\n"
            "3️⃣ Menu principal\n\n"
            "Digite apenas o número da opção desejada."
        )

    if gerar_mensagem_followup:
        try:
            mensagem_ia = gerar_mensagem_followup(
                nivel=int(getattr(at, "followup_nivel", 0) or 1) or 1,
                modelo=modelo,
                etapa=contexto,
                nome=nome,
            )
            mensagem_ia = limpar_texto(mensagem_ia)

            if mensagem_ia:
                return (
                    mensagem_ia +
                    "\n\n1ï¸âƒ£ Continuar atendimento\n"
                    "2ï¸âƒ£ Falar com consultor\n"
                    "3ï¸âƒ£ Menu principal\n\n"
                    "Digite apenas o nÃºmero da opÃ§Ã£o desejada."
                )
        except Exception as e:
            log_erro("Erro mensagem follow-up IA:", repr(e))

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
            (
                f"passando para saber se ainda deseja orçamento de {pecas_memoria[0]}.\n\n"
                if pecas_memoria else
                "vi que você iniciou uma solicitação de peças e não finalizou.\n\n"
            ) +
            "Se quiser, posso continuar seu atendimento agora 🔧"
        ),

        "acessorios": (
            saudacao +
            (
                f"passando para saber se ainda deseja orçamento de {acessorios_memoria[0]}"
                f"{f' para sua *{modelo}*' if modelo else ''}.\n\n"
                if acessorios_memoria else
                "vi que você iniciou uma solicitação de acessórios e não finalizou.\n\n"
            ) +
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

        "pos_revisao": (
            saudacao +
            "passando para saber se ficou tudo certo com sua revisao na Motoshow Yamaha.\n\n"
            "Se precisar de algum ajuste, peca ou orientacao, posso encaminhar para nossa equipe."
        ),

        "geral": (
            saudacao +
            "vi que você começou um atendimento e não finalizou.\n\n"
            "Posso te ajudar a concluir agora?"
        ),
    }

    mensagem = mensagens.get(contexto, mensagens["geral"])

    return (
        mensagem +
        "\n\n1️⃣ Continuar atendimento\n"
        "2️⃣ Falar com consultor\n"
        "3️⃣ Menu principal\n\n"
        "Digite apenas o número da opção desejada."
    )


def horario_comercial_followup():
    agora_local = datetime.now()

    if agora_local.weekday() >= 6:
        return False

    hora_inicio = env_int("FOLLOWUP_HORA_INICIO", 8)
    hora_fim = env_int("FOLLOWUP_HORA_FIM", 18)

    return hora_inicio <= agora_local.hour < hora_fim


def marcar_followup_enviado(at, contexto, mensagem, retorno_zapi):
    agora_dt = agora_datetime()
    nivel_atual = int(getattr(at, "followup_nivel", 0) or 0)
    novo_nivel = max(1, nivel_atual + 1)

    if hasattr(at, "followup_enviado"):
        at.followup_enviado = True

    if hasattr(at, "data_followup"):
        at.data_followup = agora_dt

    if hasattr(at, "followup_nivel"):
        at.followup_nivel = novo_nivel

    if hasattr(at, "followup_1"):
        at.followup_1 = True

    if hasattr(at, "followup_respondido"):
        at.followup_respondido = False

    if hasattr(at, "ultima_acao_ia"):
        at.ultima_acao_ia = f"FOLLOWUP_{contexto}".upper()

    if hasattr(at, "proxima_acao"):
        at.proxima_acao = "AGUARDAR_RESPOSTA_FOLLOWUP"

    if hasattr(at, "nivel_interesse") and not getattr(at, "nivel_interesse", ""):
        at.nivel_interesse = "MEDIO"

    if hasattr(at, "observacoes"):
        observacao_atual = limpar_texto(getattr(at, "observacoes", "") or "")
        registro = f"Follow-up IA enviado ({contexto}). Retorno Z-API: {retorno_zapi}."
        at.observacoes = f"{observacao_atual}\n{registro}".strip()

    telefone = limpar_telefone(getattr(at, "telefone", "") or "")

    if telefone:
        iniciar_cliente(telefone)
        clientes[telefone]["followup_enviado"] = True
        clientes[telefone]["followup_respondido"] = False
        clientes[telefone]["data_followup"] = agora_dt
        clientes[telefone]["followup_nivel"] = novo_nivel
        clientes[telefone]["proxima_acao"] = "AGUARDAR_RESPOSTA_FOLLOWUP"
        clientes[telefone]["nivel_interesse"] = getattr(at, "nivel_interesse", "") or "MEDIO"


def processar_followups_banco():
    if not horario_comercial_followup():
        return False

    db = SessionLocal()

    try:
        agora_dt = agora_datetime()
        vistos = set()
        houve_alteracao = False

        atendimentos = (
            db.query(Atendimento)
            .filter(or_(Atendimento.atendimento_humano == False, Atendimento.atendimento_humano.is_(None)))
            .filter(or_(Atendimento.followup_respondido == False, Atendimento.followup_respondido.is_(None)))
            .filter(or_(Atendimento.followup_enviado == False, Atendimento.followup_enviado.is_(None)))
            .filter(Atendimento.data >= (agora_dt - timedelta(days=30)))
            .order_by(Atendimento.id.desc())
            .limit(120)
            .all()
        )

        for at in atendimentos:
            telefone = limpar_telefone(getattr(at, "telefone", "") or "")

            if not telefone or telefone in vistos:
                continue

            vistos.add(telefone)

            if cliente_em_atendimento_humano(telefone):
                continue

            contexto = identificar_contexto_followup(at)

            if contexto == "ignorar":
                continue

            ultima = (
                getattr(at, "ultima_interacao", None)
                or getattr(at, "data", None)
                or agora_dt
            )

            try:
                tempo_sem_resposta = (agora_dt - ultima).total_seconds()
            except Exception:
                tempo_sem_resposta = 0

            tempo_minimo = obter_tempos_followup_por_contexto(contexto)

            if tempo_sem_resposta < tempo_minimo:
                continue

            mensagem = montar_mensagem_followup_inteligente(at)

            if not mensagem:
                continue

            log_info(
                "FOLLOWUP IA elegivel:",
                {
                    "telefone": telefone,
                    "contexto": contexto,
                    "etapa": getattr(at, "etapa", ""),
                    "tempo_sem_resposta": int(tempo_sem_resposta),
                },
            )

            retorno_zapi = enviar_mensagem(telefone, mensagem)

            log_info(
                "FOLLOWUP IA enviado:",
                {
                    "telefone": telefone,
                    "contexto": contexto,
                    "mensagem": mensagem,
                    "retorno_zapi": retorno_zapi,
                },
            )

            if retorno_zapi:
                marcar_followup_enviado(at, contexto, mensagem, retorno_zapi)
                houve_alteracao = True

        if houve_alteracao:
            db.commit()

        return houve_alteracao

    except Exception as e:
        db.rollback()
        log_erro("Erro processar_followups_banco:", repr(e))
        return False

    finally:
        db.close()


def botoes_followup_inteligente():
    return [
        {"id": "DUVIDA_CONTINUAR", "label": "Continuar atendimento"},
        {"id": "MENU_HUMANO", "label": "Falar consultor"},
        {"id": "MENU", "label": "Menu principal"},
    ]


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

        if not atendimento:
            return False

        if hasattr(atendimento, "followup_1"):
            atendimento.followup_1 = False

        if hasattr(atendimento, "followup_2"):
            atendimento.followup_2 = False

        if hasattr(atendimento, "followup_3"):
            atendimento.followup_3 = False

        if hasattr(atendimento, "ultima_interacao"):
            atendimento.ultima_interacao = datetime.now()

        if hasattr(atendimento, "followup_respondido"):
            atendimento.followup_respondido = True

        if hasattr(atendimento, "followup_recuperado"):
            atendimento.followup_recuperado = True

        db.commit()
        return True

    except Exception as e:
        db.rollback()
        log_erro("Erro reset followup:", repr(e))
        return False

    finally:
        db.close()



# ==========================================
# CONTROLE SEGURO DA IA NO WEBHOOK
# ==========================================
def etapa_permite_ia_livre(etapa):
    etapa = limpar_texto(etapa).lower()

    etapas_bloqueadas = {
        "revisao_modelo",
        "revisao_nome",
        "revisao_cpf",
        "revisao_escolher_veiculo",
        "revisao_placa_chassi",
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

        "duvidas_menu",
        "duvidas",
        "menu_duvidas",
        "duvidas_revisao",
        "duvidas_garantia",
        "duvida_manual",
        "duvida_pos_resposta",
        "duvidas_retorno",

        "consulta_agendamento_cpf",
        "cancelar_agendamento_cpf",
        "reagendar_agendamento_cpf",
        "pos_consulta_agendamento",

        "acessorios_modelo",
        "acessorios_orcamento",

        "pecas",
        "garantia",
        "garantia_menu",
        "garantia_nova_nome",
        "garantia_nova_modelo",
        "garantia_nova_ano",
        "garantia_nova_km",
        "garantia_nova_descricao",
        "garantia_acompanhar_nome",
        "garantia_acompanhar_modelo",
        "garantia_acompanhar_cpf",
        "garantia_acompanhar_descricao",
        "atacado",
        "atacado_cotacao",
        "atacado_cotacao_itens",
        "atacado_cadastro",
        "atacado_empresa",
        "atacado_responsavel",
        "atacado_cidade",
        "atacado_cnpj",
        "atacado_telefone_comercial",
        "atacado_segmento",
        "atacado_produtos_interesse",
        "atacado_cadastro_empresa",
        "atacado_cadastro_responsavel",
        "atacado_cadastro_cidade",
        "atacado_cadastro_cnpj",
        "atacado_cadastro_telefone",
        "atacado_cadastro_segmento",
        "atacado_cadastro_produtos",
        "atacado_catalogo_enviado",
        "atacado_catalogo_erro",

        "atendimento_humano",
    }

    return etapa not in etapas_bloqueadas


def texto_parece_menu_ou_saudacao(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)

    return texto_normalizado in [
        "menu",
        "inicio",
        "iniciar",
        "voltar",
        "voltar menu",
        "voltar ao menu",
        "oi",
        "ola",
        "olá",
        "bom dia",
        "boa tarde",
        "boa noite",
    ]


def interpretar_opcao_menu_rapido(telefone, opcao):
    telefone = limpar_telefone(telefone)
    opcao = limpar_texto(opcao)

    if not telefone or not opcao:
        return False

    iniciar_cliente(telefone)

    opcao_normalizada = normalizar_opcao_menu(opcao) or opcao.upper()
    etapa_atual = limpar_texto(clientes[telefone].get("etapa", "menu")).lower()

    clientes[telefone]["opcao_menu"] = opcao_normalizada
    clientes[telefone]["button_id"] = opcao_normalizada
    clientes[telefone]["ultima_interacao"] = agora()

    if opcao_normalizada in ["MENU", "VOLTAR_MENU", "MENU_PRINCIPAL", "OPCAO_MENU"]:
        encerrar_atendimento_humano(telefone)
        resetar_cliente(telefone)
        enviar_menu(telefone)
        return True

    # ==========================================
    # MENU DE DÚVIDAS
    # ==========================================
    if etapa_atual in ["duvidas_menu", "menu_duvidas"]:
        if opcao_normalizada in ["1", "OPCAO_1", "DUVIDAS_REVISAO", "DUVIDA_REVISOES"]:
            clientes[telefone]["etapa"] = "duvidas_revisao"
            clientes[telefone]["categoria_duvida"] = "revisoes"
            clientes[telefone]["ultima_interacao"] = agora()

            enviar_mensagem(
                telefone,
                "📘 *Dúvidas sobre Revisões*\n\n"
                "Me envie sua dúvida sobre revisão."
            )
            return True

        if opcao_normalizada in ["2", "OPCAO_2", "DUVIDAS_GARANTIA", "DUVIDA_GARANTIA"]:
            clientes[telefone]["etapa"] = "duvidas_garantia"
            clientes[telefone]["categoria_duvida"] = "garantia"
            clientes[telefone]["ultima_interacao"] = agora()

            enviar_mensagem(
                telefone,
                "🛡️ *Dúvidas sobre Garantia*\n\n"
                "Me envie sua dúvida sobre garantia."
            )
            return True

        if opcao_normalizada in ["3", "OPCAO_3", "MENU"]:
            enviar_menu(telefone)
            return True

    # ==========================================
    # RETORNO DE DÚVIDAS
    # ==========================================
    if etapa_atual in ["duvidas_retorno", "duvida_pos_resposta"]:
        if opcao_normalizada in ["1", "OPCAO_1", "DUVIDA_OUTRA", "DUVIDA_CONTINUAR"]:
            clientes[telefone]["etapa"] = "duvidas_menu"
            enviar_menu_duvidas(telefone)
            return True

        if opcao_normalizada in ["2", "OPCAO_2", "MENU"]:
            enviar_menu(telefone)
            return True

        if opcao_normalizada in ["3", "OPCAO_3", "MENU_HUMANO"]:
            ativar_atendimento_humano(telefone)
            return True

    # ==========================================
    # PÓS CONSULTA DE AGENDAMENTO
    # ==========================================
    if etapa_atual == "pos_consulta_agendamento":
        cpf_salvo = limpar_cpf(clientes[telefone].get("cpf", ""))

        if opcao_normalizada in ["1", "OPCAO_1", "REAGENDAR_AGENDAMENTO"]:
            iniciar_reagendamento(telefone, cpf_salvo)
            return True

        if opcao_normalizada in ["2", "OPCAO_2", "CANCELAR_AGENDAMENTO"]:
            responder_cancelamento_agendamento(telefone, cpf_salvo)
            return True

        if opcao_normalizada in ["3", "OPCAO_3", "MENU"]:
            enviar_menu(telefone)
            return True

    # ==========================================
    # MENU PRINCIPAL
    # ==========================================
    if etapa_atual == "menu":
        if opcao_normalizada in ["1", "OPCAO_1", "MENU_REVISAO", "AGENDAR_REVISAO"]:
            iniciar_fluxo_revisao_por_intencao(telefone, {})
            enviar_proxima_etapa_revisao(telefone)
            return True

        if opcao_normalizada in ["2", "OPCAO_2", "MENU_PECAS"]:
            iniciar_fluxo_pecas(telefone)
            return True

        if opcao_normalizada in ["3", "OPCAO_3", "MENU_ACESSORIOS"]:
            iniciar_fluxo_acessorios(telefone)
            return True

        if opcao_normalizada in ["4", "OPCAO_4", "MENU_GARANTIA"]:
            iniciar_fluxo_garantia(telefone)
            return True

        if opcao_normalizada in ["5", "OPCAO_5", "MENU_ATACADO"]:
            iniciar_fluxo_atacado(telefone)
            return True

        if opcao_normalizada in ["6", "OPCAO_6", "MENU_DUVIDAS"]:
            enviar_menu_duvidas(telefone)
            return True

        if opcao_normalizada in ["7", "OPCAO_7", "MENU_HUMANO"]:
            ativar_atendimento_humano(telefone)
            return True

    # ==========================================
    # OPÇÕES GERAIS FORA DO MENU
    # ==========================================
    if opcao_normalizada in ["MENU_REVISAO", "AGENDAR_REVISAO"]:
        iniciar_fluxo_revisao_por_intencao(telefone, {})
        enviar_proxima_etapa_revisao(telefone)
        return True

    if opcao_normalizada == "MENU_PECAS":
        iniciar_fluxo_pecas(telefone)
        return True

    if opcao_normalizada == "MENU_ACESSORIOS":
        iniciar_fluxo_acessorios(telefone)
        return True

    if opcao_normalizada == "MENU_GARANTIA":
        iniciar_fluxo_garantia(telefone)
        return True

    if opcao_normalizada in ["MENU_ATACADO", "ATACADO_TABELA"]:
        iniciar_fluxo_atacado(telefone)
        return True

    if opcao_normalizada == "MENU_DUVIDAS":
        enviar_menu_duvidas(telefone)
        return True

    if opcao_normalizada in ["MENU_HUMANO", "FALAR_CONSULTOR"]:
        ativar_atendimento_humano(telefone)
        return True

    if opcao_normalizada == "CONFIRMAR_PRESENCA":
        salvar_evento_atendimento(
            telefone=telefone,
            setor="Confirmação",
            status=STATUS_CONFIRMADO,
            etapa="presenca_confirmada",
            dados=clientes.get(telefone, {}),
            atendimento_humano=False,
            concluido=False,
        )

        enviar_mensagem(
            telefone,
            "✅ Presença confirmada. Obrigado!\n\n"
            "Esperamos você no horário agendado. Não esqueça de trazer o manual da moto."
        )
        return True

    if opcao_normalizada == "REAGENDAR_AGENDAMENTO":
        clientes[telefone]["etapa"] = "reagendar_agendamento_cpf"
        enviar_mensagem(
            telefone,
            "📄 Para reagendar, informe seu *CPF com 11 números*."
        )
        return True

    if opcao_normalizada == "CANCELAR_AGENDAMENTO":
        clientes[telefone]["etapa"] = "cancelar_agendamento_cpf"
        enviar_mensagem(
            telefone,
            "📄 Para cancelar seu agendamento, informe seu *CPF com 11 números*."
        )
        return True

    if opcao_normalizada == "CONSULTAR_AGENDAMENTO":
        clientes[telefone]["etapa"] = "consulta_agendamento_cpf"
        enviar_mensagem(
            telefone,
            "📄 Para consultar seu agendamento, informe seu *CPF com 11 números*."
        )
        return True

    return False


# ==========================================
# COMPATIBILIDADE COM NOME ANTIGO
# ==========================================
def interpretar_botao_menu_rapido(telefone, button_id):
    return interpretar_opcao_menu_rapido(telefone, button_id)


def tentar_interpretar_ia_no_menu(telefone, texto):
    telefone = limpar_telefone(telefone)
    texto = limpar_texto(texto)

    if not telefone:
        return False

    iniciar_cliente(telefone)

    etapa_atual = limpar_texto(clientes[telefone].get("etapa", "menu")).lower()

    opcao_menu = normalizar_opcao_menu(texto)

    if opcao_menu:
        clientes[telefone]["opcao_menu"] = opcao_menu
        clientes[telefone]["button_id"] = opcao_menu

        if interpretar_opcao_menu_rapido(telefone, opcao_menu):
            return True

    if not etapa_permite_ia_livre(etapa_atual):
        return False

    resposta_ia = obter_dados_extraidos_ia(texto)

    if not isinstance(resposta_ia, dict):
        resposta_ia = {}

    intencao = limpar_texto(resposta_ia.get("intencao", "")).lower()
    resposta_texto = limpar_texto(resposta_ia.get("resposta", ""))

    try:
        confianca = float(resposta_ia.get("confianca", 0.0) or 0.0)
    except Exception:
        confianca = 0.0

    dados_extraidos = resposta_ia.get("dados_extraidos", {}) or {}

    if not isinstance(dados_extraidos, dict):
        dados_extraidos = {}

    clientes[telefone]["intencao_ia"] = intencao
    clientes[telefone]["ultima_interacao"] = agora()

    log_info(
        "IA WEBHOOK:",
        {
            "telefone": telefone,
            "intencao": intencao,
            "confianca": confianca,
            "etapa_atual": etapa_atual,
            "dados_extraidos": dados_extraidos,
        },
    )

    intencoes_validas = [
        "agendar_revisao",
        "valor_revisao",
        "pecas",
        "acessorios",
        "garantia",
        "atacado",
        "humano",
        "atendimento_humano",
        "duvidas",
        "duvida",
        "dúvidas",
        "dúvida",
        "consultar_agendamento",
        "orcamento",
        "valor_peca",
        "consulta_estoque",
        "acompanhar_garantia",
        "cancelar_agendamento",
        "cancelar_revisao",
        "reagendar_agendamento",
        "reagendar_revisao",
        "nao_interessado",
    ]

    if confianca < 0.55 and intencao not in intencoes_validas:
        return False

    if intencao == "agendar_revisao":
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "agendar_revisao", "etapa_atual": etapa_atual})
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos)
        iniciar_fluxo_revisao_por_intencao(telefone, dados_extraidos)

        resumo = montar_resumo_dados_ia_revisao(telefone)

        if resumo:
            enviar_mensagem(telefone, resumo)

        enviar_proxima_etapa_revisao(telefone)
        return True

    if intencao == "valor_revisao":
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "valor_revisao", "etapa_atual": etapa_atual})
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos)

        resposta_duvida = ""

        try:
            resposta_duvida = responder_duvida_por_tabela(
                categoria="revisoes",
                pergunta_cliente=texto,
                modelo=dados_extraidos.get("modelo", ""),
                revisao=dados_extraidos.get("revisao", ""),
            )
        except Exception as e:
            log_erro("Erro ao responder valor revisão:", repr(e))

        if resposta_duvida:
            enviar_mensagem(telefone, resposta_duvida)

        enviar_mensagem(
            telefone,
            "Deseja agendar sua revisão agora?\n\n"
            "1️⃣ Agendar revisão\n"
            "2️⃣ Menu principal\n"
            "3️⃣ Atendimento humano\n\n"
            "Digite apenas o número da opção desejada."
        )

        clientes[telefone]["etapa"] = "menu"
        return True

    if intencao in ["pecas", "consulta_estoque"]:
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "pecas", "etapa_atual": etapa_atual})
        iniciar_fluxo_pecas(telefone, texto)
        return True

    if intencao in ["orcamento", "valor_peca"]:
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "orcamento_pecas", "etapa_atual": etapa_atual})
        montar_pre_orcamento(texto, telefone)
        return True

    if intencao == "acessorios":
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "acessorios", "etapa_atual": etapa_atual})
        modelo_ia = limpar_texto(dados_extraidos.get("modelo", ""))

        if modelo_ia:
            iniciar_fluxo_acessorios(telefone, modelo_ia)
        else:
            iniciar_fluxo_acessorios(telefone)

        return True

    if intencao == "garantia":
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "garantia", "etapa_atual": etapa_atual})
        iniciar_fluxo_garantia(telefone)
        return True

    if intencao == "acompanhar_garantia":
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "acompanhar_garantia", "etapa_atual": etapa_atual})
        iniciar_cliente(telefone)
        clientes[telefone]["intencao_ia"] = "acompanhar_garantia"
        clientes[telefone]["etapa"] = "garantia_consulta_cpf"
        clientes[telefone]["atendimento_humano"] = False
        clientes[telefone]["nome"] = ""
        clientes[telefone]["modelo"] = ""
        clientes[telefone]["cpf"] = ""
        clientes[telefone]["observacao"] = ""
        clientes[telefone]["garantia_os_sances"] = []
        clientes[telefone]["ultima_interacao"] = agora()
        enviar_mensagem(
            telefone,
            "Certo. Vou te ajudar a acompanhar sua garantia.\n\n"
            "Informe seu *CPF* com 11 números."
        )
        return True

    if intencao == "atacado":
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "atacado", "etapa_atual": etapa_atual})
        iniciar_fluxo_atacado(telefone)
        return True

    if intencao in ["duvidas", "duvida", "dúvidas", "dúvida"]:
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "duvidas", "etapa_atual": etapa_atual})
        etapa_anterior = clientes[telefone].get("etapa", "")
        clientes[telefone]["ultima_interacao"] = agora()
        clientes[telefone]["intencao_ia"] = "duvidas"

        if limpar_texto(etapa_anterior).lower() in [
            "duvidas_revisao",
            "duvidas_garantia",
            "duvida_manual",
            "duvida_pos_resposta",
        ]:
            return False

        enviado = encaminhar_para_menu_duvidas(telefone, etapa_anterior)

        if not enviado:
            enviar_menu_duvidas(telefone)

        return True

    if intencao == "consultar_agendamento":
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "consultar_agendamento", "etapa_atual": etapa_atual})
        clientes[telefone]["etapa"] = "consulta_agendamento_cpf"

        enviar_mensagem(
            telefone,
            "📄 Para consultar seu agendamento, informe seu *CPF com 11 números*."
        )

        return True

    if intencao in ["cancelar_agendamento", "cancelar_revisao"]:
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "cancelar_revisao", "etapa_atual": etapa_atual})
        clientes[telefone]["etapa"] = "cancelar_agendamento_cpf"

        enviar_mensagem(
            telefone,
            "📄 Para cancelar seu agendamento, informe seu *CPF com 11 números*."
        )

        return True

    if intencao in ["reagendar_agendamento", "reagendar_revisao"]:
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "reagendar_revisao", "etapa_atual": etapa_atual})
        clientes[telefone]["etapa"] = "reagendar_agendamento_cpf"

        enviar_mensagem(
            telefone,
            "📄 Para reagendar, informe seu *CPF com 11 números*."
        )

        return True

    if intencao in ["humano", "atendimento_humano"]:
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "atendimento_humano", "etapa_atual": etapa_atual})
        ativar_atendimento_humano(telefone)
        return True

    if intencao == "nao_interessado":
        log_info("IA FLUXO ESCOLHIDO:", {"telefone": telefone, "fluxo": "nao_interessado", "etapa_atual": etapa_atual})
        clientes[telefone]["status_retorno"] = "NAO_INTERESSADO"
        clientes[telefone]["nivel_interesse"] = "BAIXO"
        clientes[telefone]["ultima_interacao"] = agora()
        enviar_mensagem(telefone, "Tudo bem. Quando precisar, é só chamar.")
        resetar_cliente(telefone)
        return True

    return False

# ==========================================
# FLUXO REVISÃO
# ==========================================
def processar_fluxo_revisao(
    telefone,
    texto,
    message_id=None,
    texto_opcao=None,
    **kwargs
):

    try:
        telefone = limpar_telefone(telefone)
        texto = limpar_texto(texto)
        texto_opcao = limpar_texto(texto_opcao or texto)

        if not telefone:
            return False

        iniciar_cliente(telefone)

        etapa = limpar_texto(clientes[telefone].get("etapa", "")).lower()

        # ==========================================
        # MODELO
        # ==========================================
        if etapa == "revisao_modelo":

            clientes[telefone]["modelo"] = texto.upper()
            clientes[telefone]["etapa"] = "revisao_nome"

            enviar_mensagem(
                telefone,
                "👤 Perfeito!\n\nAgora me informe seu *nome completo*."
            )

            return True

        # ==========================================
        # NOME
        # ==========================================
        elif etapa == "revisao_nome":

            clientes[telefone]["nome"] = texto.title()
            clientes[telefone]["etapa"] = "revisao_cpf"

            enviar_mensagem(
                telefone,
                "📄 Informe seu *CPF*."
            )

            return True

        # ==========================================
        # CPF
        # ==========================================
        elif etapa == "revisao_cpf":

            cpf_limpo = limpar_cpf(texto)

            if len(cpf_limpo) != 11:
                enviar_mensagem(
                    telefone,
                    "📄 Informe um *CPF válido* com 11 números."
                )
                return True

            clientes[telefone]["cpf"] = cpf_limpo

            veiculos, origem_veiculos = buscar_veiculos_revisao(telefone, cpf_limpo)

            if len(veiculos) == 1:
                aplicar_veiculo_sances_no_cliente(telefone, veiculos[0])
                clientes[telefone]["veiculos_sances"] = []
                clientes[telefone]["origem_veiculos_sances"] = origem_veiculos

                enviar_mensagem(
                    telefone,
                    mensagem_veiculo_localizado(veiculos[0])
                )

                enviar_proxima_etapa_revisao(telefone)
                return True

            if len(veiculos) > 1:
                clientes[telefone]["veiculos_sances"] = veiculos[:9]
                clientes[telefone]["origem_veiculos_sances"] = origem_veiculos
                clientes[telefone]["etapa"] = "revisao_escolher_veiculo"

                enviar_mensagem(
                    telefone,
                    montar_opcoes_veiculos_sances(veiculos)
                )
                return True

            clientes[telefone]["veiculos_sances"] = []
            clientes[telefone]["origem_veiculos_sances"] = ""
            clientes[telefone]["etapa"] = "revisao_placa_chassi"

            enviar_mensagem(
                telefone,
                mensagem_por_etapa_revisao(telefone, "revisao_placa_chassi")
            )

            return True

        # ==========================================
        # ESCOLHA DE VEICULO SANCES
        # ==========================================
        elif etapa == "revisao_escolher_veiculo":

            veiculos = clientes[telefone].get("veiculos_sances") or []

            try:
                indice = int(texto_opcao)
            except Exception:
                indice = 0

            if indice < 1 or indice > len(veiculos):
                enviar_mensagem(
                    telefone,
                    montar_opcoes_veiculos_sances(veiculos)
                )
                return True

            aplicar_veiculo_sances_no_cliente(telefone, veiculos[indice - 1])
            clientes[telefone]["veiculos_sances"] = []
            clientes[telefone]["origem_veiculos_sances"] = ""

            enviar_mensagem(
                telefone,
                mensagem_veiculo_localizado(veiculos[indice - 1])
            )

            enviar_proxima_etapa_revisao(telefone)
            return True

        # ==========================================
        # PLACA OU CHASSI
        # ==========================================
        elif etapa == "revisao_placa_chassi":

            identificador = re.sub(r"[^A-Za-z0-9]", "", texto or "").upper()

            if len(identificador) < 7:
                enviar_mensagem(
                    telefone,
                    "Informe uma *placa* ou um *chassi* válido da moto."
                )
                return True

            if len(identificador) >= 12:
                clientes[telefone]["chassi"] = identificador
            else:
                clientes[telefone]["placa"] = identificador

            enviar_proxima_etapa_revisao(telefone)
            return True

        # ==========================================
        # ANO
        # ==========================================
        elif etapa == "revisao_ano":

            clientes[telefone]["ano"] = texto
            clientes[telefone]["etapa"] = "revisao_km"

            enviar_mensagem(
                telefone,
                "📍 Informe a *quilometragem atual* da moto."
            )

            return True

        # ==========================================
        # KM
        # ==========================================
        elif etapa == "revisao_km":

            clientes[telefone]["km_atual"] = texto
            clientes[telefone]["etapa"] = "revisao_revisao"

            enviar_mensagem(
                telefone,
                "🔧 *Qual revisão você deseja agendar?*\n\n"
                "1️⃣ 1ª Revisão\n"
                "2️⃣ 2ª Revisão\n"
                "3️⃣ 3ª Revisão\n"
                "4️⃣ 4ª Revisão\n"
                "5️⃣ 5ª Revisão ou acima\n\n"
                "Digite apenas o número da revisão."
            )

            return True

        # ==========================================
        # REVISÃO
        # ==========================================
        elif etapa == "revisao_revisao":

            revisao = normalizar_revisao_para_fluxo(texto_opcao)

            if not revisao:
                enviar_mensagem(
                    telefone,
                    "🔧 *Qual revisão você deseja agendar?*\n\n"
                    "1️⃣ 1ª Revisão\n"
                    "2️⃣ 2ª Revisão\n"
                    "3️⃣ 3ª Revisão\n"
                    "4️⃣ 4ª Revisão\n"
                    "5️⃣ 5ª Revisão ou acima\n\n"
                    "Digite apenas o número da revisão."
                )
                return True

            clientes[telefone]["revisao"] = revisao
            clientes[telefone]["etapa"] = "revisao_dia"

            enviar_mensagem(
                telefone,
                "📅 *Qual dia deseja agendar?*\n\n"
                "1️⃣ Segunda-feira\n"
                "2️⃣ Terça-feira\n"
                "3️⃣ Quarta-feira\n"
                "4️⃣ Quinta-feira\n"
                "5️⃣ Sexta-feira\n"
                "6️⃣ Sábado\n\n"
                "Digite apenas o número do dia."
            )

            return True

        # ==========================================
        # DIA
        # ==========================================
        elif etapa == "revisao_dia":

            dia_str = None

            if texto_opcao in ["1", "2", "3", "4", "5", "6"]:
                dia_str = texto_opcao
            else:
                dia_str = numero_dia_por_texto(texto)

            if dia_str not in ["1", "2", "3", "4", "5", "6"]:
                enviar_mensagem(
                    telefone,
                    "📅 Informe um dia válido.\n\n"
                    "1️⃣ Segunda\n"
                    "2️⃣ Terça\n"
                    "3️⃣ Quarta\n"
                    "4️⃣ Quinta\n"
                    "5️⃣ Sexta\n"
                    "6️⃣ Sábado"
                )
                return True

            clientes[telefone]["dia"] = dia_str
            clientes[telefone]["etapa"] = "revisao_data"

            enviar_mensagem(
                telefone,
                "📆 Informe a *data desejada*.\n\n"
                "Exemplo:\n25/05/2026"
            )

            return True

        # ==========================================
        # DATA
        # ==========================================
        elif etapa == "revisao_data":

            if not validar_data(texto):
                enviar_mensagem(
                    telefone,
                    "⚠️ Informe uma data válida.\n\n"
                    "Exemplo:\n25/05/2026"
                )
                return True

            clientes[telefone]["data"] = texto
            clientes[telefone]["etapa"] = "revisao_horario"

            horarios = obter_horarios_disponiveis(
                clientes[telefone].get("revisao"),
                clientes[telefone].get("dia")
            )

            if not horarios:
                enviar_mensagem(
                    telefone,
                    "⚠️ Não encontrei horários disponíveis para essa revisão."
                )
                return True

            mensagem = "⏰ *Estes são os horários disponíveis:*\n\n"

            for i, horario in enumerate(horarios, start=1):
                mensagem += f"{i}️⃣ {horario}\n"

            mensagem += "\nMe responda com o *número do horário* que você prefere."

            enviar_mensagem(telefone, mensagem)

            return True

        # ==========================================
        # HORÁRIO
        # ==========================================
        elif etapa == "revisao_horario":

            horarios = obter_horarios_disponiveis(
                clientes[telefone].get("revisao"),
                clientes[telefone].get("dia")
            )

            log_info("HORARIOS DISPONIVEIS:", horarios)
            log_info("TEXTO:", texto)
            log_info("TEXTO_OPCAO:", texto_opcao)

            opcao = texto_opcao or texto

            if not str(opcao).isdigit():

                mensagem = "⏰ *Escolha um horário válido:*\n\n"

                for i, horario in enumerate(horarios, start=1):
                    mensagem += f"{i}️⃣ {horario}\n"

                mensagem += "\nDigite apenas o número do horário."

                enviar_mensagem(telefone, mensagem)

                return True

            indice = int(opcao) - 1

            if indice < 0 or indice >= len(horarios):

                mensagem = "⏰ *Escolha um horário válido:*\n\n"

                for i, horario in enumerate(horarios, start=1):
                    mensagem += f"{i}️⃣ {horario}\n"

                mensagem += "\nDigite apenas o número do horário."

                enviar_mensagem(telefone, mensagem)

                return True

            horario_escolhido = horarios[indice]

            clientes[telefone]["horario"] = horario_escolhido
            clientes[telefone]["etapa"] = "revisao_tipo_atendimento"

            log_info("HORARIO ESCOLHIDO:", horario_escolhido)

            enviar_mensagem(
                telefone,
                "🏍️ *Tipo de atendimento:*\n\n"
                "1️⃣ Aguardar na concessionária\n"
                "2️⃣ Deixar a moto e retirar depois"
            )

            return True

        # ==========================================
        # TIPO ATENDIMENTO
        # ==========================================
        elif etapa == "revisao_tipo_atendimento":

            tipo = extrair_tipo_atendimento(texto)
            opcao_tipo = texto_opcao or texto

            if not tipo:
                if opcao_tipo == "1":
                    tipo = "AGUARDAR NA CONCESSIONÁRIA"
                elif opcao_tipo == "2":
                    tipo = "DEIXAR A MOTO E RETIRAR DEPOIS"

            if not tipo:
                enviar_mensagem(
                    telefone,
                    "🏍️ Escolha uma opção válida.\n\n"
                    "1️⃣ Aguardar na concessionária\n"
                    "2️⃣ Deixar a moto e retirar depois"
                )
                return True

            clientes[telefone]["tipo_atendimento"] = tipo
            clientes[telefone]["etapa"] = "revisao_venda"

            enviar_mensagem(
                telefone,
                "🛒 Deseja adicionar algum item?\n\n"
                "Exemplo:\nÓleo\nPastilha\nPneu\n\n"
                "Caso não queira, digite *não*."
            )

            return True

        # ==========================================
        # VENDA ADICIONAL
        # ==========================================
        elif etapa == "revisao_venda":

            if normalizar_texto(texto) in ["nao", "não", "nenhum", "nenhuma"]:
                clientes[telefone]["venda_adicional"] = "NÃO"
            else:
                clientes[telefone]["venda_adicional"] = texto

            clientes[telefone]["etapa"] = "revisao_observacao"

            enviar_mensagem(
                telefone,
                "📝 Deseja adicionar alguma observação?\n\n"
                "Caso não queira, digite *não*."
            )

            return True

        # ==========================================
        # OBSERVAÇÃO
        # ==========================================
        elif etapa == "revisao_observacao":

            if normalizar_texto(texto) in ["nao", "não", "nenhuma", "nenhum"]:
                clientes[telefone]["observacao"] = ""
            else:
                clientes[telefone]["observacao"] = texto

            clientes[telefone]["etapa"] = "revisao_confirmacao"

            resumo = (
                "📋 *CONFIRMAÇÃO DO AGENDAMENTO*\n\n"
                f"👤 Cliente: {clientes[telefone].get('nome')}\n"
                f"🏍️ Moto: {clientes[telefone].get('modelo')}\n"
                f"📅 Ano: {clientes[telefone].get('ano')}\n"
                f"📍 KM: {clientes[telefone].get('km_atual')}\n"
                f"🔧 Revisão: {clientes[telefone].get('revisao')}\n"
                f"📆 Data: {clientes[telefone].get('data')}\n"
                f"⏰ Horário: {clientes[telefone].get('horario')}\n"
                f"🏍️ Atendimento: {clientes[telefone].get('tipo_atendimento')}\n"
                f"🛒 Venda adicional: {clientes[telefone].get('venda_adicional')}\n"
                f"📝 Observação: {clientes[telefone].get('observacao') or 'Nenhuma'}\n\n"
                "1️⃣ Confirmar\n"
                "2️⃣ Cancelar"
            )

            enviar_mensagem(telefone, resumo)
            return True

        # ==========================================
        # CONFIRMAÇÃO
        # ==========================================
        elif etapa == "revisao_confirmacao":

            opcao_confirmacao = texto_opcao or texto

            if opcao_confirmacao == "1":

                sucesso_agendamento, protocolo = salvar_agendamento(
                    telefone,
                    clientes[telefone],
                )

                if not sucesso_agendamento or not protocolo:
                    enviar_mensagem(
                        telefone,
                        "⚠️ Não consegui registrar seu agendamento agora.\n\n"
                        "Vou encaminhar para um consultor te ajudar melhor."
                    )
                    ativar_atendimento_humano(telefone)
                    return True

                log_info("[SANCES] Agendamento salvo, enviando para integração:", protocolo)
                dados_sances = dict(clientes[telefone])
                dados_sances["telefone"] = telefone
                dados_sances["protocolo"] = protocolo

                retorno_sances = enviar_agendamento_para_sances(dados_sances)
                if not isinstance(retorno_sances, dict):
                    retorno_sances = {
                        "sucesso": False,
                        "status": SANCES_STATUS_ERRO,
                        "mensagem": "Retorno inválido da integração Sances.",
                        "dados": {},
                        "protocolo_sances": "",
                        "erro": "Retorno inválido da integração Sances",
                    }

                status_sances = limpar_texto(
                    retorno_sances.get("status", SANCES_STATUS_ERRO)
                ).upper()

                if status_sances == SANCES_STATUS_PENDENTE_DADOS:
                    status_sances = SANCES_STATUS_PENDENTE

                if status_sances not in [
                    SANCES_STATUS_PENDENTE,
                    SANCES_STATUS_ENVIADO,
                    SANCES_STATUS_ERRO,
                    SANCES_STATUS_NAO_CONFIGURADO,
                ]:
                    status_sances = SANCES_STATUS_ERRO

                retorno_sances["status"] = status_sances
                atualizar_status_sances_agendamento(protocolo, retorno_sances)

                clientes[telefone]["protocolo"] = protocolo
                clientes[telefone]["status"] = STATUS_AGENDADO
                clientes[telefone]["sances_status"] = status_sances
                clientes[telefone]["sances_enviado"] = bool(retorno_sances.get("sucesso"))
                clientes[telefone]["sances_protocolo"] = limpar_texto(
                    retorno_sances.get("protocolo_sances", "")
                )
                clientes[telefone]["sances_erro"] = limpar_texto(
                    retorno_sances.get("erro", "")
                )
                clientes[telefone]["sances_data_envio"] = formatar_data_hora()

                mensagem_sances = mensagem_confirmacao_sances(retorno_sances)
                enviar_mensagem(
                    telefone,
                    "✅ *Agendamento registrado!*\n\n"
                    f"📋 Protocolo interno: {protocolo}\n"
                    f"🔄 Status Sances: {status_sances}\n\n"
                    f"{mensagem_sances}\n\n"
                    "Obrigado por escolher a Motoshow Yamaha."
                )

                resetar_cliente(telefone)
                return True

            if opcao_confirmacao == "2":

                enviar_mensagem(
                    telefone,
                    "❌ Agendamento cancelado."
                )

                resetar_cliente(telefone)
                return True

            enviar_mensagem(
                telefone,
                "Digite uma opção válida:\n\n"
                "1️⃣ Confirmar\n"
                "2️⃣ Cancelar"
            )
            return True

        return False

    except Exception as e:
        log_erro("Erro processar_fluxo_revisao:", repr(e))
        return False
# ==========================================
# WEBHOOK - Z-API
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    if request.method == "GET":
        return jsonify({
            "status": "online",
            "message": "Webhook Z-API ativo"
        }), 200

    try:
        payload = request.get_json(silent=True) or {}
        log_info("PAYLOAD Z-API:", payload)

        if evento_deve_ser_ignorado(payload):
            return jsonify({"status": "ignorado", "motivo": "evento_ignorado"}), 200

        message_id, telefone, texto, tipo_mensagem = extrair_dados_zapi(payload)

        telefone = limpar_telefone(telefone)
        texto = limpar_texto(texto)
        tipo_mensagem = limpar_texto(tipo_mensagem).lower() or "text"

        texto_normalizado = normalizar_texto(texto)
        texto_opcao = limpar_opcao(texto)
        opcao_menu = normalizar_opcao_menu(texto)

        if not telefone:
            return jsonify({"status": "ignorado", "motivo": "telefone_invalido"}), 200

        if telefone_eh_grupo(str(payload)):
            return jsonify({"status": "ignorado", "motivo": "grupo"}), 200

        if message_id and mensagem_ja_processada(message_id):
            return jsonify({"status": "ignorado", "motivo": "duplicado"}), 200

        if message_id:
            registrar_mensagem_processada(message_id)

        iniciar_cliente(telefone)
        carregar_memoria_cliente_no_estado(telefone)

        etapa_anterior = limpar_texto(clientes[telefone].get("etapa", "menu")) or "menu"
        ultima_interacao_anterior = clientes[telefone].get("ultima_interacao", agora())

        if not texto and tipo_mensagem not in ["button", "audio", "image", "video", "document", "media"]:
            return jsonify({"status": "ignorado", "motivo": "sem_texto"}), 200

        etapa = limpar_texto(clientes[telefone].get("etapa", "menu")).lower() or "menu"

        # ==========================================
        # ATACADO CATÁLOGO - RETORNO IMEDIATO
        # Antes de qualquer IA, menu rápido ou revisão
        # ==========================================
        if etapa == "atacado_catalogo_enviado":
            clientes[telefone]["itens_cotacao"] = texto
            clientes[telefone]["itens"] = texto
            clientes[telefone]["observacao"] = texto
            clientes[telefone]["produto_interesse"] = texto
            clientes[telefone]["oportunidade_comercial"] = True
            clientes[telefone]["nivel_interesse"] = "ALTO"
            clientes[telefone]["temperatura_lead"] = "QUENTE"
            clientes[telefone]["nivel_interesse_atacado"] = "PARCEIRO_QUENTE"
            clientes[telefone]["proxima_acao"] = "ENCAMINHAR_CONSULTOR"
            clientes[telefone]["proxima_acao_atacado"] = "PRIORIZAR_CONSULTOR_COMERCIAL"
            clientes[telefone]["status_comercial"] = "COTACAO_ATACADO"
            classificar_atacado_estado(telefone, texto)
            salvar_lead_atacado(telefone, status="COTACAO_RECEBIDA", mensagem=texto)

            enviar_mensagem(
                telefone,
                mensagem_atacado_ia("cotacao_recebida", telefone) or (
                    "✅ Cotação recebida com sucesso.\n\n"
                    "Nossa equipe comercial irá analisar os itens e continuará o atendimento por aqui. 🤝"
                )
            )

            clientes[telefone]["atendimento_humano"] = True
            clientes[telefone]["etapa"] = "atendimento_humano"
            clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO
            clientes[telefone]["ultima_interacao"] = agora()

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Atacado",
                status=STATUS_ATENDIMENTO_HUMANO,
                etapa="atacado_cotacao_itens",
                dados=clientes[telefone],
                atendimento_humano=True,
                concluido=False,
                origem=clientes[telefone].get("origem", "BOT"),
            )

            return jsonify({"status": "ok", "fluxo": "atacado_cotacao"}), 200

        if etapa == "atacado" and texto_opcao == "1":
            classificar_atacado_estado(telefone, "catalogo")
            enviar_catalogo_atacado(telefone)
            clientes[telefone]["etapa"] = "atacado_catalogo_enviado"
            return jsonify({"status": "ok", "fluxo": "atacado_catalogo"}), 200

        # ==========================================
        # ATENDIMENTO HUMANO
        # ==========================================
        if clientes[telefone].get("atendimento_humano", False) or atendimento_humano_ativo_no_banco(telefone):
            atualizar_interacao(telefone)
            atualizar_ultima_mensagem_cliente(telefone, texto)

            if texto_pede_menu(texto):
                encerrar_atendimento_humano(telefone)
                resetar_cliente(telefone)

                enviar_mensagem(
                    telefone,
                    "✅ Atendimento automático reativado.\n\nVoltando ao menu principal."
                )

                enviar_menu(telefone)
                return jsonify({"status": "ok", "motivo": "retorno_menu"}), 200

            return jsonify({"status": "ignorado", "motivo": "atendimento_humano"}), 200

        # ==========================================
        # TIMEOUT
        # ==========================================
        try:
            tempo_sem_interacao = agora() - float(ultima_interacao_anterior)
        except Exception:
            tempo_sem_interacao = 0

        if etapa_anterior != "menu" and tempo_sem_interacao > TEMPO_INATIVIDADE:
            resetar_cliente(telefone)

            enviar_mensagem(
                telefone,
                "Olá 👋\n\nPor segurança, reiniciei seu atendimento.\nVoltando ao menu principal."
            )

            enviar_menu(telefone)
            return jsonify({"status": "ok", "motivo": "timeout"}), 200

        clientes[telefone]["ultima_mensagem_cliente"] = texto
        clientes[telefone]["tipo_mensagem"] = tipo_mensagem
        clientes[telefone]["ultima_interacao"] = agora()

        atualizar_interacao(telefone)
        atualizar_ultima_mensagem_cliente(telefone, texto)

        try:
            resetar_followups_do_cliente(telefone)
        except Exception as e:
            log_erro("Erro ao resetar follow-up:", repr(e))

        etapa = limpar_texto(clientes[telefone].get("etapa", "menu")).lower() or "menu"

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
            return jsonify({"status": "ok", "motivo": "audio_recebido"}), 200

        # ==========================================
        # MENU GLOBAL
        # ==========================================
        if texto_pede_menu(texto):
            encerrar_atendimento_humano(telefone)
            resetar_cliente(telefone)
            enviar_menu(telefone)
            return jsonify({"status": "ok", "motivo": "menu_global"}), 200

        etapa = limpar_texto(clientes[telefone].get("etapa", "menu")).lower() or "menu"

        if texto_parece_pre_orcamento(texto) and (
            etapa == "menu" or etapa.startswith("revisao_")
        ):
            montar_pre_orcamento(texto, telefone)
            return jsonify({"status": "ok", "motivo": "pre_orcamento_pecas"}), 200

        # ==========================================
        # FLUXO DE REVISÃO - PRIORIDADE ABSOLUTA
        # Evita que respostas numéricas como 1,2,3,4,5,6
        # sejam interpretadas como opções do menu principal.
        # Exceções permitidas: menu, humano/atendente e cancelar.
        # ==========================================
        if etapa.startswith("revisao_"):
            if interromper_fluxo_revisao_por_intencao_prioritaria(telefone, texto):
                return jsonify({"status": "ok", "motivo": "intencao_prioritaria_revisao"}), 200

            texto_fluxo_norm = normalizar_texto(texto)

            if texto_pede_humano(texto):
                ativar_atendimento_humano(telefone)
                return jsonify({"status": "ok", "motivo": "revisao_humano"}), 200

            if texto_fluxo_norm in ["cancelar", "cancela", "cancelamento"]:
                resetar_cliente(telefone)
                enviar_mensagem(
                    telefone,
                    "Agendamento cancelado. Voltando ao menu principal."
                )
                enviar_menu(telefone)
                return jsonify({"status": "ok", "motivo": "revisao_cancelada"}), 200

            resultado = processar_fluxo_revisao(
                telefone=telefone,
                texto=texto,
                texto_opcao=texto_opcao,
                message_id=message_id
            )

            if resultado:
                return jsonify({"status": "ok", "motivo": "fluxo_revisao"}), 200

            enviar_proxima_etapa_revisao(telefone)
            return jsonify({"status": "ok", "motivo": "proxima_etapa_revisao"}), 200

        if etapa in ["pre_orcamento_modelo", "pre_orcamento_item"]:
            montar_pre_orcamento(texto, telefone)
            return jsonify({"status": "ok", "motivo": "pre_orcamento_continuado"}), 200

        if etapa == "menu" and texto_parece_pre_orcamento(texto):
            montar_pre_orcamento(texto, telefone)
            return jsonify({"status": "ok", "motivo": "pre_orcamento"}), 200

        # ==========================================
        # DÚVIDAS POR MANUAL - PRIORIDADE ABSOLUTA
        # Antes de IA de intenção, menu rápido e revisão
        # ==========================================
        etapa = limpar_texto(clientes[telefone].get("etapa", "menu")).lower() or "menu"

        if etapa in ["duvidas_revisao", "duvidas_garantia", "duvida_manual"]:
            categoria = "revisoes" if etapa == "duvidas_revisao" else "garantia"

            if etapa == "duvida_manual":
                categoria = "manual"

            processar_pergunta_duvida_manual(
                telefone=telefone,
                texto=texto,
                categoria=categoria,
            )
            return jsonify({"status": "ok", "fluxo": "duvida_manual"}), 200

        # ==========================================
        # OPÇÃO RÁPIDA POR NÚMERO / TEXTO
        # SOMENTE QUANDO ESTIVER NO MENU
        # Isso evita quebrar horário, dia, revisão e confirmação
        # ==========================================
        etapa_atual = limpar_texto(clientes[telefone].get("etapa", "menu")).lower() or "menu"

        if etapa_atual == "menu" and opcao_menu:
            if interpretar_opcao_menu_rapido(telefone, opcao_menu):
                return jsonify({"status": "ok", "motivo": "opcao_rapida"}), 200

        etapa = limpar_texto(clientes[telefone].get("etapa", "menu")).lower() or "menu"

        # ==========================================
        # ATACADO - PRIORIDADE ANTES DE IA / REVISÃO
        # ==========================================
        if etapa in [
            "atacado",
            "atacado_catalogo_enviado",
            "atacado_cotacao",
            "atacado_cotacao_itens",
            "atacado_cadastro",
            "atacado_empresa",
            "atacado_responsavel",
            "atacado_cidade",
            "atacado_cnpj",
            "atacado_telefone_comercial",
            "atacado_segmento",
            "atacado_produtos_interesse",
            "atacado_cadastro_empresa",
            "atacado_cadastro_responsavel",
            "atacado_cadastro_cidade",
            "atacado_cadastro_cnpj",
            "atacado_cadastro_telefone",
            "atacado_cadastro_segmento",
            "atacado_cadastro_produtos",
            "atacado_catalogo_erro",
        ]:
            if processar_fluxo_atacado(telefone, texto, texto_opcao):
                return jsonify({"status": "ok", "motivo": "fluxo_atacado"}), 200

            iniciar_fluxo_atacado(telefone)
            return jsonify({"status": "ok", "motivo": "atacado_menu_reenviado"}), 200

        # ==========================================
        # CENTRAL DE DÚVIDAS - MENU
        # ==========================================
        if etapa in ["duvidas_menu", "menu_duvidas"]:
            if texto_opcao == "1":
                clientes[telefone]["etapa"] = "duvidas_revisao"
                clientes[telefone]["categoria_duvida"] = "revisoes"
                clientes[telefone]["intencao_ia"] = "duvidas"

                enviar_mensagem(
                    telefone,
                    "🔧 *Dúvidas sobre Revisões*\n\nDigite sua dúvida."
                )
                return jsonify({"status": "ok", "motivo": "duvidas_revisao"}), 200

            if texto_opcao == "2":
                clientes[telefone]["etapa"] = "duvidas_garantia"
                clientes[telefone]["categoria_duvida"] = "garantia"
                clientes[telefone]["intencao_ia"] = "duvidas"

                enviar_mensagem(
                    telefone,
                    "🛡️ *Dúvidas sobre Garantia*\n\nDigite sua dúvida."
                )
                return jsonify({"status": "ok", "motivo": "duvidas_garantia"}), 200

            if texto_opcao == "3":
                resetar_cliente(telefone)
                enviar_menu(telefone)
                return jsonify({"status": "ok", "motivo": "voltar_menu"}), 200

            if texto and texto_opcao not in ["1", "2", "3"]:
                clientes[telefone]["etapa"] = "duvida_manual"
                clientes[telefone]["categoria_duvida"] = "manual"
                processar_pergunta_duvida_manual(
                    telefone=telefone,
                    texto=texto,
                    categoria="manual",
                )
                return jsonify({"status": "ok", "motivo": "duvida_manual"}), 200

            enviar_menu_duvidas(telefone)
            return jsonify({"status": "ok", "motivo": "menu_duvidas_reenviado"}), 200

        # ==========================================
        # CENTRAL DE DÚVIDAS - PERGUNTA
        # ==========================================
        if etapa in ["duvidas", "duvida_manual", "duvidas_revisao", "duvidas_revisoes", "duvidas_garantia"]:
            categoria = "revisoes" if etapa in ["duvidas_revisao", "duvidas_revisoes"] else "garantia"
            if etapa in ["duvidas", "duvida_manual"]:
                categoria = "manual"

            processar_pergunta_duvida_manual(
                telefone=telefone,
                categoria=categoria,
                texto=texto,
            )
            return jsonify({"status": "ok", "motivo": "duvida_manual"}), 200

        # ==========================================
        # RETORNO APÓS DÚVIDA
        # ==========================================
        if etapa in ["duvidas_retorno", "duvida_pos_resposta"]:
            if texto_opcao == "1":
                enviar_menu_duvidas(telefone)
                return jsonify({"status": "ok", "motivo": "outra_duvida"}), 200

            if texto_opcao == "2":
                resetar_cliente(telefone)
                enviar_menu(telefone)
                return jsonify({"status": "ok", "motivo": "voltar_menu"}), 200

            if texto_opcao == "3":
                ativar_atendimento_humano(telefone)
                return jsonify({"status": "ok", "motivo": "duvida_humano"}), 200

            enviar_duvida_retorno_fluxo(telefone)
            return jsonify({"status": "ok", "motivo": "duvida_retorno_reenviado"}), 200

        # ==========================================
        # IA LIVRE SOMENTE FORA DE FLUXOS INTERNOS
        # ==========================================
        if etapa_permite_ia_livre(etapa):
            interpretado = tentar_interpretar_ia_no_menu(telefone, texto)

            if interpretado:
                return jsonify({"status": "ok", "motivo": "ia_ou_menu"}), 200

        etapa = limpar_texto(clientes[telefone].get("etapa", "menu")).lower() or "menu"

        # ==========================================
        # MENU PRINCIPAL
        # ==========================================
        if etapa == "menu":
            enviar_menu(telefone)
            return jsonify({"status": "ok", "motivo": "menu_reenviado"}), 200

        # ==========================================
        # CONSULTA / CANCELAMENTO / REAGENDAMENTO
        # ==========================================
        if etapa == "consulta_agendamento_cpf":
            responder_consulta_agendamento(telefone, texto)
            return jsonify({"status": "ok", "motivo": "consulta_agendamento"}), 200

        if etapa == "cancelar_agendamento_cpf":
            responder_cancelamento_agendamento(telefone, texto)
            return jsonify({"status": "ok", "motivo": "cancelamento"}), 200

        if etapa == "reagendar_agendamento_cpf":
            iniciar_reagendamento(telefone, texto)
            return jsonify({"status": "ok", "motivo": "reagendamento"}), 200

        # ==========================================
        # PEÇAS
        # ==========================================
        if etapa == "pecas":
            montar_pre_orcamento(texto, telefone)
            return jsonify({"status": "ok", "motivo": "pre_orcamento_pecas"}), 200

            clientes[telefone]["observacao"] = texto
            clientes[telefone]["produto_interesse"] = texto
            clientes[telefone]["oportunidade_comercial"] = True
            clientes[telefone]["nivel_interesse"] = "ALTO"
            clientes[telefone]["temperatura_lead"] = "QUENTE"
            clientes[telefone]["proxima_acao"] = "ENCAMINHAR_CONSULTOR"
            clientes[telefone]["status_comercial"] = "ORCAMENTO_PECAS"
            clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Peças",
                status=STATUS_ATENDIMENTO_HUMANO,
                etapa="pecas",
                dados=clientes[telefone],
                atendimento_humano=True,
                concluido=False,
                origem=clientes[telefone].get("origem", "BOT"),
            )

            enviar_mensagem(
                telefone,
                "✅ Solicitação recebida.\n\nNossa equipe de peças vai dar continuidade ao atendimento."
            )

            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok", "motivo": "pecas_humano"}), 200

        # ==========================================
        # ACESSÓRIOS
        # ==========================================
        if etapa in ["acessorios", "acessorios_modelo", "acessorios_orcamento", "acessorios_nome"]:
            if etapa in ["acessorios", "acessorios_modelo"]:
                modelo_informado = limpar_texto(texto).upper()

                if not modelo_informado:
                    enviar_mensagem(
                        telefone,
                        "Informe o modelo da sua moto para eu localizar o catálogo correto."
                    )
                    return jsonify({"status": "ok", "motivo": "acessorios_modelo_vazio"}), 200

                clientes[telefone]["modelo"] = modelo_informado
                clientes[telefone]["etapa"] = "acessorios_orcamento"
                clientes[telefone]["intencao_ia"] = "acessorios"
                clientes[telefone]["proxima_acao"] = "ACESSORIOS_ORCAMENTO"
                clientes[telefone]["ultima_interacao"] = agora()

                arquivo_pdf = obter_pdf_acessorios_por_modelo(modelo_informado)

                enviar_mensagem(
                    telefone,
                    "🛵 *Acessórios Yamaha*\n\n"
                    f"Perfeito. Identifiquei o modelo como *{modelo_informado}*."
                )

                enviado_pdf = enviar_pdf(
                    telefone,
                    arquivo_pdf,
                    "📎 Segue o catálogo de acessórios do modelo informado."
                )

                if not enviado_pdf:
                    enviar_mensagem(
                        telefone,
                        "⚠️ Não consegui enviar o catálogo agora, mas vamos continuar seu atendimento."
                    )

                enviar_mensagem(
                    telefone,
                    "Qual acessório você deseja receber orçamento? 😊"
                )

                return jsonify({"status": "ok", "motivo": "acessorios_pdf"}), 200

            if etapa in ["acessorios_orcamento", "acessorios_nome"]:
                acessorio_nome = limpar_texto(texto)

                if not acessorio_nome:
                    enviar_mensagem(
                        telefone,
                        "Por favor, informe o nome do acessório que deseja receber orçamento."
                    )
                    return jsonify({"status": "ok", "motivo": "acessorios_nome_vazio"}), 200

                clientes[telefone]["acessorio_desejado"] = acessorio_nome
                montar_pre_orcamento(acessorio_nome, telefone)
                return jsonify({"status": "ok", "motivo": "pre_orcamento_acessorios"}), 200

                clientes[telefone]["produto_interesse"] = acessorio_nome
                clientes[telefone]["oportunidade_comercial"] = True
                clientes[telefone]["nivel_interesse"] = "ALTO"
                clientes[telefone]["temperatura_lead"] = "QUENTE"
                clientes[telefone]["proxima_acao"] = "ENCAMINHAR_CONSULTOR"
                clientes[telefone]["status_comercial"] = "ORCAMENTO_ACESSORIOS"
                clientes[telefone]["observacao"] = acessorio_nome
                clientes[telefone]["itens"] = acessorio_nome
                clientes[telefone]["etapa"] = "atendimento_humano"
                clientes[telefone]["atendimento_humano"] = True
                clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO

                salvar_evento_atendimento(
                    telefone=telefone,
                    setor="Acessórios",
                    status=STATUS_ATENDIMENTO_HUMANO,
                    etapa="acessorios_orcamento",
                    dados=clientes[telefone],
                    atendimento_humano=True,
                    concluido=False,
                    origem=clientes[telefone].get("origem", "BOT"),
                )

                enviar_mensagem(
                    telefone,
                    "Perfeito! Vou encaminhar seu pedido para um consultor de acessórios. "
                    "Em instantes nossa equipe continuará o atendimento por aqui. 🤝"
                )

                ativar_atendimento_humano(telefone)
                return jsonify({"status": "ok", "motivo": "acessorios_humano"}), 200

            return jsonify({"status": "ok", "motivo": "acessorios_invalido"}), 200

        # ==========================================
        # GARANTIA - MENU E COLETA
        # ==========================================
        if etapa in [
            "garantia_menu",
            "garantia_nova_nome",
            "garantia_nova_modelo",
            "garantia_nova_ano",
            "garantia_nova_km",
            "garantia_nova_descricao",
            "garantia_acompanhar_nome",
            "garantia_acompanhar_modelo",
            "garantia_acompanhar_cpf",
            "garantia_acompanhar_descricao",
            "garantia_consulta_cpf",
            "garantia_escolher_os",
        ]:
            if processar_fluxo_garantia(telefone, texto, texto_opcao):
                return jsonify({"status": "ok", "motivo": "fluxo_garantia"}), 200

            enviar_menu_garantia(telefone)
            return jsonify({"status": "ok", "motivo": "garantia_menu_reenviado"}), 200

        # ==========================================
        # GARANTIA
        # ==========================================
        if etapa == "garantia":
            clientes[telefone]["observacao"] = texto
            clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Garantia",
                status=STATUS_ATENDIMENTO_HUMANO,
                etapa="garantia",
                dados=clientes[telefone],
                atendimento_humano=True,
                concluido=False,
                origem=clientes[telefone].get("origem", "BOT"),
            )

            enviar_mensagem(
                telefone,
                "✅ Solicitação de garantia recebida.\n\nVou encaminhar para um atendente continuar seu atendimento."
            )

            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok", "motivo": "garantia_humano"}), 200

        # ==========================================
        # ATACADO
        # ==========================================
        if etapa in [
            "atacado",
            "atacado_cotacao",
            "atacado_cotacao_itens",
            "atacado_cadastro",
            "atacado_empresa",
            "atacado_responsavel",
            "atacado_cidade",
            "atacado_cnpj",
            "atacado_telefone_comercial",
            "atacado_segmento",
            "atacado_produtos_interesse",
            "atacado_cadastro_empresa",
            "atacado_cadastro_responsavel",
            "atacado_cadastro_cidade",
            "atacado_cadastro_cnpj",
            "atacado_cadastro_telefone",
            "atacado_cadastro_segmento",
            "atacado_cadastro_produtos",
            "atacado_catalogo_enviado",
            "atacado_catalogo_erro",
        ]:
            if processar_fluxo_atacado(telefone, texto, texto_opcao):
                return jsonify({"status": "ok", "motivo": "fluxo_atacado"}), 200

            iniciar_fluxo_atacado(telefone)
            return jsonify({"status": "ok", "motivo": "atacado_menu_reenviado"}), 200

        enviar_menu(telefone)
        return jsonify({"status": "ok", "motivo": "fallback_menu"}), 200

    except Exception as e:
        log_erro("ERRO WEBHOOK Z-API:", repr(e))

        return jsonify({
            "status": "erro",
            "mensagem": "erro interno"
        }), 200


if __name__ == "__main__":
    iniciar_worker()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
