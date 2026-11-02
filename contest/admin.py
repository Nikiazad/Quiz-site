from django.contrib import admin
from .models import Answer, Option, Player, Question, Quiz, Session


class OptionInline(admin.TabularInline):
    model = Option
    extra = 2


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "order", "text", "media_type", "max_points", "speed_bonus")
    list_editable = ("max_points", "speed_bonus")
    list_filter = ("quiz",)
    inlines = [OptionInline]


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1
    show_change_link = True


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    inlines = [QuestionInline]


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "code", "phase", "created_at")
    readonly_fields = ("code",)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "session", "score")


admin.site.register(Answer)