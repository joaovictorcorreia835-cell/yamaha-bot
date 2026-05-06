import os
import time
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# CONFIG - WASENDERAPI
# ==========================================
WASENDER_API_KEY = os.getenv("WASENDER_API_KEY", "").strip()
WASENDER_BASE_URL = os.getenv(
    "WASENDER_BASE_URL",
    "https://www.wasenderapi.com/api"
).strip().rstrip("/")

ARQUIVO_PLANILHA = "templates/data/disparo_atacado.xlsx"
INTERVALO_ENTRE_ENVIOS = 90

URL_ENVIO = f"{WASENDER_BASE_URL}/send-message"

COLUNAS_OBRIGATORIAS = [
    "EMPRESA",
    "TELEFONE",
    "CIDADE",
    "RESPONSAVEL",
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


def criar_mensagem(empresa="", responsavel="", cidade=""):
    nome_destino = responsavel.strip() if responsavel else empresa.strip()

    saudacao = "Olá, tudo bem? 👋"
    if nome_destino:
        saudacao = f"Olá {nome_destino}, tudo bem? 👋"

    return f"""{saudacao}

Aqui é da Motoshow Yamaha!

Estamos expandindo nossa distribuição e abrindo parceria com oficinas e lojas da região.

Trabalhamos com:
✅ Óleo Yamalube
✅ Peças originais Yamaha
✅ Acessórios

Temos condições especiais para atacado e entrega rápida 🚀

Posso te enviar nossa tabela e condições?"""


def garantir_colunas(df):
    for coluna in COLUNAS_OBRIGATORIAS:
        if coluna not in df.columns:
            df[coluna] = ""
    return df


def normalizar_telefone(numero):
    numero = str(numero or "").strip()
    numero = (
        numero.replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace(".", "")
    )

    if numero.startswith("0"):
        numero = numero[1:]

    if numero and not numero.startswith("55"):
        numero = "55" + numero

    return numero


def headers_wasender():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WASENDER_API_KEY}",
    }


def enviar_mensagem(numero, mensagem):
    if not WASENDER_API_KEY:
        print("❌ Erro: WASENDER_API_KEY não configurada.")
        return False

    payload = {
        "to": numero,
        "text": mensagem,
    }

    try:
        response = requests.post(
            URL_ENVIO,
            json=payload,
            headers=headers_wasender(),
            timeout=30
        )

        try:
            resposta = response.json()
        except Exception:
            resposta = response.text

        print("Status Code:", response.status_code)
        print("Resposta:", resposta)

        return response.status_code in [200, 201]

    except Exception as e:
        print("Erro envio:", repr(e))
        return False


def disparar():
    print("===================================")
    print("🚀 Iniciando disparo atacado...")
    print("===================================")

    if not WASENDER_API_KEY:
        print("❌ Erro: WASENDER_API_KEY não carregada do .env ou Render.")
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
            print("⏭ Pulando linha já tratada:", row.get("EMPRESA", "Sem empresa"), "-", status_envio)
            continue

        empresa = str(row.get("EMPRESA", "")).strip()
        telefone = normalizar_telefone(row.get("TELEFONE", ""))
        cidade = str(row.get("CIDADE", "")).strip()
        responsavel = str(row.get("RESPONSAVEL", "")).strip()

        if not telefone:
            print(f"⚠ Linha {index + 2} ignorada - falta TELEFONE")
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = "Falta telefone"
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            continue

        mensagem = criar_mensagem(
            empresa=empresa,
            responsavel=responsavel,
            cidade=cidade
        )

        print(f"📤 Enviando para: {empresa or responsavel or 'Sem nome'} - {telefone}")

        enviado = enviar_mensagem(telefone, mensagem)

        if enviado:
            agora = datetime.now().strftime("%d/%m/%Y %H:%M")

            df.at[index, "DATA_DISPARO"] = agora
            df.at[index, "STATUS_ENVIO"] = "ENVIADO"
            df.at[index, "STATUS_RETORNO"] = "AGUARDANDO"
            df.at[index, "ULTIMA_INTERACAO"] = agora
            df.at[index, "FOLLOWUP_1"] = ""
            df.at[index, "FOLLOWUP_2"] = ""
            df.at[index, "OBS"] = "Disparo atacado enviado com sucesso via WasenderAPI"
            df.at[index, "LINK_ORIGEM"] = "CAMPANHA_ATACADO"
            df.at[index, "INTENCAO_IA"] = ""
            df.at[index, "PROXIMA_ACAO"] = "AGUARDAR_RETORNO"
            df.at[index, "NIVEL_INTERESSE"] = ""

            df.to_excel(ARQUIVO_PLANILHA, index=False)
            print("✅ Enviado com sucesso:", empresa or responsavel or telefone)

        else:
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = "Falha ao enviar mensagem via WasenderAPI"
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            print("❌ Falha no envio:", empresa or responsavel or telefone)

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    print("===================================")
    print("✅ Disparo atacado finalizado")
    print("===================================")


if __name__ == "__main__":
    disparar()