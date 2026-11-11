from django.contrib import admin

from .models import LineaOrden, Orden, PickLinea


class LineaInline(admin.TabularInline):
    model = LineaOrden
    extra = 1
    raw_id_fields = ("producto",)


@admin.register(Orden)
class OrdenAdmin(admin.ModelAdmin):
    list_display = ("numero", "cliente", "fecha", "fecha_compromiso", "estado", "es_vencida", "excepcion")
    list_filter = ("estado", "excepcion")
    search_fields = ("numero", "cliente")
    inlines = [LineaInline]

    @admin.display(boolean=True, description="Vencida")
    def es_vencida(self, obj):
        return obj.vencida


@admin.register(PickLinea)
class PickLineaAdmin(admin.ModelAdmin):
    list_display = ("orden", "secuencia", "linea", "ubicacion", "cantidad_a_tomar",
                    "cantidad_verificada", "cantidad_segunda", "semaforo")
    list_filter = ("semaforo",)
