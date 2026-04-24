from dataclasses import dataclass


@dataclass(frozen=True)
class Horario:
    nombre: str
    inicio: str
    fin: str

    def __str__(self):
        return f"{self.nombre} - {self.inicio} a {self.fin}"


# Cada horario queda disponible de forma independiente.
HORARIO_1 = Horario("Horario 1", "16:00", "18:00")
HORARIO_2 = Horario("Horario 2", "18:30", "20:30")
HORARIO_3 = Horario("Horario 3", "21:00", "23:00")

# Alias de compatibilidad con el estilo anterior del proyecto.
horario_1 = HORARIO_1
horario_2 = HORARIO_2
horario_3 = HORARIO_3


def obtener_horarios_disponibles():
    """Devuelve los horarios agrupados solo cuando la vista necesita mostrarlos juntos."""
    return [HORARIO_1, HORARIO_2, HORARIO_3]


def obtener_horarios_por_nombre():
    return {horario.nombre: horario for horario in obtener_horarios_disponibles()}


def obtener_horario(nombre):
    return obtener_horarios_por_nombre().get(nombre)
