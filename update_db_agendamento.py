import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    pool_pre_ping=True
)

comandos = [
    "ALTER TABLE agendamentos_revisao ADD COLUMN km_atual TEXT",
    "ALTER TABLE agendamentos_revisao ADD COLUMN tipo_atendimento TEXT",
    "ALTER TABLE agendamentos_revisao ADD COLUMN observacoes TEXT",
    "ALTER TABLE agendamentos_revisao ADD COLUMN origem TEXT",
    "ALTER TABLE agendamentos_revisao ADD COLUMN lembrete_enviado BOOLEAN DEFAULT 0",
    "ALTER TABLE agendamentos_revisao ADD COLUMN cancelado BOOLEAN DEFAULT 0",
    "ALTER TABLE agendamentos_revisao ADD COLUMN reagendado BOOLEAN DEFAULT 0",
    "ALTER TABLE agendamentos_revisao ADD COLUMN codigo_sistema TEXT",
    "ALTER TABLE agendamentos_revisao ADD COLUMN sincronizado BOOLEAN DEFAULT 0"
]

with engine.begin() as conn:
    for comando in comandos:
        try:
            conn.execute(text(comando))
            print("OK:", comando)
        except Exception as e:
            print("Já existe ou erro:", comando, "-", e)

print("Banco Agendamento atualizado com sucesso")