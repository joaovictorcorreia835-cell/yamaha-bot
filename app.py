from flask import Flask, request, jsonify
import requests
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# =========================
# CONFIGURAÇÕES
# =========================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "").strip()
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "").strip()
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", 5000))

ARQUIVO_CLIENTES = "clientes.json"


# =========================
# FUNÇÕES DE ARQUIVO
# =========================
def carregar_clientes():
    if not os.path.exists(ARQUIVO_CLIENTES):
        return {}

    try:
        with open(ARQUIVO_CLIENTES, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("Erro ao carregar clientes:", e)
        return {}


def salvar_clientes(clientes):
    with open(ARQUIVO_CLIENTES, "w", encoding="utf-8") as f:
        json.dump(clientes, f, ensure_ascii=False, indent=4)


def buscar_cliente(phone):
    clientes = carregar_clientes()

    if phone not in clientes:
        clientes[phone] = {
            "phone": phone,
            "nome": "",
            "modelo_moto": "",
            "periodo_revisao": "",
            "bairro": "",
            "data_desejada": "",
            "etapa": "menu",
            "atendimento_humano": False,
            "ultima_msg_humana": "",
            "ultima_interacao": datetime.now().isoformat(timespec="seconds")
        }
        salvar_clientes(clientes)

    return clientes[phone]


def salvar_cliente(phone, dados_cliente):
    clientes = carregar_clientes()
    dados_cliente["ultima_interacao"] = datetime.now().isoformat(timespec="seconds")
    clientes[phone] = dados_cliente
    salvar_clientes(clientes)


def ativar_atendimento_humano(phone):
    cliente = buscar_cliente(phone)
    cliente["atendimento_humano"] = True
    cliente["ultima_msg_humana"] = datetime.now().isoformat(timespec="seconds")
    salvar_cliente(phone, cliente)


def liberar_bot(phone):
    cliente = buscar_cliente(phone)
    cliente["atendimento_humano"] = False
    cliente["etapa"] = "menu"
    salvar_cliente(phone, cliente)


def passou_1_hora_sem_msg_humana(cliente):
    ultima_msg_humana = cliente.get("ultima_msg_humana", "").strip()

    if not ultima_msg_humana:
        return True

    try:
        data_ultima = datetime.fromisoformat(ultima_msg_humana)
        return datetime.now() - data_ultima >= timedelta(hours=1)
    except Exception:
        return True


# =========================
# ENVIO DE MENSAGEM
# =========================
def enviar_mensagem(phone, texto):
    if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN or not ZAPI_CLIENT_TOKEN:
        print("Erro: credenciais da Z-API não configuradas no .env")
        return False

    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "phone": phone,
        "message": texto
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print("Resposta envio:", response.status_code, response.text)
        return response.status_code in [200, 201]
    except Exception as e:
        print("Erro ao enviar mensagem:", e)
        return False


# =========================
# TEXTOS DO BOT
# =========================
def mensagem_menu():
    return (
        "Olá! Seja bem-vindo ao atendimento.\n\n"
        "Escolha uma opção:\n"
        "1 - Agendar revisão\n"
        "2 - Atendimento humano\n"
        "3 - Encerrar"
    )


def mensagem_humano():
    return (
        "Atendimento humano iniciado.\n\n"
        "Um consultor irá continuar seu atendimento em instantes."
    )


def mensagem_encerramento():
    return "Atendimento encerrado. Quando precisar, é só mandar uma mensagem."


# =========================
# PROCESSAMENTO PRINCIPAL
# =========================
def processar_mensagem(phone, mensagem, from_me):
    if not phone:
        return

    mensagem = (mensagem or "").strip()
    mensagem_lower = mensagem.lower()

    cliente = buscar_cliente(phone)

    # ---------------------------------
    # MENSAGEM ENVIADA POR VOCÊ
    # #bot = reativa
    # qualquer outra = pausa
    # ---------------------------------
    if from_me:
        if mensagem_lower == "#bot":
            liberar_bot(phone)
            print(f"[BOT REATIVADO MANUALMENTE] {phone}")
            return

        ativar_atendimento_humano(phone)
        print(f"[MENSAGEM SUA] Bot pausado para {phone}")
        return

    # ---------------------------------
    # SE ESTIVER EM ATENDIMENTO HUMANO
    # MAS JÁ PASSOU 1 HORA SEM MENSAGEM SUA
    # REATIVA AUTOMATICAMENTE
    # ---------------------------------
    if cliente.get("atendimento_humano", False):
        if passou_1_hora_sem_msg_humana(cliente):
            liberar_bot(phone)
            cliente = buscar_cliente(phone)
            print(f"[BOT REATIVADO AUTOMATICAMENTE APÓS 1H] {phone}")
        else:
            print(f"[BOT PAUSADO] Sem resposta para {phone}")
            return

    etapa = cliente.get("etapa", "menu")

    # ---------------------------------
    # SAUDAÇÕES
    # ---------------------------------
    if mensagem_lower in ["oi", "olá", "ola", "menu", "bom dia", "boa tarde", "boa noite"]:
        cliente["etapa"] = "menu"
        salvar_cliente(phone, cliente)
        enviar_mensagem(phone, mensagem_menu())
        return

    # ---------------------------------
    # MENU PRINCIPAL
    # ---------------------------------
    if mensagem == "1":
        cliente["etapa"] = "agendamento_nome"
        salvar_cliente(phone, cliente)
        enviar_mensagem(phone, "Perfeito! Vamos agendar sua revisão.\n\nInforme seu nome:")
        return

    if mensagem == "2":
        ativar_atendimento_humano(phone)
        enviar_mensagem(phone, mensagem_humano())
        return

    if mensagem == "3":
        cliente["etapa"] = "encerrado"
        salvar_cliente(phone, cliente)
        enviar_mensagem(phone, mensagem_encerramento())
        return

    # ---------------------------------
    # FLUXO DE AGENDAMENTO
    # ---------------------------------
    if etapa == "agendamento_nome":
        cliente["nome"] = mensagem
        cliente["etapa"] = "agendamento_modelo"
        salvar_cliente(phone, cliente)
        enviar_mensagem(phone, "Qual o modelo da moto?")
        return

    if etapa == "agendamento_modelo":
        cliente["modelo_moto"] = mensagem
        cliente["etapa"] = "agendamento_periodo"
        salvar_cliente(phone, cliente)
        enviar_mensagem(phone, "Informe o período da revisão da moto:")
        return

    if etapa == "agendamento_periodo":
        cliente["periodo_revisao"] = mensagem
        cliente["etapa"] = "agendamento_bairro"
        salvar_cliente(phone, cliente)
        enviar_mensagem(phone, "Qual o seu bairro?")
        return

    if etapa == "agendamento_bairro":
        cliente["bairro"] = mensagem
        cliente["etapa"] = "agendamento_data"
        salvar_cliente(phone, cliente)
        enviar_mensagem(phone, "Qual a melhor data para o agendamento?")
        return

    if etapa == "agendamento_data":
        cliente["data_desejada"] = mensagem
        cliente["etapa"] = "finalizado"
        salvar_cliente(phone, cliente)

        resumo = (
            "Agendamento recebido com sucesso.\n\n"
            f"Nome: {cliente.get('nome', '')}\n"
            f"Modelo da moto: {cliente.get('modelo_moto', '')}\n"
            f"Período da revisão: {cliente.get('periodo_revisao', '')}\n"
            f"Bairro: {cliente.get('bairro', '')}\n"
            f"Data desejada: {cliente.get('data_desejada', '')}\n\n"
            "Em breve nossa equipe confirmará o atendimento."
        )
        enviar_mensagem(phone, resumo)
        return

    # ---------------------------------
    # CASO NÃO RECONHEÇA A MENSAGEM
    # ---------------------------------
    enviar_mensagem(phone, mensagem_menu())


# =========================
# WEBHOOK
# =========================
@app.route("/webhook", methods=["GET", "POST"])
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

        phone = str(phone).replace("@c.us", "").replace("@s.whatsapp.net", "").strip()

        processar_mensagem(phone, mensagem, from_me)

        return "ok", 200

    except Exception as e:
        print("Erro no webhook:", e)
        return "ok", 200
# =========================
# ROTA INICIAL
# =========================
@app.route("/", methods=["GET"])
def home():
    return "Bot Z-API online.", 200



# =========================
# INICIAR SERVIDOR
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
