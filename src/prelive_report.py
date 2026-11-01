"""
Monta o texto do relatório "PRÉ-JOGO" enviado ao Telegram (ver seção 6 do
spec-prelive-nba.md). Só formata texto — não calcula nada (isso é
prelive_stats.py).
"""

from src import prelive_config


def _formatar_data(data_iso):
    ano, mes, dia = data_iso.split("-")
    return f"{dia}/{mes}"


def _formatar_numero(valor, eh_percentual):
    if valor is None:
        return "N/D"
    if eh_percentual:
        return f"{valor:.0f}%"
    if float(valor).is_integer():
        return f"{int(valor)}"
    return f"{valor:.1f}"


def _formatar_linha_contexto(metrica_cfg, contexto_metrica, posicao, nome_adversario):
    if contexto_metrica is None or contexto_metrica["media_adversario"] is None:
        return None
    media_adv = _formatar_numero(contexto_metrica["media_adversario"], eh_percentual=False)
    media_liga = _formatar_numero(contexto_metrica["media_liga"], eh_percentual=False)
    amostra = contexto_metrica["jogos_amostra"]
    rotulo_minusculo = metrica_cfg["rotulo"].lower()
    return (
        f"  {nome_adversario} cede {media_adv} {rotulo_minusculo} por jogo a {posicao} "
        f"(liga: {media_liga}) | {amostra} jogo(s)"
    )


def _formatar_linha_metrica(metrica_cfg, resultado, contexto, posicao, nome_adversario):
    eh_percentual = metrica_cfg["base_calculo"] == "taxa"
    v1 = _formatar_numero(resultado["valor_jogo1"], eh_percentual)
    v2 = _formatar_numero(resultado["valor_jogo2"], eh_percentual)
    media = _formatar_numero(resultado["media_baseline"], eh_percentual)

    linhas = [f"- {metrica_cfg['rotulo']}: {v1} e {v2} vs. média 3-7 = {media}"]

    if metrica_cfg["tem_linha_adversario"] and contexto is not None:
        linha_contexto = _formatar_linha_contexto(
            metrica_cfg, contexto.get(metrica_cfg["chave"]), posicao, nome_adversario
        )
        if linha_contexto:
            linhas.append(linha_contexto)

    return "\n".join(linhas)


def _montar_bloco_jogador(jogador):
    resultados = jogador["resultados"]
    metricas_desviadas = [
        chave for chave in prelive_config.ORDEM_METRICAS_PRELIVE
        if resultados.get(chave, {}).get("desviou")
    ]
    if not metricas_desviadas:
        return None

    posicao = jogador["posicao"]
    nome_adversario = jogador["adversario_hoje"]
    data_jogo1 = _formatar_data(jogador["jogo1"]["Data"])
    data_jogo2 = _formatar_data(jogador["jogo2"]["Data"])

    linhas = [
        f"{jogador['nome']} ({posicao}) — hoje vs. {nome_adversario}",
        f"Jogos 1 e 2: {data_jogo1} e {data_jogo2}",
    ]
    for chave in metricas_desviadas:
        metrica_cfg = prelive_config.METRICAS_PRELIVE[chave]
        linhas.append(_formatar_linha_metrica(metrica_cfg, resultados[chave], jogador["contexto"], posicao, nome_adversario))

    return "\n".join(linhas)


def montar_relatorio_jogo(nome_visitante, nome_casa, times_para_relatorio):
    """Monta o texto completo do relatório de UM jogo.

    `times_para_relatorio` é um dicionário:
        {
            "Nome do Time": [
                {"nome":..., "posicao":..., "jogo1":..., "jogo2":...,
                 "resultados":..., "adversario_hoje":..., "contexto":...},
                ...
            ]
        }
    (ver prelive_main.processar_jogo para como esse dicionário é montado).

    Devolve None se nenhum jogador do jogo teve desvio relevante — nesse
    caso nenhuma mensagem deve ser enviada.
    """
    blocos_times = []
    for nome_time, jogadores in times_para_relatorio.items():
        blocos_jogadores = [
            bloco for jogador in jogadores
            if (bloco := _montar_bloco_jogador(jogador)) is not None
        ]
        if blocos_jogadores:
            blocos_times.append(f"[{nome_time}]\n\n" + "\n\n".join(blocos_jogadores))

    if not blocos_times:
        return None

    titulo = f"PRÉ-JOGO — {nome_visitante} x {nome_casa}"
    return titulo + "\n\n" + "\n\n".join(blocos_times)
