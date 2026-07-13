from pathlib import Path
import shutil
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from .tracklinks import ordered_platform_link_map, ordered_platform_links


User = get_user_model()

RESERVED_MIX_SHARE_SLUGS = {
    "admin",
    "health",
    "library",
    "login",
    "mixes",
    "oidc",
    "profile",
    "upload",
}


def mix_audio_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"mixes/{instance.owner_id}/{uuid4().hex}{suffix}"


def cover_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"covers/{instance.owner_id}/{uuid4().hex}{suffix}"


def processed_audio_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"mixes/processed/{instance.owner_id}/{uuid4().hex}{suffix}"


def processed_cover_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"covers/processed/{instance.owner_id}/{uuid4().hex}{suffix}"


def profile_image_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"profiles/{instance.user_id}/{uuid4().hex}{suffix}"


def unique_mix_share_slug(title, *, exclude_pk=None):
    base = slugify(title) or "mix"
    slug = base
    counter = 2
    while slug in RESERVED_MIX_SHARE_SLUGS or Mix.objects.filter(share_slug=slug).exclude(pk=exclude_pk).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=120, blank=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    bio = models.TextField(blank=True)
    avatar_image = models.ImageField(upload_to=profile_image_path, blank=True, null=True)
    banner_image = models.ImageField(upload_to=profile_image_path, blank=True, null=True)
    public_enabled = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.display_name:
            self.display_name = self.user.get_full_name() or self.user.username
        if not self.slug:
            base = slugify(self.display_name or self.user.username) or f"user-{self.user_id}"
            slug = base
            counter = 2
            while Profile.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name

    def get_absolute_url(self):
        return reverse("mixes:profile", kwargs={"slug": self.slug})


class Genre(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name) or "genre"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Mix(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mixes")
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=220, blank=True)
    share_slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    audio_file = models.FileField(upload_to=mix_audio_path)
    cover_image = models.ImageField(upload_to=cover_path, blank=True, null=True)
    source_audio_file = models.FileField(upload_to=mix_audio_path, blank=True)
    source_cover_image = models.ImageField(upload_to=cover_path, blank=True, null=True)
    opus_file = models.FileField(upload_to=processed_audio_path, blank=True)
    mp3_file = models.FileField(upload_to=processed_audio_path, blank=True)
    cover_webp_large = models.ImageField(upload_to=processed_cover_path, blank=True, null=True)
    cover_webp_thumb = models.ImageField(upload_to=processed_cover_path, blank=True, null=True)
    primary_genre = models.ForeignKey(Genre, on_delete=models.SET_NULL, related_name="primary_mixes", blank=True, null=True)
    genres = models.ManyToManyField(Genre, related_name="mixes", blank=True)
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.PRIVATE)
    short_url_enabled = models.BooleanField(default=False)
    shared_with = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="shared_mixes", blank=True)
    tracklist_text = models.TextField(blank=True)
    duration_seconds = models.PositiveIntegerField(blank=True, null=True)
    waveform = models.JSONField(blank=True, null=True)
    original_filename = models.CharField(max_length=255, blank=True)
    processing_status = models.CharField(max_length=16, choices=ProcessingStatus.choices, default=ProcessingStatus.PENDING)
    processing_error = models.TextField(blank=True)
    media_processed_at = models.DateTimeField(blank=True, null=True)
    media_processing_error = models.TextField(blank=True)
    hide_view_count = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)
    play_count = models.PositiveIntegerField(default=0)
    unique_listener_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["owner", "slug"], name="unique_mix_slug_per_owner")]
        indexes = [
            models.Index(fields=["visibility", "-created_at"], name="mix_visibility_created_idx"),
            models.Index(fields=["owner", "-created_at"], name="mix_owner_created_idx"),
            models.Index(fields=["processing_status", "updated_at"], name="mix_processing_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "mix"
            slug = base
            counter = 2
            while Mix.objects.filter(owner=self.owner, slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        if not self.share_slug:
            self.share_slug = unique_mix_share_slug(self.title, exclude_pk=self.pk)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("mixes:detail", kwargs={"profile_slug": self.owner.profile.slug, "slug": self.slug})

    def get_short_share_url(self):
        return reverse("mixes:detail_short", kwargs={"share_slug": self.share_slug})

    @property
    def is_public(self):
        return self.visibility == self.Visibility.PUBLIC

    @property
    def short_share_url_active(self):
        return self.is_public or self.short_url_enabled

    @property
    def formatted_duration(self):
        if not self.duration_seconds:
            return ""
        total = int(self.duration_seconds)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @property
    def additional_genres(self):
        if not self.primary_genre_id:
            return self.genres.all()
        return self.genres.exclude(pk=self.primary_genre_id)

    @property
    def is_playable(self):
        return bool(self.opus_file and self.mp3_file and self.processing_status == self.ProcessingStatus.READY)

    @property
    def display_cover(self):
        return self.cover_webp_large or self.cover_image

    @property
    def thumb_cover(self):
        return self.cover_webp_thumb or self.cover_webp_large or self.cover_image

    def can_view(self, user):
        if self.is_public:
            return True
        if not user.is_authenticated:
            return False
        return user.is_staff or user == self.owner or self.shared_with.filter(pk=user.pk).exists()


class MixTracklistItem(models.Model):
    mix = models.ForeignKey(Mix, on_delete=models.CASCADE, related_name="tracklist_items")
    position = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=220)
    artist = models.CharField(max_length=180, blank=True)
    url = models.URLField(blank=True)
    links = models.JSONField(blank=True, default=dict)
    start_seconds = models.PositiveIntegerField(blank=True, null=True)
    end_seconds = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        ordering = ["position", "id"]
        indexes = [
            models.Index(fields=["mix", "position"], name="tracklist_mix_position_idx"),
            models.Index(fields=["mix", "start_seconds"], name="tracklist_mix_start_idx"),
        ]

    def clean(self):
        if self.start_seconds is not None and self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValidationError({"end_seconds": "End time must be after the start time."})

    def __str__(self):
        if self.artist:
            return f"{self.artist} - {self.title}"
        return self.title

    @staticmethod
    def format_seconds(value):
        if value is None:
            return ""
        total = int(value)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @property
    def formatted_start(self):
        return self.format_seconds(self.start_seconds)

    @property
    def formatted_end(self):
        return self.format_seconds(self.end_seconds)

    @property
    def platform_links(self):
        return ordered_platform_links(self.links, self.url)

    def as_player_payload(self):
        return {
            "position": self.position,
            "title": self.title,
            "artist": self.artist,
            "links": ordered_platform_link_map(self.links, self.url),
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "start": self.formatted_start,
            "end": self.formatted_end,
        }


class MixPlaybackProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mix_playback_progress")
    mix = models.ForeignKey(Mix, on_delete=models.CASCADE, related_name="playback_progress")
    position_seconds = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [models.UniqueConstraint(fields=["user", "mix"], name="unique_mix_progress_per_user")]
        indexes = [models.Index(fields=["user", "-updated_at"], name="mix_progress_user_updated_idx")]

    def __str__(self):
        return f"{self.user} · {self.mix} · {self.position_seconds}s"


class UploadSession(models.Model):
    class Status(models.TextChoices):
        UPLOADING = "uploading", "Uploading"
        COMPLETED = "completed", "Completed"
        ABORTED = "aborted", "Aborted"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="upload_sessions")
    upload_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    total_size = models.PositiveBigIntegerField()
    chunk_size = models.PositiveIntegerField()
    total_chunks = models.PositiveIntegerField()
    received_chunks = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    cover_temp_path = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status", "-created_at"], name="upload_session_owner_idx"),
            models.Index(fields=["status", "created_at"], name="upload_session_cleanup_idx"),
        ]

    @property
    def upload_dir(self):
        return Path(settings.MEDIA_ROOT) / "tmp" / "uploads" / str(self.upload_id)

    def chunk_path(self, index):
        return self.upload_dir / f"{index:06d}.part"

    def discard_files(self):
        shutil.rmtree(self.upload_dir, ignore_errors=True)


class MixViewEvent(models.Model):
    mix = models.ForeignKey(Mix, on_delete=models.CASCADE, related_name="view_events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="mix_view_events", blank=True, null=True)
    event_identity = models.CharField(max_length=80)
    ip_hash = models.CharField(max_length=64)
    user_agent_hash = models.CharField(max_length=64)
    session_key = models.CharField(max_length=40, blank=True)
    referrer = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["mix", "event_identity", "-created_at"], name="mix_view_dedupe_idx"),
            models.Index(fields=["mix", "-created_at"], name="mix_view_created_idx"),
        ]


class MixStreamEvent(models.Model):
    mix = models.ForeignKey(Mix, on_delete=models.CASCADE, related_name="stream_events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="mix_stream_events", blank=True, null=True)
    event_identity = models.CharField(max_length=80)
    ip_hash = models.CharField(max_length=64)
    user_agent_hash = models.CharField(max_length=64)
    session_key = models.CharField(max_length=40, blank=True)
    codec = models.CharField(max_length=16, blank=True)
    seconds_listened = models.PositiveIntegerField(default=0)
    percent_listened = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["mix", "event_identity", "-created_at"], name="mix_stream_dedupe_idx"),
            models.Index(fields=["mix", "-created_at"], name="mix_stream_created_idx"),
        ]
