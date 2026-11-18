// The server's API. Every call is to the same origin, with the login cookie; a refused request comes back as an ApiError whose message is fit to show.

export interface Me {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
}

export type Role = "owner" | "crew";

export interface Member {
  user_id: string;
  name: string;
  role: Role;
  share_percent: number | null;
}

export interface MyRequest {
  id: string;
  role: Role;
  share_percent: number | null;
}

export interface Boat {
  id: string;
  name: string;
  home_port: string;
  description: string;
  timezone: string;
  status: "pending" | "approved" | "rejected";
  owner_count: number;
  crew_count: number;
  my_role: Role | null;
  my_request: MyRequest | null;
  members?: Member[];
}

export interface Aboard {
  user_id: string;
  name: string;
}

export interface Trip {
  id: string;
  title: string;
  start: number;
  end: number;
  capacity: number | null;
  notes: string;
  created_by: string;
  created_by_name: string;
  aboard: Aboard[];
  i_am_aboard: boolean;
  can_edit: boolean;
}

export interface TripInput {
  title: string;
  start: number;
  end: number;
  capacity: number | null;
  notes: string;
}

export interface JoinRequest {
  id: string;
  boat_id: string;
  boat_name: string;
  user_id: string;
  user_name: string;
  role: Role;
  share_percent: number | null;
  message: string;
  created_at: number;
}

export interface PendingBoat {
  id: string;
  name: string;
  home_port: string;
  description: string;
  timezone: string;
}

export interface Inbox {
  boats: PendingBoat[];
  requests: JoinRequest[];
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** What to tell the user about an error answer: the server's sentence, or for a form that was filled in wrongly the first thing that is wrong with it. */
export function messageOf(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1] ?? "") : "";
    const text = String(first.msg ?? "that is not valid").replace(/^Value error, /, "");
    return field && !text.toLowerCase().includes(field.replace(/_/g, " ")) ? `${field.replace(/_/g, " ")}: ${text}` : text;
  }
  return status >= 500 ? "something went wrong on our side; please try again" : "that request was refused";
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "could not reach the server; check your connection");
  }
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) throw new ApiError(response.status, messageOf(data, response.status));
  return data as T;
}

export const api = {
  me: () => call<Me>("GET", "/api/auth/me"),
  register: (email: string, name: string, password: string) => call<Me>("POST", "/api/auth/register", { email, name, password }),
  login: (email: string, password: string) => call<Me>("POST", "/api/auth/login", { email, password }),
  logout: () => call<{ ok: boolean }>("POST", "/api/auth/logout"),
  boats: () => call<Boat[]>("GET", "/api/boats"),
  boat: (id: string) => call<Boat>("GET", `/api/boats/${id}`),
  addBoat: (b: { name: string; home_port: string; description: string; timezone: string; share_percent: number }) => call<{ id: string }>("POST", "/api/boats", b),
  join: (boatId: string, role: Role, sharePercent: number | null, message: string) =>
    call<{ id: string }>("POST", `/api/boats/${boatId}/join-requests`, { role, share_percent: sharePercent, message }),
  removeMember: (boatId: string, userId: string) => call<{ ok: boolean }>("DELETE", `/api/boats/${boatId}/members/${userId}`),
  inbox: () => call<Inbox>("GET", "/api/inbox"),
  decideBoat: (boatId: string, approve: boolean) => call<{ ok: boolean }>("POST", `/api/boats/${boatId}/decision`, { approve }),
  decideRequest: (requestId: string, approve: boolean) => call<{ ok: boolean }>("POST", `/api/join-requests/${requestId}/decision`, { approve }),
  trips: (boatId: string, start: number, end: number) => call<Trip[]>("GET", `/api/boats/${boatId}/bookings?start=${start}&end=${end}`),
  addTrip: (boatId: string, t: TripInput) => call<{ id: string }>("POST", `/api/boats/${boatId}/bookings`, t),
  changeTrip: (tripId: string, t: TripInput) => call<{ ok: boolean }>("PATCH", `/api/bookings/${tripId}`, t),
  cancelTrip: (tripId: string) => call<{ ok: boolean }>("DELETE", `/api/bookings/${tripId}`),
  signOn: (tripId: string) => call<{ ok: boolean }>("POST", `/api/bookings/${tripId}/signon`),
  signOff: (tripId: string, userId: string) => call<{ ok: boolean }>("DELETE", `/api/bookings/${tripId}/signon/${userId}`),
};
