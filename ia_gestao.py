# ==========================================
# IA DE GESTÃO - YAMAHA BOT / CRM
# Consulta dados do banco e gera resumos
# ==========================================

from datetime import datetime, timedelta
from sqlalchemy import func

from database import SessionLocal, Atendimento, AgendamentoRevisao

try:
    from database import FaqRevisao
except Exception:
    FaqRevisao = None

try:
    from database import Disparo
except Exception:
    Disparo = None

try:
    from database import LeadAtacado
except Exception:
    LeadAtacado = None


# ==========================================
# APOIO
# ==========================================
def log_erro(*args):
    print("[IA GESTÃO][ERRO]", *args, flush=True)


def normalizar_status(valor):
    return str(valor or "").strip().upper()


def periodo_datas(periodo="hoje"):
    hoje = datetime.now()
    periodo = str(periodo or "hoje").lower().strip()

    if periodo == "hoje":
        inicio = hoje.replace(hour=0, minute=0, second=0, microsecond=0)

    elif periodo == "semana":
        inicio = hoje - timedelta(days=7)

    elif periodo == "mes":
        inicio = hoje - timedelta(days=30)

    elif periodo in ["total", "geral", "todos"]:
        inicio = hoje - timedelta(days=3650)

    else:
        inicio = hoje.replace(hour=0, minute=0, second=0, microsecond=0)

    return inicio, hoje


def campo_existe(modelo, campo):
    try:
        return hasattr(modelo, campo)
    except Exception:
        return False


def aplicar_filtro_data(query, modelo, inicio, fim):
    try:
        if campo_existe(modelo, "data"):
            return query.filter(
                modelo.data >= inicio,
                modelo.data <= fim,
            )

        if campo_existe(modelo, "criado_em"):
            return query.filter(
                modelo.criado_em >= inicio,
                modelo.criado_em <= fim,
            )

        if campo_existe(modelo, "created_at"):
            return query.filter(
                modelo.created_at >= inicio,
                modelo.created_at <= fim,
            )

        return query

    except Exception as e:
        log_erro("Erro ao aplicar filtro de data:", repr(e))
        return query


def safe_dict(lista):
    resultado = {}

    try:
        for chave, valor in lista:
            chave = str(chave or "Não informado").strip()
            resultado[chave] = int(valor or 0)
    except Exception:
        pass

    return resultado


# ==========================================
# RESUMO ATENDIMENTOS
# ==========================================
def resumo_atendimentos(periodo="hoje"):
    db = SessionLocal()

    try:
        inicio, fim = periodo_datas(periodo)

        query = db.query(Atendimento)
        query = aplicar_filtro_data(query, Atendimento, inicio, fim)

        total = query.count()

        humano = 0
        concluídos = 0

        try:
            humano = query.filter(Atendimento.atendimento_humano == True).count()
        except Exception:
            humano = 0

        try:
            concluídos = query.filter(Atendimento.concluido == True).count()
        except Exception:
            concluídos = 0

        por_setor = {}

        try:
            query_setor = db.query(
                Atendimento.setor,
                func.count(Atendimento.id),
            )

            query_setor = aplicar_filtro_data(
                query_setor,
                Atendimento,
                inicio,
                fim,
            )

            por_setor = safe_dict(
                query_setor.group_by(Atendimento.setor).all()
            )

        except Exception as e:
            log_erro("Erro por_setor:", repr(e))

        return {
            "total": total,
            "humano": humano,
            "concluidos": concluídos,
            "por_setor": por_setor,
        }

    except Exception as e:
        log_erro("resumo_atendimentos:", repr(e))
        return {
            "total": 0,
            "humano": 0,
            "concluidos": 0,
            "por_setor": {},
        }

    finally:
        db.close()


# ==========================================
# RESUMO AGENDAMENTOS
# ==========================================
def resumo_agendamentos(periodo="hoje"):
    db = SessionLocal()

    try:
        inicio, fim = periodo_datas(periodo)

        query = db.query(AgendamentoRevisao)
        query = aplicar_filtro_data(query, AgendamentoRevisao, inicio, fim)

        total = query.count()

        agendados = 0
        cancelados = 0
        reagendados = 0
        confirmados = 0
        finalizados = 0

        try:
            agendados = query.filter(
                func.upper(AgendamentoRevisao.status) == "AGENDADO"
            ).count()

            cancelados = query.filter(
                func.upper(AgendamentoRevisao.status) == "CANCELADO"
            ).count()

            reagendados = query.filter(
                func.upper(AgendamentoRevisao.status) == "REAGENDADO"
            ).count()

            confirmados = query.filter(
                func.upper(AgendamentoRevisao.status) == "CONFIRMADO"
            ).count()

            finalizados = query.filter(
                func.upper(AgendamentoRevisao.status).in_([
                    "FINALIZADO",
                    "CONCLUIDO",
                    "CONCLUÍDO",
                ])
            ).count()

        except Exception as e:
            log_erro("Erro status agendamento:", repr(e))

        por_modelo = {}
        por_revisao = {}

        try:
            query_modelo = db.query(
                AgendamentoRevisao.modelo,
                func.count(AgendamentoRevisao.id),
            )

            query_modelo = aplicar_filtro_data(
                query_modelo,
                AgendamentoRevisao,
                inicio,
                fim,
            )

            por_modelo = safe_dict(
                query_modelo.group_by(AgendamentoRevisao.modelo).all()
            )

        except Exception as e:
            log_erro("Erro por_modelo:", repr(e))

        try:
            query_revisao = db.query(
                AgendamentoRevisao.revisao,
                func.count(AgendamentoRevisao.id),
            )

            query_revisao = aplicar_filtro_data(
                query_revisao,
                AgendamentoRevisao,
                inicio,
                fim,
            )

            por_revisao = safe_dict(
                query_revisao.group_by(AgendamentoRevisao.revisao).all()
            )

        except Exception as e:
            log_erro("Erro por_revisao:", repr(e))

        taxa_cancelamento = 0
        taxa_conversao = 0

        try:
            if total > 0:
                taxa_cancelamento = round((cancelados / total) * 100, 1)
                taxa_conversao = round((agendados / total) * 100, 1)
        except Exception:
            pass

        return {
            "total": total,
            "agendados": agendados,
            "cancelados": cancelados,
            "reagendados": reagendados,
            "confirmados": confirmados,
            "finalizados": finalizados,
            "por_modelo": por_modelo,
            "por_revisao": por_revisao,
            "taxa_cancelamento": taxa_cancelamento,
            "taxa_conversao": taxa_conversao,
        }

    except Exception as e:
        log_erro("resumo_agendamentos:", repr(e))
        return {
            "total": 0,
            "agendados": 0,
            "cancelados": 0,
            "reagendados": 0,
            "confirmados": 0,
            "finalizados": 0,
            "por_modelo": {},
            "por_revisao": {},
            "taxa_cancelamento": 0,
            "taxa_conversao": 0,
        }

    finally:
        db.close()


# ==========================================
# RESUMO SANCES
# ==========================================
def resumo_sances(periodo="hoje"):
    db = SessionLocal()

    try:
        if not campo_existe(AgendamentoRevisao, "sances_status"):
            return {}

        inicio, fim = periodo_datas(periodo)

        query = db.query(
            AgendamentoRevisao.sances_status,
            func.count(AgendamentoRevisao.id),
        )

        query = aplicar_filtro_data(
            query,
            AgendamentoRevisao,
            inicio,
            fim,
        )

        dados = query.group_by(
            AgendamentoRevisao.sances_status
        ).all()

        return safe_dict(dados)

    except Exception as e:
        log_erro("resumo_sances:", repr(e))
        return {}

    finally:
        db.close()


# ==========================================
# RESUMO DISPAROS
# ==========================================
def resumo_disparos(periodo="hoje"):
    if Disparo is None:
        return {
            "total": 0,
            "retornos": 0,
            "por_status": {},
        }

    db = SessionLocal()

    try:
        inicio, fim = periodo_datas(periodo)

        query = db.query(Disparo)
        query = aplicar_filtro_data(query, Disparo, inicio, fim)

        total = query.count()
        retornos = 0

        try:
            if campo_existe(Disparo, "status_retorno"):
                retornos = query.filter(
                    Disparo.status_retorno != "AGUARDANDO"
                ).count()
        except Exception:
            retornos = 0

        por_status = {}

        try:
            if campo_existe(Disparo, "status"):
                query_status = db.query(
                    Disparo.status,
                    func.count(Disparo.id),
                )

                query_status = aplicar_filtro_data(
                    query_status,
                    Disparo,
                    inicio,
                    fim,
                )

                por_status = safe_dict(
                    query_status.group_by(Disparo.status).all()
                )

        except Exception as e:
            log_erro("Erro por_status disparo:", repr(e))

        return {
            "total": total,
            "retornos": retornos,
            "por_status": por_status,
        }

    except Exception as e:
        log_erro("resumo_disparos:", repr(e))
        return {
            "total": 0,
            "retornos": 0,
            "por_status": {},
        }

    finally:
        db.close()


# ==========================================
# RESUMO LEADS ATACADO
# ==========================================
def resumo_leads_atacado(periodo="hoje"):
    if LeadAtacado is None:
        return {
            "total": 0,
            "por_interesse": {},
        }

    db = SessionLocal()

    try:
        inicio, fim = periodo_datas(periodo)

        query = db.query(LeadAtacado)
        query = aplicar_filtro_data(query, LeadAtacado, inicio, fim)

        total = query.count()
        por_interesse = {}

        try:
            if campo_existe(LeadAtacado, "interesse"):
                query_interesse = db.query(
                    LeadAtacado.interesse,
                    func.count(LeadAtacado.id),
                )

                query_interesse = aplicar_filtro_data(
                    query_interesse,
                    LeadAtacado,
                    inicio,
                    fim,
                )

                por_interesse = safe_dict(
                    query_interesse.group_by(LeadAtacado.interesse).all()
                )

        except Exception as e:
            log_erro("Erro por_interesse atacado:", repr(e))

        return {
            "total": total,
            "por_interesse": por_interesse,
        }

    except Exception as e:
        log_erro("resumo_leads_atacado:", repr(e))
        return {
            "total": 0,
            "por_interesse": {},
        }

    finally:
        db.close()


# ==========================================
# BASE DE CONHECIMENTO
# ==========================================
def resumo_base_conhecimento():
    if FaqRevisao is None:
        return {
            "total": 0,
            "ativos": 0,
            "por_categoria": {},
        }

    db = SessionLocal()

    try:
        total = db.query(FaqRevisao).count()

        ativos = 0

        try:
            ativos = db.query(FaqRevisao).filter(
                FaqRevisao.ativo == True
            ).count()
        except Exception:
            ativos = total

        por_categoria = {}

        try:
            por_categoria = safe_dict(
                db.query(
                    FaqRevisao.categoria,
                    func.count(FaqRevisao.id),
                )
                .group_by(FaqRevisao.categoria)
                .all()
            )
        except Exception as e:
            log_erro("Erro por_categoria FAQ:", repr(e))

        return {
            "total": total,
            "ativos": ativos,
            "por_categoria": por_categoria,
        }

    except Exception as e:
        log_erro("resumo_base_conhecimento:", repr(e))
        return {
            "total": 0,
            "ativos": 0,
            "por_categoria": {},
        }

    finally:
        db.close()


# ==========================================
# TEXTO PARA GESTOR
# ==========================================
def gerar_resumo_gestor(periodo="hoje"):
    atendimentos = resumo_atendimentos(periodo)
    agendamentos = resumo_agendamentos(periodo)
    sances = resumo_sances(periodo)
    disparos = resumo_disparos(periodo)
    atacado = resumo_leads_atacado(periodo)
    base = resumo_base_conhecimento()

    texto = f"""
📊 *RESUMO DO CRM YAMAHA - {str(periodo).upper()}*

👥 *Atendimentos*
• Total: {atendimentos.get("total", 0)}
• Atendimento humano: {atendimentos.get("humano", 0)}
• Concluídos: {atendimentos.get("concluidos", 0)}
• Por setor: {atendimentos.get("por_setor", {})}

📅 *Agendamentos*
• Total: {agendamentos.get("total", 0)}
• Agendados: {agendamentos.get("agendados", 0)}
• Confirmados: {agendamentos.get("confirmados", 0)}
• Finalizados: {agendamentos.get("finalizados", 0)}
• Cancelados: {agendamentos.get("cancelados", 0)}
• Reagendados: {agendamentos.get("reagendados", 0)}
• Taxa de conversão: {agendamentos.get("taxa_conversao", 0)}%
• Taxa de cancelamento: {agendamentos.get("taxa_cancelamento", 0)}%
• Por modelo: {agendamentos.get("por_modelo", {})}
• Por revisão: {agendamentos.get("por_revisao", {})}

🔗 *Sances*
• Status: {sances}

📢 *Disparos*
• Total: {disparos.get("total", 0)}
• Retornos: {disparos.get("retornos", 0)}
• Por status: {disparos.get("por_status", {})}

📦 *Atacado*
• Leads: {atacado.get("total", 0)}
• Interesse: {atacado.get("por_interesse", {})}

🧠 *Base de Conhecimento*
• Perguntas cadastradas: {base.get("total", 0)}
• Ativas: {base.get("ativos", 0)}
• Categorias: {base.get("por_categoria", {})}
""".strip()

    return texto


# ==========================================
# PERGUNTAS DO GESTOR
# ==========================================
def responder_pergunta_gestor(pergunta):
    pergunta = str(pergunta or "").lower().strip()

    periodo = "hoje"

    if "semana" in pergunta:
        periodo = "semana"
    elif "mes" in pergunta or "mês" in pergunta:
        periodo = "mes"
    elif "total" in pergunta or "geral" in pergunta or "todos" in pergunta:
        periodo = "total"

    if "agendamento" in pergunta or "agenda" in pergunta:
        return resumo_agendamentos(periodo)

    if "atendimento" in pergunta or "cliente" in pergunta:
        return resumo_atendimentos(periodo)

    if "sances" in pergunta:
        return resumo_sances(periodo)

    if "disparo" in pergunta or "campanha" in pergunta:
        return resumo_disparos(periodo)

    if "atacado" in pergunta or "lead" in pergunta or "lojista" in pergunta:
        return resumo_leads_atacado(periodo)

    if "base" in pergunta or "faq" in pergunta or "conhecimento" in pergunta:
        return resumo_base_conhecimento()

    return gerar_resumo_gestor(periodo)


if __name__ == "__main__":
    print(gerar_resumo_gestor("hoje"))