import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, Me } from "./api";

interface AuthState {
  me: Me | null | undefined; // undefined while it is still being found out
  setMe: (me: Me | null) => void;
  inboxCount: number;
  refreshInbox: () => void;
}

const Auth = createContext<AuthState>({ me: undefined, setMe: () => {}, inboxCount: 0, refreshInbox: () => {} });

export const useAuth = () => useContext(Auth);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [inboxCount, setInboxCount] = useState(0);

  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);

  const refreshInbox = useCallback(() => {
    if (!me) {
      setInboxCount(0);
      return;
    }
    api.inbox().then((i) => setInboxCount(i.boats.length + i.requests.length), () => setInboxCount(0));
  }, [me]);

  useEffect(refreshInbox, [refreshInbox]);

  return <Auth.Provider value={{ me, setMe, inboxCount, refreshInbox }}>{children}</Auth.Provider>;
}
