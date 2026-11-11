"""Núcleo de la carga de reportes del ERP. Lo usan el comando `importar_erp` y la pantalla web.

Filosofía: el ERP manda y puede venir incompleto. Nunca se detiene por datos faltantes: los carga,
los marca y los deja a la vista. Cada carga es una foto del stock (reemplaza StockLote en una transacción).
"""
import shutil
import time

from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from . import importers as im
from .models import Importacion, Producto, StockLote, Ubicacion


class ErrorCarga(Exception):
    """Error que se le puede mostrar tal cual a la persona (archivo ilegible, columna faltante...)."""


def limpiar_cargas(horas=24):
    """Borra las carpetas temporales de cargas abandonadas."""
    base = settings.CARGAS_DIR
    if not base.exists():
        return
    limite = time.time() - horas * 3600
    for d in base.iterdir():
        if d.is_dir() and d.stat().st_mtime < limite:
            shutil.rmtree(d, ignore_errors=True)


def cargar_erp(stock_path, racks_path, maestro_path=None, guardar=True, etiqueta_archivos=None):
    """Revisa (guardar=False) o carga (guardar=True) los reportes. Devuelve un dict con el resumen."""
    try:
        stock = im.leer_stock(stock_path)
        racks = im.leer_racks(racks_path)
        maestro = im.leer_maestro(maestro_path) if maestro_path else {}
    except ValueError as e:
        raise ErrorCarga(f"{e} Revisa que hayas subido cada reporte en su casilla (Stock con Stock, Racks con Racks).")
    except Exception as e:  # archivo que no es Excel, dañado, etc.
        raise ErrorCarga(f"No pude leer los archivos. ¿Son los Excel correctos? ({type(e).__name__})")
    if not stock:
        raise ErrorCarga("El archivo de stock no tiene filas con productos.")
    if not racks:
        raise ErrorCarga("El archivo de racks no tiene filas con ubicaciones.")

    upc = im.unidades_por_caja(stock, racks)
    avisos = []
    factor_distinto = []
    for sku, m in maestro.items():
        if m.factor:
            if sku in upc and upc[sku] != m.factor:
                factor_distinto.append((sku, upc[sku], m.factor))
                avisos.append(f"Unidades por caja distintas en {sku}: inferido={upc[sku]}, maestro={m.factor} (se usa el maestro)")
            upc[sku] = m.factor

    ubic, corregidas = {}, []
    for cod in dict.fromkeys(r.ubicacion for r in racks):
        try:
            norm, pas, pos, niv, orig = im.normalizar_ubicacion(cod)
        except ValueError as e:
            raise ErrorCarga(str(e))
        ubic[cod] = (norm, pas, pos, niv)
        if orig:
            corregidas.append((orig, norm))
            avisos.append(f"Ubicación corregida: {orig} -> {norm}")

    info = im.validar(stock, racks)
    skus_stock = {s.sku for s in stock}
    skus_racks = {r.sku for r in racks}
    sin_ubicacion = sorted(skus_stock - skus_racks)
    caducan = ({sku for sku, m in maestro.items() if m.caduca} if maestro
               else set(Producto.objects.filter(caduca=True).values_list("sku", flat=True)))
    caducan_sin_fecha = sum(1 for r in racks if r.sku in caducan and r.vcto is None)

    if info["skus_en_racks_sin_stock"]:
        avisos.append(f"SKUs en racks que no están en el archivo de stock: {', '.join(info['skus_en_racks_sin_stock'])}")
    avisos.append(f"SKUs con descuadre racks vs stock: {len(info['descuadre_racks_vs_stock'])}")
    avisos.append(f"Productos del stock sin ubicación en racks: {len(sin_ubicacion)}")
    avisos.append(f"Filas de racks sin fecha de vencimiento: {info['sin_vencimiento']} de {info['filas_racks']}")
    if maestro:
        avisos.append(f"SKUs de racks sin maestro: {len(skus_racks - set(maestro))}")
        avisos.append(f"SKUs de racks con EAN / DUN: {sum(1 for s in skus_racks if s in maestro and maestro[s].ean)} / "
                      f"{sum(1 for s in skus_racks if s in maestro and maestro[s].dun)} de {len(skus_racks)}")

    antes = StockLote.objects.aggregate(t=Sum("total_unidades"))["t"] or 0
    res = {
        "guardado": False,
        "n_productos_stock": len(stock), "n_filas_racks": len(racks),
        "n_ubicaciones": len(set(v[0] for v in ubic.values())),
        "n_con_ubicacion": len(skus_stock & skus_racks), "n_sin_ubicacion": len(sin_ubicacion),
        "sin_ubicacion_ejemplos": sin_ubicacion[:12],
        "racks_sin_stock": info["skus_en_racks_sin_stock"],
        "n_descuadre": len(info["descuadre_racks_vs_stock"]),
        "descuadre_ejemplos": info["descuadre_racks_vs_stock"][:8],
        "ubicaciones_corregidas": corregidas, "factor_distinto": factor_distinto,
        "n_caducan_sin_fecha": caducan_sin_fecha, "n_sin_vencimiento": info["sin_vencimiento"],
        "n_maestro": len(maestro), "usa_maestro": bool(maestro),
        "unidades_antes": antes, "unidades_despues": sum(r.total for r in racks),
        "avisos": avisos,
    }
    res["hay_avisos"] = bool(res["n_sin_ubicacion"] or res["racks_sin_stock"] or res["n_descuadre"]
                             or res["n_caducan_sin_fecha"] or corregidas or factor_distinto)
    if not guardar:
        return res

    with transaction.atomic():
        nombres = {s.sku: s.nombre for s in stock}
        unidades_erp = {s.sku: s.unidades for s in stock}
        for r in racks:
            nombres.setdefault(r.sku, r.nombre)
        # Códigos de barras completados a mano: no se pisan con vacíos
        manual = {sku: (e, d) for sku, e, d in
                  Producto.objects.exclude(ean="", dun="").values_list("sku", "ean", "dun")}

        con_maestro, sin_maestro = {}, {}
        for sku, m in maestro.items():
            e0, d0 = manual.get(sku, ("", ""))
            con_maestro[sku] = dict(
                nombre=nombres.get(sku) or m.nombre, familia=m.familia or sku[:2],
                unidades_por_caja=upc.get(sku, 1), ean=m.ean or e0, dun=m.dun or d0,
                caduca=m.caduca, en_maestro=True, stock_erp_unidades=unidades_erp.get(sku, 0))
        for sku, nombre in nombres.items():
            if sku not in con_maestro:
                sin_maestro[sku] = dict(nombre=nombre, familia=sku[:2], unidades_por_caja=upc.get(sku, 1),
                                        stock_erp_unidades=unidades_erp.get(sku, 0))
        Producto.objects.bulk_create(
            [Producto(sku=k, **v) for k, v in con_maestro.items()],
            update_conflicts=True, unique_fields=["sku"],
            update_fields=["nombre", "familia", "unidades_por_caja", "ean", "dun", "caduca",
                           "en_maestro", "stock_erp_unidades"],
        )
        # Sin maestro: si ya existe, solo se actualiza nombre y stock (no se pisa lo ya completado)
        Producto.objects.bulk_create(
            [Producto(sku=k, **v) for k, v in sin_maestro.items()],
            update_conflicts=True, unique_fields=["sku"],
            update_fields=["nombre", "stock_erp_unidades"],
        )
        pmap = dict(Producto.objects.values_list("sku", "id"))

        Ubicacion.objects.bulk_create(
            [Ubicacion(codigo=n, pasillo=p, posicion=ps, nivel=nv) for n, p, ps, nv in set(ubic.values())],
            update_conflicts=True, unique_fields=["codigo"], update_fields=["pasillo", "posicion", "nivel"],
        )
        umap = dict(Ubicacion.objects.values_list("codigo", "id"))

        StockLote.objects.all().delete()
        StockLote.objects.bulk_create([
            StockLote(producto_id=pmap[r.sku], ubicacion_id=umap[ubic[r.ubicacion][0]], lote=r.lote or "",
                      fecha_vencimiento=r.vcto, cajas=r.cajas, unidades_sueltas=r.unidades,
                      total_unidades=r.total)
            for r in racks
        ])
        Importacion.objects.create(
            archivos=etiqueta_archivos or " | ".join(x for x in (stock_path, racks_path, maestro_path) if x),
            productos=Producto.objects.count(), ubicaciones=Ubicacion.objects.count(),
            registros_stock=StockLote.objects.count(), advertencias="\n".join(avisos))
    res.update(guardado=True, productos_total=Producto.objects.count(),
               ubicaciones_total=Ubicacion.objects.count(), registros_total=StockLote.objects.count())
    return res
