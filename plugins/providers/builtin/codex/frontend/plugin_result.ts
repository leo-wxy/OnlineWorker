export function pluginResult(value: Record<string, unknown>, fallback = "账号操作失败") {
  if (value.ok === false) {
    const error = value.error as { message?: string } | undefined;
    throw new Error(error?.message || fallback);
  }
  return value;
}
