import pandas as pd
import requests
import time
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")

url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"


# ===============================
# CRIAR MENSAGEM
# ===============================
def criar_mensagem(nome, modelo, periodo):

    mensagem = f"""Olá {nome} 👋

Aqui é da Equipe Motoshow Yamaha 🏍️

Sua {modelo} está no período da revisão de {periodo} meses.

🎯 Campanha Especial Pós-Vendas:

✔ Peças Originais Yamaha
✔ Técnicos Especializados
✔ Condições Exclusivas

Deseja agendar sua revisão?

1️⃣ Agendar revisão
2️⃣ Consultar valores
3️⃣ Falar com atendente

Equipe Motoshow Yamaha"""

    return mensagem


# ===============================
# ENVIO
# ===============================
def enviar_mensagem(telefone, mensagem):

    payload = {
        "phone": str(telefone),
        "message": mensagem
    }

    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)

    return response


# ===============================
# LER PLANILHA
# ===============================

arquivo = "clientes.xlsx"

df = pd.read_excel(arquivo)

df.columns = [str(col).strip().upper() for col in df.columns]


# ===============================
# GARANTIR COLUNAS
# ===============================

colunas = [
    "NOME",
    "TELEFONE",
    "MODELO",
    "PERIODO DE REVISÃO",
    "STATUS DE ENVIO",
    "DATA DE ENVIO"
]

for col in colunas:
    if col not in df.columns:
        df[col] = ""


# ===============================
# LOOP ENVIO
# ===============================

for index, cliente in df.iterrows():

    nome = str(cliente["NOME"]).strip()
    telefone = str(cliente["TELEFONE"]).strip()
    modelo = str(cliente["MODELO"]).strip()
    status = str(cliente["STATUS DE ENVIO"]).strip().upper()

    try:
        periodo = int(cliente["PERIODO DE REVISÃO"])
    except:
        df.at[index, "STATUS DE ENVIO"] = "PERIODO INVALIDO"
        continue

    # NÃO ENVIAR NOVAMENTE
    if status == "ENVIADO":
        continue

    mensagem = criar_mensagem(nome, modelo, periodo)

    print(f"Enviando para {nome} - {telefone}")

    try:
        resposta = enviar_mensagem(telefone, mensagem)

        print("Status:", resposta.status_code)

        if resposta.status_code in [200, 201]:

            df.at[index, "STATUS DE ENVIO"] = "ENVIADO"
            df.at[index, "DATA DE ENVIO"] = datetime.now().strftime("%d/%m/%Y %H:%M")

        else:
            df.at[index, "STATUS DE ENVIO"] = f"ERRO {resposta.status_code}"

    except Exception as e:

        print("Erro:", e)
        df.at[index, "STATUS DE ENVIO"] = "ERRO ENVIO"

    # ===============================
    # INTERVALO 15 SEGUNDOS
    # ===============================

    print("Aguardando 15 segundos...")
    time.sleep(15)


# ===============================
# SALVAR PLANILHA
# ===============================

df.to_excel(arquivo, index=False)

print("Disparo Finalizado")