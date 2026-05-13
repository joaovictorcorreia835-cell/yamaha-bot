import os
import time
import re
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# CONFIG - Z-API
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "").strip()
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "").strip()
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "").strip()

ARQUIVO_PLANILHA = "templates/data/clientes.xlsx"
INTERVALO_ENTRE_ENVIOS = 90

URL_ENVIO_TEXTO = (
    f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}"
    f"/token/{ZAPI_TOKEN}/send-text"
)

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
    "ID_ENVIO",
]

STATUS_ENVIO_PERMITIDOS = ["", "PENDENTE"]


# ==========================================
# CRIAR MENSAGEM
# ==========================================
def criar_mensagem(nome, modelo, periodo):
    return f"""Olá {nome} 👋

Aqui é da Motoshow Yamaha 🏍️

Identificamos que sua {modelo} está no período ideal para a revisão de {periodo} meses.

Manter a revisão em dia ajuda a preservar a garantia, segurança e desempenho da sua Yamaha.

✅ Técnicos especializados Yamaha
✅ Peças originais
✅ Atendimento com agendamento

Responda com o número da opção desejada:

1 - Agendar revisão
2 - Falar com consultor
3 - Depois"""


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
    numero = str(numero or "").strip()
    numero = re.sub(r"\D", "", numero)

    if numero.startswith("0"):
        numero = numero[1:]

    if numero and not numero.startswith("55"):
        numero = "55" + numero

    return numero


# ==========================================
# VALIDAR TELEFONE
# ==========================================
def telefone_valido(numero):
    numero = normalizar_telefone(numero)
    return numero.startswith("55") and len(numero) in [12, 13]


# ==========================================
# HEADERS Z-API
# ==========================================
def headers_zapi():
    return {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN,
    }


# ==========================================
# VALIDAR RESPOSTA Z-API
# ==========================================
def resposta_zapi_sucesso(status_code, resposta):
    try:
        if status_code not in [200, 201]:
            return False

        if isinstance(resposta, dict):
            if resposta.get("error") is True:
                return False

            if resposta.get("success") is False:
                return False

        return True

    except Exception:
        return status_code in [200, 201]


# ==========================================
# EXTRAIR ID DE ENVIO
# ==========================================
def extrair_id_envio(resposta):
    if not isinstance(resposta, dict):
        return ""

    return (
        resposta.get("messageId")
        or resposta.get("id")
        or resposta.get("zaapId")
        or resposta.get("messageID")
        or ""
    )


# ==========================================
# ENVIAR MENSAGEM TEXTO SIMPLES
# ==========================================
def enviar_mensagem(numero, mensagem):
    if not ZAPI_INSTANCE_ID:
        print("❌ Erro: ZAPI_INSTANCE_ID não configurado.")
        return False, "ZAPI_INSTANCE_ID não configurado", ""

    if not ZAPI_TOKEN:
        print("❌ Erro: ZAPI_TOKEN não configurado.")
        return False, "ZAPI_TOKEN não configurado", ""

    if not ZAPI_CLIENT_TOKEN:
        print("❌ Erro: ZAPI_CLIENT_TOKEN não configurado.")
        return False, "ZAPI_CLIENT_TOKEN não configurado", ""

    payload = {
        "phone": numero,
        "message": mensagem,
    }

    try:
        response = requests.post(
            URL_ENVIO_TEXTO,
            json=payload,
            headers=headers_zapi(),
            timeout=30,
        )

        try:
            resposta = response.json()
        except Exception:
            resposta = response.text

        print("Status Code Texto:", response.status_code)
        print("Resposta Texto:", resposta)

        id_envio = extrair_id_envio(resposta)

        if resposta_zapi_sucesso(response.status_code, resposta):
            return True, "Enviado com sucesso via Z-API texto simples", id_envio

        return False, f"Erro Z-API texto status {response.status_code}: {resposta}", id_envio

    except Exception as e:
        print("Erro envio texto:", repr(e))
        return False, repr(e), ""


# ==========================================
# DISPARO
# ==========================================
def disparar():
    print("===================================")
    print("🚀 Iniciando disparo revisão Z-API texto simples...")
    print("===================================")

    if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN or not ZAPI_CLIENT_TOKEN:
        print("❌ Erro: credenciais Z-API não carregadas do .env ou Render.")
        return

    try:
        df = pd.read_excel(ARQUIVO_PLANILHA, dtype=str).fillna("")
    except Exception as e:
        print(f"❌ Erro ao abrir a planilha {ARQUIVO_PLANILHA}: {e}")
        return

    df = garantir_colunas(df)

    telefones_enviados_nesta_execucao = set()

    for index, row in df.iterrows():
        status_envio = str(row.get("STATUS_ENVIO", "")).strip().upper()
        status_retorno = str(row.get("STATUS_RETORNO", "")).strip().upper()

        if status_envio not in STATUS_ENVIO_PERMITIDOS:
            print("⏭ Pulando linha já tratada:", row.get("NOME", "Sem nome"), "-", status_envio)
            continue

        if status_retorno in [
            "RESPONDEU",
            "AGENDOU",
            "NAO_INTERESSADO",
            "NÃO_INTERESSADO",
        ]:
            print("⏭ Pulando cliente que já retornou:", row.get("NOME", "Sem nome"), "-", status_retorno)
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

        if not telefone_valido(numero):
            print(f"⚠ Linha {index + 2} ignorada - telefone inválido: {numero}")
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = f"Telefone inválido: {numero}"
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            continue

        if numero in telefones_enviados_nesta_execucao:
            print(f"⏭ Telefone duplicado nesta execução: {numero}")
            df.at[index, "STATUS_ENVIO"] = "DUPLICADO"
            df.at[index, "OBS"] = "Telefone duplicado na planilha ou execução"
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

        enviado, observacao, id_envio = enviar_mensagem(numero, mensagem)

        agora = datetime.now().strftime("%d/%m/%Y %H:%M")

        if enviado:
            df.at[index, "DATA_DISPARO"] = agora
            df.at[index, "STATUS_ENVIO"] = "ENVIADO"
            df.at[index, "STATUS_RETORNO"] = "AGUARDANDO"
            df.at[index, "ULTIMA_INTERACAO"] = agora
            df.at[index, "FOLLOWUP_1"] = ""
            df.at[index, "FOLLOWUP_2"] = ""
            df.at[index, "OBS"] = observacao
            df.at[index, "LINK_ORIGEM"] = "CAMPANHA_REVISAO_TEXTO"
            df.at[index, "INTENCAO_IA"] = ""
            df.at[index, "PROXIMA_ACAO"] = "AGUARDAR_RETORNO"
            df.at[index, "NIVEL_INTERESSE"] = ""
            df.at[index, "ID_ENVIO"] = id_envio

            telefones_enviados_nesta_execucao.add(numero)

            print("✅ Enviado com sucesso:", nome)

        else:
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = observacao
            df.at[index, "ID_ENVIO"] = id_envio

            print("❌ Falha no envio:", nome)
            print("Motivo:", observacao)

        df.to_excel(ARQUIVO_PLANILHA, index=False)

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    print("===================================")
    print("✅ Disparo finalizado")
    print("===================================")


if __name__ == "__main__":
    disparar()