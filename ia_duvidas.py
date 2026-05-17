# ==========================================
# BASE DE DÚVIDAS INTELIGENTE - YAMAHA
# LEITURA DE MANUAIS PDF
# ==========================================

import os
import re
import unicodedata

try:
    from pypdf import PdfReader
except ImportError:
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
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
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
            "condicoes gerais da garantia", "certificado de garantia",
            "perda da garantia",
        ],
        "oleo": [
            "oleo", "lubrificante", "viscosidade", "yamalube",
            "sae", "jaso", "api", "oleo do motor",
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

    bonus_por_assunto = {
        "pneu": ["pressao dos pneus", "calibragem", "pneu"],
        "revisao": ["manutencao periodica", "tabela de manutencao", "revisao"],
        "garantia": [
            "garantia", "termo de garantia", "cobertura",
            "condicoes gerais da garantia", "certificado de garantia",
        ],
        "oleo": ["oleo", "oleo do motor", "lubrificante", "yamalube", "viscosidade"],
        "combustivel": ["combustivel", "gasolina"],
        "bateria": ["bateria", "partida"],
        "painel": ["painel", "luz indicadora", "advertencia"],
    }

    blocos_ruins = [
        "indice",
        "sumario",
        "conteudo",
        "informacoes de seguranca",
        "descricao",
        "pagina",
        "................",
    ]

    termos_assunto = bonus_por_assunto.get(assunto, [])
    melhor_trecho = ""
    melhor_pontuacao = 0

    for termo in termos_assunto:
        termo_norm = normalizar_texto(termo)
        inicio_busca = 0

        while termo_norm:
            pos = texto_manual.find(termo_norm, inicio_busca)

            if pos < 0:
                break

            inicio_busca = pos + len(termo_norm)
            inicio = max(0, pos - 120)
            fim = min(len(texto_manual), pos + 1800)
            trecho_limpo = limpar_trecho(texto_manual[inicio:fim])
            pontuacao = 8

            if assunto == "garantia" and termo_norm in [
                "termo de garantia",
                "condicoes gerais da garantia",
                "certificado de garantia",
            ]:
                pontuacao += 14

            for ruim in blocos_ruins:
                if ruim in trecho_limpo[:500]:
                    pontuacao -= 8

            if assunto == "garantia" and "perd" not in pergunta:
                if "perda da cobertura" in trecho_limpo or "perda de cobertura" in trecho_limpo:
                    pontuacao -= 12

            for palavra in palavras:
                palavra_norm = normalizar_texto(palavra)

                if palavra_norm and palavra_norm in trecho_limpo:
                    pontuacao += 3

            for termo_bonus in termos_assunto:
                if normalizar_texto(termo_bonus) in trecho_limpo:
                    pontuacao += 5

            if pontuacao > melhor_pontuacao:
                melhor_pontuacao = pontuacao
                melhor_trecho = trecho_limpo

    if melhor_trecho and melhor_pontuacao >= 13:
        return melhor_trecho[:1500]

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

        for termo in bonus_por_assunto.get(assunto, []):
            if termo in trecho_limpo:
                pontuacao += 5

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_trecho = trecho_limpo

    if not melhor_trecho or melhor_pontuacao <= 0:
        return ""

    return melhor_trecho[:1500]


def buscar_resposta_manual(modelo, pergunta):
    texto_manual = carregar_manual_pdf(modelo)

    if not texto_manual:
        return ""

    return extrair_trecho_relevante(texto_manual, pergunta)


def palavras_chave_resumo(pergunta, assunto):
    pergunta = normalizar_texto(pergunta)
    palavras = []

    ignoradas = {
        "minha", "meu", "moto", "yamaha", "quanto", "como",
        "qual", "onde", "porque", "para", "voce", "saber",
        "sobre", "isso", "essa", "esse", "esta", "fica",
    }

    for palavra in pergunta.split():
        if len(palavra) >= 4 and palavra not in ignoradas:
            palavras.append(palavra)

    por_assunto = {
        "garantia": [
            "garantia", "cobertura", "defeito", "fabricacao",
            "manutencao", "revisao", "perda", "condicionada",
            "manual", "proprietario",
        ],
        "oleo": [
            "oleo", "motor", "lubrificante", "viscosidade",
            "yamalube", "sae", "api", "jaso",
        ],
        "revisao": [
            "revisao", "manutencao", "periodica", "quilometragem",
            "km", "troca", "tabela",
        ],
        "painel": [
            "painel", "luz", "indicadora", "advertencia",
            "injecao", "alerta",
        ],
        "pneu": ["pneu", "pressao", "calibragem"],
        "combustivel": ["combustivel", "gasolina", "etanol"],
        "bateria": ["bateria", "partida", "eletrica"],
    }

    palavras.extend(por_assunto.get(assunto, []))
    return list(dict.fromkeys(palavras))


def limpar_frase_manual(frase):
    frase = limpar_trecho(frase)
    frase = re.sub(r"\b[a-z]{1,3}\d[a-z0-9]{2,}\b", " ", frase)
    frase = re.sub(r"^\d+\.\s*", "", frase)
    frase = frase.replace("destetermo", "deste termo")
    frase = frase.replace("ofarol", "o farol")
    frase = frase.replace("oforol", "o farol")
    frase = frase.replace("pis-ca", "pisca")
    frase = frase.replace("moni- tora", "monitora")
    frase = frase.replace("ad- vertencia", "advertencia")
    frase = re.sub(r"\s+", " ", frase).strip(" .;:-")

    if not frase:
        return ""

    frase = frase[:1].upper() + frase[1:]

    if frase[-1] not in ".!?":
        frase += "."

    return frase


def dividir_frases_manual(trecho):
    trecho = limpar_trecho(trecho)
    partes = re.split(r"(?<=[.!?])\s+|;\s+|\n+", trecho)
    frases = []

    for parte in partes:
        parte = limpar_frase_manual(parte)

        if 45 <= len(parte) <= 360:
            frases.append(parte)

    return frases


def frase_ruim_para_resumo(frase, assunto):
    frase_norm = normalizar_texto(frase)

    ruins = [
        "qualquer especie de garantia extra",
        "contratual oferecida pela fabricante",
        "por mera liberalidade",
        "conta e risco",
        "expensas daquele",
        "yamaha motor da amazonia",
        "pagina",
        "copyright",
        "thursday",
        "october",
        "january",
        "pm ",
        "am ",
        "tir da posicao",
        "luz indicadora do pisca",
        "ponto morto",
    ]

    if any(ruim in frase_norm for ruim in ruins):
        return True

    if assunto == "garantia" and "perd" not in frase_norm:
        excesso_perda = [
            "perda da cobertura sobre essa peca",
            "perda de cobertura sobre essa peca",
        ]

        if any(ruim in frase_norm for ruim in excesso_perda):
            return True

    return False


def extrair_valor_campo(trecho, campo, proximos_campos=None):
    proximos_campos = proximos_campos or []
    trecho_norm = limpar_trecho(trecho)
    campo_norm = normalizar_texto(campo)
    texto_norm = normalizar_texto(trecho_norm)
    inicio = texto_norm.find(campo_norm)

    if inicio < 0:
        return ""

    inicio_valor = inicio + len(campo_norm)
    fim = len(trecho_norm)

    for proximo in proximos_campos:
        pos = texto_norm.find(normalizar_texto(proximo), inicio_valor)

        if pos > inicio_valor and pos < fim:
            fim = pos

    return limpar_frase_manual(trecho_norm[inicio_valor:fim])


def resumir_oleo_manual(modelo_detectado, trecho):
    marca = extrair_valor_campo(
        trecho,
        "marca recomendada:",
        ["grau de viscosidade", "especificacao do oleo", "quantidade de oleo"],
    )
    viscosidade = extrair_valor_campo(
        trecho,
        "grau de viscosidade sae:",
        ["especificacao do oleo", "quantidade de oleo", "combustivel"],
    )
    especificacao = extrair_valor_campo(
        trecho,
        "especificacao do oleo de motor:",
        ["quantidade de oleo", "combustivel", "troca de oleo"],
    )
    quantidade = extrair_valor_campo(
        trecho,
        "quantidade de oleo do motor:",
        ["combustivel", "injecao", "transmissao"],
    )

    linhas = []

    if marca:
        linhas.append(f"Marca recomendada: {marca}")

    if viscosidade:
        linhas.append(f"Viscosidade SAE: {viscosidade}")

    if especificacao:
        linhas.append(f"Especificação: {especificacao}")

    if quantidade:
        linhas.append(f"Quantidade indicada: {quantidade}")

    if not linhas:
        return ""

    return (
        f"📘 Pelo manual da Yamaha *{modelo_detectado.upper()}*:\n\n"
        + "\n".join(linhas[:4])
        + "\n\nSe quiser, posso encaminhar você para um consultor confirmar detalhes específicos. 🤝"
    )


def resumir_trecho_manual(modelo_detectado, pergunta, trecho, assunto):
    if assunto == "oleo":
        return resumir_oleo_manual(modelo_detectado, trecho)

    frases = dividir_frases_manual(trecho)
    palavras = palavras_chave_resumo(pergunta, assunto)
    selecionadas = []
    vistas = set()

    for frase in frases:
        if frase_ruim_para_resumo(frase, assunto):
            continue

        frase_norm = normalizar_texto(frase)
        pontuacao = sum(1 for palavra in palavras if palavra and palavra in frase_norm)

        if assunto and assunto in frase_norm:
            pontuacao += 2

        if pontuacao <= 0:
            continue

        chave = frase_norm[:120]

        if chave in vistas:
            continue

        vistas.add(chave)
        selecionadas.append((pontuacao, frase))

    selecionadas = [
        frase for _, frase in sorted(selecionadas, key=lambda item: item[0], reverse=True)
    ][:3]

    if not selecionadas:
        return ""

    corpo = "\n\n".join(selecionadas)

    return (
        f"📘 Pelo manual da Yamaha *{modelo_detectado.upper()}*:\n\n"
        f"{corpo}\n\n"
        "Se quiser, posso encaminhar você para um consultor confirmar detalhes específicos. 🤝"
    )


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

    trecho = buscar_resposta_manual(modelo_detectado, pergunta_cliente)

    if trecho:
        resposta = resumir_trecho_manual(
            modelo_detectado=modelo_detectado,
            pergunta=pergunta_cliente,
            trecho=trecho,
            assunto=assunto,
        )

        if not resposta:
            return {
                "encontrou": False,
                "modelo": modelo_detectado,
                "assunto": assunto,
                "fonte": "resumo_inseguro",
                "resposta": (
                    "Não encontrei essa informação com segurança no manual. "
                    "Vou encaminhar para um consultor te ajudar melhor. 🤝"
                )
            }

        return {
            "encontrou": True,
            "modelo": modelo_detectado,
            "assunto": assunto,
            "fonte": "manual_pdf",
            "resposta": resposta
        }

    return {
        "encontrou": False,
        "modelo": modelo_detectado,
        "assunto": assunto,
        "fonte": "nao_encontrado",
        "resposta": (
            "Não encontrei essa informação com segurança no manual. "
            "Vou encaminhar para um consultor te ajudar melhor. 🤝"
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
