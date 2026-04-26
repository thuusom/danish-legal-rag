import { env } from '$env/dynamic/private';
import type { RequestHandler } from './$types';

const API_URL = env.API_INTERNAL_URL ?? 'http://localhost:8000';

/**
 * Catch-all proxy that forwards requests to the backend API.
 * The browser never talks directly to the backend — all requests go through
 * this SvelteKit server route, keeping the API internal.
 *
 * Streaming responses (SSE) are passed through without buffering.
 */
async function proxy({ request, params }: { request: Request; params: { path: string } }): Promise<Response> {
	const path = params.path;
	const url = new URL(request.url);
	const target = `${API_URL}/${path}${url.search}`;

	// Forward headers but strip Host (backend has its own)
	const headers = new Headers(request.headers);
	headers.delete('host');

	const backendResponse = await fetch(target, {
		method: request.method,
		headers,
		body: request.body,
		// @ts-expect-error -- Node fetch supports duplex for streaming request bodies
		duplex: 'half'
	});

	// Build response headers — forward Content-Type and Cache-Control
	const responseHeaders = new Headers();
	const contentType = backendResponse.headers.get('content-type');
	if (contentType) {
		responseHeaders.set('content-type', contentType);
	}
	const cacheControl = backendResponse.headers.get('cache-control');
	if (cacheControl) {
		responseHeaders.set('cache-control', cacheControl);
	}

	// Pass body through as a stream (critical for SSE — no buffering)
	return new Response(backendResponse.body, {
		status: backendResponse.status,
		headers: responseHeaders
	});
}

export const GET: RequestHandler = proxy;
export const POST: RequestHandler = proxy;
export const PUT: RequestHandler = proxy;
export const DELETE: RequestHandler = proxy;
export const PATCH: RequestHandler = proxy;
