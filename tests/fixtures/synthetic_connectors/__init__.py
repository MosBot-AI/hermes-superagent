"""Test-only connector services. These objects confer no production authority."""

from .core import Capabilities, FixtureError, LostResponse, Remote

__all__ = ["Capabilities", "FixtureError", "LostResponse", "Remote"]
