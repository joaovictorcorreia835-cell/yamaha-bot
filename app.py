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
    )
except Exception as e:
    gerar_resposta_comercial = None
    classificar_temperatura_lead = None
    gerar_mensagem_followup = None
    gerar_mensagem_recuperacao = None
    gerar_mensagem_venda_adicional = None
    gerar_mensagem_atacado = None
    print("[ERRO] Não foi possível importar ia_comercial:", repr(e), flush=True)

try:
    from ia_duvidas import responder_duvida_manual
except Exception as e:
    responder_duvida_manual = None
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
SANCES_MODO = os.getenv("SANCES_MODO", "mock").strip().lower()
SANCES_SIMULAR_RESULTADO = os.getenv(
    "SANCES_SIMULAR_RESULTADO",
    "nao_configurado"
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
        "duvidas_revisao",
        "duvidas_garantia",
        "duvidas_retorno",

        "pecas",
        "acessorios",
        "garantia",
        "atacado",
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

        if dados.get("atendimento_humano"):
            return False

        if etapa_bloqueia_ia_comercial(dados.get("etapa", "")):
            return False

        nome = dados.get("nome", "")

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

        resposta = limpar_texto(resposta_ia.get("resposta", ""))

        if not resposta:
            return False

        enviar_mensagem(telefone, resposta)

        salvar_evento_atendimento(
            telefone=telefone,
            setor="IA_COMERCIAL",
            status="IA_COMERCIAL_RESPONDEU",
            etapa=dados.get("etapa", "menu"),
            dados=dados,
            atendimento_humano=False,
            concluido=False,
            origem=dados.get("origem", "BOT"),
            observacao=f"Interesse: {resposta_ia.get('interesse', '')}",
            intencao_ia=intencao,
        )

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

        enviar_mensagem(
            telefone,
            "📦 Perfeito! Vou te enviar agora o catálogo de atacado da Motoshow Yamaha."
        )

        enviado = enviar_pdf(
            telefone,
            PDF_CATALOGO_ATACADO,
            "📎 Catálogo de atacado Motoshow Yamaha"
        )

        clientes[telefone]["etapa"] = "atacado_catalogo_enviado"
        clientes[telefone]["intencao_ia"] = "atacado"
        clientes[telefone]["proxima_acao"] = "CATALOGO_ATACADO_ENVIADO"
        clientes[telefone]["nivel_interesse"] = "QUENTE"

        if enviado:
            salvar_evento_atendimento(
                telefone=telefone,
                setor="Logista / Atacado",
                status="CATALOGO_ATACADO_ENVIADO",
                etapa="atacado_catalogo_enviado",
                dados=clientes[telefone],
                atendimento_humano=False,
                concluido=False,
                origem=clientes[telefone].get("origem", "Campanha Atacado"),
                observacao=PDF_CATALOGO_ATACADO,
                intencao_ia="atacado",
            )

            enviar_mensagem(
                telefone,
                "✅ Catálogo enviado.\n\n"
                "Deseja falar com um consultor do atacado agora?\n\n"
                "1️⃣ Sim, falar com consultor\n"
                "2️⃣ Voltar ao menu\n\n"
                "Digite apenas o número da opção desejada."
            )

            return True

        clientes[telefone]["etapa"] = "atacado_catalogo_erro"

        enviar_mensagem(
            telefone,
            "⚠️ Não consegui enviar o catálogo agora.\n\n"
            "Deseja falar com um consultor para receber manualmente?\n\n"
            "1️⃣ Sim, falar com consultor\n"
            "2️⃣ Voltar ao menu\n\n"
            "Digite apenas o número da opção desejada."
        )

        salvar_evento_atendimento(
            telefone=telefone,
            setor="Logista / Atacado",
            status="ERRO_ENVIO_CATALOGO_ATACADO",
            etapa="atacado_catalogo_erro",
            dados=clientes[telefone],
            atendimento_humano=False,
            concluido=False,
            origem=clientes[telefone].get("origem", "Campanha Atacado"),
            observacao=PDF_CATALOGO_ATACADO,
            intencao_ia="atacado",
        )

        return False

    except Exception as e:
        log_erro("Erro enviar_catalogo_atacado:", repr(e))
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

        agendamentos = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.criado_em <= limite
        ).limit(50).all()

        for ag in agendamentos:
            try:
                telefone = limpar_telefone(getattr(ag, "telefone", ""))

                if not telefone:
                    continue

                mensagem = gerar_mensagem_recuperacao(
                    modelo=getattr(ag, "modelo", ""),
                    nome=getattr(ag, "nome", ""),
                )

                if not mensagem:
                    continue

                enviar_mensagem(telefone, mensagem)

                salvar_evento_atendimento(
                    telefone=telefone,
                    setor="RECUPERACAO_IA",
                    status="RECUPERACAO_ENVIADA",
                    etapa="recuperacao_ia",
                    dados={},
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
    "duvidas_revisao",
    "duvidas_garantia",
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
    "atacado",
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
        "opcao_menu": "",

        "tipo_mensagem": "text",
        "intencao_ia": "",
        "id_envio_zapi": "",
        "status_retorno": "",

        "proxima_acao": "",
        "nivel_interesse": "",
        "temperatura_lead": "",
        "ultima_acao_ia": "",
        "followup_nivel": 0,
        "cliente_recuperado": False,
        "valor_estimado": 0,
        "origem_ia": "",

        "ultima_mensagem_cliente": "",

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
        "opcao_menu",
        "intencao_ia",
        "id_envio_zapi",
        "status_retorno",
        "proxima_acao",
        "nivel_interesse",
        "temperatura_lead",
        "ultima_acao_ia",
        "origem_ia",
        "ultima_mensagem_cliente",
    ]

    for campo in campos_limpar:
        clientes[telefone][campo] = ""

    clientes[telefone]["horarios_disponiveis"] = []
    clientes[telefone]["concluido"] = False
    clientes[telefone]["followup_nivel"] = 0
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

        setar(
            "origem",
            limpar_texto(
                origem
                or base.get("origem", "BOT")
                or "BOT"
            )
        )

        setar("status", normalizar_status(status))

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


def iniciar_fluxo_pecas(telefone, texto_inicial=""):
    telefone = limpar_telefone(telefone)

    if not telefone:
        return False

    iniciar_cliente(telefone)

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
    clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO
    clientes[telefone]["observacao"] = ""
    clientes[telefone]["modelo"] = ""
    clientes[telefone]["itens"] = ""
    clientes[telefone]["venda_adicional"] = ""

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

        clientes[telefone]["intencao_ia"] = limpar_texto(
            resposta.get("interesse", "")
        )

        clientes[telefone]["ultima_acao_ia"] = "IA_COMERCIAL"

        nivel = limpar_texto(
            resposta.get("nivel_interesse", "")
        ).upper()

        if nivel == "ALTO":
            salvar_evento_atendimento(
                telefone=telefone,
                setor="IA_COMERCIAL",
                status=STATUS_AGENDAMENTO_INICIADO,
                etapa="lead_quente_detectado",
                dados=clientes[telefone],
                atendimento_humano=False,
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


def enviar_agendamento_para_sances(dados):
    """
    Envia dados de agendamento para integração Sances.
    Retorna dict com: sucesso, status, protocolo_sances, erro
    """
    try:
        if not isinstance(dados, dict):
            return {
                "sucesso": False,
                "status": SANCES_STATUS_ERRO,
                "protocolo_sances": "",
                "erro": "Dados inválidos para envio Sances",
            }

        # Se o modo é mock, simular resposta
        if SANCES_MODO == "mock":
            sucesso_simulado = SANCES_SIMULAR_RESULTADO.lower() == "sucesso"

            return {
                "sucesso": sucesso_simulado,
                "status": SANCES_STATUS_ENVIADO if sucesso_simulado else SANCES_STATUS_ERRO,
                "protocolo_sances": f"SANCES-{uuid.uuid4().hex[:8].upper()}" if sucesso_simulado else "",
                "erro": "" if sucesso_simulado else "Modo mock: resultado simulado",
            }

        # Modo real: integração com Sances
        log_info("[SANCES] Enviando agendamento:", dados.get("protocolo", ""))

        # Aqui você implementaria a chamada real à API do Sances
        # Por enquanto, retornar resposta padrão de não configurado
        return {
            "sucesso": False,
            "status": SANCES_STATUS_NAO_CONFIGURADO,
            "protocolo_sances": "",
            "erro": "Integração Sances não configurada em modo real",
        }

    except Exception as e:
        log_erro("Erro ao enviar agendamento para Sances:", repr(e))

        return {
            "sucesso": False,
            "status": SANCES_STATUS_ERRO,
            "protocolo_sances": "",
            "erro": f"Erro na integração Sances: {repr(e)}",
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
            "revisao": str(getattr(agendamento, "revisao", "") or ""),
            "dia_semana": str(getattr(agendamento, "dia_semana", "") or ""),
            "data_agendada": str(getattr(agendamento, "data_agendada", "") or ""),
            "horario": str(getattr(agendamento, "horario", "") or ""),
            "itens": str(getattr(agendamento, "itens", "") or ""),
            "venda_adicional": str(getattr(agendamento, "venda_adicional", "") or ""),
            "observacoes": str(getattr(agendamento, "observacoes", "") or ""),
            "status": str(getattr(agendamento, "status", "") or ""),
            "origem": str(getattr(agendamento, "origem", "") or "BOT"),
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
        processar_followups_inteligentes()
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
            ag.sances_protocolo = limpar_texto(
                retorno_sances.get("protocolo_sances", "")
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
            "1️⃣ Continuar meu agendamento\n"
            "2️⃣ Fazer outra dúvida\n"
            "3️⃣ Falar com atendimento humano\n\n"
            "Digite apenas o número da opção desejada."
        )

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

    etapa_retorno = limpar_texto(
        clientes[telefone].get("etapa_retorno_duvida", "")
    )

    if etapa_retorno and etapa_retorno.startswith("revisao"):
        return [
            {"id": "DUVIDA_CONTINUAR", "label": "Continuar agendamento"},
            {"id": "DUVIDA_OUTRA", "label": "Outra dúvida"},
            {"id": "MENU_HUMANO", "label": "Atendimento humano"},
        ]

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

    clientes[telefone]["etapa"] = "duvidas_retorno"
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
@app.route("/dashboard")
def dashboard():
    db = SessionLocal()

    try:
        filtro = limpar_texto(request.args.get("filtro", "hoje")).lower()
        hoje = agora_datetime().date()

        query_atendimentos = db.query(Atendimento)
        query_agendamentos = db.query(AgendamentoRevisao)

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

        atendimentos = query_atendimentos.all()

        agendamentos_lista = (
            query_agendamentos
            .order_by(AgendamentoRevisao.id.desc())
            .limit(100)
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
                item_limpo = limpar_item_adicional(item)

                if item_adicional_valido(item_limpo):
                    contador_itens[item_limpo] += 1

        ranking_itens = contador_itens.most_common(10)
        total_itens_vendidos = sum(contador_itens.values())
        total_agendamentos_periodo = len(agendamentos_lista)

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
            agendados=agendados,
            confirmados=confirmados,
            concluidos=concluidos,
            cancelados=cancelados,
            reagendados=reagendados,
            atendimento_humano=atendimento_humano,
            duvidas_ia=duvidas_ia,
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
        "geral": 90 * 60,
    }

    return float(tempos.get(contexto, 90 * 60))


def montar_mensagem_followup_inteligente(at):
    contexto = identificar_contexto_followup(at)

    if contexto == "ignorar":
        return ""

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

    mensagem = mensagens.get(contexto, mensagens["geral"])

    return (
        mensagem +
        "\n\n1️⃣ Continuar atendimento\n"
        "2️⃣ Falar com consultor\n"
        "3️⃣ Menu principal\n\n"
        "Digite apenas o número da opção desejada."
    )


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
        "menu_duvidas",
        "duvidas_revisao",
        "duvidas_garantia",
        "duvidas_retorno",

        "consulta_agendamento_cpf",
        "cancelar_agendamento_cpf",
        "reagendar_agendamento_cpf",
        "pos_consulta_agendamento",

        "acessorios_modelo",
        "acessorios_orcamento",

        "pecas",
        "garantia",
        "atacado",
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
    if etapa_atual == "duvidas_retorno":
        etapa_retorno = limpar_texto(
            clientes[telefone].get("etapa_retorno_duvida", "")
        )

        if etapa_retorno and etapa_retorno.startswith("revisao"):
            if opcao_normalizada in ["1", "OPCAO_1", "DUVIDA_CONTINUAR"]:
                clientes[telefone]["etapa"] = etapa_retorno
                enviar_proxima_etapa_revisao(telefone)
                return True

            if opcao_normalizada in ["2", "OPCAO_2", "DUVIDA_OUTRA"]:
                clientes[telefone]["etapa"] = "duvidas_menu"
                enviar_menu_duvidas(telefone)
                return True

            if opcao_normalizada in ["3", "OPCAO_3", "MENU_HUMANO"]:
                ativar_atendimento_humano(telefone)
                return True

        else:
            if opcao_normalizada in ["1", "OPCAO_1", "DUVIDA_OUTRA"]:
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
            clientes[telefone]["etapa"] = "garantia"
            clientes[telefone]["intencao_ia"] = "garantia"
            clientes[telefone]["atendimento_humano"] = False
            clientes[telefone]["ultima_interacao"] = agora()
            clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Garantia",
                status=STATUS_NOVO_ATENDIMENTO,
                etapa="garantia_iniciada",
                dados=clientes[telefone],
                atendimento_humano=False,
                concluido=False,
                origem=clientes[telefone].get("origem", "BOT"),
            )

            enviar_mensagem(
                telefone,
                "🛡️ *Garantia*\n\nDescreva sua solicitação de garantia:"
            )
            return True

        if opcao_normalizada in ["5", "OPCAO_5", "MENU_ATACADO"]:
            clientes[telefone]["etapa"] = "atacado"
            clientes[telefone]["intencao_ia"] = "atacado"
            clientes[telefone]["atendimento_humano"] = False
            clientes[telefone]["ultima_interacao"] = agora()
            clientes[telefone]["status"] = STATUS_NOVO_ATENDIMENTO

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

            enviar_mensagem(
                telefone,
                "📦 *Logista / Atacado*\n\nDigite sua solicitação de atacado:"
            )
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
        clientes[telefone]["etapa"] = "garantia"
        enviar_mensagem(
            telefone,
            "🛡️ *Garantia*\n\nDescreva sua solicitação de garantia:"
        )
        return True

    if opcao_normalizada in ["MENU_ATACADO", "ATACADO_TABELA"]:
        clientes[telefone]["etapa"] = "atacado"
        enviar_mensagem(
            telefone,
            "📦 *Logista / Atacado*\n\nDigite sua solicitação de atacado:"
        )
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
        "duvidas",
        "duvida",
        "dúvidas",
        "dúvida",
        "consultar_agendamento",
        "cancelar_agendamento",
        "reagendar_agendamento",
    ]

    if confianca < 0.55 and intencao not in intencoes_validas:
        return False

    if intencao == "agendar_revisao":
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos)
        iniciar_fluxo_revisao_por_intencao(telefone, dados_extraidos)

        resumo = montar_resumo_dados_ia_revisao(telefone)

        if resumo:
            enviar_mensagem(telefone, resumo)

        enviar_proxima_etapa_revisao(telefone)
        return True

    if intencao == "valor_revisao":
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

    if intencao == "pecas":
        iniciar_fluxo_pecas(telefone, texto)
        return True

    if intencao == "acessorios":
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
            origem=clientes[telefone].get("origem", "BOT"),
        )

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
            origem=clientes[telefone].get("origem", "BOT"),
        )

        if resposta_texto:
            enviar_mensagem(telefone, resposta_texto)

        enviar_mensagem(
            telefone,
            "📦 *Logista / Atacado*\n\nDigite sua solicitação de atacado:"
        )

        return True

    if intencao in ["duvidas", "duvida", "dúvidas", "dúvida"]:
        etapa_anterior = clientes[telefone].get("etapa", "")
        clientes[telefone]["ultima_interacao"] = agora()
        clientes[telefone]["intencao_ia"] = "duvidas"

        enviado = encaminhar_para_menu_duvidas(telefone, etapa_anterior)

        if not enviado:
            enviar_menu_duvidas(telefone)

        return True

    if intencao == "consultar_agendamento":
        clientes[telefone]["etapa"] = "consulta_agendamento_cpf"

        enviar_mensagem(
            telefone,
            "📄 Para consultar seu agendamento, informe seu *CPF com 11 números*."
        )

        return True

    if intencao == "cancelar_agendamento":
        clientes[telefone]["etapa"] = "cancelar_agendamento_cpf"

        enviar_mensagem(
            telefone,
            "📄 Para cancelar seu agendamento, informe seu *CPF com 11 números*."
        )

        return True

    if intencao == "reagendar_agendamento":
        clientes[telefone]["etapa"] = "reagendar_agendamento_cpf"

        enviar_mensagem(
            telefone,
            "📄 Para reagendar, informe seu *CPF com 11 números*."
        )

        return True

    if intencao == "humano":
        ativar_atendimento_humano(telefone)
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

            clientes[telefone]["cpf"] = texto
            clientes[telefone]["etapa"] = "revisao_ano"

            enviar_mensagem(
                telefone,
                "📅 Informe o *ano da moto*."
            )

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

                protocolo = gerar_protocolo()

                clientes[telefone]["protocolo"] = protocolo
                clientes[telefone]["status"] = STATUS_AGENDADO

                enviar_mensagem(
                    telefone,
                    "✅ *Agendamento realizado com sucesso!*\n\n"
                    f"📋 Protocolo: {protocolo}\n\n"
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

        etapa_anterior = limpar_texto(clientes[telefone].get("etapa", "menu")) or "menu"
        ultima_interacao_anterior = clientes[telefone].get("ultima_interacao", agora())

        if not texto and tipo_mensagem not in ["button", "audio", "image", "video", "document", "media"]:
            return jsonify({"status": "ignorado", "motivo": "sem_texto"}), 200

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

            enviar_menu_duvidas(telefone)
            return jsonify({"status": "ok", "motivo": "menu_duvidas_reenviado"}), 200

        # ==========================================
        # CENTRAL DE DÚVIDAS - PERGUNTA
        # ==========================================
        if etapa in ["duvidas_revisao", "duvidas_revisoes", "duvidas_garantia"]:
            categoria = "revisoes" if etapa in ["duvidas_revisao", "duvidas_revisoes"] else "garantia"

            resposta = responder_duvida_por_tabela(
                categoria=categoria,
                pergunta_cliente=texto,
                modelo=clientes[telefone].get("modelo", ""),
                revisao=clientes[telefone].get("revisao", ""),
            )

            salvar_duvida_dashboard(
                telefone=telefone,
                categoria=categoria,
                pergunta=texto,
                resposta=resposta or "",
            )

            enviar_mensagem(
                telefone,
                resposta or "Não encontrei essa informação na base. Vou encaminhar para um atendente."
            )

            if not resposta:
                ativar_atendimento_humano(telefone)
                return jsonify({"status": "ok", "motivo": "duvida_humano"}), 200

            enviar_duvida_retorno_fluxo(telefone)
            return jsonify({"status": "ok", "motivo": "duvida_respondida"}), 200

        # ==========================================
        # RETORNO APÓS DÚVIDA
        # ==========================================
        if etapa == "duvidas_retorno":
            etapa_retorno = limpar_texto(clientes[telefone].get("etapa_retorno_duvida", ""))

            if etapa_retorno.startswith("revisao"):
                if texto_opcao == "1":
                    clientes[telefone]["etapa"] = etapa_retorno
                    enviar_proxima_etapa_revisao(telefone)
                    return jsonify({"status": "ok", "motivo": "retorno_revisao"}), 200

                if texto_opcao == "2":
                    enviar_menu_duvidas(telefone)
                    return jsonify({"status": "ok", "motivo": "outra_duvida"}), 200

                if texto_opcao == "3":
                    ativar_atendimento_humano(telefone)
                    return jsonify({"status": "ok", "motivo": "duvida_humano"}), 200

            else:
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
        # FLUXO DE REVISÃO
        # ==========================================
        if etapa.startswith("revisao_"):
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
            clientes[telefone]["observacao"] = texto
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
        if etapa in ["acessorios", "acessorios_modelo", "acessorios_orcamento"]:
            if etapa == "acessorios_modelo":
                modelo_informado = limpar_texto(texto).upper()

                if not modelo_informado:
                    enviar_mensagem(
                        telefone,
                        "Informe o modelo da sua moto para eu localizar o catálogo correto."
                    )
                    return jsonify({"status": "ok", "motivo": "acessorios_modelo_vazio"}), 200

                clientes[telefone]["modelo"] = modelo_informado
                clientes[telefone]["etapa"] = "acessorios_orcamento"

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
                        "⚠️ Não consegui enviar o catálogo agora, mas vamos continuar."
                    )

                enviar_mensagem(
                    telefone,
                    "Agora me informe *qual acessório você deseja para orçamento*."
                )

                return jsonify({"status": "ok", "motivo": "acessorios_pdf"}), 200

            clientes[telefone]["observacao"] = texto
            clientes[telefone]["itens"] = texto
            clientes[telefone]["venda_adicional"] = texto
            clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Acessórios",
                status=STATUS_ATENDIMENTO_HUMANO,
                etapa=etapa,
                dados=clientes[telefone],
                atendimento_humano=True,
                concluido=False,
                origem=clientes[telefone].get("origem", "BOT"),
            )

            enviar_mensagem(
                telefone,
                "✅ Recebi sua solicitação de acessórios.\n\nNossa equipe vai continuar o atendimento."
            )

            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok", "motivo": "acessorios_humano"}), 200

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
        if etapa == "atacado":
            if texto_opcao == "1":
                enviar_catalogo_atacado(telefone)
                return jsonify({"status": "ok", "motivo": "atacado_catalogo"}), 200

            if texto_opcao == "2":
                ativar_atendimento_humano(telefone)
                return jsonify({"status": "ok", "motivo": "atacado_consultor"}), 200

            if texto_opcao == "3":
                clientes[telefone]["status_retorno"] = "DEPOIS"
                clientes[telefone]["nivel_interesse"] = "BAIXO"

                enviar_mensagem(
                    telefone,
                    "Tudo bem 👍\n\nQuando quiser consultar peças, óleo Yamalube ou acessórios no atacado, é só chamar."
                )

                resetar_cliente(telefone)
                return jsonify({"status": "ok", "motivo": "atacado_depois"}), 200

            clientes[telefone]["observacao"] = texto
            clientes[telefone]["status"] = STATUS_ATENDIMENTO_HUMANO

            salvar_evento_atendimento(
                telefone=telefone,
                setor="Logista / Atacado",
                status=STATUS_ATENDIMENTO_HUMANO,
                etapa="atacado",
                dados=clientes[telefone],
                atendimento_humano=True,
                concluido=False,
                origem=clientes[telefone].get("origem", "Campanha Atacado"),
            )

            enviar_mensagem(
                telefone,
                "✅ Perfeito. Vou encaminhar seu atendimento para o setor de atacado."
            )

            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok", "motivo": "atacado_humano"}), 200

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