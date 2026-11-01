"""
Acesso ao Google Sheets do modo pre-live (ver spec-prelive-nba.md).

Regra de proteção (seção 0 do spec-prelive-nba.md): este arquivo só LÊ a aba
"Historico" do halftime — nunca escreve, atualiza ou reorganiza nada nela.
As únicas escritas daqui são nas abas próprias "ControlePreLive" e
"AlertasPreLive".

Reaproveita, sem alterar, várias peças já existentes em sheets_client.py:
`_garantir_aba`, `_carregar_cache`, `_garantir_espaco`, `_salvar_cache` e
`_registro_para_estatisticas` (que já trata os valores "--" e os números com
vírgula decimal — mesma lição aplicada aqui, sem duplicar a correção).
"""

from datetime import datetime

from src import prelive_config, sheets_client


def cabecalho_alertas_prelive():
    """Monta o cabeçalho da aba AlertasPreLive: colunas de identificação +
    um bloco de 4 colunas por métrica (seção 4.4). A coluna "Resultado Real"
    fica reservada para uma etapa futura (ainda não implementada — ver nota
    de revisão em prelive_main.py) que compare o alerta com o desempenho real
    do jogador no jogo do dia.
    """
    colunas = ["GameID", "JogadorID", "Data", "Jogador", "Posicao", "Time", "Adversario"]
    for chave in prelive_config.ORDEM_METRICAS_PRELIVE:
        rotulo = prelive_config.METRICAS_PRELIVE[chave]["rotulo"]
        colunas += [
            f"{rotulo} Jogo1",
            f"{rotulo} Jogo2",
            f"{rotulo} Media 3-7",
            f"{rotulo} Resultado Real",
        ]
    return colunas


def garantir_abas_prelive(planilha):
    """Cria as abas "ControlePreLive" e "AlertasPreLive" se ainda não
    existirem. Reaproveita sheets_client._garantir_aba (mesma função que já
    cria Historico/Alertas/Controle) sem alterar nada nela.
    """
    sheets_client._garantir_aba(planilha, prelive_config.ABA_CONTROLE_PRELIVE, ["GameID", "Data", "Status", "Enviado em"])
    sheets_client._garantir_aba(planilha, prelive_config.ABA_ALERTAS_PRELIVE, cabecalho_alertas_prelive())


def carregar_cache_controle_prelive(planilha):
    return sheets_client._carregar_cache(planilha, prelive_config.ABA_CONTROLE_PRELIVE)


def carregar_cache_alertas_prelive(planilha):
    return sheets_client._carregar_cache(planilha, prelive_config.ABA_ALERTAS_PRELIVE)


# ---------------------------------------------------------------------------
# Leitura da aba "Historico" (só leitura — ver regra 2 do spec-prelive-nba.md)
# ---------------------------------------------------------------------------

def obter_jogos_validos_jogador(cache_historico, jogador_id):
    """Devolve até prelive_config.JANELA_JOGOS_VALIDOS jogos mais recentes do
    jogador em que ele atuou >= prelive_config.MINUTOS_MINIMOS_JOGO_VALIDO
    minutos no jogo completo (ver seção 4.1). Jogos com menos minutos
    (inclusive DNP) são pulados e não ocupam lugar na janela.

    O jogo 0 da lista devolvida é o mais recente (jogo 1 da spec), o último é
    o mais antigo (jogo 7 da spec).
    """
    cabecalho = cache_historico["linhas"][0]
    idx_jogador_id = cabecalho.index("JogadorID")

    registros = [
        dict(zip(cabecalho, linha))
        for linha in cache_historico["linhas"][1:]
        if linha[idx_jogador_id] == str(jogador_id)
    ]
    registros.sort(key=lambda r: r["Data"], reverse=True)

    jogos_validos = []
    for registro in registros:
        estatisticas = sheets_client._registro_para_estatisticas(registro)
        minutos_jogo = estatisticas.get("MIN_JOGO")
        if minutos_jogo is None or minutos_jogo < prelive_config.MINUTOS_MINIMOS_JOGO_VALIDO:
            continue
        estatisticas["Data"] = registro["Data"]
        estatisticas["Posicao"] = registro["Posicao"]
        jogos_validos.append(estatisticas)
        if len(jogos_validos) == prelive_config.JANELA_JOGOS_VALIDOS:
            break

    return jogos_validos


def jogadores_recentes_por_time(cache_historico):
    """Agrupa, a partir do histórico, qual é o time mais recente de cada
    jogador — a api-sports não lista o elenco de um jogo antes dele começar
    (só a partir do momento em que existe estatística registrada), então
    usamos a base histórica para saber quem joga em cada time hoje.

    Limitação conhecida (documentada aqui em vez de escondida): um jogador
    recém-trocado continua aparecendo no time antigo até ter uma estatística
    completa registrada com o time novo.

    Devolve um dicionário {"Nome do Time": [{"id":..., "nome":...}, ...]}.
    """
    cabecalho = cache_historico["linhas"][0]
    idx_jogador_id = cabecalho.index("JogadorID")
    idx_nome = cabecalho.index("Jogador")
    idx_time = cabecalho.index("Time")
    idx_data = cabecalho.index("Data")

    mais_recente_por_jogador = {}
    for linha in cache_historico["linhas"][1:]:
        jogador_id = linha[idx_jogador_id]
        data = linha[idx_data]
        atual = mais_recente_por_jogador.get(jogador_id)
        if atual is None or data > atual["Data"]:
            mais_recente_por_jogador[jogador_id] = {
                "id": jogador_id,
                "nome": linha[idx_nome],
                "time": linha[idx_time],
                "Data": data,
            }

    por_time = {}
    for info in mais_recente_por_jogador.values():
        por_time.setdefault(info["time"], []).append({"id": info["id"], "nome": info["nome"]})
    return por_time


# ---------------------------------------------------------------------------
# Aba "AlertasPreLive"
# ---------------------------------------------------------------------------

def _numero_limpo(valor):
    """Os valores do histórico voltam sempre como float (ex: 22.0), mesmo
    quando a métrica é naturalmente um número inteiro (pontos, minutos,
    rebotes...). Isso deixaria a aba cheia de ".0" desnecessários — esta
    função arredonda para número inteiro quando possível, e para 1 casa
    decimal quando não (ex: percentuais).
    """
    if valor is None:
        return ""
    if float(valor).is_integer():
        return int(valor)
    return round(valor, 1)


def registrar_alerta_prelive(cache_alertas, game_id, data, jogador_info, posicao, nome_time, nome_adversario, resultados):
    """Prepara uma nova linha na aba AlertasPreLive — não escreve na hora, só
    anota no cache (ver salvar_cache_alertas_prelive), igual ao padrão já
    usado no halftime.
    """
    linha_dados = {
        "GameID": game_id,
        "JogadorID": jogador_info["id"],
        "Data": data,
        "Jogador": jogador_info["nome"],
        "Posicao": posicao,
        "Time": nome_time,
        "Adversario": nome_adversario,
    }

    for chave in prelive_config.ORDEM_METRICAS_PRELIVE:
        resultado = resultados[chave]
        if not resultado["desviou"]:
            continue  # métricas sem desvio ficam em branco, igual à aba Alertas do halftime
        rotulo = prelive_config.METRICAS_PRELIVE[chave]["rotulo"]
        linha_dados[f"{rotulo} Jogo1"] = _numero_limpo(resultado["valor_jogo1"])
        linha_dados[f"{rotulo} Jogo2"] = _numero_limpo(resultado["valor_jogo2"])
        linha_dados[f"{rotulo} Media 3-7"] = _numero_limpo(resultado["media_baseline"])

    cabecalho = cabecalho_alertas_prelive()
    linha = [linha_dados.get(coluna, "") for coluna in cabecalho]
    cache_alertas["novas_linhas"].append(linha)
    cache_alertas["linhas"].append([str(v) for v in linha])


def salvar_cache_alertas_prelive(cache_alertas):
    sheets_client._salvar_cache(cache_alertas)


# ---------------------------------------------------------------------------
# Aba "ControlePreLive" (técnica — evita reprocessar o mesmo jogo no mesmo dia)
# ---------------------------------------------------------------------------

def jogo_ja_processado_prelive(cache_controle, game_id):
    cabecalho = cache_controle["linhas"][0]
    idx_game_id = cabecalho.index("GameID")
    return any(linha[idx_game_id] == str(game_id) for linha in cache_controle["linhas"][1:])


def marcar_jogo_processado_prelive(cache_controle, game_id, data, status):
    """Registra que um jogo foi processado hoje no pre-live, com o status
    ("ENVIADO" ou "SEM_ALERTA") e o horário em que isso aconteceu.

    Escreve na hora (sem cache de escrita), igual à aba Controle do
    halftime: o volume aqui é no máximo 1 linha por jogo por dia, bem abaixo
    de qualquer cota, e escrever na hora preserva a garantia de que um jogo
    processado com sucesso não será reprocessado mesmo se outro jogo, mais
    adiante na mesma execução, falhar.
    """
    linha = [game_id, data, status, datetime.now().strftime("%Y-%m-%d %H:%M")]
    aba = cache_controle["aba"]
    sheets_client._garantir_espaco(aba, len(cache_controle["linhas"]) + 1)
    aba.append_row(linha)
    cache_controle["linhas"].append([str(v) for v in linha])
