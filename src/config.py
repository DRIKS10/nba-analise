"""
Painel de controle do sistema.

Todo número "ajustável" (limiares, pisos, quantidade de jogos de histórico etc.)
fica neste arquivo. Se um dia você quiser calibrar o sistema com dados reais
(por exemplo, mudar o limiar de z-score de 1.5 para 1.8), é aqui que se mexe —
não é preciso tocar na lógica de cálculo em outros arquivos.
"""

# Quantos jogos recentes usamos para calcular a média e o desvio-padrão (baseline)
HISTORICO_JOGOS = 7

# Z-score mínimo para um desvio ser considerado relevante
LIMIAR_ZSCORE = 1.5

# Minutos mínimos jogados no 1º tempo para confiarmos em métricas "por minuto"
# (FGA, 3PA, FTA). Abaixo disso, a amostra é considerada pequena demais.
MINUTOS_MINIMOS_TAXA = 8

# Nomes das abas dentro da planilha do Google Sheets
ABA_HISTORICO = "Historico"
ABA_ALERTAS = "Alertas"

# Aba técnica (não faz parte da especificação original) usada só para o
# sistema lembrar quais jogos já processou em cada etapa, e não mandar
# notificações repetidas ou duplicar linhas quando o cron roda de novo
# enquanto o mesmo jogo ainda está "no intervalo" ou "Final".
ABA_CONTROLE = "Controle"

# ---------------------------------------------------------------------------
# Definição de cada métrica rastreada (ver secão 5 da especificação).
#
# Campos de cada métrica:
#   chave         : nome interno usado no código e nas colunas da planilha
#   rotulo        : nome legível, usado no relatório do Telegram
#   direcao       : "ambos" (desvio pra cima OU pra baixo conta) ou "cima" (só conta se aumentou)
#   piso          : magnitude mínima da mudança para o desvio ser relevante
#   base_calculo  : como o valor é calculado
#       - "bruto"      -> usa o número direto (ex: pontos, rebotes)
#       - "por_minuto" -> normaliza pelo minuto jogado (ex: FGA, 3PA, FTA)
#       - "taxa"       -> é uma porcentagem/taxa já pronta (ex: FG%, 3P%)
#   amostra_minima: regra de amostra mínima para a métrica ser considerada válida
#       - para "por_minuto": minutos mínimos jogados (usa MINUTOS_MINIMOS_TAXA)
#       - para "taxa": quantas tentativas da métrica-base são exigidas
#   usa_zscore    : se False, o gatilho é só um valor bruto mínimo (caso das faltas)
# ---------------------------------------------------------------------------

METRICAS = {
    "PTS": {
        "chave": "PTS",
        "rotulo": "Pontos",
        "direcao": "ambos",
        "piso": 4,
        "base_calculo": "bruto",
        "usa_zscore": True,
    },
    "FGA": {
        "chave": "FGA",
        "rotulo": "FGA",
        "direcao": "ambos",
        "piso": 3,
        "base_calculo": "por_minuto",
        "usa_zscore": True,
    },
    "FG_PCT": {
        "chave": "FG_PCT",
        "rotulo": "FG%",
        "direcao": "ambos",
        "piso": 10,
        "base_calculo": "taxa",
        "amostra_minima": {"metrica_base": "FGA", "minimo": 6},
        "usa_zscore": True,
    },
    "PA3": {
        "chave": "PA3",
        "rotulo": "3PA",
        "direcao": "ambos",
        "piso": 2,
        "base_calculo": "por_minuto",
        "usa_zscore": True,
    },
    "MIN": {
        "chave": "MIN",
        "rotulo": "Minutos",
        "direcao": "ambos",
        "piso": 4,
        "base_calculo": "bruto",
        "usa_zscore": True,
    },
    "FTA": {
        "chave": "FTA",
        "rotulo": "FTA",
        "direcao": "cima",
        "piso": 2,
        "base_calculo": "por_minuto",
        "usa_zscore": True,
    },
    "P3_PCT": {
        "chave": "P3_PCT",
        "rotulo": "3P%",
        "direcao": "cima",
        "piso": 15,
        "base_calculo": "taxa",
        "amostra_minima": {"metrica_base": "PA3", "minimo": 3},
        "usa_zscore": True,
    },
    "REB": {
        "chave": "REB",
        "rotulo": "Rebotes",
        "direcao": "cima",
        "piso": 3,
        "base_calculo": "bruto",
        "usa_zscore": True,
    },
    "AST": {
        "chave": "AST",
        "rotulo": "Assistências",
        "direcao": "cima",
        "piso": 3,
        "base_calculo": "bruto",
        "usa_zscore": True,
    },
    "PM3": {
        "chave": "PM3",
        "rotulo": "3PM",
        "direcao": "cima",
        "piso": 2,
        "base_calculo": "bruto",
        "usa_zscore": True,
    },
    "PF": {
        "chave": "PF",
        "rotulo": "Faltas cometidas",
        "direcao": "cima",
        "piso": 3,
        "base_calculo": "bruto",
        "usa_zscore": False,  # gatilho é só o valor bruto (>= 3 faltas), sem z-score
    },
}

# Métricas que, se desviarem, disparam o cálculo da projeção de pontos (seção 6)
METRICAS_GATILHO_PROJECAO = {"PTS", "FGA", "FG_PCT", "PA3", "PM3", "MIN"}

# Ordem em que os blocos de métricas aparecem nas colunas da planilha de alertas
ORDEM_COLUNAS_ALERTA = ["PTS", "FGA", "FG_PCT", "PA3", "PM3", "MIN", "REB", "AST", "FTA"]

# ---------------------------------------------------------------------------
# Projeção de pontos (ver seção 6 da especificação)
# ---------------------------------------------------------------------------

# FGA mínimo no 1ºT para confiarmos em "pontos por tentativa" na projeção
PROJECAO_FGA_MINIMO = 6
