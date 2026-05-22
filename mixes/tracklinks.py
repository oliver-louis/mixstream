from urllib.parse import urlparse


PLATFORM_ORDER = ["discogs", "bandcamp", "soundcloud", "youtube", "spotify"]
PLATFORM_LABELS = {
    "discogs": "Discogs",
    "bandcamp": "Bandcamp",
    "soundcloud": "SoundCloud",
    "youtube": "YouTube",
    "spotify": "Spotify",
}
PLATFORM_ICON_PATHS = {platform: f"{platform}.png" for platform in PLATFORM_ORDER}


def platform_from_url(value):
    parsed = urlparse(value or "")
    hostname = (parsed.hostname or "").lower()
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


def ordered_platform_links(links=None, legacy_url=""):
    ordered = []
    payload = links if isinstance(links, dict) else {}
    for platform in PLATFORM_ORDER:
        url = str(payload.get(platform) or "").strip()
        if url:
            ordered.append(
                {
                    "platform": platform,
                    "label": PLATFORM_LABELS[platform],
                    "icon_path": PLATFORM_ICON_PATHS[platform],
                    "url": url,
                }
            )
    if ordered:
        return ordered
    legacy = str(legacy_url or "").strip()
    platform = platform_from_url(legacy)
    if not platform:
        return []
    return [
        {
            "platform": platform,
            "label": PLATFORM_LABELS[platform],
            "icon_path": PLATFORM_ICON_PATHS[platform],
            "url": legacy,
        }
    ]


def ordered_platform_link_map(links=None, legacy_url=""):
    return {item["platform"]: item["url"] for item in ordered_platform_links(links=links, legacy_url=legacy_url)}
