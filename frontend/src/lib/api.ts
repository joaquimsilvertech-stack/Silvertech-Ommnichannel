import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export type AuthTokens = {
  access: string;
  refresh: string;
};

export type Workspace = {
  id: string | number;
  name?: string;
  slug?: string;
};

export type Contact = {
  id: string | number;
  name?: string;
  full_name?: string;
  phone?: string;
  email?: string;
  channel_id?: string;
  starred?: boolean;
};

export type Conversation = {
  id: string | number;
  status?: string;
  channel?: string;
  channel_name?: string;
  contact?: Contact | string | number;
  contact_data?: Contact;
  updated_at?: string;
};

export type Lead = {
  id: string | number;
  contact?: string | number;
  contact_name?: string;
  status?: string;
  score?: number;
  source?: string;
  notes?: string;
};

export type Organization = {
  id: string | number;
  name?: string;
  workspace?: Workspace;
  contacts?: Contact[];
};

export type Member = {
  id: string | number;
  user?: { id: string | number; email?: string };
  workspace?: Workspace;
  role?: string;
};

export type WorkspaceInvite = {
  id: string | number;
  email?: string;
  workspace?: Workspace;
  role?: string;
  accepted?: boolean;
  expires_at?: string;
};

export const tokenStore = {
  getAccess() {
    return localStorage.getItem("silvertech.access");
  },
  getRefresh() {
    return localStorage.getItem("silvertech.refresh");
  },
  set(tokens: AuthTokens) {
    localStorage.setItem("silvertech.access", tokens.access);
    localStorage.setItem("silvertech.refresh", tokens.refresh);
  },
  clear() {
    localStorage.removeItem("silvertech.access");
    localStorage.removeItem("silvertech.refresh");
  }
};

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json"
  }
});

api.interceptors.request.use((config) => {
  const access = tokenStore.getAccess();
  if (access) {
    config.headers.Authorization = `Bearer ${access}`;
  }
  return config;
});

export async function login(username: string, password: string) {
  const { data } = await api.post<AuthTokens>("/api/auth/token/", {
    username,
    password
  });
  tokenStore.set(data);
  return data;
}

function unwrapList<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object" && "results" in payload) {
    const results = (payload as { results?: unknown }).results;
    return Array.isArray(results) ? (results as T[]) : [];
  }
  return [];
}

export async function getWorkspaces() {
  const { data } = await api.get("/api/workspaces/workspaces/");
  return unwrapList<Workspace>(data);
}

export async function getContacts() {
  const { data } = await api.get("/api/crm/contacts/");
  return unwrapList<Contact>(data);
}

export async function getConversations() {
  const { data } = await api.get("/api/omnichannel/conversations/");
  return unwrapList<Conversation>(data);
}

export async function getLeads() {
  const { data } = await api.get("/api/crm/leads/");
  return unwrapList<Lead>(data);
}

export async function getOrganizations() {
  const { data } = await api.get("/api/crm/organizations/");
  return unwrapList<Organization>(data);
}

export async function getMembers() {
  const { data } = await api.get("/api/workspaces/members/");
  return unwrapList<Member>(data);
}

export async function getInvites() {
  const { data } = await api.get("/api/workspaces/invites/");
  return unwrapList<WorkspaceInvite>(data);
}
