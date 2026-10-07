export function mergeAppUpdateStatus(current, next) {
  return current && current.revision > next.revision ? current : next;
}

export function appUpdateBusy(info) {
  return ["checking", "downloading", "installing"].includes(info?.phase);
}

export function appUpdateProgress(info) {
  return info?.totalBytes > 0
    ? Math.min(100, Math.round(info.downloadedBytes / info.totalBytes * 100)) : null;
}
