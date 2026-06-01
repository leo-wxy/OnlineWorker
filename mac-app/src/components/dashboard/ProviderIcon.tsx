import type { ProviderDashboardStatus } from "../../types";

export function ProviderIcon({ provider }: { provider: ProviderDashboardStatus }) {
  const iconUrl = provider.icon?.url?.trim();
  if (iconUrl) {
    return <img src={iconUrl} alt="" aria-hidden="true" className="h-5 w-5 object-contain" />;
  }

  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M13 10V3L4 14h7v7l9-11h-7z"
      ></path>
    </svg>
  );
}
