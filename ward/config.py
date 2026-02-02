"""
Ward Configuration - Feature Flags

This module controls Ward's optional features, especially LLM integration.
All advanced features are OFF by default for safety.
"""

import os
from typing import Optional


class WardConfig:
    """
    Ward configuration with safe defaults.

    Philosophy:
    - Core authorization ALWAYS works
    - Intelligence features are OPTIONAL
    - Default to maximum safety (all off)
    """

    def __init__(self):
        # LLM Kill-Switch (Requirement #9)
        # Default: OFF
        # Set WARD_ENABLE_INTELLIGENCE=1 to enable
        self._intelligence_enabled = self._parse_bool_env(
            "WARD_ENABLE_INTELLIGENCE",
            default=False
        )

        # Verbose logging for debugging
        self._verbose = self._parse_bool_env(
            "WARD_VERBOSE",
            default=False
        )

    @property
    def intelligence_enabled(self) -> bool:
        """
        Whether Decision Intelligence Reports (DIRs) are enabled.

        When OFF:
        - No DIR generation
        - No risk assessment
        - No LLM advisory features
        - Pure policy + human approval

        When ON:
        - DIRs generated for decisions
        - Risk assessment provided
        - Advisory features available

        Default: OFF (safe mode)
        """
        return self._intelligence_enabled

    @property
    def verbose(self) -> bool:
        """Whether to print verbose debug logs"""
        return self._verbose

    def disable_intelligence(self):
        """
        Kill-switch: Turn off all intelligence features immediately.

        This forces Ward into deterministic mode:
        - Policies still work
        - Human approvals still work
        - Leases still work
        - Audit still works

        Only DIRs/LLM features are disabled.
        """
        self._intelligence_enabled = False
        if self._verbose:
            print("⚠️  Ward Intelligence DISABLED via kill-switch")

    def enable_intelligence(self):
        """
        Enable intelligence features.

        WARNING: Only enable after LLM readiness requirements are met!
        See: LLM_READINESS.md
        """
        self._intelligence_enabled = True
        if self._verbose:
            print("✓ Ward Intelligence ENABLED")

    @staticmethod
    def _parse_bool_env(key: str, default: bool = False) -> bool:
        """Parse boolean from environment variable"""
        value = os.environ.get(key)
        if value is None:
            return default
        return value.lower() in ("1", "true", "yes", "on")


# Global config instance
_global_config: Optional[WardConfig] = None


def get_config() -> WardConfig:
    """Get global Ward configuration"""
    global _global_config
    if _global_config is None:
        _global_config = WardConfig()
    return _global_config


def reset_config():
    """Reset config (for testing)"""
    global _global_config
    _global_config = None
