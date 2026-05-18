# ==========================================
# IA COMERCIAL - YAMAHA BOT / IA MOTOSHOW
# Fase 1: conversão, follow-up, recuperação e venda adicional
# ==========================================

import os
import re
import unicodedata

from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODELO_COMERCIAL = os.getenv("OPENAI_MODELO_COMERCIAL", "gpt-4o-mini").strip()


def obter_cliente_openai():
    if not OPENAI_API_KEY or OpenAI is None:
        return None

    try:
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        return None


# ==========================================
# NORMALIZAÇÃO
# ==========================================
def normalizar_texto(texto):
    texto = str(texto or "").lower().strip()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )

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


def limpar_texto(texto):
    return str(texto or "").strip()


# ==========================================
# DETECÇÕES
# ==========================================
def detectar_modelo(texto):
    texto = normalizar_texto(texto)

    modelos = {
        "tenere 700": "TENERE 700",
        "tenere": "TENERE 700",
        "t7": "TENERE 700",

        "fazer 250": "FAZER 250",
        "fz25": "FAZER 250",
        "fz 25": "FAZER 250",

        "fz15": "FZ15",
        "fz 15": "FZ15",
        "fazer 150": "FZ15",

        "lander": "LANDER",
        "crosser": "CROSSER",
        "factor": "FACTOR",
        "nmax": "NMAX",
        "fluo": "FLUO",
        "neo": "NEO",
        "aerox": "AEROX",

        "mt03": "MT-03",
        "mt 03": "MT-03",
        "mt-03": "MT-03",

        "mt07": "MT-07",
        "mt 07": "MT-07",
        "mt-07": "MT-07",

        "r15": "R15",
        "r 15": "R15",
        "r3": "R3",
        "r 3": "R3",
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

    if intencao in ["pecas", "pecas_orcamento", "orcamento"]:
        return "pecas"

    if intencao in ["acessorios", "acessorios_orcamento"]:
        return "acessorios"

    if intencao == "garantia":
        return "garantia"

    if intencao in ["atacado", "atacado_catalogo"]:
        return "atacado"

    if any(p in texto for p in [
        "revisao", "oleo", "manutencao", "revisar", "km",
    ]):
        return "revisao"

    if any(p in texto for p in [
        "peca", "pastilha", "filtro", "relacao", "pneu",
        "corrente", "coroa", "pinhao", "vela", "bateria",
    ]):
        return "pecas"

    if any(p in texto for p in [
        "acessorio", "slider", "bau", "protetor", "suporte",
        "bolha", "bagageiro",
    ]):
        return "acessorios"

    if any(p in texto for p in [
        "garantia", "falhando", "barulho", "vazando", "painel",
        "defeito", "cobre", "cobertura",
    ]):
        return "garantia"

    if any(p in texto for p in [
        "atacado", "lojista", "logista", "oficina", "revenda",
        "catalogo", "tabela", "parceria", "yamalube",
    ]):
        return "atacado"

    return "geral"


def detectar_produto_interesse(texto):
    texto_norm = normalizar_texto(texto)
    produtos = [
        "oleo", "filtro", "filtro de oleo", "filtro de ar", "pastilha", "pneu",
        "relacao", "kit relacao", "corrente", "coroa", "pinhao",
        "vela", "bateria", "slider", "bau", "suporte de celular",
        "protetor de motor", "protetor de carenagem", "bagageiro",
        "catalogo", "catalogo de atacado", "catalogo de acessorios",
    ]

    encontrados = [produto for produto in produtos if produto in texto_norm]

    if encontrados:
        return ", ".join(dict.fromkeys(encontrados))

    palavras = [
        p for p in re.split(r"\s+", texto_norm)
        if len(p) >= 4 and p not in {
            "quero", "preciso", "valor", "preco", "quanto", "custa",
            "orcamento", "catalogo", "minha", "moto", "yamaha",
        }
    ]

    return " ".join(palavras[:5]).strip()


def texto_pede_orcamento_ou_preco(texto):
    texto_norm = normalizar_texto(texto)
    termos = [
        "orcamento", "cotacao", "cotar", "preco", "valor",
        "quanto custa", "quanto fica", "tem disponivel", "disponibilidade",
        "pode separar", "quero comprar",
    ]
    return any(termo in texto_norm for termo in termos)


def texto_parece_lista_itens(texto):
    texto_original = str(texto or "")
    texto_norm = normalizar_texto(texto_original)

    if "," in texto_original or "\n" in texto_original:
        return True

    termos_itens = [
        "oleo", "filtro", "pastilha", "pneu", "relacao", "corrente",
        "coroa", "pinhao", "vela", "bateria", "slider", "bau",
    ]

    return sum(1 for termo in termos_itens if termo in texto_norm) >= 2


def sugestao_venda_adicional(interesse, produto_interesse="", modelo=""):
    interesse = normalizar_texto(interesse)
    produto = normalizar_texto(produto_interesse)

    if "oleo" in produto:
        return "Também vale verificar o filtro de óleo e a mão de obra da troca."

    if "filtro" in produto:
        return "Podemos verificar junto óleo adequado e instalação na oficina."

    if interesse == "revisao":
        return "Na revisão, também podemos avaliar lubrificante, filtro e lubrificação da corrente."

    if interesse == "acessorios":
        return "Para acessórios, um consultor pode confirmar instalação e compatibilidade com sua moto."

    if interesse == "pecas":
        return "Além da peça, nossa equipe pode cotar a mão de obra de instalação, se você quiser."

    if interesse == "atacado":
        return "Para atacado, envie uma lista com peças, óleo Yamalube e itens de giro para montarmos uma cotação."

    return ""


def humanizar_resposta_comercial_com_ia(resposta_base, texto="", modelo="", interesse="", produto_interesse=""):
    cliente = obter_cliente_openai()

    if cliente is None:
        return ""

    try:
        resposta = cliente.chat.completions.create(
            model=OPENAI_MODELO_COMERCIAL,
            temperature=0.25,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um assistente comercial da Motoshow Yamaha. Reescreva a resposta "
                        "em português do Brasil, com tom humano, curto e profissional. Não invente "
                        "preço, estoque, prazo, desconto ou disponibilidade. Sempre que houver pedido "
                        "de orçamento, preço ou compra, diga que um consultor confirmará os detalhes."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Mensagem do cliente: {texto}\n"
                        f"Modelo: {modelo}\n"
                        f"Interesse: {interesse}\n"
                        f"Produto de interesse: {produto_interesse}\n\n"
                        f"Resposta base segura:\n{resposta_base}\n\n"
                        "Reescreva em no máximo 3 parágrafos curtos."
                    ),
                },
            ],
        )

        conteudo = limpar_texto(resposta.choices[0].message.content)

        if conteudo:
            return conteudo[:900]

    except Exception:
        return ""

    return ""


# ==========================================
# LEAD SCORING
# ==========================================
def classificar_nivel_interesse(texto, intencao=""):
    texto = normalizar_texto(texto)
    intencao = normalizar_texto(intencao)

    baixa = [
        "depois vejo",
        "vou pensar",
        "mais tarde",
        "agora nao",
        "nao quero",
        "so olhando",
        "só olhando",
        "so pesquisando",
    ]

    alta = [
        "quero agendar",
        "pode marcar",
        "tem vaga",
        "hoje",
        "amanha",
        "vou fazer",
        "preciso fazer",
        "quero fazer",
        "qual horario",
        "agenda",
        "agendar",
        "marcar",
        "quero comprar",
        "pode separar",
        "manda o catalogo",
        "quero tabela",
    ]

    media = [
        "quanto custa",
        "qual valor",
        "quanto fica",
        "tem disponivel",
        "faz orcamento",
        "queria saber",
        "preco",
        "valor",
        "catalogo",
        "tabela",
    ]

    if any(item in texto for item in baixa):
        return "BAIXO"

    if texto_pede_orcamento_ou_preco(texto) or texto_parece_lista_itens(texto):
        return "ALTO"

    if any(item in texto for item in alta):
        return "ALTO"

    if intencao == "atacado" and any(p in texto for p in ["catalogo", "tabela"]):
        return "ALTO"

    if any(item in texto for item in media):
        return "MEDIO"

    if intencao in ["agendar_revisao", "atacado_catalogo"]:
        return "ALTO"

    if intencao in ["valor_revisao", "pecas", "acessorios", "garantia", "atacado"]:
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
    intencao = normalizar_texto(intencao)

    if intencao == "atacado_catalogo":
        return "ENVIAR_CATALOGO_ATACADO"

    if intencao == "atacado" and any(p in texto for p in ["catalogo", "tabela"]):
        return "ENVIAR_CATALOGO_ATACADO"

    if texto_pede_orcamento_ou_preco(texto) or texto_parece_lista_itens(texto):
        return "ENCAMINHAR_CONSULTOR"

    if nivel == "ALTO":
        if intencao in ["pecas", "orcamento", "acessorios", "atacado"]:
            return "ENCAMINHAR_CONSULTOR"

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
            "baú",
            "farol auxiliar",
            "lubrificação de corrente",
        ],
        "crosser": [
            "baú",
            "protetor de carenagem",
            "kit relação",
            "lubrificação de corrente",
        ],
        "nmax": [
            "bolha",
            "suporte de celular",
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

    for chave, lista in sugestoes.items():
        if chave in modelo:
            return lista

    return []


# ==========================================
# RESPOSTAS COMERCIAIS
# ==========================================
def montar_oferta_comercial(modelo="", interesse="geral"):
    modelo = modelo or "sua Yamaha"
    interesse = normalizar_texto(interesse)

    sugestoes = sugestoes_por_modelo(modelo)

    if interesse == "revisao":
        base = (
            f"A revisão da *{modelo}* é essencial para manter a moto segura, econômica "
            "e dentro do padrão Yamaha ✅\n\n"
            "Durante o atendimento, nossa equipe verifica itens importantes para evitar "
            "gastos maiores no futuro."
        )

    elif interesse == "pecas":
        base = (
            f"Consigo te ajudar com peças para *{modelo}* ✅\n\n"
            "Podemos verificar disponibilidade, prazo de encomenda, valores e instalação na oficina."
        )

    elif interesse == "acessorios":
        base = (
            f"Temos acessórios que podem deixar sua *{modelo}* mais completa, protegida "
            "e confortável ✅"
        )

    elif interesse == "garantia":
        base = (
            f"Posso te orientar sobre garantia da *{modelo}* ✅\n\n"
            "Para verificar corretamente, preciso saber o modelo, ano, o que aconteceu "
            "e se as revisões estão em dia."
        )

    elif interesse == "atacado":
        base = (
            "Temos condições comerciais para oficinas, lojistas e revendedores ✅\n\n"
            "Trabalhamos com peças, óleo Yamalube e itens Yamaha para reposição e revenda."
        )

    else:
        base = (
            "Posso te ajudar com revisão, peças, acessórios, garantia, atacado ou atendimento humano ✅"
        )

    if sugestoes:
        itens = ", ".join(sugestoes[:4])
        base += f"\n\nPara esse modelo, também recomendamos verificar: {itens}."

    return base


def gerar_resposta_comercial(texto="", modelo="", intencao="", revisao="", km_atual="", nome=""):
    texto = limpar_texto(texto)
    nome = limpar_texto(nome)

    if not modelo:
        modelo = detectar_modelo(texto)

    if not modelo:
        modelo = "sua Yamaha"

    interesse = detectar_interesse_comercial(texto, intencao)
    produto_interesse = detectar_produto_interesse(texto)
    nivel = classificar_nivel_interesse(texto, intencao)
    temperatura = classificar_temperatura_lead(texto, intencao)
    proxima_acao = proxima_acao_comercial(texto, intencao)
    oportunidade = temperatura == "QUENTE" or proxima_acao == "ENCAMINHAR_CONSULTOR"

    saudacao = f"{nome}, " if nome else ""

    resposta = saudacao + montar_oferta_comercial(
        modelo=modelo,
        interesse=interesse,
    )

    sugestao_extra = sugestao_venda_adicional(
        interesse=interesse,
        produto_interesse=produto_interesse,
        modelo=modelo,
    )

    if sugestao_extra:
        resposta += f"\n\n{sugestao_extra}"

    if proxima_acao == "ENVIAR_CATALOGO_ATACADO":
        resposta += (
            "\n\nVou te enviar o catálogo de atacado agora. "
            "Depois disso, um consultor pode te ajudar com valores, disponibilidade e condições comerciais."
        )

    elif proxima_acao == "OFERECER_AGENDAMENTO":
        resposta += "\n\nTenho horários disponíveis. Deseja que eu siga com o agendamento?"

    elif proxima_acao == "ENCAMINHAR_CONSULTOR":
        resposta += (
            "\n\nPara valores, disponibilidade e orçamento final, vou encaminhar para um consultor confirmar tudo com segurança."
        )

    elif proxima_acao == "COLETAR_DADOS_OU_ORCAMENTO":
        resposta += (
            "\n\nPara eu te ajudar melhor, me envie:\n"
            "1️⃣ Modelo da moto\n"
            "2️⃣ Ano\n"
            "3️⃣ O que você precisa"
        )

    else:
        resposta += "\n\nQuando quiser, posso te ajudar a consultar opções ou iniciar o atendimento."

    resposta_humanizada = humanizar_resposta_comercial_com_ia(
        resposta_base=resposta,
        texto=texto,
        modelo=modelo,
        interesse=interesse,
        produto_interesse=produto_interesse,
    )

    if resposta_humanizada:
        resposta = resposta_humanizada

    return {
        "resposta": resposta,
        "modelo": modelo,
        "interesse": interesse,
        "produto_interesse": produto_interesse,
        "oportunidade_comercial": oportunidade,
        "nivel_interesse": nivel,
        "temperatura_lead": temperatura,
        "proxima_acao": proxima_acao,
        "encaminhar_humano": oportunidade,
        "status_comercial": "OPORTUNIDADE_QUENTE" if oportunidade else "EM_NUTRICAO",
    }


# ==========================================
# MENSAGEM ATACADO COM ENGAJAMENTO
# ==========================================
def gerar_mensagem_atacado(nome="", empresa=""):
    nome = limpar_texto(nome)
    empresa = limpar_texto(empresa)

    saudacao = f"Olá, {nome}!" if nome else "Olá!"

    complemento_empresa = (
        f"\n\nVi aqui o contato da *{empresa}* e quero te apresentar uma oportunidade para compra no atacado."
        if empresa else
        "\n\nQuero te apresentar uma oportunidade para compra no atacado."
    )

    return (
        f"{saudacao}{complemento_empresa}\n\n"
        "A Motoshow Yamaha trabalha com peças, óleo Yamalube e itens para oficinas, lojistas e revendedores.\n\n"
        "Temos atendimento comercial para quem busca:\n"
        "✅ reposição com mais segurança\n"
        "✅ produtos Yamaha/Yamalube\n"
        "✅ suporte para orçamento\n"
        "✅ melhores condições para compra em volume\n\n"
        "Escolha uma opção:\n\n"
        "1️⃣ Receber catálogo de atacado\n"
        "2️⃣ Falar com consultor\n"
        "3️⃣ Ver depois"
    )


# ==========================================
# FOLLOW-UP
# ==========================================
def gerar_mensagem_followup(nivel, modelo="", etapa="", nome=""):
    modelo = modelo or "sua moto"
    nome_limpo = limpar_texto(nome)
    nome = f"{nome_limpo}, " if nome_limpo else ""
    etapa_limpa = limpar_texto(etapa)

    cliente = obter_cliente_openai()

    if cliente is not None:
        try:
            resposta = cliente.chat.completions.create(
                model=OPENAI_MODELO_COMERCIAL,
                temperature=0.3,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Você escreve follow-ups comerciais curtos para uma concessionária Yamaha. "
                            "Seja humano, profissional e objetivo. Não prometa valores, descontos ou prazos. "
                            "Use no máximo 2 parágrafos curtos e termine com uma pergunta simples para retomar o atendimento."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Nome: {nome_limpo or 'cliente'}\n"
                            f"Modelo: {modelo}\n"
                            f"Etapa/contexto: {etapa_limpa or 'atendimento iniciado'}\n"
                            f"Nível do follow-up: {nivel}\n"
                            "Crie a mensagem."
                        ),
                    },
                ],
            )

            conteudo = limpar_texto(resposta.choices[0].message.content)

            if conteudo:
                return conteudo[:700]
        except Exception:
            pass

    if nivel == 1:
        return (
            f"{nome}vi que você iniciou o atendimento, mas ainda não finalizou ✅\n\n"
            "Posso continuar seu atendimento agora?"
        )

    if nivel == 2:
        return (
            f"{nome}ainda temos disponibilidade para atendimento da *{modelo}*.\n\n"
            "Deseja que eu verifique um horário para você?"
        )

    if nivel == 3:
        return (
            f"{nome}sua *{modelo}* pode estar próxima da revisão preventiva.\n\n"
            "Fazer a revisão no prazo ajuda a evitar gastos maiores depois. Deseja agendar?"
        )

    return f"{nome}posso te ajudar a concluir seu atendimento?"


# ==========================================
# RECUPERAÇÃO
# ==========================================
def gerar_mensagem_recuperacao(modelo="", nome=""):
    modelo = modelo or "sua Yamaha"
    nome = f"{nome}, " if nome else ""

    return (
        f"{nome}estamos entrando em contato para lembrar da manutenção preventiva da *{modelo}* ✅\n\n"
        "Manter as revisões em dia ajuda na segurança, economia e valorização da sua moto.\n\n"
        "Deseja verificar uma vaga para revisão esta semana?"
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

    if (
        "nmax" in modelo_norm
        or "neo" in modelo_norm
        or "fluo" in modelo_norm
        or "aerox" in modelo_norm
    ):
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

    print("\n--- ATACADO ---\n")
    print(gerar_mensagem_atacado(nome="João", empresa="Oficina Teste"))
