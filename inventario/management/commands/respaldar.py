"""Respaldo de la base de datos SQLite (se puede hacer con el sistema encendido).

    python manage.py respaldar            -> hace un respaldo ahora
    python manage.py respaldar --diario   -> solo si hoy todavía no se hizo uno (lo usa iniciar.bat)

Guarda copias en settings.RESPALDOS_DIR y, si está configurada, también en RESPALDOS_COPIA_EXTRA.
Mantiene los últimos 30 respaldos (--mantener) y borra los más antiguos.
"""
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Hace un respaldo de la base de datos."

    def add_arguments(self, parser):
        parser.add_argument("--diario", action="store_true", help="Solo si hoy no hay un respaldo hecho")
        parser.add_argument("--mantener", type=int, default=30, help="Cuántos respaldos conservar (30)")

    def handle(self, *args, **o):
        db = settings.DATABASES["default"]
        if not db["ENGINE"].endswith("sqlite3"):
            raise CommandError("Este respaldo es solo para SQLite. Con PostgreSQL usa pg_dump.")
        origen = Path(db["NAME"])
        if not origen.exists():
            raise CommandError(f"No encuentro la base de datos en {origen}")

        principal = Path(settings.RESPALDOS_DIR)
        principal.mkdir(parents=True, exist_ok=True)
        hoy = datetime.now().strftime("%Y%m%d")
        if o["diario"] and any(principal.glob(f"db_{hoy}_*.sqlite3")):
            self.stdout.write("Ya hay un respaldo de hoy. No se hace otro.")
            return

        nombre = f"db_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
        destino = principal / nombre
        # API de respaldo de SQLite: es segura aunque el sistema esté en uso
        src, dst = sqlite3.connect(str(origen)), sqlite3.connect(str(destino))
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()
        self.stdout.write(self.style.SUCCESS(f"Respaldo creado: {destino}"))

        carpetas = [principal]
        extra = getattr(settings, "RESPALDOS_COPIA_EXTRA", None)
        if extra:
            try:
                Path(extra).mkdir(parents=True, exist_ok=True)
                shutil.copy2(destino, Path(extra) / nombre)
                carpetas.append(Path(extra))
                self.stdout.write(self.style.SUCCESS(f"Copia extra creada: {Path(extra) / nombre}"))
            except OSError as e:
                self.stderr.write(f"AVISO: no pude guardar la copia extra en {extra}: {e}")

        for carpeta in carpetas:
            viejos = sorted(carpeta.glob("db_*.sqlite3"))[:-o["mantener"]]
            for f in viejos:
                try:
                    f.unlink()
                except OSError:
                    pass
