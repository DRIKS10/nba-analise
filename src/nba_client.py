"""
Única parte do sistema que "conversa" com a nba_api (biblioteca não-oficial
que acessa dados da NBA). Isola essa complexidade do resto do código: as
outras partes do sistema só recebem dicionários Python já prontos.

AVISO IMPORTANTE sobre range_type: a especificação original deste projeto
dizia para usar `range_type=0` para buscar dados "por metade" do jogo.
Testei isso contra um jogo real e descobri que está incorreto:
`range_type=0` sempre devolve o JOGO COMPLETO, ignorando start_period/end_period.
O que realmente funciona para pegar só o 1º tempo é `range_type=1` (modo
"por período") somando os períodos 1 e 2. Os valores usados abaixo foram
conferidos manualmente contra a API real da NBA antes de este arquivo ser
escrito — mas como é uma API não-oficial, ela pode mudar de comportamento no
futuro sem aviso. Se um dia os números vierem estranhos, esta função é o
primeiro lugar a conferir.
"""

import re

from nba_api.live.nba.endpoints import boxscore as live_boxscore
from nba_api.live.nba.endpoints import scoreboard as live_scoreboard
from nba_api.stats.endpoints import boxscoretraditionalv3


# ---------------------------------------------------------------------------
# Jogos do dia (status ao vivo)
# ---------------------------------------------------------------------------

def listar_jogos_do_dia():
    """Devolve a lista de jogos da NBA de hoje, cada um com seu status atual
    (agendado / ao vivo / intervalo / final)."""
    return live_scoreboard.ScoreBoard().games.get_dict()


def jogo_esta_no_intervalo(jogo):
    """True se o jogo está exatamente no intervalo (fim do 2º período)."""
    return jogo["gameStatusText"].strip().lower() == "halftime"


def jogo_terminou(jogo):
    """True se o jogo já terminou (status 'Final')."""
    return jogo["gameStatus"] == 3


def nome_time(dados_time):
    return f"{dados_time['teamCity']} {dados_time['teamName']}".strip()


# ---------------------------------------------------------------------------
# Conversão de formatos de minutos
# ---------------------------------------------------------------------------

def _minutos_iso8601_para_decimal(valor_iso):
    """Converte "PT25M01.00S" (formato do box score AO VIVO) em minutos
    decimais, ex: 25.02.
    """
    if not valor_iso:
        return 0.0
    match = re.match(r"PT(\d+)M([\d.]+)S", valor_iso)
    if not match:
        return 0.0
    minutos, segundos = match.groups()
    return int(minutos) + float(segundos) / 60


def _minutos_mm_ss_para_decimal(valor_str):
    """Converte "34:12" (formato dos box scores HISTÓRICOS) em minutos
    decimais, ex: 34.2.
    """
    if not valor_str or ":" not in valor_str:
        return 0.0
    minutos, segundos = valor_str.split(":")
    return int(minutos) + int(segundos) / 60


# ---------------------------------------------------------------------------
# Box score AO VIVO (usado no intervalo — seção 3.1)
# ---------------------------------------------------------------------------

def _estatisticas_jogador_ao_vivo(jogador):
    s = jogador["statistics"]
    return {
        "id": jogador["personId"],
        "nome": jogador["name"],
        "posicao": jogador.get("position") or "N/D",
        "MIN_1T": _minutos_iso8601_para_decimal(s["minutes"]),
        "PTS_1T": s["points"],
        "FGA_1T": s["fieldGoalsAttempted"],
        "FG_PCT_1T": s["fieldGoalsPercentage"] * 100,
        "PA3_1T": s["threePointersAttempted"],
        "PM3_1T": s["threePointersMade"],
        "P3_PCT_1T": s["threePointersPercentage"] * 100,
        "FTA_1T": s["freeThrowsAttempted"],
        "REB_1T": s["reboundsTotal"],
        "AST_1T": s["assists"],
        "PF_1T": s["foulsPersonal"],
    }


def obter_boxscore_intervalo(game_id):
    """Busca o box score ao vivo de um jogo que está no intervalo.

    Como as estatísticas ao vivo são cumulativas e o jogo está pausado entre
    o 2º e o 3º período, o que a NBA reporta nesse momento já É o total do
    1º tempo (ver seção 3.1 da especificação) — não precisa de nenhum cálculo
    extra.

    Devolve um dicionário:
        {
            "time_casa": "Boston Celtics",
            "time_visitante": "Orlando Magic",
            "jogadores_casa": [ {...}, ... ],
            "jogadores_visitante": [ {...}, ... ],
        }
    """
    game = live_boxscore.BoxScore(game_id).game.get_dict()

    jogadores_casa = [
        _estatisticas_jogador_ao_vivo(j)
        for j in game["homeTeam"]["players"]
        if j.get("played") == "1"
    ]
    jogadores_visitante = [
        _estatisticas_jogador_ao_vivo(j)
        for j in game["awayTeam"]["players"]
        if j.get("played") == "1"
    ]

    return {
        "time_casa": nome_time(game["homeTeam"]),
        "time_visitante": nome_time(game["awayTeam"]),
        "jogadores_casa": jogadores_casa,
        "jogadores_visitante": jogadores_visitante,
    }


# ---------------------------------------------------------------------------
# Box score HISTÓRICO (jogo já encerrado — seção 3.2 e 4)
# ---------------------------------------------------------------------------

def _stats_por_periodo(game_id, start_period, end_period, range_type):
    dados = boxscoretraditionalv3.BoxScoreTraditionalV3(
        game_id=game_id,
        start_period=start_period,
        end_period=end_period,
        start_range=0,
        end_range=0,
        range_type=range_type,
    ).player_stats.get_dict()
    return [dict(zip(dados["headers"], linha)) for linha in dados["data"]]


def _mapear_estatisticas(linha, sufixo):
    return {
        f"MIN_{sufixo}": _minutos_mm_ss_para_decimal(linha["minutes"]),
        f"PTS_{sufixo}": linha["points"],
        f"FGA_{sufixo}": linha["fieldGoalsAttempted"],
        f"FG_PCT_{sufixo}": linha["fieldGoalsPercentage"] * 100,
        f"PA3_{sufixo}": linha["threePointersAttempted"],
        f"PM3_{sufixo}": linha["threePointersMade"],
        f"P3_PCT_{sufixo}": linha["threePointersPercentage"] * 100,
        f"FTA_{sufixo}": linha["freeThrowsAttempted"],
        f"REB_{sufixo}": linha["reboundsTotal"],
        f"AST_{sufixo}": linha["assists"],
        f"PF_{sufixo}": linha["foulsPersonal"],
    }


def obter_boxscore_final_por_jogador(game_id):
    """Busca o box score de um jogo já encerrado, separado em 1º tempo e
    jogo completo, para TODOS os jogadores que jogaram (ver seção 3.2).

    Devolve uma lista de dicionários, um por jogador, cada um com:
        id, nome, time, adversario, posicao,
        + as colunas "_1T" e "_JOGO" de cada métrica (PTS_1T, PTS_JOGO, ...)
    """
    # range_type=1 (por período), períodos 1 e 2 juntos = 1º tempo
    primeiro_tempo = _stats_por_periodo(game_id, start_period=1, end_period=2, range_type=1)
    # range_type=0 devolve sempre o jogo completo (inclui prorrogação)
    jogo_completo = _stats_por_periodo(game_id, start_period=0, end_period=0, range_type=0)

    jogo_completo_por_id = {linha["personId"]: linha for linha in jogo_completo}
    nomes_time_por_id = {linha["teamId"]: f"{linha['teamCity']} {linha['teamName']}" for linha in jogo_completo}
    ids_dos_times = list(nomes_time_por_id.keys())

    jogadores = []
    for linha_1t in primeiro_tempo:
        pid = linha_1t["personId"]
        linha_jogo = jogo_completo_por_id.get(pid)
        if linha_jogo is None:
            continue  # não deveria acontecer, mas evita quebrar o sistema

        time_id = linha_1t["teamId"]
        outro_time_id = next((t for t in ids_dos_times if t != time_id), None)

        jogador = {
            "id": pid,
            "nome": f"{linha_1t['firstName']} {linha_1t['familyName']}",
            "time": nomes_time_por_id.get(time_id, "N/D"),
            "adversario": nomes_time_por_id.get(outro_time_id, "N/D"),
            "posicao": linha_1t.get("position") or "N/D",
        }
        jogador.update(_mapear_estatisticas(linha_1t, "1T"))
        jogador.update(_mapear_estatisticas(linha_jogo, "JOGO"))
        jogadores.append(jogador)

    return jogadores
