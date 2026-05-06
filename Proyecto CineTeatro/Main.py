import os
import sys
import base64

from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render

from Salas import salas
from Horarios import obtener_horarios_disponibles, obtener_horario
from DB import (
	autenticar_administrador,
	es_registro_admin,
	es_gmail_valido,
	formatear_fecha_corta,
	parsear_programacion_emision,
	obtener_peliculas_para_main,
	obtener_rango_fechas_emision,
	registrar_administrador,
)


def main():
	os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cineteatro.settings')
	from django.core.management import execute_from_command_line
	argv = sys.argv if len(sys.argv) > 1 else [sys.argv[0], 'runserver']
	execute_from_command_line(argv)


def obtener_mime(nombre_archivo):
	extension = nombre_archivo.rsplit('.', 1)[1].lower() if nombre_archivo and '.' in nombre_archivo else ''
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
		mime = obtener_mime(portada_nombre or 'imagen.jpg')
		encoded = base64.b64encode(portada).decode('utf-8')
		return f"data:{mime};base64,{encoded}"
	if isinstance(portada, str):
		return portada
	return None


def formatear_duracion_corta(duracion):
	valor = str(duracion).strip()
	if not valor:
		return ''
	if ':' in valor:
		partes = valor.split(':')
		if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
			return f"{int(partes[0]):02d}:{int(partes[1]):02d} h"
	return f"{valor} h"


def formatear_horario_ticket(valor_horario):
	valor = str(valor_horario or '').strip()
	if not valor:
		return ''

	horario = obtener_horario(valor)
	if horario is not None:
		return f"{horario.inicio} - {horario.fin}"

	if '(' in valor and ')' in valor:
		inicio = valor.find('(')
		fin = valor.find(')', inicio + 1)
		if fin > inicio:
			return valor[inicio + 1:fin].strip()

	return valor


def _normalizar_tipo_espectaculo(valor_tipo):
	valor = str(valor_tipo or '').strip().lower()
	if valor in ('show', 'teatro', 'exposicion', 'exposición'):
		return 'exposicion' if valor in ('exposicion', 'exposición') else valor
	if valor in ('pelicula', 'película'):
		return 'pelicula'
	return 'pelicula'


def _mapear_peliculas_para_vistas(limit=40, rowid=None):
	horarios_disponibles = obtener_horarios_disponibles()
	horarios_por_nombre = {horario.nombre: horario for horario in horarios_disponibles}
	peliculas_raw = obtener_peliculas_para_main(limit=limit, rowid=rowid)
	peliculas = []

	for pelicula in peliculas_raw:
		fecha_inicio, fecha_fin, _ = obtener_rango_fechas_emision(pelicula['Fechas_emision'], pelicula['Fecha_estreno'])
		programacion = parsear_programacion_emision(pelicula['Programacion_emision'])
		programacion_detalle = []
		for fecha, horarios in programacion.items():
			horarios_formateados = []
			for nombre_horario in horarios:
				horario = horarios_por_nombre.get(nombre_horario)
				if horario is None:
					horarios_formateados.append({'nombre': nombre_horario, 'inicio': '', 'fin': ''})
				else:
					horarios_formateados.append({'nombre': horario.nombre, 'inicio': horario.inicio, 'fin': horario.fin})
			programacion_detalle.append({'fecha': formatear_fecha_corta(fecha), 'horarios': horarios_formateados})

		tipo_normalizado = _normalizar_tipo_espectaculo(pelicula['tipo_espectaculo'])
		peliculas.append(
			{
				'id': pelicula['rowid'],
				'nombre': pelicula['Nombre'],
				'proveedor': pelicula['Proveedor'],
				'generos': pelicula['Generos'],
				'clasificacion': pelicula['Clasificacion'],
				'duracion': formatear_duracion_corta(pelicula['Duracion']),
				'descripcion': pelicula['Descripcion'] or '',
				'calificacion': pelicula['Calificacion'],
				'fecha_estreno': formatear_fecha_corta(fecha_inicio),
				'fecha_hasta': formatear_fecha_corta(fecha_fin) if fecha_fin and fecha_fin != fecha_inicio else '',
				'programacion_detalle': programacion_detalle,
				'portada_src': construir_src_portada(pelicula['Portada'], pelicula['Portada_nombre']),
				'tipo_espectaculo': tipo_normalizado,
				'artista_show': pelicula['artista_show'] or '',
				'ambientacion_teatro': pelicula['ambientacion_teatro'] or '',
			}
		)

	return peliculas, horarios_disponibles


def main_view(request):
	usuario_actual = request.session.get('usuario', 'Invitado')
	peliculas, horarios_disponibles = _mapear_peliculas_para_vistas(limit=40)

	return render(
		request,
		'Main.html',
		{
			'salas': salas,
			'horarios': horarios_disponibles,
			'peliculas': peliculas,
			'usuario_actual': usuario_actual,
		},
	)


def detalle_espectaculo_view(request, espectaculo_id):
	peliculas, _ = _mapear_peliculas_para_vistas(rowid=espectaculo_id)
	espectaculo = peliculas[0] if peliculas else None
	if espectaculo is None:
		raise Http404('Espectaculo no encontrado.')

	return render(
		request,
		'espectaculo_detalle.html',
		{
			'espectaculo': espectaculo,
		},
	)


def ingresar_admin(request):
	return _render_login(request)


def _render_login(
	request,
	error=None,
	registro_error=None,
	registro_ok=None,
	active_tab='login',
	login_mode='admin',
):
	return render(
		request,
		'login.html',
		{
			'error': error,
			'registro_error': registro_error,
			'registro_ok': registro_ok,
			'active_tab': active_tab,
			'login_mode': login_mode,
		},
	)


def validar_admin_web(request):
	if request.method != 'POST':
		return redirect('ingresar_admin')

	usuario = request.POST.get('usuario', '').strip()
	contrasena = request.POST.get('contraseña', '').strip()
	tipo_login = request.POST.get('tipo_login', 'admin').strip().lower()

	if tipo_login == 'admin':
		admin = autenticar_administrador(usuario, contrasena)
		if admin:
			request.session['usuario'] = admin['nombre']
			request.session['rol'] = 'admin'
			return redirect('admin_panel')
		return _render_login(
			request,
			error='Credenciales de Administrador incorrectas.',
			active_tab='login',
			login_mode='admin',
		)

	return _render_login(
		request,
		error='Tipo de ingreso inválido.',
		active_tab='login',
		login_mode='admin',
	)


if __name__ == '__main__':
	main()
