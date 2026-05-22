import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=""):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    value = os.environ.get(name)
    if value in {None, ""}:
        return default
    return int(value)


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


def require_production_value(name, value, *, min_length=1):
    placeholders = {"", "change-me", "dev-only-change-me", "local-dev-change-me", "replace-with-authentik-client-id", "replace-with-authentik-client-secret"}
    if value in placeholders or value.startswith("replace-with-") or len(value) < min_length:
        raise ImproperlyConfigured(f"{name} must be set to a production value when DJANGO_DEBUG=false.")
    return value


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

if not DEBUG:
    require_production_value("DJANGO_SECRET_KEY", SECRET_KEY, min_length=50)
    if "*" in ALLOWED_HOSTS or not ALLOWED_HOSTS:
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must name your public host when DJANGO_DEBUG=false.")
    if not CSRF_TRUSTED_ORIGINS:
        raise ImproperlyConfigured("DJANGO_CSRF_TRUSTED_ORIGINS must include your public https origin when DJANGO_DEBUG=false.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "mozilla_django_oidc",
    "mixes.apps.MixesConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "mixes.logging.RequestLoggingMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "mixes.context_processors.static_version",
            ],
        },
    },
]

DATABASE_URL = env("DATABASE_URL")
if not DEBUG and not DATABASE_URL:
    raise ImproperlyConfigured("DATABASE_URL must be set when DJANGO_DEBUG=false.")
if DATABASE_URL:
    import urllib.parse

    parsed = urllib.parse.urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username,
            "PASSWORD": parsed.password,
            "HOST": parsed.hostname,
            "PORT": parsed.port or 5432,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TZ", "Australia/Brisbane")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "icons"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("DJMIX_MEDIA_ROOT", BASE_DIR / "media"))
APP_VERSION = env("APP_VERSION", "dev")

DJMIX_MAX_UPLOAD_BYTES = env_int("DJMIX_MAX_UPLOAD_BYTES", 3 * 1024 * 1024 * 1024)
DJMIX_MAX_COVER_PIXELS = env_int("DJMIX_MAX_COVER_PIXELS", 40_000_000)
DJMIX_COVER_LARGE_SIZE = env_int("DJMIX_COVER_LARGE_SIZE", 1600)
DJMIX_COVER_THUMB_SIZE = env_int("DJMIX_COVER_THUMB_SIZE", 480)
DJMIX_OPUS_BITRATE = env("DJMIX_OPUS_BITRATE", "128k")
DJMIX_MP3_BITRATE = env("DJMIX_MP3_BITRATE", "192k")
DJMIX_VIEW_DEDUPE_MINUTES = env_int("DJMIX_VIEW_DEDUPE_MINUTES", 30)
DJMIX_STREAM_DEDUPE_MINUTES = env_int("DJMIX_STREAM_DEDUPE_MINUTES", 360)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_VERSION = env("STATIC_VERSION", "20260518d")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "mixes.logging.JsonFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "mixes": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO"), "propagate": False},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}

OIDC_ENABLED = env_bool("OIDC_ENABLED", False)

LOGIN_REDIRECT_URL = "mixes:library"
LOGOUT_REDIRECT_URL = "mixes:home"
LOGIN_URL = "mixes:login"

AUTHENTICATION_BACKENDS = [
    "mixes.auth.AuthentikOIDCBackend",
    "django.contrib.auth.backends.ModelBackend",
]

OIDC_RP_CLIENT_ID = env("OIDC_RP_CLIENT_ID")
OIDC_RP_CLIENT_SECRET = env("OIDC_RP_CLIENT_SECRET")
OIDC_OP_AUTHORIZATION_ENDPOINT = env("OIDC_OP_AUTHORIZATION_ENDPOINT")
OIDC_OP_TOKEN_ENDPOINT = env("OIDC_OP_TOKEN_ENDPOINT")
OIDC_OP_USER_ENDPOINT = env("OIDC_OP_USER_ENDPOINT")
OIDC_OP_JWKS_ENDPOINT = env("OIDC_OP_JWKS_ENDPOINT")
OIDC_RP_SIGN_ALGO = env("OIDC_RP_SIGN_ALGO", "RS256")
OIDC_RP_SCOPES = env("OIDC_RP_SCOPES", "openid email profile")
OIDC_CREATE_USER = True
OIDC_USE_NONCE = True
OIDC_STORE_ACCESS_TOKEN = False
OIDC_STORE_ID_TOKEN = False

DJMIX_USER_GROUP = env("DJMIX_USER_GROUP", "djmix-users")
DJMIX_ADMIN_GROUP = env("DJMIX_ADMIN_GROUP", "djmix-admins")
DJMIX_REQUIRE_GROUP = env_bool("DJMIX_REQUIRE_GROUP", True)
DJMIX_INTERNAL_MEDIA_PREFIX = env("DJMIX_INTERNAL_MEDIA_PREFIX", "/protected-media/")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST", True)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_HTTPONLY = env_bool("SESSION_COOKIE_HTTPONLY", True)
SESSION_COOKIE_SAMESITE = env("SESSION_COOKIE_SAMESITE", "Lax")
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 60 * 60 * 24 * 7)
SESSION_SAVE_EVERY_REQUEST = env_bool("SESSION_SAVE_EVERY_REQUEST", False)
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool("SESSION_EXPIRE_AT_BROWSER_CLOSE", False)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SAMESITE = env("CSRF_COOKIE_SAMESITE", "Lax")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)

if not DEBUG:
    require_production_value("POSTGRES_PASSWORD", env("POSTGRES_PASSWORD"), min_length=12)
    if SESSION_COOKIE_SECURE is not True:
        raise ImproperlyConfigured("SESSION_COOKIE_SECURE must be true when DJANGO_DEBUG=false.")
    if CSRF_COOKIE_SECURE is not True:
        raise ImproperlyConfigured("CSRF_COOKIE_SECURE must be true when DJANGO_DEBUG=false.")
    if SESSION_COOKIE_HTTPONLY is not True:
        raise ImproperlyConfigured("SESSION_COOKIE_HTTPONLY must be true when DJANGO_DEBUG=false.")
    if SESSION_COOKIE_AGE <= 0:
        raise ImproperlyConfigured("SESSION_COOKIE_AGE must be a positive number of seconds.")
    if not OIDC_ENABLED:
        raise ImproperlyConfigured("OIDC_ENABLED must be true when DJANGO_DEBUG=false.")
    for oidc_name in (
        "OIDC_RP_CLIENT_ID",
        "OIDC_RP_CLIENT_SECRET",
        "OIDC_OP_AUTHORIZATION_ENDPOINT",
        "OIDC_OP_TOKEN_ENDPOINT",
        "OIDC_OP_USER_ENDPOINT",
        "OIDC_OP_JWKS_ENDPOINT",
    ):
        require_production_value(oidc_name, env(oidc_name), min_length=8)
