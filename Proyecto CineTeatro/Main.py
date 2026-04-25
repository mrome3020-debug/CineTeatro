import os
import sys
import base64

from django.http import JsonResponse
from django.shortcuts import redirect, render

from Salas import salas
from Horarios import obtener_horarios_disponibles, obtener_horario
from DB import (
	autenticar_cliente,
	autenticar_administrador,
	cancelar_reserva_usuario,
	crear_reserva_entrada,
	es_registro_admin,
	es_gmail_valido,
	formatear_fecha_corta,
	parsear_programacion_emision,
	obtener_reservas_por_usuario,
	obtener_peliculas_para_main,
	obtener_rango_fechas_emision,
	registrar_administrador,
	registrar_cliente,
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


def main_view(request):
	usuario_actual = request.session.get('usuario', 'Invitado')
	rol_actual = request.session.get('rol', '')
	puede_reservar = rol_actual == 'cliente'
	horarios_disponibles = obtener_horarios_disponibles()
	horarios_por_nombre = {horario.nombre: horario for horario in horarios_disponibles}
	peliculas_raw = obtener_peliculas_para_main(limit=40)
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

		peliculas.append(
			{
				'nombre': pelicula['Nombre'],
				'generos': pelicula['Generos'],
				'clasificacion': pelicula['Clasificacion'],
				'duracion': formatear_duracion_corta(pelicula['Duracion']),
				'calificacion': pelicula['Calificacion'],
				'fecha_estreno': formatear_fecha_corta(fecha_inicio),
				'fecha_hasta': formatear_fecha_corta(fecha_fin) if fecha_fin and fecha_fin != fecha_inicio else '',
				'programacion_detalle': programacion_detalle,
				'portada_src': construir_src_portada(pelicula['Portada'], pelicula['Portada_nombre']),
			}
		)

	return render(
		request,
		'Main.html',
		{
			'salas': salas,
			'horarios': horarios_disponibles,
			'peliculas': peliculas,
			'usuario_actual': usuario_actual,
			'puede_reservar': puede_reservar,
			'precio_entrada': 200,
		},
	)


def reservar_entrada_web(request):
	if request.method != 'POST':
		return JsonResponse({'ok': False, 'error': 'Metodo no permitido.'}, status=405)

	if request.session.get('rol') != 'cliente':
		return JsonResponse({'ok': False, 'error': 'Solo los usuarios registrados como Clientes pueden reservar entradas.'}, status=403)

	pelicula = request.POST.get('pelicula', '').strip()
	fecha_funcion = request.POST.get('fecha_funcion', '').strip()
	horario_funcion = formatear_horario_ticket(request.POST.get('horario_funcion', '').strip())
	if not pelicula:
		return JsonResponse({'ok': False, 'error': 'Debes seleccionar una pelicula.'}, status=400)
	if not fecha_funcion or not horario_funcion:
		return JsonResponse({'ok': False, 'error': 'Debes seleccionar fecha y horario de función.'}, status=400)

	usuario = request.session.get('usuario', 'Invitado')
	reserva = crear_reserva_entrada(usuario, pelicula, fecha_funcion=fecha_funcion, horario_funcion=horario_funcion, precio=200)
	if reserva is None:
		return JsonResponse({'ok': False, 'error': 'No hay entradas disponibles para esta función.'}, status=409)

	return JsonResponse({'ok': True, 'reserva': reserva})


def entradas_reservadas_web(request):
	if request.session.get('rol') != 'cliente':
		return JsonResponse({'ok': False, 'error': 'Solo los Clientes pueden ver reservas.'}, status=403)

	usuario = request.session.get('usuario', 'Invitado')
	reservas = obtener_reservas_por_usuario(usuario)
	for reserva in reservas:
		reserva['horario_funcion'] = formatear_horario_ticket(reserva.get('horario_funcion'))
	return JsonResponse({'ok': True, 'usuario': usuario, 'reservas': reservas})


def cancelar_reserva_web(request):
	if request.method != 'POST':
		return JsonResponse({'ok': False, 'error': 'Metodo no permitido.'}, status=405)

	if request.session.get('rol') != 'cliente':
		return JsonResponse({'ok': False, 'error': 'Solo los Clientes pueden cancelar reservas.'}, status=403)

	usuario = request.session.get('usuario', 'Invitado')
	reserva_id_raw = request.POST.get('reserva_id', '').strip()

	if not reserva_id_raw.isdigit():
		return JsonResponse({'ok': False, 'error': 'Reserva inválida.'}, status=400)

	reserva_id = int(reserva_id_raw)
	ok = cancelar_reserva_usuario(usuario, reserva_id)
	if not ok:
		return JsonResponse({'ok': False, 'error': 'No se pudo cancelar la reserva.'}, status=404)

	return JsonResponse({'ok': True})


def ingresar_admin(request):
	return _render_login(request)


def _render_login(
	request,
	error=None,
	registro_error=None,
	registro_ok=None,
	active_tab='login',
):
	return render(
		request,
		'login.html',
		{
			'error': error,
			'registro_error': registro_error,
			'registro_ok': registro_ok,
			'active_tab': active_tab,
		},
	)


def validar_admin_web(request):
	if request.method != 'POST':
		return redirect('ingresar_admin')

	usuario = request.POST.get('usuario', '').strip()
	contrasena = request.POST.get('contraseña', '').strip()

	admin = autenticar_administrador(usuario, contrasena)
	if admin:
		request.session['usuario'] = admin['nombre']
		request.session['rol'] = 'admin'
		return redirect('admin_panel')

	cliente = autenticar_cliente(usuario, contrasena)
	if cliente:
		request.session['usuario'] = cliente['usuario']
		request.session['rol'] = 'cliente'
		request.session['cliente_gmail'] = cliente['gmail']
		return redirect('main')

	return _render_login(request, error='Usuario o contraseña incorrectos.', active_tab='login')


def registrar_cliente_web(request):
	if request.method != 'POST':
		return redirect('ingresar_admin')

	gmail = request.POST.get('gmail', '').strip().lower()
	usuario = request.POST.get('nuevo_usuario', '').strip()
	contrasena = request.POST.get('nueva_contraseña', '').strip()
	confirmacion = request.POST.get('confirmar_contraseña', '').strip()

	if not gmail or not usuario or not contrasena or not confirmacion:
		return _render_login(request, registro_error='Todos los campos de registro son obligatorios.', active_tab='register')

	if not es_gmail_valido(gmail):
		return _render_login(request, registro_error='Debes ingresar un Gmail válido con formato usuario@gmail.com.', active_tab='register')

	if len(contrasena) < 8:
		return _render_login(request, registro_error='La contraseña debe tener al menos 8 caracteres.', active_tab='register')

	if contrasena != confirmacion:
		return _render_login(request, registro_error='La contraseña y su confirmación no coinciden.', active_tab='register')

	if es_registro_admin(usuario, contrasena):
		ok, mensaje = registrar_administrador(gmail, usuario, contrasena, nombre=usuario)
		if not ok:
			return _render_login(request, registro_error=mensaje, active_tab='register')
		return _render_login(
			request,
			registro_ok='Registro exitoso como Administrador. Ahora puedes ingresar con tu usuario o Gmail y contraseña.',
			active_tab='register',
		)

	ok, mensaje = registrar_cliente(gmail, usuario, contrasena)

	if not ok:
		return _render_login(request, registro_error=mensaje, active_tab='register')

	return _render_login(
		request,
		registro_ok='Registro exitoso. Ahora puedes ingresar con tu usuario o Gmail y contraseña.',
		active_tab='register',
	)


if __name__ == '__main__':
	main()
