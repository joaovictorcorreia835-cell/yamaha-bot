# ==========================================
# BASE DE DÚVIDAS INTELIGENTE - YAMAHA
# LEITURA DE MANUAIS PDF
# ==========================================

import os
import re

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None


# ==========================================
# PASTA DOS MANUAIS
# ==========================================
PASTA_MANUAIS = "manuais"


# ==========================================
# MANUAIS DISPONÍVEIS
# ==========================================
MANUAIS_YAMAHA = {

    "crosser": "manual_crosser150_2025_eta.pdf",

    "crypton": "manual_crypton_2015.pdf",

    "factor125": "manual_factor125_2025.pdf",

    "factor150": "manual_factor150_2025v2.pdf",

    "fz15": "manual_fazerfz15abs_2025_W2.pdf",

    "fazer250": "manual_fazerf25abs_2025.pdf",
    "fazer 250": "manual_fazerf25abs_2025.pdf",
    "fz25": "manual_fazerf25abs_2025.pdf",

    "fluo": "manual_fluoabs_2025.pdf",

    "fluo hybrid": "manual_fluoabshybridconnected_2025.pdf",

    "lander": "manual_landerxtz250_2025.pdf",
    "lander 250": "manual_landerxtz250_2025.pdf",

    "mt03": "manual_mt03absconnected_2026.pdf",

    "mt07": "manual_mt07absconnected_2026.pdf",

    "nmax": "manual_nmaxconnected_2025_etap.pdf",

    "r3": "manual_r3abs_2026.pdf",

    "r15": "manual_r15abs_2025.pdf",
}


# ==========================================
# CACHE
# ==========================================
CACHE_MANUAIS = {}


# ==========================================
# LOG
# ==========================================
def log_info(*args):
    print("[INFO]", *args, flush=True)


def log_erro(*args):
    print("[ERRO]", *args, flush=True)


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
# IDENTIFICAR MODELO
# ==========================================
def identificar_modelo(modelo):
    modelo = normalizar_texto(modelo)

    for chave in MANUAIS_YAMAHA.keys():
        if chave in modelo:
            return chave

    return ""


# ==========================================
# CARREGAR MANUAL PDF
# ==========================================
def carregar_manual_pdf(modelo):

    if PdfReader is None:
        log_erro("PyPDF2 não instalado")
        return ""

    modelo_id = identificar_modelo(modelo)

    if not modelo_id:
        return ""

    # CACHE
    if modelo_id in CACHE_MANUAIS:
        return CACHE_MANUAIS[modelo_id]

    nome_arquivo = MANUAIS_YAMAHA.get(modelo_id)

    if not nome_arquivo:
        return ""

    caminho_pdf = os.path.join(PASTA_MANUAIS, nome_arquivo)

    if not os.path.exists(caminho_pdf):
        log_erro("Manual não encontrado:", caminho_pdf)
        return ""

    texto_manual = ""

    try:

        log_info("Lendo manual:", caminho_pdf)

        reader = PdfReader(caminho_pdf)

        for pagina in reader.pages:

            try:
                texto = pagina.extract_text() or ""
                texto_manual += "\n" + texto

            except Exception as e:
                log_erro("Erro página PDF:", repr(e))

        texto_manual = normalizar_texto(texto_manual)

        CACHE_MANUAIS[modelo_id] = texto_manual

        log_info("Manual carregado:", modelo_id)

        return texto_manual

    except Exception as e:
        log_erro("Erro lendo PDF:", repr(e))
        return ""


# ==========================================
# EXTRAIR TRECHO RELEVANTE
# ==========================================
def extrair_trecho_relevante(texto_manual, pergunta):

    pergunta = normalizar_texto(pergunta)

    palavras_ignoradas = [
        "minha",
        "meu",
        "moto",
        "yamaha",
        "quanto",
        "como",
        "qual",
        "onde",
        "porque",
        "pra",
        "para",
        "com",
        "tem",
        "esta",
        "esse",
        "essa",
        "isso",
        "quero",
        "preciso",
    ]

    palavras = []

    for palavra in pergunta.split():

        palavra = palavra.strip()

        if len(palavra) < 4:
            continue

        if palavra in palavras_ignoradas:
            continue

        palavras.append(palavra)

    if not palavras:
        return ""

    melhor_trecho = ""
    melhor_pontuacao = 0

    tamanho_bloco = 1500

    for i in range(0, len(texto_manual), tamanho_bloco):

        trecho = texto_manual[i:i + tamanho_bloco]

        pontuacao = 0

        for palavra in palavras:

            if palavra in trecho:
                pontuacao += 1

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_trecho = trecho

    if not melhor_trecho:
        return ""

    melhor_trecho = re.sub(r"\s+", " ", melhor_trecho)

    return melhor_trecho[:1200]


# ==========================================
# RESPOSTAS PADRÃO
# ==========================================
RESPOSTAS_PADRAO = {

    "garantia": """
A garantia Yamaha cobre defeitos de fabricação conforme manual do proprietário.
Alterações elétricas, escapamentos não homologados e revisões fora da concessionária podem impactar a garantia.
""",

    "oleo": """
Utilize sempre o óleo recomendado no manual da Yamaha e respeite a viscosidade indicada para o modelo.
""",

    "revisao": """
As revisões devem ser realizadas conforme quilometragem e prazo informados no manual do proprietário.
""",

    "pneu": """
A calibragem correta dos pneus está especificada no manual da motocicleta.
""",
}


# ==========================================
# IDENTIFICAR ASSUNTO
# ==========================================
def identificar_assunto(pergunta):

    pergunta = normalizar_texto(pergunta)

    assuntos = {

        "garantia": [
            "garantia",
            "perde garantia",
            "cobertura",
        ],

        "oleo": [
            "oleo",
            "lubrificante",
            "viscosidade",
        ],

        "revisao": [
            "revisao",
            "manutencao",
            "troca",
        ],

        "pneu": [
            "pneu",
            "calibragem",
            "pressao",
        ],
    }

    for assunto, palavras in assuntos.items():

        for palavra in palavras:

            if palavra in pergunta:
                return assunto

    return ""


# ==========================================
# BUSCA NO MANUAL
# ==========================================
def buscar_resposta_manual(modelo, pergunta):

    texto_manual = carregar_manual_pdf(modelo)

    if not texto_manual:
        return ""

    trecho = extrair_trecho_relevante(
        texto_manual,
        pergunta
    )

    return trecho


# ==========================================
# RESPOSTA PRINCIPAL
# ==========================================
def responder_duvida_manual(modelo, pergunta_cliente):

    modelo = normalizar_texto(modelo)
    pergunta_cliente = normalizar_texto(pergunta_cliente)

    if not modelo:

        return {
            "encontrou": False,
            "resposta":
                "Informe o modelo da sua Yamaha para eu consultar o manual."
        }

    modelo_detectado = identificar_modelo(modelo)

    if not modelo_detectado:

        return {
            "encontrou": False,
            "resposta":
                "Ainda não encontrei o manual desse modelo na base."
        }

    # ==========================================
    # BUSCA NO MANUAL
    # ==========================================
    trecho = buscar_resposta_manual(
        modelo_detectado,
        pergunta_cliente
    )

    if trecho:

        resposta = f"""
Encontrei uma informação no manual da Yamaha {modelo_detectado.upper()}:

{trecho}

Caso queira, também posso ajudar com:
• revisão
• garantia
• peças
• acessórios
• agendamento
""".strip()

        return {
            "encontrou": True,
            "resposta": resposta
        }

    # ==========================================
    # RESPOSTA PADRÃO
    # ==========================================
    assunto = identificar_assunto(pergunta_cliente)

    if assunto in RESPOSTAS_PADRAO:

        return {
            "encontrou": True,
            "resposta": RESPOSTAS_PADRAO[assunto].strip()
        }

    # ==========================================
    # FALLBACK
    # ==========================================
    return {
        "encontrou": False,
        "resposta":
            "Não encontrei essa informação com segurança no manual. Vou encaminhar sua dúvida para o pós-venda."
    }


# ==========================================
# TESTE LOCAL
# ==========================================
if __name__ == "__main__":

    modelo = "FZ15"

    pergunta = "qual oleo usar?"

    resultado = responder_duvida_manual(
        modelo,
        pergunta
    )

    print("\n")
    print(resultado["resposta"])
    print("\n")