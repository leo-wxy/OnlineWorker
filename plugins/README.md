# Plugins

This directory is the repository-level extension boundary for OnlineWorker.

Provider manifests under `plugins/providers/` describe the public provider surface that the app can discover and render. Implementation code may live alongside the app code when that is the simplest public contract to keep stable.

For provider plugin development rules, see [providers/DEVELOPMENT.md](providers/DEVELOPMENT.md).

Notification manifests under `plugins/notifications/` describe notification channels that the app can discover and configure. The builtin Telegram notification channel lives there; external channels such as WeChat can be mounted with `ONLINEWORKER_NOTIFICATION_OVERLAY`.

For notification plugin development rules, see [notifications/DEVELOPMENT.md](notifications/DEVELOPMENT.md).
