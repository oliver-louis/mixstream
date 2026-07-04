import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from PIL import Image, UnidentifiedImageError

from .models import Genre, Mix, MixTracklistItem, Profile
from .tracklinks import PLATFORM_LABELS, PLATFORM_ORDER, ordered_platform_link_map, platform_from_url


ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".m4a", ".ogg"}
ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/aiff",
    "audio/flac",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/ogg",
    "audio/vnd.wave",
    "audio/wave",
    "audio/wav",
    "audio/x-pn-wav",
    "audio/x-aiff",
    "audio/x-flac",
    "audio/x-m4a",
    "audio/x-wav",
}

TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
TRACKLIST_LINE_PATTERN = re.compile(
    r"^\s*(?:(?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s*"
    r"(?:(?:-|–|—|->|→)\s*(?P<end>\d{1,2}:\d{2}(?::\d{2})?))?\s+)?"
    r"(?P<body>.+?)\s*$"
)
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
TRACKLIST_JSON_CONTENT_TYPES = {"application/json", "text/json", "application/octet-stream"}
TRACKLIST_TEXT_CONTENT_TYPES = {"text/plain", "application/octet-stream"}
SUPPORTED_AUDIO_HEADER_PREFIXES = (b"ID3", b"\xff", b"RIFF", b"fLaC", b"FORM", b"OggS")


def audio_header_looks_supported(header):
    return header.startswith(SUPPORTED_AUDIO_HEADER_PREFIXES) or b"ftyp" in header


def parse_track_time(value):
    value = (value or "").strip()
    if not value:
        return None
    if not TIME_PATTERN.match(value):
        raise forms.ValidationError("Use mm:ss or hh:mm:ss.")
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        hours = 0
    else:
        hours, minutes, seconds = parts
    if minutes >= 60 and hours:
        raise forms.ValidationError("Minutes must be less than 60 when hours are present.")
    if seconds >= 60:
        raise forms.ValidationError("Seconds must be less than 60.")
    return hours * 3600 + minutes * 60 + seconds


def format_track_time(seconds):
    return MixTracklistItem.format_seconds(seconds)


def split_artist_title(body):
    body = " ".join((body or "").strip().split())
    if " - " not in body:
        return "", body
    artist, title = body.split(" - ", 1)
    return artist.strip(), title.strip()


def normalize_track_links(links=None, legacy_url="", *, row_prefix=""):
    url_field = forms.URLField(required=False)
    normalized = {}
    provided = {}
    raw_links = links if isinstance(links, dict) else {}
    for platform, raw_url in raw_links.items():
        url = str(raw_url or "").strip()
        if not url:
            continue
        provided[platform] = url
    legacy = str(legacy_url or "").strip()
    if legacy:
        provided.setdefault("__legacy__", legacy)
    for platform, raw_url in provided.items():
        label_prefix = f"{row_prefix}: " if row_prefix else ""
        try:
            clean_url = url_field.clean(raw_url)
        except forms.ValidationError as error:
            raise forms.ValidationError(f"{label_prefix}{' '.join(error.messages)}")
        detected = platform_from_url(clean_url)
        if not detected:
            host = urlsplit(clean_url).hostname or "This domain"
            raise forms.ValidationError(
                f"{label_prefix}{host} is not supported. Use Discogs, Bandcamp, SoundCloud, YouTube, or Spotify."
            )
        if platform in PLATFORM_ORDER and platform != detected:
            raise forms.ValidationError(
                f"{label_prefix}{PLATFORM_LABELS.get(platform, platform.title())} links must use the correct platform URL."
            )
        if detected in normalized:
            raise forms.ValidationError(f"{label_prefix}Only one {PLATFORM_LABELS[detected]} link is allowed per Track ID.")
        normalized[detected] = clean_url
    return {platform: normalized[platform] for platform in PLATFORM_ORDER if platform in normalized}


def extract_links_from_line(line):
    raw_urls = URL_PATTERN.findall(line or "")
    links = normalize_track_links({f"candidate_{index}": url for index, url in enumerate(raw_urls, start=1)}) if raw_urls else {}
    cleaned = URL_PATTERN.sub("", line or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, links


def parse_tracklist_line(line):
    line = (line or "").strip()
    if not line:
        return None
    line, links = extract_links_from_line(line)
    match = TRACKLIST_LINE_PATTERN.match(line)
    if not match:
        raise forms.ValidationError("Could not read this tracklist line.")
    artist, title = split_artist_title(match.group("body"))
    if not title:
        raise forms.ValidationError("Track title is required.")
    start_seconds = parse_track_time(match.group("start"))
    end_seconds = parse_track_time(match.group("end"))
    if start_seconds is not None and end_seconds is not None and end_seconds <= start_seconds:
        raise forms.ValidationError("End time must be after the start time.")
    return {
        "title": title,
        "artist": artist,
        "links": links,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
    }


def parse_tracklist_text(raw):
    rows = []
    errors = []
    for line_number, line in enumerate((raw or "").splitlines(), start=1):
        try:
            row = parse_tracklist_line(line)
        except forms.ValidationError as error:
            errors.append(f"Line {line_number}: {' '.join(error.messages)}")
            continue
        if row:
            rows.append(row)
    if errors:
        raise forms.ValidationError(errors)
    return rows


def serialize_tracklist_rows(rows):
    serialized = []
    for row in rows or []:
        serialized.append(
            {
                "title": row.get("title", ""),
                "artist": row.get("artist", ""),
                "links": normalize_track_links(row.get("links", {})),
                "start": format_track_time(row.get("start_seconds")),
                "end": format_track_time(row.get("end_seconds")),
            }
        )
    return serialized


def serialize_tracklist_items(items):
    return serialize_tracklist_rows(
        [
            {
                "title": item.title,
                "artist": item.artist,
                "links": ordered_platform_link_map(item.links, item.url),
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
            }
            for item in items
        ]
    )


def tracklist_to_json_payload(rows):
    return serialize_tracklist_rows(rows)


def tracklist_to_text(rows):
    lines = []
    for row in serialize_tracklist_rows(rows):
        parts = []
        if row["start"]:
            parts.append(f'{row["start"]} - {row["end"]}' if row["end"] else row["start"])
        title = row["title"]
        if row["artist"]:
            title = f'{row["artist"]} - {title}'
        parts.append(title)
        for platform in PLATFORM_ORDER:
            url = row["links"].get(platform, "")
            if url:
                parts.append(url)
        lines.append(" ".join(part for part in parts if part).strip())
    return "\n".join(lines)


def parse_tracklist_json_file(file_bytes):
    try:
        payload = json.loads((file_bytes or b"").decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise forms.ValidationError("Track ID JSON could not be read.")
    return clean_tracklist_payload(payload)


def parse_tracklist_text_file(file_bytes):
    try:
        raw = (file_bytes or b"").decode("utf-8-sig")
    except UnicodeDecodeError:
        raise forms.ValidationError("Track ID text file could not be read.")
    return parse_tracklist_text(raw)


def parse_tracklist_upload(uploaded_file):
    if not uploaded_file:
        raise forms.ValidationError("Choose a Track ID file to import.")
    suffix = Path(uploaded_file.name or "").suffix.lower()
    content_type = getattr(uploaded_file, "content_type", "") or ""
    payload = uploaded_file.read()
    uploaded_file.seek(0)
    if suffix == ".json":
        if content_type and content_type not in TRACKLIST_JSON_CONTENT_TYPES:
            raise forms.ValidationError("Upload a valid .json Track ID file.")
        return parse_tracklist_json_file(payload)
    if suffix == ".txt":
        if content_type and content_type not in TRACKLIST_TEXT_CONTENT_TYPES:
            raise forms.ValidationError("Upload a valid .txt Track ID file.")
        return parse_tracklist_text_file(payload)
    raise forms.ValidationError("Track ID files must be .json or .txt.")


def clean_tracklist_payload(payload):
    if not isinstance(payload, list):
        raise forms.ValidationError("Track IDs must be a list.")
    rows = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise forms.ValidationError(f"Row {index}: Track ID must be an object.")
        title = " ".join((item.get("title") or "").strip().split())
        artist = " ".join((item.get("artist") or "").strip().split())
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        legacy_url = (item.get("url") or "").strip()
        start_raw = str(item.get("start") or item.get("start_seconds") or "").strip()
        end_raw = str(item.get("end") or item.get("end_seconds") or "").strip()
        link_values = [str(value or "").strip() for value in links.values()] if isinstance(links, dict) else []
        has_any_value = any([title, artist, legacy_url, start_raw, end_raw, *link_values])
        if not has_any_value:
            continue
        if not title:
            raise forms.ValidationError(f"Row {index}: Track title is required.")
        try:
            normalized_links = normalize_track_links(links, legacy_url=legacy_url) if (links or legacy_url) else {}
            start_seconds = parse_track_time(start_raw)
            end_seconds = parse_track_time(end_raw)
        except forms.ValidationError as error:
            raise forms.ValidationError(f"Row {index}: {' '.join(error.messages)}")
        if end_seconds is not None and start_seconds is None:
            raise forms.ValidationError(f"Row {index}: Add a start time before using an end time.")
        if start_seconds is not None and end_seconds is not None and end_seconds <= start_seconds:
            raise forms.ValidationError(f"Row {index}: End time must be after the start time.")
        rows.append(
            {
                "title": title[:220],
                "artist": artist[:180],
                "links": normalized_links,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
            }
        )
    timestamped = [row for row in rows if row["start_seconds"] is not None]
    untimed = [row for row in rows if row["start_seconds"] is None]
    timestamped.sort(key=lambda row: (row["start_seconds"], row["end_seconds"] if row["end_seconds"] is not None else 10**9, row["title"].lower()))
    return timestamped + untimed


def validate_uploaded_image(image_file):
    if not image_file:
        return image_file
    if image_file.size > settings.DJMIX_MAX_UPLOAD_BYTES:
        raise forms.ValidationError("This image is larger than the configured upload limit.")
    try:
        image = Image.open(image_file)
        width, height = image.size
        image.verify()
    except (UnidentifiedImageError, OSError):
        raise forms.ValidationError("Upload a valid image file.")
    finally:
        image_file.seek(0)
    if width * height > settings.DJMIX_MAX_COVER_PIXELS:
        raise forms.ValidationError("This image is too large. Please use a smaller image.")
    return image_file


class MixForm(forms.ModelForm):
    primary_genre_custom = forms.CharField(
        required=False,
        label="Custom main genre",
        help_text="Use this to create a new main genre instead of selecting one above.",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Minimal Techno"}),
    )
    shared_with = forms.ModelMultipleChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    genres = forms.ModelMultipleChoiceField(
        queryset=Genre.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Optional extra genres shown when someone hovers over the main genre.",
    )
    genres_custom = forms.CharField(
        required=False,
        label="Custom extra genres",
        help_text="Comma-separated extra genres. New genres will be created automatically.",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Breaks, Dub Techno"}),
    )
    tracklist_json = forms.CharField(required=False, widget=forms.HiddenInput)
    tracklist_import = forms.CharField(
        required=False,
        label="Paste track IDs",
        help_text="One per line. Supports 12:34 Artist - Track, 12:34 - 18:20 Artist - Track, and optional links.",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "12:34 Artist - Track https://soundcloud.com/example https://open.spotify.com/track/abc",
            }
        ),
    )

    class Meta:
        model = Mix
        fields = [
            "title",
            "description",
            "audio_file",
            "cover_image",
            "primary_genre",
            "primary_genre_custom",
            "genres",
            "genres_custom",
            "visibility",
            "short_url_enabled",
            "hide_view_count",
            "shared_with",
            "tracklist_json",
            "tracklist_import",
            "tracklist_text",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "cover_image": forms.FileInput(attrs={"accept": "image/*"}),
            "hide_view_count": forms.CheckboxInput(),
            "tracklist_text": forms.Textarea(attrs={"rows": 4, "placeholder": "Optional free-text notes or legacy tracklist."}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)
        users = get_user_model().objects.filter(is_active=True).exclude(pk=getattr(owner, "pk", None)).order_by("username")
        self.fields["shared_with"].queryset = users
        self.fields["primary_genre"].queryset = Genre.objects.all()
        self.fields["genres"].queryset = Genre.objects.all()
        self.fields["audio_file"].required = self.instance.pk is None
        self.fields["short_url_enabled"].label = "Enable short share URL"
        self.fields["short_url_enabled"].help_text = "Public mixes always get a short URL. For private or shared mixes, turn this on to allow a root-level share link."
        self.fields["tracklist_text"].label = "Legacy/free-text tracklist"
        self.fields["tracklist_text"].help_text = "Used below the structured track IDs, or by itself if no structured IDs are saved."
        if self.instance.pk and not self.is_bound:
            self.fields["tracklist_json"].initial = json.dumps(serialize_tracklist_items(self.instance.tracklist_items.all()))

    def clean_primary_genre_custom(self):
        return self.normalize_genre_name(self.cleaned_data.get("primary_genre_custom", ""))

    def clean_genres_custom(self):
        raw = self.cleaned_data.get("genres_custom", "")
        names = [self.normalize_genre_name(part) for part in raw.split(",")]
        return [name for name in names if name]

    def clean_tracklist_json(self):
        raw = self.cleaned_data.get("tracklist_json") or ""
        if not raw.strip():
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise forms.ValidationError("Track IDs could not be read.")
        return clean_tracklist_payload(payload)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("tracklist_json") and cleaned.get("tracklist_import"):
            cleaned["tracklist_json"] = parse_tracklist_text(cleaned["tracklist_import"])
        return cleaned

    def normalize_genre_name(self, value):
        name = " ".join((value or "").strip().split())
        if len(name) > 80:
            raise forms.ValidationError("Genre names must be 80 characters or fewer.")
        return name

    def genre_for_name(self, name):
        slug = slugify(name) or "genre"
        genre, created = Genre.objects.get_or_create(slug=slug, defaults={"name": name})
        if not created and genre.name != name:
            existing = Genre.objects.filter(name__iexact=name).first()
            if existing:
                return existing
            slug = self.unique_genre_slug(slug)
            return Genre.objects.create(name=name, slug=slug)
        return genre

    def unique_genre_slug(self, base):
        slug = base
        counter = 2
        while Genre.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug

    def save(self, commit=True):
        instance = super().save(commit=False)
        custom_primary = self.cleaned_data.get("primary_genre_custom")
        if custom_primary:
            instance.primary_genre = self.genre_for_name(custom_primary)
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def _save_m2m(self):
        super()._save_m2m()
        custom_genres = self.cleaned_data.get("genres_custom") or []
        for name in custom_genres:
            self.instance.genres.add(self.genre_for_name(name))

    def save_tracklist(self, mix):
        rows = self.cleaned_data.get("tracklist_json") or []
        mix.tracklist_items.all().delete()
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
                for index, row in enumerate(rows, start=1)
            ]
        )

    def clean_audio_file(self):
        audio_file = self.cleaned_data.get("audio_file")
        if not audio_file:
            return audio_file
        if audio_file.size > settings.DJMIX_MAX_UPLOAD_BYTES:
            raise forms.ValidationError("This audio file is larger than the configured upload limit.")
        if Path(audio_file.name).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
            raise forms.ValidationError("Upload an MP3, WAV, FLAC, AIFF, M4A, or OGG file.")
        content_type = getattr(audio_file, "content_type", "")
        if content_type and content_type not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise forms.ValidationError("The uploaded audio type is not supported.")
        header = audio_file.read(16)
        audio_file.seek(0)
        if not audio_header_looks_supported(header):
            raise forms.ValidationError("The uploaded file does not look like supported audio.")
        return audio_file

    def clean_cover_image(self):
        return validate_uploaded_image(self.cleaned_data.get("cover_image"))


class TracklistTimestampForm(forms.Form):
    tracklist_json = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, mix=None, **kwargs):
        self.mix = mix
        super().__init__(*args, **kwargs)
        if mix is not None and not self.is_bound:
            self.fields["tracklist_json"].initial = json.dumps(serialize_tracklist_items(mix.tracklist_items.all()))

    def clean_tracklist_json(self):
        raw = self.cleaned_data.get("tracklist_json") or ""
        if not raw.strip():
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise forms.ValidationError("Track IDs could not be read.")
        return clean_tracklist_payload(payload)

    def save(self):
        if self.mix is None:
            raise ValueError("TracklistTimestampForm requires a mix.")
        rows = self.cleaned_data.get("tracklist_json") or []
        self.mix.tracklist_items.all().delete()
        MixTracklistItem.objects.bulk_create(
            [
                MixTracklistItem(
                    mix=self.mix,
                    position=index,
                    title=row["title"],
                    artist=row.get("artist", ""),
                    links=row.get("links", {}),
                    url="",
                    start_seconds=row.get("start_seconds"),
                    end_seconds=row.get("end_seconds"),
                )
                for index, row in enumerate(rows, start=1)
            ]
        )
        return self.mix


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["display_name", "slug", "bio", "avatar_image", "banner_image", "public_enabled"]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4}),
            "avatar_image": forms.FileInput(attrs={"accept": "image/*"}),
            "banner_image": forms.FileInput(attrs={"accept": "image/*"}),
        }

    def clean_avatar_image(self):
        return validate_uploaded_image(self.cleaned_data.get("avatar_image"))

    def clean_banner_image(self):
        return validate_uploaded_image(self.cleaned_data.get("banner_image"))
