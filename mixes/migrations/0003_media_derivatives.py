from django.db import migrations, models
import django.db.models.deletion
import mixes.models


def copy_existing_sources(apps, schema_editor):
    Mix = apps.get_model("mixes", "Mix")
    for mix in Mix.objects.all().only("pk", "audio_file", "cover_image", "source_audio_file", "source_cover_image", "processing_status"):
        changed = []
        if mix.audio_file and not mix.source_audio_file:
            mix.source_audio_file = mix.audio_file
            changed.append("source_audio_file")
        if mix.cover_image and not mix.source_cover_image:
            mix.source_cover_image = mix.cover_image
            changed.append("source_cover_image")
        if mix.audio_file:
            mix.processing_status = "pending"
            changed.append("processing_status")
        if changed:
            mix.save(update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ("mixes", "0002_genres"),
    ]

    operations = [
        migrations.AddField(
            model_name="mix",
            name="cover_webp_large",
            field=models.ImageField(blank=True, null=True, upload_to=mixes.models.processed_cover_path),
        ),
        migrations.AddField(
            model_name="mix",
            name="cover_webp_thumb",
            field=models.ImageField(blank=True, null=True, upload_to=mixes.models.processed_cover_path),
        ),
        migrations.AddField(
            model_name="mix",
            name="media_processed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="mix",
            name="media_processing_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="mix",
            name="mp3_file",
            field=models.FileField(blank=True, upload_to=mixes.models.processed_audio_path),
        ),
        migrations.AddField(
            model_name="mix",
            name="opus_file",
            field=models.FileField(blank=True, upload_to=mixes.models.processed_audio_path),
        ),
        migrations.AddField(
            model_name="mix",
            name="source_audio_file",
            field=models.FileField(blank=True, upload_to=mixes.models.mix_audio_path),
        ),
        migrations.AddField(
            model_name="mix",
            name="source_cover_image",
            field=models.ImageField(blank=True, null=True, upload_to=mixes.models.cover_path),
        ),
        migrations.RunPython(copy_existing_sources, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="mix",
            index=models.Index(fields=["visibility", "-created_at"], name="mix_visibility_created_idx"),
        ),
        migrations.AddIndex(
            model_name="mix",
            index=models.Index(fields=["owner", "-created_at"], name="mix_owner_created_idx"),
        ),
        migrations.AddIndex(
            model_name="mix",
            index=models.Index(fields=["processing_status", "updated_at"], name="mix_processing_idx"),
        ),
    ]
