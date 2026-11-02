import argparse
import os
import threading
import time

import config
from chegada import ThreadChegada
from contador import ContadorTempo
from controle_agendados import ControleAgendados
from controle_naoagendados import ControleNaoAgendados
from estado import EstadoTerminal
from fila_sync import FilaFIFO
from mock_servidor import MockServidor
from simulados import FrontEndSimulado, GeradorChegadas


class Sistema:

    def __init__(self, intervalo=config.INTERVALO_TICK, n=config.N_PROPORCAO,
                 semente=None, latencia=config.LATENCIA_MOCK):
        self.n = n
        self.contador = ContadorTempo(intervalo)
        self.estado = EstadoTerminal(self.contador, config.MEDICOS)

        # provisório até a entrega 2
        self.servidor = MockServidor(config.MEDICOS, latencia=latencia, semente=semente)

        self.chegada = ThreadChegada(self.estado, self.servidor)

        self.canais_medicos = {m: FilaFIFO(f"fe:{m}") for m in config.MEDICOS}
        self.canal_plantonista = FilaFIFO("fe:plantonista")

        self.ctl_agendados = ControleAgendados(self.estado, self.canais_medicos)
        self.ctl_naoagendados = ControleNaoAgendados(
            self.estado, self.canal_plantonista, n)

        # Front Ends simulados (Entrega 1)
        self.simulados = [
            FrontEndSimulado(m, (lambda m=m: self.ctl_agendados.ok_medico(m)),
                             self.canais_medicos[m], self.contador)
            for m in config.MEDICOS
        ]
        self.simulados.append(FrontEndSimulado(
            "Plantonista", self.ctl_naoagendados.ok_plantonista,
            self.canal_plantonista, self.contador))

    def iniciar(self):
        for t in (self.ctl_agendados, self.ctl_naoagendados, self.chegada):
            t.start()
        for s in self.simulados:
            s.start()
        self.contador.start()          # o relógio por último

    def parar(self):
        self.contador.parar()
        self.chegada.parar()
        self.ctl_agendados.parar()
        self.ctl_naoagendados.parar()
        for s in self.simulados:
            s.parar()


def ouvinte_arquivo(estado, caminho):
    """Grava todos os eventos em um arquivo de log (evidência para o relatório)."""
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    arq = open(caminho, "a", encoding="utf-8")
    mtx = threading.Lock()                    # várias threads emitem eventos

    def gravar(ev):
        linha = f"{time.strftime('%H:%M:%S', time.localtime(ev.instante))} " \
                f"{ev.categoria:<11} {ev.texto}\n"
        with mtx:
            arq.write(linha)
            arq.flush()
    estado.registrar_ouvinte(gravar)


def main():
    ap = argparse.ArgumentParser(description="Terminal da clínica (Entrega 1)")
    ap.add_argument("--intervalo", type=float, default=config.INTERVALO_TICK,
                    help="segundos reais por hora da clínica")
    ap.add_argument("--n", type=int, default=config.N_PROPORCAO,
                    help="proporção N:1 (prioritários : comuns)")
    ap.add_argument("--semente", type=int, default=None)
    ap.add_argument("--chegadas", type=int, default=0,
                    help="gera N pacientes aleatórios ao iniciar")
    ap.add_argument("--demo", type=float, default=0,
                    help="roda SEM janela por N segundos imprimindo o log")
    ap.add_argument("--fechar-apos", type=float, default=0,
                    help="(GUI) fecha sozinha após N segundos")
    ap.add_argument("--log", default="logs/terminal.log",
                    help="arquivo de log ('' desativa)")
    args = ap.parse_args()

    sis = Sistema(args.intervalo, args.n, args.semente)
    if args.log:
        ouvinte_arquivo(sis.estado, args.log)

    if args.demo > 0:                                   # ---- modo texto
        sis.estado.registrar_ouvinte(lambda ev: print(ev.texto, flush=True))
        sis.iniciar()
        GeradorChegadas(sis.chegada, args.chegadas or 60).start()
        time.sleep(args.demo)
        sis.parar()
        return

    import tkinter as tk                                # ---- modo GUI
    from gui import JanelaTerminal
    root = tk.Tk()
    JanelaTerminal(root, sis)                           # registra ouvintes ANTES
    sis.iniciar()
    if args.chegadas:
        GeradorChegadas(sis.chegada, args.chegadas).start()
    if args.fechar_apos > 0:
        root.after(int(args.fechar_apos * 1000), root.destroy)
    root.mainloop()
    sis.parar()


if __name__ == "__main__":
    main()