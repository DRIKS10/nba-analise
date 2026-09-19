"""
Leitura e escrita na planilha do Google Sheets (ver seções 8 e 9 da especificação).

A planilha tem duas abas:
    - "Historico": todos os jogadores, todos os jogos, 1º tempo e jogo completo.
      É a fonte usada para calcular médias/desvio-padrão (baseline).
    - "Alertas": uma linha por jogador/jogo em que houve desvio relevante.

Este arquivo é a única parte do sistema que "conversa" com a API do Google —
o resto do código só troca dicionários Python com as funções daqui.
"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

from src import config

ESCOPOS_GOOGLE = ["https://www.googleapis.com/auth/spreadsheets"]

CAMPOS_IDENTIFICACAO_HISTORICO = ["Data", "JogadorID", "Jogador", "Time", "Adversario", "Posicao"]


def _campos_estatisticas():
    """Lista de colunas de estatísticas da aba Historico: uma para 1ºT e
    outra para jogo completo, para cada métrica de config.METRICAS.
    Ex: ["PTS_1T", "PTS_JOGO", "MIN_1T", "MIN_JOGO", ...]
    """
    campos = []
    for chave in config.METRICAS:
        campos.append(f"{chave}_1T")
        campos.append(f"{chave}_JOGO")
    return campos


CABECALHO_HISTORICO = CAMPOS_IDENTIFICACAO_HISTORICO + _campos_estatisticas()


def cabecalho_alertas():
    """Monta o cabeçalho da aba Alertas, seguindo a seção 8: colunas de
    identificação + um bloco de 4 colunas por métrica + colunas extras.
    """
    colunas = ["Data", "Jogador", "Posicao", "Time", "Adversario"]
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
    Cria as abas "Historico" e "Alertas" automaticamente se ainda não existirem.
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


def obter_historico_jogador(planilha, jogador_id):
    """Devolve os últimos config.HISTORICO_JOGOS jogos de um jogador (mais
    recente primeiro é irrelevante aqui — devolvemos como lista de dicionários
    de estatísticas, prontos para o stats.py usar).
    """
    aba = planilha.worksheet(config.ABA_HISTORICO)
    registros = aba.get_all_records()
    jogos_jogador = [r for r in registros if str(r.get("JogadorID")) == str(jogador_id)]
    jogos_jogador.sort(key=lambda r: r["Data"], reverse=True)
    ultimos = jogos_jogador[: config.HISTORICO_JOGOS]
    return [_registro_para_estatisticas(r) for r in ultimos]


def _registro_para_estatisticas(registro):
    dados = {}
    for campo in _campos_estatisticas():
        valor = registro.get(campo)
        dados[campo] = float(valor) if valor not in (None, "") else None
    return dados


def salvar_jogo_completo(planilha, jogador_id, jogador_nome, time, adversario, data, posicao, estatisticas):
    """Adiciona uma linha na aba Historico com os dados completos de um
    jogador em um jogo (1º tempo + jogo completo). Chamado ao final de cada
    jogo, para TODOS os jogadores (ver seção 3.2).

    `estatisticas` é um dicionário com as chaves de _campos_estatisticas()
    (ex: {"PTS_1T": 10, "PTS_JOGO": 22, ...}).
    """
    aba = planilha.worksheet(config.ABA_HISTORICO)
    linha = [data, jogador_id, jogador_nome, time, adversario, posicao]
    linha += [estatisticas.get(campo, "") for campo in _campos_estatisticas()]
    aba.append_row(linha)


def registrar_alerta(planilha, dados_linha):
    """Cria uma nova linha na aba Alertas para um jogador com desvio no intervalo.

    `dados_linha` é um dicionário cujas chaves são os nomes de coluna
    devolvidos por cabecalho_alertas(). Colunas ausentes ficam em branco.
    """
    aba = planilha.worksheet(config.ABA_ALERTAS)
    cabecalho = cabecalho_alertas()
    linha = [dados_linha.get(coluna, "") for coluna in cabecalho]
    aba.append_row(linha)


def atualizar_alerta_com_resultado_final(planilha, data, jogador, time, valores_jogo_completo):
    """Localiza a linha de alerta criada no intervalo (mesma Data + Jogador +
    Time) e preenche as colunas "[Métrica] Jogo" com os valores reais do jogo
    completo, para comparar depois com a projeção (ver seção 8).

    `valores_jogo_completo` é um dicionário {rotulo_da_metrica: valor},
    ex: {"Pontos": 24, "FGA": 15}.

    Devolve True se encontrou e atualizou a linha, False se não existia
    alerta para esse jogador nesse jogo (ele não desviou no intervalo).
    """
    aba = planilha.worksheet(config.ABA_ALERTAS)
    cabecalho = cabecalho_alertas()
    valores = aba.get_all_values()

    for indice_linha, linha in enumerate(valores[1:], start=2):  # linha 1 = cabeçalho
        if linha[0] == data and linha[1] == jogador and linha[3] == time:
            for rotulo, valor in valores_jogo_completo.items():
                nome_coluna = f"{rotulo} Jogo"
                if nome_coluna in cabecalho:
                    indice_coluna = cabecalho.index(nome_coluna) + 1
                    aba.update_cell(indice_linha, indice_coluna, valor)
            return True

    return False


def jogo_ja_processado(planilha, game_id, etapa):
    """Diz se um jogo já foi processado numa determinada etapa
    ("intervalo" ou "final"), para o main.py não repetir o trabalho (e não
    mandar notificação duplicada) quando o cron roda de novo e encontra o
    mesmo jogo ainda no mesmo status.
    """
    aba = planilha.worksheet(config.ABA_CONTROLE)
    registros = aba.get_all_records()
    return any(
        str(r.get("GameID")) == str(game_id) and r.get("Etapa") == etapa
        for r in registros
    )


def marcar_jogo_processado(planilha, game_id, etapa):
    """Registra que um jogo foi processado numa etapa, para não repetir."""
    aba = planilha.worksheet(config.ABA_CONTROLE)
    aba.append_row([game_id, etapa])
