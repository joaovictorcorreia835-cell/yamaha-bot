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

print("INSTANCE:", ZAPI_INSTANCE_ID)
print("TOKEN:", ZAPI_TOKEN)
print("CLIENT:", ZAPI_CLIENT_TOKEN)
print("URL_ENVIO:", f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text")

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

Responda com uma das opções abaixo:

AGENDAR
CONSULTOR

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
            headers=headers,
            timeout=30
        )

        print(f"[ENVIO] {numero} -> {response.status_code}")
        print(response.text)

        return response.status_code

    except Exception as e:
        print(f"[ERRO EXCEÇÃO] {numero} -> {e}")
        return None


# ==========================================
# DISPARO
# ==========================================
def disparar():
    print("Iniciando disparo revisão...")

    try:
        df = pd.read_excel(ARQUIVO_PLANILHA, dtype=str)
    except Exception as e:
        print("Erro ao abrir planilha:", e)
        return

    colunas_necessarias = [
        "NOME",
        "TELEFONE",
        "MODELO",
        "Periodo",
        "STATUS DE ENVIO",
        "DATA DE ENVIO"
    ]

    for coluna in colunas_necessarias:
        if coluna not in df.columns:
            df[coluna] = ""

    df = df.fillna("")

    for index, row in df.iterrows():
        status = str(row.get("STATUS DE ENVIO", "")).strip().upper()

        # pula somente quem já foi enviado
        if status == "ENVIADO":
            print(f"Linha {index + 2}: já enviada, pulando.")
            continue

        nome = str(row.get("NOME", "")).strip()
        telefone = str(row.get("TELEFONE", "")).strip()
        modelo = str(row.get("MODELO", "")).strip()
        periodo = str(row.get("Periodo", "")).strip()

        print(f"Processando linha {index + 2}: {nome} | {telefone} | {modelo} | {periodo}")

        if not nome or not telefone or not modelo or not periodo:
            df.loc[index, "STATUS DE ENVIO"] = "ERRO"
            df.loc[index, "DATA DE ENVIO"] = "DADOS INCOMPLETOS"
            print(f"Linha {index + 2}: dados incompletos.")
            continue

        mensagem = criar_mensagem(nome, modelo, periodo)
        status_envio = enviar_mensagem(telefone, mensagem)

        if status_envio == 200:
            df.loc[index, "STATUS DE ENVIO"] = "ENVIADO"
            df.loc[index, "DATA DE ENVIO"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            print(f"Linha {index + 2}: enviado com sucesso para {nome}.")
        else:
            df.loc[index, "STATUS DE ENVIO"] = "ERRO"
            df.loc[index, "DATA DE ENVIO"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            print(f"Linha {index + 2}: falha no envio para {nome}.")

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    df.to_excel(ARQUIVO_PLANILHA, index=False)
    print("Disparo finalizado")


# ==========================================
# EXECUTAR
# ==========================================
if __name__ == "__main__":
    disparar()