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
INTERVALO_ENTRE_ENVIOS = 15  # segundos

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
def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = {
            "etapa": "menu",
            "ultima_interacao": time.time(),
            "nome": "",
            "modelo": "",
            "ano_modelo": "",
            "revisao": "",
            "revisao_opcao": "",
            "data_agendamento": "",
            "dia_semana_opcao": "",
            "horario_agendamento": "",
            "setor": "",
            "origem": "menu normal",
            "atendimento_humano": False,
            "item_adicional": "",
            "cpf": "",
            "km_atual": "",
            "descricao_garantia": "",
            "garantia_opcao": "",
            "peca_nome": "",
            "cor_moto": "",
            "acessorio_nome": "",
            "empresa": "",
            "cnpj": "",
            "cidade": "",
            "responsavel": "",
            "telefone_empresa": "",
            "descricao_solicitacao": ""
        }


def atualizar_interacao(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["ultima_interacao"] = time.time()


def marcar_origem_campanha(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["origem"] = "Campanha"


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
        resposta = requests.post(url_envio, json=payload, headers=headers, timeout=20)
        print(f"ENVIO MENSAGEM [{telefone}] STATUS:", resposta.status_code)
        print("RESPOSTA Z-API:", resposta.text)
        return resposta.status_code in [200, 201]
    except Exception as e:
        print(f"Erro ao enviar mensagem para {telefone}: {e}")
        return False


def enviar_pdf(telefone, link_pdf, nome_arquivo="catalogo.pdf"):
    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "phone": telefone,
        "document": link_pdf,
        "fileName": nome_arquivo
    }

    try:
        resposta = requests.post(url_documento, json=payload, headers=headers, timeout=20)
        print(f"ENVIO PDF [{telefone}] STATUS:", resposta.status_code)
        print("RESPOSTA Z-API PDF:", resposta.text)

        if resposta.status_code in [200, 201]:
            return True

        return False
    except Exception as e:
        print(f"Erro ao enviar PDF para {telefone}: {e}")
        return False


def salvar_atendimento(
    telefone,
    nome="",
    setor="",
    modelo="",
    ano_modelo="",
    revisao="",
    data_agendamento="",
    horario_agendamento="",
    atendimento_humano="não",
    origem="menu normal",
    item_adicional="",
    status="aberto"
):
    db = SessionLocal()
    try:
        novo = Atendimento(
            telefone=telefone,
            nome=nome,
            setor=setor,
            modelo=modelo,
            ano_modelo=ano_modelo,
            revisao=revisao,
            data_agendamento=data_agendamento,
            horario_agendamento=horario_agendamento,
            atendimento_humano=atendimento_humano,
            origem=origem,
            item_adicional=item_adicional,
            status=status
        )
        db.add(novo)
        db.commit()
    except Exception as e:
        db.rollback()
        print("Erro ao salvar atendimento:", e)
    finally:
        db.close()


def cliente_em_atendimento_humano(telefone):
    db = SessionLocal()
    try:
        ultimo = (
            db.query(Atendimento)
            .filter(Atendimento.telefone == telefone)
            .order_by(Atendimento.id.desc())
            .first()
        )

        if ultimo and ultimo.atendimento_humano == "sim" and ultimo.status == "aguardando humano":
            return True

        return False
    except Exception as e:
        print("Erro ao verificar atendimento humano:", e)
        return False
    finally:
        db.close()


def encerrar_atendimento_humano(telefone):
    db = SessionLocal()
    try:
        ultimo = (
            db.query(Atendimento)
            .filter(
                Atendimento.telefone == telefone,
                Atendimento.atendimento_humano == "sim",
                Atendimento.status == "aguardando humano"
            )
            .order_by(Atendimento.id.desc())
            .first()
        )

        if ultimo:
            ultimo.status = "encerrado"
            db.commit()
    except Exception as e:
        db.rollback()
        print("Erro ao encerrar atendimento humano:", e)
    finally:
        db.close()


def menu_principal():
    return (
        "👋 Olá, seja bem-vindo à *Motoshow Yamaha*.\n\n"
        "Escolha uma opção:\n"
        "1 - Revisão\n"
        "2 - Peças\n"
        "3 - Acessórios\n"
        "4 - Garantia\n"
        "5 - Logista / Atacado\n"
        "6 - Atendimento humano"
    )


def menu_modelos():
    texto = "🏍 *Escolha o modelo da moto:*\n\n"
    for codigo, nome in MODELOS.items():
        texto += f"{codigo} - {nome}\n"
    return texto.strip()


def menu_revisoes():
    texto = "🔧 *Escolha a revisão:*\n\n"
    for codigo, nome in REVISOES.items():
        texto += f"{codigo} - {nome}\n"
    return texto.strip()


def menu_dias_semana():
    texto = "📅 *Escolha o dia da semana desejado:*\n\n"
    for codigo, nome in DIAS_SEMANA.items():
        texto += f"{codigo} - {nome}\n"
    return texto.strip()


def menu_garantia():
    return (
        "🛡️ *Garantia Motoshow Yamaha*\n\n"
        "Escolha uma opção:\n"
        "1 - Nova Solicitação\n"
        "2 - Acompanhar Garantia\n"
        "3 - Falar com Consultor\n"
        "0 - Voltar ao menu"
    )


def menu_pecas():
    return (
        "🔩 *Peças Motoshow Yamaha*\n\n"
        "Escolha uma opção:\n"
        "1 - Peças Originais\n"
        "2 - Consultar Disponibilidade\n"
        "3 - Falar com Consultor\n"
        "0 - Voltar ao menu"
    )


def menu_acessorios():
    return (
        "🛵 *Acessórios Motoshow Yamaha*\n\n"
        "Escolha uma opção:\n"
        "1 - Solicitar Acessório\n"
        "2 - Consultar Disponibilidade\n"
        "3 - Falar com Consultor\n"
        "0 - Voltar ao menu"
    )


def menu_atacado():
    return (
        "📦 *Logista / Atacado Motoshow Yamaha*\n\n"
        "Escolha uma opção:\n"
        "1 - Solicitar Cotação\n"
        "2 - Cadastro de Logista\n"
        "3 - Catálogo de Peças\n"
        "4 - Falar com Consultor\n"
        "0 - Voltar ao menu"
    )


def obter_horarios_por_revisao_e_dia(revisao_opcao, dia_opcao):
    if dia_opcao not in DIAS_SEMANA:
        return {}

    if revisao_opcao in ["1", "2"]:
        if dia_opcao in ["1", "2", "3", "4", "5"]:
            return {
                "1": "08:00",
                "2": "09:00",
                "3": "10:00",
                "4": "11:00",
                "5": "12:00",
                "6": "13:00",
                "7": "14:00",
                "8": "15:00"
            }
        if dia_opcao == "6":
            return {
                "1": "08:00",
                "2": "09:00",
                "3": "10:00"
            }

    if revisao_opcao in ["3", "4", "5"]:
        if dia_opcao in ["1", "2", "3", "4", "5"]:
            return {
                "1": "08:00"
            }
        if dia_opcao == "6":
            return {}

    return {}


def menu_horarios(revisao_opcao, dia_opcao):
    horarios = obter_horarios_por_revisao_e_dia(revisao_opcao, dia_opcao)

    if not horarios:
        return None

    texto = "⏰ *Escolha o horário disponível:*\n\n"
    for codigo, horario in horarios.items():
        texto += f"{codigo} - {horario}\n"
    return texto.strip()


def mensagem_encerramento():
    return (
        "⏰ Seu atendimento foi encerrado por inatividade.\n"
        "Quando quiser, envie qualquer mensagem para começar novamente.\n\n"
        "Equipe *Motoshow Yamaha*."
    )


def monitorar_inatividade():
    while True:
        try:
            agora = time.time()
            telefones_para_encerrar = []

            for telefone, dados in list(clientes.items()):
                ultima = dados.get("ultima_interacao", agora)
                if agora - ultima > TEMPO_INATIVIDADE:
                    telefones_para_encerrar.append(telefone)

            for telefone in telefones_para_encerrar:
                enviar_mensagem(telefone, mensagem_encerramento())
                clientes.pop(telefone, None)

        except Exception as e:
            print("Erro no monitoramento de inatividade:", e)

        time.sleep(30)


def extrair_mensagem_texto(payload):
    candidatos = [
        payload.get("text", {}).get("message") if isinstance(payload.get("text"), dict) else None,
        payload.get("message"),
        payload.get("body"),
        payload.get("text") if isinstance(payload.get("text"), str) else None,
        payload.get("msg"),
    ]

    for item in candidatos:
        if isinstance(item, str) and item.strip():
            return item.strip()

    return ""


def extrair_telefone(payload):
    candidatos = [
        payload.get("phone"),
        payload.get("from"),
        payload.get("senderPhone"),
        payload.get("chatId"),
        payload.get("jid"),
    ]

    for item in candidatos:
        if isinstance(item, str) and item.strip():
            return (
                item.strip()
                .replace("@s.whatsapp.net", "")
                .replace("@c.us", "")
                .replace("@g.us", "")
            )

    sender = payload.get("sender")
    if isinstance(sender, dict):
        for chave in ["phone", "id", "jid"]:
            valor = sender.get(chave)
            if isinstance(valor, str) and valor.strip():
                return (
                    valor.strip()
                    .replace("@s.whatsapp.net", "")
                    .replace("@c.us", "")
                    .replace("@g.us", "")
                )

    return None


def extrair_id_mensagem(payload):
    candidatos = [
        payload.get("messageId"),
        payload.get("id"),
        payload.get("msgId"),
        payload.get("message_id"),
    ]

    for item in candidatos:
        if isinstance(item, str) and item.strip():
            return item.strip()

    text = payload.get("text")
    if isinstance(text, dict):
        for chave in ["id", "messageId", "msgId"]:
            valor = text.get(chave)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()

    return None


def limpar_mensagens_processadas():
    agora = time.time()
    ids_para_remover = []

    for msg_id, timestamp in list(mensagens_processadas.items()):
        if agora - timestamp > TEMPO_CACHE_MENSAGENS:
            ids_para_remover.append(msg_id)

    for msg_id in ids_para_remover:
        mensagens_processadas.pop(msg_id, None)


def mensagem_ja_processada(msg_id):
    if not msg_id:
        return False

    limpar_mensagens_processadas()

    if msg_id in mensagens_processadas:
        return True

    mensagens_processadas[msg_id] = time.time()
    return False


def eh_grupo(payload):
    if payload.get("isGroup") is True:
        return True

    if payload.get("is_group") is True:
        return True

    if payload.get("fromGroup") is True:
        return True

    campos = [
        payload.get("chatId"),
        payload.get("from"),
        payload.get("phone"),
        payload.get("jid"),
    ]

    for campo in campos:
        if isinstance(campo, str) and campo.endswith("@g.us"):
            return True

    sender = payload.get("sender")
    if isinstance(sender, dict):
        if sender.get("isGroup") is True:
            return True

        for chave in ["id", "jid", "phone"]:
            valor = sender.get(chave)
            if isinstance(valor, str) and valor.endswith("@g.us"):
                return True

    return False


def eh_mensagem_do_proprio_bot(payload):
    if payload.get("fromMe") is True:
        return True
    if payload.get("isFromMe") is True:
        return True
    if payload.get("self") is True:
        return True
    if payload.get("sentByMe") is True:
        return True
    if payload.get("owner") is True:
        return True
    return False


def identificar_origem_campanha_no_payload(telefone, mensagem):
    """
    Marca o cliente como campanha se a mensagem recebida tiver o gatilho.
    """
    if not mensagem:
        return

    if "#campanha_revisao" in mensagem.lower():
        marcar_origem_campanha(telefone)
        print(f"Cliente {telefone} marcado como origem Campanha.")
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
                enviados += 1
            else:
                erros += 1

            time.sleep(INTERVALO_ENTRE_ENVIOS)

    finally:
        db.close()

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