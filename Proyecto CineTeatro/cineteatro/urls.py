from django.urls import path

import Main
import Main_admin


urlpatterns = [
    path('', Main.main_view, name='main'),
    path('espectaculo/<int:espectaculo_id>/', Main.detalle_espectaculo_view, name='detalle_espectaculo'),
    path('ingresar_admin/', Main.ingresar_admin, name='ingresar_admin'),
    path('validar_admin/', Main.validar_admin_web, name='validar_admin'),
    path('admin/', Main_admin.admin, name='admin_panel'),
    path('portadas/', Main_admin.ver_portadas, name='ver_portadas'),
    path('disponibilidad_emision/', Main_admin.obtener_disponibilidad_emision, name='disponibilidad_emision'),
    path('add_pelicula/', Main_admin.add_pelicula, name='add_pelicula'),
    path('edit_pelicula/', Main_admin.edit_pelicula, name='edit_pelicula'),
    path('delete_pelicula/', Main_admin.delete_pelicula, name='delete_pelicula'),
    path('add_show/', Main_admin.add_show, name='add_show'),
    path('edit_show/', Main_admin.edit_show, name='edit_show'),
    path('add_teatro/', Main_admin.add_teatro, name='add_teatro'),
    path('edit_teatro/', Main_admin.edit_teatro, name='edit_teatro'),
    path('add_exposicion/', Main_admin.add_exposicion, name='add_exposicion'),
    path('edit_exposicion/', Main_admin.edit_exposicion, name='edit_exposicion'),
    path('logout/', Main_admin.logout, name='logout'),
]
