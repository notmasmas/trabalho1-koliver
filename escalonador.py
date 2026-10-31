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


# ----------------------------------------------------------------------
# Testes: python escalonador.py
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import random

    from estado import Paciente
    from fila_sync import FilaFIFO

    def enche(f, *nomes, prio):
        for n in nomes:
            f.put(Paciente(n, prioritario=prio))

    def rodar(esc, p, c, k):
        return [esc.proximo(p, c).nome for _ in range(k)]

    # 1) Regra geral 3:1
    esc, p, c = EscalonadorMultiplasFilas(3), FilaFIFO(), FilaFIFO()
    enche(p, *[f"P{i}" for i in range(1, 8)], prio=True)
    enche(c, "C1", "C2", "C3", prio=False)
    seq = rodar(esc, p, c, 10)
    assert seq == ["P1", "P2", "P3", "C1", "P4", "P5", "P6", "C2", "P7", "C3"], seq
    print("[OK] regra geral 3:1:", " ".join(seq))

    # 2) Exceção 1: só comuns; chega prioritário -> 3 seguidos antes do comum
    esc, p, c = EscalonadorMultiplasFilas(3), FilaFIFO(), FilaFIFO()
    enche(c, "C1", "C2", "C3", prio=False)
    seq = rodar(esc, p, c, 2)                    # C1 C2 (1:1, sem prioritário)
    enche(p, "P1", "P2", "P3", "P4", prio=True)  # prioritários chegam
    seq += rodar(esc, p, c, 5)
    assert seq == ["C1", "C2", "P1", "P2", "P3", "C3", "P4"], seq
    print("[OK] exceção 1 (só comuns, depois chega prioritário):", " ".join(seq))

    # 3) Exceção 2: só prioritários; comum chega no meio -> espera o bloco acabar
    esc, p, c = EscalonadorMultiplasFilas(3), FilaFIFO(), FilaFIFO()
    enche(p, *[f"P{i}" for i in range(1, 9)], prio=True)
    seq = rodar(esc, p, c, 4)                    # P1 P2 P3 | P4 (novo bloco)
    enche(c, "C1", prio=False)                   # comum chega durante P4
    seq += rodar(esc, p, c, 4)                   # P5 P6 | C1 | P7
    assert seq == ["P1", "P2", "P3", "P4", "P5", "P6", "C1", "P7"], seq
    print("[OK] exceção 2 (só prioritários, comum entra na reserva):", " ".join(seq))

    # 4) N = 1 alterna 1:1
    esc, p, c = EscalonadorMultiplasFilas(1), FilaFIFO(), FilaFIFO()
    enche(p, "P1", "P2", "P3", prio=True); enche(c, "C1", "C2", "C3", prio=False)
    assert rodar(esc, p, c, 6) == ["P1", "C1", "P2", "C2", "P3", "C3"]
    print("[OK] N=1 alterna prioritário/comum")

    # 5) Vazio
    esc = EscalonadorMultiplasFilas(3)
    assert esc.proximo(FilaFIFO(), FilaFIFO()) is None
    print("[OK] filas vazias -> None")

    # 6) Propriedades sob chegadas aleatórias
    random.seed(7)
    for N in (1, 2, 3, 5):
        esc, p, c = EscalonadorMultiplasFilas(N), FilaFIFO(), FilaFIFO()
        run_p = run_c = 0
        for i in range(5000):
            if random.random() < 0.5: p.put(Paciente(f"P{i}", prioritario=True))
            if random.random() < 0.4: c.put(Paciente(f"C{i}"))
            if random.random() < 0.6:
                tp, tc = not p.vazia(), not c.vazia()
                pac = esc.proximo(p, c)
                if not tp and not tc:
                    assert pac is None
                    continue
                assert pac is not None
                if pac.prioritario:
                    run_c = 0
                    run_p = run_p + 1 if tc else 0
                    assert run_p <= N, (N, run_p)       # sem fome dos comuns
                else:
                    run_p = 0
                    run_c = run_c + 1 if tp else 0
                    assert run_c <= 1, run_c            # sem fome dos prioritários
    print("[OK] 4 valores de N x 5000 passos aleatórios: sem starvation e sem None indevido")