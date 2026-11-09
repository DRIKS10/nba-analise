# Especificação — Sistema de Análise de Desvios de Jogadores NBA

> **Nota de revisão**: esta especificação foi atualizada depois de uma tentativa real de implementação. A fonte de dados original (`nba_api`) funcionava nos testes locais, mas a NBA bloqueia esse endpoint quando o pedido vem de servidores/nuvem (confirmado rodando no GitHub Actions) — um bloqueio documentado e conhecido de outros usuários da biblioteca, não específico deste projeto. As seções 2, 3, 4, 9 e 10 foram revisadas para refletir a solução adotada: usar a API paga `api-sports.io` como fonte de dados, e construir o próprio histórico de 1º tempo em vez de depender de um provedor externo para esse dado.

## 1. Objetivo

Sistema que, no intervalo (halftime) de jogos da NBA, detecta desvios estatísticos relevantes no desempenho de jogadores em relação ao seu próprio histórico recente, e reporta essas informações **objetivamente**, sem interpretação, classificação ou sugestão de aposta. O usuário usa esses dados para montar suas próprias apostas esportivas.

Princípio central: o sistema entrega **fatos**, nunca conclusões ou recomendações.

## 2. Stack técnico

- **Linguagem**: Python
- **Fonte de dados**: `api-sports.io` (API paga de terceiros para dados da NBA). Substituiu a `nba_api` original — ver nota de revisão no topo deste documento. Requer plano pago (o plano grátis limita consulta a jogos de poucos dias atrás e não tem cota suficiente para o polling contínuo do cron)
- **Armazenamento**: Google Sheets (via API), duas planilhas/abas:
  - Base de dados histórica completa
  - Planilha de alertas/desvios
- **Notificação**: Bot do Telegram (API oficial do Telegram)
- **Hospedagem/execução**: GitHub Actions, em repositório **público** (para minutos de execução ilimitados gratuitos)
- **Agendamento**: cron fixo, rodando a cada 5 minutos, em uma janela ampla de horário: aproximadamente **12h às 04h30/05h** (horário de Brasília, cobrindo desde jogos de tarde de fim de semana até jogos tardios da costa oeste dos EUA, incluindo margem para prorrogação). O disparo real não vem do agendamento nativo do GitHub Actions — ver nota de revisão na seção 10 sobre por quê.

## 3. Fluxo geral do sistema

Duas execuções distintas, ambas disparadas pelo mesmo mecanismo de polling periódico (cron), mas com lógicas diferentes:

### 3.1 Durante o intervalo de um jogo (ativo — gera notificação)
1. Detecta que um jogo está com status "intervalo" (fim do 2º período)
2. Busca o box score parcial (1º tempo) de todos os jogadores em quadra, via `api-sports.io` (os dados acumulados até o momento da consulta já representam o 1º tempo)
3. Para cada jogador, calcula os desvios (ver seção 5) comparando com o histórico — só considera o jogador para efeito de alerta se ele já tiver o mínimo de jogos completos exigido (ver seção 4)
4. Se algum jogador tiver desvio relevante, monta o relatório (ver seção 6) e envia via Telegram
5. Para cada jogador/jogo com desvio, cria uma nova linha na planilha de alertas (ver seção 7)
6. **Também salva o 1º tempo de TODOS os jogadores do jogo** (não só os que desviaram) na base de dados histórica — ver nota abaixo sobre por que isso mudou

### 3.2 Ao final de cada jogo (silencioso — não gera notificação)
1. Detecta que um jogo terminou (status "Final")
2. Busca o box score completo do jogo via `api-sports.io`
3. Para cada jogador: se já existe a linha da base de dados histórica criada no intervalo (passo 3.1.6), **atualiza** essa linha completando-a com os valores de jogo completo. Se essa linha **não existir** (por exemplo, o intervalo daquele jogo não foi capturado por algum motivo), **cria a linha agora**, preenchendo só os dados de jogo completo — as colunas de 1º tempo ficam em branco para esse jogo específico. Isso garante que o histórico de jogo completo nunca dependa de o intervalo ter sido capturado com sucesso (ver nota abaixo)
4. Se aquele jogador/jogo já tinha uma linha criada na planilha de alertas (criada no intervalo), atualiza essa linha com os valores reais de jogo completo (para comparar depois com a projeção)

**Importante**: a base de dados histórica sempre recebe os dados de TODOS os jogadores, de TODOS os jogos — independentemente de terem aparecido no relatório de desvios ou não. É esse dado completo que alimenta o cálculo de médias/desvio-padrão usado nas comparações.

**Por que o histórico agora é construído em duas etapas (nota de revisão)**: a `nba_api` original permitia consultar o 1º tempo de um jogo **já encerrado** diretamente (o histórico "vinha pronto"). A `api-sports.io` não oferece essa consulta — só entrega o acumulado até o momento em que é consultada. Por isso o 1º tempo de cada jogo só existe se for capturado **durante** o próprio intervalo daquele jogo, em tempo real; depois que o jogo termina, esse dado não pode mais ser recuperado de forma retroativa. Consequência prática: o histórico de 1º tempo é construído pelo próprio sistema, jogo a jogo, a partir do momento em que o monitoramento começa a rodar — não existe atalho para "importar" o histórico de jogos anteriores a essa data.

**Por que o passo 3.2 pode criar a linha, e não só atualizar (nota de revisão)**: diferente do 1º tempo, os dados de **jogo completo** continuam disponíveis a qualquer momento depois do jogo terminar — não dependem de captura em tempo real. Fazer o passo 3.2 depender inteiramente de uma linha já existir (criada no intervalo) tornaria o histórico de jogo completo refém do momento mais frágil do sistema tecnicamente (o polling do intervalo, que é uma janela curta e pode falhar por qualquer instabilidade pontual). Por isso o passo 3.2 sempre garante o registro do jogo completo, com ou sem o 1º tempo daquele jogo específico.

## 4. Baseline

- Média e desvio-padrão calculados sobre os **últimos 7 jogos** de cada jogador
- Dados de 1º tempo (para comparar com o parcial do intervalo) e de jogo completo (para comparar com a projeção e o resultado final) são mantidos separadamente
- O histórico de 1º tempo é construído pelo próprio sistema a partir do momento em que o monitoramento começa a rodar (ver seção 3.1) — não é importado de nenhuma fonte externa
- **Amostra mínima antes de alertar**: um jogador só entra na análise de desvios (seção 5) depois de ter **7 jogos completos** registrados no histórico (número configurável no código). Antes disso, o sistema apenas acumula dados em silêncio, sem gerar alertas para esse jogador — isso evita alertas com base em pouquíssima amostra
- **Jogos de pré-temporada contam para o histórico**, inclusive para atingir os 7 jogos mínimos — foi uma escolha deliberada para servir também como teste do funcionamento do sistema antes da temporada regular começar

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

**Coluna extra de identificação (nota de revisão)**: a planilha também ganha uma coluna `GameID`, preenchida junto com a linha no intervalo. É o que o sistema usa para localizar a linha certa na hora de atualizar as colunas "[Métrica] Jogo" ao final do jogo — o mesmo motivo pelo qual a base de dados histórica (seção 9) tem essa coluna.

## 9. Base de dados histórica (Google Sheets, aba/planilha separada)

- Registra estatísticas completas de **todo jogador em toda partida**, tanto separadas por 1º tempo quanto por jogo completo
- Em condições normais, a linha de cada jogador/jogo é criada **durante o intervalo** (com os dados de 1º tempo) e **atualizada ao final do jogo** (completada com os dados de jogo completo) — ver seção 3.1 e 3.2. Isso exige uma coluna extra de identificação (`GameID`) para o sistema localizar a linha certa na hora de atualizar
- Se a linha não existir ainda quando o jogo terminar (o intervalo não foi capturado), o passo 3.2 cria a linha nesse momento, só com os dados de jogo completo — o histórico de jogo completo nunca fica incompleto por causa disso (ver nota na seção 3.2)
- É a fonte usada para calcular médias e desvios-padrão (baseline de 7 jogos) usados em todas as comparações do sistema
- Volume estimado: ~32.000 linhas por temporada completa (1.230 jogos × ~26 jogadores por jogo) — bem dentro do limite de 20 milhões de células do Google Sheets
- **Expansão automática (nota de revisão)**: o Google Sheets não cria linhas sozinho quando um programa escreve além do tamanho atual da planilha (só a interface faz isso, quando uma pessoa digita manualmente além do fim). A aba já chegou perto desse limite na prática, então o sistema agora verifica o espaço disponível antes de cada escrita e expande a planilha sozinho quando necessário, sem precisar de intervenção manual.

## 10. Notas de implementação

- Repositório GitHub **público** — minutos de execução do GitHub Actions ilimitados gratuitamente nesse modo. Credenciais sensíveis (token do bot Telegram, credenciais da API do Google Sheets, chave da `api-sports.io`) devem ser armazenadas via **GitHub Secrets**, nunca escritas diretamente no código.
- O usuário não tem experiência prévia em programação — priorizar código legível, bem comentado, e explicações claras a cada etapa.
- Primeira versão prioriza simplicidade sobre otimização (ex: cron em janela fixa ampla, em vez de agendamento dinâmico por jogo).
- **Histórico da migração de fonte de dados**: a primeira versão implementada usava `nba_api`. Funcionava em testes locais, mas ao rodar de verdade no GitHub Actions, o endpoint de dados ao vivo da NBA (`cdn.nba.com`) recusava a conexão ("Access Denied"), e mesmo o endpoint de estatísticas históricas (`stats.nba.com`) travava em timeout — ambos bloqueios da NBA contra pedidos vindos de servidores/nuvem, um problema documentado por outros usuários da biblioteca (não específico deste projeto ou do GitHub especificamente). A alternativa adotada foi migrar para a `api-sports.io`, uma API comercial voltada a esse tipo de uso.
- O plano gratuito da `api-sports.io` foi usado só para validar o funcionamento (endpoints existem, campos batem com o esperado, etc.) antes de contratar o plano pago necessário para o uso contínuo do cron.
- **O agendamento nativo do GitHub Actions não é confiável (nota de revisão)**: o próprio GitHub documenta que o disparo por `schedule` é "melhor esforço" — em horários de pico da plataforma, execuções podem atrasar bastante (minutos a horas) ou até não rodar, principalmente para agendamentos frequentes como o nosso (a cada 5 minutos). Isso foi confirmado na prática: o cron chegou a ficar mais de 40 minutos sem rodar, o que é tempo suficiente para perder o intervalo inteiro de um jogo. A solução adotada foi usar um serviço externo gratuito (`cron-job.org`) para, a cada 5 minutos, chamar diretamente a API do GitHub e disparar o workflow (`workflow_dispatch`) — isso contorna o agendador interno do GitHub, que não é confiável para esse tipo de uso. O agendamento nativo continua configurado no workflow como reforço, caso o serviço externo fique fora do ar.
- **Jogos de exibição não são cobertos pela api-sports (nota de revisão)**: eventos como o "NBA Canada Game" (jogos de pré-temporada fora do circuito normal) não aparecem na api-sports, nem na busca por data nem como jogo "ao vivo" — nem mesmo durante o próprio jogo. Como não são jogos oficiais de temporada, isso não compromete o histórico, mas é bom saber que esse tipo de jogo nunca vai gerar alerta nem entrar na base de dados.
- **Instabilidade nos dados ao vivo da api-sports (nota de revisão)**: mesmo no plano pago, já aconteceu de um jogo específico "travar" com um status desatualizado por várias horas (por exemplo, continuar marcado como "em andamento, 2º quarto" muito depois do jogo já ter terminado de verdade), enquanto outros jogos da mesma noite funcionavam normalmente. Na maioria dos casos observados, o jogo se corrige sozinho depois de um tempo (às vezes só no dia seguinte). Por causa disso, o sistema consulta não só hoje e amanhã, mas também **ontem** (em UTC), para dar uma chance de capturar essa correção tardia antes de desistir do jogo. Quando o status nunca chega a indicar "intervalo" de verdade, o 1º tempo daquele jogo específico se perde — isso é uma limitação da fonte de dados, sem solução conhecida no momento.
- **Armazenamento do Google cheio bloqueia a planilha (nota de revisão)**: ao contrário do que se poderia supor, Planilhas Google **contam** para a cota de armazenamento da conta (Gmail + Drive + Fotos somados), desde uma mudança de política do Google em 2021. Se a conta dona da planilha ficar sem espaço, a edição para de funcionar — inclusive por programas, inclusive em planilhas pequenas — até liberar espaço ou comprar mais armazenamento. Isso já causou um erro real de "sem permissão" no sistema.
- **Bugs reais já encontrados e corrigidos durante o uso**, registrados aqui para referência futura:
  - A api-sports às vezes devolve `"--"` no campo de minutos (jogador que não entrou em quadra) em vez de vazio ou zero — o código agora trata qualquer valor não numérico como zero.
  - O Google Sheets devolve números com vírgula decimal (ex: `"62,5"`) em vez de ponto, quando a configuração regional da planilha é em português — o código agora aceita os dois formatos ao ler de volta o histórico.
  - O sistema estourou a cota de **leitura** da API do Google Sheets por ler a planilha inteira de novo para cada jogador — corrigido lendo cada aba uma única vez por execução.
  - Depois, estourou a cota de **escrita** pelo motivo simétrico (uma chamada à API por jogador) — corrigido acumulando as mudanças em memória e enviando tudo de uma vez ao final de cada jogo processado.
  - A ordem original do código enviava a notificação do Telegram **antes** de salvar os dados na planilha — uma falha real no envio (token com quebra de linha a mais, colado sem querer no GitHub Secrets) fez o sistema perder o jogo inteiro daquela vez. Corrigido invertendo a ordem (salva primeiro, notifica depois) e isolando erros por jogo, para um jogo com problema não impedir os outros jogos da mesma execução de serem processados.
  - A coluna "Data" da base histórica usava `date.today()` — a data de **quando o código rodava** (em UTC), não a data real do jogo. Isso só dava errado quando a captura do intervalo era perdida (ex: por uma falha de rede passageira na conexão com o Google) e a linha só era criada no fim do jogo: se isso acontecesse perto da virada do dia em UTC, a linha ficava com a data errada (um dia a mais) e, por consequência, sem o 1º tempo. Corrigido usando `date.start` do próprio jogo (devolvido pela api-sports), que é estável e correto não importa quando o jogo foi processado de verdade.
  - **Falhas de rede passageiras na conexão com o Google** (ex: `Error 502` do próprio Google, `Connection reset by peer`) já aconteceram em produção, sempre bem no início da execução (`sheets_client.conectar()`). Como isso acontece antes do laço que processa jogo por jogo, a execução inteira é perdida — o cron tenta de novo 5 minutos depois, mas ainda não há uma nova tentativa automática dentro da mesma execução (melhoria avaliada, ainda não implementada).
  - **Perda real de linhas do histórico por duas execuções rodando ao mesmo tempo**: a função que expande a planilha (`_garantir_espaco`/`add_rows` do `gspread`) lê o tamanho atual da aba e manda ao Google "defina o tamanho como X" — não é uma operação de "incrementar" atômica. Como o halftime tem dois gatilhos ativos (`cron-job.org` + o agendamento nativo do GitHub como reforço), duas execuções concorrentes já aconteceram de verdade: cada uma leu o mesmo tamanho "antigo" da aba Historico, e a que terminou por último encolheu a planilha de volta, apagando sem erro nenhum as linhas que a outra tinha acabado de escrever. Sintoma observado: jogos marcados como processados na aba Controle (essa escrita não sofre desse problema), mas totalmente ausentes da aba Historico. Corrigido adicionando `concurrency` ao `monitor.yml` (mesma proteção que o `prelive.yml` já tinha desde o início), impedindo que uma nova execução comece enquanto outra ainda está rodando.
  - **Jogo marcado como processado mesmo sem gravar nada (bug real, provavelmente a causa mais comum de 1º tempo perdido)**: a api-sports às vezes demora alguns segundos para disponibilizar o boxscore (`players/statistics`) depois do status do jogo já mostrar "intervalo" — nesse caso a lista de jogadores vem **vazia**. O código marcava o jogo como processado mesmo assim (o laço `for jogador in jogadores` simplesmente não executava nada, mas `marcar_jogo_processado` rodava de qualquer jeito, incondicionalmente), fazendo o cron desistir daquele jogo pra sempre, mesmo que a tentativa seguinte (5 minutos depois, ainda dentro do intervalo) fosse encontrar os dados certinhos. Corrigido em `processar_intervalo` e `processar_final`: se a lista de jogadores vier vazia, a função simplesmente retorna sem marcar nada, deixando o cron tentar de novo na próxima execução.
  - **A correção da concorrência, na primeira versão, criou um problema novo e pior**: `concurrency` sozinho (sem `queue: max`) só permite **uma** execução esperando na fila por vez — se uma nova tentativa chegasse enquanto já tinha outra esperando, a mais antiga era **cancelada** (nunca rodava), mesmo com `cancel-in-progress: false` (que só protege a execução que já está RODANDO, não as que estão na fila — confirmado na documentação oficial do GitHub). Como os dois gatilhos disparam a cada 5 minutos, isso cancelava execuções com frequência bem maior do que o problema original, piorando bastante a perda do 1º tempo e o atraso (às vezes de dias) na gravação do jogo completo — inclusive causando jogos mais recentes serem gravados antes de jogos mais antigos, na ordem em que as execuções sobreviventes aconteceram de rodar. Corrigido adicionando `queue: max` à configuração de `concurrency`, que permite várias execuções esperarem na fila (em vez de se cancelarem), mantendo a garantia de nunca rodar duas ao mesmo tempo.
