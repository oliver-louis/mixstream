import django.db.models.deletion
from django.db import migrations, models


DEFAULT_GENRES = [
    "Ambient",
    "Breakbeat",
    "Deep House",
    "Disco",
    "Drum & Bass",
    "Dub Techno",
    "Electro",
    "Garage",
    "Hardgroove",
    "House",
    "Minimal",
    "Progressive House",
    "Tech House",
    "Techno",
    "Trance",
]


def seed_genres(apps, schema_editor):
    Genre = apps.get_model("mixes", "Genre")
    for name in DEFAULT_GENRES:
        Genre.objects.get_or_create(name=name, defaults={"slug": name.lower().replace(" & ", "-").replace(" ", "-")})


class Migration(migrations.Migration):

    dependencies = [
        ("mixes", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Genre",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, unique=True)),
                ("slug", models.SlugField(blank=True, max_length=100, unique=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="mix",
            name="primary_genre",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="primary_mixes", to="mixes.genre"),
        ),
        migrations.AddField(
            model_name="mix",
            name="genres",
            field=models.ManyToManyField(blank=True, related_name="mixes", to="mixes.genre"),
        ),
        migrations.RunPython(seed_genres, migrations.RunPython.noop),
    ]
