from datetime import date

from django.conf import settings
from django.db import models

from inventario.models import Producto, StockLote, Ubicacion


class Orden(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente (1ª verificación)"
        VERIFICACION = "verificacion", "Falta 2ª verificación"
        APROBADA = "aprobada", "Aprobada"

    numero = models.CharField("N° orden de compra", max_length=40, unique=True)
    cliente = models.CharField(max_length=200)
    fecha = models.DateField(default=date.today)
    fecha_compromiso = models.DateField(null=True, blank=True, help_text="Fecha límite de entrega.")
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    # 1ª verificación (quien hace el picking)
    primera_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    primera_en = models.DateTimeField(null=True, blank=True)
    # 2ª verificación = aprobación final (otra persona)
    aprobada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    aprobada_en = models.DateTimeField(null=True, blank=True)
    excepcion = models.BooleanField(default=False, help_text="Aprobada por un Supervisor con diferencias.")
    nota_supervisor = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name_plural = "órdenes"

    def __str__(self):
        return f"OC {self.numero} - {self.cliente}"

    @property
    def vencida(self):
        """Orden aún no despachada cuya fecha compromiso ya pasó."""
        return (self.estado != self.Estado.APROBADA and self.fecha_compromiso is not None
                and self.fecha_compromiso < date.today())

    @property
    def dias_atraso(self):
        return (date.today() - self.fecha_compromiso).days if self.vencida else 0


class LineaOrden(models.Model):
    """Lo que pidió el cliente (siempre guardado en unidades)."""

    orden = models.ForeignKey(Orden, on_delete=models.CASCADE, related_name="lineas")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad_pedida = models.PositiveIntegerField("Unidades pedidas")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["orden", "producto"], name="uniq_orden_producto")]

    def __str__(self):
        return f"{self.orden.numero} · {self.producto.sku} x {self.cantidad_pedida}"


class PickLinea(models.Model):
    """De dónde sacar cada cantidad (FEFO + ruta) y los dos conteos del operario."""

    orden = models.ForeignKey(Orden, on_delete=models.CASCADE, related_name="picks")
    linea = models.ForeignKey(LineaOrden, on_delete=models.CASCADE, related_name="picks")
    stock = models.ForeignKey(StockLote, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ubicacion = models.ForeignKey(Ubicacion, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    lote = models.CharField(max_length=40, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    semaforo = models.CharField(max_length=10, default="sin_fecha")
    cantidad_a_tomar = models.PositiveIntegerField(help_text="Unidades")
    cantidad_verificada = models.PositiveIntegerField(null=True, blank=True, help_text="1er conteo")
    cantidad_segunda = models.PositiveIntegerField(null=True, blank=True, help_text="2º conteo (ciego)")
    secuencia = models.PositiveIntegerField(default=0, help_text="Orden en la ruta de picking")
    descontado = models.BooleanField(default=False, help_text="Ya se restó del stock al aprobar.")

    class Meta:
        ordering = ["secuencia"]

    @property
    def es_faltante(self):
        return self.ubicacion_id is None

    @property
    def cajas_y_sueltas(self):
        upc = self.linea.producto.unidades_por_caja or 1
        return divmod(self.cantidad_a_tomar, upc)
