"""
controle_naoagendados.py - Thread de Controle das Filas de Não Agendados.

Papel (enunciado 5.3.2.3): aguarda o OK do plantonista; ao receber,
escolhe um paciente pela política N:1 (escalonador.py), remove da fila e
envia o nome ao Front End do Plantonista. Só escolhe se o contador estiver
em turno (0-3 ou 6-9); fora disso o plantonista fica bloqueado até o
próximo turno.

É o mesmo padrão do Controle de Agendados, com UM consumidor só:
  * `_pronto` (bool) guarda a disponibilidade do plantonista: o OK não se
    perde se ainda não há paciente, nem se estamos fora do turno.
  * `estado.sinal_nao_agendados`: semáforo de EVENTOS. Recebe release()
    a cada paciente inserido, a cada OK do plantonista e a cada tick do
    relógio. A thread acorda, e SE o plantonista está pronto, estamos em
    turno e há paciente, despacha. Senão volta a dormir.
  * Sem busy-wait, sem perda de sinal (o semáforo conta eventos), sem
    bloqueio indefinido (a thread nunca espera uma fila específica).

LOCKS: `_mutex` protege só `_pronto`; o escalonador tem o seu para `_cont`;
cada fila tem o seu. Nenhum é segurado enquanto se pega outro.

PROTOCOLO DO FRONT END DO PLANTONISTA (1 OK por ciclo):
    ok_plantonista() -> espera nome -> atende -> ok_plantonista() -> ...
"""

import threading

from contador import horario_str, pode_atender
from escalonador import EscalonadorMultiplasFilas

PLANTONISTA = "Plantonista"


class ControleNaoAgendados(threading.Thread):
    def __init__(self, estado, canal, n=3):
        """
        estado : EstadoTerminal
        canal  : objeto com .put(nome_paciente) que leva o nome ao FE do
                 plantonista (Entrega 1: FilaFIFO; Entrega 2: Pipe).
        n      : proporção N:1 do escalonador.
        """
        super().__init__(name="ControleNaoAgendados", daemon=True)
        self.estado = estado
        self.canal = canal
        self.escalonador = EscalonadorMultiplasFilas(n)
        self._pronto = False
        self._mutex = threading.Lock()
        self._parar = threading.Event()
        estado.contador.registrar_callback(self._ao_tick)

    # ---------------- chamado por outras threads ----------------
    def ok_plantonista(self):
        """O Front End do plantonista chama isto (Entrega 2: via Pipe)."""
        self.estado.atendimentos.terminar(PLANTONISTA)   # OK = "terminei o anterior"
        with self._mutex:
            novo = not self._pronto
            self._pronto = True
        if novo:
            self.estado.emitir("info", "Plantonista está disponível.")
        self.estado.sinal_nao_agendados.release()

    def pronto(self):
        with self._mutex:
            return self._pronto

    def parar(self):
        self._parar.set()

    def _ao_tick(self, evento, valor, dia):
        if evento == "reinicio":
            self.escalonador.reiniciar()
        self.estado.sinal_nao_agendados.release()        # reavalia turno

    # ---------------- thread ----------------
    def run(self):
        sinal = self.estado.sinal_nao_agendados
        while not self._parar.is_set():
            if not sinal.acquire(timeout=0.2):           # só p/ reavaliar _parar
                continue
            self._despachar()

    def _despachar(self):
        est = self.estado
        if not self.pronto():
            return                          # ninguém pediu paciente ainda
        if not pode_atender(est.contador.ler()):
            return                          # fora do turno: OK fica guardado
        pac = self.escalonador.proximo(est.prioritarios, est.comuns)
        if pac is None:
            return                          # sem paciente: OK fica guardado

        with self._mutex:
            self._pronto = False            # consumiu o OK
        est.atendimentos.iniciar(PLANTONISTA, pac.nome)   # ANTES de enviar
        self.canal.put(pac.nome)
        tipo = "prioritário" if pac.prioritario else "comum"
        est.emitir("atendimento",
                   f"Plantonista chamou {pac.nome} ({tipo}; chegou às "
                   f"{horario_str(pac.chegada)}). Prioritários restantes no "
                   f"bloco: {self.escalonador.restantes()}.")

