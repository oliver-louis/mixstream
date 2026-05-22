from django.conf import settings
from django.contrib.auth.models import Group
from django.utils.text import slugify
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from .models import Profile


def profile_values_from_claims(claims):
    username = claims.get("preferred_username") or claims.get("nickname") or claims.get("email", "").split("@")[0]
    display_name = username or claims.get("email") or ""
    slug_base = slugify(username or display_name) or "user"
    return display_name[:120], slug_base[:140] or "user"


def profile_default_values(user):
    return {value for value in (user.get_full_name(), user.username, user.email.split("@")[0] if user.email else "") if value}


def unique_profile_slug(base, *, exclude_pk=None):
    slug = base[:140] or "user"
    counter = 2
    while Profile.objects.filter(slug=slug).exclude(pk=exclude_pk).exists():
        suffix = f"-{counter}"
        slug = f"{base[:140 - len(suffix)]}{suffix}"
        counter += 1
    return slug


class AuthentikOIDCBackend(OIDCAuthenticationBackend):
    """Map authentik OIDC users and groups into Django users."""

    def filter_users_by_claims(self, claims):
        email = claims.get("email")
        if not email:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(email__iexact=email)

    def verify_claims(self, claims):
        if not super().verify_claims(claims):
            return False
        if not settings.DJMIX_REQUIRE_GROUP:
            return True
        groups = set(claims.get("groups") or [])
        return bool(groups.intersection({settings.DJMIX_USER_GROUP, settings.DJMIX_ADMIN_GROUP}))

    def create_user(self, claims):
        user = super().create_user(claims)
        return self._sync_user(user, claims)

    def update_user(self, user, claims):
        return self._sync_user(user, claims)

    def _sync_user(self, user, claims):
        groups = set(claims.get("groups") or [])
        username = claims.get("preferred_username") or claims.get("nickname") or claims.get("email", "").split("@")[0]
        previous_profile_defaults = profile_default_values(user)
        user.email = claims.get("email") or user.email
        user.username = username or user.username
        user.first_name = claims.get("given_name") or user.first_name
        user.last_name = claims.get("family_name") or user.last_name
        user.is_active = not settings.DJMIX_REQUIRE_GROUP or settings.DJMIX_ADMIN_GROUP in groups or settings.DJMIX_USER_GROUP in groups
        user.is_staff = settings.DJMIX_ADMIN_GROUP in groups
        user.is_superuser = settings.DJMIX_ADMIN_GROUP in groups
        user.save()
        if settings.DJMIX_USER_GROUP:
            group, _ = Group.objects.get_or_create(name=settings.DJMIX_USER_GROUP)
            user.groups.add(group)
        if settings.DJMIX_ADMIN_GROUP in groups:
            group, _ = Group.objects.get_or_create(name=settings.DJMIX_ADMIN_GROUP)
            user.groups.add(group)
        self._sync_profile(user, claims, previous_defaults=previous_profile_defaults)
        return user

    def _sync_profile(self, user, claims, *, previous_defaults=None):
        profile, _ = Profile.objects.get_or_create(user=user)
        display_name, slug_base = profile_values_from_claims(claims)
        updates = []
        default_display_names = profile_default_values(user) | (previous_defaults or set())
        if display_name and (not profile.display_name or profile.display_name in default_display_names):
            profile.display_name = display_name
            updates.append("display_name")
        if not profile.slug or profile.slug.startswith("user-") or profile.slug in {slugify(value) for value in default_display_names if value}:
            profile.slug = unique_profile_slug(slug_base, exclude_pk=profile.pk)
            updates.append("slug")
        if updates:
            profile.save(update_fields=updates)
