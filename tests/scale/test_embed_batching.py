"""Tests for HTTP embedding batching and client reuse."""

from pg_raggraph.embedding import HttpxEmbeddingProvider


class _FakeResponse:
    def __init__(self, size: int):
        self._size = size

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": [{"embedding": [float(i)]} for i in range(self._size)]}


class _FakeAsyncClient:
    created = 0
    closed = 0
    posts = []

    def __init__(self, *args, **kwargs):
        type(self).created += 1

    async def post(self, url, *, headers, json):
        type(self).posts.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(len(json["input"]))

    async def aclose(self):
        type(self).closed += 1


def _reset_fake_client():
    _FakeAsyncClient.created = 0
    _FakeAsyncClient.closed = 0
    _FakeAsyncClient.posts = []


async def test_http_embedding_batches_and_reuses_client(monkeypatch):
    _reset_fake_client()
    monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)

    provider = HttpxEmbeddingProvider(
        base_url="http://embeddings.internal/v1",
        model="embed-model",
        api_key="secret",
        dimension=1,
        batch_size=16,
    )
    embeddings = await provider.embed([f"text {i}" for i in range(50)])
    more = await provider.embed(["one", "two"])
    await provider.aclose()

    assert len(embeddings) == 50
    assert len(more) == 2
    assert _FakeAsyncClient.created == 1
    assert _FakeAsyncClient.closed == 1
    assert [len(post["json"]["input"]) for post in _FakeAsyncClient.posts] == [
        16,
        16,
        16,
        2,
        2,
    ]
    assert all(
        post["url"] == "http://embeddings.internal/v1/embeddings"
        for post in _FakeAsyncClient.posts
    )
    assert all(
        post["headers"]["Authorization"] == "Bearer secret"
        for post in _FakeAsyncClient.posts
    )
