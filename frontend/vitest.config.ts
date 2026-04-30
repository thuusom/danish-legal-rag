import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		// Resolve to Svelte's browser/client build so component tests can
		// `mount(...)` against jsdom — the default `node` condition picks
		// the server build which throws `lifecycle_function_unavailable`.
		conditions: ['browser']
	},
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'jsdom',
		// Provide stubs for SvelteKit modules in unit tests
		alias: {
			$lib: '/src/lib'
		},
		coverage: {
			provider: 'v8',
			reporter: ['text', 'html', 'lcov'],
			reportsDirectory: 'coverage',
			include: ['src/**/*.{ts,svelte}'],
			exclude: [
				'**/*.test.ts',
				'**/*.spec.ts',
				'src/lib/api/schema.d.ts',
				'src/app.d.ts',
				'src/app.html',
				'.svelte-kit/**',
				'build/**',
				'dist/**',
				'node_modules/**'
			]
		}
	}
});
