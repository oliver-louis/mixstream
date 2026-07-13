import json
from datetime import timedelta
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from tempfile import TemporaryDirectory

from mixes.auth import AuthentikOIDCBackend
from mixes.management.commands.process_mix_media import Command
from .forms import parse_tracklist_json_file, parse_tracklist_text, parse_tracklist_upload, tracklist_to_json_payload, tracklist_to_text
from .models import Genre, Mix, MixStreamEvent, MixTracklistItem, MixViewEvent, UploadSession


class MixVisibilityTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tmp.name)
        self.override.enable()
        self.owner = User.objects.create_user(username="owner", email="owner@example.com")
        self.friend = User.objects.create_user(username="friend", email="friend@example.com")
        self.other = User.objects.create_user(username="other", email="other@example.com")
        self.public_mix = Mix.objects.create(
            owner=self.owner,
            title="Public Set",
            audio_file="mixes/public.mp3",
            visibility=Mix.Visibility.PUBLIC,
        )
        self.private_mix = Mix.objects.create(
            owner=self.owner,
            title="Private Set",
            audio_file="mixes/private.mp3",
            visibility=Mix.Visibility.PRIVATE,
        )
        self.private_mix.shared_with.add(self.friend)
        self.owner.profile.slug = "owner-handle"
        self.owner.profile.save(update_fields=["slug"])

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()

    def test_public_mix_is_visible_anonymously(self):
        response = self.client.get(self.public_mix.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_public_mix_has_absolute_social_preview_metadata(self):
        response = self.client.get(self.public_mix.get_absolute_url(), secure=True)

        canonical_url = "https://testserver/@owner-handle/public-set/"
        default_cover_url = "https://testserver/static/mixes/branding/defaultcover.png"
        self.assertContains(response, '<meta name="description" content="Mix by owner on MixStream.">')
        self.assertContains(response, '<meta name="robots" content="index,follow,max-image-preview:large">')
        self.assertContains(response, f'<link rel="canonical" href="{canonical_url}">')
        self.assertContains(response, '<meta property="og:title" content="Public Set">')
        self.assertContains(response, '<meta property="og:type" content="website">')
        self.assertContains(response, f'<meta property="og:url" content="{canonical_url}">')
        self.assertContains(response, f'<meta property="og:image" content="{default_cover_url}">')
        self.assertContains(response, '<meta property="og:image:alt" content="Cover artwork for Public Set">')
        self.assertContains(response, '<meta property="og:site_name" content="MixStream">')
        self.assertContains(response, '<meta name="twitter:card" content="summary_large_image">')
        self.assertContains(response, f'<meta name="twitter:image" content="{default_cover_url}">')

    def test_public_mix_social_metadata_uses_cover_duration_and_escaped_text(self):
        self.public_mix.title = 'Night & "Day"'
        self.public_mix.duration_seconds = 4102
        self.public_mix.cover_webp_large = "covers/processed/1/social.webp"
        self.public_mix.save(update_fields=["title", "duration_seconds", "cover_webp_large"])
        self.owner.profile.display_name = 'DJ & "Ollie"'
        self.owner.profile.save(update_fields=["display_name"])

        response = self.client.get(self.public_mix.get_absolute_url(), secure=True)

        expected_description = "Mix by DJ &amp; &quot;Ollie&quot; · 1:08:22 on MixStream."
        self.assertContains(response, '<meta property="og:title" content="Night &amp; &quot;Day&quot;">')
        self.assertContains(response, f'<meta property="og:description" content="{expected_description}">')
        self.assertContains(response, '<meta property="og:image" content="https://testserver/media/covers/processed/1/social.webp">')
        self.assertContains(response, '<meta property="og:image:alt" content="Cover artwork for Night &amp; &quot;Day&quot;">')
        self.assertContains(response, f'<meta name="twitter:description" content="{expected_description}">')

    def test_public_mix_social_metadata_uses_uploaded_cover_when_processed_cover_is_unavailable(self):
        self.public_mix.cover_image = "covers/1/original.jpg"
        self.public_mix.save(update_fields=["cover_image"])

        response = self.client.get(self.public_mix.get_absolute_url(), secure=True)

        self.assertContains(response, '<meta property="og:image" content="https://testserver/media/covers/1/original.jpg">')
        self.assertContains(response, '<meta name="twitter:image" content="https://testserver/media/covers/1/original.jpg">')

    def test_private_mix_has_no_social_preview_metadata(self):
        for viewer in (self.owner, self.friend):
            with self.subTest(viewer=viewer.username):
                self.client.force_login(viewer)
                response = self.client.get(self.private_mix.get_absolute_url(), secure=True)

                self.assertContains(response, '<meta name="robots" content="noindex,nofollow,noarchive">')
                self.assertNotContains(response, 'rel="canonical"')
                self.assertNotContains(response, 'property="og:')
                self.assertNotContains(response, 'name="twitter:')
                self.assertNotContains(response, '<meta name="description"')

    def test_mix_absolute_url_uses_profile_slug_not_username(self):
        self.assertEqual(self.public_mix.get_absolute_url(), "/@owner-handle/public-set/")

    def test_old_username_based_mix_url_no_longer_resolves(self):
        response = self.client.get("/@owner/public-set/")
        self.assertEqual(response.status_code, 404)

    def test_short_share_url_uses_global_slug(self):
        self.assertEqual(self.public_mix.get_short_share_url(), "/public-set/")

    def test_short_share_slug_suffixes_duplicates(self):
        second_mix = Mix.objects.create(
            owner=self.friend,
            title="Public Set",
            audio_file="mixes/duplicate.mp3",
            visibility=Mix.Visibility.PUBLIC,
        )
        self.assertEqual(second_mix.share_slug, "public-set-2")

    def test_short_share_slug_avoids_reserved_routes(self):
        reserved_mix = Mix.objects.create(
            owner=self.owner,
            title="Library",
            audio_file="mixes/library.mp3",
            visibility=Mix.Visibility.PUBLIC,
        )
        self.assertEqual(reserved_mix.share_slug, "library-2")

    def test_short_share_slug_stays_stable_after_title_change(self):
        original = self.public_mix.share_slug
        self.public_mix.title = "Completely New Name"
        self.public_mix.save(update_fields=["title"])
        self.public_mix.refresh_from_db()
        self.assertEqual(self.public_mix.share_slug, original)

    def test_public_short_share_url_redirects_to_canonical_url(self):
        response = self.client.get(self.public_mix.get_short_share_url())
        self.assertRedirects(response, self.public_mix.get_absolute_url(), fetch_redirect_response=False)

    def test_private_short_share_url_returns_404_when_disabled(self):
        response = self.client.get(self.private_mix.get_short_share_url())
        self.assertEqual(response.status_code, 404)

    def test_private_short_share_url_redirects_for_authorized_user_when_enabled(self):
        self.private_mix.short_url_enabled = True
        self.private_mix.save(update_fields=["short_url_enabled"])
        self.client.force_login(self.friend)

        response = self.client.get(self.private_mix.get_short_share_url())

        self.assertRedirects(response, self.private_mix.get_absolute_url(), fetch_redirect_response=False)

    def test_private_short_share_url_redirects_anonymous_to_login_when_enabled(self):
        self.private_mix.short_url_enabled = True
        self.private_mix.save(update_fields=["short_url_enabled"])

        response = self.client.get(self.private_mix.get_short_share_url())

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"next={self.private_mix.get_short_share_url()}", response["Location"])

    def test_private_short_share_url_forbidden_to_unshared_user_when_enabled(self):
        self.private_mix.short_url_enabled = True
        self.private_mix.save(update_fields=["short_url_enabled"])
        self.client.force_login(self.other)

        response = self.client.get(self.private_mix.get_short_share_url())

        self.assertEqual(response.status_code, 403)

    def test_private_mix_redirects_anonymous_users(self):
        response = self.client.get(self.private_mix.get_absolute_url())
        self.assertEqual(response.status_code, 302)

    def test_private_mix_is_visible_to_shared_user(self):
        self.client.force_login(self.friend)
        response = self.client.get(self.private_mix.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_private_mix_is_forbidden_to_unshared_user(self):
        self.client.force_login(self.other)
        response = self.client.get(self.private_mix.get_absolute_url())
        self.assertEqual(response.status_code, 403)

    def test_public_profile_lists_public_mixes(self):
        response = self.client.get(self.owner.profile.get_absolute_url())
        self.assertContains(response, "Public Set")
        self.assertNotContains(response, "Private Set")

    def test_library_includes_shared_mixes(self):
        self.client.force_login(self.friend)
        response = self.client.get(reverse("mixes:library"))
        self.assertContains(response, "Private Set")

    def test_health_endpoint_checks_database(self):
        response = self.client.get(reverse("mixes:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_processed_audio_uses_x_accel_redirect(self):
        self.public_mix.opus_file = "mixes/processed/1/public.opus"
        self.public_mix.mp3_file = "mixes/processed/1/public.mp3"
        self.public_mix.processing_status = Mix.ProcessingStatus.READY
        self.public_mix.save(update_fields=["opus_file", "mp3_file", "processing_status"])

        response = self.client.get(reverse("mixes:stream_audio_codec", args=[self.public_mix.pk, "opus"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Accel-Redirect"], "/protected-media/mixes/processed/1/public.opus")
        self.assertEqual(response["Accept-Ranges"], "bytes")

    def test_private_processed_audio_forbidden_to_unshared_user(self):
        self.private_mix.opus_file = "mixes/processed/1/private.opus"
        self.private_mix.mp3_file = "mixes/processed/1/private.mp3"
        self.private_mix.processing_status = Mix.ProcessingStatus.READY
        self.private_mix.save(update_fields=["opus_file", "mp3_file", "processing_status"])
        self.client.force_login(self.other)

        response = self.client.get(reverse("mixes:stream_audio_codec", args=[self.private_mix.pk, "opus"]))

        self.assertEqual(response.status_code, 403)

    def test_upload_preserves_source_audio_and_marks_pending(self):
        self.client.force_login(self.owner)
        audio = SimpleUploadedFile("set.mp3", b"ID3\x00\x00\x00\x00\x00\x00\x00", content_type="audio/mpeg")

        response = self.client.post(
            reverse("mixes:upload"),
            {
                "title": "New Upload",
                "description": "",
                "audio_file": audio,
                "visibility": Mix.Visibility.PRIVATE,
                "tracklist_text": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        mix = Mix.objects.get(title="New Upload")
        self.assertEqual(mix.processing_status, Mix.ProcessingStatus.PENDING)
        self.assertTrue(mix.source_audio_file.name)

    def test_direct_upload_accepts_vendor_wave_mime_type(self):
        self.client.force_login(self.owner)
        audio = SimpleUploadedFile("set.wav", b"RIFF\x00\x00\x00\x00WAVEfmt ", content_type="audio/vnd.wave")

        response = self.client.post(
            reverse("mixes:upload"),
            {
                "title": "Wave Upload",
                "description": "",
                "audio_file": audio,
                "visibility": Mix.Visibility.PRIVATE,
                "tracklist_text": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Mix.objects.filter(title="Wave Upload").exists())

    def test_upload_creates_custom_genres_and_can_hide_view_count(self):
        self.client.force_login(self.owner)
        audio = SimpleUploadedFile("set.mp3", b"ID3\x00\x00\x00\x00\x00\x00\x00", content_type="audio/mpeg")

        response = self.client.post(
            reverse("mixes:upload"),
            {
                "title": "Genre Upload",
                "description": "",
                "audio_file": audio,
                "primary_genre_custom": "Dub Techno",
                "genres_custom": "Breaks, Deep House",
                "visibility": Mix.Visibility.PUBLIC,
                "hide_view_count": "on",
                "tracklist_text": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        mix = Mix.objects.get(title="Genre Upload")
        self.assertEqual(mix.primary_genre.name, "Dub Techno")
        self.assertTrue(mix.hide_view_count)
        self.assertEqual(set(mix.genres.values_list("name", flat=True)), {"Breaks", "Deep House"})
        self.assertTrue(Genre.objects.filter(name="Dub Techno").exists())

    def test_structured_tracklist_upload_creates_items(self):
        self.client.force_login(self.owner)
        audio = SimpleUploadedFile("set.mp3", b"ID3\x00\x00\x00\x00\x00\x00\x00", content_type="audio/mpeg")

        response = self.client.post(
            reverse("mixes:upload"),
            {
                "title": "Track ID Upload",
                "description": "",
                "audio_file": audio,
                "visibility": Mix.Visibility.PUBLIC,
                "tracklist_json": json.dumps(
                    [
                        {
                            "start": "0:00",
                            "end": "4:12",
                            "artist": "DJ One",
                            "title": "Opener",
                            "links": {
                                "soundcloud": "https://soundcloud.com/dj-one/opener",
                                "spotify": "https://open.spotify.com/track/123",
                            },
                        },
                        {"artist": "DJ Two", "title": "Untimed Cut"},
                    ]
                ),
                "tracklist_import": "",
                "tracklist_text": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        mix = Mix.objects.get(title="Track ID Upload")
        items = list(mix.tracklist_items.all())
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].artist, "DJ One")
        self.assertEqual(items[0].title, "Opener")
        self.assertEqual(items[0].start_seconds, 0)
        self.assertEqual(items[0].end_seconds, 252)
        self.assertEqual(
            items[0].links,
            {
                "soundcloud": "https://soundcloud.com/dj-one/opener",
                "spotify": "https://open.spotify.com/track/123",
            },
        )
        self.assertEqual(items[1].title, "Untimed Cut")
        self.assertIsNone(items[1].start_seconds)

    def test_edit_mix_shows_tracklist_editor_button_for_saved_mix(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("mixes:edit_mix", args=[self.public_mix.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("mixes:tracklist_editor", args=[self.public_mix.pk]))

    def test_upload_form_shows_disabled_tracklist_editor_for_unsaved_mix(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("mixes:upload"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Save the mix first to open the interactive Track ID editor.")

    def test_edit_mix_shows_short_share_url_for_public_mix(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("mixes:edit_mix", args=[self.public_mix.pk]))

        self.assertContains(response, self.public_mix.get_short_share_url())

    def test_tracklist_editor_requires_owner_or_staff(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("mixes:tracklist_editor", args=[self.public_mix.pk]))

        self.assertEqual(response.status_code, 403)

    def test_tracklist_file_endpoints_require_owner_or_staff(self):
        self.client.force_login(self.other)
        export_response = self.client.get(reverse("mixes:tracklist_export_file", args=[self.public_mix.pk, "json"]))
        import_response = self.client.post(reverse("mixes:tracklist_import_file", args=[self.public_mix.pk]), {"file": SimpleUploadedFile("ids.txt", b"0:30 Artist - Track")})

        self.assertEqual(export_response.status_code, 403)
        self.assertEqual(import_response.status_code, 403)

    def test_tracklist_editor_renders_for_owner(self):
        MixTracklistItem.objects.create(mix=self.public_mix, position=1, title="Existing Track", artist="Artist", start_seconds=42)
        self.public_mix.duration_seconds = 4102
        self.public_mix.save(update_fields=["duration_seconds"])
        self.client.force_login(self.owner)

        response = self.client.get(reverse("mixes:tracklist_editor", args=[self.public_mix.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Waveform editor")
        self.assertContains(response, "Save Track IDs")
        self.assertContains(response, "Existing Track")
        self.assertContains(response, 'data-duration="4102"')
        self.assertContains(response, "data-editor-validation-summary")

    def test_tracklist_editor_save_updates_structured_track_ids(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("mixes:tracklist_editor", args=[self.public_mix.pk]),
            {
                "tracklist_json": json.dumps(
                    [
                        {
                            "start": "5:00",
                            "end": "7:00",
                            "artist": "Second Artist",
                            "title": "Second Track",
                            "links": {"spotify": "https://open.spotify.com/track/xyz"},
                        },
                        {
                            "start": "0:30",
                            "artist": "First Artist",
                            "title": "First Track",
                            "links": {"youtube": "https://youtu.be/example123"},
                        },
                    ]
                )
            },
        )

        self.assertEqual(response.status_code, 302)
        items = list(self.public_mix.tracklist_items.order_by("position"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "First Track")
        self.assertEqual(items[0].start_seconds, 30)
        self.assertIsNone(items[0].end_seconds)
        self.assertEqual(items[0].links, {"youtube": "https://youtu.be/example123"})
        self.assertEqual(items[1].title, "Second Track")
        self.assertEqual(items[1].start_seconds, 300)
        self.assertEqual(items[1].end_seconds, 420)
        self.assertEqual(items[1].links, {"spotify": "https://open.spotify.com/track/xyz"})

    def test_tracklist_editor_rejects_end_without_start(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("mixes:tracklist_editor", args=[self.public_mix.pk]),
            {"tracklist_json": json.dumps([{"end": "1:20", "artist": "Artist", "title": "Broken"}])},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add a start time before using an end time.")

    def test_tracklist_editor_rejects_equal_start_and_end(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("mixes:tracklist_editor", args=[self.public_mix.pk]),
            {"tracklist_json": json.dumps([{"start": "33:36", "end": "33:36", "title": "Needs review"}])},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "End time must be after the start time.")
        self.assertFalse(self.public_mix.tracklist_items.exists())

    def test_tracklist_editor_rejects_unsupported_link_domain(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("mixes:tracklist_editor", args=[self.public_mix.pk]),
            {
                "tracklist_json": json.dumps(
                    [{"start": "0:20", "artist": "Artist", "title": "Bad Link", "links": {"soundcloud": "https://example.com/not-allowed"}}]
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "example.com is not supported.")

    def test_tracklist_import_parser_accepts_dj_timestamp_lines(self):
        rows = parse_tracklist_text(
            "12:34 - 18:20 Artist Name - Track Title https://soundcloud.com/artist/track https://open.spotify.com/track/abc\n"
            "1:02:03 Another Artist - Late Tune"
        )

        self.assertEqual(rows[0]["artist"], "Artist Name")
        self.assertEqual(rows[0]["title"], "Track Title")
        self.assertEqual(rows[0]["start_seconds"], 754)
        self.assertEqual(rows[0]["end_seconds"], 1100)
        self.assertEqual(
            rows[0]["links"],
            {
                "soundcloud": "https://soundcloud.com/artist/track",
                "spotify": "https://open.spotify.com/track/abc",
            },
        )
        self.assertEqual(rows[1]["start_seconds"], 3723)

    def test_tracklist_import_parser_rejects_unsupported_link_domain(self):
        with self.assertRaisesMessage(Exception, "not-supported.example is not supported."):
            parse_tracklist_text("12:34 Artist - Track https://not-supported.example/track")

    def test_tracklist_json_file_round_trips_cleanly(self):
        rows = [
            {
                "title": "First Track",
                "artist": "Artist One",
                "links": {"spotify": "https://open.spotify.com/track/123"},
                "start_seconds": 30,
                "end_seconds": 90,
            }
        ]

        payload = tracklist_to_json_payload(rows)
        restored = parse_tracklist_json_file(json.dumps(payload).encode())

        self.assertEqual(restored[0]["title"], "First Track")
        self.assertEqual(restored[0]["artist"], "Artist One")
        self.assertEqual(restored[0]["start_seconds"], 30)
        self.assertEqual(restored[0]["end_seconds"], 90)
        self.assertEqual(restored[0]["links"], {"spotify": "https://open.spotify.com/track/123"})

    def test_tracklist_json_file_only_allows_invalid_range_in_tolerant_mode(self):
        payload = json.dumps([{"title": "Zero length", "start": "33:36", "end": "33:36"}]).encode()

        with self.assertRaisesMessage(Exception, "End time must be after the start time."):
            parse_tracklist_json_file(payload)

        restored = parse_tracklist_json_file(payload, allow_invalid_time_ranges=True)
        self.assertEqual(restored[0]["start_seconds"], 2016)
        self.assertEqual(restored[0]["end_seconds"], 2016)

    def test_tolerant_tracklist_json_still_rejects_structural_errors(self):
        with self.assertRaisesMessage(Exception, "Track title is required"):
            parse_tracklist_json_file(
                json.dumps([{"start": "1:00", "end": "1:00"}]).encode(),
                allow_invalid_time_ranges=True,
            )
        with self.assertRaisesMessage(Exception, "Use mm:ss or hh:mm:ss"):
            parse_tracklist_json_file(
                json.dumps([{"title": "Bad time", "start": "not-a-time"}]).encode(),
                allow_invalid_time_ranges=True,
            )
        with self.assertRaisesMessage(Exception, "not-supported.example is not supported"):
            parse_tracklist_json_file(
                json.dumps([{"title": "Bad link", "links": {"soundcloud": "https://not-supported.example/track"}}]).encode(),
                allow_invalid_time_ranges=True,
            )

    def test_tracklist_text_export_includes_multiple_links_in_platform_order(self):
        rows = [
            {
                "title": "Track Title",
                "artist": "Artist Name",
                "links": {
                    "spotify": "https://open.spotify.com/track/abc",
                    "soundcloud": "https://soundcloud.com/artist/track",
                },
                "start_seconds": 754,
                "end_seconds": 1100,
            }
        ]

        exported = tracklist_to_text(rows)

        self.assertEqual(
            exported,
            "12:34 - 18:20 Artist Name - Track Title https://soundcloud.com/artist/track https://open.spotify.com/track/abc",
        )

    def test_tracklist_upload_rejects_unsupported_extension(self):
        upload = SimpleUploadedFile("track-ids.csv", b"title,start\nTrack,0:30", content_type="text/csv")

        with self.assertRaisesMessage(Exception, "Track ID files must be .json or .txt."):
            parse_tracklist_upload(upload)

    def test_tracklist_export_json_endpoint_returns_attachment(self):
        MixTracklistItem.objects.create(
            mix=self.public_mix,
            position=1,
            title="Structured Tune",
            artist="Artist",
            start_seconds=30,
            end_seconds=90,
            links={"soundcloud": "https://soundcloud.com/artist/tune"},
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("mixes:tracklist_export_file", args=[self.public_mix.pk, "json"]))

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="public-set-track-ids.json"', response["Content-Disposition"])
        payload = json.loads(response.content.decode())
        self.assertEqual(payload[0]["start"], "0:30")
        self.assertEqual(payload[0]["end"], "1:30")
        self.assertEqual(payload[0]["links"], {"soundcloud": "https://soundcloud.com/artist/tune"})

    def test_tracklist_export_txt_endpoint_returns_attachment(self):
        MixTracklistItem.objects.create(
            mix=self.public_mix,
            position=1,
            title="Structured Tune",
            artist="Artist",
            start_seconds=30,
            links={"youtube": "https://youtu.be/example123"},
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("mixes:tracklist_export_file", args=[self.public_mix.pk, "txt"]))

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="public-set-track-ids.txt"', response["Content-Disposition"])
        self.assertEqual(response.content.decode().strip(), "0:30 Artist - Structured Tune https://youtu.be/example123")

    def test_tracklist_import_file_endpoint_returns_normalized_rows(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            "track-ids.txt",
            b"12:34 - 18:20 Artist Name - Track Title https://soundcloud.com/artist/track https://open.spotify.com/track/abc",
            content_type="text/plain",
        )

        response = self.client.post(reverse("mixes:tracklist_import_file", args=[self.public_mix.pk]), {"file": upload})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["rows"][0]["start"], "12:34")
        self.assertEqual(payload["rows"][0]["end"], "18:20")
        self.assertEqual(payload["rows"][0]["artist"], "Artist Name")
        self.assertEqual(payload["rows"][0]["links"]["soundcloud"], "https://soundcloud.com/artist/track")

    def test_tracklist_import_file_endpoint_preserves_all_rows_with_invalid_ranges(self):
        rows = [
            {"title": f"Track {index}", "start": f"{index}:00", "end": f"{index}:30"}
            for index in range(1, 34)
        ]
        rows[16].update({"start": "33:36", "end": "33:36"})
        rows[18].update({"start": "36:15", "end": "36:15"})
        rows[31].update({"start": "1:04:43", "end": "1:09:06"})
        rows[32].update({"start": "1:07:27", "end": "1:08:22"})
        self.public_mix.duration_seconds = 4102
        self.public_mix.save(update_fields=["duration_seconds"])
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            "reverb.json",
            json.dumps(rows).encode(),
            content_type="application/json",
        )

        response = self.client.post(reverse("mixes:tracklist_import_file", args=[self.public_mix.pk]), {"file": upload})

        self.assertEqual(response.status_code, 200)
        imported = response.json()["rows"]
        self.assertEqual(len(imported), 33)
        by_title = {row["title"]: row for row in imported}
        self.assertEqual(by_title["Track 17"]["start"], "33:36")
        self.assertEqual(by_title["Track 17"]["end"], "33:36")
        self.assertEqual(by_title["Track 19"]["start"], "36:15")
        self.assertEqual(by_title["Track 19"]["end"], "36:15")
        self.assertEqual(by_title["Track 32"]["end"], "1:09:06")
        self.assertEqual(by_title["Track 33"]["end"], "1:08:22")

    def test_tracklist_editor_allows_saving_a_track_past_the_mix_duration(self):
        self.public_mix.duration_seconds = 300
        self.public_mix.save(update_fields=["duration_seconds"])
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("mixes:tracklist_editor", args=[self.public_mix.pk]),
            {"tracklist_json": json.dumps([{"title": "Long outro", "start": "4:30", "end": "5:30"}])},
        )

        self.assertEqual(response.status_code, 302)
        saved = self.public_mix.tracklist_items.get()
        self.assertEqual(saved.start_seconds, 270)
        self.assertEqual(saved.end_seconds, 330)

    def test_tracklist_import_file_endpoint_rejects_invalid_file(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile("track-ids.json", b"{not-json", content_type="application/json")

        response = self.client.post(reverse("mixes:tracklist_import_file", args=[self.public_mix.pk]), {"file": upload})

        self.assertEqual(response.status_code, 400)
        self.assertIn("could not be read", response.json()["error"].lower())

    def test_tracklist_item_rejects_end_before_start(self):
        item = MixTracklistItem(mix=self.public_mix, title="Bad Timing", start_seconds=90, end_seconds=30)

        with self.assertRaisesMessage(Exception, "End time must be after the start time."):
            item.full_clean()

    def test_detail_renders_structured_tracklist_before_legacy_notes(self):
        MixTracklistItem.objects.create(
            mix=self.public_mix,
            position=1,
            title="Structured Tune",
            artist="Artist",
            start_seconds=30,
            links={"discogs": "https://www.discogs.com/release/123"},
        )
        self.public_mix.tracklist_text = "legacy notes"
        self.public_mix.save(update_fields=["tracklist_text"])

        response = self.client.get(self.public_mix.get_absolute_url())

        self.assertContains(response, "Structured Tune")
        self.assertContains(response, "Artist")
        self.assertContains(response, "0:30")
        self.assertContains(response, "legacy notes")
        self.assertContains(response, "mix-tracklist-data")
        self.assertContains(response, 'id="track-id-1"')
        self.assertContains(response, 'data-track-id-key="1"')
        self.assertContains(response, 'data-current-track-list')
        self.assertContains(response, "discogs.png")

    def test_hidden_view_count_hides_all_public_stats(self):
        self.public_mix.hide_view_count = True
        self.public_mix.view_count = 12
        self.public_mix.play_count = 34
        self.public_mix.unique_listener_count = 7
        self.public_mix.save(update_fields=["hide_view_count", "view_count", "play_count", "unique_listener_count"])

        anonymous = self.client.get(self.public_mix.get_absolute_url())
        self.assertNotContains(anonymous, "12 views")
        self.assertNotContains(anonymous, "34 plays")
        self.assertNotContains(anonymous, "7 listeners")

        self.client.force_login(self.owner)
        owner_response = self.client.get(self.public_mix.get_absolute_url())
        self.assertContains(owner_response, "12 views")
        self.assertContains(owner_response, "34 plays")
        self.assertContains(owner_response, "7 listeners")

    def test_public_view_event_increments_once_inside_dedupe_window(self):
        response = self.client.post(reverse("mixes:increment_view", args=[self.public_mix.pk]))
        self.assertEqual(response.status_code, 200)
        self.public_mix.refresh_from_db()
        self.assertEqual(self.public_mix.view_count, 1)
        self.assertEqual(MixViewEvent.objects.filter(mix=self.public_mix).count(), 1)

        response = self.client.post(reverse("mixes:increment_view", args=[self.public_mix.pk]))
        self.assertEqual(response.status_code, 200)
        self.public_mix.refresh_from_db()
        self.assertEqual(self.public_mix.view_count, 1)
        self.assertEqual(MixViewEvent.objects.filter(mix=self.public_mix).count(), 1)

    def test_unauthorized_private_view_creates_no_event(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse("mixes:increment_view", args=[self.private_mix.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(MixViewEvent.objects.filter(mix=self.private_mix).count(), 0)

    def test_stream_event_requires_meaningful_listen_and_dedupes(self):
        self.public_mix.duration_seconds = 300
        self.public_mix.save(update_fields=["duration_seconds"])

        short_response = self.client.post(
            reverse("mixes:stream_event", args=[self.public_mix.pk]),
            data=json.dumps({"codec": "mp3", "seconds_listened": 5, "percent_listened": 2}),
            content_type="application/json",
        )
        self.assertEqual(short_response.status_code, 202)
        self.public_mix.refresh_from_db()
        self.assertEqual(self.public_mix.play_count, 0)

        response = self.client.post(
            reverse("mixes:stream_event", args=[self.public_mix.pk]),
            data=json.dumps({"codec": "mp3", "seconds_listened": 31, "percent_listened": 10}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.public_mix.refresh_from_db()
        self.assertEqual(self.public_mix.play_count, 1)
        self.assertEqual(self.public_mix.unique_listener_count, 1)
        self.assertEqual(MixStreamEvent.objects.filter(mix=self.public_mix).count(), 1)

        response = self.client.post(
            reverse("mixes:stream_event", args=[self.public_mix.pk]),
            data=json.dumps({"codec": "mp3", "seconds_listened": 80, "percent_listened": 26}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.public_mix.refresh_from_db()
        self.assertEqual(self.public_mix.play_count, 1)
        self.assertEqual(MixStreamEvent.objects.filter(mix=self.public_mix).count(), 1)


class MixProcessingTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tmp.name)
        self.override.enable()
        self.owner = User.objects.create_user(username="owner")

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()

    def test_processing_fills_derivatives_and_ready_status(self):
        mix = Mix.objects.create(
            owner=self.owner,
            title="Process Me",
            audio_file=SimpleUploadedFile("source.mp3", b"ID3\x00\x00\x00", content_type="audio/mpeg"),
            processing_status=Mix.ProcessingStatus.PENDING,
        )
        command = Command()
        def probe_duration(path):
            mix.refresh_from_db()
            self.assertEqual(mix.processing_status, Mix.ProcessingStatus.PROCESSING)
            return 123.4

        command.probe_duration = probe_duration
        command.transcode_opus = lambda mix, path: "mixes/processed/1/test.opus"
        command.transcode_mp3 = lambda mix, path: "mixes/processed/1/test.mp3"
        command.process_cover = lambda mix: ("covers/processed/1/large.webp", "covers/processed/1/thumb.webp")
        command.generate_waveform = lambda path, duration: [0.1, 0.8]

        command.process_mix(mix)

        mix.refresh_from_db()
        self.assertEqual(mix.processing_status, Mix.ProcessingStatus.READY)
        self.assertEqual(mix.duration_seconds, 123)
        self.assertEqual(mix.waveform, [0.1, 0.8])
        self.assertEqual(mix.opus_file.name, "mixes/processed/1/test.opus")
        self.assertEqual(mix.mp3_file.name, "mixes/processed/1/test.mp3")
        self.assertTrue(mix.media_processed_at)


class ChunkedUploadTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tmp.name, DJMIX_MAX_UPLOAD_BYTES=100, DJMIX_MAX_CHUNK_BYTES=10)
        self.override.enable()
        self.owner = User.objects.create_user(username="owner", password="password")
        self.other = User.objects.create_user(username="other", password="password")
        self.client.login(username="owner", password="password")

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()

    def start_upload(self, *, size=11, chunk_size=6, filename="source.mp3", content_type="audio/mpeg"):
        return self.client.post(
            reverse("mixes:chunked_upload_start"),
            {
                "title": "Chunky Mix",
                "visibility": Mix.Visibility.PRIVATE,
                "tracklist_json": "[]",
                "audio_filename": filename,
                "audio_content_type": content_type,
                "audio_size": str(size),
                "chunk_size": str(chunk_size),
            },
        )

    def test_chunked_upload_requires_login(self):
        self.client.logout()

        response = self.start_upload()

        self.assertEqual(response.status_code, 302)

    def test_chunked_upload_start_rejects_files_over_upload_limit(self):
        response = self.start_upload(size=101)

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_chunked_upload_start_accepts_vendor_wave_mime_type(self):
        response = self.start_upload(filename="source.wav", content_type="audio/vnd.wave")

        self.assertEqual(response.status_code, 200)

    def test_chunk_endpoint_rejects_oversized_and_duplicate_chunks(self):
        upload_id = self.start_upload().json()["upload_id"]

        response = self.client.post(
            reverse("mixes:chunked_upload_chunk", args=[upload_id]),
            {"index": "0", "chunk": SimpleUploadedFile("chunk.part", b"x" * 11)},
        )

        self.assertEqual(response.status_code, 413)

        response = self.client.post(
            reverse("mixes:chunked_upload_chunk", args=[upload_id]),
            {"index": "0", "chunk": SimpleUploadedFile("chunk.part", b"ID3abc")},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("mixes:chunked_upload_chunk", args=[upload_id]),
            {"index": "0", "chunk": SimpleUploadedFile("chunk.part", b"ID3abc")},
        )
        self.assertEqual(response.status_code, 409)

    def test_complete_assembles_chunks_creates_pending_mix_and_removes_temp_files(self):
        payload = self.start_upload(size=11, chunk_size=6).json()
        upload_id = payload["upload_id"]
        self.client.post(reverse("mixes:chunked_upload_chunk", args=[upload_id]), {"index": "0", "chunk": SimpleUploadedFile("chunk.part", b"ID3abc")})
        self.client.post(reverse("mixes:chunked_upload_chunk", args=[upload_id]), {"index": "1", "chunk": SimpleUploadedFile("chunk.part", b"defgh")})

        response = self.client.post(reverse("mixes:chunked_upload_complete", args=[upload_id]))

        self.assertEqual(response.status_code, 200)
        mix = Mix.objects.get(pk=response.json()["mix_id"])
        self.assertEqual(mix.processing_status, Mix.ProcessingStatus.PENDING)
        self.assertEqual(mix.original_filename, "source.mp3")
        self.assertTrue(mix.audio_file.storage.exists(mix.audio_file.name))
        upload_session = UploadSession.objects.get(upload_id=upload_id)
        self.assertEqual(upload_session.status, UploadSession.Status.COMPLETED)
        self.assertFalse(upload_session.upload_dir.exists())

    def test_complete_rejects_incomplete_upload(self):
        upload_id = self.start_upload(size=11, chunk_size=6).json()["upload_id"]

        response = self.client.post(reverse("mixes:chunked_upload_complete", args=[upload_id]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["missing"], [0, 1])

    def test_chunk_uploads_are_owner_scoped(self):
        upload_id = self.start_upload().json()["upload_id"]
        self.client.logout()
        self.client.login(username="other", password="password")

        response = self.client.post(
            reverse("mixes:chunked_upload_chunk", args=[upload_id]),
            {"index": "0", "chunk": SimpleUploadedFile("chunk.part", b"ID3abc")},
        )

        self.assertEqual(response.status_code, 404)

    def test_abort_and_cleanup_remove_temp_files(self):
        upload_id = self.start_upload().json()["upload_id"]
        self.client.post(reverse("mixes:chunked_upload_chunk", args=[upload_id]), {"index": "0", "chunk": SimpleUploadedFile("chunk.part", b"ID3abc")})
        upload_session = UploadSession.objects.get(upload_id=upload_id)
        self.assertTrue(upload_session.upload_dir.exists())

        response = self.client.post(reverse("mixes:chunked_upload_abort", args=[upload_id]))

        self.assertEqual(response.status_code, 200)
        upload_session.refresh_from_db()
        self.assertEqual(upload_session.status, UploadSession.Status.ABORTED)
        self.assertFalse(upload_session.upload_dir.exists())

        old_upload = UploadSession.objects.create(
            owner=self.owner,
            filename="old.mp3",
            total_size=6,
            chunk_size=6,
            total_chunks=1,
            metadata={"title": "Old"},
        )
        old_upload.upload_dir.mkdir(parents=True)
        old_upload.chunk_path(0).write_bytes(b"ID3abc")
        UploadSession.objects.filter(pk=old_upload.pk).update(created_at=timezone.now() - timedelta(hours=25))
        call_command("cleanup_upload_sessions", verbosity=0)
        old_upload.refresh_from_db()
        self.assertEqual(old_upload.status, UploadSession.Status.ABORTED)
        self.assertFalse(old_upload.upload_dir.exists())


class AuthentikOIDCBackendTests(TestCase):
    def claims(self, **overrides):
        data = {
            "email": "dj@example.com",
            "preferred_username": "dj",
            "given_name": "Dee",
            "family_name": "Jay",
            "groups": [],
        }
        data.update(overrides)
        return data

    @override_settings(DJMIX_REQUIRE_GROUP=False)
    def test_user_is_active_when_group_requirement_is_disabled(self):
        user = User.objects.create_user(username="old", email="dj@example.com", is_active=False)
        backend = AuthentikOIDCBackend()

        synced = backend.update_user(user, self.claims(groups=[]))

        synced.refresh_from_db()
        self.assertTrue(synced.is_active)
        self.assertFalse(synced.is_staff)
        self.assertFalse(synced.is_superuser)

    @override_settings(DJMIX_REQUIRE_GROUP=True, DJMIX_USER_GROUP="djmix-users", DJMIX_ADMIN_GROUP="djmix-admins")
    def test_user_group_keeps_user_active_without_admin_privileges(self):
        user = User.objects.create_user(username="old", email="dj@example.com", is_active=False)
        backend = AuthentikOIDCBackend()

        synced = backend.update_user(user, self.claims(groups=["djmix-users"]))

        synced.refresh_from_db()
        self.assertTrue(synced.is_active)
        self.assertFalse(synced.is_staff)
        self.assertFalse(synced.is_superuser)

    @override_settings(DJMIX_REQUIRE_GROUP=True, DJMIX_USER_GROUP="djmix-users", DJMIX_ADMIN_GROUP="djmix-admins")
    def test_admin_group_grants_staff_and_superuser(self):
        user = User.objects.create_user(username="old", email="dj@example.com", is_active=False)
        backend = AuthentikOIDCBackend()

        synced = backend.update_user(user, self.claims(groups=["djmix-admins"]))

        synced.refresh_from_db()
        self.assertTrue(synced.is_active)
        self.assertTrue(synced.is_staff)
        self.assertTrue(synced.is_superuser)

    @override_settings(DJMIX_REQUIRE_GROUP=False)
    def test_profile_uses_authentik_username_for_display_name_and_slug(self):
        user = User.objects.create_user(username="old", email="dj@example.com")
        user.profile.display_name = "Dee Jay"
        user.profile.slug = "dee-jay"
        user.profile.save(update_fields=["display_name", "slug"])
        backend = AuthentikOIDCBackend()

        backend.update_user(user, self.claims(preferred_username="olouis"))

        user.profile.refresh_from_db()
        self.assertEqual(user.profile.display_name, "olouis")
        self.assertEqual(user.profile.slug, "olouis")

    @override_settings(DJMIX_REQUIRE_GROUP=False)
    def test_profile_slug_gets_suffix_when_authentik_username_is_taken(self):
        existing = User.objects.create_user(username="existing", email="existing@example.com")
        existing.profile.slug = "olouis"
        existing.profile.save(update_fields=["slug"])
        user = User.objects.create_user(username="old", email="dj@example.com")
        backend = AuthentikOIDCBackend()

        backend.update_user(user, self.claims(preferred_username="olouis"))

        user.profile.refresh_from_db()
        self.assertEqual(user.profile.display_name, "olouis")
        self.assertEqual(user.profile.slug, "olouis-2")

    @override_settings(DJMIX_REQUIRE_GROUP=False)
    def test_profile_sync_keeps_intentional_profile_edits(self):
        user = User.objects.create_user(username="old", email="dj@example.com")
        user.profile.display_name = "Custom Name"
        user.profile.slug = "custom-handle"
        user.profile.save(update_fields=["display_name", "slug"])
        backend = AuthentikOIDCBackend()

        backend.update_user(user, self.claims(preferred_username="olouis"))

        user.profile.refresh_from_db()
        self.assertEqual(user.profile.display_name, "Custom Name")
        self.assertEqual(user.profile.slug, "custom-handle")


class LogoutTests(TestCase):
    def test_logout_clears_local_session(self):
        user = User.objects.create_user(username="dj", email="dj@example.com", password="password")
        self.client.login(username="dj", password="password")
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("mixes:logout"))

        self.assertRedirects(response, reverse("mixes:home"))
        self.assertNotIn("_auth_user_id", self.client.session)
