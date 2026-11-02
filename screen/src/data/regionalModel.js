function cleanText(value, maxLength = 180) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLength);
}

/** Normalize a Nominatim reverse-geocode response into compact place context. */
export function normalizeRegionalPlace(payload) {
  const address = payload?.address || {};
  const locality = cleanText(
    address.city ||
      address.town ||
      address.village ||
      address.municipality ||
      address.hamlet ||
      address.county,
    90,
  );
  const region = cleanText(
    address.state || address.region || address.county,
    90,
  );
  const country = cleanText(address.country, 90);
  const label =
    [locality, region]
      .filter(
        (value, index, values) => value && values.indexOf(value) === index,
      )
      .join(', ') ||
    country ||
    cleanText(payload?.display_name, 120);
  if (!label) return null;
  return {
    label,
    locality: locality || null,
    region: region || null,
    country: country || null,
    countryCode: cleanText(address.country_code, 4).toUpperCase() || null,
  };
}
