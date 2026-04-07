import os
import time
import requests
import pandas as pd

from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def enviar_mensagem(numero, mensagem):

    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "phone": numero,
        "message": mensagem
    }

    try:
        response = requests.post(
            URL_ENVIO,
            json=payload,
            headers=headers,
            timeout=30
        )

        print("Status Code:", response.status_code)
        print("Resposta:", response.text)

        if response.status_code in [200, 201]:
            return True

        return False

    except Exception as e:
        print("Erro envio:", e)
        return False


def disparar():

    print("===================================")
    print("🚀 Iniciando disparo...")
    print("===================================")

    df = pd.read_excel(ARQUIVO_PLANILHA, dtype=str).fillna("")

    if "STATUS DE ENVIO" not in df.columns:
        df["STATUS DE ENVIO"] = ""

    if "DATA_ENVIO" not in df.columns:
        df["DATA_ENVIO"] = ""

    for index, row in df.iterrows():

        status = str(row.get("STATUS DE ENVIO", "")).strip().upper()

        if status == "ENVIADO":
            print("⏭ Pulando já enviado:", row.get("NOME"))
            continue

        nome = str(row.get("NOME", "")).strip()
        numero = str(row.get("TELEFONE", "")).strip()
        modelo = str(row.get("MODELO", "")).strip()
        periodo = str(row.get("periodo", "")).strip()

        if not nome or not numero:
            print("⚠ Linha ignorada - falta nome ou telefone")
            continue

        mensagem = criar_mensagem(nome, modelo, periodo)

        print("📤 Enviando para:", nome, numero)

        enviado = enviar_mensagem(numero, mensagem)

        if enviado:

            df.at[index, "STATUS DE ENVIO"] = "ENVIADO"
            df.at[index, "DATA_ENVIO"] = datetime.now().strftime("%d/%m/%Y %H:%M")

            df.to_excel(ARQUIVO_PLANILHA, index=False)

            print("✅ Enviado com sucesso:", nome)

        else:
            print("❌ Falha no envio:", nome)

        time.sleep(INTERVALO_ENTRE_ENVIOS)

    print("===================================")
    print("✅ Disparo finalizado")
    print("===================================")


if __name__ == "__main__":
    disparar()