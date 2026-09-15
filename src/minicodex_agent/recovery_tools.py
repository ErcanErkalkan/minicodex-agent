"""Recovery helpers for failed patch/edit operations."""

from __future__ import annotations

from pathlib import Path

from .patch_tools import parse_unified_patch
from .safety import safe_resolve
from .utils import truncate


def diagnose_patch_failure(
    root: Path, patch_text: str, error: str = "", max_chars: int = 12000
) -> str:
    """Explain likely causes of a failed unified patch and suggest safer next actions."""

    output: list[str] = ["Patch recovery diagnosis"]
    if error:
        output.append(f"Observed error: {error}")

    try:
        patches = parse_unified_patch(patch_text)
    except Exception as exc:  # noqa: BLE001 - diagnostic should catch parser failures
        return (
            "Patch parse edilemedi. Muhtemel nedenler:\n"
            "- Patch unified diff formatında değil.\n"
            "- --- ve +++ dosya başlıkları eksik.\n"
            "- Hunk başlığı @@ -a,b +c,d @@ biçiminde değil.\n"
            f"Parse hatası: {exc}"
        )

    if not patches:
        return "Patch içinde dosya değişikliği bulunamadı. apply_patch yerine replace_in_file/write_file gerekebilir."

    for file_patch in patches:
        rel_path = (
            file_patch.new_path if file_patch.new_path != "/dev/null" else file_patch.old_path
        )
        output.append(f"\nFile: {rel_path}")
        output.append(f"- Hunks: {len(file_patch.hunks)}")
        if rel_path == "/dev/null":
            output.append("- Dosya silme güvenlik nedeniyle desteklenmiyor.")
            continue
        try:
            path = safe_resolve(root, rel_path)
        except Exception as exc:  # noqa: BLE001
            output.append(f"- Path güvenli değil: {exc}")
            continue
        if not path.exists() and file_patch.old_path != "/dev/null":
            output.append("- Dosya mevcut değil; önce list_files/search_text ile doğru yolu bulun.")
        elif path.exists():
            try:
                line_count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError as exc:
                output.append(f"- Dosya okunamadı: {exc}")
            else:
                output.append(f"- Current line count: {line_count}")
                for hunk in file_patch.hunks[:5]:
                    output.append(
                        f"- Hunk old_start={hunk.old_start}, old_count={hunk.old_count}, "
                        f"new_start={hunk.new_start}, new_count={hunk.new_count}"
                    )
                    if hunk.old_start > line_count + 1:
                        output.append(
                            "  * Hunk satır numarası dosya uzunluğunu aşıyor; dosya eskimiş olabilir."
                        )

    output.append("\nRecommended recovery sequence:")
    output.append("1. read_file ile hedef dosyanın güncel halini oku.")
    output.append("2. search_text ile değiştirilecek exact context'i doğrula.")
    output.append("3. Küçük değişiklikse preview_replace_in_file + replace_in_file kullan.")
    output.append("4. Büyük değişiklikse güncel dosyaya göre patch'i yeniden üret.")
    return truncate("\n".join(output), max_chars)
