import hashlib

from fastapi.testclient import TestClient

from backend.main import app


def _encoded(password="organizer-test"):
    salt="test-salt"
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),1000).hex()
    return f"pbkdf2_sha256$1000${salt}${digest}"


def test_admin_api_rejects_anonymous_requests(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD_HASH",_encoded())
    monkeypatch.setenv("ADMIN_SESSION_SECRET","unit-test-secret-that-is-longer-than-32-bytes")
    with TestClient(app) as client:
        assert client.get("/api/admin/metrics").status_code==401


def test_admin_login_sets_valid_signed_session(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD_HASH",_encoded())
    monkeypatch.setenv("ADMIN_SESSION_SECRET","unit-test-secret-that-is-longer-than-32-bytes")
    with TestClient(app) as client:
        rejected=client.post("/api/admin/login",json={"password":"wrong"})
        assert rejected.status_code==401
        accepted=client.post("/api/admin/login",json={"password":"organizer-test"})
        assert accepted.status_code==200
        assert "httponly" in accepted.headers["set-cookie"].lower()
        token=accepted.json()["csrfToken"]
        assert client.get("/api/admin/session").json()=={"authenticated":True,"csrfToken":token}
        assert client.post("/api/admin/logout").status_code==403
        assert client.post("/api/admin/logout",headers={"X-Admin-CSRF":token}).status_code==200
        assert client.get("/api/admin/session").status_code==401


def test_control_room_reports_dependencies_when_redis_is_down(monkeypatch):
    import backend.admin as admin
    monkeypatch.setenv("ADMIN_PASSWORD_HASH",_encoded())
    monkeypatch.setenv("ADMIN_SESSION_SECRET","unit-test-secret-that-is-longer-than-32-bytes")
    def unavailable(): raise ConnectionError("Redis unavailable")
    monkeypatch.setattr(admin,"redis_connection",unavailable)
    with TestClient(app) as client:
        client.post("/api/admin/login",json={"password":"organizer-test"})
        response=client.get("/api/admin/metrics")
        assert response.status_code==200
        result=response.json()
        assert result["health"]["redis"]=="offline"
        assert result["systemStatus"]=="CRITICAL"
