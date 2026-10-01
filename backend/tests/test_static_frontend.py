import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module


@pytest.mark.parametrize(
    ("path", "asset_path"),
    [("/", "index.html"), ("/meetings/new", "meetings/new/index.html")],
)
async def test_static_export_routes(tmp_path, monkeypatch, path, asset_path):
    asset = tmp_path / asset_path
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text(asset_path, encoding="utf-8")
    monkeypatch.setattr(main_module, "STATIC_DIR", tmp_path)

    transport = ASGITransport(app=main_module.create_app())
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=True
    ) as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert response.text == asset_path
