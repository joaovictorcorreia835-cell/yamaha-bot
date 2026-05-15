# ==========================================
# POPULAR BASE DE CONHECIMENTO - YAMAHA BOT
# ==========================================

from database import SessionLocal, criar_banco, FaqRevisao


FAQS = [
    {
        "categoria": "valor_revisao",
        "pergunta_chave": "quanto custa a revisao da minha fz15",
        "resposta_base": (
            "O valor depende do modelo, tipo de revisão e pacote aplicado. "
            "Se a moto estiver na garantia, podemos consultar a tabela de revisão "
            "ou direcionar para o agendamento com o pós-venda."
        )
    },
    {
        "categoria": "revisao_km",
        "pergunta_chave": "minha moto chegou nos 5 mil km ja preciso revisar",
        "resposta_base": (
            "Sim. As revisões devem seguir o manual do proprietário, considerando "
            "quilometragem ou prazo, o que ocorrer primeiro."
        )
    },
    {
        "categoria": "agendamento",
        "pergunta_chave": "posso fazer revisao sem agendar",
        "resposta_base": (
            "O ideal é agendar com antecedência para garantir melhor atendimento, "
            "horário disponível e organização da oficina."
        )
    },
    {
        "categoria": "tempo_revisao",
        "pergunta_chave": "quanto tempo demora a revisao",
        "resposta_base": (
            "O tempo depende do tipo de revisão e dos serviços adicionais. "
            "A primeira e segunda revisão costumam ser mais rápidas, com média aproximada de 1h30 a 2h."
        )
    },
    {
        "categoria": "troca_oleo",
        "pergunta_chave": "voces trocam oleo na revisao",
        "resposta_base": "Sim. Na revisão é feita a substituição do óleo conforme o plano de manutenção Yamaha."
    },
    {
        "categoria": "oleo_crosser",
        "pergunta_chave": "qual oleo voces usam na crosser",
        "resposta_base": "Para a Crosser, utilizamos óleo recomendado pela Yamaha. Confirme com o pós-venda a especificação atual antes da troca."
    },
    {
        "categoria": "oleo_cliente",
        "pergunta_chave": "posso levar meu proprio oleo",
        "resposta_base": "Pode sim, desde que seja um óleo compatível e recomendado pela Yamaha. Nossa equipe pode validar antes do serviço."
    },
    {
        "categoria": "garantia_revisao_atrasada",
        "pergunta_chave": "a revisao perde garantia se atrasar",
        "resposta_base": (
            "Pode haver restrição ou perda de cobertura se ultrapassar o limite estabelecido pela Yamaha. "
            "O ideal é verificar o caso com o pós-venda."
        )
    },
    {
        "categoria": "primeira_revisao",
        "pergunta_chave": "quantos km e a primeira revisao",
        "resposta_base": "A primeira revisão normalmente deve ser feita com 1.000 km ou 6 meses, o que ocorrer primeiro."
    },
    {
        "categoria": "tolerancia_primeira_revisao",
        "pergunta_chave": "minha moto ta com 900 km ja posso agendar",
        "resposta_base": "Sim. Com 900 km você já pode agendar a primeira revisão."
    },
    {
        "categoria": "lavagem",
        "pergunta_chave": "a revisao inclui lavagem",
        "resposta_base": "Sim. A revisão pode incluir lavagem conforme disponibilidade e fluxo da oficina."
    },
    {
        "categoria": "sala_espera",
        "pergunta_chave": "posso esperar a moto ficar pronta",
        "resposta_base": "Pode sim. Temos opção para o cliente aguardar na concessionária."
    },
    {
        "categoria": "revisao_sabado",
        "pergunta_chave": "tem revisao no sabado",
        "resposta_base": "Aos sábados realizamos somente 1ª e 2ª revisão, conforme disponibilidade de agenda."
    },
    {
        "categoria": "busca_moto",
        "pergunta_chave": "voces buscam a moto em casa",
        "resposta_base": "No momento não trabalhamos com busca da moto em casa."
    },
    {
        "categoria": "deixar_moto",
        "pergunta_chave": "posso deixar a moto e buscar depois",
        "resposta_base": "Pode sim. Você pode deixar a moto na concessionária e buscar depois."
    },
    {
        "categoria": "revisao_rapida",
        "pergunta_chave": "tem revisao rapida",
        "resposta_base": "A 1ª e 2ª revisão costumam ter média aproximada de 1h30 a 2h, dependendo do fluxo da oficina."
    },
    {
        "categoria": "regulagem_valvula",
        "pergunta_chave": "qual revisao faz regulagem de valvula",
        "resposta_base": "A verificação pode ocorrer nas revisões conforme plano de manutenção. O ajuste é feito quando estiver fora da especificação."
    },
    {
        "categoria": "servico_alinhamento",
        "pergunta_chave": "voces fazem alinhamento",
        "resposta_base": "Sim. Realizamos alinhamento."
    },
    {
        "categoria": "servico_limpeza_bico",
        "pergunta_chave": "faz limpeza de bico",
        "resposta_base": "Sim. Realizamos limpeza de bico."
    },
    {
        "categoria": "servico_relacao",
        "pergunta_chave": "fazem troca de relacao",
        "resposta_base": "Sim. Realizamos troca de relação."
    },
    {
        "categoria": "servico_pneu",
        "pergunta_chave": "tem troca de pneu",
        "resposta_base": "Sim. Realizamos troca de pneu."
    },
    {
        "categoria": "mao_de_obra",
        "pergunta_chave": "quanto fica a mao de obra",
        "resposta_base": "O valor da mão de obra depende do serviço a ser executado."
    },

    # GARANTIA
    {
        "categoria": "garantia_status",
        "pergunta_chave": "minha moto ainda ta na garantia",
        "resposta_base": "Precisamos verificar o modelo, data da compra e histórico de revisões para confirmar a garantia."
    },
    {
        "categoria": "garantia_escapamento_esportivo",
        "pergunta_chave": "se eu colocar escapamento esportivo perde garantia",
        "resposta_base": (
            "A instalação de escapamento esportivo pode restringir a cobertura se a modificação for relacionada ao defeito apresentado."
        )
    },
    {
        "categoria": "garantia_bateria",
        "pergunta_chave": "a garantia cobre bateria",
        "resposta_base": (
            "A bateria pode ter regras específicas de cobertura. É necessário avaliar se há defeito de fabricação ou desgaste natural."
        )
    },
    {
        "categoria": "revisao_fora_concessionaria",
        "pergunta_chave": "posso fazer revisao fora da concessionaria",
        "resposta_base": (
            "Para manter a garantia de fábrica, o recomendado é realizar as revisões na rede autorizada Yamaha."
        )
    },
    {
        "categoria": "garantia_eletrica",
        "pergunta_chave": "garantia cobre problema eletrico",
        "resposta_base": (
            "Problemas elétricos podem ser cobertos se forem causados por defeito de fabricação e não por instalação de acessórios ou modificações indevidas."
        )
    },
    {
        "categoria": "garantia_moto_falhando",
        "pergunta_chave": "minha moto ta falhando isso entra na garantia",
        "resposta_base": (
            "Pode ser avaliado em garantia. A concessionária fará diagnóstico para verificar se é defeito de fabricação, combustível, uso ou manutenção."
        )
    },
    {
        "categoria": "garantia_painel",
        "pergunta_chave": "garantia cobre painel apagando",
        "resposta_base": (
            "O painel pode ser coberto se houver defeito interno de fabricação e se o sistema elétrico original não tiver sido alterado."
        )
    },
    {
        "categoria": "farol_auxiliar",
        "pergunta_chave": "posso instalar farol auxiliar",
        "resposta_base": (
            "Não recomendamos instalar acessórios não originais no sistema elétrico. Se a modificação causar falha, pode afetar a garantia."
        )
    },
    {
        "categoria": "peca_paralela",
        "pergunta_chave": "peca paralela perde garantia",
        "resposta_base": (
            "O uso de peças paralelas pode afetar a garantia da parte relacionada e de sistemas que tenham ligação com a peça instalada."
        )
    },
    {
        "categoria": "garantia_vazamento",
        "pergunta_chave": "a garantia cobre vazamento",
        "resposta_base": (
            "Vazamentos podem ser cobertos se forem causados por falha de fabricação, após avaliação técnica da concessionária."
        )
    },
    {
        "categoria": "garantia_embreagem",
        "pergunta_chave": "garantia cobre embreagem",
        "resposta_base": (
            "Peças de desgaste natural geralmente não têm cobertura, mas defeitos de fabricação podem ser avaliados tecnicamente."
        )
    },
    {
        "categoria": "garantia_pintura",
        "pergunta_chave": "a yamaha cobre defeito de pintura",
        "resposta_base": (
            "Defeitos de fabricação na pintura podem ser avaliados em garantia, desde que não sejam causados por agentes externos."
        )
    },
]


def normalizar_chave(texto):
    texto = str(texto or "").strip().lower()
    return " ".join(texto.split())


def popular_faq():
    criar_banco()
    db = SessionLocal()

    try:
        total_novos = 0
        total_atualizados = 0

        for item in FAQS:
            categoria = normalizar_chave(item.get("categoria", ""))
            pergunta_chave = normalizar_chave(item.get("pergunta_chave", ""))
            resposta_base = str(item.get("resposta_base", "")).strip()

            if not categoria or not pergunta_chave or not resposta_base:
                continue

            existente = db.query(FaqRevisao).filter(
                FaqRevisao.categoria == categoria,
                FaqRevisao.pergunta_chave == pergunta_chave
            ).first()

            if existente:
                existente.resposta_base = resposta_base
                existente.ativo = True
                total_atualizados += 1
            else:
                novo = FaqRevisao(
                    categoria=categoria,
                    pergunta_chave=pergunta_chave,
                    resposta_base=resposta_base,
                    ativo=True
                )
                db.add(novo)
                total_novos += 1

        db.commit()

        print("==========================================")
        print("BASE DE CONHECIMENTO POPULADA COM SUCESSO")
        print("Novos:", total_novos)
        print("Atualizados:", total_atualizados)
        print("Total FAQS:", len(FAQS))
        print("==========================================")

    except Exception as e:
        db.rollback()
        print("[ERRO] Falha ao popular base:", repr(e))

    finally:
        db.close()


if __name__ == "__main__":
    popular_faq()