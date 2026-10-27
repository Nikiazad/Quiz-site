import random
import secrets

from django.db import models
from django.utils import timezone
from django.db import models


class Quiz(models.Model):
    title = models.CharField("title", max_length=200)
    description = models.TextField("description", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Question(models.Model):
    MEDIA_TYPES = [
        ("none", "None"),
        ("image", "Image"),
        ("audio", "Audio"),
        ("video", "Video"),
    ]

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField("Order", default=1)
    text = models.CharField("Question", max_length=300)
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES, default="none")
    media_file = models.FileField(upload_to="questions/", blank=True)
    time_limit = models.PositiveIntegerField("Time (second)", default=20)
    explanation = models.TextField("Explanation", blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.order}. {self.text[:40]}"


class Option(models.Model):
    MEDIA_TYPES = Question.MEDIA_TYPES
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField("option's text", max_length=200, blank=True)
    media_type = models.CharField("Media type", max_length=10, choices=MEDIA_TYPES, default="none")
    media_file = models.FileField("Media file", upload_to="options/", blank=True)
    is_correct = models.BooleanField("Correctness", default=False)

    def __str__(self):
        return self.text or f"گزینه {self.pk}"


def new_code():
    while True:
        code = f"{random.randint(0, 999999):06d}"
        if not Session.objects.filter(code=code).exists():
            return code


class Session(models.Model):
    LOBBY, QUESTION, REVEAL, BOARD, FINISHED = "lobby", "question", "reveal", "board", "finished"
    PHASES = [
        (LOBBY, "Waiting to start"),
        (QUESTION, "Question"),
        (REVEAL, "Reveal answer"),
        (BOARD, "Leaderboard"),
        (FINISHED, "Finished"),
    ]

    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="sessions")
    code = models.CharField(max_length=6, unique=True, default=new_code)
    phase = models.CharField(max_length=10, choices=PHASES, default=LOBBY)
    current_question = models.ForeignKey(Question, null=True, blank=True, on_delete=models.SET_NULL)
    question_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def seconds_left(self):
        if self.phase != self.QUESTION or not self.current_question or not self.question_started_at:
            return 0
        elapsed = (timezone.now() - self.question_started_at).total_seconds()
        return max(0, self.current_question.time_limit - elapsed)

    def __str__(self):
        return f"{self.quiz.title} - {self.code}"


class Player(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="players")
    name = models.CharField(max_length=40)
    token = models.CharField(max_length=32, unique=True, default=secrets.token_hex)
    score = models.PositiveIntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Answer(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    option = models.ForeignKey(Option, on_delete=models.CASCADE)
    points = models.PositiveIntegerField(default=0)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("player", "question")