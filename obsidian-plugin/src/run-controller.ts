import { applyExit, applyLine, initialRun, type RunState } from './run-state';
import type { SbJob } from './spawn';

/** Starts `sb run --json`; a client in this shape is enough for the controller (and for tests). */
export interface Runner {
	run: (onLine: (line: string) => void) => SbJob;
}

/**
 * One run at a time. The run keeps going when the modal that shows it is closed, so the status bar
 * can show progress and a click on it brings the modal back.
 */
export class RunController {
	state: RunState | null = null;
	private job: SbJob | null = null;
	private listeners = new Set<(s: RunState) => void>();

	constructor(
		private readonly client: Runner,
		private readonly onEnd: () => void = () => undefined,
	) {}

	get active(): boolean {
		return this.job !== null;
	}

	subscribe(fn: (s: RunState) => void): () => void {
		this.listeners.add(fn);
		return () => this.listeners.delete(fn);
	}

	private set(s: RunState): void {
		this.state = s;
		this.listeners.forEach((fn) => fn(s));
	}

	/** Returns false when a run is already going (the second click does nothing). */
	start(): boolean {
		if (this.job) return false;
		this.set(initialRun);
		const job = this.client.run((line) => this.set(applyLine(this.state ?? initialRun, line)));
		this.job = job;
		void job.result.then((r) => {
			this.job = null;
			this.set(applyExit(this.state ?? initialRun, r));
			this.onEnd();
		});
		return true;
	}

	cancel(): void {
		this.job?.cancel();
	}
}
