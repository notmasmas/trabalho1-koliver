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


# ----------------------------------------------------------------------
# Testes: python controle_naoagendados.py
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import random
    import time

    from estado import EstadoTerminal, Paciente
    from fila_sync import FilaFIFO

    class ContadorFalso:
        def __init__(self, valor=0):
            self.valor, self.cbs = valor, []
        def ler(self): return self.valor
        def snapshot(self): return self.valor, 1, 0
        def registrar_callback(self, fn): self.cbs.append(fn)

    def tick(c, valor, ev="tick"):
        c.valor = valor
        for cb in c.cbs:
            cb(ev, valor, 1)

    MEDICOS = ["Dr. Silva", "Dra. Costa"]

    def montar(valor=0, n=3):
        c = ContadorFalso(valor)
        est = EstadoTerminal(c, MEDICOS)
        canal = FilaFIFO("fe:plantonista")
        ctl = ControleNaoAgendados(est, canal, n)
        ctl.start()
        return c, est, ctl, canal

    def P(nome): return Paciente(nome, prioritario=True)
    def C(nome): return Paciente(nome, prioritario=False)

    # 1) OK antes do paciente
    c, est, ctl, canal = montar(0)
    ctl.ok_plantonista(); time.sleep(0.15)
    assert canal.vazia() and ctl.pronto()
    est.inserir_nao_agendado(C("Ana"))
    assert canal.get(timeout=2) == "Ana" and not ctl.pronto()
    ctl.parar()
    print("[OK] OK antes do paciente: sinal preservado")

    # 2) Paciente antes do OK
    c, est, ctl, canal = montar(0)
    est.inserir_nao_agendado(P("Bia")); time.sleep(0.15)
    assert canal.vazia()
    ctl.ok_plantonista()
    assert canal.get(timeout=2) == "Bia"
    ctl.parar()
    print("[OK] paciente antes do OK: entregue quando o plantonista avisa")

    # 3) Fora do turno (almoço) bloqueia; volta no turno da tarde sem novo OK
    c, est, ctl, canal = montar(4)
    ctl.ok_plantonista(); est.inserir_nao_agendado(C("Caio"))
    time.sleep(0.2); assert canal.vazia() and ctl.pronto()
    tick(c, 5); time.sleep(0.15); assert canal.vazia()
    tick(c, 6)
    assert canal.get(timeout=2) == "Caio"
    ctl.parar()
    print("[OK] almoço: plantonista bloqueado; atende às 14:00 sem novo OK")

    # 4) Política N:1 pela thread, com plantonista simulado
    c, est, ctl, canal = montar(0, n=3)
    for nome in ("P1", "P2", "P3", "P4"): est.inserir_nao_agendado(P(nome))
    for nome in ("C1", "C2"): est.inserir_nao_agendado(C(nome))
    ordem = []
    for _ in range(6):
        ctl.ok_plantonista()
        ordem.append(canal.get(timeout=2))
    assert ordem == ["P1", "P2", "P3", "C1", "P4", "C2"], ordem
    ctl.parar()
    print("[OK] thread aplica 3:1:", " ".join(ordem))

    # 5) Exceção 1 ao vivo: prioritário chega durante um comum -> é o próximo
    c, est, ctl, canal = montar(0, n=3)
    est.inserir_nao_agendado(C("C1")); est.inserir_nao_agendado(C("C2"))
    ctl.ok_plantonista()
    assert canal.get(timeout=2) == "C1"              # atendendo C1...
    est.inserir_nao_agendado(P("P1"))                # ...chega um prioritário
    ctl.ok_plantonista()                             # C1 terminou
    assert canal.get(timeout=2) == "P1"
    ctl.ok_plantonista()
    assert canal.get(timeout=2) == "C2"
    ctl.parar()
    print("[OK] prioritário que chega durante um comum é chamado logo em seguida")

    # 6) Atendimento em andamento visível para a GUI
    c, est, ctl, canal = montar(0)
    est.inserir_nao_agendado(C("Duda")); ctl.ok_plantonista()
    canal.get(timeout=2)
    assert est.snapshot_filas()["atendimentos"] == {PLANTONISTA: "Duda"}
    ctl.ok_plantonista()
    assert est.snapshot_filas()["atendimentos"] == {}
    ctl.parar()
    print("[OK] atendimento do plantonista refletido para a GUI")

    # 7) Reinício do dia: filas descartadas e escalonador zerado
    c, est, ctl, canal = montar(4, n=3)
    est.inserir_nao_agendado(P("P1")); est.inserir_nao_agendado(C("C1"))
    ctl.escalonador._cont = 1
    tick(c, 0, ev="reinicio")
    s = est.snapshot_filas()
    assert s["prioritarios"] == [] and s["comuns"] == []
    assert ctl.escalonador.restantes() == 3
    ctl.parar()
    print("[OK] reinício do dia: filas esvaziadas e contador N restaurado")

    # 8) Estresse: 3 produtores, 120 pacientes, plantonista simulado
    c, est, ctl, canal = montar(0, n=3)
    parar_sim = threading.Event()
    atendidos = []

    def plantonista_sim():
        ctl.ok_plantonista()
        while not parar_sim.is_set():
            p = canal.get(timeout=0.1)
            if p is None:
                continue
            time.sleep(random.uniform(0.0005, 0.003))
            atendidos.append(p)                  # só esta thread escreve
            ctl.ok_plantonista()

    def produtor(ini):
        for i in range(ini, ini + 40):
            est.inserir_nao_agendado(Paciente(f"X{i}", prioritario=random.random() < 0.5))
            time.sleep(random.uniform(0, 0.003))

    sim = threading.Thread(target=plantonista_sim)
    prods = [threading.Thread(target=produtor, args=(k * 40,)) for k in range(3)]
    sim.start()
    for t in prods: t.start()
    for t in prods: t.join()
    fim = time.time() + 10
    while time.time() < fim and len(atendidos) < 120:
        time.sleep(0.02)
    parar_sim.set(); ctl.parar(); sim.join()
    assert len(atendidos) == 120 and len(set(atendidos)) == 120, len(atendidos)
    assert est.prioritarios.vazia() and est.comuns.vazia()
    print("[OK] estresse: 120 pacientes concorrentes, todos atendidos uma única vez")