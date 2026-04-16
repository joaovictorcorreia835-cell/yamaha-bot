from database import engine
from sqlalchemy import text

def executar(conn, sql, nome_coluna):
    try:
        conn.execute(text(sql))
        print(f"{nome_coluna} criada")
    except Exception:
        print(f"{nome_coluna} já existe")

def migrar():
    with engine.connect() as conn:
        # ==========================================
        # AGENDAMENTOS_REVISAO - CAMPOS SANCES
        # ==========================================
        executar(
            conn,
            "ALTER TABLE agendamentos_revisao ADD COLUMN sances_status VARCHAR(50) DEFAULT 'PENDENTE';",
            "agendamentos_revisao.sances_status"
        )

        executar(
            conn,
            "ALTER TABLE agendamentos_revisao ADD COLUMN sances_enviado BOOLEAN DEFAULT FALSE;",
            "agendamentos_revisao.sances_enviado"
        )

        executar(
            conn,
            "ALTER TABLE agendamentos_revisao ADD COLUMN sances_protocolo VARCHAR(255) DEFAULT '';",
            "agendamentos_revisao.sances_protocolo"
        )

        executar(
            conn,
            "ALTER TABLE agendamentos_revisao ADD COLUMN sances_erro TEXT DEFAULT '';",
            "agendamentos_revisao.sances_erro"
        )

        executar(
            conn,
            "ALTER TABLE agendamentos_revisao ADD COLUMN sances_data_envio TIMESTAMP NULL;",
            "agendamentos_revisao.sances_data_envio"
        )

        executar(
            conn,
            "ALTER TABLE agendamentos_revisao ADD COLUMN sances_tentativas INTEGER DEFAULT 0;",
            "agendamentos_revisao.sances_tentativas"
        )

        executar(
            conn,
            "ALTER TABLE agendamentos_revisao ADD COLUMN sances_ultima_tentativa TIMESTAMP NULL;",
            "agendamentos_revisao.sances_ultima_tentativa"
        )

        executar(
            conn,
            "ALTER TABLE agendamentos_revisao ADD COLUMN sances_ultimo_retorno TEXT DEFAULT '';",
            "agendamentos_revisao.sances_ultimo_retorno"
        )

        # ==========================================
        # ATENDIMENTOS - CAMPOS FOLLOW-UP
        # ==========================================
        executar(
            conn,
            "ALTER TABLE atendimentos ADD COLUMN followup_1 BOOLEAN DEFAULT FALSE;",
            "atendimentos.followup_1"
        )

        executar(
            conn,
            "ALTER TABLE atendimentos ADD COLUMN followup_2 BOOLEAN DEFAULT FALSE;",
            "atendimentos.followup_2"
        )

        executar(
            conn,
            "ALTER TABLE atendimentos ADD COLUMN followup_3 BOOLEAN DEFAULT FALSE;",
            "atendimentos.followup_3"
        )

        conn.commit()

    print("✅ MIGRAÇÃO COMPLETA CONCLUÍDA")

if __name__ == "__main__":
    migrar()