const alphabet = "0123456789bcdefghjkmnpqrstuvwxyz";

/** Returns the south-west and north-east corners of a standard geohash cell. */
export function geohashBounds(
  hash: string,
): [[number, number], [number, number]] {
  const latitude: [number, number] = [-90, 90];
  const longitude: [number, number] = [-180, 180];
  let even = true;
  for (const char of hash.toLowerCase()) {
    const value = alphabet.indexOf(char);
    if (value < 0) throw new Error(`Invalid geohash: ${hash}`);
    for (let mask = 16; mask >= 1; mask >>= 1) {
      const range = even ? longitude : latitude,
        mid = (range[0] + range[1]) / 2;
      if (value & mask) range[0] = mid;
      else range[1] = mid;
      even = !even;
    }
  }
  return [
    [latitude[0], longitude[0]],
    [latitude[1], longitude[1]],
  ];
}
