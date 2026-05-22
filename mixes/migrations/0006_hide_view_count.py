from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mixes", "0005_stream_analytics"),
    ]

    operations = [
        migrations.AddField(
            model_name="mix",
            name="hide_view_count",
            field=models.BooleanField(default=False),
        ),
    ]
