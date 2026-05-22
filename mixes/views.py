import json
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import Q
import mimetypes
from pathlib import Path

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_POST

from .analytics import record_mix_stream, record_mix_view
from .forms import MixForm, ProfileForm, TracklistTimestampForm, parse_tracklist_upload, tracklist_to_json_payload, tracklist_to_text
from .models import Mix, Profile


logger = logging.getLogger("mixes.app")


def editable_mix_or_403(user, pk):
    mix = get_object_or_404(Mix.objects.select_related("owner", "owner__profile", "primary_genre").prefetch_related("tracklist_items"), pk=pk)
    if user != mix.owner and not user.is_staff:
        raise PermissionDenied
    return mix


def login_start(request):
    next_url = request.GET.get("next", "")
    target = reverse_lazy("oidc_authentication_init") if settings.OIDC_ENABLED else "/admin/login/"
    if next_url:
        return redirect(f"{target}?next={next_url}")
    return redirect(target)


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok", "version": settings.APP_VERSION})


def visible_mixes_for(user):
    qs = Mix.objects.select_related("owner", "owner__profile", "primary_genre").prefetch_related("shared_with", "genres")
    if user.is_authenticated:
        if user.is_staff:
            return qs
        return qs.filter(Q(visibility=Mix.Visibility.PUBLIC) | Q(owner=user) | Q(shared_with=user)).distinct()
    return qs.filter(visibility=Mix.Visibility.PUBLIC)


def home(request):
    mixes = Mix.objects.filter(visibility=Mix.Visibility.PUBLIC).select_related("owner", "owner__profile", "primary_genre").prefetch_related("genres")[:24]
    return render(request, "mixes/home.html", {"mixes": mixes})


@login_required
def library(request):
    mixes = visible_mixes_for(request.user)
    return render(request, "mixes/library.html", {"mixes": mixes})


def profile(request, slug):
    profile_obj = get_object_or_404(Profile.objects.select_related("user"), slug=slug)
    if not profile_obj.public_enabled and (not request.user.is_authenticated or request.user != profile_obj.user and not request.user.is_staff):
        raise Http404
    mixes = profile_obj.user.mixes.filter(visibility=Mix.Visibility.PUBLIC).select_related("owner", "owner__profile", "primary_genre").prefetch_related("genres")
    if request.user.is_authenticated and (request.user == profile_obj.user or request.user.is_staff):
        mixes = profile_obj.user.mixes.select_related("owner", "owner__profile", "primary_genre").prefetch_related("genres")
    return render(request, "mixes/profile.html", {"profile_obj": profile_obj, "mixes": mixes})


def detail(request, profile_slug, slug):
    mix = get_object_or_404(
        Mix.objects.select_related("owner", "owner__profile", "primary_genre").prefetch_related("genres", "tracklist_items"),
        owner__profile__slug=profile_slug,
        slug=slug,
    )
    if not mix.can_view(request.user):
        if request.user.is_authenticated:
            raise PermissionDenied
        return redirect(f"{resolve_url(settings.LOGIN_URL)}?next={request.path}")
    tracklist_items = list(mix.tracklist_items.all())
    tracklist_payload = [item.as_player_payload() for item in tracklist_items if item.start_seconds is not None]
    return render(request, "mixes/detail.html", {"mix": mix, "tracklist_items": tracklist_items, "tracklist_payload": tracklist_payload})


def detail_short(request, share_slug):
    mix = get_object_or_404(
        Mix.objects.select_related("owner", "owner__profile"),
        share_slug=share_slug,
    )
    if not mix.is_public and not mix.short_url_enabled:
        raise Http404
    if not mix.can_view(request.user):
        if request.user.is_authenticated:
            raise PermissionDenied
        return redirect(f"{resolve_url(settings.LOGIN_URL)}?next={request.path}")
    return redirect(mix)


@login_required
def upload(request):
    if request.method == "POST":
        logger.info("upload_submitted", extra={"event": "upload_submitted", "user_id": request.user.pk})
        form = MixForm(request.POST, request.FILES, owner=request.user)
        if form.is_valid():
            mix = form.save(commit=False)
            mix.owner = request.user
            if mix.audio_file:
                mix.original_filename = mix.audio_file.name
                mix.source_audio_file = mix.audio_file
            if mix.cover_image:
                mix.source_cover_image = mix.cover_image
            mix.save()
            form.save_m2m()
            form.save_tracklist(mix)
            logger.info("upload_created", extra={"event": "upload_created", "mix_id": mix.pk, "user_id": request.user.pk})
            messages.success(request, "Mix uploaded. Metadata and waveform processing will run shortly.")
            return redirect(mix)
    else:
        form = MixForm(owner=request.user)
    return render(
        request,
        "mixes/mix_form.html",
        {
            "form": form,
            "title": "Upload mix",
            "mix": Mix(owner=request.user),
            "short_share_url": "",
        },
    )


@login_required
def edit_mix(request, pk):
    mix = editable_mix_or_403(request.user, pk)
    if request.method == "POST":
        form = MixForm(request.POST, request.FILES, instance=mix, owner=request.user)
        if form.is_valid():
            updated = form.save(commit=False)
            if "audio_file" in form.changed_data:
                updated.processing_status = Mix.ProcessingStatus.PENDING
                updated.processing_error = ""
                updated.media_processing_error = ""
                updated.media_processed_at = None
                updated.opus_file = ""
                updated.mp3_file = ""
                updated.original_filename = updated.audio_file.name
                updated.source_audio_file = updated.audio_file
            if "cover_image" in form.changed_data:
                updated.processing_status = Mix.ProcessingStatus.PENDING
                updated.processing_error = ""
                updated.media_processing_error = ""
                updated.media_processed_at = None
                updated.cover_webp_large = None
                updated.cover_webp_thumb = None
                if updated.cover_image:
                    updated.source_cover_image = updated.cover_image
            updated.save()
            form.save_m2m()
            form.save_tracklist(updated)
            messages.success(request, "Mix updated.")
            return redirect(updated)
    else:
        form = MixForm(instance=mix, owner=request.user)
    return render(
        request,
        "mixes/mix_form.html",
        {
            "form": form,
            "title": "Edit mix",
            "mix": mix,
            "short_share_url": request.build_absolute_uri(mix.get_short_share_url()) if mix.share_slug else "",
        },
    )


@login_required
def tracklist_editor(request, pk):
    mix = editable_mix_or_403(request.user, pk)
    if request.method == "POST":
        form = TracklistTimestampForm(request.POST, mix=mix)
        if form.is_valid():
            form.save()
            messages.success(request, "Track IDs updated.")
            return redirect("mixes:edit_mix", pk=mix.pk)
    else:
        form = TracklistTimestampForm(mix=mix)
    return render(
        request,
        "mixes/tracklist_editor.html",
        {
            "mix": mix,
            "form": form,
            "tracklist_json": form["tracklist_json"].value() or "[]",
        },
    )


@login_required
@require_POST
def tracklist_import_file(request, pk):
    mix = editable_mix_or_403(request.user, pk)
    try:
        rows = parse_tracklist_upload(request.FILES.get("file"))
    except Exception as error:
        messages_list = getattr(error, "messages", None)
        return JsonResponse({"error": " ".join(messages_list) if messages_list else str(error)}, status=400)
    return JsonResponse({"mix_id": mix.pk, "rows": tracklist_to_json_payload(rows)})


@login_required
@require_GET
def tracklist_export_file(request, pk, fmt):
    mix = editable_mix_or_403(request.user, pk)
    rows = [
        {
            "title": item.title,
            "artist": item.artist,
            "links": item.platform_links and {link["platform"]: link["url"] for link in item.platform_links} or {},
            "start_seconds": item.start_seconds,
            "end_seconds": item.end_seconds,
        }
        for item in mix.tracklist_items.all()
    ]
    filename = f"{mix.slug}-track-ids"
    if fmt == "json":
        payload = json.dumps(tracklist_to_json_payload(rows), indent=2)
        response = HttpResponse(payload, content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="{filename}.json"'
        return response
    if fmt == "txt":
        response = HttpResponse(tracklist_to_text(rows), content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}.txt"'
        return response
    raise Http404


@login_required
def edit_profile(request):
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect(profile_obj)
    else:
        form = ProfileForm(instance=profile_obj)
    return render(request, "mixes/profile_form.html", {"form": form})


@require_POST
def increment_view(request, pk):
    mix = get_object_or_404(Mix, pk=pk)
    if not mix.can_view(request.user):
        raise PermissionDenied
    created = record_mix_view(request, mix)
    return JsonResponse({"recorded": created, "view_count": mix.view_count + (1 if created else 0)})


@require_POST
def increment_play(request, pk):
    mix = get_object_or_404(Mix, pk=pk)
    if not mix.can_view(request.user):
        raise PermissionDenied
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        payload = {}
    seconds_listened = int(float(payload.get("seconds_listened") or 0))
    percent_listened = int(float(payload.get("percent_listened") or 0))
    duration = int(mix.duration_seconds or 0)
    threshold_percent = duration and seconds_listened >= duration * 0.1
    if seconds_listened < 20 and not threshold_percent:
        return JsonResponse({"recorded": False, "reason": "below_threshold"}, status=202)
    created = record_mix_stream(
        request,
        mix,
        payload.get("codec") or "",
        seconds_listened,
        percent_listened,
    )
    return JsonResponse({"recorded": created, "play_count": mix.play_count + (1 if created else 0)})


def stream_audio(request, pk, codec="opus"):
    mix = get_object_or_404(Mix, pk=pk)
    if not mix.can_view(request.user):
        logger.warning("forbidden_media_access", extra={"event": "forbidden_media_access", "mix_id": mix.pk, "user_id": request.user.pk if request.user.is_authenticated else None})
        raise PermissionDenied
    if codec not in {"opus", "mp3"}:
        raise Http404
    audio_file = mix.opus_file if codec == "opus" else mix.mp3_file
    if not audio_file:
        raise Http404
    logger.info("audio_stream_authorized", extra={"event": "audio_stream_authorized", "mix_id": mix.pk, "user_id": request.user.pk if request.user.is_authenticated else None})
    content_type = mimetypes.guess_type(audio_file.name)[0] or "application/octet-stream"
    response = HttpResponse()
    response["Content-Type"] = content_type
    response["X-Accel-Redirect"] = f"{settings.DJMIX_INTERNAL_MEDIA_PREFIX}{audio_file.name}"
    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = f'inline; filename="{Path(mix.original_filename or audio_file.name).stem}.{codec}"'
    return response


class AppLogoutView(LogoutView):
    next_page = reverse_lazy("mixes:home")
