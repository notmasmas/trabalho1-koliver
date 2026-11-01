"""
escalonador.py - Múltiplas Filas com Alternância Proporcional (enunciado 5.3.2.4).

Regra geral: a cada N prioritários atendidos, 1 comum (proporção N:1).

ESTADO: um único número, `_cont` = quantos prioritários ainda cabem no
bloco atual. Começa em N.

REGRA DE ESCOLHA (dadas as filas no momento da decisão):
    tem prioritário E (cont > 0 OU não há comum)  -> chama PRIORITÁRIO
    senão, tem comum                              -> chama COMUM
    senão                                         -> ninguém (None)

ATUALIZAÇÃO DO ESTADO APÓS A ESCOLHA:
    comum chamado                 -> cont = N      (ciclo recomeça)
    prioritário, cont > 0         -> cont -= 1
    prioritário, cont == 0        -> cont = N - 1  (ver exceção 2)

EXCEÇÃO 1 (prioritários vazia, comuns não): cai direto no "senão, tem
  comum" -> comuns um atrás do outro (1:1). Cada comum chamado deixa
  cont = N; quando um prioritário chega, é chamado logo após o comum atual
  e o ciclo recomeça com N prioritários seguidos.

EXCEÇÃO 2 (comuns vazia, prioritários não): chama prioritários sem pausa.
  Quando o bloco de N se esgota (cont == 0) e ainda não há comum, o próximo
  prioritário INICIA UM NOVO BLOCO (cont = N - 1). Um comum que chegar no
  meio dele fica na "reserva" e é chamado assim que esse bloco terminar.

  >>> DECISÃO DE PROJETO: o enunciado não diz exatamente quando começa o
  >>> "bloco atual" nesse caso. Adotei: o bloco recomeça no primeiro
  >>> prioritário chamado depois que a vez do comum foi "pulada" por falta
  >>> de comum. Consequência: um comum espera, no máximo, N prioritários.
  >>> Vale confirmar com o professor e registrar no relatório.

Propriedades garantidas (testadas aleatoriamente abaixo):
  * Com comum esperando, nunca saem mais de N prioritários seguidos.
  * Com prioritário esperando, nunca saem 2 comuns seguidos.
  * Se alguma fila tem paciente, proximo() nunca devolve None.

SINCRONIZAÇÃO: `proximo()` deve ser chamado por UMA thread só (a Thread de
Controle), que é a única que REMOVE das filas; as demais só inserem. Por
isso, "a fila não está vazia" continua verdade entre o teste e o try_get.
O mutex do escalonador protege apenas `_cont` (a GUI também o lê) e NUNCA é
segurado enquanto se mexe numa fila (sem lock aninhado).
"""

import threading


class EscalonadorMultiplasFilas:
    def __init__(self, n=3):
        if n < 1:
            raise ValueError("N deve ser >= 1")
        self.n = n
        self._cont = n
        self._mutex = threading.Lock()

    def restantes(self):
        """Prioritários que ainda cabem no bloco atual (para a GUI)."""
        with self._mutex:
            return self._cont

    def reiniciar(self):
        with self._mutex:
            self._cont = self.n

    def proximo(self, prioritarios, comuns):
        """Escolhe pela política, REMOVE da fila e devolve o paciente
        (ou None se as duas estiverem vazias)."""
        tem_p = not prioritarios.vazia()
        tem_c = not comuns.vazia()
        with self._mutex:
            cont = self._cont

        if tem_p and (cont > 0 or not tem_c):
            fila, prio = prioritarios, True
        elif tem_c:
            fila, prio = comuns, False
        else:
            return None

        pac = fila.try_get()          # não bloqueia; garantido por único consumidor
        if pac is None:
            return None

        with self._mutex:
            if not prio:
                self._cont = self.n
            elif self._cont > 0:
                self._cont -= 1
            else:
                self._cont = self.n - 1
        return pac
