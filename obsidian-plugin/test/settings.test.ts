import { describe, expect, it } from 'vitest';
import { MIN_REFRESH_SECONDS, clampRefresh, loadSettings, saveSettings, type Stores } from '../src/settings';

function fakeStores(initialData: unknown = null) {
	let data: unknown = initialData;
	const local = new Map<string, unknown>();
	const stores: Stores = {
		loadData: () => Promise.resolve(data),
		saveData: (d) => {
			data = d;
			return Promise.resolve();
		},
		loadLocal: (k) => local.get(k) ?? null,
		saveLocal: (k, v) => void local.set(k, v),
	};
	return { stores, getData: () => data, local };
}

describe('settings persistence', () => {
	it('starts with defaults when nothing was saved', async () => {
		const { stores } = fakeStores();
		expect(await loadSettings(stores)).toEqual({ sbPath: '', configPath: '', statusRefreshSeconds: 60 });
	});

	it('round-trips every value', async () => {
		const { stores } = fakeStores();
		await saveSettings(stores, { sbPath: '/u/.local/bin/sb', configPath: '/c.toml', statusRefreshSeconds: 120 });
		expect(await loadSettings(stores)).toEqual({ sbPath: '/u/.local/bin/sb', configPath: '/c.toml', statusRefreshSeconds: 120 });
	});

	it('keeps machine-specific paths out of data.json, which syncs with the vault', async () => {
		const { stores, getData, local } = fakeStores();
		await saveSettings(stores, { sbPath: '/u/.local/bin/sb', configPath: '/c.toml', statusRefreshSeconds: 90 });
		expect(getData()).toEqual({ statusRefreshSeconds: 90 });
		expect(JSON.stringify(getData())).not.toContain('/u/.local');
		expect(local.get('esbi-sb-path')).toBe('/u/.local/bin/sb');
	});

	it('never lets the refresh interval go below 30 seconds, whatever the file says', async () => {
		expect(MIN_REFRESH_SECONDS).toBe(30);
		expect(clampRefresh(1)).toBe(30);
		expect(clampRefresh(-5)).toBe(30);
		expect(clampRefresh(29.6)).toBe(30);
		expect(clampRefresh(10_000_000)).toBe(3600);
		expect(clampRefresh('5')).toBe(60);
		expect(clampRefresh(NaN)).toBe(60);
		const { stores } = fakeStores({ statusRefreshSeconds: 2 });
		expect((await loadSettings(stores)).statusRefreshSeconds).toBe(30);
	});

	it('survives a corrupt data.json and non-string local values', async () => {
		const { stores, local } = fakeStores('garbage');
		local.set('esbi-sb-path', 42);
		expect(await loadSettings(stores)).toEqual({ sbPath: '', configPath: '', statusRefreshSeconds: 60 });
	});
});
