import os
import time
import pandas as pd
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")

URL_ENVIO = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

ARQUIVO_PLANILHA = "clientes.xlsx"
INTERVALO_ENTRE_ENVIOS = 15


def criar_mensagem(nome, modelo, periodo):

    mensagem = f"""Olá {nome} 👋

Aqui é da Equipe Pós-Vendas Motoshow Yamaha 🏍️

Sua {modelo} está no período da revisão de {periodo} meses.

🎯 Campanha Especial

Digite:

1️⃣ Agendar Revisão
2️⃣ Falar com Consultor

Equipe Motoshow Yamaha
"""

    return mensagem


def enviar_mensagem(numero, mensagem):

    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN
    }

    payload = {
        "phone": numero,
        "message": mensagem
    }

    requests.post(URL_ENVIO, json=payload, headers=headers)


def disparar():

    print("Iniciando disparo...")

    df = pd.read_excel(ARQUIVO_PLANILHA)

    for index, row in df.iterrows():

        status = str(row.get("STATUS DE ENVIO", "")).upper()

        if status == "ENVIADO":
            print("Pulando já enviado:", row["NOME"])
            continue

        nome = row["NOME"]
        numero = str(row["TELEFONE"])
        modelo = row["MODELO"]
        periodo = row["periodo"]

        mensagem = criar_mensagem(nome, modelo, periodo)

        enviar_mensagem(numero, mensagem)

        df.at[index, "STATUS DE ENVIO"] = "ENVIADO"
        df.at[index, "DATA_ENVIO"] = datetime.now().strftime("%d/%m/%Y %H:%M")

        print("Enviado:", nome)

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    df.to_excel(ARQUIVO_PLANILHA, index=False)

    print("Disparo finalizado")


if __name__ == "__main__":
    disparar()