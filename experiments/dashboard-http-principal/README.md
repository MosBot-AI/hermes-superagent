# Dashboard HTTP principal proposal

English | [简体中文](README-zh.md)

The optional personal API needs the host-verified caller and the effective serving profile before it can check collection access. On clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, the normal dashboard gate admits requests, the manifest mounts the plugin, and the isolated process receives `hosted_http_authenticated`. That process receives no corresponding verified provider identity. With the same synthetic plugin, the stock controls exercise authentication and return `503 host_identity_unavailable` from the protected probe.

The [review-only patch](dashboard-http-principal.patch) exposes `get_plugin_http_principal(request)` to a dashboard plugin's HTTP handler. The host records whether its existing provider gate verified a cookie session, including refresh, or a bearer. After profile resolution and plugin consent, it assembles a frozen snapshot of `provider`, `issuer`, `subject`, `organization`, `credential_kind`, and `profile_name`. In hosted mode it serializes only these six fields on the existing private request channel. The child accepts the snapshot when the same request has normal host admission and valid fields. The accessor reads the request's state in both modes.

The snapshot requires a valid provider, a nonempty verified issuer and subject, and a host-resolved profile name. The organization can be empty. The snapshot contains no bearer, cookie, display name, email, home path or policy. The serving profile is a routing label and can be renamed. Consumers still need a current owner binding, object authorization, and a revocation fence. Retain the identity only as required for the current request. Its value carries no independent authority outside the host request. The [protected synthetic consumer](test_http_principal.py) demonstrates the interface without domain data or writes.

| Existing credential | Candidate result |
| --- | --- |
| Gated provider cookie, including a refreshed cookie | Snapshot labeled `cookie_session` |
| Gated provider bearer with a verified issuer and subject | Snapshot labeled `provider_bearer` |
| Deployment session token, including bearer presentation, or issuer-less session | Existing admission can succeed. The accessor returns no snapshot. |
| Loopback browser token, native same-user HTTP grant, or registered service token | Existing admission remains specific to its native route. The accessor returns no snapshot. |

The repeated comparison covers in-process and hosted launch routing, a distinct secondary-profile host, cookie refresh and subsequent use, overlapping requests with distinct subjects, refusal for an invalid bearer even when a valid cookie is present, wrong-page cookie writes, unknown profiles and runtime plugin disablement. It also covers admission without provider identity for the native grant, loopback token, and deployment token. The dashboard is the real pinned ASGI application. The provider and Gateway authority fixture use synthetic inputs. Hosted requests reach real plugin-host child processes. The comparison does not establish deployed ingress, a real identity provider, an isolated host's revocation behavior while a response is in flight, or the shared task API.

On Python 3.14.9, seven comparison cases passed on each tree. The upstream per-file runner passed 132 cases on the candidate. The candidate also passed the upstream 15-check static suite and the import-boundary check. The [manifest](manifest.json) records the exact staged tree and test inputs.

## Reproduce in disposable checkouts

Set `PROJECT` to this project checkout, `CLEAN` and `PROPOSED` to separate clean checkouts of the base, and `PYTHON` to the pinned Hermes Python 3.14.9 test interpreter. Preserve the standard project's clean compatibility checkout.

```sh
set -eu
ARTIFACT="$PROJECT/experiments/dashboard-http-principal"
BASE=2281116525106e3c109993ccb5dc74d02bfc1427
test "$(git -C "$CLEAN" rev-parse HEAD)" = "$BASE"
test "$(git -C "$PROPOSED" rev-parse HEAD)" = "$BASE"
test -z "$(git -C "$PROPOSED" status --porcelain)"
git -C "$PROPOSED" apply --check "$ARTIFACT/dashboard-http-principal.patch"
git -C "$PROPOSED" apply --index "$ARTIFACT/dashboard-http-principal.patch"
"$PYTHON" "$ARTIFACT/run_tests.py" --clean "$CLEAN" --proposed "$PROPOSED" --python "$PYTHON"
```

The runner verifies both exact checkouts and the [manifest](manifest.json), scrubs the subprocess environment, uses a temporary home per group and denies external network access. It verifies passing comparison cases with no captured output, then runs the existing native regression selection using the upstream per-file runner. Review the [upstream license](LICENSE.hermes-agent). The patch is inactive and unsubmitted upstream.
