import httpx
import pytest

from app.llm.client import AllProvidersFailed, Provider, complete_json, parse_json


def _fails_http(key, system, user):
    req = httpx.Request("POST", "https://x")
    raise httpx.HTTPStatusError("rate limited", request=req, response=httpx.Response(429, request=req))


def _bad_json(key, system, user):
    return "Sure! Here is the answer: not json"


def _good(key, system, user):
    return '```json\n{"eligible": true, "score": 80}\n```'


def test_parse_json_handles_fences_and_chatter():
    assert parse_json('Here you go {"a": 1} thanks') == {"a": 1}
    assert parse_json('```json\n{"a": 2}\n```') == {"a": 2}


def test_falls_back_until_one_works():
    providers = [Provider("p1", "k", _fails_http), Provider("p2", "k", _bad_json), Provider("p3", "k", _good)]
    result, name = complete_json("sys", "user", providers=providers)
    assert name == "p3"
    assert result == {"eligible": True, "score": 80}


def test_validation_failure_moves_to_next_provider():
    def needs_score(d):
        if "score" not in d:
            raise ValueError("missing score")
        return d

    providers = [Provider("p1", "k", lambda *a: '{"eligible": true}'), Provider("p2", "k", _good)]
    _, name = complete_json("sys", "user", validate=needs_score, providers=providers)
    assert name == "p2"


def test_all_failing_raises_with_reasons():
    with pytest.raises(AllProvidersFailed, match="p1: HTTP 429"):
        complete_json("sys", "user", providers=[Provider("p1", "k", _fails_http)])
