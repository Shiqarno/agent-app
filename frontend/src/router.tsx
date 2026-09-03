import {
  createContext,
  useContext,
  useEffect,
  useState,
  type AnchorHTMLAttributes,
  type ReactNode,
} from 'react'

// A minimal client-side path router. The app has a handful of static routes
// with no nested/dynamic segments, so a small history-API wrapper is enough
// -- pulling in a routing library for this would be more than the project
// needs (see CLAUDE.md: no new dependencies unless necessary).

type RouterContextValue = {
  path: string
  navigate: (path: string) => void
}

const RouterContext = createContext<RouterContextValue | null>(null)

export function RouterProvider({ children }: { children: ReactNode }) {
  const [path, setPath] = useState(() => window.location.pathname)

  useEffect(() => {
    function onPopState() {
      setPath(window.location.pathname)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  function navigate(to: string) {
    if (to !== window.location.pathname + window.location.search) {
      window.history.pushState({}, '', to)
    }
    // `path` (used for route matching) is pathname-only, matching the
    // initial state above and the popstate handler -- a `to` carrying a
    // query string (e.g. "/tasks/new?from=dashboard") must not become the
    // route key itself, only change the URL the page can read from.
    setPath(to.split('?')[0].split('#')[0])
  }

  return <RouterContext.Provider value={{ path, navigate }}>{children}</RouterContext.Provider>
}

export function useRouter(): RouterContextValue {
  const context = useContext(RouterContext)
  if (!context) {
    throw new Error('useRouter must be used within a RouterProvider')
  }
  return context
}

export function Link({
  to,
  children,
  ...rest
}: { to: string; children: ReactNode } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  const { navigate } = useRouter()

  return (
    <a
      href={to}
      {...rest}
      onClick={(event) => {
        event.preventDefault()
        navigate(to)
      }}
    >
      {children}
    </a>
  )
}
