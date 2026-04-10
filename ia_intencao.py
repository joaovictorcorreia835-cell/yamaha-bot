import os

from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()


def log_info(*args):
    print("[IA][INFO]", *args, flush=True)


def log_erro(*args):
    print("[IA][ERRO]", *args, flush=True)


def obter_cliente():
    if not OPENAI_API_KEY:
        log_erro("OPENAI_API_KEY não configurada.")
        return None

    if OpenAI is None:
        log_erro("Biblioteca OpenAI não disponível.")
        return None

    try:
        cliente = OpenAI(api_key=OPENAI_API_KEY)
        return cliente
    except Exception as e:
        log_erro("Erro ao criar cliente OpenAI:", e)
        return None


def classificar_intencao(texto):
    texto = str(texto or "").strip()

    if not texto:
        return "menu"

    texto_normalizado = texto.lower()

    # ==========================================
    # REGRAS RÁPIDAS SEM IA
    # ==========================================
    if any(p in texto_normalizado for p in ["menu", "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]):
        return "menu"

    if any(p in texto_normalizado for p in [
        "agendar revisão", "agendar revisao", "revisão", "revisao",
        "marcar revisão", "marcar revisao", "quero revisar", "agendamento"
    ]):
        return "revisao"

    if any(p in texto_normalizado for p in [
        "peça", "peca", "peças", "pecas", "orçamento de peça", "orcamento de peca"
    ]):
        return "pecas"

    if any(p in texto_normalizado for p in [
        "acessório", "acessorio", "acessórios", "acessorios"
    ]):
        return "acessorios"

    if any(p in texto_normalizado for p in [
        "garantia", "defeito", "problema em garantia"
    ]):
        return "garantia"

    if any(p in texto_normalizado for p in [
        "atacado", "logista", "cotação", "cotacao", "catálogo", "catalogo"
    ]):
        return "atacado"

    if any(p in texto_normalizado for p in [
        "atendente", "humano", "consultor", "falar com alguém", "falar com alguem"
    ]):
        return "humano"

    # ==========================================
    # IA
    # ==========================================
    cliente = obter_cliente()
    if cliente is None:
        return "menu"

    try:
        resposta = cliente.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um classificador de intenção para um bot de pós-vendas Yamaha. "
                        "Responda com apenas uma única palavra, sem explicação, escolhendo uma destas opções exatas: "
                        "revisao, pecas, acessorios, garantia, atacado, humano, menu. "
                        "Nunca responda fora dessa lista."
                    )
                },
                {
                    "role": "user",
                    "content": texto
                }
            ]
        )

        conteudo = resposta.choices[0].message.content.strip().lower()
        log_info("Resposta bruta IA:", conteudo)

        permitidas = {
            "revisao",
            "pecas",
            "acessorios",
            "garantia",
            "atacado",
            "humano",
            "menu"
        }

        if conteudo in permitidas:
            return conteudo

        return "menu"

    except Exception as e:
        log_erro("Erro ao classificar intenção:", e)
        return "menu"