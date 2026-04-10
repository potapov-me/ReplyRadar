"""Тесты парсера Telegram Desktop Export."""

from __future__ import annotations

import pytest

from replyradar.ingestion.tg_export_parser import ParsedChat, parse_export


def _make_export(**kwargs: object) -> dict:
    base: dict = {
        "name": "Test Chat",
        "type": "personal_chat",
        "id": 123456789,
        "messages": [],
    }
    base.update(kwargs)
    return base


def _make_message(**kwargs: object) -> dict:
    base: dict = {
        "id": 1,
        "type": "message",
        "date": "2024-01-15T10:30:00",
        "from": "Alice",
        "from_id": "user987654321",
        "text": "Hello",
    }
    # "from" — зарезервированное слово Python; принимаем as from_
    if "from_" in kwargs:
        base["from"] = kwargs.pop("from_")  # type: ignore[misc]
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Формат одного чата
# ---------------------------------------------------------------------------


class TestSingleChatFormat:
    def test_returns_list_with_one_element(self) -> None:
        result = parse_export(_make_export(messages=[_make_message()]))
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ParsedChat)

    def test_chat_fields(self) -> None:
        result = parse_export(_make_export(name="My Chat", id=111, type="personal_chat"))
        chat = result[0]
        assert chat.telegram_id == 111
        assert chat.title == "My Chat"

    def test_empty_name_becomes_none(self) -> None:
        result = parse_export(_make_export(name="", messages=[]))
        assert result[0].title is None

    def test_missing_messages_raises(self) -> None:
        with pytest.raises(ValueError, match="messages"):
            parse_export({"id": 1, "type": "personal_chat"})

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValueError, match="id"):
            parse_export({"name": "x", "type": "personal_chat", "messages": []})

    def test_unknown_format_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_export({"about": "something", "contacts": []})


# ---------------------------------------------------------------------------
# Формат полного экспорта аккаунта
# ---------------------------------------------------------------------------


class TestAccountExportFormat:
    def _make_account_export(
        self,
        chats: list[dict] | None = None,
        left_chats: list[dict] | None = None,
    ) -> dict:
        return {
            "about": "Telegram Desktop",
            "chats": {"about": "...", "list": chats or []},
            "left_chats": {"about": "...", "list": left_chats or []},
        }

    def test_parses_chats_list(self) -> None:
        chat1 = _make_export(id=1, name="Chat A", messages=[_make_message(id=10)])
        chat2 = _make_export(id=2, name="Chat B", messages=[_make_message(id=20)])
        result = parse_export(self._make_account_export(chats=[chat1, chat2]))
        assert len(result) == 2
        assert {r.telegram_id for r in result} == {1, 2}

    def test_includes_left_chats(self) -> None:
        chat = _make_export(id=1, messages=[_make_message()])
        left = _make_export(id=2, messages=[_make_message()])
        result = parse_export(self._make_account_export(chats=[chat], left_chats=[left]))
        assert len(result) == 2

    def test_skips_malformed_chat_in_list(self) -> None:
        good = _make_export(id=1, messages=[_make_message()])
        bad = {"name": "broken"}  # нет id и messages
        result = parse_export(self._make_account_export(chats=[good, bad]))
        assert len(result) == 1
        assert result[0].telegram_id == 1

    def test_empty_chats_raises(self) -> None:
        with pytest.raises(ValueError, match="чата"):
            parse_export(self._make_account_export(chats=[], left_chats=[]))

    def test_messages_count_correct(self) -> None:
        msgs = [_make_message(id=i) for i in range(1, 6)]
        chat = _make_export(id=99, messages=msgs)
        result = parse_export(self._make_account_export(chats=[chat]))
        assert len(result[0].messages) == 5


# ---------------------------------------------------------------------------
# Нормализация telegram_id
# ---------------------------------------------------------------------------


class TestTelegramIdNormalization:
    def test_personal_chat_unchanged(self) -> None:
        assert parse_export(_make_export(type="personal_chat", id=123))[0].telegram_id == 123

    def test_private_group_unchanged(self) -> None:
        assert (
            parse_export(_make_export(type="private_group", id=-1001234567))[0].telegram_id
            == -1001234567
        )

    def test_public_supergroup_gets_prefix(self) -> None:
        assert (
            parse_export(_make_export(type="public_supergroup", id=1234567890))[0].telegram_id
            == -1001234567890
        )

    def test_private_supergroup_gets_prefix(self) -> None:
        result = parse_export(_make_export(type="private_supergroup", id=9999))[0]
        assert result.telegram_id == -1009999

    def test_public_channel_gets_prefix(self) -> None:
        result = parse_export(_make_export(type="public_channel", id=55555))[0]
        assert result.telegram_id == -10055555

    def test_private_channel_gets_prefix(self) -> None:
        result = parse_export(_make_export(type="private_channel", id=77777))[0]
        assert result.telegram_id == -10077777


# ---------------------------------------------------------------------------
# Парсинг сообщений
# ---------------------------------------------------------------------------


class TestMessageParsing:
    def test_message_fields(self) -> None:
        msg = _make_message(
            id=42,
            date="2024-06-01T12:00:00",
            from_="Bob",
            from_id="user111",
            text="Hi there",
            reply_to_message_id=10,
        )
        result = parse_export(_make_export(messages=[msg]))[0]
        assert len(result.messages) == 1
        m = result.messages[0]
        assert m.telegram_msg_id == 42
        assert m.sender_id == 111
        assert m.sender_name == "Bob"
        assert m.text == "Hi there"
        assert m.reply_to_id == 10

    def test_timestamp_utc(self) -> None:
        from datetime import UTC

        msg = _make_message(date="2024-03-15T09:00:00")
        result = parse_export(_make_export(messages=[msg]))[0]
        assert result.messages[0].timestamp.tzinfo == UTC

    def test_service_messages_skipped(self) -> None:
        msgs = [
            _make_message(id=1, type="message"),
            {"id": 2, "type": "service", "date": "2024-01-01T00:00:00", "text": "joined"},
            _make_message(id=3, type="message"),
        ]
        result = parse_export(_make_export(messages=msgs))[0]
        assert len(result.messages) == 2
        assert result.messages[0].telegram_msg_id == 1
        assert result.messages[1].telegram_msg_id == 3

    def test_empty_text_becomes_none(self) -> None:
        result = parse_export(_make_export(messages=[_make_message(text="")]))[0]
        assert result.messages[0].text is None

    def test_missing_from_id_gives_none_sender(self) -> None:
        msg = _make_message()
        del msg["from_id"]
        result = parse_export(_make_export(messages=[msg]))[0]
        assert result.messages[0].sender_id is None

    def test_no_reply_to(self) -> None:
        result = parse_export(_make_export(messages=[_make_message()]))[0]
        assert result.messages[0].reply_to_id is None


# ---------------------------------------------------------------------------
# Нормализация text
# ---------------------------------------------------------------------------


class TestTextNormalization:
    def test_plain_string(self) -> None:
        result = parse_export(_make_export(messages=[_make_message(text="Hello world")]))[0]
        assert result.messages[0].text == "Hello world"

    def test_formatted_list(self) -> None:
        msg = _make_message(text=["Hello ", {"type": "bold", "text": "world"}, "!"])
        result = parse_export(_make_export(messages=[msg]))[0]
        assert result.messages[0].text == "Hello world!"

    def test_list_with_link(self) -> None:
        msg = _make_message(
            text=["Check ", {"type": "link", "text": "https://example.com"}, " out"]
        )
        result = parse_export(_make_export(messages=[msg]))[0]
        assert result.messages[0].text == "Check https://example.com out"

    def test_empty_list_becomes_none(self) -> None:
        result = parse_export(_make_export(messages=[_make_message(text=[])]))[0]
        assert result.messages[0].text is None


# ---------------------------------------------------------------------------
# Нормализация sender_id
# ---------------------------------------------------------------------------


class TestSenderIdParsing:
    @pytest.mark.parametrize(
        ("from_id", "expected"),
        [
            ("user123456789", 123456789),
            ("channel987654321", 987654321),
            ("bot111222333", 111222333),
            ("", None),
            (None, None),
        ],
    )
    def test_various_prefixes(self, from_id: str | None, expected: int | None) -> None:
        msg = _make_message(from_id=from_id)
        result = parse_export(_make_export(messages=[msg]))[0]
        assert result.messages[0].sender_id == expected
