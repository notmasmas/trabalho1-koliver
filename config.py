"""config.py - Parâmetros do Terminal (todos num lugar só)."""

# Segundos REAIS entre dois ticks do Contador de Tempo (1 tick = 1 hora da
# clínica). O enunciado recomenda 5 a 10 s. Pode ser mudado na GUI ou por
# linha de comando (--intervalo).
INTERVALO_TICK = 5.0

# Proporção N:1 do escalonador (N prioritários para 1 comum).
N_PROPORCAO = 3

# Corpo clínico agendado (5 médicos).
MEDICOS = ["Dr. Silva", "Dra. Costa", "Dr. Souza", "Dra. Lima", "Dr. Pereira"]

# Duração simulada de um atendimento, como FRAÇÃO do intervalo do tick.
# O enunciado exige duração MENOR que o tick (ex.: 3 a 5 s para tick de 5 s).
FRACAO_ATENDIMENTO = (0.4, 0.8)

# Atraso simulado da "rede" do mock do servidor (segundos).
LATENCIA_MOCK = (0.05, 0.3)
