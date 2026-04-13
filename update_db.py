import sqlite3

conn = sqlite3.connect("yamaha.db")
cursor = conn.cursor()

comandos = [

# ==========================================
# ATENDIMENTOS
# ==========================================
"ALTER TABLE atendimentos ADD COLUMN cpf TEXT",
"ALTER TABLE atendimentos ADD COLUMN dia_semana TEXT",
"ALTER TABLE atendimentos ADD COLUMN data_agendada TEXT",
"ALTER TABLE atendimentos ADD COLUMN itens TEXT",
"ALTER TABLE atendimentos ADD COLUMN venda_adicional TEXT",
"ALTER TABLE atendimentos ADD COLUMN etapa TEXT",
"ALTER TABLE atendimentos ADD COLUMN concluido BOOLEAN DEFAULT 0",
"ALTER TABLE atendimentos ADD COLUMN ultima_interacao DATETIME",

# NOVOS CAMPOS
"ALTER TABLE atendimentos ADD COLUMN km_atual TEXT",
"ALTER TABLE atendimentos ADD COLUMN tipo_atendimento TEXT",
"ALTER TABLE atendimentos ADD COLUMN observacoes TEXT",

# ==========================================
# AGENDAMENTOS REVISAO
# ==========================================
"ALTER TABLE agendamentos_revisao ADD COLUMN km_atual TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN tipo_atendimento TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN observacoes TEXT",
"ALTER TABLE agendamentos_revisao ADD COLUMN sincronizado BOOLEAN DEFAULT 0",
"ALTER TABLE agendamentos_revisao ADD COLUMN codigo_sistema TEXT",

]

for comando in comandos:
    try:
        cursor.execute(comando)
        print("OK:", comando)
    except Exception:
        print("Já existe:", comando)

conn.commit()
conn.close()

print("Banco atualizado com sucesso")