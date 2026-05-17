# ==========================================
# FERRAMENTAS IA - YAMAHA BOT
# Integra base de conhecimento + manuais PDF
# ==========================================

import re
from difflib import SequenceMatcher

try:
    from base_conhecimento import buscar_na_base_conhecimento
except Exception as e:
    buscar_na_base_conhecimento = None
    print("[FERRAMENTAS IA][ERRO] Não foi possível importar base_conhecimento:", repr(e), flush=True)

try:
    from ia_duvidas import responder_duvida_manual, responder_duvida_manual_com_ia
except Exception:
    try:
        from base_duvidas import responder_duvida_manual
        responder_duvida_manual_com_ia = None
    except Exception as e:
        responder_duvida_manual = None
        responder_duvida_manual_com_ia = None
        print("[FERRAMENTAS IA][ERRO] Não foi possível importar ia_duvidas/base_duvidas:", repr(e), flush=True)


# ==========================================
# NORMALIZAÇÃO
# ==========================================
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


def limpar_texto(texto):
    return str(texto or "").strip()


# ==========================================
# SIMILARIDADE TEXTO
# ==========================================
def similaridade_texto(a, b):
    a = normalizar_texto(a)
    b = normalizar_texto(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


# ==========================================
# IDENTIFICAR MODELO
# ==========================================
def identificar_modelo(texto):
    texto = normalizar_texto(texto)

    modelos = {
        "tenere 700": "tenere 700",
        "tenere": "tenere 700",
        "t7": "tenere 700",

        "fazer 250": "fazer 250",
        "fz25": "fz25",
        "fz 25": "fz25",

        "fz15": "fz15",
        "fz 15": "fz15",
        "fazer 150": "fz15",

        "lander 250": "lander",
        "lander": "lander",

        "crosser": "crosser",

        "factor 125": "factor 125",
        "factor125": "factor 125",

        "factor 150": "factor 150",
        "factor150": "factor 150",
        "factor": "factor",

        "nmax": "nmax",
        "fluo": "fluo",
        "neo": "neo",
        "aerox": "aerox",

        "mt03": "mt03",
        "mt 03": "mt03",
        "mt-03": "mt03",

        "mt07": "mt07",
        "mt 07": "mt07",
        "mt-07": "mt07",

        "r15": "r15",
        "r 15": "r15",

        "r3": "r3",
        "r 3": "r3",

        "crypton": "crypton",
    }

    for chave, modelo in sorted(modelos.items(), key=lambda x: len(x[0]), reverse=True):
        if chave in texto:
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
        "fumacando muito",
        "nao liga",
        "não liga",
        "vazando oleo",
        "vazando óleo",
        "luz injecao",
        "luz injeção",
        "perdeu freio",
        "sem freio",
        "moto morreu",
        "painel apagou",
        "falhando muito",
        "travou",
        "nao pega",
        "não pega",
    ]

    moderados = [
        "barulho",
        "vibracao",
        "vibração",
        "falhando",
        "esquentando",
        "consumo alto",
        "dificuldade para ligar",
        "ruido",
        "ruído",
    ]

    for item in urgentes:
        if normalizar_texto(item) in texto:
            return "alta"

    for item in moderados:
        if normalizar_texto(item) in texto:
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
            "revisão",
            "agendar",
            "oleo",
            "óleo",
            "manutencao",
            "manutenção",
            "km",
            "quilometragem",
        ],

        "garantia": [
            "garantia",
            "cobertura",
            "perde garantia",
            "perco garantia",
            "cobre",
            "defeito de fabrica",
            "defeito de fábrica",
        ],

        "pecas": [
            "peca",
            "peça",
            "pecas",
            "peças",
            "pastilha",
            "filtro",
            "relacao",
            "relação",
            "retrovisor",
            "pneu",
            "bateria",
            "vela",
        ],

        "acessorios": [
            "acessorio",
            "acessório",
            "acessorios",
            "acessórios",
            "slider",
            "bau",
            "baú",
            "protetor",
            "escapamento",
            "suporte celular",
            "suporte de celular",
        ],

        "problema_tecnico": [
            "falhando",
            "barulho",
            "vazando",
            "injecao",
            "injeção",
            "painel",
            "motor",
            "nao liga",
            "não liga",
        ],

        "financeiro": [
            "parcelar",
            "pix",
            "cartao",
            "cartão",
            "boleto",
            "valor",
            "preco",
            "preço",
            "quanto custa",
        ],

        "atacado": [
            "atacado",
            "lojista",
            "logista",
            "oficina",
            "revenda",
            "catalogo",
            "catálogo",
            "tabela",
        ],

        "humano": [
            "atendente",
            "humano",
            "consultor",
            "falar com alguem",
            "falar com alguém",
        ],
    }

    melhor = ""
    maior = 0

    for categoria, palavras in intencoes.items():
        pontos = 0

        for palavra in palavras:
            if normalizar_texto(palavra) in texto:
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
            "suporte de celular",
            "protetor de motor",
            "lubrificação de corrente",
        ],

        "fazer 250": [
            "slider",
            "pastilha de freio",
            "kit relação",
            "suporte de celular",
        ],

        "fz25": [
            "slider",
            "pastilha de freio",
            "kit relação",
            "suporte de celular",
        ],

        "lander": [
            "protetor de motor",
            "farol auxiliar",
            "baú",
            "kit relação",
        ],

        "crosser": [
            "baú",
            "protetor de carenagem",
            "kit relação",
        ],

        "nmax": [
            "suporte de celular",
            "bolha",
            "pastilha de freio",
            "limpeza do sistema CVT",
        ],

        "aerox": [
            "bolha",
            "pastilha de freio",
            "óleo",
            "limpeza do sistema CVT",
        ],
    }

    for chave, itens in sugestoes.items():
        if chave in modelo:
            return itens

    return []


# ==========================================
# BASE DE CONHECIMENTO
# ==========================================
def consultar_base_conhecimento(texto):
    if buscar_na_base_conhecimento is None:
        return {
            "encontrou": False,
            "resposta": "",
            "categoria": "",
        }

    try:
        resultado = buscar_na_base_conhecimento(texto)

        if not isinstance(resultado, dict):
            return {
                "encontrou": False,
                "resposta": "",
                "categoria": "",
            }

        return resultado

    except Exception as e:
        print("[FERRAMENTAS IA][ERRO] Erro base_conhecimento:", repr(e), flush=True)
        return {
            "encontrou": False,
            "resposta": "",
            "categoria": "",
        }


# ==========================================
# MANUAL PDF
# ==========================================
def consultar_manual_pdf(modelo, texto):
    funcao_manual = responder_duvida_manual_com_ia or responder_duvida_manual

    if funcao_manual is None:
        return {
            "encontrou": False,
            "resposta": "",
            "fonte": "manual_indisponivel",
        }

    try:
        resultado = funcao_manual(modelo, texto)

        if not isinstance(resultado, dict):
            return {
                "encontrou": False,
                "resposta": "",
                "fonte": "manual_resposta_invalida",
            }

        return resultado

    except Exception as e:
        print("[FERRAMENTAS IA][ERRO] Erro manual PDF:", repr(e), flush=True)
        return {
            "encontrou": False,
            "resposta": "",
            "fonte": "erro_manual_pdf",
        }


# ==========================================
# MONTAR RESPOSTA FALLBACK
# ==========================================
def montar_resposta_fallback(texto, modelo="", urgencia="baixa"):
    intencao = identificar_intencao(texto)

    if urgencia == "alta":
        return (
            "⚠️ Pelo que você descreveu, pode ser uma situação que precisa de avaliação técnica com prioridade.\n\n"
            "Vou encaminhar sua mensagem para um consultor do pós-venda para te orientar com segurança."
        )

    if intencao == "garantia":
        return (
            "Recebi sua dúvida sobre garantia, mas não encontrei uma resposta segura na base.\n\n"
            "Vou encaminhar para um consultor verificar o caso corretamente."
        )

    if intencao == "problema_tecnico":
        return (
            "Entendi o problema informado. Para evitar uma orientação incorreta, o ideal é uma avaliação técnica.\n\n"
            "Vou encaminhar para o pós-venda continuar seu atendimento."
        )

    if intencao == "pecas":
        return (
            "Recebi sua solicitação de peças. Para verificar corretamente, preciso confirmar modelo, ano e item desejado.\n\n"
            "Vou encaminhar para nossa equipe de peças continuar."
        )

    if intencao == "atacado":
        return (
            "Recebi seu interesse em atacado. Nossa equipe comercial pode te passar catálogo, tabela e condições.\n\n"
            "Vou encaminhar seu atendimento."
        )

    return (
        "Não encontrei essa informação com segurança. "
        "Vou encaminhar sua dúvida para um consultor do pós-venda."
    )


# ==========================================
# IA PRINCIPAL
# ==========================================
def responder_ia(texto, modelo=""):
    texto_original = limpar_texto(texto)
    texto_norm = normalizar_texto(texto_original)

    if not modelo:
        modelo = identificar_modelo(texto_norm)

    urgencia = classificar_urgencia(texto_norm)
    intencao = identificar_intencao(texto_norm)
    intencoes_manual = {"revisao", "garantia", "problema_tecnico"}

    # Para dúvidas técnicas, o manual é a fonte oficial. A IA só transforma
    # o trecho encontrado em uma resposta natural.
    if modelo and intencao in intencoes_manual:
        resultado_manual = consultar_manual_pdf(modelo, texto_norm)

        if resultado_manual.get("encontrou"):
            return {
                "fonte": resultado_manual.get("fonte", "manual_pdf"),
                "resposta": resultado_manual.get("resposta", ""),
                "categoria": resultado_manual.get("assunto", "manual"),
                "modelo": resultado_manual.get("modelo", modelo),
                "urgencia": urgencia,
                "intencao": intencao,
                "encaminhar_humano": urgencia == "alta",
            }

    # ==========================================
    # 1) BASE DE CONHECIMENTO
    # ==========================================
    resultado_base = consultar_base_conhecimento(texto_norm)

    if resultado_base.get("encontrou"):
        return {
            "fonte": "base_conhecimento",
            "resposta": resultado_base.get("resposta", ""),
            "categoria": resultado_base.get("categoria", intencao),
            "modelo": modelo,
            "urgencia": urgencia,
            "intencao": intencao,
            "encaminhar_humano": urgencia == "alta",
        }

    # ==========================================
    # 2) MANUAL PDF
    # Só consulta manual se tiver modelo.
    # ==========================================
    if modelo:
        resultado_manual = consultar_manual_pdf(modelo, texto_norm)

        if resultado_manual.get("encontrou"):
            return {
                "fonte": resultado_manual.get("fonte", "manual_pdf"),
                "resposta": resultado_manual.get("resposta", ""),
                "categoria": resultado_manual.get("assunto", "manual"),
                "modelo": resultado_manual.get("modelo", modelo),
                "urgencia": urgencia,
                "intencao": intencao,
                "encaminhar_humano": urgencia == "alta",
            }

    # ==========================================
    # 3) FALLBACK
    # ==========================================
    return {
        "fonte": "fallback",
        "resposta": montar_resposta_fallback(
            texto=texto_norm,
            modelo=modelo,
            urgencia=urgencia,
        ),
        "categoria": intencao or "humano",
        "modelo": modelo,
        "urgencia": urgencia,
        "intencao": intencao,
        "encaminhar_humano": True,
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
