"""ThinHarness Terminal-Bench reproduction controls."""

from pathlib import Path

_recovery_receipt = Path(__file__).resolve().parent.parent / "artifacts" / "direct-openai-additional-10-pairwise" / "RECOVERY.json"
if _recovery_receipt.is_file():
    from .direct_additional_recovery import install_validator

    install_validator()
