# ==========================================
# IA COMERCIAL - YAMAHA BOT / IA MOTOSHOW
# Fase 1: conversão, follow-up, recuperação e venda adicional
# ==========================================

import re


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


# ==========================================
# DETECÇÕES
# ==========================================
def detectar_modelo(texto):
    texto = normalizar_texto(texto)

    modelos = {
        "fz15": "FZ15",
        "fazer 150": "FZ15",
        "fazer 250": "FAZER 250",
        "fz25": "FAZER 250",
        "lander": "LANDER",
        "crosser": "CROSSER",
        "factor": "FACTOR",
        "nmax": "NMAX",
        "fluo": "FLUO",
        "neo": "NEO",
        "mt03": "MT-03",
        "mt 03": "MT-03",
        "mt07": "MT-07",
        "mt 07": "MT-07",
        "r15": "R15",
        "r3": "R3",
        "aerox": "AEROX",
        "tenere": "TENERE 700",
        "tenere 700": "TENERE 700",
    }

    for chave, nome in modelos.items():
        if chave in texto:
            return nome

    return ""


def detectar_interesse_comercial(texto, intencao=""):
    texto = normalizar_texto(texto)
    intencao = normalizar_texto(intencao)

    if intencao in ["valor_revisao", "agendar_revisao", "revisao"]:
        return "revisao"

    if intencao in ["pecas", "peças", "orcamento", "orçamento"]:
        return "pecas"

    if intencao in ["acessorios", "acessórios"]:
        return "acessorios"

    if intencao == "garantia":
        return "garantia"

    if any(p in texto for p in ["revisao", "óleo", "oleo", "manutencao", "manutenção"]):
        return "revisao"

    if any(p in texto for p in ["peca", "peça", "pastilha", "filtro", "relacao", "relação", "pneu"]):
        return "pecas"

    if any(p in texto for p in ["acessorio", "acessório", "slider", "bau", "baú", "protetor", "suporte", "bolha"]):
        return "acessorios"

    if any(p in texto for p in ["garantia", "falhando", "barulho", "vazando", "painel", "defeito"]):
        return "garantia"

    return "geral"


# ==========================================
# LEAD SCORING
# ==========================================
def classificar_nivel_interesse(texto, intencao=""):
    texto = normalizar_texto(texto)
    intencao = normalizar_texto(intencao)

    alta = [
        "quero agendar",
        "pode marcar",
        "tem vaga",
        "hoje",
        "amanha",
        "amanhã",
        "vou fazer",
        "preciso fazer",
        "quero fazer",
        "qual horario",
        "qual horário",
        "agenda",
        "agendar",
        "marcar",
    ]

    media = [
        "quanto custa",
        "qual valor",
        "quanto fica",
        "tem disponivel",
        "tem disponível",
        "faz orçamento",
        "faz orcamento",
        "queria saber",
        "preco",
        "preço",
        "valor",
    ]

    baixa = [
        "depois vejo",
        "vou pensar",
        "mais tarde",
        "agora nao",
        "agora não",
        "nao quero",
        "não quero",
    ]

    if any(item in texto for item in baixa):
        return "BAIXO"

    if any(item in texto for item in alta):
        return "ALTO"

    if any(item in texto for item in media):
        return "MEDIO"

    if intencao in ["agendar_revisao", "revisao"]:
        return "ALTO"

    if intencao in ["valor_revisao", "pecas", "acessorios", "garantia"]:
        return "MEDIO"

    return "MEDIO"


def classificar_temperatura_lead(texto, intencao=""):
    nivel = classificar_nivel_interesse(texto, intencao)

    if nivel == "ALTO":
        return "QUENTE"

    if nivel == "MEDIO":
        return "MORNO"

    return "FRIO"


def proxima_acao_comercial(texto, intencao=""):
    nivel = classificar_nivel_interesse(texto, intencao)

    if nivel == "ALTO":
        return "OFERECER_AGENDAMENTO"

    if nivel == "MEDIO":
        return "COLETAR_DADOS_OU_ORCAMENTO"

    return "NUTRIR_LEAD"


# ==========================================
# SUGESTÕES POR MODELO
# ==========================================
def sugestoes_por_modelo(modelo):
    modelo = normalizar_texto(modelo)

    sugestoes = {
        "fz15": [
            "slider",
            "suporte de celular",
            "protetor de motor",
            "lubrificação de corrente"
        ],
        "fazer 250": [
            "slider",
            "pastilha de freio",
            "kit relação",
            "suporte de celular"
        ],
        "fz25": [
            "slider",
            "pastilha de freio",
            "kit relação",
            "suporte de celular"
        ],
        "lander": [
            "protetor de motor",
            "baú",
            "farol auxiliar",
            "lubrificação de corrente"
        ],
        "crosser": [
            "baú",
            "protetor de carenagem",
            "kit relação",
            "lubrificação de corrente"
        ],
        "nmax": [
            "bolha",
            "suporte de celular",
            "pastilha de freio",
            "limpeza do sistema CVT"
        ],
        "aerox": [
            "bolha",
            "pastilha de freio",
            "óleo",
            "limpeza do sistema CVT"
        ],
    }

    for chave, lista in sugestoes.items():
        if chave in modelo:
            return lista

    return []


# ==========================================
# IA COMERCIAL
# ==========================================
def montar_oferta_comercial(modelo="", interesse="geral"):
    modelo = modelo or "sua Yamaha"
    modelo_norm = normalizar_texto(modelo)
    interesse = normalizar_texto(interesse)

    sugestoes = sugestoes_por_modelo(modelo_norm)

    if interesse == "revisao":
        base = (
            f"A revisão da {modelo} é essencial para manter a moto segura, econômica "
            f"e dentro do padrão Yamaha ✅\n\n"
            f"Durante o atendimento, a equipe verifica itens importantes para evitar "
            f"gastos maiores no futuro."
        )

    elif interesse == "pecas":
        base = (
            f"Consigo te ajudar com peças para {modelo} ✅\n\n"
            f"Trabalhamos com peças Yamaha e também podemos verificar disponibilidade, "
            f"prazo de encomenda e instalação na oficina."
        )

    elif interesse == "acessorios":
        base = (
            f"Temos acessórios que podem deixar sua {modelo} mais completa, protegida "
            f"e confortável ✅"
        )

    elif interesse == "garantia":
        base = (
            f"Posso te orientar sobre garantia da {modelo} ✅\n\n"
            f"Para verificar corretamente, preciso saber o modelo, ano, o que aconteceu "
            f"e se as revisões estão em dia."
        )

    else:
        base = (
            "Posso te ajudar com revisão, peças, acessórios, garantia ou atendimento humano ✅"
        )

    if sugestoes:
        itens = ", ".join(sugestoes[:4])
        base += f"\n\nPara esse modelo, também recomendamos verificar: {itens}."

    return base


def gerar_resposta_comercial(texto="", modelo="", intencao="", revisao="", km_atual="", nome=""):
    if not modelo:
        modelo = detectar_modelo(texto)

    if not modelo:
        modelo = "sua Yamaha"

    interesse = detectar_interesse_comercial(texto, intencao)
    nivel = classificar_nivel_interesse(texto, intencao)
    temperatura = classificar_temperatura_lead(texto, intencao)
    proxima_acao = proxima_acao_comercial(texto, intencao)

    saudacao = f"{nome}, " if nome else ""

    resposta = saudacao + montar_oferta_comercial(
        modelo=modelo,
        interesse=interesse
    )

    if proxima_acao == "OFERECER_AGENDAMENTO":
        resposta += "\n\nTenho horários disponíveis. Deseja que eu siga com o agendamento?"

    elif proxima_acao == "COLETAR_DADOS_OU_ORCAMENTO":
        resposta += (
            "\n\nPara eu te ajudar melhor, me envie:\n"
            "1️⃣ Modelo da moto\n"
            "2️⃣ Ano\n"
            "3️⃣ O que você precisa"
        )

    else:
        resposta += "\n\nQuando quiser, posso te ajudar a consultar opções ou iniciar o agendamento."

    return {
        "resposta": resposta,
        "modelo": modelo,
        "interesse": interesse,
        "nivel_interesse": nivel,
        "temperatura_lead": temperatura,
        "proxima_acao": proxima_acao,
    }


# ==========================================
# FOLLOW-UP
# ==========================================
def gerar_mensagem_followup(nivel, modelo="", etapa="", nome=""):
    modelo = modelo or "sua moto"
    nome = f"{nome}, " if nome else ""

    if nivel == 1:
        return (
            f"{nome}vi que você iniciou o atendimento, mas ainda não finalizou ✅\n\n"
            f"Posso continuar seu atendimento agora?"
        )

    if nivel == 2:
        return (
            f"{nome}ainda temos disponibilidade para atendimento da {modelo}.\n\n"
            f"Deseja que eu verifique um horário para você?"
        )

    if nivel == 3:
        return (
            f"{nome}sua {modelo} pode estar próxima da revisão preventiva.\n\n"
            f"Fazer a revisão no prazo ajuda a evitar gastos maiores depois. Deseja agendar?"
        )

    return f"{nome}posso te ajudar a concluir seu atendimento?"


# ==========================================
# RECUPERAÇÃO
# ==========================================
def gerar_mensagem_recuperacao(modelo="", nome=""):
    modelo = modelo or "sua Yamaha"
    nome = f"{nome}, " if nome else ""

    return (
        f"{nome}estamos entrando em contato para lembrar da manutenção preventiva da {modelo} ✅\n\n"
        f"Manter as revisões em dia ajuda na segurança, economia e valorização da sua moto.\n\n"
        f"Deseja verificar uma vaga para revisão esta semana?"
    )


# ==========================================
# VENDA ADICIONAL
# ==========================================
def gerar_mensagem_venda_adicional(modelo="", revisao="", km_atual=""):
    modelo_norm = normalizar_texto(modelo)

    if "fz25" in modelo_norm or "fazer" in modelo_norm:
        return (
            "Aproveitando seu atendimento, para esse modelo é importante verificar também "
            "relação, pastilhas e pneu traseiro conforme o uso da moto.\n\n"
            "Deseja incluir uma avaliação desses itens no atendimento?"
        )

    if "fz15" in modelo_norm:
        return (
            "Aproveitando seu atendimento, para a FZ15 muitos clientes verificam também "
            "pastilhas, pneus, lubrificação da corrente e acessórios de proteção.\n\n"
            "Deseja incluir uma avaliação desses itens?"
        )

    if "crosser" in modelo_norm:
        return (
            "Para a Crosser, muitos clientes aproveitam a revisão para verificar relação, "
            "pneus e acessórios como protetor de carenagem e baú.\n\n"
            "Deseja incluir uma avaliação?"
        )

    if "lander" in modelo_norm:
        return (
            "Para a Lander, recomendamos verificar relação, pastilhas, pneus e itens de proteção.\n\n"
            "Deseja incluir uma avaliação junto da revisão?"
        )

    if "nmax" in modelo_norm or "neo" in modelo_norm or "fluo" in modelo_norm or "aerox" in modelo_norm:
        return (
            "Para scooters, é importante verificar correia, roletes, óleo e pneus conforme a quilometragem.\n\n"
            "Deseja incluir essa verificação?"
        )

    return (
        "Deseja aproveitar o atendimento para incluir uma avaliação de pneus, relação, pastilhas ou acessórios?"
    )


if __name__ == "__main__":
    teste = "quanto fica a revisão da minha fz15?"
    print(gerar_resposta_comercial(teste))