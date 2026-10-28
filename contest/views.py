import json
import io
import socket

import segno

from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.conf import settings
from django.db.models import Count
from django.http import HttpResponse

from .models import Answer, Player, Quiz, Session

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
    if session.phase in (Session.BOARD, Session.FINISHED):
        data["board"] = leaderboard(session)
        data["my_rank"] = session.players.filter(score__gt=player.score).count() + 1
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

def current_player(request):
    token = request.session.get("player_token")
    if not token:
        return None
    return Player.objects.select_related("session").filter(token=token).first()

def join(request):
    me = current_player(request)
    resumable = me is not None and me.session.phase != Session.FINISHED

    if request.method == "GET":
        wanted = request.GET.get("code", "").strip()
        if resumable and wanted in ("", me.session.code):
            return redirect("contest:play", code=me.session.code)
        return render(request, "contest/join.html", {"error": ""})

    error = ""
    code = request.POST.get("code", "").strip()
    name = " ".join(request.POST.get("name", "").split())[:40]
    session = Session.objects.exclude(phase=Session.FINISHED).filter(code=code).first()
    taken = (
        "این اسم توی این مسابقه استفاده شده. اگه خودت قبلاً وارد شده بودی، "
        "از همون مرورگر برگرد. وگرنه یه اسم دیگه انتخاب کن."
    )
    if not session:
        error = "کد اشتباهه یا این مسابقه تموم شده."
    elif resumable and me.session_id == session.id:
        return redirect("contest:play", code=session.code)
    elif not name:
        error = "اسمت رو بنویس."
    elif Player.objects.filter(session=session, name__iexact=name).exists():
        error = taken
    else:
        try:
            with transaction.atomic():
                player = Player.objects.create(session=session, name=name)
        except IntegrityError:
            error = taken
        else:
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


@staff_member_required
def host_home(request):
    if request.method == "POST":
        quiz = get_object_or_404(Quiz, pk=request.POST.get("quiz"))
        session = Session.objects.create(quiz=quiz)
        return redirect("contest:host", code=session.code)
    return render(request, "contest/host_home.html", {
        "quizzes": Quiz.objects.all(),
        "sessions": Session.objects.exclude(phase=Session.FINISHED).order_by("-created_at")[:10],
    })


@staff_member_required
def host(request, code):
    session = get_object_or_404(Session, code=code)
    questions = list(session.quiz.questions.all())
    ids = [q.id for q in questions]
    current_no = ids.index(session.current_question_id) + 1 if session.current_question_id in ids else 0
    answered = 0
    if session.current_question_id:
        answered = Answer.objects.filter(
            question_id=session.current_question_id, player__session=session
        ).count()
    return render(request, "contest/host.html", {
        "session": session,
        "total": len(questions),
        "current_no": current_no,
        "players": session.players.count(),
        "answered": answered,
        "join_url": player_url(request, session),
    })


@staff_member_required
@require_POST
def host_action(request, code):
    session = get_object_or_404(Session, code=code)
    action = request.POST.get("action")
    questions = list(session.quiz.questions.all())
    ids = [q.id for q in questions]

    if action == "start" and session.phase in (Session.LOBBY, Session.REVEAL, Session.BOARD):
        idx = ids.index(session.current_question_id) + 1 if session.current_question_id in ids else 0
        if idx < len(questions):
            session.current_question = questions[idx]
            session.phase = Session.QUESTION
            session.question_started_at = timezone.now()
        else:
            session.phase = Session.FINISHED
    elif action == "reveal" and session.phase == Session.QUESTION:
        session.phase = Session.REVEAL
    elif action == "board" and session.phase == Session.REVEAL:
        session.phase = Session.BOARD
    elif action == "finish":
        session.phase = Session.FINISHED
    session.save()
    return redirect("contest:host", code=session.code)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def player_url(request, session):
    # گوشی‌ها باید آدرس شبکه‌ی محلی رو ببینن، نه 127.0.0.1
    base = getattr(settings, "PUBLIC_BASE_URL", "") or f"http://{lan_ip()}:{request.get_port()}"
    return f"{base}{reverse('contest:join')}?code={session.code}"


def leaderboard(session, limit=10):
    players = session.players.order_by("-score", "joined_at")[:limit]
    return [{"name": p.name, "score": p.score} for p in players]


@staff_member_required
def screen(request, code):
    session = get_object_or_404(Session, code=code)
    return render(request, "contest/screen.html", {"session": session})


@staff_member_required
def screen_qr(request, code):
    session = get_object_or_404(Session, code=code)
    buf = io.BytesIO()
    segno.make(player_url(request, session), error="m").save(
        buf, kind="svg", scale=8, border=2, dark="#111", light="#fff"
    )
    return HttpResponse(buf.getvalue(), content_type="image/svg+xml")


@staff_member_required
def screen_state(request, code):
    session = get_object_or_404(Session, code=code)
    data = {
        "phase": session.phase,
        "title": session.quiz.title,
        "code": session.code,
        "players": session.players.count(),
        "join_url": player_url(request, session),
    }
    q = session.current_question
    if q and session.phase in (Session.QUESTION, Session.REVEAL):
        revealing = session.phase == Session.REVEAL
        counts = {}
        if revealing:
            rows = (Answer.objects.filter(question=q, player__session=session)
                    .values("option_id").annotate(n=Count("id")))
            counts = {r["option_id"]: r["n"] for r in rows}
        options = []
        for o in q.options.order_by("id"):
            item = {"id": o.id, "text": o.text, "media": media_dict(o.media_file, o.media_type)}
            if revealing:
                item["is_correct"] = o.is_correct
                item["count"] = counts.get(o.id, 0)
            options.append(item)
        data["question"] = {
            "id": q.id,
            "text": q.text,
            "media": media_dict(q.media_file, q.media_type),
            "time_limit": q.time_limit,
            "seconds_left": round(session.seconds_left(), 1),
            "answered": Answer.objects.filter(question=q, player__session=session).count(),
            "options": options,
        }
        if revealing:
            data["question"]["explanation"] = q.explanation
    if session.phase in (Session.BOARD, Session.FINISHED):
        data["board"] = leaderboard(session)
    return JsonResponse(data)