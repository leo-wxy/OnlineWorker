import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { BotInfo, GroupInfo, PermissionInfo } from "../types";
import { useI18n } from "../i18n";

interface Props {
  token: string;
  chatId: string;
  compact?: boolean;
}

type TestStatus = "idle" | "running" | "pass" | "fail";

interface TestResult {
  status: TestStatus;
  detail: string;
}

export function ConnectivityTest({ token, chatId, compact }: Props) {
  const { t } = useI18n();
  const texts = t.connectivity;
  const [botTest, setBotTest] = useState<TestResult>({ status: "idle", detail: "" });
  const [groupTest, setGroupTest] = useState<TestResult>({ status: "idle", detail: "" });
  const [permTest, setPermTest] = useState<TestResult>({ status: "idle", detail: "" });
  const [testing, setTesting] = useState(false);

  const runTests = async () => {
    setTesting(true);
    setBotTest({ status: "running", detail: texts.checkingBotToken });
    setGroupTest({ status: "idle", detail: "" });
    setPermTest({ status: "idle", detail: "" });

    // Test 1: Bot token
    let botInfo: BotInfo;
    try {
      botInfo = await invoke<BotInfo>("test_bot_token", { token });
      setBotTest({
        status: "pass",
        detail: texts.botIdentity(botInfo.username, botInfo.first_name),
      });
    } catch (e) {
      setBotTest({ status: "fail", detail: String(e) });
      setTesting(false);
      return;
    }

    // Test 2: Group access
    setGroupTest({ status: "running", detail: texts.checkingGroupAccess });
    try {
      const groupInfo = await invoke<GroupInfo>("test_group_access", { token, chatId });
      const forumBadge = groupInfo.is_forum
        ? `[${texts.topicsEnabled}]`
        : `[${texts.topicsDisabled}]`;
      setGroupTest({
        status: "pass",
        detail: texts.groupIdentity(groupInfo.title, groupInfo.chat_type, forumBadge),
      });
    } catch (e) {
      setGroupTest({ status: "fail", detail: String(e) });
      setTesting(false);
      return;
    }

    // Test 3: Bot permissions
    setPermTest({ status: "running", detail: texts.checkingBotPermissions });
    try {
      const permInfo = await invoke<PermissionInfo>("test_bot_permissions", { token, chatId });
      const perms = [];
      if (permInfo.status === "administrator") perms.push(texts.admin);
      if (permInfo.can_manage_topics) perms.push(texts.manageTopics);
      if (permInfo.can_delete_messages) perms.push(texts.deleteMessages);
      if (permInfo.can_pin_messages) perms.push(texts.pinMessages);

      const isAdmin = permInfo.status === "administrator";
      const hasTopics = permInfo.can_manage_topics;

      if (isAdmin && hasTopics) {
        setPermTest({ status: "pass", detail: perms.join(", ") });
      } else {
        const missing = [];
        if (!isAdmin) missing.push(texts.notAdmin);
        if (!hasTopics) missing.push(texts.cannotManageTopics);
        setPermTest({
          status: "fail",
          detail: texts.missingSummary(
            missing.join(", "),
            perms.join(", ") || texts.none
          ),
        });
      }
    } catch (e) {
      setPermTest({ status: "fail", detail: String(e) });
    }

    setTesting(false);
  };

  const canTest = token.trim().length > 0 && chatId.trim().length > 0;
  const allPassed = botTest.status === "pass" && groupTest.status === "pass" && permTest.status === "pass";

  const tests = [
    { label: texts.botTokenLabel, result: botTest },
    { label: texts.groupAccessLabel, result: groupTest },
    { label: texts.botPermissionsLabel, result: permTest },
  ];

  const statusIcon = (s: TestStatus) => {
    switch (s) {
      case "idle": return <span className="w-3 h-3 rounded-full bg-gray-200 inline-block" />;
      case "running": return <span className="w-3 h-3 rounded-full bg-blue-400 animate-pulse inline-block" />;
      case "pass": return <span className="text-green-500">✓</span>;
      case "fail": return <span className="text-red-500">✗</span>;
    }
  };

  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      {/* Header + button */}
      <div className="flex items-center justify-between">
        <span className={`font-medium ${compact ? "text-xs text-gray-600" : "text-sm text-gray-700"}`}>
          {texts.title}
        </span>
        <button
          onClick={runTests}
          disabled={!canTest || testing}
          className={`text-sm px-3 py-1.5 rounded-lg transition-colors ${
            allPassed
              ? "bg-green-100 text-green-700 hover:bg-green-200"
              : "bg-blue-600 text-white hover:bg-blue-700"
          } disabled:opacity-40`}
        >
          {testing ? texts.testing : allPassed ? texts.allPassed : texts.runTests}
        </button>
      </div>

      {/* Results */}
      {(botTest.status !== "idle" || groupTest.status !== "idle" || permTest.status !== "idle") && (
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 overflow-hidden">
          {tests.map(({ label, result }) => (
            result.status !== "idle" && (
              <div key={label} className="flex items-center px-3 py-2 gap-2">
                <span className="flex-shrink-0 w-4 text-center">{statusIcon(result.status)}</span>
                <span className={`font-medium flex-shrink-0 ${compact ? "text-xs w-28" : "text-sm w-32"} text-gray-700`}>
                  {label}
                </span>
                <span className="text-xs text-gray-500 truncate flex-1" title={result.detail}>
                  {result.detail}
                </span>
              </div>
            )
          ))}
        </div>
      )}

      {/* Hint when cannot test */}
      {!canTest && botTest.status === "idle" && (
        <p className="text-xs text-gray-400">
          {texts.fillRequiredFields}
        </p>
      )}
    </div>
  );
}
