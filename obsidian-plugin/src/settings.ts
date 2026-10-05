/** Never poll faster than this: each `sb status` starts a Python process. */
export const MIN_REFRESH_SECONDS = 30;
export const DEFAULT_REFRESH_SECONDS = 60;
const MAX_REFRESH_SECONDS = 3600;

export interface PluginSettings {
	/** Absolute path to sb. Per device: it is not the same on every Mac. */
	sbPath: string;
	/** Optional config.toml. Per device. */
	configPath: string;
	/** Status bar refresh. Portable, synced with the vault. */
	statusRefreshSeconds: number;
}

export const DEFAULT_SETTINGS: PluginSettings = {
	sbPath: '',
	configPath: '',
	statusRefreshSeconds: DEFAULT_REFRESH_SECONDS,
};

/** What the plugin needs from Obsidian to persist settings. */
export interface Stores {
	loadData: () => Promise<unknown>;
	saveData: (data: unknown) => Promise<void>;
	/** Per vault and per device, never synced (app.loadLocalStorage). */
	loadLocal: (key: string) => unknown;
	saveLocal: (key: string, value: string) => void;
}

const SB_PATH_KEY = 'esbi-sb-path';
const CONFIG_PATH_KEY = 'esbi-config-path';

export function clampRefresh(value: unknown): number {
	const n = typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : DEFAULT_REFRESH_SECONDS;
	return Math.min(MAX_REFRESH_SECONDS, Math.max(MIN_REFRESH_SECONDS, n));
}

export async function loadSettings(stores: Stores): Promise<PluginSettings> {
	const data = await stores.loadData();
	const synced = typeof data === 'object' && data !== null ? (data as Record<string, unknown>) : {};
	const local = (key: string): string => {
		const v = stores.loadLocal(key);
		return typeof v === 'string' ? v : '';
	};
	return {
		sbPath: local(SB_PATH_KEY),
		configPath: local(CONFIG_PATH_KEY),
		statusRefreshSeconds: clampRefresh(synced.statusRefreshSeconds),
	};
}

export async function saveSettings(stores: Stores, s: PluginSettings): Promise<void> {
	stores.saveLocal(SB_PATH_KEY, s.sbPath);
	stores.saveLocal(CONFIG_PATH_KEY, s.configPath);
	// data.json travels with the vault: only portable values go there
	await stores.saveData({ statusRefreshSeconds: clampRefresh(s.statusRefreshSeconds) });
}
