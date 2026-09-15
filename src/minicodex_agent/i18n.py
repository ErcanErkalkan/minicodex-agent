"""Tiny CLI localization helpers for MiniCodex.

The package internals and model prompts remain English-first.  User-visible CLI
chrome can be switched with --lang en|tr so supervised Turkish workflows remain
comfortable without mixing languages for English users.
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "folder_not_found": "Error: folder not found: {root}",
        "config_read_failed": "Error: could not read project configuration: {error}",
        "goal_required": "Error: goal is required. Provide a task or use --interactive.",
        "approval_prompt": "Approve? [y/N]: ",
        "agent_started": "MiniCodex Agent v{version} started",
        "agent_finished": "MiniCodex Agent finished",
        "goal": "Goal",
        "folder": "Folder",
        "model": "Model",
        "provider": "Provider",
        "approval_mode": "Approval mode",
        "safety_profile": "Safety profile",
        "dry_run": "Dry-run",
        "project_profile": "Detected project profile",
        "step": "Step {step}: {action}",
        "explanation": "Explanation",
        "git_diff": "Git diff",
        "run_result": "Run result",
        "max_steps": "Maximum step count reached",
        "logging_disabled": "Logging: disabled (--no-log)",
        "network_permission": "Network/install command permission",
        "log_dir": "Log directory",
        "interactive_title": "MiniCodex interactive mode",
        "interactive_help": "Enter one task per line. Use :q, :quit, or :exit to leave.",
        "interactive_closed": "Interactive mode closed.",
        "ask_user_title": "Agent asked a question",
        "default_answer_used": "Non-interactive mode: using default answer.",
        "user_answer": "User answer",
    },
    "tr": {
        "folder_not_found": "Hata: klasör bulunamadı: {root}",
        "config_read_failed": "Hata: proje konfigürasyonu okunamadı: {error}",
        "goal_required": "Hata: goal gerekli. Ya bir görev yazın ya da --interactive kullanın.",
        "approval_prompt": "Onaylıyor musun? [y/N]: ",
        "agent_started": "MiniCodex Agent v{version} başladı",
        "agent_finished": "MiniCodex Agent tamamladı",
        "goal": "Hedef",
        "folder": "Klasör",
        "model": "Model",
        "provider": "Provider",
        "approval_mode": "Onay modu",
        "safety_profile": "Güvenlik profili",
        "dry_run": "Dry-run",
        "project_profile": "Algılanan proje profili",
        "step": "Adım {step}: {action}",
        "explanation": "Açıklama",
        "git_diff": "Git diff",
        "run_result": "Run result",
        "max_steps": "Maksimum adım sayısına ulaşıldı",
        "logging_disabled": "Loglama: kapalı (--no-log)",
        "network_permission": "Network/install komut izni",
        "log_dir": "Log klasörü",
        "interactive_title": "MiniCodex interactive mode",
        "interactive_help": "Her satıra bir görev yaz. Çıkmak için :q, :quit veya :exit kullan.",
        "interactive_closed": "Interactive mode kapatıldı.",
        "ask_user_title": "Agent soru sordu",
        "default_answer_used": "Non-interactive mod: varsayılan cevap kullanıldı.",
        "user_answer": "Kullanıcı cevabı",
    },
}


def normalize_lang(lang: str | None) -> str:
    """Return a supported language code."""

    return "tr" if str(lang or "en").lower().startswith("tr") else "en"


def tr(key: str, lang: str = "en", **kwargs: object) -> str:
    """Translate one CLI message key."""

    language = normalize_lang(lang)
    template = MESSAGES.get(language, MESSAGES["en"]).get(key, MESSAGES["en"].get(key, key))
    return template.format(**kwargs)
