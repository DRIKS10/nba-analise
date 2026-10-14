"""
Leitura e escrita na planilha do Google Sheets (ver seções 8 e 9 da especificação).

A planilha tem três abas:
    - "Historico": todos os jogadores, todos os jogos, 1º tempo e jogo completo.
      É a fonte usada para calcular médias/desvio-padrão (baseline).
    - "Alertas": uma linha por jogador/jogo em que houve desvio relevante.
    - "Controle": aba técnica, só para o sistema lembrar quais jogos já
      processou em cada etapa (não faz parte da especificação original).

Este arquivo é a única parte do sistema que "conversa" com a API do Google —
o resto do código só troca dicionários Python com as funções daqui.

NOTA DE REVISÃO sobre a coluna GameID: como a api-sports não permite
consultar o 1º tempo de um jogo já encerrado (ver nba_client.py), a linha de
cada jogador/jogo é criada no intervalo (só com os dados de 1º tempo) e
completada no fim do jogo (com os dados de jogo completo) — ou criada
diretamente no fim, se o intervalo não tiver sido capturado por algum motivo.
Para localizar a linha certa nesse segundo momento, tanto a aba "Historico"
quanto a aba "Alertas" têm uma coluna "GameID".

NOTA DE REVISÃO sobre "cache": no primeiro teste real do sistema, ele estourou
a cota de leitura da API do Google Sheets, porque lia a planilha inteira de
novo para CADA jogador (até 20+ leituras repetidas por jogo). A solução foi
ler cada aba só UMA VEZ por execução, guardar o resultado em memória (o que
chamamos aqui de "cache"), e todas as funções trabalharem em cima desse
retrato da planilha. Isso explica por que várias funções recebem um "cache"
em vez de receberem a planilha diretamente.
"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound
from gspread.utils import rowcol_to_a1

from src import config

ESCOPOS_GOOGLE = [
    "https://www.googleapis.com/auth/spreadsheets",
    # Necessário porque abrir a planilha pelo NOME (cliente.open) usa a API
    # do Google Drive por baixo dos panos, para localizar o arquivo.
    "https://www.googleapis.com/auth/drive",
]

CAMPOS_IDENTIFICACAO_HISTORICO = ["GameID", "Data", "JogadorID", "Jogador", "Time", "Adversario", "Posicao"]


def _campos_estatisticas(sufixo):
    """Lista de colunas de estatística de uma etapa ("1T" ou "JOGO"), uma
    por métrica de config.METRICAS. Ex: ["PTS_1T", "FGA_1T", "MIN_1T", ...]

    Agrupar por etapa (em vez de alternar 1T/JOGO métrica a métrica) deixa as
    colunas de cada etapa lado a lado na planilha, o que permite atualizar
    todas de uma vez só (ver registrar_etapa_historico).
    """
    return [f"{chave}_{sufixo}" for chave in config.METRICAS]


CAMPOS_ESTATISTICAS_1T = _campos_estatisticas("1T")
CAMPOS_ESTATISTICAS_JOGO = _campos_estatisticas("JOGO")
CABECALHO_HISTORICO = CAMPOS_IDENTIFICACAO_HISTORICO + CAMPOS_ESTATISTICAS_1T + CAMPOS_ESTATISTICAS_JOGO


def cabecalho_alertas():
    """Monta o cabeçalho da aba Alertas, seguindo a seção 8: colunas de
    identificação + um bloco de 4 colunas por métrica + colunas extras.
    """
    colunas = ["GameID", "JogadorID", "Data", "Jogador", "Posicao", "Time", "Adversario"]
    for chave in config.ORDEM_COLUNAS_ALERTA:
        rotulo = config.METRICAS[chave]["rotulo"]
        colunas += [
            f"{rotulo} 1ºT",
            f"{rotulo} 1ºT (media)",
            f"{rotulo} Jogo",
            f"{rotulo} Jogo (media)",
        ]
    colunas += ["Faltas 1ºT", "Projecao Pontos"]
    return colunas


def conectar():
    """Abre a planilha configurada em GOOGLE_SHEET_NAME, usando a conta de
    serviço do Google descrita em GOOGLE_SERVICE_ACCOUNT_JSON.
    Cria as abas "Historico", "Alertas" e "Controle" automaticamente se
    ainda não existirem.
    """
    credenciais_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    credenciais = Credentials.from_service_account_info(credenciais_info, scopes=ESCOPOS_GOOGLE)
    cliente = gspread.authorize(credenciais)
    planilha = cliente.open(os.environ["GOOGLE_SHEET_NAME"])

    _garantir_aba(planilha, config.ABA_HISTORICO, CABECALHO_HISTORICO)
    _garantir_aba(planilha, config.ABA_ALERTAS, cabecalho_alertas())
    _garantir_aba(planilha, config.ABA_CONTROLE, ["GameID", "Etapa"])

    return planilha


def _garantir_aba(planilha, nome_aba, cabecalho):
    try:
        planilha.worksheet(nome_aba)
    except WorksheetNotFound:
        aba = planilha.add_worksheet(title=nome_aba, rows=2000, cols=len(cabecalho) + 5)
        aba.append_row(cabecalho)


def _carregar_cache(planilha, nome_aba):
    """Lê uma aba inteira UMA VEZ e guarda em memória, para o resto da
    execução não precisar ler a planilha de novo para cada jogador."""
    aba = planilha.worksheet(nome_aba)
    return {"aba": aba, "linhas": aba.get_all_values()}


def carregar_cache_historico(planilha):
    return _carregar_cache(planilha, config.ABA_HISTORICO)


def carregar_cache_alertas(planilha):
    return _carregar_cache(planilha, config.ABA_ALERTAS)


def carregar_cache_controle(planilha):
    return _carregar_cache(planilha, config.ABA_CONTROLE)


# ---------------------------------------------------------------------------
# Aba "Historico"
# ---------------------------------------------------------------------------

def obter_historico_jogador(cache_historico, jogador_id):
    """Devolve os últimos config.HISTORICO_JOGOS jogos de um jogador, como
    lista de dicionários de estatísticas, prontos para o stats.py usar.
    """
    cabecalho = cache_historico["linhas"][0]
    idx_jogador_id = cabecalho.index("JogadorID")

    registros = [
        dict(zip(cabecalho, linha))
        for linha in cache_historico["linhas"][1:]
        if linha[idx_jogador_id] == str(jogador_id)
    ]
    registros.sort(key=lambda r: r["Data"], reverse=True)
    ultimos = registros[: config.HISTORICO_JOGOS]
    return [_registro_para_estatisticas(r) for r in ultimos]


def _registro_para_estatisticas(registro):
    dados = {}
    for campo in CAMPOS_ESTATISTICAS_1T + CAMPOS_ESTATISTICAS_JOGO:
        valor = registro.get(campo)
        dados[campo] = float(valor) if valor not in (None, "") else None
    return dados


def _encontrar_linha_historico(cache_historico, game_id, jogador_id):
    """Devolve o número da linha (base 1, contando o cabeçalho) de um
    jogador/jogo na aba Historico, ou None se ainda não existir.
    """
    cabecalho = cache_historico["linhas"][0]
    idx_game_id = cabecalho.index("GameID")
    idx_jogador_id = cabecalho.index("JogadorID")
    for indice, linha in enumerate(cache_historico["linhas"][1:], start=2):
        if linha[idx_game_id] == str(game_id) and linha[idx_jogador_id] == str(jogador_id):
            return indice
    return None


def registrar_etapa_historico(cache_historico, game_id, data, jogador, etapa):
    """Registra os dados de UMA etapa ("1T" ou "JOGO") de um jogador/jogo na
    aba Historico — cria a linha se ela não existir, ou atualiza só as
    colunas dessa etapa se ela já existir (ver nota de revisão no topo do
    arquivo).

    `jogador` é um dicionário com id/nome/time/adversario/posicao + as
    colunas de estatística daquela etapa (ex: devolvido por
    nba_client.obter_boxscore_intervalo ou obter_boxscore_final).
    """
    aba = cache_historico["aba"]
    campos_etapa = CAMPOS_ESTATISTICAS_1T if etapa == "1T" else CAMPOS_ESTATISTICAS_JOGO
    valores_etapa = [jogador.get(campo, "") for campo in campos_etapa]

    linha_existente = _encontrar_linha_historico(cache_historico, game_id, jogador["id"])

    if linha_existente is None:
        identificacao = {
            "GameID": game_id,
            "Data": data,
            "JogadorID": jogador["id"],
            "Jogador": jogador["nome"],
            "Time": jogador["time"],
            "Adversario": jogador["adversario"],
            "Posicao": jogador["posicao"],
        }
        linha_completa = []
        for coluna in CABECALHO_HISTORICO:
            if coluna in identificacao:
                linha_completa.append(identificacao[coluna])
            elif coluna in campos_etapa:
                linha_completa.append(jogador.get(coluna, ""))
            else:
                linha_completa.append("")  # colunas da OUTRA etapa, ainda não capturada
        aba.append_row(linha_completa)
        cache_historico["linhas"].append([str(v) for v in linha_completa])
    else:
        idx_inicio = CABECALHO_HISTORICO.index(campos_etapa[0]) + 1
        idx_fim = CABECALHO_HISTORICO.index(campos_etapa[-1]) + 1
        intervalo = f"{rowcol_to_a1(linha_existente, idx_inicio)}:{rowcol_to_a1(linha_existente, idx_fim)}"
        aba.update(intervalo, [valores_etapa])
        for i, campo in enumerate(campos_etapa):
            idx_coluna = CABECALHO_HISTORICO.index(campo)
            cache_historico["linhas"][linha_existente - 1][idx_coluna] = str(valores_etapa[i])


# ---------------------------------------------------------------------------
# Aba "Alertas"
# ---------------------------------------------------------------------------

def registrar_alerta(planilha, dados_linha):
    """Cria uma nova linha na aba Alertas para um jogador com desvio no intervalo.

    `dados_linha` é um dicionário cujas chaves são os nomes de coluna
    devolvidos por cabecalho_alertas(). Colunas ausentes ficam em branco.

    Diferente das funções da aba Historico, esta não precisa de cache: ela
    só CRIA linhas (nunca procura uma existente), então não tem o mesmo
    problema de leituras repetidas.
    """
    aba = planilha.worksheet(config.ABA_ALERTAS)
    cabecalho = cabecalho_alertas()
    linha = [dados_linha.get(coluna, "") for coluna in cabecalho]
    aba.append_row(linha)


def atualizar_alerta_com_resultado_final(cache_alertas, game_id, jogador_id, valores_jogo_completo):
    """Localiza a linha de alerta criada no intervalo (pelo GameID +
    JogadorID — um jogo tem várias linhas, uma por jogador que desviou) e
    preenche as colunas "[Métrica] Jogo" com os valores reais do jogo
    completo, para comparar depois com a projeção (ver seção 8).

    `valores_jogo_completo` é um dicionário {rotulo_da_metrica: valor},
    ex: {"Pontos": 24, "FGA": 15}.

    Devolve True se encontrou e atualizou a linha, False se não existia
    alerta para esse jogador nesse jogo (ele não desviou no intervalo).
    """
    aba = cache_alertas["aba"]
    cabecalho = cabecalho_alertas()
    idx_game_id = cabecalho.index("GameID")
    idx_jogador_id = cabecalho.index("JogadorID")

    for indice_linha, linha in enumerate(cache_alertas["linhas"][1:], start=2):
        if linha[idx_game_id] == str(game_id) and linha[idx_jogador_id] == str(jogador_id):
            atualizacoes = []
            for rotulo, valor in valores_jogo_completo.items():
                nome_coluna = f"{rotulo} Jogo"
                if nome_coluna in cabecalho:
                    indice_coluna = cabecalho.index(nome_coluna) + 1
                    atualizacoes.append({
                        "range": rowcol_to_a1(indice_linha, indice_coluna),
                        "values": [[valor]],
                    })
            if atualizacoes:
                # Uma única chamada à API para todas as células dessa linha,
                # em vez de uma chamada por métrica.
                aba.batch_update(atualizacoes)
            return True

    return False


# ---------------------------------------------------------------------------
# Aba "Controle" (técnica — evita reprocessar o mesmo jogo)
# ---------------------------------------------------------------------------

def jogo_ja_processado(cache_controle, game_id, etapa):
    """Diz se um jogo já foi processado numa determinada etapa
    ("intervalo" ou "final"), para o main.py não repetir o trabalho (e não
    mandar notificação duplicada) quando o cron roda de novo e encontra o
    mesmo jogo ainda no mesmo status.
    """
    cabecalho = cache_controle["linhas"][0]
    idx_game_id = cabecalho.index("GameID")
    idx_etapa = cabecalho.index("Etapa")
    return any(
        linha[idx_game_id] == str(game_id) and linha[idx_etapa] == etapa
        for linha in cache_controle["linhas"][1:]
    )


def marcar_jogo_processado(cache_controle, game_id, etapa):
    """Registra que um jogo foi processado numa etapa, para não repetir."""
    cache_controle["aba"].append_row([game_id, etapa])
    cache_controle["linhas"].append([str(game_id), etapa])
