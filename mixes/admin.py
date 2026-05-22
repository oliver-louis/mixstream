from django.contrib import admin

from .models import Genre, Mix, MixStreamEvent, MixViewEvent, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "slug", "public_enabled")
    search_fields = ("display_name", "slug", "user__username", "user__email")
    prepopulated_fields = {"slug": ("display_name",)}


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Mix)
class MixAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "primary_genre", "visibility", "processing_status", "view_count", "play_count", "created_at")
    list_filter = ("primary_genre", "visibility", "processing_status", "created_at")
    search_fields = ("title", "description", "owner__username", "owner__email")
    autocomplete_fields = ("owner", "shared_with", "primary_genre", "genres")
    readonly_fields = ("duration_seconds", "waveform", "processing_error", "created_at", "updated_at")


@admin.register(MixViewEvent)
class MixViewEventAdmin(admin.ModelAdmin):
    list_display = ("mix", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("mix__title", "user__username", "event_identity")
    readonly_fields = ("mix", "user", "event_identity", "ip_hash", "user_agent_hash", "session_key", "referrer", "created_at")


@admin.register(MixStreamEvent)
class MixStreamEventAdmin(admin.ModelAdmin):
    list_display = ("mix", "user", "codec", "seconds_listened", "percent_listened", "created_at")
    list_filter = ("codec", "created_at")
    search_fields = ("mix__title", "user__username", "event_identity")
    readonly_fields = ("mix", "user", "event_identity", "ip_hash", "user_agent_hash", "session_key", "codec", "seconds_listened", "percent_listened", "created_at")
