from django.db import migrations, models
import mixes.models


class Migration(migrations.Migration):

    dependencies = [
        ("mixes", "0003_media_derivatives"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="avatar_image",
            field=models.ImageField(blank=True, null=True, upload_to=mixes.models.profile_image_path),
        ),
        migrations.AddField(
            model_name="profile",
            name="banner_image",
            field=models.ImageField(blank=True, null=True, upload_to=mixes.models.profile_image_path),
        ),
    ]
