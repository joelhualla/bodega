from django.contrib import admin

from .models import Importacion, Producto, StockLote, Ubicacion


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("sku", "nombre", "familia", "unidades_por_caja", "ean", "dun", "caduca", "en_maestro", "stock_erp_unidades")
    search_fields = ("sku", "nombre", "ean", "dun")
    list_filter = ("familia", "caduca")


@admin.register(Ubicacion)
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ("codigo", "pasillo", "posicion", "nivel")
    list_filter = ("pasillo",)
    search_fields = ("codigo",)


@admin.register(StockLote)
class StockLoteAdmin(admin.ModelAdmin):
    list_display = ("producto", "ubicacion", "lote", "fecha_vencimiento", "cajas", "unidades_sueltas", "total_unidades")
    list_filter = ("ubicacion__pasillo",)
    search_fields = ("producto__sku", "producto__nombre", "lote")
    autocomplete_fields = ()


@admin.register(Importacion)
class ImportacionAdmin(admin.ModelAdmin):
    list_display = ("fecha", "productos", "ubicaciones", "registros_stock")
