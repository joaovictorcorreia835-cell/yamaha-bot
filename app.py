from flask import Flask, request, jsonify, send_from_directory, render_template
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import threading
import time
from sqlalchemy import func

from database import criar_banco, SessionLocal, Atendimento

load_dotenv()

app = Flask(__name__)
criar_banco()

# ==========================================
# CONFIG
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")

BASE_URL = os.getenv("BASE_URL")

url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"

TEMPO_INATIVIDADE = 900

clientes = {}
mensagens_processadas = set()

# ==========================================
# HOME
# ==========================================
@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"


# ==========================================
# UTIL
# ==========================================
def enviar_mensagem(telefone, mensagem):

    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN
    }

    payload = {
        "phone": telefone,
        "message": mensagem
    }

    try:
        requests.post(url_envio, json=payload, headers=headers)
    except:
        pass


def enviar_catalogo(telefone):

    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN
    }

    payload = {
        "phone": telefone,
        "document": f"{BASE_URL}/pdf/catalogo-atacado.pdf",
        "fileName": "catalogo-atacado.pdf",
        "caption": "📄 Catálogo Atacado Motoshow Yamaha"
    }

    try:
        requests.post(url_documento, json=payload, headers=headers)
    except:
        pass


def iniciar_cliente(telefone):

    if telefone not in clientes:
        clientes[telefone] = {
            "etapa": "menu",
            "ultima_interacao": datetime.now(),
            "atendimento_humano": False
        }


def atualizar_interacao(telefone):
    clientes[telefone]["ultima_interacao"] = datetime.now()


# ==========================================
# INATIVIDADE
# ==========================================
def verificar_inatividade():

    while True:

        agora = datetime.now()

        for telefone in list(clientes.keys()):

            ultima = clientes[telefone]["ultima_interacao"]

            if (agora - ultima).seconds > TEMPO_INATIVIDADE:

                enviar_mensagem(
                    telefone,
                    "⏰ Atendimento encerrado por inatividade\n\nDigite *menu* para voltar ao atendimento"
                )

                clientes[telefone]["etapa"] = "menu"

        time.sleep(60)


threading.Thread(target=verificar_inatividade).start()


# ==========================================
# MENU
# ==========================================
def enviar_menu(telefone):

    mensagem = """Olá 👋

Bem-vindo ao Pós-Vendas Motoshow Yamaha 🏍️

Escolha uma opção:

1️⃣ Agendar Revisão
2️⃣ Peças
3️⃣ Acessórios
4️⃣ Garantia
5️⃣ Logista / Atacado
6️⃣ Falar com atendente
"""

    enviar_mensagem(telefone, mensagem)


# ==========================================
# WEBHOOK
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    if request.method == "GET":
        return jsonify({"status": "ok"})

    data = request.get_json()

    print("PAYLOAD RECEBIDO:", data)

    try:
        telefone = data.get("phone") or data.get("data", {}).get("phone")

        texto = (
            data.get("message")
            or data.get("data", {}).get("message")
            or data.get("text")
            or ""
        ).lower()

        message_id = data.get("messageId") or str(time.time())

    except Exception as e:
        print("Erro:", e)
        return jsonify({"status": "erro"})

    if not telefone:
        return jsonify({"status": "sem telefone"})

    if message_id in mensagens_processadas:
        return jsonify({"status": "duplicado"})

    mensagens_processadas.add(message_id)

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)

    if clientes[telefone]["atendimento_humano"]:
        return jsonify({"status": "humano"})

    if texto in ["menu", "oi", "bom dia", "boa tarde", "boa noite"]:
        enviar_menu(telefone)
        return jsonify({"status": "menu"})

    etapa = clientes[telefone]["etapa"]

    if etapa == "menu":

        if texto == "1":
            clientes[telefone]["etapa"] = "revisao"
            enviar_mensagem(telefone, "Qual modelo da moto?")
            return jsonify({"status": "ok"})

        if texto == "2":
            clientes[telefone]["etapa"] = "pecas"
            enviar_mensagem(telefone, "Qual peça deseja?")
            return jsonify({"status": "ok"})

        if texto == "3":
            clientes[telefone]["etapa"] = "acessorios"
            enviar_mensagem(telefone, "Qual acessório deseja?")
            return jsonify({"status": "ok"})

        if texto == "4":
            clientes[telefone]["etapa"] = "garantia"
            enviar_mensagem(telefone, "Descreva sua solicitação")
            return jsonify({"status": "ok"})

        if texto == "5":
            clientes[telefone]["etapa"] = "atacado"
            enviar_catalogo(telefone)
            return jsonify({"status": "ok"})

        if texto == "6":
            clientes[telefone]["atendimento_humano"] = True
            enviar_mensagem(
                telefone,
                "👨‍💼 Você será atendido por um consultor"
            )
            return jsonify({"status": "ok"})

    return jsonify({"status": "ok"})
# ==========================================
# PDF
# ==========================================
@app.route("/pdf/<arquivo>")
def pdf(arquivo):
    return send_from_directory("static/pdfs", arquivo)


# ==========================================
# DASHBOARD
# ==========================================
@app.route("/dashboard")
def dashboard():

    db = SessionLocal()

    total = db.query(Atendimento).count()

    revisao = db.query(Atendimento).filter(
        Atendimento.setor == "Revisão"
    ).count()

    pecas = db.query(Atendimento).filter(
        Atendimento.setor == "Peças"
    ).count()

    acessorios = db.query(Atendimento).filter(
        Atendimento.setor == "Acessórios"
    ).count()

    garantia = db.query(Atendimento).filter(
        Atendimento.setor == "Garantia"
    ).count()

    logista = db.query(Atendimento).filter(
        Atendimento.setor == "Logista"
    ).count()

    humano = db.query(Atendimento).filter(
        Atendimento.atendimento_humano == True
    ).count()

    agendamentos = db.query(Atendimento).filter(
        Atendimento.status == "Agendado"
    ).count()

    html = f"""
    <h1>Dashboard Yamaha Bot</h1>

    <h2>Total Atendimentos: {total}</h2>

    <h3>Por Setor</h3>
    Revisão: {revisao}<br>
    Peças: {pecas}<br>
    Acessórios: {acessorios}<br>
    Garantia: {garantia}<br>
    Logista: {logista}<br>

    <h3>Outros</h3>
    Atendimento Humano: {humano}<br>
    Agendamentos: {agendamentos}
    """

    return html


# ==========================================
# SALVAR ATENDIMENTO
# ==========================================
def salvar_atendimento(
    telefone,
    setor,
    status="Em atendimento",
    atendimento_humano=False
):

    db = SessionLocal()

    atendimento = Atendimento(
        telefone=telefone,
        setor=setor,
        status=status,
        atendimento_humano=atendimento_humano
    )

    db.add(atendimento)
    db.commit()
    db.close()


# ==========================================
# IGNORAR GRUPO
# ==========================================
def telefone_eh_grupo(telefone):

    if "@g.us" in telefone:
        return True

    return False


# ==========================================
# RUN
# ==========================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)