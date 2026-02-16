from __future__ import annotations

from aetherflow.core.validation import validate_flow_dict, validate_flow_yaml


def _base_flow() -> dict:
    return {
        "version": 1,
        "flow": {"id": "demo"},
        "resources": {},
        "jobs": [
            {
                "id": "probe",
                "depends_on": [],
                "when": None,
                "steps": [
                    {"id": "s1", "type": "check_items", "inputs": {"items": []}, "outputs": {"has_data": "true"}},
                ],
            }
        ],
    }


def test_validate_unknown_step_type():
    raw = _base_flow()
    raw["jobs"][0]["steps"][0]["type"] = "does_not_exist"
    report = validate_flow_dict(raw)
    assert report["ok"] is False
    codes = {e["code"] for e in report["errors"]}
    assert "semantic:unknown_step_type" in codes


def test_validate_depends_on_unknown_and_order():
    raw = _base_flow()
    # Add 2 jobs and make the first depend on the second (invalid ordering)
    raw["jobs"] = [
        {"id": "a", "depends_on": ["b"], "steps": [{"id": "s", "type": "check_items", "inputs": {"items": []}}]},
        {"id": "b", "depends_on": [], "steps": [{"id": "s", "type": "check_items", "inputs": {"items": []}}]},
    ]
    report = validate_flow_dict(raw)
    codes = {e["code"] for e in report["errors"]}
    assert "semantic:depends_on_order" in codes

    raw["jobs"][0]["depends_on"] = ["nope"]
    report2 = validate_flow_dict(raw)
    codes2 = {e["code"] for e in report2["errors"]}
    assert "semantic:depends_on_unknown_job" in codes2


def test_validate_when_expression_rejects_unsafe_nodes():
    raw = _base_flow()
    raw["jobs"].append({
        "id": "process",
        "depends_on": ["probe"],
        "when": "jobs.probe.outputs.has_data == true and (1 + 1) == 2",
        "steps": [{"id": "s", "type": "check_items", "inputs": {"items": []}}],
    })
    report = validate_flow_dict(raw)
    assert report["ok"] is False
    assert any(e["code"] == "semantic:invalid_when" for e in report["errors"])


def test_validate_template_syntax_on_runtime_fields(tmp_path):
    """Malformed template in a runtime-templated field must fail-fast."""
    raw = _base_flow()
    raw["jobs"][0]["steps"][0]["inputs"] = {"sql": "{{ broken "}
    p = tmp_path / "flow.yaml"
    import yaml as _yaml

    p.write_text(_yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    report = validate_flow_yaml(str(p))
    assert report["ok"] is False
    assert any(e["code"] == "template:syntax" for e in report["errors"])


def test_validate_template_syntax_on_flowmeta_fields(tmp_path):
    """Malformed template in a runtime-templated field must fail-fast."""
    raw = _base_flow()
    raw["flow"]["workspace"] = {"root": "{{ env.broken }}"}
    p = tmp_path / "flow.yaml"
    import yaml as _yaml

    p.write_text(_yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    report = validate_flow_yaml(str(p))
    print(report)
    assert report["ok"] is True
    assert len(report["errors"]) == 0
