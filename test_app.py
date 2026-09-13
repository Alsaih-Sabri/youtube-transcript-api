import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app import app, extract_video_id, build_proxy_config, humanize_error, generate_readable_paragraphs
from youtube_transcript_api._transcripts import FetchedTranscript, FetchedTranscriptSnippet, _TranslationLanguage
from youtube_transcript_api._errors import TranscriptsDisabled, VideoUnavailable, IpBlocked
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig


class TestYouTubeTranscriptApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_extract_video_id(self):
        test_cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://www.youtube.com/watch?v=dQw4w9WgXcQ&t=12s", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ?si=abcd", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            (r"\-dQw4w9WgXcQ", "-dQw4w9WgXcQ"),
        ]
        for url, expected in test_cases:
            self.assertEqual(extract_video_id(url), expected)

    def test_build_proxy_config(self):
        # Webshare proxy
        cfg = build_proxy_config(webshare_user="user1", webshare_pass="pass1")
        self.assertIsInstance(cfg, WebshareProxyConfig)

        # Generic proxy
        cfg2 = build_proxy_config(proxy_http="http://localhost:8080")
        self.assertIsInstance(cfg2, GenericProxyConfig)

        # None
        self.assertIsNone(build_proxy_config())

    def test_humanize_error(self):
        err = TranscriptsDisabled("video123")
        res = humanize_error(err, "video123")
        self.assertEqual(res["error_title"], "Subtitles Disabled")

        err = IpBlocked("video123")
        res = humanize_error(err, "video123")
        self.assertIn("IP", res["error_title"])

        err = VideoUnavailable("video123")
        res = humanize_error(err, "video123")
        self.assertIn("Unavailable", res["error_title"])

    def test_health_endpoint(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_index_page(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("YouTube Transcript Studio", res.text)

    def test_fetch_invalid_input(self):
        res = self.client.post("/api/fetch", json={"url_or_id": "abc"})
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertIn("Invalid", data["error_title"])

    @patch("app.YouTubeTranscriptApi")
    def test_fetch_endpoint_success(self, mock_ytt_api_cls):
        # Mock transcript object
        mock_transcript = MagicMock()
        mock_transcript.language = "English"
        mock_transcript.language_code = "en"
        mock_transcript.is_generated = False
        mock_transcript.is_translatable = True
        mock_transcript.translation_languages = [
            _TranslationLanguage(language="Spanish", language_code="es"),
            _TranslationLanguage(language="French", language_code="fr"),
        ]

        fetched = FetchedTranscript(
            snippets=[
                FetchedTranscriptSnippet(text="Hello world", start=0.0, duration=2.0),
                FetchedTranscriptSnippet(text="Welcome to the video", start=2.0, duration=3.0),
            ],
            video_id="dQw4w9WgXcQ",
            language="English",
            language_code="en",
            is_generated=False,
        )
        mock_transcript.fetch.return_value = fetched

        mock_transcript_list = MagicMock()
        mock_transcript_list.__iter__.return_value = [mock_transcript]
        mock_transcript_list.find_transcript.return_value = mock_transcript

        mock_instance = MagicMock()
        mock_instance.list.return_value = mock_transcript_list
        mock_ytt_api_cls.return_value = mock_instance

        res = self.client.post("/api/fetch", json={"url_or_id": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(len(data["transcript"]["snippets"]), 2)
        self.assertEqual(data["transcript"]["snippets"][0]["text"], "Hello world")
        self.assertIn("formatted", data)
        self.assertIn("text", data["formatted"])
        self.assertIn("srt", data["formatted"])
        self.assertIn("vtt", data["formatted"])
        self.assertIn("json", data["formatted"])
        self.assertEqual(len(data["available_transcripts"]), 1)
        self.assertEqual(len(data["translation_languages"]), 2)

    @patch("app.YouTubeTranscriptApi")
    def test_translate_endpoint_success(self, mock_ytt_api_cls):
        mock_source_transcript = MagicMock()
        mock_translated_transcript = MagicMock()

        translated_fetched = FetchedTranscript(
            snippets=[
                FetchedTranscriptSnippet(text="Hola mundo", start=0.0, duration=2.0),
            ],
            video_id="dQw4w9WgXcQ",
            language="Spanish",
            language_code="es",
            is_generated=True,
        )
        mock_translated_transcript.fetch.return_value = translated_fetched
        mock_source_transcript.translate.return_value = mock_translated_transcript
        mock_source_transcript.language = "English"
        mock_source_transcript.language_code = "en"
        mock_source_transcript.is_generated = False
        mock_source_transcript.is_translatable = True
        mock_source_transcript.translation_languages = []

        mock_transcript_list = MagicMock()
        mock_transcript_list.__iter__.return_value = [mock_source_transcript]
        mock_transcript_list.find_transcript.return_value = mock_source_transcript

        mock_instance = MagicMock()
        mock_instance.list.return_value = mock_transcript_list
        mock_ytt_api_cls.return_value = mock_instance

        res = self.client.post(
            "/api/translate",
            json={
                "video_id": "dQw4w9WgXcQ",
                "source_language": "en",
                "target_language": "es",
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["transcript"]["language"], "Spanish")
        self.assertEqual(data["transcript"]["snippets"][0]["text"], "Hola mundo")

    def test_docs_endpoint(self):
        res = self.client.get("/docs")
        self.assertEqual(res.status_code, 200)

    @patch("app.YouTubeTranscriptApi")
    def test_api_get_transcript_json(self, mock_ytt_api_cls):
        mock_transcript = MagicMock()
        mock_transcript.language = "English"
        mock_transcript.language_code = "en"
        mock_transcript.is_generated = False
        mock_transcript.is_translatable = True
        mock_transcript.translation_languages = []

        fetched = FetchedTranscript(
            snippets=[
                FetchedTranscriptSnippet(text="Hello API world", start=0.0, duration=2.5),
            ],
            video_id="dQw4w9WgXcQ",
            language="English",
            language_code="en",
            is_generated=False,
        )
        mock_transcript.fetch.return_value = fetched
        mock_transcript_list = MagicMock()
        mock_transcript_list.__iter__.return_value = [mock_transcript]
        mock_transcript_list.find_transcript.return_value = mock_transcript

        mock_instance = MagicMock()
        mock_instance.list.return_value = mock_transcript_list
        mock_ytt_api_cls.return_value = mock_instance

        # Test GET /api/transcript?url=...
        res = self.client.get("/api/transcript?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(data["text"], "Hello API world")
        self.assertEqual(data["word_count"], 3)
        self.assertEqual(data["duration_seconds"], 2.5)
        self.assertIn("snippets", data)
        self.assertIn("srt", data)

    @patch("app.YouTubeTranscriptApi")
    def test_api_get_transcript_plain_text(self, mock_ytt_api_cls):
        mock_transcript = MagicMock()
        mock_transcript.language = "English"
        mock_transcript.language_code = "en"
        mock_transcript.is_generated = False
        mock_transcript.is_translatable = False
        mock_transcript.translation_languages = []

        fetched = FetchedTranscript(
            snippets=[
                FetchedTranscriptSnippet(text="Plain text line 1", start=0.0, duration=2.0),
                FetchedTranscriptSnippet(text="Plain text line 2", start=2.0, duration=2.0),
            ],
            video_id="dQw4w9WgXcQ",
            language="English",
            language_code="en",
            is_generated=False,
        )
        mock_transcript.fetch.return_value = fetched
        mock_transcript_list = MagicMock()
        mock_transcript_list.__iter__.return_value = [mock_transcript]
        mock_transcript_list.find_transcript.return_value = mock_transcript

        mock_instance = MagicMock()
        mock_instance.list.return_value = mock_transcript_list
        mock_ytt_api_cls.return_value = mock_instance

        res = self.client.get("/api/transcript?url=dQw4w9WgXcQ&format=text")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "text/plain; charset=utf-8")
        self.assertEqual(res.text, "Plain text line 1 Plain text line 2")

    @patch("app.YouTubeTranscriptApi")
    def test_api_post_transcript(self, mock_ytt_api_cls):
        mock_transcript = MagicMock()
        mock_transcript.language = "English"
        mock_transcript.language_code = "en"
        mock_transcript.is_generated = False
        mock_transcript.is_translatable = False
        mock_transcript.translation_languages = []

        fetched = FetchedTranscript(
            snippets=[
                FetchedTranscriptSnippet(text="POST body test", start=0.0, duration=1.0),
            ],
            video_id="dQw4w9WgXcQ",
            language="English",
            language_code="en",
            is_generated=False,
        )
        mock_transcript.fetch.return_value = fetched
        mock_transcript_list = MagicMock()
        mock_transcript_list.__iter__.return_value = [mock_transcript]
        mock_transcript_list.find_transcript.return_value = mock_transcript

        mock_instance = MagicMock()
        mock_instance.list.return_value = mock_transcript_list
        mock_ytt_api_cls.return_value = mock_instance

        res = self.client.post("/api/transcript", json={"url": "dQw4w9WgXcQ"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["text"], "POST body test")

    @patch("app.YouTubeTranscriptApi")
    def test_get_languages_endpoint(self, mock_ytt_api_cls):
        mock_transcript = MagicMock()
        mock_transcript.language = "English"
        mock_transcript.language_code = "en"
        mock_transcript.is_generated = False
        mock_transcript.is_translatable = True
        mock_transcript.translation_languages = [
            _TranslationLanguage(language="Spanish", language_code="es"),
        ]

        mock_transcript_list = MagicMock()
        mock_transcript_list.__iter__.return_value = [mock_transcript]

        mock_instance = MagicMock()
        mock_instance.list.return_value = mock_transcript_list
        mock_ytt_api_cls.return_value = mock_instance

        res = self.client.get("/api/languages?url=dQw4w9WgXcQ")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["transcripts"]), 1)
        self.assertEqual(len(data["translation_languages"]), 1)

    def test_static_css_endpoint(self):
        res = self.client.get("/static/css/styles.css")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/css", res.headers.get("content-type", ""))
        self.assertTrue(len(res.content) > 1000)

    def test_index_no_cdn_tailwindcss(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn("/static/css/styles.css", html)
        self.assertNotIn("cdn.tailwindcss.com", html)

    def test_generate_readable_paragraphs(self):
        # Snippets with natural pause
        snippets = [
            {"text": "hello everyone and welcome back to this video today we are discussing docker and cloudflare", "start": 0.0, "duration": 5.0},
            {"text": "we will see how easy it is to deploy services securely with https and custom domains", "start": 5.0, "duration": 4.0},
            # Gap of 3 seconds (pause from 9.0 to 12.0)
            {"text": "now let us move to the second part of the tutorial where we configure certificates", "start": 12.0, "duration": 6.0},
            {"text": "make sure to follow all the steps carefully.", "start": 18.0, "duration": 3.0},
        ]
        paras = generate_readable_paragraphs(snippets)
        self.assertEqual(len(paras), 2)
        self.assertTrue(paras[0]["text"].startswith("Hello"))
        self.assertTrue(paras[1]["text"].startswith("Now"))
        self.assertEqual(paras[0]["start"], 0.0)
        self.assertEqual(paras[1]["start"], 12.0)
        self.assertGreater(paras[0]["word_count"], 0)

    @patch("app.YouTubeTranscriptApi")
    def test_readable_format_endpoint(self, mock_ytt_api_cls):
        mock_snippet = FetchedTranscriptSnippet(text="welcome to the show.", start=0.0, duration=2.0)
        mock_transcript = FetchedTranscript(
            snippets=[mock_snippet],
            language="English",
            language_code="en",
            is_generated=False,
            video_id="dQw4w9WgXcQ",
        )
        mock_transcript_obj = MagicMock()
        mock_transcript_obj.fetch.return_value = mock_transcript
        mock_transcript_obj.language = "English"
        mock_transcript_obj.language_code = "en"
        mock_transcript_obj.is_generated = False
        mock_transcript_obj.is_translatable = False

        mock_transcript_list = MagicMock()
        mock_transcript_list.__iter__.return_value = [mock_transcript_obj]
        mock_transcript_list.find_transcript.return_value = mock_transcript_obj

        mock_instance = MagicMock()
        mock_instance.list.return_value = mock_transcript_list
        mock_ytt_api_cls.return_value = mock_instance

        # Test format=readable
        res = self.client.get("/api/transcript?url=dQw4w9WgXcQ&format=readable")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Welcome to the show.", res.text)

        # Test JSON endpoint metrics
        res_json = self.client.get("/api/transcript?url=dQw4w9WgXcQ")
        self.assertEqual(res_json.status_code, 200)
        data = res_json.json()
        self.assertEqual(data["word_count"], 4)
        self.assertEqual(data["reading_time_minutes"], 1)
        self.assertIn("readable_text", data)
        self.assertIn("paragraphs", data)
        self.assertEqual(len(data["paragraphs"]), 1)


if __name__ == "__main__":
    unittest.main()
