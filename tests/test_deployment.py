from scripts.verify_manifests import validate


def test_deployment_contracts():
    result = validate()
    assert result["compose_services"] == 6
    assert result["grafana_panels"] == 5
