from database import engine
from sqlalchemy import text

def migrar():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE agendamentos_revisao ADD COLUMN sances_status VARCHAR(50) DEFAULT 'PENDENTE';"))
        except:
            print("sances_status já existe")

        try:
            conn.execute(text("ALTER TABLE agendamentos_revisao ADD COLUMN sances_enviado BOOLEAN DEFAULT FALSE;"))
        except:
            print("sances_enviado já existe")

        try:
            conn.execute(text("ALTER TABLE agendamentos_revisao ADD COLUMN sances_protocolo VARCHAR(255) DEFAULT '';"))
        except:
            print("sances_protocolo já existe")

        try:
            conn.execute(text("ALTER TABLE agendamentos_revisao ADD COLUMN sances_erro TEXT DEFAULT '';"))
        except:
            print("sances_erro já existe")

        try:
            conn.execute(text("ALTER TABLE agendamentos_revisao ADD COLUMN sances_data_envio TIMESTAMP NULL;"))
        except:
            print("sances_data_envio já existe")

        conn.commit()

    print("✅ MIGRAÇÃO CONCLUÍDA")

if __name__ == "__main__":
    migrar()