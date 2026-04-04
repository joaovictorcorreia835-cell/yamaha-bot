from flask import Flask, request, jsonify, render_template_string
import requests
import os
from dotenv import load_dotenv
from datetime import datetime
import threading
import time
from sqlalchemy import create_engine, Column, Integer, String, DateTime, func
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

app = Flask(__name__)

# ==========================================
# CONFIG
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://SEU-APP.onrender.com")
PORT = int(os.getenv("PORT", 5000))

url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"

TEMPO_INATIVIDADE = 900  # 15 minutos

clientes = {}

# ==========================================
# BANCO DE DADOS
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha_bot.db")

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
    item_adicional = Column(String(300))
    status = Column(String(80), default="aberto")
    criado_em = Column(DateTime, default=datetime.now)


Base.metadata.create_all(bind=engine)

# ==========================================
# OPÇÕES FIXAS
# ==========================================
MODELOS = {
    "1": "Fazer 250",
    "2": "FZ15",
    "3": "Crosser",
    "4": "Lander",
    "5": "MT-03",
    "6": "MT-07",
    "7": "R15",
    "8": "R3",
    "9": "Fluo",
    "10": "Neo",
    "11": "NMax",
    "12": "Tenere 700",
    "13": "Aerox"
}

REVISOES = {
    "1": "1ª Revisão",
    "2": "2ª Revisão",
    "3": "3ª Revisão",
    "4": "4ª Revisão",
    "5": "5ª Revisão ou mais"
}

DIAS_SEMANA = {
    "1": "Segunda-feira",
    "2": "Terça-feira",
    "3": "Quarta-feira",
    "4": "Quinta-feira",
    "5": "Sexta-feira",
    "6": "Sábado"
}

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
    except Exception as e:
        print(f"Erro ao enviar mensagem para {telefone}: {e}")


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
    except Exception as e:
        print(f"Erro ao enviar PDF para {telefone}: {e}")


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


def processar_mensagem(telefone, mensagem):
    iniciar_cliente(telefone)
    atualizar_interacao(telefone)

    msg = mensagem.strip().lower()
    cliente = clientes[telefone]
    etapa = cliente["etapa"]

    if etapa == "aguardando_humano":
        print(f"Cliente {telefone} está em atendimento humano. Mensagem ignorada pelo bot.")
        return

    if msg in ["menu", "oi", "olá", "ola", "iniciar", "começar", "comecar"]:
        cliente["etapa"] = "menu"
        enviar_mensagem(telefone, menu_principal())
        return

    # ==========================================
    # MENU PRINCIPAL
    # ==========================================
    if etapa == "menu":
        if msg == "1":
            cliente["setor"] = "Revisão"
            cliente["etapa"] = "nome"
            enviar_mensagem(telefone, "Perfeito. Informe seu *nome completo*.")
            return

        elif msg == "2":
            cliente["setor"] = "Peças"
            cliente["etapa"] = "pecas_menu"
            enviar_mensagem(telefone, menu_pecas())
            return

        elif msg == "3":
            cliente["setor"] = "Acessórios"
            cliente["etapa"] = "acessorios_menu"
            enviar_mensagem(telefone, menu_acessorios())
            return

        elif msg == "4":
            cliente["setor"] = "Garantia"
            cliente["etapa"] = "garantia_menu"
            enviar_mensagem(telefone, menu_garantia())
            return

        elif msg == "5":
            cliente["setor"] = "Logista/Atacado"
            cliente["etapa"] = "atacado_menu"
            enviar_mensagem(telefone, menu_atacado())
            return

        elif msg == "6" or msg == "humano":
            cliente["setor"] = "Atendimento Humano"
            cliente["atendimento_humano"] = True
            cliente["etapa"] = "aguardando_humano"

            salvar_atendimento(
                telefone=telefone,
                nome=cliente["nome"],
                setor=cliente["setor"],
                atendimento_humano="sim",
                origem=cliente["origem"],
                status="aguardando humano"
            )

            enviar_mensagem(
                telefone,
                "✅ Seu atendimento foi encaminhado para um atendente.\n"
                "Em breve nossa equipe continuará com você.\n\n"
                "Equipe *Motoshow Yamaha*."
            )
            return

        else:
            enviar_mensagem(telefone, "Opção inválida.\n\n" + menu_principal())
            return

    # ==========================================
    # FLUXO REVISÃO
    # ==========================================
    if etapa == "nome":
        cliente["nome"] = mensagem.strip()
        cliente["etapa"] = "modelo"
        enviar_mensagem(telefone, menu_modelos())
        return

    if etapa == "modelo":
        modelo_escolhido = MODELOS.get(msg)

        if not modelo_escolhido:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_modelos())
            return

        cliente["modelo"] = modelo_escolhido
        cliente["etapa"] = "ano_modelo"
        enviar_mensagem(telefone, "Informe o *ano/modelo* da moto.\nExemplo: *2024*")
        return

    if etapa == "ano_modelo":
        cliente["ano_modelo"] = mensagem.strip()
        cliente["etapa"] = "revisao"
        enviar_mensagem(telefone, menu_revisoes())
        return

    if etapa == "revisao":
        revisao_escolhida = REVISOES.get(msg)

        if not revisao_escolhida:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_revisoes())
            return

        cliente["revisao"] = revisao_escolhida
        cliente["revisao_opcao"] = msg
        cliente["etapa"] = "dia_semana"
        enviar_mensagem(telefone, menu_dias_semana())
        return

    if etapa == "dia_semana":
        dia_escolhido = DIAS_SEMANA.get(msg)

        if not dia_escolhido:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_dias_semana())
            return

        horarios = obter_horarios_por_revisao_e_dia(cliente.get("revisao_opcao", ""), msg)

        if not horarios:
            enviar_mensagem(
                telefone,
                "❌ Para essa revisão não há atendimento disponível nesse dia.\n\n"
                "Escolha outro dia:\n\n" + menu_dias_semana()
            )
            return

        cliente["data_agendamento"] = dia_escolhido
        cliente["dia_semana_opcao"] = msg
        cliente["etapa"] = "horario_agendamento"
        enviar_mensagem(telefone, menu_horarios(cliente.get("revisao_opcao", ""), msg))
        return

    if etapa == "horario_agendamento":
        horarios = obter_horarios_por_revisao_e_dia(
            cliente.get("revisao_opcao", ""),
            cliente.get("dia_semana_opcao", "")
        )

        horario_escolhido = horarios.get(msg)

        if not horario_escolhido:
            texto_horarios = menu_horarios(
                cliente.get("revisao_opcao", ""),
                cliente.get("dia_semana_opcao", "")
            )
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + texto_horarios)
            return

        cliente["horario_agendamento"] = horario_escolhido
        cliente["etapa"] = "item_adicional"

        enviar_mensagem(
            telefone,
            "Deseja incluir algum item adicional no atendimento?\n"
            "Exemplo: troca de óleo, pastilha, relação, pneu.\n\n"
            "Se não quiser, responda *não*."
        )
        return

    if etapa == "item_adicional":
        cliente["item_adicional"] = "" if msg in ["não", "nao"] else mensagem.strip()
        cliente["etapa"] = "finalizado"

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor=cliente["setor"],
            modelo=cliente["modelo"],
            ano_modelo=cliente["ano_modelo"],
            revisao=cliente["revisao"],
            data_agendamento=cliente["data_agendamento"],
            horario_agendamento=cliente["horario_agendamento"],
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=cliente["item_adicional"],
            status="agendado"
        )

        resumo = (
            "✅ *Agendamento registrado com sucesso!*\n\n"
            f"👤 Nome: {cliente['nome']}\n"
            f"🏍 Modelo: {cliente['modelo']}\n"
            f"📅 Ano/Modelo: {cliente['ano_modelo']}\n"
            f"🔧 Revisão: {cliente['revisao']}\n"
            f"🗓 Dia escolhido: {cliente['data_agendamento']}\n"
            f"⏰ Horário: {cliente['horario_agendamento']}\n"
        )

        if cliente["item_adicional"]:
            resumo += f"🛠 Item adicional: {cliente['item_adicional']}\n"

        resumo += "\nNossa equipe entrará em contato se necessário.\n\nEquipe *Motoshow Yamaha*."

        enviar_mensagem(telefone, resumo)
        clientes.pop(telefone, None)
        return

    # ==========================================
    # SUBMENU PEÇAS
    # ==========================================
    if etapa == "pecas_menu":
        if msg == "1":
            cliente["etapa"] = "pecas_nome"
            enviar_mensagem(telefone, "Informe o *nome da peça desejada*.")
            return
        elif msg == "2":
            cliente["etapa"] = "pecas_consulta_nome"
            enviar_mensagem(telefone, "Informe a *peça* que deseja consultar.")
            return
        elif msg == "3" or msg == "humano":
            cliente["atendimento_humano"] = True
            cliente["etapa"] = "aguardando_humano"

            salvar_atendimento(
                telefone=telefone,
                nome=cliente["nome"],
                setor="Peças",
                atendimento_humano="sim",
                origem=cliente["origem"],
                status="aguardando humano"
            )

            enviar_mensagem(
                telefone,
                "✅ Você será encaminhado para nosso consultor de *Peças*.\n"
                "Em breve nossa equipe continuará com você.\n\n"
                "Equipe *Motoshow Yamaha*."
            )
            return
        elif msg == "0":
            cliente["etapa"] = "menu"
            enviar_mensagem(telefone, menu_principal())
            return
        else:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_pecas())
            return

    if etapa == "pecas_nome":
        cliente["peca_nome"] = mensagem.strip()
        cliente["etapa"] = "pecas_modelo"
        enviar_mensagem(telefone, menu_modelos())
        return

    if etapa == "pecas_modelo":
        modelo_escolhido = MODELOS.get(msg)
        if not modelo_escolhido:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_modelos())
            return

        cliente["modelo"] = modelo_escolhido
        cliente["etapa"] = "pecas_ano_modelo"
        enviar_mensagem(telefone, "Informe o *ano/modelo* da moto.\nExemplo: *2024*")
        return

    if etapa == "pecas_ano_modelo":
        cliente["ano_modelo"] = mensagem.strip()
        cliente["etapa"] = "pecas_cor"
        enviar_mensagem(telefone, "Informe a *cor da moto*.\nExemplo: *azul*")
        return

    if etapa == "pecas_cor":
        cliente["cor_moto"] = mensagem.strip()

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor="Peças",
            modelo=cliente["modelo"],
            ano_modelo=cliente["ano_modelo"],
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=f"Peça: {cliente['peca_nome']} | Cor: {cliente['cor_moto']}",
            status="solicitação de peça registrada"
        )

        enviar_mensagem(
            telefone,
            "✅ Sua solicitação de *peça* foi registrada com sucesso.\n\n"
            "Nossa equipe de peças retornará em breve com a disponibilidade e orçamento.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    if etapa == "pecas_consulta_nome":
        cliente["peca_nome"] = mensagem.strip()
        cliente["etapa"] = "pecas_consulta_modelo"
        enviar_mensagem(telefone, menu_modelos())
        return

    if etapa == "pecas_consulta_modelo":
        modelo_escolhido = MODELOS.get(msg)
        if not modelo_escolhido:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_modelos())
            return

        cliente["modelo"] = modelo_escolhido
        cliente["etapa"] = "pecas_consulta_ano"
        enviar_mensagem(telefone, "Informe o *ano/modelo* da moto.\nExemplo: *2024*")
        return

    if etapa == "pecas_consulta_ano":
        cliente["ano_modelo"] = mensagem.strip()

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor="Peças",
            modelo=cliente["modelo"],
            ano_modelo=cliente["ano_modelo"],
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=f"Consulta de disponibilidade da peça: {cliente['peca_nome']}",
            status="consulta de peça registrada"
        )

        enviar_mensagem(
            telefone,
            "✅ Consulta de disponibilidade registrada.\n\n"
            "Em breve nossa equipe retornará com a posição do estoque.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    # ==========================================
    # SUBMENU ACESSÓRIOS
    # ==========================================
    if etapa == "acessorios_menu":
        if msg == "1":
            cliente["etapa"] = "acessorio_nome"
            enviar_mensagem(
                telefone,
                "Informe o *acessório desejado*.\n"
                "Exemplo: protetor de motor, slider, baú, suporte de celular."
            )
            return
        elif msg == "2":
            cliente["etapa"] = "acessorio_consulta_nome"
            enviar_mensagem(telefone, "Informe o *acessório* que deseja consultar.")
            return
        elif msg == "3" or msg == "humano":
            cliente["atendimento_humano"] = True
            cliente["etapa"] = "aguardando_humano"

            salvar_atendimento(
                telefone=telefone,
                nome=cliente["nome"],
                setor="Acessórios",
                atendimento_humano="sim",
                origem=cliente["origem"],
                status="aguardando humano"
            )

            enviar_mensagem(
                telefone,
                "✅ Você será encaminhado para nosso consultor de *Acessórios*.\n"
                "Em breve nossa equipe continuará com você.\n\n"
                "Equipe *Motoshow Yamaha*."
            )
            return
        elif msg == "0":
            cliente["etapa"] = "menu"
            enviar_mensagem(telefone, menu_principal())
            return
        else:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_acessorios())
            return

    if etapa == "acessorio_nome":
        cliente["acessorio_nome"] = mensagem.strip()
        cliente["etapa"] = "acessorio_modelo"
        enviar_mensagem(telefone, menu_modelos())
        return

    if etapa == "acessorio_modelo":
        modelo_escolhido = MODELOS.get(msg)
        if not modelo_escolhido:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_modelos())
            return

        cliente["modelo"] = modelo_escolhido
        cliente["etapa"] = "acessorio_ano"
        enviar_mensagem(telefone, "Informe o *ano/modelo* da moto.\nExemplo: *2024*")
        return

    if etapa == "acessorio_ano":
        cliente["ano_modelo"] = mensagem.strip()

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor="Acessórios",
            modelo=cliente["modelo"],
            ano_modelo=cliente["ano_modelo"],
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=f"Acessório solicitado: {cliente['acessorio_nome']}",
            status="solicitação de acessório registrada"
        )

        enviar_mensagem(
            telefone,
            "✅ Sua solicitação de *acessório* foi registrada com sucesso.\n\n"
            "Nossa equipe retornará em breve com disponibilidade e orçamento.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    if etapa == "acessorio_consulta_nome":
        cliente["acessorio_nome"] = mensagem.strip()
        cliente["etapa"] = "acessorio_consulta_modelo"
        enviar_mensagem(telefone, menu_modelos())
        return

    if etapa == "acessorio_consulta_modelo":
        modelo_escolhido = MODELOS.get(msg)
        if not modelo_escolhido:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_modelos())
            return

        cliente["modelo"] = modelo_escolhido

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor="Acessórios",
            modelo=cliente["modelo"],
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=f"Consulta de disponibilidade do acessório: {cliente['acessorio_nome']}",
            status="consulta de acessório registrada"
        )

        enviar_mensagem(
            telefone,
            "✅ Consulta de disponibilidade registrada.\n\n"
            "Em breve nossa equipe retornará.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    # ==========================================
    # SUBMENU GARANTIA
    # ==========================================
    if etapa == "garantia_menu":
        if msg == "1":
            cliente["garantia_opcao"] = "nova_solicitacao"
            cliente["etapa"] = "garantia_nome"
            enviar_mensagem(telefone, "Perfeito. Informe seu *nome completo*.")
            return

        elif msg == "2":
            cliente["garantia_opcao"] = "acompanhar"
            cliente["etapa"] = "garantia_cpf_acompanhar"
            enviar_mensagem(telefone, "Por favor, informe seu *CPF* para acompanhamento da garantia.")
            return

        elif msg == "3" or msg == "humano":
            cliente["atendimento_humano"] = True
            cliente["etapa"] = "aguardando_humano"

            salvar_atendimento(
                telefone=telefone,
                nome=cliente["nome"],
                setor="Garantia",
                atendimento_humano="sim",
                origem=cliente["origem"],
                status="aguardando humano"
            )

            enviar_mensagem(
                telefone,
                "✅ Você será encaminhado para nosso consultor de *Garantia*.\n"
                "Em breve nossa equipe continuará com você.\n\n"
                "Equipe *Motoshow Yamaha*."
            )
            return

        elif msg == "0":
            cliente["etapa"] = "menu"
            enviar_mensagem(telefone, menu_principal())
            return

        else:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_garantia())
            return

    if etapa == "garantia_nome":
        cliente["nome"] = mensagem.strip()
        cliente["etapa"] = "garantia_cpf"
        enviar_mensagem(telefone, "Informe seu *CPF*.")
        return

    if etapa == "garantia_cpf":
        cliente["cpf"] = mensagem.strip()
        cliente["etapa"] = "garantia_modelo"
        enviar_mensagem(telefone, menu_modelos())
        return

    if etapa == "garantia_modelo":
        modelo_escolhido = MODELOS.get(msg)
        if not modelo_escolhido:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_modelos())
            return

        cliente["modelo"] = modelo_escolhido
        cliente["etapa"] = "garantia_ano_modelo"
        enviar_mensagem(telefone, "Informe o *ano/modelo* da moto.\nExemplo: *2024*")
        return

    if etapa == "garantia_ano_modelo":
        cliente["ano_modelo"] = mensagem.strip()
        cliente["etapa"] = "garantia_km"
        enviar_mensagem(telefone, "Informe a *quilometragem atual* da moto.\nExemplo: *12500 km*")
        return

    if etapa == "garantia_km":
        cliente["km_atual"] = mensagem.strip()
        cliente["etapa"] = "garantia_descricao"
        enviar_mensagem(telefone, "Descreva o *problema apresentado* para análise da garantia.")
        return

    if etapa == "garantia_descricao":
        cliente["descricao_garantia"] = mensagem.strip()

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor="Garantia",
            modelo=cliente["modelo"],
            ano_modelo=cliente["ano_modelo"],
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=f"CPF: {cliente['cpf']} | KM: {cliente['km_atual']} | Problema: {cliente['descricao_garantia']}",
            status="solicitação garantia aberta"
        )

        resumo = (
            "✅ *Solicitação de garantia registrada com sucesso!*\n\n"
            f"👤 Nome: {cliente['nome']}\n"
            f"📄 CPF: {cliente['cpf']}\n"
            f"🏍 Modelo: {cliente['modelo']}\n"
            f"📅 Ano/Modelo: {cliente['ano_modelo']}\n"
            f"🔢 KM Atual: {cliente['km_atual']}\n"
            f"📝 Problema informado: {cliente['descricao_garantia']}\n\n"
            "Nossa equipe de garantia irá analisar e retornar o mais breve possível.\n\n"
            "Equipe *Motoshow Yamaha*."
        )

        enviar_mensagem(telefone, resumo)
        clientes.pop(telefone, None)
        return

    if etapa == "garantia_cpf_acompanhar":
        cpf = mensagem.strip()

        db = SessionLocal()
        try:
            registro = (
                db.query(Atendimento)
                .filter(
                    Atendimento.setor == "Garantia",
                    Atendimento.item_adicional.like(f"%CPF: {cpf}%")
                )
                .order_by(Atendimento.id.desc())
                .first()
            )
        finally:
            db.close()

        if registro:
            resposta = (
                "🛡️ *Acompanhamento de Garantia*\n\n"
                f"👤 Nome: {registro.nome or 'Não informado'}\n"
                f"🏍 Modelo: {registro.modelo or 'Não informado'}\n"
                f"📅 Ano/Modelo: {registro.ano_modelo or 'Não informado'}\n"
                f"📌 Status: {registro.status or 'Em análise'}\n\n"
                "Em breve nossa equipe entrará em contato.\n\n"
                "Equipe *Motoshow Yamaha*."
            )
        else:
            resposta = (
                "❌ Não localizamos uma solicitação de garantia com esse CPF no momento.\n"
                "Se preferir, responda *menu* e abra uma nova solicitação.\n\n"
                "Equipe *Motoshow Yamaha*."
            )

        enviar_mensagem(telefone, resposta)
        clientes.pop(telefone, None)
        return

    # ==========================================
    # SUBMENU ATACADO
    # ==========================================
    if etapa == "atacado_menu":
        if msg == "1":
            cliente["etapa"] = "atacado_empresa"
            enviar_mensagem(telefone, "Informe o *nome da empresa*.")
            return
        elif msg == "2":
            cliente["etapa"] = "atacado_cadastro_empresa"
            enviar_mensagem(telefone, "Informe o *nome da empresa* para cadastro.")
            return
        elif msg == "3":
            link_pdf = f"{BASE_URL}/static/catalogo.pdf"
            enviar_mensagem(telefone, "📄 Enviando catálogo de peças para você...")
            enviar_pdf(telefone, link_pdf, "catalogo_motoshow.pdf")

            salvar_atendimento(
                telefone=telefone,
                nome=cliente["nome"],
                setor="Logista/Atacado",
                atendimento_humano="não",
                origem=cliente["origem"],
                status="catálogo enviado"
            )

            enviar_mensagem(
                telefone,
                "✅ Catálogo enviado com sucesso.\n"
                "Se precisar de cotação, responda por aqui.\n\n"
                "Equipe *Motoshow Yamaha*."
            )
            clientes.pop(telefone, None)
            return
        elif msg == "4" or msg == "humano":
            cliente["atendimento_humano"] = True
            cliente["etapa"] = "aguardando_humano"

            salvar_atendimento(
                telefone=telefone,
                nome=cliente["nome"],
                setor="Logista/Atacado",
                atendimento_humano="sim",
                origem=cliente["origem"],
                status="aguardando humano"
            )

            enviar_mensagem(
                telefone,
                "✅ Você será encaminhado para nosso consultor de *Logista / Atacado*.\n"
                "Em breve nossa equipe continuará com você.\n\n"
                "Equipe *Motoshow Yamaha*."
            )
            return
        elif msg == "0":
            cliente["etapa"] = "menu"
            enviar_mensagem(telefone, menu_principal())
            return
        else:
            enviar_mensagem(telefone, "❌ Opção inválida.\n\n" + menu_atacado())
            return

    # Cotação
    if etapa == "atacado_empresa":
        cliente["empresa"] = mensagem.strip()
        cliente["etapa"] = "atacado_cnpj"
        enviar_mensagem(telefone, "Informe o *CNPJ*.")
        return

    if etapa == "atacado_cnpj":
        cliente["cnpj"] = mensagem.strip()
        cliente["etapa"] = "atacado_cidade"
        enviar_mensagem(telefone, "Informe a *cidade*.")
        return

    if etapa == "atacado_cidade":
        cliente["cidade"] = mensagem.strip()
        cliente["etapa"] = "atacado_pecas"
        enviar_mensagem(
            telefone,
            "Descreva as *peças desejadas*.\n"
            "Pode enviar código, modelo ou lista dos itens."
        )
        return

    if etapa == "atacado_pecas":
        cliente["descricao_solicitacao"] = mensagem.strip()

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["empresa"],
            setor="Logista/Atacado",
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=f"CNPJ: {cliente['cnpj']} | Cidade: {cliente['cidade']} | Itens: {cliente['descricao_solicitacao']}",
            status="cotação atacado registrada"
        )

        enviar_mensagem(
            telefone,
            "✅ Sua solicitação de *cotação* foi registrada com sucesso.\n\n"
            "Nossa equipe de atacado retornará em breve.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    # Cadastro logista
    if etapa == "atacado_cadastro_empresa":
        cliente["empresa"] = mensagem.strip()
        cliente["etapa"] = "atacado_cadastro_cnpj"
        enviar_mensagem(telefone, "Informe o *CNPJ*.")
        return

    if etapa == "atacado_cadastro_cnpj":
        cliente["cnpj"] = mensagem.strip()
        cliente["etapa"] = "atacado_cadastro_responsavel"
        enviar_mensagem(telefone, "Informe o *nome do responsável*.")
        return

    if etapa == "atacado_cadastro_responsavel":
        cliente["responsavel"] = mensagem.strip()
        cliente["etapa"] = "atacado_cadastro_cidade"
        enviar_mensagem(telefone, "Informe a *cidade*.")
        return

    if etapa == "atacado_cadastro_cidade":
        cliente["cidade"] = mensagem.strip()
        cliente["etapa"] = "atacado_cadastro_telefone"
        enviar_mensagem(telefone, "Informe o *telefone* para contato.")
        return

    if etapa == "atacado_cadastro_telefone":
        cliente["telefone_empresa"] = mensagem.strip()

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["empresa"],
            setor="Logista/Atacado",
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=(
                f"CNPJ: {cliente['cnpj']} | Responsável: {cliente['responsavel']} | "
                f"Cidade: {cliente['cidade']} | Telefone: {cliente['telefone_empresa']}"
            ),
            status="cadastro logista registrado"
        )

        enviar_mensagem(
            telefone,
            "✅ Seu *cadastro* foi registrado com sucesso.\n\n"
            "Nossa equipe comercial retornará em breve.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    if etapa == "aguardando_humano":
        return

    enviar_mensagem(telefone, menu_principal())


# ==========================================
# ROTAS
# ==========================================
@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Webhook ativo"}), 200

    try:
        payload = request.get_json(silent=True) or {}
        print("PAYLOAD RECEBIDO:", payload)

        if eh_grupo(payload):
            print("Mensagem de grupo ignorada.")
            return jsonify({"status": "ignored", "reason": "group_message"}), 200

        if eh_mensagem_do_proprio_bot(payload):
            print("Mensagem do próprio bot ignorada.")
            return jsonify({"status": "ignored", "reason": "from_me"}), 200

        telefone = extrair_telefone(payload)
        mensagem = extrair_mensagem_texto(payload)

        if not telefone:
            print("Telefone não encontrado no payload.")
            return jsonify({"status": "ignored", "reason": "phone_not_found"}), 200

        if not mensagem:
            print("Mensagem vazia ou não suportada.")
            return jsonify({"status": "ignored", "reason": "empty_message"}), 200

        print("TELEFONE EXTRAÍDO:", telefone)
        print("MENSAGEM EXTRAÍDA:", mensagem)

        processar_mensagem(telefone, mensagem)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("ERRO NO WEBHOOK:", str(e))
        return jsonify({"status": "erro", "detalhe": str(e)}), 500


@app.route("/dashboard")
def dashboard():
    db = SessionLocal()
    try:
        total_atendimentos = db.query(func.count(Atendimento.id)).scalar() or 0
        total_humano = db.query(func.count(Atendimento.id)).filter(Atendimento.atendimento_humano == "sim").scalar() or 0
        total_agendados = db.query(func.count(Atendimento.id)).filter(Atendimento.status == "agendado").scalar() or 0

        por_setor = db.query(
            Atendimento.setor,
            func.count(Atendimento.id)
        ).group_by(Atendimento.setor).all()

        revisoes = db.query(
            Atendimento.revisao,
            func.count(Atendimento.id)
        ).filter(Atendimento.revisao != "").group_by(Atendimento.revisao).order_by(func.count(Atendimento.id).desc()).all()

        itens = db.query(
            Atendimento.item_adicional,
            func.count(Atendimento.id)
        ).filter(Atendimento.item_adicional != "").group_by(Atendimento.item_adicional).order_by(func.count(Atendimento.id).desc()).all()

        origens = db.query(
            Atendimento.origem,
            func.count(Atendimento.id)
        ).group_by(Atendimento.origem).all()

        html = """
        <html>
        <head>
            <title>Dashboard Yamaha Bot</title>
            <style>
                body { font-family: Arial; padding: 30px; background: #f5f5f5; }
                h1, h2 { color: #222; }
                .card {
                    background: white;
                    padding: 20px;
                    border-radius: 12px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                }
                ul { padding-left: 20px; }
            </style>
        </head>
        <body>
            <h1>📊 Dashboard - Motoshow Yamaha</h1>

            <div class="card">
                <h2>Resumo</h2>
                <p><strong>Total de atendimentos:</strong> {{ total_atendimentos }}</p>
                <p><strong>Agendamentos concluídos:</strong> {{ total_agendados }}</p>
                <p><strong>Pedidos de atendimento humano:</strong> {{ total_humano }}</p>
            </div>

            <div class="card">
                <h2>Total por setor</h2>
                <ul>
                    {% for setor, qtd in por_setor %}
                        <li><strong>{{ setor or 'Não informado' }}:</strong> {{ qtd }}</li>
                    {% endfor %}
                </ul>
            </div>

            <div class="card">
                <h2>Revisões mais solicitadas</h2>
                <ul>
                    {% for rev, qtd in revisoes %}
                        <li><strong>{{ rev }}:</strong> {{ qtd }}</li>
                    {% endfor %}
                </ul>
            </div>

            <div class="card">
                <h2>Itens adicionais / solicitações</h2>
                <ul>
                    {% for item, qtd in itens %}
                        <li><strong>{{ item }}:</strong> {{ qtd }}</li>
                    {% endfor %}
                </ul>
            </div>

            <div class="card">
                <h2>Origem do lead</h2>
                <ul>
                    {% for origem, qtd in origens %}
                        <li><strong>{{ origem or 'Não informado' }}:</strong> {{ qtd }}</li>
                    {% endfor %}
                </ul>
            </div>
        </body>
        </html>
        """

        return render_template_string(
            html,
            total_atendimentos=total_atendimentos,
            total_humano=total_humano,
            total_agendados=total_agendados,
            por_setor=por_setor,
            revisoes=revisoes,
            itens=itens,
            origens=origens
        )
    finally:
        db.close()


# ==========================================
# THREAD INATIVIDADE
# ==========================================
thread_inatividade = threading.Thread(target=monitorar_inatividade, daemon=True)
thread_inatividade.start()


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)