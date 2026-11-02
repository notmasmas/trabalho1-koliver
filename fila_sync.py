import bisect
import threading
from collections import deque


# HELENA: essa fila FIFO é usada pra fila prioritária e fila comum (sem agendamento)
class FilaFIFO:

    def __init__(self, nome="fila"):
        self.nome = nome
        self._dados = deque()
        self._mutex = threading.Lock()
        self._itens = threading.Semaphore(0)    # HELENA: número de pessoas na fila

    # HELENA: adiciona uma pessoa na fila com mutex para prevenir condição de corrida
    def put(self, item):
        with self._mutex:                      
            self._dados.append(item)

        '''
        HELENA: chamamos o semáforo fora do mutex para evitar que um consumidor que tenha sido acordado pelo release()
        tenha que esperar que mutex seja liberado pelo produtor.
        '''
        self._itens.release()                    # HELENA: incrementa o número de pessoas na fila e acorda consumidor

    def get(self, timeout=None):
        # HELENA: decrementa 1 do semáforo (remove pessoa da fila), se for 0 dorme
        if not self._itens.acquire(timeout=timeout):
            return None
        with self._mutex:
            return self._dados.popleft()  # HELENA: só chega aqui quando for garantido não vazio

        '''
        HELENA: na ordem de bloqueio deste método get, primeiro garantimos que a fila não estará vazia utilizando o semáforo
        para que ela durma até haver alguma pessoa. Logo após, removemos uma pessoa da fila utilizando o mutex para garantir
        que não haja condição de corrida
        '''

    def try_get(self):
        # HELENA: diferente do get, se a fila estiver vazia ele não dorme, ele só retorna None
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
        with self._mutex:
            return list(self._dados)

# HELENA: essa fila é usada pra fila agendada de cada médico
class FilaOrdenada:

    def __init__(self, nome="ordenada", chave=lambda x: x):
        self.nome = nome
        self._chave = chave
        self._dados = []
        self._mutex = threading.Lock()
        self._itens = threading.Semaphore(0)

    # HELENA: insere na fila e ordena ela (usando bisect.insort)
    def put(self, item):
        with self._mutex:
            bisect.insort(self._dados, item, key=self._chave)
        self._itens.release()

    # HELENA: remove a primeira da fila, dorme se a fila estiver vazia
    def get(self, timeout=None):
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