# ==========================================
# BASE DE DÚVIDAS INTELIGENTE - YAMAHA
# FASE 2 - LEITURA DE MANUAIS PDF
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
PASTA_MANUAIS = os.path.join("templates", "data", "manuais")


# ==========================================
# MANUAIS DISPONÍVEIS
# ==========================================
MANUAIS_YAMAHA = {
    "crosser": "manual_crosser150_2025_eta.pdf",
    "crypton": "manual_crypton_2015.pdf",

    "factor125": "manual_factor125_2025.pdf",
    "factor 125": "manual_factor125_2025.pdf",

    "factor150": "manual_factor150_2025v2.pdf",
    "factor 150": "manual_factor150_2025v2.pdf",
    "factor": "manual_factor150_2025v2.pdf",

    "fz15": "manual_fazerfz15abs_2025_W2.pdf",
    "fz 15": "manual_fazerfz15abs_2025_W2.pdf",
    "fazer 150": "manual_fazerfz15abs_2025_W2.pdf",

    "fazer250": "manual_fazerf25abs_2025.pdf",
    "fazer 250": "manual_fazerf25abs_2025.pdf",
    "fz25": "manual_fazerf25abs_2025.pdf",
    "fz 25": "manual_fazerf25abs_2025.pdf",

    "fluo": "manual_fluoabs_2025.pdf",
    "fluo hybrid": "manual_fluoabshybridconnected_2025.pdf",

    "lander": "manual_landerxtz250_2025.pdf",
    "lander 250": "manual_landerxtz250_2025.pdf",
    "xtz 250": "manual_landerxtz250_2025.pdf",

    "mt03": "manual_mt03absconnected_2026.pdf",
    "mt 03": "manual_mt03absconnected_2026.pdf",

    "mt07": "manual_mt07absconnected_2026.pdf",
    "mt 07": "manual_mt07absconnected_2026.pdf",

    "nmax": "manual_nmaxconnected_2025_etap.pdf",

    "r3": "manual_r3abs_2026.pdf",
    "r 3": "manual_r3abs_2026.pdf",

    "r15": "manual_r15abs_2025.pdf",
    "r 15": "manual_r15abs_2025.pdf",
}


CACHE_MANUAIS = {}


# ==========================================
# LOG
# ==========================================
def log_info(*args):
    print("[INFO]", *args, flush=True)


def log_erro(*args):
    print("[ERRO]", *args, flush=True)


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


def limpar_trecho(texto):
    texto = str(texto or "")
    texto = re.sub(r"\s+", " ", texto)
    texto = texto.replace(" ,", ",").replace(" .", ".")
    return texto.strip()


# ==========================================
# IDENTIFICAR MODELO
# ==========================================
def identificar_modelo(modelo):
    modelo = normalizar_texto(modelo)

    if not modelo:
        return ""

    chaves_ordenadas = sorted(
        MANUAIS_YAMAHA.keys(),
        key=len,
        reverse=True
    )

    for chave in chaves_ordenadas:
        chave_norm = normalizar_texto(chave)

        if chave_norm and chave_norm in modelo:
            return chave

    return ""


# ==========================================
# CARREGAR MANUAL PDF
# ==========================================
def carregar_manual_pdf(modelo):
    if PdfReader is None:
        log_erro("PyPDF2 não instalado. Adicione PyPDF2 no requirements.txt")
        return ""

    modelo_id = identificar_modelo(modelo)

    if not modelo_id:
        return ""

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
                texto_manual += "\n" + (pagina.extract_text() or "")
            except Exception as e:
                log_erro("Erro ao ler página PDF:", repr(e))

        texto_manual = normalizar_texto(texto_manual)

        CACHE_MANUAIS[modelo_id] = texto_manual

        log_info("Manual carregado:", modelo_id)

        return texto_manual

    except Exception as e:
        log_erro("Erro lendo PDF:", repr(e))
        return ""


# ==========================================
# ASSUNTOS
# ==========================================
def identificar_assunto(pergunta):
    pergunta = normalizar_texto(pergunta)

    assuntos = {
        "garantia": [
            "garantia",
            "perde garantia",
            "cobertura",
            "defeito",
        ],

        "oleo": [
            "oleo",
            "lubrificante",
            "viscosidade",
            "yamalube",
        ],

        "revisao": [
            "revisao",
            "manutencao",
            "troca",
            "periodica",
            "quilometragem",
            "km",
        ],

        "pneu": [
            "pneu",
            "calibragem",
            "pressao",
            "libras",
        ],

        "combustivel": [
            "combustivel",
            "gasolina",
            "etanol",
            "alcool",
        ],

        "painel": [
            "painel",
            "luz",
            "indicador",
            "injeção",
            "injecao",
            "alerta",
        ],

        "bateria": [
            "bateria",
            "partida",
            "eletrica",
            "elétrica",
        ],
    }

    for assunto, palavras in assuntos.items():
        for palavra in palavras:
            if normalizar_texto(palavra) in pergunta:
                return assunto

    return ""


# ==========================================
# RESPOSTAS PADRÃO
# ==========================================
RESPOSTAS_PADRAO = {
    "garantia": (
        "A garantia Yamaha cobre defeitos de fabricação conforme as condições do manual do proprietário. "
        "Alterações não autorizadas, falta de revisões ou uso fora das recomendações podem afetar a cobertura."
    ),

    "oleo": (
        "O óleo correto pode variar conforme o modelo. O ideal é consultar o manual específico da moto "
        "ou confirmar com o pós-venda para evitar uso de lubrificante incorreto."
    ),

    "revisao": (
        "As revisões devem seguir a quilometragem e o prazo indicados no manual do proprietário. "
        "Manter as revisões em dia ajuda na segurança, garantia e valorização da moto."
    ),

    "pneu": (
        "A calibragem correta dos pneus varia conforme o modelo e condição de uso. "
        "O ideal é confirmar no manual da motocicleta ou com o pós-venda."
    ),

    "combustivel": (
        "Use sempre combustível de boa procedência e siga as orientações do manual da sua Yamaha."
    ),

    "painel": (
        "Luzes ou alertas no painel devem ser verificados com atenção. "
        "Se o alerta permanecer aceso, o ideal é trazer a moto para avaliação técnica."
    ),

    "bateria": (
        "Problemas de partida podem estar relacionados à bateria, sistema elétrico ou uso da moto. "
        "O ideal é fazer uma avaliação técnica."
    ),
}


# ==========================================
# EXTRAIR TRECHO RELEVANTE
# ==========================================
def extrair_trecho_relevante(texto_manual, pergunta):
    pergunta = normalizar_texto(pergunta)

    palavras_ignoradas = {
        "minha", "meu", "moto", "yamaha", "quanto", "como",
        "qual", "onde", "porque", "pra", "para", "com",
        "tem", "esta", "esse", "essa", "isso", "quero",
        "preciso", "saber", "usar", "devo", "pode",
    }

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

    blocos = []
    tamanho_bloco = 1200
    passo = 700

    for i in range(0, len(texto_manual), passo):
        blocos.append(texto_manual[i:i + tamanho_bloco])

    melhor_trecho = ""
    melhor_pontuacao = 0

    for trecho in blocos:
        pontuacao = 0

        for palavra in palavras:
            if palavra in trecho:
                pontuacao += 2

        assunto = identificar_assunto(pergunta)

        if assunto and assunto in trecho:
            pontuacao += 3

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_trecho = trecho

    if melhor_pontuacao <= 0:
        return ""

    return limpar_trecho(melhor_trecho[:1000])


# ==========================================
# BUSCA NO MANUAL
# ==========================================
def buscar_resposta_manual(modelo, pergunta):
    texto_manual = carregar_manual_pdf(modelo)

    if not texto_manual:
        return ""

    return extrair_trecho_relevante(
        texto_manual,
        pergunta
    )


# ==========================================
# RESPOSTA PRINCIPAL
# ==========================================
def responder_duvida_manual(modelo, pergunta_cliente):
    modelo_original = str(modelo or "").strip()
    pergunta_original = str(pergunta_cliente or "").strip()

    modelo = normalizar_texto(modelo)
    pergunta_cliente = normalizar_texto(pergunta_cliente)

    if not pergunta_cliente:
        return {
            "encontrou": False,
            "modelo": modelo_original,
            "assunto": "",
            "fonte": "sem_pergunta",
            "resposta": "Me envie sua dúvida para eu consultar a base Yamaha."
        }

    if not modelo:
        return {
            "encontrou": False,
            "modelo": "",
            "assunto": identificar_assunto(pergunta_cliente),
            "fonte": "sem_modelo",
            "resposta": "Informe o modelo da sua Yamaha para eu consultar o manual correto."
        }

    modelo_detectado = identificar_modelo(modelo)

    if not modelo_detectado:
        return {
            "encontrou": False,
            "modelo": modelo_original,
            "assunto": identificar_assunto(pergunta_cliente),
            "fonte": "manual_nao_encontrado",
            "resposta": "Ainda não encontrei o manual desse modelo na base. Vou encaminhar para o pós-venda."
        }

    trecho = buscar_resposta_manual(
        modelo_detectado,
        pergunta_cliente
    )

    if trecho:
        resposta = (
            f"📘 Encontrei uma informação no manual da Yamaha *{modelo_detectado.upper()}*:\n\n"
            f"{trecho}\n\n"
            "Se quiser, também posso te ajudar com revisão, garantia, peças, acessórios ou agendamento."
        )

        return {
            "encontrou": True,
            "modelo": modelo_detectado,
            "assunto": identificar_assunto(pergunta_cliente),
            "fonte": "manual_pdf",
            "resposta": resposta
        }

    assunto = identificar_assunto(pergunta_cliente)

    if assunto in RESPOSTAS_PADRAO:
        return {
            "encontrou": True,
            "modelo": modelo_detectado,
            "assunto": assunto,
            "fonte": "resposta_padrao",
            "resposta": RESPOSTAS_PADRAO[assunto]
        }

    return {
        "encontrou": False,
        "modelo": modelo_detectado,
        "assunto": assunto,
        "fonte": "nao_encontrado",
        "resposta": (
            "Não encontrei essa informação com segurança no manual. "
            "Vou encaminhar sua dúvida para o pós-venda."
        )
    }
