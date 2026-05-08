use serde::{Deserialize, Serialize};
use serde_json::json;

use super::command_registry::TelegramPublishCommand;

// ─── Response types ──────────────────────────────────────────────

#[derive(Serialize)]
pub struct BotInfo {
    pub ok: bool,
    pub username: String,
    pub bot_id: i64,
    pub first_name: String,
}

#[derive(Serialize)]
pub struct GroupInfo {
    pub ok: bool,
    pub title: String,
    pub chat_type: String,
    pub is_forum: bool,
}

#[derive(Serialize)]
pub struct PermissionInfo {
    pub ok: bool,
    pub status: String,
    pub can_manage_topics: bool,
    pub can_delete_messages: bool,
    pub can_pin_messages: bool,
}

// ─── Internal Telegram API response shapes ───────────────────────

#[derive(Deserialize)]
struct TgResponse<T> {
    ok: bool,
    result: Option<T>,
    description: Option<String>,
}

#[derive(Deserialize)]
struct TgUser {
    id: i64,
    first_name: String,
    username: Option<String>,
}

#[derive(Deserialize)]
struct TgChat {
    title: Option<String>,
    #[serde(rename = "type")]
    chat_type: String,
    is_forum: Option<bool>,
}

#[derive(Deserialize)]
struct TgChatMember {
    status: String,
    can_manage_topics: Option<bool>,
    can_delete_messages: Option<bool>,
    can_pin_messages: Option<bool>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum TelegramCommandScope {
    Default,
    AllGroupChats,
    Chat { chat_id: i64 },
}

// ─── Commands ────────────────────────────────────────────────────

fn tg_url(token: &str, method: &str) -> String {
    format!("https://api.telegram.org/bot{}/{}", token, method)
}

fn build_set_my_commands_payload(
    commands: &[TelegramPublishCommand],
    scope: &TelegramCommandScope,
) -> serde_json::Value {
    json!({
        "commands": commands
            .iter()
            .map(|command| {
                json!({
                    "command": command.command,
                    "description": command.description,
                })
            })
            .collect::<Vec<_>>(),
        "scope": scope,
    })
}

fn scope_label(scope: &TelegramCommandScope) -> String {
    match scope {
        TelegramCommandScope::Default => "default".to_string(),
        TelegramCommandScope::AllGroupChats => "all_group_chats".to_string(),
        TelegramCommandScope::Chat { chat_id } => format!("chat({chat_id})"),
    }
}

pub fn set_my_commands(
    token: &str,
    commands: &[TelegramPublishCommand],
    scope: &TelegramCommandScope,
) -> Result<(), String> {
    let payload = build_set_my_commands_payload(commands, scope);

    let resp: TgResponse<bool> = ureq::post(&tg_url(token, "setMyCommands"))
        .send_json(payload)
        .map_err(|e| {
            format!(
                "Network error while publishing {}: {}",
                scope_label(scope),
                e
            )
        })?
        .into_json()
        .map_err(|e| format!("Parse error while publishing {}: {}", scope_label(scope), e))?;

    if !resp.ok {
        return Err(resp
            .description
            .map(|description| {
                format!(
                    "Telegram publish {} failed: {description}",
                    scope_label(scope)
                )
            })
            .unwrap_or_else(|| {
                format!(
                    "Telegram publish {} failed: Unknown error",
                    scope_label(scope)
                )
            }));
    }

    Ok(())
}

pub fn publish_scoped_commands(
    token: &str,
    commands: &[TelegramPublishCommand],
    scopes: &[TelegramCommandScope],
) -> Result<(), String> {
    for scope in scopes {
        set_my_commands(token, commands, scope)?;
    }
    Ok(())
}

#[tauri::command]
pub async fn test_bot_token(token: String) -> Result<BotInfo, String> {
    let resp: TgResponse<TgUser> = ureq::get(&tg_url(&token, "getMe"))
        .call()
        .map_err(|e| format!("Network error: {}", e))?
        .into_json()
        .map_err(|e| format!("Parse error: {}", e))?;

    if !resp.ok {
        return Err(resp.description.unwrap_or_else(|| "Unknown error".into()));
    }
    let user = resp.result.ok_or("No result in response")?;
    Ok(BotInfo {
        ok: true,
        username: user.username.unwrap_or_default(),
        bot_id: user.id,
        first_name: user.first_name,
    })
}

#[tauri::command]
pub async fn test_group_access(token: String, chat_id: String) -> Result<GroupInfo, String> {
    let url = format!("{}?chat_id={}", tg_url(&token, "getChat"), chat_id);
    let resp: TgResponse<TgChat> = ureq::get(&url)
        .call()
        .map_err(|e| format!("Network error: {}", e))?
        .into_json()
        .map_err(|e| format!("Parse error: {}", e))?;

    if !resp.ok {
        return Err(resp.description.unwrap_or_else(|| "Unknown error".into()));
    }
    let chat = resp.result.ok_or("No result in response")?;
    Ok(GroupInfo {
        ok: true,
        title: chat.title.unwrap_or_default(),
        chat_type: chat.chat_type,
        is_forum: chat.is_forum.unwrap_or(false),
    })
}

#[tauri::command]
pub async fn test_bot_permissions(
    token: String,
    chat_id: String,
) -> Result<PermissionInfo, String> {
    // First get bot's own user_id
    let me_resp: TgResponse<TgUser> = ureq::get(&tg_url(&token, "getMe"))
        .call()
        .map_err(|e| format!("Network error: {}", e))?
        .into_json()
        .map_err(|e| format!("Parse error: {}", e))?;

    if !me_resp.ok {
        return Err(me_resp
            .description
            .unwrap_or_else(|| "Cannot get bot info".into()));
    }
    let bot_id = me_resp.result.ok_or("No result")?.id;

    // Then check membership
    let url = format!(
        "{}?chat_id={}&user_id={}",
        tg_url(&token, "getChatMember"),
        chat_id,
        bot_id
    );
    let resp: TgResponse<TgChatMember> = ureq::get(&url)
        .call()
        .map_err(|e| format!("Network error: {}", e))?
        .into_json()
        .map_err(|e| format!("Parse error: {}", e))?;

    if !resp.ok {
        return Err(resp.description.unwrap_or_else(|| "Unknown error".into()));
    }
    let member = resp.result.ok_or("No result")?;
    Ok(PermissionInfo {
        ok: true,
        status: member.status,
        can_manage_topics: member.can_manage_topics.unwrap_or(false),
        can_delete_messages: member.can_delete_messages.unwrap_or(false),
        can_pin_messages: member.can_pin_messages.unwrap_or(false),
    })
}

#[cfg(test)]
mod tests {
    use super::{build_set_my_commands_payload, TelegramCommandScope};
    use crate::commands::command_registry::TelegramPublishCommand;

    #[test]
    fn build_set_my_commands_payload_includes_group_scope() {
        let payload = build_set_my_commands_payload(
            &[TelegramPublishCommand {
                command: "help".to_string(),
                description: "查看帮助".to_string(),
            }],
            &TelegramCommandScope::AllGroupChats,
        );

        assert_eq!(payload["scope"]["type"], "all_group_chats");
        assert_eq!(payload["commands"][0]["command"], "help");
    }

    #[test]
    fn build_set_my_commands_payload_includes_chat_scope() {
        let payload = build_set_my_commands_payload(
            &[TelegramPublishCommand {
                command: "active".to_string(),
                description: "查看当前活跃 workspace/thread".to_string(),
            }],
            &TelegramCommandScope::Chat {
                chat_id: -1003766519352,
            },
        );

        assert_eq!(payload["scope"]["type"], "chat");
        assert_eq!(payload["scope"]["chat_id"], -1003766519352i64);
        assert_eq!(payload["commands"][0]["command"], "active");
    }
}
