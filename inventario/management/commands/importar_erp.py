"""Uso:
    python manage.py importar_erp --stock datos/STOCK_POR_FAMILIA_.xlsx --racks datos/RACKS.xlsx \
        --maestro datos/MAESTRO_LAYOUT.xlsx [--dry-run]

Es lo mismo que hace la pantalla "Cargar ERP" del sistema (Supervisor).
"""
from django.core.management.base import BaseCommand, CommandError

from inventario.cargador import ErrorCarga, cargar_erp


class Command(BaseCommand):
    help = "Importa STOCK_POR_FAMILIA, RACKS y (opcional) el maestro de productos del ERP."

    def add_arguments(self, parser):
        parser.add_argument("--stock", required=True, help="Excel STOCK_POR_FAMILIA")
        parser.add_argument("--racks", required=True, help="Excel RACKS")
        parser.add_argument("--maestro", help="Excel con la hoja BD (EAN, DUN, FACTOR, FAMILIA, CADUCA)")
        parser.add_argument("--dry-run", action="store_true", help="Valida y muestra el informe sin guardar")

    def handle(self, *args, **o):
        try:
            res = cargar_erp(o["stock"], o["racks"], o["maestro"], guardar=not o["dry_run"])
        except ErrorCarga as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.MIGRATE_HEADING("Informe de calidad de datos"))
        self.stdout.write(f"  Productos en stock: {res['n_productos_stock']} | filas de racks: {res['n_filas_racks']} | "
                          f"ubicaciones: {res['n_ubicaciones']}")
        for a in res["avisos"]:
            self.stdout.write(self.style.WARNING("  " + a))
        if o["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry-run: no se guardó nada."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Listo: {res['productos_total']} productos, {res['ubicaciones_total']} ubicaciones, "
                f"{res['registros_total']} registros de stock."))
