"""
Ponto de entrada do sistema. Roda uma vez a cada execução do cron (GitHub
Actions): verifica todos os jogos da NBA de hoje e decide o que fazer com
cada um, seguindo a seção 3 da especificação:

- Jogo no intervalo -> calcula desvios de cada jogador, manda o relatório
  pelo Telegram (se houver desvio) e salva os alertas na planilha.
- Jogo que acabou de terminar -> salva os dados completos de TODOS os
  jogadores no histórico (alimenta o baseline dos próximos jogos) e
  atualiza os alertas criados no intervalo com os valores reais do jogo.

Cada jogo só é processado uma vez em cada etapa (ver aba "Controle" em
sheets_client.py), para não repetir notificações quando o cron roda de novo
e encontra o mesmo jogo ainda no intervalo ou ainda "Final".
"""

from datetime import date

from dotenv import load_dotenv

from src import config, nba_client, projection, report, sheets_client, stats, telegram_client

# Carrega variáveis do arquivo .env quando rodamos localmente. No GitHub
# Actions não existe arquivo .env (as variáveis vêm dos Secrets), então esta
# linha simplesmente não faz nada nesse caso.
load_dotenv()


def processar_intervalo(planilha, jogo):
    game_id = jogo["gameId"]
    if sheets_client.jogo_ja_processado(planilha, game_id, "intervalo"):
        return

        jogadores_do_jogo = nba_client.obter_boxscore_intervalo(game_id)
    hoje = date.today().isoformat()

    times_para_relatorio = {}

    for jogador in jogadores_do_jogo:
        historico = sheets_client.obter_historico_jogador(planilha, jogador["id"])
        resultados = stats.avaliar_jogador(jogador, historico)

        projecao = None
        if projection.projecao_aplicavel(resultados):
            projecao = projection.calcular_projecao_pontos(jogador, historico)

        if any(r["desviou"] for r in resultados.values()):
            _salvar_linha_alerta(
                planilha, hoje, jogador, jogador["time"], jogador["adversario"], resultados, projecao
            )

        times_para_relatorio.setdefault(jogador["time"], []).append({
            "nome": jogador["nome"],
            "resultados": resultados,
            "projecao": projecao,
        })

    texto_relatorio = report.montar_relatorio(times_para_relatorio)

    if texto_relatorio:
        telegram_client.enviar_mensagem(texto_relatorio)

    sheets_client.marcar_jogo_processado(planilha, game_id, "intervalo")


def _salvar_linha_alerta(planilha, data, jogador, time, adversario, resultados, projecao):
    linha = {
        "Data": data,
        "Jogador": jogador["nome"],
        "Posicao": jogador["posicao"],
        "Time": time,
        "Adversario": adversario,
    }

    for chave in config.ORDEM_COLUNAS_ALERTA:
        resultado = resultados[chave]
        if not resultado["desviou"]:
            continue  # métricas sem desvio ficam em branco (seção 8)
        rotulo = config.METRICAS[chave]["rotulo"]
        linha[f"{rotulo} 1ºT"] = resultado["valor_1T"]
        linha[f"{rotulo} 1ºT (media)"] = resultado["media_1T"]
        linha[f"{rotulo} Jogo (media)"] = resultado["media_jogo"]
        # "[Métrica] Jogo" (valor real) só é preenchido quando o jogo
        # terminar, em atualizar_alerta_com_resultado_final()

    if resultados["PF"]["desviou"]:
        linha["Faltas 1ºT"] = resultados["PF"]["valor_1T"]

    if projecao is not None:
        linha["Projecao Pontos"] = round(projecao, 1)

    sheets_client.registrar_alerta(planilha, linha)


def processar_final(planilha, jogo):
    game_id = jogo["gameId"]
    if sheets_client.jogo_ja_processado(planilha, game_id, "final"):
        return

    hoje = date.today().isoformat()
    jogadores = nba_client.obter_boxscore_final_por_jogador(game_id)

    for jogador in jogadores:
        # Seção 3.2: SEMPRE salva no histórico, mesmo quem não desviou
        sheets_client.salvar_jogo_completo(
            planilha,
            jogador_id=jogador["id"],
            jogador_nome=jogador["nome"],
            time=jogador["time"],
            adversario=jogador["adversario"],
            data=hoje,
            posicao=jogador["posicao"],
            estatisticas=jogador,
        )

        # Se esse jogador tinha um alerta criado no intervalo, atualiza com
        # os valores reais do jogo completo (para comparar com a projeção)
        valores_jogo_completo = {
            config.METRICAS[chave]["rotulo"]: jogador[f"{chave}_JOGO"]
            for chave in config.ORDEM_COLUNAS_ALERTA
        }
        sheets_client.atualizar_alerta_com_resultado_final(
            planilha, hoje, jogador["nome"], jogador["time"], valores_jogo_completo
        )

    sheets_client.marcar_jogo_processado(planilha, game_id, "final")


def main():
    planilha = sheets_client.conectar()
    jogos_de_hoje = nba_client.listar_jogos_do_dia()

    for jogo in jogos_de_hoje:
        if nba_client.jogo_esta_no_intervalo(jogo):
            processar_intervalo(planilha, jogo)
        elif nba_client.jogo_terminou(jogo):
            processar_final(planilha, jogo)


if __name__ == "__main__":
    main()
