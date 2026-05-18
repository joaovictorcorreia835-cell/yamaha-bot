from dotenv import load_dotenv
load_dotenv()

import os
from sqlalchemy import text
from database import engine


def executar_sql(conn, sql):
    try:
        conn.execute(text(sql))
        print("✅ OK:", sql)

    except Exception as e:
        print("❌ ERRO:", sql)
        print("➡", repr(e))


def tabela_existe(conn, tabela):
    try:
        resultado = conn.execute(
            text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = :tabela
                );
            """),
            {"tabela": tabela}
        ).scalar()

        return bool(resultado)

    except Exception:
        return False


def migrar():
    print("===================================")
    print("🚀 INICIANDO MIGRAÇÃO")
    print("===================================")

    database_url = os.getenv("DATABASE_URL", "")
    print("DATABASE_URL:")
    print(database_url[:60] + "..." if database_url else "NÃO CONFIGURADA")

    with engine.begin() as conn:

        # ==========================================
        # AGENDAMENTOS_REVISAO
        # ==========================================
        if tabela_existe(conn, "agendamentos_revisao"):
            comandos_agendamentos = [
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_status VARCHAR(50) DEFAULT 'PENDENTE';",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_enviado BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_protocolo VARCHAR(255) DEFAULT '';",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_erro TEXT DEFAULT '';",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_data_envio TIMESTAMP NULL;",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_tentativas INTEGER DEFAULT 0;",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_ultima_tentativa TIMESTAMP NULL;",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_ultimo_retorno TEXT DEFAULT '';",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS observacoes TEXT;",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS km_atual VARCHAR(50);",
                "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS tipo_atendimento VARCHAR(100);",
            ]

            for sql in comandos_agendamentos:
                executar_sql(conn, sql)
        else:
            print("⚠️ Tabela agendamentos_revisao não existe. Ignorando.")

        # ==========================================
        # ATENDIMENTOS
        # ==========================================
        if tabela_existe(conn, "atendimentos"):
            comandos_atendimentos = [
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_1 BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_2 BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_3 BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_respondido BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_recuperado BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS ultima_mensagem_cliente TEXT;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS observacao TEXT;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS observacoes TEXT;",

                # IA COMERCIAL / FASE 1
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS temperatura_lead VARCHAR(50);",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS cliente_recuperado BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_nivel INTEGER DEFAULT 0;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS ultima_acao_ia TEXT;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS valor_estimado NUMERIC(10,2);",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS origem_ia TEXT;",

                # FASE 2 - IA DÚVIDAS / MANUAIS
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS assunto_ia VARCHAR(100);",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS fonte_ia VARCHAR(100);",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS modelo_ia VARCHAR(100);",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS pergunta_ia TEXT;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS resposta_ia TEXT;",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS confianca_ia VARCHAR(50);",
                "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS tipo_mensagem VARCHAR(50);",
            ]

            for sql in comandos_atendimentos:
                executar_sql(conn, sql)
        else:
            print("⚠️ Tabela atendimentos não existe. Ignorando.")

        # ==========================================
        # LEADS_ATACADO
        # ==========================================
        if tabela_existe(conn, "leads_atacado"):
            comandos_leads = [
                "ALTER TABLE leads_atacado ADD COLUMN IF NOT EXISTS interesse TEXT;",
                "ALTER TABLE leads_atacado ADD COLUMN IF NOT EXISTS temperatura_lead VARCHAR(50);",
                "ALTER TABLE leads_atacado ADD COLUMN IF NOT EXISTS ultima_acao_ia TEXT;",
                "ALTER TABLE leads_atacado ADD COLUMN IF NOT EXISTS catalogo_enviado BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE leads_atacado ADD COLUMN IF NOT EXISTS data_catalogo_enviado TIMESTAMP NULL;",
            ]

            for sql in comandos_leads:
                executar_sql(conn, sql)
        else:
            print("⚠️ Tabela leads_atacado não existe. Ignorando.")

        # ==========================================
        # DISPAROS
        # ==========================================
        if tabela_existe(conn, "disparos"):
            comandos_disparos = [
                "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'PENDENTE';",
                "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS status_retorno VARCHAR(50) DEFAULT 'AGUARDANDO';",
                "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS button_id VARCHAR(100);",
                "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS id_envio_zapi VARCHAR(255);",
                "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS intencao_ia VARCHAR(100);",
                "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS proxima_acao VARCHAR(100);",
                "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS nivel_interesse VARCHAR(50);",
                "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS catalogo_enviado BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS data_catalogo_enviado TIMESTAMP NULL;",
            ]

            for sql in comandos_disparos:
                executar_sql(conn, sql)
        else:
            print("⚠️ Tabela disparos não existe. Ignorando.")

    print("===================================")
    print("✅ MIGRAÇÃO COMPLETA CONCLUÍDA")
    print("===================================")


if __name__ == "__main__":
    migrar()
