/**
 * Formatter Cache to prevent expensive Intl.NumberFormat instantiations
 */

export class FormatterCache {
    private static cache = new Map<string, Intl.NumberFormat>();

    /**
     * Get a cached Intl.NumberFormat instance
     * @param locale The locale string (e.g., 'en-US')
     * @param options The Intl.NumberFormatOptions object
     * @returns A cached Intl.NumberFormat instance
     */
    static get(locale: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
        // Normalize options by sorting keys for consistent cache keys
        // This ensures that objects with the same properties but different order
        // will still hit the same cache entry
        const normalizedOptions = Object.keys(options)
            .sort()
            .reduce((acc, key) => {
                const typedKey = key as keyof Intl.NumberFormatOptions;
                acc[typedKey] = options[typedKey];
                return acc;
            }, {} as Record<string, any>) as Intl.NumberFormatOptions;
        
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
    static clear(): void {
        this.cache.clear();
    }
}
