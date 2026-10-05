/** Splits a text stream into complete lines. Holds a partial line until its newline arrives. */
export class LineSplitter {
	private rest = '';

	push(chunk: string): string[] {
		this.rest += chunk;
		const parts = this.rest.split('\n');
		this.rest = parts.pop() ?? '';
		return parts.map((l) => l.replace(/\r$/, '')).filter((l) => l.trim() !== '');
	}

	flush(): string[] {
		const last = this.rest.replace(/\r$/, '');
		this.rest = '';
		return last.trim() === '' ? [] : [last];
	}
}

export type JsonObject = Record<string, unknown>;

/** One line as a JSON object, or null for anything else (never throws). */
export function parseObject(line: string): JsonObject | null {
	try {
		const value: unknown = JSON.parse(line);
		if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
			return value as JsonObject;
		}
	} catch {
		// not JSON: a banner printed by the user's shell profile, or a partial line
	}
	return null;
}

/** The last line that is a JSON object; a login shell may print noise before the real answer. */
export function lastObject(lines: string[]): JsonObject | null {
	for (let i = lines.length - 1; i >= 0; i--) {
		const obj = parseObject(lines[i] ?? '');
		if (obj) return obj;
	}
	return null;
}
