use std::collections::{BTreeMap, BTreeSet};

use super::{
    provider_ai_service_defaults, AiConfigDocument, AiConfigMetadata, AiScenarioConfigEntry,
    AiScenarioMetadata, AiServiceConfigEntry, AiServiceMetadata, ProviderAiServiceDefault,
    ProviderConfigDocument,
};

const LEGACY_NOTIFICATION_SUMMARY_PROMPT: &str = "You summarize OnlineWorker task completion notifications.\nReturn compact JSON with preview_title and summary.\npreview_title identifies the completed task.\nsummary explains the completed result.\n\nCurrent task:\n{{task_summary}}\n\nFinal assistant message:\n{{final_message}}\n";
const DEFAULT_NOTIFICATION_SUMMARY_PROMPT: &str = "You summarize OnlineWorker task completion notifications.\nReturn JSON only, without markdown:\n{\"preview_title\": \"...\", \"summary\": \"...\"}\n\nRules:\n- preview_title must be a complete short Chinese title, ideally 6 to 12 Chinese characters.\n- Avoid English in preview_title unless it is a product or provider name.\n- Do not return truncated words, ellipsis, code fences, or punctuation-only titles.\n- summary must be one concise Chinese sentence describing what was completed.\n\nCurrent task:\n{{task_summary}}\n\nFinal assistant message:\n{{final_message}}\n";
fn normalize_ai_service_id(raw: &str) -> String {
    raw.trim().to_string()
}

fn normalize_ai_protocol(raw: &str) -> String {
    raw.trim().to_string()
}

fn builtin_ai_services() -> Vec<ProviderAiServiceDefault> {
    provider_ai_service_defaults()
}

fn fallback_service_id(
    service_ids: &BTreeSet<String>,
    services: &[AiServiceConfigEntry],
    builtin_services: &[ProviderAiServiceDefault],
) -> String {
    if let Some(default_service) = builtin_services
        .iter()
        .find(|service| service.default_for_scenarios && service_ids.contains(&service.id))
    {
        return default_service.id.clone();
    }
    services
        .first()
        .map(|service| service.id.clone())
        .unwrap_or_default()
}

pub(super) fn normalize_ai_document(doc: &mut ProviderConfigDocument) {
    let ai = doc.ai.get_or_insert_with(AiConfigDocument::default);
    let services = ai.services.get_or_insert_with(Vec::new);
    let builtin_services = builtin_ai_services();
    for builtin in &builtin_services {
        if !services.iter().any(|service| service.id == builtin.id) {
            services.push(builtin.config.clone());
        }
    }
    for service in services.iter_mut() {
        service.id = normalize_ai_service_id(&service.id);
        service.name = if service.name.trim().is_empty() {
            service.id.clone()
        } else {
            service.name.trim().to_string()
        };
        if service.protocol.trim().is_empty() {
            service.protocol = "openai_compatible_chat".to_string();
        } else {
            service.protocol = normalize_ai_protocol(&service.protocol);
        }
        service.base_url = service.base_url.trim().trim_end_matches('/').to_string();
        service.endpoint = service.endpoint.trim().to_string();
        service.api_key = service.api_key.trim().to_string();
        service.api_key_env = service.api_key_env.trim().to_string();
        service.models = service
            .models
            .iter()
            .map(|model| model.trim().to_string())
            .filter(|model| !model.is_empty())
            .collect();
        if service.default_model.trim().is_empty() {
            service.default_model = service.models.first().cloned().unwrap_or_default();
        } else {
            service.default_model = service.default_model.trim().to_string();
        }
        if service.timeout_seconds == 0 {
            service.timeout_seconds = 20;
        }
    }
    services.retain(|service| !service.id.is_empty());
    let service_ids: BTreeSet<String> = services.iter().map(|service| service.id.clone()).collect();
    let fallback_service_id = fallback_service_id(&service_ids, services, &builtin_services);

    let scenarios = ai.scenarios.get_or_insert_with(BTreeMap::new);
    let notification = scenarios
        .entry("notification_summary".to_string())
        .or_insert_with(AiScenarioConfigEntry::default);
    if notification.output_schema.trim().is_empty() {
        notification.output_schema = "notification_summary_v1".to_string();
    }
    if notification.fallback.trim().is_empty() {
        notification.fallback = "local_notification_summary_rules".to_string();
    }
    if notification.prompt_template.trim().is_empty()
        || notification.prompt_template == LEGACY_NOTIFICATION_SUMMARY_PROMPT
    {
        notification.prompt_template = DEFAULT_NOTIFICATION_SUMMARY_PROMPT.to_string();
    }
    notification
        .limits
        .entry("preview_title".to_string())
        .or_insert(16);

    for scenario in scenarios.values_mut() {
        scenario.service_id = scenario.service_id.trim().to_string();
        if (scenario.service_id.is_empty() || !service_ids.contains(&scenario.service_id))
            && !fallback_service_id.is_empty()
        {
            scenario.service_id = fallback_service_id.clone();
        }
        scenario.model = scenario.model.trim().to_string();
        if scenario.output_schema.trim().is_empty() {
            scenario.output_schema = "text".to_string();
        } else {
            scenario.output_schema = scenario.output_schema.trim().to_string();
        }
        scenario.fallback = scenario.fallback.trim().to_string();
    }
}

pub(super) fn ai_metadata_from_document(doc: ProviderConfigDocument) -> AiConfigMetadata {
    let ai = doc.ai.unwrap_or_default();
    let builtin_labels = builtin_ai_services()
        .into_iter()
        .map(|service| (service.id.clone(), service))
        .collect::<BTreeMap<_, _>>();
    let services = ai
        .services
        .unwrap_or_default()
        .into_iter()
        .map(|service| {
            let defaults = builtin_labels.get(&service.id);
            AiServiceMetadata {
                id: service.id.clone(),
                name: service.name,
                label: defaults
                    .map(|item| item.label.clone())
                    .unwrap_or_else(|| service.id.clone()),
                description: defaults
                    .map(|item| item.description.clone())
                    .unwrap_or_default(),
                owner_provider_id: defaults
                    .map(|item| item.owner_provider_id.clone())
                    .unwrap_or_default(),
                plugin_owned: defaults.map(|item| item.plugin_owned).unwrap_or(false),
                protocol: service.protocol,
                base_url: service.base_url,
                endpoint: service.endpoint,
                api_key: service.api_key,
                api_key_env: service.api_key_env,
                models: service.models,
                default_model: service.default_model,
                timeout_seconds: service.timeout_seconds,
                enabled: service.enabled,
            }
        })
        .collect();
    let scenarios = ai
        .scenarios
        .unwrap_or_default()
        .into_iter()
        .map(|(id, scenario)| AiScenarioMetadata {
            id,
            enabled: scenario.enabled,
            service_id: scenario.service_id,
            model: scenario.model,
            output_schema: scenario.output_schema,
            fallback: scenario.fallback,
            limits: scenario.limits,
            prompt_template: scenario.prompt_template,
        })
        .collect();
    AiConfigMetadata {
        services,
        scenarios,
    }
}

pub(in crate::commands) fn set_ai_config_in_document(
    doc: &mut ProviderConfigDocument,
    services: Vec<AiServiceConfigEntry>,
    scenarios: BTreeMap<String, AiScenarioConfigEntry>,
) {
    doc.ai = Some(AiConfigDocument {
        services: Some(services),
        scenarios: Some(scenarios),
    });
    normalize_ai_document(doc);
    doc.schema_version = Some(2);
    doc.tools = None;
}
