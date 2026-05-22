from django.conf import settings
from django.contrib.auth.models import Group
from mozilla_django_oidc.auth import OIDCAuthenticationBackend


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
        user.email = claims.get("email") or user.email
        user.username = username or user.username
        user.first_name = claims.get("given_name") or user.first_name
        user.last_name = claims.get("family_name") or user.last_name
        user.is_active = settings.DJMIX_ADMIN_GROUP in groups or settings.DJMIX_USER_GROUP in groups
        user.is_staff = settings.DJMIX_ADMIN_GROUP in groups
        user.is_superuser = settings.DJMIX_ADMIN_GROUP in groups
        user.save()
        if settings.DJMIX_USER_GROUP:
            group, _ = Group.objects.get_or_create(name=settings.DJMIX_USER_GROUP)
            user.groups.add(group)
        if settings.DJMIX_ADMIN_GROUP in groups:
            group, _ = Group.objects.get_or_create(name=settings.DJMIX_ADMIN_GROUP)
            user.groups.add(group)
        return user
