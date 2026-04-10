from flask import Flask, request, jsonify, send_from_directory, render_template
import requests
import os
import time
from datetime import datetime
from collections import Counter, deque

from dotenv import load_dotenv

load_dotenv()

from database import criar_banco, SessionLocal, Atendimento
from ia_intencao import classificar_intencao

app = Flask(__name__)
criar_banco()

# ==========================================
# CONFIG
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "")
TEMPO_INATIVIDADE = int(os.getenv("TEMPO_INATIVIDADE", "900"))

url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"

clientes = {}
mensagens_processadas = set()
fila_mensagens = deque(maxlen=2000)

# ==========================================
# HOME
# ==========================================
@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"


# ==========================================
# LOG
# ==========================================
def log_info(*args):
    print("[INFO]", *args, flush=True)


def log_erro(*args):
    print("[ERRO]", *args, flush=True)


# ==========================================
# DASHBOARD
# ==========================================
@app.route("/dashboard")
def dashboard():
    db = SessionLocal()

    try:
        filtro = request.args.get("filtro", "hoje")

        hoje = datetime.now().date()
        inicio_semana = hoje.replace(day=hoje.day - hoje.weekday())
        inicio_mes = hoje.replace(day=1)

        query = db.query(Atendimento)

        if filtro == "hoje":
            query = query.filter(
                Atendimento.data >= datetime.combine(hoje, datetime.min.time())
            )

        elif filtro == "semana":
            query = query.filter(
                Atendimento.data >= datetime.combine(inicio_semana, datetime.min.time())
            )

        elif filtro == "mes":
            query = query.filter(
                Atendimento.data >= datetime.combine(inicio_mes, datetime.min.time())
            )

        total = query.count()

        revisao = query.filter(Atendimento.setor == "Revisão").count()

        agendados = query.filter(
            Atendimento.status == "Agendado"
        ).count()

        primeira = query.filter(Atendimento.revisao == "1").count()
        segunda = query.filter(Atendimento.revisao == "2").count()
        terceira = query.filter(Atendimento.revisao == "3").count()
        quarta = query.filter(Atendimento.revisao == "4").count()
        quinta = query.filter(Atendimento.revisao == "5").count()

        contador = Counter()

        itens = query.with_entities(Atendimento.itens).all()

        for item in itens:
            valor = item[0] if isinstance(item, tuple) else item

            if valor:
                lista = str(valor).split(",")

                for i in lista:
                    contador[i.strip()] += 1

        return render_template(
            "dashboard.html",
            total=total,
            revisao=revisao,
            agendados=agendados,
            primeira=primeira,
            segunda=segunda,
            terceira=terceira,
            quarta=quarta,
            quinta=quinta,
            protetor=contador["Protetor de motor"],
            slider=contador["Slider"],
            suporte=contador["Suporte para celular"],
            bau=contador["Baú"],
            filtro=contador["Filtro de ar"],
            pastilha=contador["Pastilha de freio"],
            filtro_ativo=filtro
        )

    except Exception as e:
        log_erro("Dashboard erro:", e)
        return "Erro dashboard", 500

    finally:
        db.close()


# ==========================================
# PDFS
# ==========================================
@app.route("/pdf/<path:arquivo>")
def servir_pdf(arquivo):
    pasta_pdfs = os.path.join(app.root_path)
    return send_from_directory(pasta_pdfs, arquivo)


# ==========================================
# UTILITÁRIOS
# ==========================================
def limpar_texto(texto):
    return str(texto or "").strip()


def normalizar_texto(texto):
    return limpar_texto(texto).lower()


def telefone_eh_grupo(telefone):
    telefone = str(telefone or "")
    return "@g.us" in telefone


def agora():
    return time.time()


def agora_datetime():
    return datetime.now()


def atualizar_interacao(telefone):
    if telefone in clientes:
        clientes[telefone]["ultima_interacao"] = agora()


def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = {
            "etapa": "menu",
            "ultima_interacao": agora(),
            "atendimento_humano": False,
            "modelo": "",
            "nome": "",
            "cpf": "",
            "ano": "",
            "revisao": "",
            "dia": "",
            "dia_texto": "",
            "data": "",
            "horario": "",
            "itens": "",
            "venda_adicional": "",
            "concluido": False,
            "horarios_disponiveis": []
        }


def resetar_cliente(telefone):
    clientes[telefone] = {
        "etapa": "menu",
        "ultima_interacao": agora(),
        "atendimento_humano": False,
        "modelo": "",
        "nome": "",
        "cpf": "",
        "ano": "",
        "revisao": "",
        "dia": "",
        "dia_texto": "",
        "data": "",
        "horario": "",
        "itens": "",
        "venda_adicional": "",
        "concluido": False,
        "horarios_disponiveis": []
    }


def ativar_atendimento_humano(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["etapa"] = "atendimento_humano"
    clientes[telefone]["ultima_interacao"] = agora()

    enviar_mensagem(
        telefone,
        "👨‍💼 *Atendimento humano acionado.*\n\n"
        "Nossa equipe seguirá com você por aqui.\n"
        "Quando quiser voltar ao menu automático, envie *menu*."
    )


def processar_inatividade():
    try:
        agora_atual = agora()

        for telefone in list(clientes.keys()):
            dados = clientes.get(telefone, {})
            ultima = dados.get("ultima_interacao", agora_atual)

            if agora_atual - ultima > TEMPO_INATIVIDADE:
                if dados.get("etapa") != "menu":
                    enviar_mensagem(
                        telefone,
                        "⏰ Seu atendimento foi encerrado por inatividade.\n\n"
                        "Quando quiser continuar, envie *menu*."
                    )
                resetar_cliente(telefone)

    except Exception as e:
        log_erro("Erro ao processar inatividade:", e)


# ==========================================
# IGNORAR EVENTOS DO PRÓPRIO BOT
# ==========================================
def evento_eh_do_proprio_bot(payload):
    try:
        data = payload.get("data", {}) or {}

        marcadores_true = [
            payload.get("fromMe"),
            payload.get("isFromMe"),
            payload.get("sentByMe"),
            data.get("fromMe"),
            data.get("isFromMe"),
            data.get("sentByMe"),
            data.get("isStatusReply"),
        ]

        if any(valor is True for valor in marcadores_true):
            return True

        sender = str(
            data.get("sender")
            or data.get("from")
            or payload.get("sender")
            or payload.get("from")
            or ""
        ).lower()

        if sender in ["api", "system", "bot"]:
            return True

        texto_evento = str(
            data.get("event")
            or payload.get("event")
            or ""
        ).lower()

        if texto_evento in ["sent", "message_sent", "outbound_message"]:
            return True

        return False
    except Exception as e:
        log_erro("Erro ao validar evento do proprio bot:", e)
        return False


# ==========================================
# MENSAGENS DUPLICADAS
# ==========================================
def extrair_message_id(payload):
    try:
        data = payload.get("data", {}) or {}
        return (
            data.get("id")
            or data.get("messageId")
            or payload.get("messageId")
            or payload.get("id")
            or ""
        )
    except Exception:
        return ""


def mensagem_ja_processada(message_id):
    if not message_id:
        return False
    return message_id in mensagens_processadas


def registrar_mensagem_processada(message_id):
    if not message_id:
        return

    if len(fila_mensagens) >= fila_mensagens.maxlen:
        antigo = fila_mensagens.popleft()
        mensagens_processadas.discard(antigo)

    fila_mensagens.append(message_id)
    mensagens_processadas.add(message_id)


# ==========================================
# EXTRAÇÃO
# ==========================================
def extrair_telefone(payload):
    try:
        data = payload.get("data", {}) or {}

        return (
            data.get("phone")
            or data.get("chatId")
            or data.get("from")
            or payload.get("phone")
            or payload.get("chatId")
            or payload.get("from")
            or ""
        )
    except Exception as e:
        log_erro("Erro ao extrair telefone:", e)
        return ""


def extrair_texto(payload):
    try:
        data = payload.get("data", {}) or {}

        candidatos = [
            # dentro de data
            data.get("text", {}).get("message") if isinstance(data.get("text"), dict) else None,
            data.get("text") if isinstance(data.get("text"), str) else None,
            data.get("body"),
            data.get("message"),
            data.get("caption"),
            data.get("extendedTextMessage", {}).get("text") if isinstance(data.get("extendedTextMessage"), dict) else None,
            data.get("conversation"),
            data.get("selectedButtonId"),
            data.get("selectedDisplayText"),
            data.get("singleSelectReply", {}).get("selectedRowId") if isinstance(data.get("singleSelectReply"), dict) else None,
            data.get("singleSelectReply", {}).get("title") if isinstance(data.get("singleSelectReply"), dict) else None,

            # no nível principal do payload
            payload.get("text", {}).get("message") if isinstance(payload.get("text"), dict) else None,
            payload.get("text") if isinstance(payload.get("text"), str) else None,
            payload.get("body"),
            payload.get("message"),
            payload.get("caption"),
            payload.get("extendedTextMessage", {}).get("text") if isinstance(payload.get("extendedTextMessage"), dict) else None,
            payload.get("conversation"),
            payload.get("selectedButtonId"),
            payload.get("selectedDisplayText"),
            payload.get("singleSelectReply", {}).get("selectedRowId") if isinstance(payload.get("singleSelectReply"), dict) else None,
            payload.get("singleSelectReply", {}).get("title") if isinstance(payload.get("singleSelectReply"), dict) else None,
        ]

        for valor in candidatos:
            if valor is not None and str(valor).strip():
                return str(valor).strip()

        return ""
    except Exception as e:
        log_erro("Erro ao extrair texto:", e)
        return ""

# ==========================================
# ENVIO DE MENSAGEM
# ==========================================
def headers_zapi():
    return {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }


def enviar_mensagem(telefone, mensagem):
    payload = {
        "phone": telefone,
        "message": mensagem
    }

    try:
        log_info("Enviando mensagem para:", telefone)
        log_info("Payload envio:", payload)

        response = requests.post(
            url_envio,
            json=payload,
            headers=headers_zapi(),
            timeout=30
        )

        log_info("Status envio:", response.status_code)
        log_info("Resposta Z-API:", response.text)

        if 200 <= response.status_code < 300:
            log_info("Mensagem enviada com sucesso:", telefone)
            return True

        log_erro("Falha envio:", response.status_code, response.text)
        return False

    except Exception as e:
        log_erro("Erro envio:", e)
        return False


def enviar_documento_pdf(telefone, arquivo_pdf, nome_exibicao=None, legenda="📄 Catálogo Atacado Motoshow Yamaha"):
    try:
        if not BASE_URL:
            log_erro("BASE_URL não configurada para envio de PDF.")
            return False

        nome_exibicao = nome_exibicao or arquivo_pdf
        link_pdf = f"{BASE_URL}/pdf/{arquivo_pdf}"

        payload = {
            "phone": telefone,
            "document": link_pdf,
            "fileName": nome_exibicao,
            "caption": legenda
        }

        log_info("Enviando PDF para:", telefone)
        log_info("Payload PDF:", payload)

        response = requests.post(
            url_documento,
            json=payload,
            headers=headers_zapi(),
            timeout=60
        )

        log_info("Status PDF:", response.status_code)
        log_info("Resposta PDF:", response.text)

        if 200 <= response.status_code < 300:
            return True

        return False

    except Exception as e:
        log_erro("Erro envio PDF:", e)
        return False


# ==========================================
# MENU
# ==========================================
def enviar_menu(telefone):
    mensagem = (
        "Olá 👋\n\n"
        "🏍️ *Pós-Vendas Motoshow Yamaha*\n\n"
        "Escolha uma opção abaixo:\n\n"
        "1️⃣ Agendar Revisão\n"
        "2️⃣ Peças\n"
        "3️⃣ Acessórios\n"
        "4️⃣ Garantia\n"
        "5️⃣ Logista / Atacado\n"
        "6️⃣ Falar com Atendente\n\n"
        "Digite apenas o número da opção desejada.\n\n"
        "Equipe Motoshow Yamaha"
    )
    enviar_mensagem(telefone, mensagem)


# ==========================================
# IA INTENÇÃO
# ==========================================
def tratar_intencao_ia(telefone, texto):
    try:
        resultado = classificar_intencao(texto)
        log_info("Resultado IA:", resultado)
    except Exception as e:
        log_erro("Erro na IA de intenção:", e)
        return False

    if not resultado:
        return False

    intent = str(resultado).strip().lower()

    if intent in ["revisao", "agendar_revisao"]:
        clientes[telefone]["etapa"] = "revisao_modelo"
        enviar_mensagem(
            telefone,
            "🔧 *Agendamento de Revisão*\n\n"
            "Informe o *modelo da moto*:"
        )
        return True

    if intent == "menu":
        resetar_cliente(telefone)
        enviar_menu(telefone)
        return True

    if intent == "humano":
        ativar_atendimento_humano(telefone)
        return True

    if intent == "pecas":
        enviar_mensagem(
            telefone,
            "🔩 *Peças*\n\n"
            "Informe a *peça desejada* para seguirmos com o atendimento."
        )
        return True

    if intent == "acessorios":
        enviar_mensagem(
            telefone,
            "🛵 *Acessórios*\n\n"
            "Informe o *acessório desejado* para seguirmos com o atendimento."
        )
        return True

    if intent == "garantia":
        enviar_mensagem(
            telefone,
            "🛡️ *Garantia*\n\n"
            "Descreva sua solicitação de garantia para seguirmos com o atendimento."
        )
        return True

    if intent == "atacado":
        clientes[telefone]["etapa"] = "submenu_atacado"
        enviar_mensagem(
            telefone,
            "📦 *Logista / Atacado*\n\n"
            "Digite uma opção:\n\n"
            "1 - Solicitar cotação\n"
            "2 - Cadastro de logista\n"
            "3 - Receber catálogo\n"
            "4 - Falar com consultor"
        )
        return True

    return False


# ==========================================
# HORÁRIOS
# ==========================================
def nome_dia(opcao):
    mapa = {
        "1": "Segunda",
        "2": "Terça",
        "3": "Quarta",
        "4": "Quinta",
        "5": "Sexta",
        "6": "Sábado"
    }
    return mapa.get(str(opcao), "")


def gerar_horarios_disponiveis(revisao, dia):
    revisao = str(revisao).strip()
    dia = str(dia).strip()

    if dia in ["1", "2", "3", "4", "5"]:
        if revisao in ["1", "2"]:
            return [
                "08:00", "09:00", "10:00", "11:00",
                "12:00", "13:00", "14:00", "15:00"
            ]
        return ["08:00"]

    if dia == "6":
        if revisao in ["1", "2"]:
            return ["08:00", "09:00", "10:00"]
        return []

    return []


def montar_mensagem_horarios(horarios):
    mensagem = "⏰ *Escolha o horário:*\n\n"
    for i, horario in enumerate(horarios, start=1):
        mensagem += f"{i} - {horario}\n"
    return mensagem


# ==========================================
# SALVAR ATENDIMENTO COM SEGURANÇA
# ==========================================
def salvar_atendimento_seguro(dados):
    db = SessionLocal()
    try:
        atendimento = Atendimento()

        for campo, valor in dados.items():
            if hasattr(atendimento, campo):
                setattr(atendimento, campo, valor)

        db.add(atendimento)
        db.commit()
        log_info("Atendimento salvo com sucesso.")
        return True

    except Exception as e:
        db.rollback()
        log_erro("Erro salvar atendimento:", e)
        return False

    finally:
        db.close()


# ==========================================
# WEBHOOK
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Webhook ativo"}), 200

    processar_inatividade()

    payload = request.get_json(silent=True) or {}
    log_info("PAYLOAD RECEBIDO:", payload)

    if evento_eh_do_proprio_bot(payload):
        return jsonify({"status": "ignorado", "motivo": "evento do proprio bot"}), 200

    telefone = extrair_telefone(payload)
    texto = limpar_texto(extrair_texto(payload))
    texto_normalizado = normalizar_texto(texto)
    message_id = extrair_message_id(payload)

    log_info("Telefone extraído:", telefone)
    log_info("Texto extraído:", texto)
    log_info("Texto extraído repr:", repr(texto))
    log_info("Message ID:", message_id)

    if not telefone:
        return jsonify({"status": "ignorado", "motivo": "telefone ausente"}), 200

    if telefone_eh_grupo(telefone):
        return jsonify({"status": "ignorado", "motivo": "grupo"}), 200

    if mensagem_ja_processada(message_id):
        return jsonify({"status": "ignorado", "motivo": "duplicada"}), 200

    registrar_mensagem_processada(message_id)

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)

    log_info("Etapa atual antes do fluxo:", clientes.get(telefone, {}).get("etapa"))

    if not texto:
        log_info("Mensagem ignorada: texto vazio")
        return jsonify({"status": "ignorado", "motivo": "texto vazio"}), 200

    # ==========================================
    # COMANDOS GERAIS
    # ==========================================
    if texto_normalizado in ["menu", "oi", "ola", "olá", "bom dia", "boa tarde", "boa noite"]:
        resetar_cliente(telefone)
        enviar_menu(telefone)
        return jsonify({"status": "ok", "acao": "menu"}), 200

    if clientes[telefone].get("atendimento_humano") and texto_normalizado != "menu":
        return jsonify({"status": "ok", "modo": "humano"}), 200

    etapa = clientes[telefone]["etapa"]

    # ==========================================
    # IA NO MENU
    # ==========================================
    if etapa == "menu" and texto and texto not in ["1", "2", "3", "4", "5", "6"]:
        if tratar_intencao_ia(telefone, texto):
            return jsonify({"status": "ok", "origem": "ia"}), 200

    # ==========================================
    # MENU
    # ==========================================
    if etapa == "menu":
        opcao = (
            texto.replace("️⃣", "")
            .replace("\u200e", "")
            .replace("\u200f", "")
            .strip()
        )

        log_info("Opcao tratada no menu:", repr(opcao))

        if opcao == "1":
            clientes[telefone]["etapa"] = "revisao_modelo"
            enviar_mensagem(
                telefone,
                "🔧 *Agendamento de Revisão*\n\n"
                "Informe o *modelo da moto*:"
            )
            return jsonify({"status": "ok", "fluxo": "revisao_modelo"}), 200

        elif opcao == "2":
            enviar_mensagem(
                telefone,
                "🔩 *Peças*\n\n"
                "Informe a *peça desejada* para seguirmos com o atendimento."
            )
            return jsonify({"status": "ok", "fluxo": "pecas"}), 200

        elif opcao == "3":
            enviar_mensagem(
                telefone,
                "🛵 *Acessórios*\n\n"
                "Informe o *acessório desejado* para seguirmos com o atendimento."
            )
            return jsonify({"status": "ok", "fluxo": "acessorios"}), 200

        elif opcao == "4":
            enviar_mensagem(
                telefone,
                "🛡️ *Garantia*\n\n"
                "Descreva sua solicitação de garantia para seguirmos com o atendimento."
            )
            return jsonify({"status": "ok", "fluxo": "garantia"}), 200

        elif opcao == "5":
            clientes[telefone]["etapa"] = "submenu_atacado"
            enviar_mensagem(
                telefone,
                "📦 *Logista / Atacado*\n\n"
                "Digite uma opção:\n\n"
                "1 - Solicitar cotação\n"
                "2 - Cadastro de logista\n"
                "3 - Receber catálogo\n"
                "4 - Falar com consultor"
            )
            return jsonify({"status": "ok", "fluxo": "submenu_atacado"}), 200

        elif opcao == "6":
            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok", "fluxo": "humano"}), 200

        else:
            log_info("Opção inválida no menu. Texto recebido:", repr(texto))
            enviar_menu(telefone)
            return jsonify({"status": "ok", "fluxo": "menu_reenviado"}), 200

    # ==========================================
    # SUBMENU ATACADO
    # ==========================================
    elif etapa == "submenu_atacado":
        opcao = (
            texto.replace("️⃣", "")
            .replace("\u200e", "")
            .replace("\u200f", "")
            .strip()
        )

        if opcao == "1":
            ativar_atendimento_humano(telefone)
            enviar_mensagem(
                telefone,
                "📦 *Solicitação de Cotação*\n\n"
                "Envie:\n"
                "• Empresa\n"
                "• CNPJ\n"
                "• Cidade\n"
                "• Peças desejadas"
            )
            return jsonify({"status": "ok"}), 200

        elif opcao == "2":
            ativar_atendimento_humano(telefone)
            enviar_mensagem(
                telefone,
                "📝 *Cadastro de Logista*\n\n"
                "Envie:\n"
                "• Empresa\n"
                "• CNPJ\n"
                "• Responsável\n"
                "• Cidade\n"
                "• Telefone"
            )
            return jsonify({"status": "ok"}), 200

        elif opcao == "3":
            ok = enviar_documento_pdf(
                telefone,
                "catalogo-atacado.pdf",
                nome_exibicao="catalogo-atacado.pdf",
                legenda="📄 Catálogo Atacado Motoshow Yamaha"
            )

            if ok:
                enviar_mensagem(
                    telefone,
                    "✅ Catálogo enviado com sucesso.\n\n"
                    "Equipe Motoshow Yamaha"
                )
            else:
                enviar_mensagem(
                    telefone,
                    "⚠️ Não consegui enviar o catálogo agora.\n"
                    "Tente novamente em instantes ou envie *menu*."
                )

            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        elif opcao == "4":
            ativar_atendimento_humano(telefone)
            return jsonify({"status": "ok"}), 200

        else:
            enviar_mensagem(
                telefone,
                "❌ Opção inválida.\n\n"
                "Digite:\n"
                "1 - Solicitar cotação\n"
                "2 - Cadastro de logista\n"
                "3 - Receber catálogo\n"
                "4 - Falar com consultor"
            )
            return jsonify({"status": "ok"}), 200

    # ==========================================
    # FLUXO REVISÃO
    # ==========================================
    elif etapa == "revisao_modelo":
        clientes[telefone]["modelo"] = texto
        clientes[telefone]["etapa"] = "revisao_nome"

        enviar_mensagem(
            telefone,
            "👤 Informe seu *nome completo*:"
        )
        return jsonify({"status": "ok"}), 200

    elif etapa == "revisao_nome":
        clientes[telefone]["nome"] = texto
        clientes[telefone]["etapa"] = "revisao_cpf"

        enviar_mensagem(
            telefone,
            "📄 Informe o *CPF do proprietário*:"
        )
        return jsonify({"status": "ok"}), 200

    elif etapa == "revisao_cpf":
        clientes[telefone]["cpf"] = texto
        clientes[telefone]["etapa"] = "revisao_ano"

        enviar_mensagem(
            telefone,
            "📅 Informe o *ano da moto*:"
        )
        return jsonify({"status": "ok"}), 200

    elif etapa == "revisao_ano":
        clientes[telefone]["ano"] = texto
        clientes[telefone]["etapa"] = "revisao_tipo"

        enviar_mensagem(
            telefone,
            "🔧 *Qual revisão deseja agendar?*\n\n"
            "1 - 1ª revisão\n"
            "2 - 2ª revisão\n"
            "3 - 3ª revisão\n"
            "4 - 4ª revisão\n"
            "5 - 5ª ou acima"
        )
        return jsonify({"status": "ok"}), 200

    elif etapa == "revisao_tipo":
        opcao = (
            texto.replace("️⃣", "")
            .replace("\u200e", "")
            .replace("\u200f", "")
            .strip()
        )

        if opcao not in ["1", "2", "3", "4", "5"]:
            enviar_mensagem(
                telefone,
                "❌ Opção inválida.\n\n"
                "Digite:\n"
                "1 - 1ª\n"
                "2 - 2ª\n"
                "3 - 3ª\n"
                "4 - 4ª\n"
                "5 - 5ª+"
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["revisao"] = opcao
        clientes[telefone]["etapa"] = "revisao_dia"

        enviar_mensagem(
            telefone,
            "📅 *Escolha o dia da semana:*\n\n"
            "1 - Segunda\n"
            "2 - Terça\n"
            "3 - Quarta\n"
            "4 - Quinta\n"
            "5 - Sexta\n"
            "6 - Sábado"
        )
        return jsonify({"status": "ok"}), 200

    elif etapa == "revisao_dia":
        opcao = (
            texto.replace("️⃣", "")
            .replace("\u200e", "")
            .replace("\u200f", "")
            .strip()
        )

        if opcao not in ["1", "2", "3", "4", "5", "6"]:
            enviar_mensagem(
                telefone,
                "❌ Dia inválido.\n\n"
                "Digite um número de 1 a 6."
            )
            return jsonify({"status": "ok"}), 200

        horarios = gerar_horarios_disponiveis(
            clientes[telefone]["revisao"],
            opcao
        )

        if not horarios:
            enviar_mensagem(
                telefone,
                "⚠️ Para essa revisão não há atendimento no dia selecionado.\n\n"
                "Escolha outro dia:\n"
                "1 - Segunda\n"
                "2 - Terça\n"
                "3 - Quarta\n"
                "4 - Quinta\n"
                "5 - Sexta\n"
                "6 - Sábado"
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["dia"] = opcao
        clientes[telefone]["dia_texto"] = nome_dia(opcao)
        clientes[telefone]["horarios_disponiveis"] = horarios
        clientes[telefone]["etapa"] = "revisao_data"

        enviar_mensagem(
            telefone,
            "📆 Informe a *data desejada* do agendamento:\n"
            "Exemplo: 15/04/2026"
        )
        return jsonify({"status": "ok"}), 200

    elif etapa == "revisao_data":
        clientes[telefone]["data"] = texto
        clientes[telefone]["etapa"] = "revisao_horario"

        enviar_mensagem(
            telefone,
            montar_mensagem_horarios(
                clientes[telefone].get("horarios_disponiveis", ["08:00"])
            )
        )
        return jsonify({"status": "ok"}), 200

    elif etapa == "revisao_horario":
        horarios = clientes[telefone].get("horarios_disponiveis", [])

        if not horarios:
            clientes[telefone]["etapa"] = "revisao_dia"
            enviar_mensagem(
                telefone,
                "⚠️ Não encontrei horários disponíveis. Vamos escolher o dia novamente."
            )
            return jsonify({"status": "ok"}), 200

        try:
            indice = int(
                texto.replace("️⃣", "")
                .replace("\u200e", "")
                .replace("\u200f", "")
                .strip()
            ) - 1
            horario_escolhido = horarios[indice]
        except Exception:
            enviar_mensagem(
                telefone,
                montar_mensagem_horarios(horarios)
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["horario"] = horario_escolhido
        clientes[telefone]["etapa"] = "revisao_confirmar"

        enviar_mensagem(
            telefone,
            "✅ *Confira seu agendamento:*\n\n"
            f"👤 Nome: {clientes[telefone]['nome']}\n"
            f"🏍️ Modelo: {clientes[telefone]['modelo']}\n"
            f"📄 CPF: {clientes[telefone]['cpf']}\n"
            f"📅 Data: {clientes[telefone]['data']}\n"
            f"📍 Dia: {clientes[telefone]['dia_texto']}\n"
            f"⏰ Horário: {clientes[telefone]['horario']}\n"
            f"🔧 Revisão: {clientes[telefone]['revisao']}ª\n\n"
            "Digite:\n"
            "1 - Confirmar\n"
            "2 - Cancelar"
        )
        return jsonify({"status": "ok"}), 200

    elif etapa == "revisao_confirmar":
        opcao = (
            texto.replace("️⃣", "")
            .replace("\u200e", "")
            .replace("\u200f", "")
            .strip()
        )

        if opcao == "2":
            resetar_cliente(telefone)
            enviar_mensagem(
                telefone,
                "❌ Agendamento cancelado.\n\n"
                "Envie *menu* para iniciar novamente."
            )
            return jsonify({"status": "ok"}), 200

        if opcao != "1":
            enviar_mensagem(
                telefone,
                "Digite:\n"
                "1 - Confirmar\n"
                "2 - Cancelar"
            )
            return jsonify({"status": "ok"}), 200

        salvar_atendimento_seguro({
            "telefone": telefone,
            "nome": clientes[telefone]["nome"],
            "setor": "Revisão",
            "modelo": clientes[telefone]["modelo"],
            "ano": clientes[telefone]["ano"],
            "revisao": clientes[telefone]["revisao"],
            "cpf": clientes[telefone]["cpf"],
            "dia_semana": clientes[telefone]["dia_texto"],
            "data_agendada": clientes[telefone]["data"],
            "horario": clientes[telefone]["horario"],
            "itens": clientes[telefone].get("itens", ""),
            "venda_adicional": clientes[telefone].get("venda_adicional", ""),
            "origem": "Bot",
            "status": "Agendado",
            "etapa": "revisao_confirmada",
            "atendimento_humano": False,
            "concluido": True,
            "ultima_interacao": agora_datetime(),
            "data": agora_datetime()
        })

        enviar_mensagem(
            telefone,
            "✅ *Revisão agendada com sucesso!*\n\n"
            f"👤 {clientes[telefone]['nome']}\n"
            f"🏍️ {clientes[telefone]['modelo']}\n"
            f"📄 CPF: {clientes[telefone]['cpf']}\n"
            f"📅 {clientes[telefone]['data']}\n"
            f"📍 {clientes[telefone]['dia_texto']}\n"
            f"⏰ {clientes[telefone]['horario']}\n\n"
            "Agradecemos o contato.\n"
            "Equipe Motoshow Yamaha"
        )

        resetar_cliente(telefone)
        return jsonify({"status": "ok"}), 200

    return jsonify({"status": "ok"}), 200


# ==========================================
# EXECUÇÃO
# ==========================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)