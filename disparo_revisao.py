import os
import time
import re
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

# ==========================================
# CONFIG
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha.db")

URL_ENVIO = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

ARQUIVO_PLANILHA = "clientes.xlsx"
INTERVALO_ENTRE_ENVIOS = 15

# ==========================================
# BANCO DE DADOS
# ==========================================
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Atendimento(Base):
    __tablename__ = "atendimentos"

    id = Column(Integer, primary_key=True, index=True)
    telefone = Column(String(30))
    nome = Column(String(150))
    setor = Column(String(50))
    modelo = Column(String(100))
    ano_modelo = Column(String(20))
    revisao = Column(String(50))
    data_agendamento = Column(String(20))
    horario_agendamento = Column(String(20))
    atendimento_humano = Column(String(10), default="não")
    origem = Column(String(50))
    item_adicional = Column(String(500))
    status = Column(String(100), default="aberto")
    criado_em = Column(DateTime, default=datetime.now)


Base.metadata.create_all(bind=engine)

# ==========================================
# UTILITÁRIOS
# ==========================================
def normalizar_telefone(valor):
    if pd.isna(valor):
        return ""
    return re.sub(r"\D", "", str(valor))


def validar_colunas(df):
    colunas = {str(c).strip().lower(): c for c in df.columns}

    obrigatorias = ["telefone", "nome", "modelo", "periodo"]
    faltando = [c for c in obrigatorias if c not in colunas]

    if faltando:
        raise ValueError(
            f"Faltam colunas obrigatórias: {', '.join(faltando)}"
        )

    return {
        "telefone": colunas["telefone"],
        "nome": colunas["nome"],
        "modelo": colunas["modelo"],
        "periodo": colunas["periodo"],
        "status": colunas["status"] if "status" in colunas else None,
        "data": colunas["data"] if "data" in colunas else None,
    }


def criar_mensagem(nome, modelo, periodo):
    return f"""Olá {nome} 👋

Aqui é da *Equipe Motoshow Yamaha* 🏍️

Sua *{modelo}* está no período da revisão de *{periodo}* meses.

🎯 *Campanha Especial Pós-Vendas:*

✔ Peças Originais Yamaha
✔ Atendimento especializado
✔ Condições especiais para sua revisão

Digite uma opção para continuar:

*1* - Agendar revisão
*2* - Consultar valores
*3* - Falar com atendente

Equipe *Motoshow Yamaha*.
"""


def enviar_mensagem(telefone, mensagem):
    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "phone": telefone,
        "message": mensagem
    }

    try:
        resposta = requests.post(
            URL_ENVIO,
            json=payload,
            headers=headers,
            timeout=30
        )
        print(f"[ENVIO] {telefone} -> {resposta.status_code}")
        print(resposta.text)
        return resposta.status_code in [200, 201]
    except Exception as e:
        print(f"[ERRO ENVIO] {telefone}: {e}")
        return False


def registrar_campanha(db, telefone, nome="", modelo="", periodo=""):
    try:
        registro = (
            db.query(Atendimento)
            .filter(
                Atendimento.telefone == telefone,
                Atendimento.status == "aguardando_campanha"
            )
            .order_by(Atendimento.id.desc())
            .first()
        )

        item_info = f"Campanha revisão {periodo} meses"

        if registro:
            registro.nome = nome or registro.nome
            registro.modelo = modelo or registro.modelo
            registro.setor = "Revisão"
            registro.origem = "campanha"
            registro.atendimento_humano = "não"
            registro.item_adicional = item_info
            registro.status = "aguardando_campanha"
            db.commit()
            return

        novo = Atendimento(
            telefone=telefone,
            nome=nome,
            setor="Revisão",
            modelo=modelo,
            atendimento_humano="não",
            origem="campanha",
            item_adicional=item_info,
            status="aguardando_campanha"
        )
        db.add(novo)
        db.commit()

    except Exception as e:
        db.rollback()
        print(f"[ERRO BANCO] {telefone}: {e}")


# ==========================================
# PROCESSAMENTO DA PLANILHA
# ==========================================
def processar_planilha():
    if not os.path.exists(ARQUIVO_PLANILHA):
        print(f"[ERRO] Arquivo não encontrado: {ARQUIVO_PLANILHA}")
        return

    try:
        df = pd.read_excel(ARQUIVO_PLANILHA)
    except Exception as e:
        print(f"[ERRO] Falha ao ler planilha: {e}")
        return

    if df.empty:
        print("[INFO] A planilha está vazia.")
        return

    try:
        cols = validar_colunas(df)
    except Exception as e:
        print(f"[ERRO] {e}")
        return

    db = SessionLocal()

    enviados = 0
    erros = 0
    ignorados = 0

    try:
        for i, row in df.iterrows():
            telefone = normalizar_telefone(row[cols["telefone"]])
            nome = str(row[cols["nome"]]).strip() if pd.notna(row[cols["nome"]]) else ""
            modelo = str(row[cols["modelo"]]).strip() if pd.notna(row[cols["modelo"]]) else ""
            periodo = str(row[cols["periodo"]]).strip() if pd.notna(row[cols["periodo"]]) else ""

            status_atual = ""
            if cols["status"]:
                status_atual = str(row[cols["status"]]).strip().upper() if pd.notna(row[cols["status"]]) else ""

            if status_atual == "ENVIADO":
                ignorados += 1
                continue

            if not telefone:
                print(f"[IGNORADO] Linha {i + 2}: telefone inválido.")
                ignorados += 1
                continue

            mensagem = criar_mensagem(nome, modelo, periodo)
            sucesso = enviar_mensagem(telefone, mensagem)

            if sucesso:
                registrar_campanha(
                    db=db,
                    telefone=telefone,
                    nome=nome,
                    modelo=modelo,
                    periodo=periodo
                )

                if cols["status"]:
                    df.at[i, cols["status"]] = "ENVIADO"
                if cols["data"]:
                    df.at[i, cols["data"]] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

                enviados += 1
            else:
                erros += 1

            time.sleep(INTERVALO_ENTRE_ENVIOS)

    finally:
        db.close()

    try:
        df.to_excel(ARQUIVO_PLANILHA, index=False)
    except Exception as e:
        print(f"[ERRO] Não foi possível salvar atualização na planilha: {e}")

    print("\n===== RESUMO DO DISPARO =====")
    print(f"Enviados com sucesso: {enviados}")
    print(f"Com erro: {erros}")
    print(f"Ignorados: {ignorados}")
    print("=============================\n")


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    processar_planilha()