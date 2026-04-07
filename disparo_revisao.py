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

    df = pd.read_excel(ARQUIVO_PLANILHA, dtype=str).fillna("")

    if "STATUS DE ENVIO" not in df.columns:
        df["STATUS DE ENVIO"] = ""

    if "DATA_ENVIO" not in df.columns:
        df["DATA_ENVIO"] = ""

    for index, row in df.iterrows():
        status = str(row.get("STATUS DE ENVIO", "")).strip().upper()

        if status == "ENVIADO":
            print("Pulando já enviado:", row.get("NOME", "Sem nome"))
            continue

        nome = str(row.get("NOME", "")).strip()
        numero = str(row.get("TELEFONE", "")).strip()
        modelo = str(row.get("MODELO", "")).strip()
        periodo = str(row.get("periodo", "")).strip()

        if not nome or not numero:
            print("Linha ignorada por falta de nome ou telefone.")
            continue

        mensagem = criar_mensagem(nome, modelo, periodo)

        enviar_mensagem(numero, mensagem)

        df.at[index, "STATUS DE ENVIO"] = "ENVIADO"
        df.at[index, "DATA_ENVIO"] = datetime.now().strftime("%d/%m/%Y %H:%M")

        df.to_excel(ARQUIVO_PLANILHA, index=False)

        print("Enviado:", nome)

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    print("Disparo finalizado")


if __name__ == "__main__":
    disparar()