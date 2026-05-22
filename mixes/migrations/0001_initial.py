import django.db.models.deletion
import mixes.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Profile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(blank=True, max_length=120)),
                ("slug", models.SlugField(blank=True, max_length=140, unique=True)),
                ("bio", models.TextField(blank=True)),
                ("public_enabled", models.BooleanField(default=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="Mix",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("slug", models.SlugField(blank=True, max_length=220)),
                ("description", models.TextField(blank=True)),
                ("audio_file", models.FileField(upload_to=mixes.models.mix_audio_path)),
                ("cover_image", models.ImageField(blank=True, null=True, upload_to=mixes.models.cover_path)),
                ("visibility", models.CharField(choices=[("public", "Public"), ("private", "Private")], default="private", max_length=16)),
                ("tracklist_text", models.TextField(blank=True)),
                ("duration_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("waveform", models.JSONField(blank=True, null=True)),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("processing_status", models.CharField(choices=[("pending", "Pending"), ("ready", "Ready"), ("failed", "Failed")], default="pending", max_length=16)),
                ("processing_error", models.TextField(blank=True)),
                ("play_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mixes", to=settings.AUTH_USER_MODEL)),
                ("shared_with", models.ManyToManyField(blank=True, related_name="shared_mixes", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="mix",
            constraint=models.UniqueConstraint(fields=("owner", "slug"), name="unique_mix_slug_per_owner"),
        ),
    ]
