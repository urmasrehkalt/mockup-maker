// JSON API client. Errors become ApiError with the server's code when it sent one.

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const code = data?.error?.code ?? (response.status === 404 ? "not_found"
      : response.status === 422 ? "validation" : "generic");
    throw new ApiError(response.status, code, data?.error?.message ?? response.statusText);
  }
  return data;
}

export const api = {
  aiStatus: () => request("GET", "/api/ai/status"),
  listProjects: () => request("GET", "/api/projects"),
  createProject: (data) => request("POST", "/api/projects", data),
  openProject: (id) => request("GET", `/api/projects/${id}`),
  patchProject: (id, data) => request("PATCH", `/api/projects/${id}`, data),
};
