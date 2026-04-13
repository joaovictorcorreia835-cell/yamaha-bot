import sqlite3

conn = sqlite3.connect("yamaha.db")
cursor = conn.cursor()

comandos = [

"ALTER TABLE agendamentos_revisao ADD COLUMN protocolo TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN observacoes TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN origem TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN lembrete_enviado BOOLEAN DEFAULT 0",
"ALTER TABLE agendamentos_revisao ADD COLUMN cancelado BOOLEAN DEFAULT 0",
"ALTER TABLE agendamentos_revisao ADD COLUMN reagendado BOOLEAN DEFAULT 0",
"ALTER TABLE agendamentos_revisao ADD COLUMN codigo_sistema TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN sincronizado BOOLEAN DEFAULT 0",
"ALTER TABLE agendamentos_revisao ADD COLUMN atualizado_em DATETIME"

]

for comando in comandos:
    try:
        cursor.execute(comando)
        print("OK:", comando)
    except Exception:
        print("Já existe:", comando)

conn.commit()
conn.close()

print("Banco Agendamento atualizado")