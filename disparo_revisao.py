import os
import time
import re
import unicodedata
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
INTERVALO_ENTRE_ENVIOS = 60
LIMITE_ENVIOS_POR_LOTE = 25
INTERVALO_ENTRE_LOTES = 30 * 60

URL_BASE = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}"

URL_ENVIO_TEXTO = f"{URL_BASE}/send-text"
URL_ENVIO_BOTOES = f"{URL_BASE}/send-button-list"

COLUNAS_CONTROLE = [
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

CABECALHOS_ORIGEM = {
    "NOME": ["NOME", "NOME DO CLIENTE"],
    "TELEFONE": ["TELEFONE", "CELULAR DO CLIENTE"],
    "MODELO": ["MODELO"],
    "PERIODO_REVISAO": ["PERIODO REVISAO", "TIPO DA PROXIMA REVISAO"],
    "CIDADE": ["CIDADE"],
    "CHASSI": ["CHASSI"],
    "DATA_VENDA": ["DATA DA VENDA"],
    "KM_ULTIMO_REGISTRO": ["KM ULTIMO REGISTRO"],
}

STATUS_ENVIO_PERMITIDOS = ["", "PENDENTE"]


# ==========================================
# MENSAGEM
# ==========================================
def criar_mensagem(nome, modelo, periodo, cidade=""):
    nome = str(nome or "").strip().title()
    modelo = str(modelo or "").strip().upper()
    periodo = str(periodo or "").strip()
    cidade = str(cidade or "").strip().title()
    cidade_txt = f" em *{cidade}*" if cidade else ""

    return f"""Olá, {nome}! 👋

Aqui é da *Motoshow Yamaha* 🏍️

Identificamos que sua *{modelo}* está no período ideal para a revisão de *{periodo}*{cidade_txt}.

Manter a revisão em dia ajuda a preservar:

✅ garantia da Yamaha
✅ segurança da moto
✅ economia no uso diário
✅ valorização na revenda

Como deseja continuar?"""


def criar_mensagem_fallback(nome, modelo, periodo, cidade=""):
    mensagem = criar_mensagem(nome, modelo, periodo, cidade)

    return mensagem + """

Responda com o número da opção desejada:

1 - Agendar revisão
2 - Falar com consultor
3 - Ver depois"""


# ==========================================
# PLANILHA
# ==========================================
def garantir_colunas(df):
    for coluna in COLUNAS_CONTROLE:
        if coluna not in df.columns:
            df[coluna] = ""
    return df


def normalizar_cabecalho(valor):
    valor = str(valor or "").strip().upper()
    valor = unicodedata.normalize("NFKD", valor)
    valor = "".join(char for char in valor if not unicodedata.combining(char))
    valor = re.sub(r"[^A-Z0-9]+", " ", valor)
    return re.sub(r"\s+", " ", valor).strip()


def mapear_colunas_origem(df):
    colunas_normalizadas = {
        normalizar_cabecalho(coluna): coluna for coluna in df.columns
    }
    return {
        campo: next(
            (
                colunas_normalizadas.get(normalizar_cabecalho(cabecalho))
                for cabecalho in opcoes
                if normalizar_cabecalho(cabecalho) in colunas_normalizadas
            ),
            None,
        )
        for campo, opcoes in CABECALHOS_ORIGEM.items()
    }


def ha_proximo_cliente_apto(
    df,
    indice_atual,
    colunas_origem,
    telefones_enviados_nesta_execucao,
):
    """Verifica se ainda existe outro cliente válido aguardando disparo."""
    posicao_atual = df.index.get_loc(indice_atual)

    for _, row in df.iloc[posicao_atual + 1 :].iterrows():
        status_envio = str(row.get("STATUS_ENVIO", "")).strip().upper()
        status_retorno = str(row.get("STATUS_RETORNO", "")).strip().upper()

        if status_envio not in STATUS_ENVIO_PERMITIDOS:
            continue

        if status_retorno in [
            "RESPONDEU",
            "AGENDOU",
            "NAO_INTERESSADO",
            "NÃO_INTERESSADO",
        ]:
            continue

        nome = str(row.get(colunas_origem["NOME"], "")).strip()
        numero = normalizar_telefone(row.get(colunas_origem["TELEFONE"], ""))
        modelo = str(row.get(colunas_origem["MODELO"], "")).strip()
        periodo = str(row.get(colunas_origem["PERIODO_REVISAO"], "")).strip()

        if (
            nome
            and telefone_valido(numero)
            and numero not in telefones_enviados_nesta_execucao
            and modelo
            and periodo
        ):
            return True

    return False


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
        print("❌ Erro:", erro)
        return False, erro, ""

    payload = {
        "phone": numero,
        "message": mensagem,
        "buttonList": {
            "buttons": [
                {
                    "id": "AGENDAR_REVISAO",
                    "label": "1 - Agendar revisão"
                },
                {
                    "id": "MENU_HUMANO",
                    "label": "2 - Falar com consultor"
                },
                {
                    "id": "DEPOIS",
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
            return True, "Enviado com sucesso via Z-API botões", id_envio

        return False, f"Erro Z-API botões status {response.status_code}: {resposta}", id_envio

    except Exception as e:
        print("Erro envio botões:", repr(e))
        return False, repr(e), ""


# ==========================================
# ENVIO TEXTO FALLBACK
# ==========================================
def enviar_mensagem_texto(numero, mensagem):
    ok, erro = credenciais_validas()

    if not ok:
        print("❌ Erro:", erro)
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
            return True, "Enviado com sucesso via Z-API texto", id_envio

        return False, f"Erro Z-API texto status {response.status_code}: {resposta}", id_envio

    except Exception as e:
        print("Erro envio texto:", repr(e))
        return False, repr(e), ""


# ==========================================
# ENVIO PRINCIPAL
# ==========================================
def enviar_mensagem(numero, mensagem_botoes, mensagem_fallback):
    enviado, obs, id_envio = enviar_mensagem_botoes(numero, mensagem_botoes)

    if enviado:
        return True, obs, id_envio, "BOTOES"

    print("⚠️ Falha ao enviar botões. Tentando fallback em texto...")

    enviado_texto, obs_texto, id_texto = enviar_mensagem_texto(
        numero,
        mensagem_fallback,
    )

    if enviado_texto:
        return True, f"Fallback texto enviado. Motivo botões: {obs}", id_texto, "TEXTO"

    return False, f"Botões falharam: {obs} | Texto falhou: {obs_texto}", id_texto, "ERRO"


# ==========================================
# DISPARO
# ==========================================
def disparar():
    print("===================================")
    print("🚀 Iniciando disparo revisão Z-API...")
    print("===================================")

    ok, erro = credenciais_validas()

    if not ok:
        print("❌ Erro:", erro)
        return

    try:
        df = pd.read_excel(ARQUIVO_PLANILHA, dtype=str).fillna("")
    except Exception as e:
        print(f"❌ Erro ao abrir a planilha {ARQUIVO_PLANILHA}: {e}")
        return

    colunas_origem = mapear_colunas_origem(df)
    campos_necessarios = ["NOME", "TELEFONE", "MODELO", "PERIODO_REVISAO"]
    campos_ausentes = [
        campo for campo in campos_necessarios if not colunas_origem.get(campo)
    ]

    if campos_ausentes:
        print(
            "❌ A planilha não possui os cabeçalhos necessários: "
            + ", ".join(campos_ausentes)
        )
        return

    df = garantir_colunas(df)

    telefones_enviados_nesta_execucao = set()
    envios_no_lote = 0

    for index, row in df.iterrows():
        status_envio = str(row.get("STATUS_ENVIO", "")).strip().upper()
        status_retorno = str(row.get("STATUS_RETORNO", "")).strip().upper()

        if status_envio not in STATUS_ENVIO_PERMITIDOS:
            print(
                "⏭ Pulando linha já tratada:",
                row.get(colunas_origem["NOME"], "Sem nome"),
                "-",
                status_envio,
            )
            continue

        if status_retorno in [
            "RESPONDEU",
            "AGENDOU",
            "NAO_INTERESSADO",
            "NÃO_INTERESSADO",
        ]:
            print(
                "⏭ Pulando cliente que já retornou:",
                row.get(colunas_origem["NOME"], "Sem nome"),
                "-",
                status_retorno,
            )
            continue

        nome = str(row.get(colunas_origem["NOME"], "")).strip()
        numero = normalizar_telefone(row.get(colunas_origem["TELEFONE"], ""))
        modelo = str(row.get(colunas_origem["MODELO"], "")).strip()
        periodo = str(row.get(colunas_origem["PERIODO_REVISAO"], "")).strip()
        cidade = str(row.get(colunas_origem.get("CIDADE"), "")).strip()

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

        mensagem_botoes = criar_mensagem(nome, modelo, periodo, cidade)
        mensagem_fallback = criar_mensagem_fallback(nome, modelo, periodo, cidade)

        print(f"📤 Enviando para: {nome} - {numero}")

        enviado, observacao, id_envio, tipo_envio = enviar_mensagem(
            numero,
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
            df.at[index, "LINK_ORIGEM"] = f"CAMPANHA_REVISAO_{tipo_envio}"
            df.at[index, "INTENCAO_IA"] = ""
            df.at[index, "PROXIMA_ACAO"] = "AGUARDAR_RETORNO"
            df.at[index, "NIVEL_INTERESSE"] = ""
            df.at[index, "ID_ENVIO"] = id_envio

            telefones_enviados_nesta_execucao.add(numero)
            envios_no_lote += 1

            print("✅ Enviado com sucesso:", nome)

        else:
            df.at[index, "STATUS_ENVIO"] = "ERRO"
            df.at[index, "OBS"] = observacao
            df.at[index, "ID_ENVIO"] = id_envio

            print("❌ Falha no envio:", nome)
            print("Motivo:", observacao)

        df.to_excel(ARQUIVO_PLANILHA, index=False)

        if enviado and ha_proximo_cliente_apto(
            df,
            index,
            colunas_origem,
            telefones_enviados_nesta_execucao,
        ):
            if envios_no_lote >= LIMITE_ENVIOS_POR_LOTE:
                print(
                    "⏸️ Limite de 25 mensagens atingido. "
                    "Aguardando 30 minutos para o próximo lote..."
                )
                time.sleep(INTERVALO_ENTRE_LOTES)
                envios_no_lote = 0
            else:
                print("⏳ Aguardando 60 segundos para o próximo envio...")
                time.sleep(INTERVALO_ENTRE_ENVIOS)

    print("===================================")
    print("✅ Disparo finalizado")
    print("===================================")


if __name__ == "__main__":
    disparar()
