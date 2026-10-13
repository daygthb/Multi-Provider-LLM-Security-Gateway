"""Portable semantic checks; external schema validators remain separate gates."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def validate() -> dict[str, int]:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))
    assert {"api", "redis", "mock-provider", "prometheus", "grafana"} <= set(compose["services"])
    for service in compose["services"].values():
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:"), "demo ports must bind loopback"
    documents = []
    for path in (ROOT / "deploy/kubernetes").glob("*.yaml"):
        documents.extend(yaml.safe_load_all(path.read_text("utf-8")))
    kinds = {document["kind"] for document in documents}
    assert {
        "ConfigMap",
        "Deployment",
        "StatefulSet",
        "HorizontalPodAutoscaler",
        "NetworkPolicy",
    } <= kinds
    assert "Secret" not in kinds, "Credentials must be supplied externally"
    config = next(d for d in documents if d["kind"] == "ConfigMap")
    assert yaml.safe_load(config["data"]["policy.yaml"]) == yaml.safe_load(
        (ROOT / "config/policy.yaml").read_text("utf-8")
    ), "policy ConfigMap drift"
    for document in documents:
        if document["kind"] not in {"Deployment", "StatefulSet"}:
            continue
        pod = document["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        for container in pod["containers"]:
            assert {"livenessProbe", "readinessProbe", "resources"} <= set(container)
            assert {"limits", "requests"} <= set(container["resources"])
            assert container["securityContext"]["allowPrivilegeEscalation"] is False
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))
    runs = "\n".join(step.get("run", "") for step in workflow["jobs"]["quality"]["steps"])
    for command in [
        "ruff",
        "mypy",
        "pytest",
        "pip-audit",
        "docker build",
        "docker compose",
        "kubeconform",
    ]:
        assert command in runs
    assert "-v ./data:/app/data:ro" in runs
    assert "api python scripts/smoke_demo.py --existing" in runs
    panels = json.loads((ROOT / "deploy/grafana/dashboards/gateway.json").read_text("utf-8"))[
        "panels"
    ]
    assert len(panels) == 5
    return {
        "compose_services": len(compose["services"]),
        "kubernetes_documents": len(documents),
        "grafana_panels": len(panels),
    }


if __name__ == "__main__":
    print(json.dumps(validate()))
