"""
Busca os jogos do "dia de jogo" que ainda não começaram, para o modo
pre-live (ver seção 2 do spec-prelive-nba.md).

Reaproveita a função interna de chamada HTTP da api-sports já usada pelo
halftime (`nba_client._chamar_api`) — mesma autenticação, mesma tratativa de
erro — sem alterar nenhuma linha de nba_client.py.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.nba_client import _chamar_api

FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")


def _dia_de_jogo_brasilia():
    """O pre-live roda uma vez por dia, sempre de manhã (seção 2), bem depois
    do corte das 6h definido na especificação — então o "dia de jogo" de
    hoje é simplesmente a data atual no fuso de Brasília.
    """
    return datetime.now(FUSO_BRASILIA).date()


def listar_jogos_nao_iniciados():
    """Devolve os jogos ainda não iniciados ("Scheduled") do dia de jogo de
    hoje, em horário de Brasília.

    A api-sports organiza os jogos por data em UTC (ver nba_client.py), e
    Brasília está 3h atrás de UTC. Um jogo marcado para a noite em Brasília
    pode cair no dia seguinte em UTC — por isso consultamos a data de hoje
    em Brasília E a de amanhã (em UTC), para não perder nenhum jogo da noite.

    Cada jogo devolvido é o objeto original da api-sports, igual ao que
    nba_client.listar_jogos_do_dia() já devolve.
    """
    dia_brasilia = _dia_de_jogo_brasilia()
    jogos_por_id = {}
    for offset in (0, 1):
        data_utc = (dia_brasilia + timedelta(days=offset)).isoformat()
        dados = _chamar_api("games", {"date": data_utc})
        for jogo in dados["response"]:
            jogos_por_id[jogo["id"]] = jogo

    return [jogo for jogo in jogos_por_id.values() if jogo["status"]["long"] == "Scheduled"]
