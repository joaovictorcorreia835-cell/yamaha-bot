import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

comandos = [

"ALTER TABLE agendamentos_revisao ADD COLUMN km_atual TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN tipo_atendimento TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN cancelado BOOLEAN DEFAULT FALSE",
"ALTER TABLE agendamentos_revisao ADD COLUMN reagendado BOOLEAN DEFAULT FALSE",
"ALTER TABLE agendamentos_revisao ADD COLUMN codigo_sistema TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN sincronizado BOOLEAN DEFAULT FALSE"

]

with engine.begin() as conn:
    for comando in comandos:
        try:
            conn.execute(text(comando))
            print("OK:", comando)
        except Exception as e:
            print("Já existe:", comando)

print("Banco atualizado")