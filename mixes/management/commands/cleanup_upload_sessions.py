from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from mixes.models import UploadSession


class Command(BaseCommand):
    help = "Remove abandoned chunked upload sessions and temporary chunk files."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24, help="Clean upload sessions older than this many hours.")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be cleaned without deleting files.")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options["hours"])
        sessions = UploadSession.objects.filter(status=UploadSession.Status.UPLOADING, created_at__lt=cutoff)
        count = sessions.count()
        if options["dry_run"]:
            self.stdout.write(f"Would clean {count} abandoned upload session(s).")
            return
        for upload_session in sessions:
            upload_session.status = UploadSession.Status.ABORTED
            upload_session.save(update_fields=["status", "updated_at"])
            upload_session.discard_files()
        self.stdout.write(self.style.SUCCESS(f"Cleaned {count} abandoned upload session(s)."))
