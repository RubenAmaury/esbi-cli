import { chmodSync, mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

export const FAKE_SB = resolve(__dirname, 'fixtures', 'fake-sb');

export function scratchDir(): string {
	return mkdtempSync(join(tmpdir(), 'esbi-plugin-test-'));
}

/** The fixture must be executable even if a checkout lost the mode bit. */
export function ensureFakeSbExecutable(): void {
	chmodSync(FAKE_SB, 0o755);
}

/** The arguments fake-sb received (it writes them NUL-separated). */
export function readArgv(file: string): string[] {
	const text = readFileSync(file, 'utf8');
	const parts = text.split('\0');
	parts.pop();
	return parts;
}
