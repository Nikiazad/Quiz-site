import json

from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Answer, Player, Session

MAX_POINTS = 1000

def media_dict(file_field, media_type):
    if media_type == "none" or not file_field:
        return None
    return {"type": media_type, "url": file_field.url}


def state(request, code):
    session = get_object_or_404(Session, code=code)
    token = request.session.get("player_token")
    player = Player.objects.filter(token=token, session=session).first()
    if not player:
        return JsonResponse({"error": "not_joined"}, status=403)

    data = {
        "phase": session.phase,
        "player": {"name": player.name, "score": player.score},
    }
    q = session.current_question
    if q and session.phase in (Session.QUESTION, Session.REVEAL):
        revealing = session.phase == Session.REVEAL
        options = []
        for o in q.options.order_by("id"):
            item = {"id": o.id, "text": o.text, "media": media_dict(o.media_file, o.media_type)}
            if revealing:
                item["is_correct"] = o.is_correct
            options.append(item)
        data["question"] = {
            "id": q.id,
            "text": q.text,
            "media": media_dict(q.media_file, q.media_type),
            "time_limit": q.time_limit,
            "seconds_left": round(session.seconds_left(), 1),
            "options": options,
        }

        mine = Answer.objects.filter(player=player, question=q).first()
        data["question"]["my_option"] = mine.option_id if mine else None
        if revealing and mine:
            data["question"]["my_points"] = mine.points
            
        if revealing:
            data["question"]["explanation"] = q.explanation
    return JsonResponse(data)


def join(request):
    error = ""
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        name = request.POST.get("name", "").strip()[:40]
        session = Session.objects.exclude(phase=Session.FINISHED).filter(code=code).first()
        if not session:
            error = "کد اشتباهه یا این مسابقه تموم شده."
        elif not name:
            error = "اسمت رو بنویس."
        else:
            player = Player.objects.create(session=session, name=name)
            request.session["player_token"] = player.token
            return redirect("contest:play", code=session.code)
    return render(request, "contest/join.html", {"error": error})


def play(request, code):
    session = get_object_or_404(Session, code=code)
    token = request.session.get("player_token")
    player = Player.objects.filter(token=token, session=session).first()
    if not player:
        return redirect("contest:join")
    return render(request, "contest/play.html", {"session": session, "player": player})


@require_POST
def answer(request, code):
    session = get_object_or_404(Session, code=code)
    token = request.session.get("player_token")
    player = Player.objects.filter(token=token, session=session).first()
    if not player:
        return JsonResponse({"error": "not_joined"}, status=403)

    q = session.current_question
    if session.phase != Session.QUESTION or not q:
        return JsonResponse({"error": "not_open"}, status=400)

    left = session.seconds_left()
    if left <= 0:
        return JsonResponse({"error": "time_up"}, status=400)

    try:
        option_id = int(json.loads(request.body).get("option_id"))
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({"error": "bad_request"}, status=400)

    option = q.options.filter(id=option_id).first()
    if not option:
        return JsonResponse({"error": "bad_option"}, status=400)

    points = 0
    if option.is_correct:
        points = int(MAX_POINTS * (0.5 + 0.5 * left / max(q.time_limit, 1)))

    try:
        with transaction.atomic():
            Answer.objects.create(player=player, question=q, option=option, points=points)
            Player.objects.filter(pk=player.pk).update(score=F("score") + points)
    except IntegrityError:
        return JsonResponse({"error": "already_answered"}, status=409)
    return JsonResponse({"ok": True})