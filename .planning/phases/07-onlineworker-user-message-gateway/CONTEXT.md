# Phase 7 Context: OnlineWorker User Message Gateway

## User Intent

The original feature idea was to turn abusive wording into ordinary language before the message reaches the AI provider, while preserving the user's meaning. Example:

```text
这什么傻逼问题
=> 这是什么问题
```

During design discussion, the scope was raised from a Telegram-specific hook to an OnlineWorker-level hook capability. The concrete text rewrite is the first built-in use case, not the whole architecture.

## Target Abstraction

Introduce an OnlineWorker User Message Gateway that receives every provider-bound user message as a common request object, runs OnlineWorker-level `before_user_message_send` hooks, then delegates to provider-specific `ensure_connected`, `prepare_send`, and `send` hooks.

```text
Telegram / Session Tab / owner bridge / provider session bridge / Codex CLI hook
  -> OnlineWorker User Message Gateway
  -> before_user_message_send hooks
  -> provider prepare/send
  -> Codex / Claude / future provider
```

## Design Boundaries

- Keep input-source differences at the adapter edge: Telegram update metadata, owner bridge socket requests, provider session bridge args, and Codex CLI hook payloads should be normalized into one gateway request.
- Keep provider-specific behavior in provider hooks: thread resume, owner bridge routing, Codex active-turn interruption, Claude runtime behavior, and materialization rules remain provider responsibilities.
- Keep notification delivery, approval buttons, provider output, and final-reply sync outside this input hook path.
- Treat Codex CLI direct input as a separate gateway source via `UserPromptSubmit` hook, subject to Codex hook protocol support for returning a rewritten prompt.

## First Built-In Hook

`abusive_language_normalization` should conservatively reduce attack wording without changing the user's task intent.

Initial behavior should prefer deterministic, testable rules. LLM-based rewriting can be added later as an optional hook if the rule-based path proves too limited.

## Open Planning Questions

- Whether the built-in abusive-language hook is enabled by default or only after config/UI opt-in.
- Whether slash command arguments should be hookable later; first implementation should preserve slash command semantics.
- What exact return contract Codex `UserPromptSubmit` supports for prompt rewriting.
