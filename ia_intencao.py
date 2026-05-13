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
    "FAZER 250", "FZ15", "FZ25", "CROSSER", "LANDER",
    "MT03", "MT07", "R15", "R3", "FLUO", "NEO",
    "NMAX", "TENERE 700", "AEROX", "FACTOR", "CRYPTON",
]


BASE_DUVIDAS = {
    "garantia": [
        {
            "palavras_chave": [
                "garantia", "cobertura", "cobre", "defeito",
                "defeito de fabrica", "defeito de fábrica", "problema",
                "falha", "bateria", "painel", "motor", "vazamento",
                "embreagem", "pintura", "escapamento", "parte eletrica",
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
                "documento", "documentos", "manual", "nota", "nota fiscal",
                "preciso levar", "solicitar garantia",
            ],
            "resposta": (
                "Para atendimento de garantia, normalmente orientamos apresentar "
                "documentos da moto, informações do proprietário e histórico de revisões.\n\n"
                "Dependendo do caso, nossa equipe poderá solicitar dados complementares."
            )
        },
        {
            "palavras_chave": [
                "revisoes em dia", "revisões em dia", "perco garantia",
                "perder garantia", "fora da garantia", "garantia vencida",
                "revisao atrasada", "revisão atrasada",
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


# ==========================================
# NORMALIZAR OPÇÃO DIGITADA PELO CLIENTE
# Substitui antiga função de botão.
# Agora trabalha com texto simples/menu numérico.
# ==========================================
def normalizar_opcao_menu(texto):
    texto_norm = normalizar_texto(texto)
    texto_norm = texto_norm.replace("-", "_").replace(" ", "_")

    mapa_opcoes = {
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
        "marcar_revisao": "AGENDAR_REVISAO",

        "reagendar": "REAGENDAR_AGENDAMENTO",
        "reagendar_agendamento": "REAGENDAR_AGENDAMENTO",
        "remarcar": "REAGENDAR_AGENDAMENTO",
        "remarcar_revisao": "REAGENDAR_AGENDAMENTO",

        "cancelar": "CANCELAR_AGENDAMENTO",
        "cancelar_agendamento": "CANCELAR_AGENDAMENTO",
        "cancelar_revisao": "CANCELAR_AGENDAMENTO",

        "consultar": "CONSULTAR_AGENDAMENTO",
        "consultar_agendamento": "CONSULTAR_AGENDAMENTO",
        "consultar_revisao": "CONSULTAR_AGENDAMENTO",

        "falar_consultor": "MENU_HUMANO",
        "falar_com_consultor": "MENU_HUMANO",
        "consultor": "MENU_HUMANO",
        "humano": "MENU_HUMANO",
        "atendente": "MENU_HUMANO",

        "duvida_revisoes": "DUVIDA_REVISOES",
        "duvida_garantia": "DUVIDA_GARANTIA",
        "duvida_continuar": "DUVIDA_CONTINUAR",
        "duvida_outra": "DUVIDA_OUTRA",

        "quero_tabela": "ATACADO_TABELA",
        "tabela": "ATACADO_TABELA",
        "atacado_tabela": "ATACADO_TABELA",

        "atacado_consultor": "ATACADO_CONSULTOR",
        "consultor_atacado": "ATACADO_CONSULTOR",

        "depois": "DEPOIS",
        "atacado_depois": "ATACADO_DEPOIS",
    }

    return mapa_opcoes.get(texto_norm, "")


# Compatibilidade com trechos antigos do app.py
# Se ainda existir chamada antiga, não quebra o sistema.
def normalizar_botao_zapi(texto):
    return normalizar_opcao_menu(texto)


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
    if not OPENAI_API_KEY or OpenAI is None:
        return None

    try:
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        log_erro("Erro ao criar cliente OpenAI:", repr(e))
        return None


def texto_parece_garantia(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)

    termos_garantia = [
        "garantia", "garantido", "cobertura", "cobre", "cobrir",
        "perde garantia", "perco garantia", "perder garantia",
        "entra na garantia", "cobre bateria", "garantia cobre",
        "defeito", "defeito de fabrica",
        "problema de fabrica", "painel apagando",
        "vazamento", "motor falhando", "falhando",
    ]

    return any(t in texto_normalizado for t in termos_garantia)


def texto_parece_valor_revisao(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)

    termos_agendamento = [
        "agendar", "agendamento", "marcar", "remarcar", "reagendar",
        "cancelar", "consultar", "acompanhar", "horario", "segunda",
        "terca", "quarta", "quinta", "sexta", "sabado",
    ]

    if any(p in texto_normalizado for p in termos_agendamento):
        return False

    tem_valor = any(p in texto_normalizado for p in [
        "valor", "preco", "custa", "quanto custa", "quanto e",
    ])

    tem_contexto_revisao = any(p in texto_normalizado for p in [
        "revisao", "km", "quilometragem", "meses", "mes",
    ])

    tem_km = re.search(r"\b\d{1,3}(?:[.\s]?\d{3})*\s*km\b", texto_normalizado) is not None
    tem_meses = re.search(r"\b\d+\s*(?:meses|mes)\b", texto_normalizado) is not None

    return tem_valor and (tem_contexto_revisao or tem_km or tem_meses)


def texto_parece_valor_pecas(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)

    if texto_parece_garantia(texto_normalizado):
        return False

    termos_valor = [
        "valor", "preco", "quanto custa", "quanto e",
        "custa", "orcamento", "disponibilidade", "tem", "possui",
    ]

    termos_pecas = [
        "peca", "pecas", "oleo", "filtro",
        "filtro de oleo", "filtro de ar", "pastilha",
        "pastilha de freio", "pastilha dianteira", "pastilha traseira",
        "vela", "vela de ignicao", "bateria", "relacao",
        "kit transmissao", "corrente", "coroa",
        "pinhao", "pneu", "camara", "retentor",
        "amortecedor", "embreagem", "disco de freio", "lona de freio",
        "sapata de freio",
    ]

    return (
        any(p in texto_normalizado for p in termos_valor)
        and any(p in texto_normalizado for p in termos_pecas)
    )


def texto_parece_consulta_pecas(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)

    if texto_parece_garantia(texto_normalizado):
        return False

    termos_pecas = [
        "peca", "pecas", "oleo", "filtro",
        "filtro de oleo", "filtro de ar", "pastilha",
        "vela", "bateria", "relacao", "kit transmissao",
        "pneu", "corrente", "coroa", "pinhao",
        "retentor", "embreagem",
    ]

    termos_consulta = [
        "tem", "possui", "quanto", "valor", "preco", "custa",
        "orcamento", "disponibilidade", "quero saber", "preciso de",
    ]

    return (
        any(p in texto_normalizado for p in termos_pecas)
        and any(p in texto_normalizado for p in termos_consulta)
    )


def frase_parece_duvida(texto):
    texto_norm = normalizar_texto(texto)

    if texto_parece_garantia(texto_norm):
        return True

    if texto_parece_valor_pecas(texto_norm) or texto_parece_consulta_pecas(texto_norm):
        return False

    gatilhos_duvida = [
        "qual o valor", "qual valor", "quanto custa", "quanto e",
        "o que troca", "o que inclui", "o que faz", "o que e verificado",
        "quanto tempo", "quanto demora", "com quantos km",
        "qual km", "quais itens", "quais pecas", "como funciona",
        "me explica", "pode me explicar", "tenho uma duvida",
        "duvida sobre", "garantia cobre", "entra na garantia",
        "perde garantia", "perco garantia",
    ]

    marcadores_pergunta = [
        "qual", "quais", "quanto", "como", "o que", "me explica", "explica",
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
    return match.group(1) if match else ""


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

    return {
        1000: "1",
        5000: "2",
        10000: "3",
        15000: "4",
        20000: "5",
    }.get(km_int, "")


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
        "segunda": "1", "segunda feira": "1", "segunda-feira": "1",
        "terca": "2", "terca feira": "2", "terca-feira": "2",
        "quarta": "3", "quarta feira": "3", "quarta-feira": "3",
        "quinta": "4", "quinta feira": "4", "quinta-feira": "4",
        "sexta": "5", "sexta feira": "5", "sexta-feira": "5",
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
            nome = re.sub(r"\s+", " ", match.group(1)).strip()
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
            "lander", "crosser", "mt03", "mt07", "r15", "r3", "neo", "nmax",
            "aerox", "logista", "lojista", "atacado", "catalogo", "catálogo",
            "pecas", "peças", "cancelar", "reagendar", "consultar", "agendamento",
            "protocolo", "falar", "alguem", "alguém", "consultor", "duvida",
            "dúvida", "depois", "tabela", "oficina", "parceria", "bateria",
            "óleo", "oleo",
        }

        if not any(p.lower() in bloqueadas for p in palavras):
            return " ".join(palavras).upper()

    return ""


def extrair_cpf(texto):
    match = re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", str(texto or ""))
    return re.sub(r"\D", "", match.group(0)) if match else ""


def extrair_item_adicional(texto):
    texto_lower = normalizar_texto(texto)

    if texto_parece_garantia(texto_lower):
        return ""

    itens_comuns = [
        "filtro", "filtro de oleo", "filtro de ar",
        "pastilha traseira", "pastilha dianteira", "pastilha de freio",
        "sapata de freio", "kit lubrificante", "oleo",
        "slider", "bau", "suporte celular", "suporte para celular",
        "protetor motor", "protetor de motor", "vela", "vela de ignicao",
        "limpeza de bico", "limpeza de injecao",
        "troca de oleo", "bateria", "relacao", "kit transmissao",
        "pneu",
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

    if normalizar_opcao_menu(texto_limpo):
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

    if normalizar_opcao_menu(texto_limpo):
        return False

    intencoes_fortes = [
        "agendar", "agendar revisao", "marcar revisao",
        "falar consultor", "consultor", "humano",
        "quero tabela", "tabela", "atacado", "pecas",
        "acessorios", "garantia", "menu", "depois",
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
    opcao = normalizar_opcao_menu(texto_normalizado)

    if opcao in ["AGENDAR_REVISAO", "OPCAO_1"]:
        return "agendar_revisao", 1.0

    if opcao in ["MENU_HUMANO", "FALAR_CONSULTOR"]:
        return "humano", 1.0

    if opcao in ["MENU"]:
        return "menu", 0.99

    if opcao == "DEPOIS":
        return "menu", 0.80

    if opcao == "ATACADO_TABELA":
        return "atacado", 1.0

    if opcao == "ATACADO_CONSULTOR":
        return "humano", 1.0

    if opcao == "ATACADO_DEPOIS":
        return "menu", 0.80

    if texto_normalizado in ["menu", "voltar", "inicio"]:
        return "menu", 0.99

    if texto_normalizado in ["oi", "ola", "bom dia", "boa tarde", "boa noite"]:
        return "menu", 0.95

    if texto_parece_garantia(texto_normalizado):
        return "duvidas", 0.98

    if any(p in texto_normalizado for p in [
        "cancelar revisao", "cancelar minha revisao",
        "cancelar agendamento", "desmarcar revisao",
        "quero cancelar", "cancelar meu horario",
    ]):
        return "cancelar_agendamento", 0.98

    if any(p in texto_normalizado for p in [
        "reagendar revisao", "reagendar agendamento",
        "remarcar revisao", "trocar horario",
        "mudar horario", "quero remarcar", "quero reagendar",
    ]):
        return "reagendar_agendamento", 0.98

    if any(p in texto_normalizado for p in [
        "consultar agendamento", "consultar revisao",
        "consultar minha revisao", "ver agendamento",
        "ver minha revisao", "ver meu protocolo",
        "acompanhar agendamento", "acompanhar revisao",
        "qual meu agendamento", "tenho agendamento", "meu protocolo",
    ]):
        return "consultar_agendamento", 0.97

    if texto_parece_valor_revisao(texto_normalizado):
        return "valor_revisao", 0.98

    if any(p in texto_normalizado for p in [
        "agendar revisao", "marcar revisao", "quero agendar",
        "agendamento", "marcar horario", "agenda revisao",
    ]):
        return "agendar_revisao", 0.99

    if texto_parece_valor_pecas(texto_normalizado):
        return "pecas", 0.99

    if texto_parece_consulta_pecas(texto_normalizado):
        return "pecas", 0.97

    if any(p in texto_normalizado for p in [
        "peca", "pecas", "orcamento",
        "valor do filtro", "preco do filtro",
        "quanto custa o filtro", "filtro de oleo",
        "filtro de ar", "pastilha", "vela", "oleo do motor",
        "oleo", "relacao", "kit transmissao", "pneu",
    ]):
        return "pecas", 0.96

    if any(p in texto_normalizado for p in [
        "acessorio", "acessorios", "slider", "bau",
        "suporte de celular", "suporte para celular",
        "protetor de motor",
    ]):
        return "acessorios", 0.95

    if frase_parece_duvida(texto_normalizado):
        return "duvidas", 0.90

    if any(p in texto_normalizado for p in [
        "atacado", "logista", "lojista", "oficina", "parceria",
        "revenda", "revender", "comprar no atacado", "cotacao",
        "catalogo", "quero tabela", "tabela de preco",
        "condicoes", "oleo yamalube", "oleo yamalub",
    ]):
        return "atacado", 0.96

    if any(p in texto_normalizado for p in [
        "atendente", "humano", "consultor", "falar com alguem",
        "falar com vendedor", "falar com consultor",
    ]):
        return "humano", 0.97

    return "", 0.0

def sugerir_proxima_etapa(intencao, dados):
    if intencao == "agendar_revisao":
        if not dados.get("modelo"):
            return "revisao_modelo"
        if not dados.get("nome"):
            return "revisao_nome"
        if not dados.get("cpf"):
            return "revisao_cpf"
        if not dados.get("ano"):
            return "revisao_ano"
        if not dados.get("km"):
            return "revisao_km"
        if not dados.get("revisao"):
            return "revisao_revisao"
        if not dados.get("dia"):
            return "revisao_dia"
        if not dados.get("data"):
            return "revisao_data"
        if not dados.get("horario"):
            return "revisao_horario"

        return "revisao_venda"

    return {
        "cancelar_agendamento": "cancelar_agendamento",
        "reagendar_agendamento": "reagendar_agendamento",
        "consultar_agendamento": "consultar_agendamento",
        "valor_revisao": "consulta_valor_revisao",
        "duvidas": "menu_duvidas",
        "pecas": "pecas",
        "acessorios": "acessorios_modelo",
        "garantia": "garantia",
        "atacado": "atacado",
        "humano": "atendimento_humano",
        "menu": "menu",
    }.get(intencao, "menu")


def gerar_resposta(intencao, dados):
    if intencao == "agendar_revisao":
        return "Perfeito. Vou te ajudar com o agendamento da sua revisão."

    return {
        "cancelar_agendamento": "Certo. Vou te ajudar a cancelar seu agendamento de revisão.",
        "reagendar_agendamento": "Perfeito. Vou te ajudar a reagendar sua revisão.",
        "consultar_agendamento": "Certo. Vou consultar seu agendamento de revisão.",
        "valor_revisao": "Perfeito. Vou verificar as informações da revisão.",
        "duvidas": "Perfeito. Vou te direcionar para a central de dúvidas.",
        "pecas": "Certo. Vou seguir com seu atendimento de peças.",
        "acessorios": "Perfeito. Vou seguir com seu atendimento de acessórios.",
        "garantia": "Certo. Vou seguir com sua solicitação de garantia.",
        "atacado": "Perfeito. Vou te direcionar para o atendimento de logista e atacado.",
        "humano": "Certo. Vou te encaminhar para atendimento humano.",
        "menu": "Perfeito. Vou te enviar o menu principal.",
    }.get(intencao, "Entendi sua mensagem. Vou te ajudar com isso.")


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
                        "Responda apenas uma palavra: agendar_revisao, cancelar_agendamento, "
                        "reagendar_agendamento, consultar_agendamento, valor_revisao, duvidas, "
                        "pecas, acessorios, garantia, atacado, humano, menu. "
                        "Se parecer dado de cadastro, responda vazio."
                    )
                },
                {
                    "role": "user",
                    "content": texto
                }
            ]
        )

        conteudo = resposta.choices[0].message.content.strip().lower()

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
            "menu",
        }

        if conteudo in permitidas:
            return conteudo, 0.85

        return "", 0.0

    except Exception as e:
        log_erro("Erro ao classificar intenção:", repr(e))
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
        log_erro("Erro ao carregar planilha revisões:", repr(e))
        return "Não consegui consultar as informações de revisão no momento."

    if df.empty:
        return "A planilha de revisões está vazia no momento."

    colunas_necessarias = [
        "modelo",
        "revisao_numero",
        "KM",
        "MESES",
        "valor",
        "tempo_estimado",
        "itens_trocados",
        "itens_verificados",
    ]

    for coluna in colunas_necessarias:
        if coluna not in df.columns:
            return f"A coluna '{coluna}' não foi encontrada na planilha de revisões."

    pergunta_normalizada = normalizar_texto(pergunta)

    df["modelo"] = df["modelo"].astype(str).str.upper().str.strip()

    modelo_filtrado = str(modelo or "").upper().strip()
    revisao_filtrada = str(revisao or "").strip()

    if not modelo_filtrado:
        modelo_filtrado = extrair_modelo(pergunta).upper().strip()

    if not revisao_filtrada:
        revisao_filtrada = extrair_revisao(pergunta)

    if not revisao_filtrada:
        km_extraido = extrair_km(pergunta)

        if km_extraido:
            revisao_filtrada = km_para_revisao(km_extraido)

    if modelo_filtrado:
        df = df[df["modelo"] == modelo_filtrado]

    if revisao_filtrada:
        try:
            df = df[df["revisao_numero"] == int(revisao_filtrada)]
        except Exception:
            pass

    if df.empty:
        return (
            "Não encontrei essa revisão na base de dados.\n\n"
            "Tente informar o modelo da moto e o número da revisão."
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

    if any(p in pergunta_normalizada for p in [
        "valor",
        "preco",
        "quanto custa",
        "custo",
    ]):
        return (
            f"O valor estimado da {revisao_linha}ª revisão da "
            f"{modelo_linha} é {formatar_valor_brl(valor)}."
        )

    if any(p in pergunta_normalizada for p in [
        "tempo",
        "demora",
        "duracao",
        "quanto tempo",
    ]):
        return (
            f"O tempo estimado da {revisao_linha}ª revisão da "
            f"{modelo_linha} é {tempo_estimado}."
        )

    if any(p in pergunta_normalizada for p in [
        "troca",
        "trocado",
        "trocados",
        "o que troca",
    ]):
        return (
            f"Na {revisao_linha}ª revisão da {modelo_linha}, "
            f"os principais itens trocados são:\n\n{itens_trocados}"
        )

    if any(p in pergunta_normalizada for p in [
        "verifica",
        "verificado",
        "verificados",
        "checagem",
        "confere",
    ]):
        return (
            f"Na {revisao_linha}ª revisão da {modelo_linha}, "
            f"os principais itens verificados são:\n\n{itens_verificados}"
        )

    if any(p in pergunta_normalizada for p in [
        "km",
        "quilometragem",
    ]):
        return (
            f"A {revisao_linha}ª revisão da {modelo_linha} "
            f"é prevista para aproximadamente {km} km."
        )

    if any(p in pergunta_normalizada for p in [
        "mes",
        "meses",
        "prazo",
    ]):
        return (
            f"A {revisao_linha}ª revisão da {modelo_linha} "
            f"é prevista para {meses} meses."
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
            revisao=revisao,
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
            item.get("palavras_chave", []),
        )

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_item = item

    if melhor_item and melhor_pontuacao > 0:
        return melhor_item["resposta"]

    return (
        "Recebi sua dúvida, mas ainda não encontrei uma resposta exata na base.\n\n"
        "Se desejar, posso te encaminhar para nossa equipe."
    )


def classificar_intencao(texto):
    texto = limpar_texto(texto)

    dados_vazios = {
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
        "km_atual": "",
        "observacao": "",
        "tipo_atendimento": "",
        "opcao_menu": "",
        "botao_zapi": "",
    }

    if not texto:
        return {
            "intencao": "menu",
            "confianca": 1.0,
            "resposta": gerar_resposta("menu", dados_vazios),
            "proxima_etapa": "menu",
            "dados_extraidos": dados_vazios,
        }

    texto_normalizado = normalizar_texto(texto)

    # Agora usamos opção de menu em texto simples.
    # botao_zapi fica apenas por compatibilidade com app.py antigo.
    opcao_menu = normalizar_opcao_menu(texto)
    botao_zapi = opcao_menu

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
        "km_atual": extrair_km(texto),
        "observacao": extrair_observacao(texto),
        "tipo_atendimento": extrair_tipo_atendimento(texto),
        "opcao_menu": opcao_menu,
        "botao_zapi": botao_zapi,
    }

    if not dados["revisao"] and dados["km"]:
        dados["revisao"] = km_para_revisao(dados["km"])

    if opcao_menu:
        dados["observacao"] = ""

    if not intencao:
        if texto_parece_garantia(texto_normalizado):
            intencao = "duvidas"
            confianca = 0.95

        elif texto_parece_valor_pecas(texto_normalizado):
            intencao = "pecas"
            confianca = 0.95

        elif texto_parece_consulta_pecas(texto_normalizado):
            intencao = "pecas"
            confianca = 0.93

        elif frase_parece_duvida(texto):
            intencao = "duvidas"
            confianca = 0.90

        elif (
            dados["nome"]
            or dados["cpf"]
            or dados["ano"]
            or dados["dia"]
            or dados["data"]
            or dados["horario"]
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
        "dados_extraidos": dados,
    }

    log_info("Retorno final IA:", retorno)

    return retorno


def extrair_tipo_atendimento(texto):
    texto_norm = normalizar_texto(texto)

    if "aguardar" in texto_norm or texto_norm in ["1", "opcao_1"]:
        return "AGUARDAR NA CONCESSIONÁRIA"

    if (
        "deixar" in texto_norm
        or "retirar depois" in texto_norm
        or texto_norm in ["2", "opcao_2"]
    ):
        return "DEIXAR A MOTO E RETIRAR DEPOIS"

    return ""


def texto_parece_dado_de_fluxo(texto):
    texto_limpo = limpar_texto(texto)
    texto_norm = normalizar_texto(texto_limpo)

    if not texto_limpo:
        return False

    if normalizar_opcao_menu(texto_limpo):
        return False

    intencoes_fortes = [
        "agendar",
        "agendar revisao",
        "marcar revisao",
        "falar consultor",
        "consultor",
        "humano",
        "quero tabela",
        "tabela",
        "atacado",
        "pecas",
        "acessorios",
        "garantia",
        "menu",
        "depois",
        "cancelar",
        "reagendar",
        "consultar",
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

    if texto_norm in ["1", "2", "3", "4", "5", "6", "7"]:
        return True

    return False


def detectar_intencao_regras(texto_normalizado):
    texto_normalizado = normalizar_texto(texto_normalizado)
    opcao = normalizar_opcao_menu(texto_normalizado)

    if opcao in ["AGENDAR_REVISAO", "OPCAO_1"]:
        return "agendar_revisao", 1.0

    if opcao in ["MENU_HUMANO", "FALAR_CONSULTOR"]:
        return "humano", 1.0

    if opcao == "MENU":
        return "menu", 0.99

    if opcao == "DEPOIS":
        return "menu", 0.80

    if opcao == "ATACADO_TABELA":
        return "atacado", 1.0

    if opcao == "ATACADO_CONSULTOR":
        return "humano", 1.0

    if opcao == "ATACADO_DEPOIS":
        return "menu", 0.80

    if texto_normalizado in ["menu", "voltar", "inicio"]:
        return "menu", 0.99

    if texto_normalizado in [
        "oi",
        "ola",
        "bom dia",
        "boa tarde",
        "boa noite",
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
        "painel apagando",
        "problema eletrico",
        "vazamento",
    ]):
        return "duvidas", 0.98

    # ==========================================
    # CANCELAMENTO
    # ==========================================
    if any(p in texto_normalizado for p in [
        "cancelar revisao",
        "cancelar minha revisao",
        "cancelar agendamento",
        "desmarcar revisao",
        "quero cancelar",
        "cancelar meu horario",
    ]):
        return "cancelar_agendamento", 0.98

    # ==========================================
    # REAGENDAMENTO
    # ==========================================
    if any(p in texto_normalizado for p in [
        "reagendar revisao",
        "reagendar agendamento",
        "remarcar revisao",
        "trocar horario",
        "mudar horario",
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
        "consultar minha revisao",
        "ver agendamento",
        "ver minha revisao",
        "ver meu protocolo",
        "acompanhar agendamento",
        "acompanhar revisao",
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
        "marcar revisao",
        "quero agendar",
        "agendamento",
        "marcar horario",
        "agenda revisao",
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
        "orcamento",
        "valor do filtro",
        "preco do filtro",
        "quanto custa o filtro",
        "filtro de oleo",
        "filtro de ar",
        "pastilha",
        "vela",
        "oleo do motor",
        "oleo",
        "relacao",
        "kit transmissao",
        "pneu",
    ]):
        return "pecas", 0.96

    # ==========================================
    # ACESSÓRIOS
    # ==========================================
    if any(p in texto_normalizado for p in [
        "acessorio",
        "acessorios",
        "slider",
        "bau",
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
        "o que e verificado",
        "o que inclui na revisao",
        "quanto tempo demora a revisao",
        "quanto tempo leva a revisao",
        "com quantos km faz a revisao",
        "qual revisao de",
        "segunda revisao",
        "terceira revisao",
        "quarta revisao",
        "quinta revisao",
    ]):
        return "duvidas", 0.95

    if any(p in texto_normalizado for p in [
        "duvida",
        "tenho uma duvida",
        "tenho duvida",
        "pergunta",
        "informacao",
        "informacao sobre",
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
        "catalogo",
        "quero tabela",
        "tabela de preco",
        "condicoes",
        "oleo yamalube",
        "oleo yamalub",
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
        "falar com vendedor",
        "falar com consultor",
    ]):
        return "humano", 0.97

    return "", 0.0