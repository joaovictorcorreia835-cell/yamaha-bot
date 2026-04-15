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

ARQUIVO_PLANILHA = "templates/data/clientes.xlsx"
INTERVALO_ENTRE_ENVIOS = 90  # segundos

URL_ENVIO = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

COLUNAS_OBRIGATORIAS = [
    "NOME",
    "TELEFONE",
    "PERIODO_REVISAO",
    "MODELO",
    "DATA_DISPARO",
    "STATUS_ENVIO",
    "STATUS_RETORNO",
    "DATA_RETORNO",
    "ULTIMA_INTERACAO",
    "FOLLOWUP_1",
    "FOLLOWUP_2",
    "OBS",
    "LINK_ORIGEM",
    "INTENCAO_IA",
    "PROXIMA_ACAO",
    "NIVEL_INTERESSE",
]

STATUS_ENVIO_PERMITIDOS = ["", "PENDENTE"]


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

Responda com uma das opções:
1️⃣ *AGENDAR*
2️⃣ *FALAR COM CONSULTOR*
3️⃣ *DEPOIS*

Equipe Motoshow Yamaha 🏍️
"""
    return mensagem


# ==========================================
# GARANTIR COLUNAS
# ==========================================
def garantir_colunas(df):
    for coluna in COLUNAS_OBRIGATORIAS:
        if coluna not in df.columns:
            df[coluna] = ""
    return df


# ==========================================
# NORMALIZAR TELEFONE
# ==========================================
def normalizar_telefone(numero):
    numero = str(numero).strip()
    numero = numero.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    return numero


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

    try:
        df = pd.read_excel(ARQUIVO_PLANILHA, dtype=str).fillna("")
    except Exception as e:
        print(f"❌ Erro ao abrir a planilha {ARQUIVO_PLANILHA}: {e}")
        return

    df = garantir_colunas(df)

    for index, row in df.iterrows():
        status_envio = str(row.get("STATUS_ENVIO", "")).strip().upper()

        if status_envio not in STATUS_ENVIO_PERMITIDOS:
            print("⏭ Pulando linha já tratada:", row.get("NOME", "Sem nome"), "-", status_envio)
            continue

        nome = str(row.get("NOME", "")).strip()
        numero = normalizar_telefone(row.get("TELEFONE", ""))
        modelo = str(row.get("MODELO", "")).strip()
        periodo = str(row.get("PERIODO_REVISAO", "")).strip()

        if not nome or not numero:
            print(f"⚠ Linha {index + 2} ignorada - falta NOME ou TELEFONE")
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = "Falta nome ou telefone"
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            continue

        if not modelo or not periodo:
            print(f"⚠ Linha {index + 2} ignorada - falta MODELO ou PERIODO_REVISAO")
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = "Falta modelo ou período de revisão"
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            continue

        mensagem = criar_mensagem(nome, modelo, periodo)

        print(f"📤 Enviando para: {nome} - {numero}")

        enviado = enviar_mensagem(numero, mensagem)

        if enviado:
            agora = datetime.now().strftime("%d/%m/%Y %H:%M")

            df.at[index, "DATA_DISPARO"] = agora
            df.at[index, "STATUS_ENVIO"] = "ENVIADO"
            df.at[index, "STATUS_RETORNO"] = "AGUARDANDO"
            df.at[index, "ULTIMA_INTERACAO"] = agora
            df.at[index, "FOLLOWUP_1"] = ""
            df.at[index, "FOLLOWUP_2"] = ""
            df.at[index, "OBS"] = "Disparo enviado com sucesso"
            df.at[index, "LINK_ORIGEM"] = "CAMPANHA_REVISAO"
            df.at[index, "INTENCAO_IA"] = ""
            df.at[index, "PROXIMA_ACAO"] = "AGUARDAR_RETORNO"
            df.at[index, "NIVEL_INTERESSE"] = ""

            df.to_excel(ARQUIVO_PLANILHA, index=False)
            print("✅ Enviado com sucesso:", nome)
        else:
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = "Falha ao enviar mensagem"
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            print("❌ Falha no envio:", nome)

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    print("===================================")
    print("✅ Disparo finalizado")
    print("===================================")


if __name__ == "__main__":
    disparar()