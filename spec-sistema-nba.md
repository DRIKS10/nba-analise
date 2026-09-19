# Especificação — Sistema de Análise de Desvios de Jogadores NBA

## 1. Objetivo

Sistema que, no intervalo (halftime) de jogos da NBA, detecta desvios estatísticos relevantes no desempenho de jogadores em relação ao seu próprio histórico recente, e reporta essas informações **objetivamente**, sem interpretação, classificação ou sugestão de aposta. O usuário usa esses dados para montar suas próprias apostas esportivas.

Princípio central: o sistema entrega **fatos**, nunca conclusões ou recomendações.

## 2. Stack técnico

- **Linguagem**: Python
- **Fonte de dados**: `nba_api` (biblioteca Python não-oficial, gratuita, usa os endpoints ao vivo e históricos oficiais da NBA)
- **Armazenamento**: Google Sheets (via API), duas planilhas/abas:
  - Base de dados histórica completa
  - Planilha de alertas/desvios
- **Notificação**: Bot do Telegram (API oficial do Telegram)
- **Hospedagem/execução**: GitHub Actions, em repositório **público** (para minutos de execução ilimitados gratuitos)
- **Agendamento**: cron fixo, rodando a cada 5-10 minutos, em uma janela ampla de horário: aproximadamente **12h às 04h30/05h** (horário de Brasília, cobrindo desde jogos de tarde de fim de semana até jogos tardios da costa oeste dos EUA, incluindo margem para prorrogação)

## 3. Fluxo geral do sistema

Duas execuções distintas, ambas disparadas pelo mesmo mecanismo de polling periódico (cron), mas com lógicas diferentes:

### 3.1 Durante o intervalo de um jogo (ativo — gera notificação)
1. Detecta que um jogo está com status "intervalo" (fim do 2º período)
2. Busca o box score parcial (1º tempo) de todos os jogadores em quadra, via `nba_api` (endpoint de box score ao vivo — os dados acumulados até o momento da consulta já representam o 1º tempo)
3. Para cada jogador, calcula os desvios (ver seção 5) comparando com o histórico
4. Se algum jogador tiver desvio relevante, monta o relatório (ver seção 6) e envia via Telegram
5. Para cada jogador/jogo com desvio, cria uma nova linha na planilha de alertas (ver seção 7)

### 3.2 Ao final de cada jogo (silencioso — não gera notificação)
1. Detecta que um jogo terminou (status "Final")
2. Busca o box score completo do jogo via `nba_api`
3. Salva os dados de **todos os jogadores** (não só os que desviaram) na base de dados histórica — isso alimenta o cálculo de baseline dos próximos jogos
4. Se aquele jogador/jogo já tinha uma linha criada na planilha de alertas (criada no intervalo), atualiza essa linha com os valores reais de jogo completo (para comparar depois com a projeção)

**Importante**: a base de dados histórica sempre recebe os dados de TODOS os jogadores, de TODOS os jogos — independentemente de terem aparecido no relatório de desvios ou não. É esse dado completo que alimenta o cálculo de médias/desvio-padrão usado nas comparações.

## 4. Baseline

- Média e desvio-padrão calculados sobre os **últimos 7 jogos** de cada jogador
- Dados de 1º tempo (para comparar com o parcial do intervalo) e de jogo completo (para comparar com a projeção e o resultado final) são mantidos separadamente
- Para jogos históricos, o `nba_api` permite consultar estatísticas separadas por metade do jogo via `BoxScoreTraditionalV3` com `range_type=0` ("by half")

## 5. Métricas rastreadas e regras de desvio relevante

Um desvio só é reportado se **dois critérios forem atendidos simultaneamente**:
1. **Z-score** (jogador vs. seu próprio histórico de 7 jogos) ≥ limiar definido
2. **Magnitude absoluta** da mudança ≥ piso mínimo definido para aquela métrica

Limiar de z-score inicial: **1.5** (ajustável depois de calibrar com dados reais)

| Métrica | Direção do desvio | Piso de magnitude | Pré-requisito de amostra | Cálculo |
|---|---|---|---|---|
| FGA | Bidirecional (↕) | ± 3 tentativas | — | Por minuto, só válido com ≥ 8 min jogados no 1ºT |
| FG% | Bidirecional (↕) | ± 10 pontos percentuais | ≥ 6 FGA no 1ºT | Taxa direta |
| 3PA | Bidirecional (↕) | ± 2 tentativas | — | Por minuto, só válido com ≥ 8 min jogados |
| Minutos (1ºT) | Bidirecional (↕) | ± ~4 minutos | — | Bruto |
| Pontos | Bidirecional (↕) | ± 4 pontos | — | Bruto |
| FTA | Só positivo (↑) | + 2 tentativas | — | Por minuto, só válido com ≥ 8 min jogados |
| 3P% | Só positivo (↑) | + 15 pontos percentuais | ≥ 3 3PA no 1ºT | Taxa direta |
| Rebotes | Só positivo (↑) | + 3 rebotes | — | Bruto |
| Assistências | Só positivo (↑) | + 3 assistências | — | Bruto |
| 3PM | Só positivo (↑) | + 2 conversões | — | Bruto |
| Faltas cometidas | Só positivo (↑) | Gatilho a partir de 3 faltas (número bruto, sem z-score) | — | Bruto |

**Fora do sistema** (decidido explicitamente excluir): FT%, USG Rate, Faltas sofridas, Turnovers.

**Regra de amostra mínima para taxas por minuto**: métricas de volume (FGA, 3PA, FTA) só têm seu z-score/desvio considerado válido se o jogador tiver jogado ≥ 8 minutos no 1º tempo. Abaixo disso, a taxa por minuto é considerada estatisticamente não confiável (amostra pequena demais).

O sistema **não classifica automaticamente** o tipo de anomalia (ex: "volume real" vs. "eficiência pontual") — apenas lista os z-scores/desvios individuais que passaram no filtro. A interpretação fica a cargo do usuário.

## 6. Projeção de pontos

Calculada apenas quando pelo menos uma das seguintes métricas apresentar desvio relevante: **Pontos, FGA, FG%, 3PA, 3PM ou Minutos**. Caso contrário, a projeção é omitida do relatório.

**Fórmula**:

```
Minutos projetados = Minutos reais do 1º tempo (hoje) + Média histórica de minutos no 2º tempo (últimos 7 jogos)

FGA por minuto (hoje) = FGA do 1ºT ÷ Minutos do 1ºT (requer ≥ 8 min jogados)

Pontos por tentativa (hoje) = Pontos do 1ºT ÷ FGA do 1ºT (requer ≥ 6 FGA)

Pontos projetados = Minutos projetados × (FGA por minuto hoje) × (Pontos por tentativa hoje)
```

## 7. Formato do relatório (Telegram)

- Enviado apenas durante o intervalo (nunca no fim de jogo)
- Agrupado por time; cada jogador aparece como um bloco/mensagem separada
- Projeção de pontos destacada no topo do bloco do jogador (quando aplicável)
- Cada métrica com desvio relevante aparece em uma linha própria, no formato:

```
[Métrica]: [valor hoje, 1ºT] vs. média [X] (1ºT) | média jogo completo: [Y]
```

- Métricas sem desvio relevante **não aparecem** na lista daquele jogador
- Nenhum número de z-score é exibido — apenas valores absolutos e comparações diretas

**Exemplo**:

```
[Time A]

Jogador X — Projeção: 32 pontos
- Pontos: 19 (1ºT) vs. média 13 (1ºT) | média jogo completo: 24
- FGA: 12 (1ºT) vs. média 8 (1ºT) | média jogo completo: 15
- Minutos: 19 (1ºT) vs. média 14 (1ºT) | média jogo completo: 28

Jogador Z
- Rebotes: 7 (1ºT) vs. média 3 (1ºT) | média jogo completo: 6

[Time B]

Jogador Y — Projeção: 17 pontos
- Minutos: 19 (1ºT) vs. média 14 (1ºT) | média jogo completo: 28
```

## 8. Estrutura da planilha de alertas (Google Sheets)

- Uma linha por jogador por jogo em que houve desvio (não registra jogos sem desvio)
- Um mesmo jogador pode ter múltiplas linhas (uma por jogo diferente em que desviou)

**Colunas de identificação, nesta ordem**:
`Data | Jogador | Posição (1-5) | Time | Adversário`

**Bloco de 4 colunas por métrica** (repetido para: Pontos, FGA, FG%, 3PA, 3PM, Minutos, Rebotes, Assistências, FTA), preenchido **apenas** para as métricas que desviaram naquela linha (demais ficam em branco):

`[Métrica] 1ºT | [Métrica] 1ºT (média) | [Métrica] Jogo (valor real, preenchido após o fim do jogo) | [Métrica] Jogo (média)`

**Colunas extras**:
`Faltas 1ºT` (bruto, sem comparação) | `Projeção Pontos`

A coluna "[Métrica] Jogo" (valor real) é preenchida em um segundo momento, quando o jogo termina — a linha já existe (criada no intervalo) e é **atualizada**, não duplicada. Serve para depois comparar a Projeção de Pontos com o resultado real.

## 9. Base de dados histórica (Google Sheets, aba/planilha separada)

- Registra estatísticas completas de **todo jogador em toda partida**, tanto separadas por 1º tempo quanto por jogo completo
- Alimentada ao final de cada jogo (ver seção 3.2)
- É a fonte usada para calcular médias e desvios-padrão (baseline de 7 jogos) usados em todas as comparações do sistema
- Volume estimado: ~32.000 linhas por temporada completa (1.230 jogos × ~26 jogadores por jogo) — bem dentro do limite de 20 milhões de células do Google Sheets

## 10. Notas de implementação

- Repositório GitHub **público** — minutos de execução do GitHub Actions ilimitados gratuitamente nesse modo. Credenciais sensíveis (token do bot Telegram, credenciais da API do Google Sheets) devem ser armazenadas via **GitHub Secrets**, nunca escritas diretamente no código.
- O usuário não tem experiência prévia em programação — priorizar código legível, bem comentado, e explicações claras a cada etapa.
- Primeira versão prioriza simplicidade sobre otimização (ex: cron em janela fixa ampla, em vez de agendamento dinâmico por jogo).
