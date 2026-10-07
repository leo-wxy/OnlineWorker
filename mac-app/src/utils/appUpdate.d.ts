export interface AppUpdateInfo {
  revision: number;
  currentVersion: string;
  latestVersion: string;
  updateAvailable: boolean;
  phase: "idle" | "checking" | "current" | "available" | "downloading" | "ready" | "installing";
  downloadedBytes: number;
  totalBytes: number | null;
  notes: string;
}
export function mergeAppUpdateStatus(current: AppUpdateInfo | null, next: AppUpdateInfo): AppUpdateInfo;
export function appUpdateBusy(info: AppUpdateInfo | null): boolean;
export function appUpdateProgress(info: AppUpdateInfo | null): number | null;
