"""
fila_sync.py - Filas internas do Terminal, sincronizadas com mutex + semáforo.

NÃO usa queue.Queue nem multiprocessing.Queue (proibido pelo enunciado).

Padrão usado (produtor/consumidor clássico):
  - `_mutex`  (Lock)      : protege a estrutura de dados (lista/deque).
  - `_itens`  (Semaphore) : conta quantos itens existem na fila.
                            put()  -> insere sob mutex e faz release()
                            get()  -> acquire() e só então remove sob mutex

Por que o semáforo é bom aqui:
  * quem chama get() dorme SEM busy-wait quando a fila está vazia;
  * o sinal nunca se perde: se o item chegou antes de alguém pedir, o
    contador do semáforo já está em 1 e o acquire() passa direto;
  * a ordem é "acquire do semáforo -> pega o mutex". Nunca esperamos o
    semáforo segurando o mutex (isso causaria deadlock: o produtor não
    conseguiria entrar para inserir).
"""

import bisect
import threading
from collections import deque


class FilaFIFO:
    """Fila FIFO thread-safe (usada para prioritários e comuns)."""

    def __init__(self, nome="fila"):
        self.nome = nome
        self._dados = deque()
        self._mutex = threading.Lock()
        self._itens = threading.Semaphore(0)  # nº de itens disponíveis

    def put(self, item):
        """Insere no final da fila e sinaliza que há um item."""
        with self._mutex:
            self._dados.append(item)
        self._itens.release()  # fora do mutex: não precisa segurá-lo

    def get(self, timeout=None):
        """Remove e devolve a cabeça. Bloqueia se vazia.
        Com timeout (segundos) devolve None se expirar."""
        if not self._itens.acquire(timeout=timeout):
            return None
        with self._mutex:
            return self._dados.popleft()  # garantido não-vazio

    def try_get(self):
        """Versão não bloqueante: devolve o item ou None."""
        if not self._itens.acquire(blocking=False):
            return None
        with self._mutex:
            return self._dados.popleft()

    def vazia(self):
        with self._mutex:
            return len(self._dados) == 0

    def tamanho(self):
        with self._mutex:
            return len(self._dados)

    def snapshot(self):
        """Cópia da fila (para a GUI desenhar sem segurar o mutex)."""
        with self._mutex:
            return list(self._dados)


class FilaOrdenada:
    """Fila thread-safe mantida ordenada por `chave(item)` (ex.: horário
    da consulta). Empates mantêm ordem de chegada. A cabeça é sempre o
    item de menor chave. Usada para a sub-lista de cada médico."""

    def __init__(self, nome="ordenada", chave=lambda x: x):
        self.nome = nome
        self._chave = chave
        self._dados = []
        self._mutex = threading.Lock()
        self._itens = threading.Semaphore(0)

    def put(self, item):
        """Insere na posição correta (insort_right => estável em empates)."""
        with self._mutex:
            bisect.insort(self._dados, item, key=self._chave)  # Python 3.10+
        self._itens.release()

    def get(self, timeout=None):
        """Remove a cabeça (menor chave). Bloqueia se vazia."""
        if not self._itens.acquire(timeout=timeout):
            return None
        with self._mutex:
            return self._dados.pop(0)

    def try_get(self):
        if not self._itens.acquire(blocking=False):
            return None
        with self._mutex:
            return self._dados.pop(0)

    def vazia(self):
        with self._mutex:
            return len(self._dados) == 0

    def tamanho(self):
        with self._mutex:
            return len(self._dados)

    def snapshot(self):
        with self._mutex:
            return list(self._dados)


# ----------------------------------------------------------------------
# Teste rápido: python fila_sync.py
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import random
    import time

    # --- Teste 1: vários produtores/consumidores, nada se perde/duplica ---
    f = FilaFIFO("teste")
    N_PROD, POR_PROD, N_CONS = 4, 500, 3
    total = N_PROD * POR_PROD
    recebidos, mtx = [], threading.Lock()

    def produtor(pid):
        for i in range(POR_PROD):
            f.put((pid, i))

    def consumidor():
        while True:
            x = f.get(timeout=1)
            if x is None:
                return
            with mtx:
                recebidos.append(x)

    ts = [threading.Thread(target=produtor, args=(p,)) for p in range(N_PROD)]
    ts += [threading.Thread(target=consumidor) for _ in range(N_CONS)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(recebidos) == total and len(set(recebidos)) == total
    print(f"[OK] FIFO concorrente: {total} itens, sem perda nem duplicação")

    # --- Teste 2: consumidor espera ANTES do produtor (sem busy-wait) ---
    f2, saida = FilaFIFO(), []
    c = threading.Thread(target=lambda: saida.append(f2.get()))
    c.start(); time.sleep(0.3)
    f2.put("paciente"); c.join()
    assert saida == ["paciente"]
    print("[OK] consumidor bloqueado acordou ao chegar o item")

    # --- Teste 3: sinal não se perde (put antes do get) ---
    f3 = FilaFIFO(); f3.put("a")
    assert f3.get(timeout=0.1) == "a" and f3.get(timeout=0.1) is None
    print("[OK] sinal preservado + timeout em fila vazia")

    # --- Teste 4: ordenação por horário com inserções concorrentes ---
    fo = FilaOrdenada("medico1", chave=lambda p: p[1])  # (nome, horario)
    horarios = list(range(10)); random.shuffle(horarios)
    ts = [threading.Thread(target=fo.put, args=((f"P{h}", h),)) for h in horarios]
    for t in ts: t.start()
    for t in ts: t.join()
    ordem = [fo.get()[1] for _ in range(10)]
    assert ordem == sorted(ordem)
    print("[OK] FilaOrdenada devolve sempre o menor horário:", ordem)