from datetime import date

from django.conf import settings
from django.db import models


class Producto(models.Model):
    sku = models.CharField(max_length=20, unique=True)
    nombre = models.CharField("Nombre / descripción", max_length=250)
    # Viene del maestro (VINOS, CERVEZA, WHISKY...). Sin maestro: prefijo del SKU.
    familia = models.CharField(max_length=40, blank=True, db_index=True)
    unidades_por_caja = models.PositiveIntegerField(default=1)
    ean = models.CharField(max_length=30, blank=True, db_index=True,
                           help_text="Código de barras de la UNIDAD (botella/lata).")
    dun = models.CharField(max_length=30, blank=True, db_index=True,
                           help_text="Código de barras de la CAJA (DUN-14).")
    caduca = models.BooleanField(default=False, help_text="Producto con fecha de vencimiento (maestro).")
    en_maestro = models.BooleanField(default=False, help_text="Aparece en el maestro de productos del ERP.")
    stock_erp_unidades = models.PositiveIntegerField(
        default=0, help_text="Stock total según STOCK_POR_FAMILIA (referencia ERP)."
    )

    class Meta:
        ordering = ["sku"]

    def __str__(self):
        return f"{self.sku} - {self.nombre}"


class Ubicacion(models.Model):
    """Código tipo A0101 = Pasillo A, posición 01, nivel 01 (J101 = J, 1, 01)."""

    codigo = models.CharField(max_length=10, unique=True)
    pasillo = models.CharField(max_length=2, db_index=True)
    posicion = models.PositiveSmallIntegerField()
    nivel = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["pasillo", "posicion", "nivel"]
        verbose_name_plural = "ubicaciones"

    def __str__(self):
        return self.codigo

    def clave_ruta(self, serpentina=False):
        """Clave de orden para el recorrido de picking."""
        pos = self.posicion
        if serpentina and (ord(self.pasillo[0]) - ord("A")) % 2 == 1:
            pos = -pos  # pasillos pares (B, D, ...) se recorren al revés
        return (self.pasillo, pos, self.nivel)


class StockLote(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="lotes")
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, related_name="lotes")
    lote = models.CharField(max_length=40, blank=True, default="")
    fecha_vencimiento = models.DateField(null=True, blank=True)
    cajas = models.PositiveIntegerField(default=0)
    unidades_sueltas = models.PositiveIntegerField(default=0)
    total_unidades = models.PositiveIntegerField(default=0)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["producto", "ubicacion", "lote"], name="uniq_producto_ubicacion_lote"
            )
        ]
        indexes = [models.Index(fields=["producto", "fecha_vencimiento"])]

    def __str__(self):
        return f"{self.producto.sku} @ {self.ubicacion.codigo} ({self.total_unidades} un)"

    @property
    def dias_para_vencer(self):
        if not self.fecha_vencimiento:
            return None
        return (self.fecha_vencimiento - date.today()).days

    @property
    def semaforo(self):
        d = self.dias_para_vencer
        if d is None:
            # Solo importa la fecha si el producto caduca; si no, "no aplica"
            return "sin_fecha" if self.producto.caduca else "no_aplica"
        if d <= settings.SEMAFORO_ROJO_DIAS:
            return "rojo"
        if d <= settings.SEMAFORO_AMARILLO_DIAS:
            return "amarillo"
        return "verde"


class Importacion(models.Model):
    """Bitácora de cada carga de reportes del ERP (para saber qué tan completa venía la información)."""

    fecha = models.DateTimeField(auto_now_add=True)
    archivos = models.CharField(max_length=500, blank=True)
    productos = models.PositiveIntegerField(default=0)
    ubicaciones = models.PositiveIntegerField(default=0)
    registros_stock = models.PositiveIntegerField(default=0)
    advertencias = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name_plural = "importaciones"

    def __str__(self):
        return f"Importación {self.fecha:%d/%m/%Y %H:%M}"
