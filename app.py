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
from ia_intencao import classificar_intencao

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

MENSAGEM_FOLLOWUP_1 = os.getenv(
    "MENSAGEM_FOLLOWUP_1",
    "Olá 👋\n\n"
    "Passando para saber se conseguiu verificar nossa mensagem.\n\n"
    "Estamos com agenda aberta para revisões e podemos verificar um horário para você.\n\n"
    "Se desejar, responda esta mensagem e seguimos com seu atendimento.\n\n"
    "Equipe Motoshow Yamaha"
)

MENSAGEM_FOLLOWUP_2 = os.getenv(
    "MENSAGEM_FOLLOWUP_2",
    "Olá 👋\n\n"
    "Estamos finalizando nosso acompanhamento e gostaria de confirmar se ainda deseja atendimento.\n\n"
    "Se quiser, posso verificar disponibilidade para sua revisão ou seguir com sua solicitação.\n\n"
    "Equipe Motoshow Yamaha"
)

url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"

clientes = {}
mensagens_processadas = set()
fila_mensagens = deque(maxlen=2000)

followup_lock = threading.Lock()
worker_followup_iniciado = False

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

INTENCOES_REVISAO = {
    "agendar_revisao",
    "cancelar_agendamento",
    "reagendar_agendamento",
    "acompanhar_agendamento",
    "consultar_agendamento",
    "falar_humano",
    "humano",
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


def normalizar_revisao_para_fluxo(valor):
    texto = limpar_opcao(valor)
    mapa = {
        "1": "1",
        "1a": "1",
        "1ª": "1",
        "1o": "1",
        "2": "2",
        "2a": "2",
        "2ª": "2",
        "2o": "2",
        "3": "3",
        "3a": "3",
        "3ª": "3",
        "3o": "3",
        "4": "4",
        "4a": "4",
        "4ª": "4",
        "4o": "4",
        "5": "5",
        "5a": "5",
        "5ª": "5",
        "5o": "5",
    }
    return mapa.get(normalizar_texto(texto), texto if texto in ["1", "2", "3", "4", "5"] else "")


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


# ==========================================
# ITENS ADICIONAIS
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
        for v in valor:
            item = limpar_item_adicional(v)
            if item:
                itens.append(item)
        return itens

    texto = str(valor).strip()
    if not texto:
        return []

    texto = texto.replace("\n", ",").replace(";", ",")
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


# ==========================================
# APOIO IA REVISÃO
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
    dia_texto = limpar_texto(dados_extraidos.get("dia"))
    if dia_texto in ["1", "2", "3", "4", "5", "6"]:
        dia_numero = dia_texto
    else:
        dia_numero = numero_dia_por_texto(dia_texto) if dia_texto else ""
    data = limpar_texto(dados_extraidos.get("data"))
    horario = limpar_texto(dados_extraidos.get("horario"))
    item_adicional = formatar_itens_adicionais_para_salvar(dados_extraidos.get("item_adicional", ""))

    if modelo and not dados.get("modelo"):
        dados["modelo"] = modelo.upper()

    if nome and not dados.get("nome"):
        dados["nome"] = nome.upper()

    if cpf and len(cpf) == 11 and not dados.get("cpf"):
        dados["cpf"] = cpf

    if ano and not dados.get("ano"):
        dados["ano"] = ano

    if revisao and not dados.get("revisao"):
        dados["revisao"] = revisao

    if dia_numero and not dados.get("dia"):
        dados["dia"] = dia_numero
        dados["dia_texto"] = nome_dia(dia_numero)

    if data and not dados.get("data"):
        dados["data"] = data

    if horario and not dados.get("horario"):
        dados["horario"] = horario

    if item_adicional and not dados.get("itens"):
        dados["itens"] = item_adicional
        dados["venda_adicional"] = item_adicional


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
    if not dados.get("revisao"):
        return "revisao_tipo"
    if not dados.get("dia"):
        return "revisao_dia"
    if not dados.get("data"):
        return "revisao_data"
    if not dados.get("horario"):
        return "revisao_horario"
    if not dados.get("itens") and clientes[telefone]["etapa"] != "revisao_venda":
        return "revisao_venda"
    return "revisao_confirmar"


def iniciar_fluxo_revisao_por_intencao(telefone, dados_extraidos=None):
    limpar_dados_fluxo_revisao(telefone)

    if dados_extraidos:
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos)

    proxima = primeira_etapa_pendente_revisao(telefone)
    clientes[telefone]["etapa"] = proxima
    return proxima


def mensagem_por_etapa_revisao(telefone, etapa):
    iniciar_cliente(telefone)
    dados = clientes[telefone]

    if etapa == "revisao_modelo":
        return "🔧 *Agendamento de Revisão*\n\nInforme o *modelo da moto*:"

    if etapa == "revisao_nome":
        resumo = f"🏍️ Modelo: {dados['modelo']}\n\n" if dados.get("modelo") else ""
        return f"{resumo}👤 Informe seu *nome completo*:"

    if etapa == "revisao_cpf":
        return "📄 Informe seu *CPF*:"

    if etapa == "revisao_ano":
        return "📅 Informe o *ano da moto*:"

    if etapa == "revisao_tipo":
        return (
            "🔧 Qual revisão deseja agendar?\n\n"
            "1 - 1ª Revisão\n"
            "2 - 2ª Revisão\n"
            "3 - 3ª Revisão\n"
            "4 - 4ª Revisão\n"
            "5 - 5ª Revisão ou acima"
        )

    if etapa == "revisao_dia":
        return (
            "📅 Escolha o dia:\n\n"
            "1 - Segunda\n"
            "2 - Terça\n"
            "3 - Quarta\n"
            "4 - Quinta\n"
            "5 - Sexta\n"
            "6 - Sábado"
        )

    if etapa == "revisao_data":
        return (
            "📆 Informe a data desejada:\n"
            "Exemplo: 20/04/2026"
        )

    if etapa == "revisao_venda":
        return montar_mensagem_venda_adicional(telefone)

    return "Vamos continuar seu agendamento."
# ==========================================
# CONTROLE DE ESTADO
# ==========================================
def estado_padrao_cliente():
    return {
        "etapa": "menu",
        "ultima_interacao": agora(),
        "atendimento_humano": False,
        "modelo": "",
        "nome": "",
        "cpf": "",
        "ano": "",
        "revisao": "",
        "dia": "",
        "dia_texto": "",
        "data": "",
        "horario": "",
        "itens": "",
        "venda_adicional": "",
        "concluido": False,
        "horarios_disponiveis": []
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
    clientes[telefone]["dia"] = ""
    clientes[telefone]["dia_texto"] = ""
    clientes[telefone]["data"] = ""
    clientes[telefone]["horario"] = ""
    clientes[telefone]["itens"] = ""
    clientes[telefone]["venda_adicional"] = ""
    clientes[telefone]["concluido"] = False
    clientes[telefone]["horarios_disponiveis"] = []


def ativar_atendimento_humano(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["etapa"] = "atendimento_humano"
    clientes[telefone]["ultima_interacao"] = agora()

    enviar_mensagem(
        telefone,
        "👨‍💼 *Atendimento humano acionado.*\n\n"
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


# ==========================================
# DUPLICIDADE
# ==========================================
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


# ==========================================
# IGNORAR PRÓPRIO BOT
# ==========================================
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

        if any(valor is True for valor in marcadores_true):
            return True

        return False
    except Exception as e:
        log_erro("Erro ao validar evento do próprio bot:", e)
        return False


# ==========================================
# ENVIO MENSAGEM
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


# ==========================================
# ENVIAR PDF
# ==========================================
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
# MENU
# ==========================================
def enviar_menu(telefone):
    mensagem = (
        "Olá 👋\n\n"
        "🏍️ *Pós-Vendas Motoshow Yamaha*\n\n"
        "1️⃣ Agendar Revisão\n"
        "2️⃣ Peças\n"
        "3️⃣ Acessórios\n"
        "4️⃣ Garantia\n"
        "5️⃣ Logista / Atacado\n"
        "6️⃣ Atendimento Humano\n\n"
        "Equipe Motoshow Yamaha"
    )
    enviar_mensagem(telefone, mensagem)


def montar_mensagem_venda_adicional(telefone):
    return (
        "🛠️ Deseja adicionar algo?\n\n"
        "Ex:\n"
        "• Filtro de ar\n"
        "• Pastilha de freio\n"
        "• Slider\n\n"
        "Digite o item ou 2 para não"
    )


def montar_mensagem_horarios(lista):
    msg = "⏰ Escolha o horário:\n\n"
    for i, h in enumerate(lista):
        msg += f"{i+1} - {h}\n"
    return msg


# ==========================================
# CAPACIDADE POR HORÁRIO
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
            AgendamentoRevisao.status == "AGENDADO"
        ).count()

        return quantidade < limite

    except Exception as e:
        log_erro("Erro capacidade:", e)
        return True

    finally:
        db.close()


def gerar_protocolo():
    return str(uuid.uuid4())[:8].upper()


def salvar_agendamento(telefone, dados):
    db = SessionLocal()

    try:
        protocolo = gerar_protocolo()

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
            itens=formatar_itens_adicionais_para_salvar(dados.get("itens", "")),
            venda_adicional=formatar_itens_adicionais_para_salvar(dados.get("venda_adicional", "")),
            status="AGENDADO",
            origem="BOT"
        )

        db.add(agendamento)
        db.commit()

        log_info("Agendamento salvo:", protocolo)
        return protocolo

    except Exception as e:
        db.rollback()
        log_erro("Erro salvar agendamento:", e)
        return None

    finally:
        db.close()


def buscar_agendamento_ativo(cpf):
    db = SessionLocal()

    try:
        agendamento = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.cpf == cpf,
            AgendamentoRevisao.status == "AGENDADO"
        ).first()

        return agendamento

    except Exception as e:
        log_erro("Erro buscar agendamento:", e)
        return None

    finally:
        db.close()


def buscar_agendamento_por_cpf(cpf):
    return buscar_agendamento_ativo(cpf)


def cancelar_agendamento(cpf, novo_status="CANCELADO"):
    db = SessionLocal()

    try:
        agendamento = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.cpf == cpf,
            AgendamentoRevisao.status == "AGENDADO"
        ).first()

        if agendamento:
            agendamento.status = novo_status
            db.commit()
            return agendamento

        return None

    except Exception as e:
        db.rollback()
        log_erro("Erro cancelar:", e)
        return None

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


# ==========================================
# FOLLOW-UP + LEMBRETES
# ==========================================
def processar_lembretes_agendamento():
    db = SessionLocal()

    try:
        hoje = datetime.now().date()

        agendamentos = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.status == "AGENDADO",
            AgendamentoRevisao.lembrete_enviado == False
        ).all()

        for ag in agendamentos:
            try:
                data_agendada = datetime.strptime(
                    ag.data_agendada,
                    "%d/%m/%Y"
                ).date()

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
                log_erro("Erro lembrete:", e)

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
    thread = threading.Thread(
        target=worker,
        daemon=True
    )
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
            query = query.filter(
                Atendimento.data >= datetime.combine(hoje, datetime.min.time())
            )

            query_ag = query_ag.filter(
                AgendamentoRevisao.criado_em >= datetime.combine(hoje, datetime.min.time())
            )

        elif filtro == "semana":
            query = query.filter(
                Atendimento.data >= datetime.combine(inicio_semana, datetime.min.time())
            )

            query_ag = query_ag.filter(
                AgendamentoRevisao.criado_em >= datetime.combine(inicio_semana, datetime.min.time())
            )

        elif filtro == "mes":
            query = query.filter(
                Atendimento.data >= datetime.combine(inicio_mes, datetime.min.time())
            )

            query_ag = query_ag.filter(
                AgendamentoRevisao.criado_em >= datetime.combine(inicio_mes, datetime.min.time())
            )

        total = query.count()
        revisao = query.filter(Atendimento.setor == "Revisão").count()
        agendados = query.filter(Atendimento.status == "Agendado").count()

        cancelados = query_ag.filter(
            AgendamentoRevisao.status == "CANCELADO"
        ).count()

        reagendados = query_ag.filter(
            AgendamentoRevisao.status == "REAGENDADO"
        ).count()

        total_agendamentos_periodo = query_ag.count()

        primeira = query.filter(Atendimento.revisao == "1").count()
        segunda = query.filter(Atendimento.revisao == "2").count()
        terceira = query.filter(Atendimento.revisao == "3").count()
        quarta = query.filter(Atendimento.revisao == "4").count()
        quinta = query.filter(Atendimento.revisao == "5").count()

        contador_itens = Counter()
        registros_itens = query.with_entities(Atendimento.itens).all()

        for item in registros_itens:
            valor = item[0] if isinstance(item, tuple) else item

            if not valor:
                continue

            lista_itens = extrair_lista_itens_adicionais(valor)

            for i in lista_itens:
                contador_itens[i] += 1

        ranking_itens = contador_itens.most_common(20)
        total_itens_vendidos = sum(contador_itens.values())

        agendamentos = db.query(AgendamentoRevisao).order_by(
            AgendamentoRevisao.criado_em.desc()
        ).limit(20).all()

        return render_template(
            "dashboard.html",
            total=total,
            revisao=revisao,
            agendados=agendados,
            cancelados=cancelados,
            reagendados=reagendados,
            total_agendamentos_periodo=total_agendamentos_periodo,
            primeira=primeira,
            segunda=segunda,
            terceira=terceira,
            quarta=quarta,
            quinta=quinta,
            total_itens_vendidos=total_itens_vendidos,
            ranking_itens=ranking_itens,
            filtro_ativo=filtro,
            agendamentos=agendamentos
        )

    except Exception as e:
        log_erro("Dashboard erro:", e)
        return "Erro dashboard", 500

    finally:
        db.close()


# ==========================================
# AUXILIARES DO FLUXO DE REVISÃO
# ==========================================
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
                "⚠️ Não há horários disponíveis para esse tipo de revisão neste dia.\n\n"
                "Escolha outro dia."
            )

            enviar_mensagem(
                telefone,
                mensagem_por_etapa_revisao(
                    telefone,
                    "revisao_dia"
                )
            )
            return

        clientes[telefone]["horarios_disponiveis"] = horarios
        enviar_mensagem(
            telefone,
            montar_mensagem_horarios(
                horarios
            )
        )
        return

    if etapa == "revisao_confirmar":
        clientes[telefone]["etapa"] = "revisao_venda"

        enviar_mensagem(
            telefone,
            montar_mensagem_venda_adicional(
                telefone
            )
        )
        return

    enviar_mensagem(
        telefone,
        mensagem_por_etapa_revisao(
            telefone,
            etapa
        )
    )


# ==========================================
# CONSULTAR AGENDAMENTO
# ==========================================
def responder_consulta_agendamento(
    telefone,
    cpf
):

    if not cpf or len(
        limpar_cpf(cpf)
    ) != 11:

        enviar_mensagem(
            telefone,
            "📄 Para consultar seu agendamento, informe seu *CPF com 11 números*."
        )

        clientes[
            telefone
        ]["etapa"] = "consulta_agendamento_cpf"

        return

    ag = buscar_agendamento_por_cpf(
        limpar_cpf(cpf)
    )

    if not ag:

        enviar_mensagem(
            telefone,
            "⚠️ Não localizei agendamento ativo para este CPF.\n\n"
            "Se quiser, posso iniciar um novo agendamento. Envie *quero agendar revisão*."
        )

        resetar_cliente(
            telefone
        )

        return

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

    resetar_cliente(
        telefone
    )


# ==========================================
# CANCELAR AGENDAMENTO
# ==========================================
def responder_cancelamento_agendamento(
    telefone,
    cpf
):

    if not cpf or len(
        limpar_cpf(cpf)
    ) != 11:

        enviar_mensagem(
            telefone,
            "📄 Para cancelar seu agendamento, informe seu *CPF com 11 números*."
        )

        clientes[
            telefone
        ]["etapa"] = "cancelar_agendamento_cpf"

        return

    ag_cancelado = cancelar_agendamento(
        limpar_cpf(cpf)
    )

    if not ag_cancelado:

        enviar_mensagem(
            telefone,
            "⚠️ Não encontrei agendamento ativo para este CPF."
        )

        resetar_cliente(
            telefone
        )

        return

    enviar_mensagem(
        telefone,
        "✅ *Agendamento cancelado com sucesso.*\n\n"
        f"👤 {ag_cancelado.nome}\n"
        f"🏍️ {ag_cancelado.modelo}\n"
        f"📅 {ag_cancelado.data_agendada}\n"
        f"⏰ {ag_cancelado.horario}\n"
        f"📌 Protocolo: {ag_cancelado.protocolo}\n\n"
        "Equipe Motoshow Yamaha"
    )

    resetar_cliente(
        telefone
    )


# ==========================================
# REAGENDAMENTO
# ==========================================
def iniciar_reagendamento(
    telefone,
    cpf
):

    if not cpf or len(
        limpar_cpf(cpf)
    ) != 11:

        enviar_mensagem(
            telefone,
            "📄 Para reagendar, informe seu *CPF com 11 números*."
        )

        clientes[
            telefone
        ]["etapa"] = "reagendar_agendamento_cpf"

        return

    ag = buscar_agendamento_por_cpf(
        limpar_cpf(cpf)
    )

    if not ag:

        enviar_mensagem(
            telefone,
            "⚠️ Não encontrei agendamento ativo para este CPF."
        )

        resetar_cliente(
            telefone
        )

        return

    clientes[telefone]["modelo"] = limpar_texto(
        ag.modelo
    ).upper()

    clientes[telefone]["nome"] = limpar_texto(
        ag.nome
    ).upper()

    clientes[telefone]["cpf"] = limpar_cpf(
        ag.cpf
    )

    clientes[telefone]["ano"] = limpar_texto(
        ag.ano
    )

    clientes[telefone]["revisao"] = limpar_texto(
        ag.revisao
    )

    cancelar_agendamento(
        clientes[telefone]["cpf"],
        novo_status="REAGENDADO"
    )

    clientes[
        telefone
    ]["etapa"] = "revisao_dia"

    enviar_mensagem(
        telefone,
        "🔄 *Reagendamento iniciado.*\n\n"
        f"👤 {clientes[telefone]['nome']}\n"
        f"🏍️ {clientes[telefone]['modelo']}\n"
        f"🔧 Revisão: {clientes[telefone]['revisao']}ª\n\n"
        "Escolha o novo dia:"
    )

    enviar_mensagem(
        telefone,
        mensagem_por_etapa_revisao(
            telefone,
            "revisao_dia"
        )
    )
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
    # INTENÇÕES GERAIS DE REVISÃO
    # ==========================================
    if intencao_ia == "humano" or intencao_ia == "falar_humano":
        ativar_atendimento_humano(telefone)
        return jsonify({"status": "ok"}), 200

    if intencao_ia == "consultar_agendamento" or intencao_ia == "acompanhar_agendamento":
        cpf = limpar_cpf(dados_extraidos_ia.get("cpf", "") or texto)
        responder_consulta_agendamento(telefone, cpf)
        return jsonify({"status": "ok"}), 200

    if intencao_ia == "cancelar_agendamento":
        cpf = limpar_cpf(dados_extraidos_ia.get("cpf", "") or texto)
        responder_cancelamento_agendamento(telefone, cpf)
        return jsonify({"status": "ok"}), 200

    if intencao_ia == "reagendar_agendamento":
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
    # MENU PRINCIPAL
    # ==========================================
    if etapa == "menu":

        if texto_opcao == "1":
            proxima = iniciar_fluxo_revisao_por_intencao(telefone, {})
            enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, proxima))
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "2":
            clientes[telefone]["etapa"] = "pecas"
            enviar_mensagem(
                telefone,
                "🔩 *Peças*\n\n"
                "Informe a peça desejada:"
            )
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "3":
            clientes[telefone]["etapa"] = "acessorios"
            enviar_mensagem(
                telefone,
                "🛵 *Acessórios*\n\n"
                "Informe o acessório desejado:"
            )
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "4":
            clientes[telefone]["etapa"] = "garantia"
            enviar_mensagem(
                telefone,
                "🛡️ *Garantia*\n\n"
                "Descreva sua solicitação:"
            )
            return jsonify({"status": "ok"}), 200

        elif texto_opcao == "5":
            clientes[telefone]["etapa"] = "atacado"
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
            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "agendar_revisao":
            proxima = iniciar_fluxo_revisao_por_intencao(telefone, dados_extraidos_ia)
            enviar_mensagem(telefone, "Perfeito. Vou seguir com seu agendamento de revisão.")

            if proxima == "revisao_horario":
                enviar_proxima_etapa_revisao(telefone)
            else:
                enviar_mensagem(telefone, mensagem_por_etapa_revisao(telefone, proxima))

            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "pecas":
            clientes[telefone]["etapa"] = "pecas"
            enviar_mensagem(telefone, "🔩 Informe a peça desejada:")
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "acessorios":
            clientes[telefone]["etapa"] = "acessorios"
            enviar_mensagem(telefone, "🛵 Informe o acessório desejado:")
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "garantia":
            clientes[telefone]["etapa"] = "garantia"
            enviar_mensagem(telefone, "🛡️ Descreva sua solicitação de garantia:")
            return jsonify({"status": "ok"}), 200

        elif intencao_ia == "atacado":
            clientes[telefone]["etapa"] = "atacado"
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
    # REVISÃO AUTOMÁTICA POR ETAPA
    # ==========================================
    if etapa == "revisao_modelo":
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos_ia)

        if not clientes[telefone].get("modelo"):
            clientes[telefone]["modelo"] = texto.upper()

        enviar_proxima_etapa_revisao(telefone)
        return jsonify({"status": "ok"}), 200


    if etapa == "revisao_nome":
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos_ia)

        if not clientes[telefone].get("nome"):
            clientes[telefone]["nome"] = texto.upper()

        enviar_proxima_etapa_revisao(telefone)
        return jsonify({"status": "ok"}), 200


    if etapa == "revisao_cpf":
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos_ia)

        cpf = clientes[telefone].get("cpf") or limpar_cpf(texto)

        if len(cpf) != 11:
            enviar_mensagem(telefone, "⚠️ CPF inválido. Digite novamente com 11 números:")
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["cpf"] = cpf
        enviar_proxima_etapa_revisao(telefone)
        return jsonify({"status": "ok"}), 200


    if etapa == "revisao_ano":
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos_ia)

        ano = clientes[telefone].get("ano") or texto

        if not ano:
            enviar_mensagem(telefone, "⚠️ Informe o ano da moto.")
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["ano"] = ano
        enviar_proxima_etapa_revisao(telefone)
        return jsonify({"status": "ok"}), 200


    if etapa == "revisao_tipo":
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos_ia)

        revisao = clientes[telefone].get("revisao") or normalizar_revisao_para_fluxo(texto)

        if revisao not in ["1", "2", "3", "4", "5"]:
            enviar_mensagem(telefone, "⚠️ Opção inválida. Digite de 1 a 5.")
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["revisao"] = revisao
        enviar_proxima_etapa_revisao(telefone)
        return jsonify({"status": "ok"}), 200


    if etapa == "revisao_dia":
        aplicar_dados_ia_no_cliente(telefone, dados_extraidos_ia)

        dia = clientes[telefone].get("dia")

        if not dia:
            dia = texto

        if dia not in ["1", "2", "3", "4", "5", "6"]:
            enviar_mensagem(telefone, "⚠️ Dia inválido. Digite 1 a 6.")
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
                "⚠️ Data inválida.\n\nDigite novamente (dd/mm/aaaa)"
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["data"] = data_digitada

        revisao = clientes[telefone]["revisao"]
        dia = clientes[telefone]["dia"]

        horarios = horarios_por_revisao(revisao, dia)

        clientes[telefone]["horarios_disponiveis"] = horarios
        clientes[telefone]["etapa"] = "revisao_horario"

        enviar_mensagem(
            telefone,
            montar_mensagem_horarios(horarios)
        )

        return jsonify({"status": "ok"}), 200


    if etapa == "revisao_horario":

        horarios = clientes[telefone]["horarios_disponiveis"]

        try:
            idx = int(texto) - 1
            horario = horarios[idx]
        except:
            enviar_mensagem(telefone, "⚠️ Escolha um horário válido.")
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["horario"] = horario
        clientes[telefone]["etapa"] = "revisao_venda"

        enviar_mensagem(
            telefone,
            montar_mensagem_venda_adicional(telefone)
        )

        return jsonify({"status": "ok"}), 200


    if etapa == "revisao_venda":

        if texto == "2":
            clientes[telefone]["venda_adicional"] = ""
        else:
            clientes[telefone]["venda_adicional"] = texto

        dados = clientes[telefone]

        protocolo = salvar_agendamento(
            telefone,
            dados
        )

        atendimento = Atendimento(
            telefone=telefone,
            nome=dados["nome"],
            setor="Revisão",
            modelo=dados["modelo"],
            ano=dados["ano"],
            revisao=dados["revisao"],
            cpf=dados["cpf"],
            dia_semana=nome_dia(dados["dia"]),
            data_agendada=dados["data"],
            horario=dados["horario"],
            itens=dados["venda_adicional"],
            origem="Bot",
            status="Agendado",
            etapa="revisao_finalizada",
            concluido=True,
            ultima_interacao=agora_datetime(),
            data=agora_datetime()
        )

        db = SessionLocal()
        db.add(atendimento)
        db.commit()
        db.close()

        enviar_mensagem(
            telefone,
            "✅ *Agendamento Confirmado*\n\n"
            f"👤 {dados['nome']}\n"
            f"🏍️ {dados['modelo']}\n"
            f"📅 {dados['data']}\n"
            f"⏰ {dados['horario']}\n"
            f"📌 Protocolo: {protocolo}\n\n"
            "Equipe Motoshow Yamaha"
        )

        resetar_cliente(telefone)

        return jsonify({"status": "ok"}), 200


    # ==========================================
    # PEÇAS / ACESSÓRIOS / GARANTIA
    # ==========================================
    if etapa == "pecas":
        enviar_mensagem(
            telefone,
            "✅ Solicitação de peças registrada.\nNossa equipe dará continuidade."
        )
        resetar_cliente(telefone)
        return jsonify({"status": "ok"}), 200


    if etapa == "acessorios":
        enviar_mensagem(
            telefone,
            "✅ Solicitação registrada.\nNossa equipe dará continuidade."
        )
        resetar_cliente(telefone)
        return jsonify({"status": "ok"}), 200


    if etapa == "garantia":
        enviar_mensagem(
            telefone,
            "✅ Solicitação registrada.\nNossa equipe dará continuidade."
        )
        resetar_cliente(telefone)
        return jsonify({"status": "ok"}), 200


    if etapa == "atacado":
        enviar_pdf(
            telefone,
            "catalogo-atacado.pdf",
            "📄 Catálogo Atacado"
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