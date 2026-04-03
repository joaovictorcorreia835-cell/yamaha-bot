from flask import Flask, request, jsonify, send_from_directory, render_template
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import threading
import time
from sqlalchemy import func

from database import criar_banco, SessionLocal, Atendimento

load_dotenv()

app = Flask(__name__)
criar_banco()

@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"

ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")

BASE_URL = os.getenv("BASE_URL", "https://SEU-LINK-NGROK.ngrok-free.app")

url_envio = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
url_documento = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-document/pdf"

clientes = {}
TEMPO_INATIVIDADE = 900  # 15 minutos


# ===============================
# BANCO DE DADOS
# ===============================

def salvar_atendimento(
    telefone,
    nome="",
    setor="",
    origem="",
    modelo="",
    revisao="",
    horario="",
    status="",
    atendimento_humano="Não",
    itens=""
):
    db = None
    try:
        db = SessionLocal()

        atendimento = Atendimento(
            telefone=telefone,
            nome=nome,
            setor=setor,
            origem=origem,
            modelo=modelo,
            revisao=revisao,
            horario=horario,
            status=status,
            atendimento_humano=atendimento_humano,
            itens=itens
        )

        db.add(atendimento)
        db.commit()

    except Exception as e:
        print("Erro ao salvar atendimento:", e)
        if db:
            db.rollback()
    finally:
        if db:
            db.close()


# ===============================
# UTILITÁRIOS
# ===============================

def agora_timestamp():
    return datetime.now().timestamp()


def iniciar_cliente(telefone):
    if telefone not in clientes:
        clientes[telefone] = {
            "etapa": "menu",
            "atendimento_humano": False,
            "ultima_interacao": agora_timestamp(),
            "origem": "Menu Normal",
            "itens_adicionais": [],
            "menu_venda_casada": [],
            "horarios_disponiveis": {},
            "mensagem_inatividade_enviada": False
        }
    else:
        clientes[telefone]["ultima_interacao"] = agora_timestamp()
        clientes[telefone]["mensagem_inatividade_enviada"] = False


def atualizar_interacao(telefone):
    if telefone in clientes:
        clientes[telefone]["ultima_interacao"] = agora_timestamp()
        clientes[telefone]["mensagem_inatividade_enviada"] = False


def resetar_estado_cliente(telefone):
    if telefone not in clientes:
        return

    atendimento_humano = clientes[telefone].get("atendimento_humano", False)

    clientes[telefone] = {
        "etapa": "menu",
        "atendimento_humano": atendimento_humano,
        "ultima_interacao": agora_timestamp(),
        "origem": "Menu Normal",
        "itens_adicionais": [],
        "menu_venda_casada": [],
        "horarios_disponiveis": {},
        "mensagem_inatividade_enviada": False
    }


def limpar_fluxo_agendamento(telefone):
    if telefone in clientes:
        clientes[telefone]["itens_adicionais"] = []
        clientes[telefone]["menu_venda_casada"] = []
        clientes[telefone]["horarios_disponiveis"] = {}
        for campo in ["revisao_numero", "dia_semana", "horario_escolhido"]:
            clientes[telefone].pop(campo, None)


def normalizar_texto(texto):
    return str(texto).strip().lower()


def obter_modelo_moto(texto):
    texto = str(texto).strip()
    mapa = {
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
        "12": "TENERE 700",
        "13": "AEROX"
    }
    return mapa.get(texto, texto)


def obter_numero_revisao(texto):
    texto = str(texto).strip()
    mapa = {
        "1": "1ª Revisão",
        "2": "2ª Revisão",
        "3": "3ª Revisão",
        "4": "4ª Revisão",
        "5": "5ª Revisão ou superior"
    }
    return mapa.get(texto, texto)


def revisao_categoria(texto):
    texto = normalizar_texto(texto)

    if texto in ["1", "1ª revisão", "1a revisão", "1 revisao", "1a revisao"]:
        return 1
    if texto in ["2", "2ª revisão", "2a revisão", "2 revisao", "2a revisao"]:
        return 2
    return 3


def revisao_eh_segunda_ou_mais(texto):
    return revisao_categoria(texto) >= 2


def obter_dia_semana(texto):
    texto = normalizar_texto(texto)
    mapa = {
        "1": "Segunda-feira",
        "2": "Terça-feira",
        "3": "Quarta-feira",
        "4": "Quinta-feira",
        "5": "Sexta-feira",
        "6": "Sábado",
        "segunda": "Segunda-feira",
        "segunda-feira": "Segunda-feira",
        "terca": "Terça-feira",
        "terça": "Terça-feira",
        "terca-feira": "Terça-feira",
        "terça-feira": "Terça-feira",
        "quarta": "Quarta-feira",
        "quarta-feira": "Quarta-feira",
        "quinta": "Quinta-feira",
        "quinta-feira": "Quinta-feira",
        "sexta": "Sexta-feira",
        "sexta-feira": "Sexta-feira",
        "sabado": "Sábado",
        "sábado": "Sábado"
    }
    return mapa.get(texto, texto.title())


def gerar_horarios_por_regra(revisao_numero, dia_semana):
    categoria = revisao_categoria(revisao_numero)
    dia = normalizar_texto(dia_semana)

    dias_uteis = [
        "segunda-feira",
        "terça-feira",
        "terca-feira",
        "quarta-feira",
        "quinta-feira",
        "sexta-feira"
    ]

    if dia in dias_uteis:
        if categoria in [1, 2]:
            return ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"]
        return ["08:00"]

    if dia in ["sábado", "sabado"]:
        if categoria in [1, 2]:
            return ["08:00", "09:00", "10:00"]
        return []

    return []


def gerar_menu_horarios(horarios):
    linhas = ["Selecione o horário desejado:"]
    mapa = {}

    for i, horario in enumerate(horarios, start=1):
        linhas.append(f"{i}️⃣ {horario}")
        mapa[str(i)] = horario

    linhas.append("")
    linhas.append("Digite a opção:")
    return "\n".join(linhas), mapa


def gerar_opcoes_venda_casada(revisao_numero):
    opcoes = []

    if revisao_eh_segunda_ou_mais(revisao_numero):
        opcoes.extend([
            "Filtro de ar",
            "Pastilha de freio"
        ])

    opcoes.extend([
        "Protetor de motor",
        "Slider",
        "Suporte para celular",
        "Baú"
    ])

    return opcoes


def gerar_menu_venda_casada(revisao_numero):
    opcoes = gerar_opcoes_venda_casada(revisao_numero)

    linhas = [
        "Selecione os itens que deseja acrescentar 🏍️",
        "",
        "Você pode escolher mais de um item.",
        "Responda com os números separados por vírgula.",
        "Exemplo: 1,3,4",
        ""
    ]

    for i, item in enumerate(opcoes, start=1):
        linhas.append(f"{i}️⃣ {item}")

    linhas.extend([
        "",
        "0️⃣ Nenhum item adicional",
        "",
        "Digite a opção:"
    ])

    return "\n".join(linhas), opcoes


def interpretar_itens_escolhidos(mensagem, opcoes):
    texto = normalizar_texto(mensagem)

    if texto in ["0", "nenhum", "nenhum item", "nao", "não"]:
        return [], None

    partes = [p.strip() for p in texto.replace(";", ",").split(",") if p.strip()]
    itens = []
    invalidos = []

    for parte in partes:
        if not parte.isdigit():
            invalidos.append(parte)
            continue

        indice = int(parte)
        if 1 <= indice <= len(opcoes):
            item = opcoes[indice - 1]
            if item not in itens:
                itens.append(item)
        else:
            invalidos.append(parte)

    if invalidos:
        return None, "Opção inválida"

    return itens, None


def formatar_itens(itens):
    if not itens:
        return "Nenhum item adicional"
    return "\n".join([f"• {item}" for item in itens])


def extrair_mensagem_texto(data):
    if not isinstance(data, dict):
        return None

    candidatos = [
        data.get("message"),
        data.get("body"),
        data.get("text"),
        data.get("caption"),
    ]

    text_obj = data.get("text")
    if isinstance(text_obj, dict):
        candidatos.extend([
            text_obj.get("message"),
            text_obj.get("body"),
            text_obj.get("text")
        ])

    msg_obj = data.get("message")
    if isinstance(msg_obj, dict):
        candidatos.extend([
            msg_obj.get("text"),
            msg_obj.get("body"),
            msg_obj.get("message")
        ])

    for item in candidatos:
        if isinstance(item, str) and item.strip():
            return item.strip()

    return None


def evento_eh_do_proprio_bot(data):
    if not isinstance(data, dict):
        return False

    if data.get("fromMe") is True or data.get("from_me") is True:
        return True

    text_obj = data.get("text")
    if isinstance(text_obj, dict) and text_obj.get("fromMe") is True:
        return True

    msg_obj = data.get("message")
    if isinstance(msg_obj, dict) and msg_obj.get("fromMe") is True:
        return True

    return False


# ===============================
# ENVIO DE MENSAGEM
# ===============================

def enviar_mensagem(telefone, mensagem):
    payload = {
        "phone": telefone,
        "message": mensagem
    }

    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url_envio, json=payload, headers=headers, timeout=15)
        print("Resposta envio mensagem:", response.status_code, response.text)
    except requests.RequestException as e:
        print(f"Erro ao enviar mensagem para {telefone}: {e}")


def enviar_pdf(telefone, nome_arquivo="catalogo-atacado.pdf", legenda="📄 Catálogo Atacado Motoshow Yamaha"):
    link_pdf = f"{BASE_URL}/pdf/{nome_arquivo}"

    payload = {
        "phone": telefone,
        "document": link_pdf,
        "fileName": nome_arquivo,
        "caption": legenda
    }

    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url_documento, json=payload, headers=headers, timeout=20)
        print("Resposta envio PDF:", response.status_code, response.text)
    except requests.RequestException as e:
        print(f"Erro ao enviar PDF para {telefone}: {e}")
        enviar_mensagem(telefone, "Não foi possível enviar o catálogo neste momento.\n\nEquipe Motoshow Yamaha")


# ===============================
# MENUS
# ===============================

def menu_modelos():
    return """Informe o modelo da moto:

1️⃣ Fazer 250
2️⃣ FZ15
3️⃣ Crosser
4️⃣ Lander
5️⃣ MT03
6️⃣ MT07
7️⃣ R15
8️⃣ R3
9️⃣ FLUO
🔟 NEO
11️⃣ NMAX
12️⃣ TENERE 700
13️⃣ AEROX"""


def menu_principal_texto():
    return """Olá 👋

Bem-vindo ao Pós-Vendas Motoshow Yamaha 🏍️
Estamos prontos para ajudar com revisões, peças, garantia e serviços.

1️⃣ Agendar Revisão
2️⃣ Orçamento Peças
3️⃣ Acompanhar Serviço
4️⃣ Agendar Serviço / Avaliação
5️⃣ Garantia
6️⃣ Logista / Atacado
7️⃣ Falar com Atendente

Digite a opção:"""


def menu(telefone):
    enviar_mensagem(telefone, menu_principal_texto())


def menu_pecas(telefone):
    texto = """Orçamento de Peças 🏍️

1️⃣ Peças Originais
2️⃣ Acessórios
3️⃣ Consultar Disponibilidade
4️⃣ Falar com Atendente
5️⃣ Voltar ao Menu Principal

Digite a opção:"""
    enviar_mensagem(telefone, texto)


def menu_logista(telefone):
    texto = """🤝 Atendimento Logista / Atacado - Motoshow Yamaha

Atendimento exclusivo para:
• Lojas
• Oficinas
• Revendedores
• Frotistas

Selecione uma opção:

1️⃣ Solicitar Cotação
2️⃣ Cadastro de Logista
3️⃣ Catálogo de Peças
4️⃣ Falar com Consultor Comercial
5️⃣ Voltar ao Menu Principal

Digite a opção:"""
    enviar_mensagem(telefone, texto)


def menu_catalogo_atacado(telefone):
    texto = """📦 Catálogo Atacado Motoshow Yamaha

Selecione uma opção:

1️⃣ Receber Catálogo em PDF
2️⃣ Falar com Consultor Comercial
3️⃣ Voltar ao Menu Logista / Atacado

Digite a opção:"""
    enviar_mensagem(telefone, texto)


def menu_revisao_numero(telefone):
    texto = """Informe qual revisão deseja agendar:

1️⃣ 1ª Revisão
2️⃣ 2ª Revisão
3️⃣ 3ª Revisão
4️⃣ 4ª Revisão
5️⃣ 5ª Revisão ou superior

Digite a opção:"""
    enviar_mensagem(telefone, texto)


def menu_dias_semana(telefone):
    texto = """Selecione o dia desejado para agendamento:

1️⃣ Segunda-feira
2️⃣ Terça-feira
3️⃣ Quarta-feira
4️⃣ Quinta-feira
5️⃣ Sexta-feira
6️⃣ Sábado

Digite a opção:"""
    enviar_mensagem(telefone, texto)


def menu_confirma_venda_casada(telefone):
    texto = """Deseja acrescentar peça ou acessório ao atendimento?

1️⃣ Sim
2️⃣ Não

Digite a opção:"""
    enviar_mensagem(telefone, texto)


def menu_garantia(telefone):
    enviar_mensagem(
        telefone,
        """Garantia

1️⃣ Nova Solicitação
2️⃣ Acompanhar Garantia
3️⃣ Falar com Atendente
4️⃣ Voltar ao Menu Principal

Digite a opção:"""
    )


# ===============================
# PDF
# ===============================

@app.route("/pdf/<arquivo>")
def servir_pdf(arquivo):
    return send_from_directory("static/pdfs", arquivo)


# ===============================
# INATIVIDADE
# ===============================

def monitorar_inatividade():
    while True:
        try:
            agora = agora_timestamp()
            for telefone, dados in list(clientes.items()):
                ultima = dados.get("ultima_interacao", agora)
                humano = dados.get("atendimento_humano", False)
                enviada = dados.get("mensagem_inatividade_enviada", False)

                if not humano and not enviada and (agora - ultima) > TEMPO_INATIVIDADE:
                    enviar_mensagem(
                        telefone,
                        """Seu atendimento foi encerrado por inatividade.

Quando quiser continuar, envie *menu* para iniciar novamente.

Equipe Motoshow Yamaha"""
                    )
                    dados["mensagem_inatividade_enviada"] = True
                    resetar_estado_cliente(telefone)

        except Exception as e:
            print("Erro no monitor de inatividade:", e)

        time.sleep(30)


# ===============================
# WEBHOOK
# ===============================

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "Webhook online", 200

    data = request.json or {}
    print("Webhook recebido:", data)

    # Ignora mensagens enviadas pelo próprio bot
    if evento_eh_do_proprio_bot(data):
        return jsonify({"status": "ignorado_from_me"})

    telefone = data.get("phone")
    mensagem = extrair_mensagem_texto(data)

    # Ignora eventos sem telefone ou sem mensagem textual do cliente
    if not telefone or not mensagem:
        return jsonify({"status": "ignorado"})

    mensagem = str(mensagem).strip()

    iniciar_cliente(telefone)
    atualizar_interacao(telefone)

    if clientes[telefone].get("atendimento_humano"):
        return jsonify({"status": "atendimento_humano"})

    etapa = clientes[telefone]["etapa"]
    msg = normalizar_texto(mensagem)

    # ===============================
    # COMANDOS GERAIS
    # ===============================
    if msg in ["oi", "ola", "olá", "menu", "inicio", "início"]:
        clientes[telefone]["etapa"] = "menu"
        clientes[telefone]["origem"] = "Menu Normal"
        clientes[telefone]["atendimento_humano"] = False
        limpar_fluxo_agendamento(telefone)
        menu(telefone)
        return jsonify({"status": "ok"})

    if msg in ["encerrar atendimento humano", "finalizar atendimento humano", "voltar bot"]:
        clientes[telefone]["atendimento_humano"] = False
        clientes[telefone]["etapa"] = "menu"
        menu(telefone)
        return jsonify({"status": "ok"})

    # ===============================
    # CAMPANHA - AGENDAMENTO
    # ===============================
    if etapa == "campanha_agendamento_modelo":
        clientes[telefone]["modelo_moto"] = obter_modelo_moto(mensagem)
        clientes[telefone]["etapa"] = "campanha_agendamento_nome"
        enviar_mensagem(telefone, "Informe seu nome completo:")
        return jsonify({"status": "ok"})

    elif etapa == "campanha_agendamento_nome":
        clientes[telefone]["nome_cliente"] = mensagem
        clientes[telefone]["etapa"] = "campanha_agendamento_ano"
        enviar_mensagem(telefone, "Informe o ano da moto:")
        return jsonify({"status": "ok"})

    elif etapa == "campanha_agendamento_ano":
        clientes[telefone]["ano_moto"] = mensagem
        clientes[telefone]["etapa"] = "campanha_agendamento_revisao"
        menu_revisao_numero(telefone)
        return jsonify({"status": "ok"})

    elif etapa == "campanha_agendamento_revisao":
        clientes[telefone]["revisao_numero"] = obter_numero_revisao(mensagem)
        clientes[telefone]["etapa"] = "campanha_agendamento_dia"
        menu_dias_semana(telefone)
        return jsonify({"status": "ok"})

    elif etapa == "campanha_agendamento_dia":
        dia = obter_dia_semana(mensagem)
        horarios = gerar_horarios_por_regra(clientes[telefone].get("revisao_numero", ""), dia)

        if not horarios:
            enviar_mensagem(
                telefone,
                """Para esta revisão não há atendimento disponível no dia selecionado.

Regras de agendamento:
• 1ª e 2ª revisão: segunda a sexta de 08:00 às 15:00, sábado de 08:00 às 10:00
• 3ª revisão em diante: segunda a sexta somente às 08:00

Escolha outro dia:"""
            )
            menu_dias_semana(telefone)
            return jsonify({"status": "ok"})

        clientes[telefone]["dia_semana"] = dia
        texto_menu, mapa_horarios = gerar_menu_horarios(horarios)
        clientes[telefone]["horarios_disponiveis"] = mapa_horarios
        clientes[telefone]["etapa"] = "campanha_agendamento_horario"
        enviar_mensagem(telefone, texto_menu)
        return jsonify({"status": "ok"})

    elif etapa == "campanha_agendamento_horario":
        mapa_horarios = clientes[telefone].get("horarios_disponiveis", {})
        horario = mapa_horarios.get(mensagem)

        if not horario:
            texto_menu, mapa = gerar_menu_horarios(list(mapa_horarios.values()))
            clientes[telefone]["horarios_disponiveis"] = mapa
            enviar_mensagem(telefone, f"Opção inválida.\n\n{texto_menu}")
            return jsonify({"status": "ok"})

        clientes[telefone]["horario_escolhido"] = horario
        clientes[telefone]["etapa"] = "campanha_agendamento_confirma_item"
        menu_confirma_venda_casada(telefone)
        return jsonify({"status": "ok"})

    elif etapa == "campanha_agendamento_confirma_item":
        if msg == "1":
            texto_menu, opcoes = gerar_menu_venda_casada(clientes[telefone].get("revisao_numero", ""))
            clientes[telefone]["menu_venda_casada"] = opcoes
            clientes[telefone]["etapa"] = "campanha_agendamento_venda_casada"
            enviar_mensagem(telefone, texto_menu)
            return jsonify({"status": "ok"})

        elif msg == "2":
            resumo = f"""Agendamento solicitado ✅

Nome: {clientes[telefone].get("nome_cliente", "")}
Modelo: {clientes[telefone].get("modelo_moto", "")}
Ano: {clientes[telefone].get("ano_moto", "")}
Revisão: {clientes[telefone].get("revisao_numero", "")}
Dia: {clientes[telefone].get("dia_semana", "")}
Horário: {clientes[telefone].get("horario_escolhido", "")}

Itens adicionados:
Nenhum item adicional

Nossa equipe irá confirmar seu agendamento.

Equipe Motoshow Yamaha"""

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone].get("nome_cliente", ""),
                setor="Revisão",
                origem="Campanha",
                modelo=clientes[telefone].get("modelo_moto", ""),
                revisao=clientes[telefone].get("revisao_numero", ""),
                horario=clientes[telefone].get("horario_escolhido", ""),
                status="Agendado",
                itens=""
            )

            enviar_mensagem(telefone, resumo)
            resetar_estado_cliente(telefone)
            return jsonify({"status": "ok"})

        else:
            menu_confirma_venda_casada(telefone)
            return jsonify({"status": "ok"})

    elif etapa == "campanha_agendamento_venda_casada":
        opcoes = clientes[telefone].get("menu_venda_casada", [])
        itens, erro = interpretar_itens_escolhidos(mensagem, opcoes)

        if erro:
            texto_menu, opcoes_atualizadas = gerar_menu_venda_casada(clientes[telefone].get("revisao_numero", ""))
            clientes[telefone]["menu_venda_casada"] = opcoes_atualizadas
            enviar_mensagem(telefone, f"Não entendi sua seleção.\n\n{texto_menu}")
            return jsonify({"status": "ok"})

        clientes[telefone]["itens_adicionais"] = itens or []

        resumo = f"""Agendamento solicitado ✅

Nome: {clientes[telefone].get("nome_cliente", "")}
Modelo: {clientes[telefone].get("modelo_moto", "")}
Ano: {clientes[telefone].get("ano_moto", "")}
Revisão: {clientes[telefone].get("revisao_numero", "")}
Dia: {clientes[telefone].get("dia_semana", "")}
Horário: {clientes[telefone].get("horario_escolhido", "")}

Itens adicionados:
{formatar_itens(clientes[telefone].get("itens_adicionais", []))}

Nossa equipe irá confirmar seu agendamento e a disponibilidade dos itens solicitados.

Equipe Motoshow Yamaha"""

        salvar_atendimento(
            telefone=telefone,
            nome=clientes[telefone].get("nome_cliente", ""),
            setor="Revisão",
            origem="Campanha",
            modelo=clientes[telefone].get("modelo_moto", ""),
            revisao=clientes[telefone].get("revisao_numero", ""),
            horario=clientes[telefone].get("horario_escolhido", ""),
            status="Agendado",
            itens=", ".join(clientes[telefone].get("itens_adicionais", []))
        )

        enviar_mensagem(telefone, resumo)
        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    # ===============================
    # CAMPANHA - ORÇAMENTO
    # ===============================
    elif etapa == "campanha_orcamento_modelo":
        clientes[telefone]["modelo_moto"] = obter_modelo_moto(mensagem)
        clientes[telefone]["etapa"] = "campanha_orcamento_nome"
        enviar_mensagem(telefone, "Informe seu nome completo:")
        return jsonify({"status": "ok"})

    elif etapa == "campanha_orcamento_nome":
        clientes[telefone]["nome_cliente"] = mensagem
        clientes[telefone]["etapa"] = "campanha_orcamento_ano"
        enviar_mensagem(telefone, "Informe o ano da moto:")
        return jsonify({"status": "ok"})

    elif etapa == "campanha_orcamento_ano":
        clientes[telefone]["ano_moto"] = mensagem
        clientes[telefone]["etapa"] = "campanha_orcamento_periodo"
        enviar_mensagem(telefone, "Informe qual revisão deseja consultar. Exemplo: 1ª revisão, 2ª revisão, 3ª revisão:")
        return jsonify({"status": "ok"})

    elif etapa == "campanha_orcamento_periodo":
        clientes[telefone]["km_atual"] = mensagem

        resumo = f"""Consulta de valores registrada ✅

Nome: {clientes[telefone].get("nome_cliente", "")}
Modelo: {clientes[telefone].get("modelo_moto", "")}
Ano: {clientes[telefone].get("ano_moto", "")}
Revisão: {clientes[telefone].get("km_atual", "")}

Nossa equipe irá retornar com os valores da revisão.

Equipe Motoshow Yamaha"""

        salvar_atendimento(
            telefone=telefone,
            nome=clientes[telefone].get("nome_cliente", ""),
            setor="Revisão",
            origem="Campanha",
            modelo=clientes[telefone].get("modelo_moto", ""),
            revisao=clientes[telefone].get("km_atual", ""),
            horario="",
            status="Consulta de Valores",
            itens=""
        )

        enviar_mensagem(telefone, resumo)
        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    # ===============================
    # MENU PRINCIPAL
    # ===============================
    if etapa == "menu":
        if msg == "1":
            clientes[telefone]["etapa"] = "modelo"
            clientes[telefone]["origem"] = "Menu Normal"
            limpar_fluxo_agendamento(telefone)
            enviar_mensagem(telefone, menu_modelos())
            return jsonify({"status": "ok"})

        elif msg == "2":
            clientes[telefone]["etapa"] = "pecas_menu"
            clientes[telefone]["origem"] = "Menu Normal"
            menu_pecas(telefone)
            return jsonify({"status": "ok"})

        elif msg == "3":
            clientes[telefone]["etapa"] = "acompanhar_nome"
            clientes[telefone]["origem"] = "Menu Normal"
            enviar_mensagem(telefone, "Informe seu nome completo:")
            return jsonify({"status": "ok"})

        elif msg == "4":
            clientes[telefone]["etapa"] = "servico_nome"
            clientes[telefone]["origem"] = "Menu Normal"
            enviar_mensagem(telefone, "Informe seu nome completo:")
            return jsonify({"status": "ok"})

        elif msg == "5":
            clientes[telefone]["etapa"] = "garantia_menu"
            clientes[telefone]["origem"] = "Menu Normal"
            menu_garantia(telefone)
            return jsonify({"status": "ok"})

        elif msg == "6":
            clientes[telefone]["etapa"] = "logista_menu"
            clientes[telefone]["origem"] = "Menu Normal"
            menu_logista(telefone)
            return jsonify({"status": "ok"})

        elif msg == "7":
            clientes[telefone]["atendimento_humano"] = True

            salvar_atendimento(
                telefone=telefone,
                setor="Atendimento Humano",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                atendimento_humano="Sim",
                status="Transferido"
            )

            enviar_mensagem(
                telefone,
                """Seu atendimento foi encaminhado para um consultor.

Em instantes nossa equipe continuará seu atendimento.

Equipe Motoshow Yamaha"""
            )
            return jsonify({"status": "ok"})

        else:
            menu(telefone)
            return jsonify({"status": "ok"})

    # ===============================
    # SUBMENU PEÇAS
    # ===============================
    elif etapa == "pecas_menu":
        if msg == "1":
            clientes[telefone]["etapa"] = "peca_nome"
            enviar_mensagem(telefone, "Informe o nome da peça:")
            return jsonify({"status": "ok"})

        elif msg == "2":
            clientes[telefone]["etapa"] = "acessorio_nome"
            enviar_mensagem(telefone, "Informe o nome do acessório:")
            return jsonify({"status": "ok"})

        elif msg == "3":
            clientes[telefone]["etapa"] = "consulta_nome"
            enviar_mensagem(telefone, "Informe o nome da peça ou acessório:")
            return jsonify({"status": "ok"})

        elif msg == "4":
            clientes[telefone]["atendimento_humano"] = True

            salvar_atendimento(
                telefone=telefone,
                setor="Peças",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                atendimento_humano="Sim",
                status="Transferido"
            )

            enviar_mensagem(
                telefone,
                "Seu atendimento foi direcionado para o setor de peças.\n\nEquipe Motoshow Yamaha"
            )
            return jsonify({"status": "ok"})

        elif msg == "5":
            clientes[telefone]["etapa"] = "menu"
            menu(telefone)
            return jsonify({"status": "ok"})

        else:
            menu_pecas(telefone)
            return jsonify({"status": "ok"})

    # ===============================
    # PEÇAS
    # ===============================
    elif etapa == "peca_nome":
        clientes[telefone]["peca"] = mensagem
        clientes[telefone]["etapa"] = "peca_modelo"
        enviar_mensagem(telefone, "Informe o modelo da moto:")
        return jsonify({"status": "ok"})

    elif etapa == "peca_modelo":
        clientes[telefone]["modelo"] = mensagem
        clientes[telefone]["etapa"] = "peca_ano"
        enviar_mensagem(telefone, "Informe o ano da moto:")
        return jsonify({"status": "ok"})

    elif etapa == "peca_ano":
        clientes[telefone]["ano"] = mensagem
        clientes[telefone]["etapa"] = "peca_cor"
        enviar_mensagem(telefone, "Informe a cor da moto:")
        return jsonify({"status": "ok"})

    elif etapa == "peca_cor":
        clientes[telefone]["cor"] = mensagem

        resumo = f"""Resumo do atendimento ✅

Peça: {clientes[telefone]["peca"]}
Modelo: {clientes[telefone]["modelo"]}
Ano: {clientes[telefone]["ano"]}
Cor: {clientes[telefone]["cor"]}

Encaminhado para Balcão de Peças

Equipe Motoshow Yamaha"""

        salvar_atendimento(
            telefone=telefone,
            setor="Peças",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            modelo=clientes[telefone].get("modelo", ""),
            status="Orçamento",
            itens=clientes[telefone].get("peca", "")
        )

        enviar_mensagem(telefone, resumo)
        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    # ===============================
    # ACESSÓRIOS
    # ===============================
    elif etapa == "acessorio_nome":
        clientes[telefone]["acessorio"] = mensagem
        clientes[telefone]["etapa"] = "acessorio_modelo"
        enviar_mensagem(telefone, "Informe o modelo da moto:")
        return jsonify({"status": "ok"})

    elif etapa == "acessorio_modelo":
        clientes[telefone]["modelo"] = mensagem

        resumo = f"""Resumo do atendimento ✅

Acessório: {clientes[telefone]["acessorio"]}
Modelo: {clientes[telefone]["modelo"]}

Encaminhado para setor de acessórios

Equipe Motoshow Yamaha"""

        salvar_atendimento(
            telefone=telefone,
            setor="Acessórios",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            modelo=clientes[telefone].get("modelo", ""),
            status="Orçamento",
            itens=clientes[telefone].get("acessorio", "")
        )

        enviar_mensagem(telefone, resumo)
        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    # ===============================
    # CONSULTA
    # ===============================
    elif etapa == "consulta_nome":
        clientes[telefone]["consulta"] = mensagem

        resumo = f"""Consulta registrada ✅

Item: {clientes[telefone]["consulta"]}

Encaminhado para consulta de estoque

Equipe Motoshow Yamaha"""

        salvar_atendimento(
            telefone=telefone,
            setor="Peças",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            status="Consulta Estoque",
            itens=clientes[telefone].get("consulta", "")
        )

        enviar_mensagem(telefone, resumo)
        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    # ===============================
    # LOGISTA / ATACADO
    # ===============================
    elif etapa == "logista_menu":
        if msg == "1":
            clientes[telefone]["etapa"] = "logista_cotacao_empresa"
            enviar_mensagem(telefone, "Perfeito! Vamos preparar sua cotação.\n\nInforme o nome da empresa:")
            return jsonify({"status": "ok"})

        elif msg == "2":
            clientes[telefone]["etapa"] = "logista_cadastro_empresa"
            enviar_mensagem(telefone, "Vamos realizar seu cadastro de logista.\n\nInforme o nome da empresa:")
            return jsonify({"status": "ok"})

        elif msg == "3":
            clientes[telefone]["etapa"] = "logista_catalogo_menu"
            menu_catalogo_atacado(telefone)
            return jsonify({"status": "ok"})

        elif msg == "4":
            clientes[telefone]["atendimento_humano"] = True

            salvar_atendimento(
                telefone=telefone,
                setor="Logista",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                atendimento_humano="Sim",
                status="Transferido"
            )

            enviar_mensagem(
                telefone,
                """Perfeito, vou transferir você para um consultor comercial 🤝

Um de nossos especialistas irá continuar seu atendimento.

Equipe Motoshow Yamaha"""
            )
            return jsonify({"status": "ok"})

        elif msg == "5":
            clientes[telefone]["etapa"] = "menu"
            menu(telefone)
            return jsonify({"status": "ok"})

        else:
            menu_logista(telefone)
            return jsonify({"status": "ok"})

    elif etapa == "logista_cotacao_empresa":
        clientes[telefone]["logista_empresa"] = mensagem
        clientes[telefone]["etapa"] = "logista_cotacao_cnpj"
        enviar_mensagem(telefone, "Informe o CNPJ:")
        return jsonify({"status": "ok"})

    elif etapa == "logista_cotacao_cnpj":
        clientes[telefone]["logista_cnpj"] = mensagem
        clientes[telefone]["etapa"] = "logista_cotacao_cidade"
        enviar_mensagem(telefone, "Informe a cidade:")
        return jsonify({"status": "ok"})

    elif etapa == "logista_cotacao_cidade":
        clientes[telefone]["logista_cidade"] = mensagem
        clientes[telefone]["etapa"] = "logista_cotacao_pecas"
        enviar_mensagem(telefone, "Informe as peças desejadas (código ou modelo da moto):")
        return jsonify({"status": "ok"})

    elif etapa == "logista_cotacao_pecas":
        clientes[telefone]["logista_pecas"] = mensagem

        resumo = f"""✅ Solicitação de cotação recebida

Empresa: {clientes[telefone]["logista_empresa"]}
CNPJ: {clientes[telefone]["logista_cnpj"]}
Cidade: {clientes[telefone]["logista_cidade"]}
Peças de interesse: {clientes[telefone]["logista_pecas"]}

Nossa equipe comercial irá analisar e retornar com:
• Preços especiais
• Condição atacado
• Prazo de envio

Equipe Motoshow Yamaha"""

        salvar_atendimento(
            telefone=telefone,
            setor="Logista",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            status="Cotação",
            itens=clientes[telefone].get("logista_pecas", "")
        )

        enviar_mensagem(telefone, resumo)
        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    elif etapa == "logista_cadastro_empresa":
        clientes[telefone]["cadastro_empresa"] = mensagem
        clientes[telefone]["etapa"] = "logista_cadastro_cnpj"
        enviar_mensagem(telefone, "Informe o CNPJ:")
        return jsonify({"status": "ok"})

    elif etapa == "logista_cadastro_cnpj":
        clientes[telefone]["cadastro_cnpj"] = mensagem
        clientes[telefone]["etapa"] = "logista_cadastro_responsavel"
        enviar_mensagem(telefone, "Informe o nome do responsável:")
        return jsonify({"status": "ok"})

    elif etapa == "logista_cadastro_responsavel":
        clientes[telefone]["cadastro_responsavel"] = mensagem
        clientes[telefone]["etapa"] = "logista_cadastro_cidade"
        enviar_mensagem(telefone, "Informe a cidade:")
        return jsonify({"status": "ok"})

    elif etapa == "logista_cadastro_cidade":
        clientes[telefone]["cadastro_cidade"] = mensagem
        clientes[telefone]["etapa"] = "logista_cadastro_telefone"
        enviar_mensagem(telefone, "Informe o telefone para contato:")
        return jsonify({"status": "ok"})

    elif etapa == "logista_cadastro_telefone":
        clientes[telefone]["cadastro_telefone"] = mensagem

        resumo = f"""Cadastro recebido com sucesso 🤝

Empresa: {clientes[telefone]["cadastro_empresa"]}
CNPJ: {clientes[telefone]["cadastro_cnpj"]}
Responsável: {clientes[telefone]["cadastro_responsavel"]}
Cidade: {clientes[telefone]["cadastro_cidade"]}
Telefone: {clientes[telefone]["cadastro_telefone"]}

Nossa equipe comercial irá validar e liberar seu cadastro.

Benefícios do cadastro:
✔ Preços diferenciados
✔ Promoções exclusivas
✔ Prioridade no atendimento

Equipe Motoshow Yamaha"""

        salvar_atendimento(
            telefone=telefone,
            setor="Logista",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            status="Cadastro"
        )

        enviar_mensagem(telefone, resumo)
        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    elif etapa == "logista_catalogo_menu":
        if msg == "1":
            enviar_mensagem(telefone, "Perfeito! Segue nosso catálogo atacado em PDF 📄")
            enviar_pdf(telefone, nome_arquivo="catalogo-atacado.pdf", legenda="📄 Catálogo Atacado Motoshow Yamaha")
            clientes[telefone]["etapa"] = "logista_menu"
            return jsonify({"status": "ok"})

        elif msg == "2":
            clientes[telefone]["atendimento_humano"] = True

            salvar_atendimento(
                telefone=telefone,
                setor="Logista",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                atendimento_humano="Sim",
                status="Transferido"
            )

            enviar_mensagem(
                telefone,
                """Perfeito, vou transferir você para um consultor comercial 🤝

Um de nossos especialistas irá continuar seu atendimento.

Equipe Motoshow Yamaha"""
            )
            return jsonify({"status": "ok"})

        elif msg == "3":
            clientes[telefone]["etapa"] = "logista_menu"
            menu_logista(telefone)
            return jsonify({"status": "ok"})

        else:
            menu_catalogo_atacado(telefone)
            return jsonify({"status": "ok"})

    # ===============================
    # ACOMPANHAR SERVIÇO
    # ===============================
    elif etapa == "acompanhar_nome":
        clientes[telefone]["acompanhar_nome"] = mensagem
        enviar_mensagem(
            telefone,
            f"""Solicitação registrada ✅

Nome: {clientes[telefone]["acompanhar_nome"]}

Nossa equipe irá verificar o andamento do serviço e retornará em seguida.

Equipe Motoshow Yamaha"""
        )

        salvar_atendimento(
            telefone=telefone,
            nome=clientes[telefone].get("acompanhar_nome", ""),
            setor="Serviço",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            status="Acompanhamento"
        )

        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    # ===============================
    # AGENDAR SERVIÇO / AVALIAÇÃO
    # ===============================
    elif etapa == "servico_nome":
        clientes[telefone]["servico_nome"] = mensagem
        enviar_mensagem(
            telefone,
            f"""Solicitação registrada ✅

Nome: {clientes[telefone]["servico_nome"]}

Nossa equipe entrará em contato para agendar o serviço / avaliação.

Equipe Motoshow Yamaha"""
        )

        salvar_atendimento(
            telefone=telefone,
            nome=clientes[telefone].get("servico_nome", ""),
            setor="Serviço",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            status="Solicitação Serviço"
        )

        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    # ===============================
    # GARANTIA
    # ===============================
    elif etapa == "garantia_menu":
        if msg == "1":
            salvar_atendimento(
                telefone=telefone,
                setor="Garantia",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                status="Solicitação"
            )

            enviar_mensagem(
                telefone,
                """Nova Solicitação de Garantia ✅

Por favor, envie:
• Nome completo
• Modelo da moto
• Ano
• Descrição do problema

Equipe Motoshow Yamaha"""
            )
            resetar_estado_cliente(telefone)
            return jsonify({"status": "ok"})

        elif msg == "2":
            salvar_atendimento(
                telefone=telefone,
                setor="Garantia",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                status="Acompanhamento"
            )

            enviar_mensagem(
                telefone,
                """Acompanhar Garantia ✅

Por favor, informe seu nome completo para consulta.

Equipe Motoshow Yamaha"""
            )
            resetar_estado_cliente(telefone)
            return jsonify({"status": "ok"})

        elif msg == "3":
            clientes[telefone]["atendimento_humano"] = True

            salvar_atendimento(
                telefone=telefone,
                setor="Garantia",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                atendimento_humano="Sim",
                status="Transferido"
            )

            enviar_mensagem(
                telefone,
                "Seu atendimento foi encaminhado para o setor de garantia.\n\nEquipe Motoshow Yamaha"
            )
            return jsonify({"status": "ok"})

        elif msg == "4":
            clientes[telefone]["etapa"] = "menu"
            menu(telefone)
            return jsonify({"status": "ok"})

        else:
            menu_garantia(telefone)
            return jsonify({"status": "ok"})

    # ===============================
    # AGENDAMENTO NORMAL
    # ===============================
    elif etapa == "modelo":
        clientes[telefone]["modelo_moto"] = obter_modelo_moto(mensagem)
        clientes[telefone]["etapa"] = "agendamento_nome"
        enviar_mensagem(telefone, "Informe seu nome completo:")
        return jsonify({"status": "ok"})

    elif etapa == "agendamento_nome":
        clientes[telefone]["nome_cliente"] = mensagem
        clientes[telefone]["etapa"] = "agendamento_ano"
        enviar_mensagem(telefone, "Informe o ano da moto:")
        return jsonify({"status": "ok"})

    elif etapa == "agendamento_ano":
        clientes[telefone]["ano_moto"] = mensagem
        clientes[telefone]["etapa"] = "agendamento_revisao"
        menu_revisao_numero(telefone)
        return jsonify({"status": "ok"})

    elif etapa == "agendamento_revisao":
        clientes[telefone]["revisao_numero"] = obter_numero_revisao(mensagem)
        clientes[telefone]["etapa"] = "agendamento_dia"
        menu_dias_semana(telefone)
        return jsonify({"status": "ok"})

    elif etapa == "agendamento_dia":
        dia = obter_dia_semana(mensagem)
        horarios = gerar_horarios_por_regra(clientes[telefone].get("revisao_numero", ""), dia)

        if not horarios:
            enviar_mensagem(
                telefone,
                """Para esta revisão não há atendimento disponível no dia selecionado.

Regras de agendamento:
• 1ª e 2ª revisão: segunda a sexta de 08:00 às 15:00, sábado de 08:00 às 10:00
• 3ª revisão em diante: segunda a sexta somente às 08:00

Escolha outro dia:"""
            )
            menu_dias_semana(telefone)
            return jsonify({"status": "ok"})

        clientes[telefone]["dia_semana"] = dia
        texto_menu, mapa_horarios = gerar_menu_horarios(horarios)
        clientes[telefone]["horarios_disponiveis"] = mapa_horarios
        clientes[telefone]["etapa"] = "agendamento_horario"
        enviar_mensagem(telefone, texto_menu)
        return jsonify({"status": "ok"})

    elif etapa == "agendamento_horario":
        mapa_horarios = clientes[telefone].get("horarios_disponiveis", {})
        horario = mapa_horarios.get(mensagem)

        if not horario:
            texto_menu, mapa = gerar_menu_horarios(list(mapa_horarios.values()))
            clientes[telefone]["horarios_disponiveis"] = mapa
            enviar_mensagem(telefone, f"Opção inválida.\n\n{texto_menu}")
            return jsonify({"status": "ok"})

        clientes[telefone]["horario_escolhido"] = horario
        clientes[telefone]["etapa"] = "agendamento_confirma_item"
        menu_confirma_venda_casada(telefone)
        return jsonify({"status": "ok"})

    elif etapa == "agendamento_confirma_item":
        if msg == "1":
            texto_menu, opcoes = gerar_menu_venda_casada(clientes[telefone].get("revisao_numero", ""))
            clientes[telefone]["menu_venda_casada"] = opcoes
            clientes[telefone]["etapa"] = "agendamento_venda_casada"
            enviar_mensagem(telefone, texto_menu)
            return jsonify({"status": "ok"})

        elif msg == "2":
            resumo = f"""Agendamento solicitado ✅

Nome: {clientes[telefone].get("nome_cliente", "")}
Modelo: {clientes[telefone].get("modelo_moto", "")}
Ano: {clientes[telefone].get("ano_moto", "")}
Revisão: {clientes[telefone].get("revisao_numero", "")}
Dia: {clientes[telefone].get("dia_semana", "")}
Horário: {clientes[telefone].get("horario_escolhido", "")}

Itens adicionados:
Nenhum item adicional

Nossa equipe seguirá com a confirmação do agendamento.

Equipe Motoshow Yamaha"""

            salvar_atendimento(
                telefone=telefone,
                nome=clientes[telefone].get("nome_cliente", ""),
                setor="Revisão",
                origem=clientes[telefone].get("origem", "Menu Normal"),
                modelo=clientes[telefone].get("modelo_moto", ""),
                revisao=clientes[telefone].get("revisao_numero", ""),
                horario=clientes[telefone].get("horario_escolhido", ""),
                status="Agendado",
                itens=""
            )

            enviar_mensagem(telefone, resumo)
            resetar_estado_cliente(telefone)
            return jsonify({"status": "ok"})

        else:
            menu_confirma_venda_casada(telefone)
            return jsonify({"status": "ok"})

    elif etapa == "agendamento_venda_casada":
        opcoes = clientes[telefone].get("menu_venda_casada", [])
        itens, erro = interpretar_itens_escolhidos(mensagem, opcoes)

        if erro:
            texto_menu, opcoes_atualizadas = gerar_menu_venda_casada(clientes[telefone].get("revisao_numero", ""))
            clientes[telefone]["menu_venda_casada"] = opcoes_atualizadas
            enviar_mensagem(telefone, f"Não entendi sua seleção.\n\n{texto_menu}")
            return jsonify({"status": "ok"})

        clientes[telefone]["itens_adicionais"] = itens or []

        resumo = f"""Agendamento solicitado ✅

Nome: {clientes[telefone].get("nome_cliente", "")}
Modelo: {clientes[telefone].get("modelo_moto", "")}
Ano: {clientes[telefone].get("ano_moto", "")}
Revisão: {clientes[telefone].get("revisao_numero", "")}
Dia: {clientes[telefone].get("dia_semana", "")}
Horário: {clientes[telefone].get("horario_escolhido", "")}

Itens adicionados:
{formatar_itens(clientes[telefone].get("itens_adicionais", []))}

Nossa equipe seguirá com a confirmação do agendamento e da disponibilidade dos itens selecionados.

Equipe Motoshow Yamaha"""

        salvar_atendimento(
            telefone=telefone,
            nome=clientes[telefone].get("nome_cliente", ""),
            setor="Revisão",
            origem=clientes[telefone].get("origem", "Menu Normal"),
            modelo=clientes[telefone].get("modelo_moto", ""),
            revisao=clientes[telefone].get("revisao_numero", ""),
            horario=clientes[telefone].get("horario_escolhido", ""),
            status="Agendado",
            itens=", ".join(clientes[telefone].get("itens_adicionais", []))
        )

        enviar_mensagem(telefone, resumo)
        resetar_estado_cliente(telefone)
        return jsonify({"status": "ok"})

    else:
        clientes[telefone]["etapa"] = "menu"
        menu(telefone)
        return jsonify({"status": "ok"})


@app.route("/")
def home():
    return "BOT YAMAHA ONLINE"


@app.route("/dashboard")
def dashboard():
    db = SessionLocal()

    try:
        periodo = request.args.get("periodo", "hoje")
        hoje = datetime.now().date()

        if periodo == "7dias":
            data_inicio = hoje - timedelta(days=6)
            periodo_label = "Últimos 7 dias"
        elif periodo == "30dias":
            data_inicio = hoje - timedelta(days=29)
            periodo_label = "Últimos 30 dias"
        elif periodo == "mes":
            data_inicio = hoje.replace(day=1)
            periodo_label = "Mês atual"
        else:
            periodo = "hoje"
            data_inicio = hoje
            periodo_label = "Hoje"

        base_query = db.query(Atendimento).filter(func.date(Atendimento.data) >= data_inicio)

        total_atendimentos = base_query.count()

        total_agendamentos = base_query.filter(Atendimento.status == "Agendado").count()

        total_pecas_acessorios = base_query.filter(
            Atendimento.setor.in_(["Peças", "Acessórios"])
        ).count()

        atendimento_humano = base_query.filter(
            Atendimento.atendimento_humano == "Sim"
        ).count()

        setores = base_query.with_entities(
            Atendimento.setor,
            func.count(Atendimento.id)
        ).group_by(Atendimento.setor).all()

        setores_labels = [s[0] if s[0] else "Não informado" for s in setores]
        setores_valores = [s[1] for s in setores]

        origem = base_query.with_entities(
            Atendimento.origem,
            func.count(Atendimento.id)
        ).group_by(Atendimento.origem).all()

        origem_labels = [o[0] if o[0] else "Não informado" for o in origem]
        origem_valores = [o[1] for o in origem]

        ultimos = base_query.filter(
            Atendimento.status == "Agendado"
        ).order_by(Atendimento.id.desc()).limit(10).all()

        evolucao_query = base_query.with_entities(
            func.date(Atendimento.data),
            func.count(Atendimento.id)
        ).group_by(func.date(Atendimento.data)).all()

        dias = [str(item[0]) for item in evolucao_query]
        evolucao = [item[1] for item in evolucao_query]

        revisoes_query = base_query.with_entities(
            Atendimento.revisao,
            func.count(Atendimento.id)
        ).filter(
            Atendimento.revisao.isnot(None),
            Atendimento.revisao != ""
        ).group_by(Atendimento.revisao).order_by(func.count(Atendimento.id).desc()).limit(10).all()

        revisoes = [{"nome": r[0], "total": r[1]} for r in revisoes_query]

        itens_contagem = {}
        itens_query = base_query.with_entities(Atendimento.itens).all()

        for registro in itens_query:
            texto = registro[0]
            if not texto:
                continue

            partes = [p.strip() for p in texto.split(",") if p.strip()]
            for item in partes:
                itens_contagem[item] = itens_contagem.get(item, 0) + 1

        itens_top = sorted(
            [{"nome": nome, "total": total} for nome, total in itens_contagem.items()],
            key=lambda x: x["total"],
            reverse=True
        )[:10]

        return render_template(
            "dashboard.html",
            periodo=periodo,
            periodo_label=periodo_label,
            total_atendimentos=total_atendimentos,
            total_agendamentos=total_agendamentos,
            total_pecas_acessorios=total_pecas_acessorios,
            atendimento_humano=atendimento_humano,
            setores_labels=setores_labels,
            setores_valores=setores_valores,
            origem_labels=origem_labels,
            origem_valores=origem_valores,
            ultimos=ultimos,
            dias=dias,
            evolucao=evolucao,
            revisoes=revisoes,
            itens_top=itens_top
        )
    finally:
        db.close()


thread_inatividade = threading.Thread(
    target=monitorar_inatividade,
    daemon=True
)
thread_inatividade.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)