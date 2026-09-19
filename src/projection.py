"""
Projeção de pontos para o jogo completo, a partir do desempenho do 1º tempo
de hoje combinado com o histórico do jogador (ver seção 6 da especificação).

Assim como stats.py, este arquivo é "matemática pura".
"""

from src import config
from src.stats import media_e_desvio_padrao


def calcular_projecao_pontos(hoje, historico):
    """Calcula a projeção de pontos do jogo completo.

    Parâmetros:
        hoje: dict com as estatísticas do 1º tempo de hoje (precisa de
              MIN_1T, FGA_1T e PTS_1T)
        historico: lista de jogos passados, cada um com MIN_1T e MIN_JOGO

    Devolve o número de pontos projetados (float), ou None se não houver
    dados suficientes para calcular com confiança (ver pré-requisitos da
    seção 6: >= 8 min jogados no 1ºT e >= 6 FGA no 1ºT).
    """
    minutos_hoje = hoje.get("MIN_1T")
    fga_hoje = hoje.get("FGA_1T")
    pontos_hoje = hoje.get("PTS_1T")

    if minutos_hoje is None or minutos_hoje < config.MINUTOS_MINIMOS_TAXA:
        return None
    if fga_hoje is None or fga_hoje < config.PROJECAO_FGA_MINIMO:
        return None
    if pontos_hoje is None:
        return None

    minutos_2t_historico = [
        jogo["MIN_JOGO"] - jogo["MIN_1T"]
        for jogo in historico
        if jogo.get("MIN_JOGO") is not None and jogo.get("MIN_1T") is not None
    ]
    media_minutos_2t, _ = media_e_desvio_padrao(minutos_2t_historico)
    if media_minutos_2t is None:
        return None

    minutos_projetados = minutos_hoje + media_minutos_2t
    fga_por_minuto_hoje = fga_hoje / minutos_hoje
    pontos_por_tentativa_hoje = pontos_hoje / fga_hoje

    return minutos_projetados * fga_por_minuto_hoje * pontos_por_tentativa_hoje


def projecao_aplicavel(resultados_metricas):
    """Diz se a projeção deve ser calculada: só quando pelo menos uma das
    métricas-gatilho (Pontos, FGA, FG%, 3PA, 3PM ou Minutos) desviou.

    `resultados_metricas` é o dicionário devolvido por stats.avaliar_jogador.
    """
    return any(
        resultados_metricas[chave]["desviou"]
        for chave in config.METRICAS_GATILHO_PROJECAO
        if chave in resultados_metricas
    )
