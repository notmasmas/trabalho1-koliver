"""
teste_integracao.py - Liga o Terminal INTEIRO (relógio, chegada, 2 controles,
5 médicos + plantonista simulados) e confere invariantes globais.

Uso:
    python teste_integracao.py                       # parte 1 (sem janela)
    xvfb-run -a python teste_integracao.py           # + parte 2 (GUI) no Linux
"""

import re
import threading
import time

from contador import turno_de
from main import Sistema
from simulados import GeradorChegadas


def parte1_balanco():
    """Roda ~2,5 'dias' acelerados com 150 chegadas aleatórias e confere:
         admitidos == chamados + descartados no reinício + ainda nas filas
         ninguém é chamado duas vezes; ninguém é chamado sem ter sido admitido;
         paciente agendado só é chamado pelo médico do seu agendamento."""
    sis = Sistema(intervalo=0.2, n=3, semente=11, latencia=(0.0, 0.02))
    sis.iniciar()
    GeradorChegadas(sis.chegada, 150, pausa=(0.005, 0.05)).start()
    time.sleep(6.0)
    sis.parar()
    time.sleep(0.6)                       # deixa todas as threads pararem

    hist = sis.estado.historico()
    admitidos, medico_do_agendado = [], {}
    chamados, quem_chamou = [], {}
    descartados = 0
    for ev in hist:
        corpo = ev.texto.split("] ", 1)[1]
        if ev.categoria == "chegada":
            nome = corpo.split(": ", 1)[0]
            admitidos.append(nome)
            m = re.search(r"agendada com (.+?) às", corpo)
            if m:
                medico_do_agendado[nome] = m.group(1)
        elif ev.categoria == "atendimento":
            m = re.match(r"(.+?) chamou (.+?) \(", corpo)
            chamados.append(m.group(2))
            quem_chamou[m.group(2)] = m.group(1)
        elif ev.categoria == "info":
            m = re.search(r"\((\d+) paciente", corpo)
            if m:
                descartados += int(m.group(1))

    snap = sis.estado.snapshot_filas()
    nas_filas = (sum(len(v) for v in snap["agendados"].values())
                 + len(snap["prioritarios"]) + len(snap["comuns"]))

    assert len(set(chamados)) == len(chamados), "paciente chamado duas vezes!"
    assert set(chamados) <= set(admitidos), "chamado sem ter sido admitido!"
    assert len(set(admitidos)) == len(admitidos)
    assert len(admitidos) == len(chamados) + descartados + nas_filas, \
        (len(admitidos), len(chamados), descartados, nas_filas)
    for nome, med in medico_do_agendado.items():
        if nome in quem_chamou:
            assert quem_chamou[nome] == med, (nome, med, quem_chamou[nome])
    dias = sum(1 for e in hist if "Novo dia" in e.texto) + 1
    print(f"[OK] balanço em {dias} dias: {len(admitidos)} admitidos = "
          f"{len(chamados)} chamados + {descartados} descartados no reinício "
          f"+ {nas_filas} ainda nas filas")
    print("[OK] ninguém chamado duas vezes; agendados atendidos pelo médico certo")
    recusas = sum(1 for e in hist if e.categoria == "recusa")
    print(f"     ({recusas} recusas registradas: fechado, sem vaga, atraso, sem agenda)")


def parte2_gui():
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
    except Exception as e:                       # sem tkinter ou sem display
        print(f"[--] parte GUI ignorada ({type(e).__name__}: sem display?)")
        return
    from gui import JanelaTerminal

    perguntas, avisos = [], []
    messagebox.askyesno = lambda *a, **k: perguntas.append(a[1]) or True
    messagebox.showwarning = lambda *a, **k: avisos.append(a)

    sis = Sistema(intervalo=5.0, semente=2)      # relógio lento: fica em 08:00
    gui = JanelaTerminal(root, sis)
    sis.iniciar()

    def bombear(segundos, ate=None):
        fim = time.time() + segundos
        while time.time() < fim:
            root.update()
            if ate and ate():
                return True
            time.sleep(0.01)
        return False

    # a) paciente não agendado: a pergunta aparece (na thread da GUI) e a
    #    resposta (prioritário) volta para a thread de chegada
    sis.chegada.solicitar("Zé", agendada=False)
    ok = bombear(4, lambda: "Zé: consulta não agendada (prioritário)" in
                 gui.log.get("1.0", "end"))
    assert ok and len(perguntas) == 1 and "Zé" in perguntas[0]
    print("[OK] GUI: diálogo 'prioritário?' respondido e paciente roteado")

    # b) nome vazio é barrado, sem enviar nada à thread de chegada
    gui.var_nome.set("   ")
    gui._chegou(True)
    assert len(avisos) == 1 and sis.chegada.pedidos.vazia()
    print("[OK] GUI: nome vazio é recusado")

    # c) intervalo configurável pela interface
    gui.var_intervalo.set("0.3")
    gui._aplicar_intervalo()
    assert sis.contador.intervalo == 0.3
    print("[OK] GUI: intervalo do contador alterado em tempo de execução")

    # d) a GUI não trava: 150 chegadas, e ela continua respondendo
    GeradorChegadas(sis.chegada, 150, pausa=(0.001, 0.01)).start()
    t0 = time.time(); ciclos = 0
    while time.time() - t0 < 4:
        root.update(); ciclos += 1; time.sleep(0.005)
    assert ciclos > 100
    print(f"[OK] GUI responsiva durante carga ({ciclos} ciclos de atualização em 4 s)")

    sis.parar()
    root.destroy()


if __name__ == "__main__":
    parte1_balanco()
    parte2_gui()