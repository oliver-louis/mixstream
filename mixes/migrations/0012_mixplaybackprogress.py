import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mixes", "0011_uploadsession"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MixPlaybackProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position_seconds", models.PositiveIntegerField(default=0)),
                ("completed", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mix", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="playback_progress", to="mixes.mix")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mix_playback_progress", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-updated_at"],
                "constraints": [models.UniqueConstraint(fields=("user", "mix"), name="unique_mix_progress_per_user")],
                "indexes": [models.Index(fields=["user", "-updated_at"], name="mix_progress_user_updated_idx")],
            },
        ),
    ]
