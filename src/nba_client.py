"""
Única parte do sistema que "conversa" com a nba_api (biblioteca não-oficial
que acessa dados da NBA). Isola essa complexidade do resto do código: as
outras partes do sistema só recebem dicionários Python já prontos.

AVISO IMPORTANTE (histórico de uma correção real feita neste projeto): a
versão original deste arquivo usava o endpoint "ao vivo" da NBA
(nba_api.live, que fala com cdn.nba.com). Ao testar rodando no GitHub
Actions, esse endpoint devolveu "Access Denied" (bloqueio a pedidos vindos
de servidores/nuvem — algo comum em provedores de CI/CD). A solução foi usar
só os endpoints de `nba_api.stats` (stats.nba.com), que não têm esse
bloqueio: o mesmo endpoint de box score usado para jogos históricos também
funciona para um jogo AINDA EM ANDAMENTO — basta pedir só os períodos 1 e 2
(1º tempo), mesmo que o jogo ainda não tenha terminado.

Como é uma API não-oficial, ela pode mudar de comportamento no futuro sem
aviso. Se um dia os números vierem estranhos (ou o bloqueio voltar de outra
forma), este arquivo é o primeiro lugar a conferir.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from nba_api.stats.endpoints import boxscoretraditionalv3, scoreboardv3


# ---------------------------------------------------------------------------
# Jogos do dia (status atual: agendado / ao vivo / intervalo / final)
# ---------------------------------------------------------------------------

def _data_nba(offset_dias=0):
    """A NBA organiza os jogos por data do horário dos EUA (não Brasília).
    `offset_dias=1` devolve o dia anterior."""
    hoje_et = datetime.now(ZoneInfo("America/New_York")).date()
    return (hoje_et - timedelta(days=offset_dias)).isoformat()


def listar_jogos_do_dia():
    """Devolve os jogos de HOJE e de ONTEM (horário dos EUA) — dois dias,
    não um só — porque um jogo da costa oeste que começa à noite nos EUA
    pode continuar "ao vivo" ou terminar já depois da meia-noite no horário
    de Brasília, quando por aqui já viramos o dia.

    Cada jogo é um dicionário simples com pelo menos: gameId, gameStatus
    (1=agendado, 2=ao vivo, 3=final) e gameStatusText (ex: "Halftime", "Final").
    """
    jogos_por_id = {}
    for offset in (0, 1):
        cabecalho = scoreboardv3.ScoreboardV3(
            game_date=_data_nba(offset), league_id="00"
        ).game_header.get_dict()
        for linha in cabecalho["data"]:
            jogo = dict(zip(cabecalho["headers"], linha))
            jogos_por_id[jogo["gameId"]] = jogo  # evita duplicar se aparecer nos dois dias
    return list(jogos_por_id.values())


def jogo_esta_no_intervalo(jogo):
    """True se o jogo está exatamente no intervalo (fim do 2º período)."""
    return jogo["gameStatusText"].strip().lower() == "halftime"


def jogo_terminou(jogo):
    """True se o jogo já terminou (status 'Final')."""
    return jogo["gameStatus"] == 3


# ---------------------------------------------------------------------------
# Conversão do formato de minutos usado pelos box scores (stats.nba.com)
# ---------------------------------------------------------------------------

def _minutos_para_decimal(valor_str):
    """Converte "34:12" em minutos decimais, ex: 34.2."""
    if not valor_str or ":" not in valor_str:
        return 0.0
    minutos, segundos = valor_str.split(":")
    return int(minutos) + int(segundos) / 60


# ---------------------------------------------------------------------------
# Box score por período (usado tanto no intervalo quanto no jogo encerrado)
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
        f"MIN_{sufixo}": _minutos_para_decimal(linha["minutes"]),
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


def _nomes_dos_times(linhas):
    """Mapa {teamId: "Cidade Nome"} a partir de qualquer lista de linhas de
    box score (elas já trazem teamCity/teamName repetidos em cada linha)."""
    return {linha["teamId"]: f"{linha['teamCity']} {linha['teamName']}" for linha in linhas}


def obter_boxscore_intervalo(game_id):
    """Busca o placar parcial (1º tempo) de um jogo que está no intervalo,
    pedindo só os períodos 1 e 2 do box score — o jogo ainda não terminou,
    então não existe "jogo completo" ainda (ver seção 3.1 da especificação).

    Devolve uma lista de dicionários, um por jogador, cada um com:
        id, nome, time, adversario, posicao, + as colunas "_1T"
    """
    linhas = _stats_por_periodo(game_id, start_period=1, end_period=2, range_type=1)
    nomes_time_por_id = _nomes_dos_times(linhas)
    ids_dos_times = list(nomes_time_por_id.keys())

    jogadores = []
    for linha in linhas:
        time_id = linha["teamId"]
        outro_time_id = next((t for t in ids_dos_times if t != time_id), None)
        jogador = {
            "id": linha["personId"],
            "nome": f"{linha['firstName']} {linha['familyName']}",
            "time": nomes_time_por_id.get(time_id, "N/D"),
            "adversario": nomes_time_por_id.get(outro_time_id, "N/D"),
            "posicao": linha.get("position") or "N/D",
        }
        jogador.update(_mapear_estatisticas(linha, "1T"))
        jogadores.append(jogador)

    return jogadores


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
    nomes_time_por_id = _nomes_dos_times(jogo_completo)
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
