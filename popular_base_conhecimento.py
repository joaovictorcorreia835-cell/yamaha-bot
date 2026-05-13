# ==========================================
# POPULAR BASE DE CONHECIMENTO - YAMAHA BOT
# ==========================================

from database import SessionLocal, criar_banco, FaqRevisao


FAQS = [
    {
        "categoria": "valor_revisao",
        "pergunta_chave": "quanto custa a revisao da minha fz15",
        "resposta_base": "O valor depende do pacote da revisão e se a moto está na garantia. Se estiver na garantia, os valores podem ser consultados no site da Yamaha, na aba Serviços."
    },
    {
        "categoria": "revisao_km",
        "pergunta_chave": "minha moto chegou nos 5 mil km ja preciso revisar",
        "resposta_base": "As revisões são feitas de acordo com o manual do proprietário. Lá constam todas as revisões por tempo ou quilometragem."
    },
    {
        "categoria": "agendamento",
        "pergunta_chave": "posso fazer revisao sem agendar",
        "resposta_base": "De preferência, as revisões devem ser agendadas com antecedência para garantir melhor atendimento."
    },
    {
        "categoria": "tempo_revisao",
        "pergunta_chave": "quanto tempo demora a revisao",
        "resposta_base": "O tempo da revisão depende de qual revisão será realizada. Cada revisão tem uma estimativa conforme o manual de serviços."
    },
    {
        "categoria": "troca_oleo",
        "pergunta_chave": "voces trocam oleo na revisao",
        "resposta_base": "Sim. Em toda revisão é feita a substituição do óleo."
    },
    {
        "categoria": "oleo_crosser",
        "pergunta_chave": "qual oleo voces usam na crosser",
        "resposta_base": "Para a Crosser, utilizamos Yamalube 20W50."
    },
    {
        "categoria": "oleo_cliente",
        "pergunta_chave": "posso levar meu proprio oleo",
        "resposta_base": "Pode sim, desde que seja óleo Yamalube."
    },
    {
        "categoria": "garantia_revisao_atrasada",
        "pergunta_chave": "a revisao perde garantia se atrasar",
        "resposta_base": "Sim. Se ultrapassar o limite estabelecido pelo fabricante, pode haver perda da garantia."
    },
    {
        "categoria": "primeira_revisao",
        "pergunta_chave": "quantos km e a primeira revisao",
        "resposta_base": "A primeira revisão deve ser feita com 1.000 km ou 6 meses da data da compra, o que ocorrer primeiro."
    },
    {
        "categoria": "tolerancia_primeira_revisao",
        "pergunta_chave": "minha moto ta com 900 km ja posso agendar",
        "resposta_base": "Sim. A tolerância da primeira revisão é de 900 km a 1.100 km."
    },
    {
        "categoria": "lavagem",
        "pergunta_chave": "a revisao inclui lavagem",
        "resposta_base": "Sim. A revisão inclui lavagem."
    },
    {
        "categoria": "sala_espera",
        "pergunta_chave": "posso esperar a moto ficar pronta",
        "resposta_base": "Pode sim. Temos sala de espera para clientes."
    },
    {
        "categoria": "revisao_sabado",
        "pergunta_chave": "tem revisao no sabado",
        "resposta_base": "Aos sábados realizamos somente primeira e segunda revisão, dependendo do fluxo de agendamento."
    },
    {
        "categoria": "busca_moto",
        "pergunta_chave": "voces buscam a moto em casa",
        "resposta_base": "No momento não buscamos a moto em casa."
    },
    {
        "categoria": "deixar_moto",
        "pergunta_chave": "posso deixar a moto e buscar depois",
        "resposta_base": "Pode sim. Você pode deixar a moto e buscar depois."
    },
    {
        "categoria": "revisao_rapida",
        "pergunta_chave": "tem revisao rapida",
        "resposta_base": "A primeira e segunda revisão têm média de tempo de 1h30 a 2h."
    },
    {
        "categoria": "regulagem_valvula",
        "pergunta_chave": "qual revisao faz regulagem de valvula",
        "resposta_base": "A partir da primeira revisão é feita a verificação. Sempre que estiver fora do especificado, é realizado o ajuste."
    },
    {
        "categoria": "tempo_lander",
        "pergunta_chave": "a revisao da lander demora quantas horas",
        "resposta_base": "Depende da revisão. Cada revisão tem uma estimativa conforme o manual de serviços."
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
    {
        "categoria": "revisao_nmax",
        "pergunta_chave": "a revisao da nmax e mais cara",
        "resposta_base": "Não. As revisões na garantia possuem preço fixo."
    },
    {
        "categoria": "filtro_ar",
        "pergunta_chave": "qual revisao troca filtro de ar",
        "resposta_base": "Depende da necessidade de substituição. Em todas as revisões é feita a verificação."
    },

    # GARANTIA
    {
        "categoria": "garantia_status",
        "pergunta_chave": "minha moto ainda ta na garantia",
        "resposta_base": "Precisamos verificar o manual e o histórico de revisões para confirmar se a moto ainda está na garantia."
    },
    {
        "categoria": "garantia_escapamento",
        "pergunta_chave": "escapamento enferrujado entra na garantia",
        "resposta_base": "Depende do uso e do estado da peça. É necessário avaliar na concessionária."
    },
    {
        "categoria": "garantia_escapamento_esportivo",
        "pergunta_chave": "se eu colocar escapamento esportivo perde garantia",
        "resposta_base": "A instalação de escapamento esportivo não anula automaticamente toda a garantia, mas pode restringir a cobertura. A garantia pode ser negada se a modificação for considerada causa direta de um defeito."
    },
    {
        "categoria": "garantia_bateria",
        "pergunta_chave": "a garantia cobre bateria",
        "resposta_base": "A bateria geralmente não possui a mesma cobertura contratual da motocicleta, por ser item de desgaste. Ela possui garantia legal obrigatória de 90 dias, desde que seja constatado vício de fabricação."
    },
    {
        "categoria": "tempo_garantia",
        "pergunta_chave": "quanto tempo dura a garantia yamaha",
        "resposta_base": "O tempo de garantia depende do modelo da motocicleta."
    },
    {
        "categoria": "revisao_fora_concessionaria",
        "pergunta_chave": "posso fazer revisao fora da concessionaria",
        "resposta_base": "Fazer revisão fora da concessionária Yamaha pode resultar na perda da garantia de fábrica. A Yamaha exige que as revisões periódicas sejam realizadas na rede autorizada para manter a cobertura."
    },
    {
        "categoria": "garantia_guidao",
        "pergunta_chave": "perco garantia se trocar o guidao",
        "resposta_base": "A troca do guidão não anula automaticamente toda a garantia, mas pode restringir a cobertura. A garantia pode ser negada se a modificação for considerada causa direta do defeito."
    },
    {
        "categoria": "garantia_eletrica",
        "pergunta_chave": "garantia cobre problema eletrico",
        "resposta_base": "Sim. Problemas no sistema elétrico, como injeção, sensores, ECU ou alternador, podem ser cobertos, desde que sejam causados por defeito de fabricação e não por instalação de acessórios indevidos."
    },
    {
        "categoria": "garantia_moto_falhando",
        "pergunta_chave": "minha moto ta falhando isso entra na garantia",
        "resposta_base": "Sim. Falhas no motor ou sistema de injeção podem ser cobertas. A concessionária fará um diagnóstico para confirmar se não há mau uso ou combustível adulterado."
    },
    {
        "categoria": "garantia_painel",
        "pergunta_chave": "garantia cobre painel apagando",
        "resposta_base": "Sim. O painel de instrumentos pode ser coberto se apagar por defeito interno, desde que o sistema elétrico original não tenha sido alterado."
    },
    {
        "categoria": "farol_auxiliar",
        "pergunta_chave": "posso instalar farol auxiliar",
        "resposta_base": "Não é recomendado instalar acessórios não originais no sistema elétrico, como faróis auxiliares, lâmpadas de LED ou alarmes. Caso a modificação afete o sistema elétrico, pode haver perda de garantia."
    },
    {
        "categoria": "peca_paralela",
        "pergunta_chave": "peca paralela perde garantia",
        "resposta_base": "Sim. O uso de peças, acessórios ou componentes não autorizados pela marca pode invalidar a garantia da parte afetada e, em alguns casos, de outros sistemas relacionados."
    },
    {
        "categoria": "garantia_vazamento",
        "pergunta_chave": "a garantia cobre vazamento",
        "resposta_base": "Sim. Vazamentos de óleo ou fluidos causados por falha de vedação, juntas ou retentores dentro do período de garantia podem ser cobertos, após análise técnica."
    },
    {
        "categoria": "garantia_embreagem",
        "pergunta_chave": "garantia cobre embreagem",
        "resposta_base": "Geralmente não. Peças de desgaste natural, como discos de embreagem, pastilhas de freio, relação e pneus normalmente não são cobertas. Porém, defeitos em componentes estruturais podem ser avaliados."
    },
    {
        "categoria": "garantia_pintura",
        "pergunta_chave": "a yamaha cobre defeito de pintura",
        "resposta_base": "Sim. Defeitos de fabricação na pintura original, como descascamento, bolhas ou falhas no verniz, podem ser cobertos, desde que não sejam causados por agentes externos."
    },
]


def popular_faq():
    criar_banco()

    db = SessionLocal()

    try:
        total_novos = 0
        total_atualizados = 0

        for item in FAQS:
            categoria = item["categoria"].strip()
            pergunta_chave = item["pergunta_chave"].strip().lower()
            resposta_base = item["resposta_base"].strip()

            existente = db.query(FaqRevisao).filter(
                FaqRevisao.pergunta_chave == pergunta_chave
            ).first()

            if existente:
                existente.categoria = categoria
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
        print("Total:", len(FAQS))
        print("==========================================")

    except Exception as e:
        db.rollback()
        print("[ERRO] Falha ao popular base:", repr(e))

    finally:
        db.close()


if __name__ == "__main__":
    popular_faq()