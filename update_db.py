import sqlite3

conn = sqlite3.connect("yamaha.db")
cursor = conn.cursor()

comandos = [

"ALTER TABLE atendimentos ADD COLUMN cpf TEXT",
"ALTER TABLE atendimentos ADD COLUMN dia_semana TEXT",
"ALTER TABLE atendimentos ADD COLUMN data_agendada TEXT",
"ALTER TABLE atendimentos ADD COLUMN itens TEXT",
"ALTER TABLE atendimentos ADD COLUMN venda_adicional TEXT",
"ALTER TABLE atendimentos ADD COLUMN etapa TEXT",
"ALTER TABLE atendimentos ADD COLUMN concluido BOOLEAN DEFAULT 0",
"ALTER TABLE atendimentos ADD COLUMN ultima_interacao DATETIME"

]

for comando in comandos:
    try:
        cursor.execute(comando)
        print("OK:", comando)
    except Exception as e:
        print("Já existe:", comando)

conn.commit()
conn.close()

print("Banco atualizado com sucesso")