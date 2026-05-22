from django.db import migrations, models
from django.utils.text import slugify


RESERVED_MIX_SHARE_SLUGS = {
    "admin",
    "health",
    "library",
    "login",
    "mixes",
    "oidc",
    "profile",
    "upload",
}


def populate_mix_share_slugs(apps, schema_editor):
    Mix = apps.get_model("mixes", "Mix")
    used = set(Mix.objects.exclude(share_slug__isnull=True).exclude(share_slug="").values_list("share_slug", flat=True))
    for mix in Mix.objects.order_by("pk"):
        if mix.share_slug:
            continue
        base = slugify(mix.title) or "mix"
        slug = base
        counter = 2
        while slug in RESERVED_MIX_SHARE_SLUGS or slug in used:
            slug = f"{base}-{counter}"
            counter += 1
        mix.share_slug = slug
        mix.save(update_fields=["share_slug"])
        used.add(slug)


def create_share_slug_unique_index(apps, schema_editor):
    schema_editor.execute("DROP INDEX IF EXISTS mixes_mix_share_slug_5fb3eb8e_like")
    schema_editor.execute("DROP INDEX IF EXISTS mixes_mix_share_slug_5fb3eb8e")
    schema_editor.execute("DROP INDEX IF EXISTS mixes_mix_share_slug_uniq")
    schema_editor.execute(
        "CREATE UNIQUE INDEX mixes_mix_share_slug_uniq "
        "ON mixes_mix (share_slug) "
        "WHERE share_slug IS NOT NULL"
    )


def drop_share_slug_unique_index(apps, schema_editor):
    schema_editor.execute("DROP INDEX IF EXISTS mixes_mix_share_slug_uniq")


class Migration(migrations.Migration):

    dependencies = [
        ("mixes", "0008_mixtracklistitem_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="mix",
            name="share_slug",
            field=models.SlugField(blank=True, max_length=220, null=True),
        ),
        migrations.AddField(
            model_name="mix",
            name="short_url_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(populate_mix_share_slugs, migrations.RunPython.noop),
        migrations.RunPython(create_share_slug_unique_index, drop_share_slug_unique_index),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="mix",
                    name="share_slug",
                    field=models.SlugField(blank=True, max_length=220, unique=True),
                ),
            ],
            database_operations=[],
        ),
    ]
