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


PASTA_MANUAIS = os.getenv("CAMINHO_MANUAIS", os.path.join("static", "manuais"))

MANUAIS_YAMAHA = {
    "crosser": "manual_crosser150_2025_eta.pdf",
    "crypton": "manual_crypton_2015.pdf",

    "factor125": "manual_factor125_2025.pdf",
    "factor 125": "manual_factor125_2025.pdf",

    "factor150": "manual_factor150_2025.v2.pdf",
    "factor 150": "manual_factor150_2025.v2.pdf",
    "factor": "manual_factor150_2025.v2.pdf",

    "fz15": "manual_fazerfz15abs_2025_W2.pdf",
    "fz 15": "manual_fazerfz15abs_2025_W2.pdf",
    "fazer 150": "manual_fazerfz15abs_2025_W2.pdf",

    "fazer250": "manual_fazerfz25abs_2025.pdf",
    "fazer 250": "manual_fazerfz25abs_2025.pdf",
    "fz25": "manual_fazerfz25abs_2025.pdf",
    "fz 25": "manual_fazerfz25abs_2025.pdf",

    "fluo": "manual_fluoabs_2025.pdf",
    "fluo hybrid": "manual_fluoabshybridconnected_2026.pdf",

    "lander": "manual_landerxtz250_2025.pdf",
    "lander 250": "manual_landerxtz250_2025.pdf",

    "mt03": "manual_mt03absconnected_2026.pdf",
    "mt 03": "manual_mt03absconnected_2026.pdf",

    "mt07": "manual_mt07absconnected_2026.pdf",
    "mt 07": "manual_mt07absconnected_2026.pdf",

    "nmax": "manual_nmaxconnected_2025_eta.pdf",

    "r3": "manual_r3abs_2026.pdf",
    "r 3": "manual_r3abs_2026.pdf",

    "r15": "manual_r15abs_2025.pdf",
    "r 15": "manual_r15abs_2025.pdf",
}

CACHE_MANUAIS = {}


def log_info(*args):
    print("[IA DÚVIDAS][INFO]", *args, flush=True)


def log_erro(*args):
    print("[IA DÚVIDAS][ERRO]", *args, flush=True)


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
    texto = texto.replace(" :", ":").replace(" ;", ";")
    return texto.strip()


def normalizar_nome_arquivo(nome):
    nome = str(nome or "").lower().strip()
    nome = nome.replace("\\", "/").split("/")[-1]
    nome = re.sub(r"[^a-z0-9]+", "", nome)
    return nome


def identificar_modelo(modelo):
    modelo = normalizar_texto(modelo)

    if not modelo:
        return ""

    for chave in sorted(MANUAIS_YAMAHA.keys(), key=len, reverse=True):
        if normalizar_texto(chave) in modelo:
            return chave

    return ""


def localizar_pdf(nome_arquivo):
    caminho_pdf = os.path.join(PASTA_MANUAIS, nome_arquivo)

    if os.path.exists(caminho_pdf):
        return caminho_pdf

    if not os.path.isdir(PASTA_MANUAIS):
        log_erro("Pasta de manuais não encontrada:", PASTA_MANUAIS)
        return ""

    alvo_norm = normalizar_nome_arquivo(nome_arquivo)

    for arquivo in os.listdir(PASTA_MANUAIS):
        if normalizar_nome_arquivo(arquivo) == alvo_norm:
            return os.path.join(PASTA_MANUAIS, arquivo)

    partes_alvo = [
        p for p in re.split(r"[_\-. ]+", nome_arquivo.lower())
        if len(p) >= 3
    ]

    melhor = ""
    melhor_score = 0

    for arquivo in os.listdir(PASTA_MANUAIS):
        arquivo_lower = arquivo.lower()
        score = sum(1 for parte in partes_alvo if parte in arquivo_lower)

        if score > melhor_score:
            melhor_score = score
            melhor = arquivo

    if melhor and melhor_score >= 2:
        return os.path.join(PASTA_MANUAIS, melhor)

    return ""


def carregar_manual_pdf(modelo):
    if PdfReader is None:
        log_erro("PyPDF2 não instalado. Adicione PyPDF2 no requirements.txt")
        return ""

    modelo_id = identificar_modelo(modelo)

    if not modelo_id:
        log_erro("Modelo não identificado:", modelo)
        return ""

    if modelo_id in CACHE_MANUAIS:
        return CACHE_MANUAIS[modelo_id]

    nome_arquivo = MANUAIS_YAMAHA.get(modelo_id)

    if not nome_arquivo:
        log_erro("Manual não mapeado:", modelo_id)
        return ""

    caminho_pdf = localizar_pdf(nome_arquivo)

    if not caminho_pdf:
        log_erro("Manual não encontrado:", os.path.join(PASTA_MANUAIS, nome_arquivo))
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


def identificar_assunto(pergunta):
    pergunta = normalizar_texto(pergunta)

    assuntos = {
        "garantia": [
            "garantia", "perde garantia", "cobertura", "termo de garantia",
            "defeito", "fabrica",
        ],
        "oleo": [
            "oleo", "lubrificante", "viscosidade", "yamalube",
            "sae", "jaso", "api",
        ],
        "revisao": [
            "revisao", "manutencao", "troca", "quilometragem",
            "periodica", "km", "revisar",
        ],
        "pneu": [
            "pneu", "calibragem", "pressao", "libras",
        ],
        "combustivel": [
            "combustivel", "gasolina", "etanol", "alcool",
        ],
        "bateria": [
            "bateria", "partida", "eletrica", "sistema eletrico",
        ],
        "painel": [
            "painel", "luz", "indicador", "injecao", "alerta",
            "advertencia",
        ],
    }

    for assunto, palavras in assuntos.items():
        for palavra in palavras:
            if normalizar_texto(palavra) in pergunta:
                return assunto

    return ""


def extrair_trecho_relevante(texto_manual, pergunta):
    pergunta = normalizar_texto(pergunta)
    assunto = identificar_assunto(pergunta)

    palavras_ignoradas = {
        "minha", "meu", "moto", "yamaha", "quanto", "como",
        "qual", "onde", "porque", "pra", "para", "com",
        "tem", "esta", "esse", "essa", "isso", "quero",
        "preciso", "pode", "usar", "saber", "devo",
    }

    palavras = []

    for palavra in pergunta.split():
        palavra = palavra.strip()

        if len(palavra) < 4:
            continue

        if palavra in palavras_ignoradas:
            continue

        palavras.append(palavra)

    palavras_por_assunto = {
        "pneu": [
            "pneu", "pressao", "pressao dos pneus", "calibragem",
            "calibre",
        ],
        "revisao": [
            "manutencao periodica", "tabela de manutencao",
            "revisao", "quilometragem", "troca",
        ],
        "garantia": [
            "garantia", "termo de garantia", "cobertura",
            "perda da garantia",
        ],
        "combustivel": [
            "combustivel", "gasolina", "etanol", "alcool",
        ],
        "bateria": [
            "bateria", "partida", "sistema eletrico",
        ],
        "painel": [
            "painel", "luz indicadora", "luz de advertencia",
            "injecao", "indicador",
        ],
    }

    if assunto in palavras_por_assunto:
        palavras.extend(palavras_por_assunto[assunto])

    if not palavras:
        return ""

    blocos_ruins = [
        "indice",
        "sumario",
        "conteudo",
        "informacoes de seguranca",
        "descricao",
        "pagina",
        "................",
    ]

    melhor_trecho = ""
    melhor_pontuacao = 0
    tamanho_bloco = 2200
    passo = 700

    for i in range(0, len(texto_manual), passo):
        trecho = texto_manual[i:i + tamanho_bloco]
        trecho_limpo = limpar_trecho(trecho)

        pontuacao = 0

        for ruim in blocos_ruins:
            if ruim in trecho_limpo[:600]:
                pontuacao -= 6

        for palavra in palavras:
            palavra_norm = normalizar_texto(palavra)

            if palavra_norm and palavra_norm in trecho_limpo:
                pontuacao += 3

        bonus_por_assunto = {
            "pneu": ["pressao dos pneus", "calibragem", "pneu"],
            "revisao": ["manutencao periodica", "tabela de manutencao", "revisao"],
            "garantia": ["garantia", "termo de garantia", "cobertura"],
            "combustivel": ["combustivel", "gasolina"],
            "bateria": ["bateria", "partida"],
            "painel": ["painel", "luz indicadora", "advertencia"],
        }

        for termo in bonus_por_assunto.get(assunto, []):
            if termo in trecho_limpo:
                pontuacao += 5

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_trecho = trecho_limpo

    if not melhor_trecho or melhor_pontuacao <= 0:
        return ""

    return melhor_trecho[:1500]


RESPOSTAS_PADRAO = {
    "garantia": (
        "A garantia Yamaha cobre defeitos de fabricação conforme o manual do proprietário. "
        "Alterações elétricas, escapamentos não homologados, uso de peças paralelas "
        "e revisões fora da concessionária podem impactar a cobertura."
    ),
    "oleo": (
        "Utilize sempre o óleo recomendado no manual da Yamaha e respeite a viscosidade indicada "
        "para o modelo. Para evitar erro de aplicação, confirme a especificação com o pós-venda."
    ),
    "revisao": (
        "As revisões devem ser realizadas conforme quilometragem e prazo informados no manual "
        "do proprietário. Manter as revisões em dia ajuda na segurança e na garantia."
    ),
    "pneu": (
        "A calibragem correta dos pneus está especificada no manual da motocicleta e pode variar "
        "conforme modelo, carga e condição de uso."
    ),
    "combustivel": (
        "Use sempre combustível de boa procedência e siga as orientações do manual da Yamaha."
    ),
    "bateria": (
        "Problemas de partida podem estar relacionados à bateria, sistema elétrico ou uso da moto. "
        "O ideal é fazer uma avaliação técnica."
    ),
    "painel": (
        "Luzes ou alertas no painel devem ser verificados com atenção. "
        "Se o alerta permanecer aceso, o ideal é trazer a moto para avaliação técnica."
    ),
}


def resposta_oleo_segura(modelo_detectado):
    return {
        "encontrou": True,
        "modelo": modelo_detectado,
        "assunto": "oleo",
        "fonte": "base_tecnica_oleo",
        "resposta": (
            f"🛢️ Para a Yamaha *{modelo_detectado.upper()}*, utilize o óleo recomendado no manual do proprietário.\n\n"
            "O ideal é confirmar a especificação exata com o pós-venda antes de completar ou trocar o óleo, "
            "para evitar uso de lubrificante incorreto.\n\n"
            "Também posso te ajudar a agendar a revisão ou verificar peças e acessórios."
        )
    }


def buscar_resposta_manual(modelo, pergunta):
    texto_manual = carregar_manual_pdf(modelo)

    if not texto_manual:
        return ""

    return extrair_trecho_relevante(texto_manual, pergunta)


def responder_duvida_manual(modelo, pergunta_cliente):
    modelo_original = str(modelo or "").strip()
    pergunta_original = str(pergunta_cliente or "").strip()

    modelo = normalizar_texto(modelo_original)
    pergunta_cliente = normalizar_texto(pergunta_original)

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
            "fonte": "modelo_nao_encontrado",
            "resposta": "Ainda não encontrei o manual desse modelo na base."
        }

    assunto = identificar_assunto(pergunta_cliente)

    if assunto == "oleo":
        return resposta_oleo_segura(modelo_detectado)

    trecho = buscar_resposta_manual(modelo_detectado, pergunta_cliente)

    if trecho:
        resposta = f"""
📖 Encontrei uma informação no manual da Yamaha *{modelo_detectado.upper()}*:

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
            "modelo": modelo_detectado,
            "assunto": assunto,
            "fonte": "manual_pdf",
            "resposta": resposta
        }

    if assunto in RESPOSTAS_PADRAO:
        return {
            "encontrou": True,
            "modelo": modelo_detectado,
            "assunto": assunto,
            "fonte": "resposta_padrao",
            "resposta": RESPOSTAS_PADRAO[assunto].strip()
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