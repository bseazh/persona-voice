import os
import time

from fastapi.testclient import TestClient

from app.main import app


def setup_module():
    try:
        os.unlink("/tmp/persona_voice_test.db")
    except FileNotFoundError:
        pass


def payload(phone="+8613812345678", mode="mock"):
    return {"phone_number": phone, "task": {"goal": "询问明天下午是否可预约"}, "mode": mode}


def test_health_and_mock_lifecycle():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["real_calls_enabled"] is False
        created = client.post("/api/calls", json=payload(), headers={"Idempotency-Key": "test-one"})
        assert created.status_code == 202
        call_id = created.json()["call_id"]
        for _ in range(30):
            result = client.get(f"/api/calls/{call_id}").json()
            if result["status"] == "completed":
                break
            time.sleep(0.01)
        assert result["status"] == "completed"
        assert result["result"]["simulated"] is True
        assert result["phone_masked"] != "+8613812345678"


def test_validation_idempotency_and_real_guard():
    with TestClient(app) as client:
        assert client.post("/api/calls", json=payload("13812345678")).status_code == 422
        first = client.post("/api/calls", json=payload("+8613912345678"), headers={"Idempotency-Key": "same"})
        second = client.post("/api/calls", json=payload("+8613912345678"), headers={"Idempotency-Key": "same"})
        assert first.json()["call_id"] == second.json()["call_id"]
        for _ in range(30):
            if client.get(f"/api/calls/{first.json()['call_id']}").json()["status"] == "completed":
                break
            time.sleep(0.01)
        real = payload(mode="real")
        real["confirmed"] = True
        response = client.post("/api/calls", json=real)
        assert response.status_code == 403
        assert response.json()["detail"] == "服务器未启用真实外呼"
