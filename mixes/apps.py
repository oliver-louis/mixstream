from django.apps import AppConfig


class MixesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mixes"

    def ready(self):
        import mixes.signals  # noqa: F401
