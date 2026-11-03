import random
import threading
import time
from typing import NamedTuple, Optional

MEDICOS_PADRAO = ["Dr. Silva", "Dra. Costa", "Dr. Souza", "Dra. Lima", "Dr. Pereira"]
HORARIOS_VALIDOS = [0, 1, 2, 3, 6, 7, 8, 9]   # Pinho: sem almoço (4 e 5)


class Agendamento(NamedTuple):
    medico: str
    horario: int


class ServidorBase:
    # Interface que o Terminal espera. O mock e o cliente real herdam dela.

    def consultar_agendamento(self, paciente: str, dia) -> Optional[Agendamento]:
        raise NotImplementedError


class MockServidor(ServidorBase):
    def __init__(self, medicos=None, agenda_fixa=None, prob_agendado=0.7,
                 latencia=(0.0, 0.0), semente=None):
        """
        medicos       : lista de nomes dos médicos (para sorteio).
        agenda_fixa   : dict {paciente: (medico, horario)}
        prob_agendado : chance de um paciente desconhecido ter consulta.
        latencia      : (min, max) segundos de atraso simulado da "rede".
        semente       : fixa o gerador aleatório (testes reproduzíveis).
        """
        self._medicos = list(medicos or MEDICOS_PADRAO)
        self._fixa = {n: Agendamento(*a) for n, a in (agenda_fixa or {}).items()}
        self._prob = prob_agendado
        self._latencia = latencia
        self._rng = random.Random(semente)
        # PINHO: gerador próprio (não o random global): a semente só afeta o mock, não o GeradorChegadas nem os Front Ends.
        self._cache = {}                  
        self._mutex = threading.Lock()    # protege _rng e _cache

    def consultar_agendamento(self, paciente, dia=None):
        #Pinho: Simula o tempo de ida e volta ao servidor (fora do mutex! senão o mock serializaria todas as consultas).
        lo, hi = self._latencia
        if hi > 0:
            with self._mutex:
                atraso = self._rng.uniform(lo, hi)
            time.sleep(atraso)
        #Pinho: precisam  estar na mesma thread, ja imaginou duas threads sortearem resultados dif para o mesmo paciente

        with self._mutex:
            # PINHO: a agenda fixa tem prioridade e não passa pelo sorteio;
            if paciente in self._fixa:
                return self._fixa[paciente]
            # Servidor real é consistente: o mesmo paciente recebe sempre
            # a mesma resposta no mesmo dia. O cache reproduz isso.
            if paciente not in self._cache:
                if self._rng.random() < self._prob:
                    self._cache[paciente] = Agendamento(
                        self._rng.choice(self._medicos),
                        self._rng.choice(HORARIOS_VALIDOS))
                else:
                    self._cache[paciente] = None
            return self._cache[paciente]

"""
mock_servidor.py - Servidor de mentira para testar o Terminal (Entrega 1).

Pinho: o Terminal NUNCA conhece o mock diretamente. Ele recebe um objeto
`servidor` que tem o método `consultar_agendamento(paciente, dia)`.
Na Entrega 2, basta criar uma classe `ClienteServidor` (que fala com o
servidor real via Pipe/Queue) com o MESMO método e passá-la no lugar do mock.
Nenhuma outra linha do Terminal muda.

Contrato (igual ao enunciado, item 5.1.2.2-b):
    consultar_agendamento(paciente X, dia D)
        -> Agendamento(medico Y, horario)   se X tem consulta em D
        -> None                              caso contrário
    `horario` é um valor do Contador de Tempo (0..9).
    O servidor NÃO compara com o horário corrente: quem compara é o Terminal.
"""