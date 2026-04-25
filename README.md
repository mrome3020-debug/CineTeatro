# CineTeatro
# Proyecto CineTeatro

Aplicación web de cartelera y reservas construida con Django+ Python + SQLite, con dos áreas principales:

- Vista pública/cliente: cartelera, detalle de funciones y reservas.
- Vista de administración: gestión de películas, programación (fecha/horario) y portadas.

## Función de cada archivo

### Raíz del proyecto

- `Main.py`: controlador principal de la app pública. Define las vistas para:
  - mostrar cartelera (`main_view`),
  - iniciar sesión/registro de usuarios,
  - reservar entradas,
  - listar y cancelar reservas.
  También prepara datos para renderizar `templates/Main.html`.

- `Main_admin.py`: controlador del panel de administración. Define vistas para:
  - mostrar el panel admin,
  - consultar disponibilidad de horarios por fecha,
  - agregar/editar/eliminar películas,
  - visualizar galería de portadas,
  - cerrar sesión.

- `DB.py`: capa de acceso a datos y reglas de negocio. Incluye:
  - conexión SQLite,
  - creación/ajuste de esquema (clientes, administradores, reservas y columnas de películas),
  - autenticación/registro,
  - manejo de reservas,
  - parseo/normalización de fechas y programación,
  - validaciones de conflictos de horario,
  - formularios Django (`PeliculaCreateForm`, `PeliculaEditForm`).

- `Fechas.py`: utilidades de calendario. Genera fechas seleccionables (mes actual y siguiente), valida fechas no pasadas y ofrece métodos de visualización en consola.

- `Horarios.py`: define los horarios disponibles (`Horario 1`, `Horario 2`, `Horario 3`) y funciones auxiliares para obtenerlos por lista o por nombre.

- `Salas.py`: define el modelo simple de salas y crea las salas disponibles (`Sala Principal`, `Mini Cine`) con cantidad de asientos.

- `Validacion.py`: script de validación por consola (credenciales de ejemplo) para administradores. Es una utilidad independiente del flujo web Django.

- `manage.py`: entrypoint estándar de Django para comandos de administración (`runserver`, migraciones, etc.).

- `requirements.txt`: dependencias Python del proyecto.

- `db.sqlite3`: base de datos SQLite usada por Django según `cineteatro/settings.py`.

- `Peliculas.db`: base de datos SQLite usada por la lógica de negocio en `DB.py` (películas, usuarios y reservas del sistema).

### Carpeta `cineteatro/`

- `cineteatro/settings.py`: configuración global de Django:
  - apps instaladas,
  - middleware,
  - templates,
  - base de datos por defecto (`db.sqlite3`),
  - estáticos,
  - configuración SMTP (Gmail) leída desde `.env`.

- `cineteatro/urls.py`: enrutador principal de URLs. Mapea endpoints públicos y de administración a funciones de `Main.py` y `Main_admin.py`.

- `cineteatro/asgi.py`: punto de entrada ASGI para despliegue asíncrono.

- `cineteatro/wsgi.py`: punto de entrada WSGI para despliegue tradicional.

- `cineteatro/__init__.py`: archivo de paquete Python (vacío).

### Carpeta `templates/`

- `templates/Main.html`: interfaz principal para usuarios/clientes. Muestra cartelera, información de películas, funciones y acciones de reserva.

- `templates/login.html`: pantalla de acceso con pestañas de iniciar sesión y registrarse (cliente/admin).

- `templates/Main_admin.html`: layout/base del panel de administración (estructura general, menú y estilos comunes).

- `templates/admin_peliculas.html`: vista admin específica para gestión de películas. Incluye formularios y lógica visual para alta/edición, selección de programación y acciones sobre portadas.

- `templates/Portadas.html`: galería de portadas cargadas, con controles para ajustar dimensiones de visualización y regreso al panel admin.

- `templates/Fechas.html`: plantilla de calendario visual estático de ejemplo para selección de fechas.

## Nota rápida de arquitectura

Actualmente conviven dos archivos SQLite (`db.sqlite3` y `Peliculas.db`) con roles distintos en el código. Si se desea simplificar mantenimiento, conviene unificar la persistencia a una sola base de datos en una futura mejora.
