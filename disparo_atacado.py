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

ARQUIVO_PLANILHA = "templates/data/disparo_atacado.xlsx"
INTERVALO_ENTRE_ENVIOS = 90

HORARIO_INICIO = 8
HORARIO_FIM = 20

URL_ENVIO_TEXTO = (
    f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}"
    f"/token/{ZAPI_TOKEN}/send-text"
)

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
    "ID_ENVIO",
]

STATUS_ENVIO_PERMITIDOS = ["", "PENDENTE"]


def dentro_horario_comercial():
    agora = datetime.now()
    return HORARIO_INICIO <= agora.hour < HORARIO_FIM


def criar_mensagem(empresa="", responsavel="", cidade=""):
    empresa = str(empresa or "").strip()
    responsavel = str(responsavel or "").strip()
    cidade = str(cidade or "").strip()

    nome_destino = responsavel or empresa

    saudacao = "Olá, tudo bem? 👋"
    if nome_destino:
        saudacao = f"Olá {nome_destino}, tudo bem? 👋"

    cidade_txt = f" em {cidade} e região" if cidade else " na sua região"

    return f"""{saudacao}

Aqui é da Motoshow Yamaha 🏍️

Estamos selecionando oficinas e lojas parceiras{cidade_txt} para fornecimento de peças, óleo Yamalube e acessórios Yamaha.

✅ Condições especiais para atacado
✅ Produtos originais Yamaha
✅ Entrega rápida conforme região
✅ Atendimento direto com nossa equipe

Posso te enviar nossa tabela e condições de parceria?

Responda com o número da opção desejada:

1 - Quero tabela
2 - Falar com consultor
3 - Depois"""


def garantir_colunas(df):
    for coluna in COLUNAS_OBRIGATORIAS:
        if coluna not in df.columns:
            df[coluna] = ""
    return df


def normalizar_telefone(numero):
    numero = str(numero or "").strip()
    numero = re.sub(r"\D", "", numero)

    if numero.startswith("0"):
        numero = numero[1:]

    if numero and not numero.startswith("55"):
        numero = "55" + numero

    return numero


def telefone_valido(numero):
    numero = normalizar_telefone(numero)
    return numero.startswith("55") and len(numero) in [12, 13]


def headers_zapi():
    return {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN,
    }


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


def enviar_mensagem_texto(numero, mensagem):
    payload = {
        "phone": numero,
        "message": mensagem,
    }

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
        return True, "Disparo atacado enviado com sucesso via Z-API texto simples", id_envio

    return False, f"Erro Z-API texto status {response.status_code}: {resposta}", id_envio


def enviar_mensagem(numero, mensagem):
    if not ZAPI_INSTANCE_ID:
        return False, "ZAPI_INSTANCE_ID não configurado", ""

    if not ZAPI_TOKEN:
        return False, "ZAPI_TOKEN não configurado", ""

    if not ZAPI_CLIENT_TOKEN:
        return False, "ZAPI_CLIENT_TOKEN não configurado", ""

    try:
        return enviar_mensagem_texto(numero, mensagem)

    except Exception as e:
        return False, f"Erro ao enviar texto simples: {repr(e)}", ""


def disparar():
    print("===================================")
    print("🚀 Iniciando disparo atacado Z-API texto simples...")
    print("===================================")

    if not dentro_horario_comercial():
        print("⏸ Fora do horário comercial. Envio permitido apenas das 08:00 às 20:00.")
        return

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
        if not dentro_horario_comercial():
            print("⏸ Horário comercial encerrado. Disparo pausado.")
            break

        status_envio = str(row.get("STATUS_ENVIO", "")).strip().upper()
        status_retorno = str(row.get("STATUS_RETORNO", "")).strip().upper()

        if status_envio not in STATUS_ENVIO_PERMITIDOS:
            print("⏭ Pulando linha já tratada:", row.get("EMPRESA", "Sem empresa"), "-", status_envio)
            continue

        if status_retorno in [
            "RESPONDEU",
            "INTERESSADO",
            "QUER_TABELA",
            "FALAR_CONSULTOR",
            "DEPOIS",
            "NAO_INTERESSADO",
            "NÃO_INTERESSADO",
        ]:
            print("⏭ Pulando cliente que já retornou:", row.get("EMPRESA", "Sem empresa"), "-", status_retorno)
            continue

        empresa = str(row.get("EMPRESA", "")).strip()
        telefone = normalizar_telefone(row.get("TELEFONE", ""))
        cidade = str(row.get("CIDADE", "")).strip()
        responsavel = str(row.get("RESPONSAVEL", "")).strip()

        nome_exibicao = empresa or responsavel or telefone

        if not telefone:
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = "Falta telefone"
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            continue

        if not telefone_valido(telefone):
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = f"Telefone inválido: {telefone}"
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            continue

        if telefone in telefones_enviados_nesta_execucao:
            df.at[index, "STATUS_ENVIO"] = "DUPLICADO"
            df.at[index, "OBS"] = "Telefone duplicado na planilha ou execução"
            df.to_excel(ARQUIVO_PLANILHA, index=False)
            continue

        mensagem = criar_mensagem(
            empresa=empresa,
            responsavel=responsavel,
            cidade=cidade,
        )

        print(f"📤 Enviando para: {nome_exibicao} - {telefone}")

        enviado, observacao, id_envio = enviar_mensagem(telefone, mensagem)

        agora = datetime.now().strftime("%d/%m/%Y %H:%M")

        if enviado:
            df.at[index, "DATA_DISPARO"] = agora
            df.at[index, "STATUS_ENVIO"] = "ENVIADO"
            df.at[index, "STATUS_RETORNO"] = "AGUARDANDO"
            df.at[index, "ULTIMA_INTERACAO"] = agora
            df.at[index, "FOLLOWUP_1"] = ""
            df.at[index, "FOLLOWUP_2"] = ""
            df.at[index, "OBS"] = observacao
            df.at[index, "LINK_ORIGEM"] = "CAMPANHA_ATACADO_TEXTO"
            df.at[index, "INTENCAO_IA"] = ""
            df.at[index, "PROXIMA_ACAO"] = "AGUARDAR_RETORNO"
            df.at[index, "NIVEL_INTERESSE"] = ""
            df.at[index, "ID_ENVIO"] = id_envio

            telefones_enviados_nesta_execucao.add(telefone)

            print("✅ Enviado com sucesso:", nome_exibicao)

        else:
            df.at[index, "DATA_DISPARO"] = agora
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = observacao
            df.at[index, "ID_ENVIO"] = id_envio

            print("❌ Falha no envio:", nome_exibicao)
            print("Motivo:", observacao)

        df.to_excel(ARQUIVO_PLANILHA, index=False)

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    print("===================================")
    print("✅ Disparo atacado finalizado")
    print("===================================")


if __name__ == "__main__":
    disparar()