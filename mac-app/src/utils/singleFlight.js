export function createSingleFlightByKey() {
  const flights = new Map();

  return {
    run(key, operation) {
      const existing = flights.get(key);
      if (existing) {
        return existing;
      }

      let result;
      try {
        result = operation();
      } catch (error) {
        result = Promise.reject(error);
      }

      let flight;
      flight = Promise.resolve(result).finally(() => {
        if (flights.get(key) === flight) {
          flights.delete(key);
        }
      });
      flights.set(key, flight);
      return flight;
    },
  };
}
