"""
Ponto de entrada do sistema. Roda uma vez a cada execução do cron (GitHub
Actions): verifica todos os jogos da NBA de hoje/amanhã e decide o que fazer
com cada um, seguindo a seção 3 da especificação:

- Jogo no intervalo -> calcula desvios de cada jogador com histórico
  suficiente (seção 4), manda o relatório pelo Telegram (se houver desvio),
  salva os alertas na planilha, e grava o 1º tempo de TODOS os jogadores no
  histórico (mesmo que não tenham desviado).
- Jogo que acabou de terminar -> grava o jogo completo de TODOS os
  jogadores no histórico (criando a linha se o intervalo não tiver sido
  capturado) e atualiza os alertas criados no intervalo com os valores
  reais do jogo.

Cada jogo só é processado uma vez em cada etapa (ver aba "Controle" em
sheets_client.py), para não repetir notificações quando o cron roda de novo
e encontra o mesmo jogo ainda no intervalo ou ainda "Final".

Cada aba da planilha é lida apenas UMA VEZ por execução (ver nota de revisão
em sheets_client.py) — por isso as funções de leitura recebem um "cache"
em vez de ler a planilha direto a cada jogador.
"""

from datetime import date

from dotenv import load_dotenv

from src import config, nba_client, projection, report, sheets_client, stats, telegram_client

# Carrega variáveis do arquivo .env quando rodamos localmente. No GitHub
# Actions não existe arquivo .env (as variáveis vêm dos Secrets), então esta
# linha simplesmente não faz nada nesse caso.
load_dotenv()


def processar_intervalo(planilha, cache_controle, jogo):
    game_id = jogo["id"]
    if sheets_client.jogo_ja_processado(cache_controle, game_id, "intervalo"):
        return

    jogadores_do_jogo = nba_client.obter_boxscore_intervalo(game_id, jogo)
    hoje = date.today().isoformat()
    cache_historico = sheets_client.carregar_cache_historico(planilha)

    times_para_relatorio = {}

    for jogador in jogadores_do_jogo:
        # Histórico ANTES de registrar o jogo de hoje, para não comparar o
        # jogador com ele mesmo
        historico = sheets_client.obter_historico_jogador(cache_historico, jogador["id"])

        if stats.amostra_suficiente(historico):
            resultados = stats.avaliar_jogador(jogador, historico)

            projecao = None
            if projection.projecao_aplicavel(resultados):
                projecao = projection.calcular_projecao_pontos(jogador, historico)

            if any(r["desviou"] for r in resultados.values()):
                _salvar_linha_alerta(planilha, game_id, hoje, jogador, resultados, projecao)

            times_para_relatorio.setdefault(jogador["time"], []).append({
                "nome": jogador["nome"],
                "resultados": resultados,
                "projecao": projecao,
            })
        # Se a amostra ainda não é suficiente, o jogador não entra na análise
        # nem no relatório — mas o 1º tempo dele é gravado de qualquer forma
        # (linha abaixo), para a amostra ir crescendo.

        sheets_client.registrar_etapa_historico(cache_historico, game_id, hoje, jogador, "1T")

    texto_relatorio = report.montar_relatorio(times_para_relatorio)
    if texto_relatorio:
        telegram_client.enviar_mensagem(texto_relatorio)

    sheets_client.marcar_jogo_processado(cache_controle, game_id, "intervalo")


def _salvar_linha_alerta(planilha, game_id, data, jogador, resultados, projecao):
    linha = {
        "GameID": game_id,
        "JogadorID": jogador["id"],
        "Data": data,
        "Jogador": jogador["nome"],
        "Posicao": jogador["posicao"],
        "Time": jogador["time"],
        "Adversario": jogador["adversario"],
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


def processar_final(planilha, cache_controle, jogo):
    game_id = jogo["id"]
    if sheets_client.jogo_ja_processado(cache_controle, game_id, "final"):
        return

    hoje = date.today().isoformat()
    jogadores = nba_client.obter_boxscore_final(game_id, jogo)
    cache_historico = sheets_client.carregar_cache_historico(planilha)
    cache_alertas = sheets_client.carregar_cache_alertas(planilha)

    for jogador in jogadores:
        # Seção 3.2: SEMPRE grava no histórico, mesmo quem não desviou —
        # cria a linha se o intervalo não tiver sido capturado (ver nota de
        # revisão em sheets_client.py)
        sheets_client.registrar_etapa_historico(cache_historico, game_id, hoje, jogador, "JOGO")

        # Se esse jogador tinha um alerta criado no intervalo, atualiza com
        # os valores reais do jogo completo (para comparar com a projeção)
        valores_jogo_completo = {
            config.METRICAS[chave]["rotulo"]: jogador[f"{chave}_JOGO"]
            for chave in config.ORDEM_COLUNAS_ALERTA
        }
        sheets_client.atualizar_alerta_com_resultado_final(
            cache_alertas, game_id, jogador["id"], valores_jogo_completo
        )

    sheets_client.marcar_jogo_processado(cache_controle, game_id, "final")


def main():
    planilha = sheets_client.conectar()
    jogos_de_hoje = nba_client.listar_jogos_do_dia()
    cache_controle = sheets_client.carregar_cache_controle(planilha)

    for jogo in jogos_de_hoje:
        if nba_client.jogo_esta_no_intervalo(jogo):
            processar_intervalo(planilha, cache_controle, jogo)
        elif nba_client.jogo_terminou(jogo):
            processar_final(planilha, cache_controle, jogo)


if __name__ == "__main__":
    main()
