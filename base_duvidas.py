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
# Ajuste conforme onde seus PDFs estão.
# Se seus PDFs estão em static/manuais, mantenha assim.
# ==========================================
PASTA_MANUAIS = os.path.join("static", "manuais")


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


def normalizar_nome_arquivo(nome):
    nome = str(nome or "").lower().strip()
    nome = nome.replace("\\", "/").split("/")[-1]
    nome = re.sub(r"[^a-z0-9]+", "", nome)
    return nome


def limpar_trecho(texto):
    texto = str(texto or "")
    texto = re.sub(r"\s+", " ", texto)
    texto = texto.replace(" ,", ",").replace(" .", ".")
    texto = texto.replace(" :", ":").replace(" ;", ";")
    texto = texto.strip()

    # Remove marcas comuns extraídas de PDF
    texto = re.sub(r"ubf\w*\.book page \d+.*?\d{1,2}:\d{2}.*?(am|pm)?", "", texto)
    texto = re.sub(r"\.{4,}", " ", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def cortar_em_frases(texto, limite=650):
    texto = limpar_trecho(texto)

    if len(texto) <= limite:
        return texto

    partes = re.split(r"(?<=[.!?])\s+", texto)
    saida = ""

    for parte in partes:
        if len(saida + " " + parte) > limite:
            break
        saida = (saida + " " + parte).strip()

    if not saida:
        saida = texto[:limite].strip()

    return saida.strip()


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
# LOCALIZAR PDF COM TOLERÂNCIA
# ==========================================
def localizar_pdf(nome_arquivo):
    caminho_pdf = os.path.join(PASTA_MANUAIS, nome_arquivo)

    if os.path.exists(caminho_pdf):
        return caminho_pdf

    if not os.path.isdir(PASTA_MANUAIS):
        log_erro("Pasta de manuais não encontrada:", PASTA_MANUAIS)
        return ""

    alvo_norm = normalizar_nome_arquivo(nome_arquivo)

    for arquivo in os.listdir(PASTA_MANUAIS):
        arquivo_norm = normalizar_nome_arquivo(arquivo)

        if arquivo_norm == alvo_norm:
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
            "termo de garantia",
        ],

        "oleo": [
            "oleo",
            "lubrificante",
            "viscosidade",
            "yamalube",
            "sae",
            "jaso",
            "api",
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
# RESPOSTAS DIRETAS SEGURAS
# Evita enviar trecho errado ou muito técnico do PDF
# ==========================================
def resposta_direta_por_assunto(modelo_detectado, assunto):
    modelo_formatado = str(modelo_detectado or "").upper()

    if assunto == "oleo":
        return (
            f"🛢️ Para a Yamaha *{modelo_formatado}*, utilize o óleo recomendado no manual do proprietário.\n\n"
            "Antes de completar ou trocar o óleo, o ideal é confirmar a especificação exata com o pós-venda, "
            "para evitar uso de lubrificante incorreto.\n\n"
            "Também posso te ajudar a agendar a revisão."
        )

    if assunto == "garantia":
        return (
            f"🛡️ Sobre garantia da Yamaha *{modelo_formatado}*:\n\n"
            "A cobertura depende das condições do manual, histórico de revisões e avaliação técnica da concessionária.\n\n"
            "Alterações não autorizadas, falta de manutenção ou uso fora das recomendações podem afetar a garantia."
        )

    if assunto == "bateria":
        return (
            f"🔋 Sobre bateria da Yamaha *{modelo_formatado}*:\n\n"
            "Falhas de partida podem estar ligadas à bateria, sistema elétrico ou uso da moto. "
            "O ideal é fazer uma avaliação técnica para confirmar a causa."
        )

    if assunto == "painel":
        return (
            f"⚠️ Sobre luzes ou alertas no painel da Yamaha *{modelo_formatado}*:\n\n"
            "Se alguma luz permanecer acesa ou aparecer alerta no painel, o ideal é trazer a moto para avaliação técnica."
        )

    return ""


# ==========================================
# EXTRAIR TRECHO RELEVANTE
# ==========================================
def extrair_trecho_relevante(texto_manual, pergunta):
    pergunta = normalizar_texto(pergunta)
    assunto = identificar_assunto(pergunta)

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

    palavras_por_assunto = {
        "pneu": [
            "pneu",
            "pneus",
            "pressao",
            "pressao dos pneus",
            "calibragem",
            "calibre",
            "libras",
        ],

        "revisao": [
            "manutencao periodica",
            "tabela de manutencao",
            "revisao",
            "quilometragem",
            "troca",
            "km",
        ],

        "combustivel": [
            "combustivel",
            "gasolina",
            "etanol",
            "alcool",
            "tanque",
        ],
    }

    if assunto in palavras_por_assunto:
        palavras.extend(palavras_por_assunto[assunto])

    if not palavras:
        return ""

    blocos = []
    tamanho_bloco = 1500
    passo = 500

    for i in range(0, len(texto_manual), passo):
        blocos.append(texto_manual[i:i + tamanho_bloco])

    melhor_trecho = ""
    melhor_pontuacao = 0

    for trecho in blocos:
        trecho_limpo = limpar_trecho(trecho)
        pontuacao = 0

        # Penaliza sumário/índice
        if "........................" in trecho_limpo:
            pontuacao -= 10

        if any(x in trecho_limpo[:400] for x in ["indice", "sumario", "conteudo"]):
            pontuacao -= 8

        for palavra in palavras:
            palavra_norm = normalizar_texto(palavra)

            if palavra_norm and palavra_norm in trecho_limpo:
                pontuacao += 3

        if assunto and assunto in trecho_limpo:
            pontuacao += 3

        bonus = [
            "pressao dos pneus",
            "manutencao periodica",
            "tabela de manutencao",
            "combustivel recomendado",
            "gasolina",
            "etanol",
        ]

        for termo in bonus:
            if termo in trecho_limpo:
                pontuacao += 4

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_trecho = trecho_limpo

    if melhor_pontuacao <= 0:
        return ""

    return cortar_em_frases(melhor_trecho, limite=650)


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
# MONTAR RESPOSTA FINAL PARA WHATSAPP
# ==========================================
def montar_resposta_whatsapp(modelo_detectado, assunto, trecho):
    modelo_formatado = str(modelo_detectado or "").upper()
    trecho = cortar_em_frases(trecho, limite=650)

    if not trecho:
        return ""

    titulo_assunto = {
        "pneu": "calibragem/pneus",
        "revisao": "revisão/manutenção",
        "combustivel": "combustível",
        "garantia": "garantia",
        "oleo": "óleo",
        "bateria": "bateria",
        "painel": "painel",
    }.get(assunto, "manual")

    return (
        f"📘 No manual da Yamaha *{modelo_formatado}*, encontrei uma informação sobre *{titulo_assunto}*:\n\n"
        f"{trecho}\n\n"
        "Para confirmar no atendimento, posso te encaminhar para o pós-venda ou ajudar com agendamento."
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

    assunto = identificar_assunto(pergunta_cliente)

    resposta_direta = resposta_direta_por_assunto(modelo_detectado, assunto)

    if resposta_direta:
        return {
            "encontrou": True,
            "modelo": modelo_detectado,
            "assunto": assunto,
            "fonte": "resposta_direta",
            "resposta": resposta_direta
        }

    trecho = buscar_resposta_manual(
        modelo_detectado,
        pergunta_cliente
    )

    if trecho:
        resposta = montar_resposta_whatsapp(
            modelo_detectado=modelo_detectado,
            assunto=assunto,
            trecho=trecho,
        )

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