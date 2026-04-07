import os
import time
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# CONFIG
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")

ARQUIVO_PLANILHA = "clientes.xlsx"
INTERVALO_ENTRE_ENVIOS = 15  # segundos

URL_ENVIO = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"


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
✔ Agendamento rápido

📅 Agende agora sua revisão e mantenha sua Yamaha sempre em dia.

Digite *AGENDAR* para agendar sua revisão.

Equipe Motoshow Yamaha 🏍️
"""
    return mensagem


# ==========================================
# ENVIAR MENSAGEM
# ==========================================
def enviar_mensagem(numero, mensagem):
    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "phone": numero,
        "message": mensagem
    }

    try:
        response = requests.post(
            URL_ENVIO,
            json=payload,
            headers=headers,
            timeout=30
        )

        print("Status Code:", response.status_code)
        print("Resposta:", response.text)

        if response.status_code in [200, 201]:
            return True

        return False

    except Exception as e:
        print("Erro envio:", e)
        return False


# ==========================================
# DISPARO
# ==========================================
def disparar():
    print("===================================")
    print("🚀 Iniciando disparo...")
    print("===================================")

    if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN or not ZAPI_CLIENT_TOKEN:
        print("❌ Erro: variáveis da Z-API não carregadas do .env")
        print("Verifique ZAPI_INSTANCE_ID, ZAPI_TOKEN e ZAPI_CLIENT_TOKEN")
        return

    df = pd.read_excel(ARQUIVO_PLANILHA, dtype=str).fillna("")

    if "STATUS DE ENVIO" not in df.columns:
        df["STATUS DE ENVIO"] = ""

    if "DATA_ENVIO" not in df.columns:
        df["DATA_ENVIO"] = ""

    for index, row in df.iterrows():
        status = str(row.get("STATUS DE ENVIO", "")).strip().upper()

        if status == "ENVIADO":
            print("⏭ Pulando já enviado:", row.get("NOME", "Sem nome"))
            continue

        nome = str(row.get("NOME", "")).strip()
        numero = str(row.get("TELEFONE", "")).strip()
        modelo = str(row.get("MODELO", "")).strip()
        periodo = str(row.get("periodo", "")).strip()

        if not nome or not numero:
            print("⚠ Linha ignorada - falta nome ou telefone")
            continue

        mensagem = criar_mensagem(nome, modelo, periodo)

        print(f"📤 Enviando para: {nome} {numero}")

        enviado = enviar_mensagem(numero, mensagem)

        if enviado:
            df.at[index, "STATUS DE ENVIO"] = "ENVIADO"
            df.at[index, "DATA_ENVIO"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            print("✅ Enviado com sucesso:", nome)
        else:
            print("❌ Falha no envio:", nome)

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    print("===================================")
    print("✅ Disparo finalizado")
    print("===================================")


if __name__ == "__main__":
    disparar()