from flask import Flask, request, jsonify, send_from_directory, render_template
import requests
import os
import json
import threading
import time
from datetime import datetime
from collections import Counter

from dotenv import load_dotenv
from sqlalchemy import func

from database import criar_banco, SessionLocal, Atendimento, Disparo, LeadAtacado

load_dotenv()

app = Flask(__name__)
criar_banco()
# ==========================================
# TESTE BANCO
# ==========================================
@app.route("/test-banco")
def test_banco():
    db = SessionLocal()
    try:
        total = db.query(Atendimento).count()
        return {
            "status": "ok",
            "total_atendimentos": total
        }, 200
    except Exception as e:
        return {
            "status": "erro",
            "detalhe": str(e)
        }, 500
    finally:
        db.close()


@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"
# ==========================================
# CONFIG
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://yamaha-bot-1.onrender.com")
TEMPO_INATIVIDADE = int(os.getenv("TEMPO_INATIVIDADE", "600"))

url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"

clientes = {}
mensagens_processadas = set()
ARQUIVO_JSON = "atendimentos.json"

MODELOS_YAMAHA = [
    "FAZER 250", "FZ15", "CROSSER", "LANDER", "MT03", "MT07",
    "R15", "R3", "FLUO", "NEO", "NMAX", "TENERE 700", "AEROX"
]


# ==========================================
# UTILITÁRIOS GERAIS
# ==========================================
def log_info(*args):
    print("[INFO]", *args, flush=True)


def log_erro(*args):
    print("[ERRO]", *args, flush=True)


def carregar_json():
    if not os.path.exists(ARQUIVO_JSON):
        with open(ARQUIVO_JSON, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

    try:
        with open(ARQUIVO_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_erro("Falha ao carregar JSON:", e)
        return []


def salvar_json_registro(registro):
    try:
        dados = carregar_json()
        dados.append(registro)
        with open(ARQUIVO_JSON, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_erro("Falha ao salvar JSON:", e)


def telefone_eh_grupo(telefone):
    return "@g.us" in str(telefone)


def limpar_texto(texto):
    return str(texto or "").strip()


def normalizar_texto(texto):
    return limpar_texto(texto).lower()


def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = {
            "etapa": "menu",
            "ultima_interacao": time.time(),
            "atendimento_humano": False,
            "origem": "Menu Normal",
            "nome_cliente": "",
            "modelo_moto": "",
            "ano_moto": "",
            "revisao_numero": "",
            "dia_semana": "",
            "horario_escolhido": "",
            "itens": [],
            "setor": "",
            "peca_nome": "",
            "acessorio_nome": "",
            "empresa": "",
            "cnpj": "",
            "cidade": "",
            "cpf": "",
            "descricao": "",
            "responsavel": "",
            "telefone_empresa": "",
            "mensagem_original": ""
        }


def atualizar_interacao(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["ultima_interacao"] = time.time()


def resetar_cliente(telefone, manter_origem=False):
    origem_atual = clientes.get(telefone, {}).get("origem", "Menu Normal")
    clientes[telefone] = {
        "etapa": "menu",
        "ultima_interacao": time.time(),
        "atendimento_humano": False,
        "origem": origem_atual if manter_origem else "Menu Normal",
        "nome_cliente": "",
        "modelo_moto": "",
        "ano_moto": "",
        "revisao_numero": "",
        "dia_semana": "",
        "horario_escolhido": "",
        "itens": [],
        "setor": "",
        "peca_nome": "",
        "acessorio_nome": "",
        "empresa": "",
        "cnpj": "",
        "cidade": "",
        "cpf": "",
        "descricao": "",
        "responsavel": "",
        "telefone_empresa": "",
        "mensagem_original": ""
    }


def resposta_fallback(telefone):

    etapa = clientes.get(telefone, {}).get("etapa")

    if etapa == "escolher_dia":
        enviar_dias(telefone)
        return

    elif etapa == "escolher_horario":
        enviar_horarios(telefone)
        return

    elif etapa == "escolher_revisao":
        enviar_revisoes(telefone)
        return

    elif etapa == "modelo":
        enviar_modelos(telefone)
        return

    elif etapa == "venda_adicional":
        enviar_venda_adicional(telefone)
        return

    enviar_mensagem(
        telefone,
        "Não entendi sua resposta 🤖\n\nDigite uma opção válida ou digite *menu* para voltar ao início.\n\nEquipe Motoshow Yamaha"
    )


def headers_zapi():
    return {
        "Client-Token": ZAPI_CLIENT_TOKEN
    }


def enviar_mensagem(telefone, mensagem):
    payload = {
        "phone": telefone,
        "message": mensagem
    }

    try:
        print("URL_ENVIO:", url_envio)
        print("PAYLOAD_ENVIO:", payload)

        r = requests.post(url_envio, json=payload, headers=headers_zapi(), timeout=30)

        print("RESPOSTA_ZAPI:", r.text)
        log_info("Envio mensagem:", telefone, "status:", r.status_code)
        return r.ok

    except Exception as e:
        log_erro("Erro ao enviar mensagem:", e)
        return False


def enviar_catalogo(telefone):
    payload = {
        "phone": telefone,
        "document": f"{BASE_URL}/pdf/catalogo-atacado.pdf",
        "fileName": "catalogo-atacado.pdf",
        "caption": "📄 Catálogo Atacado Motoshow Yamaha"
    }

    try:
        r = requests.post(url_documento, json=payload, headers=headers_zapi(), timeout=30)
        log_info("Envio catálogo:", telefone, "status:", r.status_code)
        return r.ok
    except Exception as e:
        log_erro("Erro ao enviar catálogo:", e)
        return False


def salvar_atendimento(
    telefone,
    nome="",
    setor="",
    modelo="",
    ano="",
    revisao="",
    horario="",
    itens="",
    origem="Menu Normal",
    status="Em atendimento",
    atendimento_humano=False
):
    db = SessionLocal()
    try:
        atendimento = Atendimento(
            telefone=telefone,
            nome=nome,
            setor=setor,
            modelo=modelo,
            ano=ano,
            revisao=revisao,
            horario=horario,
            itens=itens,
            origem=origem,
            status=status,
            atendimento_humano=atendimento_humano
        )
        db.add(atendimento)
        db.commit()

        salvar_json_registro({
            "telefone": telefone,
            "nome": nome,
            "setor": setor,
            "modelo": modelo,
            "ano": ano,
            "revisao": revisao,
            "horario": horario,
            "itens": itens,
            "origem": origem,
            "status": status,
            "atendimento_humano": atendimento_humano,
            "data": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

    except Exception as e:
        log_erro("Erro ao salvar atendimento:", e)
    finally:
        db.close()
        # ==========================================
# EXTRAÇÃO DE PAYLOAD Z-API
# ==========================================
def extrair_payload_base(payload):
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def extrair_telefone(payload):
    base = extrair_payload_base(payload)

    candidatos = [
        base.get("phone"),
        base.get("chatLid"),
        base.get("from"),
        base.get("sender"),
        base.get("jid"),
    ]

    if isinstance(base.get("sender"), dict):
        candidatos.extend([
            base["sender"].get("phone"),
            base["sender"].get("id"),
        ])

    for c in candidatos:
        if c:
            return str(c)

    return ""


def extrair_mensagem_texto(payload):
    try:
        base = extrair_payload_base(payload)

        # Formato novo Z-API
        text = base.get("text")

        if isinstance(text, dict):
            mensagem = text.get("message")
            if mensagem:
                return mensagem.strip()

        if isinstance(text, str):
            return text.strip()

        message = base.get("message")

        if isinstance(message, dict):
            for campo in ["text", "body", "caption", "message"]:
                valor = message.get(campo)
                if isinstance(valor, str) and valor.strip():
                    return valor.strip()

        for campo in ["body", "caption", "message"]:
            valor = base.get(campo)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()

        return ""

    except Exception as e:
        print("Erro ao extrair mensagem:", e)
        return ""

    return ""


def extrair_message_id(payload):
    base = extrair_payload_base(payload)

    possibilidades = [
        base.get("messageId"),
        base.get("id"),
        base.get("msgId"),
    ]

    if isinstance(base.get("message"), dict):
        possibilidades.append(base["message"].get("id"))

    for p in possibilidades:
        if p:
            return str(p)

    return f"sem-id-{time.time()}"


def evento_eh_do_proprio_bot(payload):
    base = extrair_payload_base(payload)

    if base.get("fromMe") is True:
        return True

    if isinstance(base.get("message"), dict) and base["message"].get("fromMe") is True:
        return True

    return False


# ==========================================
# INATIVIDADE
# ==========================================
def verificar_inatividade():
    while True:
        try:
            agora = time.time()

            for telefone in list(clientes.keys()):
                info = clientes.get(telefone, {})

                if info.get("atendimento_humano"):
                    continue

                ultima = info.get("ultima_interacao", agora)

                if agora - ultima > TEMPO_INATIVIDADE:
                    enviar_mensagem(
                        telefone,
                        "⏰ Atendimento encerrado por inatividade\n\nDigite *menu* para continuar o atendimento.\n\nEquipe Motoshow Yamaha"
                    )
                    resetar_cliente(telefone, manter_origem=True)

        except Exception as e:
            log_erro("Erro no monitor de inatividade:", e)

        time.sleep(30)


threading.Thread(target=verificar_inatividade, daemon=True).start()


# ==========================================
# REGRAS DE HORÁRIO
# ==========================================
def horarios_disponiveis(revisao, dia):
    revisao = str(revisao).strip()
    dia = normalizar_texto(dia)

    if dia in ["sabado", "sábado"]:
        if revisao in ["1", "2"]:
            return ["08:00", "09:00", "10:00"]
        return []

    if dia in ["segunda", "terça", "terca", "quarta", "quinta", "sexta"]:
        if revisao in ["1", "2"]:
            return ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"]
        return ["08:00"]

    return []


def menu_horarios(horarios):
    linhas = ["Escolha um horário:\n"]
    for i, h in enumerate(horarios, start=1):
        linhas.append(f"{i}️⃣ {h}")
    return "\n".join(linhas)


def itens_adicionais_disponiveis(revisao):
    itens = [
        "Protetor de motor",
        "Slider",
        "Suporte para celular",
        "Baú"
    ]

    if str(revisao).strip() not in ["1"]:
        itens.extend([
            "Filtro de ar",
            "Pastilha de freio"
        ])

    return itens


def menu_itens(itens):
    linhas = ["Deseja incluir algum item adicional?\n"]
    for i, item in enumerate(itens, start=1):
        linhas.append(f"{i}️⃣ {item}")
    linhas.append("0️⃣ Não quero nenhum item")
    linhas.append("\nVocê pode responder com números separados por vírgula.")
    return "\n".join(linhas)


# ==========================================
# MENUS
# ==========================================
def enviar_menu(telefone):
    mensagem = (
        "Olá 👋\n\n"
        "Bem-vindo ao Pós-Vendas Motoshow Yamaha 🏍️\n\n"
        "Escolha uma opção:\n\n"
        "1️⃣ Agendar Revisão\n"
        "2️⃣ Peças\n"
        "3️⃣ Acessórios\n"
        "4️⃣ Garantia\n"
        "5️⃣ Logista / Atacado\n"
        "6️⃣ Falar com atendente\n\n"
        "Equipe Motoshow Yamaha"
    )
    enviar_mensagem(telefone, mensagem)


def enviar_submenu_pecas(telefone):
    enviar_mensagem(
        telefone,
        "Peças Yamaha 🧩\n\n"
        "Escolha uma opção:\n\n"
        "1️⃣ Peças Originais\n"
        "2️⃣ Consultar Disponibilidade\n"
        "3️⃣ Falar com Atendente\n"
        "4️⃣ Voltar ao Menu"
    )


def enviar_submenu_acessorios(telefone):
    enviar_mensagem(
        telefone,
        "Acessórios Yamaha 🛵\n\n"
        "Escolha uma opção:\n\n"
        "1️⃣ Solicitar Acessório\n"
        "2️⃣ Falar com Atendente\n"
        "3️⃣ Voltar ao Menu"
    )


def enviar_submenu_garantia(telefone):
    enviar_mensagem(
        telefone,
        "Garantia Yamaha 🛠️\n\n"
        "Escolha uma opção:\n\n"
        "1️⃣ Nova Solicitação\n"
        "2️⃣ Acompanhar Garantia\n"
        "3️⃣ Falar com Atendente\n"
        "4️⃣ Voltar ao Menu"
    )


def enviar_submenu_atacado(telefone):
    enviar_mensagem(
        telefone,
        "Logista / Atacado 📦\n\n"
        "Escolha uma opção:\n\n"
        "1️⃣ Solicitar Cotação\n"
        "2️⃣ Cadastro de Logista\n"
        "3️⃣ Catálogo de Peças\n"
        "4️⃣ Falar com Consultor\n"
        "5️⃣ Voltar ao Menu"
    )


def ativar_atendimento_humano(telefone, setor="Atendente"):
    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["setor"] = setor

    salvar_atendimento(
        telefone=telefone,
        nome=clientes[telefone].get("nome_cliente", ""),
        setor=setor,
        modelo=clientes[telefone].get("modelo_moto", ""),
        ano=clientes[telefone].get("ano_moto", ""),
        revisao=clientes[telefone].get("revisao_numero", ""),
        horario=clientes[telefone].get("horario_escolhido", ""),
        itens=", ".join(clientes[telefone].get("itens", [])),
        origem=clientes[telefone].get("origem", "Menu Normal"),
        status="Atendimento Humano",
        atendimento_humano=True
    )

    enviar_mensagem(
        telefone,
        "👨‍💼 Seu atendimento foi encaminhado para um consultor.\n\nEquipe Motoshow Yamaha"
    )


# ==========================================
# DASHBOARD
# ==========================================
@app.route("/dashboard")
def dashboard():
    db = SessionLocal()

    try:
        total = db.query(Atendimento).count()
        agendamentos = db.query(Atendimento).filter(Atendimento.status == "Agendado").count()
        humano = db.query(Atendimento).filter(Atendimento.atendimento_humano == True).count()

        revisao = db.query(Atendimento).filter(Atendimento.setor == "Revisão").count()
        pecas = db.query(Atendimento).filter(Atendimento.setor == "Peças").count()
        acessorios = db.query(Atendimento).filter(Atendimento.setor == "Acessórios").count()
        garantia = db.query(Atendimento).filter(Atendimento.setor == "Garantia").count()
        logista = db.query(Atendimento).filter(Atendimento.setor == "Logista").count()

        campanha = db.query(Atendimento).filter(Atendimento.origem == "Campanha").count()
        menu = db.query(Atendimento).filter(Atendimento.origem == "Menu Normal").count()

        r1 = db.query(Atendimento).filter(Atendimento.revisao == "1").count()
        r2 = db.query(Atendimento).filter(Atendimento.revisao == "2").count()
        r3 = db.query(Atendimento).filter(Atendimento.revisao == "3").count()
        r4 = db.query(Atendimento).filter(Atendimento.revisao == "4").count()
        r5 = db.query(Atendimento).filter(Atendimento.revisao.notin_(["1", "2", "3", "4", "", None])).count()

        todos_itens = db.query(Atendimento.itens).all()
        contador_itens = Counter()

        for linha in todos_itens:
            valor = linha[0] or ""
            for item in [x.strip() for x in valor.split(",") if x.strip()]:
                contador_itens[item] += 1

        protetor = contador_itens.get("Protetor de motor", 0)
        slider = contador_itens.get("Slider", 0)
        suporte = contador_itens.get("Suporte para celular", 0)
        bau = contador_itens.get("Baú", 0)
        filtro = contador_itens.get("Filtro de ar", 0)
        pastilha = contador_itens.get("Pastilha de freio", 0)

        return render_template(
            "dashboard.html",
            total=total,
            agendamentos=agendamentos,
            humano=humano,
            revisao=revisao,
            pecas=pecas,
            acessorios=acessorios,
            garantia=garantia,
            logista=logista,
            campanha=campanha,
            menu=menu,
            r1=r1,
            r2=r2,
            r3=r3,
            r4=r4,
            r5=r5,
            protetor=protetor,
            slider=slider,
            suporte=suporte,
            bau=bau,
            filtro=filtro,
            pastilha=pastilha
        )

    except Exception as e:
        log_erro("Erro dashboard:", e)
        return f"Erro ao carregar dashboard: {e}", 500
    finally:
        db.close()


# ==========================================
# PDF
# ==========================================
@app.route("/pdf/<arquivo>")
def pdf(arquivo):
    return send_from_directory("static/pdfs", arquivo)
# ==========================================
# WEBHOOK
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Webhook ativo"}), 200

    payload = request.get_json(silent=True) or {}
    log_info("PAYLOAD RECEBIDO:", payload)

    try:
        if evento_eh_do_proprio_bot(payload):
            return jsonify({"status": "ignorado", "motivo": "mensagem do proprio bot"}), 200

        telefone = extrair_telefone(payload)
        texto = limpar_texto(extrair_mensagem_texto(payload))
        texto_normalizado = normalizar_texto(texto)
        message_id = extrair_message_id(payload)

        log_info("TELEFONE:", telefone)
        log_info("TEXTO:", texto)
        log_info("MESSAGE_ID:", message_id)

        if not telefone or telefone_eh_grupo(telefone):
            return jsonify({"status": "ignorado", "motivo": "grupo ou telefone invalido"}), 200

        if message_id in mensagens_processadas:
            return jsonify({"status": "ignorado", "motivo": "mensagem duplicada"}), 200

        mensagens_processadas.add(message_id)

        iniciar_cliente(telefone)
        atualizar_interacao(telefone)
        clientes[telefone]["mensagem_original"] = texto

        texto_normalizado = texto.lower().strip()

        # ==========================================
        # BLOQUEIO ATENDIMENTO HUMANO
        # ==========================================
        if clientes[telefone].get("atendimento_humano"):
            print("Atendimento humano ativo - Bot não responde")
            return jsonify({"status": "atendimento humano"}), 200

        if texto_normalizado in ["menu", "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]:
            resetar_cliente(telefone, manter_origem=True)
            enviar_menu(telefone)
            return jsonify({"status": "menu"}), 200


        # ==============================
        # CONTINUA FLUXO
        # ==============================
        etapa = clientes[telefone]["etapa"]
        log_info("ETAPA:", etapa)

# ==========================
# MENU PRINCIPAL
# ==========================
        if etapa == "menu":

            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "revisao_modelo"
                clientes[telefone]["setor"] = "Revisão"
                enviar_mensagem(telefone, "Informe o modelo da sua Yamaha:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "submenu_pecas"
                clientes[telefone]["setor"] = "Peças"
                enviar_submenu_pecas(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                clientes[telefone]["etapa"] = "submenu_acessorios"
                clientes[telefone]["setor"] = "Acessórios"
                enviar_submenu_acessorios(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                clientes[telefone]["etapa"] = "submenu_garantia"
                clientes[telefone]["setor"] = "Garantia"
                enviar_submenu_garantia(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "5":
                clientes[telefone]["etapa"] = "submenu_atacado"
                clientes[telefone]["setor"] = "Logista"
                enviar_submenu_atacado(telefone)
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "6":
                ativar_atendimento_humano(telefone, setor="Atendente")
                return jsonify({"status": "ok"}), 200

            else:
                resposta_fallback(telefone)
                return jsonify({"status": "fallback"}), 200
        # ==========================
        # SUBMENU PEÇAS
        # ==========================
        elif etapa == "submenu_pecas":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "pecas_nome"
                enviar_mensagem(telefone, "Informe o nome da peça desejada:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "pecas_disponibilidade_nome"
                enviar_mensagem(telefone, "Informe o item que deseja consultar:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                clientes[telefone]["etapa"] = "pecas_disponibilidade_modelo"
                enviar_mensagem(telefone, "Informe o modelo da moto:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                ativar_atendimento_humano(telefone, setor="Peças")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "5":
                resetar_cliente(telefone, manter_origem=True)
                enviar_menu(telefone)
                return jsonify({"status": "ok"}), 200

            else:
                resposta_fallback(telefone)
                return jsonify({"status": "fallback"}), 200


        # ===============================
        # PEÇAS NOME
        # ===============================
        elif etapa == "pecas_nome":
            clientes[telefone]["peca_nome"] = texto
            clientes[telefone]["etapa"] = "pecas_modelo"
            enviar_mensagem(telefone, "Informe o modelo da moto:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_modelo":
            clientes[telefone]["modelo_moto"] = texto
            clientes[telefone]["etapa"] = "pecas_ano"
            enviar_mensagem(telefone, "Informe o ano da moto:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_ano":
            clientes[telefone]["ano_moto"] = texto
            clientes[telefone]["etapa"] = "pecas_cor"
            enviar_mensagem(telefone, "Informe a cor da moto:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_cor":
            clientes[telefone]["cor_moto"] = texto

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone].get("nome_cliente", ""),
                setor="Peças",
                modelo=clientes[telefone].get("modelo_moto", ""),
                ano=clientes[telefone].get("ano_moto", ""),
                revisao="",
                horario="",
                itens=clientes[telefone].get("peca_nome", ""),
                origem=clientes[telefone].get("origem", "Menu Normal"),
                status="Orçamento Peças",
                atendimento_humano=False
            )

            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\nSua solicitação de peças foi registrada e será encaminhada para orçamento.\n\nEquipe Motoshow Yamaha"
            )

            resetar_cliente(telefone, manter_origem=True)
            return jsonify({"status": "ok"}), 200
        
        elif etapa == "pecas_disponibilidade_nome":
            clientes[telefone]["peca_nome"] = texto
            clientes[telefone]["etapa"] = "pecas_disponibilidade_modelo"
            enviar_mensagem(telefone, "Informe o modelo da moto:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_disponibilidade_modelo":
            clientes[telefone]["modelo_moto"] = texto

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone].get("nome_cliente", ""),
                setor="Peças",
                modelo=clientes[telefone].get("modelo_moto", ""),
                ano="",
                revisao="",
                horario="",
                itens=clientes[telefone].get("peca_nome", ""),
                origem=clientes[telefone].get("origem", "Menu Normal"),
                status="Consulta Disponibilidade",
                atendimento_humano=False
            )

            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\nVamos consultar a disponibilidade no estoque e retornar em breve.\n\nEquipe Motoshow Yamaha"
            )

            resetar_cliente(telefone, manter_origem=True)
            return jsonify({"status": "ok"}), 200

        # ==========================
        # SUBMENU ACESSÓRIOS
        # ==========================
        elif etapa == "submenu_acessorios":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "acessorio_nome"
                enviar_mensagem(telefone, "Informe o acessório desejado:")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                ativar_atendimento_humano(telefone, setor="Acessórios")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                resetar_cliente(telefone, manter_origem=True)
                enviar_menu(telefone)
                return jsonify({"status": "ok"}), 200

            else:
                resposta_fallback(telefone)
                return jsonify({"status": "fallback"}), 200

        elif etapa == "acessorio_nome":
                clientes[telefone]["acessorio_nome"] = texto
                clientes[telefone]["etapa"] = "acessorio_modelo"
                enviar_mensagem(telefone, "Informe o modelo da moto:")
                return jsonify({"status": "ok"}), 200

        elif etapa == "acessorio_nome":
                clientes[telefone]["acessorio_nome"] = texto
                clientes[telefone]["etapa"] = "acessorio_modelo"
                enviar_mensagem(telefone, "Informe o modelo da moto:")
                return jsonify({"status": "ok"}), 200

        elif etapa == "acessorio_modelo":
            clientes[telefone]["modelo_moto"] = texto

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone].get("nome_cliente", ""),
                setor="Acessórios",
                modelo=clientes[telefone].get("modelo_moto", ""),
                ano="",
                revisao="",
                horario="",
                itens=clientes[telefone].get("acessorio_nome", ""),
                origem=clientes[telefone].get("origem", "Menu Normal"),
                status="Orçamento Acessórios",
                atendimento_humano=False
            )

            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\nSua solicitação de acessório foi registrada e será encaminhada para orçamento.\n\nEquipe Motoshow Yamaha"
            )

            resetar_cliente(telefone, manter_origem=True)
            return jsonify({"status": "ok"}), 200
        # ==========================
        # SUBMENU GARANTIA
        # ==========================
        elif etapa == "submenu_garantia":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "garantia_nova_nome"
                enviar_mensagem(
                    telefone,
                    "🛡️ *Nova Solicitação de Garantia*\n\n"
                    "Para continuarmos, informe seu *nome completo*:"
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "garantia_acompanhar_nome"
                enviar_mensagem(
                    telefone,
                    "📋 *Acompanhar Garantia*\n\n"
                    "Para localizar sua solicitação, informe seu *nome completo*:"
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                ativar_atendimento_humano(telefone, setor="Garantia")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                resetar_cliente(telefone, manter_origem=True)
                enviar_menu(telefone)
                return jsonify({"status": "ok"}), 200

            else:
                resposta_fallback(telefone)
                return jsonify({"status": "fallback"}), 200

        elif etapa == "garantia_nova_nome":
            clientes[telefone]["nome_cliente"] = texto
            clientes[telefone]["etapa"] = "garantia_nova_modelo"
            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\n🏍️ Informe o *modelo da sua Yamaha*:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_nova_modelo":
            clientes[telefone]["modelo_moto"] = texto
            clientes[telefone]["etapa"] = "garantia_nova_descricao"
            enviar_mensagem(
                telefone,
                "📝 Descreva o *problema apresentado* na moto para registrarmos sua solicitação de garantia:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_nova_descricao":
            clientes[telefone]["descricao"] = texto

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone].get("nome_cliente", ""),
                setor="Garantia",
                modelo=clientes[telefone].get("modelo_moto", ""),
                ano="",
                revisao="",
                horario="",
                itens="Nova Solicitação",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                status="Nova Garantia",
                atendimento_humano=False
            )

            enviar_mensagem(
                telefone,
                "✅ *Solicitação de garantia registrada com sucesso!*\n\n"
                "📋 *Resumo do atendimento*\n\n"
                f"👤 Cliente: {clientes[telefone].get('nome_cliente', '')}\n"
                f"🏍️ Modelo: {clientes[telefone].get('modelo_moto', '')}\n"
                f"📝 Problema informado: {clientes[telefone].get('descricao', '')}\n\n"
                "Nossa equipe fará a análise e retornará em breve.\n\n"
                "🏍️ *Equipe Motoshow Yamaha*"
            )

            resetar_cliente(telefone, manter_origem=True)
            return jsonify({"status": "ok"}), 200
        # ==========================
        # SUBMENU ATACADO
        # ==========================
        elif etapa == "submenu_atacado":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "atacado_empresa"
                enviar_mensagem(
                    telefone,
                    "🏢 Informe o *nome da empresa*:"
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "cadastro_empresa"
                enviar_mensagem(
                    telefone,
                    "🏢 Informe o *nome da empresa* para cadastro:"
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                ok = enviar_catalogo(telefone)

                if ok:
                    enviar_mensagem(
                        telefone,
                        "📄 Catálogo enviado com sucesso ✅"
                    )
                else:
                    enviar_mensagem(
                        telefone,
                        "⚠️ Não foi possível enviar o catálogo. Tente novamente."
                    )

                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                ativar_atendimento_humano(telefone, setor="Logista/Atacado")
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "5":
                resetar_cliente(telefone, manter_origem=True)
                enviar_menu(telefone)
                return jsonify({"status": "ok"}), 200

            else:
                resposta_fallback(telefone)
                return jsonify({"status": "fallback"}), 200

        elif etapa == "atacado_empresa":
            clientes[telefone]["empresa"] = texto
            clientes[telefone]["etapa"] = "atacado_cnpj"
            enviar_mensagem(telefone, "Informe o CNPJ:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_cnpj":
            clientes[telefone]["cnpj"] = texto
            clientes[telefone]["etapa"] = "atacado_cidade"
            enviar_mensagem(telefone, "Informe a cidade:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_cidade":
            clientes[telefone]["cidade"] = texto
            clientes[telefone]["etapa"] = "atacado_pecas"
            enviar_mensagem(telefone, "Informe as peças desejadas (código ou modelo):")
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_pecas":
            clientes[telefone]["descricao"] = texto

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone].get("empresa", ""),
                setor="Logista/Atacado",
                modelo="",
                ano="",
                revisao="",
                horario="",
                itens=clientes[telefone].get("descricao", ""),
                origem=clientes[telefone].get("origem", "Menu Normal"),
                status="Cotação Atacado",
                atendimento_humano=False
            )

            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\n"
                "Sua solicitação de cotação foi registrada e será encaminhada para o consultor comercial.\n\n"
                "Equipe Motoshow Yamaha"
            )

            resetar_cliente(telefone, manter_origem=True)
            return jsonify({"status": "ok"}), 200

        elif etapa == "cadastro_empresa":
            clientes[telefone]["empresa"] = texto
            clientes[telefone]["etapa"] = "cadastro_cnpj"
            enviar_mensagem(
                telefone,
                "Informe o CNPJ:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "cadastro_cnpj":
            clientes[telefone]["cnpj"] = texto
            clientes[telefone]["etapa"] = "cadastro_responsavel"
            enviar_mensagem(
                telefone,
                "Informe o nome do responsável:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "cadastro_responsavel":
            clientes[telefone]["responsavel"] = texto
            clientes[telefone]["etapa"] = "cadastro_cidade"
            enviar_mensagem(
                telefone,
                "Informe a cidade:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "cadastro_cidade":
            clientes[telefone]["cidade"] = texto

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone].get("responsavel", ""),
                setor="Logista/Atacado",
                modelo="",
                ano="",
                revisao="",
                horario="",
                itens="Cadastro Logista",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                status="Cadastro Logista",
                atendimento_humano=False
            )

            enviar_mensagem(
                telefone,
                "✅ Cadastro recebido com sucesso!\n\n"
                "Nossa equipe comercial entrará em contato em breve.\n\n"
                "Equipe Motoshow Yamaha"
            )

            resetar_cliente(telefone, manter_origem=True)
            return jsonify({"status": "ok"}), 200
        # ==========================
        # FLUXO REVISÃO
        # ==========================
        elif etapa == "revisao_modelo":
            clientes[telefone]["modelo_moto"] = texto
            clientes[telefone]["etapa"] = "revisao_nome"
            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\n👤 Agora informe seu *nome completo*:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_nome":
            clientes[telefone]["nome_cliente"] = texto
            clientes[telefone]["etapa"] = "revisao_ano"
            enviar_mensagem(
                telefone,
                "Ótimo ✅\n\n📅 Informe o *ano da sua moto*.\nExemplo: *2024*"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_ano":
            clientes[telefone]["ano_moto"] = texto
            clientes[telefone]["etapa"] = "revisao_numero"
            enviar_mensagem(
                telefone,
                "🔧 *Agendamento de Revisão*\n\n"
                "Informe o número da revisão desejada:\n\n"
                "1️⃣ 1ª Revisão\n"
                "2️⃣ 2ª Revisão\n"
                "3️⃣ 3ª Revisão\n"
                "4️⃣ 4ª Revisão\n"
                "5️⃣ 5ª Revisão ou mais"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_numero":
            if not texto_normalizado.isdigit():
                resposta_fallback(telefone)
                return jsonify({"status": "fallback"}), 200

            clientes[telefone]["revisao_numero"] = texto_normalizado
            clientes[telefone]["etapa"] = "revisao_dia"
            enviar_mensagem(
                telefone,
                "📅 *Escolha o dia para o agendamento:*\n\n"
                "1️⃣ Segunda-feira\n"
                "2️⃣ Terça-feira\n"
                "3️⃣ Quarta-feira\n"
                "4️⃣ Quinta-feira\n"
                "5️⃣ Sexta-feira\n"
                "6️⃣ Sábado"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_dia":
            mapa_dias = {
                "1": "segunda",
                "2": "terca",
                "3": "quarta",
                "4": "quinta",
                "5": "sexta",
                "6": "sabado"
            }

            if texto_normalizado not in mapa_dias:
                resposta_fallback(telefone)
                return jsonify({"status": "fallback"}), 200

            dia = mapa_dias[texto_normalizado]
            clientes[telefone]["dia_semana"] = dia

            horarios = horarios_disponiveis(
                clientes[telefone]["revisao_numero"],
                dia
            )

            if not horarios:
                enviar_mensagem(
                    telefone,
                    "❌ *Não há horário disponível para esse tipo de revisão nesse dia.*\n\n"
                    "Digite outro dia ou envie *menu* para voltar ao início."
                )
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["horarios_disponiveis"] = horarios
            clientes[telefone]["etapa"] = "revisao_horario"
            enviar_mensagem(
                telefone,
                "⏰ *Escolha um horário disponível:*\n\n" + menu_horarios(horarios)
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_horario":
            if not texto_normalizado.isdigit():
                resposta_fallback(telefone)
                return jsonify({"status": "fallback"}), 200

            indice = int(texto_normalizado) - 1
            horarios = clientes[telefone].get("horarios_disponiveis", [])

            if indice < 0 or indice >= len(horarios):
                resposta_fallback(telefone)
                return jsonify({"status": "fallback"}), 200

            clientes[telefone]["horario_escolhido"] = horarios[indice]
            itens = itens_adicionais_disponiveis(clientes[telefone]["revisao_numero"])
            clientes[telefone]["itens_menu"] = itens
            clientes[telefone]["etapa"] = "revisao_itens"

            enviar_mensagem(
                telefone,
                "🛠️ *Deseja incluir algum item adicional?*\n\n" + menu_itens(itens)
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_itens":
            if texto_normalizado == "0":
                clientes[telefone]["itens"] = []
            else:
                escolhidos = []
                itens_menu = clientes[telefone].get("itens_menu", [])
                partes = [p.strip() for p in texto.split(",") if p.strip()]

                for p in partes:
                    if p.isdigit():
                        idx = int(p) - 1
                        if 0 <= idx < len(itens_menu):
                            escolhidos.append(itens_menu[idx])

                clientes[telefone]["itens"] = list(dict.fromkeys(escolhidos))

            itens_txt = ", ".join(clientes[telefone]["itens"]) if clientes[telefone]["itens"] else "Nenhum"

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone].get("nome_cliente", ""),
                setor="Revisão",
                modelo=clientes[telefone].get("modelo_moto", ""),
                ano=clientes[telefone].get("ano_moto", ""),
                revisao=clientes[telefone].get("revisao_numero", ""),
                horario=clientes[telefone].get("horario_escolhido", ""),
                itens=itens_txt,
                origem=clientes[telefone].get("origem", "Menu Normal"),
                status="Agendado",
                atendimento_humano=False
            )

            enviar_mensagem(
                telefone,
                "✅ *Agendamento solicitado com sucesso!*\n\n"
                "📋 *Resumo do agendamento*\n\n"
                f"👤 Cliente: {clientes[telefone].get('nome_cliente', '')}\n"
                f"🏍️ Modelo: {clientes[telefone].get('modelo_moto', '')}\n"
                f"📅 Ano: {clientes[telefone].get('ano_moto', '')}\n"
                f"🔧 Revisão: {clientes[telefone].get('revisao_numero', '')}ª\n"
                f"🗓️ Dia: {clientes[telefone].get('dia_semana', '').title()}\n"
                f"⏰ Horário: {clientes[telefone].get('horario_escolhido', '')}\n"
                f"🛠️ Itens adicionais: {itens_txt}\n\n"
                "Em breve nossa equipe fará a confirmação.\n\n"
                "🏍️ *Equipe Motoshow Yamaha*"
            )

            resetar_cliente(telefone, manter_origem=True)
            return jsonify({"status": "ok"}), 200

        else:
            resposta_fallback(telefone)
            return jsonify({"status": "fallback"}), 200

    except Exception as e:
        log_erro("ERRO WEBHOOK:", e)
        return jsonify({"status": "erro", "detalhe": str(e)}), 500