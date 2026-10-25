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