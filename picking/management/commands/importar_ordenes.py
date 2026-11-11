"""Importa órdenes de compra desde CSV/Excel del B2B.

Columnas mínimas:  orden, cliente, sku, cajas      (opcionales: fecha, unidades)
Ejemplo:
    python manage.py importar_ordenes datos/ejemplo_ordenes.csv

Si una orden ya existe y está PENDIENTE, se reemplazan sus líneas. Si está APROBADA, se omite.
"""
from collections import defaultdict
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventario.importers import leer_ordenes
from inventario.models import Producto
from picking.models import LineaOrden, Orden


class Command(BaseCommand):
    help = "Importa órdenes de compra (CSV o Excel)."

    def add_arguments(self, parser):
        parser.add_argument("archivo")

    def handle(self, *args, archivo, **o):
        try:
            lineas = leer_ordenes(archivo)
        except FileNotFoundError:
            raise CommandError(f"No existe {archivo}")
        except ValueError as e:
            raise CommandError(str(e))

        prods = {p.sku: p for p in Producto.objects.filter(sku__in={l.sku for l in lineas})}
        desconocidos = sorted({l.sku for l in lineas} - set(prods))
        if desconocidos:
            self.stdout.write(self.style.WARNING(f"SKUs no encontrados (se omiten): {', '.join(desconocidos)}"))

        por_orden = defaultdict(list)
        for l in lineas:
            por_orden[l.orden].append(l)

        creadas = omitidas = 0
        with transaction.atomic():
            for numero, grupo in por_orden.items():
                orden, _ = Orden.objects.get_or_create(
                    numero=numero,
                    defaults={"cliente": grupo[0].cliente, "fecha": grupo[0].fecha or date.today(),
                              "fecha_compromiso": grupo[0].compromiso},
                )
                if orden.estado == Orden.Estado.APROBADA:
                    omitidas += 1
                    continue
                orden.lineas.all().delete()
                orden.picks.all().delete()
                acumulado = {}
                for l in grupo:
                    p = prods.get(l.sku)
                    if not p:
                        continue
                    unidades = int(round(l.cajas * p.unidades_por_caja)) + l.unidades
                    acumulado[p] = acumulado.get(p, 0) + unidades
                LineaOrden.objects.bulk_create(
                    [LineaOrden(orden=orden, producto=p, cantidad_pedida=u) for p, u in acumulado.items() if u > 0])
                creadas += 1
        self.stdout.write(self.style.SUCCESS(f"Órdenes cargadas: {creadas}. Omitidas por estar aprobadas: {omitidas}."))
