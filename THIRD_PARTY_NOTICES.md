# Third-party notices

English | [简体中文](THIRD_PARTY_NOTICES-zh.md)

This plugin is distributed under the repository's MIT license. It has no third-party Python runtime dependencies of its own. Hermes supplies the host APIs.

Compatibility tests exercise **NousResearch/hermes-agent**, commit `2281116525106e3c109993ccb5dc74d02bfc1427`, from a separate checkout. Hermes is MIT-licensed. The full host is not vendored into this repository. Preserve its license when redistributing Hermes itself:

- Source: https://github.com/NousResearch/hermes-agent/tree/2281116525106e3c109993ccb5dc74d02bfc1427
- License: https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/LICENSE
- Behavior-contract reference: https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tests/hermes_cli/test_plugin_api_compat.py

The [voice IPC experiment](experiments/voice-ipc/README.md) contains a review-only patch with selected upstream-derived code/context and new prototype code. The original Hermes MIT notice is preserved verbatim in [LICENSE.hermes-agent](experiments/voice-ipc/LICENSE.hermes-agent). The patch is not installed, imported or applied by this plugin, and has not been submitted upstream. It does not change the official compatibility pin.

The [command-context experiment](experiments/command-context/README.md) likewise includes a review-only upstream-derived patch, with the original MIT notice in [LICENSE.hermes-agent](experiments/command-context/LICENSE.hermes-agent). It is not installed or applied, grants no owner authority and has not been submitted upstream.

Development and CI environments resolve the pinned Hermes `uv.lock`, including its `dev` and `test` groups. Those dependencies retain their own licenses and are not bundled into the plugin. The workflow uses SHA-pinned official `actions/checkout` and `actions/setup-python`.

DSH Superagent, Switchyard, LiteLLM and vLLM Semantic Router are research references in `docs/`. Their implementation code is not included or executed by this foundation slice.

The [text-worker experiment](experiments/text-worker/README.md) packages an uninstalled host proposal with upstream-derived code/context under the preserved [Hermes MIT notice](experiments/text-worker/LICENSE.hermes-agent). The concrete experimental consumer is project code; neither artifact is imported by the production plugin.
