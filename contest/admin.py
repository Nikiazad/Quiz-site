from django.contrib import admin
from .models import Quiz, Question, Option


class OptionInline(admin.TabularInline):
    model = Option
    extra = 2


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "order", "text", "media_type")
    list_filter = ("quiz",)
    inlines = [OptionInline]


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1
    show_change_link = True


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    inlines = [QuestionInline]