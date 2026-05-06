from dotenv import load_dotenv
load_dotenv()

from database import engine
from sqlalchemy import text
import os


def executar_sql(conn, sql):
    try:
        conn.execute(text(sql))
        print("✅ OK:", sql)

    except Exception as e:
        print("❌ ERRO:", sql)
        print("➡", repr(e))


def migrar():
    print("===================================")
    print("🚀 INICIANDO MIGRAÇÃO")
    print("===================================")

    print("DATABASE_URL:")
    print(os.getenv("DATABASE_URL"))

    comandos = [

        # ==========================================
        # AGENDAMENTOS_REVISAO
        # ==========================================
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_status VARCHAR(50) DEFAULT 'PENDENTE';",

        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_enviado BOOLEAN DEFAULT FALSE;",

        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_protocolo VARCHAR(255) DEFAULT '';",

        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_erro TEXT DEFAULT '';",

        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_data_envio TIMESTAMP NULL;",

        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_tentativas INTEGER DEFAULT 0;",

        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_ultima_tentativa TIMESTAMP NULL;",

        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_ultimo_retorno TEXT DEFAULT '';",


        # ==========================================
        # ATENDIMENTOS
        # ==========================================
        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_1 BOOLEAN DEFAULT FALSE;",

        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_2 BOOLEAN DEFAULT FALSE;",

        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_3 BOOLEAN DEFAULT FALSE;",

        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_respondido BOOLEAN DEFAULT FALSE;",

        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_recuperado BOOLEAN DEFAULT FALSE;",

        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS ultima_mensagem_cliente TIMESTAMP NULL;",

        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS observacao TEXT;",

        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS observacoes TEXT;",


        # ==========================================
        # AGENDAMENTOS - OBSERVAÇÕES
        # ==========================================
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS observacoes TEXT;",


        # ==========================================
        # LEADS ATACADO
        # ==========================================
        "ALTER TABLE leads_atacado ADD COLUMN IF NOT EXISTS interesse TEXT;",


        # ==========================================
        # DISPAROS
        # ==========================================
        "ALTER TABLE disparos ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'pendente';",

    ]

    with engine.begin() as conn:

        for sql in comandos:
            executar_sql(conn, sql)

    print("===================================")
    print("✅ MIGRAÇÃO COMPLETA CONCLUÍDA")
    print("===================================")


if __name__ == "__main__":
    migrar()