"""Skill loader for markdown-based domain analysis guidance.

Loads .md skill files from web_dashboard/skills/, matches them to prompts via
keyword/article_type triggers, and injects domain-specific analysis instructions
into AI prompts within a configurable token budget.

Design notes:
- max_tokens in each skill's YAML frontmatter is self-declared by the author,
  NOT validated against the actual body length.  Keep frontmatter values honest
  when editing skills, or the budget math will be wrong.
- Keyword matching uses substring search (``keyword in text``), so short keywords
  like "Q1" could match inside longer words.  Choose keywords carefully.
- Cache is invalidated by comparing mtime_ns of every .md file in SKILLS_DIR.
  Editing a skill file triggers a full reload on the next call.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent / "skills"

# Raised from 1500 when falsifiable_proposal was added as an always-on priority-1
# skill. The budget is spent in (priority, name) order and anything that overflows
# is dropped with only a WARNING, so a new always-on skill silently evicts the
# lowest-priority domain skills from every prompt rather than failing loudly.
#
# For ticker_analysis the always=True floor is what actually squeezes: it was
# multi_source_synthesis(250) + technical_analysis(220) = 470, leaving 1030 of the
# 1500 for keyword-matched domain skills. falsifiable_proposal(420) lifts that
# floor to 890 and leaves only 610 -- so a biotech micro-cap, whose priority-1 set
# alone is biotech_catalyst(380) + earnings_analysis(330) + falsifiable(420) +
# microcap_red_flags(360) = 1490, loses canadian_market and everything below it.
# 2200 restores roughly the pre-existing domain headroom on top of the new floor.
DEFAULT_MAX_TOTAL_TOKENS = 2200


@dataclass(frozen=True)
class SkillDefinition:
    """Parsed skill definition from markdown frontmatter + body."""

    name: str
    description: str
    target_prompts: tuple[str, ...]
    keywords: tuple[str, ...]
    article_types: tuple[str, ...]
    always: bool
    always_for_targets: tuple[str, ...]
    priority: int
    max_tokens: int  # Self-declared by frontmatter author; not validated vs body length
    body: str
    file_path: Path


_skills_cache: list[SkillDefinition] = []
_skill_mtimes_cache: dict[Path, int] = {}
_skills_cache_loaded = False


def clear_skill_cache() -> None:
    """Reset in-memory skill cache (used by tests and reload scenarios)."""
    global _skills_cache, _skill_mtimes_cache, _skills_cache_loaded
    _skills_cache = []
    _skill_mtimes_cache = {}
    _skills_cache_loaded = False


def _list_skill_files() -> list[Path]:
    if not SKILLS_DIR.exists():
        return []
    return sorted(SKILLS_DIR.glob("*.md"))


def _split_frontmatter(markdown_text: str, source: Path) -> tuple[dict[str, Any], str] | None:
    text = markdown_text.strip()
    if not text.startswith("---"):
        logger.warning("Skill file missing YAML frontmatter: %s", source)
        return None

    lines = markdown_text.splitlines()
    if not lines or lines[0].strip() != "---":
        logger.warning("Skill file has malformed frontmatter start: %s", source)
        return None

    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break

    if end_idx is None:
        logger.warning("Skill file has unclosed YAML frontmatter: %s", source)
        return None

    frontmatter_raw = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :]).strip()

    try:
        parsed = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse skill frontmatter for %s: %s", source, exc)
        return None

    if not isinstance(parsed, dict):
        logger.warning("Skill frontmatter must be a YAML object: %s", source)
        return None

    return parsed, body


def _parse_skill_file(path: Path) -> SkillDefinition | None:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed reading skill file %s: %s", path, exc)
        return None

    split = _split_frontmatter(raw_text, path)
    if split is None:
        return None
    frontmatter, body = split

    triggers = frontmatter.get("triggers") or {}
    if not isinstance(triggers, dict):
        triggers = {}

    name = str(frontmatter.get("name") or path.stem)
    description = str(frontmatter.get("description") or "")

    target_prompts_raw = frontmatter.get("target_prompts") or []
    if isinstance(target_prompts_raw, str):
        target_prompts_raw = [target_prompts_raw]

    keywords_raw = triggers.get("keywords") or []
    if isinstance(keywords_raw, str):
        keywords_raw = [keywords_raw]

    article_types_raw = triggers.get("article_types") or []
    if isinstance(article_types_raw, str):
        article_types_raw = [article_types_raw]

    try:
        priority = int(frontmatter.get("priority", 99))
    except (TypeError, ValueError):
        priority = 99

    try:
        max_tokens = int(frontmatter.get("max_tokens", 500))
    except (TypeError, ValueError):
        max_tokens = 500

    always = bool(triggers.get("always", False))
    always_for_raw = triggers.get("always_for") or []
    if isinstance(always_for_raw, str):
        always_for_raw = [always_for_raw]

    return SkillDefinition(
        name=name,
        description=description,
        target_prompts=tuple(str(item).strip().lower() for item in target_prompts_raw if str(item).strip()),
        keywords=tuple(str(item).strip().lower() for item in keywords_raw if str(item).strip()),
        article_types=tuple(str(item).strip().lower() for item in article_types_raw if str(item).strip()),
        always=always,
        always_for_targets=tuple(
            str(item).strip().lower() for item in always_for_raw if str(item).strip()
        ),
        priority=priority,
        max_tokens=max_tokens,
        body=body,
        file_path=path,
    )


def _current_skill_mtimes() -> dict[Path, int]:
    mtimes: dict[Path, int] = {}
    for path in _list_skill_files():
        try:
            mtimes[path] = path.stat().st_mtime_ns
        except OSError:
            continue
    return mtimes


def _skill_cache_is_stale() -> bool:
    if not _skills_cache_loaded:
        return True
    return _current_skill_mtimes() != _skill_mtimes_cache


def _load_skills() -> list[SkillDefinition]:
    global _skills_cache, _skill_mtimes_cache, _skills_cache_loaded

    parsed_skills: list[SkillDefinition] = []
    for path in _list_skill_files():
        parsed = _parse_skill_file(path)
        if parsed is not None:
            parsed_skills.append(parsed)

    _skills_cache = parsed_skills
    _skill_mtimes_cache = _current_skill_mtimes()
    _skills_cache_loaded = True

    # Log each skill with declared vs actual body size for budget auditing.
    for skill in parsed_skills:
        actual_tokens_est = len(skill.body) // 4
        drift = actual_tokens_est - skill.max_tokens
        level = logging.WARNING if drift > 100 else logging.DEBUG
        logger.log(
            level,
            "  skill %-35s  declared=%4d  actual≈%4d tokens  drift=%+d%s",
            skill.name,
            skill.max_tokens,
            actual_tokens_est,
            drift,
            "  ⚠ OVER-BUDGET" if drift > 100 else "",
        )
    logger.info("Loaded %d markdown analysis skills from %s", len(parsed_skills), SKILLS_DIR)
    return parsed_skills


def _get_loaded_skills() -> list[SkillDefinition]:
    if _skill_cache_is_stale():
        return _load_skills()
    return _skills_cache


def _skill_matches(
    skill: SkillDefinition,
    *,
    text: str,
    target_prompt: str,
    article_type: str,
) -> bool:
    normalized_target = target_prompt.strip().lower()
    if normalized_target not in skill.target_prompts:
        return False

    if skill.always:
        return True
    if normalized_target in skill.always_for_targets:
        return True

    # NOTE: Substring match — "Q1" will match inside "Q100" or "IQ1".
    # Keep keywords specific enough to avoid false positives.
    text_lower = text.lower()
    if text_lower and any(keyword in text_lower for keyword in skill.keywords):
        return True

    article_type_lower = article_type.strip().lower()
    if article_type_lower and article_type_lower in skill.article_types:
        return True

    return False


def _get_matching_skill_objects(
    text: str,
    target_prompt: str,
    article_type: str = "",
    max_total_tokens: int = DEFAULT_MAX_TOTAL_TOKENS,
) -> list[SkillDefinition]:
    matched = [
        skill
        for skill in _get_loaded_skills()
        if _skill_matches(
            skill,
            text=text,
            target_prompt=target_prompt,
            article_type=article_type,
        )
    ]
    matched.sort(key=lambda item: (item.priority, item.name.lower()))

    selected: list[SkillDefinition] = []
    dropped: list[SkillDefinition] = []
    used_tokens = 0
    for skill in matched:
        if used_tokens + skill.max_tokens > max_total_tokens:
            dropped.append(skill)
            continue
        selected.append(skill)
        used_tokens += skill.max_tokens

    if selected:
        names = ", ".join(s.name for s in selected)
        logger.info(
            "Skills injected for [%s]: %s (%d/%d budget tokens used)",
            target_prompt, names, used_tokens, max_total_tokens,
        )
    if dropped:
        names = ", ".join(d.name for d in dropped)
        logger.warning(
            "Skills DROPPED (token budget exceeded) for [%s]: %s "
            "(budget %d, used %d, needed %s more)",
            target_prompt, names, max_total_tokens, used_tokens,
            "+".join(str(d.max_tokens) for d in dropped),
        )
    return selected


def get_matching_skills(
    text: str,
    target_prompt: str,
    article_type: str = "",
    max_total_tokens: int = DEFAULT_MAX_TOTAL_TOKENS,
) -> list[str]:
    """Return matched skill bodies for target prompt within token budget."""
    return [
        skill.body
        for skill in _get_matching_skill_objects(
            text=text,
            target_prompt=target_prompt,
            article_type=article_type,
            max_total_tokens=max_total_tokens,
        )
    ]


def build_enhanced_prompt(
    base_prompt: str,
    text: str,
    target_prompt: str,
    article_type: str = "",
    max_total_tokens: int = DEFAULT_MAX_TOTAL_TOKENS,
) -> str:
    """Append matching domain skill guidance to a base system prompt.

    Returns *base_prompt* unchanged when no skills match.  When skills are
    injected the caller should verify the total prompt + article text still
    fits within the model's context window.  This function logs a warning at
    the INFO level with the final character count so context-overflow issues
    are diagnosable from logs without requiring a debugger.
    """
    matched_skills = _get_matching_skill_objects(
        text=text,
        target_prompt=target_prompt,
        article_type=article_type,
        max_total_tokens=max_total_tokens,
    )
    if not matched_skills:
        return base_prompt

    parts = [
        base_prompt,
        "",
        "DOMAIN-SPECIFIC ANALYSIS GUIDANCE:",
        "The following additional analysis instructions apply to this specific article. "
        "Use them to enhance your analysis where relevant.",
        "",
    ]
    for skill in matched_skills:
        parts.append(f"--- {skill.name} ---")
        parts.append(skill.body.strip())
        parts.append("")
    enhanced = "\n".join(parts).rstrip()

    # Log final prompt size so context-window overflows are diagnosable.
    # Rough estimate: 1 token ≈ 4 chars for English text.
    enhanced_chars = len(enhanced)
    base_chars = len(base_prompt)
    added_chars = enhanced_chars - base_chars
    logger.info(
        "Enhanced prompt for [%s]: %d chars (~%d tokens), "
        "+%d chars from %d skill(s)",
        target_prompt, enhanced_chars, enhanced_chars // 4,
        added_chars, len(matched_skills),
    )
    return enhanced
