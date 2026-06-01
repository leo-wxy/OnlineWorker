import { useI18n } from "../../i18n";
import type { ConnectionStatus } from "../../types";
import { getTelegramStyles } from "./model";

export function TelegramBadge({ status }: { status: ConnectionStatus }) {
  const { t } = useI18n();
  const style = getTelegramStyles(t)[status];
  return (
    <span className={`ow-badge rounded-full px-2.5 py-1 text-[10px] ${style.badge}`}>
      {style.label}
    </span>
  );
}
