from flask import Flask, request, jsonify, render_template_string
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
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
    item_adicional = Column(String(150))
    status = Column(String(50), default="aberto")
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
            "data_agendamento": "",
            "horario_agendamento": "",
            "setor": "",
            "origem": "menu normal",
            "atendimento_humano": False,
            "item_adicional": ""
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
        requests.post(url_envio, json=payload, headers=headers, timeout=20)
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
        requests.post(url_documento, json=payload, headers=headers, timeout=20)
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


def horarios_disponiveis(revisao, data_str):
    try:
        data_obj = datetime.strptime(data_str, "%d/%m/%Y")
    except:
        return []

    dia_semana = data_obj.weekday()  # segunda=0 ... domingo=6

    if dia_semana == 6:
        return []

    revisao = revisao.strip().lower()

    # sábado
    if dia_semana == 5:
        if revisao in ["1", "1ª", "1a", "primeira", "2", "2ª", "2a", "segunda"]:
            return ["1 - 08:00", "2 - 09:00", "3 - 10:00"]
        return []

    # segunda a sexta
    if revisao in ["1", "1ª", "1a", "primeira", "2", "2ª", "2a", "segunda"]:
        return [
            "1 - 08:00", "2 - 09:00", "3 - 10:00", "4 - 11:00",
            "5 - 12:00", "6 - 13:00", "7 - 14:00", "8 - 15:00"
        ]
    else:
        return ["1 - 08:00"]


def opcao_para_horario(opcao, revisao, data_str):
    horarios = horarios_disponiveis(revisao, data_str)
    mapa = {}

    for item in horarios:
        partes = item.split(" - ")
        if len(partes) == 2:
            mapa[partes[0].strip()] = partes[1].strip()

    return mapa.get(opcao.strip())


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
        payload.get("text"),
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
            return item.strip().replace("@s.whatsapp.net", "").replace("@c.us", "").replace("@g.us", "")

    return None


def eh_grupo(payload):
    # 1) campos booleanos comuns
    if payload.get("isGroup") is True:
        return True

    if payload.get("fromGroup") is True:
        return True

    # 2) chatId / from / phone terminando com @g.us
    campos = [
        payload.get("chatId"),
        payload.get("from"),
        payload.get("phone"),
        payload.get("jid"),
    ]

    for campo in campos:
        if isinstance(campo, str) and campo.endswith("@g.us"):
            return True

    # 3) objeto sender
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
    # campos comuns que indicam mensagem enviada por mim/bot
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

    # Sempre permite reinício rápido
    if msg in ["menu", "oi", "olá", "ola", "iniciar", "começar", "comecar"]:
        cliente["etapa"] = "menu"
        enviar_mensagem(telefone, menu_principal())
        return

    if etapa == "menu":
        if msg == "1":
            cliente["setor"] = "Revisão"
            cliente["etapa"] = "nome"
            enviar_mensagem(telefone, "Perfeito. Informe seu *nome completo*.")
            return

        elif msg == "2":
            cliente["setor"] = "Peças"
            cliente["etapa"] = "pecas"
            enviar_mensagem(
                telefone,
                "Você selecionou *Peças*.\n\n"
                "Digite o que precisa ou envie o código da peça.\n"
                "Se preferir, digite *humano* para atendimento."
            )
            return

        elif msg == "3":
            cliente["setor"] = "Acessórios"
            cliente["etapa"] = "acessorios"
            enviar_mensagem(
                telefone,
                "Você selecionou *Acessórios*.\n\n"
                "Digite o acessório desejado.\n"
                "Se preferir, digite *humano* para atendimento."
            )
            return

        elif msg == "4":
            cliente["setor"] = "Garantia"
            cliente["etapa"] = "garantia"
            enviar_mensagem(
                telefone,
                "Você selecionou *Garantia*.\n\n"
                "Descreva seu caso para encaminharmos ao setor responsável."
            )
            return

        elif msg == "5":
            cliente["setor"] = "Logista/Atacado"
            cliente["etapa"] = "atacado"
            enviar_mensagem(
                telefone,
                "Você selecionou *Logista / Atacado*.\n\n"
                "Descreva sua necessidade ou digite *catálogo* para receber o PDF."
            )
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

    if etapa == "nome":
        cliente["nome"] = mensagem.strip()
        cliente["etapa"] = "modelo"
        enviar_mensagem(telefone, "Informe o *modelo da moto*.")
        return

    if etapa == "modelo":
        cliente["modelo"] = mensagem.strip()
        cliente["etapa"] = "ano_modelo"
        enviar_mensagem(telefone, "Informe o *ano/modelo* da moto.")
        return

    if etapa == "ano_modelo":
        cliente["ano_modelo"] = mensagem.strip()
        cliente["etapa"] = "revisao"
        enviar_mensagem(telefone, "Qual revisão deseja agendar?\nExemplo: *1*, *2*, *3*...")
        return

    if etapa == "revisao":
        cliente["revisao"] = mensagem.strip()
        cliente["etapa"] = "data_agendamento"
        enviar_mensagem(telefone, "Informe a *data desejada* no formato: *dd/mm/aaaa*")
        return

    if etapa == "data_agendamento":
        cliente["data_agendamento"] = mensagem.strip()
        horarios = horarios_disponiveis(cliente["revisao"], cliente["data_agendamento"])

        if not horarios:
            enviar_mensagem(
                telefone,
                "❌ Não há horários disponíveis para essa data/revisão.\n"
                "Envie outra data no formato *dd/mm/aaaa*."
            )
            return

        cliente["etapa"] = "horario_agendamento"
        texto_horarios = "\n".join(horarios)
        enviar_mensagem(
            telefone,
            f"Horários disponíveis:\n{texto_horarios}\n\n"
            "Responda apenas com o número da opção."
        )
        return

    if etapa == "horario_agendamento":
        horario_escolhido = opcao_para_horario(
            mensagem.strip(),
            cliente["revisao"],
            cliente["data_agendamento"]
        )

        if not horario_escolhido:
            horarios = horarios_disponiveis(cliente["revisao"], cliente["data_agendamento"])
            texto_horarios = "\n".join(horarios)
            enviar_mensagem(
                telefone,
                f"❌ Opção inválida.\n\nHorários disponíveis:\n{texto_horarios}\n\n"
                "Responda apenas com o número da opção."
            )
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
        cliente["item_adicional"] = "" if msg == "não" or msg == "nao" else mensagem.strip()
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
            f"🗓 Data: {cliente['data_agendamento']}\n"
            f"⏰ Horário: {cliente['horario_agendamento']}\n"
        )

        if cliente["item_adicional"]:
            resumo += f"🛠 Item adicional: {cliente['item_adicional']}\n"

        resumo += "\nNossa equipe entrará em contato se necessário.\n\nEquipe *Motoshow Yamaha*."

        enviar_mensagem(telefone, resumo)

        clientes.pop(telefone, None)
        return

    if etapa == "pecas":
        if msg == "humano":
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

            enviar_mensagem(telefone, "✅ Encaminhado para atendimento humano do setor de *Peças*.")
            return

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor="Peças",
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=mensagem.strip(),
            status="solicitação recebida"
        )

        enviar_mensagem(
            telefone,
            "✅ Sua solicitação de *Peças* foi registrada.\n"
            "Em breve nossa equipe retornará.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    if etapa == "acessorios":
        if msg == "humano":
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

            enviar_mensagem(telefone, "✅ Encaminhado para atendimento humano do setor de *Acessórios*.")
            return

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor="Acessórios",
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=mensagem.strip(),
            status="solicitação recebida"
        )

        enviar_mensagem(
            telefone,
            "✅ Sua solicitação de *Acessórios* foi registrada.\n"
            "Em breve nossa equipe retornará.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    if etapa == "garantia":
        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor="Garantia",
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=mensagem.strip(),
            status="solicitação recebida"
        )

        enviar_mensagem(
            telefone,
            "✅ Sua solicitação de *Garantia* foi registrada.\n"
            "Nossa equipe analisará e retornará em breve.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    if etapa == "atacado":
        if msg == "catálogo" or msg == "catalogo":
            link_pdf = f"{BASE_URL}/static/catalogo.pdf"
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

        salvar_atendimento(
            telefone=telefone,
            nome=cliente["nome"],
            setor="Logista/Atacado",
            atendimento_humano="não",
            origem=cliente["origem"],
            item_adicional=mensagem.strip(),
            status="solicitação recebida"
        )

        enviar_mensagem(
            telefone,
            "✅ Sua solicitação de *Logista / Atacado* foi registrada.\n"
            "Em breve nossa equipe retornará.\n\n"
            "Equipe *Motoshow Yamaha*."
        )
        clientes.pop(telefone, None)
        return

    if etapa == "aguardando_humano":
        # não reenviar menu enquanto atendimento humano estiver ativo
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

        # 1) IGNORA GRUPO
        if eh_grupo(payload):
            print("Mensagem de grupo ignorada.")
            return jsonify({"status": "ignored", "reason": "group_message"}), 200

        # 2) IGNORA MENSAGEM ENVIADA PELO PRÓPRIO BOT
        if eh_mensagem_do_proprio_bot(payload):
            print("Mensagem do próprio bot ignorada.")
            return jsonify({"status": "ignored", "reason": "from_me"}), 200

        telefone = extrair_telefone(payload)
        mensagem = extrair_mensagem_texto(payload)

        if not telefone or not mensagem:
            return jsonify({"status": "ignored", "reason": "missing_phone_or_message"}), 200

        processar_mensagem(telefone, mensagem)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print("Erro no webhook:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


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
                <h2>Itens adicionais mais vendidos</h2>
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