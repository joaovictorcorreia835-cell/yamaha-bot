from dotenv import load_dotenv
load_dotenv()

from database import engine
from sqlalchemy import text
import os

def migrar():
    print("DATABASE_URL:", os.getenv("DATABASE_URL"))

    comandos = [
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_status VARCHAR(50) DEFAULT 'PENDENTE';",
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_enviado BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_protocolo VARCHAR(255) DEFAULT '';",
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_erro TEXT DEFAULT '';",
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_data_envio TIMESTAMP NULL;",
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_tentativas INTEGER DEFAULT 0;",
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_ultima_tentativa TIMESTAMP NULL;",
        "ALTER TABLE agendamentos_revisao ADD COLUMN IF NOT EXISTS sances_ultimo_retorno TEXT DEFAULT '';",
        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_1 BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_2 BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE atendimentos ADD COLUMN IF NOT EXISTS followup_3 BOOLEAN DEFAULT FALSE;",
    ]

    with engine.begin() as conn:
        for sql in comandos:
            conn.execute(text(sql))

    print("✅ MIGRAÇÃO COMPLETA CONCLUÍDA")

if __name__ == "__main__":
    migrar()