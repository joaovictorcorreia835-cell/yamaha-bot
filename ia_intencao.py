def detectar_intencao_regras(texto_normalizado):

    # ============================
    # PRIORIDADE 1 — DÚVIDAS
    # ============================

    if any(p in texto_normalizado for p in PALAVRAS_DUVIDAS_REVISAO):
        return "duvidas", 0.99

    # ============================
    # MENU
    # ============================

    if any(p in texto_normalizado for p in [
        "menu", "oi", "ola", "bom dia", "boa tarde", "boa noite"
    ]):
        return "menu", 0.99


    # ============================
    # AGENDAMENTO
    # ============================

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


    # ============================
    # CANCELAR
    # ============================

    if any(p in texto_normalizado for p in [
        "cancelar revisao",
        "cancelar minha revisao",
        "cancelar agendamento",
        "desmarcar revisao",
        "quero cancelar"
    ]):
        return "cancelar_agendamento", 0.98


    # ============================
    # REAGENDAR
    # ============================

    if any(p in texto_normalizado for p in [
        "reagendar revisao",
        "remarcar revisao",
        "trocar horario",
        "mudar horario"
    ]):
        return "reagendar_agendamento", 0.98


    # ============================
    # CONSULTAR
    # ============================

    if any(p in texto_normalizado for p in [
        "consultar agendamento",
        "ver minha revisao",
        "ver protocolo",
        "acompanhar revisao"
    ]):
        return "consultar_agendamento", 0.97


    # ============================
    # VALOR
    # ============================

    if texto_parece_valor_revisao(texto_normalizado):
        return "valor_revisao", 0.98


    # ============================
    # DÚVIDAS GERAIS
    # ============================

    if any(p in texto_normalizado for p in [
        "duvida",
        "tenho uma duvida",
        "informacao",
        "informação",
        "pergunta"
    ]):
        return "duvidas", 0.95


    # ============================
    # PEÇAS
    # ============================

    if any(p in texto_normalizado for p in [
        "peca",
        "pecas",
        "orcamento"
    ]):
        return "pecas", 0.94


    # ============================
    # ACESSORIOS
    # ============================

    if any(p in texto_normalizado for p in [
        "acessorio",
        "acessorios"
    ]):
        return "acessorios", 0.94


    # ============================
    # GARANTIA
    # ============================

    if "garantia" in texto_normalizado:
        return "garantia", 0.94


    # ============================
    # ATACADO
    # ============================

    if any(p in texto_normalizado for p in [
        "atacado",
        "logista",
        "cotacao",
        "catalogo"
    ]):
        return "atacado", 0.94


    # ============================
    # HUMANO
    # ============================

    if any(p in texto_normalizado for p in [
        "atendente",
        "humano",
        "consultor"
    ]):
        return "humano", 0.97


    return "", 0.0