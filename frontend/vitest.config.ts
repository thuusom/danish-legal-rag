import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [sveltekit()],
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'jsdom',
		// Provide stubs for SvelteKit modules in unit tests
		alias: {
			'$lib': '/src/lib'
		}
	}
});
