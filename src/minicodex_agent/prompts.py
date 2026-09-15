"""Prompt compatibility wrapper for MiniCodex.

The active prompt implementation lives in prompt_engine.py. This module keeps the
old import path stable for callers that import SYSTEM_PROMPT/build_system_prompt.
"""

from __future__ import annotations

from .prompt_engine import (
    PROMPT_PROFILES,
    PromptBundle,
    build_prompt_bundle,
    build_system_prompt,
    infer_prompt_profile,
    list_prompt_profiles,
    normalize_prompt_profile,
    render_prompt_preview,
    validate_prompt_bundle,
)

SYSTEM_PROMPT = build_system_prompt(profile="general")

__all__ = [
    "PROMPT_PROFILES",
    "PromptBundle",
    "SYSTEM_PROMPT",
    "build_prompt_bundle",
    "build_system_prompt",
    "infer_prompt_profile",
    "list_prompt_profiles",
    "normalize_prompt_profile",
    "render_prompt_preview",
    "validate_prompt_bundle",
]
