# Next.js Frontend Rules

## Stack

- Next.js 14+ with App Router
- TypeScript (strict mode)
- Tailwind CSS
- TanStack Query v5 for server state
- Zustand for client-only UI state
- Zod for form validation
- **pnpm** as package manager (never npm or yarn)

## Package Management (pnpm)

```bash
# Install all deps from pnpm-lock.yaml
pnpm install

# Add a runtime dep
pnpm add @tanstack/react-query

# Add a dev dep
pnpm add -D @types/node

# Run scripts
pnpm dev
pnpm build
pnpm test
pnpm lint
```

`pnpm-lock.yaml` must be committed. Never commit `node_modules`. Never use `npm install` or `yarn` — it will create a conflicting lockfile.

`package.json` engines field:
```json
{
  "engines": {
    "node": ">=20",
    "pnpm": ">=9"
  },
  "packageManager": "pnpm@9.x"
}
```

## Directory Layout

```
frontend/src/
├── app/                         # App Router — pages and layouts
│   ├── (auth)/                  # Route group: login, register
│   ├── dashboard/
│   │   ├── page.tsx
│   │   └── layout.tsx
│   ├── workouts/
│   ├── coaching/
│   └── layout.tsx               # Root layout with providers
├── components/
│   ├── ui/                      # Generic, domain-free primitives
│   └── [feature]/               # Feature-scoped components
├── lib/
│   ├── api/                     # API client + typed fetchers
│   ├── hooks/                   # Custom hooks (useWorkouts, etc.)
│   └── utils.ts
└── types/                       # Shared TypeScript interfaces
```

## Component Rules

### Server vs Client Components

- Default to **Server Components** — add `"use client"` only when needed
- Needs `"use client"`: event handlers, hooks, browser APIs, TanStack Query
- Never put `"use client"` on layout files — pass data down as props

```tsx
// Server Component (default) — fine to async/await
export default async function WorkoutHistoryPage() {
  const workouts = await fetchWorkouts(); // server-side fetch
  return <WorkoutList workouts={workouts} />;
}
```

### Component Structure

```tsx
// types at top, props interface, then component
interface WorkoutCardProps {
  workout: Workout;
  onDelete?: (id: string) => void;
}

export function WorkoutCard({ workout, onDelete }: WorkoutCardProps) {
  // hooks first
  // derived state / handlers
  // return JSX
}
```

- One component per file, filename matches export name in kebab-case
- No default exports in `components/` — use named exports
- Co-locate component-specific types in the same file

### Data Fetching

Use TanStack Query for all client-side data fetching. Define query keys as constants.

```tsx
// lib/api/workouts.ts
export const workoutKeys = {
  all: ['workouts'] as const,
  byUser: (userId: string) => [...workoutKeys.all, userId] as const,
};

export function useWorkouts(userId: string) {
  return useQuery({
    queryKey: workoutKeys.byUser(userId),
    queryFn: () => apiClient.get<Workout[]>(`/workouts?user_id=${userId}`),
  });
}
```

### API Client

Central typed client — never call `fetch` directly in components.

```typescript
// lib/api/client.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL;

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
  });
  if (!res.ok) throw new ApiError(res.status, await res.json());
  return res.json();
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
};
```

### Forms

Use React Hook Form + Zod. Keep schema in a separate `*.schema.ts` file.

```tsx
// workouts/new/workout-form.schema.ts
export const workoutSchema = z.object({
  exercise: z.string().min(1),
  sets: z.array(setSchema).min(1),
  date: z.coerce.date(),
});

// workouts/new/workout-form.tsx
"use client";
const form = useForm<WorkoutFormValues>({
  resolver: zodResolver(workoutSchema),
});
```

### Error & Loading States

Always handle loading and error in UI — no silent failures.

```tsx
const { data, isLoading, error } = useWorkouts(userId);

if (isLoading) return <WorkoutSkeleton />;
if (error) return <ErrorBoundaryFallback error={error} />;
```

### Environment Variables

| Variable | Use |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend base URL (exposed to browser) |
| `NEXTAUTH_SECRET` | Auth secret (server-only) |
| `NEXTAUTH_URL` | Auth callback URL |

Never prefix server-only secrets with `NEXT_PUBLIC_`.

## Routing Conventions

- Dynamic routes: `[workoutId]` — always validate with Zod in the page component
- Route groups `(group)` for shared layouts without URL segments
- Loading UI: `loading.tsx` co-located with page
- Error UI: `error.tsx` co-located with page (must be `"use client"`)

## TypeScript Rules

- `strict: true` in `tsconfig.json`
- No `any` — use `unknown` + type guards when necessary
- Co-locate types with the feature, not in a global `types/` unless truly shared
- Use `type` over `interface` for unions; use `interface` for extendable shapes

## Performance

- Use `next/image` for all images
- Use `next/font` for fonts — no external CSS font imports
- Dynamic import heavy components: `const Chart = dynamic(() => import('./chart'))`
- Wrap non-critical Client Components in `Suspense` with skeleton fallbacks

## Don'ts

- No inline styles — Tailwind only
- No `useEffect` for data fetching — use TanStack Query or Server Components
- No storing auth tokens in localStorage — use httpOnly cookies
- No direct DOM manipulation — use React refs
