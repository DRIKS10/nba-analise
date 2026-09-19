"""
Monta o texto do relatório enviado ao Telegram (ver seção 7 da especificação).

Espera receber os dados já calculados (por stats.py e projection.py) — este
arquivo só cuida de formatação de texto, não faz nenhuma conta.
"""

from src import config

# Ordem em que as métricas aparecem no relatório de cada jogador
ORDEM_METRICAS_RELATORIO = list(config.ORDEM_COLUNAS_ALERTA) + ["PF"]


def _formatar_numero(valor, eh_percentual):
    if valor is None:
        return "N/D"
    if eh_percentual:
        return f"{valor:.0f}%"
    if float(valor).is_integer():
        return f"{int(valor)}"
    return f"{valor:.1f}"


def _formatar_linha_metrica(metrica_cfg, resultado):
    eh_percentual = metrica_cfg["base_calculo"] == "taxa"

    # Faltas cometidas: sem comparação com média (ver seção 8)
    if not metrica_cfg["usa_zscore"]:
        valor = _formatar_numero(resultado["valor_1T"], eh_percentual=False)
        return f"- {metrica_cfg['rotulo']}: {valor} (1ºT)"

    valor = _formatar_numero(resultado["valor_1T"], eh_percentual)
    media_1t = _formatar_numero(resultado["media_1T"], eh_percentual)
    media_jogo = _formatar_numero(resultado["media_jogo"], eh_percentual)
    return (
        f"- {metrica_cfg['rotulo']}: {valor} (1ºT) vs. média {media_1t} (1ºT) "
        f"| média jogo completo: {media_jogo}"
    )


def _montar_bloco_jogador(jogador):
    """Devolve o texto do bloco de um jogador, ou None se ele não teve
    nenhuma métrica com desvio relevante (nesse caso ele não aparece no relatório).
    """
    resultados = jogador["resultados"]
    metricas_desviadas = [
        chave for chave in ORDEM_METRICAS_RELATORIO
        if resultados.get(chave, {}).get("desviou")
    ]
    if not metricas_desviadas:
        return None

    cabecalho = jogador["nome"]
    projecao = jogador.get("projecao")
    if projecao is not None:
        cabecalho += f" — Projeção: {round(projecao)} pontos"

    linhas = [cabecalho]
    for chave in metricas_desviadas:
        metrica_cfg = config.METRICAS[chave]
        linhas.append(_formatar_linha_metrica(metrica_cfg, resultados[chave]))

    return "\n".join(linhas)


def montar_relatorio(times):
    """Monta o texto completo do relatório.

    `times` é um dicionário no formato:
        {
            "Nome do Time": [
                {"nome": "Jogador X", "resultados": {...}, "projecao": 32.4},
                {"nome": "Jogador Z", "resultados": {...}, "projecao": None},
            ],
            ...
        }
    onde "resultados" é o dicionário devolvido por stats.avaliar_jogador.

    Devolve None se nenhum jogador de nenhum time teve desvio (isto é,
    não deve ser enviada notificação nenhuma).
    """
    blocos_times = []
    for nome_time, jogadores in times.items():
        blocos_jogadores = [
            bloco for jogador in jogadores
            if (bloco := _montar_bloco_jogador(jogador)) is not None
        ]
        if blocos_jogadores:
            blocos_times.append(f"[{nome_time}]\n\n" + "\n\n".join(blocos_jogadores))

    if not blocos_times:
        return None

    return "\n\n".join(blocos_times)
