"""Lectura y normalización de los Excel/CSV del ERP y B2B (sin Django y sin pandas).

Usa solo openpyxl (Python puro): así Windows (Smart App Control) no bloquea nada.
"""
import csv
import re
import unicodedata
from collections import defaultdict, namedtuple
from datetime import date, datetime

from openpyxl import load_workbook

RE_UBIC = re.compile(r"^([A-Z])(\d{1,2})(\d{2})$")

Stock = namedtuple("Stock", "sku nombre familia unidades cajas")
Rack = namedtuple("Rack", "sku nombre ubicacion cajas unidades total vcto lote")
LineaPedido = namedtuple("LineaPedido", "orden cliente fecha compromiso sku cajas unidades")
Maestro = namedtuple("Maestro", "sku nombre familia ean dun factor caduca")


def _norm(texto):
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def _vacio(v):
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() in ("", "nan", "None")


def _num(v):
    if _vacio(v):
        return 0.0
    try:
        return float(str(v).replace(",", ".")) if isinstance(v, str) else float(v)
    except ValueError:
        return 0.0


def _int(v):
    return int(round(_num(v)))


def _texto(v):
    return "" if _vacio(v) else str(v).strip()


def normalizar_ubicacion(codigo):
    """Devuelve (codigo_normalizado, pasillo, posicion, nivel, corregido_desde|None).

    - 'BO0601' (letra O de más) -> 'B0601'
    - 'J101'   -> pasillo J, posición 1, nivel 01
    """
    original = str(codigo).strip().upper().replace(" ", "")
    limpio = original
    if re.match(r"^[A-Z]O\d{4}$", limpio):
        limpio = limpio[0] + limpio[2:]
    m = RE_UBIC.match(limpio)
    if not m:
        raise ValueError(f"Ubicación con formato no reconocido: {original!r}")
    pasillo, pos, nivel = m.group(1), int(m.group(2)), int(m.group(3))
    return limpio, pasillo, pos, nivel, (original if original != limpio else None)


def parse_fecha(valor):
    """Fecha de vencimiento: acepta date/datetime, 20261029, '29/10/2026', '=0', 0, vacío."""
    if _vacio(valor):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    txt = str(valor).strip().lstrip("=")
    if txt.endswith(".0"):
        txt = txt[:-2]
    if txt in ("", "0"):
        return None
    if re.fullmatch(r"\d{8}", txt):
        return datetime.strptime(txt, "%Y%m%d").date()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt[:10], fmt).date()
        except ValueError:
            pass
    return None


def _filas_excel(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        return [list(f) for f in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()


def _tabla(filas, primera_col):
    """Encuentra la fila de encabezado y devuelve ({nombre_normalizado: indice}, filas_de_datos)."""
    for i, f in enumerate(filas[:15]):
        if f and not _vacio(f[0]) and _norm(f[0]) == primera_col:
            cab = {}
            for j, c in enumerate(f):
                if not _vacio(c):
                    cab.setdefault(_norm(c), j)  # si hay columnas repetidas, gana la primera
            return cab, filas[i + 1:]
    raise ValueError(f"No encontré el encabezado (columna '{primera_col}') en las primeras filas.")


def _get(fila, cab, nombre):
    j = cab.get(nombre)
    return fila[j] if j is not None and j < len(fila) else None


def leer_stock(path):
    """STOCK_POR_FAMILIA: SKU, Nombre, Unidades, Cajas -> lista de Stock."""
    cab, datos = _tabla(_filas_excel(path), "sku")
    for req in ("nombre", "unidades", "cajas"):
        if req not in cab:
            raise ValueError(f"Al archivo de stock le falta la columna '{req}'.")
    out = []
    for f in datos:
        sku = _texto(_get(f, cab, "sku")).upper()
        if not sku:
            continue
        out.append(Stock(sku, _texto(_get(f, cab, "nombre")), sku[:2],
                         _int(_get(f, cab, "unidades")), _num(_get(f, cab, "cajas"))))
    return out


def leer_racks(path):
    """RACKS: una fila por SKU/ubicación. Detecta el encabezado (hay una fila vacía arriba)."""
    cab, datos = _tabla(_filas_excel(path), "idsku")
    for req in ("ubicacion", "cajas", "unidades", "totalunid"):
        if req not in cab:
            raise ValueError(f"Al archivo de racks le falta la columna '{req}'.")
    out = []
    for f in datos:
        sku = _texto(_get(f, cab, "idsku")).upper()
        ubic = _texto(_get(f, cab, "ubicacion"))
        if not sku or not ubic:
            continue
        out.append(Rack(
            sku, _texto(_get(f, cab, "descripcion")), ubic,
            _int(_get(f, cab, "cajas")), _int(_get(f, cab, "unidades")), _int(_get(f, cab, "totalunid")),
            parse_fecha(_get(f, cab, "fechavcto")), _texto(_get(f, cab, "lote")),
        ))
    return out


def _codigo(v):
    """EAN/DUN: devuelve solo dígitos; '', 0, '0' y 'sin codigo' -> ''."""
    if _vacio(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    txt = str(v).strip()
    return txt if txt.isdigit() and int(txt) != 0 else ""


def leer_maestro(path, hoja="BD"):
    """Maestro de productos (hoja BD): EAN (unidad), DUN (caja), FACTOR (un/caja), FAMILIA, CADUCA."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[hoja] if hoja in wb.sheetnames else wb.worksheets[0]
        filas = [list(f) for f in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    cab, datos = _tabla(filas, "sku")
    for req in ("descripcion", "ean", "dun", "factor"):
        if req not in cab:
            raise ValueError(f"A la hoja del maestro le falta la columna '{req}'.")
    out = {}
    for f in datos:
        sku = _texto(_get(f, cab, "sku")).upper()
        if not sku:
            continue
        factor = _int(_get(f, cab, "factor"))
        out[sku] = Maestro(
            sku, _texto(_get(f, cab, "descripcion")), _texto(_get(f, cab, "familia")),
            _codigo(_get(f, cab, "ean")), _codigo(_get(f, cab, "dun")),
            factor if factor >= 1 else None,
            _texto(_get(f, cab, "caduca")).upper() == "S",
        )
    return out


def leer_ordenes(path):
    """Órdenes del B2B (CSV o Excel). Columnas: orden, cliente, sku, cajas (+ fecha, unidades)."""
    if path.lower().endswith((".xlsx", ".xlsm")):
        filas = _filas_excel(path)
    else:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            muestra = fh.read(4096)
            fh.seek(0)
            try:
                dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t")
            except csv.Error:
                dialecto = csv.excel
            filas = [list(r) for r in csv.reader(fh, dialecto)]
    alias = {"orden": "orden", "oc": "orden", "numero": "orden", "cliente": "cliente",
             "sku": "sku", "cajas": "cajas", "unidades": "unidades", "fecha": "fecha",
             "fechacompromiso": "compromiso", "compromiso": "compromiso"}
    cab = {}
    for j, c in enumerate(filas[0] if filas else []):
        n = alias.get(_norm(c))
        if n:
            cab.setdefault(n, j)
    faltan = {"orden", "cliente", "sku", "cajas"} - set(cab)
    if faltan:
        raise ValueError(f"Faltan columnas: {', '.join(sorted(faltan))}")
    out = []
    for f in filas[1:]:
        sku = _texto(_get(f, cab, "sku")).upper()
        orden = _texto(_get(f, cab, "orden"))
        if not sku or not orden:
            continue
        out.append(LineaPedido(orden, _texto(_get(f, cab, "cliente")), parse_fecha(_get(f, cab, "fecha")),
                               parse_fecha(_get(f, cab, "compromiso")), sku, _num(_get(f, cab, "cajas")), _int(_get(f, cab, "unidades"))))
    return out


def unidades_por_caja(stock, racks):
    """{sku: unidades_por_caja}.

    1) Racks (exacto): (total - sueltas) / cajas cuando es entero.
    2) Stock: round(unidades / cajas). No se usa la descripción: '6X4PACK' sería 6 y la caja real es 24.
    """
    upc = {}
    for r in racks:
        if r.cajas > 0:
            v = (r.total - r.unidades) / r.cajas
            if v == int(v) and v >= 1:
                upc.setdefault(r.sku, int(v))
    for s in stock:
        if s.sku not in upc and s.cajas > 0:
            upc[s.sku] = max(1, int(round(s.unidades / s.cajas)))
    return upc


def validar(stock, racks):
    """Informe de calidad de datos (para mostrar al importar)."""
    en_stock = {s.sku: s.unidades for s in stock}
    total_racks = defaultdict(int)
    for r in racks:
        total_racks[r.sku] += r.total
    return {
        "skus_en_racks_sin_stock": sorted(set(total_racks) - set(en_stock)),
        "descuadre_racks_vs_stock": [
            (sku, t, en_stock[sku]) for sku, t in sorted(total_racks.items())
            if sku in en_stock and t != en_stock[sku]
        ],
        "sin_vencimiento": sum(1 for r in racks if r.vcto is None),
        "filas_racks": len(racks),
    }
