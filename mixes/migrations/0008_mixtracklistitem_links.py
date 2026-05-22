from urllib.parse import urlparse

from django.db import migrations, models


def platform_from_url(value):
    hostname = (urlparse(value or "").hostname or "").lower()
    if not hostname:
        return None
    if hostname == "youtu.be" or hostname == "youtube.com" or hostname.endswith(".youtube.com"):
        return "youtube"
    if hostname == "open.spotify.com" or hostname == "spotify.link":
        return "spotify"
    if hostname == "discogs.com" or hostname.endswith(".discogs.com"):
        return "discogs"
    if hostname == "bandcamp.com" or hostname.endswith(".bandcamp.com"):
        return "bandcamp"
    if hostname == "soundcloud.com" or hostname.endswith(".soundcloud.com"):
        return "soundcloud"
    return None


def migrate_legacy_track_links(apps, schema_editor):
    MixTracklistItem = apps.get_model("mixes", "MixTracklistItem")
    for item in MixTracklistItem.objects.all().only("pk", "url", "links"):
        url = (item.url or "").strip()
        platform = platform_from_url(url)
        item.links = {platform: url} if platform else {}
        item.save(update_fields=["links"])


class Migration(migrations.Migration):

    dependencies = [
        ("mixes", "0007_mix_tracklist_items"),
    ]

    operations = [
        migrations.AddField(
            model_name="mixtracklistitem",
            name="links",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(migrate_legacy_track_links, migrations.RunPython.noop),
    ]
