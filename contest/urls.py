from django.urls import path
from . import views

app_name = "contest"

urlpatterns = [
    path("", views.join, name="join"),
    path("play/<str:code>/", views.play, name="play"),
    path("api/<str:code>/state/", views.state, name="state"),
    path("api/<str:code>/answer/", views.answer, name="answer"),
]