import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ==========================================
# CONFIG
# ==========================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
IA_HABILITADA = os.getenv("IA_HABILITADA", "false").lower() == "true"
IA_CONFIANCA_MINIMA = float(os.getenv("IA_CONFIANCA_MINIMA", "0.75"))
IA_MODELO = os.getenv("IA_MODELO", "gpt-4o-mini")

client = OpenAI(api_key=OPENAI_API_KEY)


# ==========================================
# CLASSIFICAR INTENÇÃO
# ==========================================

def classificar_intencao(texto):

    if not IA_HABILITADA:
        return None

    if not texto or len(texto.strip()) < 2:
        return None

    try:

        prompt = f"""
Você é um classificador de intenção para atendimento de pós-vendas Yamaha.

Classifique a mensagem do cliente em apenas uma das intenções abaixo:

- agendar_revisao
- pecas
- acessorios
- garantia
- logista_atacado
- atendimento_humano
- acompanhar_servico
- orcamento
- duvida_geral
- nao_interessado
- menu

Responda apenas em JSON no formato:

{{
 "intent": "nome_da_intencao",
 "confidence": 0.00
}}

Mensagem do cliente:
"{texto}"
"""

        response = client.chat.completions.create(
            model=IA_MODELO,
            messages=[
                {"role": "system", "content": "Você classifica intenção de mensagens de clientes."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )

        resposta = response.choices[0].message.content.strip()

        resultado = json.loads(resposta)

        intent = resultado.get("intent")
        confidence = float(resultado.get("confidence", 0))

        if confidence >= IA_CONFIANCA_MINIMA:

            return {
                "intent": intent,
                "confidence": confidence
            }

        return None

    except Exception as e:
        print("Erro IA:", str(e))
        return None