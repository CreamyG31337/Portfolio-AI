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
        // Create a unique key for the cache
        // We assume options keys are consistent.
        // For this specific application usage, the options objects are created with consistent property order.
        const key = `${locale}:${JSON.stringify(options)}`;

        let formatter = this.cache.get(key);
        if (!formatter) {
            // console.debug(`[FormatterCache] Creating new formatter for key: ${key}`);
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
