"""Documentation cleanup preserves link checks and executable acceptance evidence."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "karkinos_docs_health", _REPO_ROOT / "scripts/ci/check_docs_health.py"
)
assert _SPEC is not None and _SPEC.loader is not None
health = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(health)


def _write(root: Path, name: str, text: str = "# Reference\n") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def docs_root(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "REPO_ROOT", tmp_path)
    return tmp_path


def test_missing_required_document_is_rejected(docs_root):
    assert health._check_document("docs/missing.md", 10) == [
        "missing documentation file: docs/missing.md"
    ]


def test_document_guardrail_is_enforced_without_becoming_a_target(docs_root):
    _write(docs_root, "docs/example.md", "one\ntwo\n")
    errors = health._check_document("docs/example.md", 1)
    assert "documentation guardrail is 1" in errors[0]
    assert health._check_document("docs/example.md", None) == []


def test_agent_entrypoints_enforce_routing_not_micro_line_counts(docs_root):
    _write(
        docs_root,
        "AGENTS.md",
        "# Agent Guide\nRead AI_COLLABORATION.md and docs/README.md.\n",
    )
    _write(
        docs_root,
        "CLAUDE.md",
        "# Claude\nFollow AGENTS.md, then AI_COLLABORATION.md.\n",
    )
    assert health._check_agent_entrypoints() == []

    _write(docs_root, "CLAUDE.md", "# Claude\nStandalone rules.\n")
    errors = health._check_agent_entrypoints()
    assert "delegate repository instructions to AGENTS.md" in errors[0]


@pytest.mark.parametrize("path_text", health.OPERATIONAL_REFERENCE_DOCS)
def test_operational_reference_rejects_broken_link(docs_root, path_text):
    _write(docs_root, path_text, "[Removed translation](removed.en.md)\n")
    assert health._check_document(path_text, None) == [
        f"{path_text} has a broken local link: removed.en.md"
    ]


def test_local_links_resolve_without_translation_stubs(docs_root):
    _write(docs_root, "docs/README.md")
    _write(docs_root, "docs/reference.md", "[文档入口](README.md#reference)\n")
    assert health._check_document("docs/reference.md", None) == []


def test_outside_repository_link_is_rejected(docs_root):
    _write(docs_root, "docs/reference.md", "[Outside](../../outside.md)\n")
    errors = health._check_document("docs/reference.md", None)
    assert "links outside the repository" in errors[0]


def test_external_and_fragment_links_remain_allowed(docs_root):
    _write(
        docs_root,
        "docs/reference.md",
        "[Section](#section) [Web](https://example.com) [Mail](mailto:test@example.com)\n",
    )
    assert health._check_document("docs/reference.md", None) == []


@pytest.mark.parametrize("path_text", health.REMOVED_STUB_DOCS)
def test_retired_stub_cannot_return(docs_root, path_text):
    assert health._check_removed_docs_stay_removed() == []
    _write(docs_root, path_text)
    assert health._check_removed_docs_stay_removed() == [
        f"retired documentation stub returned: {path_text}"
    ]


def test_retired_stubs_are_not_required_documents():
    required = {
        *health.CORE_DOC_BUDGETS,
        *health.AGENT_ENTRYPOINT_BUDGETS,
        *health.COMPATIBILITY_STUB_BUDGETS,
        *health.MAINTENANCE_DOC_BUDGETS,
        *health.FROZEN_REFERENCE_STUB_BUDGETS,
        *health.OPERATIONAL_REFERENCE_DOCS,
    }
    assert not set(health.REMOVED_STUB_DOCS).intersection(required)
    assert all(not (_REPO_ROOT / name).exists() for name in health.REMOVED_STUB_DOCS)


def test_retired_stubs_are_not_acceptance_evidence():
    import analytics.acceptance as acceptance

    retired = set(health.REMOVED_STUB_DOCS)
    for name in acceptance.__all__:
        if not name.startswith("build_"):
            continue
        audit = getattr(acceptance, name)()
        for criterion in audit.criteria:
            assert not retired.intersection(criterion.evidence_paths), criterion.key
            for command in criterion.validation_commands:
                assert not any(path in command for path in retired), criterion.key


def test_main_keeps_routing_operational_links_and_retirement_gate(docs_root, capsys):
    required = {
        *health.CORE_DOC_BUDGETS,
        *health.AGENT_ENTRYPOINT_BUDGETS,
        *health.COMPATIBILITY_STUB_BUDGETS,
        *health.MAINTENANCE_DOC_BUDGETS,
        *health.FROZEN_REFERENCE_STUB_BUDGETS,
        *health.OPERATIONAL_REFERENCE_DOCS,
    }
    for path_text in required:
        _write(docs_root, path_text)
    _write(
        docs_root,
        "AGENTS.md",
        "# Agent Guide\nRead AI_COLLABORATION.md and docs/README.md.\n",
    )
    _write(
        docs_root,
        "CLAUDE.md",
        "# Claude\nFollow AGENTS.md, then AI_COLLABORATION.md.\n",
    )

    assert health.main() == 0
    assert "passed" in capsys.readouterr().out

    reference = health.OPERATIONAL_REFERENCE_DOCS[0]
    _write(docs_root, reference, "[Missing](missing.md)\n")
    assert health.main() == 1
    assert "broken local link" in capsys.readouterr().out

    _write(docs_root, reference)
    _write(docs_root, health.REMOVED_STUB_DOCS[0])
    assert health.main() == 1
    assert "retired documentation stub returned" in capsys.readouterr().out
