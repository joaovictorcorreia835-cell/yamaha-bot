# ==========================================
# IA COMERCIAL - YAMAHA BOT
# Sugestões de venda, follow-up e conversão
# ==========================================

import re


def normalizar_texto(texto):
    texto = str(texto or "").lower().strip()

    substituicoes = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
    }

    for antigo, novo in substituicoes.items():
        texto = texto.replace(antigo, novo)

    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def detectar_modelo(texto):
    texto = normalizar_texto(texto)

    modelos = [
        "fz15", "fazer 250", "fz25", "lander", "crosser",
        "factor", "nmax", "fluo", "mt03", "mt07", "r15", "r3"
    ]

    for modelo in modelos:
        if modelo in texto:
            return modelo

    return ""


def detectar_interesse_comercial(texto):
    texto = normalizar_texto(texto)

    if any(p in texto for p in ["revisao", "oleo", "manutencao"]):
        return "revisao"

    if any(p in texto for p in ["peca", "pastilha", "filtro", "relacao", "pneu"]):
        return "pecas"

    if any(p in texto for p in ["acessorio", "slider", "bau", "protetor", "suporte", "bolha"]):
        return "acessorios"

    if any(p in texto for p in ["garantia", "falhando", "barulho", "vazando", "painel"]):
        return "diagnostico"

    return "geral"


def sugestoes_por_modelo(modelo):
    modelo = normalizar_texto(modelo)

    sugestoes = {
        "fz15": [
            "slider",
            "suporte de celular",
            "protetor de motor",
            "lubrificação de corrente"
        ],
        "fazer 250": [
            "slider",
            "pastilha de freio",
            "kit relação",
            "suporte de celular"
        ],
        "fz25": [
            "slider",
            "pastilha de freio",
            "kit relação",
            "suporte de celular"
        ],
        "lander": [
            "protetor de motor",
            "baú",
            "farol auxiliar",
            "lubrificação de corrente"
        ],
        "crosser": [
            "baú",
            "protetor de carenagem",
            "kit relação",
            "lubrificação de corrente"
        ],
        "nmax": [
            "bolha",
            "suporte de celular",
            "pastilha de freio",
            "limpeza do sistema CVT"
        ],
    }

    return sugestoes.get(modelo, [])


def montar_oferta_comercial(modelo="", interesse="geral"):
    modelo = normalizar_texto(modelo)
    interesse = normalizar_texto(interesse)

    sugestoes = sugestoes_por_modelo(modelo)

    if interesse == "revisao":
        base = (
            "Além da revisão, podemos verificar alguns itens importantes para manter sua moto em dia, "
            "como pastilhas de freio, relação, pneus e lubrificação da corrente."
        )

    elif interesse == "pecas":
        base = (
            "Trabalhamos com peças originais Yamaha e também podemos verificar disponibilidade, "
            "prazo de encomenda e instalação na oficina."
        )

    elif interesse == "acessorios":
        base = (
            "Temos opções de acessórios para deixar sua Yamaha mais completa, confortável e protegida."
        )

    elif interesse == "diagnostico":
        base = (
            "O ideal é trazer a moto para uma avaliação técnica. Durante o diagnóstico, também podemos verificar "
            "itens preventivos para evitar problemas futuros."
        )

    else:
        base = (
            "Podemos ajudar com revisão, peças, acessórios, garantia e agendamento no pós-venda Yamaha."
        )

    if sugestoes:
        itens = ", ".join(sugestoes[:4])
        return f"{base}\n\nPara sua {modelo.upper()}, também recomendamos verificar: {itens}."

    return base


def classificar_nivel_interesse(texto):
    texto = normalizar_texto(texto)

    alta = [
        "quero agendar",
        "pode marcar",
        "tem vaga",
        "hoje",
        "amanha",
        "quanto fica",
        "vou fazer",
        "preciso fazer"
    ]

    media = [
        "quanto custa",
        "qual valor",
        "tem disponivel",
        "faz orçamento",
        "queria saber"
    ]

    for item in alta:
        if item in texto:
            return "ALTO"

    for item in media:
        if item in texto:
            return "MEDIO"

    return "BAIXO"


def proxima_acao_comercial(texto):
    texto = normalizar_texto(texto)
    nivel = classificar_nivel_interesse(texto)

    if nivel == "ALTO":
        return "OFERECER_AGENDAMENTO"

    if nivel == "MEDIO":
        return "ENVIAR_ORCAMENTO_OU_EXPLICAR"

    return "NUTRIR_LEAD"


def gerar_resposta_comercial(texto, modelo=""):
    if not modelo:
        modelo = detectar_modelo(texto)

    interesse = detectar_interesse_comercial(texto)
    nivel = classificar_nivel_interesse(texto)
    proxima_acao = proxima_acao_comercial(texto)

    oferta = montar_oferta_comercial(
        modelo=modelo,
        interesse=interesse
    )

    resposta = oferta

    if proxima_acao == "OFERECER_AGENDAMENTO":
        resposta += "\n\nPosso seguir com o agendamento para você?"

    elif proxima_acao == "ENVIAR_ORCAMENTO_OU_EXPLICAR":
        resposta += "\n\nMe informe o modelo e o ano da moto para eu verificar melhor."

    else:
        resposta += "\n\nCaso queira, posso te direcionar para revisão, peças, acessórios ou garantia."

    return {
        "resposta": resposta,
        "modelo": modelo,
        "interesse": interesse,
        "nivel_interesse": nivel,
        "proxima_acao": proxima_acao,
    }


if __name__ == "__main__":
    teste = "quanto fica a revisão da minha fz15?"
    print(gerar_resposta_comercial(teste))