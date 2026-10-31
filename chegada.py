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


# ----------------------------------------------------------------------
# Testes: python chegada.py
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import time
    from mock_servidor import MockServidor

    class ContadorFalso:
        """Relógio parado em um valor escolhido (injeção de dependência)."""
        def __init__(self, valor=0):
            self.valor = valor
            self.cbs = []
        def ler(self): return self.valor
        def snapshot(self): return self.valor, 1, 0
        def registrar_callback(self, fn): self.cbs.append(fn)

    MEDICOS = ["Dr. Silva", "Dra. Costa", "Dr. Souza", "Dra. Lima", "Dr. Pereira"]

    def montar(valor, agenda=None):
        c = ContadorFalso(valor)
        est = EstadoTerminal(c, MEDICOS)
        th = ThreadChegada(est, MockServidor(agenda_fixa=agenda or {}, prob_agendado=0))
        th.start()
        return c, est, th

    def esperar(cond, t=3):
        fim = time.time() + t
        while time.time() < fim:
            if cond():
                return True
            time.sleep(0.01)
        return False

    def drenar(est, th, n_eventos):
        assert esperar(lambda: len(est.historico()) >= n_eventos), est.historico()
        th.parar()

    # 1) Agendados: horário futuro aceito, passado recusado, ordenação
    c, est, th = montar(1, {"Ana": ("Dr. Silva", 3), "Bia": ("Dr. Silva", 1),
                            "Bruno": ("Dra. Lima", 0), "Caio": ("Dr. Silva", 2)})
    for n in ("Ana", "Bia", "Bruno", "Caio", "Zeca"):   # Zeca: sem agendamento
        th.solicitar(n, agendada=True)
    drenar(est, th, 5)
    fila = [p.nome for p in est.agendados["Dr. Silva"].snapshot()]
    assert fila == ["Bia", "Caio", "Ana"], fila          # ordenado por horário
    assert est.agendados["Dra. Lima"].vazia()            # Bruno (0 < 1) recusado
    print("[OK] agendados: ordenados por horário; atrasado e sem agenda recusados")

    # 2) Não agendados: 4 vagas na manhã, roteamento comum/prioritário
    c, est, th = montar(2)
    th.solicitar("P1", False, prioritario=True)
    th.solicitar("P2", False)
    th.solicitar("P3", False, prioritario=True)
    th.solicitar("P4", False)
    th.solicitar("P5", False)                            # 5º: sem vaga
    th.solicitar("P6", False, prioritario=True)          # 6º: sem vaga
    drenar(est, th, 6)
    snap = est.snapshot_filas()
    assert snap["prioritarios"] == ["P1", "P3"] and snap["comuns"] == ["P2", "P4"]
    assert snap["slots"] == {"manha": 0, "tarde": 4}
    print("[OK] manhã: 4 vagas, filas corretas, 5º e 6º recusados; tarde intacta")

    # 3) Turno da tarde tem vagas próprias
    c.valor = 7
    th2 = ThreadChegada(est, MockServidor()); th2.start()
    th2.solicitar("T1", False)
    drenar(est, th2, 7)
    assert est.snapshot_filas()["slots"] == {"manha": 0, "tarde": 3}
    print("[OK] turno da tarde usa suas próprias 4 vagas")

    # 4) Fechado: almoço (4,5), >= 9 e fim do dia (10) nunca admitem
    for v in (4, 5, 9, 10):
        c, est, th = montar(v, {"Ana": ("Dr. Silva", 9)})
        th.solicitar("Ana", True); th.solicitar("Beto", False)
        drenar(est, th, 2)
        s = est.snapshot_filas()
        assert not s["agendados"]["Dr. Silva"] and not s["comuns"] and \
               s["slots"] == {"manha": 4, "tarde": 4}
        assert all(e.categoria == "recusa" for e in est.historico())
    print("[OK] contador 4, 5, 9 e 10: nenhuma chegada admitida")

    # 5) Corrida nas vagas: 50 threads disputando 4 vagas -> exatamente 4
    est = EstadoTerminal(ContadorFalso(0), MEDICOS)
    ganhou, mtx = [], threading.Lock()
    def disputa():
        r = est.slots.reservar("manha")
        with mtx: ganhou.append(r)
    ts = [threading.Thread(target=disputa) for _ in range(50)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert sum(ganhou) == 4
    print("[OK] 50 threads disputando 4 vagas: exatamente 4 reservas")

    # 6) Reinício do dia devolve as vagas
    c = ContadorFalso(0); est = EstadoTerminal(c, MEDICOS)
    est.slots.reservar("manha"); est.slots.reservar("tarde")
    c.cbs[0]("reinicio", 0, 2)
    assert est.slots.snapshot() == {"manha": 4, "tarde": 4}
    print("[OK] reinício do dia restaura as vagas do plantonista")

    print("\nExemplo do log gerado:")
    for e in est.historico():
        print("  ", e.texto)