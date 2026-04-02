import os
import json
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta

app = Flask(__name__)

# =========================
# CONFIG
# =========================

ZAPI_URL = os.getenv("ZAPI_URL")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_INSTANCE = os.getenv("ZAPI_INSTANCE")

PORT = int(os.environ.get("PORT", 10000))

ARQUIVO_CLIENTES = "clientes.json"

# =========================
# CLIENTES
# =========================

def carregar_clientes():
    if not os.path.exists(ARQUIVO_CLIENTES):
        return {}

    with open(ARQUIVO_CLIENTES, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_clientes(clientes):
    with open(ARQUIVO_CLIENTES, "w", encoding="utf-8") as f:
        json.dump(clientes, f, indent=4, ensure_ascii=False)


# =========================
# ENVIO ZAPI
# =========================

def enviar_mensagem(phone, mensagem):

    url = f"{ZAPI_URL}/instances/{ZAPI_INSTANCE}/token/{ZAPI_TOKEN}/send-text"

    payload = {
        "phone": phone,
        "message": mensagem
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        print("Resposta envio:", response.status_code)

    except Exception as e:
        print("Erro envio:", e)


# =========================
# BOT
# =========================

def processar_mensagem(phone, mensagem, from_me):

    clientes = carregar_clientes()

    if phone not in clientes:
        clientes[phone] = {
            "etapa": "inicio",
            "bot_pausado": False,
            "ultima_interacao_humana": None
        }

    cliente = clientes[phone]

    agora = datetime.now()

    # =========================
    # SE FOI VOCÊ QUE ENVIOU
    # =========================

    if from_me:

        cliente["bot_pausado"] = True
        cliente["ultima_interacao_humana"] = agora.isoformat()

        salvar_clientes(clientes)

        print("[BOT PAUSADO]", phone)
        return


    # =========================
    # REATIVAR APÓS 1H
    # =========================

    if cliente.get("bot_pausado"):

        ultima = cliente.get("ultima_interacao_humana")

        if ultima:

            ultima = datetime.fromisoformat(ultima)

            if agora - ultima > timedelta(hours=1):

                cliente["bot_pausado"] = False
                cliente["etapa"] = "inicio"

                salvar_clientes(clientes)

                print("[BOT REATIVADO]", phone)

        else:
            return

    if cliente.get("bot_pausado"):
        print("[BOT PAUSADO] Sem resposta")
        return

    # =========================
    # FLUXO BOT
    # =========================

    etapa = cliente.get("etapa")

    if etapa == "inicio":

        enviar_mensagem(
            phone,
            "Olá 👋\n\n"
            "Sou o assistente Yamaha\n\n"
            "Como posso ajudar?\n\n"
            "1️⃣ Agendar revisão\n"
            "2️⃣ Orçamento de peças\n"
            "3️⃣ Atendimento humano"
        )

        cliente["etapa"] = "menu"

    elif etapa == "menu":

        if mensagem == "1":

            enviar_mensagem(
                phone,
                "Qual modelo da moto?\n\n"
                "Exemplo:\n"
                "FZ25\n"
                "Factor\n"
                "Lander"
            )

            cliente["etapa"] = "modelo"

        elif mensagem == "2":

            enviar_mensagem(
                phone,
                "Informe a peça desejada"
            )

            cliente["etapa"] = "pecas"

        elif mensagem == "3":

            enviar_mensagem(
                phone,
                "Um atendente irá falar com você."
            )

            cliente["bot_pausado"] = True
            cliente["ultima_interacao_humana"] = datetime.now().isoformat()

        else:

            enviar_mensagem(
                phone,
                "Escolha uma opção válida\n\n"
                "1️⃣ Revisão\n"
                "2️⃣ Peças\n"
                "3️⃣ Atendimento humano"
            )

    elif etapa == "modelo":

        cliente["modelo"] = mensagem

        enviar_mensagem(
            phone,
            "Qual KM ou período?"
        )

        cliente["etapa"] = "km"


    elif etapa == "km":

        cliente["km"] = mensagem

        enviar_mensagem(
            phone,
            "Perfeito 👍\n\n"
            "Um consultor irá confirmar."
        )

        cliente["bot_pausado"] = True
        cliente["ultima_interacao_humana"] = datetime.now().isoformat()


    elif etapa == "pecas":

        enviar_mensagem(
            phone,
            "Recebido 👍\n\n"
            "Um consultor irá responder."
        )

        cliente["bot_pausado"] = True
        cliente["ultima_interacao_humana"] = datetime.now().isoformat()


    salvar_clientes(clientes)


# =========================
# WEBHOOK ZAPI
# =========================

@app.route("/webhook", methods=["GET","POST"])
def webhook():

    if request.method == "GET":
        return "Webhook online", 200

    try:

        data = request.json or {}

        print("Webhook recebido:")
        print(json.dumps(data, indent=4, ensure_ascii=False))

        phone = data.get("phone") or data.get("from") or ""

        mensagem = ""

        if isinstance(data.get("text"), dict):
            mensagem = data.get("text", {}).get("message", "")

        elif isinstance(data.get("text"), str):
            mensagem = data.get("text", "")

        elif "message" in data:
            mensagem = data.get("message", "")

        from_me = data.get("fromMe", False)

        phone = str(phone).replace("@c.us","").replace("@s.whatsapp.net","")

        processar_mensagem(phone, mensagem, from_me)

        return "ok", 200

    except Exception as e:
        print("Erro webhook:", e)
        return "ok", 200


# =========================
# ROTA VALIDAÇÃO ZAPI
# =========================

@app.route("/zapi", methods=["GET","POST"])
def zapi():
    return jsonify({"status":"online"}), 200


# =========================
# HOME
# =========================

@app.route("/", methods=["GET"])
def home():
    return "Bot Yamaha online", 200


# =========================
# START
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)