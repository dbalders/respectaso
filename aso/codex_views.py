"""CSRF-protected local UI for the independent Codex workflow."""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from . import codex_ai, run_queue
from .forms import COUNTRY_CHOICES
from .models import CodexRun
from .apple_ads import discovery
from .research_pipeline import app_id_from_input


def payload(row):
    return {"id": row.pk, "mode": row.mode, "brief": row.brief, "seed": row.seed,
            "promoted_app_id": row.promoted_app_id, "competitor_app_id": row.competitor_app_id,
            "discovery": row.discovery_data, "country": row.country, "status": row.status, "progress": row.progress_message,
            "error": row.error_message, "report": row.report, "evidence": row.evidence,
            "created_at": row.created_at.isoformat(),
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None}


@never_cache
@require_GET
def workspace(request):
    from pathlib import Path
    from django.conf import settings
    revision = int((Path(settings.BASE_DIR) / "static/js/codex-workspace.js").stat().st_mtime)
    return render(request, "aso/codex.html", {"countries": COUNTRY_CHOICES, "asset_revision": revision})


@never_cache
@require_GET
def status(request):
    return JsonResponse({**codex_ai.connection_status(), "apple": discovery.connection_status()})


@require_http_methods(["GET", "POST"])
def runs(request):
    if request.method == "GET":
        return JsonResponse({"runs": [payload(r) for r in CodexRun.objects.all()[:30]]})
    mode = request.POST.get("mode", "research")
    brief = request.POST.get("brief", "").strip()
    seed = request.POST.get("seed", "").strip()
    country = request.POST.get("country", "us")
    if mode not in ("research", "competitor", "metadata") or not 5 <= len(brief) <= 12000 or len(seed) > 200 or country not in dict(COUNTRY_CHOICES):
        return JsonResponse({"error": "Choose a valid mode and country; enter a brief of 5–12,000 characters and a seed of at most 200 characters."}, status=400)
    if not codex_ai.connection_status()["connected"]:
        return JsonResponse({"error": "Sign into Codex with ChatGPT in Terminal first: codex login"}, status=409)
    try:
        promoted = app_id_from_input(request.POST.get("promoted_app_id", ""))
        competitor = app_id_from_input(request.POST.get("competitor_app_id", ""))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    row = CodexRun.objects.create(mode=mode, brief=brief, seed=seed, country=country,
                                 promoted_app_id=promoted, competitor_app_id=competitor)
    run_queue.kick()
    return JsonResponse(payload(row), status=202)


@require_GET
def detail(request, pk):
    return JsonResponse(payload(get_object_or_404(CodexRun, pk=pk)))


@require_POST
def retry(request, pk):
    row = get_object_or_404(CodexRun, pk=pk)
    if not CodexRun.objects.filter(pk=pk, status="failed").update(status="queued", error_message="", progress_message="Queued", queue_rank=None, started_at=None, finished_at=None, report={}, evidence=[], discovery_data={}):
        return JsonResponse({"error": "Only failed runs can be retried."}, status=409)
    run_queue.kick()
    row.refresh_from_db()
    return JsonResponse(payload(row), status=202)
