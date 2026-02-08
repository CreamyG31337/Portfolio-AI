import time
from pathlib import Path

import skill_loader
from summary_common import get_summary_system_prompt


def _write_skill(path: Path, frontmatter: str, body: str) -> None:
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")


def _use_temp_skills_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(skill_loader, "SKILLS_DIR", tmp_path)
    skill_loader.clear_skill_cache()


def test_parsing_valid_and_malformed_files(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    _write_skill(
        tmp_path / "valid.md",
        "\n".join(
            [
                "name: Valid Skill",
                "target_prompts: [summary]",
                "triggers:",
                "  keywords: [alpha]",
                "  article_types: []",
                "  always: false",
                "priority: 1",
                "max_tokens: 200",
            ]
        ),
        "Valid body",
    )
    (tmp_path / "bad.md").write_text("---\nname: bad\ntriggers:\n  keywords: [x]\n", encoding="utf-8")

    matches = skill_loader.get_matching_skills("Alpha catalyst", "summary")
    assert matches == ["Valid body"]


def test_keyword_matching_is_case_insensitive(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    _write_skill(
        tmp_path / "keywords.md",
        "\n".join(
            [
                "name: Keyword Skill",
                "target_prompts: [summary]",
                "triggers:",
                "  keywords: [phase 3, fda]",
                "  article_types: []",
                "  always: false",
                "priority: 1",
                "max_tokens: 100",
            ]
        ),
        "Biotech body",
    )

    assert skill_loader.get_matching_skills("Upcoming PHASE 3 data release", "summary") == ["Biotech body"]
    assert skill_loader.get_matching_skills("No trigger here", "summary") == []


def test_article_type_matching(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    _write_skill(
        tmp_path / "newsletter.md",
        "\n".join(
            [
                "name: Newsletter Skill",
                "target_prompts: [summary]",
                "triggers:",
                "  keywords: []",
                "  article_types: [Newsletter]",
                "  always: false",
                "priority: 2",
                "max_tokens: 120",
            ]
        ),
        "Newsletter body",
    )

    assert (
        skill_loader.get_matching_skills("", "summary", article_type="Newsletter") == ["Newsletter body"]
    )
    assert skill_loader.get_matching_skills("", "summary", article_type="Research") == []


def test_always_true_skills_included_for_target_only(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    _write_skill(
        tmp_path / "always.md",
        "\n".join(
            [
                "name: Always Skill",
                "target_prompts: [crowd_sentiment]",
                "triggers:",
                "  keywords: []",
                "  article_types: []",
                "  always: true",
                "priority: 1",
                "max_tokens: 100",
            ]
        ),
        "Always body",
    )

    assert skill_loader.get_matching_skills("anything", "crowd_sentiment") == ["Always body"]
    assert skill_loader.get_matching_skills("anything", "summary") == []


def test_always_for_target_support(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    _write_skill(
        tmp_path / "always_for.md",
        "\n".join(
            [
                "name: Congress Skill",
                "target_prompts: [summary, congress_trades]",
                "triggers:",
                "  keywords: [insider buying]",
                "  article_types: []",
                "  always: false",
                "  always_for: [congress_trades]",
                "priority: 2",
                "max_tokens: 100",
            ]
        ),
        "Congress body",
    )

    assert skill_loader.get_matching_skills("", "congress_trades") == ["Congress body"]
    assert skill_loader.get_matching_skills("", "summary") == []


def test_token_budget_enforcement_and_priority(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    _write_skill(
        tmp_path / "p1.md",
        "\n".join(
            [
                "name: Priority One",
                "target_prompts: [summary]",
                "triggers:",
                "  keywords: [alpha]",
                "  article_types: []",
                "  always: false",
                "priority: 1",
                "max_tokens: 600",
            ]
        ),
        "P1",
    )
    _write_skill(
        tmp_path / "p3.md",
        "\n".join(
            [
                "name: Priority Three",
                "target_prompts: [summary]",
                "triggers:",
                "  keywords: [alpha]",
                "  article_types: []",
                "  always: false",
                "priority: 3",
                "max_tokens: 600",
            ]
        ),
        "P3",
    )

    assert skill_loader.get_matching_skills("alpha", "summary", max_total_tokens=700) == ["P1"]
    assert skill_loader.get_matching_skills("alpha", "summary", max_total_tokens=1500) == ["P1", "P3"]


def test_build_enhanced_prompt_format(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    _write_skill(
        tmp_path / "format.md",
        "\n".join(
            [
                "name: Format Skill",
                "target_prompts: [summary]",
                "triggers:",
                "  keywords: [alpha]",
                "  article_types: []",
                "  always: false",
                "priority: 1",
                "max_tokens: 100",
            ]
        ),
        "Format body",
    )

    prompt = skill_loader.build_enhanced_prompt("BASE", "alpha context", "summary")
    assert prompt.startswith("BASE")
    assert "DOMAIN-SPECIFIC ANALYSIS GUIDANCE:" in prompt
    assert "--- Format Skill ---" in prompt
    assert "Format body" in prompt


def test_empty_skills_directory_returns_base_prompt(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    prompt = skill_loader.build_enhanced_prompt("BASE PROMPT", "alpha", "summary")
    assert prompt == "BASE PROMPT"


def test_cache_invalidation_on_file_modification(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    skill_path = tmp_path / "cache.md"
    _write_skill(
        skill_path,
        "\n".join(
            [
                "name: Cache Skill",
                "target_prompts: [summary]",
                "triggers:",
                "  keywords: [alpha]",
                "  article_types: []",
                "  always: false",
                "priority: 1",
                "max_tokens: 100",
            ]
        ),
        "Body Alpha",
    )

    assert skill_loader.get_matching_skills("alpha", "summary") == ["Body Alpha"]

    time.sleep(0.02)
    _write_skill(
        skill_path,
        "\n".join(
            [
                "name: Cache Skill",
                "target_prompts: [summary]",
                "triggers:",
                "  keywords: [beta]",
                "  article_types: []",
                "  always: false",
                "priority: 1",
                "max_tokens: 100",
            ]
        ),
        "Body Beta",
    )

    assert skill_loader.get_matching_skills("beta", "summary") == ["Body Beta"]
    assert skill_loader.get_matching_skills("alpha", "summary") == []


def test_get_summary_system_prompt_backwards_compatible(monkeypatch, tmp_path: Path) -> None:
    _use_temp_skills_dir(monkeypatch, tmp_path)
    prompt = get_summary_system_prompt()
    assert isinstance(prompt, str)
    assert "You are a skeptical financial analyst." in prompt
