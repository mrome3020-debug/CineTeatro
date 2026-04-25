import sqlite3
import json
import re
import random
from datetime import datetime

from django import forms
from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import FileExtensionValidator
from Horarios import obtener_horarios_disponibles


HORARIOS_VALIDOS = tuple(horario.nombre for horario in obtener_horarios_disponibles())
HORARIOS_ORDEN = {nombre: indice for indice, nombre in enumerate(HORARIOS_VALIDOS)}


class PeliculaBaseForm(forms.Form):
    CLASIFICACION_MPA_CHOICES = [
        ('G', 'G - Audiencias generales'),
        ('PG', 'PG - Guía parental sugerida'),
        ('PG-13', 'PG-13 - Menores de 13 con advertencia'),
        ('R', 'R - Restringida'),
        ('NC-17', 'NC-17 - Solo adultos'),
    ]

    nombre = forms.CharField(max_length=120)
    proveedor = forms.IntegerField(min_value=1)
    generos = forms.CharField(max_length=120)
    clasificacion = forms.ChoiceField(choices=CLASIFICACION_MPA_CHOICES)
    duracion = forms.CharField(max_length=5)
    descripcion = forms.CharField(max_length=1500)
    calificacion = forms.FloatField(min_value=0.0, max_value=10.0)
    fechas_emision = forms.CharField(max_length=1000, required=False)
    programacion_emision = forms.CharField(max_length=20000, required=False)
    portada = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=['png', 'jpg', 'jpeg', 'gif', 'webp'])],
    )

    def clean_duracion(self):
        duracion = self.cleaned_data['duracion'].strip()
        if not re.fullmatch(r"\d{1,2}:[0-5]\d", duracion):
            raise forms.ValidationError('La duración debe tener formato HH:MM, por ejemplo 02:15.')
        horas, minutos = duracion.split(':')
        return f"{int(horas):02d}:{minutos}"

    def clean_generos(self):
        valor = str(self.cleaned_data['generos']).strip()
        if not valor:
            raise forms.ValidationError('Debes seleccionar al menos un género.')

        generos = []
        vistos = set()
        for item in valor.replace(';', ',').split(','):
            genero = item.strip()
            if not genero:
                continue

            clave = genero.lower()
            if clave in vistos:
                continue
            vistos.add(clave)
            generos.append(genero)

        if not generos:
            raise forms.ValidationError('Debes seleccionar al menos un género.')
        if len(generos) > 5:
            raise forms.ValidationError('Solo puedes seleccionar hasta 5 géneros.')

        return ', '.join(generos)

    def clean_calificacion(self):
        valor_raw = str(self.data.get('calificacion', '')).strip()
        if not re.fullmatch(r"(?:10(?:\.0)?|[0-9](?:\.[0-9])?)", valor_raw):
            raise forms.ValidationError('La calificación debe estar entre 0.0 y 10.0 y usar solo un decimal.')

        calificacion = self.cleaned_data['calificacion']
        if calificacion < 0 or calificacion > 10.0:
            raise forms.ValidationError('La calificación debe estar entre 0.0 y 10.0.')
        return calificacion

    def clean_fechas_emision(self):
        fechas = parsear_fechas_emision(self.cleaned_data['fechas_emision'])
        return fechas

    def clean_programacion_emision(self):
        programacion = parsear_programacion_emision(self.cleaned_data['programacion_emision'])
        return programacion

    def clean(self):
        cleaned_data = super().clean()
        programacion = cleaned_data.get('programacion_emision')
        if not programacion:
            self.add_error('programacion_emision', 'Debes seleccionar al menos un horario en una fecha de función.')
            return cleaned_data

        pelicula_id = cleaned_data.get('id')
        ok, mensaje = validar_programacion_emision(programacion, pelicula_id=pelicula_id)
        if not ok:
            self.add_error('programacion_emision', mensaje)
            return cleaned_data

        cleaned_data['fechas_emision'] = fechas_desde_programacion_emision(programacion)
        return cleaned_data


class PeliculaCreateForm(PeliculaBaseForm):
    pass


class PeliculaEditForm(PeliculaBaseForm):
    id = forms.IntegerField(min_value=1)
    eliminar_portada = forms.BooleanField(required=False)


def obtener_conexion(row_factory=False):
    conn = sqlite3.connect('Peliculas.db')
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn


def ensure_clientes_schema():
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS CLIENTES (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail TEXT NOT NULL UNIQUE,
            usuario TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            creado_en TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_administradores_schema():
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ADMINISTRADORES (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail TEXT UNIQUE,
            usuario TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            nombre TEXT NOT NULL,
            creado_en TEXT NOT NULL
        )
        """
    )
    cursor.execute("PRAGMA table_info(ADMINISTRADORES)")
    columnas = {fila[1] for fila in cursor.fetchall()}
    if 'gmail' not in columnas:
        cursor.execute('ALTER TABLE ADMINISTRADORES ADD COLUMN gmail TEXT')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_administradores_gmail ON ADMINISTRADORES(gmail)')
    conn.commit()
    conn.close()


def es_gmail_valido(gmail):
    valor = (gmail or '').strip().lower()
    patron = r'^[a-zA-Z0-9._%+-]+@gmail\.com$'
    return bool(re.fullmatch(patron, valor))


def es_usuario_admin_valido(usuario):
    valor = (usuario or '').strip()
    if len(valor) < 2:
        return False
    return valor.endswith('.')


def es_registro_admin(usuario, contrasena):
    return es_usuario_admin_valido(usuario) and contrasena == 'Admin123'


def usuario_ya_registrado(usuario):
    ensure_clientes_schema()
    ensure_administradores_schema()

    usuario_normalizado = (usuario or '').strip()
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM CLIENTES WHERE LOWER(usuario) = LOWER(?)', (usuario_normalizado,))
    existe_cliente = cursor.fetchone() is not None
    cursor.execute('SELECT 1 FROM ADMINISTRADORES WHERE LOWER(usuario) = LOWER(?)', (usuario_normalizado,))
    existe_admin = cursor.fetchone() is not None
    conn.close()
    return existe_cliente or existe_admin


def gmail_ya_registrado(gmail):
    ensure_clientes_schema()
    ensure_administradores_schema()

    gmail_normalizado = (gmail or '').strip().lower()
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM CLIENTES WHERE gmail = ?', (gmail_normalizado,))
    existe_cliente = cursor.fetchone() is not None
    cursor.execute('SELECT 1 FROM ADMINISTRADORES WHERE LOWER(COALESCE(gmail, "")) = ?', (gmail_normalizado,))
    existe_admin = cursor.fetchone() is not None
    conn.close()
    return existe_cliente or existe_admin


def registrar_administrador(gmail, usuario, contrasena, nombre=None):
    ensure_administradores_schema()

    gmail_normalizado = (gmail or '').strip().lower()
    usuario_normalizado = (usuario or '').strip()
    nombre_normalizado = (nombre or usuario_normalizado).strip()

    if not es_registro_admin(usuario_normalizado, contrasena):
        return False, 'Para registrarse como administrador, el usuario debe terminar en punto y la contraseña debe ser Admin123.'

    conn = obtener_conexion()
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(1) FROM ADMINISTRADORES')
    total_admins = int(cursor.fetchone()[0])
    if total_admins >= 3:
        conn.close()
        return False, 'Solo se permiten 3 usuarios administradores.'

    if gmail_ya_registrado(gmail_normalizado):
        conn.close()
        return False, 'El Gmail ya está registrado.'

    if usuario_ya_registrado(usuario_normalizado):
        conn.close()
        return False, 'El nombre de usuario administrador ya está en uso.'

    password_hash = make_password(contrasena)
    cursor.execute(
        'INSERT INTO ADMINISTRADORES (gmail, usuario, password_hash, nombre, creado_en) VALUES (?, ?, ?, ?, ?)',
        (gmail_normalizado, usuario_normalizado, password_hash, nombre_normalizado, datetime.now().isoformat(timespec='seconds')),
    )
    conn.commit()
    conn.close()
    return True, None


def autenticar_administrador(usuario, contrasena):
    ensure_administradores_schema()

    usuario_normalizado = (usuario or '').strip()
    usuario_normalizado_lower = usuario_normalizado.lower()

    conn = obtener_conexion(row_factory=True)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, gmail, usuario, nombre, password_hash FROM ADMINISTRADORES WHERE LOWER(usuario) = ? OR LOWER(COALESCE(gmail, "")) = ?',
        (usuario_normalizado_lower, usuario_normalizado_lower),
    )
    admin = cursor.fetchone()
    conn.close()

    if not admin:
        return None

    if not check_password(contrasena, admin['password_hash']):
        return None

    return dict(admin)


def registrar_cliente(gmail, usuario, contrasena):
    ensure_clientes_schema()

    gmail_normalizado = (gmail or '').strip().lower()
    usuario_normalizado = (usuario or '').strip()
    password_hash = make_password(contrasena)

    if gmail_ya_registrado(gmail_normalizado):
        return False, 'El Gmail ya está registrado.'

    if usuario_ya_registrado(usuario_normalizado):
        return False, 'El nombre de usuario ya está en uso.'

    conn = obtener_conexion()
    cursor = conn.cursor()

    cursor.execute(
        'INSERT INTO CLIENTES (gmail, usuario, password_hash, creado_en) VALUES (?, ?, ?, ?)',
        (gmail_normalizado, usuario_normalizado, password_hash, datetime.now().isoformat(timespec='seconds')),
    )
    conn.commit()
    conn.close()
    return True, None


def registrar_cliente_con_hash(gmail, usuario, password_hash):
    ensure_clientes_schema()

    gmail_normalizado = (gmail or '').strip().lower()
    usuario_normalizado = (usuario or '').strip()

    if gmail_ya_registrado(gmail_normalizado):
        return False, 'El Gmail ya está registrado.'

    if usuario_ya_registrado(usuario_normalizado):
        return False, 'El nombre de usuario ya está en uso.'

    conn = obtener_conexion()
    cursor = conn.cursor()

    cursor.execute(
        'INSERT INTO CLIENTES (gmail, usuario, password_hash, creado_en) VALUES (?, ?, ?, ?)',
        (gmail_normalizado, usuario_normalizado, password_hash, datetime.now().isoformat(timespec='seconds')),
    )
    conn.commit()
    conn.close()
    return True, None


def autenticar_cliente(identificador, contrasena):
    ensure_clientes_schema()

    valor = (identificador or '').strip()
    valor_lower = valor.lower()

    conn = obtener_conexion(row_factory=True)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, gmail, usuario, password_hash FROM CLIENTES WHERE LOWER(usuario) = ? OR gmail = ?',
        (valor_lower, valor_lower),
    )
    cliente = cursor.fetchone()
    conn.close()

    if not cliente:
        return None

    if not check_password(contrasena, cliente['password_hash']):
        return None

    return dict(cliente)


def ensure_reservas_schema():
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS RESERVAS (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL,
            pelicula TEXT NOT NULL,
            fecha_funcion TEXT,
            horario_funcion TEXT,
            numero_entrada INTEGER NOT NULL,
            precio INTEGER NOT NULL,
            creado_en TEXT NOT NULL
        )
        """
    )

    cursor.execute("PRAGMA table_info(RESERVAS)")
    columnas = {col[1] for col in cursor.fetchall()}
    if 'fecha_funcion' not in columnas:
        cursor.execute("ALTER TABLE RESERVAS ADD COLUMN fecha_funcion TEXT")
    if 'horario_funcion' not in columnas:
        cursor.execute("ALTER TABLE RESERVAS ADD COLUMN horario_funcion TEXT")

    conn.commit()
    conn.close()


def crear_reserva_entrada(usuario, pelicula, fecha_funcion='', horario_funcion='', precio=200):
    ensure_reservas_schema()

    conn = obtener_conexion(row_factory=True)
    cursor = conn.cursor()

    cursor.execute(
        'SELECT numero_entrada FROM RESERVAS WHERE pelicula = ? AND COALESCE(fecha_funcion, "") = ? AND COALESCE(horario_funcion, "") = ?',
        (pelicula, str(fecha_funcion or '').strip(), str(horario_funcion or '').strip()),
    )
    usados = {int(fila['numero_entrada']) for fila in cursor.fetchall()}
    disponibles = [numero for numero in range(1, 301) if numero not in usados]

    if not disponibles:
        conn.close()
        return None

    numero = random.choice(disponibles)
    creado_en = datetime.now().isoformat(timespec='seconds')

    cursor.execute(
        'INSERT INTO RESERVAS (usuario, pelicula, fecha_funcion, horario_funcion, numero_entrada, precio, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (usuario, pelicula, str(fecha_funcion or '').strip(), str(horario_funcion or '').strip(), numero, precio, creado_en),
    )
    conn.commit()
    conn.close()

    return {
        'usuario': usuario,
        'pelicula': pelicula,
        'fecha_funcion': str(fecha_funcion or '').strip(),
        'horario_funcion': str(horario_funcion or '').strip(),
        'numero_entrada': numero,
        'precio': precio,
        'creado_en': creado_en,
    }


def obtener_reservas_por_usuario(usuario):
    ensure_reservas_schema()

    conn = obtener_conexion(row_factory=True)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, pelicula, fecha_funcion, horario_funcion, numero_entrada, precio, creado_en
        FROM RESERVAS
        WHERE usuario = ?
        ORDER BY id DESC
        """,
        (usuario,),
    )
    reservas = [dict(fila) for fila in cursor.fetchall()]
    conn.close()
    return reservas


def cancelar_reserva_usuario(usuario, reserva_id):
    ensure_reservas_schema()

    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM RESERVAS WHERE id = ? AND usuario = ?', (reserva_id, usuario))
    eliminadas = cursor.rowcount
    conn.commit()
    conn.close()
    return eliminadas > 0


def _convertir_fecha_para_comparar(fecha_dd_mm_yyyy):
    """Convierte dd/mm/yyyy a YYYY-MM-DD para comparaciones y ordenamiento."""
    try:
        return datetime.strptime(fecha_dd_mm_yyyy, '%d/%m/%Y').strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return fecha_dd_mm_yyyy


def parsear_fechas_emision(valor):
    if valor is None:
        return []

    if isinstance(valor, (list, tuple, set)):
        candidatos = valor
    else:
        candidatos = str(valor).replace(';', ',').split(',')

    fechas = []
    vistas = set()
    for candidato in candidatos:
        texto = str(candidato).strip()
        if not texto:
            continue

        normalizada = None
        for formato in ('%Y-%m-%d', '%d/%m/%y', '%d/%m/%Y'):
            try:
                normalizada = datetime.strptime(texto, formato).strftime('%d/%m/%Y')
                break
            except ValueError:
                continue

        if normalizada and normalizada not in vistas:
            fechas.append(normalizada)
            vistas.add(normalizada)

    return sorted(fechas, key=_convertir_fecha_para_comparar)


def parsear_programacion_emision(valor):
    if valor is None:
        return {}

    if isinstance(valor, dict):
        programacion_raw = valor
    else:
        texto = str(valor).strip()
        if not texto:
            return {}
        try:
            programacion_raw = json.loads(texto)
        except json.JSONDecodeError:
            return {}

    programacion = {}
    for fecha_raw, horarios_raw in programacion_raw.items():
        fechas = parsear_fechas_emision(fecha_raw)
        if not fechas:
            continue

        fecha = fechas[0]
        if isinstance(horarios_raw, (list, tuple, set)):
            candidatos = horarios_raw
        else:
            candidatos = str(horarios_raw).replace(';', ',').split(',')

        horarios = []
        vistos = set()
        for candidato in candidatos:
            horario = str(candidato).strip()
            if horario not in HORARIOS_VALIDOS or horario in vistos:
                continue
            vistos.add(horario)
            horarios.append(horario)

        if horarios:
            programacion[fecha] = sorted(horarios, key=lambda nombre: HORARIOS_ORDEN[nombre])

    return dict(sorted(programacion.items(), key=lambda item: _convertir_fecha_para_comparar(item[0])))


def serializar_programacion_emision(valor):
    return json.dumps(parsear_programacion_emision(valor), ensure_ascii=True, separators=(',', ':'))


def fechas_desde_programacion_emision(valor):
    return list(parsear_programacion_emision(valor).keys())


def construir_programacion_base(fechas_emision, programacion_emision=None):
    programacion = parsear_programacion_emision(programacion_emision)
    if programacion:
        return programacion

    return {fecha: [] for fecha in parsear_fechas_emision(fechas_emision)}


def obtener_ocupacion_horarios(excluir_pelicula_id=None):
    ensure_fechas_emision_schema()

    conn = obtener_conexion(row_factory=True)
    cursor = conn.cursor()
    cursor.execute('SELECT rowid, Nombre, Programacion_emision FROM PELICULAS')
    filas = cursor.fetchall()
    conn.close()

    ocupacion = {}
    for fila in filas:
        pelicula_id = fila['rowid']
        if excluir_pelicula_id is not None and pelicula_id == excluir_pelicula_id:
            continue

        for fecha, horarios in parsear_programacion_emision(fila['Programacion_emision']).items():
            ocupacion_fecha = ocupacion.setdefault(fecha, {})
            for horario in horarios:
                ocupacion_fecha[horario] = {
                    'pelicula_id': pelicula_id,
                    'pelicula_nombre': fila['Nombre'],
                }

    return ocupacion


def validar_programacion_emision(programacion_emision, pelicula_id=None):
    programacion = parsear_programacion_emision(programacion_emision)
    if not programacion:
        return False, 'Debes seleccionar al menos un horario en una fecha de emisión.'

    ocupacion = obtener_ocupacion_horarios(excluir_pelicula_id=pelicula_id)
    for fecha, horarios in programacion.items():
        for horario in horarios:
            conflicto = ocupacion.get(fecha, {}).get(horario)
            if conflicto:
                return False, f"El {fecha} en {horario} ya está asignado a {conflicto['pelicula_nombre']}."

    return True, None


def serializar_fechas_emision(valor):
    return ','.join(parsear_fechas_emision(valor))


def obtener_rango_fechas_emision(fechas_emision, fecha_estreno=None):
    fechas = parsear_fechas_emision(fechas_emision)
    if not fechas and fecha_estreno:
        fechas = parsear_fechas_emision(fecha_estreno)
    if not fechas:
        return None, None, []
    return fechas[0], fechas[-1], fechas


def formatear_fecha_corta(fecha_valor):
    fechas = parsear_fechas_emision(fecha_valor)
    if not fechas:
        return ''
    try:
        return datetime.strptime(fechas[0], '%d/%m/%Y').strftime('%d/%m/%y')
    except ValueError:
        return ''


def ensure_fechas_emision_schema():
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(PELICULAS)")
    columnas = [col[1] for col in cursor.fetchall()]

    if not columnas:
        conn.close()
        return

    if 'Fecha_estreno' not in columnas:
        cursor.execute("ALTER TABLE PELICULAS ADD COLUMN Fecha_estreno TEXT")
        columnas.append('Fecha_estreno')

    if 'Fechas_emision' not in columnas:
        cursor.execute("ALTER TABLE PELICULAS ADD COLUMN Fechas_emision TEXT")
        columnas.append('Fechas_emision')

    if 'Programacion_emision' not in columnas:
        cursor.execute("ALTER TABLE PELICULAS ADD COLUMN Programacion_emision TEXT")
        columnas.append('Programacion_emision')

    cursor.execute(
        """
        UPDATE PELICULAS
        SET Fechas_emision = Fecha_estreno
        WHERE (Fechas_emision IS NULL OR TRIM(Fechas_emision) = '')
          AND Fecha_estreno IS NOT NULL
          AND TRIM(Fecha_estreno) <> ''
        """
    )

    cursor.execute("SELECT rowid, Fecha_estreno, Fechas_emision, Programacion_emision FROM PELICULAS")
    filas = cursor.fetchall()
    for rowid, fecha_estreno, fechas_emision, programacion_emision in filas:
        programacion = parsear_programacion_emision(programacion_emision)
        if programacion:
            fechas = list(programacion.keys())
            inicio = fechas[0]
            fechas_texto = ','.join(fechas)
            programacion_texto = serializar_programacion_emision(programacion)
            if (
                fecha_estreno != inicio
                or fechas_emision != fechas_texto
                or (programacion_emision or '') != programacion_texto
            ):
                cursor.execute(
                    "UPDATE PELICULAS SET Fecha_estreno = ?, Fechas_emision = ?, Programacion_emision = ? WHERE rowid = ?",
                    (inicio, fechas_texto, programacion_texto, rowid),
                )
            continue

        inicio, _, fechas = obtener_rango_fechas_emision(fechas_emision, fecha_estreno)
        if not fechas:
            continue

        fechas_texto = ','.join(fechas)
        if fecha_estreno != inicio or fechas_emision != fechas_texto:
            cursor.execute(
                "UPDATE PELICULAS SET Fecha_estreno = ?, Fechas_emision = ? WHERE rowid = ?",
                (inicio, fechas_texto, rowid),
            )

    conn.commit()
    conn.close()


def obtener_programacion_pelicula(pelicula_id):
    ensure_fechas_emision_schema()

    conn = obtener_conexion(row_factory=True)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT Fechas_emision, Programacion_emision FROM PELICULAS WHERE rowid = ?',
        (pelicula_id,),
    )
    fila = cursor.fetchone()
    conn.close()

    if not fila:
        return {}

    return construir_programacion_base(fila['Fechas_emision'], fila['Programacion_emision'])


def obtener_peliculas_para_main(limit=10):
    ensure_fechas_emision_schema()
    conn = obtener_conexion(row_factory=True)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT Nombre, Generos, Clasificacion, Duracion, Calificacion, Fecha_estreno, Fechas_emision, Programacion_emision, Portada, Portada_nombre
        FROM PELICULAS
        LIMIT ?
        """,
        (limit,),
    )
    peliculas = list(cursor.fetchall())
    conn.close()
    
    def obtener_fecha_ordenamiento(pelicula):
        fecha_str = pelicula['Fecha_estreno'] or ''
        if not fecha_str:
            fechas = parsear_fechas_emision(pelicula['Fechas_emision'])
            fecha_str = fechas[0] if fechas else '31/12/9999'
        return _convertir_fecha_para_comparar(fecha_str)
    
    peliculas_ordenadas = sorted(peliculas, key=obtener_fecha_ordenamiento)
    return peliculas_ordenadas


def eliminar_portada_por_rowid(rowid):
    """Elimina portada y nombre de portada para una pelicula por rowid.
    Devuelve True si se pudo ejecutar la operación.
    """
    conn = obtener_conexion()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(PELICULAS)")
    columnas = [col[1] for col in cursor.fetchall()]

    sets = []
    if 'Portada' in columnas:
        sets.append("Portada = NULL")
    if 'Portada_nombre' in columnas:
        sets.append("Portada_nombre = NULL")

    # Si no existen columnas de portada, no bloqueamos el flujo de edición.
    if not sets:
        conn.close()
        return True

    query = f"UPDATE PELICULAS SET {', '.join(sets)} WHERE rowid = ?"
    cursor.execute(query, (rowid,))
    conn.commit()
    conn.close()
    return True


def normalizar_portadas_nulas():
    """Convierte valores vacíos de portada en NULL para evitar falsos positivos de imagen."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(PELICULAS)")
    columnas = [col[1] for col in cursor.fetchall()]

    if 'Portada' in columnas:
        cursor.execute("UPDATE PELICULAS SET Portada = NULL WHERE Portada = ''")
    if 'Portada_nombre' in columnas:
        cursor.execute("UPDATE PELICULAS SET Portada_nombre = NULL WHERE Portada_nombre = ''")

    conn.commit()
    conn.close()


def normalizar_clasificacion_mpa():
    """Convierte clasificaciones numéricas antiguas al estándar MPA."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(PELICULAS)")
    columnas = [col[1] for col in cursor.fetchall()]

    if 'Clasificacion' not in columnas:
        conn.close()
        return

    cursor.execute("SELECT rowid, Clasificacion FROM PELICULAS")
    filas = cursor.fetchall()

    def mapear_a_mpa(valor):
        if valor in ('G', 'PG', 'PG-13', 'R', 'NC-17'):
            return valor
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            return valor

        if numero <= 7:
            return 'G'
        if numero <= 12:
            return 'PG'
        if numero <= 15:
            return 'PG-13'
        if numero <= 17:
            return 'R'
        return 'NC-17'

    for rowid, clasificacion in filas:
        nueva = mapear_a_mpa(clasificacion)
        if nueva != clasificacion:
            cursor.execute("UPDATE PELICULAS SET Clasificacion = ? WHERE rowid = ?", (nueva, rowid))

    conn.commit()
    conn.close()


def normalizar_duracion_hhmm():
    """Convierte duración histórica en minutos al formato HH:MM."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(PELICULAS)")
    columnas = [col[1] for col in cursor.fetchall()]

    if 'Duracion' not in columnas:
        conn.close()
        return

    cursor.execute("SELECT rowid, Duracion FROM PELICULAS")
    filas = cursor.fetchall()

    for rowid, duracion in filas:
        if duracion is None:
            continue

        valor = str(duracion).strip()
        if ':' in valor:
            partes = valor.split(':')
            if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit() and 0 <= int(partes[1]) <= 59:
                cursor.execute("UPDATE PELICULAS SET Duracion = ? WHERE rowid = ?", (f"{int(partes[0]):02d}:{int(partes[1]):02d}", rowid))
                continue

        try:
            minutos_totales = int(float(valor))
        except ValueError:
            continue

        horas = minutos_totales // 60
        minutos = minutos_totales % 60
        cursor.execute("UPDATE PELICULAS SET Duracion = ? WHERE rowid = ?", (f"{horas:02d}:{minutos:02d}", rowid))

    conn.commit()
    conn.close()


def inicializar_db():
    conn = obtener_conexion()
    cursor = conn.cursor()

    # Verificar las tablas disponibles
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tablas = cursor.fetchall()
    print("Tablas en la base de datos:", tablas)

    if ('PELICULAS',) in tablas:
        # Obtener la estructura de la tabla
        cursor.execute("PRAGMA table_info(PELICULAS)")
        columnas = cursor.fetchall()
        nombres_columnas = [col[1] for col in columnas]

        # Añadir columna Fecha_estreno si no existe
        if 'Fecha_estreno' not in nombres_columnas:
            cursor.execute("ALTER TABLE PELICULAS ADD COLUMN Fecha_estreno TEXT")
            conn.commit()
            print("Columna 'Fecha_estreno' añadida a la tabla PELICULAS.")

        if 'Fechas_emision' not in nombres_columnas:
            cursor.execute("ALTER TABLE PELICULAS ADD COLUMN Fechas_emision TEXT")
            conn.commit()
            print("Columna 'Fechas_emision' añadida a la tabla PELICULAS.")

        # Añadir columna Portada si no existe (guarda bytes de imagen)
        if 'Portada' not in nombres_columnas:
            cursor.execute("ALTER TABLE PELICULAS ADD COLUMN Portada BLOB")
            conn.commit()
            print("Columna 'Portada' añadida a la tabla PELICULAS.")

        # Añadir columna para guardar el nombre original del archivo de portada
        if 'Portada_nombre' not in nombres_columnas:
            cursor.execute("ALTER TABLE PELICULAS ADD COLUMN Portada_nombre TEXT")
            conn.commit()
            print("Columna 'Portada_nombre' añadida a la tabla PELICULAS.")

        # Ejecutar una consulta para seleccionar todos los registros de la tabla PELICULAS
        cursor.execute("SELECT * FROM PELICULAS")
        peliculas = cursor.fetchall()

        if peliculas:
            print("Datos de la tabla PELICULAS:")
            for pelicula in peliculas:
                print(pelicula)

            # Actualizar las fechas de estreno para las películas existentes
            fechas_estreno = {
                'El Último Viaje': '2026-03-15',
                'Sombras del Pasado': '2026-05-20',
                'Risas Inesperadas': '2026-07-10',
                'Guerra de Titanes': '2026-09-05',
                'Misterio en la Niebla': '2026-11-12',
                'Amor Eterno': '2026-02-28',
                'Exploradores del Abismo': '2026-04-18',
                'La Rebelión': '2026-06-22',
                'Código Secreto': '2026-08-30',
                'Sueños Perdidos': '2026-10-14',
            }

            for nombre, fecha in fechas_estreno.items():
                cursor.execute(
                    "UPDATE PELICULAS SET Fecha_estreno = ?, Fechas_emision = COALESCE(NULLIF(Fechas_emision, ''), ?) WHERE Nombre = ?",
                    (fecha, fecha, nombre),
                )

            conn.commit()
            print("Fechas de estreno actualizadas.")

            # Mostrar los datos actualizados
            cursor.execute("SELECT * FROM PELICULAS")
            peliculas_actualizadas = cursor.fetchall()
            print("Datos actualizados de la tabla PELICULAS:")
            for pelicula in peliculas_actualizadas:
                print(pelicula)
        else:
            print("La tabla PELICULAS está vacía.")

            # 10 películas de 2026 con fecha de estreno
            peliculas_a_insertar = [
                ('El Último Viaje', 1, 'Ciencia Ficción', 'PG', '02:00', 'Una aventura épica en el espacio.', 8.5, '2026-03-15', '2026-03-15', None, None),
                ('Sombras del Pasado', 2, 'Drama', 'PG-13', '01:35', 'Una historia de redención y amor.', 7.8, '2026-05-20', '2026-05-20', None, None),
                ('Risas Inesperadas', 3, 'Comedia', 'G', '01:25', 'Una comedia ligera sobre malentendidos.', 6.9, '2026-07-10', '2026-07-10', None, None),
                ('Guerra de Titanes', 1, 'Acción', 'NC-17', '02:20', 'Batallas épicas entre dioses y humanos.', 9.0, '2026-09-05', '2026-09-05', None, None),
                ('Misterio en la Niebla', 4, 'Thriller', 'R', '01:50', 'Un detective resuelve un crimen en una ciudad brumosa.', 8.2, '2026-11-12', '2026-11-12', None, None),
                ('Amor Eterno', 2, 'Romance', 'PG', '01:40', 'Una historia de amor que trasciende el tiempo.', 7.5, '2026-02-28', '2026-02-28', None, None),
                ('Exploradores del Abismo', 1, 'Aventura', 'PG', '02:05', 'Una expedición al fondo del océano.', 8.7, '2026-04-18', '2026-04-18', None, None),
                ('La Rebelión', 3, 'Fantasía', 'PG-13', '02:10', 'Una joven lucha contra un régimen opresivo.', 8.0, '2026-06-22', '2026-06-22', None, None),
                ('Código Secreto', 4, 'Suspenso', 'R', '01:45', 'Espías en una misión de alto riesgo.', 7.9, '2026-08-30', '2026-08-30', None, None),
                ('Sueños Perdidos', 2, 'Drama', 'PG-13', '01:30', 'Reflexiones sobre la vida y las decisiones.', 8.1, '2026-10-14', '2026-10-14', None, None),
            ]

            cursor.executemany(
                "INSERT INTO PELICULAS (Nombre, Proveedor, Generos, Clasificacion, Duracion, Descripcion, Calificacion, Fecha_estreno, Fechas_emision, Portada, Portada_nombre) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                peliculas_a_insertar,
            )
            conn.commit()
            print("Se han insertado 10 películas en la tabla PELICULAS con fechas de estreno.")

            # Mostrar los datos después de la inserción
            cursor.execute("SELECT * FROM PELICULAS")
            peliculas = cursor.fetchall()
            print("Datos de la tabla PELICULAS:")
            for pelicula in peliculas:
                print(pelicula)
    else:
        print("La tabla PELICULAS no existe en la base de datos.")

    conn.close()
    ensure_fechas_emision_schema()
    normalizar_portadas_nulas()
    normalizar_clasificacion_mpa()
    normalizar_duracion_hhmm()


if __name__ == "__main__":
    inicializar_db()
