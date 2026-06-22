use serde::{Deserialize, Serialize};
use serde_json::json;
use std::time::Duration;

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
    use super::{model_for_test, test_ai_service_connection_blocking};
    use crate::commands::config_provider::AiServiceConfigEntry;

    #[test]
    fn test_ai_connection_rejects_missing_api_key_before_http_call() {
        let result = test_ai_service_connection_blocking(AiServiceConfigEntry {
            id: "openai_default".to_string(),
            name: "OpenAI".to_string(),
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
}
