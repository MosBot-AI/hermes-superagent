# Third-party notices

This plugin is distributed under the repository's MIT license. It has no third-party Python runtime dependencies of its own. Hermes supplies the host APIs.

Compatibility tests exercise **NousResearch/hermes-agent**, commit `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`, from a separate checkout. Hermes is MIT-licensed; its source and license are not vendored into this repository. Preserve its license when redistributing Hermes itself:

- Source: https://github.com/NousResearch/hermes-agent/tree/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
- License: https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/LICENSE
- Behavior-contract reference: https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tests/hermes_cli/test_plugin_api_compat.py

Development and CI environments resolve the pinned Hermes `uv.lock`, including its `dev` and `test` groups. Those dependencies retain their own licenses and are not bundled into the plugin. The workflow uses SHA-pinned official `actions/checkout` and `actions/setup-python`.

DSH Superagent, Switchyard, LiteLLM and vLLM Semantic Router are research references in `docs/`. Their implementation code is not included or executed by this foundation slice.
