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

