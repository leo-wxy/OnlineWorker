export interface SingleFlightByKey<Key = string> {
  run<Result>(key: Key, operation: () => Promise<Result> | Result): Promise<Result>;
}

export function createSingleFlightByKey<Key = string>(): SingleFlightByKey<Key>;
