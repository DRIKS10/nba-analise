# Sistema de Análise de Desvios de Jogadores NBA

Sistema que, no intervalo dos jogos da NBA, detecta desvios estatísticos
relevantes no desempenho dos jogadores em relação ao próprio histórico
recente, e avisa por Telegram — sem dar palpite, só fatos.

Este guia assume que você **nunca configurou nada parecido antes**. Siga na
ordem. Cada etapa tem um "porquê" explicado.

## Como o sistema funciona, resumidamente

A cada 5 minutos, o GitHub roda o programa sozinho (isso é o que o arquivo
`.github/workflows/monitor.yml` faz). O programa:

1. Pergunta à api-sports.io quais jogos estão rolando agora.
2. Se algum jogo está **no intervalo**, compara o 1º tempo de cada jogador
   com o histórico dele (quando já houver histórico suficiente — ver seção 4
   da especificação) e, se achar algo fora do padrão, manda uma mensagem no
   seu Telegram. O 1º tempo de todos os jogadores também é salvo no
   histórico, mesmo quem não desviou.
3. Se algum jogo **acabou**, guarda os dados completos numa planilha do
   Google Sheets — é esse histórico que alimenta as comparações dos
   próximos jogos.

Você precisa configurar quatro coisas antes do sistema funcionar: um bot do
Telegram, uma planilha do Google, uma conta na api-sports.io (fonte dos
dados da NBA), e os "Secrets" do GitHub (senhas guardadas com segurança,
para o código nunca precisar expor nada).

---

## 1. Criar o bot do Telegram

1. No Telegram, procure o contato **@BotFather** e inicie uma conversa.
2. Envie `/newbot` e siga as instruções (escolha um nome e um "username"
   terminado em `bot`).
3. O BotFather vai te dar um **token** (uma string longa tipo
   `123456789:ABCdefGhIJKlmNoPQRstuVwxYZ`). Guarde-o — é o seu
   `TELEGRAM_BOT_TOKEN`.
4. Envie qualquer mensagem para o seu bot recém-criado (procure pelo
   username que você escolheu e clique em "Iniciar"/"Start"). Isso é
   necessário para o bot "saber" que pode te enviar mensagens.
5. Para descobrir o `TELEGRAM_CHAT_ID` (o seu ID de conversa), abra no
   navegador, substituindo `SEU_TOKEN`:
   `https://api.telegram.org/botSEU_TOKEN/getUpdates`
   Depois de mandar uma mensagem pro bot (passo 4), essa página vai mostrar
   um número em `"chat":{"id": ...}` — esse número é o seu `TELEGRAM_CHAT_ID`.

## 2. Criar a planilha do Google e as credenciais de acesso

O sistema precisa de uma "conta de serviço" do Google (uma conta especial,
sem interface, só para programas acessarem planilhas).

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/) e crie
   um projeto novo (qualquer nome).
2. No menu, vá em **APIs e Serviços > Biblioteca**, procure por
   **Google Sheets API** e clique em **Ativar**.
3. Vá em **APIs e Serviços > Credenciais > Criar Credenciais > Conta de
   serviço**. Dê um nome qualquer e conclua a criação.
4. Clique na conta de serviço criada, vá na aba **Chaves > Adicionar chave >
   Criar nova chave**, escolha o formato **JSON** e baixe o arquivo.
5. Abra esse arquivo JSON baixado num editor de texto — o **conteúdo inteiro
   dele** (é um texto que começa com `{"type": "service_account", ...}`)
   será o valor da variável `GOOGLE_SERVICE_ACCOUNT_JSON`.
6. Dentro do JSON, tem um campo `"client_email"` — copie esse e-mail
   (parece um e-mail normal, mas termina em
   `.iam.gserviceaccount.com`).
7. Crie uma planilha nova no [Google Sheets](https://sheets.google.com), dê
   um nome a ela (esse nome vai virar a variável `GOOGLE_SHEET_NAME`).
8. Na planilha, clique em **Compartilhar** e cole o e-mail do passo 6,
   dando permissão de **Editor**. Sem esse passo, o sistema não consegue
   escrever na planilha, mesmo com as credenciais certas.

O sistema cria sozinho as três abas que precisa (`Historico`, `Alertas` e
`Controle`) na primeira vez que rodar — não precisa criar nada manualmente
dentro da planilha. Se essas abas já existiam de uma versão anterior do
sistema (com colunas diferentes), apague-as antes de rodar de novo, para o
sistema recriar do zero com as colunas certas.

## 3. Criar a conta na api-sports.io (fonte dos dados da NBA)

1. Crie uma conta em [api-sports.io](https://api-sports.io/) e assine o
   plano **Pro** (US$ 15/mês na época em que este sistema foi construído —
   confira o preço atual no painel, na aba de planos/assinatura).
2. No painel (dashboard), copie sua **chave de API** — será o valor da
   variável `APISPORTS_KEY`.

O plano gratuito não é suficiente para o cron rodar sozinho (o limite diário
de pedidos é baixo demais), mas serve para testes manuais pontuais.

## 4. Colocar o projeto num repositório GitHub público

O repositório precisa ser **público** para o GitHub Actions rodar de graça
sem limite de minutos. Nenhuma senha vai ficar exposta por causa disso — os
valores sensíveis vão morar nos **Secrets** do GitHub (próximo passo), nunca
no código.

Se ainda não tem o projeto num repositório: crie um repositório novo no
GitHub (público), e suba os arquivos desta pasta para ele.

## 5. Configurar os Secrets no GitHub

No repositório, vá em **Settings > Secrets and variables > Actions > New
repository secret** e crie, um de cada vez:

| Nome do Secret | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | o token do passo 1.3 |
| `TELEGRAM_CHAT_ID` | o número do passo 1.5 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | o conteúdo inteiro do JSON do passo 2.5 |
| `GOOGLE_SHEET_NAME` | o nome da planilha do passo 2.7 |
| `APISPORTS_KEY` | a chave do passo 3.2 |

## 6. Testar

- **Teste manual pelo GitHub**: vá na aba **Actions** do repositório,
  clique no workflow "Monitorar jogos da NBA" e depois em **Run workflow**.
  Isso roda o sistema uma vez, na hora, sem esperar o cron. Se não houver
  jogo no intervalo/final nesse momento, ele simplesmente não faz nada
  (isso é esperado, não é erro).
- **Teste local (opcional, exige Python instalado)**:
  1. Copie `.env.example` para `.env` e preencha os valores.
  2. Rode `pip install -r requirements.txt`.
  3. Rode `python -m src.main`.

Depois de configurado, o sistema roda sozinho a cada 5 minutos, na janela de
horário definida em `.github/workflows/monitor.yml`.

---

## Limitações conhecidas desta primeira versão

- **A api-sports.io é uma API de terceiros**: ela pode mudar o formato das
  respostas sem aviso. Se o sistema parar de funcionar do nada, o primeiro
  lugar a investigar é `src/nba_client.py`.
- **O histórico de 1º tempo começa do zero**: a api-sports não permite
  consultar o 1º tempo de um jogo já encerrado, só o "acumulado até agora"
  de um jogo em andamento. Por isso o histórico de 1º tempo só existe a
  partir do momento em que o sistema está rodando de verdade — não dá para
  importar jogos anteriores a essa data (ver seção 4 da especificação).
- **Alertas só começam depois de 7 jogos por jogador**: antes disso, o
  sistema só acumula histórico em silêncio (ver `config.AMOSTRA_MINIMA_JOGOS`).
- **Posição do jogador**: vem genérica (tipo "G", "F" ou "C"), sem o detalhe
  de base/ala-armador etc. Isso é uma limitação dos dados da própria fonte,
  não do sistema.
- **Jogos de exibição não entram**: eventos como o "NBA Canada Game" não
  aparecem na api-sports (testado e confirmado). Como não são jogos oficiais
  de temporada, isso não afeta o histórico.
- **GitHub desativa cron de repositórios inativos**: se o repositório ficar
  60 dias sem nenhum commit, o GitHub pausa os agendamentos automáticos.
  Um commit qualquer (mesmo pequeno) reativa.
- **Limiares em `src/config.py` são um ponto de partida**: a própria
  especificação prevê calibrar o limiar de z-score (hoje 1.5) depois de ver
  dados reais. Ajustar esses números não exige mexer em mais nada.
