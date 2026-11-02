"""
estado.py - estado compartilhado do Terminal (tudo que as threads dividem).

recursos e quem protege:
  contador           -> Condition própria (contador.py)
  agendados[medico]  -> FilaOrdenada por médico (mutex + semáforo próprios)
  prioritarios       -> FilaFIFO (mutex + semáforo próprios)
  comuns             -> FilaFIFO (mutex + semáforo próprios)
  slots              -> SlotsPlantonista (mutex próprio)
  atendimentos       -> Atendimentos (mutex próprio)
  histórico/eventos  -> mutex próprio
"""

import threading
import time
from dataclasses import dataclass
from typing import NamedTuple, Optional

from contador import horario_str
from fila_sync import FilaFIFO, FilaOrdenada


@dataclass
class Paciente:
    nome: str
    prioritario: bool = False
    medico: Optional[str] = None            # só para agendados
    horario: Optional[int] = None           # contador da consulta (só agendados)
    chegada: int = 0                        # contador no momento em que chegou


class Evento(NamedTuple):
    instante: float
    categoria: str                          # 'chegada', 'recusa', 'info', 'atendimento', ...
    texto: str


class SlotsPlantonista:

    def __init__(self, por_turno=4):
        self._por_turno = por_turno         # HELENA: quantidadade de vagas por turno
        self._mutex = threading.Lock()
        self._livres = {"manha": por_turno, "tarde": por_turno}


    """
    reservar() verifica e decrementa como uma operação atômica.
    Se fossem dois passos separados (if livres>0: livres-=1), duas threads
    poderiam ver livres=1 ao mesmo tempo e ambas reservar -> race condition.
    """
    def reservar(self, turno):
        with self._mutex:                   # usa o mutex (seção crítica) para leitura e escrita
            if self._livres.get(turno, 0) > 0:
                self._livres[turno] -= 1
                return True
            return False

    def restantes(self, turno):
        with self._mutex:                   # usa o mutex (seção crítica) para leitura
            return self._livres.get(turno, 0)

    def snapshot(self):
        with self._mutex:                   # usa o mutex (seção crítica) para leitura
            return dict(self._livres)

    def reiniciar(self):
        with self._mutex:                   # usa o mutex (seção crítica) para escrita
            self._livres = {"manha": self._por_turno, "tarde": self._por_turno}


class Atendimentos:

    def __init__(self):
        self._mutex = threading.Lock()
        self._dados = {}

    def iniciar(self, profissional, paciente):
        with self._mutex:               # usa o mutex (seção crítica) para escrita
            self._dados[profissional] = paciente

    def terminar(self, profissional):
        with self._mutex:               # usa o mutex (seção crítica) para escrita
            self._dados.pop(profissional, None)

    def snapshot(self):
        with self._mutex:               # usa o mutex (seção crítica) para leitura
            return dict(self._dados)


class EstadoTerminal:
    def __init__(self, contador, medicos):
        self.contador = contador
        self.medicos = list(medicos)
        self.agendados = {
            m: FilaOrdenada(nome=f"agendados:{m}", chave=lambda p: p.horario)
            for m in self.medicos
        }
        self.prioritarios = FilaFIFO("prioritarios")
        self.comuns = FilaFIFO("comuns")
        self.slots = SlotsPlantonista(4)
        self.atendimentos = Atendimentos()
        self.sinal_agendados = threading.Semaphore(0)
        self.sinal_nao_agendados = threading.Semaphore(0)

        self._ouvintes = []
        self._historico = []
        self._log_mutex = threading.Lock()

        # Ao reiniciar o dia, as vagas do plantonista voltam a 4.
        contador.registrar_callback(self._ao_tick)

    # ---------------- eventos (log + GUI) ----------------
    def registrar_ouvinte(self, fn):
        """fn(Evento). Ex.: a GUI empurra o evento para a sua fila."""
        self._ouvintes.append(fn)

    def emitir(self, categoria, texto):
        valor = self.contador.ler()
        ev = Evento(time.time(), categoria, f"[{horario_str(valor)}] {texto}")
        with self._log_mutex:
            self._historico.append(ev)
        for fn in list(self._ouvintes):      # fora do mutex
            fn(ev)

    def historico(self):
        with self._log_mutex:
            return list(self._historico)

    def _ao_tick(self, evento, valor, dia):
        if evento == "reinicio":
            self.slots.reiniciar()
            self.emitir("info", f"Novo dia ({dia}): vagas do plantonista reiniciadas")

    def inserir_agendado(self, paciente):
        self.agendados[paciente.medico].put(paciente)
        self.sinal_agendados.release()

    def inserir_nao_agendado(self, paciente):
        fila = self.prioritarios if paciente.prioritario else self.comuns
        fila.put(paciente)
        self.sinal_nao_agendados.release()

    # ---------------- visão para a GUI ----------------
    def snapshot_filas(self):
        return {
            "agendados": {m: [p.nome for p in f.snapshot()]
                          for m, f in self.agendados.items()},
            "prioritarios": [p.nome for p in self.prioritarios.snapshot()],
            "comuns": [p.nome for p in self.comuns.snapshot()],
            "slots": self.slots.snapshot(),
            "atendimentos": self.atendimentos.snapshot(),
        }