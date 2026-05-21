# ==========================================
# FERRAMENTAS IA - YAMAHA BOT
# Integra base de conhecimento + manuais PDF
# ==========================================

import re
import unicodedata
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
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caractere for caractere in texto
        if unicodedata.category(caractere) != "Mn"
    )
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def limpar_texto(texto):
    return str(texto or "").strip()


TERMOS_PECAS_PRIORITARIOS = [
    "yamalube",
    "10w40",
    "20w50",
    "oleo",
    "óleo",
    "filtro",
    "pastilha",
    "relacao",
    "relação",
    "pneu",
    "bateria",
    "vela",
    "retrovisor",
    "manete",
    "cabo",
    "corrente",
    "coroa",
    "pinhao",
    "pinhão",
]

TERMOS_COTACAO = [
    "preco",
    "preço",
    "valor",
    "quanto custa",
    "cotacao",
    "cotação",
    "orcamento",
    "orçamento",
]

TERMOS_ESTOQUE = [
    "tem",
    "estoque",
    "disponivel",
    "disponível",
    "referencia",
    "referência",
]


def contem_termo(texto, termos):
    texto_norm = normalizar_texto(texto)
    return any(normalizar_texto(termo) in texto_norm for termo in termos)


def detectar_item_peca(texto):
    texto_norm = normalizar_texto(texto)
    encontrados = []
    vistos = set()

    for termo in TERMOS_PECAS_PRIORITARIOS:
        termo_norm = normalizar_texto(termo)

        if termo_norm in texto_norm and termo_norm not in vistos:
            vistos.add(termo_norm)
            encontrados.append(termo_norm)

    if not encontrados:
        return ""

    item = " ".join(encontrados)
    medidas = re.findall(r"\b\d{1,2}w\d{2}\b", texto_norm)
    medidas = [medida for medida in medidas if medida not in vistos]

    if medidas:
        item = f"{item} {' '.join(medidas)}"

    return item.strip()


def texto_parece_peca_ou_cotacao(texto):
    tem_peca = contem_termo(texto, TERMOS_PECAS_PRIORITARIOS)
    tem_cotacao = contem_termo(texto, TERMOS_COTACAO)
    tem_estoque = contem_termo(texto, TERMOS_ESTOQUE)
    return tem_peca and (tem_cotacao or tem_estoque or "yamalube" in normalizar_texto(texto))


def texto_parece_status_garantia_ou_os(texto):
    texto_norm = normalizar_texto(texto)

    if "garantia" in texto_norm and any(
        termo in texto_norm
        for termo in ["consultar", "acompanhar", "status", "processo", "como esta"]
    ):
        return True

    return (
        ("os" in texto_norm or "ordem de servico" in texto_norm)
        and any(termo in texto_norm for termo in ["consultar", "acompanhar", "status", "aberta", "andamento"])
    )


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

    if texto_parece_status_garantia_ou_os(texto):
        if "garantia" in texto:
            return "acompanhar_garantia"
        return "acompanhar_os"

    if texto_parece_peca_ou_cotacao(texto):
        if contem_termo(texto, TERMOS_ESTOQUE):
            return "consulta_estoque"
        return "pecas"

    intencoes = {
        "revisao": [
            "revisao",
            "revisão",
            "agendar",
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


def extrair_dados_estruturados(texto, modelo="", contexto_cliente=None):
    contexto_cliente = contexto_cliente if isinstance(contexto_cliente, dict) else {}
    modelo_detectado = modelo or identificar_modelo(texto) or contexto_cliente.get("modelo", "")

    return {
        "modelo": modelo_detectado,
        "item": detectar_item_peca(texto),
        "cpf": limpar_texto(contexto_cliente.get("cpf", "")),
        "telefone": limpar_texto(contexto_cliente.get("telefone", "")),
        "nome": limpar_texto(contexto_cliente.get("nome", "")),
        "texto_original": limpar_texto(texto),
    }


def sugerir_acao(intencao):
    return {
        "pecas": "iniciar_fluxo_pecas",
        "consulta_estoque": "consultar_estoque_sances",
        "orcamento": "montar_pre_orcamento",
        "garantia": "iniciar_fluxo_garantia",
        "acompanhar_garantia": "consultar_garantia_sances",
        "acompanhar_os": "consultar_os_sances",
        "revisao": "responder_duvida_revisao",
        "problema_tecnico": "encaminhar_pos_venda",
        "humano": "encaminhar_atendimento_humano",
        "atacado": "iniciar_fluxo_atacado",
        "acessorios": "iniciar_fluxo_acessorios",
    }.get(intencao or "", "encaminhar_atendimento_humano")


def calcular_confianca(intencao, fonte, urgencia="baixa"):
    if fonte in ["base_conhecimento", "manual_pdf"]:
        return 0.9 if urgencia != "alta" else 0.75

    if intencao in ["pecas", "consulta_estoque", "acompanhar_garantia", "acompanhar_os"]:
        return 0.88

    if intencao:
        return 0.72

    return 0.45


def montar_retorno_ia(fonte, resposta, categoria, modelo, urgencia, intencao, dados, encaminhar_humano=False):
    confianca = calcular_confianca(intencao, fonte, urgencia)

    return {
        "fonte": fonte,
        "resposta": resposta,
        "categoria": categoria,
        "modelo": modelo,
        "urgencia": urgencia,
        "intencao": intencao,
        "acao": sugerir_acao(intencao),
        "dados": dados,
        "confianca": confianca,
        "encaminhar_humano": bool(encaminhar_humano or urgencia == "alta" or confianca < 0.55),
    }


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

    if intencao in ["acompanhar_garantia", "acompanhar_os"]:
        return (
            "Certo. Para consultar o andamento no Sances, preciso confirmar seu CPF com 11 números."
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

    if intencao == "consulta_estoque":
        return (
            "Vou consultar a disponibilidade desse item. Para cotar corretamente, me informe modelo, ano e a peça ou referência desejada."
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
def responder_ia(texto, modelo="", contexto_cliente=None):
    texto_original = limpar_texto(texto)
    texto_norm = normalizar_texto(texto_original)
    contexto_cliente = contexto_cliente if isinstance(contexto_cliente, dict) else {}

    if not modelo:
        modelo = identificar_modelo(texto_norm) or contexto_cliente.get("modelo", "")

    urgencia = classificar_urgencia(texto_norm)
    intencao = identificar_intencao(texto_norm)
    intencoes_manual = {"revisao", "garantia", "problema_tecnico"}
    dados = extrair_dados_estruturados(texto_original, modelo=modelo, contexto_cliente=contexto_cliente)

    if intencao in ["pecas", "consulta_estoque", "acompanhar_garantia", "acompanhar_os"]:
        return montar_retorno_ia(
            fonte="ferramenta_roteamento",
            resposta=montar_resposta_fallback(texto_norm, modelo=modelo, urgencia=urgencia),
            categoria=intencao,
            modelo=modelo,
            urgencia=urgencia,
            intencao=intencao,
            dados=dados,
            encaminhar_humano=False,
        )

    # Para dúvidas técnicas, o manual é a fonte oficial. A IA só transforma
    # o trecho encontrado em uma resposta natural.
    if modelo and intencao in intencoes_manual:
        resultado_manual = consultar_manual_pdf(modelo, texto_norm)

        if resultado_manual.get("encontrou"):
            return montar_retorno_ia(
                fonte=resultado_manual.get("fonte", "manual_pdf"),
                resposta=resultado_manual.get("resposta", ""),
                categoria=resultado_manual.get("assunto", "manual"),
                modelo=resultado_manual.get("modelo", modelo),
                urgencia=urgencia,
                intencao=intencao,
                dados=dados,
                encaminhar_humano=urgencia == "alta",
            )

    # ==========================================
    # 1) BASE DE CONHECIMENTO
    # ==========================================
    resultado_base = consultar_base_conhecimento(texto_norm)

    if resultado_base.get("encontrou"):
        return montar_retorno_ia(
            fonte="base_conhecimento",
            resposta=resultado_base.get("resposta", ""),
            categoria=resultado_base.get("categoria", intencao),
            modelo=modelo,
            urgencia=urgencia,
            intencao=intencao,
            dados=dados,
            encaminhar_humano=urgencia == "alta",
        )

    # ==========================================
    # 2) MANUAL PDF
    # Só consulta manual se tiver modelo.
    # ==========================================
    if modelo:
        resultado_manual = consultar_manual_pdf(modelo, texto_norm)

        if resultado_manual.get("encontrou"):
            return montar_retorno_ia(
                fonte=resultado_manual.get("fonte", "manual_pdf"),
                resposta=resultado_manual.get("resposta", ""),
                categoria=resultado_manual.get("assunto", "manual"),
                modelo=resultado_manual.get("modelo", modelo),
                urgencia=urgencia,
                intencao=intencao,
                dados=dados,
                encaminhar_humano=urgencia == "alta",
            )

    # ==========================================
    # 3) FALLBACK
    # ==========================================
    return montar_retorno_ia(
        fonte="fallback",
        resposta=montar_resposta_fallback(
            texto=texto_norm,
            modelo=modelo,
            urgencia=urgencia,
        ),
        categoria=intencao or "humano",
        modelo=modelo,
        urgencia=urgencia,
        intencao=intencao,
        dados=dados,
        encaminhar_humano=True,
    )


# ==========================================
# TESTE LOCAL
# ==========================================
if __name__ == "__main__":
    pergunta = "quanto custa a revisão da minha fz15"

    resultado = responder_ia(pergunta)

    print("\n")
    print(resultado)
    print("\n")
