from django.urls import path

from . import views


app_name = "mixes"

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("login/", views.login_start, name="login"),
    path("logout/", views.AppLogoutView.as_view(), name="logout"),
    path("library/", views.library, name="library"),
    path("upload/", views.upload, name="upload"),
    path("profile/edit/", views.edit_profile, name="edit_profile"),
    path("mixes/<int:pk>/edit/", views.edit_mix, name="edit_mix"),
    path("mixes/<int:pk>/tracklist-editor/", views.tracklist_editor, name="tracklist_editor"),
    path("mixes/<int:pk>/tracklist/import/", views.tracklist_import_file, name="tracklist_import_file"),
    path("mixes/<int:pk>/tracklist/export/<str:fmt>/", views.tracklist_export_file, name="tracklist_export_file"),
    path("mixes/<int:pk>/audio/", views.stream_audio, name="stream_audio"),
    path("mixes/<int:pk>/audio/<str:codec>/", views.stream_audio, name="stream_audio_codec"),
    path("mixes/<int:pk>/play/", views.increment_play, name="increment_play"),
    path("mixes/<int:pk>/view/", views.increment_view, name="increment_view"),
    path("mixes/<int:pk>/stream-event/", views.increment_play, name="stream_event"),
    path("@<slug:slug>/", views.profile, name="profile"),
    path("@<slug:profile_slug>/<slug:slug>/", views.detail, name="detail"),
    path("<slug:share_slug>/", views.detail_short, name="detail_short"),
]
