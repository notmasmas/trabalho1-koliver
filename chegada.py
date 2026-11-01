"""
chegada.py - Thread Atendimento de Chegada (produtor das filas).

Fluxo (enunciado 5.3.2.1):
  Consulta AGENDADA:     pergunta ao servidor (X, D) -> (Y, horário) | None
                         horário >= contador -> insere na fila do médico Y
                         senão               -> "sem horário agendado"
  Consulta NÃO AGENDADA: há slot no turno? -> pergunta comum/prioritário
                         -> insere no fim da fila -> decrementa slot

Regras gerais: nenhuma chegada com contador >= 9 nem em 4, 5 ou 10.

Entrada: quem quiser simular uma chegada (GUI ou teste) chama
`solicitar(...)`, que coloca um pedido numa FilaFIFO própria (passo 1).
A thread dorme nessa fila (semáforo) enquanto não há pacientes.

DECISÃO DE PROJETO: o contador é lido UMA vez, no instante da chegada
(snapshot). Esse valor vale para admitir o paciente e para comparar com o
horário agendado, mesmo que a consulta ao servidor demore e o relógio
avance nesse meio tempo. Isso evita que a regra mude no meio do
processamento de um mesmo paciente.
"""

import threading
from dataclasses import dataclass
from typing import Optional

from contador import aceita_chegada, horario_str, turno_de
from estado import EstadoTerminal, Paciente
from fila_sync import FilaFIFO


@dataclass
class PedidoChegada:
    nome: str
    agendada: bool
    prioritario: Optional[bool] = None  # só usado em consulta não agendada


class ThreadChegada(threading.Thread):
    def __init__(self, estado: EstadoTerminal, servidor):
        super().__init__(name="Chegada", daemon=True)
        self.estado = estado
        self.servidor = servidor           # qualquer objeto com consultar_agendamento
        self.pedidos = FilaFIFO("pedidos_chegada")
        self._parar = threading.Event()
        self.perguntar_prioridade = None

    # ---------- API para a GUI / testes ----------
    def solicitar(self, nome, agendada, prioritario=None):
        self.pedidos.put(PedidoChegada(nome, agendada, prioritario))

    def parar(self):
        self._parar.set()

    # ---------- thread ----------
    def run(self):
        while not self._parar.is_set():
            # timeout só para reavaliar _parar; sem busy-wait de verdade
            ped = self.pedidos.get(timeout=0.2)
            if ped is not None:
                self._atender(ped)

    def _atender(self, ped: PedidoChegada):
        est = self.estado
        valor, dia, _ = est.contador.snapshot()      # leitura única e consistente

        if not aceita_chegada(valor):
            if valor >= 9 and valor != 10:
                motivo = "a clínica não aceita mais pacientes após 17:00"
            else:
                motivo = "a clínica está fechada neste horário"
            est.emitir("recusa", f"{ped.nome}: {motivo}.")
            return

        if ped.agendada:
            self._agendada(ped, valor, dia)
        else:
            self._nao_agendada(ped, valor)

    # ---------- consulta agendada ----------
    def _agendada(self, ped, valor, dia):
        est = self.estado
        resp = self.servidor.consultar_agendamento(ped.nome, dia)   # pode demorar

        if resp is None:
            est.emitir("recusa", f"{ped.nome}: não tem consulta agendada para hoje.")
        elif resp.medico not in est.agendados:
            est.emitir("recusa", f"{ped.nome}: médico desconhecido '{resp.medico}'.")
        elif resp.horario < valor:                                  # sem tolerância
            est.emitir("recusa",
                       f"{ped.nome}: consulta era às {horario_str(resp.horario)}; "
                       f"horário já passou (não há tolerância de atraso).")
        else:
            pac = Paciente(ped.nome, medico=resp.medico,
                           horario=resp.horario, chegada=valor)
            est.inserir_agendado(pac)
            est.emitir("chegada",
                       f"{ped.nome}: consulta agendada com {resp.medico} "
                       f"às {horario_str(resp.horario)}. Aguarde ser chamado.")

    # ---------- consulta não agendada ----------
    def _nao_agendada(self, ped, valor):
        est = self.estado
        turno = turno_de(valor)
        nome_turno = "manhã" if turno == "manha" else "tarde"

        # 'há vaga?' + 'decrementa' em UM passo atômico (evita race condition)
        if not est.slots.reservar(turno):
            est.emitir("recusa",
                       f"{ped.nome}: não há mais atendimentos no turno da {nome_turno}.")
            return

        prioritario = ped.prioritario
        if prioritario is None and self.perguntar_prioridade is not None:
            prioritario = self.perguntar_prioridade(ped.nome)

        pac = Paciente(ped.nome, prioritario=bool(prioritario), chegada=valor)
        est.inserir_nao_agendado(pac)
        tipo = "prioritário" if prioritario else "comum"
        est.emitir("chegada",
                   f"{ped.nome}: consulta não agendada ({tipo}). "
                   f"Vagas restantes na {nome_turno}: {est.slots.restantes(turno)}.")
