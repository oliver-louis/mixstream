import json
import logging
import math
from pathlib import Path
import struct
import subprocess
import time
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image

from mixes.models import Mix


logger = logging.getLogger("mixes.worker")


class Command(BaseCommand):
    help = "Extract duration and lightweight waveform data for pending mixes."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process pending mixes once and exit.")
        parser.add_argument("--sleep", type=int, default=30, help="Seconds to sleep between polling runs.")
        parser.add_argument("--all", action="store_true", help="Reprocess every mix, including ready mixes.")
        parser.add_argument("--failed", action="store_true", help="Retry failed mixes.")

    def handle(self, *args, **options):
        while True:
            if options["all"]:
                pending = Mix.objects.all()
            elif options["failed"]:
                pending = Mix.objects.filter(processing_status=Mix.ProcessingStatus.FAILED)
            else:
                pending = Mix.objects.filter(processing_status=Mix.ProcessingStatus.PENDING)
            for mix in pending:
                self.process_mix(mix)
            if options["once"]:
                break
            time.sleep(options["sleep"])

    def process_mix(self, mix):
        logger.info("media_processing_started", extra={"event": "media_processing_started", "mix_id": mix.pk, "user_id": mix.owner_id})
        if mix.audio_file and not mix.source_audio_file:
            mix.source_audio_file = mix.audio_file
        if mix.cover_image and not mix.source_cover_image:
            mix.source_cover_image = mix.cover_image
        source_audio = mix.source_audio_file or mix.audio_file
        if not source_audio:
            raise ValueError("Mix has no source audio file.")
        path = source_audio.path
        try:
            duration = self.probe_duration(path)
            opus_name = self.transcode_opus(mix, path)
            mp3_name = self.transcode_mp3(mix, path)
            cover_large, cover_thumb = self.process_cover(mix)
            waveform = self.generate_waveform(path, duration)
            mix.duration_seconds = int(duration) if duration else None
            mix.waveform = waveform
            mix.opus_file.name = opus_name
            mix.mp3_file.name = mp3_name
            if cover_large:
                mix.cover_webp_large.name = cover_large
            if cover_thumb:
                mix.cover_webp_thumb.name = cover_thumb
            mix.processing_status = Mix.ProcessingStatus.READY
            mix.processing_error = ""
            mix.media_processing_error = ""
            mix.media_processed_at = timezone.now()
            mix.save(
                update_fields=[
                    "source_audio_file",
                    "source_cover_image",
                    "duration_seconds",
                    "waveform",
                    "opus_file",
                    "mp3_file",
                    "cover_webp_large",
                    "cover_webp_thumb",
                    "processing_status",
                    "processing_error",
                    "media_processing_error",
                    "media_processed_at",
                    "updated_at",
                ]
            )
            logger.info("media_processing_finished", extra={"event": "media_processing_finished", "mix_id": mix.pk, "user_id": mix.owner_id})
            self.stdout.write(self.style.SUCCESS(f"Processed {mix.title}"))
        except Exception as exc:
            mix.processing_status = Mix.ProcessingStatus.FAILED
            mix.processing_error = str(exc)
            mix.media_processing_error = str(exc)
            mix.save(update_fields=["processing_status", "processing_error", "media_processing_error", "updated_at"])
            logger.exception("media_processing_failed", extra={"event": "media_processing_failed", "mix_id": mix.pk, "user_id": mix.owner_id})
            self.stderr.write(f"Failed {mix.title}: {exc}")

    def output_name(self, mix, folder, suffix):
        return f"{folder}/{mix.owner_id}/{uuid4().hex}{suffix}"

    def absolute_media_path(self, name):
        path = Path(settings.MEDIA_ROOT) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def transcode_opus(self, mix, source_path):
        name = self.output_name(mix, "mixes/processed", ".opus")
        output = self.absolute_media_path(name)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                source_path,
                "-vn",
                "-ac",
                "2",
                "-c:a",
                "libopus",
                "-b:a",
                settings.DJMIX_OPUS_BITRATE,
                "-vbr",
                "on",
                str(output),
            ],
            check=True,
        )
        return name

    def transcode_mp3(self, mix, source_path):
        name = self.output_name(mix, "mixes/processed", ".mp3")
        output = self.absolute_media_path(name)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                source_path,
                "-vn",
                "-ac",
                "2",
                "-c:a",
                "libmp3lame",
                "-b:a",
                settings.DJMIX_MP3_BITRATE,
                str(output),
            ],
            check=True,
        )
        return name

    def process_cover(self, mix):
        source_cover = mix.source_cover_image or mix.cover_image
        if not source_cover:
            return "", ""
        large_name = self.output_name(mix, "covers/processed", ".webp")
        thumb_name = self.output_name(mix, "covers/processed", ".webp")
        large_path = self.absolute_media_path(large_name)
        thumb_path = self.absolute_media_path(thumb_name)
        with Image.open(source_cover.path) as image:
            image = image.convert("RGB")
            large = image.copy()
            large.thumbnail((settings.DJMIX_COVER_LARGE_SIZE, settings.DJMIX_COVER_LARGE_SIZE), Image.Resampling.LANCZOS)
            large.save(large_path, "WEBP", quality=82, method=6)

            side = min(image.size)
            left = (image.width - side) // 2
            top = (image.height - side) // 2
            thumb = image.crop((left, top, left + side, top + side))
            thumb = thumb.resize((settings.DJMIX_COVER_THUMB_SIZE, settings.DJMIX_COVER_THUMB_SIZE), Image.Resampling.LANCZOS)
            thumb.save(thumb_path, "WEBP", quality=78, method=6)
        return large_name, thumb_name

    def probe_duration(self, path):
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])

    def generate_waveform(self, path, duration):
        samples = 720
        if not duration:
            return []
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                path,
                "-ac",
                "1",
                "-ar",
                "8000",
                "-f",
                "s16le",
                "-",
            ],
            check=True,
            capture_output=True,
        )
        pcm = result.stdout
        if not pcm:
            return []

        total = len(pcm) // 2
        window = max(total // samples, 1)
        values = []
        peak = 1
        for start in range(0, total, window):
            chunk = pcm[start * 2 : min(total, start + window) * 2]
            if not chunk:
                continue
            count = len(chunk) // 2
            unpacked = struct.unpack(f"<{count}h", chunk)
            rms = math.sqrt(sum(sample * sample for sample in unpacked) / count)
            values.append(rms)
            peak = max(peak, rms)
            if len(values) >= samples:
                break

        normalized = [max(0.035, min(1.0, value / peak)) for value in values]
        return [round(math.sqrt(value), 3) for value in normalized]
