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


def limpar_cpf(cpf):
    return re.sub(r"\D", "", str(cpf or ""))


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

    except Exception as e:
        log_erro("Erro envio mensagem:", e)


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
            headers=headers
        )

        log_info("PDF enviado:", response.status_code)

    except Exception as e:
        log_erro("Erro enviar PDF:", e)


# ==========================================
# CAPACIDADE POR HORÁRIO
# ==========================================
def limite_por_revisao(revisao):

    try:
        revisao = int(revisao)
    except:
        revisao = 1

    if revisao <= 2:
        return 10
    else:
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


# ==========================================
# GERAR PROTOCOLO
# ==========================================
def gerar_protocolo():
    return str(uuid.uuid4())[:8].upper()


# ==========================================
# SALVAR AGENDAMENTO
# ==========================================
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
            dia_semana=dados["dia"],
            data_agendada=dados["data"],
            horario=dados["horario"],
            itens=dados.get("itens", ""),
            venda_adicional=dados.get("venda_adicional", ""),
            status="AGENDADO",
            origem="BOT"
        )

        db.add(agendamento)
        db.commit()

        return protocolo

    except Exception as e:
        log_erro("Erro salvar agendamento:", e)
        return None

    finally:
        db.close()


# ==========================================
# BUSCAR AGENDAMENTO ATIVO
# ==========================================
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


# ==========================================
# CANCELAR AGENDAMENTO
# ==========================================
def cancelar_agendamento(cpf):

    db = SessionLocal()

    try:
        agendamento = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.cpf == cpf,
            AgendamentoRevisao.status == "AGENDADO"
        ).first()

        if agendamento:
            agendamento.status = "CANCELADO"
            db.commit()
            return True

        return False

    except Exception as e:
        log_erro("Erro cancelar:", e)
        return False

    finally:
        db.close()


# ==========================================
# HORÁRIOS DISPONÍVEIS
# ==========================================
def horarios_por_revisao(revisao, dia):

    try:
        revisao = int(revisao)
    except:
        revisao = 1

    if dia == "sabado":

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


# ==========================================
# VALIDAR DATA
# ==========================================
def validar_data(data):

    try:
        data_obj = datetime.strptime(data, "%d/%m/%Y")

        if data_obj.date() < datetime.now().date():
            return False

        if data_obj.weekday() == 6:
            return False

        return True

    except:
        return False
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


def processar_lembretes_agendamento():
    db = SessionLocal()
    try:
        hoje = datetime.now().date()

        agendamentos = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.status == "AGENDADO",
            AgendamentoRevisao.lembrete_enviado == False
        ).all()

        for ag in agendamentos:
            dt = parse_data_hora(ag.data_agendada)
            if not dt:
                continue

            diferenca = (dt.date() - hoje).days

            if diferenca == 1:
                ok = enviar_mensagem(
                    ag.telefone,
                    "🔔 *Lembrete de Revisão*\n\n"
                    f"Olá, {ag.nome}.\n"
                    f"Seu agendamento está confirmado para *{ag.data_agendada}* às *{ag.horario}*.\n\n"
                    f"📌 Protocolo: {ag.protocolo}\n\n"
                    "Equipe Motoshow Yamaha"
                )

                if ok:
                    ag.lembrete_enviado = True

        db.commit()

    except Exception as e:
        db.rollback()
        log_erro("Erro ao processar lembretes:", e)
    finally:
        db.close()


def worker_followup():
    log_info("Worker de follow-up iniciado.")
    while True:
        try:
            processar_followups()
            processar_lembretes_agendamento()
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
        processar_lembretes_agendamento()
        return jsonify({"status": "ok", "message": "Follow-ups processados"}), 200
    except Exception as e:
        log_erro("Erro na rota de processar follow-ups:", e)
        return jsonify({"status": "erro", "message": str(e)}), 500


# ==========================================
# EXTRAÇÃO
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
            telefone = (
                str(telefone)
                .replace("@c.us", "")
                .replace("@s.whatsapp.net", "")
                .strip()
            )

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
# IA / MENU
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
# ==========================================
# WEBHOOK
# ==========================================
@app.route("/webhook", methods=["POST"])
def webhook():

    iniciar_worker_followup()

    payload = request.get_json()

    telefone = extrair_telefone(payload)
    texto = extrair_texto(payload)

    if not telefone:
        return jsonify({"status": "sem telefone"}), 200

    if telefone_eh_grupo(telefone):
        return jsonify({"status": "grupo ignorado"}), 200

    telefone = limpar_telefone(telefone)

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)

    texto_normalizado = normalizar_texto(texto)
    texto_opcao = limpar_opcao(texto)

    # ==========================================
    # VOLTAR MENU
    # ==========================================
    if texto_normalizado in ["menu", "voltar", "inicio", "início"]:

        resetar_cliente(telefone)
        enviar_menu(telefone)

        return jsonify({"status": "ok"}), 200

    # ==========================================
    # IA INTENÇÃO
    # ==========================================
    if clientes[telefone]["etapa"] == "menu":

        resposta_ia = classificar_intencao(texto)

        intencao = resposta_ia["intencao"]
        proxima_etapa = resposta_ia["proxima_etapa"]

        if intencao == "agendar_revisao":

            limpar_dados_fluxo_revisao(telefone)

            clientes[telefone]["etapa"] = "revisao_modelo"

            enviar_mensagem(
                telefone,
                "🏍️ *Agendamento de Revisão*\n\n"
                "Informe o *modelo da moto*:"
            )

            return jsonify({"status": "ok"}), 200

        if intencao == "pecas":

            enviar_mensagem(
                telefone,
                "🔧 *Peças*\n\n"
                "Informe a peça desejada:"
            )

            clientes[telefone]["etapa"] = "pecas"

            return jsonify({"status": "ok"}), 200

        if intencao == "acessorios":

            enviar_mensagem(
                telefone,
                "🛠️ *Acessórios*\n\n"
                "Informe o acessório desejado:"
            )

            clientes[telefone]["etapa"] = "acessorios"

            return jsonify({"status": "ok"}), 200

        if intencao == "garantia":

            enviar_mensagem(
                telefone,
                "🛡️ *Garantia*\n\n"
                "Informe seu nome completo:"
            )

            clientes[telefone]["etapa"] = "garantia_nome"

            return jsonify({"status": "ok"}), 200

        if intencao == "atacado":

            enviar_mensagem(
                telefone,
                "🏪 *Logista / Atacado*\n\n"
                "Informe sua empresa:"
            )

            clientes[telefone]["etapa"] = "atacado_empresa"

            return jsonify({"status": "ok"}), 200

        if intencao == "humano":

            ativar_atendimento_humano(telefone)

            return jsonify({"status": "ok"}), 200

        enviar_menu(telefone)

        return jsonify({"status": "ok"}), 200

    # ==========================================
    # FLUXO REVISÃO AUTÔNOMA
    # ==========================================
    etapa = clientes[telefone]["etapa"]

    # MODELO
    if etapa == "revisao_modelo":

        clientes[telefone]["modelo"] = texto.upper()

        clientes[telefone]["etapa"] = "revisao_nome"

        enviar_mensagem(
            telefone,
            "Informe seu *nome completo*:"
        )

        return jsonify({"status": "ok"}), 200

    # NOME
    if etapa == "revisao_nome":

        clientes[telefone]["nome"] = texto.upper()

        clientes[telefone]["etapa"] = "revisao_cpf"

        enviar_mensagem(
            telefone,
            "Informe seu *CPF*:"
        )

        return jsonify({"status": "ok"}), 200

    # CPF
    if etapa == "revisao_cpf":

        cpf = limpar_cpf(texto)

        if len(cpf) != 11:

            enviar_mensagem(
                telefone,
                "CPF inválido. Digite novamente:"
            )

            return jsonify({"status": "ok"}), 200

        clientes[telefone]["cpf"] = cpf

        clientes[telefone]["etapa"] = "revisao_ano"

        enviar_mensagem(
            telefone,
            "Informe o *ano da moto*:"
        )

        return jsonify({"status": "ok"}), 200

    # ANO
    if etapa == "revisao_ano":

        clientes[telefone]["ano"] = texto

        clientes[telefone]["etapa"] = "revisao_tipo"

        enviar_mensagem(
            telefone,
            "Qual revisão?\n\n"
            "1 - 1ª Revisão\n"
            "2 - 2ª Revisão\n"
            "3 - 3ª Revisão\n"
            "4 - 4ª Revisão\n"
            "5 - 5ª Revisão"
        )

        return jsonify({"status": "ok"}), 200

    # TIPO REVISÃO
    if etapa == "revisao_tipo":

        revisao = normalizar_revisao_para_fluxo(texto_opcao)

        clientes[telefone]["revisao"] = revisao

        clientes[telefone]["etapa"] = "revisao_dia"

        enviar_mensagem(
            telefone,
            "Escolha o dia:\n\n"
            "1 - Segunda\n"
            "2 - Terça\n"
            "3 - Quarta\n"
            "4 - Quinta\n"
            "5 - Sexta\n"
            "6 - Sábado"
        )

        return jsonify({"status": "ok"}), 200

    # DIA
    if etapa == "revisao_dia":

        clientes[telefone]["dia"] = texto_opcao

        clientes[telefone]["etapa"] = "revisao_data"

        enviar_mensagem(
            telefone,
            "Informe a data:\n"
            "Ex: 20/04/2026"
        )

        return jsonify({"status": "ok"}), 200

    # DATA
    if etapa == "revisao_data":

        if not validar_data(texto):

            enviar_mensagem(
                telefone,
                "Data inválida. Digite novamente:"
            )

            return jsonify({"status": "ok"}), 200

        clientes[telefone]["data"] = texto

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

    # HORÁRIO
    if etapa == "revisao_horario":

        horarios = clientes[telefone]["horarios_disponiveis"]

        try:
            idx = int(texto_opcao) - 1
            horario = horarios[idx]
        except:
            horario = texto

        data = clientes[telefone]["data"]
        revisao = clientes[telefone]["revisao"]

        if not verificar_capacidade(data, horario, revisao):

            enviar_mensagem(
                telefone,
                "Horário cheio, escolha outro."
            )

            return jsonify({"status": "ok"}), 200

        clientes[telefone]["horario"] = horario

        clientes[telefone]["etapa"] = "revisao_venda"

        enviar_mensagem(
            telefone,
            montar_mensagem_venda_adicional(telefone)
        )

        return jsonify({"status": "ok"}), 200

    # VENDA ADICIONAL
    if etapa == "revisao_venda":

        if texto_opcao == "2":
            clientes[telefone]["venda_adicional"] = ""
        else:
            clientes[telefone]["venda_adicional"] = texto.upper()

        dados = clientes[telefone]

        protocolo = salvar_agendamento(telefone, dados)

        enviar_mensagem(
            telefone,
            "✅ *Agendamento Confirmado*\n\n"
            f"👤 {dados['nome']}\n"
            f"🏍️ {dados['modelo']}\n"
            f"📅 {dados['data']}\n"
            f"⏰ {dados['horario']}\n\n"
            f"📌 Protocolo: {protocolo}\n\n"
            "Equipe Motoshow Yamaha"
        )

        resetar_cliente(telefone)

        return jsonify({"status": "ok"}), 200

    return jsonify({"status": "ok"}), 200


# ==========================================
# START
# ==========================================
if __name__ == "__main__":

    iniciar_worker_followup()

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000))
    )