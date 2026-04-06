from flask import Flask, request, jsonify, render_template, send_from_directory
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

TEMPO_INATIVIDADE = 900
TEMPO_CACHE_MENSAGENS = 300

clientes = {}
mensagens_processadas = {}

# ==========================================
# BANCO DE DADOS
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///yamaha.db")

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
            "horario_agendamento": "",
            "origem": "menu normal",
            "setor": "",
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
        response = requests.post(
            url_envio,
            json=payload,
            headers=headers,
            timeout=20
        )
        print(f"ENVIO MENSAGEM [{telefone}] STATUS:", response.status_code)
        print("RESPOSTA Z-API:", response.text)
        return response.status_code in [200, 201]

    except Exception as e:
        print("Erro envio:", e)
        return False


def enviar_pdf(telefone, link):
    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "phone": telefone,
        "document": link,
        "fileName": "catalogo.pdf"
    }

    try:
        response = requests.post(
            url_documento,
            json=payload,
            headers=headers,
            timeout=20
        )
        print(f"ENVIO PDF [{telefone}] STATUS:", response.status_code)
        print("RESPOSTA Z-API PDF:", response.text)
        return response.status_code in [200, 201]

    except Exception as e:
        print("Erro PDF:", e)
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
        print("Erro salvar:", e)

    finally:
        db.close()


def menu_principal():
    return (
        "👋 Olá, bem-vindo ao *Pós-Vendas Motoshow Yamaha*\n\n"
        "Escolha uma opção:\n\n"
        "1️⃣ Agendar Revisão\n"
        "2️⃣ Peças\n"
        "3️⃣ Acessórios\n"
        "4️⃣ Garantia\n"
        "5️⃣ Logista / Atacado\n"
        "6️⃣ Atendimento Humano"
    )


def menu_modelos():
    texto = "🏍 Escolha o modelo:\n\n"
    for k, v in MODELOS.items():
        texto += f"{k} - {v}\n"
    return texto.strip()


def menu_revisoes():
    texto = "🔧 Escolha a revisão:\n\n"
    for k, v in REVISOES.items():
        texto += f"{k} - {v}\n"
    return texto.strip()


def menu_horarios():
    return (
        "Escolha horário:\n\n"
        "1 - 08:00\n"
        "2 - 09:00\n"
        "3 - 10:00\n"
        "4 - 11:00\n"
        "5 - 12:00\n"
        "6 - 13:00\n"
        "7 - 14:00\n"
        "8 - 15:00"
    )
# ==========================================
# INTEGRAÇÃO CAMPANHA
# ==========================================
def verificar_campanha(telefone, mensagem):
    db = SessionLocal()

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

        if not registro:
            return False

        msg = mensagem.strip().lower()

        if msg == "1":
            iniciar_cliente(telefone)

            clientes[telefone]["origem"] = "campanha"
            clientes[telefone]["setor"] = "Revisão"
            clientes[telefone]["etapa"] = "nome"
            clientes[telefone]["modelo"] = registro.modelo or ""

            registro.status = "respondido"
            db.commit()

            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\n"
                "Vamos agendar sua revisão.\n\n"
                "Informe seu *nome completo*."
            )
            return True

        if msg == "2":
            registro.status = "consultar_valores"
            db.commit()

            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\n"
                "Nossa equipe irá enviar os valores da revisão.\n\n"
                "Equipe *Motoshow Yamaha*"
            )
            return True

        if msg == "3":
            registro.status = "aguardando humano"
            registro.atendimento_humano = "sim"
            db.commit()

            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\n"
                "Encaminhando para atendimento humano.\n\n"
                "Equipe *Motoshow Yamaha*"
            )
            return True

        return False

    except Exception as e:
        db.rollback()
        print("Erro verificar_campanha:", e)
        return False

    finally:
        db.close()


# ==========================================
# PROCESSAR MENSAGEM
# ==========================================
def processar_mensagem(telefone, mensagem):
    iniciar_cliente(telefone)
    atualizar_interacao(telefone)

    msg = mensagem.lower().strip()
    etapa = clientes[telefone]["etapa"]

    # ==========================================
    # VERIFICAR CAMPANHA
    # ==========================================
    if verificar_campanha(telefone, msg):
        return

    # ==========================================
    # PALAVRAS DE ENTRADA
    # ==========================================
    if msg in ["menu", "oi", "olá", "ola", "iniciar", "começar", "comecar"]:
        clientes[telefone]["etapa"] = "menu"

        enviar_mensagem(
            telefone,
            menu_principal()
        )
        return

    # ==========================================
    # MENU PRINCIPAL
    # ==========================================
    if etapa == "menu":
        if msg == "1":
            clientes[telefone]["setor"] = "Revisão"
            clientes[telefone]["etapa"] = "nome"

            enviar_mensagem(
                telefone,
                "Informe seu *nome completo*"
            )
            return

        if msg == "2":
            clientes[telefone]["setor"] = "Peças"
            clientes[telefone]["etapa"] = "peca_nome"

            enviar_mensagem(
                telefone,
                "Informe a peça desejada"
            )
            return

        if msg == "3":
            clientes[telefone]["setor"] = "Acessórios"
            clientes[telefone]["etapa"] = "acessorio_nome"

            enviar_mensagem(
                telefone,
                "Informe o acessório desejado"
            )
            return

        if msg == "4":
            clientes[telefone]["setor"] = "Garantia"
            clientes[telefone]["etapa"] = "garantia_nome"

            enviar_mensagem(
                telefone,
                "Informe seu nome"
            )
            return

        if msg == "5":
            clientes[telefone]["setor"] = "Logista / Atacado"
            clientes[telefone]["etapa"] = "atacado_empresa"

            enviar_mensagem(
                telefone,
                "Informe o nome da empresa"
            )
            return

        if msg == "6":
            clientes[telefone]["setor"] = "Atendimento Humano"
            clientes[telefone]["atendimento_humano"] = True

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone]["nome"],
                setor="Atendimento Humano",
                atendimento_humano="sim",
                origem=clientes[telefone]["origem"],
                status="aguardando humano"
            )

            enviar_mensagem(
                telefone,
                "✅ Encaminhando para atendimento humano.\n\n"
                "Equipe *Motoshow Yamaha*"
            )
            return

        enviar_mensagem(telefone, menu_principal())
        return

    # ==========================================
    # FLUXO REVISÃO
    # ==========================================
    if etapa == "nome":
        clientes[telefone]["nome"] = mensagem.strip()

        # Se veio da campanha e já tinha modelo salvo, pula escolha do modelo
        if clientes[telefone]["origem"] == "campanha" and clientes[telefone]["modelo"]:
            clientes[telefone]["etapa"] = "revisao"
            enviar_mensagem(telefone, menu_revisoes())
            return

        clientes[telefone]["etapa"] = "modelo"
        enviar_mensagem(telefone, menu_modelos())
        return

    if etapa == "modelo":
        if msg not in MODELOS:
            enviar_mensagem(telefone, menu_modelos())
            return

        clientes[telefone]["modelo"] = MODELOS[msg]
        clientes[telefone]["etapa"] = "revisao"
        enviar_mensagem(telefone, menu_revisoes())
        return

    if etapa == "revisao":
        if msg not in REVISOES:
            enviar_mensagem(telefone, menu_revisoes())
            return

        clientes[telefone]["revisao"] = REVISOES[msg]
        clientes[telefone]["etapa"] = "horario_agendamento"
        enviar_mensagem(telefone, menu_horarios())
        return

    if etapa == "horario_agendamento":
        horarios = {
            "1": "08:00",
            "2": "09:00",
            "3": "10:00",
            "4": "11:00",
            "5": "12:00",
            "6": "13:00",
            "7": "14:00",
            "8": "15:00"
        }

        if msg not in horarios:
            enviar_mensagem(telefone, menu_horarios())
            return

        clientes[telefone]["horario_agendamento"] = horarios[msg]
        clientes[telefone]["etapa"] = "item_adicional"

        enviar_mensagem(
            telefone,
            "Deseja incluir algum item adicional?\n\n"
            "Exemplo: troca de óleo, pastilha, relação, pneu.\n\n"
            "Se não quiser, responda *não*."
        )
        return

    if etapa == "item_adicional":
        clientes[telefone]["item_adicional"] = "" if msg in ["não", "nao"] else mensagem.strip()

        salvar_atendimento(
            telefone=telefone,
            nome=clientes[telefone]["nome"],
            setor="Revisão",
            modelo=clientes[telefone]["modelo"],
            revisao=clientes[telefone]["revisao"],
            horario_agendamento=clientes[telefone]["horario_agendamento"],
            atendimento_humano="não",
            origem=clientes[telefone]["origem"],
            item_adicional=clientes[telefone]["item_adicional"],
            status="agendado"
        )

        resumo = (
            "✅ Agendamento realizado com sucesso\n\n"
            f"👤 Nome: {clientes[telefone]['nome']}\n"
            f"🏍 Modelo: {clientes[telefone]['modelo']}\n"
            f"🔧 Revisão: {clientes[telefone]['revisao']}\n"
            f"⏰ Horário: {clientes[telefone]['horario_agendamento']}\n"
        )

        if clientes[telefone]["item_adicional"]:
            resumo += f"🛠 Item adicional: {clientes[telefone]['item_adicional']}\n"

        resumo += "\nEquipe *Motoshow Yamaha*"

        enviar_mensagem(telefone, resumo)
        clientes.pop(telefone, None)
        return

    # ==========================================
    # FLUXOS SIMPLESMENTE REGISTRADOS
    # ==========================================
    if etapa == "peca_nome":
        salvar_atendimento(
            telefone=telefone,
            nome=clientes[telefone]["nome"],
            setor="Peças",
            origem=clientes[telefone]["origem"],
            item_adicional=f"Peça solicitada: {mensagem.strip()}",
            status="solicitação registrada"
        )
        enviar_mensagem(
            telefone,
            "✅ Solicitação de peça registrada.\n\n"
            "Equipe *Motoshow Yamaha*"
        )
        clientes.pop(telefone, None)
        return

    if etapa == "acessorio_nome":
        salvar_atendimento(
            telefone=telefone,
            nome=clientes[telefone]["nome"],
            setor="Acessórios",
            origem=clientes[telefone]["origem"],
            item_adicional=f"Acessório solicitado: {mensagem.strip()}",
            status="solicitação registrada"
        )
        enviar_mensagem(
            telefone,
            "✅ Solicitação de acessório registrada.\n\n"
            "Equipe *Motoshow Yamaha*"
        )
        clientes.pop(telefone, None)
        return

    if etapa == "garantia_nome":
        salvar_atendimento(
            telefone=telefone,
            nome=mensagem.strip(),
            setor="Garantia",
            origem=clientes[telefone]["origem"],
            status="solicitação registrada"
        )
        enviar_mensagem(
            telefone,
            "✅ Solicitação de garantia registrada.\n\n"
            "Equipe *Motoshow Yamaha*"
        )
        clientes.pop(telefone, None)
        return

    if etapa == "atacado_empresa":
        salvar_atendimento(
            telefone=telefone,
            nome=mensagem.strip(),
            setor="Logista / Atacado",
            origem=clientes[telefone]["origem"],
            status="solicitação registrada"
        )
        enviar_mensagem(
            telefone,
            "✅ Solicitação de atacado registrada.\n\n"
            "Equipe *Motoshow Yamaha*"
        )
        clientes.pop(telefone, None)
        return

    enviar_mensagem(telefone, menu_principal())
    # ==========================================
# EXTRAÇÃO / VALIDAÇÃO DE MENSAGENS
# ==========================================
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
    remover = []

    for msg_id, ts in list(mensagens_processadas.items()):
        if agora - ts > TEMPO_CACHE_MENSAGENS:
            remover.append(msg_id)

    for msg_id in remover:
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


# ==========================================
# INATIVIDADE
# ==========================================
def mensagem_encerramento():
    return (
        "⏰ Seu atendimento foi encerrado por inatividade.\n"
        "Quando quiser continuar, envie *menu*.\n\n"
        "Equipe *Motoshow Yamaha*."
    )


def monitorar_inatividade():
    while True:
        try:
            agora = time.time()
            remover = []

            for telefone, dados in list(clientes.items()):
                ultima = dados.get("ultima_interacao", agora)

                if agora - ultima > TEMPO_INATIVIDADE:
                    enviar_mensagem(telefone, mensagem_encerramento())
                    remover.append(telefone)

            for telefone in remover:
                clientes.pop(telefone, None)

        except Exception as e:
            print("Erro monitoramento:", e)

        time.sleep(30)


# ==========================================
# ROTAS
# ==========================================
@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"


@app.route("/static/<path:filename>")
def arquivos_estaticos(filename):
    return send_from_directory("static", filename)


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
        msg_id = extrair_id_mensagem(payload)

        if not telefone:
            print("Telefone não encontrado.")
            return jsonify({"status": "ignored", "reason": "phone_not_found"}), 200

        if not mensagem:
            print("Mensagem vazia.")
            return jsonify({"status": "ignored", "reason": "empty_message"}), 200

        if mensagem_ja_processada(msg_id):
            print("Mensagem duplicada ignorada:", msg_id)
            return jsonify({"status": "ignored", "reason": "duplicate"}), 200

        print("TELEFONE:", telefone)
        print("MENSAGEM:", mensagem)

        processar_mensagem(telefone, mensagem)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("ERRO WEBHOOK:", e)
        return jsonify({"status": "erro", "detalhe": str(e)}), 500


@app.route("/dashboard")
def dashboard():
    db = SessionLocal()

    try:
        total_atendimentos = db.query(func.count(Atendimento.id)).scalar() or 0

        total_humano = (
            db.query(func.count(Atendimento.id))
            .filter(Atendimento.atendimento_humano == "sim")
            .scalar()
            or 0
        )

        total_agendados = (
            db.query(func.count(Atendimento.id))
            .filter(Atendimento.status == "agendado")
            .scalar()
            or 0
        )

        por_setor = (
            db.query(Atendimento.setor, func.count(Atendimento.id))
            .group_by(Atendimento.setor)
            .all()
        )

        revisoes = (
            db.query(Atendimento.revisao, func.count(Atendimento.id))
            .filter(Atendimento.revisao != "")
            .group_by(Atendimento.revisao)
            .order_by(func.count(Atendimento.id).desc())
            .all()
        )

        itens = (
            db.query(Atendimento.item_adicional, func.count(Atendimento.id))
            .filter(Atendimento.item_adicional != "")
            .group_by(Atendimento.item_adicional)
            .order_by(func.count(Atendimento.id).desc())
            .all()
        )

        origens = (
            db.query(Atendimento.origem, func.count(Atendimento.id))
            .group_by(Atendimento.origem)
            .all()
        )

        return render_template(
            "dashboard.html",
            total_atendimentos=total_atendimentos,
            total_humano=total_humano,
            total_agendados=total_agendados,
            por_setor=por_setor,
            revisoes=revisoes,
            itens=itens,
            origens=origens,
            periodo="geral",
            periodo_label="Geral",
            total_agendamentos=total_agendados,
            total_pecas_acessorios=sum(
                qtd for setor, qtd in por_setor if setor in ["Peças", "Acessórios"]
            ),
            atendimento_humano=total_humano,
            setores_labels=[setor or "Não informado" for setor, _ in por_setor],
            setores_valores=[qtd for _, qtd in por_setor],
            origem_labels=[origem or "Não informado" for origem, _ in origens],
            origem_valores=[qtd for _, qtd in origens],
            dias=[],
            evolucao=[],
            ultimos=[],
            itens_top=[
                {"nome": item or "Não informado", "total": qtd}
                for item, qtd in itens[:10]
            ]
        )

    finally:
        db.close()


# ==========================================
# THREAD DE INATIVIDADE
# ==========================================
thread_inatividade = threading.Thread(
    target=monitorar_inatividade,
    daemon=True
)
thread_inatividade.start()


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)