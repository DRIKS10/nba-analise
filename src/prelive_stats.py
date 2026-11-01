"""
Cálculo da Camada 1 (jogador contra ele mesmo) e do contexto do adversário
do modo pre-live (ver seções 4 e 5 do spec-prelive-nba.md).

Reaproveita a matemática genérica já existente em stats.py
(media_e_desvio_padrao, calcular_zscore) sem alterar nenhuma linha daquele
arquivo — essas funções só recebem listas de números, não sabem nada sobre
halftime nem pre-live.
"""

from src import prelive_config, stats


def avaliar_jogador_prelive(jogos_validos):
    """Avalia a Camada 1 (seção 4) para um jogador, a partir da lista de
    jogos válidos devolvida por prelive_sheets_client.obter_jogos_validos_jogador
    (jogo 0 = mais recente / jogo 1 da spec).

    Devolve None se o jogador não tem jogos válidos suficientes (seção 4.1)
    ou não passa no filtro de minutos de rotação (seção 4.2) — nesses casos
    ele fica de fora, em silêncio, sem gerar nenhum resultado.

    Caso contrário, devolve um dicionário com "jogo1", "jogo2" (para exibição
    no relatório) e "resultados" (um dicionário {chave_da_metrica: resultado}).
    """
    if len(jogos_validos) < prelive_config.JANELA_JOGOS_VALIDOS:
        return None

    jogo1, jogo2 = jogos_validos[0], jogos_validos[1]
    baseline = jogos_validos[2:7]

    media_minutos_recente = (jogo1["MIN_JOGO"] + jogo2["MIN_JOGO"]) / 2
    if media_minutos_recente < prelive_config.FILTRO_MINUTOS_ROTACAO:
        return None

    resultados = {
        chave: _avaliar_metrica_prelive(metrica_cfg, jogo1, jogo2, baseline)
        for chave, metrica_cfg in prelive_config.METRICAS_PRELIVE.items()
    }

    return {"jogo1": jogo1, "jogo2": jogo2, "resultados": resultados}


def _avaliar_metrica_prelive(metrica_cfg, jogo1, jogo2, baseline):
    chave = metrica_cfg["chave"]
    campo = f"{chave}_JOGO"

    valor1, valor2 = jogo1.get(campo), jogo2.get(campo)
    resultado = {
        "chave": chave,
        "desviou": False,
        "valor_jogo1": valor1,
        "valor_jogo2": valor2,
        "media_baseline": None,
    }
    if valor1 is None or valor2 is None:
        return resultado

    valores_baseline = [jogo[campo] for jogo in baseline if jogo.get(campo) is not None]
    if len(valores_baseline) < len(baseline):
        return resultado  # algum jogo do baseline sem esse dado -> não dá para confiar na média

    media_baseline, desvio_baseline = stats.media_e_desvio_padrao(valores_baseline)
    resultado["media_baseline"] = media_baseline

    # Critério 4: pré-requisito de amostra (FG% e 3P%) — soma das tentativas
    # dos jogos 1 e 2, não por jogo individual (diferente do halftime).
    amostra = metrica_cfg.get("amostra_minima")
    if amostra:
        campo_base = f"{amostra['metrica_base']}_JOGO"
        soma_amostra = (jogo1.get(campo_base) or 0) + (jogo2.get(campo_base) or 0)
        if soma_amostra < amostra["minimo"]:
            return resultado

    # Critério 2: piso de magnitude
    media_recente = (valor1 + valor2) / 2
    magnitude = media_recente - media_baseline
    if magnitude < metrica_cfg["piso"]:
        return resultado

    # Critério 3: trava — jogo 1 E jogo 2 precisam estar, cada um, acima da
    # média do baseline (evita que um único jogo atípico puxe a média).
    if not (valor1 > media_baseline and valor2 > media_baseline):
        return resultado

    # Critério 1: z-score. Decisão do usuário para desvio-padrão zero (seção
    # 4.3/9): dispensar o z-score e exigir só piso+trava, que já foram
    # confirmados acima.
    if desvio_baseline == 0:
        resultado["desviou"] = True
        return resultado

    z = stats.calcular_zscore(media_recente, media_baseline, desvio_baseline)
    resultado["desviou"] = bool(z is not None and z >= prelive_config.LIMIAR_ZSCORE)
    return resultado


# ---------------------------------------------------------------------------
# Contexto do adversário (seção 5) — fato ao lado do alerta, nunca um filtro.
# ---------------------------------------------------------------------------

def construir_indice_contexto(cache_historico):
    """Faz UMA passada pela aba Historico e organiza os dados de jogo
    completo por posição e adversário, para o cálculo de contexto não
    precisar escanear a planilha inteira de novo para cada jogador avaliado.

    Devolve um dicionário {(posicao, chave_da_metrica): {"liga": [...],
    "por_adversario": {"Nome do Time": [...]}}}, só para as métricas que têm
    linha de contexto (prelive_config.METRICAS_COM_CONTEXTO).
    """
    cabecalho = cache_historico["linhas"][0]
    idx_posicao = cabecalho.index("Posicao")
    idx_adversario = cabecalho.index("Adversario")
    idx_campo_por_metrica = {
        chave: cabecalho.index(f"{chave}_JOGO") for chave in prelive_config.METRICAS_COM_CONTEXTO
    }

    indice = {}
    for linha in cache_historico["linhas"][1:]:
        posicao = linha[idx_posicao]
        adversario = linha[idx_adversario]
        for chave, idx_campo in idx_campo_por_metrica.items():
            valor_bruto = linha[idx_campo]
            if valor_bruto in (None, ""):
                continue
            valor = float(str(valor_bruto).replace(",", "."))
            registro = indice.setdefault((posicao, chave), {"liga": [], "por_adversario": {}})
            registro["liga"].append(valor)
            registro["por_adversario"].setdefault(adversario, []).append(valor)

    return indice


def calcular_contexto_adversario(indice_contexto, posicao, adversario):
    """Devolve, para cada métrica com contexto, a média que jogadores
    daquela posição fizeram contra esse adversário, a média da liga para a
    mesma posição, e o tamanho da amostra contra esse adversário (seção 5).
    """
    contexto = {}
    for chave in prelive_config.METRICAS_COM_CONTEXTO:
        registro = indice_contexto.get((posicao, chave), {"liga": [], "por_adversario": {}})
        media_liga, _ = stats.media_e_desvio_padrao(registro["liga"])
        valores_adversario = registro["por_adversario"].get(adversario, [])
        media_adversario, _ = stats.media_e_desvio_padrao(valores_adversario)
        contexto[chave] = {
            "media_adversario": media_adversario,
            "media_liga": media_liga,
            "jogos_amostra": len(valores_adversario),
        }
    return contexto
