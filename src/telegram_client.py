"""
Envio de mensagens para o Telegram.

Usa a API HTTP oficial do Telegram diretamente (sem biblioteca extra), com
uma chamada simples via `requests`. O token do bot e o ID do chat vêm de
variáveis de ambiente (ver .env.example / GitHub Secrets).
"""

import os

import requests

# O Telegram corta mensagens acima desse tamanho, então dividimos relatórios
# muito grandes em vários envios.
LIMITE_CARACTERES_TELEGRAM = 4000


def _url_envio():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    return f"https://api.telegram.org/bot{token}/sendMessage"


def _dividir_em_partes(texto, limite=LIMITE_CARACTERES_TELEGRAM):
    """Divide um texto longo em pedaços menores, sempre cortando entre blocos
    de time (que são separados por linha em branco dupla "\\n\\n"), para não
    cortar o relatório de um jogador no meio.
    """
    blocos = texto.split("\n\n")
    partes = []
    parte_atual = ""

    for bloco in blocos:
        candidato = f"{parte_atual}\n\n{bloco}" if parte_atual else bloco
        if len(candidato) > limite and parte_atual:
            partes.append(parte_atual)
            parte_atual = bloco
        else:
            parte_atual = candidato

    if parte_atual:
        partes.append(parte_atual)

    return partes


def enviar_mensagem(texto):
    """Envia o texto do relatório para o chat configurado.

    Se o texto for muito grande, envia em várias mensagens separadas.
    Lança uma exceção se o Telegram recusar o envio (ex: token inválido).
    """
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    for parte in _dividir_em_partes(texto):
        resposta = requests.post(
            _url_envio(),
            data={"chat_id": chat_id, "text": parte},
            timeout=15,
        )
        resposta.raise_for_status()
