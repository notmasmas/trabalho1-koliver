import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import config
from contador import FIM_DO_DIA, aceita_chegada, horario_str, turno_de
from fila_sync import FilaFIFO
from simulados import GeradorChegadas

ATUALIZACAO_MS = 150            # HELENA: de quanto em quanto tempo a GUI vai atualizar com snapshots dos dados
MAX_LINHAS_LOG = 800


class _Pergunta:

    def __init__(self, nome):
        self.nome = nome
        self.resposta = False
        self.evento = threading.Event()


class JanelaTerminal:
    def __init__(self, root, sistema):
        self.root = root
        self.sis = sistema
        self.est = sistema.estado
        self.eventos = FilaFIFO("eventos_gui")       # threads -> GUI
        self.perguntas = FilaFIFO("perguntas_gui")   # thread chegada -> GUI
        self._cache = {}
        self._dialogo_aberto = False
        self._chamados = 0

        self.est.registrar_ouvinte(self.eventos.put)
        self.sis.chegada.perguntar_prioridade = self._perguntar_prioridade

        self._construir()
        root.protocol("WM_DELETE_WINDOW", self._fechar)
        self._atualizar()

    def _construir(self):
        r = self.root
        r.title("Terminal da Clínica - INE5611")
        r.geometry("1200x820")
        r.minsize(1000, 700)
        r.columnconfigure(0, weight=1)
        r.rowconfigure(3, weight=1)

        # ---- Relógio ----
        f = ttk.LabelFrame(r, text="Contador de Tempo", padding=8)
        f.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        f.columnconfigure(1, weight=1)
        self.lbl_hora = ttk.Label(f, text="--:--", font=("TkDefaultFont", 26, "bold"))
        self.lbl_hora.grid(row=0, column=0, rowspan=2, padx=(0, 20))
        self.lbl_turno = ttk.Label(f, text="", font=("TkDefaultFont", 12, "bold"))
        self.lbl_turno.grid(row=0, column=1, sticky="w")
        self.lbl_dia = ttk.Label(f, text="")
        self.lbl_dia.grid(row=1, column=1, sticky="w")
        cfg = ttk.Frame(f)
        cfg.grid(row=0, column=2, rowspan=2, sticky="e")
        ttk.Label(cfg, text="Segundos por hora:").grid(row=0, column=0)
        self.var_intervalo = tk.StringVar(value=str(self.sis.contador.intervalo))
        ttk.Spinbox(cfg, from_=0.1, to=60, increment=0.5, width=6,
                    textvariable=self.var_intervalo).grid(row=0, column=1, padx=4)
        ttk.Button(cfg, text="Aplicar", command=self._aplicar_intervalo).grid(row=0, column=2)

        # ---- Linha do meio: chegada | não agendados | plantonista ----
        meio = ttk.Frame(r)
        meio.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        for c in range(3):
            meio.columnconfigure(c, weight=1, uniform="meio")

        # Chegada
        fc = ttk.LabelFrame(meio, text="Chegada de pacientes", padding=8)
        fc.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        ttk.Label(fc, text="Nome do paciente:").pack(anchor="w")
        self.var_nome = tk.StringVar()
        ent = ttk.Entry(fc, textvariable=self.var_nome)
        ent.pack(fill="x", pady=(0, 6))
        ent.bind("<Return>", lambda e: self._chegou(True))
        ttk.Button(fc, text="Consulta Agendada",
                   command=lambda: self._chegou(True)).pack(fill="x", pady=1)
        ttk.Button(fc, text="Consulta Não Agendada",
                   command=lambda: self._chegou(False)).pack(fill="x", pady=1)
        ttk.Separator(fc).pack(fill="x", pady=6)
        ttk.Button(fc, text="Simular 10 chegadas aleatórias",
                   command=lambda: GeradorChegadas(self.sis.chegada, 10).start()
                   ).pack(fill="x")
        self.lbl_chegada = ttk.Label(fc, text="", wraplength=300, foreground="#555")
        self.lbl_chegada.pack(anchor="w", pady=(6, 0))

        # Filas de não agendados
        fn = ttk.LabelFrame(meio, text="Filas de não agendados", padding=8)
        fn.grid(row=0, column=1, sticky="nsew", padx=4)
        fn.columnconfigure((0, 1), weight=1)
        self.lbl_prio = ttk.Label(fn, text="Prioritários", font=("TkDefaultFont", 10, "bold"))
        self.lbl_prio.grid(row=0, column=0)
        self.lbl_comum = ttk.Label(fn, text="Comuns", font=("TkDefaultFont", 10, "bold"))
        self.lbl_comum.grid(row=0, column=1)
        self.lst_prio = tk.Listbox(fn, height=7, exportselection=False)
        self.lst_prio.grid(row=1, column=0, sticky="nsew", padx=(0, 2))
        self.lst_comum = tk.Listbox(fn, height=7, exportselection=False)
        self.lst_comum.grid(row=1, column=1, sticky="nsew", padx=(2, 0))

        # Plantonista
        fp = ttk.LabelFrame(meio, text="Plantonista (não agendados)", padding=8)
        fp.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        self.lbl_pl_estado = ttk.Label(fp, text="", font=("TkDefaultFont", 11, "bold"))
        self.lbl_pl_estado.pack(anchor="w")
        self.lbl_pl_slots = ttk.Label(fp, text="")
        self.lbl_pl_slots.pack(anchor="w", pady=(6, 0))
        self.lbl_pl_bloco = ttk.Label(fp, text="")
        self.lbl_pl_bloco.pack(anchor="w")
        self.lbl_chamados = ttk.Label(fp, text="")
        self.lbl_chamados.pack(anchor="w", pady=(6, 0))

        # ---- Agendados por médico ----
        fa = ttk.LabelFrame(r, text="Filas de agendados (por médico, ordenadas por horário)",
                            padding=6)
        fa.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        self.med_status, self.med_lista = {}, {}
        for i, m in enumerate(self.est.medicos):
            fa.columnconfigure(i, weight=1, uniform="med")
            ttk.Label(fa, text=m, font=("TkDefaultFont", 10, "bold")).grid(row=0, column=i)
            st = ttk.Label(fa, text="", foreground="#555")
            st.grid(row=1, column=i)
            lb = tk.Listbox(fa, height=5, exportselection=False)
            lb.grid(row=2, column=i, sticky="ew", padx=2)
            self.med_status[m], self.med_lista[m] = st, lb

        # ---- Log ----
        fl = ttk.LabelFrame(r, text="Mensagens", padding=4)
        fl.grid(row=3, column=0, sticky="nsew", padx=8, pady=(4, 8))
        fl.columnconfigure(0, weight=1)
        fl.rowconfigure(0, weight=1)
        self.log = ScrolledText(fl, height=10, state="disabled", wrap="word",
                                font=("TkFixedFont", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        for tag, cor in (("recusa", "#b00020"), ("chegada", "#1b7f3b"),
                         ("atendimento", "#0b4fb3"), ("info", "#666666")):
            self.log.tag_config(tag, foreground=cor)


    def _chegou(self, agendada):
        nome = self.var_nome.get().strip()
        if not nome:
            messagebox.showwarning("Nome", "Informe o nome do paciente.", parent=self.root)
            return
        self.sis.chegada.solicitar(nome, agendada)     # apenas um put() na fila
        self.var_nome.set("")
        tipo = "agendada" if agendada else "não agendada"
        self.lbl_chegada.config(text=f"Pedido de {nome} ({tipo}) enviado.")

    def _aplicar_intervalo(self):
        try:
            v = float(self.var_intervalo.get().replace(",", "."))
            if v <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Intervalo", "Informe um número maior que zero.",
                                 parent=self.root)
            return
        self.sis.contador.intervalo = v    # a thread do relógio lê a cada tick

    def _fechar(self):
        self.sis.parar()
        self.root.destroy()

    # Pergunta "comum ou prioritário?" (thread de chegada <-> GUI)
    def _perguntar_prioridade(self, nome):
        """Chamada pela THREAD DE CHEGADA (não pela GUI). Posta a pergunta e
        dorme até a GUI responder; a GUI nunca é bloqueada."""
        p = _Pergunta(nome)
        self.perguntas.put(p)
        if not p.evento.wait(timeout=300):
            return False                       # sem resposta: trata como comum
        return p.resposta

    def _tratar_pergunta(self):
        if self._dialogo_aberto:
            return
        p = self.perguntas.try_get()
        if p is None:
            return
        self._dialogo_aberto = True
        try:
            p.resposta = messagebox.askyesno(
                "Tipo de atendimento",
                f"{p.nome}: o paciente é PRIORITÁRIO?\n\n"
                f"Sim = prioritário\nNão = comum", parent=self.root)
        finally:
            self._dialogo_aberto = False
            p.evento.set()                     # libera a thread de chegada


    # HELENA: atualização periódica (leitura de snapshots)
    def _atualizar(self):
        try:
            self._desenhar_relogio()
            self._desenhar_filas()
            self._desenhar_log()
        finally:
            self.root.after(ATUALIZACAO_MS, self._atualizar)   # reagenda ANTES
        self._tratar_pergunta()                # diálogo modal por último

    def _set_lista(self, chave, listbox, itens):
        if self._cache.get(chave) != itens:    # só redesenha se mudou
            self._cache[chave] = itens
            listbox.delete(0, tk.END)
            for i in itens:
                listbox.insert(tk.END, i)

    def _desenhar_relogio(self):
        valor, dia, _ = self.sis.contador.snapshot()
        self.lbl_hora.config(text=horario_str(valor))
        turno = turno_de(valor)
        if valor == FIM_DO_DIA:
            txt = "Fim do expediente (reinicia no próximo tick)"
        elif turno is None:
            txt = "Intervalo de almoço: clínica fechada"
        else:
            nome = "manhã" if turno == "manha" else "tarde"
            txt = f"Turno da {nome} - " + ("chegadas abertas" if aceita_chegada(valor)
                                           else "não aceita novas chegadas (após 17:00)")
        self.lbl_turno.config(text=txt)
        self.lbl_dia.config(text=f"Dia {dia}   |   contador = {valor}   |   "
                                 f"{self.sis.contador.intervalo:g} s reais por hora")

    def _desenhar_filas(self):
        est = self.est
        prio = [p.nome for p in est.prioritarios.snapshot()]
        comum = [p.nome for p in est.comuns.snapshot()]
        self._set_lista("prio", self.lst_prio, prio)
        self._set_lista("comum", self.lst_comum, comum)
        self.lbl_prio.config(text=f"Prioritários ({len(prio)})")
        self.lbl_comum.config(text=f"Comuns ({len(comum)})")

        atend = est.atendimentos.snapshot()
        livres = self.sis.ctl_agendados.livres()
        for m in est.medicos:
            itens = [f"{p.nome}  ({horario_str(p.horario)})"
                     for p in est.agendados[m].snapshot()]
            self._set_lista(("med", m), self.med_lista[m], itens)
            if m in atend:
                self.med_status[m].config(text=f"Atendendo: {atend[m]}", foreground="#0b4fb3")
            elif m in livres:
                self.med_status[m].config(text="Disponível", foreground="#1b7f3b")
            else:
                self.med_status[m].config(text="-", foreground="#555")

        ctl = self.sis.ctl_naoagendados
        if "Plantonista" in atend:
            self.lbl_pl_estado.config(text=f"Atendendo: {atend['Plantonista']}",
                                      foreground="#0b4fb3")
        elif ctl.pronto():
            self.lbl_pl_estado.config(text="Disponível", foreground="#1b7f3b")
        else:
            self.lbl_pl_estado.config(text="-", foreground="#555")
        s = est.slots.snapshot()
        self.lbl_pl_slots.config(
            text=f"Vagas restantes   manhã: {s['manha']}/4   tarde: {s['tarde']}/4")
        self.lbl_pl_bloco.config(
            text=f"Prioritários restantes no bloco: "
                 f"{ctl.escalonador.restantes()}/{ctl.escalonador.n}  (N:1)")
        self.lbl_chamados.config(text=f"Pacientes chamados (total): {self._chamados}")

    def _desenhar_log(self):
        novos = []
        for _ in range(200):                   # limite por ciclo: GUI nunca engasga
            ev = self.eventos.try_get()
            if ev is None:
                break
            novos.append(ev)
        if not novos:
            return
        self.log.config(state="normal")
        for ev in novos:
            if ev.categoria == "atendimento":
                self._chamados += 1
            hora = time.strftime("%H:%M:%S", time.localtime(ev.instante))
            self.log.insert(tk.END, f"{hora}  {ev.texto}\n", ev.categoria)
        linhas = int(self.log.index("end-1c").split(".")[0])
        if linhas > MAX_LINHAS_LOG:
            self.log.delete("1.0", f"{linhas - MAX_LINHAS_LOG}.0")
        self.log.see(tk.END)
        self.log.config(state="disabled")