const DEFAULT_RANGE_DAYS = 7;

function localIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isoDateOffset(daysAgo, baseDate = new Date()) {
  const date = new Date(baseDate);
  date.setDate(date.getDate() - daysAgo);
  return localIsoDate(date);
}

export function buildDefaultUsageQuery(baseDate = new Date()) {
  return {
    startDate: isoDateOffset(DEFAULT_RANGE_DAYS - 1, baseDate),
    endDate: isoDateOffset(0, baseDate),
  };
}
