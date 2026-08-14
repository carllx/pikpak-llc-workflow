from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = ROOT / ".agents" / "skills" / "pikpak-llc" / "SKILL.md"


def test_skill_is_model_invoked_for_narrow_pikpak_losslesscut_triggers():
    text = SKILL.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]

    assert "disable-model-invocation" not in frontmatter
    for trigger in ("PikPak Share", "proxy preparation", "LosslessCut", ".llc", "Origin segments"):
        assert trigger in frontmatter
    assert "不用于其他媒体" in frontmatter
    integration = (SKILL.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "allow_implicit_invocation: true" in integration
    assert "$pikpak-llc" not in integration


def test_agents_hard_routes_matching_operations_to_production_skill():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "## Operational Workflow" in text
    assert "明确属于 PikPak→LosslessCut workflow" in text
    assert ".agents/skills/pikpak-llc/SKILL.md" in text
    assert "执行项目命令前必须完整读取" in text
    assert "LEGACY_OPERATOR_FILE_DETECTED" in text
    assert "clean `master`" in text


def test_skill_daily_origin_uses_authenticated_latest_batch_and_completion_gate():
    text = SKILL.read_text(encoding="utf-8")

    assert "python -m pikpak_llc.authenticated_workflow" in text
    assert "自动发现 `projects/` 中全部 `.llc`" in text
    assert "只有 batch `STATUS=PASS`" in text
    assert "文件存在或进程 exit code 0 不构成成功" in text
    assert "origin_segment_extractor.py` 禁止用于 daily workflow" in text
