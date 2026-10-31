"""
controle_agendados.py - Thread de Controle da Fila de Agendados.

Papel (enunciado 5.3.2.2): aguarda o OK de um médico; quando recebe,
remove da fila DAQUELE médico o paciente de menor horário (a cabeça) e
envia o nome ao Front End do médico.

O PROBLEMA DE PROJETO
  Há 5 médicos e uma única thread de controle. Se ela bloqueasse no get()
  da fila de um médico sem pacientes, os outros médicos ficariam sem
  atendimento mesmo com pacientes esperando. Além disso, o OK do médico
  pode chegar ANTES do paciente, e o paciente pode chegar ANTES do OK.
  Nos dois casos nada pode se perder nem travar.

A SOLUÇÃO
  * `_livres`: lista (FIFO) dos médicos que sinalizaram OK e ainda não
    receberam paciente. É a "disponibilidade preservada": o OK fica
    guardado aqui até aparecer alguém para aquele médico.
  * `estado.sinal_agendados`: semáforo de EVENTOS. Recebe release() quando
      - um paciente é inserido (estado.inserir_agendado),
      - um médico manda OK (ok_medico),
      - o relógio avança um tick (para reavaliar turno/almoço).
    A thread faz acquire() e, a cada despertar, VARRE todos os médicos
    livres e despacha todo mundo que tiver paciente (try_get, sem bloquear).
  * Por que não perde sinal: o semáforo é um contador. Cada evento gera
    uma varredura futura; um evento que acontece durante uma varredura
    fica contado e provoca outra. Despertar "à toa" é inofensivo.
  * Por que não bloqueia indefinidamente: nunca esperamos a fila de um
    médico específico; só esperamos o semáforo de eventos.

LOCKS: `_mutex` (só protege `_livres`) nunca é segurado ao mesmo tempo que
o mutex de uma fila (try_get é chamado FORA dele). Sem aninhamento.

REGRA DE NEGÓCIO: médicos só iniciam consultas em turno (contador 0-3 ou
6-9). Fora disso os OKs permanecem em `_livres` e o próximo tick reabre a
varredura. (O enunciado só explicita isso para o plantonista, mas a
premissa 3 vale para os médicos: só podem exceder o horário para
concluir atendimento em andamento.)

PROTOCOLO DO FRONT END DO MÉDICO (1 OK por ciclo):
    ok_medico(m) -> espera nome -> atende -> ok_medico(m) -> ...
  O mesmo OK serve de "terminei" e de "estou pronto". Um OK repetido
  enquanto o médico já está na lista de livres é ignorado (idempotente).
  O FE NÃO deve mandar OK enquanto tem um paciente em mãos.
"""

import threading

from contador import horario_str, pode_atender


class ControleAgendados(threading.Thread):
    def __init__(self, estado, canais):
        """
        estado : EstadoTerminal
        canais : dict {nome_medico: objeto com .put(nome_paciente)}
                 Entrega 1: FilaFIFO lida pela thread simulada do médico.
                 Entrega 2: adaptador que escreve no Pipe do Front End.
        """
        super().__init__(name="ControleAgendados", daemon=True)
        self.estado = estado
        self.canais = canais
        self._livres = []                 # médicos prontos, na ordem do OK
        self._mutex = threading.Lock()    # protege somente _livres
        self._parar = threading.Event()
        # A cada tick, reavalia (pode ter acabado o almoço).
        estado.contador.registrar_callback(self._ao_tick)

    # ---------------- chamado por outras threads ----------------
    def ok_medico(self, medico):
        """O Front End do médico chama isto (Entrega 2: via Pipe)."""
        if medico not in self.estado.agendados:
            return
        self.estado.atendimentos.terminar(medico)   # OK = "terminei o anterior"
        with self._mutex:
            novo = medico not in self._livres
            if novo:
                self._livres.append(medico)
        if novo:
            self.estado.emitir("info", f"{medico} está disponível.")
        self.estado.sinal_agendados.release()

    def livres(self):
        with self._mutex:
            return list(self._livres)

    def parar(self):
        self._parar.set()

    def _ao_tick(self, evento, valor, dia):
        self.estado.sinal_agendados.release()

    # ---------------- thread ----------------
    def run(self):
        sinal = self.estado.sinal_agendados
        while not self._parar.is_set():
            # timeout só para reavaliar _parar; fora isso dorme no semáforo
            if not sinal.acquire(timeout=0.2):
                continue
            self._despachar()

    def _despachar(self):
        est = self.estado
        if not pode_atender(est.contador.ler()):
            return        # almoço/fechado: OKs continuam guardados em _livres

        with self._mutex:
            candidatos = list(self._livres)     # cópia: soltamos o mutex já

        for medico in candidatos:               # ordem do OK => justo
            pac = est.agendados[medico].try_get()   # não bloqueia; cabeça da fila
            if pac is None:
                continue                        # este médico espera; os outros seguem
            with self._mutex:
                self._livres.remove(medico)
            est.atendimentos.iniciar(medico, pac.nome)   # ANTES de enviar
            self.canais[medico].put(pac.nome)            # envia nome ao FE
            est.emitir("atendimento",
                       f"{medico} chamou {pac.nome} "
                       f"(consulta das {horario_str(pac.horario)}).")


# ----------------------------------------------------------------------
# Testes: python controle_agendados.py
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

    def tick(c, valor):
        c.valor = valor
        for cb in c.cbs:
            cb("tick", valor, 1)

    MEDICOS = ["Dr. Silva", "Dra. Costa", "Dr. Souza", "Dra. Lima", "Dr. Pereira"]

    def montar(valor=0):
        c = ContadorFalso(valor)
        est = EstadoTerminal(c, MEDICOS)
        canais = {m: FilaFIFO(f"fe:{m}") for m in MEDICOS}
        ctl = ControleAgendados(est, canais)
        ctl.start()
        return c, est, ctl, canais

    def pac(nome, medico, h):
        return Paciente(nome, medico=medico, horario=h)

    S = "Dr. Silva"

    # 1) OK do médico chega ANTES do paciente: sinal guardado
    c, est, ctl, canais = montar(0)
    ctl.ok_medico(S)
    time.sleep(0.15)
    assert canais[S].vazia() and ctl.livres() == [S]
    est.inserir_agendado(pac("Ana", S, 1))
    assert canais[S].get(timeout=2) == "Ana"
    ctl.parar()
    print("[OK] OK antes do paciente: sinal preservado, entregue quando chega")

    # 2) Paciente chega ANTES do OK
    c, est, ctl, canais = montar(0)
    est.inserir_agendado(pac("Ana", S, 1))
    time.sleep(0.15)
    assert canais[S].vazia()
    ctl.ok_medico(S)
    assert canais[S].get(timeout=2) == "Ana"
    ctl.parar()
    print("[OK] paciente antes do OK: entregue assim que o médico avisa")

    # 3) Médico sem paciente NÃO bloqueia outro médico
    c, est, ctl, canais = montar(0)
    ctl.ok_medico(S)                       # Silva: ninguém para ele
    ctl.ok_medico("Dra. Lima")
    est.inserir_agendado(pac("Bia", "Dra. Lima", 2))
    assert canais["Dra. Lima"].get(timeout=2) == "Bia"
    assert canais[S].vazia() and ctl.livres() == [S]
    ctl.parar()
    print("[OK] médico sem paciente não bloqueia os demais; OK dele segue guardado")

    # 4) Cabeça = menor horário; ordem 1, 2, 3
    c, est, ctl, canais = montar(0)
    for n, h in (("Ana", 3), ("Bia", 1), ("Caio", 2)):
        est.inserir_agendado(pac(n, S, h))
    ordem = []
    for _ in range(3):
        ctl.ok_medico(S)
        ordem.append(canais[S].get(timeout=2))
    assert ordem == ["Bia", "Caio", "Ana"], ordem
    ctl.parar()
    print("[OK] médico recebe sempre o de menor horário:", ordem)

    # 5) Almoço: nada é entregue em 4 e 5; ao chegar 6, entrega sem novo OK
    c, est, ctl, canais = montar(4)
    ctl.ok_medico(S)
    est.inserir_agendado(pac("Ana", S, 3))
    time.sleep(0.2)
    assert canais[S].vazia() and ctl.livres() == [S]
    tick(c, 5); time.sleep(0.15)
    assert canais[S].vazia()
    tick(c, 6)
    assert canais[S].get(timeout=2) == "Ana"
    ctl.parar()
    print("[OK] almoço: OK guardado; atendimento retomado às 14:00 sem novo OK")

    # 6) OK duplicado é idempotente: 3 OKs, 2 pacientes -> só 1 entregue
    c, est, ctl, canais = montar(4)
    for _ in range(3):
        ctl.ok_medico(S)
    assert ctl.livres() == [S]
    est.inserir_agendado(pac("Ana", S, 1)); est.inserir_agendado(pac("Bia", S, 2))
    tick(c, 6)
    assert canais[S].get(timeout=2) == "Ana"
    time.sleep(0.2)
    assert canais[S].vazia() and est.agendados[S].tamanho() == 1
    ctl.parar()
    print("[OK] OKs repetidos contam como um só")

    # 7) 'Em atendimento' visível e limpo no próximo OK
    c, est, ctl, canais = montar(0)
    est.inserir_agendado(pac("Ana", S, 1)); ctl.ok_medico(S)
    canais[S].get(timeout=2)
    assert est.snapshot_filas()["atendimentos"] == {S: "Ana"}
    ctl.ok_medico(S)
    assert est.snapshot_filas()["atendimentos"] == {}
    ctl.parar()
    print("[OK] atendimentos em andamento refletidos para a GUI")

    # 8) Estresse: 5 médicos simulados, 3 produtores concorrentes, 100 pacientes
    c, est, ctl, canais = montar(0)
    parar_sim = threading.Event()
    atendidos, mtx = [], threading.Lock()

    def medico_sim(nome):
        ctl.ok_medico(nome)                      # 1 OK por ciclo
        while not parar_sim.is_set():
            p = canais[nome].get(timeout=0.1)
            if p is None:
                continue
            time.sleep(random.uniform(0.001, 0.01))      # "atende"
            with mtx:
                atendidos.append((nome, p))
            ctl.ok_medico(nome)

    def produtor(ini):
        for i in range(ini, ini + 34):
            if i >= 100: break
            m = random.choice(MEDICOS)
            est.inserir_agendado(pac(f"P{i}", m, random.choice([0, 1, 2, 3, 6, 7])))
            time.sleep(random.uniform(0, 0.005))

    sims = [threading.Thread(target=medico_sim, args=(m,)) for m in MEDICOS]
    prods = [threading.Thread(target=produtor, args=(k * 34,)) for k in range(3)]
    for t in sims + prods: t.start()
    for t in prods: t.join()
    fim = time.time() + 10
    while time.time() < fim:
        with mtx:
            if len(atendidos) == 100: break
        time.sleep(0.02)
    parar_sim.set(); ctl.parar()
    for t in sims: t.join()
    nomes = [p for _, p in atendidos]
    assert len(nomes) == 100 and len(set(nomes)) == 100, len(nomes)
    print("[OK] estresse: 100 pacientes, todos atendidos exatamente uma vez")

    # Confere que cada paciente foi ao médico certo
    esperado = {}
    for e in est.historico():
        if e.categoria == "atendimento":
            partes = e.texto.split("] ", 1)[1]
            med, resto = partes.split(" chamou ", 1)
            esperado[resto.split(" (")[0]] = med
    assert {p: m for m, p in atendidos} == esperado
    print("[OK] cada paciente foi para o seu próprio médico")
