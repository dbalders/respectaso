from django.conf import settings


def version(request):
    """Expose VERSION, IS_NATIVE_APP, and INSTALLED_APPS to all templates."""
    return {
        "VERSION": settings.VERSION,
        "LOCAL_FORK": True,
        "is_pro": True,
        "IS_NATIVE_APP": getattr(settings, "IS_NATIVE_APP", False),
        "INSTALLED_APPS": settings.INSTALLED_APPS,
    }
