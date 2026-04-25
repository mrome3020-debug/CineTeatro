import base64
from datetime import datetime

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.utils.datastructures import MultiValueDict
from django.utils.text import get_valid_filename

from DB import (
    construir_programacion_base,
    eliminar_portada_por_rowid,
    ensure_fechas_emision_schema,
    fechas_desde_programacion_emision,
    formatear_fecha_corta,
    obtener_conexion,
    obtener_ocupacion_horarios,
    obtener_rango_fechas_emision,
    PeliculaCreateForm,
    PeliculaEditForm,
    serializar_programacion_emision,
)
from Fechas import calendario
from Horarios import obtener_horarios_disponibles


def obtener_mime(nombre_archivo):
    extension = nombre_archivo.rsplit('.', 1)[1].lower() if '.' in nombre_archivo else ''
    if extension in ('jpg', 'jpeg'):
        return 'image/jpeg'
    if extension == 'png':
        return 'image/png'
    if extension == 'gif':
        return 'image/gif'
    if extension == 'webp':
        return 'image/webp'
    return 'application/octet-stream'


def construir_src_portada(portada, portada_nombre):
    if portada is None:
        return None
    if isinstance(portada, bytes):
        nombre = portada_nombre or 'imagen.jpg'
        mime = obtener_mime(nombre)
        encoded = base64.b64encode(portada).decode('utf-8')
        return f"data:{mime};base64,{encoded}"
    if isinstance(portada, str):
        return portada
    return None


def formatear_errores_formulario(form):
    errores = []
    for campo, errores_campo in form.errors.items():
        for err in errores_campo:
            errores.append(f"{campo}: {err}")
    return '; '.join(errores)


def limpiar_archivos_vacios(files):
    """Elimina entradas de archivos vacios para compatibilidad con Django FileField."""
    limpios = MultiValueDict()
    for key, values in files.lists():
        for value in values:
            if value and getattr(value, 'name', '').strip():
                limpios.appendlist(key, value)
    return limpios


def get_db_connection():
    return obtener_conexion(row_factory=True)


def _requiere_admin_activo(request):
    return request.session.get('rol') == 'admin'


def _normalizar_pelicula(fila):
    data = dict(fila)
    data['fechas_emision_resumen'] = data.get('Fechas_emision') or data.get('Fecha_estreno') or ''
    data['programacion_emision_json'] = serializar_programacion_emision(
        construir_programacion_base(data.get('Fechas_emision'), data.get('Programacion_emision'))
    )
    data['portada_src'] = construir_src_portada(data.get('Portada'), data.get('Portada_nombre'))
    return data


def _obtener_horarios_contexto():
    return [
        {
            'nombre': horario.nombre,
            'inicio': horario.inicio,
            'fin': horario.fin,
        }
        for horario in obtener_horarios_disponibles()
    ]


def _obtener_proveedores_contexto(peliculas):
    proveedores = set()
    for pelicula in peliculas:
        valor = str(pelicula.get('Proveedor', '')).strip()
        if valor:
            proveedores.add(valor)

    return sorted(proveedores, key=lambda item: int(item) if item.isdigit() else item)


def _obtener_generos_contexto(peliculas):
    generos = set()
    for pelicula in peliculas:
        valor = str(pelicula.get('Generos', '')).strip()
        if not valor:
            continue
        for genero in valor.replace(';', ',').split(','):
            nombre = genero.strip()
            if nombre:
                generos.add(nombre)

    return sorted(generos, key=str.lower)


def _obtener_fechas_calendario_contexto():
    fechas = calendario.obtener_fechas_seleccionables()
    return sorted([fecha.strftime('%Y-%m-%d') for fecha in fechas])


def admin(request):
    if not _requiere_admin_activo(request):
        return redirect('ingresar_admin')

    ensure_fechas_emision_schema()
    conn = get_db_connection()
    peliculas = conn.execute('SELECT rowid, * FROM PELICULAS').fetchall()
    conn.close()

    peliculas_contexto = [_normalizar_pelicula(pelicula) for pelicula in peliculas]
    return render(
        request,
        'admin_peliculas.html',
        {
            'peliculas': peliculas_contexto,
            'horarios': _obtener_horarios_contexto(),
            'fechas_calendario': _obtener_fechas_calendario_contexto(),
            'proveedores': _obtener_proveedores_contexto(peliculas_contexto),
            'generos_disponibles': _obtener_generos_contexto(peliculas_contexto),
            'usuario': request.session['usuario'],
        },
    )


def obtener_disponibilidad_emision(request):
    if not _requiere_admin_activo(request):
        return JsonResponse({'ok': False, 'error': 'Acceso no autorizado.'}, status=403)

    pelicula_id_raw = (request.GET.get('pelicula_id') or '').strip()
    pelicula_id = int(pelicula_id_raw) if pelicula_id_raw.isdigit() else None
    return JsonResponse(
        {
            'ok': True,
            'horarios': _obtener_horarios_contexto(),
            'ocupacion': obtener_ocupacion_horarios(excluir_pelicula_id=pelicula_id),
        }
    )


def ver_portadas(request):
    if not _requiere_admin_activo(request):
        return redirect('ingresar_admin')

    ensure_fechas_emision_schema()
    conn = get_db_connection()
    filas = conn.execute(
        'SELECT rowid, Nombre, Portada, Portada_nombre, Fecha_estreno, Fechas_emision FROM PELICULAS'
    ).fetchall()
    conn.close()

    portadas = []
    for fila in filas:
        src = construir_src_portada(fila['Portada'], fila['Portada_nombre'])
        if src:
            estreno, hasta, _ = obtener_rango_fechas_emision(fila['Fechas_emision'], fila['Fecha_estreno'])
            portadas.append(
                {
                    'id': fila['rowid'],
                    'nombre': fila['Nombre'],
                    'src': src,
                    'estreno': formatear_fecha_corta(estreno),
                    'hasta': formatear_fecha_corta(hasta) if hasta and hasta != estreno else '',
                }
            )

    return render(
        request,
        'Portadas.html',
        {
            'portadas': portadas,
            'usuario': request.session['usuario'],
        },
    )


def add_pelicula(request):
    if not _requiere_admin_activo(request):
        return redirect('ingresar_admin')
    if request.method != 'POST':
        return redirect('admin_panel')

    form = PeliculaCreateForm(request.POST, limpiar_archivos_vacios(request.FILES))
    if not form.is_valid():
        return HttpResponseBadRequest(f"Datos invalidos ({formatear_errores_formulario(form)})")

    datos = form.cleaned_data
    programacion_emision = datos.get('programacion_emision') or {}
    fechas_emision = fechas_desde_programacion_emision(programacion_emision)
    fecha_estreno = fechas_emision[0] if fechas_emision else None
    fechas_emision_texto = ','.join(fechas_emision)
    programacion_emision_texto = serializar_programacion_emision(programacion_emision) if programacion_emision else ''
    portada_archivo = datos.get('portada')
    portada_bytes = None
    portada_nombre = None

    if portada_archivo:
        portada_nombre = get_valid_filename(portada_archivo.name)
        portada_bytes = portada_archivo.read()

    ensure_fechas_emision_schema()
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO PELICULAS (Nombre, Proveedor, Generos, Clasificacion, Duracion, Descripcion, Calificacion, Fecha_estreno, Fechas_emision, Programacion_emision, Portada, Portada_nombre) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            datos['nombre'],
            datos['proveedor'],
            datos['generos'],
            datos['clasificacion'],
            datos['duracion'],
            datos['descripcion'],
            datos['calificacion'],
            fecha_estreno,
            fechas_emision_texto,
            programacion_emision_texto,
            portada_bytes,
            portada_nombre,
        ),
    )
    conn.commit()
    conn.close()
    return redirect('admin_panel')


def edit_pelicula(request):
    if not _requiere_admin_activo(request):
        return redirect('ingresar_admin')
    if request.method != 'POST':
        return redirect('admin_panel')

    form = PeliculaEditForm(request.POST, limpiar_archivos_vacios(request.FILES))
    if not form.is_valid():
        return HttpResponseBadRequest(f"Datos invalidos ({formatear_errores_formulario(form)})")

    datos = form.cleaned_data
    pelicula_id = datos['id']
    programacion_emision = datos.get('programacion_emision') or {}
    fechas_emision = fechas_desde_programacion_emision(programacion_emision)
    fecha_estreno = fechas_emision[0] if fechas_emision else None
    fechas_emision_texto = ','.join(fechas_emision)
    programacion_emision_texto = serializar_programacion_emision(programacion_emision) if programacion_emision else ''
    portada_archivo = datos.get('portada')
    eliminar_portada = bool(datos.get('eliminar_portada'))
    portada_bytes = None
    portada_nombre = None

    if portada_archivo:
        portada_nombre = get_valid_filename(portada_archivo.name)
        portada_bytes = portada_archivo.read()

    ensure_fechas_emision_schema()
    conn = get_db_connection()
    if not programacion_emision:
        fila_actual = conn.execute(
            'SELECT Fecha_estreno, Fechas_emision, Programacion_emision FROM PELICULAS WHERE rowid=?',
            (pelicula_id,),
        ).fetchone()
        if fila_actual:
            fecha_estreno = fila_actual['Fecha_estreno']
            fechas_emision_texto = fila_actual['Fechas_emision']
            programacion_emision_texto = fila_actual['Programacion_emision']

    if eliminar_portada:
        conn.execute(
            'UPDATE PELICULAS SET Nombre=?, Proveedor=?, Generos=?, Clasificacion=?, Duracion=?, Descripcion=?, Calificacion=?, Fecha_estreno=?, Fechas_emision=?, Programacion_emision=? WHERE rowid=?',
            (
                datos['nombre'],
                datos['proveedor'],
                datos['generos'],
                datos['clasificacion'],
                datos['duracion'],
                datos['descripcion'],
                datos['calificacion'],
                fecha_estreno,
                fechas_emision_texto,
                programacion_emision_texto,
                pelicula_id,
            ),
        )
        conn.commit()
        conn.close()

        eliminar_portada_por_rowid(pelicula_id)
        return redirect('admin_panel')

    if portada_bytes is not None:
        conn.execute(
            'UPDATE PELICULAS SET Nombre=?, Proveedor=?, Generos=?, Clasificacion=?, Duracion=?, Descripcion=?, Calificacion=?, Fecha_estreno=?, Fechas_emision=?, Programacion_emision=?, Portada=?, Portada_nombre=? WHERE rowid=?',
            (
                datos['nombre'],
                datos['proveedor'],
                datos['generos'],
                datos['clasificacion'],
                datos['duracion'],
                datos['descripcion'],
                datos['calificacion'],
                fecha_estreno,
                fechas_emision_texto,
                programacion_emision_texto,
                portada_bytes,
                portada_nombre,
                pelicula_id,
            ),
        )
    else:
        conn.execute(
            'UPDATE PELICULAS SET Nombre=?, Proveedor=?, Generos=?, Clasificacion=?, Duracion=?, Descripcion=?, Calificacion=?, Fecha_estreno=?, Fechas_emision=?, Programacion_emision=?, Portada=CASE WHEN Portada = "" THEN NULL ELSE Portada END WHERE rowid=?',
            (
                datos['nombre'],
                datos['proveedor'],
                datos['generos'],
                datos['clasificacion'],
                datos['duracion'],
                datos['descripcion'],
                datos['calificacion'],
                fecha_estreno,
                fechas_emision_texto,
                programacion_emision_texto,
                pelicula_id,
            ),
        )
    conn.commit()
    conn.close()
    return redirect('admin_panel')


def delete_pelicula(request):
    if not _requiere_admin_activo(request):
        return redirect('ingresar_admin')
    if request.method != 'POST':
        return redirect('admin_panel')

    pelicula_id = int(request.POST['id'])
    conn = get_db_connection()
    conn.execute('DELETE FROM PELICULAS WHERE rowid=?', (pelicula_id,))
    conn.commit()
    conn.close()
    return redirect('admin_panel')


def logout(request):
    request.session.pop('usuario', None)
    request.session.pop('rol', None)
    request.session.pop('cliente_gmail', None)
    return redirect('main')
