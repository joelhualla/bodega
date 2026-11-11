# Bodega · Pedidos, picking y doble verificación (Django)

## Instalación (Windows PowerShell, dentro de la carpeta que contiene manage.py)
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations inventario picking
python manage.py migrate
python manage.py createsuperuser
python manage.py crear_roles
python manage.py importar_erp --stock datos/STOCK_POR_FAMILIA_.xlsx --racks datos/RACKS.xlsx --maestro datos/MAESTRO_LAYOUT.xlsx --dry-run
python manage.py importar_erp --stock datos/STOCK_POR_FAMILIA_.xlsx --racks datos/RACKS.xlsx --maestro datos/MAESTRO_LAYOUT.xlsx
python manage.py importar_ordenes datos/ejemplo_ordenes.csv     # opcional: órdenes de ejemplo
python manage.py runserver
```
Abre http://127.0.0.1:8000/ e ingresa con tu usuario.
Usuarios nuevos: /admin → Usuarios → marcar **Staff status** y asignar grupo **Operario** o **Supervisor**.

## Encender el sistema (doble clic)
Doble clic en **iniciar.bat** (junto a manage.py). Hace el respaldo diario, enciende el sistema y abre el navegador.
**No cierres la ventana negra mientras lo uses.** Para apagarlo, ciérrala. Ingreso: http://127.0.0.1:8000/ (pantalla de login propia).

## Respaldos
- Se hace uno automático (máx. 1 por día) cada vez que usas **iniciar.bat**, en la carpeta `respaldos/` (se conservan los últimos 30).
- Para hacer uno ahora: doble clic en **respaldar.bat**.
- Copia en otro lugar (pendrive, disco D:, OneDrive): en `config/settings.py` descomenta y ajusta `RESPALDOS_COPIA_EXTRA`.
- **Restaurar**: apaga el sistema, copia un archivo de `respaldos/`, pégalo en la carpeta del sistema, borra `db.sqlite3`
  y renombra la copia a `db.sqlite3`.

## Usuarios
Los usuarios ya NO necesitan "Staff status". Se crean en /admin → Usuarios, asignando el grupo **Operario** o **Supervisor**
(el grupo debe quedar en la columna de la derecha antes de guardar). Sin grupo, el sistema muestra "Tu usuario no tiene un rol asignado".

## Cuando llegan reportes nuevos del ERP (la forma fácil)
Entra como **Supervisor** → menú **⬆ Cargar ERP** → sube el Excel de **Stock** y el de **Racks** (y el **Maestro** solo si cambió)
→ **Revisar** (no guarda nada) → **Confirmar**. Es lo mismo que el comando `importar_erp`, pero con pantalla.

## Requerimientos ↔ dónde están
| Requerimiento | Dónde / cómo |
|---|---|
| Integrar información del ERP | `importar_erp` (stock, racks, maestro). Tolera datos incompletos y deja bitácora |
| Identificar órdenes vencidas | Lista de órdenes: filtro **⚠ Vencidas** (fecha compromiso pasada y orden no aprobada) |
| Identificar vencimientos | Semáforo por lote (verde/amarillo/rojo, `settings.py`), FEFO, y pantalla **Calidad de datos** |
| Controlar existencias | "Disponible" = stock − comprometido en pedidos abiertos; se descuenta al aprobar |
| Validar pedidos | Formulario de pedido avisa si no alcanza el stock; el picking marca SIN STOCK |
| Ruta de picking | Líneas ordenadas por ubicación (A→J, posición, nivel); opción serpentina en settings |
| Segunda verificación | 1ª: operario cuenta y compara. 2ª: **otra persona**, conteo ciego, debe coincidir con la 1ª |

## Pedidos
Menú **➕ Nuevo pedido**: busca por nombre/SKU o escanea; por cada producto se ponen **cajas**, **unidades sueltas** o ambas
(el sistema suma). Así no importa si el cliente pide en cajas o en unidades.

## Roles
- **Operario**: crea pedidos, hace picking y verificaciones.
- **Supervisor**: además autoriza excepciones (con nota), regenera rutas y ve **Calidad de datos**.

## Ajustes (`config/settings.py`)
`SEMAFORO_ROJO_DIAS`, `SEMAFORO_AMARILLO_DIAS`, `PICKING_SERPENTINA`.

## Limitaciones conocidas
- El stock se descuenta al aprobar; cada `importar_erp` reemplaza todo con la foto del ERP. Importa cuando el ERP
  ya refleje los despachos, o el stock descontado "se recupera".
- Los reportes de racks actuales no traen lote ni fecha de vencimiento.
- Falta el reporte de **detalle de pedidos** del ERP (PEDIDO, SKU, CANTIDAD); por eso los pedidos se crean en pantalla.
