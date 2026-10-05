/** An http(s) URL without credentials, or null. Whitespace is rejected so a sentence is never taken for a link. */
export function parseWebUrl(text: string): string | null {
	const s = text.trim();
	if (s === '' || /\s/.test(s)) return null;
	try {
		const u = new URL(s);
		if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
		if (u.username !== '' || u.password !== '') return null; // a link with a login in it must not land in a wiki
		return u.href;
	} catch {
		return null;
	}
}

/** The URL in a selection that is a bare URL, `<url>` or a Markdown link `[text](url)`. */
export function urlFromSelection(selection: string): string | null {
	const s = selection.trim();
	const md = /^\[[^\]]*\]\((\S+?)(?:\s+"[^"]*")?\)$/.exec(s);
	const angle = /^<(\S+)>$/.exec(s);
	return parseWebUrl(md?.[1] ?? angle?.[1] ?? s);
}

export type Target = { url: string } | { problem: string };

/**
 * What to queue: the selected link if there is a selection, otherwise the note's `source` property.
 * Only the URL leaves the note, never its text.
 */
export function pickTarget(input: { selection: string; source: unknown }): Target {
	if (input.selection.trim() !== '') {
		const url = urlFromSelection(input.selection);
		return url ? { url } : { problem: 'The selection is not a single web link (http or https).' };
	}
	if (typeof input.source === 'string' && input.source.trim() !== '') {
		const url = parseWebUrl(input.source);
		return url ? { url } : { problem: 'The source of this note is not a web link, so there is nothing to queue.' };
	}
	return { problem: 'Select a link, or open a note that has a source property with a web link.' };
}

/** `wiki/daily/YYYY-MM-DD.md` for the local calendar day. */
export function dailyIndexPath(d: Date): string {
	const p = (n: number): string => String(n).padStart(2, '0');
	return `wiki/daily/${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}.md`;
}
