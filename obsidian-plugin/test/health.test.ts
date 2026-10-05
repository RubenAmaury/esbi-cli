import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { SbError } from '../src/contract';
import { INSTALL_BREW, INSTALL_UV, checkHealth, explain } from '../src/health';
import { SbClient } from '../src/sb';
import { ensureFakeSbExecutable, FAKE_SB } from './helpers';

beforeAll(ensureFakeSbExecutable);
afterEach(() => vi.unstubAllEnvs());

const client = (sbPath = FAKE_SB) => new SbClient(() => ({ sbPath, configPath: '' }));

describe('checkHealth with the fake sb', () => {
	it('is ok for contract 1 and reports the version', async () => {
		expect(await checkHealth(client())).toEqual({ ok: true, version: '0.3.0', contract: 1 });
	});

	it('refuses a newer contract with one clear message and no crash', async () => {
		vi.stubEnv('FAKE_SB_CONTRACT', '2');
		const h = await checkHealth(client());
		expect(h.ok).toBe(false);
		if (!h.ok) {
			expect(h.error.kind).toBe('too_new');
			expect(explain(h.error).title).toMatch(/newer than this plugin/);
			expect(explain(h.error).steps.join(' ')).toMatch(/Update the plugin/);
		}
	});

	it('explains a missing sb with both install commands and the site', async () => {
		const h = await checkHealth(client('/nonexistent/dir/sb'));
		expect(h.ok).toBe(false);
		if (!h.ok) {
			const x = explain(h.error);
			expect(x.commands).toEqual([INSTALL_BREW, INSTALL_UV]);
			expect(x.steps.join(' ')).toContain('https://rubenamaury.github.io/esbi-cli/');
		}
	});

	it('explains an sb without --json by telling the user to update esbi-cli', async () => {
		vi.stubEnv('FAKE_SB_OLD', '1');
		const h = await checkHealth(client());
		expect(h.ok).toBe(false);
		if (!h.ok) expect(explain(h.error).commands).toEqual(['sb update']);
	});
});

describe('checkHealth with a stub client', () => {
	it('never throws, even for an unexpected exception', async () => {
		const h = await checkHealth({ version: () => Promise.reject(new TypeError('weird')) });
		expect(h).toMatchObject({ ok: false, error: { kind: 'bad_output', message: 'weird' } });
	});

	it('refuses a newer contract even when the client did not', async () => {
		const h = await checkHealth({ version: () => Promise.resolve({ version: '9.0.0', contract: 3 }) });
		expect(h.ok).toBe(false);
	});

	it('gives every error kind a title', () => {
		for (const kind of ['missing', 'old', 'too_new', 'failed', 'bad_output', 'timeout', 'spawn'] as const) {
			expect(explain(new SbError(kind, 'vault not found')).title.length).toBeGreaterThan(5);
		}
	});
});
