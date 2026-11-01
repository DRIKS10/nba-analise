# Especificação COMPLEMENTAR — Modo Pre-Live

> **Este documento é um COMPLEMENTO de `spec-sistema-nba.md`.** Ele descreve um segundo modo de operação (pre-live) que funciona ao lado do modo halftime já implementado. Leia primeiro `spec-sistema-nba.md`: o stack, a fonte de dados, o Google Sheets, o Telegram e os Secrets são os mesmos.

## 0. Regras de proteção do sistema atual (LEIA ANTES DE QUALQUER ALTERAÇÃO)

O modo halftime já está em produção e passou por vários bugs reais (ver seção 10 da spec principal). Para não quebrar nada:

1. **Não alterar o comportamento do halftime.** O workflow atual, o disparo pelo `cron-job.org`, a lógica de intervalo, a gravação da base histórica e a planilha de alertas de intervalo continuam exatamente como estão.
2. **O pre-live só LÊ a base histórica.** Ele não grava, não altera e não reorganiza nenhuma aba existente. A única escrita nova é na aba de controle do pre-live (seção 3) e, se for decidido na seção 9, numa aba nova de alertas do pre-live.
3. **Código novo em arquivos e workflow separados.** Funções compartilhadas (acesso ao Sheets, Telegram, API-Sports) podem ser reaproveitadas, mas, se for preciso alterar alguma delas, **avise o usuário antes** e confirme que o halftime continua funcionando.
4. **Aplicar as mesmas lições já aprendidas:** ler cada aba uma única vez por execução, gravar em lote, expandir a planilha antes de escrever, isolar erros por jogo, e tratar valores como `"--"` e números com vírgula decimal.
5. **Em caso de dúvida entre mexer no que existe ou criar algo novo, criar algo novo.**

## 1. Objetivo

Antes dos jogos do dia, identificar jogadores que vêm **melhorando** em relação ao próprio histórico recente (mais minutos, mais volume de arremessos, melhor aproveitamento, mais rebotes etc.). O sistema entrega **apenas fatos**, sem interpretação, classificação ou sugestão de aposta, como no modo halftime.

**Por que existe:** a casa de apostas do usuário só libera apostas em jogadores antes do jogo começar (player props apenas pre-live). Por isso os alertas de intervalo não viram aposta naquela partida, e este modo aplica a mesma estratégia (detectar desvios positivos) antes do início.

## 2. Execução

- **Workflow novo e separado** no mesmo repositório, com os mesmos GitHub Secrets.
- **Roda 1 vez por dia**, por volta de **10h-11h (horário de Brasília)**, antes dos jogos do dia.
- Disparo: agendamento nativo do GitHub Actions. Como é uma execução diária e os jogos começam horas depois, um atraso de 30-60 minutos não prejudica. Se for desejado, pode-se criar um job no `cron-job.org` chamando este workflow uma vez por dia (`workflow_dispatch`), igual ao que já existe para o halftime.
- **Usar `concurrency`** no workflow, para nunca haver duas execuções do pre-live ao mesmo tempo.
- **Definição de "dia de jogo":** corte às **06h (Brasília)**. Jogos que terminam depois da meia-noite pertencem ao dia anterior.
- **Só processa jogos ainda não iniciados** (status "não iniciado"). Jogos em andamento ou encerrados são ignorados.

## 3. Aba de controle do pre-live

- **Aba própria**, separada da aba de controle do halftime, para que um GameID processado no pre-live nunca seja confundido com um processado no halftime.
- Chave: `GameID`. Colunas sugeridas: `GameID | Data | Status | Enviado em`.
- **Marcar como enviado somente depois de o Telegram confirmar o envio.** No pior caso, isso gera uma mensagem duplicada, que é preferível a um relatório perdido.
- Ler a aba uma única vez por execução e gravar em lote ao final.

## 4. Camada 1: o jogador contra ele mesmo

### 4.1 Janela de comparação

Considere os **7 jogos mais recentes do jogador em que ele atuou 10 ou mais minutos**. O jogo mais recente é o **jogo 1** e o mais antigo da janela é o **jogo 7**.

- **Janela recente:** jogos 1 e 2 (média dos dois).
- **Baseline:** jogos 3 a 7 (média e desvio-padrão dos cinco).
- Jogos com menos de 10 minutos (inclusive DNP) **não ocupam lugar** na janela.
- Jogador com menos de 7 jogos válidos no histórico **fica de fora, em silêncio**.
- Jogos de pré-temporada contam para o histórico (como na spec principal).
- **Não há regra de corte para ausência longa** (decisão do usuário). O relatório mostra a data dos jogos 1 e 2, e o usuário avalia se houve um buraco no calendário.

### 4.2 Filtro de relevância

O jogador só é considerado se a **média de minutos dos jogos 1 e 2 for ≥ 16**. Este filtro vale para todas as métricas. Ele é o único filtro de rotação (não existe filtro na baseline, para não eliminar reservas que acabam de ganhar espaço).

### 4.3 Critério de desvio (só alta)

Uma métrica é reportada somente se **todas** as condições abaixo valerem:

1. **Z-score** ≥ **1.5**, calculado como:
   `(média dos jogos 1 e 2 − média dos jogos 3 a 7) ÷ desvio-padrão dos jogos 3 a 7`
   (método simples, que tende a alertar menos; a calibração vem depois com dados reais).
2. **Piso de magnitude** da métrica (tabela abaixo): `média dos jogos 1 e 2 − média dos jogos 3 a 7 ≥ piso`.
3. **Trava:** o jogo 1 **e** o jogo 2 precisam estar, cada um, **acima** da média dos jogos 3 a 7. Isso evita que um único jogo atípico puxe a média.
4. **Pré-requisito de amostra** da métrica, quando houver (tabela abaixo).

**Desvio-padrão zero:** tratar o caso sem erro de divisão. A regra exata (por exemplo, ignorar o z-score e exigir só o piso e a trava) deve ser **proposta ao usuário antes de ser implementada**.

### 4.4 Métricas e pisos (valores iniciais, a calibrar)

Todas são só de **alta**.

| Métrica | Piso de magnitude | Pré-requisito de amostra |
|---|---|---|
| Minutos | +5 min | — |
| FGA | +5 tentativas | — |
| 3PA | +3 tentativas | — |
| FTA | +4 tentativas | — |
| Pontos | +5 pontos | — |
| FG% | +8 pontos percentuais | ≥ 12 FGA somando os jogos 1 e 2 |
| 3P% | +12 pontos percentuais | ≥ 6 3PA somando os jogos 1 e 2 |
| Rebotes | +2 | — |
| Assistências | +2 | — |
| 3PM | +1 | — |

Observações para calibrar depois: 3PM em +1 é o mais sensível e, se gerar alertas demais, subir para +2. FTA em +4 é um salto grande e deve disparar raramente.

### 4.5 Fora do pre-live (decisão explícita)

- **Faltas cometidas:** não entram (o efeito sobre os minutos já aparece na métrica Minutos).
- **Projeção de pontos:** não existe neste modo (a fórmula depende do 1º tempo).
- **Desvios de queda:** não são reportados.
- Sem classificação automática do tipo de anomalia.

## 5. Contexto do adversário (fato, NUNCA requisito)

O adversário é só informação ao lado do alerta. **Nunca filtra, esconde ou altera um alerta da Camada 1.**

- **Métricas com linha de adversário:** Pontos, Rebotes, Assistências e 3PM. As demais não têm essa linha.
- **Posição:** primeira letra do campo de posição (G, F ou C). Um "G-F" conta como G. Confirmar o formato real que a api-sports devolve, e como a base histórica já guarda a posição.
- **Cálculo:** com a base histórica, média do que jogadores daquela posição fizeram **contra** aquele time, comparada à média da liga para a mesma posição.
- **Sempre exibir o número de jogos da amostra** (ex: "9 jogos"), para o usuário julgar a confiabilidade. No início da temporada a amostra é pequena, e o sistema não deve esconder isso.
- Uma linha de adversário por métrica que disparou, só para as métricas listadas acima.
- Se a base histórica não tiver Time, Adversário e Posição por linha, **avisar o usuário** em vez de improvisar.

## 6. Formato do relatório (Telegram)

- Título da mensagem: **PRÉ-JOGO**, para diferenciar do halftime ("INTERVALO").
- Agrupado por jogo e por time, com cada jogador como um bloco separado.
- Cada métrica que disparou em uma linha própria, mostrando os valores dos jogos 1 e 2 **separados**, a média dos jogos 3 a 7 e a data dos dois jogos recentes.
- Sem z-score e sem texto de interpretação.

**Exemplo:**

```
PRÉ-JOGO — Time A x Time Y

Jogador X (C) — hoje vs. Time Y
Jogos 1 e 2: 12/11 e 10/11
- Minutos: 28 e 31 vs. média 3-7 = 22
- Rebotes: 11 e 12 vs. média 3-7 = 8
  Time Y cede 14 rebotes por jogo a C (liga: 11) | 9 jogos
```

## 7. Cuidados de implementação

- Ler cada aba **uma única vez** por execução e gravar tudo **em lote** (cotas do Google Sheets).
- Isolar erros **por jogo**: um jogo com problema não impede os outros de serem processados.
- Não perder o jogo do dia por falha de Telegram: tratar o erro e registrar nos logs.
- Tratar `"--"` e números com vírgula decimal, como no sistema atual.
- Antes de ativar em produção, **rodar em modo de teste** (enviar só para o usuário e sem gravar na aba de controle) e conferir os resultados contra a planilha.

## 8. Calibração e validação

Todos os pisos e o limiar de z-score são **chutes iniciais**. Depois de algumas semanas de dados, comparar: "os jogadores sinalizados no pre-live voltaram a superar a baseline nos jogos seguintes?". Ajustar pisos conforme o ruído observado.

## 9. Decisões em aberto (resolvidas na implementação)

- **Registro dos alertas do pre-live (resolvido):** criada a aba `AlertasPreLive`, com uma linha por jogador/jogo em que houve desvio (`GameID | JogadorID | Data | Jogador | Posicao | Time | Adversario` + um bloco `[Métrica] Jogo1 | [Métrica] Jogo2 | [Métrica] Media 3-7 | [Métrica] Resultado Real` por métrica). A coluna "Resultado Real" existe desde já, mas **ainda não é preenchida automaticamente** — o preenchimento automático (comparar o alerta com o desempenho real do jogador no jogo do dia) é uma etapa futura, a implementar e confirmar separadamente. Por ora a validação da seção 8 é manual, cruzando esta aba com a aba `Historico` pelo `GameID`.
- **Desvio-padrão zero (resolvido):** quando os 5 jogos do baseline têm desvio-padrão zero, o z-score é dispensado e a métrica dispara só com base no piso de magnitude e na trava (mesmo padrão já usado para "Faltas cometidas" no halftime).
- **Formato real da posição (resolvido):** a api-sports e a base histórica guardam a posição como uma única letra (`G`, `F` ou `C`), sem combinações — usada diretamente, sem necessidade de extrair a "primeira letra" de nada.

## 10. Etapas futuras (NÃO implementar agora)

- **Camada 2:** cruzar o alerta de pre-live com os alertas de intervalo anteriores do mesmo jogador (planilha de alertas do halftime), por exemplo "desviou no intervalo do último jogo".
- **Camada 3:** descanso e back-to-back, casa ou fora, desfalques de companheiros (a confirmar se a api-sports oferece lesões).
- **Linha de adversário completa** (todas as métricas, em vez de só a que disparou).
- **Lista separada de jogadores em queda**, se o usuário sentir falta.
- Opção de transformar o adversário em filtro opcional, quando a amostra por time e posição for grande.
- **Preenchimento automático da coluna "Resultado Real"** da aba `AlertasPreLive` (ver seção 9) — hoje é só manual.

## 11. Notas de implementação (nota de revisão)

- **Elenco de um jogo que ainda não começou:** a api-sports não lista os jogadores de uma partida "Scheduled" (só a partir do momento em que existem estatísticas). Por isso o sistema descobre quem joga em cada time hoje olhando, na própria base `Historico`, qual foi o time mais recente de cada `JogadorID`. Limitação conhecida: um jogador recém-trocado continua aparecendo no time antigo até ter uma estatística completa registrada pelo novo time — não há solução melhor sem uma fonte de elenco/escalação, que a api-sports não oferece.
- **Fuso horário de Brasília:** o cálculo do "dia de jogo" usa `zoneinfo` (biblioteca padrão do Python) com o fuso `America/Sao_Paulo`. No Windows (diferente do Linux), essa biblioteca depende do pacote `tzdata` para funcionar — por isso ele foi adicionado de volta ao `requirements.txt` (tinha sido removido quando deixamos de usar `nba_api`).
- **Arquivos totalmente separados do halftime:** `prelive_config.py`, `prelive_nba_client.py`, `prelive_sheets_client.py`, `prelive_stats.py`, `prelive_report.py`, `prelive_main.py` e o workflow `prelive.yml` são todos novos. Nenhuma linha de `config.py`, `nba_client.py`, `stats.py`, `report.py`, `telegram_client.py`, `main.py` ou `monitor.yml` foi alterada — o pre-live só reaproveita, sem modificar, `sheets_client.conectar()`, `sheets_client._garantir_aba/_carregar_cache/_garantir_espaco/_salvar_cache/_registro_para_estatisticas`, a chamada HTTP interna de `nba_client._chamar_api`, a matemática de `stats.media_e_desvio_padrao/calcular_zscore` e `telegram_client.enviar_mensagem`.
