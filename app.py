from flask import Flask, request, jsonify
import os
import re
import time
import threading
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

load_dotenv()

app = Flask(__name__)

# =========================================================
# CONFIG
# =========================================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "").strip()
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "").strip()
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "").strip()
BASE_URL = os.getenv("BASE_URL", "https://SEU-APP.onrender.com").strip()
PORT = int(os.getenv("PORT", "5000"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()

TEMPO_INATIVIDADE = int(os.getenv("TEMPO_INATIVIDADE", "900"))

URL_ENVIO = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

# =========================================================
# MEMÓRIA EM RAM
# =========================================================
clientes = {}
mensagens_processadas = {}
LOCK = threading.Lock()

MODELOS_YAMAHA = {
    "1": "Fazer 250",
    "2": "FZ15",
    "3": "Crosser",
    "4": "Lander",
    "5": "MT03",
    "6": "MT07",
    "7": "R15",
    "8": "R3",
    "9": "FLUO",
    "10": "NEO",
    "11": "NMAX",
    "12": "Ténéré 700",
    "13": "AEROX",
}

# =========================================================
# LOG
# =========================================================
def log_info(*args):
    print("[INFO]", *args)

def log_erro(*args):
    print("[ERRO]", *args)

# =========================================================
# HELPERS GERAIS
# =========================================================
def limpar_texto(texto):
    if not texto:
        return ""
    return str(texto).strip()

def normalizar_texto(texto):
    texto = limpar_texto(texto).lower()
    texto = texto.replace("á", "a").replace("à", "a").replace("ã", "a").replace("â", "a")
    texto = texto.replace("é", "e").replace("ê", "e")
    texto = texto.replace("í", "i")
    texto = texto.replace("ó", "o").replace("ô", "o").replace("õ", "o")
    texto = texto.replace("ú", "u")
    texto = texto.replace("ç", "c")
    return texto.strip()

def telefone_eh_grupo(telefone):
    return "@g.us" in str(telefone)

def extrair_telefone(payload):
    candidates = [
        payload.get("phone"),
        payload.get("from"),
        (payload.get("data") or {}).get("phone"),
        (payload.get("data") or {}).get("from"),
        (payload.get("message") or {}).get("phone"),
        (payload.get("message") or {}).get("from"),
    ]
    for item in candidates:
        if item:
            return str(item)
    return ""

def extrair_message_id(payload):
    candidates = [
        payload.get("messageId"),
        payload.get("id"),
        (payload.get("data") or {}).get("messageId"),
        (payload.get("data") or {}).get("id"),
        ((payload.get("data") or {}).get("message") or {}).get("id"),
        (payload.get("message") or {}).get("id"),
    ]
    for item in candidates:
        if item:
            return str(item)
    return ""

def extrair_mensagem_texto(payload):
    caminhos = [
        payload.get("text"),
        payload.get("message"),
        (payload.get("data") or {}).get("text"),
        (payload.get("data") or {}).get("message"),
        ((payload.get("data") or {}).get("message") or {}).get("text"),
        (((payload.get("data") or {}).get("text") or {}).get("message")),
        ((payload.get("message") or {}).get("text") if isinstance(payload.get("message"), dict) else None),
    ]

    for item in caminhos:
        if isinstance(item, str) and item.strip():
            return item.strip()

    return ""

def evento_eh_do_proprio_bot(payload):
    verificacoes = [
        payload.get("fromMe"),
        (payload.get("data") or {}).get("fromMe"),
        (payload.get("message") or {}).get("fromMe") if isinstance(payload.get("message"), dict) else None,
        ((payload.get("data") or {}).get("message") or {}).get("fromMe")
            if isinstance((payload.get("data") or {}).get("message"), dict) else None,
    ]
    return any(v is True for v in verificacoes)

# =========================================================
# CONTROLE CLIENTE
# =========================================================
def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = {
            "etapa": "inicio",
            "ultima_interacao": datetime.now(),
            "atendimento_humano": False,
            "setor": "",
            "nome_cliente": "",
            "modelo_moto": "",
            "ano_moto": "",
            "revisao_numero": "",
            "dia_semana": "",
            "horario_escolhido": "",
            "origem": "Menu Normal",
        }

def resetar_cliente(telefone):
    clientes[telefone] = {
        "etapa": "menu_principal",
        "ultima_interacao": datetime.now(),
        "atendimento_humano": False,
        "setor": "",
        "nome_cliente": "",
        "modelo_moto": "",
        "ano_moto": "",
        "revisao_numero": "",
        "dia_semana": "",
        "horario_escolhido": "",
        "origem": "Menu Normal",
    }

def atualizar_interacao(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["ultima_interacao"] = datetime.now()

def ativar_atendimento_humano(telefone, setor="Atendimento Humano"):
    iniciar_cliente(telefone)
    clientes[telefone]["atendimento_humano"] = True
    clientes[telefone]["setor"] = setor
    clientes[telefone]["etapa"] = "atendimento_humano"

    enviar_mensagem(
        telefone,
        "👨‍💼 *Atendimento humano solicitado*\n\n"
        "Seu atendimento foi encaminhado para nossa equipe.\n"
        "Em breve um consultor continuará com você por aqui.\n\n"
        "Agradecemos pela sua preferência.\n\n"
        "_Equipe Motoshow Yamaha_"
    )

# =========================================================
# DUPLICIDADE
# =========================================================
def limpar_cache_mensagens():
    agora = time.time()
    expirados = [k for k, v in mensagens_processadas.items() if agora - v > 600]
    for k in expirados:
        mensagens_processadas.pop(k, None)

def mensagem_ja_processada(message_id):
    if not message_id:
        return False
    limpar_cache_mensagens()
    return message_id in mensagens_processadas

def registrar_mensagem_processada(message_id):
    if message_id:
        mensagens_processadas[message_id] = time.time()

# =========================================================
# Z-API
# =========================================================
def enviar_mensagem(numero, mensagem):
    if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN or not ZAPI_CLIENT_TOKEN:
        log_erro("Credenciais Z-API não configuradas.")
        return False

    headers = {"Client-Token": ZAPI_CLIENT_TOKEN}
    payload = {
        "phone": numero,
        "message": mensagem
    }

    try:
        response = requests.post(URL_ENVIO, json=payload, headers=headers, timeout=20)
        log_info("Envio WhatsApp:", response.status_code, response.text)
        return response.status_code in [200, 201]
    except Exception as e:
        log_erro("Erro ao enviar mensagem:", e)
        return False

# =========================================================
# MENU
# =========================================================
def enviar_menu_principal(telefone):
    clientes[telefone]["etapa"] = "menu_principal"

    enviar_mensagem(
        telefone,
        "🏍️ *Pós-Vendas Motoshow Yamaha*\n\n"
        "Olá! Seja bem-vindo(a) 👋\n"
        "Estamos prontos para te ajudar com revisão, peças, garantia e serviços Yamaha.\n\n"
        "📋 *Escolha uma opção abaixo:*\n\n"
        "1️⃣ *Agendar Revisão*\n"
        "2️⃣ *Orçamento de Peças*\n"
        "3️⃣ *Acompanhar Serviço*\n"
        "4️⃣ *Agendar Serviço / Avaliação*\n"
        "5️⃣ *Garantia*\n"
        "6️⃣ *Logista / Atacado*\n"
        "7️⃣ *Falar com Atendente*\n\n"
        "✍️ Se preferir, você também pode escrever o que precisa.\n\n"
        "_Equipe Motoshow Yamaha_"
    )

# =========================================================
# HORÁRIOS
# =========================================================
def obter_horarios_revisao(revisao_numero, dia_semana):
    dia = normalizar_texto(dia_semana)

    if revisao_numero in ["1", "2"]:
        if dia in ["segunda", "terca", "quarta", "quinta", "sexta"]:
            return ["08:00", "09:00", "10:00", "11:00", "13:00", "14:00", "15:00"]
        elif dia == "sabado":
            return ["08:00", "09:00", "10:00"]

    if revisao_numero not in ["1", "2"]:
        if dia in ["segunda", "terca", "quarta", "quinta", "sexta"]:
            return ["08:00"]

    return []

def montar_lista_horarios(horarios):
    linhas = []
    for i, h in enumerate(horarios, start=1):
        linhas.append(f"{i}️⃣ {h}")
    return "\n".join(linhas)

# =========================================================
# IA - ETAPA 1
# =========================================================
def classificar_intencao_ia(texto_cliente):
    if not OpenAI or not OPENAI_API_KEY:
        return "desconhecido"

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)

        instructions = """
Você é um classificador de intenção para um bot de pós-vendas de concessionária Yamaha.

Classifique a mensagem em exatamente UMA destas categorias:
- revisao
- pecas
- acessorios
- garantia
- atacado
- humano
- menu
- acompanhar_servico
- agendar_servico
- nao_interessado
- duvida
- desconhecido

Regras:
- Responda com apenas uma palavra, exatamente igual a uma das categorias.
- Se o cliente quiser agendar revisão, manutenção periódica, troca de óleo de revisão, revisão por km ou meses: revisao
- Se o cliente pedir peça, orçamento de peça, código, disponibilidade, peça original: pecas
- Se o cliente quiser acessório: acessorios
- Se falar de garantia: garantia
- Se falar de logista, atacado, revenda, CNPJ, catálogo atacado, cotação empresa: atacado
- Se quiser pessoa, consultor, atendente, humano: humano
- Se disser oi, olá, bom dia, boa tarde, boa noite, menu, começar, iniciar: menu
- Se quiser saber andamento de moto, status de serviço, acompanhar serviço: acompanhar_servico
- Se quiser avaliação, oficina, agendar serviço sem citar revisão: agendar_servico
- Se disser que não quer, sem interesse, pare de mandar: nao_interessado
- Se for dúvida geral: duvida
- Se não entender claramente: desconhecido
        """.strip()

        response = client.responses.create(
            model=OPENAI_MODEL,
            instructions=instructions,
            input=texto_cliente
        )

        intencao = (response.output_text or "").strip().lower()

        categorias_validas = {
            "revisao",
            "pecas",
            "acessorios",
            "garantia",
            "atacado",
            "humano",
            "menu",
            "acompanhar_servico",
            "agendar_servico",
            "nao_interessado",
            "duvida",
            "desconhecido",
        }

        if intencao not in categorias_validas:
            return "desconhecido"

        return intencao

    except Exception as e:
        log_erro("Erro IA:", e)
        return "desconhecido"

def deve_usar_ia(etapa_atual, texto_normalizado):
    palavras_menu = {
        "oi", "ola", "olá", "menu", "inicio", "iniciar",
        "bom dia", "boa tarde", "boa noite", "comecar", "começar"
    }

    if texto_normalizado in palavras_menu:
        return True

    etapas_livres = {
        "inicio",
        "menu_principal"
    }

    if etapa_atual in etapas_livres:
        return True

    return False

def tratar_intencao_ia(telefone, intencao):
    if intencao == "menu":
        resetar_cliente(telefone)
        enviar_menu_principal(telefone)
        return True

    elif intencao == "revisao":
        clientes[telefone]["etapa"] = "escolher_modelo"
        clientes[telefone]["setor"] = "Revisão"

        enviar_mensagem(
            telefone,
            "🔧 *Agendamento de Revisão Yamaha*\n\n"
            "Vamos iniciar seu atendimento de forma rápida e prática.\n\n"
            "🏍️ *Selecione o modelo da sua moto:*\n\n"
            "1️⃣ Fazer 250\n"
            "2️⃣ FZ15\n"
            "3️⃣ Crosser\n"
            "4️⃣ Lander\n"
            "5️⃣ MT03\n"
            "6️⃣ MT07\n"
            "7️⃣ R15\n"
            "8️⃣ R3\n"
            "9️⃣ FLUO\n"
            "🔟 NEO\n"
            "11️⃣ NMAX\n"
            "12️⃣ Ténéré 700\n"
            "13️⃣ AEROX\n\n"
            "Digite apenas o *número da opção*."
        )
        return True

    elif intencao == "pecas":
        clientes[telefone]["etapa"] = "submenu_pecas"
        clientes[telefone]["setor"] = "Peças"

        enviar_mensagem(
            telefone,
            "🛠️ *Peças Yamaha*\n\n"
            "Selecione uma opção para continuarmos:\n\n"
            "1️⃣ *Peças Originais*\n"
            "2️⃣ *Acessórios*\n"
            "3️⃣ *Consultar Disponibilidade*\n"
            "4️⃣ *Falar com Atendente*\n"
            "5️⃣ *Voltar ao Menu*\n\n"
            "Digite o *número da opção* desejada."
        )
        return True

    elif intencao == "acessorios":
        clientes[telefone]["etapa"] = "acessorios_nome"
        clientes[telefone]["setor"] = "Acessórios"

        enviar_mensagem(
            telefone,
            "✨ *Acessórios Yamaha*\n\n"
            "Informe qual acessório você procura:"
        )
        return True

    elif intencao == "garantia":
        clientes[telefone]["etapa"] = "submenu_garantia"
        clientes[telefone]["setor"] = "Garantia"

        enviar_mensagem(
            telefone,
            "🛡️ *Garantia Yamaha*\n\n"
            "Escolha a opção desejada:\n\n"
            "1️⃣ *Nova Solicitação*\n"
            "2️⃣ *Acompanhar Garantia*\n"
            "3️⃣ *Falar com Atendente*\n"
            "4️⃣ *Voltar ao Menu*\n\n"
            "Digite o *número da opção*."
        )
        return True

    elif intencao == "atacado":
        clientes[telefone]["etapa"] = "submenu_atacado"
        clientes[telefone]["setor"] = "Atacado"

        enviar_mensagem(
            telefone,
            "🏢 *Logista / Atacado Yamaha*\n\n"
            "Selecione uma opção abaixo:\n\n"
            "1️⃣ *Solicitar Cotação*\n"
            "2️⃣ *Cadastro de Logista*\n"
            "3️⃣ *Catálogo de Peças*\n"
            "4️⃣ *Falar com Consultor*\n"
            "5️⃣ *Voltar ao Menu*\n\n"
            "Digite o *número da opção* desejada."
        )
        return True

    elif intencao == "humano":
        ativar_atendimento_humano(telefone, setor="Atendimento Humano")
        return True

    elif intencao == "acompanhar_servico":
        clientes[telefone]["etapa"] = "acompanhar_servico_nome"
        clientes[telefone]["setor"] = "Acompanhar Serviço"

        enviar_mensagem(
            telefone,
            "📋 *Acompanhar Serviço*\n\n"
            "Informe seu *nome completo* para localizarmos o atendimento:"
        )
        return True

    elif intencao == "agendar_servico":
        clientes[telefone]["etapa"] = "agendar_servico_nome"
        clientes[telefone]["setor"] = "Agendar Serviço"

        enviar_mensagem(
            telefone,
            "🧰 *Agendar Serviço / Avaliação*\n\n"
            "Informe seu *nome completo* para continuarmos:"
        )
        return True

    elif intencao == "nao_interessado":
        enviar_mensagem(
            telefone,
            "Tudo bem 👍\n\n"
            "Quando precisar da *Motoshow Yamaha*, é só enviar *menu*.\n\n"
            "_Equipe Motoshow Yamaha_"
        )
        resetar_cliente(telefone)
        return True

    elif intencao == "duvida":
        enviar_menu_principal(telefone)
        return True

    return False

# =========================================================
# INATIVIDADE
# =========================================================
def processar_inatividade():
    agora = datetime.now()

    for telefone, dados in list(clientes.items()):
        ultima = dados.get("ultima_interacao")
        atendimento_humano = dados.get("atendimento_humano", False)

        if not ultima or atendimento_humano:
            continue

        if (agora - ultima).total_seconds() >= TEMPO_INATIVIDADE:
            enviar_mensagem(
                telefone,
                "⏳ *Atendimento encerrado por inatividade*\n\n"
                "Seu atendimento foi finalizado automaticamente.\n"
                "Quando quiser continuar, basta enviar *menu*.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)

# =========================================================
# WEBHOOK
# =========================================================
@app.route("/", methods=["GET"])
def home():
    return "BOT YAMAHA ONLINE", 200

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Webhook ativo"}), 200

    processar_inatividade()

    payload = request.get_json(silent=True) or {}
    log_info("PAYLOAD RECEBIDO:", payload)

    try:
        if evento_eh_do_proprio_bot(payload):
            return jsonify({"status": "ignorado", "motivo": "mensagem do proprio bot"}), 200

        telefone = extrair_telefone(payload)
        texto = limpar_texto(extrair_mensagem_texto(payload))
        texto_normalizado = normalizar_texto(texto)
        message_id = extrair_message_id(payload)

        if not telefone or telefone_eh_grupo(telefone):
            return jsonify({"status": "ignorado", "motivo": "grupo ou telefone invalido"}), 200

        if mensagem_ja_processada(message_id):
            return jsonify({"status": "ignorado", "motivo": "mensagem duplicada"}), 200

        registrar_mensagem_processada(message_id)

        iniciar_cliente(telefone)
        atualizar_interacao(telefone)

        if clientes[telefone].get("atendimento_humano"):
            return jsonify({"status": "ok", "modo": "atendimento_humano"}), 200

        # ==========================
        # IA ETAPA 1
        # ==========================
        etapa_atual = clientes[telefone].get("etapa", "inicio")

        if deve_usar_ia(etapa_atual, texto_normalizado):
            intencao = classificar_intencao_ia(texto)
            log_info(f"IA classificou '{texto}' como: {intencao}")

            if tratar_intencao_ia(telefone, intencao):
                return jsonify({"status": "ok", "ia": True, "intencao": intencao}), 200

        # ==========================
        # MENU PRINCIPAL
        # ==========================
        etapa = clientes[telefone].get("etapa", "inicio")

        if texto_normalizado in ["menu", "oi", "ola", "olá", "bom dia", "boa tarde", "boa noite"]:
            resetar_cliente(telefone)
            enviar_menu_principal(telefone)
            return jsonify({"status": "ok"}), 200

        if etapa == "inicio":
            resetar_cliente(telefone)
            enviar_menu_principal(telefone)
            return jsonify({"status": "ok"}), 200

        elif etapa == "menu_principal":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "escolher_modelo"
                clientes[telefone]["setor"] = "Revisão"
                enviar_mensagem(
                    telefone,
                    "🔧 *Agendamento de Revisão Yamaha*\n\n"
                    "Vamos iniciar seu atendimento de forma rápida e prática.\n\n"
                    "🏍️ *Selecione o modelo da sua moto:*\n\n"
                    "1️⃣ Fazer 250\n"
                    "2️⃣ FZ15\n"
                    "3️⃣ Crosser\n"
                    "4️⃣ Lander\n"
                    "5️⃣ MT03\n"
                    "6️⃣ MT07\n"
                    "7️⃣ R15\n"
                    "8️⃣ R3\n"
                    "9️⃣ FLUO\n"
                    "🔟 NEO\n"
                    "11️⃣ NMAX\n"
                    "12️⃣ Ténéré 700\n"
                    "13️⃣ AEROX\n\n"
                    "Digite apenas o *número da opção*."
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "submenu_pecas"
                clientes[telefone]["setor"] = "Peças"
                enviar_mensagem(
                    telefone,
                    "🛠️ *Peças Yamaha*\n\n"
                    "Selecione uma opção para continuarmos:\n\n"
                    "1️⃣ *Peças Originais*\n"
                    "2️⃣ *Acessórios*\n"
                    "3️⃣ *Consultar Disponibilidade*\n"
                    "4️⃣ *Falar com Atendente*\n"
                    "5️⃣ *Voltar ao Menu*\n\n"
                    "Digite o *número da opção* desejada."
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "3":
                clientes[telefone]["etapa"] = "acompanhar_servico_nome"
                clientes[telefone]["setor"] = "Acompanhar Serviço"
                enviar_mensagem(
                    telefone,
                    "📋 *Acompanhar Serviço*\n\n"
                    "Informe seu *nome completo* para localizarmos o atendimento:"
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "4":
                clientes[telefone]["etapa"] = "agendar_servico_nome"
                clientes[telefone]["setor"] = "Agendar Serviço"
                enviar_mensagem(
                    telefone,
                    "🧰 *Agendar Serviço / Avaliação*\n\n"
                    "Informe seu *nome completo* para continuarmos:"
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "5":
                clientes[telefone]["etapa"] = "submenu_garantia"
                clientes[telefone]["setor"] = "Garantia"
                enviar_mensagem(
                    telefone,
                    "🛡️ *Garantia Yamaha*\n\n"
                    "Escolha a opção desejada:\n\n"
                    "1️⃣ *Nova Solicitação*\n"
                    "2️⃣ *Acompanhar Garantia*\n"
                    "3️⃣ *Falar com Atendente*\n"
                    "4️⃣ *Voltar ao Menu*\n\n"
                    "Digite o *número da opção*."
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "6":
                clientes[telefone]["etapa"] = "submenu_atacado"
                clientes[telefone]["setor"] = "Atacado"
                enviar_mensagem(
                    telefone,
                    "🏢 *Logista / Atacado Yamaha*\n\n"
                    "Selecione uma opção abaixo:\n\n"
                    "1️⃣ *Solicitar Cotação*\n"
                    "2️⃣ *Cadastro de Logista*\n"
                    "3️⃣ *Catálogo de Peças*\n"
                    "4️⃣ *Falar com Consultor*\n"
                    "5️⃣ *Voltar ao Menu*\n\n"
                    "Digite o *número da opção* desejada."
                )
                return jsonify({"status": "ok"}), 200

            elif texto_normalizado == "7":
                ativar_atendimento_humano(telefone, setor="Atendimento Humano")
                return jsonify({"status": "ok"}), 200

            else:
                enviar_menu_principal(telefone)
                return jsonify({"status": "ok"}), 200

        # ==========================
        # REVISÃO
        # ==========================
        elif etapa == "escolher_modelo":
            if texto_normalizado in MODELOS_YAMAHA:
                clientes[telefone]["modelo_moto"] = MODELOS_YAMAHA[texto_normalizado]
                clientes[telefone]["etapa"] = "revisao_nome"

                enviar_mensagem(
                    telefone,
                    f"✅ *Modelo selecionado:* {MODELOS_YAMAHA[texto_normalizado]}\n\n"
                    "👤 Agora informe seu *nome completo* para continuarmos:"
                )
            else:
                enviar_mensagem(
                    telefone,
                    "❌ Modelo inválido.\n\n"
                    "Digite o *número correspondente* ao modelo da moto."
                )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_nome":
            clientes[telefone]["nome_cliente"] = texto
            clientes[telefone]["etapa"] = "revisao_ano"
            enviar_mensagem(
                telefone,
                "Perfeito 👍\n\n"
                "📅 Informe agora o *ano da sua moto*.\n"
                "Exemplo: *2024*"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_ano":
            clientes[telefone]["ano_moto"] = texto
            clientes[telefone]["etapa"] = "revisao_numero"
            enviar_mensagem(
                telefone,
                "🔧 Informe qual revisão deseja agendar:\n\n"
                "1️⃣ *1ª Revisão*\n"
                "2️⃣ *2ª Revisão*\n"
                "3️⃣ *3ª Revisão*\n"
                "4️⃣ *4ª Revisão ou mais*"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_numero":
            if texto_normalizado not in ["1", "2", "3", "4"]:
                enviar_mensagem(
                    telefone,
                    "❌ Opção inválida.\n\n"
                    "Digite uma opção válida: *1, 2, 3 ou 4*."
                )
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["revisao_numero"] = texto_normalizado
            clientes[telefone]["etapa"] = "revisao_dia"

            enviar_mensagem(
                telefone,
                "📆 Escolha o *dia desejado* para o agendamento:\n\n"
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
                enviar_mensagem(
                    telefone,
                    "❌ Dia inválido.\n\n"
                    "Digite uma opção válida de *1 a 6*."
                )
                return jsonify({"status": "ok"}), 200

            dia = mapa_dias[texto_normalizado]
            revisao_numero = clientes[telefone]["revisao_numero"]
            horarios = obter_horarios_revisao(revisao_numero, dia)

            if not horarios:
                enviar_mensagem(
                    telefone,
                    "❌ Não temos horário disponível para essa revisão nesse dia.\n\n"
                    "Escolha outro dia para continuarmos."
                )
                return jsonify({"status": "ok"}), 200

            clientes[telefone]["dia_semana"] = dia
            clientes[telefone]["horarios_disponiveis"] = horarios
            clientes[telefone]["etapa"] = "revisao_horario"

            enviar_mensagem(
                telefone,
                "🕐 *Horários disponíveis para a data escolhida:*\n\n"
                f"{montar_lista_horarios(horarios)}\n\n"
                "Digite o *número do horário* desejado."
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "revisao_horario":
            horarios = clientes[telefone].get("horarios_disponiveis", [])

            if not texto_normalizado.isdigit():
                enviar_mensagem(
                    telefone,
                    "❌ Horário inválido.\n\n"
                    "Digite o *número correto* do horário desejado."
                )
                return jsonify({"status": "ok"}), 200

            indice = int(texto_normalizado) - 1
            if indice < 0 or indice >= len(horarios):
                enviar_mensagem(
                    telefone,
                    "❌ Horário inválido.\n\n"
                    "Digite o *número correto* do horário desejado."
                )
                return jsonify({"status": "ok"}), 200

            horario = horarios[indice]
            clientes[telefone]["horario_escolhido"] = horario

            resumo = (
                "✅ *Agendamento recebido com sucesso!*\n\n"
                "📋 *Resumo do agendamento:*\n\n"
                f"👤 *Cliente:* {clientes[telefone]['nome_cliente']}\n"
                f"🏍️ *Modelo:* {clientes[telefone]['modelo_moto']}\n"
                f"📅 *Ano:* {clientes[telefone]['ano_moto']}\n"
                f"🔧 *Revisão:* {clientes[telefone]['revisao_numero']}ª\n"
                f"📆 *Dia:* {clientes[telefone]['dia_semana'].capitalize()}\n"
                f"🕐 *Horário:* {horario}\n\n"
                "Nossa equipe poderá confirmar os detalhes em seguida.\n\n"
                "Obrigado por escolher a *Motoshow Yamaha* 💙\n\n"
                "_Equipe Motoshow Yamaha_"
            )

            enviar_mensagem(telefone, resumo)
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        # ==========================
        # PEÇAS
        # ==========================
        elif etapa == "submenu_pecas":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "pecas_nome"
                enviar_mensagem(
                    telefone,
                    "🛠️ *Peças Originais Yamaha*\n\n"
                    "Informe o *nome da peça* que você procura:"
                )
            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "acessorios_nome"
                enviar_mensagem(
                    telefone,
                    "✨ *Acessórios Yamaha*\n\n"
                    "Informe qual acessório você procura:"
                )
            elif texto_normalizado == "3":
                clientes[telefone]["etapa"] = "consultar_disponibilidade"
                enviar_mensagem(
                    telefone,
                    "📦 *Consulta de Disponibilidade*\n\n"
                    "Informe a peça, código ou item que deseja consultar:"
                )
            elif texto_normalizado == "4":
                ativar_atendimento_humano(telefone, setor="Peças")
            elif texto_normalizado == "5":
                enviar_menu_principal(telefone)
            else:
                enviar_mensagem(
                    telefone,
                    "❌ Opção inválida.\n\n"
                    "Por favor, digite o *número correspondente* à opção desejada."
                )
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_nome":
            clientes[telefone]["peca_nome"] = texto
            clientes[telefone]["etapa"] = "pecas_modelo"
            enviar_mensagem(telefone, "🏍️ Informe o *modelo da moto*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_modelo":
            clientes[telefone]["peca_modelo"] = texto
            clientes[telefone]["etapa"] = "pecas_ano"
            enviar_mensagem(telefone, "📅 Informe o *ano da moto*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_ano":
            clientes[telefone]["peca_ano"] = texto
            clientes[telefone]["etapa"] = "pecas_cor"
            enviar_mensagem(telefone, "🎨 Informe a *cor da moto*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "pecas_cor":
            enviar_mensagem(
                telefone,
                "✅ *Solicitação de peça recebida com sucesso!*\n\n"
                f"🛠️ *Peça:* {clientes[telefone].get('peca_nome', '')}\n"
                f"🏍️ *Modelo:* {clientes[telefone].get('peca_modelo', '')}\n"
                f"📅 *Ano:* {clientes[telefone].get('peca_ano', '')}\n"
                f"🎨 *Cor:* {texto}\n\n"
                "Nossa equipe irá seguir com o seu atendimento.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        elif etapa == "acessorios_nome":
            enviar_mensagem(
                telefone,
                "✅ *Solicitação de acessório recebida!*\n\n"
                f"✨ *Acessório informado:* {texto}\n\n"
                "Nossa equipe irá retornar com as opções disponíveis.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        elif etapa == "consultar_disponibilidade":
            enviar_mensagem(
                telefone,
                "✅ *Consulta recebida com sucesso!*\n\n"
                f"📦 *Item informado:* {texto}\n\n"
                "Vamos verificar a disponibilidade e seguir com seu atendimento.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        # ==========================
        # GARANTIA
        # ==========================
        elif etapa == "submenu_garantia":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "garantia_nova_nome"
                enviar_mensagem(
                    telefone,
                    "🛡️ *Nova Solicitação de Garantia*\n\n"
                    "Informe seu *nome completo* para continuarmos:"
                )
            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "garantia_acompanhar_nome"
                enviar_mensagem(
                    telefone,
                    "📋 *Acompanhar Garantia*\n\n"
                    "Informe seu *nome completo*:"
                )
            elif texto_normalizado == "3":
                ativar_atendimento_humano(telefone, setor="Garantia")
            elif texto_normalizado == "4":
                enviar_menu_principal(telefone)
            else:
                enviar_mensagem(
                    telefone,
                    "❌ Opção inválida.\n\n"
                    "Por favor, digite o *número correspondente* à opção desejada."
                )
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_nova_nome":
            clientes[telefone]["garantia_nome"] = texto
            clientes[telefone]["etapa"] = "garantia_nova_descricao"
            enviar_mensagem(
                telefone,
                "📝 Descreva o problema apresentado para registrarmos sua solicitação:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_nova_descricao":
            enviar_mensagem(
                telefone,
                "✅ *Solicitação de garantia registrada com sucesso!*\n\n"
                f"👤 *Cliente:* {clientes[telefone].get('garantia_nome', '')}\n"
                f"📝 *Descrição:* {texto}\n\n"
                "Nossa equipe dará continuidade ao atendimento.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_acompanhar_nome":
            clientes[telefone]["garantia_nome"] = texto
            clientes[telefone]["etapa"] = "garantia_acompanhar_cpf"
            enviar_mensagem(
                telefone,
                "🔐 Informe o *CPF do proprietário* para localizarmos a solicitação:"
            )
            return jsonify({"status": "ok"}), 200

        elif etapa == "garantia_acompanhar_cpf":
            enviar_mensagem(
                telefone,
                "✅ *Pedido de acompanhamento recebido!*\n\n"
                f"👤 *Cliente:* {clientes[telefone].get('garantia_nome', '')}\n"
                f"🔐 *CPF:* {texto}\n\n"
                "Nossa equipe irá verificar e retornar com as informações.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        # ==========================
        # ATACADO
        # ==========================
        elif etapa == "submenu_atacado":
            if texto_normalizado == "1":
                clientes[telefone]["etapa"] = "atacado_empresa"
                enviar_mensagem(telefone, "🏢 Informe o *nome da empresa*:")
            elif texto_normalizado == "2":
                clientes[telefone]["etapa"] = "cadastro_logista_empresa"
                enviar_mensagem(telefone, "🏢 Informe o *nome da empresa*:")
            elif texto_normalizado == "3":
                enviar_mensagem(
                    telefone,
                    "📄 *Catálogo solicitado com sucesso!*\n\n"
                    "Se o envio automático do PDF estiver habilitado no sistema, ele será enviado em seguida.\n\n"
                    "_Equipe Motoshow Yamaha_"
                )
                resetar_cliente(telefone)
            elif texto_normalizado == "4":
                ativar_atendimento_humano(telefone, setor="Atacado")
            elif texto_normalizado == "5":
                enviar_menu_principal(telefone)
            else:
                enviar_mensagem(
                    telefone,
                    "❌ Opção inválida.\n\n"
                    "Por favor, digite o *número correspondente* à opção desejada."
                )
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_empresa":
            clientes[telefone]["empresa"] = texto
            clientes[telefone]["etapa"] = "atacado_cnpj"
            enviar_mensagem(telefone, "📄 Informe o *CNPJ* da empresa:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_cnpj":
            clientes[telefone]["cnpj"] = texto
            clientes[telefone]["etapa"] = "atacado_cidade"
            enviar_mensagem(telefone, "📍 Informe a *cidade*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_cidade":
            clientes[telefone]["cidade"] = texto
            clientes[telefone]["etapa"] = "atacado_pecas"
            enviar_mensagem(telefone, "🛠️ Informe as peças por *código ou modelo*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "atacado_pecas":
            enviar_mensagem(
                telefone,
                "✅ *Solicitação de cotação recebida!*\n\n"
                f"🏢 *Empresa:* {clientes[telefone].get('empresa', '')}\n"
                f"📄 *CNPJ:* {clientes[telefone].get('cnpj', '')}\n"
                f"📍 *Cidade:* {clientes[telefone].get('cidade', '')}\n"
                f"🛠️ *Peças:* {texto}\n\n"
                "Nosso consultor comercial seguirá com o atendimento.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        elif etapa == "cadastro_logista_empresa":
            clientes[telefone]["empresa"] = texto
            clientes[telefone]["etapa"] = "cadastro_logista_cnpj"
            enviar_mensagem(telefone, "📄 Informe o *CNPJ*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "cadastro_logista_cnpj":
            clientes[telefone]["cnpj"] = texto
            clientes[telefone]["etapa"] = "cadastro_logista_responsavel"
            enviar_mensagem(telefone, "👤 Informe o *nome do responsável*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "cadastro_logista_responsavel":
            clientes[telefone]["responsavel"] = texto
            clientes[telefone]["etapa"] = "cadastro_logista_cidade"
            enviar_mensagem(telefone, "📍 Informe a *cidade*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "cadastro_logista_cidade":
            clientes[telefone]["cidade"] = texto
            clientes[telefone]["etapa"] = "cadastro_logista_telefone"
            enviar_mensagem(telefone, "📞 Informe o *telefone de contato*:")
            return jsonify({"status": "ok"}), 200

        elif etapa == "cadastro_logista_telefone":
            enviar_mensagem(
                telefone,
                "✅ *Cadastro de logista recebido com sucesso!*\n\n"
                f"🏢 *Empresa:* {clientes[telefone].get('empresa', '')}\n"
                f"📄 *CNPJ:* {clientes[telefone].get('cnpj', '')}\n"
                f"👤 *Responsável:* {clientes[telefone].get('responsavel', '')}\n"
                f"📍 *Cidade:* {clientes[telefone].get('cidade', '')}\n"
                f"📞 *Telefone:* {texto}\n\n"
                "Nossa equipe comercial dará continuidade.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        # ==========================
        # ACOMPANHAR SERVIÇO
        # ==========================
        elif etapa == "acompanhar_servico_nome":
            clientes[telefone]["nome_cliente"] = texto
            enviar_mensagem(
                telefone,
                "✅ *Solicitação de acompanhamento recebida!*\n\n"
                f"👤 *Cliente:* {texto}\n\n"
                "Nossa equipe vai localizar a moto no processo e retornar com as informações.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        # ==========================
        # AGENDAR SERVIÇO
        # ==========================
        elif etapa == "agendar_servico_nome":
            clientes[telefone]["nome_cliente"] = texto
            enviar_mensagem(
                telefone,
                "✅ *Pedido de agendamento recebido!*\n\n"
                f"👤 *Cliente:* {texto}\n\n"
                "Nossa equipe continuará com você para definir os detalhes do atendimento.\n\n"
                "_Equipe Motoshow Yamaha_"
            )
            resetar_cliente(telefone)
            return jsonify({"status": "ok"}), 200

        else:
            enviar_menu_principal(telefone)
            return jsonify({"status": "ok"}), 200

    except Exception as e:
        log_erro("Erro no webhook:", e)
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)