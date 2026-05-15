# ==========================================
# BASE DE CONHECIMENTO - MOTOSHOW YAMAHA
# Pós-venda / Revisão / Garantia
# ==========================================

import re
from difflib import SequenceMatcher


# ==========================================
# BASE FIXA
# ==========================================
BASE_CONHECIMENTO = {

    "valor_revisao": {
        "keywords": [
            "quanto custa a revisao",
            "valor da revisao",
            "preco da revisao",
            "preço da revisão",
            "revisao da fz15",
            "quanto fica revisao",
            "quanto fica a revisao",
            "valor revisao",
            "valor revisão",
        ],
        "resposta": (
            "O valor da revisão depende do modelo, número da revisão e se a moto está na garantia.\n\n"
            "Se estiver na garantia, os valores podem ser consultados no site da Yamaha, na aba Serviços, "
            "ou confirmados diretamente com o pós-venda da concessionária."
        )
    },

    "revisao_5000km": {
        "keywords": [
            "5 mil km",
            "5000 km",
            "minha moto chegou nos 5 mil",
            "preciso revisar",
            "quando fazer revisao",
            "quando fazer revisão",
        ],
        "resposta": (
            "As revisões devem seguir o manual do proprietário, considerando tempo ou quilometragem, "
            "o que ocorrer primeiro.\n\n"
            "Se sua moto chegou próximo da quilometragem da revisão, o ideal é agendar para evitar perda de prazo."
        )
    },

    "revisao_sem_agendar": {
        "keywords": [
            "posso fazer revisao sem agendar",
            "sem agendamento",
            "precisa agendar",
            "revisao sem marcar",
            "posso ir sem marcar",
        ],
        "resposta": (
            "De preferência, as revisões devem ser agendadas com antecedência para garantir melhor atendimento, "
            "organização da oficina e disponibilidade de horário."
        )
    },

    "tempo_revisao": {
        "keywords": [
            "quanto tempo demora a revisao",
            "demora revisao",
            "tempo da revisao",
            "quantas horas revisao",
            "lander demora quantas horas",
            "quanto tempo leva",
        ],
        "resposta": (
            "O tempo da revisão depende do modelo e de qual revisão será realizada.\n\n"
            "A primeira e segunda revisão costumam ser mais rápidas, mas revisões maiores podem exigir mais tempo."
        )
    },

    "troca_oleo_revisao": {
        "keywords": [
            "troca oleo na revisao",
            "trocam oleo",
            "oleo na revisao",
            "substitui oleo",
            "troca óleo revisão",
        ],
        "resposta": (
            "Sim. Nas revisões é feita a substituição do óleo conforme o plano de manutenção do modelo."
        )
    },

    "oleo_crosser": {
        "keywords": [
            "qual oleo crosser",
            "oleo da crosser",
            "óleo da crosser",
            "yamalube crosser",
            "20w50 crosser",
        ],
        "resposta": (
            "Para a Crosser, normalmente utilizamos Yamalube 20W50.\n\n"
            "Mesmo assim, o ideal é confirmar a especificação conforme o ano/modelo da moto."
        )
    },

    "oleo_proprio_cliente": {
        "keywords": [
            "posso levar meu proprio oleo",
            "posso levar meu próprio óleo",
            "levar oleo",
            "meu oleo",
            "oleo proprio",
            "óleo próprio",
        ],
        "resposta": (
            "Pode sim, desde que seja óleo adequado e dentro da especificação recomendada pela Yamaha. "
            "Para maior segurança, confirme com o pós-venda antes do atendimento."
        )
    },

    "atraso_revisao_garantia": {
        "keywords": [
            "revisao perde garantia se atrasar",
            "atrasar revisao perde garantia",
            "passei do km da revisao",
            "limite da revisao",
            "passei da revisão",
            "perdi a garantia",
        ],
        "resposta": (
            "Se ultrapassar o limite estabelecido pelo fabricante, pode haver restrição ou perda da garantia.\n\n"
            "O ideal é verificar o histórico da moto e o prazo exato com o pós-venda."
        )
    },

    "primeira_revisao": {
        "keywords": [
            "quantos km primeira revisao",
            "primeira revisao",
            "1 revisao",
            "1ª revisão",
            "1000 km",
            "seis meses",
            "6 meses",
        ],
        "resposta": (
            "A primeira revisão deve ser feita com 1.000 km ou 6 meses da data da compra, "
            "o que ocorrer primeiro."
        )
    },

    "tolerancia_primeira_revisao": {
        "keywords": [
            "900 km posso agendar",
            "tolerancia primeira revisao",
            "tolerância primeira revisão",
            "minha moto ta com 900 km",
            "900 a 1100",
        ],
        "resposta": (
            "Sim. Para a primeira revisão, a tolerância normalmente é de 900 km a 1.100 km."
        )
    },

    "lavagem_revisao": {
        "keywords": [
            "revisao inclui lavagem",
            "lava a moto",
            "lavagem na revisao",
        ],
        "resposta": (
            "Sim. A revisão inclui lavagem, conforme disponibilidade e fluxo da oficina."
        )
    },

    "esperar_moto": {
        "keywords": [
            "posso esperar a moto ficar pronta",
            "sala de espera",
            "aguardar revisao",
            "esperar a moto",
        ],
        "resposta": (
            "Pode sim. Temos sala de espera para clientes, principalmente em revisões mais rápidas."
        )
    },

    "revisao_sabado": {
        "keywords": [
            "tem revisao no sabado",
            "revisao sabado",
            "sabado faz revisao",
        ],
        "resposta": (
            "Aos sábados realizamos somente a primeira e segunda revisão, dependendo do fluxo de agendamento."
        )
    },

    "busca_moto": {
        "keywords": [
            "voces buscam a moto",
            "buscar moto em casa",
            "leva e traz",
            "busca em casa",
        ],
        "resposta": (
            "No momento não buscamos a moto em casa."
        )
    },

    "deixar_moto": {
        "keywords": [
            "posso deixar a moto",
            "buscar depois",
            "deixar e buscar depois",
            "deixar a moto e retirar depois",
        ],
        "resposta": (
            "Pode sim. Você pode deixar a moto na concessionária e buscar depois."
        )
    },

    "revisao_rapida": {
        "keywords": [
            "tem revisao rapida",
            "revisao rapida",
            "1 revisao demora",
            "2 revisao demora",
        ],
        "resposta": (
            "A primeira e segunda revisão têm média de tempo de 1h30 a 2h, dependendo do fluxo da oficina."
        )
    },

    "regulagem_valvula": {
        "keywords": [
            "qual revisao faz regulagem de valvula",
            "regulagem de valvula",
            "ajuste de valvula",
        ],
        "resposta": (
            "A partir da primeira revisão é feita a verificação. "
            "Sempre que estiver fora do especificado, é realizado o ajuste."
        )
    },

    "servicos_oficina": {
        "keywords": [
            "faz alinhamento",
            "faz limpeza de bico",
            "troca relacao",
            "troca relação",
            "troca de pneu",
            "tem troca de pneu",
        ],
        "resposta": (
            "Sim. Realizamos alinhamento, limpeza de bico, troca de relação e troca de pneu."
        )
    },

    "mao_de_obra": {
        "keywords": [
            "quanto fica a mao de obra",
            "valor da mao de obra",
            "preco mao de obra",
            "preço mão de obra",
        ],
        "resposta": (
            "O valor da mão de obra depende do serviço a ser executado. "
            "Nossa equipe pode verificar o orçamento conforme o modelo e serviço necessário."
        )
    },

    "nmax_revisao": {
        "keywords": [
            "revisao da nmax e mais cara",
            "nmax revisao cara",
            "valor revisao nmax",
        ],
        "resposta": (
            "As revisões na garantia possuem preço fixo conforme tabela da Yamaha. "
            "O valor pode variar conforme a revisão e itens necessários."
        )
    },

    "filtro_ar": {
        "keywords": [
            "qual revisao troca filtro de ar",
            "troca filtro de ar",
            "filtro de ar",
        ],
        "resposta": (
            "Depende da necessidade de substituição. Em todas as revisões é feita a verificação."
        )
    },

    # ==========================================
    # GARANTIA
    # ==========================================
    "garantia_status": {
        "keywords": [
            "minha moto ainda ta na garantia",
            "esta na garantia",
            "garantia da minha moto",
        ],
        "resposta": (
            "Precisamos verificar o modelo, data da compra e histórico de revisões para confirmar se a moto ainda está na garantia."
        )
    },

    "garantia_escapamento_enferrujado": {
        "keywords": [
            "escapamento enferrujado garantia",
            "escapamento enferrujou",
            "ferrugem escapamento",
        ],
        "resposta": (
            "Depende do uso e do estado da peça. É necessário avaliar na concessionária."
        )
    },

    "garantia_escapamento_esportivo": {
        "keywords": [
            "escapamento esportivo perde garantia",
            "colocar escapamento perde garantia",
            "escape esportivo",
        ],
        "resposta": (
            "A instalação de escapamento esportivo não anula automaticamente toda a garantia, "
            "mas pode restringir a cobertura se a modificação for considerada causa direta de algum defeito."
        )
    },

    "garantia_bateria": {
        "keywords": [
            "garantia cobre bateria",
            "bateria tem garantia",
            "garantia da bateria",
        ],
        "resposta": (
            "A bateria geralmente não possui a mesma cobertura contratual da motocicleta, por ser item de desgaste. "
            "Ela pode ter garantia legal obrigatória de 90 dias, desde que seja constatado vício de fabricação."
        )
    },

    "tempo_garantia": {
        "keywords": [
            "quanto tempo dura a garantia yamaha",
            "tempo de garantia",
            "garantia yamaha dura quanto",
        ],
        "resposta": (
            "O tempo de garantia depende do modelo da motocicleta. "
            "Para confirmar corretamente, informe o modelo e ano da moto."
        )
    },

    "revisao_fora_concessionaria": {
        "keywords": [
            "posso fazer revisao fora da concessionaria",
            "revisao fora perde garantia",
            "oficina fora da yamaha",
        ],
        "resposta": (
            "Fazer revisão fora da concessionária Yamaha pode resultar na perda da garantia de fábrica. "
            "A Yamaha exige que as revisões periódicas sejam realizadas na rede autorizada para manter a cobertura."
        )
    },

    "garantia_guidao": {
        "keywords": [
            "trocar guidao perde garantia",
            "guidão perde garantia",
            "guidao perde garantia",
            "instalar guidao",
        ],
        "resposta": (
            "A troca do guidão não anula automaticamente toda a garantia, mas pode restringir a cobertura. "
            "A garantia pode ser negada se a modificação for considerada causa direta do defeito."
        )
    },

    "garantia_eletrica": {
        "keywords": [
            "garantia cobre problema eletrico",
            "problema eletrico garantia",
            "sistema eletrico garantia",
        ],
        "resposta": (
            "Problemas no sistema elétrico podem ser cobertos quando causados por defeito de fabricação, "
            "desde que o sistema original não tenha sido alterado."
        )
    },

    "garantia_moto_falhando": {
        "keywords": [
            "moto falhando entra garantia",
            "moto falhando garantia",
            "falha no motor garantia",
        ],
        "resposta": (
            "Falhas no motor ou sistema de injeção podem ser avaliadas em garantia. "
            "A concessionária fará um diagnóstico para verificar se há defeito de fabricação, mau uso ou combustível adulterado."
        )
    },

    "garantia_painel": {
        "keywords": [
            "garantia cobre painel apagando",
            "painel apagou garantia",
            "painel apagando",
        ],
        "resposta": (
            "O painel de instrumentos pode ser coberto se apagar por defeito interno, "
            "desde que o sistema elétrico original não tenha sido alterado."
        )
    },

    "farol_auxiliar": {
        "keywords": [
            "posso instalar farol auxiliar",
            "farol auxiliar perde garantia",
            "instalar led",
            "instalar farol",
        ],
        "resposta": (
            "Não é recomendado instalar acessórios não originais no sistema elétrico, como faróis auxiliares, "
            "lâmpadas de LED ou alarmes. Caso a modificação afete o sistema elétrico, pode haver perda de garantia."
        )
    },

    "peca_paralela_garantia": {
        "keywords": [
            "peca paralela perde garantia",
            "peça paralela perde garantia",
            "usar peca paralela",
            "peca nao original",
        ],
        "resposta": (
            "O uso de peças, acessórios ou componentes não autorizados pela marca pode invalidar a garantia da parte afetada "
            "e, em alguns casos, de sistemas relacionados."
        )
    },

    "garantia_vazamento": {
        "keywords": [
            "garantia cobre vazamento",
            "vazamento garantia",
            "vazando oleo garantia",
        ],
        "resposta": (
            "Vazamentos de óleo ou fluidos causados por falha de vedação, juntas ou retentores podem ser avaliados em garantia, "
            "após análise técnica."
        )
    },

    "garantia_embreagem": {
        "keywords": [
            "garantia cobre embreagem",
            "embreagem garantia",
            "disco de embreagem garantia",
        ],
        "resposta": (
            "Peças de desgaste natural, como discos de embreagem, pastilhas de freio, relação e pneus, normalmente não são cobertas. "
            "Porém, defeitos em componentes estruturais podem ser avaliados."
        )
    },

    "garantia_pintura": {
        "keywords": [
            "yamaha cobre defeito de pintura",
            "garantia pintura",
            "pintura descascando",
            "bolha na pintura",
        ],
        "resposta": (
            "Defeitos de fabricação na pintura original, como descascamento, bolhas ou falhas no verniz, podem ser avaliados, "
            "desde que não sejam causados por agentes externos."
        )
    },
}


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

    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def similaridade(a, b):
    a = normalizar_texto(a)
    b = normalizar_texto(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def pontuar(pergunta_norm, keyword_norm):
    if not pergunta_norm or not keyword_norm:
        return 0

    pontos = 0

    if keyword_norm in pergunta_norm:
        pontos += 6

    palavras_keyword = [
        p for p in keyword_norm.split()
        if len(p) > 3
    ]

    for palavra in palavras_keyword:
        if palavra in pergunta_norm:
            pontos += 1

    sim = similaridade(pergunta_norm, keyword_norm)

    if sim >= 0.85:
        pontos += 5
    elif sim >= 0.70:
        pontos += 3
    elif sim >= 0.55:
        pontos += 1

    return pontos


# ==========================================
# BUSCAR RESPOSTA
# ==========================================
def buscar_na_base_conhecimento(pergunta):
    pergunta_norm = normalizar_texto(pergunta)

    if not pergunta_norm:
        return {
            "encontrou": False,
            "categoria": "",
            "resposta": "",
            "pontuacao": 0,
        }

    melhor_resposta = ""
    melhor_pontuacao = 0
    melhor_categoria = ""

    for categoria, dados in BASE_CONHECIMENTO.items():
        pontuacao_categoria = 0

        for keyword in dados.get("keywords", []):
            keyword_norm = normalizar_texto(keyword)
            pontuacao_categoria += pontuar(pergunta_norm, keyword_norm)

        if pontuacao_categoria > melhor_pontuacao:
            melhor_pontuacao = pontuacao_categoria
            melhor_resposta = dados.get("resposta", "")
            melhor_categoria = categoria

    if melhor_pontuacao <= 1:
        return {
            "encontrou": False,
            "categoria": "",
            "resposta": "",
            "pontuacao": melhor_pontuacao,
        }

    return {
        "encontrou": True,
        "categoria": melhor_categoria,
        "resposta": melhor_resposta,
        "pontuacao": melhor_pontuacao,
    }


# ==========================================
# TESTE LOCAL
# ==========================================
if __name__ == "__main__":
    pergunta = "quanto custa a revisão da minha fz15?"

    resultado = buscar_na_base_conhecimento(pergunta)

    print(resultado)