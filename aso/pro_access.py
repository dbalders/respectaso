"""Public-source capabilities in this independently maintained fork.

All bundled research and queue features are available. This does not load,
patch, or activate upstream's separately distributed proprietary modules.
"""


def has_pro_license():
    """Compatibility name used by upstream for public feature availability."""
    return True


def pro_required_json(view_func):
    """Public-source routes need no license in this fork."""
    return view_func
