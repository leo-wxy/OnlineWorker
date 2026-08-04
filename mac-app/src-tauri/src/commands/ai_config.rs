use serde::{Deserialize, Serialize};
use serde_json::json;
use std::io::Read;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use super::config::{
    provider_launch_command, provider_validation_rich_path, read_provider_metadata_from_disk,
    resolve_provider_cli_path,
};
use super::config_provider::AiServiceConfigEntry;

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AiConnectionTestResult {
    pub ok: bool,
    pub status: Option<u16>,
    pub message: String,
}

#[tauri::command]
pub async fn test_ai_service_connection(
    service: AiServiceConfigEntry,
) -> Result<AiConnectionTestResult, String> {
    tauri::async_runtime::spawn_blocking(move || test_ai_service_connection_blocking(service))
        .await
        .map_err(|e| e.to_string())?
}

fn test_ai_service_connection_blocking(
    service: AiServiceConfigEntry,
) -> Result<AiConnectionTestResult, String> {
    if service.protocol.trim() == "provider_login" {
        return test_provider_login(&service);
    }

    let api_key = service.api_key.trim().to_string();
    if api_key.trim().is_empty() {
        return Ok(AiConnectionTestResult {
            ok: false,
            status: None,
            message: "API Key is empty".to_string(),
        });
    }

    match service.protocol.trim() {
        "openai_compatible_chat" => test_openai_compatible_chat(&service, &api_key),
        "anthropic_messages" => test_anthropic_messages(&service, &api_key),
        protocol => Ok(AiConnectionTestResult {
            ok: false,
            status: None,
            message: format!("Unsupported protocol: {protocol}"),
        }),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ProviderLoginCommandOutput {
    success: bool,
    code: Option<i32>,
    stdout: String,
    stderr: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum ProviderLoginProbeError {
    Io(String),
    Timeout(Duration),
}

fn test_provider_login(service: &AiServiceConfigEntry) -> Result<AiConnectionTestResult, String> {
    let owner_provider_id = service.owner_provider_id.trim();
    if owner_provider_id.is_empty() {
        return Ok(provider_login_failure(
            "Provider login service is missing ownerProviderId",
        ));
    }
    let Some(probe_args) = provider_login_probe_args(owner_provider_id) else {
        return Ok(provider_login_failure(&format!(
            "Unsupported provider login owner: {owner_provider_id}"
        )));
    };

    let providers = read_provider_metadata_from_disk()?;
    let Some(provider) = providers
        .iter()
        .find(|provider| provider.id == owner_provider_id)
    else {
        return Ok(provider_login_failure(&format!(
            "Provider metadata not found for {owner_provider_id}"
        )));
    };
    let Some(launch_command) = provider_launch_command(provider) else {
        return Ok(provider_login_failure(&format!(
            "No CLI launch command is configured for {owner_provider_id}"
        )));
    };
    let Some(cli_path) = resolve_provider_cli_path(&launch_command) else {
        return Ok(provider_login_failure(&format!(
            "CLI not found for {owner_provider_id}: {launch_command}"
        )));
    };

    let mut args = command_line_tail_args(&launch_command);
    args.extend(probe_args.into_iter().map(str::to_string));
    match run_provider_login_command(&cli_path, &args, provider_login_timeout(service)) {
        Ok(output) => Ok(provider_login_result_from_parts(
            owner_provider_id,
            output.success,
            output.code,
            &combined_output(&output.stdout, &output.stderr),
        )),
        Err(ProviderLoginProbeError::Timeout(timeout)) => Ok(provider_login_failure(&format!(
            "{} CLI login status timed out after {}s",
            provider_display_name(owner_provider_id),
            timeout.as_secs().max(1)
        ))),
        Err(ProviderLoginProbeError::Io(message)) => Ok(provider_login_failure(&format!(
            "{} CLI login status failed: {message}",
            provider_display_name(owner_provider_id)
        ))),
    }
}

fn provider_login_timeout(service: &AiServiceConfigEntry) -> Duration {
    let seconds = if service.timeout_seconds == 0 {
        30
    } else {
        service.timeout_seconds.min(30)
    };
    Duration::from_secs(u64::from(seconds))
}

fn provider_login_probe_args(owner_provider_id: &str) -> Option<Vec<&'static str>> {
    match owner_provider_id {
        "codex" => Some(vec!["login", "status"]),
        "claude" => Some(vec!["auth", "status"]),
        _ => None,
    }
}

fn run_provider_login_command(
    program: &str,
    args: &[String],
    timeout: Duration,
) -> Result<ProviderLoginCommandOutput, ProviderLoginProbeError> {
    let mut child = Command::new(program)
        .args(args)
        .env("PATH", provider_validation_rich_path())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| ProviderLoginProbeError::Io(e.to_string()))?;

    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                let mut stdout = String::new();
                if let Some(mut pipe) = child.stdout.take() {
                    pipe.read_to_string(&mut stdout)
                        .map_err(|e| ProviderLoginProbeError::Io(e.to_string()))?;
                }
                let mut stderr = String::new();
                if let Some(mut pipe) = child.stderr.take() {
                    pipe.read_to_string(&mut stderr)
                        .map_err(|e| ProviderLoginProbeError::Io(e.to_string()))?;
                }
                return Ok(ProviderLoginCommandOutput {
                    success: status.success(),
                    code: status.code(),
                    stdout,
                    stderr,
                });
            }
            Ok(None) if started.elapsed() >= timeout => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(ProviderLoginProbeError::Timeout(timeout));
            }
            Ok(None) => thread::sleep(Duration::from_millis(50)),
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(ProviderLoginProbeError::Io(e.to_string()));
            }
        }
    }
}

fn command_line_tail_args(command_line: &str) -> Vec<String> {
    let mut parts = split_command_line(command_line);
    if !parts.is_empty() {
        parts.remove(0);
    }
    parts
}

fn split_command_line(command_line: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut quote: Option<char> = None;
    let mut escaped = false;

    for ch in command_line.chars() {
        if escaped {
            current.push(ch);
            escaped = false;
            continue;
        }
        if ch == '\\' {
            escaped = true;
            continue;
        }
        match quote {
            Some(quote_char) if ch == quote_char => quote = None,
            Some(_) => current.push(ch),
            None if ch == '"' || ch == '\'' => quote = Some(ch),
            None if ch.is_whitespace() => {
                if !current.is_empty() {
                    parts.push(std::mem::take(&mut current));
                }
            }
            None => current.push(ch),
        }
    }
    if escaped {
        current.push('\\');
    }
    if !current.is_empty() {
        parts.push(current);
    }
    parts
}

fn combined_output(stdout: &str, stderr: &str) -> String {
    [stdout.trim(), stderr.trim()]
        .into_iter()
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

fn provider_login_result_from_parts(
    owner_provider_id: &str,
    success: bool,
    code: Option<i32>,
    output: &str,
) -> AiConnectionTestResult {
    let label = provider_display_name(owner_provider_id);
    let detail = compact_status_output(output);
    if provider_login_output_indicates_logged_out(output) {
        return provider_login_failure(&format!("{label} CLI is not logged in"));
    }
    if provider_login_output_indicates_logged_in(output) {
        return AiConnectionTestResult {
            ok: true,
            status: None,
            message: format!("{label} CLI login verified"),
        };
    }
    if success {
        return provider_login_failure(&format!(
            "{label} CLI login status is unknown: {}",
            detail_or_exit(&detail, code)
        ));
    }
    provider_login_failure(&format!(
        "{label} CLI login status failed{}: {}",
        code.map(|value| format!(" (exit {value})"))
            .unwrap_or_default(),
        detail_or_exit(&detail, code)
    ))
}

fn provider_login_output_indicates_logged_out(output: &str) -> bool {
    let lower = output.to_ascii_lowercase();
    let compact = lower
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect::<String>();
    lower.contains("not logged in")
        || lower.contains("not authenticated")
        || lower.contains("please run /login")
        || lower.contains("run codex login")
        || compact.contains("\"ready\":false")
        || compact.contains("\"authenticated\":false")
        || compact.contains("\"loggedin\":false")
        || compact.contains("\"logged_in\":false")
}

fn provider_login_output_indicates_logged_in(output: &str) -> bool {
    let lower = output.to_ascii_lowercase();
    let compact = lower
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect::<String>();
    lower.contains("logged in")
        || lower.contains("authenticated")
        || compact.contains("\"ready\":true")
        || compact.contains("\"authenticated\":true")
        || compact.contains("\"loggedin\":true")
        || compact.contains("\"logged_in\":true")
}

fn compact_status_output(output: &str) -> String {
    let text = output
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    let mut compact = text.chars().take(500).collect::<String>();
    if text.chars().count() > 500 {
        compact.push_str("...");
    }
    compact
}

fn detail_or_exit(detail: &str, code: Option<i32>) -> String {
    if !detail.is_empty() {
        return detail.to_string();
    }
    code.map(|value| format!("exit {value}"))
        .unwrap_or_else(|| "no output".to_string())
}

fn provider_display_name(owner_provider_id: &str) -> &str {
    match owner_provider_id {
        "codex" => "Codex",
        "claude" => "Claude",
        _ => owner_provider_id,
    }
}

fn provider_login_failure(message: &str) -> AiConnectionTestResult {
    AiConnectionTestResult {
        ok: false,
        status: None,
        message: message.to_string(),
    }
}

fn ai_test_agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(10))
        .timeout_read(Duration::from_secs(20))
        .timeout_write(Duration::from_secs(20))
        .try_proxy_from_env(true)
        .build()
}

fn test_openai_compatible_chat(
    service: &AiServiceConfigEntry,
    api_key: &str,
) -> Result<AiConnectionTestResult, String> {
    let endpoint = if service.endpoint.trim().is_empty() {
        let base = if service.base_url.trim().is_empty() {
            "https://api.openai.com/v1"
        } else {
            service.base_url.trim().trim_end_matches('/')
        };
        format!("{base}/chat/completions")
    } else {
        service.endpoint.trim().to_string()
    };
    let model = model_for_test(service);
    if model.is_empty() {
        return Ok(AiConnectionTestResult {
            ok: false,
            status: None,
            message: "Model is empty".to_string(),
        });
    }

    let payload = json!({
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Return compact JSON: {\"ok\": true}"
            }
        ],
        "temperature": 0,
        "max_tokens": 32,
        "response_format": { "type": "json_object" }
    });

    let response = ai_test_agent()
        .post(&endpoint)
        .set("Authorization", &format!("Bearer {api_key}"))
        .set("Content-Type", "application/json")
        .send_json(payload);
    Ok(connection_result(response))
}

fn test_anthropic_messages(
    service: &AiServiceConfigEntry,
    api_key: &str,
) -> Result<AiConnectionTestResult, String> {
    let endpoint = if service.endpoint.trim().is_empty() {
        "https://api.anthropic.com/v1/messages".to_string()
    } else {
        service.endpoint.trim().to_string()
    };
    let model = model_for_test(service);
    if model.is_empty() {
        return Ok(AiConnectionTestResult {
            ok: false,
            status: None,
            message: "Model is empty".to_string(),
        });
    }

    let payload = json!({
        "model": model,
        "max_tokens": 32,
        "messages": [
            {
                "role": "user",
                "content": "Return compact JSON: {\"ok\": true}"
            }
        ]
    });

    let response = ai_test_agent()
        .post(&endpoint)
        .set("x-api-key", api_key)
        .set("anthropic-version", "2023-06-01")
        .set("Content-Type", "application/json")
        .send_json(payload);
    Ok(connection_result(response))
}

fn model_for_test(service: &AiServiceConfigEntry) -> String {
    let default_model = service.default_model.trim();
    if !default_model.is_empty() {
        return default_model.to_string();
    }
    service
        .models
        .iter()
        .find_map(|model| {
            let trimmed = model.trim();
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            }
        })
        .unwrap_or_default()
}

fn connection_result(response: Result<ureq::Response, ureq::Error>) -> AiConnectionTestResult {
    match response {
        Ok(resp) => AiConnectionTestResult {
            ok: (200..300).contains(&resp.status()),
            status: Some(resp.status()),
            message: "Connection verified".to_string(),
        },
        Err(ureq::Error::Status(code, resp)) => AiConnectionTestResult {
            ok: false,
            status: Some(code),
            message: resp
                .into_string()
                .unwrap_or_else(|_| format!("HTTP {code}")),
        },
        Err(err) => AiConnectionTestResult {
            ok: false,
            status: None,
            message: err.to_string(),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::{
        command_line_tail_args, model_for_test, provider_login_probe_args,
        provider_login_result_from_parts, test_ai_service_connection_blocking,
    };
    use crate::commands::config_provider::AiServiceConfigEntry;

    #[test]
    fn test_ai_connection_rejects_missing_api_key_before_http_call() {
        let result = test_ai_service_connection_blocking(AiServiceConfigEntry {
            id: "openai_default".to_string(),
            name: "OpenAI".to_string(),
            owner_provider_id: String::new(),
            protocol: "openai_compatible_chat".to_string(),
            base_url: "https://api.openai.com/v1".to_string(),
            endpoint: String::new(),
            api_key: String::new(),
            api_key_env: String::new(),
            models: vec!["gpt-5.4".to_string()],
            default_model: "gpt-5.4".to_string(),
            timeout_seconds: 20,
            enabled: true,
        })
        .expect("test result");

        assert!(!result.ok);
        assert_eq!(result.status, None);
        assert_eq!(result.message, "API Key is empty");
    }

    #[test]
    fn model_for_test_falls_back_to_first_model() {
        let service = AiServiceConfigEntry {
            id: "provider_default".to_string(),
            name: "Provider".to_string(),
            owner_provider_id: String::new(),
            protocol: "openai_compatible_chat".to_string(),
            base_url: String::new(),
            endpoint: String::new(),
            api_key: "sk-test".to_string(),
            api_key_env: "PROVIDER_API_KEY".to_string(),
            models: vec!["model-alpha".to_string()],
            default_model: String::new(),
            timeout_seconds: 20,
            enabled: true,
        };

        assert_eq!(model_for_test(&service), "model-alpha");
    }

    #[test]
    fn provider_login_test_skips_api_key_requirement() {
        let result = test_ai_service_connection_blocking(AiServiceConfigEntry {
            id: "codex_login".to_string(),
            name: "Codex Login".to_string(),
            owner_provider_id: String::new(),
            protocol: "provider_login".to_string(),
            base_url: String::new(),
            endpoint: String::new(),
            api_key: String::new(),
            api_key_env: String::new(),
            models: Vec::new(),
            default_model: String::new(),
            timeout_seconds: 30,
            enabled: true,
        })
        .expect("test result");

        assert!(!result.ok);
        assert_eq!(result.status, None);
        assert_eq!(
            result.message,
            "Provider login service is missing ownerProviderId"
        );
    }

    #[test]
    fn provider_login_probe_uses_known_cli_auth_commands() {
        assert_eq!(
            provider_login_probe_args("codex"),
            Some(vec!["login", "status"])
        );
        assert_eq!(
            provider_login_probe_args("claude"),
            Some(vec!["auth", "status"])
        );
        assert_eq!(provider_login_probe_args("other"), None);
    }

    #[test]
    fn provider_login_result_recognizes_logged_in_status() {
        let result = provider_login_result_from_parts("codex", true, Some(0), "Logged in as user");

        assert!(result.ok);
        assert_eq!(result.status, None);
        assert_eq!(result.message, "Codex CLI login verified");
    }

    #[test]
    fn provider_login_result_reports_logged_out_before_logged_in_match() {
        let result = provider_login_result_from_parts("claude", false, Some(1), "Not logged in");

        assert!(!result.ok);
        assert_eq!(result.status, None);
        assert_eq!(result.message, "Claude CLI is not logged in");
    }

    #[test]
    fn provider_login_result_recognizes_json_readiness_status() {
        let result = provider_login_result_from_parts(
            "claude",
            true,
            Some(0),
            r#"{"ready": true, "authMethod": "oauth"}"#,
        );

        assert!(result.ok);
        assert_eq!(result.message, "Claude CLI login verified");
    }

    #[test]
    fn command_line_tail_args_preserves_configured_launcher_args() {
        assert_eq!(
            command_line_tail_args(r#""/Users/example/bin/company launcher" start --profile main"#),
            vec![
                "start".to_string(),
                "--profile".to_string(),
                "main".to_string()
            ]
        );
    }
}
