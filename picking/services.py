"""Reglas de negocio: disponibilidad, creación de pedidos, ruta de picking y doble verificación."""
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from inventario.models import StockLote

from .models import LineaOrden, Orden, PickLinea

FUTURO = 10 ** 9
ABIERTAS = [Orden.Estado.PENDIENTE, Orden.Estado.VERIFICACION]


# --------------------------------------------------------------------------- roles
def tiene_rol(user, nombre):
    return user.is_superuser or user.groups.filter(name=nombre).exists()


def es_supervisor(user):
    return tiene_rol(user, "Supervisor")


def puede_operar(user):
    return user.is_authenticated and (tiene_rol(user, "Operario") or es_supervisor(user))


# --------------------------------------------------------------------------- existencias
def stock_disponible(producto_ids):
    """{producto_id: (stock_total, comprometido, disponible)}.

    comprometido = lo pedido en órdenes abiertas que todavía no descontaron stock.
    """
    ids = list(producto_ids)
    stock = dict(StockLote.objects.filter(producto_id__in=ids)
                 .values("producto_id").annotate(t=Sum("total_unidades")).values_list("producto_id", "t"))
    comp = dict(LineaOrden.objects.filter(producto_id__in=ids, orden__estado__in=ABIERTAS)
                .values("producto_id").annotate(t=Sum("cantidad_pedida")).values_list("producto_id", "t"))
    return {i: (stock.get(i, 0), comp.get(i, 0), max(0, stock.get(i, 0) - comp.get(i, 0))) for i in ids}


def siguiente_numero():
    base = f"OC-{timezone.localdate():%y%m%d}"
    n = Orden.objects.filter(numero__startswith=base).count() + 1
    while Orden.objects.filter(numero=f"{base}-{n:02d}").exists():
        n += 1
    return f"{base}-{n:02d}"


@transaction.atomic
def crear_orden(user, cliente, numero, fecha_compromiso, items):
    """items: {Producto: unidades}. Devuelve la Orden creada."""
    orden = Orden.objects.create(numero=numero, cliente=cliente, fecha=timezone.localdate(),
                                 fecha_compromiso=fecha_compromiso, creada_por=user)
    LineaOrden.objects.bulk_create(
        [LineaOrden(orden=orden, producto=p, cantidad_pedida=u) for p, u in items.items()])
    return orden


# --------------------------------------------------------------------------- ruta de picking
def _clave_fefo(lote):
    # Primero lo que vence antes; sin fecha al final. Desempate por ruta.
    return (lote.fecha_vencimiento is None, lote.fecha_vencimiento or FUTURO,
            lote.ubicacion.clave_ruta(settings.PICKING_SERPENTINA))


def generar_picking(orden):
    """(Re)crea las PickLinea de una orden. Devuelve cuántas líneas quedaron sin stock."""
    orden.picks.all().delete()
    filas = []
    faltantes = 0
    for linea in orden.lineas.select_related("producto"):
        lotes = list(StockLote.objects.filter(producto=linea.producto, total_unidades__gt=0)
                     .select_related("ubicacion", "producto"))
        lotes.sort(key=_clave_fefo)
        pendiente = linea.cantidad_pedida
        for lote in lotes:
            if pendiente <= 0:
                break
            tomar = min(pendiente, lote.total_unidades)
            filas.append(PickLinea(
                orden=orden, linea=linea, stock=lote, ubicacion=lote.ubicacion,
                lote=lote.lote, fecha_vencimiento=lote.fecha_vencimiento,
                semaforo=lote.semaforo, cantidad_a_tomar=tomar,
            ))
            pendiente -= tomar
        if pendiente > 0:
            faltantes += 1
            filas.append(PickLinea(orden=orden, linea=linea, cantidad_a_tomar=pendiente, semaforo="rojo"))

    # Orden final de la ruta: ubicación (A -> J), faltantes al final
    filas.sort(key=lambda f: (f.ubicacion is None,
                              f.ubicacion.clave_ruta(settings.PICKING_SERPENTINA) if f.ubicacion else ()))
    for i, f in enumerate(filas, start=1):
        f.secuencia = i
    PickLinea.objects.bulk_create(filas)
    return faltantes


# --------------------------------------------------------------------------- verificaciones
def _exigir_excepcion(user, excepcion, nota):
    return es_supervisor(user) and excepcion and nota.strip()


@transaction.atomic
def primera_verificacion(orden, user, conteos, excepcion=False, nota=""):
    """1ª verificación (quien hace el picking): lo contado debe coincidir con lo que correspondía.

    conteos: {pick_id: int}. Devuelve (ok, [problemas]).
    """
    if orden.estado != Orden.Estado.PENDIENTE:
        return False, ["La orden no está en 1ª verificación."]
    problemas = []
    for p in orden.picks.select_related("linea__producto", "ubicacion"):
        if p.es_faltante:
            problemas.append(f"{p.linea.producto.sku}: sin stock suficiente (faltan {p.cantidad_a_tomar} un).")
            continue
        p.cantidad_verificada = conteos.get(p.id)
        p.save(update_fields=["cantidad_verificada"])
        donde = f"{p.linea.producto.sku} en {p.ubicacion.codigo}"
        if p.cantidad_verificada is None:
            problemas.append(f"{donde}: sin contar.")
        elif p.cantidad_verificada != p.cantidad_a_tomar:
            problemas.append(f"{donde}: contaste {p.cantidad_verificada}, corresponden {p.cantidad_a_tomar}.")
        if p.semaforo == "rojo":
            problemas.append(f"{donde}: vencimiento en rojo.")

    if problemas:
        if not _exigir_excepcion(user, excepcion, nota):
            return False, problemas
        orden.excepcion = True
        orden.nota_supervisor = nota.strip()
        orden.picks.filter(cantidad_verificada__isnull=True, ubicacion__isnull=False).update(cantidad_verificada=0)
    orden.estado = Orden.Estado.VERIFICACION
    orden.primera_por = user
    orden.primera_en = timezone.now()
    orden.save()
    return True, problemas


@transaction.atomic
def segunda_verificacion(orden, user, conteos, excepcion=False, nota=""):
    """2ª verificación (ciega, otra persona): su conteo debe coincidir con el 1º. Si coincide, aprueba."""
    if orden.estado != Orden.Estado.VERIFICACION:
        return False, ["La orden no está esperando la 2ª verificación."]
    if orden.primera_por_id == user.id and not es_supervisor(user):
        return False, ["La 2ª verificación la debe hacer otra persona distinta de quien hizo la 1ª."]
    problemas = []
    for p in orden.picks.select_related("linea__producto", "ubicacion"):
        if p.es_faltante:
            continue
        p.cantidad_segunda = conteos.get(p.id)
        p.save(update_fields=["cantidad_segunda"])
        donde = f"{p.linea.producto.sku} en {p.ubicacion.codigo}"
        if p.cantidad_segunda is None:
            problemas.append(f"{donde}: sin contar.")
        elif p.cantidad_segunda != p.cantidad_verificada:
            problemas.append(f"{donde}: el 2º conteo no coincide con el 1º. Vuelve a contar.")

    if problemas:
        if not _exigir_excepcion(user, excepcion, nota):
            return False, problemas
        orden.excepcion = True
        orden.nota_supervisor = (orden.nota_supervisor + " | " if orden.nota_supervisor else "") + nota.strip()
        orden.picks.filter(cantidad_segunda__isnull=True, ubicacion__isnull=False).update(cantidad_segunda=0)
    orden.estado = Orden.Estado.APROBADA
    orden.aprobada_por = user
    orden.aprobada_en = timezone.now()
    orden.save()
    descontar_stock(orden)
    return True, problemas


def descontar_stock(orden):
    """Resta del stock lo realmente contado (2º conteo). Idempotente."""
    for p in orden.picks.select_related("linea__producto"):
        if p.descontado or p.es_faltante or not p.cantidad_segunda:
            continue
        lotes = StockLote.objects.select_for_update()
        # Si el stock se re-importó, el vínculo directo se perdió: se busca por producto+ubicación+lote
        lote = (lotes.filter(pk=p.stock_id).first() if p.stock_id else None) or lotes.filter(
            producto=p.linea.producto, ubicacion=p.ubicacion, lote=p.lote).first()
        if lote is None:
            continue  # la ubicación ya no existe en el stock actual: queda para revisión manual
        lote.total_unidades -= min(p.cantidad_segunda, lote.total_unidades)
        upc = p.linea.producto.unidades_por_caja or 1
        lote.cajas, lote.unidades_sueltas = divmod(lote.total_unidades, upc)
        lote.save()
        p.descontado = True
        p.save(update_fields=["descontado"])
