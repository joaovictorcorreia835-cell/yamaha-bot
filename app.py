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
# PDFS
# ==========================================
@app.route("/pdf/<path:arquivo>")
def servir_pdf(arquivo):
    pasta_pdfs = os.path.join(app.root_path, "static", "pdfs")
    return send_from_directory(pasta_pdfs, arquivo)


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
# UTILITÁRIOS GERAIS
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
    telefone = str(telefone or "").strip()
    telefone = telefone.replace("@c.us", "").replace("@s.whatsapp.net", "").replace("@g.us", "")
    return re.sub(r"\D", "", telefone)


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
            valor_float = float(valor_texto)

        return f"R$ {valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {valor}"


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


def atualizar_interacao(telefone):
    if telefone in clientes:
        clientes[telefone]["ultima_interacao"] = agora()


def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = estado_padrao_cliente()


def resetar_cliente(telefone):
    clientes[telefone] = estado_padrao_cliente()


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
# FOLLOW-UP PLANILHA
# ==========================================
def garantir_colunas_followup(df):
    colunas_necessarias = [
        "TELEFONE",
        "STATUS_ENVIO",
        "STATUS_RETORNO",
        "DATA_RETORNO",
        "ULTIMA_INTERACAO",
        "FOLLOWUP_1",
        "FOLLOWUP_2",
        "OBS",
        "LINK_ORIGEM",
        "INTENCAO_IA",
        "PROXIMA_ACAO",
        "NIVEL_INTERESSE",
        "DATA_DISPARO",
    ]

    for coluna in colunas_necessarias:
        if coluna not in df.columns:
            df[coluna] = ""

    return df


def carregar_planilha_followup():
    if not os.path.exists(ARQUIVO_FOLLOWUP):
        log_info("Planilha de follow-up não encontrada:", ARQUIVO_FOLLOWUP)
        return None

    try:
        df = pd.read_excel(ARQUIVO_FOLLOWUP)
        df = garantir_colunas_followup(df)
        return df
    except Exception as e:
        log_erro("Erro ao carregar planilha de follow-up:", e)
        return None


def salvar_planilha_followup(df):
    try:
        df.to_excel(ARQUIVO_FOLLOWUP, index=False)
        return True
    except Exception as e:
        log_erro("Erro ao salvar planilha de follow-up:", e)
        return False


def obter_data_base_followup(row):
    data_disparo = parse_data_hora(row.get("DATA_DISPARO"))
    if data_disparo:
        return data_disparo

    ultima_interacao = parse_data_hora(row.get("ULTIMA_INTERACAO"))
    if ultima_interacao:
        return ultima_interacao

    return None


def append_obs(obs_atual, nova_obs):
    obs_atual = str(obs_atual or "").strip()
    nova_obs = str(nova_obs or "").strip()

    if not obs_atual:
        return nova_obs

    return f"{obs_atual} | {nova_obs}"


def atualizar_retorno_na_planilha(telefone, texto_recebido=""):
    telefone_limpo = limpar_telefone(telefone)
    if not telefone_limpo:
        return

    with followup_lock:
        df = carregar_planilha_followup()
        if df is None or df.empty or "TELEFONE" not in df.columns:
            return

        alterou = False

        for idx, row in df.iterrows():
            tel_planilha = limpar_telefone(row.get("TELEFONE"))
            if not tel_planilha:
                continue

            if tel_planilha.endswith(telefone_limpo[-11:]) or telefone_limpo.endswith(tel_planilha[-11:]):
                status_retorno = normalizar_texto(row.get("STATUS_RETORNO"))
                if status_retorno != "respondido":
                    df.at[idx, "STATUS_RETORNO"] = "RESPONDIDO"
                    df.at[idx, "DATA_RETORNO"] = formatar_data_hora()
                    df.at[idx, "ULTIMA_INTERACAO"] = formatar_data_hora()
                    df.at[idx, "PROXIMA_ACAO"] = "ANALISAR_RETORNO"
                    df.at[idx, "OBS"] = append_obs(
                        row.get("OBS"),
                        f"Cliente respondeu em {formatar_data_hora()}"
                    )
                    alterou = True

        if alterou:
            salvar_planilha_followup(df)
            log_info("Retorno atualizado na planilha para:", telefone)


def processar_followups():
    with followup_lock:
        df = carregar_planilha_followup()
        if df is None or df.empty:
            return

        agora_dt = datetime.now()
        alterou = False

        for idx, row in df.iterrows():
            try:
                telefone = limpar_telefone(row.get("TELEFONE"))
                status_envio = normalizar_texto(row.get("STATUS_ENVIO"))
                status_retorno = normalizar_texto(row.get("STATUS_RETORNO"))
                followup_1 = limpar_texto(row.get("FOLLOWUP_1"))
                followup_2 = limpar_texto(row.get("FOLLOWUP_2"))

                if not telefone:
                    continue

                if status_envio != "enviado":
                    continue

                if status_retorno == "respondido":
                    continue

                data_base = obter_data_base_followup(row)
                if not data_base:
                    continue

                horas_passadas = (agora_dt - data_base).total_seconds() / 3600
                dias_passados = (agora_dt - data_base).days

                if not followup_1 and horas_passadas >= FOLLOWUP_1_HORAS:
                    ok = enviar_mensagem(telefone, MENSAGEM_FOLLOWUP_1)
                    if ok:
                        df.at[idx, "FOLLOWUP_1"] = formatar_data_hora()
                        df.at[idx, "ULTIMA_INTERACAO"] = formatar_data_hora()
                        df.at[idx, "PROXIMA_ACAO"] = "AGUARDAR_FOLLOWUP_2"
                        df.at[idx, "OBS"] = append_obs(
                            row.get("OBS"),
                            f"FOLLOWUP_1 enviado em {formatar_data_hora()}"
                        )
                        alterou = True
                    continue

                if not followup_2 and dias_passados >= FOLLOWUP_2_DIAS:
                    ok = enviar_mensagem(telefone, MENSAGEM_FOLLOWUP_2)
                    if ok:
                        df.at[idx, "FOLLOWUP_2"] = formatar_data_hora()
                        df.at[idx, "ULTIMA_INTERACAO"] = formatar_data_hora()
                        df.at[idx, "PROXIMA_ACAO"] = "ENCERRAR_SEM_RETORNO"
                        df.at[idx, "OBS"] = append_obs(
                            row.get("OBS"),
                            f"FOLLOWUP_2 enviado em {formatar_data_hora()}"
                        )
                        alterou = True

            except Exception as e:
                log_erro("Erro ao processar linha do follow-up:", e)

        if alterou:
            salvar_planilha_followup(df)


def worker_followup():
    log_info("Worker de follow-up iniciado.")
    while True:
        try:
            processar_followups()
        except Exception as e:
            log_erro("Erro no worker de follow-up:", e)
        time.sleep(INTERVALO_WORKER_FOLLOWUP)


def iniciar_worker_followup():
    global worker_followup_iniciado

    if worker_followup_iniciado:
        return

    worker_followup_iniciado = True
    thread = threading.Thread(target=worker_followup, daemon=True)
    thread.start()
    log_info("Thread de follow-up iniciada com sucesso.")


@app.route("/processar-followups", methods=["GET"])
def rota_processar_followups():
    try:
        processar_followups()
        return jsonify({"status": "ok", "message": "Follow-ups processados"}), 200
    except Exception as e:
        log_erro("Erro na rota de processar follow-ups:", e)
        return jsonify({"status": "erro", "message": str(e)}), 500


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
        log_erro("Erro ao validar evento do próprio bot:", e)
        return False


# ==========================================
# MENSAGENS DUPLICADAS
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
# EXTRAÇÃO
# ==========================================
def extrair_telefone(payload):
    try:
        data = payload.get("data", {}) or {}

        telefone = (
            data.get("phone")
            or data.get("chatId")
            or data.get("from")
            or data.get("sender", {}).get("phone") if isinstance(data.get("sender"), dict) else None
            or payload.get("phone")
            or payload.get("chatId")
            or payload.get("from")
            or payload.get("sender", {}).get("phone") if isinstance(payload.get("sender"), dict) else None
            or ""
        )

        return str(telefone).strip()
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
            data.get("selectedButtonId"),
            data.get("selectedDisplayText"),
            data.get("singleSelectReply", {}).get("selectedRowId") if isinstance(data.get("singleSelectReply"), dict) else None,
            data.get("singleSelectReply", {}).get("title") if isinstance(data.get("singleSelectReply"), dict) else None,

            payload.get("text", {}).get("message") if isinstance(payload.get("text"), dict) else None,
            payload.get("text") if isinstance(payload.get("text"), str) else None,
            payload.get("body"),
            payload.get("message"),
            payload.get("caption"),
            payload.get("extendedTextMessage", {}).get("text") if isinstance(payload.get("extendedTextMessage"), dict) else None,
            payload.get("conversation"),
            payload.get("selectedButtonId"),
            payload.get("selectedDisplayText"),
            payload.get("singleSelectReply", {}).get("selectedRowId") if isinstance(payload.get("singleSelectReply"), dict) else None,
            payload.get("singleSelectReply", {}).get("title") if isinstance(payload.get("singleSelectReply"), dict) else None,
        ]

        for valor in candidatos:
            if valor is not None and str(valor).strip():
                return str(valor).strip()

        return ""
    except Exception as e:
        log_erro("Erro ao extrair texto:", e)
        return ""


# ==========================================
# ENVIO DE MENSAGEM
# ==========================================
def headers_zapi():
    return {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }


def enviar_mensagem(telefone, mensagem):
    payload = {
        "phone": limpar_telefone(telefone),
        "message": mensagem
    }

    try:
        log_info("Enviando mensagem para:", telefone)
        log_info("Payload envio:", payload)

        response = requests.post(
            url_envio,
            json=payload,
            headers=headers_zapi(),
            timeout=30
        )

        log_info("Status envio:", response.status_code)
        log_info("Resposta Z-API:", response.text)

        if 200 <= response.status_code < 300:
            log_info("Mensagem enviada com sucesso:", telefone)
            return True

        log_erro("Falha envio:", response.status_code, response.text)
        return False

    except Exception as e:
        log_erro("Erro envio:", e)
        return False


def enviar_documento_pdf(
    telefone,
    arquivo_pdf,
    nome_exibicao=None,
    legenda="📄 Catálogo Atacado Motoshow Yamaha"
):
    try:
        if not BASE_URL:
            log_erro("BASE_URL não configurada para envio de PDF.")
            return False

        nome_exibicao = nome_exibicao or arquivo_pdf
        link_pdf = f"{BASE_URL}/pdf/{arquivo_pdf}"

        payload = {
            "phone": limpar_telefone(telefone),
            "document": link_pdf,
            "fileName": nome_exibicao,
            "caption": legenda
        }

        log_info("Enviando PDF para:", telefone)
        log_info("Payload PDF:", payload)

        response = requests.post(
            url_documento,
            json=payload,
            headers=headers_zapi(),
            timeout=60
        )

        log_info("Status PDF:", response.status_code)
        log_info("Resposta PDF:", response.text)

        if 200 <= response.status_code < 300:
            return True

        return False

    except Exception as e:
        log_erro("Erro envio PDF:", e)
        return False


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


def gerar_horarios_disponiveis(revisao, dia):
    revisao = str(revisao).strip()
    dia = str(dia).strip()

    if dia in ["1", "2", "3", "4", "5"]:
        if revisao in ["1", "2"]:
            return [
                "08:00", "09:00", "10:00", "11:00",
                "12:00", "13:00", "14:00", "15:00"
            ]
        return ["08:00"]

    if dia == "6":
        if revisao in ["1", "2"]:
            return ["08:00", "09:00", "10:00"]
        return []

    return []


def montar_mensagem_horarios(horarios):
    mensagem = "⏰ *Escolha o horário:*\n\n"
    for i, horario in enumerate(horarios, start=1):
        mensagem += f"{i} - {horario}\n"
    mensagem += "\nSe preferir, você também pode responder com o horário direto. Ex.: 08:00"
    return mensagem


def sugestoes_contextuais_revisao(telefone):
    dados = clientes.get(telefone, {})
    revisao = str(dados.get("revisao", "")).strip()
    modelo = str(dados.get("modelo", "")).upper().strip()

    sugestoes = []

    if revisao == "1":
        sugestoes.extend(["SLIDER", "SUPORTE CELULAR"])

    if revisao == "2":
        sugestoes.extend(["FILTRO DE AR", "PASTILHA DE FREIO", "SUPORTE CELULAR"])

    if revisao in ["3", "4", "5"]:
        sugestoes.extend(["FILTRO DE AR", "PASTILHA DE FREIO", "VELA"])

    if any(x in modelo for x in ["FLUO", "NEO", "NMAX", "AEROX"]):
        sugestoes.extend(["BAU", "SUPORTE CELULAR"])

    if any(x in modelo for x in ["FAZER 250", "FZ15", "MT03", "MT07", "R15", "R3"]):
        sugestoes.extend(["SLIDER", "SUPORTE CELULAR"])

    if any(x in modelo for x in ["LANDER", "CROSSER", "TENERE 700"]):
        sugestoes.extend(["PROTETOR MOTOR", "SUPORTE CELULAR"])

    finais = []
    for item in sugestoes:
        item = limpar_item_adicional(item)
        if item and item not in finais:
            finais.append(item)

    return finais[:4]


def montar_mensagem_venda_adicional(telefone):
    sugestoes = sugestoes_contextuais_revisao(telefone)

    if sugestoes:
        texto_sugestoes = "\n".join([f"• {item}" for item in sugestoes])
        return (
            "🛠️ *Deseja adicionar algum item ao atendimento?*\n\n"
            "📌 Sugestões para esse perfil de revisão:\n"
            f"{texto_sugestoes}\n\n"
            "Você pode responder de 3 formas:\n"
            "1 - Sim\n"
            "2 - Não\n"
            "ou escrever o item direto.\n\n"
            "Exemplo: *filtro de ar e pastilha de freio*"
        )

    return (
        "🛠️ *Deseja adicionar peças ou acessórios?*\n\n"
        "Você pode responder:\n"
        "1 - Sim\n"
        "2 - Não\n"
        "ou escrever o item direto.\n\n"
        "Exemplo: *slider*"
    )


def preencher_dados_ia_no_cliente(telefone, dados):
    if telefone not in clientes:
        iniciar_cliente(telefone)

    modelo = limpar_texto(dados.get("modelo"))
    nome = limpar_texto(dados.get("nome"))
    cpf = limpar_texto(dados.get("cpf"))
    ano = limpar_texto(dados.get("ano"))
    revisao = normalizar_revisao_para_fluxo(dados.get("revisao"))
    horario = limpar_texto(dados.get("horario"))
    data_agendamento = limpar_texto(dados.get("data"))
    item_adicional = formatar_itens_adicionais_para_salvar(dados.get("item_adicional"))
    dia_nome = limpar_texto(dados.get("dia"))
    dia_opcao = opcao_dia_por_nome(dia_nome)

    if modelo:
        clientes[telefone]["modelo"] = modelo

    if nome:
        clientes[telefone]["nome"] = nome

    if cpf:
        clientes[telefone]["cpf"] = cpf

    if ano:
        clientes[telefone]["ano"] = ano

    if revisao:
        clientes[telefone]["revisao"] = str(revisao)

    if dia_opcao:
        clientes[telefone]["dia"] = dia_opcao
        clientes[telefone]["dia_texto"] = nome_dia(dia_opcao)

        if clientes[telefone].get("revisao"):
            horarios = gerar_horarios_disponiveis(clientes[telefone]["revisao"], dia_opcao)
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


def proxima_etapa_revisao(telefone):
    dados = clientes.get(telefone, {})

    if not limpar_texto(dados.get("modelo")):
        return "revisao_modelo"

    if not limpar_texto(dados.get("nome")):
        return "revisao_nome"

    if not limpar_texto(dados.get("cpf")):
        return "revisao_cpf"

    if not limpar_texto(dados.get("ano")):
        return "revisao_ano"

    if not limpar_texto(dados.get("revisao")):
        return "revisao_tipo"

    if not limpar_texto(dados.get("dia")):
        return "revisao_dia"

    if not limpar_texto(dados.get("data")):
        return "revisao_data"

    if not limpar_texto(dados.get("horario")):
        return "revisao_horario"

    if not limpar_texto(dados.get("venda_adicional")):
        return "revisao_venda_opcao"

    return "revisao_confirmar"


def resumo_identificado_revisao(telefone):
    d = clientes.get(telefone, {})
    resumo = []

    if d.get("nome"):
        resumo.append(f"👤 Nome: {d['nome']}")
    if d.get("modelo"):
        resumo.append(f"🏍️ Modelo: {d['modelo']}")
    if d.get("ano"):
        resumo.append(f"📅 Ano: {d['ano']}")
    if d.get("revisao"):
        resumo.append(f"🔧 Revisão: {d['revisao']}ª")
    if d.get("dia_texto"):
        resumo.append(f"📍 Dia: {d['dia_texto']}")
    if d.get("data"):
        resumo.append(f"📆 Data: {d['data']}")
    if d.get("horario"):
        resumo.append(f"⏰ Horário: {d['horario']}")

    return resumo


def enviar_pergunta_etapa_revisao(telefone, etapa_destino):
    if etapa_destino == "revisao_modelo":
        enviar_mensagem(
            telefone,
            "🔧 Perfeito. Para seguir com seu agendamento, me informe o *modelo da moto*."
        )
        return True

    if etapa_destino == "revisao_nome":
        enviar_mensagem(
            telefone,
            "👤 Agora me informe seu *nome completo*."
        )
        return True

    if etapa_destino == "revisao_cpf":
        enviar_mensagem(
            telefone,
            "📄 Agora me informe o *CPF do proprietário*."
        )
        return True

    if etapa_destino == "revisao_ano":
        enviar_mensagem(
            telefone,
            "📅 Agora me informe o *ano da moto*."
        )
        return True

    if etapa_destino == "revisao_tipo":
        enviar_mensagem(
            telefone,
            "🔧 Qual revisão deseja agendar?\n\n"
            "1 - 1ª revisão\n"
            "2 - 2ª revisão\n"
            "3 - 3ª revisão\n"
            "4 - 4ª revisão\n"
            "5 - 5ª ou acima"
        )
        return True

    if etapa_destino == "revisao_dia":
        enviar_mensagem(
            telefone,
            "📅 Qual dia da semana você prefere?\n\n"
            "1 - Segunda\n"
            "2 - Terça\n"
            "3 - Quarta\n"
            "4 - Quinta\n"
            "5 - Sexta\n"
            "6 - Sábado"
        )
        return True

    if etapa_destino == "revisao_data":
        enviar_mensagem(
            telefone,
            "📆 Perfeito. Agora me informe a *data desejada*.\n"
            "Exemplo: 15/04/2026"
        )
        return True

    if etapa_destino == "revisao_horario":
        horarios = clientes[telefone].get("horarios_disponiveis", [])
        if horarios:
            enviar_mensagem(telefone, montar_mensagem_horarios(horarios))
        else:
            clientes[telefone]["etapa"] = "revisao_dia"
            enviar_mensagem(
                telefone,
                "📅 Preciso confirmar o *dia da semana* para te mostrar os horários.\n\n"
                "1 - Segunda\n"
                "2 - Terça\n"
                "3 - Quarta\n"
                "4 - Quinta\n"
                "5 - Sexta\n"
                "6 - Sábado"
            )
        return True

    if etapa_destino == "revisao_venda_opcao":
        enviar_mensagem(telefone, montar_mensagem_venda_adicional(telefone))
        return True

    if etapa_destino == "revisao_confirmar":
        adicionais_exibicao = clientes[telefone]["itens"] if clientes[telefone]["itens"] else "Nenhum"

        enviar_mensagem(
            telefone,
            "✅ *Confira seu agendamento:*\n\n"
            f"👤 Nome: {clientes[telefone]['nome']}\n"
            f"🏍️ Modelo: {clientes[telefone]['modelo']}\n"
            f"📄 CPF: {clientes[telefone]['cpf']}\n"
            f"📅 Data: {clientes[telefone]['data']}\n"
            f"📍 Dia: {clientes[telefone]['dia_texto']}\n"
            f"⏰ Horário: {clientes[telefone]['horario']}\n"
            f"🔧 Revisão: {clientes[telefone]['revisao']}ª\n"
            f"🛒 Adicionais: {adicionais_exibicao}\n\n"
            "Digite:\n"
            "1 - Confirmar\n"
            "2 - Cancelar"
        )
        return True

    return False


def tentar_aproveitar_texto_no_horario(telefone, texto):
    texto_limpo = limpar_texto(texto)
    horarios = clientes[telefone].get("horarios_disponiveis", [])

    if not horarios:
        return False

    if texto_limpo in horarios:
        clientes[telefone]["horario"] = texto_limpo
        return True

    try:
        indice = int(limpar_opcao(texto_limpo)) - 1
        if 0 <= indice < len(horarios):
            clientes[telefone]["horario"] = horarios[indice]
            return True
    except Exception:
        pass

    return False


def tratar_desvio_de_intencao_durante_fluxo(telefone, intencao, resposta):
    if intencao == "menu":
        resetar_cliente(telefone)
        enviar_menu(telefone)
        return True

    if intencao == "humano":
        ativar_atendimento_humano(telefone)
        return True

    if intencao == "pecas":
        resetar_cliente(telefone)
        clientes[telefone]["etapa"] = "pecas_descricao"
        if resposta:
            enviar_mensagem(telefone, resposta)
        enviar_mensagem(
            telefone,
            "🔩 *Peças*\n\n"
            "Informe a *peça desejada* para seguirmos com o atendimento."
        )
        return True

    if intencao == "acessorios":
        resetar_cliente(telefone)
        clientes[telefone]["etapa"] = "acessorios_descricao"
        if resposta:
            enviar_mensagem(telefone, resposta)
        enviar_mensagem(
            telefone,
            "🛵 *Acessórios*\n\n"
            "Informe o *acessório desejado* para seguirmos com o atendimento."
        )
        return True

    if intencao == "garantia":
        resetar_cliente(telefone)
        clientes[telefone]["etapa"] = "garantia_descricao"
        if resposta:
            enviar_mensagem(telefone, resposta)
        enviar_mensagem(
            telefone,
            "🛡️ *Garantia*\n\n"
            "Descreva sua solicitação de garantia para seguirmos com o atendimento."
        )
        return True

    if intencao == "atacado":
        resetar_cliente(telefone)
        clientes[telefone]["etapa"] = "submenu_atacado"
        if resposta:
            enviar_mensagem(telefone, resposta)
        enviar_mensagem(
            telefone,
            "📦 *Logista / Atacado*\n\n"
            "Digite uma opção:\n\n"
            "1 - Solicitar cotação\n"
            "2 - Cadastro de logista\n"
            "3 - Receber catálogo\n"
            "4 - Falar com consultor"
        )
        return True

    return False


def tentar_fluxo_revisao_com_ia(telefone, texto):
    try:
        resultado = classificar_intencao(texto)
        log_info("IA durante fluxo:", resultado)
    except Exception as e:
        log_erro("Erro IA durante fluxo:", e)
        return False

    if not resultado or not isinstance(resultado, dict):
        return False

    intencao = str(resultado.get("intencao", "")).strip().lower()
    resposta = limpar_texto(resultado.get("resposta", ""))
    dados = resultado.get("dados_extraidos", {}) or {}

    etapa_atual = clientes[telefone]["etapa"]

    if etapa_atual == "revisao_modelo" and limpar_texto(texto):
        clientes[telefone]["modelo"] = limpar_texto(texto)
    elif etapa_atual == "revisao_nome" and limpar_texto(texto):
        clientes[telefone]["nome"] = limpar_texto(texto)
    elif etapa_atual == "revisao_cpf" and limpar_texto(texto):
        clientes[telefone]["cpf"] = limpar_texto(dados.get("cpf")) or limpar_texto(texto)
    elif etapa_atual == "revisao_ano":
        ano_limpo = re.sub(r"\D", "", texto)
        if len(ano_limpo) == 4:
            clientes[telefone]["ano"] = ano_limpo
        else:
            preencher_dados_ia_no_cliente(telefone, dados)
    elif etapa_atual == "revisao_data" and data_texto_valida(texto):
        clientes[telefone]["data"] = texto
    elif etapa_atual == "revisao_horario" and tentar_aproveitar_texto_no_horario(telefone, texto):
        pass
    else:
        if intencao in ["menu", "humano", "pecas", "acessorios", "garantia", "atacado"]:
            possui_dado_extraido = any([
                limpar_texto(dados.get("modelo")),
                limpar_texto(dados.get("nome")),
                limpar_texto(dados.get("cpf")),
                limpar_texto(dados.get("ano")),
                limpar_texto(dados.get("revisao")),
                limpar_texto(dados.get("dia")),
                limpar_texto(dados.get("data")),
                limpar_texto(dados.get("horario")),
                limpar_texto(dados.get("item_adicional")),
            ])

            if not possui_dado_extraido:
                return tratar_desvio_de_intencao_durante_fluxo(telefone, intencao, resposta)

        preencher_dados_ia_no_cliente(telefone, dados)

    etapa_destino = proxima_etapa_revisao(telefone)
    clientes[telefone]["etapa"] = etapa_destino

    resumo = resumo_identificado_revisao(telefone)
    if resumo:
        enviar_mensagem(
            telefone,
            "Perfeito. Já aproveitei estas informações da sua mensagem:\n\n" + "\n".join(resumo)
        )

    return enviar_pergunta_etapa_revisao(telefone, etapa_destino)


# ==========================================
# IA INTENÇÃO
# ==========================================
def tratar_intencao_ia(telefone, texto):
    try:
        resultado = classificar_intencao(texto)
        log_info("Resultado IA:", resultado)
    except Exception as e:
        log_erro("Erro na IA de intenção:", e)
        return False

    if not resultado or not isinstance(resultado, dict):
        return False

    intencao = str(resultado.get("intencao", "")).strip().lower()
    resposta = limpar_texto(resultado.get("resposta", ""))
    dados = resultado.get("dados_extraidos", {}) or {}

    log_info("Intenção:", intencao)
    log_info("Dados extraídos:", dados)

    if intencao == "agendar_revisao":
        limpar_dados_fluxo_revisao(telefone)
        preencher_dados_ia_no_cliente(telefone, dados)

        etapa_destino = proxima_etapa_revisao(telefone)
        clientes[telefone]["etapa"] = etapa_destino

        resumo = resumo_identificado_revisao(telefone)

        if resposta and not resumo:
            enviar_mensagem(telefone, resposta)
        elif resumo:
            enviar_mensagem(
                telefone,
                "Perfeito. Já identifiquei estas informações do seu agendamento:\n\n"
                + "\n".join(resumo)
            )

        return enviar_pergunta_etapa_revisao(telefone, etapa_destino)

    if intencao == "valor_revisao":
        modelo = limpar_texto(dados.get("modelo")) or extrair_modelo_do_texto(texto)
        revisao_extraida = dados.get("revisao")
        dados_consulta = extrair_revisao_km_ou_meses(texto)

        revisao = None
        km = dados_consulta.get("km")
        meses = dados_consulta.get("meses")

        if str(revisao_extraida or "").isdigit():
            revisao = int(str(revisao_extraida).strip())
        else:
            revisao = dados_consulta.get("revisao")

        if not modelo:
            enviar_mensagem(
                telefone,
                "🔎 Para eu consultar o valor da revisão, preciso do *modelo da moto*.\n\n"
                "Exemplos:\n"
                "• Valor da 3 revisão da Fluo\n"
                "• Valor da revisão de 6000 km da Fluo\n"
                "• Valor da revisão de 18 meses da Fluo"
            )
            return True

        if revisao is None and km is None and meses is None:
            enviar_mensagem(
                telefone,
                "🔎 Me informe qual revisão deseja consultar:\n\n"
                "• Número da revisão\n"
                "• Quilometragem\n"
                "• Tempo em meses\n\n"
                "Exemplos:\n"
                "• 3 revisão da Fluo\n"
                "• revisão de 6000 km da Fluo\n"
                "• revisão de 18 meses da Fluo"
            )
            return True

        resultado_busca = buscar_valor_revisao(
            modelo=modelo,
            revisao=revisao,
            km=km,
            meses=meses
        )

        if not resultado_busca:
            enviar_mensagem(
                telefone,
                "⚠️ Não encontrei esse valor na tabela no momento.\n\n"
                "Verifique o modelo e a referência da revisão e tente novamente."
            )
            return True

        valor = resultado_busca["valor"]
        revisao_encontrada = resultado_busca["revisao"]
        km_encontrado = resultado_busca["km"]
        meses_encontrado = resultado_busca["meses"]

        valor_formatado = formatar_valor_brl(valor)

        if revisao is not None:
            referencia = f"{revisao_encontrada}ª revisão"
        elif km is not None:
            referencia = f"{km_encontrado} km"
        else:
            referencia = f"{meses_encontrado} meses"

        enviar_mensagem(
            telefone,
            "🔧 *Valor da Revisão*\n\n"
            f"🏍️ Modelo: *{modelo}*\n"
            f"📌 Referência informada: *{referencia}*\n"
            f"🔄 Equivale à: *{revisao_encontrada}ª revisão*\n"
            f"💰 Valor: *{valor_formatado}*\n\n"
            "Caso queira, já posso seguir com o *agendamento da sua revisão*."
        )
        return True

    if intencao == "menu":
        resetar_cliente(telefone)
        enviar_menu(telefone)
        return True

    if intencao == "humano":
        ativar_atendimento_humano(telefone)
        return True

    if intencao == "pecas":
        clientes[telefone]["etapa"] = "pecas_descricao"
        if resposta:
            enviar_mensagem(telefone, resposta)

        enviar_mensagem(
            telefone,
            "🔩 *Peças*\n\n"
            "Informe a *peça desejada* para seguirmos com o atendimento."
        )
        return True

    if intencao == "acessorios":
        clientes[telefone]["etapa"] = "acessorios_descricao"
        if resposta:
            enviar_mensagem(telefone, resposta)

        enviar_mensagem(
            telefone,
            "🛵 *Acessórios*\n\n"
            "Informe o *acessório desejado* para seguirmos com o atendimento."
        )
        return True

    if intencao == "garantia":
        clientes[telefone]["etapa"] = "garantia_descricao"
        if resposta:
            enviar_mensagem(telefone, resposta)

        enviar_mensagem(
            telefone,
            "🛡️ *Garantia*\n\n"
            "Descreva sua solicitação de garantia para seguirmos com o atendimento."
        )
        return True

    if intencao == "atacado":
        clientes[telefone]["etapa"] = "submenu_atacado"

        if resposta:
            enviar_mensagem(telefone, resposta)

        enviar_mensagem(
            telefone,
            "📦 *Logista / Atacado*\n\n"
            "Digite uma opção:\n\n"
            "1 - Solicitar cotação\n"
            "2 - Cadastro de logista\n"
            "3 - Receber catálogo\n"
            "4 - Falar com consultor"
        )
        return True

    return False
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
        return jsonify({"status": "ignorado", "motivo": "evento do proprio bot"}), 200

    telefone = extrair_telefone(payload)
    texto = limpar_texto(extrair_texto(payload))
    texto_normalizado = normalizar_texto(texto)
    message_id = extrair_message_id(payload)

    log_info("Telefone extraído:", telefone)
    log_info("Texto extraído:", texto)
    log_info("Texto extraído repr:", repr(texto))
    log_info("Message ID:", message_id)

    if not telefone:
        return jsonify({"status": "ignorado", "motivo": "telefone ausente"}), 200

    if telefone_eh_grupo(telefone):
        return jsonify({"status": "ignorado", "motivo": "grupo"}), 200

    if mensagem_ja_processada(message_id):
        return jsonify({"status": "ignorado", "motivo": "duplicada"}), 200

    registrar_mensagem_processada(message_id)

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)
    atualizar_retorno_na_planilha(telefone, texto)

    log_info("Etapa atual antes do fluxo:", clientes.get(telefone, {}).get("etapa"))

    if not texto:
        log_info("Mensagem ignorada: texto vazio")
        return jsonify({"status": "ignorado", "motivo": "texto vazio"}), 200

    # ==========================================
    # SAÍDA DO ATENDIMENTO HUMANO
    # ==========================================
    if clientes[telefone].get("atendimento_humano"):
        if texto_normalizado in [
            "menu", "oi", "ola", "olá", "voltar", "inicio", "início",
            "bom dia", "boa tarde", "boa noite"
        ]:
            resetar_cliente(telefone)
            enviar_menu(telefone)
            return jsonify({"status": "ok", "acao": "saiu_humano"}), 200

        return jsonify({"status": "ok", "modo": "humano"}), 200

    # ==========================================
    # CHAMADA DE MENU
    # ==========================================
    if texto_normalizado in ["menu", "oi", "ola", "olá", "bom dia", "boa tarde", "boa noite"]:
        resetar_cliente(telefone)
        enviar_menu(telefone)
        return jsonify({"status": "ok", "acao": "menu"}), 200

    etapa = clientes[telefone]["etapa"]

    # ==========================================
    # IA NO MENU
    # ==========================================
    if etapa == "menu" and texto and texto not in ["1", "2", "3", "4", "5", "6"]:
        if tratar_intencao_ia(telefone, texto):
            return jsonify({"status": "ok", "origem": "ia"}), 200

    # ==========================================
    # IA DURANTE FLUXO DE REVISÃO
    # ==========================================
    if etapa.startswith("revisao_") and texto_normalizado not in ["1", "2"] and not texto.isdigit():
        if tentar_fluxo_revisao_com_ia(telefone, texto):
            return jsonify({"status": "ok", "origem": "ia_fluxo_revisao"}), 200

    # ==========================================
    # MENU PRINCIPAL
    # ==========================================
    if etapa == "menu":
        opcao = limpar_opcao(texto)

        log_info("Opcao tratada no menu:", repr(opcao))

        if opcao == "1":
            clientes[telefone]["etapa"] = "revisao_modelo"
            enviar_mensagem(
                telefone,
                "🔧 *Agendamento de Revisão*\n\n"
                "Informe o *modelo da moto*:"
            )
            return jsonify({"status": "ok", "fluxo": "revisao_modelo"}), 200

        elif opcao == "2":
            clientes[telefone]["etapa"] = "pecas_descricao"
            enviar_mensagem(
                telefone,
                "🔩 *Peças*\n\n"
                "Informe a *peça desejada* para seguirmos com o atendimento."
            )
            return jsonify({"status": "ok", "fluxo": "pecas"}), 200

        elif opcao == "3":
            clientes[telefone]["etapa"] = "acessorios_descricao"
            enviar_mensagem(
                telefone,
                "🛵 *Acessórios*\n\n"
                "Informe o *acessório desejado* para seguirmos com o atendimento."
            )
            return jsonify({"status": "ok", "fluxo": "acessorios"}), 200

        elif opcao == "4":
            clientes[telefone]["etapa"] = "garantia_descricao"
            enviar_mensagem(
                telefone,
                "🛡️ *Garantia*\n\n"
                "Descreva sua solicitação de garantia para seguirmos com o atendimento."
            )
            return jsonify({"status": "ok", "fluxo": "garantia"}), 200

        elif opcao == "5":
            clientes[telefone]["etapa"] = "submenu_atacado"
            enviar_mensagem(
                telefone,
                "📦 *Logista / Atacado*\n\n"
                "Digite uma opção:\n\n"
                "1 - Solicitar cotação\n"
                "2 - Cadastro de logista\n"
                "3 - Receber catálogo\n"
                "4 - Falar com consultor"
            )
            return jsonify({"status": "ok", "fluxo": "submenu_atacado"}), 200

        elif opcao == "6":
            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok", "fluxo": "humano"}), 200

        else:
            log_info("Opção inválida no menu. Texto recebido:", repr(texto))
            enviar_menu(telefone)
            return jsonify({"status": "ok", "fluxo": "menu_reenviado"}), 200

    # ==========================================
    # SUBMENU ATACADO
    # ==========================================
    elif etapa == "submenu_atacado":
        opcao = limpar_opcao(texto)

        if opcao == "1":
            ativar_atendimento_humano(telefone)
            enviar_mensagem(
                telefone,
                "📦 *Solicitação de Cotação*\n\n"
                "Envie:\n"
                "• Empresa\n"
                "• CNPJ\n"
                "• Cidade\n"
                "• Peças desejadas"
            )
            return jsonify({"status": "ok"}), 200

        elif opcao == "2":
            ativar_atendimento_humano(telefone)
            enviar_mensagem(
                telefone,
                "📝 *Cadastro de Logista*\n\n"
                "Envie:\n"
                "• Empresa\n"
                "• CNPJ\n"
                "• Responsável\n"
                "• Cidade\n"
                "• Telefone"
            )
            return jsonify({"status": "ok"}), 200

        elif opcao == "3":
            ok = enviar_documento_pdf(
                telefone,
                "catalogo-atacado.pdf",
                nome_exibicao="catalogo-atacado.pdf",
                legenda="📄 Catálogo Atacado Motoshow Yamaha"
            )

            if ok:
                enviar_mensagem(
                    telefone,
                    "✅ Catálogo enviado com sucesso.\n\n"
                    "Equipe Motoshow Yamaha"
                )
            else:
                enviar_mensagem(
                    telefone,
                    "⚠️ Não consegui enviar o catálogo agora.\n"
                    "Tente novamente em instantes ou envie *menu*."
                )

            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        elif opcao == "4":
            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok"}), 200

        else:
            enviar_mensagem(
                telefone,
                "❌ Opção inválida.\n\n"
                "Digite:\n"
                "1 - Solicitar cotação\n"
                "2 - Cadastro de logista\n"
                "3 - Receber catálogo\n"
                "4 - Falar com consultor"
            )
            return jsonify({"status": "ok"}), 200

    # ==========================================
    # FLUXO PEÇAS
    # ==========================================
    elif etapa == "pecas_descricao":
        salvar_atendimento_seguro({
            "telefone": limpar_telefone(telefone),
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
        return jsonify({"status": "ok", "fluxo": "pecas_registrado"}), 200

    # ==========================================
    # FLUXO ACESSÓRIOS
    # ==========================================
    elif etapa == "acessorios_descricao":
        salvar_atendimento_seguro({
            "telefone": limpar_telefone(telefone),
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
        return jsonify({"status": "ok", "fluxo": "acessorios_registrado"}), 200

    # ==========================================
    # FLUXO GARANTIA
    # ==========================================
    elif etapa == "garantia_descricao":
        salvar_atendimento_seguro({
            "telefone": limpar_telefone(telefone),
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
        return jsonify({"status": "ok", "fluxo": "garantia_registrada"}), 200

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

        enviar_mensagem(telefone, montar_mensagem_venda_adicional(telefone))
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
            "telefone": limpar_telefone(telefone),
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
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)