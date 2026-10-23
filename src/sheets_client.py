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

NOTA DE REVISÃO sobre "cache" (leitura): no primeiro teste real do sistema,
ele estourou a cota de LEITURA da API do Google Sheets, porque lia a
planilha inteira de novo para CADA jogador (até 20+ leituras repetidas por
jogo). A solução foi ler cada aba só UMA VEZ por execução, guardar o
resultado em memória ("cache"), e todas as funções trabalharem em cima
desse retrato da planilha.

NOTA DE REVISÃO sobre escrita em lote: depois, em um dia com vários jogos
terminando ao mesmo tempo, o sistema estourou a cota de ESCRITA pelo motivo
simétrico: uma chamada à API por jogador (até 20+ por jogo). A solução foi
parecida — as funções de Historico e Alertas não escrevem mais na hora;
elas só anotam o que precisa ser escrito dentro do próprio "cache", e as
funções salvar_cache_historico()/salvar_cache_alertas() mandam tudo de uma
vez pro Google, em no máximo 2 chamadas por aba (uma para linhas novas,
outra para atualizações), não importa quantos jogadores tenham sido
processados. Por isso main.py chama essas duas funções ao final de cada
jogo processado.
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
    execução não precisar ler a planilha de novo para cada jogador.

    `novas_linhas` e `atualizacoes` começam vazias — são preenchidas pelas
    funções de escrita (ex: registrar_etapa_historico) e só viram chamadas
    de verdade à API quando salvar_cache_historico()/salvar_cache_alertas()
    forem chamadas.
    """
    aba = planilha.worksheet(nome_aba)
    return {
        "aba": aba,
        "linhas": aba.get_all_values(),
        "novas_linhas": [],
        "atualizacoes": [],
    }


def carregar_cache_historico(planilha):
    return _carregar_cache(planilha, config.ABA_HISTORICO)


def carregar_cache_alertas(planilha):
    return _carregar_cache(planilha, config.ABA_ALERTAS)


def carregar_cache_controle(planilha):
    return _carregar_cache(planilha, config.ABA_CONTROLE)


def _salvar_cache(cache):
    """Envia as mudanças acumuladas num cache para a planilha de verdade,
    em no máximo 2 chamadas à API: uma pra criar todas as linhas novas de
    uma vez (append_rows), outra pra aplicar todas as atualizações de
    células de uma vez (batch_update)."""
    aba = cache["aba"]
    if cache["novas_linhas"]:
        aba.append_rows(cache["novas_linhas"])
        cache["novas_linhas"] = []
    if cache["atualizacoes"]:
        aba.batch_update(cache["atualizacoes"])
        cache["atualizacoes"] = []


def salvar_cache_historico(cache_historico):
    _salvar_cache(cache_historico)


def salvar_cache_alertas(cache_alertas):
    _salvar_cache(cache_alertas)


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
        if valor in (None, ""):
            dados[campo] = None
        else:
            # A planilha pode devolver números com vírgula decimal (ex: "62,5")
            # se a configuração regional do Google Sheets for em português.
            dados[campo] = float(str(valor).replace(",", "."))
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
    """Prepara os dados de UMA etapa ("1T" ou "JOGO") de um jogador/jogo na
    aba Historico — cria a linha se ela não existir, ou atualiza só as
    colunas dessa etapa se ela já existir (ver nota de revisão no topo do
    arquivo).

    Não escreve na planilha na hora — só anota a mudança no cache. É preciso
    chamar salvar_cache_historico() depois de processar todos os jogadores
    para a mudança realmente chegar ao Google Sheets.

    `jogador` é um dicionário com id/nome/time/adversario/posicao + as
    colunas de estatística daquela etapa (ex: devolvido por
    nba_client.obter_boxscore_intervalo ou obter_boxscore_final).
    """
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
        cache_historico["novas_linhas"].append(linha_completa)
        cache_historico["linhas"].append([str(v) for v in linha_completa])
    else:
        idx_inicio = CABECALHO_HISTORICO.index(campos_etapa[0]) + 1
        idx_fim = CABECALHO_HISTORICO.index(campos_etapa[-1]) + 1
        intervalo = f"{rowcol_to_a1(linha_existente, idx_inicio)}:{rowcol_to_a1(linha_existente, idx_fim)}"
        cache_historico["atualizacoes"].append({"range": intervalo, "values": [valores_etapa]})
        for i, campo in enumerate(campos_etapa):
            idx_coluna = CABECALHO_HISTORICO.index(campo)
            cache_historico["linhas"][linha_existente - 1][idx_coluna] = str(valores_etapa[i])


# ---------------------------------------------------------------------------
# Aba "Alertas"
# ---------------------------------------------------------------------------

def registrar_alerta(cache_alertas, dados_linha):
    """Prepara uma nova linha na aba Alertas para um jogador com desvio no
    intervalo — não escreve na hora, só anota no cache (ver
    salvar_cache_alertas).

    `dados_linha` é um dicionário cujas chaves são os nomes de coluna
    devolvidos por cabecalho_alertas(). Colunas ausentes ficam em branco.
    """
    cabecalho = cabecalho_alertas()
    linha = [dados_linha.get(coluna, "") for coluna in cabecalho]
    cache_alertas["novas_linhas"].append(linha)
    cache_alertas["linhas"].append([str(v) for v in linha])


def atualizar_alerta_com_resultado_final(cache_alertas, game_id, jogador_id, valores_jogo_completo):
    """Localiza a linha de alerta criada no intervalo (pelo GameID +
    JogadorID — um jogo tem várias linhas, uma por jogador que desviou) e
    prepara o preenchimento das colunas "[Métrica] Jogo" com os valores
    reais do jogo completo, para comparar depois com a projeção (ver
    seção 8). Não escreve na hora — ver salvar_cache_alertas.

    `valores_jogo_completo` é um dicionário {rotulo_da_metrica: valor},
    ex: {"Pontos": 24, "FGA": 15}.

    Devolve True se encontrou a linha, False se não existia alerta para
    esse jogador nesse jogo (ele não desviou no intervalo).
    """
    cabecalho = cabecalho_alertas()
    idx_game_id = cabecalho.index("GameID")
    idx_jogador_id = cabecalho.index("JogadorID")

    for indice_linha, linha in enumerate(cache_alertas["linhas"][1:], start=2):
        if linha[idx_game_id] == str(game_id) and linha[idx_jogador_id] == str(jogador_id):
            for rotulo, valor in valores_jogo_completo.items():
                nome_coluna = f"{rotulo} Jogo"
                if nome_coluna in cabecalho:
                    indice_coluna = cabecalho.index(nome_coluna) + 1
                    cache_alertas["atualizacoes"].append({
                        "range": rowcol_to_a1(indice_linha, indice_coluna),
                        "values": [[valor]],
                    })
            return True

    return False


# ---------------------------------------------------------------------------
# Aba "Controle" (técnica — evita reprocessar o mesmo jogo)
# ---------------------------------------------------------------------------
#
# Diferente de Historico/Alertas, esta aba continua escrevendo na hora (sem
# cache de escrita): o volume aqui é 1 linha por JOGO (não por jogador), bem
# abaixo do limite de escrita, e escrever na hora preserva a garantia de que
# um jogo processado com sucesso não será reprocessado mesmo se outro jogo,
# mais adiante na mesma execução, falhar.

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
