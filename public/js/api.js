// JSON API client. Errors become ApiError with the server's code when it sent one.

export class ApiError extends Error {
  constructor(status, code, message, details = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
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
    // Errors come as {error: {code, message}} (AI) or {detail: {code, ...}} (rule checks).
    const detail = data?.detail && typeof data.detail === "object" && !Array.isArray(data.detail) ? data.detail : {};
    const code = data?.error?.code ?? detail.code ?? (response.status === 404 ? "not_found"
      : response.status === 422 ? "validation" : "generic");
    // FastAPI's own validation errors are a list; keep their messages readable.
    const listed = Array.isArray(data?.detail) ? data.detail.map((d) => d.msg).join("; ") : null;
    throw new ApiError(response.status, code, data?.error?.message ?? detail.message ?? listed ?? response.statusText, detail);
  }
  return data;
}

export const api = {
  aiStatus: () => request("GET", "/api/ai/status"),
  listProjects: () => request("GET", "/api/projects"),
  createProject: (data) => request("POST", "/api/projects", data),
  openProject: (id) => request("GET", `/api/projects/${id}`),
  patchProject: (id, data) => request("PATCH", `/api/projects/${id}`, data),
  turn: (id, input) => request("POST", `/api/projects/${id}/turn`, input),
  createStory: (id, data) => request("POST", `/api/projects/${id}/stories`, data),
  patchStory: (id, storyId, data) => request("PATCH", `/api/projects/${id}/stories/${storyId}`, data),
  deleteStory: (id, storyId) => request("DELETE", `/api/projects/${id}/stories/${storyId}`),
  reorderStories: (id, ids, line = {}) => request("PUT", `/api/projects/${id}/stories/order`, { ids, ...line }),
  splitStory: (id, storyId, data) => request("POST", `/api/projects/${id}/stories/${storyId}/split`, data),
  mergeStories: (id, data) => request("POST", `/api/projects/${id}/stories/merge`, data),
  review: (id) => request("POST", `/api/projects/${id}/review`),
  trackerStatus: () => request("GET", "/api/tracker"),
  pushToTracker: (id, storyIds) => request("POST", `/api/projects/${id}/tracker/push`, { story_ids: storyIds }),
  decideFinding: (id, messageId, index, data) => request("POST", `/api/projects/${id}/review/${messageId}/findings/${index}`, data),
  undo: (id) => request("POST", `/api/projects/${id}/undo`),
  templates: () => request("GET", "/api/mockup-templates"),
  projectTemplates: () => request("GET", "/api/templates"),
  saveProjectTemplate: (data) => request("POST", "/api/templates", data),
  deleteProjectTemplate: (key) => request("DELETE", `/api/templates/${key}`),
  checkCriteria: (texts) => request("POST", "/api/criteria/check", { texts }),
  mockupVersions: (id, mockupId) => request("GET", `/api/projects/${id}/mockups/${mockupId}/versions`),
  saveAnnotations: (id, mockupId, annotations) => request("PUT", `/api/projects/${id}/mockups/${mockupId}/annotations`, { annotations }),
  saveMockupVersion: (id, mockupId, tree) => request("POST", `/api/projects/${id}/mockups/${mockupId}/versions`, { tree }),
  restoreVersion: (id, mockupId, number) => request("POST", `/api/projects/${id}/mockups/${mockupId}/versions/${number}/restore`),
  createMockup: (id, data) => request("POST", `/api/projects/${id}/mockups`, data),
  linkMockup: (id, storyId, mockupId) => request("PUT", `/api/projects/${id}/stories/${storyId}/mockups/${mockupId}`),
  unlinkMockup: (id, storyId, mockupId) => request("DELETE", `/api/projects/${id}/stories/${storyId}/mockups/${mockupId}`),
};
