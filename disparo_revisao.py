import pandas as pd
import requests
import time
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# ==========================================
# CONFIG
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")

URL_ENVIO = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

ARQUIVO_PLANILHA = "clientes.xlsx"
INTERVALO_ENTRE_ENVIOS = 15


# ==========================================
# CRIAR MENSAGEM
# ==========================================
def criar_mensagem(nome, modelo, periodo):

    mensagem = f"""Olá {nome} 👋

Aqui é da Equipe Motoshow Yamaha 🏍️

Sua {modelo} está no período da revisão de {periodo} meses.

🎯 Campanha Especial Pós-Vendas:

✔ Peças Originais Yamaha  
✔ Técnicos Especializados  
✔ Garantia de Serviço  

Deseja agendar sua revisão?

Digite:

1️⃣ Agendar Revisão  
2️⃣ Falar com Consultor

Equipe Motoshow Yamaha
"""

    return mensagem


# ==========================================
# ENVIAR MENSAGEM
# ==========================================
def enviar_mensagem(numero, mensagem):

    payload = {
        "phone": numero,
        "message": mensagem
    }

    headers = {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN
    }

    try:
        response = requests.post(
            URL_ENVIO,
            json=payload,
            headers=headers
        )

        return response.status_code

    except Exception as e:
        print("Erro:", e)
        return None


# ==========================================
# DISPARO
# ==========================================
def disparar():

    print("Iniciando disparo revisão...")

    df = pd.read_excel(ARQUIVO_PLANILHA)

    for index, row in df.iterrows():

        status = str(row.get("STATUS DE ENVIO", ""))

        if status == "ENVIADO":
            continue

        nome = str(row["NOME"])
        telefone = str(row["TELEFONE"])
        modelo = str(row["MODELO"])
        periodo = str(row["Periodo"])

        mensagem = criar_mensagem(nome, modelo, periodo)

        status_envio = enviar_mensagem(telefone, mensagem)

        if status_envio == 200:
            df.loc[index, "STATUS DE ENVIO"] = "ENVIADO"
            df.loc[index, "DATA DE ENVIO"] = datetime.now().strftime("%d/%m/%Y %H:%M")

            print(f"Enviado para {nome}")

        else:
            df.loc[index, "STATUS DE ENVIO"] = "ERRO"

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    df.to_excel(ARQUIVO_PLANILHA, index=False)

    print("Disparo finalizado")


# ==========================================
# EXECUTAR
# ==========================================
if __name__ == "__main__":
    disparar()