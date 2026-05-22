import json
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from tempfile import TemporaryDirectory

from mixes.management.commands.process_mix_media import Command
from .forms import parse_tracklist_json_file, parse_tracklist_text, parse_tracklist_upload, tracklist_to_json_payload, tracklist_to_text
from .models import Genre, Mix, MixStreamEvent, MixTracklistItem, MixViewEvent


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
        self.client.force_login(self.owner)

        response = self.client.get(reverse("mixes:tracklist_editor", args=[self.public_mix.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Waveform editor")
        self.assertContains(response, "Save Track IDs")
        self.assertContains(response, "Existing Track")

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
        command.probe_duration = lambda path: 123.4
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
