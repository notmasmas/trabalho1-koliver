import threading

FIM_DO_DIA = 10          # valor que representa 18:00
TICKS_MANHA = range(0, 4)    # 08:00-11:59  -> contadores 0..3
TICKS_TARDE = range(6, 10)   # 14:00-17:59  -> contadores 6..9

# HELENA: retorna o turno do dia (manhã ou tarde) baseado no valor do contador
def turno_de(valor):
    if valor in TICKS_MANHA:
        return "manha"
    if valor in TICKS_TARDE:
        return "tarde"
    return None

# HELENA: retorna se um paciente ainda pode chegar na clínica (antes da 17:00)
def aceita_chegada(valor):
    return turno_de(valor) is not None and valor < 9

# HELENA: retorna se um médico ainda pode atender um (está dentro de um turno)
def pode_atender(valor):
    return turno_de(valor) is not None


def horario_str(valor):
    return f"{8 + valor:02d}:00"


class ContadorTempo(threading.Thread):
    def __init__(self, intervalo=5.0): # HELENA: valor padrão é 5 segundos reais por hora na clínica
        super().__init__(name="ContadorTempo", daemon=True) # HELENA: daemon permite que o programa encerre mesmo com essa thread ainda rodando
        self.intervalo = intervalo

        """
        HELENA: 
        Condition é parecido com mutex. Ele bloqueia um recurso para que outras threads não possam alterá-lo ou lê-lo
        Condition também tem um mecanismo que notifica essas threads dormentes para acordarem e checarem o valor novamente (notify_all)
        Essas threads podem dormir até que uma certa condição seja verdadeira também (wait_for)
        """
        self._cond = threading.Condition()
        self._valor = 0
        self._dia = 1
        self._versao = 0
        self._parado = False
        self._parar_evt = threading.Event() # HELENA: objeto que a thread usa pra sinalizar que deve parar
        self._callbacks = []

    # ---------------- thread ----------------
    def run(self):
        while not self._parar_evt.wait(self.intervalo):
            with self._cond:                        # HELENA: usando o "mutex" (essa área é protegida)
                if self._valor >= FIM_DO_DIA:       # HELENA: reinicia os valores quando acaba o dia
                    self._valor = 0
                    self._dia += 1
                    evento = "reinicio"
                else:
                    self._valor += 1
                    evento = "fim_dia" if self._valor == FIM_DO_DIA else "tick"
                self._versao += 1
                valor, dia = self._valor, self._dia
                self._cond.notify_all()             # HELENA: acorda todas as threads esperando
            for cb in list(self._callbacks):        
                cb(evento, valor, dia)

    def parar(self):
        self._parar_evt.set()
        with self._cond:
            self._parado = True
            self._cond.notify_all()

    def ler(self):   
        with self._cond:                              # HELENA: lê o valor do contador com mutex (essa área é protegida)
            return self._valor

    def snapshot(self):
        with self._cond:                           # HELENA: lê o valor do contador, dia e versão com mutex (essa área é protegida)
            return self._valor, self._dia, self._versao


    def esperar_mudanca(self, versao_vista, timeout=None):
        with self._cond:
            self._cond.wait_for(                  # HELENA: dorme até houver uma nova versão (mudança) ou até o tempo acabar.
                lambda: self._versao != versao_vista or self._parado, timeout)
            return self._valor, self._dia, self._versao

    def esperar_turno(self):
        with self._cond:
            self._cond.wait_for(
                lambda: pode_atender(self._valor) or self._parado)
            return self._valor if pode_atender(self._valor) else None

    def registrar_callback(self, fn):
        self._callbacks.append(fn)

