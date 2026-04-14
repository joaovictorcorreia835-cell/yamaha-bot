import os
import re
import unicodedata

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
CAMINHO_PLANILHA_REVISOES = "templates/data/revisoes_yamaha.xlsx"

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

BASE_DUVIDAS = {
    "garantia": [
        {
            "palavras_chave": [
                "como funciona", "garantia", "cobertura", "cobre", "defeito",
                "defeito de fabrica", "defeito de fábrica"
            ],
            "resposta": (
                "A garantia cobre situações elegíveis conforme as regras da Yamaha "
                "e mediante avaliação técnica da concessionária.\n\n"
                "A cobertura depende do tipo de ocorrência e das condições da motocicleta."
            )
        },
        {
            "palavras_chave": [
                "documento", "documentos", "manual", "nota", "nota fiscal",
                "preciso levar", "levar", "solicitar garantia"
            ],
            "resposta": (
                "Para atendimento de garantia, normalmente orientamos apresentar os documentos da moto, "
                "informações do proprietário e histórico de revisões.\n\n"
                "Dependendo do caso, nossa equipe poderá solicitar dados complementares."
            )
        },
        {
            "palavras_chave": [
                "revisoes em dia", "revisões em dia", "perco garantia",
                "perder garantia", "fora da garantia", "garantia vencida"
            ],
            "resposta": (
                "A análise de garantia considera as condições da moto e o histórico de manutenção "
                "conforme orientação da fabricante.\n\n"
                "Nossa equipe pode avaliar seu caso e orientar corretamente."
            )
        },
        {
            "palavras_chave": [
                "painel", "motor", "barulho", "falha", "problema", "defeito"
            ],
            "resposta": (
                "Problemas técnicos podem passar por avaliação de garantia, dependendo da origem da falha "
                "e das condições da motocicleta.\n\n"
                "Se desejar, podemos encaminhar seu caso para análise da equipe."
            )
        }
    ]
}


def log_info(*args):
    print("[IA][INFO]", *args, flush=True)


def log_erro(*args):
    print("[IA][ERRO]", *args, flush=True)


def limpar_texto(texto):
    return str(texto or "").strip()


def remover_acentos(texto):
    texto = str(texto or "")
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def normalizar_texto(texto):
    texto = limpar_texto(texto).lower()
    texto = remover_acentos(texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def formatar_valor_brl(valor):
    try:
        if isinstance(valor, (int, float)):
            valor_float = float(valor)
        else:
            valor_texto = str(valor).replace("R$", "").strip()
            if "," in valor_texto:
                valor_texto = valor_texto.replace(".", "").replace(",", ".")
            valor_float = float(valor_texto)

        return f"R$ {valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {valor}"


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
    termos_agendamento = [
        "agendar", "agendamento", "marcar", "remarcar", "reagendar",
        "cancelar", "consultar", "acompanhar", "horario", "segunda",
        "terca", "quarta", "quinta", "sexta", "sabado"
    ]

    if any(p in texto_normalizado for p in termos_agendamento):
        return False

    tem_valor = any(p in texto_normalizado for p in [
        "valor", "preco", "preço", "custa", "quanto custa", "quanto e", "quanto é"
    ])

    tem_contexto_revisao = any(p in texto_normalizado for p in [
        "revisao", "km", "quilometragem", "meses", "mes"
    ])

    tem_km = re.search(r"\b\d{1,3}(?:[.\s]?\d{3})*\s*km\b", texto_normalizado) is not None
    tem_meses = re.search(r"\b\d+\s*(?:meses|mes)\b", texto_normalizado) is not None

    return tem_valor and (tem_contexto_revisao or tem_km or tem_meses)


def extrair_modelo(texto):
    texto_upper = str(texto or "").upper()

    for modelo in sorted(MODELOS_YAMAHA, key=len, reverse=True):
        if modelo in texto_upper:
            return modelo

    aliases = {
        "FAZER": "FAZER 250",
        "FZ 15": "FZ15",
        "FZ-15": "FZ15",
        "MT 03": "MT03",
        "MT-03": "MT03",
        "MT 07": "MT07",
        "MT-07": "MT07",
        "R 15": "R15",
        "R-15": "R15",
        "R 3": "R3",
        "R-3": "R3",
        "TENERE": "TENERE 700",
    }

    for alias, modelo in aliases.items():
        if alias in texto_upper:
            return modelo

    return ""


def extrair_ano(texto):
    match = re.search(r"\b(20\d{2})\b", str(texto or ""))
    if match:
        return match.group(1)
    return ""


def extrair_revisao(texto):
    texto = normalizar_texto(texto)

    match = re.search(r"(\d+)\s*(?:a|ª|o)?\s*revis", texto)
    if match:
        return match.group(1)

    mapa_texto = {
        "primeira revisao": "1",
        "segunda revisao": "2",
        "terceira revisao": "3",
        "quarta revisao": "4",
        "quinta revisao": "5",
        "1 revisao": "1",
        "2 revisao": "2",
        "3 revisao": "3",
        "4 revisao": "4",
        "5 revisao": "5",
    }

    for chave, valor in mapa_texto.items():
        if chave in texto:
            return valor

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
        hora = int(match.group(1))
        minuto = match.group(2)
        if 0 <= hora <= 23:
            return f"{hora:02d}:{minuto}"

    match = re.search(r"\b(\d{1,2})\s*h\b", texto)
    if match:
        hora = int(match.group(1))
        if 0 <= hora <= 23:
            return f"{hora:02d}:00"

    match = re.search(r"\b(?:as)\s*(\d{1,2})\b", texto)
    if match:
        hora = int(match.group(1))
        if 0 <= hora <= 23:
            return f"{hora:02d}:00"

    return ""


def extrair_dia(texto):
    texto = normalizar_texto(texto)

    mapa = {
        "segunda": "1",
        "terca": "2",
        "quarta": "3",
        "quinta": "4",
        "sexta": "5",
        "sabado": "6",
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
            "lander", "crosser", "mt03", "mt07", "r15", "r3", "neo", "nmax", "aerox",
            "logista", "atacado", "catalogo", "catálogo", "pecas", "peças",
            "cancelar", "reagendar", "consultar", "agendamento", "protocolo",
            "falar", "alguem", "alguém", "consultor", "duvida", "dúvida"
        }

        if not any(p.lower() in bloqueadas for p in palavras):
            return " ".join(palavras).upper()

    return ""


def extrair_cpf(texto):
    match = re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", str(texto or ""))
    if match:
        return re.sub(r"\D", "", match.group(0))
    return ""


def extrair_item_adicional(texto):
    texto_lower = normalizar_texto(texto)

    itens_comuns = [
        "filtro de ar",
        "pastilha traseira",
        "pastilha dianteira",
        "pastilha de freio",
        "sapata de freio",
        "kit lubrificante",
        "oleo",
        "slider",
        "bau",
        "suporte celular",
        "suporte para celular",
        "protetor motor",
        "vela",
        "vela de ignicao",
        "limpeza de bico",
        "limpeza de injecao",
        "troca de oleo"
    ]

    encontrados = []

    for item in itens_comuns:
        if item in texto_lower:
            item_formatado = item.upper()
            if item_formatado not in encontrados:
                encontrados.append(item_formatado)

    return ", ".join(encontrados)


def texto_parece_dado_de_fluxo(texto):
    texto_limpo = limpar_texto(texto)
    if not texto_limpo:
        return False

    if extrair_nome(texto_limpo):
        return True
    if extrair_cpf(texto_limpo):
        return True
    if extrair_data(texto_limpo):
        return True
    if extrair_horario(texto_limpo):
        return True
    if extrair_modelo(texto_limpo):
        return True
    if extrair_ano(texto_limpo):
        return True
    if extrair_revisao(texto_limpo):
        return True
    if extrair_dia(texto_limpo):
        return True

    if texto_limpo in ["1", "2", "3", "4", "5", "6", "7"]:
        return True

    return False


def detectar_intencao_regras(texto_normalizado):
    if any(p in texto_normalizado for p in [
        "menu", "oi", "ola", "bom dia", "boa tarde", "boa noite"
    ]):
        return "menu", 0.99

    if any(p in texto_normalizado for p in [
        "agendar revisao",
        "marcar revisao",
        "quero agendar",
        "agendar",
        "agendamento",
        "marcar horario",
        "agenda revisao"
    ]):
        return "agendar_revisao", 0.99

    if any(p in texto_normalizado for p in [
        "cancelar revisao",
        "cancelar minha revisao",
        "cancelar agendamento",
        "desmarcar revisao",
        "quero cancelar",
        "cancelar meu horario"
    ]):
        return "cancelar_agendamento", 0.98

    if any(p in texto_normalizado for p in [
        "reagendar revisao",
        "reagendar agendamento",
        "remarcar revisao",
        "trocar horario",
        "mudar horario",
        "quero remarcar",
        "quero reagendar"
    ]):
        return "reagendar_agendamento", 0.98

    if any(p in texto_normalizado for p in [
        "consultar agendamento",
        "consultar revisao",
        "consultar minha revisao",
        "ver agendamento",
        "ver minha revisao",
        "ver meu protocolo",
        "acompanhar agendamento",
        "acompanhar revisao",
        "qual meu agendamento",
        "tenho agendamento",
        "meu protocolo"
    ]):
        return "consultar_agendamento", 0.97

    if texto_parece_valor_revisao(texto_normalizado):
        return "valor_revisao", 0.98

    if any(p in texto_normalizado for p in [
        "duvida", "tenho uma duvida", "tenho duvida", "pergunta", "informacao", "informacao sobre"
    ]):
        return "duvidas", 0.95

    if any(p in texto_normalizado for p in [
        "peca", "pecas", "orcamento de peca"
    ]):
        return "pecas", 0.94

    if any(p in texto_normalizado for p in [
        "acessorio", "acessorios"
    ]):
        return "acessorios", 0.94

    if any(p in texto_normalizado for p in [
        "garantia", "defeito", "problema em garantia"
    ]):
        return "garantia", 0.94

    if any(p in texto_normalizado for p in [
        "atacado", "logista", "cotacao", "catalogo"
    ]):
        return "atacado", 0.94

    if any(p in texto_normalizado for p in [
        "atendente", "humano", "consultor", "falar com alguem"
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
        return "revisao_venda"

    if intencao == "cancelar_agendamento":
        return "cancelar_agendamento"

    if intencao == "reagendar_agendamento":
        return "reagendar_agendamento"

    if intencao == "consultar_agendamento":
        return "consultar_agendamento"

    if intencao == "valor_revisao":
        return "consulta_valor_revisao"

    if intencao == "duvidas":
        return "menu_duvidas"

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

        if dados.get("modelo"):
            partes.append(f"🏍️ Modelo: {dados['modelo']}")
        if dados.get("ano"):
            partes.append(f"📅 Ano: {dados['ano']}")
        if dados.get("revisao"):
            partes.append(f"🔧 Revisão: {dados['revisao']}ª")
        if dados.get("data"):
            partes.append(f"📆 Data: {dados['data']}")
        if dados.get("horario"):
            partes.append(f"⏰ Horário: {dados['horario']}")

        if partes:
            return "Perfeito. Já identifiquei estas informações:\n\n" + "\n".join(partes)

        return "Perfeito. Vou te ajudar com o agendamento da sua revisão."

    if intencao == "cancelar_agendamento":
        return "Certo. Vou te ajudar a cancelar seu agendamento de revisão."

    if intencao == "reagendar_agendamento":
        return "Perfeito. Vou te ajudar a reagendar sua revisão."

    if intencao == "consultar_agendamento":
        return "Certo. Vou consultar seu agendamento de revisão."

    if intencao == "valor_revisao":
        return "Perfeito. Vou verificar as informações para consultar o valor da revisão."

    if intencao == "duvidas":
        return "Perfeito. Vou te direcionar para a central de dúvidas."

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
    if texto_parece_dado_de_fluxo(texto):
        return "", 0.0

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
                        "agendar_revisao, cancelar_agendamento, reagendar_agendamento, consultar_agendamento, "
                        "valor_revisao, duvidas, pecas, acessorios, garantia, atacado, humano, menu. "
                        "Use valor_revisao apenas quando a pessoa quiser saber preço, valor ou custo da revisão. "
                        "Use duvidas quando a pessoa quiser apenas tirar uma dúvida ou pedir informação, sem pedir "
                        "agendamento, cancelamento ou consulta objetiva de protocolo. "
                        "Se houver intenção de agendar ou marcar horário, sempre responda agendar_revisao. "
                        "Se o texto parecer apenas um nome, CPF, data, horário, modelo ou outra resposta curta de cadastro, responda vazio."
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
            "cancelar_agendamento",
            "reagendar_agendamento",
            "consultar_agendamento",
            "valor_revisao",
            "duvidas",
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


def pontuar_correspondencia_duvida(pergunta_normalizada, palavras_chave):
    pontos = 0

    for palavra in palavras_chave:
        palavra_normalizada = normalizar_texto(palavra)
        if palavra_normalizada and palavra_normalizada in pergunta_normalizada:
            pontos += 1

    return pontos


def responder_duvida_revisao_excel(pergunta, modelo="", revisao=""):
    try:
        df = pd.read_excel(CAMINHO_PLANILHA_REVISOES)
    except Exception as e:
        log_erro("Erro ao carregar planilha revisões:", e)
        return "Não consegui consultar as informações de revisão no momento."

    if df.empty:
        return "A planilha de revisões está vazia no momento."

    colunas_necessarias = [
        "modelo", "revisao_numero", "KM", "MESES",
        "valor", "tempo_estimado", "itens_trocados", "itens_verificados"
    ]

    for coluna in colunas_necessarias:
        if coluna not in df.columns:
            return f"A coluna '{coluna}' não foi encontrada na planilha de revisões."

    pergunta_normalizada = normalizar_texto(pergunta)

    df["modelo"] = df["modelo"].astype(str).str.upper().str.strip()

    modelo_filtrado = str(modelo or "").upper().strip()
    revisao_filtrada = str(revisao or "").strip()

    if not modelo_filtrado:
        modelo_extraido = extrair_modelo(pergunta)
        if modelo_extraido:
            modelo_filtrado = modelo_extraido.upper().strip()

    if not revisao_filtrada:
        revisao_extraida = extrair_revisao(pergunta)
        if revisao_extraida:
            revisao_filtrada = str(revisao_extraida).strip()

    if not revisao_filtrada:
        km_extraido = extrair_km(pergunta)
        if km_extraido:
            revisao_por_km = km_para_revisao(km_extraido)
            if revisao_por_km:
                revisao_filtrada = str(revisao_por_km).strip()

    if modelo_filtrado:
        df = df[df["modelo"] == modelo_filtrado]

    if revisao_filtrada:
        try:
            revisao_int = int(revisao_filtrada)
            df = df[df["revisao_numero"] == revisao_int]
        except Exception:
            pass

    if df.empty:
        return (
            "Não encontrei essa revisão na base de dados.\n\n"
            "Tente informar o modelo da moto e o número da revisão.\n\n"
            "Se preferir, nossa equipe pode verificar para você."
        )

    linha = df.iloc[0]

    valor = linha["valor"]
    tempo_estimado = linha["tempo_estimado"]
    itens_trocados = str(linha["itens_trocados"]).strip()
    itens_verificados = str(linha["itens_verificados"]).strip()
    km = linha["KM"]
    meses = linha["MESES"]
    modelo_linha = str(linha["modelo"]).strip()
    revisao_linha = str(linha["revisao_numero"]).strip()

    if any(p in pergunta_normalizada for p in ["valor", "preco", "preço", "quanto custa", "custo"]):
        return (
            f"O valor estimado da {revisao_linha}ª revisão da {modelo_linha} é "
            f"{formatar_valor_brl(valor)}."
        )

    if any(p in pergunta_normalizada for p in ["tempo", "demora", "duracao", "duração", "quanto tempo"]):
        return (
            f"O tempo estimado da {revisao_linha}ª revisão da {modelo_linha} é "
            f"{tempo_estimado}."
        )

    if any(p in pergunta_normalizada for p in ["troca", "trocado", "trocados", "o que troca", "itens trocados"]):
        return (
            f"Na {revisao_linha}ª revisão da {modelo_linha}, os principais itens trocados são:\n\n"
            f"{itens_trocados}"
        )

    if any(p in pergunta_normalizada for p in ["verifica", "verificado", "verificados", "checagem", "confere"]):
        return (
            f"Na {revisao_linha}ª revisão da {modelo_linha}, os principais itens verificados são:\n\n"
            f"{itens_verificados}"
        )

    if any(p in pergunta_normalizada for p in ["km", "quilometragem"]):
        return (
            f"A {revisao_linha}ª revisão da {modelo_linha} é prevista para aproximadamente "
            f"{km} km."
        )

    if any(p in pergunta_normalizada for p in ["mes", "meses", "prazo"]):
        return (
            f"A {revisao_linha}ª revisão da {modelo_linha} é prevista para "
            f"{meses} meses."
        )

    return (
        f"📋 {revisao_linha}ª revisão da {modelo_linha}\n\n"
        f"🔢 KM: {km}\n"
        f"📅 Meses: {meses}\n"
        f"💰 Valor: {formatar_valor_brl(valor)}\n"
        f"⏱️ Tempo estimado: {tempo_estimado}\n\n"
        f"Se quiser, posso te explicar também o que troca ou o que é verificado nessa revisão."
    )


def responder_duvida_por_tabela(categoria, pergunta_cliente, modelo="", revisao=""):
    categoria_normalizada = normalizar_texto(categoria)

    if categoria_normalizada == "revisoes":
        return responder_duvida_revisao_excel(
            pergunta=pergunta_cliente,
            modelo=modelo,
            revisao=revisao
        )

    pergunta_normalizada = normalizar_texto(pergunta_cliente)

    if categoria_normalizada not in BASE_DUVIDAS:
        return (
            "No momento, essa categoria de dúvidas ainda não está configurada.\n\n"
            "Se desejar, posso te encaminhar para nossa equipe."
        )

    base_categoria = BASE_DUVIDAS.get(categoria_normalizada, [])
    melhor_item = None
    melhor_pontuacao = 0

    for item in base_categoria:
        pontuacao = pontuar_correspondencia_duvida(
            pergunta_normalizada,
            item.get("palavras_chave", [])
        )

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_item = item

    if melhor_item and melhor_pontuacao > 0:
        return melhor_item["resposta"]

    if categoria_normalizada == "garantia":
        return (
            "Entendi sua dúvida sobre garantia.\n\n"
            "No momento, não encontrei uma resposta exata na base de conhecimento.\n\n"
            "Para te orientar corretamente, o ideal é que nossa equipe analise o seu caso. "
            "Se desejar, posso te encaminhar para atendimento."
        )

    return (
        "Recebi sua dúvida, mas ainda não encontrei uma resposta exata na base.\n\n"
        "Se desejar, posso te encaminhar para nossa equipe."
    )


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

    retorno = {
        "intencao": intencao,
        "confianca": confianca,
        "resposta": gerar_resposta(intencao, dados),
        "proxima_etapa": sugerir_proxima_etapa(intencao, dados),
        "dados_extraidos": dados
    }

    log_info("Retorno final IA:", retorno)
    return retorno