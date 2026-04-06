from flask import Flask, request, jsonify, send_from_directory, render_template
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import threading
import time

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

TEMPO_INATIVIDADE = int(os.getenv("TEMPO_INATIVIDADE", 900))

clientes = {}
mensagens_processadas = {}

# ==========================================
# HOME
# ==========================================

@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"


# ==========================================
# ENVIAR MENSAGEM
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
    except Exception as e:
        print("Erro enviar mensagem:", e)


# ==========================================
# MENU PRINCIPAL
# ==========================================

def menu_principal():
    return """Olá 👋

Bem-vindo ao Pós-Vendas Motoshow Yamaha 🏍️

Escolha uma opção:

1️⃣ Agendar Revisão
2️⃣ Peças
3️⃣ Acompanhar Serviço
4️⃣ Agendar Serviço / Avaliação
5️⃣ Garantia
6️⃣ Logista / Atacado
7️⃣ Falar com Consultor

Digite apenas o número da opção desejada.

Equipe Motoshow Yamaha
"""


def enviar_menu(telefone):
    enviar_mensagem(telefone, menu_principal())


# ==========================================
# CLIENTE
# ==========================================

def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = {
            "etapa": "menu",
            "atendimento_humano": False,
            "ultima_interacao": time.time(),
            "origem": "Menu Normal"
        }


def atualizar_interacao(telefone):
    clientes[telefone]["ultima_interacao"] = time.time()


def cliente_em_atendimento_humano(telefone):
    return clientes.get(telefone, {}).get("atendimento_humano", False)


def limpar_dados_fluxo(telefone):
    clientes[telefone]["etapa"] = "menu"


# ==========================================
# INATIVIDADE
# ==========================================

def processar_inatividade():
    agora = time.time()

    for telefone in list(clientes.keys()):
        ultima = clientes[telefone]["ultima_interacao"]

        if agora - ultima > TEMPO_INATIVIDADE:
            enviar_mensagem(
                telefone,
                "Seu atendimento foi encerrado por inatividade.\n\nEnvie *menu* para iniciar novamente."
            )

            del clientes[telefone]


# ==========================================
# EXTRAIR DADOS
# ==========================================

def extrair_telefone(payload):
    return payload.get("phone")


def telefone_eh_grupo(telefone):
    return "@g.us" in str(telefone)


def extrair_mensagem_texto(payload):
    try:
        if "text" in payload:
            if isinstance(payload["text"], dict):
                return payload["text"].get("message", "")
            return payload.get("text", "")

        if "message" in payload:
            return payload.get("message", "")

        return ""

    except:
        return ""


# ==========================================
# DUPLICAÇÃO
# ==========================================

def registrar_mensagem_processada(message_id):
    if not message_id:
        return

    agora = time.time()
    mensagens_processadas[message_id] = agora

    expirados = [
        mid for mid, timestamp in mensagens_processadas.items()
        if agora - timestamp > 60
    ]

    for mid in expirados:
        mensagens_processadas.pop(mid, None)


def mensagem_ja_processada(message_id):
    return message_id in mensagens_processadas


def extrair_message_id(payload):
    return payload.get("messageId")
# ==========================================
# WEBHOOK
# ==========================================

@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    if request.method == "GET":
        return jsonify({"status": "ok"}), 200

    processar_inatividade()

    payload = request.get_json(silent=True) or {}
    print("RECEBIDO:", payload)

    message_id = extrair_message_id(payload)

    if mensagem_ja_processada(message_id):
        return jsonify({"status": "ignorado"}), 200

    registrar_mensagem_processada(message_id)

    telefone = extrair_telefone(payload)
    texto = extrair_mensagem_texto(payload).strip()

    if not telefone or telefone_eh_grupo(telefone):
        return jsonify({"status": "ignorado"}), 200

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)

    texto_normalizado = texto.lower().strip()

    # ==========================================
    # VOLTAR MENU
    # ==========================================

    if texto_normalizado in [
        "menu",
        "oi",
        "ola",
        "olá",
        "bom dia",
        "boa tarde",
        "boa noite"
    ]:
        limpar_dados_fluxo(telefone)
        clientes[telefone]["atendimento_humano"] = False
        enviar_menu(telefone)

        return jsonify({"status": "menu"}), 200

    # ==========================================
    # ATENDIMENTO HUMANO
    # ==========================================

    if cliente_em_atendimento_humano(telefone):

        if texto_normalizado == "menu":
            clientes[telefone]["atendimento_humano"] = False
            limpar_dados_fluxo(telefone)
            enviar_menu(telefone)

        return jsonify({"status": "humano"}), 200

    # ==========================================
    # MENU PRINCIPAL
    # ==========================================

    etapa = clientes[telefone].get("etapa")

    if etapa == "menu":

        if texto_normalizado == "1":
            clientes[telefone]["etapa"] = "revisao_modelo"

            enviar_mensagem(
                telefone,
                "Informe o modelo da sua Yamaha:\n\nFazer 250\nFZ15\nLander\nCrosser\nMT03\nMT07\nNMAX\nNEO\nFLUO"
            )

            return jsonify({"status": "ok"}), 200


        if texto_normalizado == "2":
            enviar_mensagem(
                telefone,
                "Informe a peça desejada e modelo da moto."
            )

            return jsonify({"status": "ok"}), 200


        if texto_normalizado == "3":
            enviar_mensagem(
                telefone,
                "Informe seu nome completo para acompanhar o serviço."
            )

            return jsonify({"status": "ok"}), 200


        if texto_normalizado == "4":
            enviar_mensagem(
                telefone,
                "Informe o serviço que deseja agendar."
            )

            return jsonify({"status": "ok"}), 200


        if texto_normalizado == "5":
            enviar_mensagem(
                telefone,
                "Informe seu nome completo para garantia."
            )

            return jsonify({"status": "ok"}), 200


        if texto_normalizado == "6":

            enviar_mensagem(
                telefone,
                """Logista / Atacado

1 Solicitar Cotação
2 Cadastro Logista
3 Catálogo Peças
4 Falar com Consultor

Digite a opção desejada."""
            )

            return jsonify({"status": "ok"}), 200


        if texto_normalizado == "7":

            clientes[telefone]["atendimento_humano"] = True

            enviar_mensagem(
                telefone,
                "Você será atendido por um consultor.\n\nEnvie *menu* para voltar ao atendimento automático."
            )

            return jsonify({"status": "ok"}), 200
# ==========================================
# INICIAR APP
# ==========================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)