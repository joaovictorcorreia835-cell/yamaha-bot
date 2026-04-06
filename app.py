# ==========================================
# WEBHOOK
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Webhook ativo"}), 200

    processar_inatividade()

    payload = request.get_json(silent=True) or {}
    print("PAYLOAD RECEBIDO:", payload)

    if evento_eh_do_proprio_bot(payload):
        return jsonify({"status": "ignorado", "motivo": "mensagem do proprio bot"}), 200

    message_id = extrair_message_id(payload)
    if mensagem_ja_processada(message_id):
        return jsonify({"status": "ignorado", "motivo": "mensagem duplicada"}), 200

    registrar_mensagem_processada(message_id)

    telefone = extrair_telefone(payload)
    texto = extrair_mensagem_texto(payload).strip()

    if not telefone or telefone_eh_grupo(telefone):
        return jsonify({"status": "ignorado", "motivo": "grupo ou telefone invalido"}), 200

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)

    texto_normalizado = texto.lower().strip()

    if texto_normalizado in ["menu", "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]:
        liberar_trava_humana(telefone)
        clientes[telefone]["origem"] = "Menu Normal"
        limpar_dados_fluxo(telefone)
        enviar_mensagem(telefone, menu_principal())
        return jsonify({"status": "ok"}), 200

    if cliente_em_atendimento_humano(telefone):
        if texto_normalizado == "menu":
            liberar_trava_humana(telefone)
            limpar_dados_fluxo(telefone)
            enviar_mensagem(telefone, menu_principal())
        return jsonify({"status": "ok", "motivo": "cliente em atendimento humano"}), 200

    # Resposta de campanha
    if texto_normalizado == "1":
        if clientes[telefone].get("etapa") == "menu":
            clientes[telefone]["etapa"] = "revisao_modelo"
            enviar_mensagem(telefone, "Informe o modelo da sua Yamaha:")
            return jsonify({"status": "ok"}), 200

    if texto_normalizado == "2" and clientes[telefone].get("etapa") == "menu":
        clientes[telefone]["etapa"] = "pecas_menu"
        enviar_mensagem(telefone, submenu_pecas())
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "3" and clientes[telefone].get("etapa") == "menu":
        clientes[telefone]["etapa"] = "acessorio_nome"
        enviar_mensagem(telefone, "Informe o acessório desejado:")
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "4" and clientes[telefone].get("etapa") == "menu":
        clientes[telefone]["etapa"] = "garantia_menu"
        enviar_mensagem(telefone, submenu_garantia())
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "5" and clientes[telefone].get("etapa") == "menu":
        clientes[telefone]["etapa"] = "logista_menu"
        enviar_mensagem(telefone, submenu_logista())
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "6" and clientes[telefone].get("etapa") == "menu":
        salvar_atendimento(
            telefone=telefone,
            setor="Acompanhar Serviço",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            status="Acompanhamento solicitado",
            atendimento_humano="Não"
        )
        enviar_mensagem(
            telefone,
            "Para acompanhar seu serviço, informe seu nome completo ou CPF.\n\nEquipe Motoshow Yamaha"
        )
        clientes[telefone]["etapa"] = "acompanhar_servico"
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "7" and clientes[telefone].get("etapa") == "menu":
        transferir_para_humano(telefone, "Atendimento")
        return jsonify({"status": "ok"}), 200

    # ==========================================
    # FLUXO REVISÃO
    # ==========================================
    etapa = clientes[telefone].get("etapa")

    if etapa == "revisao_modelo":
        clientes[telefone]["modelo_moto"] = texto
        clientes[telefone]["etapa"] = "revisao_nome"
        enviar_mensagem(telefone, "Informe seu nome completo:")
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_nome":
        clientes[telefone]["nome_cliente"] = texto
        clientes[telefone]["etapa"] = "revisao_ano"
        enviar_mensagem(telefone, "Informe o ano da sua moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_ano":
        clientes[telefone]["ano_moto"] = texto
        clientes[telefone]["etapa"] = "revisao_numero"
        enviar_mensagem(
            telefone,
            "Qual revisão deseja?\n\n"
            "1️⃣ 1ª Revisão\n"
            "2️⃣ 2ª Revisão\n"
            "3️⃣ 3ª Revisão ou acima"
        )
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_numero":
        if texto_normalizado not in ["1", "2", "3"]:
            enviar_mensagem(telefone, "Escolha uma opção válida:\n1️⃣ 1ª Revisão\n2️⃣ 2ª Revisão\n3️⃣ 3ª Revisão ou acima")
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["revisao_numero"] = texto_normalizado
        clientes[telefone]["etapa"] = "revisao_dia"
        enviar_mensagem(
            telefone,
            "Informe o dia desejado:\n\n"
            "Segunda\nTerça\nQuarta\nQuinta\nSexta\nSábado"
        )
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_dia":
        clientes[telefone]["dia_semana"] = texto
        lista_horarios = horarios_disponiveis(
            clientes[telefone]["revisao_numero"],
            clientes[telefone]["dia_semana"]
        )

        if not lista_horarios:
            enviar_mensagem(
                telefone,
                "Para essa revisão não há disponibilidade nesse dia.\n\n"
                "Digite outro dia da semana.\n\n"
                "Equipe Motoshow Yamaha"
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["horarios_opcoes"] = lista_horarios
        clientes[telefone]["etapa"] = "revisao_horario"
        enviar_mensagem(telefone, texto_opcoes_horario(lista_horarios))
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_horario":
        opcoes = clientes[telefone].get("horarios_opcoes", [])
        if not texto_normalizado.isdigit():
            enviar_mensagem(telefone, "Informe apenas o número da opção do horário.")
            return jsonify({"status": "ok"}), 200

        indice = int(texto_normalizado) - 1
        if indice < 0 or indice >= len(opcoes):
            enviar_mensagem(telefone, "Opção inválida. Escolha um número de horário disponível.")
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["horario_escolhido"] = opcoes[indice]
        clientes[telefone]["etapa"] = "revisao_itens"
        enviar_mensagem(
            telefone,
            "Deseja incluir algum item?\n\n"
            "1️⃣ Troca de óleo\n"
            "2️⃣ Pastilha de freio\n"
            "3️⃣ Filtro de ar\n"
            "4️⃣ Kit relação\n"
            "5️⃣ Acessórios\n"
            "0️⃣ Não desejo\n\n"
            "Pode enviar mais de um separado por vírgula.\nExemplo: 1,3"
        )
        return jsonify({"status": "ok"}), 200
    from flask import Flask, request, jsonify, render_template, send_from_directory
import requests
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import func

from database import (
    criar_banco,
    SessionLocal,
    Atendimento,
    salvar_atendimento,
    total_atendimentos,
    total_por_setor,
    total_agendamentos_concluidos,
    total_atendimento_humano,
    total_origem,
    revisoes_mais_solicitadas,
    itens_mais_vendidos
)

load_dotenv()

app = Flask(__name__)
criar_banco()

# ==========================================
# CONFIG
# ==========================================
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://yamaha-bot-1.onrender.com")
PORT = int(os.getenv("PORT", 5000))
TEMPO_INATIVIDADE = int(os.getenv("TEMPO_INATIVIDADE", 900))

url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"

clientes = {}
mensagens_processadas = {}

MODELOS_YAMAHA = [
    "FAZER 250", "FZ15", "CROSSER", "LANDER", "MT03", "MT07",
    "R15", "R3", "FLUO", "NEO", "NMAX", "TENERE 700", "AEROX"
]

ITENS_ADICIONAIS = {
    "1": "Troca de óleo",
    "2": "Pastilha de freio",
    "3": "Filtro de ar",
    "4": "Kit relação",
    "5": "Acessórios"
}


# ==========================================
# UTILITÁRIOS
# ==========================================
def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = {
            "etapa": "menu",
            "ultima_interacao": time.time(),
            "origem": "Menu Normal",
            "nome_cliente": "",
            "modelo_moto": "",
            "ano_moto": "",
            "revisao_numero": "",
            "dia_semana": "",
            "horario_escolhido": "",
            "itens": "",
            "peca_nome": "",
            "cor": "",
            "cpf": "",
            "km_atual": "",
            "problema": "",
            "empresa": "",
            "cnpj": "",
            "cidade": "",
            "responsavel": "",
            "acessorio_nome": "",
            "consulta_item": "",
            "atendimento_humano": False
        }


def limpar_dados_fluxo(telefone):
    iniciar_cliente(telefone)
    origem_atual = clientes[telefone].get("origem", "Menu Normal")
    atendimento_humano = clientes[telefone].get("atendimento_humano", False)

    clientes[telefone] = {
        "etapa": "menu",
        "ultima_interacao": time.time(),
        "origem": origem_atual,
        "nome_cliente": "",
        "modelo_moto": "",
        "ano_moto": "",
        "revisao_numero": "",
        "dia_semana": "",
        "horario_escolhido": "",
        "itens": "",
        "peca_nome": "",
        "cor": "",
        "cpf": "",
        "km_atual": "",
        "problema": "",
        "empresa": "",
        "cnpj": "",
        "cidade": "",
        "responsavel": "",
        "acessorio_nome": "",
        "consulta_item": "",
        "atendimento_humano": atendimento_humano
    }


def atualizar_interacao(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["ultima_interacao"] = time.time()


def telefone_eh_grupo(telefone):
    return "@g.us" in str(telefone)


def evento_eh_do_proprio_bot(payload):
    if payload.get("fromMe") is True:
        return True

    message = payload.get("message") or {}
    if isinstance(message, dict):
        if message.get("fromMe") is True:
            return True

        data = message.get("data") or {}
        if isinstance(data, dict) and data.get("fromMe") is True:
            return True

    return False


def extrair_message_id(payload):
    for chave in ["messageId", "id"]:
        if payload.get(chave):
            return str(payload.get(chave))

    message = payload.get("message") or {}
    if isinstance(message, dict):
        if message.get("messageId"):
            return str(message.get("messageId"))
        if message.get("id"):
            return str(message.get("id"))

        data = message.get("data") or {}
        if isinstance(data, dict):
            if data.get("id"):
                return str(data.get("id"))
            if data.get("messageId"):
                return str(data.get("messageId"))

    return None


def extrair_telefone(payload):
    for chave in ["phone", "from", "sender"]:
        if payload.get(chave):
            return str(payload.get(chave))

    message = payload.get("message") or {}
    if isinstance(message, dict):
        for chave in ["phone", "from", "sender"]:
            if message.get(chave):
                return str(message.get(chave))

        data = message.get("data") or {}
        if isinstance(data, dict):
            for chave in ["phone", "from", "sender"]:
                if data.get(chave):
                    return str(data.get(chave))

    return ""


def extrair_mensagem_texto(payload):
    candidatos = []

    for chave in ["text", "message", "body"]:
        valor = payload.get(chave)
        if isinstance(valor, str):
            candidatos.append(valor)

    message = payload.get("message") or {}
    if isinstance(message, dict):
        for chave in ["text", "body"]:
            valor = message.get(chave)
            if isinstance(valor, str):
                candidatos.append(valor)

        text_obj = message.get("text")
        if isinstance(text_obj, dict):
            for chave in ["message", "body"]:
                valor = text_obj.get(chave)
                if isinstance(valor, str):
                    candidatos.append(valor)

        data = message.get("data") or {}
        if isinstance(data, dict):
            for chave in ["text", "body"]:
                valor = data.get(chave)
                if isinstance(valor, str):
                    candidatos.append(valor)

            extended = data.get("extendedTextMessage") or {}
            if isinstance(extended, dict):
                texto = extended.get("text")
                if isinstance(texto, str):
                    candidatos.append(texto)

            conversation = data.get("conversation")
            if isinstance(conversation, str):
                candidatos.append(conversation)

    for item in candidatos:
        texto = item.strip()
        if texto:
            return texto

    return ""


def registrar_mensagem_processada(message_id):
    if not message_id:
        return
    mensagens_processadas[message_id] = time.time()

    agora = time.time()
    expirados = [mid for mid, ts in mensagens_processadas.items() if agora - ts > 600]
    for mid in expirados:
        mensagens_processadas.pop(mid, None)

        def mensagem_ja_processada(message_id):
    if not message_id:
        return False
    return message_id in mensagens_processadas


def enviar_mensagem(telefone, mensagem):
    payload = {
        "phone": telefone,
        "message": mensagem
    }

    headers = {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN
    }

    try:
        response = requests.post(url_envio, json=payload, headers=headers, timeout=30)
        print(f"[ENVIO] {telefone} -> {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
        return False


def enviar_catalogo_pdf(telefone):
    pdf_url = f"{BASE_URL}/pdf/catalogo-atacado.pdf"

    payload = {
        "phone": telefone,
        "pdf": pdf_url,
        "fileName": "catalogo-atacado.pdf",
        "caption": "📄 Catálogo Atacado Motoshow Yamaha"
    }

    headers = {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN
    }

    try:
        response = requests.post(url_documento, json=payload, headers=headers, timeout=60)
        print(f"[PDF] {telefone} -> {response.status_code} | {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"Erro ao enviar PDF: {e}")
        return False


def menu_principal():
    return """Olá 👋

Bem-vindo ao Pós-Vendas Motoshow Yamaha 🏍️
Estamos prontos para ajudar com revisões, peças, garantia e serviços.

Digite uma opção:

1️⃣ Agendar Revisão
2️⃣ Peças
3️⃣ Acessórios
4️⃣ Garantia
5️⃣ Logista / Atacado
6️⃣ Acompanhar Serviço
7️⃣ Falar com Atendente"""


def submenu_pecas():
    return """Peças Motoshow Yamaha 🛠️

Selecione uma opção:

1️⃣ Peças Originais
2️⃣ Acessórios
3️⃣ Consultar Disponibilidade
4️⃣ Falar com Atendente
0️⃣ Voltar ao Menu Principal"""


def submenu_garantia():
    return """Garantia Motoshow Yamaha 🛡️

Selecione uma opção:

1️⃣ Nova Solicitação
2️⃣ Acompanhar Garantia
3️⃣ Falar com Atendente
0️⃣ Voltar ao Menu Principal"""


def submenu_logista():
    return """Logista / Atacado 🏪

Selecione uma opção:

1️⃣ Solicitar Cotação
2️⃣ Cadastro Logista
3️⃣ Catálogo de Peças
4️⃣ Falar com Consultor
0️⃣ Voltar ao Menu Principal"""


def horarios_disponiveis(revisao, dia_semana):
    dia = dia_semana.strip().lower()

    if dia in ["segunda", "terça", "terca", "quarta", "quinta", "sexta"]:
        if revisao in ["1", "2"]:
            return ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"]
        return ["08:00"]

    if dia == "sábado" or dia == "sabado":
        if revisao in ["1", "2"]:
            return ["08:00", "09:00", "10:00"]
        return []

    return []


def texto_opcoes_horario(lista_horarios):
    linhas = ["Selecione um horário disponível:"]
    for i, horario in enumerate(lista_horarios, start=1):
        linhas.append(f"{i}️⃣ {horario}")
    return "\n".join(linhas)


def ultima_trava_humana(telefone):
    session = SessionLocal()
    try:
        registro = (
            session.query(Atendimento)
            .filter(Atendimento.telefone == telefone, Atendimento.atendimento_humano == "Sim")
            .order_by(Atendimento.criado_em.desc())
            .first()
        )
        return registro is not None
    finally:
        session.close()


def liberar_trava_humana(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["atendimento_humano"] = False


def ativar_trava_humana(telefone):
    iniciar_cliente(telefone)
    clientes[telefone]["atendimento_humano"] = True


def cliente_em_atendimento_humano(telefone):
    iniciar_cliente(telefone)
    return clientes[telefone].get("atendimento_humano", False) or ultima_trava_humana(telefone)


def processar_inatividade():
    agora = time.time()
    for telefone in list(clientes.keys()):
        if clientes[telefone].get("atendimento_humano"):
            continue

        ultima = clientes[telefone].get("ultima_interacao", agora)
        if agora - ultima > TEMPO_INATIVIDADE and clientes[telefone].get("etapa") != "encerrado":
            enviar_mensagem(
                telefone,
                "Seu atendimento foi encerrado por inatividade.\n\n"
                "Quando quiser continuar envie:\nmenu\n\n"
                "Equipe Motoshow Yamaha"
            )
            clientes[telefone]["etapa"] = "encerrado"
            clientes[telefone]["ultima_interacao"] = agora


def salvar_agendamento_revisao(telefone):
    dados = clientes[telefone]
    salvar_atendimento(
        telefone=telefone,
        nome=dados.get("nome_cliente"),
        setor="Revisão",
        origem=dados.get("origem", "Menu Normal"),
        modelo=dados.get("modelo_moto"),
        ano=dados.get("ano_moto"),
        revisao=f"{dados.get('revisao_numero')}ª Revisão" if dados.get("revisao_numero") in ["1", "2"] else "3ª Revisão ou acima",
        horario=dados.get("horario_escolhido"),
        status="Agendado",
        atendimento_humano="Não",
        itens=dados.get("itens")
    )
    def salvar_peca_original(telefone):
    dados = clientes[telefone]
    salvar_atendimento(
        telefone=telefone,
        nome=dados.get("nome_cliente"),
        setor="Peças",
        origem=dados.get("origem", "Menu Normal"),
        modelo=dados.get("modelo_moto"),
        ano=dados.get("ano_moto"),
        status="Solicitação recebida",
        atendimento_humano="Não",
        peca_nome=dados.get("peca_nome"),
        cor=dados.get("cor")
    )


def salvar_acessorio(telefone):
    dados = clientes[telefone]
    salvar_atendimento(
        telefone=telefone,
        nome=dados.get("nome_cliente"),
        setor="Acessórios",
        origem=dados.get("origem", "Menu Normal"),
        modelo=dados.get("modelo_moto"),
        status="Solicitação recebida",
        atendimento_humano="Não",
        itens=dados.get("acessorio_nome")
    )


def salvar_consulta_disponibilidade(telefone):
    dados = clientes[telefone]
    salvar_atendimento(
        telefone=telefone,
        nome=dados.get("nome_cliente"),
        setor="Peças",
        origem=dados.get("origem", "Menu Normal"),
        modelo=dados.get("modelo_moto"),
        status="Consulta recebida",
        atendimento_humano="Não",
        peca_nome=dados.get("consulta_item")
    )


def salvar_garantia_nova(telefone):
    dados = clientes[telefone]
    salvar_atendimento(
        telefone=telefone,
        nome=dados.get("nome_cliente"),
        setor="Garantia",
        origem=dados.get("origem", "Menu Normal"),
        modelo=dados.get("modelo_moto"),
        ano=dados.get("ano_moto"),
        status="Nova solicitação",
        atendimento_humano="Não",
        km_atual=dados.get("km_atual"),
        problema=dados.get("problema")
    )


def salvar_garantia_acompanhamento(telefone):
    dados = clientes[telefone]
    salvar_atendimento(
        telefone=telefone,
        nome=dados.get("nome_cliente"),
        setor="Garantia",
        origem=dados.get("origem", "Menu Normal"),
        status="Acompanhamento solicitado",
        atendimento_humano="Não",
        cpf=dados.get("cpf")
    )


def salvar_logista_cotacao(telefone):
    dados = clientes[telefone]
    salvar_atendimento(
        telefone=telefone,
        nome=dados.get("responsavel"),
        setor="Logista / Atacado",
        origem=dados.get("origem", "Menu Normal"),
        status="Cotação solicitada",
        atendimento_humano="Não",
        empresa=dados.get("empresa"),
        cnpj=dados.get("cnpj"),
        cidade=dados.get("cidade"),
        peca_nome=dados.get("peca_nome")
    )


def salvar_logista_cadastro(telefone):
    dados = clientes[telefone]
    salvar_atendimento(
        telefone=telefone,
        nome=dados.get("responsavel"),
        setor="Logista / Atacado",
        origem=dados.get("origem", "Menu Normal"),
        status="Cadastro solicitado",
        atendimento_humano="Não",
        empresa=dados.get("empresa"),
        cnpj=dados.get("cnpj"),
        cidade=dados.get("cidade"),
        responsavel=dados.get("responsavel")
    )


def transferir_para_humano(telefone, setor):
    ativar_trava_humana(telefone)
    salvar_atendimento(
        telefone=telefone,
        nome=clientes.get(telefone, {}).get("nome_cliente"),
        setor=setor,
        origem=clientes.get(telefone, {}).get("origem", "Menu Normal"),
        status="Transferido para atendimento humano",
        atendimento_humano="Sim"
    )
    return enviar_mensagem(
        telefone,
        f"Você será transferido para um atendente do setor de {setor} 👨‍💼\n\n"
        f"Aguarde um momento...\n\n"
        f"Equipe Motoshow Yamaha"
    )


# ==========================================
# ROTAS BÁSICAS
# ==========================================
@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"


@app.route("/pdf/<arquivo>")
def servir_pdf(arquivo):
    return send_from_directory("static/pdfs", arquivo)


@app.route("/dashboard")
def dashboard():
    dados_revisoes = revisoes_mais_solicitadas()
    dados_itens = itens_mais_vendidos()

    return render_template(
        "dashboard.html",
        total_atendimentos=total_atendimentos(),
        agendamentos_concluidos=total_agendamentos_concluidos(),
        atendimento_humano=total_atendimento_humano(),
        origem_campanha=total_origem("Campanha"),
        origem_menu=total_origem("Menu Normal"),
        total_revisao=total_por_setor("Revisão"),
        total_pecas=total_por_setor("Peças"),
        total_acessorios=total_por_setor("Acessórios"),
        total_garantia=total_por_setor("Garantia"),
        total_logista=total_por_setor("Logista / Atacado"),
        revisoes=dados_revisoes,
        itens=dados_itens
    )
# ==========================================
# WEBHOOK
# ==========================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Webhook ativo"}), 200

    processar_inatividade()

    payload = request.get_json(silent=True) or {}
    print("PAYLOAD RECEBIDO:", payload)

    if evento_eh_do_proprio_bot(payload):
        return jsonify({"status": "ignorado", "motivo": "mensagem do proprio bot"}), 200

    message_id = extrair_message_id(payload)
    if mensagem_ja_processada(message_id):
        return jsonify({"status": "ignorado", "motivo": "mensagem duplicada"}), 200

    registrar_mensagem_processada(message_id)

    telefone = extrair_telefone(payload)
    texto = extrair_mensagem_texto(payload).strip()

    if not telefone or telefone_eh_grupo(telefone):
        return jsonify({"status": "ignorado", "motivo": "grupo ou telefone invalido"}), 200

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)

    texto_normalizado = texto.lower().strip()

    if texto_normalizado in ["menu", "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]:
        liberar_trava_humana(telefone)
        clientes[telefone]["origem"] = "Menu Normal"
        limpar_dados_fluxo(telefone)
        enviar_mensagem(telefone, menu_principal())
        return jsonify({"status": "ok"}), 200

    if cliente_em_atendimento_humano(telefone):
        if texto_normalizado == "menu":
            liberar_trava_humana(telefone)
            limpar_dados_fluxo(telefone)
            enviar_mensagem(telefone, menu_principal())
        return jsonify({"status": "ok", "motivo": "cliente em atendimento humano"}), 200

    # Resposta de campanha
    if texto_normalizado == "1":
        if clientes[telefone].get("etapa") == "menu":
            clientes[telefone]["etapa"] = "revisao_modelo"
            enviar_mensagem(telefone, "Informe o modelo da sua Yamaha:")
            return jsonify({"status": "ok"}), 200

    if texto_normalizado == "2" and clientes[telefone].get("etapa") == "menu":
        clientes[telefone]["etapa"] = "pecas_menu"
        enviar_mensagem(telefone, submenu_pecas())
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "3" and clientes[telefone].get("etapa") == "menu":
        clientes[telefone]["etapa"] = "acessorio_nome"
        enviar_mensagem(telefone, "Informe o acessório desejado:")
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "4" and clientes[telefone].get("etapa") == "menu":
        clientes[telefone]["etapa"] = "garantia_menu"
        enviar_mensagem(telefone, submenu_garantia())
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "5" and clientes[telefone].get("etapa") == "menu":
        clientes[telefone]["etapa"] = "logista_menu"
        enviar_mensagem(telefone, submenu_logista())
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "6" and clientes[telefone].get("etapa") == "menu":
        salvar_atendimento(
            telefone=telefone,
            setor="Acompanhar Serviço",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            status="Acompanhamento solicitado",
            atendimento_humano="Não"
        )
        enviar_mensagem(
            telefone,
            "Para acompanhar seu serviço, informe seu nome completo ou CPF.\n\nEquipe Motoshow Yamaha"
        )
        clientes[telefone]["etapa"] = "acompanhar_servico"
        return jsonify({"status": "ok"}), 200

    if texto_normalizado == "7" and clientes[telefone].get("etapa") == "menu":
        transferir_para_humano(telefone, "Atendimento")
        return jsonify({"status": "ok"}), 200

    # ==========================================
    # FLUXO REVISÃO
    # ==========================================
    etapa = clientes[telefone].get("etapa")

    if etapa == "revisao_modelo":
        clientes[telefone]["modelo_moto"] = texto
        clientes[telefone]["etapa"] = "revisao_nome"
        enviar_mensagem(telefone, "Informe seu nome completo:")
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_nome":
        clientes[telefone]["nome_cliente"] = texto
        clientes[telefone]["etapa"] = "revisao_ano"
        enviar_mensagem(telefone, "Informe o ano da sua moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_ano":
        clientes[telefone]["ano_moto"] = texto
        clientes[telefone]["etapa"] = "revisao_numero"
        enviar_mensagem(
            telefone,
            "Qual revisão deseja?\n\n"
            "1️⃣ 1ª Revisão\n"
            "2️⃣ 2ª Revisão\n"
            "3️⃣ 3ª Revisão ou acima"
        )
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_numero":
        if texto_normalizado not in ["1", "2", "3"]:
            enviar_mensagem(telefone, "Escolha uma opção válida:\n1️⃣ 1ª Revisão\n2️⃣ 2ª Revisão\n3️⃣ 3ª Revisão ou acima")
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["revisao_numero"] = texto_normalizado
        clientes[telefone]["etapa"] = "revisao_dia"
        enviar_mensagem(
            telefone,
            "Informe o dia desejado:\n\n"
            "Segunda\nTerça\nQuarta\nQuinta\nSexta\nSábado"
        )
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_dia":
        clientes[telefone]["dia_semana"] = texto
        lista_horarios = horarios_disponiveis(
            clientes[telefone]["revisao_numero"],
            clientes[telefone]["dia_semana"]
        )

        if not lista_horarios:
            enviar_mensagem(
                telefone,
                "Para essa revisão não há disponibilidade nesse dia.\n\n"
                "Digite outro dia da semana.\n\n"
                "Equipe Motoshow Yamaha"
            )
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["horarios_opcoes"] = lista_horarios
        clientes[telefone]["etapa"] = "revisao_horario"
        enviar_mensagem(telefone, texto_opcoes_horario(lista_horarios))
        return jsonify({"status": "ok"}), 200

    if etapa == "revisao_horario":
        opcoes = clientes[telefone].get("horarios_opcoes", [])
        if not texto_normalizado.isdigit():
            enviar_mensagem(telefone, "Informe apenas o número da opção do horário.")
            return jsonify({"status": "ok"}), 200

        indice = int(texto_normalizado) - 1
        if indice < 0 or indice >= len(opcoes):
            enviar_mensagem(telefone, "Opção inválida. Escolha um número de horário disponível.")
            return jsonify({"status": "ok"}), 200

        clientes[telefone]["horario_escolhido"] = opcoes[indice]
        clientes[telefone]["etapa"] = "revisao_itens"
        enviar_mensagem(
            telefone,
            "Deseja incluir algum item?\n\n"
            "1️⃣ Troca de óleo\n"
            "2️⃣ Pastilha de freio\n"
            "3️⃣ Filtro de ar\n"
            "4️⃣ Kit relação\n"
            "5️⃣ Acessórios\n"
            "0️⃣ Não desejo\n\n"
            "Pode enviar mais de um separado por vírgula.\nExemplo: 1,3"
        )
        return jsonify({"status": "ok"}), 200
    
        if etapa == "revisao_itens":
        itens_escolhidos = []

        if texto_normalizado != "0":
            partes = [p.strip() for p in texto_normalizado.split(",")]
            for p in partes:
                if p in ITENS_ADICIONAIS:
                    itens_escolhidos.append(ITENS_ADICIONAIS[p])

        clientes[telefone]["itens"] = ", ".join(itens_escolhidos) if itens_escolhidos else ""
        salvar_agendamento_revisao(telefone)

        revisao_txt = f"{clientes[telefone]['revisao_numero']}ª Revisão" if clientes[telefone]["revisao_numero"] in ["1", "2"] else "3ª Revisão ou acima"

        enviar_mensagem(
            telefone,
            f"Agendamento realizado com sucesso ✅\n\n"
            f"Nome: {clientes[telefone]['nome_cliente']}\n"
            f"Moto: {clientes[telefone]['modelo_moto']}\n"
            f"Ano: {clientes[telefone]['ano_moto']}\n"
            f"Revisão: {revisao_txt}\n"
            f"Dia: {clientes[telefone]['dia_semana']}\n"
            f"Horário: {clientes[telefone]['horario_escolhido']}\n"
            f"Itens: {clientes[telefone]['itens'] if clientes[telefone]['itens'] else 'Nenhum'}\n\n"
            f"Nossa equipe entrará em contato para confirmação.\n\n"
            f"Equipe Motoshow Yamaha"
        )
        limpar_dados_fluxo(telefone)
        return jsonify({"status": "ok"}), 200

    # ==========================================
    # SUBMENU PEÇAS
    # ==========================================
    if etapa == "pecas_menu":
        if texto_normalizado == "1":
            clientes[telefone]["etapa"] = "peca_nome"
            enviar_mensagem(telefone, "Informe o nome da peça desejada:")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "2":
            clientes[telefone]["etapa"] = "acessorio_nome"
            enviar_mensagem(telefone, "Informe o acessório desejado:")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "3":
            clientes[telefone]["etapa"] = "consulta_item"
            enviar_mensagem(telefone, "Informe a peça ou acessório que deseja consultar:")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "4":
            transferir_para_humano(telefone, "Peças")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "0":
            clientes[telefone]["etapa"] = "menu"
            enviar_mensagem(telefone, menu_principal())
            return jsonify({"status": "ok"}), 200

    if etapa == "peca_nome":
        clientes[telefone]["peca_nome"] = texto
        clientes[telefone]["etapa"] = "peca_modelo"
        enviar_mensagem(telefone, "Informe o modelo da sua moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "peca_modelo":
        clientes[telefone]["modelo_moto"] = texto
        clientes[telefone]["etapa"] = "peca_ano"
        enviar_mensagem(telefone, "Informe o ano da moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "peca_ano":
        clientes[telefone]["ano_moto"] = texto
        clientes[telefone]["etapa"] = "peca_cor"
        enviar_mensagem(telefone, "Informe a cor da moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "peca_cor":
        clientes[telefone]["cor"] = texto
        salvar_peca_original(telefone)
        enviar_mensagem(
            telefone,
            f"Recebemos sua solicitação de peça ✅\n\n"
            f"Peça: {clientes[telefone]['peca_nome']}\n"
            f"Modelo: {clientes[telefone]['modelo_moto']}\n"
            f"Ano: {clientes[telefone]['ano_moto']}\n"
            f"Cor: {clientes[telefone]['cor']}\n\n"
            f"Nossa equipe de peças irá verificar disponibilidade e retorno.\n\n"
            f"Equipe Motoshow Yamaha"
        )
        limpar_dados_fluxo(telefone)
        return jsonify({"status": "ok"}), 200

    if etapa == "acessorio_nome":
        clientes[telefone]["acessorio_nome"] = texto
        clientes[telefone]["etapa"] = "acessorio_modelo"
        enviar_mensagem(telefone, "Informe o modelo da sua moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "acessorio_modelo":
        clientes[telefone]["modelo_moto"] = texto
        salvar_acessorio(telefone)
        enviar_mensagem(
            telefone,
            f"Recebemos sua solicitação de acessório ✅\n\n"
            f"Acessório: {clientes[telefone]['acessorio_nome']}\n"
            f"Modelo: {clientes[telefone]['modelo_moto']}\n\n"
            f"Nossa equipe irá retornar com disponibilidade.\n\n"
            f"Equipe Motoshow Yamaha"
        )
        limpar_dados_fluxo(telefone)
        return jsonify({"status": "ok"}), 200

    if etapa == "consulta_item":
        clientes[telefone]["consulta_item"] = texto
        clientes[telefone]["etapa"] = "consulta_modelo"
        enviar_mensagem(telefone, "Informe o modelo da sua moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "consulta_modelo":
        clientes[telefone]["modelo_moto"] = texto
        salvar_consulta_disponibilidade(telefone)
        enviar_mensagem(
            telefone,
            f"Consulta recebida ✅\n\n"
            f"Item: {clientes[telefone]['consulta_item']}\n"
            f"Modelo: {clientes[telefone]['modelo_moto']}\n\n"
            f"Vamos verificar a disponibilidade e em breve retornaremos.\n\n"
            f"Equipe Motoshow Yamaha"
        )
        limpar_dados_fluxo(telefone)
        return jsonify({"status": "ok"}), 200

    # ==========================================
    # GARANTIA
    # ==========================================
    if etapa == "garantia_menu":
        if texto_normalizado == "1":
            clientes[telefone]["etapa"] = "garantia_nova_nome"
            enviar_mensagem(telefone, "Informe seu nome completo:")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "2":
            clientes[telefone]["etapa"] = "garantia_acomp_nome"
            enviar_mensagem(telefone, "Informe seu nome completo:")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "3":
            transferir_para_humano(telefone, "Garantia")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "0":
            clientes[telefone]["etapa"] = "menu"
            enviar_mensagem(telefone, menu_principal())
            return jsonify({"status": "ok"}), 200

    if etapa == "garantia_nova_nome":
        clientes[telefone]["nome_cliente"] = texto
        clientes[telefone]["etapa"] = "garantia_nova_modelo"
        enviar_mensagem(telefone, "Informe o modelo da sua moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "garantia_nova_modelo":
        clientes[telefone]["modelo_moto"] = texto
        clientes[telefone]["etapa"] = "garantia_nova_ano"
        enviar_mensagem(telefone, "Informe o ano da moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "garantia_nova_ano":
        clientes[telefone]["ano_moto"] = texto
        clientes[telefone]["etapa"] = "garantia_nova_problema"
        enviar_mensagem(telefone, "Descreva o problema apresentado na moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "garantia_nova_problema":
        clientes[telefone]["problema"] = texto
        clientes[telefone]["etapa"] = "garantia_nova_km"
        enviar_mensagem(telefone, "Informe a quilometragem atual da moto:")
        return jsonify({"status": "ok"}), 200

    if etapa == "garantia_nova_km":
        clientes[telefone]["km_atual"] = texto
        salvar_garantia_nova(telefone)
        enviar_mensagem(
            telefone,
            f"Recebemos sua solicitação de garantia ✅\n\n"
            f"Nome: {clientes[telefone]['nome_cliente']}\n"
            f"Modelo: {clientes[telefone]['modelo_moto']}\n"
            f"Ano: {clientes[telefone]['ano_moto']}\n"
            f"Problema: {clientes[telefone]['problema']}\n"
            f"KM atual: {clientes[telefone]['km_atual']}\n\n"
            f"Nossa equipe irá analisar as informações e retornar em breve.\n\n"
            f"Equipe Motoshow Yamaha"
        )
        limpar_dados_fluxo(telefone)
        return jsonify({"status": "ok"}), 200

    if etapa == "garantia_acomp_nome":
        clientes[telefone]["nome_cliente"] = texto
        clientes[telefone]["etapa"] = "garantia_acomp_cpf"
        enviar_mensagem(telefone, "Informe seu CPF para consultar o andamento da garantia:")
        return jsonify({"status": "ok"}), 200

    if etapa == "garantia_acomp_cpf":
        clientes[telefone]["cpf"] = texto
        salvar_garantia_acompanhamento(telefone)
        enviar_mensagem(
            telefone,
            f"Recebemos sua solicitação de acompanhamento ✅\n\n"
            f"Nome: {clientes[telefone]['nome_cliente']}\n"
            f"CPF: {clientes[telefone]['cpf']}\n\n"
            f"Nossa equipe irá verificar o andamento da garantia e retornará em breve.\n\n"
            f"Equipe Motoshow Yamaha"
        )
        limpar_dados_fluxo(telefone)
        return jsonify({"status": "ok"}), 200

    # ==========================================
    # LOGISTA / ATACADO
    # ==========================================
    if etapa == "logista_menu":
        if texto_normalizado == "1":
            clientes[telefone]["etapa"] = "logista_cot_empresa"
            enviar_mensagem(telefone, "Informe o nome da empresa:")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "2":
            clientes[telefone]["etapa"] = "logista_cad_empresa"
            enviar_mensagem(telefone, "Informe o nome da empresa:")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "3":
            enviado = enviar_catalogo_pdf(telefone)
            if enviado:
                enviar_mensagem(telefone, "Catálogo enviado com sucesso ✅\n\nEquipe Motoshow Yamaha")
            else:
                enviar_mensagem(telefone, "Não foi possível enviar o catálogo agora. Nossa equipe irá auxiliar em seguida.\n\nEquipe Motoshow Yamaha")
            clientes[telefone]["etapa"] = "menu"
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "4":
            transferir_para_humano(telefone, "Logista / Atacado")
            return jsonify({"status": "ok"}), 200

        if texto_normalizado == "0":
            clientes[telefone]["etapa"] = "menu"
            enviar_mensagem(telefone, menu_principal())
            return jsonify({"status": "ok"}), 200

    if etapa == "logista_cot_empresa":
        clientes[telefone]["empresa"] = texto
        clientes[telefone]["etapa"] = "logista_cot_cnpj"
        enviar_mensagem(telefone, "Informe o CNPJ:")
        return jsonify({"status": "ok"}), 200

    if etapa == "logista_cot_cnpj":
        clientes[telefone]["cnpj"] = texto
        clientes[telefone]["etapa"] = "logista_cot_cidade"
        enviar_mensagem(telefone, "Informe a cidade:")
        return jsonify({"status": "ok"}), 200

    if etapa == "logista_cot_cidade":
        clientes[telefone]["cidade"] = texto
        clientes[telefone]["etapa"] = "logista_cot_pecas"
        enviar_mensagem(telefone, "Informe as peças desejadas (por código ou modelo):")
        return jsonify({"status": "ok"}), 200

    if etapa == "logista_cot_pecas":
        clientes[telefone]["peca_nome"] = texto
        salvar_logista_cotacao(telefone)
        enviar_mensagem(
            telefone,
            f"Solicitação de cotação recebida ✅\n\n"
            f"Empresa: {clientes[telefone]['empresa']}\n"
            f"CNPJ: {clientes[telefone]['cnpj']}\n"
            f"Cidade: {clientes[telefone]['cidade']}\n"
            f"Peças: {clientes[telefone]['peca_nome']}\n\n"
            f"Nosso consultor comercial retornará em breve.\n\n"
            f"Equipe Motoshow Yamaha"
        )
        limpar_dados_fluxo(telefone)
        return jsonify({"status": "ok"}), 200

    if etapa == "logista_cad_empresa":
        clientes[telefone]["empresa"] = texto
        clientes[telefone]["etapa"] = "logista_cad_cnpj"
        enviar_mensagem(telefone, "Informe o CNPJ:")
        return jsonify({"status": "ok"}), 200

    if etapa == "logista_cad_cnpj":
        clientes[telefone]["cnpj"] = texto
        clientes[telefone]["etapa"] = "logista_cad_responsavel"
        enviar_mensagem(telefone, "Informe o nome do responsável:")
        return jsonify({"status": "ok"}), 200

    if etapa == "logista_cad_responsavel":
        clientes[telefone]["responsavel"] = texto
        clientes[telefone]["etapa"] = "logista_cad_cidade"
        enviar_mensagem(telefone, "Informe a cidade:")
        return jsonify({"status": "ok"}), 200

    if etapa == "logista_cad_cidade":
        clientes[telefone]["cidade"] = texto
        salvar_logista_cadastro(telefone)
        enviar_mensagem(
            telefone,
            f"Cadastro de logista recebido ✅\n\n"
            f"Empresa: {clientes[telefone]['empresa']}\n"
            f"CNPJ: {clientes[telefone]['cnpj']}\n"
            f"Responsável: {clientes[telefone]['responsavel']}\n"
            f"Cidade: {clientes[telefone]['cidade']}\n\n"
            f"Nosso consultor entrará em contato em breve.\n\n"
            f"Equipe Motoshow Yamaha"
        )
        limpar_dados_fluxo(telefone)
        return jsonify({"status": "ok"}), 200

    if etapa == "acompanhar_servico":
        salvar_atendimento(
            telefone=telefone,
            nome=texto,
            setor="Acompanhar Serviço",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            status="Consulta recebida",
            atendimento_humano="Não"
        )
        enviar_mensagem(
            telefone,
            f"Recebemos sua solicitação de acompanhamento ✅\n\n"
            f"Informação enviada: {texto}\n\n"
            f"Nossa equipe irá verificar e retornar em breve.\n\n"
            f"Equipe Motoshow Yamaha"
        )
        limpar_dados_fluxo(telefone)
        return jsonify({"status": "ok"}), 200

    # fallback
    enviar_mensagem(telefone, "Não entendi sua mensagem.\n\nDigite *menu* para voltar ao início.\n\nEquipe Motoshow Yamaha")
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)