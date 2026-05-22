import logging

from django.contrib.auth import get_user_model, user_logged_in, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


logger = logging.getLogger("mixes.auth")


@receiver(post_save, sender=get_user_model())
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def log_user_logged_in(sender, request, user, **kwargs):
    logger.info("login_success", extra={"event": "login_success", "user_id": user.pk, "path": getattr(request, "path", "")})


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    logger.warning("login_failed", extra={"event": "login_failed", "path": getattr(request, "path", "")})
