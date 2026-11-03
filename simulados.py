import itertools
import random
import threading

from config import FRACAO_ATENDIMENTO #atendimento dura 40% a 80% de um tick

class FrontEndSimulado(threading.Thread):
    def __init__(self, nome, enviar_ok, canal, contador, fracao=FRACAO_ATENDIMENTO):
        """
        enviar_ok : função sem argumentos que sinaliza "estou pronto"
                    (ex.: lambda: ctl.ok_medico("Dr. Silva")).
        canal     : fila de onde sai o nome do próximo paciente (get).
        contador  : usado só para ler o intervalo do tick, de modo que o
                    atendimento dure SEMPRE menos que um tick.
        """
        super().__init__(name=f"FE:{nome}", daemon=True)
        self.nome_fe = nome
        self.enviar_ok = enviar_ok
        self.canal = canal
        self.contador = contador
        self.fracao = fracao
        # PINHO: contador de pacientes atendidos, usado nos testes. Só esta thread escreve nele, 
        # então não precisa de mutex; quem lê de fora (testes/GUI) só consulta o valor.
        self.atendidos = 0
        # PINHO: permite tanto checar ("já pediram para parar?") quanto dormir de forma interrompível (wait com tempo)
        self._parar = threading.Event()

    def parar(self):
        self._parar.set()

    def run(self):
        self.enviar_ok()                   
        # Pinho: "estou pronto" protocolo avisa o controle
        while not self._parar.is_set():
            # Pinho:esperar num semáforo, a thread fica bloqueada sem gastar CPU enqunato fila estiver vazia
            paciente = self.canal.get(timeout=0.2)
            if paciente is None:
                continue
            # PINHO: o intervalo é lido a cada paciente, e não uma vez no construtor
            tick = getattr(self.contador, "intervalo", 1.0)
            duracao = random.uniform(*self.fracao) * tick
            if self._parar.wait(duracao):  # "atende" (interrompível)
                return
            self.atendidos += 1
            self.enviar_ok()               # terminou: "pronto de novo"


_NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabi", "Hugo",
          "Iara", "João", "Karen", "Lucas", "Marta", "Nuno", "Olga", "Paulo"]
_contagem = itertools.count(1)
_contagem_mutex = threading.Lock()

def nome_unico():
    with _contagem_mutex:
        n = next(_contagem)
    return f"{random.choice(_NOMES)} {n}"
# PINHO: só 16 nomes existem; o número no fim torna cada paciente único

class GeradorChegadas(threading.Thread):
    # Pinho: Gera quantidade pacientes, com pausas aleatórias entre eles.

    def __init__(self, chegada, quantidade, pausa=(0.05, 0.6), parar=None):
        super().__init__(name="GeradorChegadas", daemon=True)
        self.chegada, self.quantidade, self.pausa = chegada, quantidade, pausa
        self._parar = parar or threading.Event()

    def run(self):
        for _ in range(self.quantidade):
            if self._parar.wait(random.uniform(*self.pausa)):
                # PINHO: pausa aleatória entre chegadas == realismo
                return
            self.chegada.solicitar(
                nome_unico(),
                agendada=random.random() < 0.5,
                prioritario=random.random() < 0.3) 

"""
simulados.py - Substitutos da Entrega 1 para o que só existirá na Entrega 2.

  * FrontEndSimulado : faz o papel do Front End do médico / do plantonista
                       (ciclo: OK -> espera nome -> atende -> OK).
  * GeradorChegadas  : gera pacientes aleatórios (para demonstração e testes
                       de saturação das filas).

Na Entrega 2 os Front Ends passam a ser PROCESSOS; para o Terminal nada
muda: ele continua chamando ok_medico()/ok_plantonista() e escrevendo o
nome do paciente num canal (que passa a ser um Pipe).

PINHO: Ideia geral do módulo. Nenhuma das duas threads decide nada do
sistema: elas apenas imitam o "mundo externo" (médicos e pacientes) para que
o Terminal possa ser exercitado sem a Entrega 2. Por isso são as threads
usadas nos testes de integração, de saturação e de carga da GUI.
Ambas são daemon: não impedem o programa de encerrar.
"""