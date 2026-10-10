/**
 * Formatter Cache to prevent expensive Intl.NumberFormat instantiations
 */
export class FormatterCache {
    /**
     * Get a cached Intl.NumberFormat instance
     * @param locale The locale string (e.g., 'en-US')
     * @param options The Intl.NumberFormatOptions object
     * @returns A cached Intl.NumberFormat instance
     */
    static get(locale, options) {
        // Normalize options by sorting keys for consistent cache keys
        // This ensures that objects with the same properties but different order
        // will still hit the same cache entry
        const normalizedOptions = Object.keys(options)
            .sort()
            .reduce((acc, key) => {
            const typedKey = key;
            acc[typedKey] = options[typedKey];
            return acc;
        }, {});
        const key = `${locale}:${JSON.stringify(normalizedOptions)}`;
        let formatter = this.cache.get(key);
        if (!formatter) {
            formatter = new Intl.NumberFormat(locale, options);
            this.cache.set(key, formatter);
        }
        return formatter;
    }
    /**
     * Clear the cache
     */
    static clear() {
        this.cache.clear();
    }
}
FormatterCache.cache = new Map();
//# sourceMappingURL=formatters.js.map