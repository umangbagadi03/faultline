from fastapi.testclient import TestClient

from faultline.api import app

client = TestClient(app)


def test_end_to_end_api():
    with TestClient(app) as c:
        assert c.post("/api/seed").json()["seeded"] == 48
        assert c.post("/api/analyze-all").json()["analyzed"] == 48

        stats = c.get("/api/stats").json()
        assert stats["total_traces"] == 48
        assert stats["root_causes_found"] == 30
        assert stats["clusters"]

        detail = c.get("/api/traces/run-005").json()
        assert detail["autopsy"]["root_cause"]["failure_class"] == "TOOL_ARG_ERROR"

        test_file = c.get("/api/traces/run-005/regression-test")
        assert test_file.status_code == 200
        assert "def test_recorded_failure_is_detected" in test_file.text

        assert c.post("/api/eval?mode=rules").json()["class_accuracy"] > 80
        assert c.get("/").status_code == 200


def test_upload_custom_trace():
    with TestClient(app) as c:
        trace = {
            "id": "custom-1", "task": "Refund order 4417", "status": "failed",
            "tools": [{"name": "get_order", "params": {"order_id": "str"}, "required": ["order_id"]}],
            "steps": [{"index": 0, "type": "tool", "name": "get_order", "input": {"id": "4417"},
                       "error": "missing argument order_id"}],
            "final_output": "Sorry, I could not find your order.",
        }
        assert c.post("/api/traces", json=trace).status_code == 200
        autopsy = c.post("/api/traces/custom-1/analyze").json()
        assert autopsy["root_cause"]["failure_class"] == "TOOL_ARG_ERROR"
        # Unknown tool -> no mock available -> replay falls back to the recorded cassette.
        assert autopsy["replay"]["verified"] is False
        assert "cassette" in " ".join(autopsy["replay"]["log"])
