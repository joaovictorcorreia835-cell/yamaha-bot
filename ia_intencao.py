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
CAMINHO_PLANILHA_REVISOES = os.getenv(
    "CAMINHO_PLANILHA_REVISOES",
    "templates/data/revisoes_yamaha.xlsx"
).strip()


MODELOS_YAMAHA = [
    "FAZER 250",
    "FZ15",
    "FZ25",
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
    "AEROX",
    "FACTOR",
]


BASE_DUVIDAS = {
    "garantia": [
        {
            "palavras_chave": [
                "garantia",
                "cobertura",
                "cobre",
                "defeito",
                "defeito de fabrica",
                "defeito de fábrica",
                "problema",
                "falha",
                "bateria",
                "painel",
                "motor",
                "vazamento",
                "embreagem",
                "pintura",
                "escapamento",
                "parte eletrica",
                "parte elétrica",
            ],
            "resposta": (
                "A garantia cobre situações elegíveis conforme as regras da Yamaha "
                "e mediante avaliação técnica da concessionária.\n\n"
                "A cobertura depende do tipo de ocorrência, histórico de revisões, "
                "condições da motocicleta e análise técnica."
            )
        },
        {
            "palavras_chave": [
                "documento",
                "documentos",
                "manual",
                "nota",
                "nota fiscal",
                "preciso levar",
                "solicitar garantia",
            ],
            "resposta": (
                "Para atendimento de garantia, normalmente orientamos apresentar "
                "documentos da moto, informações do proprietário e histórico de revisões.\n\n"
                "Dependendo do caso, nossa equipe poderá solicitar dados complementares."
            )
        },
        {
            "palavras_chave": [
                "revisoes em dia",
                "revisões em dia",
                "perco garantia",
                "perder garantia",
                "fora da garantia",
                "garantia vencida",
                "revisao atrasada",
                "revisão atrasada",
            ],
            "resposta": (
                "A análise de garantia considera as condições da moto e o histórico "
                "de manutenção conforme orientação da fabricante.\n\n"
                "Se a revisão ultrapassar o limite estabelecido pela Yamaha, pode haver "
                "restrição ou perda de cobertura da garantia."
            )
        },
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


def normalizar_botao_zapi(texto):
    texto_norm = normalizar_texto(texto)
    texto_norm = texto_norm.replace("-", "_").replace(" ", "_")

    mapa_botoes = {
        "menu": "MENU",
        "voltar_menu": "MENU",
        "menu_principal": "MENU",

        "1": "OPCAO_1",
        "2": "OPCAO_2",
        "3": "OPCAO_3",
        "4": "OPCAO_4",
        "5": "OPCAO_5",
        "6": "OPCAO_6",
        "7": "OPCAO_7",

        "agendar": "AGENDAR_REVISAO",
        "agendar_revisao": "AGENDAR_REVISAO",
        "agendar_revisão": "AGENDAR_REVISAO",

        "reagendar": "REAGENDAR_AGENDAMENTO",
        "reagendar_agendamento": "REAGENDAR_AGENDAMENTO",

        "cancelar": "CANCELAR_AGENDAMENTO",
        "cancelar_agendamento": "CANCELAR_AGENDAMENTO",

        "consultar": "CONSULTAR_AGENDAMENTO",
        "consultar_agendamento": "CONSULTAR_AGENDAMENTO",

        "falar_consultor": "MENU_HUMANO",
        "falar_com_consultor": "MENU_HUMANO",
        "consultor": "MENU_HUMANO",
        "humano": "MENU_HUMANO",

        "duvida_revisoes": "DUVIDA_REVISOES",
        "duvida_revisões": "DUVIDA_REVISOES",
        "duvida_garantia": "DUVIDA_GARANTIA",
        "duvida_continuar": "DUVIDA_CONTINUAR",
        "duvida_outra": "DUVIDA_OUTRA",

        "atacado_tabela": "ATACADO_TABELA",
        "quero_tabela": "ATACADO_TABELA",
        "tabela": "ATACADO_TABELA",
        "atacado_consultor": "ATACADO_CONSULTOR",
        "atacado_depois": "ATACADO_DEPOIS",
    }

    return mapa_botoes.get(texto_norm, "")


def formatar_valor_brl(valor):
    try:
        if isinstance(valor, (int, float)):
            valor_float = float(valor)
        else:
            valor_texto = str(valor).replace("R$", "").strip()

            if "," in valor_texto:
                valor_texto = valor_texto.replace(".", "").replace(",", ".")

            valor_float = float(valor_texto)

        return (
            f"R$ {valor_float:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

    except Exception:
        return f"R$ {valor}"


def obter_cliente():
    if not OPENAI_API_KEY:
        return None

    if OpenAI is None:
        return None

    try:
        return OpenAI(api_key=OPENAI_API_KEY)

    except Exception as e:
        log_erro("Erro ao criar cliente OpenAI:", repr(e))
        return None


def texto_parece_garantia(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)

    termos_garantia = [
        "garantia",
        "garantido",
        "cobertura",
        "cobre",
        "cobrir",
        "perde garantia",
        "perco garantia",
        "perder garantia",
        "entra na garantia",
        "cobre bateria",
        "garantia cobre",
        "defeito",
        "defeito de fabrica",
        "defeito de fábrica",
        "problema de fabrica",
        "problema de fábrica",
        "painel apagando",
        "vazamento",
        "motor falhando",
        "falhando",
    ]

    return any(t in texto_normalizado for t in termos_garantia)


def texto_parece_valor_revisao(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)

    termos_agendamento = [
        "agendar",
        "agendamento",
        "marcar",
        "remarcar",
        "reagendar",
        "cancelar",
        "consultar",
        "acompanhar",
        "horario",
        "segunda",
        "terca",
        "quarta",
        "quinta",
        "sexta",
        "sabado",
    ]

    if any(p in texto_normalizado for p in termos_agendamento):
        return False

    tem_valor = any(p in texto_normalizado for p in [
        "valor",
        "preco",
        "preço",
        "custa",
        "quanto custa",
        "quanto e",
        "quanto é",
    ])

    tem_contexto_revisao = any(p in texto_normalizado for p in [
        "revisao",
        "revisão",
        "km",
        "quilometragem",
        "meses",
        "mes",
    ])

    tem_km = re.search(
        r"\b\d{1,3}(?:[.\s]?\d{3})*\s*km\b",
        texto_normalizado
    ) is not None

    tem_meses = re.search(
        r"\b\d+\s*(?:meses|mes)\b",
        texto_normalizado
    ) is not None

    return tem_valor and (tem_contexto_revisao or tem_km or tem_meses)


def texto_parece_valor_pecas(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)

    # Se tiver contexto claro de garantia, não classifica como peças.
    if texto_parece_garantia(texto_normalizado):
        return False

    termos_valor = [
        "valor",
        "preco",
        "preço",
        "quanto custa",
        "quanto e",
        "quanto é",
        "custa",
        "orcamento",
        "orçamento",
        "disponibilidade",
        "tem",
        "possui",
    ]

    termos_pecas = [
        "peca",
        "pecas",
        "peça",
        "peças",
        "oleo",
        "óleo",
        "filtro",
        "filtro de oleo",
        "filtro de óleo",
        "filtro de ar",
        "pastilha",
        "pastilha de freio",
        "pastilha dianteira",
        "pastilha traseira",
        "vela",
        "vela de ignicao",
        "vela de ignição",
        "bateria",
        "relacao",
        "relação",
        "kit transmissao",
        "kit transmissão",
        "corrente",
        "coroa",
        "pinhao",
        "pinhão",
        "pneu",
        "camara",
        "câmara",
        "retentor",
        "amortecedor",
        "embreagem",
        "disco de freio",
        "lona de freio",
        "sapata de freio",
    ]

    tem_valor = any(p in texto_normalizado for p in termos_valor)
    tem_peca = any(p in texto_normalizado for p in termos_pecas)

    return tem_valor and tem_peca


def texto_parece_consulta_pecas(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)

    # Se tiver contexto claro de garantia, não classifica como peças.
    if texto_parece_garantia(texto_normalizado):
        return False

    termos_pecas = [
        "peca",
        "pecas",
        "peça",
        "peças",
        "oleo",
        "óleo",
        "filtro",
        "filtro de oleo",
        "filtro de óleo",
        "filtro de ar",
        "pastilha",
        "vela",
        "bateria",
        "relacao",
        "relação",
        "kit transmissao",
        "kit transmissão",
        "pneu",
        "corrente",
        "coroa",
        "pinhao",
        "pinhão",
        "retentor",
        "embreagem",
    ]

    termos_consulta = [
        "tem",
        "possui",
        "quanto",
        "valor",
        "preco",
        "preço",
        "custa",
        "orcamento",
        "orçamento",
        "disponibilidade",
        "quero saber",
        "preciso de",
    ]

    tem_peca = any(p in texto_normalizado for p in termos_pecas)
    tem_consulta = any(p in texto_normalizado for p in termos_consulta)

    return tem_peca and tem_consulta


def frase_parece_duvida(texto):
    texto_norm = normalizar_texto(texto)

    # Garantia também é dúvida, mas não deve virar peças.
    if texto_parece_garantia(texto_norm):
        return True

    if texto_parece_valor_pecas(texto_norm) or texto_parece_consulta_pecas(texto_norm):
        return False

    gatilhos_duvida = [
        "qual o valor",
        "qual valor",
        "quanto custa",
        "quanto e",
        "quanto é",
        "o que troca",
        "o que inclui",
        "o que faz",
        "o que e verificado",
        "o que é verificado",
        "quanto tempo",
        "quanto demora",
        "com quantos km",
        "qual km",
        "quais itens",
        "quais pecas",
        "quais peças",
        "como funciona",
        "me explica",
        "pode me explicar",
        "tenho uma duvida",
        "tenho uma dúvida",
        "duvida sobre",
        "dúvida sobre",
        "garantia cobre",
        "entra na garantia",
        "perde garantia",
        "perco garantia",
    ]

    marcadores_pergunta = [
        "qual",
        "quais",
        "quanto",
        "como",
        "o que",
        "me explica",
        "explica",
    ]

    if any(gatilho in texto_norm for gatilho in gatilhos_duvida):
        return True

    if "?" in str(texto):
        return True

    if any(texto_norm.startswith(marcador) for marcador in marcadores_pergunta):
        return True

    return False


def extrair_modelo(texto):
    texto_upper = remover_acentos(str(texto or "").upper())

    for modelo in sorted(MODELOS_YAMAHA, key=len, reverse=True):
        if remover_acentos(modelo) in texto_upper:
            return modelo

    aliases = {
        "FAZER": "FAZER 250",
        "FZ 15": "FZ15",
        "FZ-15": "FZ15",
        "FZ 25": "FZ25",
        "FZ-25": "FZ25",
        "MT 03": "MT03",
        "MT-03": "MT03",
        "MT 07": "MT07",
        "MT-07": "MT07",
        "R 15": "R15",
        "R-15": "R15",
        "R 3": "R3",
        "R-3": "R3",
        "TENERE": "TENERE 700",
        "TENERE 700": "TENERE 700",
        "T7": "TENERE 700",
        "CRYPTON": "CRYPTON",
        "MAX": "NMAX",
        "N MAX": "NMAX",
        "N-MAX": "NMAX",
        "BAU": "",
        "BAÚ": "",
        "SLIDER": "",
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
        "primeira revisão": "1",
        "segunda revisao": "2",
        "segunda revisão": "2",
        "terceira revisao": "3",
        "terceira revisão": "3",
        "quarta revisao": "4",
        "quarta revisão": "4",
        "quinta revisao": "5",
        "quinta revisão": "5",
        "1 revisao": "1",
        "1 revisão": "1",
        "2 revisao": "2",
        "2 revisão": "2",
        "3 revisao": "3",
        "3 revisão": "3",
        "4 revisao": "4",
        "4 revisão": "4",
        "5 revisao": "5",
        "5 revisão": "5",
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

    match_mil = re.search(r"\b(\d{1,2})\s*mil\b", texto)

    if match_mil:
        return str(int(match_mil.group(1)) * 1000)

    return ""


def km_para_revisao(km):
    try:
        km_int = int(re.sub(r"\D", "", str(km or "")))
    except Exception:
        return ""

    if 900 <= km_int <= 1100:
        return "1"

    if 4500 <= km_int <= 5500:
        return "2"

    if 9500 <= km_int <= 10500:
        return "3"

    if 14500 <= km_int <= 15500:
        return "4"

    if km_int >= 19000:
        return "5"

    mapa = {
        1000: "1",
        5000: "2",
        10000: "3",
        15000: "4",
        20000: "5",
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

    match = re.search(r"\b(?:as|às)\s*(\d{1,2})\b", texto)

    if match:
        hora = int(match.group(1))

        if 0 <= hora <= 23:
            return f"{hora:02d}:00"

    return ""


def extrair_dia(texto):
    texto = normalizar_texto(texto)

    mapa = {
        "segunda": "1",
        "segunda feira": "1",
        "segunda-feira": "1",
        "terca": "2",
        "terça": "2",
        "terca feira": "2",
        "terça feira": "2",
        "terca-feira": "2",
        "terça-feira": "2",
        "quarta": "3",
        "quarta feira": "3",
        "quarta-feira": "3",
        "quinta": "4",
        "quinta feira": "4",
        "quinta-feira": "4",
        "sexta": "5",
        "sexta feira": "5",
        "sexta-feira": "5",
        "sabado": "6",
        "sábado": "6",
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

    texto_puro = re.sub(
        r"[^a-zA-ZáàâãéèêíìîóòôõúùûçÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ\s]",
        " ",
        texto_original
    )
    texto_puro = re.sub(r"\s+", " ", texto_puro).strip()

    palavras = texto_puro.split()

    if 2 <= len(palavras) <= 6:
        bloqueadas = {
            "quero", "agendar", "revisao", "revisão", "garantia", "peca", "peça",
            "acessorio", "acessório", "menu", "atendente", "humano", "segunda",
            "terca", "terça", "quarta", "quinta", "sexta", "sabado", "sábado",
            "dia", "as", "às", "valor", "quanto", "custa", "fluo", "fazer",
            "lander", "crosser", "mt03", "mt07", "r15", "r3", "neo", "nmax", "aerox",
            "logista", "lojista", "atacado", "catalogo", "catálogo", "pecas", "peças",
            "cancelar", "reagendar", "consultar", "agendamento", "protocolo",
            "falar", "alguem", "alguém", "consultor", "duvida", "dúvida",
            "depois", "tabela", "oficina", "parceria", "bateria", "óleo", "oleo"
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

    if texto_parece_garantia(texto_lower):
        return ""

    itens_comuns = [
        "filtro",
        "filtro de oleo",
        "filtro de óleo",
        "filtro de ar",
        "pastilha traseira",
        "pastilha dianteira",
        "pastilha de freio",
        "sapata de freio",
        "kit lubrificante",
        "oleo",
        "óleo",
        "slider",
        "bau",
        "baú",
        "suporte celular",
        "suporte para celular",
        "protetor motor",
        "protetor de motor",
        "vela",
        "vela de ignicao",
        "vela de ignição",
        "limpeza de bico",
        "limpeza de injecao",
        "limpeza de injeção",
        "troca de oleo",
        "troca de óleo",
        "bateria",
        "relacao",
        "relação",
        "kit transmissao",
        "kit transmissão",
        "pneu"
    ]

    encontrados = []

    for item in itens_comuns:
        item_normalizado = normalizar_texto(item)

        if item_normalizado in texto_lower:
            item_formatado = item_normalizado.upper()

            if item_formatado not in encontrados:
                encontrados.append(item_formatado)

    return ", ".join(encontrados)


def extrair_observacao(texto):
    texto_limpo = limpar_texto(texto)

    if not texto_limpo:
        return ""

    if normalizar_botao_zapi(texto_limpo):
        return ""

    if len(texto_limpo) < 8:
        return ""

    return texto_limpo


def extrair_tipo_atendimento(texto):
    texto_norm = normalizar_texto(texto)

    if "aguardar" in texto_norm:
        return "AGUARDAR NA CONCESSIONÁRIA"

    if "deixar" in texto_norm or "retirar depois" in texto_norm:
        return "DEIXAR A MOTO E RETIRAR DEPOIS"

    return ""


def texto_parece_dado_de_fluxo(texto):
    texto_limpo = limpar_texto(texto)
    texto_norm = normalizar_texto(texto_limpo)

    if not texto_limpo:
        return False

    if normalizar_botao_zapi(texto_limpo):
        return False

    intencoes_fortes = [
        "agendar",
        "agendar revisao",
        "agendar revisão",
        "marcar revisao",
        "marcar revisão",
        "falar consultor",
        "consultor",
        "humano",
        "quero tabela",
        "tabela",
        "atacado",
        "pecas",
        "peças",
        "acessorios",
        "acessórios",
        "garantia",
        "menu",
        "depois",
    ]

    if any(p in texto_norm for p in intencoes_fortes):
        return False

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

    if extrair_nome(texto_limpo):
        return True

    if texto_limpo in ["1", "2", "3", "4", "5", "6", "7"]:
        return True

    return False


def detectar_intencao_regras(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)
    botao = normalizar_botao_zapi(texto_normalizado)

    if botao in ["AGENDAR_REVISAO", "OPCAO_1"]:
        return "agendar_revisao", 1.0

    if botao in ["MENU_HUMANO", "FALAR_CONSULTOR"]:
        return "humano", 1.0

    if botao in ["MENU"]:
        return "menu", 0.99

    if botao == "DEPOIS":
        return "menu", 0.80

    if botao == "ATACADO_TABELA":
        return "atacado", 1.0

    if botao == "ATACADO_CONSULTOR":
        return "humano", 1.0

    if botao == "ATACADO_DEPOIS":
        return "menu", 0.80

    if texto_normalizado in ["menu", "voltar", "inicio", "início"]:
        return "menu", 0.99

    if texto_normalizado in [
        "oi", "ola", "olá",
        "bom dia", "boa tarde", "boa noite"
    ]:
        return "menu", 0.95

    # ==========================================
    # GARANTIA - PRIORIDADE ANTES DE PEÇAS
    # ==========================================
    if texto_parece_garantia(texto_normalizado):
        return "duvidas", 0.98

    if any(p in texto_normalizado for p in [
        "garantia cobre",
        "cobre bateria",
        "bateria na garantia",
        "entra na garantia",
        "perde garantia",
        "perco garantia",
        "defeito de fabrica",
        "defeito de fábrica",
        "painel apagando",
        "problema eletrico",
        "problema elétrico",
        "vazamento",
    ]):
        return "duvidas", 0.98

    # ==========================================
    # CANCELAMENTO
    # ==========================================
    if any(p in texto_normalizado for p in [
        "cancelar revisao",
        "cancelar revisão",
        "cancelar minha revisao",
        "cancelar minha revisão",
        "cancelar agendamento",
        "desmarcar revisao",
        "desmarcar revisão",
        "quero cancelar",
        "cancelar meu horario",
        "cancelar meu horário",
    ]):
        return "cancelar_agendamento", 0.98

    # ==========================================
    # REAGENDAMENTO
    # ==========================================
    if any(p in texto_normalizado for p in [
        "reagendar revisao",
        "reagendar revisão",
        "reagendar agendamento",
        "remarcar revisao",
        "remarcar revisão",
        "trocar horario",
        "trocar horário",
        "mudar horario",
        "mudar horário",
        "quero remarcar",
        "quero reagendar",
    ]):
        return "reagendar_agendamento", 0.98

    # ==========================================
    # CONSULTA
    # ==========================================
    if any(p in texto_normalizado for p in [
        "consultar agendamento",
        "consultar revisao",
        "consultar revisão",
        "consultar minha revisao",
        "consultar minha revisão",
        "ver agendamento",
        "ver minha revisao",
        "ver minha revisão",
        "ver meu protocolo",
        "acompanhar agendamento",
        "acompanhar revisao",
        "acompanhar revisão",
        "qual meu agendamento",
        "tenho agendamento",
        "meu protocolo",
    ]):
        return "consultar_agendamento", 0.97

    # ==========================================
    # VALOR REVISÃO
    # ==========================================
    if texto_parece_valor_revisao(texto_normalizado):
        return "valor_revisao", 0.98

    # ==========================================
    # AGENDAMENTO
    # ==========================================
    if any(p in texto_normalizado for p in [
        "agendar revisao",
        "agendar revisão",
        "marcar revisao",
        "marcar revisão",
        "quero agendar",
        "agendamento",
        "marcar horario",
        "marcar horário",
        "agenda revisao",
        "agenda revisão",
    ]):
        return "agendar_revisao", 0.99

    # ==========================================
    # PEÇAS
    # ==========================================
    if texto_parece_valor_pecas(texto_normalizado):
        return "pecas", 0.99

    if texto_parece_consulta_pecas(texto_normalizado):
        return "pecas", 0.97

    if any(p in texto_normalizado for p in [
        "peca",
        "pecas",
        "peça",
        "peças",
        "orcamento",
        "orçamento",
        "valor do filtro",
        "preco do filtro",
        "preço do filtro",
        "quanto custa o filtro",
        "filtro de oleo",
        "filtro de óleo",
        "filtro de ar",
        "pastilha",
        "vela",
        "oleo do motor",
        "óleo do motor",
        "oleo",
        "óleo",
        "relacao",
        "relação",
        "kit transmissao",
        "kit transmissão",
        "pneu",
    ]):
        return "pecas", 0.96

    # ==========================================
    # ACESSÓRIOS
    # ==========================================
    if any(p in texto_normalizado for p in [
        "acessorio",
        "acessorios",
        "acessório",
        "acessórios",
        "slider",
        "bau",
        "baú",
        "suporte de celular",
        "suporte para celular",
        "protetor de motor",
    ]):
        return "acessorios", 0.95

    # ==========================================
    # DÚVIDAS
    # ==========================================
    if any(p in texto_normalizado for p in [
        "o que troca",
        "o que e trocado",
        "o que é trocado",
        "o que e verificado",
        "o que é verificado",
        "o que inclui na revisao",
        "o que inclui na revisão",
        "quanto tempo demora a revisao",
        "quanto tempo demora a revisão",
        "quanto tempo leva a revisao",
        "quanto tempo leva a revisão",
        "com quantos km faz a revisao",
        "com quantos km faz a revisão",
        "qual revisao de",
        "qual revisão de",
        "segunda revisao",
        "segunda revisão",
        "terceira revisao",
        "terceira revisão",
        "quarta revisao",
        "quarta revisão",
        "quinta revisao",
        "quinta revisão",
    ]):
        return "duvidas", 0.95

    if any(p in texto_normalizado for p in [
        "duvida",
        "dúvida",
        "tenho uma duvida",
        "tenho uma dúvida",
        "tenho duvida",
        "tenho dúvida",
        "pergunta",
        "informacao",
        "informação",
        "informacao sobre",
        "informação sobre",
        "me explica",
        "como funciona",
    ]):
        return "duvidas", 0.90

    # ==========================================
    # ATACADO
    # ==========================================
    if any(p in texto_normalizado for p in [
        "atacado",
        "logista",
        "lojista",
        "oficina",
        "parceria",
        "revenda",
        "revender",
        "comprar no atacado",
        "cotacao",
        "cotação",
        "catalogo",
        "catálogo",
        "quero tabela",
        "tabela de preco",
        "tabela de preço",
        "condicoes",
        "condições",
        "oleo yamalube",
        "óleo yamalube",
        "oleo yamalub",
        "óleo yamalub",
    ]):
        return "atacado", 0.96

    # ==========================================
    # HUMANO
    # ==========================================
    if any(p in texto_normalizado for p in [
        "atendente",
        "humano",
        "consultor",
        "falar com alguem",
        "falar com alguém",
        "falar com vendedor",
        "falar com consultor",
    ]):
        return "humano", 0.97

    return "", 0.0