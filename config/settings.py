from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "cambia-esto-en-produccion"
DEBUG = True
ALLOWED_HOSTS = ["*"]  # en producción: la IP/host del servidor de la bodega

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "inventario",
    "picking",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "picking.context.roles",
    ]},
}]

# --- Base de datos: SQLite para maquetar rápido -------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
# PostgreSQL (descomenta y ajusta cuando quieras pasar a producción):
# DATABASES = {"default": {
#     "ENGINE": "django.db.backends.postgresql",
#     "NAME": "bodega", "USER": "bodega", "PASSWORD": "...",
#     "HOST": "localhost", "PORT": "5432",
# }}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CARGAS_DIR = BASE_DIR / "cargas"   # archivos temporales de la pantalla "Cargar ERP"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# --- Respaldos de la base de datos (python manage.py respaldar) -----------
RESPALDOS_DIR = BASE_DIR / "respaldos"
# Segunda copia en OTRO lugar (pendrive, disco D:, carpeta de OneDrive...). Ejemplo:
# RESPALDOS_COPIA_EXTRA = r"D:\respaldos_bodega"
RESPALDOS_COPIA_EXTRA = None

# --- Reglas de negocio ---------------------------------------------------
# Semáforo de vencimientos (días que faltan para vencer)
SEMAFORO_ROJO_DIAS = 30       # <= 30 días: rojo (bloquea picking salvo Supervisor)
SEMAFORO_AMARILLO_DIAS = 90   # <= 90 días: amarillo (alerta visual)
# Recorrido en serpentina: pasillos pares se recorren al revés (evita volver al inicio)
PICKING_SERPENTINA = False
