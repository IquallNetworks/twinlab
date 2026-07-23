from twinlab_backend.app import create_app


def test_terminal_websocket_route_is_mounted_under_api_prefix() -> None:
    # Guards the wiring: the terminal endpoint is reachable by name at the
    # API-prefixed path the frontend connects to. `url_path_for` resolves through
    # the included router's prefix and 404s if the route (a WebSocket, not HTTP)
    # isn't registered. The auth-before-accept gate and the relay are exercised by
    # the live integration test (real DB + clab-api).
    app = create_app()
    path = app.url_path_for("node_terminal", name="lab1", node="r1")
    assert path == "/api/v1/labs/lab1/nodes/r1/terminal"
