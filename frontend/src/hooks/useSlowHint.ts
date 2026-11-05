import { useEffect, useState } from 'react';

/** True once `active` has been continuously true for `afterMs`. */
export const useSlowHint = (active: boolean, afterMs = 3000): boolean => {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!active) return;
    const id = window.setTimeout(() => setSlow(true), afterMs);
    return () => {
      window.clearTimeout(id);
      setSlow(false);
    };
  }, [active, afterMs]);
  return active && slow;
};

export const WAKING_UP_MESSAGE =
  'Waking up the server, this can take up to a minute on the first visit.';
