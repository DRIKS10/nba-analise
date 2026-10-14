"""
Única parte do sistema que "conversa" com a fonte de dados da NBA. Isola essa
complexidade do resto do código: as outras partes do sistema só recebem
dicionários Python já prontos.

HISTÓRICO DESTA FONTE DE DADOS (nota de revisão): a primeira versão deste
arquivo usava a biblioteca `nba_api`. Funcionava em testes locais, mas a NBA
bloqueia esse endpoint quando o pedido vem de servidores/nuvem — confirmado
rodando de verdade no GitHub Actions, e um problema conhecido de outros
usuários da biblioteca. A solução foi migrar para a `api-sports.io`, uma API
paga de terceiros feita para esse tipo de uso. Ver spec-sistema-nba.md para
o histórico completo da decisão.

Particularidade importante desta API: ela não permite consultar o 1º tempo
de um jogo já encerrado — só devolve o "acumulado até agora". Por isso o
1º tempo de cada jogo só existe se for capturado DURANTE o próprio intervalo,
em tempo real (ver main.py). A mesma função de busca de estatísticas
(`_estatisticas_dos_jogadores`) é usada tanto no intervalo quanto no fim do
jogo — muda só o momento em que é chamada, e a etiqueta (1T ou JOGO) que o
chamador escolhe para os dados.
"""

import os
from datetime import datetime, timedelta

import requests

from src import config


class ErroApiSports(Exception):
    pass


def _chamar_api(caminho, params=None):
    headers = {"x-apisports-key": os.environ["APISPORTS_KEY"]}
    resposta = requests.get(
        f"{config.APISPORTS_BASE_URL}/{caminho}",
        headers=headers,
        params=params or {},
        timeout=30,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    if dados.get("errors"):
        raise ErroApiSports(f"api-sports devolveu erro em {caminho}: {dados['errors']}")
    return dados


# ---------------------------------------------------------------------------
# Jogos do dia (status atual: agendado / ao vivo / intervalo / final)
# ---------------------------------------------------------------------------

def _data_utc(offset_dias=0):
    """A api-sports organiza os jogos por data em UTC (não existe parâmetro
    de fuso horário nessa API — já testamos e confirmamos isso)."""
    hoje = datetime.utcnow().date()
    return (hoje + timedelta(days=offset_dias)).isoformat()


def listar_jogos_do_dia():
    """Devolve os jogos de HOJE e de AMANHÃ em UTC — dois dias, não um só —
    porque um jogo da costa oeste dos EUA que começa à noite pode cair, em
    UTC, no dia seguinte ao do resto dos jogos da rodada.

    Cada jogo devolvido é o objeto original da api-sports (um dicionário com
    "id", "status" {"long", "short", "halftime"}, "teams" {"home", "visitors"}
    etc.) — não precisamos reformatar nada aqui, o resto do código usa os
    campos diretamente.
    """
    jogos_por_id = {}
    for offset in (0, 1):
        dados = _chamar_api("games", {"date": _data_utc(offset)})
        for jogo in dados["response"]:
            jogos_por_id[jogo["id"]] = jogo
    return list(jogos_por_id.values())


def jogo_esta_no_intervalo(jogo):
    """True se o jogo está exatamente no intervalo (fim do 2º período)."""
    return bool(jogo["status"]["halftime"])


def jogo_terminou(jogo):
    """True se o jogo já terminou. status.short == 3 é o código de 'Finished'
    (confirmado testando um jogo real até o fim)."""
    return jogo["status"]["short"] == 3


# ---------------------------------------------------------------------------
# Conversão de campos que a api-sports devolve como texto
# ---------------------------------------------------------------------------

def _para_numero(valor):
    """A api-sports devolve minutos e porcentagens como texto (ex: "15",
    "33.3"). Essa função converte para número, tratando qualquer valor que
    não seja um número válido (vazio, nulo, ou um placeholder tipo "--" para
    jogador que não entrou em quadra) como zero.
    """
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Estatísticas dos jogadores de um jogo
# ---------------------------------------------------------------------------

def _mapear_estatisticas(linha, sufixo):
    return {
        f"MIN_{sufixo}": _para_numero(linha.get("min")),
        f"PTS_{sufixo}": linha.get("points") or 0,
        f"FGA_{sufixo}": linha.get("fga") or 0,
        f"FG_PCT_{sufixo}": _para_numero(linha.get("fgp")),
        f"PA3_{sufixo}": linha.get("tpa") or 0,
        f"PM3_{sufixo}": linha.get("tpm") or 0,
        f"P3_PCT_{sufixo}": _para_numero(linha.get("tpp")),
        f"FTA_{sufixo}": linha.get("fta") or 0,
        f"REB_{sufixo}": linha.get("totReb") or 0,
        f"AST_{sufixo}": linha.get("assists") or 0,
        f"PF_{sufixo}": linha.get("pFouls") or 0,
    }


def _estatisticas_dos_jogadores(game_id, jogo, sufixo):
    """Busca as estatísticas acumuladas de todos os jogadores de um jogo,
    no momento em que a função é chamada, e devolve uma lista de
    dicionários prontos para salvar na planilha ou avaliar desvios.

    `jogo` é o objeto devolvido por listar_jogos_do_dia() para esse jogo —
    usamos os nomes dos dois times de lá para calcular o "adversário" de
    cada jogador (o endpoint de estatísticas só informa o time do próprio
    jogador, não o adversário).
    `sufixo` é "1T" (chamado durante o intervalo) ou "JOGO" (chamado depois
    que o jogo termina) — define o nome das colunas de estatística.
    """
    dados = _chamar_api("players/statistics", {"game": game_id})

    id_casa = jogo["teams"]["home"]["id"]
    nome_casa = jogo["teams"]["home"]["name"]
    nome_visitante = jogo["teams"]["visitors"]["name"]

    jogadores = []
    for linha in dados["response"]:
        time_do_jogador = linha["team"]["id"]
        if time_do_jogador == id_casa:
            nome_time, nome_adversario = nome_casa, nome_visitante
        else:
            nome_time, nome_adversario = nome_visitante, nome_casa

        jogador = {
            "id": linha["player"]["id"],
            "nome": f"{linha['player']['firstname']} {linha['player']['lastname']}",
            "time": nome_time,
            "adversario": nome_adversario,
            "posicao": linha.get("pos") or "N/D",
        }
        jogador.update(_mapear_estatisticas(linha, sufixo))
        jogadores.append(jogador)

    return jogadores


def obter_boxscore_intervalo(game_id, jogo):
    """Estatísticas acumuladas no intervalo = 1º tempo (ver seção 3.1).
    Devolve uma lista de jogadores com id/nome/time/adversario/posicao
    + colunas "_1T".
    """
    return _estatisticas_dos_jogadores(game_id, jogo, "1T")


def obter_boxscore_final(game_id, jogo):
    """Estatísticas acumuladas depois do jogo terminar = jogo completo
    (ver seção 3.2). Devolve uma lista de jogadores com
    id/nome/time/adversario/posicao + colunas "_JOGO".
    """
    return _estatisticas_dos_jogadores(game_id, jogo, "JOGO")
