# ==========================================
# FERRAMENTAS IA - YAMAHA BOT
# ==========================================

import re
from difflib import SequenceMatcher

from base_conhecimento import buscar_na_base_conhecimento
from base_duvidas import responder_duvida_manual


# ==========================================
# NORMALIZAR TEXTO
# ==========================================
def normalizar_texto(texto):

    texto = str(texto or "").lower().strip()

    substituicoes = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",

        "é": "e",
        "ê": "e",

        "í": "i",

        "ó": "o",
        "ô": "o",
        "õ": "o",

        "ú": "u",

        "ç": "c",
    }

    for antigo, novo in substituicoes.items():
        texto = texto.replace(antigo, novo)

    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


# ==========================================
# SIMILARIDADE TEXTO
# ==========================================
def similaridade_texto(a, b):

    a = normalizar_texto(a)
    b = normalizar_texto(b)

    return SequenceMatcher(None, a, b).ratio()


# ==========================================
# IDENTIFICAR MODELO
# ==========================================
def identificar_modelo(texto):

    texto = normalizar_texto(texto)

    modelos = [

        "fz15",
        "fazer 250",
        "fz25",

        "lander",
        "crosser",

        "factor",
        "factor125",
        "factor150",

        "nmax",
        "fluo",

        "mt03",
        "mt07",

        "r15",
        "r3",

        "crypton",
    ]

    for modelo in modelos:

        if modelo in texto:
            return modelo

    return ""


# ==========================================
# CLASSIFICAR URGÊNCIA
# ==========================================
def classificar_urgencia(texto):

    texto = normalizar_texto(texto)

    urgentes = [

        "motor fundiu",
        "fumacando",
        "nao liga",
        "vazando oleo",
        "luz injecao",
        "perdeu freio",
        "moto morreu",
        "painel apagou",
        "falhando muito",
        "travou",
    ]

    moderados = [

        "barulho",
        "vibracao",
        "falhando",
        "esquentando",
        "consumo alto",
    ]

    for item in urgentes:
        if item in texto:
            return "alta"

    for item in moderados:
        if item in texto:
            return "media"

    return "baixa"


# ==========================================
# IDENTIFICAR INTENÇÃO
# ==========================================
def identificar_intencao(texto):

    texto = normalizar_texto(texto)

    intencoes = {

        "revisao": [
            "revisao",
            "agendar",
            "oleo",
            "manutencao",
        ],

        "garantia": [
            "garantia",
            "cobertura",
            "perde garantia",
        ],

        "pecas": [
            "peca",
            "pastilha",
            "filtro",
            "relacao",
            "retrovisor",
        ],

        "acessorios": [
            "slider",
            "bau",
            "protetor",
            "escapamento",
            "suporte celular",
        ],

        "problema_tecnico": [
            "falhando",
            "barulho",
            "vazando",
            "injeção",
            "painel",
            "motor",
        ],

        "financeiro": [
            "parcelar",
            "pix",
            "cartao",
            "boleto",
            "valor",
            "preco",
        ],

        "humano": [
            "atendente",
            "humano",
            "consultor",
        ]
    }

    melhor = ""
    maior = 0

    for categoria, palavras in intencoes.items():

        pontos = 0

        for palavra in palavras:

            if palavra in texto:
                pontos += 1

        if pontos > maior:
            maior = pontos
            melhor = categoria

    return melhor


# ==========================================
# SUGESTÃO DE VENDA
# ==========================================
def sugerir_venda_adicional(modelo):

    modelo = normalizar_texto(modelo)

    sugestoes = {

        "fz15": [
            "slider",
            "suporte celular",
            "bolha",
        ],

        "lander": [
            "protetor motor",
            "farol auxiliar",
            "bau",
        ],

        "crosser": [
            "bau",
            "protetor carenagem",
        ],

        "nmax": [
            "suporte celular",
            "bolha",
        ]
    }

    return sugestoes.get(modelo, [])


# ==========================================
# IA PRINCIPAL
# ==========================================
def responder_ia(texto, modelo=""):

    texto = normalizar_texto(texto)

    if not modelo:
        modelo = identificar_modelo(texto)

    # ==========================================
    # BASE DE CONHECIMENTO
    # ==========================================
    resultado_base = buscar_na_base_conhecimento(texto)

    if resultado_base.get("encontrou"):

        return {
            "fonte": "base_conhecimento",
            "resposta": resultado_base["resposta"],
            "categoria": resultado_base.get("categoria", ""),
            "modelo": modelo,
            "urgencia": classificar_urgencia(texto),
        }

    # ==========================================
    # MANUAL PDF
    # ==========================================
    resultado_manual = responder_duvida_manual(
        modelo,
        texto
    )

    if resultado_manual.get("encontrou"):

        return {
            "fonte": "manual_pdf",
            "resposta": resultado_manual["resposta"],
            "categoria": "manual",
            "modelo": modelo,
            "urgencia": classificar_urgencia(texto),
        }

    # ==========================================
    # FALLBACK
    # ==========================================
    return {
        "fonte": "fallback",
        "resposta":
            "Não encontrei essa informação com segurança. Vou encaminhar sua dúvida para um consultor do pós-venda.",
        "categoria": "humano",
        "modelo": modelo,
        "urgencia": classificar_urgencia(texto),
    }


# ==========================================
# TESTE LOCAL
# ==========================================
if __name__ == "__main__":

    pergunta = "quanto custa a revisão da minha fz15"

    resultado = responder_ia(pergunta)

    print("\n")
    print(resultado)
    print("\n")