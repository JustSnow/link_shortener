"""Integration tests for API endpoints."""


class TestShortenEndpoint:
    def test_post_shorten_returns_200(self, app_client):
        response = app_client.post(
            "/shorten",
            json={"url": "https://example.com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "short_url" in data
        assert "/s/" in data["short_url"]

    def test_post_shorten_invalid_url_returns_422(self, app_client):
        response = app_client.post(
            "/shorten",
            json={"url": "not-a-url"},
        )
        assert response.status_code == 422

    def test_post_shorten_missing_body_returns_422(self, app_client):
        response = app_client.post("/shorten", json={})
        assert response.status_code == 422


class TestRedirectEndpoint:
    def test_redirect_existing_link(self, app_client):
        # Create a link first.
        shorten_resp = app_client.post(
            "/shorten",
            json={"url": "https://example.com"},
        )
        short_url = shorten_resp.json()["short_url"]
        short_id = short_url.split("/s/")[-1]

        response = app_client.get(f"/s/{short_id}", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] in (
            "https://example.com",
            "https://example.com/",
        )

    def test_redirect_nonexistent_link_returns_404(self, app_client):
        response = app_client.get("/s/ZZZZZZ", follow_redirects=False)
        assert response.status_code == 404


class TestIndexEndpoint:
    def test_index_returns_html(self, app_client):
        response = app_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
