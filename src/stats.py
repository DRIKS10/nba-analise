"""
Cálculo de baseline (média e desvio-padrão) e de desvios (z-score + magnitude)
de cada jogador, comparando o desempenho de hoje com o histórico dos últimos
jogos (ver seções 4 e 5 da especificação).

Este arquivo é "matemática pura": não sabe nada sobre Telegram, planilha ou
nba_api. Ele só recebe números (dicionários simples) e devolve resultados.
Isso facilita testar se a conta está certa isoladamente do resto do sistema.
"""

import statistics

from src import config


def media_e_desvio_padrao(valores):
    """Recebe uma lista de números e devolve (média, desvio_padrao).

    Precisa de pelo menos 2 valores para calcular um desvio-padrão de amostra;
    com menos que isso, devolve desvio_padrao=None (não dá pra confiar nele).
    """
    valores = [v for v in valores if v is not None]
    if not valores:
        return None, None
    media = statistics.mean(valores)
    if len(valores) < 2:
        return media, None
    desvio = statistics.stdev(valores)
    return media, desvio


def calcular_zscore(valor, media, desvio_padrao):
    """Quantos desvios-padrão o valor de hoje está da média histórica.

    Devolve None se não for possível calcular (média ausente ou desvio zero).
    """
    if media is None or desvio_padrao is None or desvio_padrao == 0:
        return None
    return (valor - media) / desvio_padrao


def _valores_historico(historico, campo):
    """Extrai de uma lista de jogos passados os valores de um campo específico,
    ignorando jogos em que esse campo não existe (None).
    """
    return [jogo[campo] for jogo in historico if jogo.get(campo) is not None]


def avaliar_metrica(metrica_cfg, hoje, historico):
    """
    Verifica se UMA métrica teve um desvio relevante para um jogador, comparando
    o 1º tempo de hoje com o histórico dos últimos N jogos (config.HISTORICO_JOGOS).

    Parâmetros:
        metrica_cfg: um dos dicionários definidos em config.METRICAS
        hoje: dicionário com as estatísticas do 1º tempo de hoje do jogador
              (chaves como "PTS_1T", "MIN_1T", "FGA_1T", ...)
        historico: lista de dicionários, um por jogo passado, cada um com as
                   estatísticas de 1º tempo E de jogo completo desse jogo
                   (chaves como "PTS_1T", "PTS_JOGO", ...)

    Devolve um dicionário com, no mínimo:
        desviou    -> True/False
        valor_1T   -> valor de hoje no 1º tempo (para exibição no relatório)
        media_1T   -> média histórica do 1º tempo (para exibição)
        media_jogo -> média histórica de jogo completo (para exibição)
    """
    chave = metrica_cfg["chave"]
    campo_1t = f"{chave}_1T"
    campo_jogo = f"{chave}_JOGO"

    valor_1T = hoje.get(campo_1t)
    media_jogo, _ = media_e_desvio_padrao(_valores_historico(historico, campo_jogo))

    resultado = {
        "chave": chave,
        "desviou": False,
        "valor_1T": valor_1T,
        "media_1T": None,
        "media_jogo": media_jogo,
    }

    if valor_1T is None or len(historico) == 0:
        return resultado

    # --- Faltas cometidas: regra especial, sem z-score (ver seção 5) ---
    if not metrica_cfg["usa_zscore"]:
        media_1T, _ = media_e_desvio_padrao(_valores_historico(historico, campo_1t))
        resultado["media_1T"] = media_1T
        resultado["desviou"] = valor_1T >= metrica_cfg["piso"]
        return resultado

    base_calculo = metrica_cfg["base_calculo"]
    z = None
    magnitude = None

    if base_calculo == "bruto":
        historico_1T = _valores_historico(historico, campo_1t)
        media_1T, desvio_1T = media_e_desvio_padrao(historico_1T)
        z = calcular_zscore(valor_1T, media_1T, desvio_1T)
        if media_1T is not None:
            magnitude = abs(valor_1T - media_1T)

    elif base_calculo == "por_minuto":
        # A magnitude e a média exibida usam o valor BRUTO (ex: "12 tentativas"),
        # mas o z-score é calculado sobre a taxa por minuto, para não confundir
        # "jogou mais minutos" com "mudou de comportamento".
        historico_1T = _valores_historico(historico, campo_1t)
        media_1T, _ = media_e_desvio_padrao(historico_1T)

        minutos_hoje = hoje.get("MIN_1T")
        if minutos_hoje is not None and minutos_hoje >= config.MINUTOS_MINIMOS_TAXA:
            taxa_hoje = valor_1T / minutos_hoje
            taxas_historico = [
                jogo[campo_1t] / jogo["MIN_1T"]
                for jogo in historico
                if jogo.get("MIN_1T") and jogo["MIN_1T"] >= config.MINUTOS_MINIMOS_TAXA
                and jogo.get(campo_1t) is not None
            ]
            media_taxa, desvio_taxa = media_e_desvio_padrao(taxas_historico)
            z = calcular_zscore(taxa_hoje, media_taxa, desvio_taxa)
            if media_1T is not None:
                magnitude = abs(valor_1T - media_1T)
        # Se o jogador jogou pouco no 1ºT, a amostra é pequena demais: z e
        # magnitude ficam None e a métrica não é considerada (desviou=False).

    elif base_calculo == "taxa":
        amostra_ok = True
        amostra = metrica_cfg.get("amostra_minima")
        if amostra:
            campo_amostra = f"{amostra['metrica_base']}_1T"
            valor_amostra = hoje.get(campo_amostra) or 0
            amostra_ok = valor_amostra >= amostra["minimo"]

        historico_1T = _valores_historico(historico, campo_1t)
        media_1T, desvio_1T = media_e_desvio_padrao(historico_1T)

        if amostra_ok:
            z = calcular_zscore(valor_1T, media_1T, desvio_1T)
            if media_1T is not None:
                magnitude = abs(valor_1T - media_1T)
        # Se a amostra mínima não foi atingida (ex: menos de 6 FGA para o FG%),
        # a métrica não é considerada, mas ainda mostramos media_1T se pedido.

    resultado["media_1T"] = media_1T

    if z is None or magnitude is None:
        return resultado

    if metrica_cfg["direcao"] == "cima":
        z_relevante = z >= config.LIMIAR_ZSCORE
    else:  # "ambos"
        z_relevante = abs(z) >= config.LIMIAR_ZSCORE

    magnitude_relevante = magnitude >= metrica_cfg["piso"]

    resultado["desviou"] = bool(z_relevante and magnitude_relevante)
    return resultado


def avaliar_jogador(hoje, historico):
    """Avalia TODAS as métricas de config.METRICAS para um jogador.

    Devolve um dicionário {chave_da_metrica: resultado_de_avaliar_metrica}.
    """
    return {
        chave: avaliar_metrica(metrica_cfg, hoje, historico)
        for chave, metrica_cfg in config.METRICAS.items()
    }
