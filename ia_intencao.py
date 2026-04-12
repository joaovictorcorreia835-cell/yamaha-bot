import os
import re

from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

MODELOS_YAMAHA = [
    "FAZER 250",
    "FZ15",
    "CROSSER",
    "LANDER",
    "MT03",
    "MT07",
    "R15",
    "R3",
    "FLUO",
    "NEO",
    "NMAX",
    "TENERE 700",
    "AEROX"
]


def log_info(*args):
    print("[IA][INFO]", *args, flush=True)


def log_erro(*args):
    print("[IA][ERRO]", *args, flush=True)


def limpar_texto(texto):
    return str(texto or "").strip()


def normalizar_texto(texto):
    return limpar_texto(texto).lower()


def obter_cliente():
    if not OPENAI_API_KEY:
        log_erro("OPENAI_API_KEY não configurada.")
        return None

    if OpenAI is None:
        log_erro("Biblioteca OpenAI não disponível.")
        return None

    try:
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        log_erro("Erro ao criar cliente OpenAI:", e)
        return None


def texto_parece_valor_revisao(texto_normalizado):
    tem_valor = any(p in texto_normalizado for p in [
        "valor", "preço", "preco", "custa", "quanto custa", "quanto é", "quanto e"
    ])

    tem_contexto_revisao = any(p in texto_normalizado for p in [
        "revisão", "revisao", "km", "quilometragem", "meses", "mês", "mes"
    ])

    tem_numero_revisao = re.search(r"\b\d+\s*(?:ª|a)?\s*revis", texto_normalizado) is not None
    tem_km = re.search(r"\b\d{1,3}(?:[.\s]?\d{3})*\s*km\b", texto_normalizado) is not None
    tem_meses = re.search(r"\b\d+\s*(?:meses|mês|mes)\b", texto_normalizado) is not None

    return (tem_valor and tem_contexto_revisao) or tem_numero_revisao or tem_km or tem_meses


def extrair_modelo(texto):
    texto_upper = str(texto or "").upper()

    for modelo in sorted(MODELOS_YAMAHA, key=len, reverse=True):
        if modelo in texto_upper:
            return modelo

    return ""


def extrair_ano(texto):
    match = re.search(r"\b(20\d{2})\b", str(texto or ""))
    if match:
        return match.group(1)
    return ""


def extrair_revisao(texto):
    texto = normalizar_texto(texto)

    match = re.search(r"(\d+)\s*(?:a|ª)?\s*revis", texto)
    if match:
        return match.group(1)

    return ""


def extrair_km(texto):
    texto = normalizar_texto(texto)
    match = re.search(r"\b(\d{1,3}(?:[.\s]?\d{3})*|\d+)\s*km\b", texto)
    if match:
        return re.sub(r"[^\d]", "", match.group(1))
    return ""


def km_para_revisao(km):
    try:
        km_int = int(str(km).strip())
    except Exception:
        return ""

    mapa = {
        1000: "1",
        3000: "2",
        6000: "3",
        9000: "4",
        12000: "5",
        15000: "5",
        18000: "5",
        21000: "5",
        24000: "5",
    }

    return mapa.get(km_int, "")


def extrair_horario(texto):
    texto = normalizar_texto(texto)

    match = re.search(r"\b(\d{1,2}):(\d{2})\b", texto)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    match = re.search(r"\b(\d{1,2})\s*h\b", texto)
    if match:
        return f"{int(match.group(1)):02d}:00"

    match = re.search(r"\bàs\s*(\d{1,2})\b", texto)
    if match:
        return f"{int(match.group(1)):02d}:00"

    match = re.search(r"\bas\s*(\d{1,2})\b", texto)
    if match:
        return f"{int(match.group(1)):02d}:00"

    return ""


def extrair_dia(texto):
    texto = normalizar_texto(texto)

    mapa = {
        "segunda": "segunda",
        "terça": "terca",
        "terca": "terca",
        "quarta": "quarta",
        "quinta": "quinta",
        "sexta": "sexta",
        "sábado": "sabado",
        "sabado": "sabado",
    }

    for chave, valor in mapa.items():
        if chave in texto:
            return valor

    return ""


def extrair_data(texto):
    texto = limpar_texto(texto)

    match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto)
    if match:
        return match.group(1)

    match = re.search(r"\b(\d{2}-\d{2}-\d{4})\b", texto)
    if match:
        return match.group(1).replace("-", "/")

    return ""


def extrair_nome(texto):
    texto_original = limpar_texto(texto)
    texto_lower = texto_original.lower()

    padroes = [
        r"meu nome é ([a-záàâãéèêíìîóòôõúùûç\s]+?)(?:,|\.| e | que | quero | preciso | para | pra |$)",
        r"meu nome e ([a-záàâãéèêíìîóòôõúùûç\s]+?)(?:,|\.| e | que | quero | preciso | para | pra |$)",
        r"nome[:\s]+([a-záàâãéèêíìîóòôõúùûç\s]+?)(?:,|\.| e | que | quero | preciso | para | pra |$)",
        r"sou ([a-záàâãéèêíìîóòôõúùûç\s]+?)(?:,|\.| e | que | quero | preciso | para | pra |$)",
    ]

    for padrao in padroes:
        match = re.search(padrao, texto_lower, re.IGNORECASE)
        if match:
            nome = match.group(1).strip()
            nome = re.sub(r"\s+", " ", nome).strip()
            if len(nome) >= 3:
                return nome.upper()

    texto_puro = re.sub(r"[^a-zA-ZáàâãéèêíìîóòôõúùûçÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ\s]", " ", texto_original)
    texto_puro = re.sub(r"\s+", " ", texto_puro).strip()

    palavras = texto_puro.split()
    if 2 <= len(palavras) <= 6:
        bloqueadas = {
            "quero", "agendar", "revisao", "revisão", "garantia", "peca", "peça",
            "acessorio", "acessório", "menu", "atendente", "humano", "segunda",
            "terca", "terça", "quarta", "quinta", "sexta", "sabado", "sábado",
            "dia", "as", "às", "valor", "quanto", "custa", "fluo", "fazer",
            "lander", "crosser", "mt03", "mt07", "r15", "r3", "neo", "nmax", "aerox"
        }

        if not any(p.lower() in bloqueadas for p in palavras):
            return " ".join(palavras).upper()

    return ""


def extrair_cpf(texto):
    match = re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", str(texto or ""))
    if match:
        return match.group(0)
    return ""


def extrair_item_adicional(texto):
    texto_lower = normalizar_texto(texto)

    itens_comuns = [
        "filtro de ar",
        "pastilha de freio",
        "óleo",
        "oleo",
        "slider",
        "baú",
        "bau",
        "suporte celular",
        "suporte para celular",
        "protetor motor",
        "vela",
        "vela de ignição",
        "limpeza de bico",
        "limpeza de injeção",
        "troca de óleo",
        "troca de oleo"
    ]

    encontrados = []

    for item in itens_comuns:
        if item in texto_lower:
            item_formatado = (
                item.upper()
                .replace("Ó", "O")
                .replace("Ú", "U")
                .replace("Ç", "C")
                .replace("Ã", "A")
                .replace("Õ", "O")
            )
            if item_formatado not in encontrados:
                encontrados.append(item_formatado)

    return ", ".join(encontrados)


def detectar_intencao_regras(texto_normalizado):
    if any(p in texto_normalizado for p in ["menu", "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]):
        return "menu", 0.99

    if texto_parece_valor_revisao(texto_normalizado):
        return "valor_revisao", 0.98

    if any(p in texto_normalizado for p in [
        "agendar revisão", "agendar revisao", "revisão", "revisao",
        "marcar revisão", "marcar revisao", "quero revisar", "agendamento",
        "quero agendar", "agendar", "marcar horario", "marcar horário"
    ]):
        return "agendar_revisao", 0.96

    if any(p in texto_normalizado for p in [
        "peça", "peca", "peças", "pecas", "orçamento de peça", "orcamento de peca"
    ]):
        return "pecas", 0.94

    if any(p in texto_normalizado for p in [
        "acessório", "acessorio", "acessórios", "acessorios"
    ]):
        return "acessorios", 0.94

    if any(p in texto_normalizado for p in [
        "garantia", "defeito", "problema em garantia"
    ]):
        return "garantia", 0.94

    if any(p in texto_normalizado for p in [
        "atacado", "logista", "cotação", "cotacao", "catálogo", "catalogo"
    ]):
        return "atacado", 0.94

    if any(p in texto_normalizado for p in [
        "atendente", "humano", "consultor", "falar com alguém", "falar com alguem"
    ]):
        return "humano", 0.97

    return "", 0.0


def sugerir_proxima_etapa(intencao, dados):
    if intencao == "agendar_revisao":
        if not dados["modelo"]:
            return "revisao_modelo"
        if not dados["nome"]:
            return "revisao_nome"
        if not dados["cpf"]:
            return "revisao_cpf"
        if not dados["ano"]:
            return "revisao_ano"
        if not dados["revisao"]:
            return "revisao_tipo"
        if not dados["dia"]:
            return "revisao_dia"
        if not dados["data"]:
            return "revisao_data"
        if not dados["horario"]:
            return "revisao_horario"
        return "revisao_confirmar"

    if intencao == "valor_revisao":
        return "consulta_valor_revisao"

    if intencao == "pecas":
        return "pecas"

    if intencao == "acessorios":
        return "acessorios"

    if intencao == "garantia":
        return "garantia"

    if intencao == "atacado":
        return "submenu_atacado"

    if intencao == "humano":
        return "atendimento_humano"

    return "menu"


def gerar_resposta(intencao, dados):
    if intencao == "agendar_revisao":
        partes = []

        if dados.get("nome"):
            partes.append(f"👤 Nome: {dados['nome']}")
        if dados.get("modelo"):
            partes.append(f"🏍️ Modelo: {dados['modelo']}")
        if dados.get("ano"):
            partes.append(f"📅 Ano: {dados['ano']}")
        if dados.get("revisao"):
            partes.append(f"🔧 Revisão: {dados['revisao']}ª")
        if dados.get("dia"):
            partes.append(f"📍 Dia: {dados['dia']}")
        if dados.get("data"):
            partes.append(f"📆 Data: {dados['data']}")
        if dados.get("horario"):
            partes.append(f"⏰ Horário: {dados['horario']}")

        if partes:
            return (
                "Perfeito. Já identifiquei estas informações do seu agendamento:\n\n"
                + "\n".join(partes)
            )

        return "Perfeito. Vou te ajudar com o agendamento da sua revisão."

    if intencao == "valor_revisao":
        return "Perfeito. Vou verificar as informações para consultar o valor da revisão."

    if intencao == "pecas":
        return "Certo. Vou seguir com seu atendimento de peças."

    if intencao == "acessorios":
        return "Perfeito. Vou seguir com seu atendimento de acessórios."

    if intencao == "garantia":
        return "Certo. Vou seguir com sua solicitação de garantia."

    if intencao == "atacado":
        return "Perfeito. Vou te direcionar para o atendimento de logista e atacado."

    if intencao == "humano":
        return "Certo. Vou te encaminhar para atendimento humano."

    if intencao == "menu":
        return "Perfeito. Vou te enviar o menu principal."

    return "Entendi sua mensagem. Vou te ajudar com isso."


def classificar_com_ia(texto):
    cliente = obter_cliente()
    if cliente is None:
        return "", 0.0

    try:
        resposta = cliente.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um classificador de intenção para um bot de pós-vendas Yamaha. "
                        "Responda com apenas uma única palavra, sem explicação, escolhendo uma destas opções exatas: "
                        "agendar_revisao, valor_revisao, pecas, acessorios, garantia, atacado, humano, menu. "
                        "Use valor_revisao quando a pessoa quiser saber preço, valor ou custo de revisão por número, km ou meses. "
                        "Nunca responda fora dessa lista."
                    )
                },
                {
                    "role": "user",
                    "content": texto
                }
            ]
        )

        conteudo = resposta.choices[0].message.content.strip().lower()
        log_info("Resposta bruta IA:", conteudo)

        permitidas = {
            "agendar_revisao",
            "valor_revisao",
            "pecas",
            "acessorios",
            "garantia",
            "atacado",
            "humano",
            "menu"
        }

        if conteudo in permitidas:
            return conteudo, 0.85

        return "", 0.0

    except Exception as e:
        log_erro("Erro ao classificar intenção:", e)
        return "", 0.0


def classificar_intencao(texto):
    texto = limpar_texto(texto)

    if not texto:
        dados = {
            "modelo": "",
            "ano": "",
            "revisao": "",
            "dia": "",
            "data": "",
            "horario": "",
            "nome": "",
            "cpf": "",
            "item_adicional": "",
            "km": "",
        }
        return {
            "intencao": "menu",
            "confianca": 1.0,
            "resposta": gerar_resposta("menu", dados),
            "proxima_etapa": "menu",
            "dados_extraidos": dados
        }

    texto_normalizado = normalizar_texto(texto)

    intencao, confianca = detectar_intencao_regras(texto_normalizado)

    if not intencao:
        intencao, confianca = classificar_com_ia(texto)

    dados = {
        "modelo": extrair_modelo(texto),
        "ano": extrair_ano(texto),
        "revisao": extrair_revisao(texto),
        "dia": extrair_dia(texto),
        "data": extrair_data(texto),
        "horario": extrair_horario(texto),
        "nome": extrair_nome(texto),
        "cpf": extrair_cpf(texto),
        "item_adicional": extrair_item_adicional(texto),
        "km": extrair_km(texto),
    }

    if not dados["revisao"] and dados["km"]:
        dados["revisao"] = km_para_revisao(dados["km"])

    if not intencao:
        if (
            dados["modelo"] or dados["nome"] or dados["cpf"] or dados["ano"] or
            dados["revisao"] or dados["dia"] or dados["data"] or
            dados["horario"] or dados["item_adicional"]
        ):
            intencao = "agendar_revisao"
            confianca = 0.80
        else:
            intencao = "menu"
            confianca = 0.50

    proxima_etapa = sugerir_proxima_etapa(intencao, dados)
    resposta = gerar_resposta(intencao, dados)

    retorno = {
        "intencao": intencao,
        "confianca": confianca,
        "resposta": resposta,
        "proxima_etapa": proxima_etapa,
        "dados_extraidos": dados
    }

    log_info("Retorno final IA:", retorno)
    return retorno