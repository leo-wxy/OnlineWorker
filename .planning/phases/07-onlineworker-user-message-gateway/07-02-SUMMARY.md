# 07-02 Summary: Dictionary-Backed User Message Neutralizer

## Result

Upgraded the Phase 7 abusive-language hook from inline string replacement to a small dictionary-backed neutralizer.

## Implemented

- Added `core/user_messages/sensitive_terms.py`:
  - `SensitiveTerm`
  - `SensitiveTermMatch`
  - `SensitiveTermMatcher`
  - first built-in term set with `drop` and `replace` actions.
- Added `core/user_messages/neutralizer.py`:
  - applies matched term actions outside fenced code blocks.
  - removes leading/trailing leftover punctuation.
  - repairs the `这什么...问题` sentence pattern to `这是什么...问题`.
- Updated `core/user_messages/builtin_hooks.py` so `abusive_language_normalization` delegates to the neutralizer.
- Added `scripts/test_user_message_normalizer.py` for manual checks.

## Behavior Examples

```text
你妈的，这什么傻逼问题
=> 这是什么问题
```

```text
妈的，怎么又连不上了
=> 怎么又连不上了
```

```text
你妈的
=>
```

```text
这破玩意怎么一直报错
=> 这个怎么一直报错
```

## Script

```bash
python3 scripts/test_user_message_normalizer.py '你妈的，这什么傻逼问题'
```

Example output:

```text
original: 你妈的，这什么傻逼问题
normalized: 这是什么问题
changed: true
matches:
  - 你妈的 / abuse_prefix / drop
  - 傻逼 / insult / drop
```

## Verification

Passed:

```bash
rtk pytest -q tests/test_handlers.py tests/test_user_message_hooks.py tests/test_user_message_normalizer_script.py tests/test_config.py tests/test_thread_controls.py tests/test_provider_owner_bridge.py tests/test_provider_session_bridge.py tests/test_provider_session_bridge_attachments.py tests/test_codex_hook_bridge.py && git diff --check
```

Observed result:

```text
Pytest: 137 passed
```

`git diff --check` produced no output.

## Not Run

Packaged-app build/install/relaunch verification was not run for Phase 7 after this extension.
