import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mixes", "0004_profile_images"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="mix",
            name="unique_listener_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="mix",
            name="view_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="MixViewEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_identity", models.CharField(max_length=80)),
                ("ip_hash", models.CharField(max_length=64)),
                ("user_agent_hash", models.CharField(max_length=64)),
                ("session_key", models.CharField(blank=True, max_length=40)),
                ("referrer", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("mix", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="view_events", to="mixes.mix")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="mix_view_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="MixStreamEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_identity", models.CharField(max_length=80)),
                ("ip_hash", models.CharField(max_length=64)),
                ("user_agent_hash", models.CharField(max_length=64)),
                ("session_key", models.CharField(blank=True, max_length=40)),
                ("codec", models.CharField(blank=True, max_length=16)),
                ("seconds_listened", models.PositiveIntegerField(default=0)),
                ("percent_listened", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("mix", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stream_events", to="mixes.mix")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="mix_stream_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="mixviewevent",
            index=models.Index(fields=["mix", "event_identity", "-created_at"], name="mix_view_dedupe_idx"),
        ),
        migrations.AddIndex(
            model_name="mixviewevent",
            index=models.Index(fields=["mix", "-created_at"], name="mix_view_created_idx"),
        ),
        migrations.AddIndex(
            model_name="mixstreamevent",
            index=models.Index(fields=["mix", "event_identity", "-created_at"], name="mix_stream_dedupe_idx"),
        ),
        migrations.AddIndex(
            model_name="mixstreamevent",
            index=models.Index(fields=["mix", "-created_at"], name="mix_stream_created_idx"),
        ),
    ]
