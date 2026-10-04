import { access, constants } from 'fs/promises';
import { loginShell, startSb } from './spawn';

/** Where Homebrew and uv put `sb`, in the order we look. */
export function probePaths(home: string): string[] {
	return [`${home}/.local/bin/sb`, '/opt/homebrew/bin/sb', '/usr/local/bin/sb'];
}

/** The absolute path a shell printed for `command -v sb`: the last absolute line, ignoring profile noise. */
export function pickPath(lines: string[]): string | null {
	for (let i = lines.length - 1; i >= 0; i--) {
		const line = (lines[i] ?? '').trim();
		if (line.startsWith('/')) return line;
	}
	return null;
}

export interface Finder {
	/** Ask the user's login shell where `sb` is. */
	lookup: () => Promise<string | null>;
	isExecutable: (path: string) => Promise<boolean>;
}

export function loginShellFinder(env?: Record<string, string>): Finder {
	return {
		lookup: async () => {
			const r = await startSb({
				sbPath: 'sb', // becomes $0 of the one-line script and is ignored by it
				args: [],
				env,
				shell: { file: loginShell().file, args: ['-lc', 'command -v sb'] },
				timeoutMs: 8000,
			}).result;
			return r.code === 0 ? pickPath(r.stdoutLines) : null;
		},
		isExecutable: (p) =>
			access(p, constants.X_OK).then(
				() => true,
				() => false,
			),
	};
}

/** Auto-detect sb: the login shell first (it sees the user's PATH), then the usual install folders. */
export async function detectSb(home: string, finder: Finder = loginShellFinder()): Promise<string | null> {
	const viaShell = await finder.lookup();
	if (viaShell && (await finder.isExecutable(viaShell))) return viaShell;
	for (const candidate of probePaths(home)) {
		if (await finder.isExecutable(candidate)) return candidate;
	}
	return null;
}
