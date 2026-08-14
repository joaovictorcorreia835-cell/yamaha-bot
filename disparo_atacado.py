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
MENSAGENS_PECAS_ATIVAS = str(
    os.getenv("MENSAGENS_PECAS_ATIVAS", "false")
).strip().lower() in ["1", "true", "sim", "yes", "on"]

HORARIO_INICIO = 8
HORARIO_FIM = 20

URL_BASE = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}"

URL_ENVIO_TEXTO = f"{URL_BASE}/send-text"
URL_ENVIO_BOTOES = f"{URL_BASE}/send-button-list"

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
    "TIPO_ENVIO",
]

STATUS_ENVIO_PERMITIDOS = ["", "PENDENTE"]


# ==========================================
# HORÁRIO
# ==========================================
def dentro_horario_comercial():
    agora = datetime.now()
    return HORARIO_INICIO <= agora.hour < HORARIO_FIM


# ==========================================
# MENSAGEM
# ==========================================
def criar_mensagem(empresa="", responsavel="", cidade=""):
    empresa = str(empresa or "").strip()
    responsavel = str(responsavel or "").strip()
    cidade = str(cidade or "").strip()

    nome_destino = responsavel or empresa

    saudacao = "Olá, tudo bem? 👋"

    if nome_destino:
        saudacao = f"Olá, {nome_destino}! Tudo bem? 👋"

    cidade_txt = f" em {cidade} e região" if cidade else " na sua região"

    return f"""{saudacao}

Aqui é da *Motoshow Yamaha* 🏍️

Estamos selecionando oficinas, lojas e revendedores{cidade_txt} para uma parceria de fornecimento no atacado.

Trabalhamos com:

✅ peças Yamaha
✅ óleo Yamalube
✅ acessórios
✅ suporte para orçamento
✅ atendimento comercial direto

Tenho um catálogo de atacado para te enviar agora.

Como deseja continuar?"""


def criar_mensagem_fallback(empresa="", responsavel="", cidade=""):
    mensagem = criar_mensagem(
        empresa=empresa,
        responsavel=responsavel,
        cidade=cidade,
    )

    return mensagem + """

Responda com o número da opção desejada:

1 - Receber catálogo de atacado
2 - Falar com consultor
3 - Ver depois"""


# ==========================================
# PLANILHA
# ==========================================
def garantir_colunas(df):
    for coluna in COLUNAS_OBRIGATORIAS:
        if coluna not in df.columns:
            df[coluna] = ""

    return df


# ==========================================
# TELEFONE
# ==========================================
def normalizar_telefone(numero):
    numero = str(numero or "").strip()
    numero = re.sub(r"\D", "", numero)

    while numero.startswith("0"):
        numero = numero[1:]

    if numero and not numero.startswith("55"):
        numero = "55" + numero

    return numero


def telefone_valido(numero):
    numero = normalizar_telefone(numero)
    return numero.startswith("55") and len(numero) in [12, 13]


# ==========================================
# Z-API
# ==========================================
def headers_zapi():
    return {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN,
    }


def credenciais_validas():
    if not ZAPI_INSTANCE_ID:
        return False, "ZAPI_INSTANCE_ID não configurado"

    if not ZAPI_TOKEN:
        return False, "ZAPI_TOKEN não configurado"

    if not ZAPI_CLIENT_TOKEN:
        return False, "ZAPI_CLIENT_TOKEN não configurado"

    return True, ""


def resposta_zapi_sucesso(status_code, resposta):
    try:
        if status_code not in [200, 201]:
            return False

        if isinstance(resposta, dict):
            if resposta.get("error") is True:
                return False

            if resposta.get("success") is False:
                return False

            if resposta.get("message") == "Instance not connected":
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
        or resposta.get("message_id")
        or ""
    )


# ==========================================
# ENVIO COM BOTÕES
# ==========================================
def enviar_mensagem_botoes(numero, mensagem):
    ok, erro = credenciais_validas()

    if not ok:
        return False, erro, ""

    payload = {
        "phone": numero,
        "message": mensagem,
        "buttonList": {
            "buttons": [
                {
                    "id": "ATACADO_TABELA",
                    "label": "1 - Receber catálogo"
                },
                {
                    "id": "ATACADO_CONSULTOR",
                    "label": "2 - Falar com consultor"
                },
                {
                    "id": "ATACADO_DEPOIS",
                    "label": "3 - Ver depois"
                },
            ]
        }
    }

    try:
        response = requests.post(
            URL_ENVIO_BOTOES,
            json=payload,
            headers=headers_zapi(),
            timeout=30,
        )

        try:
            resposta = response.json()
        except Exception:
            resposta = response.text

        print("Status Code Botões:", response.status_code)
        print("Resposta Botões:", resposta)

        id_envio = extrair_id_envio(resposta)

        if resposta_zapi_sucesso(response.status_code, resposta):
            return True, "Disparo atacado enviado com sucesso via botões Z-API", id_envio

        return False, f"Erro Z-API botões status {response.status_code}: {resposta}", id_envio

    except Exception as e:
        return False, f"Erro ao enviar botões: {repr(e)}", ""


# ==========================================
# ENVIO TEXTO FALLBACK
# ==========================================
def enviar_mensagem_texto(numero, mensagem):
    ok, erro = credenciais_validas()

    if not ok:
        return False, erro, ""

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
            return True, "Disparo atacado enviado com sucesso via texto simples", id_envio

        return False, f"Erro Z-API texto status {response.status_code}: {resposta}", id_envio

    except Exception as e:
        return False, f"Erro ao enviar texto simples: {repr(e)}", ""


# ==========================================
# ENVIO PRINCIPAL
# ==========================================
def enviar_mensagem(numero, mensagem_botoes, mensagem_fallback):
    enviado, observacao, id_envio = enviar_mensagem_botoes(
        numero,
        mensagem_botoes,
    )

    if enviado:
        return True, observacao, id_envio, "BOTOES"

    print("⚠️ Falha ao enviar botões. Tentando fallback em texto...")

    enviado_texto, obs_texto, id_texto = enviar_mensagem_texto(
        numero,
        mensagem_fallback,
    )

    if enviado_texto:
        return (
            True,
            f"Fallback texto enviado. Motivo botões: {observacao}",
            id_texto,
            "TEXTO",
        )

    return (
        False,
        f"Botões falharam: {observacao} | Texto falhou: {obs_texto}",
        id_texto,
        "ERRO",
    )


# ==========================================
# DISPARO
# ==========================================
def disparar():
    if not MENSAGENS_PECAS_ATIVAS:
        print("⏸ Mensagens de peças pausadas. Disparo atacado não iniciado.")
        return

    print("===================================")
    print("🚀 Iniciando disparo atacado Z-API...")
    print("===================================")

    if not dentro_horario_comercial():
        print("⏸ Fora do horário comercial. Envio permitido apenas das 08:00 às 20:00.")
        return

    ok, erro = credenciais_validas()

    if not ok:
        print("❌ Erro:", erro)
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
            "CATALOGO_ENVIADO",
            "CATÁLOGO_ENVIADO",
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

        mensagem_botoes = criar_mensagem(
            empresa=empresa,
            responsavel=responsavel,
            cidade=cidade,
        )

        mensagem_fallback = criar_mensagem_fallback(
            empresa=empresa,
            responsavel=responsavel,
            cidade=cidade,
        )

        print(f"📤 Enviando para: {nome_exibicao} - {telefone}")

        enviado, observacao, id_envio, tipo_envio = enviar_mensagem(
            telefone,
            mensagem_botoes,
            mensagem_fallback,
        )

        agora = datetime.now().strftime("%d/%m/%Y %H:%M")

        if enviado:
            df.at[index, "DATA_DISPARO"] = agora
            df.at[index, "STATUS_ENVIO"] = "ENVIADO"
            df.at[index, "STATUS_RETORNO"] = "AGUARDANDO"
            df.at[index, "ULTIMA_INTERACAO"] = agora
            df.at[index, "FOLLOWUP_1"] = ""
            df.at[index, "FOLLOWUP_2"] = ""
            df.at[index, "OBS"] = observacao
            df.at[index, "LINK_ORIGEM"] = f"CAMPANHA_ATACADO_{tipo_envio}"
            df.at[index, "INTENCAO_IA"] = "atacado"
            df.at[index, "PROXIMA_ACAO"] = "AGUARDAR_RETORNO"
            df.at[index, "NIVEL_INTERESSE"] = "MORNO"
            df.at[index, "ID_ENVIO"] = id_envio
            df.at[index, "TIPO_ENVIO"] = tipo_envio

            telefones_enviados_nesta_execucao.add(telefone)

            print("✅ Enviado com sucesso:", nome_exibicao)

        else:
            df.at[index, "DATA_DISPARO"] = agora
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = observacao
            df.at[index, "ID_ENVIO"] = id_envio
            df.at[index, "TIPO_ENVIO"] = tipo_envio

            print("❌ Falha no envio:", nome_exibicao)
            print("Motivo:", observacao)

        df.to_excel(ARQUIVO_PLANILHA, index=False)

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    print("===================================")
    print("✅ Disparo atacado finalizado")
    print("===================================")


if __name__ == "__main__":
    disparar()
