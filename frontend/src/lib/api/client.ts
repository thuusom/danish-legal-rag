import createClient from 'openapi-fetch';
import type { paths } from './schema';

// Base URL defaults to the server-side proxy at /api (same origin).
// Override with VITE_API_BASE_URL for bare-metal dev without the proxy.
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? '/api';

export const client = createClient<paths>({ baseUrl });
