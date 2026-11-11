from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea los grupos de usuario: Operario (hace picking) y Supervisor (autoriza excepciones)."

    def handle(self, *args, **o):
        for nombre in ("Operario", "Supervisor"):
            _, creado = Group.objects.get_or_create(name=nombre)
            self.stdout.write(f"{'Creado' if creado else 'Ya existía'}: {nombre}")
        self.stdout.write("Asigna usuarios a los grupos desde /admin (Usuarios -> Grupos).")
