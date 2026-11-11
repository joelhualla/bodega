from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="picking/login.html",
                                                redirect_authenticated_user=True), name="login"),
    path("salir/", auth_views.LogoutView.as_view(), name="salir"),
    path("", views.lista_ordenes, name="ordenes"),
    path("pedido/nuevo/", views.nuevo_pedido, name="nuevo_pedido"),
    path("api/productos/", views.buscar_productos, name="buscar_productos"),
    path("orden/<int:pk>/", views.picking, name="picking"),
    path("orden/<int:pk>/verificar/", views.verificar, name="verificar"),
    path("orden/<int:pk>/regenerar/", views.regenerar, name="regenerar"),
    path("stock/", views.stock, name="stock"),
    path("cargar-erp/", views.cargar_erp, name="cargar_erp"),
    path("calidad/", views.calidad, name="calidad"),
]
