"""
Ponto de entrada do modo pre-live (ver spec-prelive-nba.md). Roda uma vez por
dia, de manhã, bem antes dos jogos começarem — independente do main.py do
halftime, que continua rodando a cada 5 minutos exatamente como antes.

Regras de proteção (seção 0 do spec-prelive-nba.md): este arquivo NUNCA
escreve na aba "Historico" nem na aba "Alertas" do halftime — só lê a
primeira (para calcular o histórico de cada jogador) e escreve apenas nas
abas próprias "ControlePreLive" e "AlertasPreLive". Reaproveita
sheets_client.conectar() e telegram_client.enviar_mensagem() sem alterar
nenhuma linha desses arquivos.

Nota de revisão (etapa ainda não implementada): a coluna "[Métrica] Resultado
Real" da aba AlertasPreLive (ver prelive_sheets_client.cabecalho_alertas_prelive)
fica em branco por enquanto. Preenchê-la automaticamente com o resultado real
do jogo do dia é uma etapa futura, a implementar e confirmar com o usuário
separadamente (ver seção 8 do spec-prelive-nba.md) — por ora a comparação
"o jogador sinalizado realmente jogou melhor?" é feita manualmente, cruzando
esta aba com a aba Historico pelo GameID.
"""

from dotenv import load_dotenv

from src import prelive_config, prelive_nba_client, prelive_report, prelive_sheets_client, prelive_stats, sheets_client, telegram_client
from src.prelive_nba_client import _dia_de_jogo_brasilia

load_dotenv()


def _avaliar_time(nome_time, nome_adversario, jogadores_por_time, cache_historico, indice_contexto):
    """Avalia todos os jogadores de UM time contra UM adversário, e devolve
    (jogadores_com_desvio, contagem_diagnostico). A contagem é só para log —
    não afeta o Telegram nem a planilha — e serve para o usuário conseguir
    confirmar, pelo log da execução no GitHub Actions, se um time "silencioso"
    no relatório é porque ninguém desviou mesmo, ou porque ninguém tinha
    histórico/minutos suficientes ainda (seção 4.1/4.2 do spec-prelive-nba.md).
    """
    elenco = jogadores_por_time.get(nome_time, [])
    contagem = {
        "elenco": len(elenco),
        "sem_historico_suficiente": 0,
        "abaixo_do_piso_de_minutos": 0,
        "sem_desvio": 0,
        "com_desvio": 0,
    }
    jogadores_com_desvio = []

    for jogador_info in elenco:
        jogos_validos = prelive_sheets_client.obter_jogos_validos_jogador(cache_historico, jogador_info["id"])
        avaliacao = prelive_stats.avaliar_jogador_prelive(jogos_validos)
        if avaliacao is None:
            if len(jogos_validos) < prelive_config.JANELA_JOGOS_VALIDOS:
                contagem["sem_historico_suficiente"] += 1
            else:
                contagem["abaixo_do_piso_de_minutos"] += 1
            continue

        resultados = avaliacao["resultados"]
        if not any(r["desviou"] for r in resultados.values()):
            contagem["sem_desvio"] += 1
            continue

        contagem["com_desvio"] += 1
        posicao = avaliacao["jogo1"]["Posicao"]
        contexto = prelive_stats.calcular_contexto_adversario(indice_contexto, posicao, nome_adversario)
        jogadores_com_desvio.append({
            "jogador_info": jogador_info,
            "posicao": posicao,
            "jogo1": avaliacao["jogo1"],
            "jogo2": avaliacao["jogo2"],
            "resultados": resultados,
            "contexto": contexto,
        })

    return jogadores_com_desvio, contagem


def processar_jogo(cache_controle, cache_alertas, cache_historico, indice_contexto, jogadores_por_time, jogo, data_hoje):
    game_id = jogo["id"]
    if prelive_sheets_client.jogo_ja_processado_prelive(cache_controle, game_id):
        return

    nome_casa = jogo["teams"]["home"]["name"]
    nome_visitante = jogo["teams"]["visitors"]["name"]

    print(f"[pre-live] Jogo {game_id}: {nome_visitante} @ {nome_casa}")

    times_para_relatorio = {}
    alertas_para_gravar = []

    for nome_time, nome_adversario in ((nome_casa, nome_visitante), (nome_visitante, nome_casa)):
        jogadores_com_desvio, contagem = _avaliar_time(
            nome_time, nome_adversario, jogadores_por_time, cache_historico, indice_contexto
        )
        print(
            f"[pre-live]   {nome_time}: {contagem['elenco']} no elenco recente | "
            f"{contagem['sem_historico_suficiente']} sem 7 jogos válidos ainda | "
            f"{contagem['abaixo_do_piso_de_minutos']} abaixo de {prelive_config.FILTRO_MINUTOS_ROTACAO} min de rotação | "
            f"{contagem['sem_desvio']} avaliados sem desvio | "
            f"{contagem['com_desvio']} com desvio relevante"
        )

        for item in jogadores_com_desvio:
            times_para_relatorio.setdefault(nome_time, []).append({
                "nome": item["jogador_info"]["nome"],
                "posicao": item["posicao"],
                "jogo1": item["jogo1"],
                "jogo2": item["jogo2"],
                "resultados": item["resultados"],
                "adversario_hoje": nome_adversario,
                "contexto": item["contexto"],
            })
            alertas_para_gravar.append((item["jogador_info"], item["posicao"], nome_time, nome_adversario, item["resultados"]))

    texto_relatorio = prelive_report.montar_relatorio_jogo(nome_visitante, nome_casa, times_para_relatorio)

    if texto_relatorio:
        # Só grava e marca como processado DEPOIS do Telegram confirmar o
        # envio (seção 3 do spec-prelive-nba.md): no pior caso duplica a
        # mensagem numa execução manual extra, o que é preferível a perder o
        # relatório do dia.
        telegram_client.enviar_mensagem(texto_relatorio)
        for jogador_info, posicao, nome_time, nome_adversario, resultados in alertas_para_gravar:
            prelive_sheets_client.registrar_alerta_prelive(
                cache_alertas, game_id, data_hoje, jogador_info, posicao, nome_time, nome_adversario, resultados
            )
        prelive_sheets_client.salvar_cache_alertas_prelive(cache_alertas)
        prelive_sheets_client.marcar_jogo_processado_prelive(cache_controle, game_id, data_hoje, "ENVIADO")
    else:
        prelive_sheets_client.marcar_jogo_processado_prelive(cache_controle, game_id, data_hoje, "SEM_ALERTA")


def main():
    planilha = sheets_client.conectar()
    prelive_sheets_client.garantir_abas_prelive(planilha)

    cache_controle = prelive_sheets_client.carregar_cache_controle_prelive(planilha)
    cache_alertas = prelive_sheets_client.carregar_cache_alertas_prelive(planilha)
    cache_historico = sheets_client.carregar_cache_historico(planilha)  # só leitura — ver regra 2

    indice_contexto = prelive_stats.construir_indice_contexto(cache_historico)
    jogadores_por_time = prelive_sheets_client.jogadores_recentes_por_time(cache_historico)

    jogos = prelive_nba_client.listar_jogos_nao_iniciados()
    data_hoje = _dia_de_jogo_brasilia().isoformat()

    erros = []
    for jogo in jogos:
        try:
            processar_jogo(cache_controle, cache_alertas, cache_historico, indice_contexto, jogadores_por_time, jogo, data_hoje)
        except Exception as erro:
            # Um erro em UM jogo não pode impedir os outros jogos do dia de
            # serem processados (mesmo padrão já usado no halftime).
            erros.append(f"Jogo {jogo.get('id')}: {erro}")

    if erros:
        raise RuntimeError(
            f"{len(erros)} jogo(s) falharam nesta execução (os demais foram "
            "processados normalmente):\n" + "\n".join(erros)
        )


if __name__ == "__main__":
    main()
