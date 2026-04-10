import os
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path

# Carregar .env corretamente
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
IA_MODEL = os.getenv("IA_MODEL", "gpt-4o-mini")

print("OPENAI_API_KEY carregada:", "OK" if OPENAI_API_KEY else "NÃO ENCONTRADA")

client = OpenAI(api_key=OPENAI_API_KEY)


def classificar_intencao(texto):

    try:

        prompt = f"""
Você é um classificador de intenção para um bot de concessionária Yamaha.

Classifique a intenção do cliente:

Possíveis intenções:
- agendar_revisao
- pecas
- acessorios
- garantia
- atacado
- humano
- menu
- outro

Mensagem do cliente:
{texto}

Retorne apenas JSON:
{{"intent":"nome_da_intencao"}}
"""

        response = client.chat.completions.create(
            model=IA_MODEL,
            messages=[
                {"role": "system", "content": "Você classifica intenção."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )

        resposta = response.choices[0].message.content

        import json
        return json.loads(resposta)

    except Exception as e:
        print("Erro IA:", e)
        return None