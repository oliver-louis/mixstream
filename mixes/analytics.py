import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Mix, MixStreamEvent, MixViewEvent


logger = logging.getLogger("mixes.analytics")


def _hash_value(value):
    if not value:
        value = "unknown"
    salt = settings.SECRET_KEY.encode()
    return hashlib.sha256(salt + value.encode()).hexdigest()


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def event_identity(request):
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        return f"user:{user.pk}"
    agent = request.META.get("HTTP_USER_AGENT", "")
    return f"anon:{_hash_value(client_ip(request) + '|' + agent)}"


def event_hashes(request):
    return {
        "ip_hash": _hash_value(client_ip(request)),
        "user_agent_hash": _hash_value(request.META.get("HTTP_USER_AGENT", "")),
        "session_key": request.session.session_key or "",
        "event_identity": event_identity(request),
    }


def record_mix_view(request, mix):
    hashes = event_hashes(request)
    cutoff = timezone.now() - timedelta(minutes=settings.DJMIX_VIEW_DEDUPE_MINUTES)
    exists = MixViewEvent.objects.filter(mix=mix, event_identity=hashes["event_identity"], created_at__gte=cutoff).exists()
    if exists:
        return False
    with transaction.atomic():
        MixViewEvent.objects.create(
            mix=mix,
            user=request.user if request.user.is_authenticated else None,
            referrer=request.META.get("HTTP_REFERER", "")[:500],
            **hashes,
        )
        Mix.objects.filter(pk=mix.pk).update(view_count=F("view_count") + 1)
    logger.info("mix_view_recorded", extra={"event": "mix_view_recorded", "mix_id": mix.pk, "user_id": request.user.pk if request.user.is_authenticated else None})
    return True


def record_mix_stream(request, mix, codec, seconds_listened, percent_listened):
    hashes = event_hashes(request)
    cutoff = timezone.now() - timedelta(minutes=settings.DJMIX_STREAM_DEDUPE_MINUTES)
    exists = MixStreamEvent.objects.filter(mix=mix, event_identity=hashes["event_identity"], created_at__gte=cutoff).exists()
    if exists:
        return False
    with transaction.atomic():
        MixStreamEvent.objects.create(
            mix=mix,
            user=request.user if request.user.is_authenticated else None,
            codec=codec[:16],
            seconds_listened=max(0, int(seconds_listened)),
            percent_listened=max(0, min(100, int(percent_listened))),
            **hashes,
        )
        unique_count = MixStreamEvent.objects.filter(mix=mix).values("event_identity").distinct().count()
        Mix.objects.filter(pk=mix.pk).update(play_count=F("play_count") + 1, unique_listener_count=unique_count)
    logger.info("mix_stream_recorded", extra={"event": "mix_stream_recorded", "mix_id": mix.pk, "user_id": request.user.pk if request.user.is_authenticated else None})
    return True
