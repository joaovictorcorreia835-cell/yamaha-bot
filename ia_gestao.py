# ==========================================
# IA DE GESTÃO - YAMAHA BOT / CRM
# Consulta dados do banco e gera resumos
# ==========================================

from datetime import datetime, timedelta
from sqlalchemy import func

from database import (
    SessionLocal,
    Atendimento,
    AgendamentoRevisao,
    FaqRevisao,
    Disparo,
    LeadAtacado,
)


def periodo_datas(periodo="hoje"):
    hoje = datetime.now()

    if periodo == "hoje":
        inicio = hoje.replace(hour=0, minute=0, second=0, microsecond=0)

    elif periodo == "semana":
        inicio = hoje - timedelta(days=7)

    elif periodo == "mes":
        inicio = hoje - timedelta(days=30)

    else:
        inicio = hoje - timedelta(days=3650)

    return inicio, hoje


def resumo_atendimentos(periodo="hoje"):
    db = SessionLocal()

    try:
        inicio, fim = periodo_datas(periodo)

        total = db.query(Atendimento).filter(
            Atendimento.data >= inicio,
            Atendimento.data <= fim
        ).count()

        humano = db.query(Atendimento).filter(
            Atendimento.data >= inicio,
            Atendimento.data <= fim,
            Atendimento.atendimento_humano == True
        ).count()

        concluidos = db.query(Atendimento).filter(
            Atendimento.data >= inicio,
            Atendimento.data <= fim,
            Atendimento.concluido == True
        ).count()

        por_setor = db.query(
            Atendimento.setor,
            func.count(Atendimento.id)
        ).filter(
            Atendimento.data >= inicio,
            Atendimento.data <= fim
        ).group_by(
            Atendimento.setor
        ).all()

        return {
            "total": total,
            "humano": humano,
            "concluidos": concluidos,
            "por_setor": dict(por_setor),
        }

    except Exception as e:
        print("[ERRO] resumo_atendimentos:", repr(e))
        return {}

    finally:
        db.close()


def resumo_agendamentos(periodo="hoje"):
    db = SessionLocal()

    try:
        inicio, fim = periodo_datas(periodo)

        total = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.criado_em >= inicio,
            AgendamentoRevisao.criado_em <= fim
        ).count()

        agendados = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.criado_em >= inicio,
            AgendamentoRevisao.criado_em <= fim,
            AgendamentoRevisao.status == "AGENDADO"
        ).count()

        cancelados = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.criado_em >= inicio,
            AgendamentoRevisao.criado_em <= fim,
            AgendamentoRevisao.status == "CANCELADO"
        ).count()

        reagendados = db.query(AgendamentoRevisao).filter(
            AgendamentoRevisao.criado_em >= inicio,
            AgendamentoRevisao.criado_em <= fim,
            AgendamentoRevisao.status == "REAGENDADO"
        ).count()

        por_modelo = db.query(
            AgendamentoRevisao.modelo,
            func.count(AgendamentoRevisao.id)
        ).filter(
            AgendamentoRevisao.criado_em >= inicio,
            AgendamentoRevisao.criado_em <= fim
        ).group_by(
            AgendamentoRevisao.modelo
        ).all()

        por_revisao = db.query(
            AgendamentoRevisao.revisao,
            func.count(AgendamentoRevisao.id)
        ).filter(
            AgendamentoRevisao.criado_em >= inicio,
            AgendamentoRevisao.criado_em <= fim
        ).group_by(
            AgendamentoRevisao.revisao
        ).all()

        return {
            "total": total,
            "agendados": agendados,
            "cancelados": cancelados,
            "reagendados": reagendados,
            "por_modelo": dict(por_modelo),
            "por_revisao": dict(por_revisao),
        }

    except Exception as e:
        print("[ERRO] resumo_agendamentos:", repr(e))
        return {}

    finally:
        db.close()


def resumo_sances(periodo="hoje"):
    db = SessionLocal()

    try:
        inicio, fim = periodo_datas(periodo)

        dados = db.query(
            AgendamentoRevisao.sances_status,
            func.count(AgendamentoRevisao.id)
        ).filter(
            AgendamentoRevisao.criado_em >= inicio,
            AgendamentoRevisao.criado_em <= fim
        ).group_by(
            AgendamentoRevisao.sances_status
        ).all()

        return dict(dados)

    except Exception as e:
        print("[ERRO] resumo_sances:", repr(e))
        return {}

    finally:
        db.close()


def resumo_disparos(periodo="hoje"):
    db = SessionLocal()

    try:
        inicio, fim = periodo_datas(periodo)

        total = db.query(Disparo).filter(
            Disparo.criado_em >= inicio,
            Disparo.criado_em <= fim
        ).count()

        retornos = db.query(Disparo).filter(
            Disparo.criado_em >= inicio,
            Disparo.criado_em <= fim,
            Disparo.status_retorno != "AGUARDANDO"
        ).count()

        por_status = db.query(
            Disparo.status,
            func.count(Disparo.id)
        ).filter(
            Disparo.criado_em >= inicio,
            Disparo.criado_em <= fim
        ).group_by(
            Disparo.status
        ).all()

        return {
            "total": total,
            "retornos": retornos,
            "por_status": dict(por_status),
        }

    except Exception as e:
        print("[ERRO] resumo_disparos:", repr(e))
        return {}

    finally:
        db.close()


def resumo_base_conhecimento():
    db = SessionLocal()

    try:
        total = db.query(FaqRevisao).count()

        ativos = db.query(FaqRevisao).filter(
            FaqRevisao.ativo == True
        ).count()

        por_categoria = db.query(
            FaqRevisao.categoria,
            func.count(FaqRevisao.id)
        ).group_by(
            FaqRevisao.categoria
        ).all()

        return {
            "total": total,
            "ativos": ativos,
            "por_categoria": dict(por_categoria),
        }

    except Exception as e:
        print("[ERRO] resumo_base_conhecimento:", repr(e))
        return {}

    finally:
        db.close()


def gerar_resumo_gestor(periodo="hoje"):
    atendimentos = resumo_atendimentos(periodo)
    agendamentos = resumo_agendamentos(periodo)
    sances = resumo_sances(periodo)
    disparos = resumo_disparos(periodo)
    base = resumo_base_conhecimento()

    texto = f"""
📊 RESUMO DO CRM YAMAHA - {periodo.upper()}

👥 Atendimentos:
• Total: {atendimentos.get("total", 0)}
• Atendimento humano: {atendimentos.get("humano", 0)}
• Concluídos: {atendimentos.get("concluidos", 0)}

📅 Agendamentos:
• Total: {agendamentos.get("total", 0)}
• Agendados: {agendamentos.get("agendados", 0)}
• Cancelados: {agendamentos.get("cancelados", 0)}
• Reagendados: {agendamentos.get("reagendados", 0)}

🔗 Sances:
• Status: {sances}

📢 Disparos:
• Total: {disparos.get("total", 0)}
• Retornos: {disparos.get("retornos", 0)}

🧠 Base de Conhecimento:
• Perguntas cadastradas: {base.get("total", 0)}
• Ativas: {base.get("ativos", 0)}
""".strip()

    return texto


def responder_pergunta_gestor(pergunta):
    pergunta = str(pergunta or "").lower()

    periodo = "hoje"

    if "semana" in pergunta:
        periodo = "semana"
    elif "mes" in pergunta or "mês" in pergunta:
        periodo = "mes"
    elif "total" in pergunta or "geral" in pergunta:
        periodo = "total"

    if "agendamento" in pergunta:
        return resumo_agendamentos(periodo)

    if "atendimento" in pergunta:
        return resumo_atendimentos(periodo)

    if "sances" in pergunta:
        return resumo_sances(periodo)

    if "disparo" in pergunta:
        return resumo_disparos(periodo)

    if "base" in pergunta or "faq" in pergunta:
        return resumo_base_conhecimento()

    return gerar_resumo_gestor(periodo)


if __name__ == "__main__":
    print(gerar_resumo_gestor("hoje"))