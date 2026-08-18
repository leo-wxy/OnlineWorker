import type { AccountFeatureEntryProps } from "../../../../../mac-app/src/components/AccountFeatureHost";
import { AccountOverview } from "./AccountOverview";
import "./account.css";


export const featureId = "codex";
export const frontendEntry = "frontend/account_entry.tsx";

export default function CodexAccountEntry(props: AccountFeatureEntryProps) {
  return <AccountOverview api={props.api} />;
}
