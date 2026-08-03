import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

/**
 * State that persists in localStorage WITHOUT breaking hydration.
 *
 * The bug this replaces: `useState(() => readFromLocalStorage())`. The
 * initializer branches on `typeof localStorage`, so the server renders the
 * default while a client with a stored preference renders that preference —
 * two different HTML trees, and React throws "Hydration failed because the
 * server rendered HTML didn't match the client" on every page load for any
 * user who has ever customised anything.
 *
 * The fix is the standard two-phase pattern: initialise to the DEFAULT on both
 * server and first client render (so they match), then adopt the stored value
 * in an effect after mount. The cost is one repaint from default to preference
 * on load; the alternative was a full client-side tree regeneration on every
 * load, which is both slower and noisy.
 */
export function useStoredState<T>(
  read: () => T,
  serverDefault: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(serverDefault);
  // The reader is captured once: it identifies WHICH storage key this state
  // mirrors, and that never changes for the lifetime of the component.
  const readRef = useRef(read);
  useEffect(() => {
    setValue(readRef.current());
  }, []);
  return [value, setValue];
}
