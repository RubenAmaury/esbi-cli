import { chmodSync, symlinkSync } from 'node:fs';
import { join } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';
import { detectSb, loginShellFinder, pickPath, probePaths, type Finder } from '../src/locate';
import { ensureFakeSbExecutable, FAKE_SB, scratchDir } from './helpers';

beforeAll(ensureFakeSbExecutable);

const finder = (lookup: string | null, executable: string[]): Finder => ({
	lookup: () => Promise.resolve(lookup),
	isExecutable: (p) => Promise.resolve(executable.includes(p)),
});

describe('pickPath', () => {
	it('takes the last absolute line and ignores profile noise', () => {
		expect(pickPath(['Welcome', '/Users/me/.local/bin/sb'])).toBe('/Users/me/.local/bin/sb');
		expect(pickPath(['sb: aliased to something', 'not a path'])).toBeNull();
		expect(pickPath([])).toBeNull();
	});
});

describe('detectSb', () => {
	it('prefers what the login shell finds', async () => {
		const home = '/Users/me';
		const found = await detectSb(home, finder('/custom/sb', ['/custom/sb', ...probePaths(home)]));
		expect(found).toBe('/custom/sb');
	});

	it('falls back to the usual install folders in order', async () => {
		const home = '/Users/me';
		expect(await detectSb(home, finder(null, ['/opt/homebrew/bin/sb', '/usr/local/bin/sb']))).toBe('/opt/homebrew/bin/sb');
		expect(await detectSb(home, finder(null, ['/usr/local/bin/sb']))).toBe('/usr/local/bin/sb');
		expect(await detectSb(home, finder(null, [`${home}/.local/bin/sb`, '/usr/local/bin/sb']))).toBe(`${home}/.local/bin/sb`);
	});

	it('ignores a shell answer that is not executable', async () => {
		expect(await detectSb('/h', finder('/gone/sb', ['/usr/local/bin/sb']))).toBe('/usr/local/bin/sb');
	});

	it('returns null when sb is nowhere', async () => {
		expect(await detectSb('/h', finder(null, []))).toBeNull();
	});
});

describe('loginShellFinder (real login shell)', () => {
	it('finds an sb that is on PATH', async () => {
		const dir = scratchDir();
		symlinkSync(FAKE_SB, join(dir, 'sb'));
		chmodSync(FAKE_SB, 0o755);
		// an empty HOME/ZDOTDIR keeps this machine's own shell profile out of the test
		const f = loginShellFinder({ PATH: `${dir}:${process.env.PATH ?? ""}`, HOME: dir, ZDOTDIR: dir });
		expect(await f.lookup()).toBe(join(dir, 'sb'));
		expect(await f.isExecutable(join(dir, 'sb'))).toBe(true);
		expect(await f.isExecutable(join(dir, 'nope'))).toBe(false);
	});
});
