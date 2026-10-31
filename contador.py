"""
contador.py - Thread Contador de Tempo do Terminal.

Mapeamento (1 tick = 1 hora da clínica):
    0=08:00 1=09:00 2=10:00 3=11:00 | 4=12:00 5=13:00 (almoço)
    6=14:00 7=15:00 8=16:00 9=17:00 | 10=18:00 (fim do dia -> reinicia)

Sincronização:
  * Uma Condition (que já contém um mutex) protege `valor`, `dia` e `versao`.
  * Quem precisa esperar uma mudança de hora (ex.: plantonista esperando o
    próximo turno) dorme em `wait_for(predicado)`, sem busy-wait.
  * `versao` é incrementada a cada tick. Quem espera guarda a última versão
    que viu; assim NENHUM tick é perdido, mesmo que a thread esteja
    ocupada quando o notify_all() acontece.
  * Os callbacks (ex.: avisar a GUI) são chamados FORA do mutex, para que
    um callback lento nunca bloqueie as outras threads.
"""

import threading

FIM_DO_DIA = 10          # valor que representa 18:00
TICKS_MANHA = range(0, 4)    # 08:00-11:59  -> contadores 0..3
TICKS_TARDE = range(6, 10)   # 14:00-17:59  -> contadores 6..9


# ---------------------------------------------------------------------
# Regras de negócio baseadas no contador (funções puras, sem estado)
# ---------------------------------------------------------------------
def turno_de(valor):
    """'manha', 'tarde' ou None (almoço / fechado)."""
    if valor in TICKS_MANHA:
        return "manha"
    if valor in TICKS_TARDE:
        return "tarde"
    return None


def aceita_chegada(valor):
    """Chegadas de pacientes: só dentro de um turno E antes de 17:00.
    (contador >= 9 nunca admite nova chegada, como pede o enunciado)."""
    return turno_de(valor) is not None and valor < 9


def pode_atender(valor):
    """Plantonista/médicos podem CHAMAR pacientes já admitidos em 0-3 e 6-9."""
    return turno_de(valor) is not None


def horario_str(valor):
    return f"{8 + valor:02d}:00"


# ---------------------------------------------------------------------
class ContadorTempo(threading.Thread):
    def __init__(self, intervalo=5.0):
        super().__init__(name="ContadorTempo", daemon=True)
        self.intervalo = intervalo            # segundos reais por tick
        self._cond = threading.Condition()
        self._valor = 0
        self._dia = 1
        self._versao = 0
        self._parado = False
        self._parar_evt = threading.Event()   # só para dormir interrompível
        self._callbacks = []

    # ---------------- thread ----------------
    def run(self):
        # Event.wait(t) dorme t segundos, mas acorda na hora se parar() for
        # chamado -> encerramento limpo, sem esperar o fim do sleep.
        while not self._parar_evt.wait(self.intervalo):
            with self._cond:
                if self._valor >= FIM_DO_DIA:       # 18:00 -> novo dia
                    self._valor = 0
                    self._dia += 1
                    evento = "reinicio"
                else:
                    self._valor += 1
                    evento = "fim_dia" if self._valor == FIM_DO_DIA else "tick"
                self._versao += 1
                valor, dia = self._valor, self._dia
                self._cond.notify_all()             # acorda todos os esperando
            for cb in list(self._callbacks):        # fora do mutex
                cb(evento, valor, dia)

    def parar(self):
        self._parar_evt.set()
        with self._cond:
            self._parado = True
            self._cond.notify_all()                 # destrava quem espera

    # ---------------- leitura protegida ----------------
    def ler(self):
        with self._cond:
            return self._valor

    def snapshot(self):
        """(valor, dia, versao) lidos de forma consistente."""
        with self._cond:
            return self._valor, self._dia, self._versao

    # ---------------- espera sem busy-wait ----------------
    def esperar_mudanca(self, versao_vista, timeout=None):
        """Bloqueia até haver um tick mais novo que `versao_vista`.
        Devolve (valor, dia, versao). Use a versao devolvida na próxima
        chamada para não perder nenhum tick."""
        with self._cond:
            self._cond.wait_for(
                lambda: self._versao != versao_vista or self._parado, timeout)
            return self._valor, self._dia, self._versao

    def esperar_turno(self):
        """Bloqueia até o contador estar em turno (0-3 ou 6-9).
        Devolve o valor, ou None se o contador foi parado.
        Usado pelo plantonista: fora do turno ele dorme até o próximo."""
        with self._cond:
            self._cond.wait_for(
                lambda: pode_atender(self._valor) or self._parado)
            return self._valor if pode_atender(self._valor) else None

    def registrar_callback(self, fn):
        """fn(evento, valor, dia); evento in {'tick','fim_dia','reinicio'}.
        Ideal para empurrar um evento para a fila da GUI."""
        self._callbacks.append(fn)


# ----------------------------------------------------------------------
# Teste rápido: python contador.py   (dia inteiro em ~1 segundo)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import time

    c = ContadorTempo(intervalo=0.05)
    eventos = []
    c.registrar_callback(lambda ev, v, d: eventos.append((ev, v, d)))

    # Observador: vê TODOS os ticks, mesmo atrasando de propósito
    vistos = []
    def observador():
        ver = 0
        while True:
            v, d, ver = c.esperar_mudanca(ver, timeout=1)
            if c._parado:
                return
            vistos.append(v)
            time.sleep(0.02)          # simula trabalho lento
            if len(vistos) == 11:
                return

    # Plantonista: tenta esperar turno quando o contador está em 4 (almoço)
    acordou_em = []
    def plantonista():
        while c.ler() != 4:
            time.sleep(0.005)
        acordou_em.append(c.esperar_turno())

    ts = [threading.Thread(target=observador), threading.Thread(target=plantonista)]
    for t in ts: t.start()
    c.start()
    for t in ts: t.join(timeout=5)
    c.parar()

    assert vistos == list(range(1, 11)) + [0], vistos
    print("[OK] observador lento viu todos os ticks, sem perder nenhum:", vistos)
    assert acordou_em == [6], acordou_em
    print("[OK] esperar_turno() dormiu no almoço e acordou em 6 (14:00)")
    assert [e for e, _, _ in eventos if e != "tick"] == ["fim_dia", "reinicio"]
    print("[OK] callbacks sinalizaram fim_dia e reinicio")
    assert [aceita_chegada(v) for v in range(11)] == \
        [True]*4 + [False]*2 + [True]*3 + [False]*2
    assert [pode_atender(v) for v in range(11)] == \
        [True]*4 + [False]*2 + [True]*4 + [False]
    print("[OK] regras: chegadas 0-3 e 6-8; atendimento 0-3 e 6-9")
