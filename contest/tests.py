import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.db import IntegrityError, transaction

from .models import Answer, Option, Player, Question, Quiz, Session


class GameTestBase(TestCase):
    def setUp(self):
        self.quiz = Quiz.objects.create(title="Test quiz")
        self.q1 = Question.objects.create(
            quiz=self.quiz, order=1, text="Q1", time_limit=20, explanation="because"
        )
        self.q1_right = Option.objects.create(question=self.q1, text="AI", is_correct=True)
        self.q1_wrong = Option.objects.create(question=self.q1, text="Human")
        self.q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2", time_limit=20)
        self.q2_right = Option.objects.create(question=self.q2, text="Human", is_correct=True)
        self.q2_wrong = Option.objects.create(question=self.q2, text="AI")
        self.session = Session.objects.create(quiz=self.quiz)

    def open_question(self, question=None):
        self.session.current_question = question or self.q1
        self.session.phase = Session.QUESTION
        self.session.question_started_at = timezone.now()
        self.session.save()

    def make_player(self, name="Ali"):
        player = Player.objects.create(session=self.session, name=name)
        client = self.client_class()
        s = client.session
        s["player_token"] = player.token
        s.save()
        return player, client

    def send_answer(self, client, option):
        return client.post(
            reverse("contest:answer", args=[self.session.code]),
            data=json.dumps({"option_id": option.id}),
            content_type="application/json",
        )

    def get_state(self, client):
        return client.get(reverse("contest:state", args=[self.session.code]))


class AnswerTests(GameTestBase):
    def test_correct_answer_gives_points(self):
        self.open_question()
        player, client = self.make_player()
        resp = self.send_answer(client, self.q1_right)
        self.assertEqual(resp.status_code, 200)
        player.refresh_from_db()
        self.assertGreater(player.score, 900)
        self.assertLessEqual(player.score, 1000)
        self.assertEqual(Answer.objects.count(), 1)

    def test_wrong_answer_gives_zero(self):
        self.open_question()
        player, client = self.make_player()
        self.assertEqual(self.send_answer(client, self.q1_wrong).status_code, 200)
        player.refresh_from_db()
        self.assertEqual(player.score, 0)

    def test_second_answer_is_rejected(self):
        self.open_question()
        player, client = self.make_player()
        self.send_answer(client, self.q1_right)
        score_after_first = Player.objects.get(pk=player.pk).score
        resp = self.send_answer(client, self.q1_right)
        self.assertEqual(resp.status_code, 409)
        player.refresh_from_db()
        self.assertEqual(player.score, score_after_first)
        self.assertEqual(Answer.objects.count(), 1)

    def test_answer_after_time_is_up_is_rejected(self):
        self.open_question()
        self.session.question_started_at = timezone.now() - timedelta(seconds=25)
        self.session.save()
        player, client = self.make_player()
        self.assertEqual(self.send_answer(client, self.q1_right).status_code, 400)
        self.assertEqual(Answer.objects.count(), 0)

    def test_answer_outside_question_phase_is_rejected(self):
        self.open_question()
        self.session.phase = Session.REVEAL
        self.session.save()
        player, client = self.make_player()
        self.assertEqual(self.send_answer(client, self.q1_right).status_code, 400)

    def test_option_of_another_question_is_rejected(self):
        self.open_question(self.q1)
        player, client = self.make_player()
        self.assertEqual(self.send_answer(client, self.q2_right).status_code, 400)
        self.assertEqual(Answer.objects.count(), 0)

    def test_faster_answer_scores_more(self):
        self.open_question()
        fast, fast_client = self.make_player("Fast")
        slow, slow_client = self.make_player("Slow")
        self.send_answer(fast_client, self.q1_right)
        self.session.question_started_at = timezone.now() - timedelta(seconds=15)
        self.session.save()
        self.send_answer(slow_client, self.q1_right)
        fast.refresh_from_db()
        slow.refresh_from_db()
        self.assertGreater(fast.score, slow.score)
        self.assertGreater(slow.score, 0)

    def test_anonymous_cannot_answer(self):
        self.open_question()
        resp = self.send_answer(self.client, self.q1_right)
        self.assertEqual(resp.status_code, 403)


class StateTests(GameTestBase):
    def test_correct_flag_hidden_during_question(self):
        self.open_question()
        player, client = self.make_player()
        data = self.get_state(client).json()
        self.assertEqual(data["phase"], Session.QUESTION)
        self.assertTrue(data["question"]["options"])
        for option in data["question"]["options"]:
            self.assertNotIn("is_correct", option)
        self.assertNotIn("explanation", data["question"])

    def test_correct_flag_shown_on_reveal(self):
        self.open_question()
        self.session.phase = Session.REVEAL
        self.session.save()
        player, client = self.make_player()
        data = self.get_state(client).json()
        flags = {o["id"]: o["is_correct"] for o in data["question"]["options"]}
        self.assertTrue(flags[self.q1_right.id])
        self.assertFalse(flags[self.q1_wrong.id])

    def test_state_requires_a_joined_player(self):
        self.assertEqual(self.get_state(self.client).status_code, 403)


class HostTests(GameTestBase):
    def host_post(self, client, action):
        return client.post(reverse("contest:host_action", args=[self.session.code]), {"action": action})

    def staff_client(self):
        user = get_user_model().objects.create_user("host", password="pw", is_staff=True)
        client = self.client_class()
        client.force_login(user)
        return client

    def test_full_flow(self):
        client = self.staff_client()
        self.host_post(client, "start")
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, Session.QUESTION)
        self.assertEqual(self.session.current_question, self.q1)
        self.assertIsNotNone(self.session.question_started_at)

        self.host_post(client, "reveal")
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, Session.REVEAL)

        self.host_post(client, "board")
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, Session.BOARD)

        self.host_post(client, "start")
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, Session.QUESTION)
        self.assertEqual(self.session.current_question, self.q2)

        self.host_post(client, "reveal")
        self.host_post(client, "start")
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, Session.FINISHED)

    def test_start_is_ignored_during_a_live_question(self):
        client = self.staff_client()
        self.open_question()
        self.host_post(client, "start")
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, Session.QUESTION)
        self.assertEqual(self.session.current_question, self.q1)

    def test_anonymous_cannot_control_the_game(self):
        self.host_post(self.client, "start")
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, Session.LOBBY)

    def test_player_cannot_control_the_game(self):
        player, client = self.make_player()
        self.host_post(client, "start")
        self.session.refresh_from_db()
        self.assertEqual(self.session.phase, Session.LOBBY)


class JoinTests(GameTestBase):
    def test_join_with_valid_code(self):
        resp = self.client.post(reverse("contest:join"), {"code": self.session.code, "name": "Niki"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Player.objects.filter(session=self.session, name="Niki").exists())

    def test_join_with_wrong_code(self):
        resp = self.client.post(reverse("contest:join"), {"code": "000000", "name": "Niki"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Player.objects.count(), 0)

    def test_cannot_join_finished_session(self):
        self.session.phase = Session.FINISHED
        self.session.save()
        self.client.post(reverse("contest:join"), {"code": self.session.code, "name": "Niki"})
        self.assertEqual(Player.objects.count(), 0)


    def test_duplicate_name_is_rejected_ignoring_case_and_spaces(self):
        Player.objects.create(session=self.session, name="Niki")
        resp = self.client.post(
            reverse("contest:join"), {"code": self.session.code, "name": "  niki "}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Player.objects.filter(session=self.session).count(), 1)

    def test_same_name_allowed_in_another_session(self):
        other = Session.objects.create(quiz=self.quiz)
        Player.objects.create(session=other, name="Niki")
        resp = self.client.post(
            reverse("contest:join"), {"code": self.session.code, "name": "Niki"}
        )
        self.assertEqual(resp.status_code, 302)

    def test_database_blocks_duplicate_names(self):
        Player.objects.create(session=self.session, name="Niki")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Player.objects.create(session=self.session, name="NIKI")