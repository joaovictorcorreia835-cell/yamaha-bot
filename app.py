from flask import Flask, request, jsonify, send_from_directory, render_template
import requests
import os
import time
import re
import threading
from datetime import datetime, timedelta
from collections import Counter, deque

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from database import criar_banco, SessionLocal, Atendimento
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

# FOLLOW-UP
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
# UTILITÁRIOS DE ITENS ADICIONAIS
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

    item = re.sub(r"\s+", " ", item).strip()
    return item.upper()


def extrair_lista_itens_adicionais(valor):
    if valor is None:
        return []

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

        if filtro == "hoje":
            query = query.filter(
                Atendimento.data >= datetime.combine(hoje, datetime.min.time())
            )
        elif filtro == "semana":
            query = query.filter(
                Atendimento.data >= datetime.combine(inicio_semana, datetime.min.time())
            )
        elif filtro == "mes":
            query = query.filter(
                Atendimento.data >= datetime.combine(inicio_mes, datetime.min.time())
            )
        elif filtro == "total":
            pass
        else:
            filtro = "hoje"
            query = query.filter(
                Atendimento.data >= datetime.combine(hoje, datetime.min.time())
            )

        total = query.count()
        revisao = query.filter(Atendimento.setor == "Revisão").count()
        agendados = query.filter(Atendimento.status == "Agendado").count()

        primeira = query.filter(Atendimento.revisao == "1").count()
        segunda = query.filter(Atendimento.revisao == "2").count()
        terceira = query.filter(Atendimento.revisao == "3").count()
        quarta = query.filter(Atendimento.revisao == "4").count()
        quinta = query.filter(Atendimento.revisao == "5").count()

        contador_itens = Counter()
        registros_itens = query.with_entities(Atendimento.itens).all()

        for item in registros_itens:
            valor = item[0] if isinstance(item, tuple) else item
            lista_itens = extrair_lista_itens_adicionais(valor)

            for item_limpo in lista_itens:
                contador_itens[item_limpo] += 1

        ranking_itens = contador_itens.most_common(20)
        total_itens_vendidos = sum(contador_itens.values())

        return render_template(
            "dashboard.html",
            total=total,
            revisao=revisao,
            agendados=agendados,
            primeira=primeira,
            segunda=segunda,
            terceira=terceira,
            quarta=quarta,
            quinta=quinta,
            total_itens_vendidos=total_itens_vendidos,
            ranking_itens=ranking_itens,
            filtro_ativo=filtro
        )

    except Exception as e:
        log_erro("Dashboard erro:", e)
        return "Erro dashboard", 500

    finally:
        db.close()


# ==========================================
# PDFS
# ==========================================
@app.route("/pdf/<path:arquivo>")
def servir_pdf(arquivo):
    pasta_pdfs = os.path.join(app.root_path, "static", "pdfs")
    return send_from_directory(pasta_pdfs, arquivo)


# ==========================================
# UTILITÁRIOS
# ==========================================
def limpar_texto(texto):
    return str(texto or "").strip()


def normalizar_texto(texto):
    return limpar_texto(texto).lower()


def telefone_eh_grupo(telefone):
    telefone = str(telefone or "")
    return "@g.us" in telefone


def agora():
    return time.time()


def agora_datetime():
    return datetime.now()


def formatar_data_hora(dt=None):
    dt = dt or datetime.now()
    return dt.strftime("%d/%m/%Y %H:%M")


def limpar_telefone(telefone):
    return re.sub(r"\D", "", str(telefone or ""))


def limpar_opcao(texto):
    return (
        str(texto or "")
        .replace("️⃣", "")
        .replace("\u200e", "")
        .replace("\u200f", "")
        .strip()
    )


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
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y",
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
    dt = parse_data_hora(valor)
    return dt is not None


def formatar_valor_brl(valor):
    try:
        if isinstance(valor, (int, float)):
            valor_float = float(valor)
        else:
            valor_texto = str(valor).replace("R$", "").strip()

            if "," in valor_texto:
                valor_texto = valor_texto.replace(".", "").replace(",", ".")
            else:
                valor_texto = valor_texto.strip()

            valor_float = float(valor_texto)

        return f"R$ {valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {valor}"


def atualizar_interacao(telefone):
    if telefone in clientes:
        clientes[telefone]["ultima_interacao"] = agora()


def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = {
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


def resetar_cliente(telefone):
    clientes[telefone] = {
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


def buscar_valor_revisao(modelo, revisao=None, km=None, meses=None):
    try:
        df = pd.read_excel("valores_revisao.xlsx")

        df["MODELO"] = df["MODELO"].astype(str).str.upper().str.strip()
        modelo = str(modelo).upper().strip()

        df_modelo = df[df["MODELO"].str.contains(modelo, na=False)]

        if revisao is not None:
            resultado = df_modelo[df_modelo["REVISAO"] == int(revisao)]
        elif km is not None:
            resultado = df_modelo[df_modelo["KM"] == int(km)]
        elif meses is not None:
            resultado = df_modelo[df_modelo["MESES"] == int(meses)]
        else:
            return None

        if not resultado.empty:
            valor = resultado.iloc[0]["VALOR"]
            revisao_encontrada = resultado.iloc[0]["REVISAO"]
            km_encontrado = resultado.iloc[0]["KM"]
            meses_encontrado = resultado.iloc[0]["MESES"]
            return {
                "valor": valor,
                "revisao": revisao_encontrada,
                "km": km_encontrado,
                "meses": meses_encontrado
            }

        return None

    except Exception as e:
        log_erro("Erro ao buscar valor da revisão:", e)
        return None


def extrair_modelo_do_texto(texto):
    try:
        df = pd.read_excel("valores_revisao.xlsx")
        modelos = df["MODELO"].dropna().astype(str).str.upper().str.strip().unique()

        texto_upper = str(texto or "").upper()

        for modelo in modelos:
            if modelo in texto_upper:
                return modelo

        return None

    except Exception as e:
        log_erro("Erro ao extrair modelo do texto:", e)
        return None


def extrair_revisao_km_ou_meses(texto):
    texto = str(texto or "").lower().strip()

    padrao_revisao = re.search(r"(\d+)\s*(?:ª|a)?\s*revis", texto)
    if padrao_revisao:
        return {"revisao": int(padrao_revisao.group(1)), "km": None, "meses": None}

    padrao_km = re.search(r"(\d{1,3}(?:[.\s]?\d{3})+|\d+)\s*km", texto)
    if padrao_km:
        km = re.sub(r"[^\d]", "", padrao_km.group(1))
        return {"revisao": None, "km": int(km), "meses": None}

    padrao_meses = re.search(r"(\d+)\s*(?:meses|mês|mes)", texto)
    if padrao_meses:
        return {"revisao": None, "km": None, "meses": int(padrao_meses.group(1))}

    return {"revisao": None, "km": None, "meses": None}
# ==========================================
# MENU
# ==========================================
def enviar_menu(telefone):
    mensagem = (
        "Olá 👋\n\n"
        "🏍️ *Pós-Vendas Motoshow Yamaha*\n\n"
        "Escolha uma opção abaixo:\n\n"
        "1️⃣ Agendar Revisão\n"
        "2️⃣ Peças\n"
        "3️⃣ Acessórios\n"
        "4️⃣ Garantia\n"
        "5️⃣ Logista / Atacado\n"
        "6️⃣ Falar com Atendente\n\n"
        "Ou se preferir, pode me escrever em texto livre.\n\n"
        "Equipe Motoshow Yamaha"
    )
    enviar_mensagem(telefone, mensagem)


# ==========================================
# APOIO IA FASE 2
# ==========================================
def normalizar_revisao_para_fluxo(valor):
    valor = str(valor or "").strip()

    if valor in ["1", "2", "3", "4", "5"]:
        return valor

    if valor.isdigit():
        numero = int(valor)

        if numero <= 1:
            return "1"
        if numero == 2:
            return "2"
        if numero == 3:
            return "3"
        if numero == 4:
            return "4"

        return "5"

    return ""


def opcao_dia_por_nome(nome):
    nome = normalizar_texto(nome)

    mapa = {
        "segunda": "1",
        "terca": "2",
        "terça": "2",
        "quarta": "3",
        "quinta": "4",
        "sexta": "5",
        "sabado": "6",
        "sábado": "6",
    }

    return mapa.get(nome, "")


def nome_dia(opcao):
    mapa = {
        "1": "Segunda",
        "2": "Terça",
        "3": "Quarta",
        "4": "Quinta",
        "5": "Sexta",
        "6": "Sábado"
    }

    return mapa.get(str(opcao), "")


# ==========================================
# GERAR HORÁRIOS
# ==========================================
def gerar_horarios_disponiveis(revisao, dia):
    revisao = str(revisao).strip()
    dia = str(dia).strip()

    if dia in ["1", "2", "3", "4", "5"]:
        if revisao in ["1", "2"]:
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

    if dia == "6":
        if revisao in ["1", "2"]:
            return [
                "08:00",
                "09:00",
                "10:00"
            ]

        return []

    return []


def montar_mensagem_horarios(horarios):
    mensagem = "⏰ *Escolha o horário:*\n\n"

    for i, horario in enumerate(horarios, start=1):
        mensagem += f"{i} - {horario}\n"

    mensagem += "\nOu responda com o horário direto. Ex: 08:00"

    return mensagem


# ==========================================
# SUGESTÕES INTELIGENTES
# ==========================================
def sugestoes_contextuais_revisao(telefone):

    dados = clientes.get(telefone, {})

    revisao = str(dados.get("revisao", "")).strip()
    modelo = str(dados.get("modelo", "")).upper().strip()

    sugestoes = []

    if revisao == "1":
        sugestoes.extend([
            "SLIDER",
            "SUPORTE CELULAR"
        ])

    if revisao == "2":
        sugestoes.extend([
            "FILTRO DE AR",
            "PASTILHA DE FREIO",
            "SUPORTE CELULAR"
        ])

    if revisao in ["3", "4", "5"]:
        sugestoes.extend([
            "FILTRO DE AR",
            "PASTILHA DE FREIO",
            "VELA"
        ])

    # Scooters
    if any(x in modelo for x in ["FLUO", "NEO", "NMAX", "AEROX"]):
        sugestoes.extend([
            "BAU",
            "SUPORTE CELULAR"
        ])

    # Street
    if any(x in modelo for x in [
        "FAZER",
        "FZ15",
        "MT03",
        "MT07",
        "R15",
        "R3"
    ]):
        sugestoes.extend([
            "SLIDER",
            "SUPORTE CELULAR"
        ])

    # Off-road
    if any(x in modelo for x in [
        "LANDER",
        "CROSSER",
        "TENERE"
    ]):
        sugestoes.extend([
            "PROTETOR MOTOR",
            "SUPORTE CELULAR"
        ])

    finais = []

    for item in sugestoes:
        item = limpar_item_adicional(item)

        if item and item not in finais:
            finais.append(item)

    return finais[:4]


# ==========================================
# VENDA ADICIONAL
# ==========================================
def montar_mensagem_venda_adicional(telefone):

    sugestoes = sugestoes_contextuais_revisao(telefone)

    if sugestoes:

        texto_sugestoes = "\n".join(
            [f"• {item}" for item in sugestoes]
        )

        return (
            "🛠️ *Deseja adicionar algum item ao atendimento?*\n\n"
            "📌 Sugestões:\n"
            f"{texto_sugestoes}\n\n"
            "1 - Sim\n"
            "2 - Não\n\n"
            "Ou escreva o item direto."
        )

    return (
        "🛠️ Deseja adicionar peças ou acessórios?\n\n"
        "1 - Sim\n"
        "2 - Não\n\n"
        "Ou escreva o item direto."
    )


# ==========================================
# IA — PREENCHER DADOS
# ==========================================
def preencher_dados_ia_no_cliente(telefone, dados):

    if telefone not in clientes:
        iniciar_cliente(telefone)

    modelo = limpar_texto(dados.get("modelo"))
    nome = limpar_texto(dados.get("nome"))
    cpf = limpar_texto(dados.get("cpf"))
    ano = limpar_texto(dados.get("ano"))
    revisao = normalizar_revisao_para_fluxo(
        dados.get("revisao")
    )

    horario = limpar_texto(
        dados.get("horario")
    )

    data_agendamento = limpar_texto(
        dados.get("data")
    )

    item_adicional = formatar_itens_adicionais_para_salvar(
        dados.get("item_adicional")
    )

    dia_nome = limpar_texto(
        dados.get("dia")
    )

    dia_opcao = opcao_dia_por_nome(
        dia_nome
    )

    if modelo:
        clientes[telefone]["modelo"] = modelo

    if nome:
        clientes[telefone]["nome"] = nome

    if cpf:
        clientes[telefone]["cpf"] = cpf

    if ano:
        clientes[telefone]["ano"] = ano

    if revisao:
        clientes[telefone]["revisao"] = revisao

    if dia_opcao:

        clientes[telefone]["dia"] = dia_opcao
        clientes[telefone]["dia_texto"] = nome_dia(dia_opcao)

        if clientes[telefone].get("revisao"):

            horarios = gerar_horarios_disponiveis(
                clientes[telefone]["revisao"],
                dia_opcao
            )

            clientes[telefone]["horarios_disponiveis"] = horarios

    if data_agendamento and data_texto_valida(data_agendamento):
        clientes[telefone]["data"] = data_agendamento

    if horario:

        if clientes[telefone].get("horarios_disponiveis"):

            if horario in clientes[telefone]["horarios_disponiveis"]:
                clientes[telefone]["horario"] = horario

        else:
            clientes[telefone]["horario"] = horario

    if item_adicional:

        clientes[telefone]["itens"] = item_adicional
        clientes[telefone]["venda_adicional"] = "Sim"
# ==========================================
# SALVAR ATENDIMENTO COM SEGURANÇA
# ==========================================
def salvar_atendimento_seguro(dados):
    db = SessionLocal()

    try:
        atendimento = Atendimento()

        for campo, valor in dados.items():
            if hasattr(atendimento, campo):
                setattr(atendimento, campo, valor)

        db.add(atendimento)
        db.commit()

        log_info("Atendimento salvo com sucesso.")
        return True

    except Exception as e:
        db.rollback()
        log_erro("Erro salvar atendimento:", e)
        return False

    finally:
        db.close()

# ==========================================
# WORKER FOLLOWUP
# ==========================================
def worker_followup():
    log_info("Worker de follow-up iniciado.")

    while True:
        try:
            processar_followups()
        except Exception as e:
            log_erro("Erro no worker follow-up:", e)

        time.sleep(INTERVALO_WORKER_FOLLOWUP)


def iniciar_worker_followup():
    global worker_followup_iniciado

    if worker_followup_iniciado:
        return

    worker_followup_iniciado = True

    thread = threading.Thread(
        target=worker_followup,
        daemon=True
    )

    thread.start()

    log_info("Worker follow-up iniciado")
# ==========================================
# IGNORAR EVENTOS DO PRÓPRIO BOT
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

        sender = str(
            data.get("sender")
            or data.get("from")
            or payload.get("sender")
            or payload.get("from")
            or ""
        ).lower()

        if sender in ["api", "system", "bot"]:
            return True

        texto_evento = str(
            data.get("event")
            or payload.get("event")
            or ""
        ).lower()

        if texto_evento in ["sent", "message_sent", "outbound_message"]:
            return True

        return False

    except Exception as e:
        log_erro("Erro validar evento bot:", e)
        return False
# ==========================================
# WEBHOOK
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Webhook ativo"}), 200

    processar_inatividade()

    payload = request.get_json(silent=True) or {}
    log_info("PAYLOAD RECEBIDO:", payload)

    if evento_eh_do_proprio_bot(payload):
        return jsonify({"status": "ignorado"}), 200

    telefone = extrair_telefone(payload)
    texto = limpar_texto(extrair_texto(payload))
    texto_normalizado = normalizar_texto(texto)
    message_id = extrair_message_id(payload)

    if not telefone:
        return jsonify({"status": "ignorado"}), 200

    if telefone_eh_grupo(telefone):
        return jsonify({"status": "grupo"}), 200

    if mensagem_ja_processada(message_id):
        return jsonify({"status": "duplicada"}), 200

    registrar_mensagem_processada(message_id)

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)
    atualizar_retorno_na_planilha(telefone, texto)

    if not texto:
        return jsonify({"status": "vazio"}), 200


# ==========================================
# SAIR DO HUMANO
# ==========================================
    if clientes[telefone].get("atendimento_humano"):

        if texto_normalizado in [
            "menu","oi","ola","olá",
            "voltar","inicio","início"
        ]:
            resetar_cliente(telefone)
            enviar_menu(telefone)
            return jsonify({"status":"menu"}),200

        return jsonify({"status":"humano"}),200


# ==========================================
# MENU AUTOMATICO
# ==========================================
    if texto_normalizado in [
        "menu","oi","ola","olá",
        "bom dia","boa tarde","boa noite"
    ]:

        resetar_cliente(telefone)
        enviar_menu(telefone)
        return jsonify({"status":"menu"}),200


    etapa = clientes[telefone]["etapa"]


# ==========================================
# IA MENU
# ==========================================
    if etapa == "menu" and texto not in ["1","2","3","4","5","6"]:

        if tratar_intencao_ia(telefone, texto):
            return jsonify({"status":"ia"}),200


# ==========================================
# MENU PRINCIPAL
# ==========================================
    if etapa == "menu":

        opcao = limpar_opcao(texto)

        if opcao == "1":

            clientes[telefone]["etapa"] = "revisao_modelo"

            enviar_mensagem(
                telefone,
                "🔧 *Agendamento de Revisão*\n\n"
                "Informe o modelo da moto:"
            )

            return jsonify({"fluxo":"revisao"}),200


        elif opcao == "2":

            clientes[telefone]["etapa"] = "pecas_descricao"

            enviar_mensagem(
                telefone,
                "🔩 Informe a peça desejada"
            )

            return jsonify({"fluxo":"pecas"}),200


        elif opcao == "3":

            clientes[telefone]["etapa"] = "acessorios_descricao"

            enviar_mensagem(
                telefone,
                "🛵 Informe o acessório desejado"
            )

            return jsonify({"fluxo":"acessorios"}),200


        elif opcao == "4":

            clientes[telefone]["etapa"] = "garantia_descricao"

            enviar_mensagem(
                telefone,
                "🛡️ Descreva sua solicitação de garantia"
            )

            return jsonify({"fluxo":"garantia"}),200


        elif opcao == "5":

            clientes[telefone]["etapa"] = "submenu_atacado"

            enviar_mensagem(
                telefone,
                "📦 Logista / Atacado\n\n"
                "1 - Cotação\n"
                "2 - Cadastro\n"
                "3 - Catálogo\n"
                "4 - Consultor"
            )

            return jsonify({"fluxo":"atacado"}),200


        elif opcao == "6":

            ativar_atendimento_humano(telefone)
            return jsonify({"fluxo":"humano"}),200


        else:

            enviar_menu(telefone)
            return jsonify({"fluxo":"menu"}),200



# ==========================================
# SUBMENU ATACADO
# ==========================================
    elif etapa == "submenu_atacado":

        opcao = limpar_opcao(texto)

        if opcao == "1":

            ativar_atendimento_humano(telefone)

            enviar_mensagem(
                telefone,
                "Envie empresa, CNPJ e peças"
            )

            return jsonify({"status":"ok"}),200


        elif opcao == "2":

            ativar_atendimento_humano(telefone)

            enviar_mensagem(
                telefone,
                "Envie dados para cadastro"
            )

            return jsonify({"status":"ok"}),200


        elif opcao == "3":

            enviar_documento_pdf(
                telefone,
                "catalogo-atacado.pdf"
            )

            resetar_cliente(telefone)

            return jsonify({"status":"ok"}),200


        elif opcao == "4":

            ativar_atendimento_humano(telefone)
            return jsonify({"status":"ok"}),200
        else:
            enviar_mensagem(
                telefone,
                "❌ Opção inválida.\n\n"
                "Digite:\n"
                "1 - Cotação\n"
                "2 - Cadastro\n"
                "3 - Catálogo\n"
                "4 - Consultor"
            )
            return jsonify({"status": "ok"}), 200


# ==========================================
# FLUXO PEÇAS
# ==========================================
    elif etapa == "pecas_descricao":

        salvar_atendimento_seguro({
            "telefone": telefone,
            "nome": clientes[telefone].get("nome", ""),
            "setor": "Peças",
            "modelo": clientes[telefone].get("modelo", ""),
            "origem": "Bot",
            "status": "Solicitação recebida",
            "itens": texto,
            "atendimento_humano": False,
            "concluido": False,
            "data": agora_datetime()
        })

        ativar_atendimento_humano(telefone)

        enviar_mensagem(
            telefone,
            "✅ *Solicitação de peças registrada.*\n\n"
            "Nossa equipe vai seguir com seu atendimento por aqui."
        )

        return jsonify({"status": "ok"}), 200


# ==========================================
# FLUXO ACESSÓRIOS
# ==========================================
    elif etapa == "acessorios_descricao":

        salvar_atendimento_seguro({
            "telefone": telefone,
            "nome": clientes[telefone].get("nome", ""),
            "setor": "Acessórios",
            "modelo": clientes[telefone].get("modelo", ""),
            "origem": "Bot",
            "status": "Solicitação recebida",
            "itens": texto,
            "atendimento_humano": False,
            "concluido": False,
            "data": agora_datetime()
        })

        ativar_atendimento_humano(telefone)

        enviar_mensagem(
            telefone,
            "✅ *Solicitação de acessórios registrada.*\n\n"
            "Nossa equipe vai seguir com você por aqui."
        )

        return jsonify({"status": "ok"}), 200


# ==========================================
# FLUXO GARANTIA
# ==========================================
    elif etapa == "garantia_descricao":

        salvar_atendimento_seguro({
            "telefone": telefone,
            "nome": clientes[telefone].get("nome", ""),
            "setor": "Garantia",
            "modelo": clientes[telefone].get("modelo", ""),
            "origem": "Bot",
            "status": "Solicitação recebida",
            "itens": texto,
            "atendimento_humano": False,
            "concluido": False,
            "data": agora_datetime()
        })

        ativar_atendimento_humano(telefone)

        enviar_mensagem(
            telefone,
            "✅ *Solicitação de garantia registrada.*\n\n"
            "Nossa equipe especializada vai continuar seu atendimento."
        )

        return jsonify({"status": "ok"}), 200


# ==========================================
# FLUXO REVISÃO
# ==========================================
    elif etapa == "revisao_modelo":
        clientes[telefone]["modelo"] = texto
        clientes[telefone]["etapa"] = "revisao_nome"

        enviar_mensagem(
            telefone,
            "👤 Informe seu *nome completo*:"
        )
        return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_nome":
        clientes[telefone]["nome"] = texto
        clientes[telefone]["etapa"] = "revisao_cpf"

        enviar_mensagem(
            telefone,
            "📄 Informe o *CPF do proprietário*:"
        )
        return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_cpf":
        clientes[telefone]["cpf"] = texto
        clientes[telefone]["etapa"] = "revisao_ano"

        enviar_mensagem(
            telefone,
            "📅 Informe o *ano da moto*:"
        )
        return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_ano":
        clientes[telefone]["ano"] = texto
        clientes[telefone]["etapa"] = "revisao_tipo"

        enviar_mensagem(
            telefone,
            "🔧 *Qual revisão deseja agendar?*\n\n"
            "1 - 1ª revisão\n"
            "2 - 2ª revisão\n"
            "3 - 3ª revisão\n"
            "4 - 4ª revisão\n"
            "5 - 5ª ou acima"
        )
        return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_tipo":
        opcao = limpar_opcao(texto)

        if opcao not in ["1", "2", "3", "4", "5"]:
            enviar_mensagem(
                telefone,
                "❌ Opção inválida.\n\n"
                "Digite:\n"
                "1 - 1ª\n"
                "2 - 2ª\n"
                "3 - 3ª\n"
                "4 - 4ª\n"
                "5 - 5ª+"
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["revisao"] = opcao
        clientes[telefone]["etapa"] = "revisao_dia"

        enviar_mensagem(
            telefone,
            "📅 *Escolha o dia da semana:*\n\n"
            "1 - Segunda\n"
            "2 - Terça\n"
            "3 - Quarta\n"
            "4 - Quinta\n"
            "5 - Sexta\n"
            "6 - Sábado"
        )
        return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_dia":
        opcao = limpar_opcao(texto)

        if opcao not in ["1", "2", "3", "4", "5", "6"]:
            enviar_mensagem(
                telefone,
                "❌ Dia inválido.\n\n"
                "Digite um número de 1 a 6."
            )
            return jsonify({"status": "ok"}), 200

        horarios = gerar_horarios_disponiveis(
            clientes[telefone]["revisao"],
            opcao
        )

        if not horarios:
            enviar_mensagem(
                telefone,
                "⚠️ Para essa revisão não há atendimento no dia selecionado.\n\n"
                "Escolha outro dia:\n"
                "1 - Segunda\n"
                "2 - Terça\n"
                "3 - Quarta\n"
                "4 - Quinta\n"
                "5 - Sexta\n"
                "6 - Sábado"
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["dia"] = opcao
        clientes[telefone]["dia_texto"] = nome_dia(opcao)
        clientes[telefone]["horarios_disponiveis"] = horarios
        clientes[telefone]["etapa"] = "revisao_data"

        enviar_mensagem(
            telefone,
            "📆 Informe a *data desejada* do agendamento:\n"
            "Exemplo: 15/04/2026"
        )
        return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_data":
        if not data_texto_valida(texto):
            enviar_mensagem(
                telefone,
                "📆 Não consegui validar a data.\n\n"
                "Me envie no formato *dd/mm/aaaa*.\n"
                "Exemplo: 15/04/2026"
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["data"] = texto
        clientes[telefone]["etapa"] = "revisao_horario"

        enviar_mensagem(
            telefone,
            montar_mensagem_horarios(
                clientes[telefone].get("horarios_disponiveis", ["08:00"])
            )
        )
        return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_horario":
        horarios = clientes[telefone].get("horarios_disponiveis", [])

        if not horarios:
            clientes[telefone]["etapa"] = "revisao_dia"
            enviar_mensagem(
                telefone,
                "⚠️ Não encontrei horários disponíveis. Vamos escolher o dia novamente."
            )
            return jsonify({"status": "ok"}), 200

        if not tentar_aproveitar_texto_no_horario(telefone, texto):
            enviar_mensagem(
                telefone,
                montar_mensagem_horarios(horarios)
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["etapa"] = "revisao_venda_opcao"

        enviar_mensagem(
            telefone,
            montar_mensagem_venda_adicional(telefone)
        )
        return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_venda_opcao":
        opcao = limpar_opcao(texto)
        itens_formatados = formatar_itens_adicionais_para_salvar(texto)

        if opcao == "1":
            clientes[telefone]["etapa"] = "revisao_venda_adicional"

            enviar_mensagem(
                telefone,
                "🛠️ *Peça ou acessório adicional*\n\n"
                "Informe qual item deseja adicionar.\n\n"
                "Exemplos:\n"
                "• Filtro de ar\n"
                "• Pastilha de freio\n"
                "• Baú\n"
                "• Slider\n"
                "• Suporte celular\n"
                "• Protetor motor"
            )
            return jsonify({"status": "ok"}), 200

        elif opcao == "2":
            clientes[telefone]["itens"] = ""
            clientes[telefone]["venda_adicional"] = "Não"
            clientes[telefone]["etapa"] = "revisao_confirmar"

            enviar_pergunta_etapa_revisao(telefone, "revisao_confirmar")
            return jsonify({"status": "ok"}), 200

        elif itens_formatados:
            clientes[telefone]["itens"] = itens_formatados
            clientes[telefone]["venda_adicional"] = "Sim"
            clientes[telefone]["etapa"] = "revisao_confirmar"

            enviar_pergunta_etapa_revisao(telefone, "revisao_confirmar")
            return jsonify({"status": "ok"}), 200

        else:
            enviar_mensagem(
                telefone,
                "❌ Não entendi sua resposta.\n\n"
                "Você pode responder:\n"
                "1 - Sim\n"
                "2 - Não\n"
                "ou escrever o item direto.\n\n"
                "Exemplo: *pastilha de freio*"
            )
            return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_venda_adicional":
        itens_formatados = formatar_itens_adicionais_para_salvar(texto)

        clientes[telefone]["itens"] = itens_formatados
        clientes[telefone]["venda_adicional"] = "Sim" if itens_formatados else "Não"
        clientes[telefone]["etapa"] = "revisao_confirmar"

        enviar_pergunta_etapa_revisao(telefone, "revisao_confirmar")
        return jsonify({"status": "ok"}), 200


    elif etapa == "revisao_confirmar":
        opcao = limpar_opcao(texto)

        if opcao == "2":
            resetar_cliente(telefone)

            enviar_mensagem(
                telefone,
                "❌ Agendamento cancelado.\n\n"
                "Envie *menu* para iniciar novamente."
            )
            return jsonify({"status": "ok"}), 200

        if opcao != "1":
            enviar_mensagem(
                telefone,
                "Digite:\n"
                "1 - Confirmar\n"
                "2 - Cancelar"
            )
            return jsonify({"status": "ok"}), 200

        salvar_atendimento_seguro({
            "telefone": telefone,
            "nome": clientes[telefone]["nome"],
            "setor": "Revisão",
            "modelo": clientes[telefone]["modelo"],
            "ano": clientes[telefone]["ano"],
            "revisao": clientes[telefone]["revisao"],
            "cpf": clientes[telefone]["cpf"],
            "dia_semana": clientes[telefone]["dia_texto"],
            "data_agendada": clientes[telefone]["data"],
            "horario": clientes[telefone]["horario"],
            "itens": clientes[telefone].get("itens", ""),
            "venda_adicional": clientes[telefone].get("venda_adicional", "Não"),
            "origem": "Bot",
            "status": "Agendado",
            "etapa": "revisao_confirmada",
            "atendimento_humano": False,
            "concluido": True,
            "ultima_interacao": agora_datetime(),
            "data": agora_datetime()
        })

        itens_texto = clientes[telefone]["itens"] if clientes[telefone]["itens"] else "Nenhum"

        enviar_mensagem(
            telefone,
            "✅ *Revisão agendada com sucesso!*\n\n"
            f"👤 {clientes[telefone]['nome']}\n"
            f"🏍️ {clientes[telefone]['modelo']}\n"
            f"📄 CPF: {clientes[telefone]['cpf']}\n"
            f"📅 {clientes[telefone]['data']}\n"
            f"📍 {clientes[telefone]['dia_texto']}\n"
            f"⏰ {clientes[telefone]['horario']}\n"
            f"🛒 Adicionais: {itens_texto}\n\n"
            "Agradecemos o contato.\n"
            "Equipe Motoshow Yamaha"
        )

        resetar_cliente(telefone)
        return jsonify({"status": "ok"}), 200

    return jsonify({"status": "ok"}), 200


# ==========================================
# INICIAR WORKER
# ==========================================
iniciar_worker_followup()


# ==========================================
# EXECUÇÃO
# ==========================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)