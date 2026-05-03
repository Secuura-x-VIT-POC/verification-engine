const API_BASE_URL =
	import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const AUTH_STORAGE_KEY = "secuura-auth";

export function loadStoredAuth() {
	const rawValue = window.localStorage.getItem(AUTH_STORAGE_KEY);
	if (!rawValue) {
		return null;
	}

	try {
		return JSON.parse(rawValue);
	} catch {
		window.localStorage.removeItem(AUTH_STORAGE_KEY);
		return null;
	}
}

export function storeAuth(auth) {
	window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
}

export function clearStoredAuth() {
	window.localStorage.removeItem(AUTH_STORAGE_KEY);
}

export async function apiRequest(path, options = {}) {
	const { token, body, headers, ...rest } = options;
	const requestHeaders = new Headers(headers || {});

	if (token) {
		requestHeaders.set("Authorization", `Bearer ${token}`);
	}

	const isFormData = body instanceof FormData;
	if (body && !isFormData) {
		requestHeaders.set("Content-Type", "application/json");
	}

	const response = await fetch(`${API_BASE_URL}${path}`, {
		...rest,
		headers: requestHeaders,
		body: body ? (isFormData ? body : JSON.stringify(body)) : undefined,
	});

	if (response.status === 410) {
		console.warn("Deprecated API removed:", path);
		return null;
	}

	if (!response.ok) {
		let message = `Request failed with status ${response.status}`;
		let payload = null;
		try {
			payload = await response.json();
			message = payload.detail || payload.message || message;
		} catch {
			// Keep the default fallback.
		}
		const error = new Error(message);
		error.status = response.status;
		error.payload = payload;
		throw error;
	}

	const contentType = response.headers.get("content-type") || "";
	if (contentType.includes("application/json")) {
		return response.json();
	}

	return response.blob();
}
