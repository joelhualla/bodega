import re
import shutil
import uuid
from functools import wraps
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from django.utils import timezone

from inventario import cargador
from inventario.models import Importacion, Producto, StockLote

from . import services
from .models import Orden

def operario(vista):
    """Exige haber iniciado sesión y tener un rol (Operario o Supervisor). Sin rol: página clara, sin rebotes."""
    @wraps(vista)
    def interna(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not services.puede_operar(request.user):
            return render(request, "picking/sin_rol.html", status=403)
        return vista(request, *args, **kwargs)
    return interna


# ------------------------------------------------------------------ lista de órdenes
@login_required
@operario
def lista_ordenes(request):
    filtro = request.GET.get("f", "abiertas")
    todas = list(Orden.objects.prefetch_related("lineas"))
    cuentas = {
        "abiertas": sum(1 for o in todas if o.estado != Orden.Estado.APROBADA),
        "vencidas": sum(1 for o in todas if o.vencida),
        "aprobadas": sum(1 for o in todas if o.estado == Orden.Estado.APROBADA),
        "todas": len(todas),
    }
    if filtro == "vencidas":
        ordenes = [o for o in todas if o.vencida]
    elif filtro == "aprobadas":
        ordenes = [o for o in todas if o.estado == Orden.Estado.APROBADA]
    elif filtro == "todas":
        ordenes = todas
    else:
        filtro = "abiertas"
        ordenes = [o for o in todas if o.estado != Orden.Estado.APROBADA]
    # Vencidas primero, luego por fecha compromiso más cercana
    ordenes.sort(key=lambda o: (not o.vencida, o.estado == Orden.Estado.APROBADA,
                                o.fecha_compromiso or date.max))
    return render(request, "picking/ordenes.html", {"ordenes": ordenes, "filtro": filtro, "cuentas": cuentas})


# ------------------------------------------------------------------ nuevo pedido
def _entero(txt):
    txt = (txt or "").strip()
    return int(txt) if txt.isdigit() else 0


@login_required
@operario
def nuevo_pedido(request):
    previo = []
    datos = {"cliente": "", "numero": "", "compromiso": (date.today() + timedelta(days=1)).isoformat()}
    if request.method == "POST":
        datos = {"cliente": request.POST.get("cliente", "").strip(),
                 "numero": request.POST.get("numero", "").strip(),
                 "compromiso": request.POST.get("compromiso", "").strip()}
        skus = request.POST.getlist("sku")
        cajas = request.POST.getlist("cajas")
        sueltas = request.POST.getlist("unidades")
        prods = {p.sku: p for p in Producto.objects.filter(sku__in=skus)}
        items, errores = {}, []
        for sku, c, u in zip(skus, cajas, sueltas):
            p = prods.get(sku)
            if not p:
                errores.append(f"Producto {sku} no encontrado.")
                continue
            total = _entero(c) * (p.unidades_por_caja or 1) + _entero(u)
            if total > 0:
                items[p] = items.get(p, 0) + total
        disp = services.stock_disponible([p.id for p in items]) if items else {}
        previo = [{"sku": p.sku, "nombre": p.nombre, "upc": p.unidades_por_caja, "disp": disp[p.id][2], "erp": p.stock_erp_unidades,
                   "ubicado": disp[p.id][0], "cajas": 0, "unidades": total} for p, total in items.items()]
        # al volver con errores se muestra todo en unidades sueltas (equivalente y sin pérdida)

        if not datos["cliente"]:
            errores.append("Falta el cliente.")
        if not items:
            errores.append("Agrega al menos un producto con cantidad.")
        compromiso = None
        if datos["compromiso"]:
            try:
                compromiso = date.fromisoformat(datos["compromiso"])
            except ValueError:
                errores.append("La fecha compromiso no es válida.")
        numero = datos["numero"] or services.siguiente_numero()
        if Orden.objects.filter(numero=numero).exists():
            errores.append(f"Ya existe una orden con el número {numero}.")

        if not errores:
            avisos = [f"{p.sku}: pides {u} un y hay {disp[p.id][2]} disponibles."
                      for p, u in items.items() if u > disp[p.id][2]]
            orden = services.crear_orden(request.user, datos["cliente"], numero, compromiso, items)
            messages.success(request, f"Pedido {orden.numero} creado con {len(items)} producto(s).")
            for a in avisos:
                messages.warning(request, "Stock insuficiente → " + a)
            return redirect("ordenes")
        for e in errores:
            messages.error(request, e)
    return render(request, "picking/pedido_nuevo.html", {"datos": datos, "previo": previo,
                                                         "numero_sugerido": services.siguiente_numero()})


@login_required
@operario
@require_GET
def buscar_productos(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"resultados": []})
    filtro = Q(sku__icontains=q) | Q(nombre__icontains=q) | Q(ean=q) | Q(dun=q)
    if q.isdigit() and len(q) >= 8:  # la pistola a veces entrega el código sin el cero inicial
        filtro |= Q(ean__endswith=q.lstrip("0")) | Q(dun__endswith=q.lstrip("0"))
    prods = list(Producto.objects.filter(filtro)[:12])
    disp = services.stock_disponible([p.id for p in prods])
    return JsonResponse({"resultados": [{
        "sku": p.sku, "nombre": p.nombre, "familia": p.familia, "upc": p.unidades_por_caja,
        "disp": disp[p.id][2], "erp": p.stock_erp_unidades, "ubicado": disp[p.id][0], "exacto": q.upper() == p.sku or q in (p.ean, p.dun) or
        (q.isdigit() and len(q) >= 8 and q.lstrip("0") in (p.ean.lstrip("0"), p.dun.lstrip("0"))),
    } for p in prods]})


# ------------------------------------------------------------------ picking y verificaciones
@login_required
@operario
def picking(request, pk):
    orden = get_object_or_404(Orden, pk=pk)
    if orden.estado == Orden.Estado.PENDIENTE and not orden.picks.exists():
        services.generar_picking(orden)
    modo = {"pendiente": "primera", "verificacion": "segunda"}.get(orden.estado, "lectura")
    return render(request, "picking/picking.html", {
        "orden": orden,
        "picks": orden.picks.select_related("linea__producto", "ubicacion"),
        "modo": modo,
        "misma_persona": orden.primera_por_id == request.user.id and not services.es_supervisor(request.user),
    })


@login_required
@operario
@require_POST
def verificar(request, pk):
    orden = get_object_or_404(Orden, pk=pk)
    if orden.estado == Orden.Estado.APROBADA:
        messages.info(request, "La orden ya estaba aprobada.")
        return redirect("picking", pk=pk)

    conteos = {int(k[2:]): int(v) for k, v in request.POST.items()
               if k.startswith("v_") and k[2:].isdigit() and v.strip().isdigit()}
    paso = services.primera_verificacion if orden.estado == Orden.Estado.PENDIENTE \
        else services.segunda_verificacion
    ok, problemas = paso(orden, request.user, conteos,
                         excepcion=request.POST.get("excepcion") == "on", nota=request.POST.get("nota", ""))
    if ok:
        if orden.estado == Orden.Estado.APROBADA:
            messages.success(request, f"Orden {orden.numero} aprobada tras la 2ª verificación.")
        else:
            messages.success(request, f"1ª verificación lista. Ahora OTRA persona debe hacer la 2ª verificación de {orden.numero}.")
        return redirect("ordenes")
    for p in problemas:
        messages.error(request, p)
    if services.es_supervisor(request.user):
        messages.warning(request, "Como Supervisor puedes marcar 'Autorizar excepción' y dejar una nota.")
    else:
        messages.warning(request, "Hay diferencias: corrige el conteo o avisa a un Supervisor.")
    return redirect("picking", pk=pk)


@login_required
@operario
@require_POST
def regenerar(request, pk):
    orden = get_object_or_404(Orden, pk=pk)
    if orden.estado == Orden.Estado.PENDIENTE and services.es_supervisor(request.user):
        faltantes = services.generar_picking(orden)
        messages.success(request, f"Ruta regenerada ({faltantes} línea(s) sin stock).")
    return redirect("picking", pk=pk)


# ------------------------------------------------------------------ calidad de datos del ERP
@login_required
@operario
def calidad(request):
    if not services.es_supervisor(request.user):
        messages.error(request, "Esta pantalla es solo para Supervisores.")
        return redirect("ordenes")
    hoy = date.today()
    con_stock = Producto.objects.filter(lotes__total_unidades__gt=0).distinct()
    sin_ean, sin_dun, sin_maestro = (con_stock.filter(ean=""), con_stock.filter(dun=""),
                                     con_stock.filter(en_maestro=False))
    caducan_sin_fecha = StockLote.objects.filter(
        producto__caduca=True, fecha_vencimiento__isnull=True, total_unidades__gt=0
    ).select_related("producto", "ubicacion")
    por_vencer = StockLote.objects.filter(
        fecha_vencimiento__isnull=False, total_unidades__gt=0,
        fecha_vencimiento__lte=hoy + timedelta(days=settings.SEMAFORO_AMARILLO_DIAS),
    ).order_by("fecha_vencimiento").select_related("producto", "ubicacion")
    ultima = Importacion.objects.first()
    return render(request, "picking/calidad.html", {
        "ultima": ultima,
        "avisos": ultima.advertencias.splitlines() if ultima else [],
        "sin_ean": sin_ean[:40], "n_sin_ean": sin_ean.count(),
        "sin_dun": sin_dun[:40], "n_sin_dun": sin_dun.count(),
        "sin_maestro": sin_maestro[:40], "n_sin_maestro": sin_maestro.count(),
        "caducan_sin_fecha": caducan_sin_fecha[:40], "n_caducan_sin_fecha": caducan_sin_fecha.count(),
        "por_vencer": por_vencer[:60], "n_por_vencer": por_vencer.count(),
    })


# ------------------------------------------------------------------ stock actual (ERP vs ubicado)
@login_required
@operario
def stock(request):
    q = request.GET.get("q", "").strip()
    f = request.GET.get("f", "todo")
    qs = Producto.objects.annotate(ubicado=Sum("lotes__total_unidades")).prefetch_related("lotes__ubicacion")
    qs = qs.filter(Q(stock_erp_unidades__gt=0) | Q(ubicado__gt=0))
    if q:
        qs = qs.filter(Q(sku__icontains=q) | Q(nombre__icontains=q) | Q(ean=q) | Q(dun=q))
    filas = []
    for p in qs.order_by("sku"):
        p.ubic = p.ubicado or 0
        p.sin_ubicar = max(0, p.stock_erp_unidades - p.ubic)
        upc = p.unidades_por_caja or 1
        p.erp_cajas, p.erp_sueltas = divmod(p.stock_erp_unidades, upc)
        p.donde = [f"{l.ubicacion.codigo} ({l.total_unidades})" for l in p.lotes.all() if l.total_unidades > 0]
        filas.append(p)
    total = {"erp": sum(p.stock_erp_unidades for p in filas), "ubicado": sum(p.ubic for p in filas),
             "sin_ubicar": sum(1 for p in filas if p.stock_erp_unidades > 0 and p.ubic == 0), "n": len(filas)}
    if f == "sin_ubicar":
        filas = [p for p in filas if p.stock_erp_unidades > 0 and p.ubic == 0]
    elif f == "ubicados":
        filas = [p for p in filas if p.ubic > 0]
    return render(request, "picking/stock.html", {
        "filas": filas[:300], "n_filas": len(filas), "q": q, "filtro": f, "total": total,
        "ultima": Importacion.objects.first(),
    })


# ------------------------------------------------------------------ cargar reportes del ERP (3 pasos)
MAX_MB = 25


@login_required
@operario
def cargar_erp(request):
    if not services.es_supervisor(request.user):
        messages.error(request, "Cargar el ERP es solo para Supervisores.")
        return redirect("ordenes")
    cargador.limpiar_cargas()
    ultima = Importacion.objects.first()
    ctx = {"paso": "form", "ultima": ultima, "historial": Importacion.objects.all()[:5],
           "dias": (timezone.now() - ultima.fecha).days if ultima else None}

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "revisar":
            archivos = {n: request.FILES.get(n) for n in ("stock", "racks", "maestro")}
            errores = [f"Falta el archivo de {n}." for n in ("stock", "racks") if not archivos[n]]
            for n, f in archivos.items():
                if f and not f.name.lower().endswith((".xlsx", ".xlsm")):
                    errores.append(f"El archivo de {n} debe ser Excel (.xlsx).")
                if f and f.size > MAX_MB * 1024 * 1024:
                    errores.append(f"El archivo de {n} pesa más de {MAX_MB} MB.")
            if errores:
                for e in errores:
                    messages.error(request, e)
                return render(request, "picking/cargar_erp.html", ctx)
            token = uuid.uuid4().hex
            carpeta = settings.CARGAS_DIR / token
            carpeta.mkdir(parents=True)
            rutas = {}
            for n, f in archivos.items():
                if f:
                    rutas[n] = carpeta / f"{n}.xlsx"
                    with open(rutas[n], "wb") as fh:
                        for trozo in f.chunks():
                            fh.write(trozo)
            try:
                res = cargador.cargar_erp(str(rutas["stock"]), str(rutas["racks"]),
                                          str(rutas["maestro"]) if "maestro" in rutas else None, guardar=False)
            except cargador.ErrorCarga as e:
                shutil.rmtree(carpeta, ignore_errors=True)
                messages.error(request, str(e))
                return render(request, "picking/cargar_erp.html", ctx)
            ctx.update(paso="revision", res=res, token=token,
                       nombres={n: f.name for n, f in archivos.items() if f})
        elif accion == "confirmar":
            token = request.POST.get("token", "")
            carpeta = settings.CARGAS_DIR / token
            if not re.fullmatch(r"[0-9a-f]{32}", token) or not carpeta.is_dir():
                messages.error(request, "La revisión expiró. Vuelve a subir los archivos.")
                return render(request, "picking/cargar_erp.html", ctx)
            rutas = {n: carpeta / f"{n}.xlsx" for n in ("stock", "racks", "maestro") if (carpeta / f"{n}.xlsx").exists()}
            etiqueta = request.POST.get("etiqueta", "")[:480]
            try:
                res = cargador.cargar_erp(str(rutas["stock"]), str(rutas["racks"]),
                                          str(rutas["maestro"]) if "maestro" in rutas else None,
                                          guardar=True, etiqueta_archivos=etiqueta or None)
            except cargador.ErrorCarga as e:
                messages.error(request, str(e))
                return render(request, "picking/cargar_erp.html", ctx)
            finally:
                shutil.rmtree(carpeta, ignore_errors=True)
            ctx.update(paso="listo", res=res, ultima=Importacion.objects.first(), dias=0,
                       historial=Importacion.objects.all()[:5])
    return render(request, "picking/cargar_erp.html", ctx)
