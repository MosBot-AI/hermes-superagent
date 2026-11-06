"""Static native Automation Blueprint data; no jobs, storage or host imports.

Prompt instructions are not a tool policy. Jobs created through Hermes remain
ordinary cron jobs with the host's model, tools, budget and delivery behavior.
Disabling this template does not pause or delete jobs already created from it.
"""

from typing import Any


def planning_check_in() -> dict[str, Any]:
    """Return fresh JSON-compatible registration data for every profile/load."""
    return {
        "key": "planning-check-in",
        "title": "Personal planning check-in",
        "description": (
            "Requests three planning questions without fetching personal data. "
            "Creates an ordinary Hermes cron job only when you schedule it. "
            "Default delivery is local (saved output); choose a connected target for messages. "
            "Prompt guidance is not a tool restriction; normal host costs apply. "
            "Disabling this template does not stop existing jobs."
        ),
        "category": "daily",
        "schedule_template": "{minute} {hour} * * {dow}",
        "prompt_template": (
            "Write a short personal planning check-in in {language}, focused on {focus}. "
            "Ask exactly three brief questions: What matters most now? "
            "Which commitment needs attention? What is one manageable next step? "
            "Ask the user to reflect; do not invent answers or claim knowledge of their tasks. "
            "Do not use tools, read files or inboxes, fetch data, or take actions. "
            "Return only the check-in text for the configured cron delivery."
        ),
        "slots": [
            {
                "name": "time",
                "type": "time",
                "label": "What time?",
                "default": "09:00",
                "help": "HH:MM (24-hour). Verify the host scheduler timezone before scheduling.",
            },
            {
                "name": "recurrence",
                "type": "enum",
                "label": "Repeat on",
                "default": "weekdays",
                "options": ["everyday", "weekdays", "weekends"],
            },
            {
                "name": "focus",
                "type": "enum",
                "label": "Planning focus",
                "default": "priorities",
                "options": ["priorities", "commitments", "weekly-review"],
            },
            {
                "name": "language",
                "type": "enum",
                "label": "Output language",
                "default": "English",
                "options": ["English", "Simplified Chinese"],
            },
            {
                "name": "deliver",
                "type": "enum",
                "label": "Where to deliver?",
                "default": "local",
                "options": ["local", "origin"],
                "strict": False,
                "help": (
                    "local = save output, no message; origin = originating chat or configured "
                    "home channel. Hermes resolves delivery; verify the target before scheduling."
                ),
            },
        ],
        "deliver_default": "local",
        "skills": [],
        "tags": ["planning", "check-in"],
    }
