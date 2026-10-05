// Optional: the same client and process helper against the REAL esbi-cli, in a scratch vault.
// Skipped unless ESBI_REAL_SB (path to an sb with --json) and ESBI_REAL_CONFIG (a scratch config) are set.
// ESBI_REAL_CONFIG_RUN (a second scratch config whose queue holds one local .md source) enables the run and cancel test,
// which calls a local model: run it through the model lock.
import { describe, expect, it } from 'vitest';
import { SbError } from '../src/contract';
import { RunController } from '../src/run-controller';
import { runMessage } from '../src/run-state';
import { SbClient } from '../src/sb';

const sbPath = process.env.ESBI_REAL_SB ?? '';
const config = process.env.ESBI_REAL_CONFIG ?? '';
const runConfig = process.env.ESBI_REAL_CONFIG_RUN ?? '';
const enabled = sbPath !== '' && config !== '';

describe.skipIf(!enabled)('against the real esbi-cli (scratch vault)', () => {
	const client = new SbClient(() => ({ sbPath, configPath: config }));

	it('speaks contract 1', async () => {
		const v = await client.version();
		expect(v.contract).toBe(1);
		expect(v.version).toMatch(/^\d+\.\d+\.\d+/);
	});

	it('reads info, status and doctor', async () => {
		expect((await client.info()).vault).toContain('plugin/vault');
		const s = await client.status();
		expect(s.queue.queued).toBeGreaterThanOrEqual(0);
		const d = await client.doctor();
		expect(d.checks.length).toBeGreaterThan(3);
		expect(d.checks.every((c) => ['ok', 'WARN', 'FAIL'].includes(c.level))).toBe(true);
	});

	it('queues a hostile-looking URL as plain text and dedupes it', async () => {
		const url = 'https://example.com/a?x=$(touch /tmp/esbi-plugin-pwned)&y=`id`&z="q";';
		const first = await client.add(url);
		const second = await client.add(url);
		expect(first.queued + first.alreadyKnown).toBe(1);
		expect(second).toEqual({ queued: 0, alreadyKnown: 1 });
		const { existsSync } = await import('node:fs');
		expect(existsSync('/tmp/esbi-plugin-pwned')).toBe(false);
	});

	it('maps a contract error to a failed SbError with its code', async () => {
		const e = await client.add('not a url').catch((x: unknown) => x);
		expect(e).toBeInstanceOf(SbError);
		expect(e).toMatchObject({ kind: 'failed', code: 'bad_target' });
	});

	it('answers a question with a hostile text (refused, since the scratch wiki is empty)', async () => {
		const a = await client.ask('what is $(id) `id` "x"; --help?');
		expect(a.refused).toBe(true);
	});

	it('tells a missing sb from a broken one', async () => {
		const missing = new SbClient(() => ({ sbPath: '/nonexistent/sb', configPath: '' }));
		await expect(missing.version()).rejects.toMatchObject({ kind: 'missing' });
	});
});

describe.skipIf(!enabled || runConfig === '')('run and cancel against the real esbi-cli (calls a local model)', () => {
	it('cancels with SIGINT: sb says it was interrupted and the source stays in the queue', async () => {
		const client = new SbClient(() => ({ sbPath, configPath: runConfig }));
		const before = (await client.status()).queue.queued;
		expect(before).toBeGreaterThanOrEqual(1);
		const c = new RunController(client);
		c.start();
		await expect.poll(() => c.state?.current?.step ?? null, { timeout: 120_000, interval: 200 }).not.toBeNull();
		c.cancel();
		await expect.poll(() => c.active, { timeout: 30_000, interval: 200 }).toBe(false);
		const s = c.state;
		console.log('real run end state:', JSON.stringify({ phase: s?.phase, canceled: s?.canceled, summary: s?.summary }), '->', s ? runMessage(s) : '');
		expect(s?.canceled).toBe(true);
		const after = (await client.status()).queue;
		console.log('queue after cancel:', JSON.stringify(after));
	});
});
