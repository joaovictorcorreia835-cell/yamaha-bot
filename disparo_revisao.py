import pandas as pd
import requests
import time
import os
import re
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")

url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

ARQUIVO = "clientes.xlsx"
INTERVALO_ENVIO = 15  # segundos


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
# NORMALIZAR TELEFONE
# ===============================
def limpar_telefone(telefone):
    if pd.isna(telefone):
        return ""

    telefone = str(telefone).strip()

    # remove .0 quando vier de número do Excel
    if telefone.endswith(".0"):
        telefone = telefone[:-2]

    # mantém só números
    telefone = re.sub(r"\D", "", telefone)

    return telefone


# ===============================
# VALIDAR PERÍODO
# ===============================
def tratar_periodo(valor):
    if pd.isna(valor):
        return None

    texto = str(valor).strip().replace(",", ".")
    try:
        return int(float(texto))
    except Exception:
        return None


# ===============================
# ENVIO
# ===============================
def enviar_mensagem(telefone, mensagem):
    payload = {
        "phone": telefone,
        "message": mensagem
    }

    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    return response


# ===============================
# VALIDAR CONFIG
# ===============================
if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN or not ZAPI_CLIENT_TOKEN:
    raise ValueError("Verifique o .env: ZAPI_INSTANCE_ID, ZAPI_TOKEN e ZAPI_CLIENT_TOKEN são obrigatórios.")

if not os.path.exists(ARQUIVO):
    raise FileNotFoundError(f"Arquivo não encontrado: {ARQUIVO}")


# ===============================
# LER PLANILHA
# ===============================
df = pd.read_excel(ARQUIVO)

df.columns = [str(col).strip().upper() for col in df.columns]


# ===============================
# GARANTIR COLUNAS
# ===============================
colunas_obrigatorias = [
    "NOME",
    "TELEFONE",
    "MODELO",
    "PERIODO DE REVISÃO",
    "STATUS DE ENVIO",
    "DATA DE ENVIO"
]

for col in colunas_obrigatorias:
    if col not in df.columns:
        df[col] = ""


# ===============================
# LOOP DE ENVIO
# ===============================
for index, cliente in df.iterrows():
    nome = "" if pd.isna(cliente["NOME"]) else str(cliente["NOME"]).strip()
    telefone = limpar_telefone(cliente["TELEFONE"])
    modelo = "" if pd.isna(cliente["MODELO"]) else str(cliente["MODELO"]).strip()
    status = "" if pd.isna(cliente["STATUS DE ENVIO"]) else str(cliente["STATUS DE ENVIO"]).strip().upper()
    periodo = tratar_periodo(cliente["PERIODO DE REVISÃO"])

    # Não enviar novamente
    if status == "ENVIADO":
        print(f"Linha {index + 2}: já enviado, pulando.")
        continue

    # Validações
    if not nome:
        df.at[index, "STATUS DE ENVIO"] = "NOME VAZIO"
        df.to_excel(ARQUIVO, index=False)
        print(f"Linha {index + 2}: nome vazio.")
        continue

    if not telefone:
        df.at[index, "STATUS DE ENVIO"] = "TELEFONE INVÁLIDO"
        df.to_excel(ARQUIVO, index=False)
        print(f"Linha {index + 2}: telefone inválido.")
        continue

    if len(telefone) < 12:
        df.at[index, "STATUS DE ENVIO"] = "TELEFONE CURTO"
        df.to_excel(ARQUIVO, index=False)
        print(f"Linha {index + 2}: telefone curto -> {telefone}")
        continue

    if not modelo:
        df.at[index, "STATUS DE ENVIO"] = "MODELO VAZIO"
        df.to_excel(ARQUIVO, index=False)
        print(f"Linha {index + 2}: modelo vazio.")
        continue

    if periodo is None:
        df.at[index, "STATUS DE ENVIO"] = "PERIODO INVALIDO"
        df.to_excel(ARQUIVO, index=False)
        print(f"Linha {index + 2}: período inválido.")
        continue

    mensagem = criar_mensagem(nome, modelo, periodo)

    print(f"Enviando para {nome} - {telefone}")

    try:
        resposta = enviar_mensagem(telefone, mensagem)

        print("Status:", resposta.status_code)
        print("Resposta:", resposta.text)

        if resposta.status_code in [200, 201]:
            df.at[index, "STATUS DE ENVIO"] = "ENVIADO"
            df.at[index, "DATA DE ENVIO"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        else:
            df.at[index, "STATUS DE ENVIO"] = f"ERRO {resposta.status_code}"

    except requests.exceptions.Timeout:
        print("Erro: timeout no envio.")
        df.at[index, "STATUS DE ENVIO"] = "TIMEOUT"

    except requests.exceptions.RequestException as e:
        print("Erro de requisição:", e)
        df.at[index, "STATUS DE ENVIO"] = "ERRO REQUISICAO"

    except Exception as e:
        print("Erro inesperado:", e)
        df.at[index, "STATUS DE ENVIO"] = "ERRO ENVIO"

    # salva a cada envio para não perder progresso
    df.to_excel(ARQUIVO, index=False)

    print(f"Aguardando {INTERVALO_ENVIO} segundos...")
    time.sleep(INTERVALO_ENVIO)


print("Disparo finalizado com sucesso.")