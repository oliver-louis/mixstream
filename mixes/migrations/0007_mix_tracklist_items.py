from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("mixes", "0006_hide_view_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="MixTracklistItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField(default=0)),
                ("title", models.CharField(max_length=220)),
                ("artist", models.CharField(blank=True, max_length=180)),
                ("url", models.URLField(blank=True)),
                ("start_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("end_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("mix", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tracklist_items", to="mixes.mix")),
            ],
            options={
                "ordering": ["position", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="mixtracklistitem",
            index=models.Index(fields=["mix", "position"], name="tracklist_mix_position_idx"),
        ),
        migrations.AddIndex(
            model_name="mixtracklistitem",
            index=models.Index(fields=["mix", "start_seconds"], name="tracklist_mix_start_idx"),
        ),
    ]
