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


url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"


clientes = {}
mensagens_processadas = set()
fila_mensagens = deque(maxlen=2000)


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
# CLIENTE
# ==========================================

def iniciar_cliente(telefone):

    if telefone not in clientes:

        clientes[telefone] = {
            "etapa": "menu",
            "ultima_interacao": time.time(),
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
        "ultima_interacao": time.time(),
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


# ==========================================
# ENVIO MENSAGEM
# ==========================================

def enviar_mensagem(telefone, mensagem):

    payload = {
        "phone": telefone,
        "message": mensagem
    }

    try:

        response = requests.post(
            url_envio,
            json=payload,
            headers={
                "Client-Token": ZAPI_CLIENT_TOKEN
            }
        )

        log_info("Mensagem enviada", telefone)
        return True

    except Exception as e:

        log_erro("Erro envio", e)
        return False


# ==========================================
# MENU
# ==========================================

def enviar_menu(telefone):

    mensagem = (
        "Olá 👋\n\n"
        "🏍️ *Pós-Vendas Motoshow Yamaha*\n\n"

        "Escolha uma opção:\n\n"

        "1️⃣ Agendar Revisão\n"
        "2️⃣ Peças\n"
        "3️⃣ Acessórios\n"
        "4️⃣ Garantia\n"
        "5️⃣ Logista / Atacado\n"
        "6️⃣ Falar com Atendente\n\n"

        "Ou escreva diretamente o que precisa."
    )

    enviar_mensagem(telefone, mensagem)


# ==========================================
# IA — PREENCHIMENTO AUTOMÁTICO
# ==========================================

def preencher_dados_ia(telefone, dados):

    if telefone not in clientes:
        iniciar_cliente(telefone)

    if dados.get("modelo"):
        clientes[telefone]["modelo"] = dados["modelo"]

    if dados.get("nome"):
        clientes[telefone]["nome"] = dados["nome"]

    if dados.get("cpf"):
        clientes[telefone]["cpf"] = dados["cpf"]

    if dados.get("ano"):
        clientes[telefone]["ano"] = dados["ano"]

    if dados.get("revisao"):
        clientes[telefone]["revisao"] = dados["revisao"]

    if dados.get("dia"):
        clientes[telefone]["dia_texto"] = dados["dia"]

    if dados.get("data"):
        clientes[telefone]["data"] = dados["data"]

    if dados.get("horario"):
        clientes[telefone]["horario"] = dados["horario"]

    if dados.get("item_adicional"):
        clientes[telefone]["itens"] = dados["item_adicional"]


# ==========================================
# WEBHOOK
# ==========================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        data = request.json or {}

        telefone = data.get("phone")
        texto = data.get("message")

        if not telefone or not texto:
            return jsonify({"status": "ok"})

        texto = str(texto).strip()

        iniciar_cliente(telefone)
        clientes[telefone]["ultima_interacao"] = time.time()

        # =====================================
        # SAIR DO ATENDIMENTO HUMANO
        # =====================================

        if clientes[telefone].get("atendimento_humano"):

            if texto.lower() in ["menu", "voltar", "oi", "inicio", "início"]:

                resetar_cliente(telefone)

                enviar_mensagem(
                    telefone,
                    "🔄 Retornando ao menu automático...\n\n"
                    "Olá 👋\n\n"
                    "🏍️ *Pós-Vendas Motoshow Yamaha*\n\n"
                    "1️⃣ Agendar Revisão\n"
                    "2️⃣ Peças\n"
                    "3️⃣ Acessórios\n"
                    "4️⃣ Garantia\n"
                    "5️⃣ Logista / Atacado\n"
                    "6️⃣ Falar com Atendente\n\n"
                    "Ou escreva diretamente o que precisa."
                )

                return jsonify({"status": "ok"})

            return jsonify({"status": "ok", "modo": "humano"})
        # =====================================
        # IA
        # =====================================

        resultado_ia = classificar_intencao(texto)

        intencao = resultado_ia.get("intencao")
        dados = resultado_ia.get("dados_extraidos", {})

        preencher_dados_ia(telefone, dados)
        etapa = clientes[telefone]["etapa"]

        # =====================================
        # MENU IA
        # =====================================

        if intencao == "menu":

            resetar_cliente(telefone)
            enviar_menu(telefone)

            return jsonify({"status": "ok"})


        # =====================================
        # HUMANO
        # =====================================

        if intencao == "humano":

            clientes[telefone]["atendimento_humano"] = True

            enviar_mensagem(
                telefone,
                "👨‍💼 Atendimento humano acionado\n\n"
                "Nossa equipe irá assumir seu atendimento.\n\n"
                "Para voltar ao menu automático, envie *menu*."
            )

            return jsonify({"status": "ok"})


        # =====================================
        # AGENDAR REVISÃO IA
        # =====================================

        if intencao == "agendar_revisao":

            clientes[telefone]["etapa"] = "revisao"

        etapa = clientes[telefone]["etapa"]


        # =====================================
        # FLUXO REVISÃO
        # =====================================

        if etapa == "revisao":

            dados = clientes[telefone]

            if not dados["modelo"]:

                enviar_mensagem(
                    telefone,
                    "Qual modelo da moto ?\n\n"
                    "Exemplo:\n"
                    "Fazer 250\n"
                    "FLUO\n"
                    "Lander"
                )

                return jsonify({"status": "ok"})


            if not dados["nome"]:

                enviar_mensagem(
                    telefone,
                    "Informe seu nome completo:"
                )

                return jsonify({"status": "ok"})


            if not dados["cpf"]:

                enviar_mensagem(
                    telefone,
                    "Informe seu CPF:"
                )

                return jsonify({"status": "ok"})


            if not dados["ano"]:

                enviar_mensagem(
                    telefone,
                    "Qual o ano da moto ?"
                )

                return jsonify({"status": "ok"})


            if not dados["revisao"]:

                enviar_mensagem(
                    telefone,
                    "Qual revisão ?\n\n"
                    "1 - 1000km\n"
                    "2 - 3000km\n"
                    "3 - 6000km\n"
                    "4 - 9000km\n"
                    "5 - 12000km +"
                )

                return jsonify({"status": "ok"})


            if not dados["dia_texto"]:

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

                return jsonify({"status": "ok"})


            if not dados["data"]:

                enviar_mensagem(
                    telefone,
                    "Informe a data desejada\n\n"
                    "Exemplo: 13/04/2026"
                )

                return jsonify({"status": "ok"})


            if not dados["horario"]:

                revisao = dados["revisao"]

                if revisao in ["1", "2"]:

                    horarios = [
                        "08:00",
                        "09:00",
                        "10:00",
                        "11:00",
                        "12:00",
                        "13:00",
                        "14:00",
                        "15:00"
                    ]

                else:

                    horarios = ["08:00"]

                clientes[telefone]["horarios_disponiveis"] = horarios

                mensagem = "Escolha o horário:\n\n"

                for i, h in enumerate(horarios):

                    mensagem += f"{i+1} - {h}\n"

                enviar_mensagem(telefone, mensagem)

                return jsonify({"status": "ok"})


            if not dados["itens"]:

                enviar_mensagem(
                    telefone,
                    "Deseja adicionar algum item ?\n\n"
                    "Exemplo:\n"
                    "Filtro de ar\n"
                    "Pastilha de freio\n"
                    "Slider\n\n"
                    "Ou responda 2 para não"
                )

                clientes[telefone]["etapa"] = "venda_adicional"

                return jsonify({"status": "ok"})
        # =====================================
        # VENDA ADICIONAL
        # =====================================

        if etapa == "venda_adicional":

            if texto.lower() in ["2", "nao", "não"]:

                clientes[telefone]["itens"] = "Nenhum"

            else:

                clientes[telefone]["itens"] = texto


            dados = clientes[telefone]


            resumo = (
                "📅 *Agendamento Confirmado*\n\n"

                f"👤 Nome: {dados['nome']}\n"
                f"📄 CPF: {dados['cpf']}\n"
                f"🏍️ Modelo: {dados['modelo']}\n"
                f"📅 Ano: {dados['ano']}\n"
                f"🔧 Revisão: {dados['revisao']}\n"
                f"📆 Dia: {dados['dia_texto']}\n"
                f"📆 Data: {dados['data']}\n"
                f"⏰ Horário: {dados['horario']}\n"
                f"🛠️ Itens: {dados['itens']}\n\n"

                "Equipe Motoshow Yamaha"
            )


            enviar_mensagem(
                telefone,
                resumo
            )


            salvar_atendimento(telefone)

            resetar_cliente(telefone)

            return jsonify({"status": "ok"})


        # =====================================
        # MENU NUMERICO
        # =====================================

        if texto == "1":

            clientes[telefone]["etapa"] = "revisao"
            return jsonify({"status": "ok"})


        if texto == "2":

            enviar_mensagem(
                telefone,
                "Informe a peça desejada"
            )

            return jsonify({"status": "ok"})


        if texto == "3":

            enviar_mensagem(
                telefone,
                "Informe o acessório desejado"
            )

            return jsonify({"status": "ok"})


        if texto == "4":

            enviar_mensagem(
                telefone,
                "Informe o problema para garantia"
            )

            return jsonify({"status": "ok"})


        if texto == "5":

            enviar_mensagem(
                telefone,
                "Atendimento logista acionado"
            )

            return jsonify({"status": "ok"})


        if texto == "6":

            clientes[telefone]["atendimento_humano"] = True

            enviar_mensagem(
                telefone,
                "👨‍💼 Atendimento humano acionado\n\n"
                "Nossa equipe irá assumir seu atendimento.\n\n"
                "Para voltar ao menu automático, envie *menu*."
            )

            return jsonify({"status": "ok"})


        return jsonify({"status": "ok"})


    except Exception as e:

        log_erro("Erro webhook", e)

        return jsonify({"status": "erro"})


# ==========================================
# SALVAR BANCO
# ==========================================

def salvar_atendimento(telefone):

    try:

        db = SessionLocal()

        dados = clientes.get(telefone, {})

        atendimento = Atendimento(

            telefone=telefone,
            nome=dados.get("nome"),
            modelo=dados.get("modelo"),
            ano=dados.get("ano"),
            revisao=dados.get("revisao"),
            cpf=dados.get("cpf"),
            dia_semana=dados.get("dia_texto"),
            data_agendada=dados.get("data"),
            horario=dados.get("horario"),
            itens=dados.get("itens"),
            setor="Revisão",
            status="Agendado"

        )

        db.add(atendimento)
        db.commit()
        db.close()

    except Exception as e:

        log_erro("Erro salvar", e)


# ==========================================
# INATIVIDADE
# ==========================================

def verificar_inatividade():

    while True:

        try:

            agora = time.time()

            for telefone, dados in list(clientes.items()):

                if agora - dados["ultima_interacao"] > TEMPO_INATIVIDADE:

                    enviar_mensagem(
                        telefone,
                        "Atendimento encerrado por inatividade.\n\n"
                        "Digite menu para iniciar novamente"
                    )

                    resetar_cliente(telefone)

        except Exception as e:

            log_erro("Erro inatividade", e)

        time.sleep(60)


threading.Thread(
    target=verificar_inatividade,
    daemon=True
).start()


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000))
    )