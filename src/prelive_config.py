"""
Painel de controle do modo pre-live (ver spec-prelive-nba.md).

Arquivo totalmente separado do config.py do modo halftime — nenhuma
constante daqui é compartilhada com o sistema de intervalo, para eliminar
qualquer risco de uma calibração aqui afetar o halftime (e vice-versa).
"""

# Quantos jogos válidos (10+ minutos) compõem a janela: jogo 1 e 2 (recente)
# + jogos 3 a 7 (baseline) — ver seção 4.1.
JANELA_JOGOS_VALIDOS = 7

# Minutos mínimos jogados para um jogo "contar" na janela (seção 4.1). Jogos
# com menos minutos (inclusive DNP) não ocupam lugar na janela.
MINUTOS_MINIMOS_JOGO_VALIDO = 10

# Média mínima de minutos dos jogos 1 e 2 para o jogador ser considerado —
# único filtro de rotação do sistema (seção 4.2).
FILTRO_MINUTOS_ROTACAO = 16

# Z-score mínimo para considerar o desvio relevante (seção 4.3).
LIMIAR_ZSCORE = 1.5

# Nomes das abas novas na planilha — separadas das abas "Historico"/"Alertas"/
# "Controle" do halftime, para nunca confundir um jogo processado num modo
# com o outro (ver regra 2 de spec-prelive-nba.md).
ABA_CONTROLE_PRELIVE = "ControlePreLive"
ABA_ALERTAS_PRELIVE = "AlertasPreLive"

# Corte de "dia de jogo" em horário de Brasília (seção 2). Como o pre-live
# sempre roda de manhã (bem depois das 6h), na prática o "dia de jogo" de
# hoje é sempre a data atual em Brasília — esta constante só documenta a
# regra, não é usada em nenhuma conta de data.
CORTE_DIA_DE_JOGO_HORA_BRASILIA = 6

# ---------------------------------------------------------------------------
# Métricas da Camada 1 (seção 4.4) — todas são só de ALTA.
#
#   chave               : mesmo nome usado nas colunas "<chave>_JOGO" da aba
#                          Historico (reaproveita a convenção já existente,
#                          sem alterar nada em config.py ou sheets_client.py)
#   rotulo              : nome legível, usado no relatório do Telegram
#   piso                : magnitude mínima exigida: média dos jogos 1 e 2
#                          menos a média dos jogos 3 a 7
#   base_calculo        : "bruto" (número direto) ou "taxa" (porcentagem)
#   amostra_minima      : regra de amostra mínima, quando houver — soma dos
#                          jogos 1 e 2 da métrica-base (ex: FGA para FG%)
#   tem_linha_adversario: se essa métrica ganha uma linha extra de contexto
#                          do adversário no relatório (seção 5)
# ---------------------------------------------------------------------------

METRICAS_PRELIVE = {
    "MIN": {
        "chave": "MIN", "rotulo": "Minutos", "piso": 5,
        "base_calculo": "bruto", "tem_linha_adversario": False,
    },
    "FGA": {
        "chave": "FGA", "rotulo": "FGA", "piso": 5,
        "base_calculo": "bruto", "tem_linha_adversario": False,
    },
    "PA3": {
        "chave": "PA3", "rotulo": "3PA", "piso": 3,
        "base_calculo": "bruto", "tem_linha_adversario": False,
    },
    "FTA": {
        "chave": "FTA", "rotulo": "FTA", "piso": 4,
        "base_calculo": "bruto", "tem_linha_adversario": False,
    },
    "PTS": {
        "chave": "PTS", "rotulo": "Pontos", "piso": 5,
        "base_calculo": "bruto", "tem_linha_adversario": True,
    },
    "FG_PCT": {
        "chave": "FG_PCT", "rotulo": "FG%", "piso": 8, "base_calculo": "taxa",
        "amostra_minima": {"metrica_base": "FGA", "minimo": 12},
        "tem_linha_adversario": False,
    },
    "P3_PCT": {
        "chave": "P3_PCT", "rotulo": "3P%", "piso": 12, "base_calculo": "taxa",
        "amostra_minima": {"metrica_base": "PA3", "minimo": 6},
        "tem_linha_adversario": False,
    },
    "REB": {
        "chave": "REB", "rotulo": "Rebotes", "piso": 2,
        "base_calculo": "bruto", "tem_linha_adversario": True,
    },
    "AST": {
        "chave": "AST", "rotulo": "Assistências", "piso": 2,
        "base_calculo": "bruto", "tem_linha_adversario": True,
    },
    "PM3": {
        "chave": "PM3", "rotulo": "3PM", "piso": 1,
        "base_calculo": "bruto", "tem_linha_adversario": True,
    },
}

# Ordem em que as métricas aparecem no relatório e nas colunas da aba
# AlertasPreLive (seção 4.4).
ORDEM_METRICAS_PRELIVE = ["MIN", "FGA", "PA3", "FTA", "PTS", "FG_PCT", "P3_PCT", "REB", "AST", "PM3"]

# Métricas que têm linha de contexto do adversário (seção 5): Pontos,
# Rebotes, Assistências e 3PM.
METRICAS_COM_CONTEXTO = [chave for chave, cfg in METRICAS_PRELIVE.items() if cfg["tem_linha_adversario"]]
