"""Hermes directory-plugin entry point. No agent loop or import-time effects."""

__all__ = ["register"]


def register(ctx):
    from .personal_agent.plugin import register as register_plugin

    register_plugin(ctx)
