#[cfg(test)]
mod tests {
    use super::{
        await_loopback_session, begin_loopback_session, cancel_loopback_session,
        confined_feature_root, normalize_sidecar_result, validate_action_payload,
        valid_feature_id, AccountFeatureHostState, CapabilityMode,
    };
    use crate::commands::provider_bridge_common::ProviderBridgeOutput;
    use serde_json::json;
    use std::fs;
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::os::unix::fs::{symlink, PermissionsExt};
    use std::time::Duration;

    fn temp_dir() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "onlineworker-account-feature-test-{}",
            uuid::Uuid::new_v4()
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn feature_root_is_safe_and_confined() {
        let base = temp_dir();
        assert!(valid_feature_id("feature-a"));
        for invalid in ["", "../feature", "feature/a", "feature\\a", "/absolute"] {
            assert!(!valid_feature_id(invalid));
        }

        let root = confined_feature_root(&base, "feature-a").unwrap();

        assert!(root.starts_with(base.canonicalize().unwrap()));
        assert_eq!(fs::metadata(&root).unwrap().permissions().mode() & 0o777, 0o700);
        assert!(confined_feature_root(&base, "../escape").is_err());
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn reserved_trusted_context_fields_are_rejected() {
        assert!(validate_action_payload(&json!({"value": 1})).is_ok());
        for key in ["data_root", "dataRoot", "native_paths", "nativePaths"] {
            let mut payload = serde_json::Map::new();
            payload.insert(key.to_string(), json!("/tmp/not-trusted"));
            assert!(validate_action_payload(&serde_json::Value::Object(payload)).is_err());
        }
    }

    #[test]
    fn process_failures_are_generic_and_redacted() {
        let failed = normalize_sidecar_result(Ok(ProviderBridgeOutput {
            code: Some(1),
            signal: None,
            stdout: b"credential-fixture".to_vec(),
            stderr: b"credential-fixture /Users/example/private.json".to_vec(),
        }));
        let malformed = normalize_sidecar_result(Ok(ProviderBridgeOutput {
            code: Some(0),
            signal: None,
            stdout: b"not-json".to_vec(),
            stderr: Vec::new(),
        }));
        let timeout = normalize_sidecar_result(Err("account feature timed out after 10ms".into()));

        for response in [&failed, &malformed, &timeout] {
            let serialized = serde_json::to_string(response).unwrap();
            assert!(!serialized.contains("credential-fixture"));
            assert!(!serialized.contains("/Users/example"));
        }
        assert_eq!(failed.error.unwrap().code, "feature_failed");
        assert_eq!(malformed.error.unwrap().code, "invalid_response");
        assert_eq!(timeout.error.unwrap().code, "host_timeout");
    }

    #[test]
    fn native_handles_are_feature_mode_expiry_and_replay_bound() {
        let state = AccountFeatureHostState::default();
        let root = temp_dir();
        let file = root.join("fixture.json");
        fs::write(&file, b"fixture").unwrap();
        let handle = state
            .issue_native_handle("feature-a", CapabilityMode::Open, file.clone(), Duration::from_secs(5))
            .unwrap();
        let visible = serde_json::to_string(&handle).unwrap();
        assert!(!visible.contains(file.to_string_lossy().as_ref()));

        assert!(state
            .redeem_native_handle("feature-b", &handle.handle_id, CapabilityMode::Open)
            .is_err());
        assert_eq!(
            state
                .redeem_native_handle("feature-a", &handle.handle_id, CapabilityMode::Open)
                .unwrap(),
            file.canonicalize().unwrap()
        );
        assert!(state
            .redeem_native_handle("feature-a", &handle.handle_id, CapabilityMode::Open)
            .is_err());

        let wrong_mode = state
            .issue_native_handle("feature-a", CapabilityMode::Open, file.clone(), Duration::from_secs(5))
            .unwrap();
        assert!(state
            .redeem_native_handle("feature-a", &wrong_mode.handle_id, CapabilityMode::Save)
            .is_err());

        let expired = state
            .issue_native_handle("feature-a", CapabilityMode::Open, file.clone(), Duration::ZERO)
            .unwrap();
        assert!(state
            .redeem_native_handle("feature-a", &expired.handle_id, CapabilityMode::Open)
            .is_err());

        let target = root.join("target.json");
        symlink(&file, &target).unwrap();
        let linked = state
            .issue_native_handle("feature-a", CapabilityMode::Open, target, Duration::from_secs(5))
            .unwrap();
        assert!(state
            .redeem_native_handle("feature-a", &linked.handle_id, CapabilityMode::Open)
            .is_err());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn loopback_is_local_bounded_single_use_and_cancellable() {
        let state = AccountFeatureHostState::default();
        let session = begin_loopback_session(
            &state,
            "feature-a",
            0,
            "/auth/callback",
            Duration::from_secs(2),
        )
        .unwrap();
        assert!(session.redirect_uri.starts_with("http://127.0.0.1:"));
        let address = session.redirect_uri.trim_start_matches("http://");
        let address = address.split('/').next().unwrap();
        let mut stream = TcpStream::connect(address).unwrap();
        stream
            .write_all(b"GET /auth/callback?code=fixture&state=fixture HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            .unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).unwrap();
        assert!(response.starts_with("HTTP/1.1 200"));

        let completed = await_loopback_session(&state, "feature-a", &session.handle_id).unwrap();
        assert_eq!(completed.status, "completed");
        assert!(completed
            .callback_url
            .unwrap()
            .ends_with("/auth/callback?code=fixture&state=fixture"));
        assert!(await_loopback_session(&state, "feature-a", &session.handle_id).is_err());

        let cancelled = begin_loopback_session(
            &state,
            "feature-a",
            0,
            "/auth/callback",
            Duration::from_secs(2),
        )
        .unwrap();
        assert!(cancel_loopback_session(&state, "feature-a", &cancelled.handle_id).unwrap());
        let _ = cancel_loopback_session(&state, "feature-a", &cancelled.handle_id);
        assert!(begin_loopback_session(&state, "feature-a", 0, "bad?path", Duration::from_secs(1)).is_err());
    }

    #[test]
    fn shared_host_source_has_no_live_or_provider_business_authority() {
        let source = include_str!("account_feature.rs");
        for forbidden in [
            ["provider", "_owner_bridge"].concat(),
            ["provider", "_sessions"].concat(),
            ["provider", "_usage"].concat(),
            ["task_board", "_state"].concat(),
            ["Bot", "State"].concat(),
            ["Tele", "gram"].concat(),
        ] {
            assert!(!source.contains(&forbidden));
        }
    }
}
