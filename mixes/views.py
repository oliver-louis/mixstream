import json
import logging
import math
import shutil
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.core.exceptions import ValidationError
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
from .forms import ALLOWED_AUDIO_CONTENT_TYPES, ALLOWED_AUDIO_EXTENSIONS, MixForm, ProfileForm, TracklistTimestampForm, audio_header_looks_supported, parse_tracklist_upload, tracklist_to_json_payload, tracklist_to_text
from .models import Genre, Mix, MixTracklistItem, Profile, UploadSession, cover_path, mix_audio_path


logger = logging.getLogger("mixes.app")


def upload_form_without_required_audio(post_data, files, *, owner):
    form = MixForm(post_data, files, owner=owner)
    form.fields["audio_file"].required = False
    return form


def upload_metadata_from_form(form):
    cleaned = form.cleaned_data
    return {
        "title": cleaned.get("title") or "",
        "description": cleaned.get("description") or "",
        "visibility": cleaned.get("visibility") or Mix.Visibility.PRIVATE,
        "short_url_enabled": bool(cleaned.get("short_url_enabled")),
        "hide_view_count": bool(cleaned.get("hide_view_count")),
        "tracklist_text": cleaned.get("tracklist_text") or "",
        "tracklist_json": cleaned.get("tracklist_json") or [],
        "primary_genre_id": cleaned["primary_genre"].pk if cleaned.get("primary_genre") else None,
        "primary_genre_custom": cleaned.get("primary_genre_custom") or "",
        "genre_ids": [genre.pk for genre in cleaned.get("genres") or []],
        "genres_custom": cleaned.get("genres_custom") or [],
        "shared_with_ids": [user.pk for user in cleaned.get("shared_with") or []],
    }


def genre_for_name(name):
    form = MixForm(owner=None)
    return form.genre_for_name(name)


def create_mix_from_upload_session(upload_session, audio_name, cover_name=""):
    metadata = upload_session.metadata
    primary_genre = None
    if metadata.get("primary_genre_custom"):
        primary_genre = genre_for_name(metadata["primary_genre_custom"])
    elif metadata.get("primary_genre_id"):
        primary_genre = Genre.objects.filter(pk=metadata["primary_genre_id"]).first()
    mix = Mix.objects.create(
        owner=upload_session.owner,
        title=metadata["title"],
        description=metadata.get("description", ""),
        visibility=metadata.get("visibility") or Mix.Visibility.PRIVATE,
        short_url_enabled=bool(metadata.get("short_url_enabled")),
        hide_view_count=bool(metadata.get("hide_view_count")),
        tracklist_text=metadata.get("tracklist_text", ""),
        primary_genre=primary_genre,
        audio_file=audio_name,
        source_audio_file=audio_name,
        cover_image=cover_name or None,
        source_cover_image=cover_name or None,
        original_filename=upload_session.filename,
        processing_status=Mix.ProcessingStatus.PENDING,
    )
    if metadata.get("genre_ids"):
        mix.genres.add(*Genre.objects.filter(pk__in=metadata["genre_ids"]))
    for name in metadata.get("genres_custom") or []:
        mix.genres.add(genre_for_name(name))
    if metadata.get("shared_with_ids"):
        mix.shared_with.add(*upload_session.owner.__class__.objects.filter(pk__in=metadata["shared_with_ids"], is_active=True))
    MixTracklistItem.objects.bulk_create(
        [
            MixTracklistItem(
                mix=mix,
                position=index,
                title=row["title"],
                artist=row.get("artist", ""),
                links=row.get("links", {}),
                url="",
                start_seconds=row.get("start_seconds"),
                end_seconds=row.get("end_seconds"),
            )
            for index, row in enumerate(metadata.get("tracklist_json") or [], start=1)
        ]
    )
    return mix


def validate_chunked_audio_metadata(filename, content_type, total_size):
    if total_size <= 0 or total_size > settings.DJMIX_MAX_UPLOAD_BYTES:
        raise ValidationError("This audio file is larger than the configured upload limit.")
    if Path(filename).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValidationError("Upload an MP3, WAV, FLAC, AIFF, M4A, or OGG file.")
    if content_type and content_type not in ALLOWED_AUDIO_CONTENT_TYPES:
        raise ValidationError("The uploaded audio type is not supported.")


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
            "chunked_upload": True,
        },
    )


@login_required
@require_POST
def chunked_upload_start(request):
    try:
        filename = request.POST.get("audio_filename", "")
        content_type = request.POST.get("audio_content_type", "")
        total_size = int(request.POST.get("audio_size", "0"))
        chunk_size = int(request.POST.get("chunk_size", "0"))
    except ValueError:
        return JsonResponse({"error": "Upload size values are invalid."}, status=400)
    try:
        validate_chunked_audio_metadata(filename, content_type, total_size)
    except ValidationError as exc:
        return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
    if chunk_size <= 0 or chunk_size > settings.DJMIX_MAX_CHUNK_BYTES:
        return JsonResponse({"error": "Chunk size is larger than the configured chunk limit."}, status=400)
    form = upload_form_without_required_audio(request.POST, request.FILES, owner=request.user)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    total_chunks = math.ceil(total_size / chunk_size)
    upload_session = UploadSession.objects.create(
        owner=request.user,
        filename=Path(filename).name,
        content_type=content_type,
        total_size=total_size,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        metadata=upload_metadata_from_form(form),
    )
    cover = form.cleaned_data.get("cover_image")
    if cover:
        suffix = Path(cover.name).suffix.lower() or ".cover"
        upload_session.upload_dir.mkdir(parents=True, exist_ok=True)
        cover_path_tmp = upload_session.upload_dir / f"cover{suffix}"
        with cover_path_tmp.open("wb") as destination:
            for chunk in cover.chunks():
                destination.write(chunk)
        upload_session.cover_temp_path = str(cover_path_tmp)
        upload_session.save(update_fields=["cover_temp_path", "updated_at"])
    logger.info("chunked_upload_started", extra={"event": "chunked_upload_started", "upload_id": str(upload_session.upload_id), "user_id": request.user.pk})
    return JsonResponse(
        {
            "upload_id": str(upload_session.upload_id),
            "chunk_size": chunk_size,
            "total_chunks": total_chunks,
            "max_chunk_size": settings.DJMIX_MAX_CHUNK_BYTES,
        }
    )


@login_required
@require_POST
def chunked_upload_chunk(request, upload_id):
    upload_session = get_object_or_404(UploadSession, upload_id=upload_id, owner=request.user)
    if upload_session.status != UploadSession.Status.UPLOADING:
        return JsonResponse({"error": "This upload is not accepting chunks."}, status=409)
    try:
        index = int(request.POST.get("index", "-1"))
    except ValueError:
        return JsonResponse({"error": "Chunk index is invalid."}, status=400)
    if index < 0 or index >= upload_session.total_chunks:
        return JsonResponse({"error": "Chunk index is out of range."}, status=400)
    if index in set(upload_session.received_chunks):
        return JsonResponse({"error": "Chunk has already been received."}, status=409)
    chunk_file = request.FILES.get("chunk")
    if not chunk_file:
        return JsonResponse({"error": "No chunk was uploaded."}, status=400)
    if chunk_file.size > settings.DJMIX_MAX_CHUNK_BYTES:
        return JsonResponse({"error": "Chunk is larger than the configured chunk limit."}, status=413)
    upload_session.upload_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = upload_session.chunk_path(index)
    with chunk_path.open("wb") as destination:
        for chunk in chunk_file.chunks():
            destination.write(chunk)
    received = sorted(set(upload_session.received_chunks) | {index})
    upload_session.received_chunks = received
    upload_session.save(update_fields=["received_chunks", "updated_at"])
    return JsonResponse({"received": received, "received_count": len(received), "total_chunks": upload_session.total_chunks})


@login_required
@require_POST
def chunked_upload_complete(request, upload_id):
    upload_session = get_object_or_404(UploadSession, upload_id=upload_id, owner=request.user)
    if upload_session.status != UploadSession.Status.UPLOADING:
        return JsonResponse({"error": "This upload cannot be completed."}, status=409)
    expected = set(range(upload_session.total_chunks))
    received = set(upload_session.received_chunks)
    if received != expected:
        return JsonResponse({"error": "Upload is missing chunks.", "missing": sorted(expected - received)}, status=400)
    temp_mix = Mix(owner=request.user, title=upload_session.metadata["title"])
    audio_name = mix_audio_path(temp_mix, upload_session.filename)
    audio_path = Path(settings.MEDIA_ROOT) / audio_name
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = 0
    with audio_path.open("wb") as destination:
        for index in range(upload_session.total_chunks):
            chunk_path = upload_session.chunk_path(index)
            if not chunk_path.exists():
                audio_path.unlink(missing_ok=True)
                return JsonResponse({"error": "Upload is missing chunks.", "missing": [index]}, status=400)
            bytes_written += chunk_path.stat().st_size
            with chunk_path.open("rb") as source:
                shutil.copyfileobj(source, destination)
    if bytes_written != upload_session.total_size or audio_path.stat().st_size != upload_session.total_size:
        audio_path.unlink(missing_ok=True)
        return JsonResponse({"error": "Assembled upload size did not match the expected size."}, status=400)
    with audio_path.open("rb") as source:
        header = source.read(16)
    if not audio_header_looks_supported(header):
        audio_path.unlink(missing_ok=True)
        return JsonResponse({"error": "The uploaded file does not look like supported audio."}, status=400)
    cover_name = ""
    if upload_session.cover_temp_path:
        cover_source = Path(upload_session.cover_temp_path)
        if cover_source.exists():
            cover_name = cover_path(temp_mix, cover_source.name)
            cover_destination = Path(settings.MEDIA_ROOT) / cover_name
            cover_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(cover_source), cover_destination)
    mix = create_mix_from_upload_session(upload_session, audio_name, cover_name)
    upload_session.status = UploadSession.Status.COMPLETED
    upload_session.save(update_fields=["status", "updated_at"])
    upload_session.discard_files()
    logger.info("chunked_upload_completed", extra={"event": "chunked_upload_completed", "upload_id": str(upload_session.upload_id), "mix_id": mix.pk, "user_id": request.user.pk})
    messages.success(request, "Mix uploaded. Metadata and waveform processing will run shortly.")
    return JsonResponse({"mix_id": mix.pk, "redirect_url": mix.get_absolute_url()})


@login_required
@require_POST
def chunked_upload_abort(request, upload_id):
    upload_session = get_object_or_404(UploadSession, upload_id=upload_id, owner=request.user)
    upload_session.status = UploadSession.Status.ABORTED
    upload_session.save(update_fields=["status", "updated_at"])
    upload_session.discard_files()
    logger.info("chunked_upload_aborted", extra={"event": "chunked_upload_aborted", "upload_id": str(upload_session.upload_id), "user_id": request.user.pk})
    return JsonResponse({"aborted": True})


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
        rows = parse_tracklist_upload(request.FILES.get("file"), allow_invalid_time_ranges=True)
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
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = f'inline; filename="{Path(mix.original_filename or audio_file.name).stem}.{codec}"'
    return response


class AppLogoutView(LogoutView):
    next_page = reverse_lazy("mixes:home")
